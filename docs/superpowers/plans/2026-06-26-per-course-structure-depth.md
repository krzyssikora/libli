# Per-Course Structure / Depth Config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each course pick a structure preset (Flat / Chapters / Parts / Full) that fixes which content levels (`part`/`chapter`/`section`/`unit`) its builder offers, narrowing the currently-global four-level hierarchy per course.

**Architecture:** Three booleans on `Course` (`uses_parts`/`uses_chapters`/`uses_sections`; `unit` always present) are the flexible core; named presets are a UI layer that writes them. `legal_child_kinds` intersects the global rank logic with the course's `allowed_kinds`; the builder chips and a view-layer add-guard both consume it. A data migration backfills existing courses to the kinds they already use. Spec: `docs/superpowers/specs/2026-06-26-per-course-structure-depth-design.md`.

**Tech Stack:** Django (server-rendered templates, ModelForm, data migration `RunPython`), pytest / pytest-django, EN+PL i18n (`gettext`/`ngettext` + `.po`/`.mo`), bespoke token-driven CSS.

## Global Constraints

- Tooling: bash `ruff`/`pytest`/`python` are NOT on PATH — use `uv run ruff` / `uv run pytest` / `uv run python manage.py`. Run `uv run ruff check --fix && uv run ruff format` per task; CI checks `ruff format --check`.
- Model field defaults are `True` (= Full) — any non-form code path reproduces today's four-level behavior (backward-safe).
- The create-form picker defaults to **Chapters**; the three booleans are **never** added to a form's editable `Meta.fields` (no `fields = "__all__"`) — the preset picker is their sole writer.
- `allowed_kinds` is always RANK-ordered and ends in `unit`. `legal_child_kinds(parent_kind, allowed_kinds)` takes `allowed_kinds` as a **required** arg.
- `PRESET_FLAGS`, `kinds_for_flags`, `kinds_for_preset`, `preset_for_flags`, `primary_child_kind` live in `courses/ordering.py`; `forms.py` imports from there, never the reverse.
- EN + PL for every new user-facing string; compile `.mo`; clear any `#, fuzzy` flags makemessages adds. Verify the builder legend light + dark via throwaway Playwright screenshots (delete after review).
- The add-guard rejection must reuse `node_add`'s existing `ValidationError` → 422 path (the check goes *inside* the `try:` block).

---

## File structure

- `courses/ordering.py` — **Modify.** Add `PRESET_FLAGS`, `kinds_for_flags`, `kinds_for_preset`, `preset_for_flags`; change `legal_child_kinds` signature; replace the `PRIMARY_CHILD_KIND` dict with a `primary_child_kind(parent_kind, allowed_kinds)` function.
- `courses/models.py` — **Modify.** Add three `BooleanField`s + an `allowed_kinds` property to `Course`.
- `courses/structure_backfill.py` — **Create.** Pure data-migration helper `backfill_structure_flags(Course, ContentNode)`.
- `courses/migrations/0023_course_structure_flags.py` — **Create.** Schema (3 booleans) + `RunPython` backfill.
- `courses/templatetags/courses_manage_extras.py` — **Modify.** `legal_child_kinds` / `primary_child_kind` tags take `allowed_kinds`.
- `templates/courses/manage/_add_affordance.html` — **Modify.** Pass `course.allowed_kinds` into the tags.
- `courses/forms.py` — **Modify.** Add the non-model `structure` picker to `CourseForm`: preset↔flags on init/save, required-on-create, narrowing guard in `clean()`.
- `courses/views_manage.py` — **Modify.** `node_add` add-guard.
- `templates/courses/manage/_structure_legend.html` — **Create.** Legend partial.
- `templates/courses/manage/builder.html` — **Modify.** Include the legend.
- `courses/static/courses/css/builder.css` — **Modify.** Legend styling.
- `locale/pl/LC_MESSAGES/django.po` / `.mo` — **Modify.** PL translations.
- `tests/test_legal_kinds.py` — **Modify** (new signatures). `tests/test_course_structure.py` — **Create** (model, helpers, backfill, form, view-guard, legend).

---

## Task 1: Ordering helpers — presets + per-course `legal_child_kinds`

**Files:**
- Modify: `courses/ordering.py:119-134`
- Test: `tests/test_legal_kinds.py` (rewrite)

**Interfaces:**
- Produces:
  - `PRESET_FLAGS: dict[str, tuple[bool,bool,bool]]` keys `"flat"|"chapters"|"parts"|"full"`.
  - `kinds_for_flags(parts: bool, chapters: bool, sections: bool) -> list[str]` (RANK order, always ends `"unit"`).
  - `kinds_for_preset(key: str) -> list[str]`.
  - `preset_for_flags(parts, chapters, sections) -> str | None` (None = Custom).
  - `legal_child_kinds(parent_kind: str | None, allowed_kinds: list[str]) -> list[str]`.
  - `primary_child_kind(parent_kind: str | None, allowed_kinds: list[str]) -> str | None`.

