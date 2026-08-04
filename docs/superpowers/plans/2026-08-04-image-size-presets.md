# Image Size Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an author four bounding-box size presets for an image, so a tall diagram can no longer overflow a phone screen and nobody has to guess pixel dimensions before seeing the result.

**Architecture:** `ImageElement` gains a `size` choice field defaulting to `full`. Each preset is a bounding box — a `max-width` percentage on the `<figure>` plus a `max-height` in `dvh` on the `<img>` — so images of any aspect ratio scale to fit while preserving ratio. `full` carries `max-height: 100dvh` ("never taller than the screen"), which fixes all 54 measured over-tall images via CSS alone with no data migration. A delegated listener already present in `editor.js` swaps the class live, without a save.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, Playwright (e2e), vanilla JS (no framework), token-driven CSS.

**Spec:** `docs/superpowers/specs/2026-08-04-image-size-presets-design.md` (10 review rounds, 36 catches applied).

## Global Constraints

- **Tooling is behind `uv run`** — `ruff`, `pytest`, `python` are NOT on PATH. Always `uv run pytest …`, `uv run ruff …`.
- **e2e tests need `-m e2e`** or they are silently deselected (exit 5). An exit-5 run is NOT a pass.
- **`--verbosity=0`, never a second `-q`** — `addopts` already has `-q`; doubling it prints no verdict.
- **Never run two pytest invocations at once** — test-DB contention across runs. Never background pytest or let a timeout kill it; an abandoned run makes the next die with `DuplicateDatabase`.
- **The real content column is 648px desktop / 296px phone**, at the pinned viewports. **This supersedes
  the spec's §Purpose figure of 880/328**, which omits the outermost wrapper: `base.html:147` puts
  `{% block content %}` inside `<main class="app-main">`, and `app.css:34` caps it at
  `max-width: 960px` with `padding: var(--space-8) var(--space-5)` (20px inline), dropping to
  `var(--space-4)` (16px) at ≤640px (`app.css:246`). `lesson_unit.html` does not override
  `{% block main_class %}`, and the only `.app-main` widening anywhere is
  `body.editor-page .app-main { max-width: 102rem }` (`editor.css:36`) — the **editor**, not the lesson
  page. The full chain:
  - **Desktop @1280:** `.app-main` 960 − 40 padding = 920 (so `.unit-shell`'s 72rem = 1152 cap never
    binds) − `.unit-tree` 14rem = 224 → 696 − `.lesson` padding 3rem = **648**.
  - **Phone @360:** `.app-main` 360 − 32 = 328; at `max-width: 640px` (`courses.css:833-837`)
    `.unit-shell` becomes `display: block` and `.unit-tree` `display: none`, and the lesson padding
    drops to `1rem` each side → 328 − 32 = **296**.

  **Not** `.lesson`'s nominal 46rem either — `.unit-shell__main > .lesson` overrides it to
  `max-width: none` at `courses.css:545-546`. This correction does **not** weaken the spec's case: a
  narrower column can only make *more* images overflow, so the measured defect counts are a floor.
  Nothing in this slice hardcodes either number — Task 8 reads the column at runtime — but an
  implementer who "sanity-checks" a measurement against 880 will chase a phantom.
- **Pinned e2e viewports:** desktop **1280x900**, phone **360x640**.
- **Pinned fixtures:** tall **297x719**, wide **948x719** (both real images from unit 1095).
- **Token-driven CSS** — no hardcoded colours; use existing custom properties. `core/static/core/css/app.css` is GLOBAL.
- **Django multi-line comments** use `{% comment %}`; `{# #}` must be single-line.
- **Module-level translatable strings** must use `gettext_lazy`.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **Never create `courses/tests/__init__.py`** — it renames every module under that directory.
- **Fixtures live inline, per module.** `courses/tests/` has **no `conftest.py`** and this slice does
  **not** add one: `tests/conftest.py` (which holds `_enable_db_access` and three other autouse
  fixtures) applies only to the `tests/` subtree and is invisible from `courses/tests/`, and the root
  `conftest.py` defines exactly one fixture (`_reset_active_language`). Note that even inside `tests/`
  the house style is module-local — `course` and `image_asset` live in
  `tests/test_transfer_export.py:47-52`, not in any conftest. Every fixture a
  `courses/tests/` module needs is written **in that module**, matching the house style
  (`test_question_restore.py`'s local `_image(course)` helper, `test_callout_nesting.py`'s local
  `_top_callout`). Shared *helpers* come from `tests.factories` — `make_course_with_unit`,
  `add_element`, `TEST_PASSWORD` — which import fine from anywhere.
- **A `MediaAsset` of kind `image`, in the unit tests (Tasks 1-5 only)**, is built as
  `MediaAsset.objects.create(course=course, kind="image", file="courses/media/x.png",
  original_filename="x.png")` (the `test_question_restore.py:364-370` pattern). No real file is needed
  **there** — nothing in Tasks 1-5 reads the bytes, and the raw `create()` skips a Pillow round-trip.
- **The e2e tasks (8 and 9) are the exception and need real bytes.** Every assertion there depends on
  the browser loading a file whose intrinsic ratio is 0.413 / 1.319, so they use the house factory
  `tests.factories.make_image_asset(course, filename, size=(w, h), color=…)` (`tests/factories.py:145`),
  which writes a real PNG at a given size — **and** the `_isolated_media` fixture, which is mandatory
  rather than hygienic: `live_server`'s `_MediaFilesHandler` reads `settings.MEDIA_ROOT` *per request*,
  so pointing it at `tmp_path` before any asset exists is what makes `/media/<path>` resolve at all
  (`tests/test_e2e_imagezoom.py:8-16, 56-69`). Without it the `<img>` 404s and collapses to the
  broken-image box, and every measurement is meaningless.
- **A nested element** is `Element.objects.create(unit=unit, content_object=obj, parent=<parent join>,
  tab_id=<Parent>.SLOT_ID)`; a top-level one is `add_element(unit, obj)` from `tests.factories`.
