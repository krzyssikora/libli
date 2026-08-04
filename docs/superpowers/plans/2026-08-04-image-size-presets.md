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
- **`makemigrations --check --dry-run` must stay clean** (CI guards this since #204).
- **A passing test proves nothing** — for every test, delete the code it guards and confirm it goes RED before moving on. Name the mutant.
- **Lint at the task that introduces the code.** `ruff` runs `select = ["E","F","I","UP","B","S"]` at line-length 88, with `[tool.ruff.lint.isort] force-single-line = true` (so a combined `from x import A, B` must be split one-per-line). Every task's test step must also run `uv run ruff check <files touched>` and `uv run ruff format --check <same>`.

## File Structure

| File | Responsibility in this slice |
|---|---|
| `courses/models.py` | `ImageElement.Size` TextChoices + the `size` field |
| `courses/migrations/00NN_imageelement_size.py` | schema migration, `default="full"`, no data migration |
| `courses/element_forms.py` | `ImageElementForm.Meta.fields` gains `"size"` |
| `templates/courses/elements/imageelement.html` | preset class + `data-preview-el` on the `<figure>` |
| `templates/courses/manage/editor/_edit_image.html` | fieldset/legend + four radios with checked reflection |
| `courses/static/courses/css/courses.css` | four bounding boxes, figure box rules, print block |
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
- Create: `courses/migrations/00NN_imageelement_size.py` (via `makemigrations`)
- Test: `courses/tests/test_image_size_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ImageElement.Size` (nested `TextChoices` with values `"small"`, `"medium"`, `"large"`, `"full"`), `ImageElement.Size.values`, and the field `ImageElement.size` (`CharField`, `max_length=8`, `default=Size.FULL`).

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
git add courses/models.py courses/migrations/00NN_imageelement_size.py courses/tests/test_image_size_model.py
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
import pytest
from django.urls import reverse

from courses.element_forms import ImageElementForm
from courses.models import ImageElement

pytestmark = pytest.mark.django_db


def test_form_accepts_the_size_field():
    assert "size" in ImageElementForm.Meta.fields


def test_form_saves_a_chosen_size(image_media):
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "a", "figcaption": "", "size": "medium"},
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert form.save().size == "medium"


def test_an_alt_only_edit_still_saves(image_media):
    """The required-ChoiceField trap: a POST that omits `size` must not 400."""
    el = ImageElement.objects.create(media=image_media, alt="before", size="large")
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "after", "figcaption": "", "size": "large"},
        instance=el,
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert form.save().alt == "after"
```

Add the `image_media` fixture at the top of the file (a `MediaAsset` of kind `image` in a course), following the pattern in `tests/test_media_model.py`.

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
     form.fields.size.choices keeps the four presets from being duplicated here.{% endcomment %}
  <fieldset class="size-presets">
    <legend>{% trans "Size" %}</legend>
    {% for value, label in form.fields.size.choices %}
      <label><input type="radio" name="size" value="{{ value }}"
        {% if form.size.value|stringformat:"s" == value|stringformat:"s" %} checked{% endif %}
        data-size-preset data-for-element="{{ form.instance.pk }}"> {{ label }}</label>
    {% endfor %}
  </fieldset>
```

- [ ] **Step 5: Add the template assertions**

Append to `courses/tests/test_image_size_editor.py`:

```python
def test_editor_renders_four_radios_with_the_stored_one_checked(client, pa_user, image_el):
    client.force_login(pa_user)
    url = reverse("courses:manage_element_edit", args=[image_el.unit.course.slug, image_el.pk])
    html = client.get(url).content.decode()
    for value in ("small", "medium", "large", "full"):
        assert f'value="{value}"' in html
    assert 'data-size-preset' in html
    assert f'data-for-element="{image_el.content_object.pk}"' in html
    assert '<legend>' in html
```

