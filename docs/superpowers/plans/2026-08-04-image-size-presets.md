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
- **The real content column is 880px desktop / 328px phone**, derived from the shell (`.unit-shell` 72rem − `.unit-tree` 14rem − `.lesson` padding 3rem). **Not** `.lesson`'s nominal 46rem — `.unit-shell__main > .lesson` overrides it to `max-width: none` at `courses.css:545-546`.
- **Pinned e2e viewports:** desktop **1280x900**, phone **360x640**.
- **Pinned fixtures:** tall **297x719**, wide **948x719** (both real images from unit 1095).
- **Token-driven CSS** — no hardcoded colours; use existing custom properties. `core/static/core/css/app.css` is GLOBAL.
- **Django multi-line comments** use `{% comment %}`; `{# #}` must be single-line.
- **Module-level translatable strings** must use `gettext_lazy`.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **Never create `courses/tests/__init__.py`** — it renames every module under that directory.
- **Fixtures live inline, per module.** `courses/tests/` has **no `conftest.py`** and this slice does
  **not** add one: `tests/conftest.py` (which holds `_enable_db_access`, `course`, `image_asset`)
  applies only to the `tests/` subtree and is invisible from `courses/tests/`, and the root
  `conftest.py` defines exactly one fixture (`_reset_active_language`). Every fixture a
  `courses/tests/` module needs is written **in that module**, matching the house style
  (`test_question_restore.py`'s local `_image(course)` helper, `test_callout_nesting.py`'s local
  `_top_callout`). Shared *helpers* come from `tests.factories` — `make_course_with_unit`,
  `add_element`, `TEST_PASSWORD` — which import fine from anywhere.
- **A `MediaAsset` of kind `image`** is built as
  `MediaAsset.objects.create(course=course, kind="image", file="courses/media/x.png",
  original_filename="x.png")` (the `test_question_restore.py:364-370` pattern). No real file is
  needed — nothing in this slice reads the bytes.
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
    el = ImageElement(size="enormous")
    with pytest.raises(ValidationError):
        el.full_clean(exclude=["media"])
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
        FULL = "full", _("Full")
```

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

Change the field's `default=Size.FULL` to `default=Size.SMALL`; confirm `test_size_defaults_to_full` goes RED. Restore. Remove `"large"` from the choices; confirm `test_size_choices_are_the_four_presets` goes RED. Restore, re-run, confirm 3 passed.

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

import pytest

from courses.element_forms import ImageElementForm
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


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
and this project has no global `fieldset`/`legend` rule (only `.analytics__export-form fieldset` at
`app.css:789-794` and `.roster > legend` at `:188`, both scoped elsewhere). "Every view ships styled"
is a standing project rule. The editor's other `.el-editor__*` chrome lives in
`core/static/core/css/app.css` (see `.el-editor__option-row` at `:1222`), so put it there, beside it:

```css
/* The image size preset control. No global fieldset/legend rule exists, so without
   this the radios ship with the UA border and zero spacing next to the flat
   .el-editor labels above them. Tokens only — no literal colours. */