- **`makemigrations --check --dry-run` must stay clean** (CI guards this since #204).
- **A passing test proves nothing** — for every test, delete the code it guards and confirm it goes RED before moving on. Name the mutant.
- **Lint at the task that introduces the code.** `ruff` runs `select = ["E","F","I","UP","B","S"]` at line-length 88, with `[tool.ruff.lint.isort] force-single-line = true` (so a combined `from x import A, B` must be split one-per-line). Every task's test step must also run `uv run ruff check <files touched>` and `uv run ruff format --check <same>`.

## File Structure

| File | Responsibility in this slice |
|---|---|
| `courses/models.py` | `ImageElement.Size` TextChoices + the `size` field |
| `courses/migrations/0054_imageelement_size.py` | schema migration, `default="full"`, no data migration |
| `courses/element_forms.py` | `ImageElementForm.Meta.fields` gains `"size"` |
| `templates/courses/elements/imageelement.html` | preset class + `data-preview-el` on the `<figure>` |
| `templates/courses/manage/editor/_edit_image.html` | fieldset/legend + four radios with checked reflection |
| `courses/static/courses/css/courses.css` | four bounding boxes, figure box rules, print block |
| `core/static/core/css/app.css` | `.size-presets` editor-control chrome (Task 2) |
| `tests/test_transfer_{schema,export}.py`, `tests/test_{link,tabs}_transfer.py` | existing `FORMAT_VERSION`/payload assertions this slice invalidates |
| `courses/static/courses/js/editor.js` | size branch inside the existing `root` change handler |
| `courses/transfer/export.py` | `_ser_image` emits `size` |
| `courses/transfer/payloads.py` | `_val_image` `setdefault` + exact-keys + value check |
| `courses/transfer/importer.py` | `_build_image` reads `size` |
| `courses/transfer/schema.py` | `FORMAT_VERSION` 6 → 7 |
| `docs/help/course-admin/{content-editors,interactive-elements}{,.pl}.md` | author documentation |

---

### Task 1: Model field and migration

**Files:**
- Modify: `courses/models.py` (the `ImageElement` class)
- Create: `courses/migrations/0054_imageelement_size.py` (via `makemigrations`)
- Test: `courses/tests/test_image_size_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ImageElement.Size` (nested `TextChoices` with values `"small"`, `"medium"`, `"large"`, `"full"`), `ImageElement.Size.values`, and the field `ImageElement.size` (`CharField`, `max_length=8`, `default=Size.FULL`).

**The migration is `0054_…`** — the latest on this branch is `0053_spoiler_body_cleanup.py`. Re-check
before committing: if a migration landed on `master` in the meantime the generated number will differ,
and the commit command below stages the directory rather than a literal filename precisely so a
different number cannot abort the `git add`.

**Between this task's commit and Task 4's, `size` is silently dropped by duplicate-and-paste.**
`duplicate_element` (`courses/builder.py`) and the element clipboard both round-trip through
`courses/transfer/export.py` + `importer.py`, which do not carry `size` until Task 4. Every
intermediate commit on this branch has that hole; it closes at Task 4 and is not a defect to report
when reviewing the commits in between.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_model.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from courses.models import ImageElement

pytestmark = pytest.mark.django_db


def test_size_defaults_to_full():
    el = ImageElement()
    assert el.size == "full"


def test_size_choices_are_the_four_presets():
    assert list(ImageElement.Size.values) == ["small", "medium", "large", "full"]


def test_size_rejects_an_unknown_value():
    """`size` in error_dict, not a bare raises: full_clean aggregates errors across
    every field and the model's own clean(), so a bare pytest.raises passes if ANY
    field fails — including for reasons that have nothing to do with the choices."""
    el = ImageElement(size="enormous")
    with pytest.raises(ValidationError) as exc:
        el.full_clean(exclude=["media"])
    assert "size" in exc.value.error_dict
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_image_size_model.py --verbosity=0`
Expected: FAIL — `AttributeError: type object 'ImageElement' has no attribute 'Size'`.

- [ ] **Step 3: Add the field**

In `courses/models.py`, inside `class ImageElement(ElementBase):`, above the existing `media` field:

```python
    class Size(models.TextChoices):
        SMALL = "small", _("Small")
        MEDIUM = "medium", _("Medium")
        LARGE = "large", _("Large")
        # pgettext, not plain _: the bare msgid "Full" is ALREADY taken by the
        # structure-preset label at courses/forms.py:166, and Django's catalog is keyed
        # by msgid alone. Its Polish translation is "Pełna" (feminine, agreeing with the
        # noun there); an image size wants the masculine "Pełny". Sharing the msgid means
        # one of the two ships ungrammatical, and no test would see it. The context
        # string forks the entry.
        FULL = "full", pgettext_lazy("image size", "Full")
```

Import it beside the existing `_`: `from django.utils.translation import pgettext_lazy` (one import
per line — `force-single-line` is on). `SMALL`/`MEDIUM`/`LARGE` need no context; re-grep
`locale/pl/LC_MESSAGES/django.po` for each before committing in case another lands first.

and after the existing `figcaption` field:

```python
    # A bounding box, not a width: max-width lives on the <figure> and max-height
    # on the <img> (see courses.css). `full` is today's rendering plus a
    # max-height:100dvh floor, so no data migration is needed.
    size = models.CharField(max_length=8, choices=Size.choices, default=Size.FULL)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses -n imageelement_size`
Then: `uv run python manage.py makemigrations --check --dry-run` → expect `No changes detected`.

The migration must contain only an `AddField` with `default="full"`. If it contains a `RunPython`, delete it — this slice has no data migration by design.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_model.py --verbosity=0`
Expected: 3 passed.

- [ ] **Step 6: Falsify**

Change the field's `default=Size.FULL` to `default=Size.SMALL`; confirm `test_size_defaults_to_full` goes RED. Restore. Remove `"large"` from the choices; confirm `test_size_choices_are_the_four_presets` goes RED. Restore. Drop `choices=Size.choices` from the field entirely; confirm `test_size_rejects_an_unknown_value` goes RED (nothing validates the value any more). Restore, re-run, confirm 3 passed.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check courses/models.py courses/tests/test_image_size_model.py
uv run ruff format --check courses/models.py courses/tests/test_image_size_model.py
git add courses/models.py courses/migrations/ courses/tests/test_image_size_model.py
git commit -m "feat(image): add a size preset field defaulting to full"
```

---

### Task 2: Form wiring and the editor control

**Files:**
- Modify: `courses/element_forms.py:118-120` (`ImageElementForm.Meta.fields`)
- Modify: `templates/courses/manage/editor/_edit_image.html`
- Test: `courses/tests/test_image_size_editor.py`

**Interfaces:**
- Consumes: `ImageElement.Size` and `ImageElement.size` from Task 1.
- Produces: radios named `size`, each carrying `data-size-preset` (marker attribute, no value) and `data-for-element="<element pk>"`. Task 7's JS matches on exactly these.

**Why both halves are one task:** `Meta.fields` without the checked radios breaks *every* image save (a required `ChoiceField` with nothing checked submits no `size` key); the radios without `Meta.fields` are silently discarded. Neither half is shippable alone.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_editor.py`:

```python
import re
from pathlib import Path

import pytest

from courses.element_forms import ImageElementForm
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

# Anchor for the CSS token test in Step 6. Same pattern Task 5 uses.
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def image_media():
    """A course-scoped image MediaAsset. Defined here, not in a conftest — see
    Global Constraints: courses/tests/ has none and this slice does not add one."""
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def test_form_accepts_the_size_field():
    assert "size" in ImageElementForm.Meta.fields


def test_form_saves_a_chosen_size(image_media):
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "a", "figcaption": "", "size": "medium"},
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert form.save().size == "medium"


def test_a_post_that_omits_size_is_rejected(image_media):
    """THE TRAP, stated as a fact rather than assumed: `size` is a required
    ChoiceField, so a POST without the key is INVALID — which is exactly why the
    template's `checked` attribute is load-bearing rather than cosmetic. The
    companion pin is test_editor_always_checks_exactly_one_radio below: together
    they say "a save without `size` fails" AND "the rendered form can never
    produce such a save"."""
    el = ImageElement.objects.create(media=image_media, alt="before", size="large")
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "after", "figcaption": ""},
        instance=el,
        course=image_media.course,
    )
    assert not form.is_valid()
    assert "size" in form.errors


def test_an_alt_only_edit_still_saves(image_media):
    """Spec row 16: with the rendered form's `size` present (as `checked` guarantees),
    an edit that changes only `alt` succeeds."""
    el = ImageElement.objects.create(media=image_media, alt="before", size="large")
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "after", "figcaption": "", "size": "large"},
        instance=el,
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.alt == "after"
    assert saved.size == "large"  # the untouched preset survives the edit
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_image_size_editor.py --verbosity=0`
Expected: FAIL — `"size" in ImageElementForm.Meta.fields` is False.

- [ ] **Step 3: Widen the form**

In `courses/element_forms.py`, in `ImageElementForm.Meta`:

```python
        fields = ["media", "alt", "figcaption", "size"]
```

- [ ] **Step 4: Add the control to the editor template**

In `templates/courses/manage/editor/_edit_image.html`, after the caption `<label>`:

```html
  {% comment %}Radios rather than a select: all four options stay visible at once and one
     click both selects and drives the live preview. `checked` is NOT cosmetic — `size` is a
     required ChoiceField, so a group with nothing checked submits no `size` key and fails
     validation on ANY save of this element, including an alt-only edit. Looping over
     form.fields.size.choices keeps the four presets from being duplicated here.

     The loop yields exactly FOUR options, never a leading blank: Field.formfield() passes
     include_blank = self.blank or not (self.has_default() or "initial" in kwargs), and the
     model field is blank=False WITH a default — so both disjuncts are false. If you ever see
     a phantom empty first radio, the model field lost its default; fix that, not this loop.

     default_if_none:"" — on the CREATE flow form.instance.pk is None, and Django renders a
     resolved None as the string "None" (string_if_invalid applies only to VariableDoesNotExist).
     The empty string is what Task 7's JS comment and Task 9's preconditions both assume.{% endcomment %}
  <fieldset class="size-presets">
    <legend>{% trans "Size" %}</legend>
    {% for value, label in form.fields.size.choices %}
      <label><input type="radio" name="size" value="{{ value }}"
        {% if form.size.value|stringformat:"s" == value|stringformat:"s" %} checked{% endif %}
        data-size-preset data-for-element="{{ form.instance.pk|default_if_none:'' }}"> {{ label }}</label>
    {% endfor %}
  </fieldset>
```

- [ ] **Step 5: Add the template assertions**

**These four assertions are deliberately not red-first**, unlike Step 1's form tests: they land after
Step 4 has already added the control, because a rendering assertion written before the template exists
fails on a missing radio rather than on the property under test, which is a weaker signal than it
looks. The red signal for them is recovered in Step 8's falsify pass, which deletes the `checked`
clause and the `default_if_none` filter and requires each to go RED. That is the trade, made on
purpose — not an oversight.

**There is no per-element edit PAGE in this app.** `courses:manage_element_edit` does not exist
(`courses/urls.py` has `manage_element_form` / `_save` / `_add`, no `_edit`), so `reverse` would raise
`NoReverseMatch`. Element editing happens inside the unit editor via fetched fragments — the same fact
`tests/test_e2e_imagezoom.py:982-986` records. Render the partial directly, exactly as
`tests/test_table_editor_partial.py:17-22`, `test_tabs_editor_partial.py` and
`test_gallery_editor_partial.py` do. That also removes the need for `client`, a `pa_user` and a login.

Append to `courses/tests/test_image_size_editor.py`:

```python
def _render_editor(instance=None):
    """The house partial-render pattern (tests/test_table_editor_partial.py:17-22)."""
    from django.template.loader import render_to_string

    form = ImageElementForm(instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_image.html", {"form": form, "type_key": "image"}
    )


def _radio_tag(html, value):
    """The single <input> tag whose value="<value>", so `checked` can be attributed to
    THAT radio rather than to `checked` appearing anywhere in the document."""
    m = re.search(r"<input[^>]*value=\"" + value + r"\"[^>]*>", html)
    assert m, f"no radio rendered for {value}"
    return m.group(0)


def test_editor_renders_four_radios_with_the_contract_attributes(image_media):
    # `image_el` is the ImageElement (what the form and both data-* hooks key on).
    # Its Element join row is a DIFFERENT object and is deliberately not needed here:
    # `unit`/`content_object` live on Element, `media`/`alt`/`size` on ImageElement.
    image_el = ImageElement.objects.create(media=image_media, alt="a", size="large")
    html = _render_editor(image_el)
    for value in ("small", "medium", "large", "full"):
        assert f'value="{value}"' in html
    assert "data-size-preset" in html
    assert f'data-for-element="{image_el.pk}"' in html
    assert "<legend>" in html


def test_editor_checks_the_stored_preset_and_only_that_one(image_media):
    """Spec row 15, first half."""
    image_el = ImageElement.objects.create(media=image_media, alt="a", size="large")
    html = _render_editor(image_el)
    assert " checked" in _radio_tag(html, "large")
    for other in ("small", "medium", "full"):
        assert " checked" not in _radio_tag(html, other)


def test_a_fresh_element_checks_full(image_media):
    """Spec row 15, second half — an UNBOUND form (the create flow) must still
    submit a `size`, so the default has to arrive pre-checked."""
    html = _render_editor()
    assert " checked" in _radio_tag(html, "full")
    for other in ("small", "medium", "large"):
        assert " checked" not in _radio_tag(html, other)


def test_the_create_flow_renders_an_empty_for_element(image_media):
    """Pins the default_if_none filter: an unsaved instance has pk None, which Django
    would otherwise render as the literal string "None"."""
    assert 'data-for-element=""' in _render_editor()
```

- [ ] **Step 6: Style the control**

The fieldset ships with the raw UA border and no spacing otherwise — `reset.css` zeroes every margin
and this project has no global `fieldset`/`legend` rule that sets **border, padding or spacing**. The
one global fieldset rule, `reset.css:22`'s `fieldset { min-inline-size: 0 }`, touches none of those
(it exists to stop the UA's `min-inline-size: min-content` defeating nested scroll boxes); the only
rules that do style a fieldset are `.analytics__export-form fieldset` at `app.css:789-794` and
`.roster > legend` at `:188`, both scoped elsewhere. "Every view ships styled"
is a standing project rule. The editor's other `.el-editor__*` chrome lives in
`core/static/core/css/app.css` (see `.el-editor__option-row` at `:1222`), so put it there, beside it:

```css
/* The image size preset control. No global fieldset/legend rule exists, so without
   this the radios ship with the UA border and zero spacing next to the flat
   .el-editor labels above them. Tokens only — no literal colours. */
.size-presets {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
  margin: var(--space-2) 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: center;
}
.size-presets > legend { color: var(--text-secondary); padding-inline: var(--space-1); }
.size-presets label { display: inline-flex; align-items: center; gap: var(--space-1); }
```

**There is no `--border` token** — `core/static/core/css/tokens.css:52` (light) and `:95` (dark) define
`--border-subtle`, `--border-default` and `--border-strong` only, which is why the block above says
`--border-default` (the same one `.analytics__export-form fieldset` uses). This matters more than it
looks: an *undefined* custom property makes the whole declaration invalid at computed-value time, so
the fieldset would ship with no border at all — the exact "every view ships styled" failure this step
exists to prevent, and no test in Tasks 7-8 touches `app.css` to catch it. Confirm every custom
property used here against `core/static/core/css/tokens.css` (**not** `app.css`, which has no `:root`
block); if one is missing, substitute a defined token rather than inventing a name.

**Assert it, don't eyeball it.** Every other step in this plan ends in a test; a manual check is the
one thing a tired implementer skips, and the failure is invisible (a missing border looks like a
design choice). Add to `courses/tests/test_image_size_editor.py`:

```python
def test_size_preset_css_uses_only_declared_tokens():
    """An UNDEFINED custom property invalidates the whole declaration at
    computed-value time, so `var(--border)` would ship a borderless fieldset with
    nothing red anywhere."""
    app_css = (REPO / "core" / "static" / "core" / "css" / "app.css").read_text(encoding="utf-8")
    tokens = (REPO / "core" / "static" / "core" / "css" / "tokens.css").read_text(encoding="utf-8")
    # Brace-count from the first `.size-presets` to the last of its consecutive rules
    # (the Task 6 approach). Do NOT terminate on "the next line starting with a dot":
    # at the mandated insertion point the next such line is `.switchgrid` and the scan
    # would swallow the comment between them — and at EOF, or before an @media/#id
    # rule, it would match nothing and fail with a misleading "not found".
    start = app_css.find(".size-presets")
    assert start != -1, ".size-presets rules not found in app.css"
    end, depth, i = start, 0, start
    while i < len(app_css):
        if app_css[i] == "{":
            depth += 1
        elif app_css[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                nxt = app_css.find(".size-presets", end)
                if nxt == -1 or app_css[end:nxt].strip():
                    break  # next .size-presets rule is not adjacent — stop here
                i = nxt
                continue
        i += 1
    block = app_css[start:end]
    used = set(re.findall(r"var\((--[\w-]+)\)", block))
    assert used, "the block declares no tokens — did it hardcode a colour?"
    declared = set(re.findall(r"(--[\w-]+)\s*:", tokens))
    assert used <= declared, f"undeclared tokens: {sorted(used - declared)}"
```

`REPO` and the `pathlib` import are already at the top of
`courses/tests/test_image_size_editor.py` from Step 1 — that is the module this test belongs to.
**Mutant:** change one `var(--border-default)` to `var(--border)` and confirm RED.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_editor.py --verbosity=0`
Expected: all pass.

Then re-run the existing suites that touch the image form, image rendering, and the duplicate path —
widening a required field on `ImageElementForm` reaches all of them, and Task 10's repo-wide sweep is
four tasks too late to find out:

```bash
uv run pytest tests/test_element_add_save.py tests/test_courses_elements.py \
  tests/test_imagezoom_render.py tests/test_media_model.py \
  tests/test_manage_node_ops.py tests/test_builder_duplicate_element.py --verbosity=0
```

Expected: all green (unchanged). If any goes red, it is this task's regression — fix it here.

- [ ] **Step 8: Falsify**

Remove `"size"` from `Meta.fields`; confirm `test_form_saves_a_chosen_size` goes RED. Restore. Delete
the `{% if %}…checked{% endif %}` clause; confirm **both** `test_editor_checks_the_stored_preset_and_only_that_one`
and `test_a_fresh_element_checks_full` go RED. Restore. Delete the `|default_if_none:''` filter; confirm
`test_the_create_flow_renders_an_empty_for_element` goes RED with `data-for-element="None"`. Restore.
Change one `var(--border-default)` in the `.size-presets` block to `var(--border)`; confirm
`test_size_preset_css_uses_only_declared_tokens` goes RED. Restore, re-run, confirm all pass.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check courses/element_forms.py courses/tests/test_image_size_editor.py
uv run ruff format --check courses/element_forms.py courses/tests/test_image_size_editor.py
git add courses/element_forms.py templates/courses/manage/editor/_edit_image.html \
  core/static/core/css/app.css courses/tests/test_image_size_editor.py
git commit -m "feat(image): accept and render the size control in the editor"
```

---

### Task 3: Render the preset class and the preview hook

**Files:**
- Modify: `templates/courses/elements/imageelement.html`
- Test: `courses/tests/test_image_size_render.py`

**Interfaces:**
- Consumes: `ImageElement.size` from Task 1.
- Produces: `<figure class="el el--image el--image--<size>" data-preview-el="<pk>">`. Task 5's CSS and Task 7's JS both key on these.

**The attribute is `data-preview-el`, NOT `data-element-id`.** `progress.js:52` runs `document.querySelectorAll("[data-element-id]")` unscoped across the whole document to build the "seen" set, and `views.py:709-713` documents that only top-level `.lesson-block[data-element-id]` ids are ever reported. No element template emits that attribute today; using it here would make images the first violation. Do not "unify" them.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_render.py`. Both helpers are **module-level functions, not
fixtures**, with one fixed signature each: `make_image(size, course=None) -> ImageElement` (saved, so
`pk` is real) and `render(el, *, element=None) -> str`. The `course=` kwarg exists because Step 4's
nesting test must put the asset and the unit in the **same** course; passed nothing, `make_image` mints
its own. There is no `with_element` kwarg — the caller already holds the element it built.

```python
import pytest

from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import SpoilerElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _media(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def make_image(size, course=None):
    """A SAVED ImageElement — data-preview-el carries its pk, so it must exist."""
    if course is None:
        course, _unit = make_course_with_unit()
    return ImageElement.objects.create(media=_media(course), alt="a", size=size)


def render(el, *, element=None):
    return el.render(element=element)


@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
def test_figure_carries_its_preset_class(size):
    assert f"el--image--{size}" in render(make_image(size))


def test_figure_carries_the_preview_hook():
    el = make_image("medium")
    assert f'data-preview-el="{el.pk}"' in render(el)


def test_figure_does_not_carry_data_element_id():
    """Guards the progress.js invariant: [data-element-id] is queried unscoped on
    student pages and must stay top-level-only. See views.py:709-713."""
    assert "data-element-id" not in render(make_image("small"))


def test_nested_image_still_carries_the_preview_hook():
    """Nested under a spoiler — the figure's own markup must not depend on depth.
    `data-preview-el` is the IMAGE ELEMENT's pk at every depth (same pk Task 2's
    `data-for-element` emits), never the Element join row's."""
    course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)
    el = make_image("large", course=course)
    join = Element.objects.create(
        unit=unit, content_object=el, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    assert f'data-preview-el="{el.pk}"' in render(el, element=join)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_image_size_render.py --verbosity=0`
Expected: FAIL — neither the class nor the attribute is rendered.

- [ ] **Step 3: Update the element template**

`templates/courses/elements/imageelement.html` line 1 becomes:

```html
<figure class="el el--image el--image--{{ el.size }}" data-preview-el="{{ el.pk }}">
```

- [ ] **Step 4: Add the `_seen_current_ids` pin**

Spec row 3c. This is a **characterization** test of existing behaviour, not a TDD step — nothing in
this slice touches `_seen_current_ids`, so it is green before and after the template edit. It earns
its place by having a real mutant, which is why it is written *before* the falsify step rather than
after it.

`_seen_current_ids` (`courses/views.py:715-719`) returns **`Element` join-row pks**, filtered by
`parent__isnull=True` — a different pk namespace from `data-preview-el` (the `ImageElement` pk).
The assertion is about the join row:

```python
def test_a_nested_image_join_row_is_not_a_seen_id():
    """The nested image's ELEMENT join-row pk must be absent from the seen-set, which
    is what makes the data-element-id invariant above safe even if an attribute leaks.
    Note the two pk namespaces: `join.pk` here, `el.pk` in data-preview-el."""
    from courses.views import _seen_current_ids

    course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)
    el = make_image("small", course=course)
    join = Element.objects.create(
        unit=unit, content_object=el, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    seen = _seen_current_ids(unit)
    assert sp_join.pk in seen  # the top-level container IS reported
    assert join.pk not in seen  # its nested child is NOT
```

**Mutant:** delete `parent__isnull=True` from `_seen_current_ids`; confirm the `join.pk not in seen`
assertion goes RED. Restore.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_render.py --verbosity=0`
Expected: 8 passed (4 parametrized + 4).

Then re-run the existing suites that render `imageelement.html`, since this task rewrites its root tag:

```bash
uv run pytest tests/test_imagezoom_render.py tests/test_media_model.py --verbosity=0
```

Expected: green (unchanged).

- [ ] **Step 6: Falsify**

Replace `el--image--{{ el.size }}` with a bare `el--image`; confirm all four parametrized cases go RED. Restore. Change `data-preview-el` to `data-element-id`; confirm both `test_figure_carries_the_preview_hook` and `test_figure_does_not_carry_data_element_id` go RED. Restore. Apply the Step 4 mutant and restore it. Re-run, confirm 8 passed.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check courses/tests/test_image_size_render.py
uv run ruff format --check courses/tests/test_image_size_render.py
git add templates/courses/elements/imageelement.html courses/tests/test_image_size_render.py
git commit -m "feat(image): render the preset class and the preview hook"
```

---

### Task 4: Course transfer

**Files:**
- Modify: `courses/transfer/export.py:82-83` (`_ser_image`)
- Modify: `courses/transfer/payloads.py:131-136` (`_val_image`)
- Modify: `courses/transfer/importer.py:491-495` (`_build_image`)
- Modify: `courses/transfer/schema.py:14` (`FORMAT_VERSION`)
- Test: `courses/tests/test_image_size_transfer.py`

**Interfaces:**
- Consumes: `ImageElement.size`, `ImageElement.Size.values` from Task 1.
- Produces: element payloads carrying `"size"`; `FORMAT_VERSION == 7`.

**`_exact_keys` is exact, not an allowlist** — an archive with an unexpected key is rejected AND one missing a listed key is rejected. So `size` cannot simply be appended: every pre-feature archive would fail. Follow the house pattern already in this file for iframe `width`/`height` (`payloads.py:153-157`): `setdefault` **before** `_exact_keys`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_transfer.py`. Drive the three registries directly — the house
pattern in `courses/tests/test_callout_transfer.py:24-42` — rather than a whole-course export/import,
so no fixture beyond a `MediaAsset` is needed. `media_kinds` is a `{media_id: kind}` dict
(`payloads.py:97-102`).

```python
import pytest

from courses.models import ImageElement
from courses.models import MediaAsset
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import make_course_with_unit

MEDIA_KINDS = {"m1": "image"}


class _Ids:
    """Stand-in for the export id registry: every asset serialises to "m1"."""

    def register(self, *a, **k):
        return "m1"


def _media(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return _media(course)


def _validate(data):
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)


def test_format_version_is_bumped():
    assert FORMAT_VERSION == 7


@pytest.mark.django_db
@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
def test_round_trip_preserves_the_preset(size, image_media):
    el = ImageElement.objects.create(media=image_media, alt="a", figcaption="", size=size)
    _model, ser = SERIALIZERS["image"]
    data = ser(el, _Ids())
    assert data["size"] == size
    _validate(data)
    rebuilt, _refs = BUILDERS["image"](data, {"m1": image_media})
    assert rebuilt.size == size


@pytest.mark.django_db
def test_archive_without_a_size_key_imports_as_full(image_media):
    data = {"media": "m1", "alt": "a", "figcaption": ""}
    _validate(data)
    assert data["size"] == "full"
    rebuilt, _refs = BUILDERS["image"](data, {"m1": image_media})
    assert rebuilt.size == "full"


@pytest.mark.django_db
def test_a_junk_size_is_coerced_to_full(image_media):
    """Named for what it does: this one pins COERCION, not import — unlike its
    sibling above it never calls BUILDERS."""
    data = {"media": "m1", "alt": "a", "figcaption": "", "size": "enormous"}
    _validate(data)  # must NOT raise
    assert data["size"] == "full"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_image_size_transfer.py --verbosity=0`
Expected: FAIL — `FORMAT_VERSION == 6`.

- [ ] **Step 3: Emit `size` on export**

`courses/transfer/export.py`:

```python
def _ser_image(el, ids):
    return {
        "media": ids.register(el.media),
        "alt": el.alt,
        "figcaption": el.figcaption,
        "size": el.size,
    }
```

- [ ] **Step 4: Validate with a back-compat default**

Add `from courses.models import ImageElement` to the **module-level** import block (`payloads.py:16-17`
already imports `DragZone` and `TableElement` there, so there is no cycle to dodge; one import per
line for `force-single-line`), then, inside `_val_image`, **before** the `_exact_keys` call:

```python
    # `size` is optional (added in FORMAT_VERSION 7). setdefault first so a legacy
    # archive (which has neither) gains it and passes the exact-keys check, and so
    # downstream _build_image never KeyErrors. Mirrors the iframe width/height
    # precedent at :153-157.
    data.setdefault("size", "full")
    if data["size"] not in ImageElement.Size.values:
        # A cosmetic field with a lossless default must never fail an import:
        # `full` IS the pre-feature rendering. (Contrast _val_callout, which
        # rejects an unknown `kind` — a kind has no safe fallback.)
        data["size"] = "full"
```

and widen the key list:

```python
    _exact_keys(data, ["media", "alt", "figcaption", "size"], _("image data"))
```

- [ ] **Step 5: Read it on import**

`courses/transfer/importer.py`:

```python
def _build_image(data, assets):
    el = ImageElement(
        media=assets[data["media"]],
        alt=data["alt"],
        figcaption=data["figcaption"],
        size=data["size"],
    )
    return _clean_save(el), ()
```

- [ ] **Step 6: Bump the format version**

`courses/transfer/schema.py`: `FORMAT_VERSION = 7`.

- [ ] **Step 7: Update the existing assertions this bump invalidates**

Steps 3 and 6 falsify five existing places. None of them is a defect — each one *pins* the old value
on purpose, so each must be re-pinned to the new one. Three of the five live in files the original
verification command never ran, so they would otherwise surface four tasks later in Task 10:

| File | Line | Change |
|---|---|---|
| `tests/test_transfer_schema.py` | 57 | `assert FORMAT_VERSION == 6` → `== 7` |
| `tests/test_link_transfer.py` | 54 | `assert FORMAT_VERSION == 6` → `== 7`, **and rename the enclosing `test_format_version_is_6` → `test_format_version_is_7`** |
| `tests/test_tabs_transfer.py` | 58 | `assert FORMAT_VERSION == 6` → `== 7`, **and rename `test_format_version_is_6` → `test_format_version_is_7`** |
| `tests/test_transfer_export.py` | 220 | `assert manifest["format_version"] == 6` → `== 7` |
| `tests/test_transfer_export.py` | 76 | `assert data == {"media": "m1", "alt": "a", "figcaption": "c"}` → add `"size": "full"` |
| `tests/test_table_transfer.py` | 265 | comment `4 <= FORMAT_VERSION=6` → `=7` (prose only) |

**This six-row table is the authority**, not a grep. The obvious re-grep
(`grep -rn "FORMAT_VERSION == 6\|format_version\"\] == 6" tests courses`) finds only the first four:
it misses the exact-dict row at `test_transfer_export.py:76` — which Step 3, not Step 6, breaks — and
the prose comment. Run the grep anyway, as a guard against a *new* `FORMAT_VERSION == 6` landing on
`master` in the meantime, but never as the definition of "done".

- [ ] **Step 8: Pin that duplicate-and-paste now carries `size`**

Task 1's preamble asserts as a *mechanism* that `duplicate_element` round-trips through
`export.py` + `importer.py` and therefore starts preserving `size` the moment this task lands
(`courses/builder.py:420-449` confirms it: `_copy_below(el, unit, _export, _importer, …)`). Nothing
verifies it — the tests above drive the three registries directly, and Task 2's re-run of
`tests/test_builder_duplicate_element.py` knows nothing about `size`. Close the loop:

```python
@pytest.mark.django_db
def test_duplicating_an_image_preserves_its_preset():
    """The hole Task 1 opened and this task closes, asserted rather than assumed."""
    from courses import builder
    from tests.factories import add_element

    course, unit = make_course_with_unit()
    el = ImageElement.objects.create(
        media=_media(course), alt="a", figcaption="", size="small"
    )
    join = add_element(unit, el)
    _unit, new_join = builder.duplicate_element(course, join.pk, unit.updated.isoformat())
    assert new_join.content_object.size == "small"
```

It takes no `image_media` fixture: the asset must belong to the **same course as the unit**, so the
test builds both together via the module's `_media(course)` helper. `unit.updated.isoformat()` is the
conflict token `duplicate_element` checks.

**Mutant:** drop `"size"` from `_ser_image`; confirm this goes RED alongside the round-trip cases.

- [ ] **Step 9: Run tests to verify they pass**

Run:

```bash
uv run pytest courses/tests/test_image_size_transfer.py tests/test_transfer_export.py \
  tests/test_transfer_import.py tests/test_transfer_schema.py tests/test_link_transfer.py \
  tests/test_tabs_transfer.py tests/test_table_transfer.py \
  tests/test_transfer_validation.py tests/test_transfer_media.py --verbosity=0
```

The last two are the cheapest proof the `setdefault` works: `tests/test_transfer_validation.py:235,244,495,540`
and `tests/test_transfer_media.py:67` all push `{"media": …, "alt": "", "figcaption": ""}` — payloads
with **no** `size` key — straight through the widened `_exact_keys`. They must stay green *without*
being edited; if one goes red, the back-compat default is broken, not the test.

Expected: all pass. (Before Step 7 they do **not** — five assertions are red by construction. That is
the point of Step 7, not a surprise.)

- [ ] **Step 10: Falsify**

Delete the `data.setdefault("size", "full")` line; confirm `test_archive_without_a_size_key_imports_as_full` goes RED — the observed error is **`KeyError: 'size'`** raised by the very next line (`if data["size"] not in …`), *not* an exact-keys `TransferError`, because that line runs before `_exact_keys` is reached. To see the exact-keys path instead, delete the `setdefault` **and** the whole junk-value block: then `_exact_keys` rejects the legacy payload with a `TransferError`. Restore. Delete only the junk-value coercion; confirm `test_a_junk_size_is_coerced_to_full` goes RED. Restore. Drop `"size"` from `_ser_image`; confirm the round-trip cases go RED. Restore, re-run, confirm all pass.

- [ ] **Step 11: Lint and commit**

```bash
uv run ruff check courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/transfer/schema.py courses/tests/test_image_size_transfer.py
uv run ruff format --check courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/transfer/schema.py courses/tests/test_image_size_transfer.py
git add courses/transfer/ courses/tests/test_image_size_transfer.py \
  tests/test_transfer_schema.py tests/test_link_transfer.py tests/test_tabs_transfer.py \
  tests/test_transfer_export.py tests/test_table_transfer.py
git commit -m "feat(transfer): carry the image size preset, defaulting old archives to full"
```

---

### Task 5: The preset CSS

**Files:**
- Modify: `courses/static/courses/css/courses.css` (after the existing `.el--image img` rule at `:46`)
- Test: `courses/tests/test_image_size_css.py`

**Interfaces:**
- Consumes: the class names rendered in Task 3.
- Produces: `.el--image--{small,medium,large,full}` figure rules and `.el--image--* img` height rules.

**Placement is load-bearing.** The block MUST come after `.el { margin: 1rem 0 }` (`courses.css:4`), because `.el` and `.el--image--small` are both single-class selectors on the same figure and tie on specificity — `margin-inline: auto` wins the horizontal margin only on source order.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_css.py`.

**Locate the file the house way**, never by a relative path (which breaks with the pytest invocation
directory) — the pattern is `tests/test_imagezoom_render.py:92-93`, and the explicit encoding matters
on Windows:

```python
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COURSES_CSS = REPO / "courses" / "static" / "courses" / "css" / "courses.css"


def _css():
    """Comments STRIPPED. Non-negotiable: the comment blocks this plan mandates
    contain the very tokens being asserted — the Task 5 comment names
    `.el--image--small` and `.el { margin: 1rem 0 }`, the Task 6 one contains
    "30/45/60%" — so a bare-substring scan of the raw file passes on prose alone.
    This repo has the recorded lesson (test_element_state_write_routes.py regexes
    raw source including comments AND docstrings)."""
    return re.sub(r"/\*.*?\*/", "", COURSES_CSS.read_text(encoding="utf-8"), flags=re.S)
```

Assert against **declarations, not substrings** — mirroring
`tests/test_imagezoom_render.py:97-100`'s `SCRIM_DECL = re.compile(r"--scrim-solid\s*:")` style. One
regex per claim:

- `\.el--image--small\s*\{[^}]*max-width:\s*25%` (and 50% / 75% for medium / large);
- `\.el--image--small\s+img\s*\{[^}]*max-height:\s*30dvh` (45/60/100dvh for medium/large/full);
- the **figure** group carrying `width: fit-content; margin-inline: auto`, and
- the **img** group carrying `margin-inline: auto`.

The last two need their own regexes, not prose, because both are harder than they look: each selector
list spans three comma-separated lines, and the "excludes `full`" half must be scoped to *that rule*
— a file-wide `"el--image--full" not in css` is red before any mutant lands, since `full` legitimately
appears in the `max-height` rule two lines below. Isolate the rule the same way Task 6 isolates the
print block (match the selector list, then brace-count its body), then assert on the **selector list**
itself:

```python
FIG_GROUP = re.compile(
    r"((?:\.el--image--\w+\s*,\s*)+\.el--image--\w+)\s*\{[^}]*width:\s*fit-content[^}]*\}", re.S
)
IMG_GROUP = re.compile(
    r"((?:\.el--image--\w+\s+img\s*,\s*)+\.el--image--\w+\s+img)\s*\{[^}]*margin-inline:\s*auto[^}]*\}",
    re.S,
)
```

For each: assert exactly one match; assert its captured selector list mentions `small`, `medium` and
`large`; assert it does **not** mention `full`. Step 5's mutant (add `.el--image--full` to the
`fit-content` group) then lands inside the captured group and turns that last assertion RED, which a
file-wide scan could never do.

Also assert `.el--image img { max-width: 100%; height: auto; }` is still present unchanged — Task 5
retains it, and nothing else in this slice would notice its removal. (Only `height: auto` is actually
load-bearing there: `reset.css:11` already declares `img, picture, svg { display: block; max-width:
100%; }` app-wide. The assertion pins the rule as written regardless.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_image_size_css.py --verbosity=0`
Expected: FAIL — no preset rules exist.

- [ ] **Step 3: Add the rules**

```css
/* Image size presets. Each is a BOUNDING BOX: max-width on the figure (a % of
   .lesson's definite content box) and max-height on the img (dvh). A % on the img
   would resolve circularly against a fit-content figure, which is why the two axes
   live on different elements.

   dvh not vh: vh resolves against the toolbar-COLLAPSED viewport, so a vh-capped
   image can still fall below the fold on a phone with the address bar showing —
   the exact defect this feature exists to fix. Same reasoning as the imagezoom
   overlay at :1724.

   This block MUST stay after `.el { margin: 1rem 0 }` (:4): `.el` and
   `.el--image--small` tie on specificity, so margin-inline:auto wins only on
   source order. */
.el--image--small  { max-width: 25%; }
.el--image--medium { max-width: 50%; }
.el--image--large  { max-width: 75%; }

.el--image--small,
.el--image--medium,
.el--image--large  { width: fit-content; margin-inline: auto; }

/* Centre the image WITHIN the figure. Load-bearing whenever the figure ends up WIDER
   than the constrained image, which happens two independent ways:
     1. a figcaption — fit-content sizes the figure to the WIDER of {image, caption}
        max-content contributions, so a long caption widens the figure past the image;
     2. POSSIBLY a binding max-height with NO caption — at 1280x900, `small`, the
        297x719 fixture, the img shrinks to ~111.5x270 while max-width caps the figure
        at 162px. Whether fit-content then shrink-wraps the figure to the constrained
        (111.5px) or the unconstrained (162px) contribution is engine-dependent, so
        whether reason 2 exists at all is MEASURED in Task 9 step 1, not reasoned about.
        If that measurement says the figure tracks the image, delete reason 2 from this
        comment — do not leave a mechanism here that the measurement disproved.
   Scoped to the capped presets so `full` keeps today's flush-left geometry — 1013
   images must render byte-identically.

   `margin-inline` is the ONLY differentiator here: reset.css:11 already sets
   `img, picture, svg { display: block; max-width: 100%; }` app-wide, so restating
   display:block keeps this rule self-contained but changes nothing. Do not read it as
   the thing `full` is being excluded from. (That reset also makes the `max-width: 100%`
   half of the retained `.el--image img` rule below redundant — only its `height: auto`
   is doing work. Both are kept as-is; this slice changes no existing rule.) */
.el--image--small  img,
.el--image--medium img,
.el--image--large  img { display: block; margin-inline: auto; }

.el--image--small  img { max-height: 30dvh; }
.el--image--medium img { max-height: 45dvh; }
.el--image--large  img { max-height: 60dvh; }
.el--image--full   img { max-height: 100dvh; }
```

The existing `.el--image img { max-width: 100%; height: auto; }` at `:46` is **retained unchanged**.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_css.py --verbosity=0`
Expected: all pass.

- [ ] **Step 5: Falsify**

Step 1 mandates about eleven assertions — three width regexes, four height regexes, two group regexes
with two sub-claims each, and the retained rule — and **every one gets its own named mutant**,
including the two group regexes the step itself calls "harder than they look". Apply and restore each
in turn:

| mutant | expected RED |
|---|---|
| **delete `.el--image--full img { max-height: 100dvh }`** | the `full` height assertion. **Do not skip this one** — it is the declaration the Architecture section credits with fixing all 54 measured over-tall images, i.e. the entire reason this feature ships without a data migration, and it is otherwise the only assertion in the plan whose subject has no mutant anywhere. It has a second predicted RED site in Task 8: the **phone `full` tall** case, where `hcap = 640` currently binds against `wcap/ratio = 716.7` and `naturalHeight = 719`, so removing the cap moves the predicted height from 640 to 716.7 |
| delete `.el--image--medium img { max-height: 45dvh }` | the medium height assertion |
| delete `.el--image--small img { max-height: 30dvh }` and `.el--image--large img { max-height: 60dvh }` (one at a time) | the corresponding height assertion. Listed for completeness: with `full` and `medium` above, all four height regexes then have a named mutant |
| change `.el--image--medium`'s `max-width` to `55%`, then `.el--image--large`'s to `80%` (one at a time) | the corresponding width assertion — completing the three percentage regexes |
| change `.el--image--small`'s `max-width` to `35%` | the small width assertion (proves the three percentage regexes are declaration-scoped, not substring scans) |
| add `.el--image--full` to the `fit-content` group | the FIG_GROUP "excludes `full`" assertion — and *not* the "exactly one match" one |
| delete the whole IMG_GROUP `margin-inline: auto` rule | the IMG_GROUP "exactly one match" assertion |
| delete `height: auto` from the retained `.el--image img` rule | the retained-rule assertion |

Restore each, re-run, confirm all pass.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check courses/tests/test_image_size_css.py
uv run ruff format --check courses/tests/test_image_size_css.py
git add courses/static/courses/css/courses.css courses/tests/test_image_size_css.py
git commit -m "style(image): four bounding-box size presets"
```

---

### Task 6: Print styles

**Files:**
- Modify: `courses/static/courses/css/courses.css` (a new `@media print` block, **after** the Task 5 rules)
- Test: `courses/tests/test_image_size_css.py` (extend)

**Interfaces:**
- Consumes: the preset selectors from Task 5.
- Produces: an `@media print` block bounding all four presets in millimetres.

**Ordering is the whole point.** `@media print { .el--image--small img { max-height: 45mm } }` ties on specificity with the screen rule — **a media query adds no specificity** — so the print block MUST come after the presets or every image prints at its `dvh` height. This project has hit this exact trap; see the comment at `courses.css:942-945`.

- [ ] **Step 1: Write the failing test**

Extend `courses/tests/test_image_size_css.py` with a `_print_block(css)` helper that extracts the
`@media print` block **in isolation** — a file-wide scan passes while the print block is empty,
because the selectors also appear in the screen rules — then asserts all four `mm` values inside it.

Two traps make the obvious one-line regex wrong, and both fail *silently* (the falsify step in Step 5
would then pass for the wrong reason):

- **`courses.css` already holds several `@media print` blocks** (`:822`, `:947`, `:1476`, `:1813`), so
  "the" print block is ambiguous and a first-match regex picks the breadcrumbs one. Select **by
  content**: the block whose body contains `.el--image--`. Assert exactly one such block exists.
- **`@media` bodies contain nested rule braces**, so `@media print\s*\{[^}]*\}` truncates at the first
  inner `}` — extracting only the `small` rule. Scan forward from the `@media print` match **counting
  braces** to the matching close, and return `(block_text, start_index)`.

The ordering test then asserts that `start_index` (of the selected block) is greater than the index of
the `full` height declaration in the comment-stripped source. Anchor it with a **regex**, not a
literal: Task 5's block is column-aligned (`.el--image--full   img { max-height: 100dvh; }`, three
spaces), so `css.index(".el--image--full img")` raises `ValueError` instead of failing an assertion.
Use `re.search(r"\.el--image--full\s+img\s*\{[^}]*100dvh", css).start()`, matching the
declaration-regex discipline Task 5 already mandates.

- [ ] **Step 2: Run the test to verify it fails**

Expected: FAIL — no print block mentions the preset selectors.

- [ ] **Step 3: Add the print block**

```css
/* dvh is meaningless on paper. These mm values are chosen to be sensible on A4
   (297mm tall, ~250mm printable): `full` at 170mm leaves ~80mm for surrounding
   text so an image never monopolises a page. NOT ratio-transferred from the screen
   boxes — as fractions of full they are 26/44/65% against the screen's 30/45/60%.

   This block MUST stay after the screen presets above: media queries add no
   specificity, so an earlier print block would lose the tie and every image would
   print at its dvh height. Same trap as :942-945. */
@media print {
  .el--image--small  img { max-height: 45mm; }
  .el--image--medium img { max-height: 75mm; }
  .el--image--large  img { max-height: 110mm; }
  .el--image--full   img { max-height: 170mm; }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_css.py --verbosity=0`
Expected: all pass.

- [ ] **Step 5: Falsify**

Move the print block above the Task 5 rules; confirm the ordering test goes RED. Restore. Delete the `.el--image--large img` line from inside the block; confirm the block-extracted scan goes RED **while a file-wide scan for the same selector would still pass** — note that contrast in the report. Restore, re-run, confirm all pass.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check courses/tests/test_image_size_css.py
uv run ruff format --check courses/tests/test_image_size_css.py
git add courses/static/courses/css/courses.css courses/tests/test_image_size_css.py
git commit -m "style(image): print bounds for the size presets"
```

---

### Task 7: Live preview without a save

**Files:**
- Modify: `courses/static/courses/js/editor.js` (inside the existing `root.addEventListener("change", …)` at `:462`)
- Test: `courses/tests/test_image_size_js.py`

**Interfaces:**
- Consumes: `data-size-preset` / `data-for-element` from Task 2, `data-preview-el` from Task 3, the class names from Task 5.
- Produces: no new exports — a branch inside an existing handler.

**Extend the existing handler; do not add a second listener.** `editor.js:3` establishes `var root = document.querySelector(".editor")` and `:462` already delegates `change`. `.editor` (`templates/courses/manage/editor/editor.html:11`) wraps both `[data-scope]` panes, and `applyFragments` replaces those panes wholesale — so anything bound *inside* a pane dies on the next swap, while a delegated handler on `root` survives.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_js.py`. Locate the file with the same
`REPO = Path(__file__).resolve().parents[2]` pattern and explicit `encoding="utf-8"` Task 5 uses —
a relative path breaks with the pytest invocation directory, and the Windows default encoding will
mangle a non-ASCII byte.

**Strip comments before scanning**, the same rule Task 5 applies to CSS. `tests/test_imagezoom_render.py`
already ships the helper for this exact file — two `re.sub`s, block comments then `//` lines — and its
docstring records why: a source assertion was once satisfied by `imagezoom.js`'s *prose* quoting
another module's code, and the capture-phase guard passed with capture removed. The JS branch this
task adds ships a three-line comment block of its own, so the discipline applies here even though
today's two assertions happen not to be comment-satisfiable.

Assert, against the stripped source: it contains `data-size-preset` and `data-preview-el`; and
`source.count('addEventListener("change"') == 1`. The count form is the concrete version of "no second
change listener" — a source scan cannot inspect what an arbitrary listener is *bound to*, but it can
insist there is still exactly one, which today is `root`'s at `editor.js:462`. (A source scan is weak;
the behaviour is pinned by Task 9's e2e.)

- [ ] **Step 2: Run the test to verify it fails**

Expected: FAIL — no `data-size-preset` in `editor.js`.

- [ ] **Step 3: Add the branch**

**Append it after the `[name$="-DELETE"]` (`del`) branch, immediately before the handler's closing
`});`** — last, not first. The `[data-choice-correct]` branch ends in an early `return`, so inserting
above it would silently move every other branch behind a guard; appending at the end changes no
existing reading order in a handler this project treats as load-bearing.

Inside the existing `root.addEventListener("change", function (e) { … })`:

```js
    var preset = e.target.closest("[data-size-preset]");
    if (preset) {
      // Live size preview with no save. classList.remove/add on just the
      // el--image--* token, never className assignment, so the swap cannot
      // clobber another class the figure carries now or later.
      var fig = document.querySelector(
        '.el--image[data-preview-el="' + preset.dataset.forElement + '"]'
      );
      if (fig) {
        fig.classList.remove(
          "el--image--small", "el--image--medium", "el--image--large", "el--image--full"
        );
        fig.classList.add("el--image--" + preset.value);
      }
      // On the CREATE flow data-for-element is "" (Task 2's template applies
      // |default_if_none:'' — without it Django would render the string "None")
      // and no figure exists yet, so the querySelector finds nothing and this is
      // inertly a no-op until first save. That is correct behaviour.
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: pass.

- [ ] **Step 5: Falsify**

Delete the branch; confirm the `data-size-preset` scan goes RED. Restore.

The `source.count('addEventListener("change"') == 1` assertion needs its **own** mutant — it is green
both before and after this task (there is exactly one such listener today, at `editor.js:462`), so the
mutant above never exercises it. Add a second `root.addEventListener("change", function () {});` to the
file; confirm the count assertion goes RED. Restore, re-run, confirm pass.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check courses/tests/test_image_size_js.py
uv run ruff format --check courses/tests/test_image_size_js.py
git add courses/static/courses/js/editor.js courses/tests/test_image_size_js.py
git commit -m "feat(editor): live size preview without a save"
```

---

### Task 8: e2e — computed bounding boxes

**Files:**
- Create: `tests/test_e2e_image_size.py`
- Test: itself

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces, all copied **verbatim** from `tests/test_e2e_depth3.py` (they close over `TEST_PASSWORD`
  and `make_verified_user`) and all reused by Task 9: `_make_pa_user`, `_login`, `_seed_unit`,
  `_lesson_url`, `_editor_url`, `_save_open_form` (`:133-137` — three lines, depends only on `page`;
  Task 9 Step 2 calls it), **and the session-scoped autouse `_allow_sync_orm_under_playwright`**
  (`test_e2e_depth3.py:47-52`, setting `DJANGO_ALLOW_ASYNC_UNSAFE`). Plus, from
  `tests/test_e2e_imagezoom.py:163-176`, **`_await_decoded(page, locator)`** — see Step 1.
- Also produces the **`seeded` fixture** — the interface Task 9 leans on hardest, so it is named here
  rather than left as locals. It must be a **fixture**, not locals inside a test function, or Task 9
  cannot reach any of it:

  ```python
  PA_USERNAME = "pa-imgsize"


  @pytest.fixture
  def seeded(_isolated_media):
      """(owner, course, unit, tall, wide). Depends on _isolated_media so MEDIA_ROOT is
      redirected BEFORE make_image_asset writes any bytes."""
      owner = _make_pa_user(PA_USERNAME)
      course, unit = _seed_unit(owner, "imgsize")
      tall = make_image_asset(course, "tall.png", size=(297, 719), color="magenta")
      wide = make_image_asset(course, "wide.png", size=(948, 719), color="magenta")
      # ... seed the eight elements on `unit` (Step 2)
      return owner, course, unit, tall, wide
  ```

  **`owner` is part of the return tuple, not a local.** Every test in both tasks must log in as it
  (see Step 2's navigation preamble), and Task 9 builds two more units in the same course; without it
  each test re-types the literal username, which is exactly the reachability problem this fixture
  exists to solve.

- Also produces the module's **import block**. `_seed_unit` imports `ContentNodeFactory` /
  `CourseFactory` *inside its own body*, so copying it verbatim does **not** put those names in the
  module namespace. Import at module level, one per line (`force-single-line`) — but **only what the
  file actually uses at that point**, because `ruff`'s `F401` is on for `tests/**` (the per-file
  ignores grant just `S105/S106/S107`), so a name imported for Task 9's benefit reddens **Task 8's own
  lint step**:

  ```python
  # Task 8 needs exactly these:
  import os                                            # _allow_sync_orm_under_playwright
  import pytest                                        # pytestmark + fixture decorators
  from courses.models import ImageElement
  from tests.factories import TEST_PASSWORD            # closed over by _login
  from tests.factories import add_element
  from tests.factories import make_image_asset
  from tests.factories import make_verified_user       # closed over by _make_pa_user
  ```

  **Task 9 adds these when it first needs them** (Step 0 / Step 3), not before:

  ```python
  from courses.models import CalloutElement
  from courses.models import Element
  from courses.models import SpoilerElement
  from courses.models import TabsElement
  from courses.models import TwoColumnElement
  from tests.factories import ContentNodeFactory
  ```

  Between the two blocks the list is exhaustive: Task 9 adds no *helpers* of its own, so anything it
  calls that is not here or above is a `NameError`. `TEST_PASSWORD` / `make_verified_user` are what
  `_make_pa_user` and `_login` close over — never a hardcoded password. Task 9 drives the **editor**, not
  just the lesson page, so `_seed_unit` and `_editor_url` are part of this task's contract, not
  optional extras.

  `_allow_sync_orm_under_playwright` is **module-local in every `tests/test_e2e_*.py` by design and is
  NOT in any conftest** (`tests/test_e2e_imagezoom.py` records exactly this). Omit it and every ORM
  call the module makes under `live_server` — seeding the eight elements, Task 9's `size` re-read —
  raises `SynchronousOnlyOperation`. Do not "tidy" it into a conftest.
- Also required at module top: **`pytestmark = pytest.mark.e2e`** (`test_e2e_depth3.py:44`). The marker
  is applied per module, not by filename: `pyproject.toml:49` sets `addopts = "-q -m 'not e2e'"`, so
  without it this file is deselected under `-m e2e` (the exit-5 "pass" the Global Constraints warn
  about) *and* gets picked up by Task 10's default `uv run pytest`, dragging Playwright and
  `live_server` into the unit run.

**This is the load-bearing row.** The CSS source tests only prove a rule is *present*; only these measure what the browser computes.

- [ ] **Step 1: Set up the media harness**

Copy `_isolated_media` verbatim from `tests/test_e2e_imagezoom.py:56-69` — `autouse=True`,
`(settings, tmp_path)`, assigning `settings.MEDIA_ROOT` — and have the `seeded` fixture (see
Interfaces) depend on it explicitly so it is ordered **before** any asset is created. Seed the two
assets with the house factory, inside `seeded`:

```python
tall = make_image_asset(course, "tall.png", size=(297, 719), color="magenta")
wide = make_image_asset(course, "wide.png", size=(948, 719), color="magenta")
```

`color` is deliberately not the factory's default black — the same reason
`tests/test_e2e_imagezoom.py` gives: black is indistinguishable from the near-black overlay scrim, so
a later occlusion assertion could pass for the wrong reason.

**Copy `_await_decoded` too, and call it on every `<img>` before touching it.** This is the
synchronisation primitive the whole task rests on:
`locator.wait_for()` defaults to `state="visible"`, and an `<img>` whose bytes have not arrived
**still gets a non-empty box from its alt text** — so `naturalWidth` legitimately reads 0 and
`getBoundingClientRect()` returns the alt-text box, not the image.
`tests/test_e2e_imagezoom.py:163-176` records this and its
`test_harness_serves_the_real_fixture_image` works only because `_await_decoded` runs first. Without
it every one of the sixteen box reads races the decode, and the failures wear the *same* `naturalWidth
== 0` signature this plan reserves for the bogus-`MEDIA_ROOT` mutant — indistinguishable at the point
of failure.

Then add the **harness guard** before any measurement, following
`test_harness_serves_the_real_fixture_image`: `_await_decoded` each `<img>`, then assert its
`naturalWidth`/`naturalHeight` equal 297x719 / 948x719. A 404'd image reports 0x0, so this one
assertion distinguishes "the preset is wrong" from "the fixture never loaded" — without it every box
assertion below fails identically and uninformatively. Task 9's nested, zoom and print cases need
`_await_decoded` on their images too.

- [ ] **Step 2: Write the test**

Seed the lesson with **eight image elements — each of the two fixtures at each of the four presets**
(spec: *"One tall + one wide per preset per viewport"*). Not two elements total: with only one image
per preset, whichever fixture you picked decides which axis is measured and the other cap ships
untested.

- tall fixture **297x719** (ratio 0.413), wide fixture **948x719** (ratio 1.319).

**Every test opens with this preamble — logging in is a STEP, not just a listed helper.**
`courses/views.py:651-654` decorates `lesson_unit` with `@login_required` *and* raises
`PermissionDenied` unless `can_access_course(request.user, course)`. A `page.goto(_lesson_url(...))`
without a prior login lands on `/accounts/login/`, so every `img[alt='…']` locator times out with no
hint as to why:

```python
owner, course, unit, tall, wide = seeded
_login(page, live_server, owner.username)
page.set_viewport_size({"width": 1280, "height": 900})   # or 360x640
page.goto(_lesson_url(live_server, unit))
```

**Give each of the eight an identifying `alt`, or they are unaddressable.** `.el--image--small img`
matches two nodes and Playwright raises a strict-mode violation; there is also no other way to pair a
measured node with the preset and fixture the formula needs. Seed them as:

```python
for shape, asset in (("tall", tall), ("wide", wide)):
    for preset in ("small", "medium", "large", "full"):
        el = ImageElement.objects.create(media=asset, alt=f"{shape}-{preset}", size=preset)
        add_element(unit, el)
```

and locate each with `page.locator(f"img[alt='{shape}-{preset}']")` — exactly one node per pair.
Derive `ratio` from that node's own `naturalWidth / naturalHeight` rather than from `shape`, so the
assertion cannot drift from the fixture.

Run the whole set at **1280x900** and again at **360x640**. For each image read
`getBoundingClientRect()` and assert against the **bounding box computed in the test**, so no
per-combination table has to be maintained and no axis has to be guessed:

```
container = fig.parentElement                  # div.lesson-block__body — see below
cw   = parseFloat(getComputedStyle(container).width)   # CONTENT box, at RUNTIME
vh   = page.evaluate("window.innerHeight")             # at RUNTIME, not the number
                                                       # passed to set_viewport_size
wcap = cw * {small:.25, medium:.50, large:.75, full:1.0}
hcap = vh * {small:.30, medium:.45, large:.60, full:1.00}
h    = min(hcap, wcap / ratio, img.naturalHeight)   # the binding axis falls out of the min()
w    = h * ratio
assert abs(rect.height - h) <= 1 and abs(rect.width - w) <= 1
```

**The intrinsic clamp is not decoration.** `max-width`/`max-height` only ever *shrink* — neither
upscales — so a preset whose box is larger than the image renders it at its natural size. Of the
sixteen (fixture × preset × viewport) combinations exactly one is decided this way: **desktop `full`
with the tall fixture**, where wcap 648 and hcap 900 both exceed 297x719, so the browser renders
297x719. Without `img.naturalHeight` in the `min()` the formula predicts 900px tall and the *correct*
implementation fails by 181px — the shape of failure a hurried implementer "fixes" by widening the
tolerance. Read `naturalWidth`/`naturalHeight` at runtime rather than restating 297/948, so the
assertion cannot drift from the fixture.

**Do not hand-compute which axis binds for the other fifteen.** The `min()` decides it, and the
answers are not intuitive — at the phone viewport, for instance, the *tall* fixture is width-bound at
`small` and height-bound at the other three. Every assertion is written against the formula, so no
per-combination table exists to fall out of date.

**Measure `fig.parentElement`, not `.lesson`.** The `<figure>`'s containing block is
`div.lesson-block__body` inside `section.lesson-block` (`templates/courses/_lesson_article.html:38-39`)
— *not* `.lesson`. A `max-width` percentage resolves against the containing block's **content box**,
and `.unit-shell__main > .lesson` carries `padding: 1.25rem 1.5rem` (`courses.css:545-546`), so
measuring `.lesson` gives 696px against a real 648px column — 25% of the wrong number is 174px instead
of 162px, a 12px error that no tolerance would forgive and no reviewer would spot.

**`getComputedStyle(...).width` is *not* the content box in this app** — `reset.css:2` sets
`*, *::before, *::after { box-sizing: border-box }` globally, so the computed `width` of any element
is its **border** box. It is nonetheless the right thing to read here, for a specific reason:
`.lesson-block__body` has **no CSS rule anywhere** in the project, and the nested wrappers Task 9 uses
(`.spoiler__child`, `.callout__child`, `.tabs__child`, `.twocolumn__child`) carry only margins — the
padding lives on their *ancestors* (`.callout`, `.spoiler__children`, `.twocolumn__column`,
`.tabs__panel`). With zero padding and zero border, border box == content box, so the two agree by
accident rather than by rule. **If a future case ever measures a padded element, that equality
breaks** and the test must subtract `paddingLeft/Right` and `borderLeftWidth/RightWidth` explicitly.
Read it **at runtime** — never hardcode 648 or 880 — so the test
keeps testing the preset rather than re-encoding today's shell layout. (For orientation only, never as
literals in the test: the **height** caps are 270/405/540/900px at 1280x900 and 192/288/384/640px at
360x640; the **width** caps are 162/324/486/648px and 74/148/222/296px respectively.)

**Both fixtures are required.** At the desktop viewport the tall image is height-bound at all four
presets (and intrinsic-bound at `full`), so `max-width` is never exercised by it there: shipping
`small` as `35%` would not move one of its pixels. The wide fixture is what makes the width caps
load-bearing.

**On a phone `small` really is ~74px wide, and that is the intended behaviour.** The content column is
296px at a 360px viewport (see Global Constraints — 880/328 was the pre-`.app-main` figure), so the
four percentage **caps** are **74 / 148 / 222 / 296px**. Those are caps, not measurements: which of
the two axes actually binds is the `min()`'s job per fixture and preset, and the answers are not
uniform — at the phone viewport the wide fixture is width-bound at **all four** presets (at `small`
that is a 74x56 thumbnail; even `full` gives `296/1.319 = 224.4 < 640`), while the tall fixture is
width-bound only at `small`. Do not restate the caps as expected widths; let them fall out of the formula.
The spec ships no phone breakpoint and no floor — the presets are uniform percentages at every
viewport by design — so the ~74px thumbnail is *recorded as decided* rather than silently encoded by
whoever writes the test.

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/test_e2e_image_size.py -m e2e --verbosity=0`
Expected: pass. **An exit-5 deselection is a failure, not a pass** — report the verdict line verbatim.

- [ ] **Step 4: Falsify**

Each mutant below states exactly which cases redden — the counts are load-bearing, because a case that
stays green for a *known* reason looks identical to a broken assertion. Work out nothing by hand; the
predictions here are what the `min()` gives.

- **`.el--image--large img` → `max-height: 45dvh`:** the **tall** fixture's `large` cases go RED at
  both viewports. The **wide** fixture's stay **green**, and that is correct: it is width-bound at
  `large` at both sizes (desktop `486/1.319 = 368.5 < 540`; phone `222/1.319 = 168.3 < 384`), so
  lowering `hcap` changes neither `min()`. Restore.
- **`.el--image--large img` → `max-height: 20dvh`** (optional second pass): now *both* fixtures redden
  at both viewports, since 180/128px is below every width-derived height. Use this one if you want a
  single mutant that moves all four `large` cases. Restore.
- **`.el--image--small` → `max-width: 35%`:** the **wide** fixture's `small` case reddens at both
  viewports, **and so does the tall fixture's phone `small` case** — at 360x640 the tall fixture is
  width-bound at `small` (`74/0.413 = 179 < 192`), and 35% lifts it past the height cap
  (`103.6/0.413 = 251 > 192`), moving the predicted height from 179 to 192. Only the tall fixture's
  **desktop** `small` case stays green. Restore.
- **Point `_isolated_media` at a bogus path:** the harness guard goes RED with `naturalWidth == 0`
  **before** any box assertion reports — that is the guard earning its place. Restore.

Re-run and confirm pass.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/test_e2e_image_size.py
uv run ruff format --check tests/test_e2e_image_size.py
git add tests/test_e2e_image_size.py
git commit -m "test(image): e2e bounding boxes for all four presets at two viewports"
```

---

### Task 9: e2e — figure geometry, live preview, print, zoom

**Files:**
- Modify: `tests/test_e2e_image_size.py`

**Interfaces:**
- Consumes: the helpers, the `_isolated_media` fixture and the two image assets from Task 8.

**Centring tolerance, once, for every centring assertion in this task:** `abs(left - right) <= 1`.
Sub-pixel layout makes a bare float `==` flaky, and "roughly equal" left unpinned would hide a real
off-centre bug — the same 1px discipline Task 8's box assertions use.

**Every case in this task runs at 1280x900**, set explicitly with `page.set_viewport_size` exactly as
Task 8 does. Playwright's default page viewport is **1280x720**, not 1280x900, and nothing in
`tests/conftest.py` or the root `conftest.py` overrides it — so an unpinned test silently measures
against a 720px-tall viewport, where the `small` height cap is 216px rather than 270px and the tall
fixture renders ~89px wide rather than ~111.5px. Every orientation figure quoted in this task assumes
1280x900. (The print case in Step 3 restates this because it has a second reason for it.)

- [ ] **Step 0: Seed this task's own fixtures**

Task 8 seeds eight **captionless, top-level** images on one lesson unit. Most of Task 9's cases need
elements Task 8 never creates — a captioned image, an editor-reachable element, four nested children.
Create those explicitly before writing any assertion. Take `owner`, `course`, `unit`, `tall` and
`wide` from Task 8's **`seeded`** fixture (which already depends on `_isolated_media`) — request
`seeded` and unpack it; do not re-seed assets of your own. The two cases that need no new elements say
so in the table.

**Put this seed in a fixture too, for the reason Task 8 gives.** Steps 1-3 are several test functions
— Step 4's falsify table alone names seven distinct assertion groups, and the live-preview and print
cases cannot share one test — so an ~11-element seed written inline would be copy-pasted per test or
stranded as locals. Pin it the same way `seeded` is pinned:

```python
@pytest.fixture
def geom(seeded):
    """(owner, course, geom_unit, preview_unit, nested_joins).

    geom_unit  — rows 1-4 + row 6 (ten images; located by alt)
    preview_unit — row 5 only, so the editor page holds exactly one image row
    nested_joins — {"spoiler": join, "tabs": join, "twocolumn": join, "callout": join},
                   the CONTAINER join rows, so Step 3 can locate each container's
                   wrapper without re-deriving it
    """
```

Consumers: Steps 1, 3 (print, zoom, nested) take `geom_unit`; Step 2 takes `preview_unit`; Step 3's
nested cases take `nested_joins`. Every element is located by its unique `alt`, so no other member
needs to be returned.

| # | for | element | seeded how |
|---|---|---|---|
| 1 | figure-centred (Step 1) | `alt="centred-<preset>"`, one per capped preset, **no caption**, tall fixture | `add_element(unit, …)` — top level |
| 2 | long-caption centring (Step 1) | `alt="captioned"`, `size="small"`, tall fixture, `figcaption` of ~200 chars **made of ordinary spaced words** — e.g. `("a longer caption about the diagram " * 6)[:200]`. Not `"x" * 200`: nothing in this project's CSS sets `overflow-wrap` or `word-break` on a `figcaption`, so an unbroken 200-char token has a min-content contribution of ~1300px, overflows its figure, and gives the whole page a horizontal scrollbar — harmless for this element's own clamped assertion, but a real side effect on the `full`-captioned element (no `max-width`) and on the print, zoom and nested cases sharing the page. The corpus's real captions are 212/200/132 chars of prose | top level |
| 3 | height-bound centring (Step 1) | *reuses* row 1's `centred-small` — same element in every respect (tall fixture, `small`, no caption, top level); the two Step 1 bullets simply measure different boxes on it (figure-inside-parent vs image-inside-figure) | no new element |
| 4 | `full` unchanged (Step 1) | `alt="full-plain"` and `alt="full-captioned"` (~200-char caption), tall fixture, `size="full"` | top level |
| 5 | live preview (Step 2) | `alt="preview-target"`, `size="full"`, wide fixture | a **second unit in the SAME course** — see the warning below |
| 6 | nested (Step 3) | `alt="nested-<container>"`, `size="small"`, wide fixture, one per container | child rows under each of the four containers, on the same unit as rows 1-4 — see Step 3 for each container's creation recipe and `tab_id` |
| 7 | print (Step 3) | reuse rows 1 and 4 — `centred-{small,medium,large}` plus `full-plain` cover all four presets on one page | no new elements |
| 8 | zoom (Step 3) | reuse `centred-small` from row 1 | no new elements |

**Rows 1-4 (and therefore 3, 7 and 8) go on a fresh lesson unit in Task 8's course**, not on Task 8's
eight-image unit — mixing them in would make Task 8's own strict-mode-safe `alt` locators share a page
with six more images for no benefit. (`geom_unit` ends up holding ten images itself: three
`centred-*`, one captioned, two `full`, four nested. That is fine — every assertion locates by a
unique `alt` — but it is *not* "one image per preset", so do not write a locator that assumes it.)
Create it the same way as row 5:

```python
geom_unit = ContentNodeFactory(
    course=course, kind="unit", unit_type="lesson", parent=None, title="Geometry"
)
```

Row 6's four nested cases go on that same `geom_unit`.

**Row 5 must NOT use `_seed_unit`.** `_seed_unit(owner, slug)` (`tests/test_e2e_depth3.py:80-90`)
calls `CourseFactory(...)` — it creates a whole new **Course**, not just a unit. `MediaAsset` is
course-scoped, and `builder.save_element` passes `course=course` for `type_key == "image"`
(`courses/builder.py:953-961`), so `_CourseScopedMediaForm` filters the `media` queryset to the unit's
own course. Seed row 5 in a fresh course and its media (Task 8's `wide`) is absent from the rendered
`<select name="media">`; Step 2's `_save_open_form` then posts a `media` value outside the queryset →
`ElementFormInvalid` → 422 → no fragment swap → **the after-swap case, the only one that distinguishes
a `root`-delegated handler from a pane-bound one, can never pass**. Instead give row 5 its own unit
inside Task 8's course:

```python
preview_unit = ContentNodeFactory(
    course=course, kind="unit", unit_type="lesson", parent=None, title="Preview"
)
```

(`ContentNodeFactory` is what `_seed_unit` itself uses.) A separate *unit* is still worth it — the
editor page then holds exactly one image row — but the *course* must be shared.

- [ ] **Step 1: Add the figure-geometry tests**

- **Figure centred (no caption):** for each capped preset, the `<figure>`'s own box has roughly equal left/right offsets inside its containing block (`fig.parentElement`, i.e. `div.lesson-block__body` — the same element Task 8 measures, never `.lesson`). This is the ONLY coverage of the figure rule — the box tests in Task 8 check dimensions, not position, so they all pass with the figure rule deleted.

  **`div.lesson-block__body` is the parent on the *lesson* page only.** In the editor's preview pane
  each element is wrapped in `<section class="prev-el">` (`templates/courses/manage/editor/_preview.html:16`),
  so `fig.parentElement` there is `.prev-el`. Every geometry measurement in this task stays on the
  lesson page; Step 2's editor-side cases compare **classes only**, never boxes, precisely so this
  difference cannot bite.
- **Image centred under a LONG caption:** with a caption of ~200 characters (the corpus has 212/200/132-char captions), assert the image is centred within the now caption-widened figure. A short caption cannot exercise this. (Seed row 2.)
- **Image centred with NO caption, height-bound — measure first, then decide.** The caption is not the
  only way the figure can end up wider than the image: at 1280x900, `small`, tall fixture, the image
  renders ~111.5px wide because `max-height` binds and shrinks it on both axes. Whether the
  `fit-content` figure then shrink-wraps to that **constrained** width (111.5px) or to the image's
  **unconstrained** max-content contribution (clamped to the 162px preset cap) is engine-dependent —
  Task 5's comment says so, and this is the step that settles it. So do not write the assertion blind:

  1. Read `figure.getBoundingClientRect().width` and `img.getBoundingClientRect().width` and record
     both in the commit message.
  2. **If `figure.width > img.width`** (Chromium shrink-wraps to the unconstrained contribution):
     assert the image's left and right offsets inside the figure are equal. This case is real and
     falsifiable — deleting the img `margin-inline: auto` moves it.
  3. **If they are equal** (Chromium shrink-wraps to the *constrained* contribution): both offsets are
     0 by construction, the assertion would pass vacuously, and no mutant can redden it. **Delete the
     case** and note the measured finding in the commit message. Do not reshape it — no variation
     keeps both defining conditions (no caption, height-bound) while making it falsifiable. **In the
     same commit, delete reason 2 from Task 5's img `margin-inline` comment** — that comment names
     the height-bound path as one of "two independent ways" the figure ends up wider than the image,
     and branch 3 is the measurement disproving it. Leaving it would ship a false mechanism in a
     comment, which this project has a recorded lesson about.

  Branch 2 is the expectation; branch 3 is a legitimate outcome, not a failure. Either way the img
  `margin-inline: auto` rule keeps its captioned-path coverage.
- **`full` geometry unchanged.** "Same as before the feature" is not something a single run can read —
  there is no earlier state to compare against — so state the property as concrete post-conditions
  instead. Assert PC1 and PC2 on `full-plain`, and PC3 on **`full-captioned`** — a caption is what would widen
  the figure past the image, so it is the only element on which PC3 can distinguish "the image is
  flush left" from "the figure is exactly as wide as the image".

  - **PC1:** the figure's rect width equals its containing block's content width (it did **not**
    shrink-wrap: `full` is excluded from the `fit-content` group);
  - **PC2:** the figure's left offset inside `fig.parentElement` is 0 (no `margin-inline: auto`);
  - **PC3:** the image's own left offset inside the figure is 0 — `full` is excluded from the img
    `margin-inline: auto` rule (the `display: block` half of that rule is already global via
    `reset.css:11`, so `margin-inline` is the only thing that would move it).

  Together these are exactly what "byte-identical for the 1013 untouched images" means in layout
  terms. They take **two** mutants, not one, because two different rules guard them — see the
  falsify table.

- [ ] **Step 2: Add the live-preview tests**

- Changing a radio updates the rendered figure's class **with no save**.
- It still works **after a fragment swap**: save once, then change the preset again. This is the seam between a handler on `root` and one bound to a pane; invisible to any server-render test.

Both scope to the **edit-an-existing-element** flow — on the create flow `data-for-element` is `""` and the preview is inertly a no-op.

**The locator chain, since no existing helper covers "open an existing element's edit form".** The
editor page is `_editor_url(live_server, course, unit)`; the rendered figure lives in the **preview**
pane (`editor.html` mounts the student templates there), which is why the JS's unscoped
`document.querySelector('.el--image[data-preview-el=…]')` finds it. Steps:

1. `page.goto(_editor_url(...))`. **No view-mode gesture is needed.** The preview pane is always in
   the DOM — the view toggle
   (`templates/courses/manage/editor/editor.html:88`) only swaps an `is-mode-*` class that *hides* a
   pane — and this step's assertions read `classList`, never boxes, so a hidden pane answers them
   correctly. (If a later case ever measures a box on the editor page it would need
   `page.locator("[data-view='split']").click()` plus a wait for `.editor-grid.is-mode-split`; none
   does today.)
2. Open the element's form: click its row's edit control.
   `templates/courses/manage/editor/_element_row.html` gives two equivalent triggers, both stamped
   `data-form-url="/manage/courses/<slug>/build/element/<pk>/form/"` (the rendered value of
   `{% url 'courses:manage_element_form' … %}` — the *name* never appears in the DOM, same trap as the
   save URL in item 4) **and both carrying `class="el-select"` with the same `data-element-id`** — for a plain image element the ✎ icon button is at `:257` and the row label at
   `:265`. (The file is a five-way `{% if el.content_type.model == … %}` chain and an image falls
   through to the final `{% else %}`; the same two-node pair repeats in every branch — `:54`/`:62` is
   the *tabs* one — so the hazard is structural, not branch-specific.) So `button.el-select[data-element-id="…"]` matches **two** nodes and Playwright
   raises a strict-mode violation. Use the label's own class:
   `button.el-row__label[data-element-id="<Element join pk>"]`. **Note the pk**: this editor-side
   attribute is the `Element` **join-row** pk, unlike `data-for-element` / `data-preview-el`, which are
   `ImageElement` pks. Seed the element and keep both objects.
3. `page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")` — the form mounts into
   `[data-edit-slot]` by fetch (`tests/test_e2e_editor_ws3.py:69` uses exactly this wait).
4. Click a radio: `page.locator("[data-edit-slot] input[data-size-preset][value='small']").click()`.
   Assert the preview figure gained `el--image--small` and lost `el--image--full`.

   **Assert "no save" on REQUESTS, not on a DB read.** Install a recorder before the click and require
   zero matches:

   ```python
   saves = []
   page.on("request", lambda r: saves.append(r.url)
           if r.method == "POST" and "/build/element/save/" in r.url else None)
   ```

   **Filter on the PATH, never the URL name.** `manage_element_save` is the `path(...)` *name*
   (`courses/urls.py:241-245`); the URL itself is `/manage/courses/<slug>/build/element/save/` and
   contains no such substring. A recorder filtered on `manage_element_save` matches nothing and the
   assertion is **vacuously true** — it would stay green even if every radio click fired a save, which
   is precisely the false-green this whole item exists to prevent.

   **Settle before asserting, and prove the filter with a positive control in the same test.**
   `page.on("request", …)` events arrive asynchronously over CDP, so `assert saves == []` taken
   straight off `.click()` samples a window rather than observing a settled state — the identical
   "measure the window, not the event" trap the DB read falls into. Sequence it:

   1. assert the class change first (that is a real barrier: the handler has run);
   2. `assert saves == []`;
   3. **positive control** — now call `_save_open_form(page)`, wait for the fragment swap, and assert
      `len(saves) == 1`.

   Step 3 is what proves the filter string actually matches a real save; without it a recorder watching
   the wrong substring reports zero forever and step 2 is vacuous. It also makes the assertion
   self-checking rather than dependent on remembering to run the mutant.

   Keep the DB re-read only as a secondary check, never as the primary signal.
5. For the after-swap case, save with `_save_open_form(page)` (depth3's helper), wait for the row to
   re-render, re-open the form per steps 2-3, and flip to a different preset. The assertion is the
   same; only the preceding fragment swap differs.

- [ ] **Step 3: Add the print and zoom tests**

- Under `page.emulate_media(media="print")`, the resolved `max-height` is the **mm** value, not the
  `dvh` one. A source scan cannot prove the print rule *wins* the tie.

  `getComputedStyle(img).maxHeight` returns **px, never mm**, so assert the converted value:
  `mm * 96 / 25.4` → **45mm ≈ 170.1px, 75mm ≈ 283.5px, 110mm ≈ 415.7px, 170mm ≈ 642.5px**, tolerance
  1px. Also assert it is *not* the screen value for that preset, so a browser that ignored the print
  block could not pass by coincidence.

  **Run this case at 1280x900 only.** The "not the screen value" guard needs headroom, and at 360x640
  it barely has any: `medium`'s screen value is 45dvh = 288px against a print value of 283.5px — 4.5px
  apart, so one tolerance widening erases the guard entirely. At 1280x900 the closest pair is 170.1 vs
  270px.
- **The zoom overlay is unaffected by the preset**, stated as a measurement rather than a mood. Open a
  `small` image's overlay (the `[data-zoomable]` click path, dialog selector per
  `tests/test_e2e_imagezoom.py`) and assert: (a) the overlay image carries **no** `el--image--*` class
  and has no `.el--image` ancestor — `imagezoom.js` `build()` creates a fresh
  `img.imgzoom__img` appended to `document.body`, so this pins the *structural* reason the presets
  cannot reach it; and (b) the overlay image's rendered height is **greater than** the in-page
  figure's height.

  Do **not** phrase (a) as "the computed `max-height` is not the preset's `dvh` value": that is a
  tautology no mutant can break, because `courses.css:1771` gives `.imgzoom__img { max-height: 100% }`
  at (0,1,0), which beats any `dialog img`-style rule at (0,0,2) regardless of source order. (b) is
  what a real mutant moves — see the falsify table.
- A nested image scales to its container — one case each for **spoiler, tabs, two-column and callout**.

  **Split the two axes; only `wcap` is container-relative.** `max-width` is a percentage of the
  *containing block*, so `cw = parseFloat(getComputedStyle(fig.parentElement).width)` — the figure's
  actual parent, which here is the per-child wrapper (`.spoiler__child`, `.callout__child`,
  `.tabs__child`, `.twocolumn__child`). Those wrappers carry only margins — the padding sits on their
  ancestors — so under the app's global `border-box` their computed `width` still equals their content
  width, exactly as Task 8 explains for `.lesson-block__body`. Measure the **wrapper**, never the
  padded container above it.
  `max-height` is authored in `dvh`, which resolves against the **viewport** at every nesting depth, so
  `hcap` stays `vh * fraction` exactly as at top level — it does **not** shrink with the container.
  A test written as "scales to its container, not the page" on both axes asserts a false invariant.

  **Then use Task 8's formula unchanged** — one height assertion, not two:
  `h = min(hcap, wcap / ratio, naturalHeight)`, `w = h * ratio`. Do **not** additionally assert
  `height == vh * fraction`: that is only true when the height axis binds, and inside a nesting
  container it essentially never does. With Step 0 row 6's parameters (wide fixture, ratio 1.319,
  `small`) the height would bind only if `0.25 × cw / 1.319 > 0.30 × 900`, i.e. `cw > ~1424px` — wider
  than the entire 648px column. The container-relative `wcap` inside the `min()` is what carries the
  "scales to its container" claim; the un-shrunk `hcap` is what carries the `dvh` claim.

  **The four containers do not share one seeding recipe.** Global Constraints gives
  `tab_id=<Parent>.SLOT_ID`, which only exists for the **single-slot** containers — `SpoilerElement`
  and `CalloutElement` both set `SLOT_ID = SINGLE_SLOT_ID` (`"only"`, `models.py:402,413,469`), so
  `SpoilerElement.objects.create(label="s")` / `CalloutElement.objects.create(kind="note")` is the
  whole recipe.

  The other two key their children on a **generated** id, and must be created **with
  `default_data()`** — this is not optional:

  ```python
  tabs   = TabsElement.objects.create(data=TabsElement.default_data())
  twocol = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
  tab_id = tabs.data["tabs"][0]["id"]
  col_id = twocol.data["columns"][0]["id"]
  ```

  - `data` is `JSONField(default=dict)` and `save()` runs the **non-destructive** normalizer
    (`normalize_labels_and_ids` / `normalize_ids`, `models.py:1412+, 1537+`), which maps `{}` to
    `{"tabs": []}` / `{"columns": []}`. So a bare `TabsElement.objects.create()` gives an **empty**
    list and `data["tabs"][0]` raises `IndexError`.
  - Hardcoding a slot id is worse than useless: `resolved_tabs()` / `resolved_columns()` render
    through the **destructive** `normalize_data`, which pads an empty list by minting *brand-new* ids
    at read time — the child's `tab_id` then matches nothing and is silently skipped, so the image
    never appears on the page and the test fails with an empty locator rather than a wrong number.
  - Read the id off the **saved** instance (the normalizer ran in `save()`), and never call
    `normalize_data` yourself.
  - Note the shape: `default_data()` returns a list of **dicts**
    (`{"columns": [{"id": …}, {"id": …}]}`, `models.py:1530-1534`), so `data["columns"][0]` alone
    would write a stringified dict into `Element.tab_id` (`CharField(max_length=12)`) and orphan the
    child. The `["id"]` is load-bearing.

  **Two of the four containers hide their contents until acted on**, and a hidden box measures zero:
  a closed `<details>` hides via `content-visibility` (so `getBoundingClientRect()` returns zeros and
  even `offsetParent` checks mislead), and an inactive tab panel has no layout box at all. Open the
  spoiler and activate the tab first, then wait on `img.checkVisibility()` before measuring — never a
  sleep.

- [ ] **Step 4: Run, falsify, lint, commit**

Run the file with `-m e2e`. Falsify each — one named mutant per assertion group, including the two
added in Step 3, which the Global Constraint requires just as much as the older ones:

| assertion group | mutant | expected RED |
|---|---|---|
| figure centred | delete the figure `margin-inline: auto` | figure-centred cases |
| long caption | delete the img `margin-inline: auto` | the long-caption case, **and** the no-caption height-bound one *if Step 1 branch 2 applied* (i.e. if it was kept at all). If the height-bound case was kept and does **not** redden, it is not really measuring the image's offset — that means branch 3 was the true outcome and the case should have been deleted |
| `full` unchanged (figure) | add `.el--image--full` to the **figure** `width: fit-content; margin-inline: auto` group | PC1 and PC2 RED (the figure shrink-wraps and gains auto margins). **PC3 stays green**, for a known reason — and note the reason is about `full-captioned`, the element PC3 is measured on, not `full-plain`: the ~200-char caption's max-content contribution exceeds the 648px column, so `fit-content` still resolves to the full column width and the image's offset inside it remains 0 |
| `full` unchanged (image) | add `.el--image--full img` to the **img** `margin-inline: auto` group | PC3 RED; PC1 and PC2 green. PC3 is guarded only by this second rule, so without this mutant it ships unfalsified |
| print | move the print block above the presets | the print case |
| live preview | rebind the JS handler to the **editor** pane: `root.querySelector('[data-scope="editor"]').addEventListener("change", …)` | the after-swap case only — the before-swap one stays **green**, and that contrast is the whole point. Do **not** use the *preview* pane as the mutant: `_editor_scope.html:2-3` and `_preview.html:2` are **siblings** inside `.editor-grid`, so a radio's `change` bubbles editor-pane → `.editor` → document and never enters the preview pane at all; that mutant reddens *both* cases and proves nothing. The editor pane is the right one because `applyFragments` (`editor.js:92-96`) `replaceWith`s exactly that node |
| no-save recorder | make the radio branch also click the form's submit button | the zero-saves assertion. Run this one: a recorder filtered on the wrong string passes the happy path *and* this mutant, and that is the only way to tell |
| zoom overlay | change `.imgzoom__img`'s own `max-height: 100%` (`courses.css:1771`) to **`10dvh`** | assertion (b), the overlay-taller-than-figure one. Not `30dvh`: at 1280x900 the `centred-small` image is already 270px tall (30dvh binds), so a 30dvh overlay cap ties exactly and the mutant reddens only on a strict `>` with zero margin — any rounding or tolerance flips it green. 10dvh (90px) is unambiguously shorter. Assertion (b) must be a strict `>` with no tolerance |
| nested containers, width axis | change `small`'s `max-width` (25% → 35%) | all four nested cases. Both the width **and** the height assertion redden together, because the nested cases are width-bound and `h` is derived from `wcap` — that coupling is expected, not a bug |
| nested containers, height axis | change `.el--image--small img`'s `max-height` (30dvh → 5dvh) | all four nested cases again — this is the mutant that proves `hcap` is still viewport-derived rather than silently shrunk to the container: at 5dvh (45px) the height axis binds even inside a nested container, which no container-relative `hcap` would reproduce |

Restore each and re-run.

```bash
uv run ruff check tests/test_e2e_image_size.py
uv run ruff format --check tests/test_e2e_image_size.py
git add tests/test_e2e_image_size.py
# Branch 3 of Step 1 ONLY — it edits the CSS comment, and nothing else in this plan
# ever stages courses.css again, so omitting this leaves the mandated correction
# uncommitted in the working tree. Under branch 2 the file is deliberately untouched.
git add courses/static/courses/css/courses.css   # if and only if branch 3 applied

git commit -F - <<'MSG'
test(image): e2e figure geometry, live preview, print and zoom

fit-content measurement (Step 1, 1280x900, small, tall fixture):
  figure width: <measured>px
  image  width: <measured>px
  -> branch <2|3>: Chromium shrink-wraps to the <unconstrained|constrained> contribution
  <under branch 3: reason 2 deleted from the Task 5 img margin-inline comment>
MSG
```

The body is not decoration: that measurement is the one piece of engine-dependent evidence this slice
produces, and Step 1 asks for it to be recorded. A bare `-m` subject has nowhere to put it.

---

### Task 10: Author documentation and final verification

**Files:**
- Modify: `docs/help/course-admin/content-editors.md` and `.pl.md`
- Modify: `docs/help/course-admin/interactive-elements.md` and `.pl.md`

**Interfaces:** none.

**Both languages must agree.** Match the surrounding Polish tone; do not machine-translate loosely, and never leave the Polish file describing the old behaviour.

- [ ] **Step 1: Document the control**

Describe the four presets as bounding boxes ("the image scales to fit inside a box this big, keeping its shape"), that `full` is the default and matches today, and that a picture is never taller than the reader's screen. Do not describe alignment or text-wrap — neither exists.

- [ ] **Step 2: Regenerate the catalogs**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

`makemessages` fuzzy-prefills WRONG translations on this repo — clearing one is TWO deletions (the flag line and the bogus `msgstr`). Clear every one before continuing.

- [ ] **Step 3: Write the five Polish translations**

Clearing a fuzzy flag leaves an **empty** `msgstr`, which passes both greps above and compiles
without complaint — and ships English to Polish readers. This slice adds five catalog entries, of
which **four are new bare msgids and one is context-qualified**:

| entry | Polish |
|---|---|
| `msgid "Size"` | `Rozmiar` |
| `msgid "Small"` | `Mały` |
| `msgid "Medium"` | `Średni` |
| `msgid "Large"` | `Duży` |
| `msgctxt "image size"` + `msgid "Full"` | `Pełny` |

The four size labels describe an *obraz* (masculine), hence the masculine forms.

**Do not touch the existing bare `msgid "Full"` / `msgstr "Pełna"` at
`locale/pl/LC_MESSAGES/django.po:690-692`.** That entry belongs to `courses/forms.py:166`'s
structure-preset label and its feminine form is correct there. Task 1's `pgettext_lazy("image size",
"Full")` is what makes the image label a *separate* entry (`msgctxt "image size"`) rather than a
collision; if `makemessages` produces no `msgctxt` entry, the model is still using plain `_()` — fix
that in `courses/models.py` before continuing. Verify explicitly: `grep -c 'msgstr "Pełna"'` is
unchanged, and the new `msgctxt "image size"` block exists with a non-empty `msgstr`.

Then run the catalog guard — **this repo already owns it, so do not hand-roll greps**:

```bash
uv run pytest tests/test_i18n_po_health.py --verbosity=0
```

`test_no_fuzzy_entries`, `test_no_obsolete_entries` and `test_pl_has_no_untranslated_msgid` are
exactly the three checks this step needs, and the third is one a `grep` **cannot** perform: a cleared
fuzzy flag leaves an *empty* `msgstr`, which no `#, fuzzy` / `^#~` scan can see. It parses
continuation lines and plural forms and prints the offending msgids. Task 10 step 4's full-suite run
would reach it eventually, but four steps later — run it here, where a red is cheapest to act on.