Build `image_el` as an `ImageElement` stored with `size="large"` and assert its radio is the checked one.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_editor.py --verbosity=0`
Expected: all pass.

- [ ] **Step 7: Falsify**

Remove `"size"` from `Meta.fields`; confirm `test_form_saves_a_chosen_size` goes RED. Restore. Delete the `{% if %}…checked{% endif %}` clause; confirm the checked-radio assertion goes RED. Restore, re-run, confirm all pass.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check courses/element_forms.py courses/tests/test_image_size_editor.py
uv run ruff format --check courses/element_forms.py courses/tests/test_image_size_editor.py
git add courses/element_forms.py templates/courses/manage/editor/_edit_image.html courses/tests/test_image_size_editor.py
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

Create `courses/tests/test_image_size_render.py`:

```python
import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
def test_figure_carries_its_preset_class(size, render_image):
    html = render_image(size=size)
    assert f"el--image--{size}" in html


def test_figure_carries_the_preview_hook(render_image):
    el, html = render_image(size="medium", with_element=True)
    assert f'data-preview-el="{el.pk}"' in html


def test_figure_does_not_carry_data_element_id(render_image):
    """Guards the progress.js invariant: [data-element-id] is queried unscoped on
    student pages and must stay top-level-only. See views.py:709-713."""
    html = render_image(size="small")
    assert "data-element-id" not in html


def test_nested_image_still_carries_the_preview_hook(render_image_in_spoiler):
    el, html = render_image_in_spoiler(size="large")
    assert f'data-preview-el="{el.pk}"' in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest courses/tests/test_image_size_render.py --verbosity=0`
Expected: FAIL — neither the class nor the attribute is rendered.

- [ ] **Step 3: Update the element template**

`templates/courses/elements/imageelement.html` line 1 becomes:

```html
<figure class="el el--image el--image--{{ el.size }}" data-preview-el="{{ el.pk }}">
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_render.py --verbosity=0`
Expected: 7 passed (4 parametrized + 3).

- [ ] **Step 5: Falsify**

Replace `el--image--{{ el.size }}` with a bare `el--image`; confirm all four parametrized cases go RED. Restore. Change `data-preview-el` to `data-element-id`; confirm both `test_figure_carries_the_preview_hook` and `test_figure_does_not_carry_data_element_id` go RED. Restore, re-run, confirm 7 passed.

- [ ] **Step 6: Add the `_seen_current_ids` pin**

Append a test asserting a nested image's pk is absent from `courses.views._seen_current_ids(node)` — the server-side filter that makes the invariant above safe even if an attribute leaks.

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

Create `courses/tests/test_image_size_transfer.py`:

```python
import pytest

from courses.transfer.schema import FORMAT_VERSION

pytestmark = pytest.mark.django_db


def test_format_version_is_bumped():
    assert FORMAT_VERSION == 7


@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
def test_round_trip_preserves_the_preset(size, export_import_course):
    imported = export_import_course(image_size=size)
    assert imported.size == size


def test_archive_without_a_size_key_imports_as_full(validate_image_payload):
    data = {"media": "m1", "alt": "a", "figcaption": ""}
    validate_image_payload(data)
    assert data["size"] == "full"


def test_archive_with_a_junk_size_imports_as_full(validate_image_payload):
    data = {"media": "m1", "alt": "a", "figcaption": "", "size": "enormous"}
    validate_image_payload(data)
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

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_image_size_transfer.py tests/test_transfer_export.py tests/test_transfer_import.py --verbosity=0`
Expected: all pass.

- [ ] **Step 8: Falsify**

Delete the `data.setdefault("size", "full")` line; confirm `test_archive_without_a_size_key_imports_as_full` goes RED with an exact-keys error. Restore. Delete the junk-value coercion; confirm `test_archive_with_a_junk_size_imports_as_full` goes RED. Restore. Drop `"size"` from `_ser_image`; confirm the round-trip cases go RED. Restore, re-run, confirm all pass.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/transfer/schema.py courses/tests/test_image_size_transfer.py
uv run ruff format --check courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/transfer/schema.py courses/tests/test_image_size_transfer.py
git add courses/transfer/ courses/tests/test_image_size_transfer.py
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

Create `courses/tests/test_image_size_css.py`, reading `courses/static/courses/css/courses.css` and asserting each preset's `max-width` on the figure selector and `max-height` on the img selector, plus that the capped presets carry `fit-content` and `margin-inline: auto`, and that `full` does NOT.

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

- [ ] **Step 6: Commit**

```bash
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
      // On the CREATE flow data-for-element is "" and no figure exists yet, so
      // this is inertly a no-op until first save. That is correct behaviour.
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: pass.