- [ ] **Step 1: Rewrite the test file to the new signatures**

Replace the entire contents of `tests/test_legal_kinds.py`:

```python
from courses.ordering import kinds_for_flags
from courses.ordering import kinds_for_preset
from courses.ordering import legal_child_kinds
from courses.ordering import preset_for_flags
from courses.ordering import primary_child_kind

ALL = ["part", "chapter", "section", "unit"]


def test_legal_child_kinds_top_allows_all_in_rank_order():
    assert legal_child_kinds(None, ALL) == ["part", "chapter", "section", "unit"]


def test_legal_child_kinds_nested():
    assert legal_child_kinds("part", ALL) == ["chapter", "section", "unit"]
    assert legal_child_kinds("chapter", ALL) == ["section", "unit"]
    assert legal_child_kinds("section", ALL) == ["unit"]
    assert legal_child_kinds("unit", ALL) == []


def test_legal_child_kinds_restricted_by_course_set():
    assert legal_child_kinds(None, ["chapter", "unit"]) == ["chapter", "unit"]
    assert legal_child_kinds(None, ["unit"]) == ["unit"]
    custom = ["part", "section", "unit"]  # no chapter
    assert legal_child_kinds(None, custom) == ["part", "section", "unit"]
    assert legal_child_kinds("part", custom) == ["section", "unit"]


def test_primary_child_kind():
    assert primary_child_kind(None, ALL) == "chapter"
    assert primary_child_kind("part", ALL) == "chapter"
    assert primary_child_kind("chapter", ALL) is None  # only 2 legal
    assert primary_child_kind("section", ALL) is None
    assert primary_child_kind(None, ["chapter", "unit"]) is None  # 2 legal
    assert primary_child_kind(None, ["part", "section", "unit"]) == "part"  # no chapter


def test_kinds_for_flags_and_presets():
    assert kinds_for_flags(False, False, False) == ["unit"]
    assert kinds_for_flags(False, True, False) == ["chapter", "unit"]
    assert kinds_for_flags(True, True, False) == ["part", "chapter", "unit"]
    assert kinds_for_flags(True, True, True) == ALL
    assert kinds_for_preset("flat") == ["unit"]
    assert kinds_for_preset("full") == ALL


def test_preset_for_flags_reverse_lookup():
    assert preset_for_flags(False, False, False) == "flat"
    assert preset_for_flags(False, True, False) == "chapters"
    assert preset_for_flags(True, True, False) == "parts"
    assert preset_for_flags(True, True, True) == "full"
    assert preset_for_flags(True, False, True) is None  # custom
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_legal_kinds.py -q`
Expected: FAIL (ImportError: cannot import `kinds_for_flags` / `legal_child_kinds()` arg mismatch).

- [ ] **Step 3: Update `courses/ordering.py`**

Replace the block at `courses/ordering.py:119-134` (the `PRIMARY_CHILD_KIND` dict and the old `legal_child_kinds`) with:

```python
# --- per-course structure presets + builder "+" affordances -----------------
# The model stores three booleans (uses_parts/uses_chapters/uses_sections);
# presets are a UI-layer naming over flag-triples. `unit` is always present
# (mandatory leaf) and has no flag. A child's kind must be strictly deeper
# (larger RANK) than its parent's; the top scope (parent_kind=None) allows all
# kinds, then everything is intersected with the course's allowed set.
PRESET_FLAGS = {
    "flat": (False, False, False),     # course -> unit
    "chapters": (False, True, False),  # course -> chapter -> unit
    "parts": (True, True, False),      # course -> part -> chapter -> unit
    "full": (True, True, True),        # course -> part -> chapter -> section -> unit
}


def kinds_for_flags(parts, chapters, sections):
    """Allowed kinds in RANK order for the given optional-level flags. Always
    ends with 'unit' (the mandatory leaf)."""
    ks = []
    if parts:
        ks.append("part")
    if chapters:
        ks.append("chapter")
    if sections:
        ks.append("section")
    ks.append("unit")
    return ks


def kinds_for_preset(key):
    """Allowed kinds for a named preset key (see PRESET_FLAGS)."""
    return kinds_for_flags(*PRESET_FLAGS[key])


def preset_for_flags(parts, chapters, sections):
    """Reverse lookup: the preset key matching a flag-triple, else None (Custom)."""
    target = (parts, chapters, sections)
    for key, flags in PRESET_FLAGS.items():
        if flags == target:
            return key
    return None


def legal_child_kinds(parent_kind, allowed_kinds):
    """Kinds a node of `parent_kind` (a kind string, or None for the top scope)
    may directly contain, in RANK order, restricted to this course's
    `allowed_kinds` (the per-course structure policy)."""
    order = sorted(ContentNode.RANK, key=ContentNode.RANK.get)
    if parent_kind is None:
        deeper = order
    else:
        parent_rank = ContentNode.RANK[parent_kind]
        deeper = [k for k in order if ContentNode.RANK[k] > parent_rank]
    return [k for k in deeper if k in allowed_kinds]


def primary_child_kind(parent_kind, allowed_kinds):
    """One-click primary "+" kind for a scope with >=3 legal child kinds:
    'chapter' when chapter is legal here (preserves today's UX), else the
    shallowest legal kind. None when <3 legal kinds (all chips show inline)."""
    legal = legal_child_kinds(parent_kind, allowed_kinds)
    if len(legal) < 3:
        return None
    if "chapter" in legal:
        return "chapter"
    return legal[0]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_legal_kinds.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix courses/ordering.py tests/test_legal_kinds.py && uv run ruff format courses/ordering.py tests/test_legal_kinds.py
git add courses/ordering.py tests/test_legal_kinds.py
git commit -m "feat(structure): per-course legal_child_kinds + preset helpers"
```