Only once it is green, run `uv run python manage.py compilemessages`.

- [ ] **Step 4: Full verification**

Run each in the FOREGROUND and report the verbatim verdict line:

```bash
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
uv run ruff check . && uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
```

If any is red, report it honestly with the failing test names. Do not fix unrelated pre-existing failures.

- [ ] **Step 5: Commit**

```bash
git add docs/help/course-admin/ locale/
git commit -m "docs(image): document the size presets"
```

---

## Self-Review

**Spec coverage.** §1 model → Task 1. §2 rendering → Task 3. §3 CSS incl. figure box and print → Tasks 5, 6. §4a form → Task 2. §4b/§4c control → Task 2 (including the `.size-presets` chrome, so the control ships styled). §5 live preview → Tasks 7, 9. §6 zoom → Task 9. §7 transfer → Task 4. Error handling → Task 4 (steps 4, 9). Testing rows 1-19 → rows 1 (T1), 2/3/3b (T3 steps 1-3), 3c (T3 step 4), 4-7 (T4), 8 (T8), 9/10 (T9), 11/12 (T9), 13/13b (T6, T9), 14/15 (T2 step 5 — both halves of 15: the stored preset AND an unbound form's `full`), 16 (T2 step 1, as the pair `test_a_post_that_omits_size_is_rejected` + `test_an_alt_only_edit_still_saves`), 17/18/19 (T9). No spec requirement is unassigned.

**Placeholder scan.** No "TBD"/"similar to Task N"/"add appropriate error handling". Task 5's and Task 6's CSS, Task 2's `.size-presets` CSS, Task 4's transfer code, Task 7's JS branch and Task 2's template are given in full. Every test fixture and helper is written inline in the task that needs it — no test references a fixture no step defines, and `courses/tests/` gains no `conftest.py`. Tasks 8-10 describe assertions rather than pasting whole e2e bodies, because the fixture helpers are copied verbatim from a named existing file — the values (viewports, fixture dimensions, the eight-element seed, the binding formula, caption length, tolerances, the mm→px conversions) are all pinned explicitly.

**Type consistency.** `ImageElement.Size` / `.size` / `Size.values` used identically in Tasks 1, 2, 4. Attribute names are consistent throughout: `data-preview-el` on the figure (never `data-element-id`), `data-size-preset` and `data-for-element` on the radios. Class names are `el--image--{small,medium,large,full}` everywhere.

**The two pk namespaces, stated once.** `data-preview-el` (Task 3) and `data-for-element` (Task 2) both carry the **`ImageElement`** pk — that is what makes Task 7's `querySelector` match. `_seen_current_ids` (Task 3, step 4) deals in **`Element` join-row** pks, a different namespace; no test conflates them, and no test treats an `ImageElement` as if it had `unit` or `content_object` (those are `Element` fields).

**Blast radius outside this slice.** Widening `ImageElementForm.Meta.fields` and rewriting `imageelement.html`'s root tag are re-verified against the existing suites in Task 2 step 7 and Task 3 step 5; bumping `FORMAT_VERSION` invalidates five existing assertions, all re-pinned in Task 4 step 7; duplicate-and-paste is pinned in Task 4 step 8. The one shared-namespace hazard is the msgid `"Full"`, already owned by `courses/forms.py:166` with a feminine Polish translation — Task 1 forks it with `pgettext_lazy("image size", …)` and Task 10 step 3 requires the existing `msgstr "Pełna"` to be left untouched. The migration is generated as `0054_imageelement_size` but staged via `git add courses/migrations/`, so a different number cannot break the commit.

**Measurement discipline in the two e2e tasks.** Four facts that would each silently corrupt a box
assertion are stated once and referenced from both tasks: caps only *shrink*, so the `min()` carries
`img.naturalHeight` (desktop-`full`-tall is the single case it decides); the real content column is
648/296px, not the spec's 880/328, because `.app-main` caps and pads the page outside `.unit-shell`;
a `max-width` percentage resolves against the **content box** of `fig.parentElement`
(`div.lesson-block__body` on the lesson page, `section.prev-el` in the editor preview), never
`.lesson` — and because `reset.css:2` makes every box `border-box`, `getComputedStyle().width` is only
equal to that content box because those particular wrappers have zero padding and border, which the
tasks state rather than assume; and `dvh` resolves against the viewport at every nesting depth, so only the
width axis is container-relative. No expected pixel value is written as a literal — every one is
derived from the formula at runtime. The fixtures are real PNGs via `make_image_asset`, served through
the mandatory `_isolated_media` redirect, with a `naturalWidth`/`naturalHeight` harness guard so "the
fixture never loaded" can never masquerade as "the preset is wrong"; and the module carries both
`pytestmark = pytest.mark.e2e` and the module-local `_allow_sync_orm_under_playwright`, without which
it would silently deselect or raise `SynchronousOnlyOperation`.