- [ ] **Step 5: Falsify**

Delete the branch; confirm the source scan goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
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

Seed a lesson with two images — **tall 297x719** and **wide 948x719** — one per preset. For each preset, at **1280x900** and at **360x640**, read `getBoundingClientRect()` and assert:
- the height is within 1px of the preset's `dvh` fraction of the viewport height when height binds;
- the width is within 1px of the preset's percentage of `container.getBoundingClientRect().width` when width binds.

Read the container width **at runtime** — never hardcode 736 or 880 — so the test keeps testing the preset rather than re-encoding today's shell layout.

**Both fixtures are required.** For the tall image the height cap binds at every preset, so `max-width` is never exercised: shipping `small` as `35%` would not move a pixel. The wide fixture is the only one that binds on width.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_e2e_image_size.py -m e2e --verbosity=0`
Expected: pass. **An exit-5 deselection is a failure, not a pass** — report the verdict line verbatim.

- [ ] **Step 3: Falsify**

Change `.el--image--large img` to `max-height: 45dvh`; confirm the large cases go RED at both viewports. Restore. Change `.el--image--small` to `max-width: 35%`; confirm the **wide** fixture's small case goes RED (and note that the tall fixture stays green — that is why both exist). Restore, re-run, confirm pass.

- [ ] **Step 4: Commit**

```bash
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

- Under `page.emulate_media(media="print")`, the resolved `max-height` is the **mm** value, not the `dvh` one. A source scan cannot prove the print rule *wins* the tie.
- The zoom overlay shows the image unaffected by the preset.
- A nested image scales to its container, not the page — one case each for **spoiler, tabs, two-column and callout**.

- [ ] **Step 4: Run, falsify, commit**

Run the file with `-m e2e`. Falsify each: delete the figure `margin-inline: auto` (figure-centred goes RED); delete the img `margin-inline: auto` (long-caption case goes RED); move the print block above the presets (print case goes RED); rebind the JS handler to the preview pane instead of `root` (the after-swap case goes RED, the before-swap one stays green). Restore each and re-run.

```bash
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

Then inspect: `grep -c '#, fuzzy'` and `grep -c '^#~'` must both be **0** in both `.po` files. `makemessages` fuzzy-prefills WRONG translations on this repo — clearing one is TWO deletions (the flag line and the bogus `msgstr`). Then `uv run python manage.py compilemessages`.

- [ ] **Step 3: Full verification**

Run each in the FOREGROUND and report the verbatim verdict line:

```bash
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
uv run ruff check . && uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
```

If any is red, report it honestly with the failing test names. Do not fix unrelated pre-existing failures.

- [ ] **Step 4: Commit**

```bash
git add docs/help/course-admin/ locale/
git commit -m "docs(image): document the size presets"
```

---

## Self-Review

**Spec coverage.** §1 model → Task 1. §2 rendering → Task 3. §3 CSS incl. figure box and print → Tasks 5, 6. §4a form → Task 2. §4b/§4c control → Task 2. §5 live preview → Tasks 7, 9. §6 zoom → Task 9. §7 transfer → Task 4. Error handling → Task 4 (steps 4, 8). Testing rows 1-19 → rows 1 (T1), 2/3/3b/3c (T3), 4-7 (T4), 8 (T8), 9/10 (T9), 11/12 (T9), 13/13b (T6, T9), 14-16 (T2), 17/18/19 (T9). No spec requirement is unassigned.

**Placeholder scan.** No "TBD"/"similar to Task N"/"add appropriate error handling". Task 5's and Task 6's CSS, Task 4's transfer code, Task 7's JS branch and Task 2's template are given in full. Tasks 8-10 describe assertions rather than pasting whole e2e bodies, because the fixture helpers are copied verbatim from a named existing file — the values (viewports, fixture dimensions, caption length, tolerances) are all pinned explicitly.

**Type consistency.** `ImageElement.Size` / `.size` / `Size.values` used identically in Tasks 1, 2, 4. Attribute names are consistent throughout: `data-preview-el` on the figure (never `data-element-id`), `data-size-preset` and `data-for-element` on the radios. Class names are `el--image--{small,medium,large,full}` everywhere. The migration is referred to as `00NN_imageelement_size` in Task 1 only.