---

## Task 2: Course model fields, `allowed_kinds`, backfill + migration

**Files:**
- Modify: `courses/models.py:83` (after `html_js`), and add a property in the `Course` class
- Create: `courses/structure_backfill.py`
- Create: `courses/migrations/0023_course_structure_flags.py`
- Test: `tests/test_course_structure.py`

**Interfaces:**
- Consumes: `kinds_for_flags` (Task 1).
- Produces: `Course.uses_parts/uses_chapters/uses_sections` (BooleanField default True); `Course.allowed_kinds` property; `backfill_structure_flags(Course, ContentNode)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_course_structure.py`:

```python
import pytest

from courses.models import ContentNode
from courses.models import Course
from courses.structure_backfill import backfill_structure_flags

pytestmark = pytest.mark.django_db


def _add(course, kind, parent=None):
    extra = {"unit_type": "lesson"} if kind == "unit" else {}
    return ContentNode.objects.create(
        course=course, kind=kind, title=kind, parent=parent, **extra
    )


def test_allowed_kinds_full_default():
    c = Course.objects.create(title="C", slug="c-full")
    assert c.allowed_kinds == ["part", "chapter", "section", "unit"]


def test_allowed_kinds_flat():
    c = Course.objects.create(
        title="C", slug="c-flat",
        uses_parts=False, uses_chapters=False, uses_sections=False,
    )
    assert c.allowed_kinds == ["unit"]


def test_allowed_kinds_chapters():
    c = Course.objects.create(
        title="C", slug="c-ch",
        uses_parts=False, uses_chapters=True, uses_sections=False,
    )
    assert c.allowed_kinds == ["chapter", "unit"]


def test_backfill_units_only_to_flat():
    c = Course.objects.create(title="C", slug="c1")
    _add(c, "unit")
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (False, False, False)


def test_backfill_chapters_only():
    c = Course.objects.create(title="C", slug="c2")
    ch = _add(c, "chapter")
    _add(c, "unit", parent=ch)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (False, True, False)


def test_backfill_parts_chapters():
    c = Course.objects.create(title="C", slug="c3")
    p = _add(c, "part")
    ch = _add(c, "chapter", parent=p)
    _add(c, "unit", parent=ch)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, False)


def test_backfill_mixed_custom():
    c = Course.objects.create(title="C", slug="c5")
    p = _add(c, "part")
    s = _add(c, "section", parent=p)
    _add(c, "unit", parent=s)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, False, True)


def test_backfill_empty_course_keeps_full():
    c = Course.objects.create(title="C", slug="c4")
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, True)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_course_structure.py -q`
Expected: FAIL (ImportError on `structure_backfill`; `Course` has no `allowed_kinds`/`uses_*`).

- [ ] **Step 3: Add the model fields + property**

In `courses/models.py`, add after the `html_js` field (`:83`) inside `Course`:

```python
    # Per-course structure (depth) policy. True = that optional level is offered
    # in the builder; `unit` is always present (mandatory leaf). Defaults = Full
    # reproduce today's part>chapter>section>unit depth (backward-safe). Edited
    # only via CourseForm's preset picker, never as raw checkboxes.
    uses_parts = models.BooleanField(default=True)
    uses_chapters = models.BooleanField(default=True)
    uses_sections = models.BooleanField(default=True)
```

And add this property to `Course` (e.g. just below `__str__`):

```python
    @property
    def allowed_kinds(self):
        """Content kinds this course offers, RANK-ordered, always ending in
        'unit'. Drives the builder + chips and the add-time policy guard."""
        from courses.ordering import kinds_for_flags

        return kinds_for_flags(
            self.uses_parts, self.uses_chapters, self.uses_sections
        )
```

- [ ] **Step 4: Create the backfill helper**

Create `courses/structure_backfill.py`:

```python
"""Data-migration helper: set each existing course's structure flags from the
content kinds it actually uses, so no in-use level is ever excluded. A course
with zero nodes is skipped, keeping the True/Full default (nothing to infer)."""


def backfill_structure_flags(Course, ContentNode):
    for course in Course.objects.all():
        kinds = set(
            ContentNode.objects.filter(course=course).values_list("kind", flat=True)
        )
        if not kinds:
            continue  # empty course -> keep default (Full)
        course.uses_parts = "part" in kinds
        course.uses_chapters = "chapter" in kinds
        course.uses_sections = "section" in kinds
        course.save(
            update_fields=["uses_parts", "uses_chapters", "uses_sections"]
        )
```

- [ ] **Step 5: Create the migration**

Create `courses/migrations/0023_course_structure_flags.py`:

```python
from django.db import migrations
from django.db import models

from courses.structure_backfill import backfill_structure_flags


def _forward(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    ContentNode = apps.get_model("courses", "ContentNode")
    backfill_structure_flags(Course, ContentNode)


def _reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("courses", "0022_questionresponse_review_feedback")]

    operations = [
        migrations.AddField(
            model_name="course",
            name="uses_parts",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="course",
            name="uses_chapters",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="course",
            name="uses_sections",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(_forward, _reverse),
    ]
```

- [ ] **Step 6: Verify migration state is consistent**

Run: `uv run python manage.py makemigrations --check --dry-run courses`
Expected: "No changes detected" (the hand-written migration matches the model). If it reports changes, reconcile the field definitions.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_course_structure.py -q`
Expected: PASS (7 tests).

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check --fix courses/models.py courses/structure_backfill.py tests/test_course_structure.py && uv run ruff format courses/models.py courses/structure_backfill.py tests/test_course_structure.py courses/migrations/0023_course_structure_flags.py
git add courses/models.py courses/structure_backfill.py courses/migrations/0023_course_structure_flags.py tests/test_course_structure.py
git commit -m "feat(structure): Course structure flags, allowed_kinds, backfill migration"
```

---

## Task 3: Builder chips become per-course (templatetags + affordance)

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py:11-12,92-101`
- Modify: `templates/courses/manage/_add_affordance.html:2-3`
- Test: `tests/test_course_structure.py` (append)

**Interfaces:**
- Consumes: `legal_child_kinds`/`primary_child_kind` (Task 1), `course.allowed_kinds` (Task 2).

- [ ] **Step 1: Append failing render tests**

Add to `tests/test_course_structure.py`:

```python
from django.template import Context  # noqa: E402
from django.template import Template  # noqa: E402


def _render_affordance(course, parent_kind):
    tpl = Template("{% include 'courses/manage/_add_affordance.html' %}")
    return tpl.render(
        Context(
            {
                "course": course,
                "parent_kind": parent_kind,
                "scope_id": "top",
                "scope_updated": "x",
            }
        )
    )


def test_affordance_flat_course_only_unit_chips():
    c = Course.objects.create(
        title="C", slug="c-aff-flat",
        uses_parts=False, uses_chapters=False, uses_sections=False,
    )
    html = _render_affordance(c, None)
    assert 'data-add-kind="lesson"' in html
    assert 'data-add-kind="quiz"' in html
    assert 'data-add-kind="chapter"' not in html
    assert 'data-add-kind="part"' not in html


def test_affordance_full_course_offers_part_and_chapter():
    c = Course.objects.create(title="C", slug="c-aff-full")
    html = _render_affordance(c, None)
    assert 'data-add-kind="chapter"' in html
    assert 'data-add-kind="part"' in html
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_course_structure.py -k affordance -q`
Expected: FAIL (the tag still takes one arg → `TemplateSyntaxError`/too-many-values, or chips not filtered).

- [ ] **Step 3: Update the templatetags**

In `courses/templatetags/courses_manage_extras.py`, change the imports at `:11-12`:

```python
from courses.ordering import legal_child_kinds as _legal_child_kinds
from courses.ordering import primary_child_kind as _primary_child_kind
```

(remove the `PRIMARY_CHILD_KIND` import). Replace the two tags at `:92-101`:

```python
@register.simple_tag
def legal_child_kinds(parent_kind, allowed_kinds):
    """Kind strings (RANK order) a `parent_kind` scope may add within this
    course's `allowed_kinds`. None = top scope."""
    return _legal_child_kinds(parent_kind, allowed_kinds)


@register.simple_tag
def primary_child_kind(parent_kind, allowed_kinds):
    """The one-click primary "+" kind for a >=3-legal-kind scope, else None."""
    return _primary_child_kind(parent_kind, allowed_kinds)