.size-presets {
  border: 1px solid var(--border);
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

Confirm every custom property used here already exists in the token block (`app.css` `:root`); if one
does not, substitute the nearest that does rather than inventing a name.

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
`test_the_create_flow_renders_an_empty_for_element` goes RED with `data-for-element="None"`. Restore,
re-run, confirm all pass.

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
fixtures**, with one fixed signature each: `make_image(size) -> ImageElement` (saved, so `pk` is real)
and `render(el, *, element=None) -> str`. There is no `with_element` kwarg — the caller already holds
the element it built.

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


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


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
def test_archive_with_a_junk_size_imports_as_full(image_media):
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

`courses/transfer/payloads.py`, in `_val_image`, **before** the `_exact_keys` call:

```python
    from courses.models import ImageElement

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
| `tests/test_link_transfer.py` | 54 | `assert FORMAT_VERSION == 6` → `== 7` |
| `tests/test_tabs_transfer.py` | 58 | `assert FORMAT_VERSION == 6` → `== 7` |
| `tests/test_transfer_export.py` | 220 | `assert manifest["format_version"] == 6` → `== 7` |
| `tests/test_transfer_export.py` | 76 | `assert data == {"media": "m1", "alt": "a", "figcaption": "c"}` → add `"size": "full"` |
| `tests/test_table_transfer.py` | 265 | comment `4 <= FORMAT_VERSION=6` → `=7` (prose only) |

Re-grep before editing (`grep -rn "FORMAT_VERSION == 6\|format_version\"\] == 6" tests courses`) in
case another lands on `master` first; the line numbers are a convenience, the grep is the authority.

- [ ] **Step 8: Run tests to verify they pass**

Run:

```bash
uv run pytest courses/tests/test_image_size_transfer.py tests/test_transfer_export.py \
  tests/test_transfer_import.py tests/test_transfer_schema.py tests/test_link_transfer.py \
  tests/test_tabs_transfer.py tests/test_table_transfer.py --verbosity=0
```

Expected: all pass. (Before Step 7 they do **not** — five assertions are red by construction. That is
the point of Step 7, not a surprise.)

- [ ] **Step 9: Falsify**

Delete the `data.setdefault("size", "full")` line; confirm `test_archive_without_a_size_key_imports_as_full` goes RED — the observed error is **`KeyError: 'size'`** raised by the very next line (`if data["size"] not in …`), *not* an exact-keys `TransferError`, because that line runs before `_exact_keys` is reached. To see the exact-keys path instead, delete the `setdefault` **and** the whole junk-value block: then `_exact_keys` rejects the legacy payload with a `TransferError`. Restore. Delete only the junk-value coercion; confirm `test_archive_with_a_junk_size_imports_as_full` goes RED. Restore. Drop `"size"` from `_ser_image`; confirm the round-trip cases go RED. Restore, re-run, confirm all pass.

- [ ] **Step 10: Lint and commit**

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
- the `fit-content` + `margin-inline:\s*auto` group **matches** small, medium and large, and the block
  containing it does **not** mention `.el--image--full`;
- the `img { display: block; margin-inline: auto }` group likewise covers the three capped presets and
  not `full`.

Also assert `.el--image img { max-width: 100%; height: auto; }` is still present unchanged — Task 5
retains it, and nothing else in this slice would notice its removal.

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

/* Centre the image WITHIN the figure. Load-bearing whenever a figcaption exists:
   fit-content sizes the figure to the WIDER of {image, caption} max-content
   contributions, so a long caption widens the figure past the image and the image
   would otherwise sit flush left. Scoped to the capped presets so `full` keeps
   today's flush-left geometry — 1013 images must render byte-identically. */
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

Delete the `.el--image--medium img { max-height: 45dvh }` line; confirm the medium height assertion goes RED. Restore. Add `.el--image--full` to the `fit-content` group; confirm the "full is excluded" assertion goes RED. Restore, re-run, confirm all pass.

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

Extend `courses/tests/test_image_size_css.py` with a `_print_block(css)` helper that regex-extracts the `@media print` block **in isolation** (a file-wide scan passes while the print block is empty, because the selectors also appear in the screen rules), then asserts all four `mm` values inside it. Add a second test asserting the print block's start index is greater than the index of `.el--image--full img`.

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

**Extend the existing handler; do not add a second listener.** `editor.js:3` establishes `var root = document.querySelector(".editor")` and `:462` already delegates `change`. `.editor` (`editor.html:11`) wraps both `[data-scope]` panes, and `applyFragments` replaces those panes wholesale — so anything bound *inside* a pane dies on the next swap, while a delegated handler on `root` survives.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_image_size_js.py` asserting the source of `editor.js` contains `data-size-preset` and `data-preview-el`, and that it does NOT contain a second `addEventListener("change"` bound to anything other than `root`. (A source scan is weak; the behaviour is pinned by Task 9's e2e.)

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

Delete the branch; confirm the source scan goes RED. Restore.

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
- Produces: `_make_pa_user` / `_login` / `_lesson_url` helpers copied **verbatim** from `tests/test_e2e_depth3.py` (they close over `TEST_PASSWORD` and `make_verified_user`), reused by Task 9.

**This is the load-bearing row.** The CSS source tests only prove a rule is *present*; only these measure what the browser computes.

- [ ] **Step 1: Write the test**

Seed the lesson with **eight image elements — each of the two fixtures at each of the four presets**
(spec: *"One tall + one wide per preset per viewport"*). Not two elements total: with only one image
per preset, whichever fixture you picked decides which axis is measured and the other cap ships
untested.

- tall fixture **297x719** (ratio 0.413), wide fixture **948x719** (ratio 1.319).

Run the whole set at **1280x900** and again at **360x640**. For each image read
`getBoundingClientRect()` and assert against the **bounding box computed in the test**, so no
per-combination table has to be maintained and no axis has to be guessed:

```
cw   = container.getBoundingClientRect().width      # read at RUNTIME, never hardcoded
vh   = viewport height
wcap = cw * {small:.25, medium:.50, large:.75, full:1.0}
hcap = vh * {small:.30, medium:.45, large:.60, full:1.00}
h    = min(hcap, wcap / ratio)      # the binding axis falls out of the min()
w    = h * ratio
assert abs(rect.height - h) <= 1 and abs(rect.width - w) <= 1
```

Read the container width **at runtime** — never hardcode 736 or 880 — so the test keeps testing the
preset rather than re-encoding today's shell layout. (For orientation only, not as literals in the
test: at 1280x900 the caps are 270/405/540/900px tall; at 360x640 they are 192/288/384/640px tall,
which is what the spec pins.)

**Both fixtures are required.** For the tall image the height cap binds at every preset, so
`max-width` is never exercised: shipping `small` as `35%` would not move a pixel. The wide fixture is
the only one that binds on width.

**On a phone `small` really is ~82px wide, and that is the intended behaviour.** The content column is
328px at a 360px viewport, so the four percentage caps give **82 / 164 / 246 / 328px**; for the wide
fixture the width cap binds at `small` and `medium`, producing an 82x62 thumbnail. The spec ships no
phone breakpoint and no floor — the presets are uniform percentages at every viewport by design.
Assert these phone widths explicitly (they fall out of the formula above; no extra literals needed),
so the number is *recorded as decided* rather than silently encoded by whoever writes the test.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_e2e_image_size.py -m e2e --verbosity=0`
Expected: pass. **An exit-5 deselection is a failure, not a pass** — report the verdict line verbatim.

- [ ] **Step 3: Falsify**

Change `.el--image--large img` to `max-height: 45dvh`; confirm the large cases go RED at both viewports. Restore. Change `.el--image--small` to `max-width: 35%`; confirm the **wide** fixture's small case goes RED (and note that the tall fixture stays green — that is why both exist). Restore, re-run, confirm pass.

- [ ] **Step 4: Lint and commit**

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
- Consumes: the helpers from Task 8.

- [ ] **Step 1: Add the figure-geometry tests**

- **Figure centred (no caption):** for each capped preset, the `<figure>`'s own box has roughly equal left/right offsets inside `.lesson`. This is the ONLY coverage of the figure rule — the box tests in Task 8 check dimensions, not position, so they all pass with the figure rule deleted.
- **Image centred under a LONG caption:** with a caption of ~200 characters (the corpus has 212/200/132-char captions), assert the image is centred within the now caption-widened figure. A short caption cannot exercise this.
- **`full` geometry unchanged:** same box and offset as before the feature — the guard on the byte-identical promise for the 1013 untouched images.

- [ ] **Step 2: Add the live-preview tests**

- Changing a radio updates the rendered figure's class **with no save**.
- It still works **after a fragment swap**: save once, then change the preset again. This is the seam between a handler on `root` and one bound to a pane; invisible to any server-render test.

Both scope to the **edit-an-existing-element** flow — on the create flow `data-for-element` is `""` and the preview is inertly a no-op.

- [ ] **Step 3: Add the print and zoom tests**

- Under `page.emulate_media(media="print")`, the resolved `max-height` is the **mm** value, not the
  `dvh` one. A source scan cannot prove the print rule *wins* the tie.

  `getComputedStyle(img).maxHeight` returns **px, never mm**, so assert the converted value:
  `mm * 96 / 25.4` → **45mm ≈ 170.1px, 75mm ≈ 283.5px, 110mm ≈ 415.7px, 170mm ≈ 642.5px**, tolerance
  1px. Also assert it is *not* the screen value for that preset, so a browser that ignored the print
  block could not pass by coincidence.
- The zoom overlay shows the image unaffected by the preset.
- A nested image scales to its container — one case each for **spoiler, tabs, two-column and callout**.

  **Split the two axes; only width is container-relative.** `max-width` is a percentage of the
  *containing block*, so the width assertion is `container.getBoundingClientRect().width * fraction`.
  `max-height` is authored in `dvh`, which resolves against the **viewport** at every nesting depth —
  so the height assertion stays `viewport height * dvh fraction`, exactly as at top level. A test
  written as "scales to its container, not the page" on both axes asserts a false invariant and will
  fail for the wrong reason.

  **Two of the four containers hide their contents until acted on**, and a hidden box measures zero:
  a closed `<details>` hides via `content-visibility` (so `getBoundingClientRect()` returns zeros and
  even `offsetParent` checks mislead), and an inactive tab panel has no layout box at all. Open the
  spoiler and activate the tab first, then wait on `img.checkVisibility()` before measuring — never a
  sleep.

- [ ] **Step 4: Run, falsify, lint, commit**

Run the file with `-m e2e`. Falsify each: delete the figure `margin-inline: auto` (figure-centred goes RED); delete the img `margin-inline: auto` (long-caption case goes RED); move the print block above the presets (print case goes RED); rebind the JS handler to the preview pane instead of `root` (the after-swap case goes RED, the before-swap one stays green). Restore each and re-run.

```bash
uv run ruff check tests/test_e2e_image_size.py
uv run ruff format --check tests/test_e2e_image_size.py
git add tests/test_e2e_image_size.py
git commit -m "test(image): e2e figure geometry, live preview, print and zoom"
```

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

Then inspect: `grep -c '#, fuzzy'` and `grep -c '^#~'` must both be **0** in both `.po` files. `makemessages` fuzzy-prefills WRONG translations on this repo — clearing one is TWO deletions (the flag line and the bogus `msgstr`).

- [ ] **Step 3: Write the five Polish translations**

Clearing a fuzzy flag leaves an **empty** `msgstr`, which passes both greps above and compiles
without complaint — and ships English to Polish readers. This slice introduces exactly five msgids:
`"Size"`, `"Small"`, `"Medium"`, `"Large"`, `"Full"`. Fill each in
`locale/pl/LC_MESSAGES/django.po` (`Rozmiar`, `Mały`, `Średni`, `Duży`, `Pełny` — check the
surrounding entries and match their register; the four size labels describe an image, so keep the
masculine form agreeing with *obraz*).

Then verify none is left blank — for each of the five msgids the following `msgstr` must be
non-empty — and only then run `uv run python manage.py compilemessages`.

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

**Blast radius outside this slice.** Widening `ImageElementForm.Meta.fields` and rewriting `imageelement.html`'s root tag are re-verified against the existing suites in Task 2 step 7 and Task 3 step 5; bumping `FORMAT_VERSION` invalidates five existing assertions, all re-pinned in Task 4 step 7. The migration is generated as `0054_imageelement_size` but staged via `git add courses/migrations/`, so a different number cannot break the commit.