```

- [ ] **Step 4: Update the affordance template**

In `templates/courses/manage/_add_affordance.html`, change lines 2-3 to pass the course's set:

```django
{% legal_child_kinds parent_kind course.allowed_kinds as kinds %}
{% primary_child_kind parent_kind course.allowed_kinds as primary %}
```

- [ ] **Step 5: Run the affordance tests + the full legal-kinds suite**

Run: `uv run pytest tests/test_course_structure.py -k affordance tests/test_legal_kinds.py tests/test_manage_node_ops.py -q`
Expected: PASS (affordance renders filtered chips; node-op tests still green — `CourseFactory` courses default to Full).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix courses/templatetags/courses_manage_extras.py tests/test_course_structure.py && uv run ruff format courses/templatetags/courses_manage_extras.py tests/test_course_structure.py
git add courses/templatetags/courses_manage_extras.py templates/courses/manage/_add_affordance.html tests/test_course_structure.py
git commit -m "feat(structure): builder + chips honor the course's allowed kinds"
```

---

## Task 4: `CourseForm` preset picker + narrowing guard

**Files:**
- Modify: `courses/forms.py:1-9` (imports), `26-116` (`CourseForm`)
- Test: `tests/test_course_structure.py` (append)

**Interfaces:**
- Consumes: `PRESET_FLAGS`, `kinds_for_preset`, `preset_for_flags` (Task 1); `Course.uses_*`/`allowed_kinds` (Task 2).
- Produces: `CourseForm` with a non-model `structure` `ChoiceField`; preset→flags applied in `save()`; narrowing guard in `clean()`.

- [ ] **Step 1: Append failing form tests**

Add to `tests/test_course_structure.py`:

```python
from courses.forms import CourseForm  # noqa: E402


def _form_data(**over):
    data = {"title": "C", "slug": "", "language": "en", "visibility": "assigned"}
    data.update(over)
    return data


def test_create_form_writes_chapters_preset():
    form = CourseForm(data=_form_data(slug="new-ch", structure="chapters"))
    assert form.is_valid(), form.errors
    course = form.save(commit=False)
    course.save()
    assert (course.uses_parts, course.uses_chapters, course.uses_sections) == (
        False, True, False,
    )


def test_create_form_requires_structure():
    form = CourseForm(data=_form_data(slug="no-struct"))  # no structure
    assert not form.is_valid()
    assert "structure" in form.errors


def test_settings_save_without_preset_preserves_flags():
    c = Course.objects.create(
        title="C", slug="c-keep",
        uses_parts=True, uses_chapters=False, uses_sections=True,  # Custom
    )
    form = CourseForm(data=_form_data(slug="c-keep"), instance=c)  # no structure
    assert form.is_valid(), form.errors
    form.save()
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, False, True)


def test_narrowing_guard_blocks_in_use_level():
    c = Course.objects.create(title="C", slug="c-narrow")  # Full
    ContentNode.objects.create(course=c, kind="chapter", title="Ch")
    form = CourseForm(
        data=_form_data(slug="c-narrow", structure="flat"), instance=c
    )
    assert not form.is_valid()
    assert "level" in str(form.errors).lower()


def test_widening_always_allowed():
    c = Course.objects.create(
        title="C", slug="c-widen",
        uses_parts=False, uses_chapters=True, uses_sections=False,
    )
    form = CourseForm(
        data=_form_data(slug="c-widen", structure="full"), instance=c
    )
    assert form.is_valid(), form.errors
    form.save()
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, True)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_course_structure.py -k "form or preset or guard or widening or settings_save" -q`
Expected: FAIL (no `structure` field; create form does not require it).

- [ ] **Step 3: Add the imports**

In `courses/forms.py`, add below the existing imports (`:1-9`):

```python
from django.utils.translation import ngettext

from courses.models import ContentNode
from courses.ordering import PRESET_FLAGS
from courses.ordering import kinds_for_preset
from courses.ordering import preset_for_flags
```

- [ ] **Step 4: Declare the `structure` field**

In `CourseForm` (class body, above `class Meta`), add:

```python
    # Non-model picker: writes uses_parts/uses_chapters/uses_sections in save().
    # required-ness + initial are set per create/edit in __init__.
    structure = forms.ChoiceField(
        required=False,
        widget=forms.RadioSelect,
        label=_("Structure"),
        help_text=_("Which content levels this course uses."),
    )
```

- [ ] **Step 5: Build choices, initial, required in `__init__`**

At the **end** of `CourseForm.__init__` (after the `self_enroll_cohorts` block, `:102`), add:

```python
        def _chain(kinds):
            labels = [str(_("Course"))] + [
                str(ContentNode.Kind(k).label) for k in kinds
            ]
            return " › ".join(labels)

        preset_labels = {
            "flat": _("Flat"),
            "chapters": _("Chapters"),
            "parts": _("Parts"),
            "full": _("Full"),
        }
        self.fields["structure"].choices = [
            (key, f"{preset_labels[key]} — {_chain(kinds_for_preset(key))}")
            for key in PRESET_FLAGS
        ]

        if self.instance.pk is None:  # creating
            self.fields["structure"].required = True
            self.fields["structure"].initial = "chapters"
        else:  # editing
            current = preset_for_flags(
                self.instance.uses_parts,
                self.instance.uses_chapters,
                self.instance.uses_sections,
            )
            self.fields["structure"].required = False
            self.fields["structure"].initial = current  # None => no radio checked
            if current is None:  # Custom course
                self.fields["structure"].help_text = _(
                    "Custom: %(chain)s (keeps current structure)."
                ) % {"chain": _chain(self.instance.allowed_kinds)}
```

- [ ] **Step 6: Add the narrowing guard (`clean`) and flag-writing (`save`)**

Add these two methods to `CourseForm` (after `clean_slug`):

```python
    def clean(self):
        cleaned = super().clean()
        preset = cleaned.get("structure")
        if not preset:
            return cleaned  # no preset chosen -> flags unchanged
        parts, chapters, sections = PRESET_FLAGS[preset]
        if self.instance.pk:  # block True->False transitions for in-use levels
            transitions = [
                ("part", self.instance.uses_parts, parts),
                ("chapter", self.instance.uses_chapters, chapters),
                ("section", self.instance.uses_sections, sections),
            ]
            msgs = []
            for kind, current, target in transitions:
                if current and not target:
                    n = ContentNode.objects.filter(
                        course=self.instance, kind=kind
                    ).count()
                    if n:
                        msgs.append(
                            ngettext(
                                "%(count)d item at the %(level)s level",
                                "%(count)d items at the %(level)s level",
                                n,
                            )
                            % {"count": n, "level": ContentNode.Kind(kind).label}
                        )
            if msgs:
                raise forms.ValidationError(
                    _("Remove these before changing the structure: %(list)s.")
                    % {"list": "; ".join(msgs)}
                )
        return cleaned

    def save(self, commit=True):
        preset = self.cleaned_data.get("structure")
        if preset:
            (
                self.instance.uses_parts,
                self.instance.uses_chapters,
                self.instance.uses_sections,
            ) = PRESET_FLAGS[preset]
        return super().save(commit=commit)
```

- [ ] **Step 7: Run the form tests**

Run: `uv run pytest tests/test_course_structure.py -q`
Expected: PASS (all model/backfill/affordance/form tests).

- [ ] **Step 8: Run the broader manage suite for regressions**

Run: `uv run pytest tests/test_manage_node_ops.py tests/test_manage_access.py tests/test_e2e_settings.py -q`
Expected: PASS. If a `course_create`/`course_edit` test now fails because the create POST omits `structure`, update that test to include `"structure": "full"` (per the spec's create-default audit note — any test relying on the post-create course being Full-shaped).

- [ ] **Step 9: Lint + commit**

```bash
uv run ruff check --fix courses/forms.py tests/test_course_structure.py && uv run ruff format courses/forms.py tests/test_course_structure.py
git add courses/forms.py tests/test_course_structure.py
git commit -m "feat(structure): CourseForm preset picker + narrowing guard"
```

---

## Task 5: Server-side add-guard in `node_add`

**Files:**
- Modify: `courses/views_manage.py:217-218` (inside the `try:`)
- Test: `tests/test_course_structure.py` (append)

**Interfaces:**
- Consumes: `course.allowed_kinds` (Task 2), `ContentNode.RANK`/`Kind`.

- [ ] **Step 1: Append the failing view-guard test**

Add to `tests/test_course_structure.py`:

```python
from django.urls import reverse  # noqa: E402

from tests.factories import CourseFactory  # noqa: E402
from tests.factories import make_login  # noqa: E402

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def test_node_add_rejects_excluded_kind(client):
    owner = make_login(client, "structowner")
    course = CourseFactory(
        slug="c-guard", owner=owner,
        uses_parts=False, uses_chapters=True, uses_sections=False,  # Chapters
    )
    url = reverse("courses:manage_node_add", kwargs={"slug": "c-guard"})
    bad = client.post(
        url,
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "part",
            "title": "P",
        },
        **FETCH,
    )
    assert bad.status_code == 422
    assert not ContentNode.objects.filter(course=course, kind="part").exists()

    ok = client.post(
        url,
        {
            "parent": "top",
            "parent_token": course.updated.isoformat(),
            "kind": "chapter",
            "title": "Ch",
        },
        **FETCH,
    )
    assert ok.status_code == 200
    assert ContentNode.objects.filter(course=course, kind="chapter").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_course_structure.py -k node_add -q`
Expected: FAIL (the excluded `part` is accepted today → no 422; a part row is created).

- [ ] **Step 3: Add the guard inside the `try:` block**

In `courses/views_manage.py`, the `kind` is fully resolved by `:216`; insert the check as the **first statement inside** the existing `try:` (`:217`), immediately before the `node = builder_svc.add_node(...)` call (`:218`):

```python
    try:
        if kind in ContentNode.RANK and kind not in course.allowed_kinds:
            # Course-policy exclusion: reuse the existing ValidationError -> 422
            # path below. Empty/unknown kinds are NOT caught here — they fall
            # through to add_node/full_clean unchanged.
            raise ValidationError(
                _("You can't add the %(kind)s level to this course.")
                % {"kind": ContentNode.Kind(kind).label}
            )
        node = builder_svc.add_node(
            course,
            parent,
            kind,
            request.POST.get("title", ""),
            unit_type,
            request.POST.get("parent_token"),
        )
```

(`_` is `gettext` and `ValidationError` is already imported at the top of the module.)

- [ ] **Step 4: Run the view-guard test + node-op regression suite**

Run: `uv run pytest tests/test_course_structure.py -k node_add tests/test_manage_node_ops.py -q`
Expected: PASS (guard returns 422; allowed add 200; existing node-op tests still green — their courses are Full).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix courses/views_manage.py tests/test_course_structure.py && uv run ruff format courses/views_manage.py tests/test_course_structure.py
git add courses/views_manage.py tests/test_course_structure.py
git commit -m "feat(structure): reject excluded kinds in node_add (422)"
```

---

## Task 6: Structure legend + i18n

**Files:**
- Create: `templates/courses/manage/_structure_legend.html`
- Modify: `templates/courses/manage/builder.html:15-16`
- Modify: `courses/static/courses/css/builder.css` (append)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compile `.mo`)
- Test: `tests/test_course_structure.py` (append)

**Interfaces:**
- Consumes: `course.allowed_kinds` (Task 2), the `kind_label` tag.

- [ ] **Step 1: Append the failing legend tests**

Add to `tests/test_course_structure.py`:

```python
from django.utils import translation  # noqa: E402


def _render_legend(course):
    tpl = Template("{% include 'courses/manage/_structure_legend.html' %}")
    return tpl.render(Context({"course": course}))


def test_structure_legend_renders_configured_chain():
    c = Course.objects.create(
        title="C", slug="c-leg",
        uses_parts=False, uses_chapters=True, uses_sections=False,
    )
    html = _render_legend(c)
    assert "Chapter" in html
    assert "Unit" in html
    assert "Part" not in html


def test_structure_legend_polish_kind_labels():
    c = Course.objects.create(title="C", slug="c-leg-pl")  # Full
    with translation.override("pl"):
        html = _render_legend(c)
    assert "Rozdział" in html  # "Chapter" in PL (existing translation)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_course_structure.py -k legend -q`
Expected: FAIL (`TemplateDoesNotExist: courses/manage/_structure_legend.html`).

- [ ] **Step 3: Create the legend partial**

Create `templates/courses/manage/_structure_legend.html`:

```django
{% load i18n courses_manage_extras %}
<p class="builder__legend" aria-label="{% trans 'Course structure' %}">
  <span class="builder__legend-label">{% trans "Structure" %}</span>
  <span class="builder__legend-chain">{% trans "Course" %}{% for kind in course.allowed_kinds %} › {% kind_label kind %}{% endfor %}</span>
</p>
```

- [ ] **Step 4: Include it in the builder**

In `templates/courses/manage/builder.html`, change `:15-16` to render the legend under the title:

```django
    <h1 class="builder__title">{{ course.title }}</h1>
    {% include "courses/manage/_structure_legend.html" with course=course %}
    {% include "courses/manage/_scope.html" with scope_id="top" scope_updated=course.updated.isoformat nodes=top_nodes children_map=children_map parent_kind=None %}
```

- [ ] **Step 5: Style the legend (quiet)**

Append to `courses/static/courses/css/builder.css`:

```css
.builder__legend {
  display: flex;
  align-items: baseline;
  gap: var(--space-2, 0.5rem);
  margin: 0 0 var(--space-3, 0.75rem);
  font-size: 0.85rem;
  color: var(--text-muted, #6b7280);
}
.builder__legend-label {
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 0.7rem;
  font-weight: 600;
}
.builder__legend-chain { color: var(--text, inherit); }
```

(Match the actual token names used elsewhere in `builder.css`/`app.css`; the fallbacks keep it legible if a token differs.)

- [ ] **Step 6: Run the legend tests**

Run: `uv run pytest tests/test_course_structure.py -k legend -q`
Expected: PASS.

- [ ] **Step 7: Extract + translate new strings (EN→PL)**

Run: `uv run python manage.py makemessages -l pl`

In `locale/pl/LC_MESSAGES/django.po`, fill the new msgids (clear any `#, fuzzy`):

```
msgid "Structure"            -> msgstr "Struktura"
msgid "Course structure"     -> msgstr "Struktura kursu"
msgid "Flat"                 -> msgstr "Płaska"
msgid "Chapters"             -> msgstr "Rozdziały"
msgid "Parts"                -> msgstr "Części"
msgid "Full"                 -> msgstr "Pełna"
msgid "Which content levels this course uses." -> msgstr "Których poziomów treści używa ten kurs."
msgid "Custom: %(chain)s (keeps current structure)." -> msgstr "Niestandardowa: %(chain)s (zachowuje obecną strukturę)."
msgid "Remove these before changing the structure: %(list)s." -> msgstr "Usuń je przed zmianą struktury: %(list)s."
msgid "You can't add the %(kind)s level to this course." -> msgstr "Nie możesz dodać poziomu %(kind)s do tego kursu."
```

For the `ngettext` plural (`"%(count)d item at the %(level)s level"`), fill the Polish `msgstr[0]/[1]/[2]` forms:

```
msgstr[0] "%(count)d element na poziomie %(level)s"
msgstr[1] "%(count)d elementy na poziomie %(level)s"
msgstr[2] "%(count)d elementów na poziomie %(level)s"
```

(Verify the `"Course"` msgid is the standalone legend string and not an unrelated reuse; if `makemessages` marked any copied entry `#, fuzzy`, delete that flag line.)

- [ ] **Step 8: Compile and verify the PL plural + a new string**

```bash
uv run python manage.py compilemessages -l pl
```

Add one PL assertion to `tests/test_course_structure.py` and run it:

```python
def test_structure_label_polish():
    c = Course.objects.create(title="C", slug="c-leg-pl2")
    with translation.override("pl"):
        html = _render_legend(c)
    assert "Struktura" in html
```

Run: `uv run pytest tests/test_course_structure.py -k "legend or polish or structure_label" -q`
Expected: PASS.

- [ ] **Step 9: Visual check (light + dark)**

Screenshot the builder legend light + dark via a throwaway Playwright harness (per `verify-ui-with-screenshots`); confirm the legend reads as a quiet eyebrow, not a heavy banner; delete the harness after review.

- [ ] **Step 10: Lint + commit**

```bash
uv run ruff check --fix tests/test_course_structure.py && uv run ruff format tests/test_course_structure.py
git add templates/courses/manage/_structure_legend.html templates/courses/manage/builder.html courses/static/courses/css/builder.css locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_course_structure.py
git commit -m "feat(structure): builder structure legend + PL translations"
```

---

## Final verification (after all tasks)

- [ ] Full suite: `uv run pytest -q` — all green (watch for create-flow tests needing `structure="full"` per Task 4 Step 8).
- [ ] Lint gate: `uv run ruff check . && uv run ruff format --check .`
- [ ] Migrations clean: `uv run python manage.py makemigrations --check --dry-run`
- [ ] Manual smoke: create a course (picker → Flat) → builder offers only Lesson/Quiz at top + legend reads `Course › Unit`; switch a populated Full course to Flat in settings → blocked with the counted message; widen Chapters→Full → succeeds.

---

## Self-review (against the spec)

- **§1.1 model + `allowed_kinds`** → Task 2. **§1.1 `kinds_for_flags`/`kinds_for_preset` instance-free** → Task 1 (used by the form in Task 4). **§1.2 `PRESET_FLAGS` in `ordering.py` + reverse lookup** → Task 1. **§1.3 `legal_child_kinds(parent_kind, allowed_kinds)` required arg + `primary_child_kind` function (chapter-if-legal-else-shallowest) + test_legal_kinds update** → Task 1; **template-tag rewrite** → Task 3. **§1.4 view guard inside `try:`, real-kind-only, 422 reuse** → Task 5; **`clean()` unchanged** → respected (no edit to `ContentNode.clean`). **§2.1 picker on create (required, Chapters) + settings (not required, Custom keeps flags) + booleans excluded from `Meta.fields`** → Task 4 (the `structure` field is non-model; `Meta.fields` is untouched). **§2.2 narrowing guard True→False + count message + ngettext** → Task 4; **v1 "presets stay live radios"** → no client-side disabling implemented (matches the deliberate decision). **§2.3 migration schema + backfill (units-only⇒Flat, empty⇒skip)** → Task 2. **§2.4 legend prefixed `Course`** → Task 6. **§3 tests** (allowed_kinds, legal_child_kinds intersection, primary/overflow, server guard 422, narrowing guard, backfill incl. units-only, builder chips, legend, EN/PL incl. ngettext) → distributed across Tasks 1–6. **§ i18n** → Task 6.
- **Custom-state widget mechanic (4 radios unchecked + read-only line):** Task 4 sets `initial=None` (no radio pre-checked) and surfaces the Custom chain via the field `help_text`. The spec's "read-only line above the radios" is realized as the picker's help text rather than a separate element — a deliberate simplification within `{{ form.as_p }}` rendering; the load-bearing behavior (no preset pre-checked → unchanged-flags save) is fully implemented and tested.
- **Placeholder scan:** none — every step has concrete code/commands.
- **Type consistency:** `legal_child_kinds(parent_kind, allowed_kinds)`, `primary_child_kind(parent_kind, allowed_kinds)`, `kinds_for_flags(parts, chapters, sections)`, `kinds_for_preset(key)`, `preset_for_flags(...)`, `backfill_structure_flags(Course, ContentNode)`, `Course.allowed_kinds` — used identically across Tasks 1–6.
