# Iframe Embed Aspect Ratio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each pasted embed at the aspect ratio of its `<iframe>` (falling back to 16:9 when unknown), instead of forcing every embed into a hard-coded 16:9 box.

**Architecture:** A new pure helper `parse_iframe_dimensions` in `courses/embed.py` reads the sole pasted `<iframe>`'s `width`/`height` attributes. `IframeElementForm.clean_url` stores them on two new nullable `IframeElement` fields (`width`, `height`). The consumption template renders `aspect-ratio: W / H` inline when both are known, else the default 16:9 wrapper (renamed `.embed-16x9` → `.embed-frame`). Course export/import carries the dimensions via a `FORMAT_VERSION` bump.

**Tech Stack:** Python 3.13, Django, pytest, `uv` for all tooling, `ruff` for lint/format.

## Global Constraints

- **Tooling is `uv`-prefixed:** bash `pytest`/`ruff`/`python` are NOT on PATH. Use `uv run pytest`, `uv run ruff`, `uv run python manage.py`.
- **Before every commit:** `uv run ruff format <files>` then `uv run ruff check <files>` (CI enforces `ruff format --check`).
- **Run focused test files only** (the full suite can stall a subagent); the controller runs the full suite at the end.
- **Capture-side upper bound is load-bearing:** `parse_iframe_dimensions` returns `None` for a dimension `> 2147483647`. `width`/`height` are NOT form fields, so `ModelForm._post_clean` excludes them from `full_clean` and the `PositiveIntegerField` range validator never runs on the form path — an unbounded value would 500 at the DB on save. The cap degrades it to the 16:9 fallback.
- **Edit rule:** dimensions update only when a paste yields BOTH usable numeric dimensions (a full `<iframe>` with `width`/`height`). Any input without a usable pair (a plain URL, or an `<iframe>` lacking dimensions) leaves stored dimensions unchanged — so a title-only edit never wipes a captured ratio.
- **`FORMAT_VERSION` bump is blanket:** every new export declares version 2 regardless of content; a version-1 instance rejects all version-2 archives (accepted trade-off).
- **Migration** `0030` depends on the current head `0029_backfill_geogebra_urls`.
- **Delivery:** all work is on the existing branch `geogebra-embed-canonicalization` (extends open PR #69) — do not create a new branch.
- `IframeElement.width`/`.height` are `models.PositiveIntegerField(null=True, blank=True)`. Output aspect-ratio uses the raw integers: `aspect-ratio: {{ el.width }} / {{ el.height }}`.

---

### Task 1: Model fields + migration

**Files:**
- Modify: `courses/models.py` (the `IframeElement` class, around line 387)
- Create: `courses/migrations/0030_iframeelement_dimensions.py`
- Test: `tests/test_iframe_dimensions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `IframeElement.width` and `IframeElement.height`, both `PositiveIntegerField(null=True, blank=True)`. Later tasks (form, render, transfer) read/write these.

- [ ] **Step 1: Write the failing model test**

Create `tests/test_iframe_dimensions.py`:

```python
import pytest

from courses.models import IframeElement

URL = "https://www.geogebra.org/material/iframe/id/abc"


@pytest.mark.django_db
def test_iframe_element_stores_nullable_dimensions():
    el = IframeElement.objects.create(url=URL, title="t", width=800, height=760)
    el.refresh_from_db()
    assert (el.width, el.height) == (800, 760)


@pytest.mark.django_db
def test_iframe_element_dimensions_default_null():
    el = IframeElement.objects.create(url=URL, title="t")
    el.refresh_from_db()
    assert (el.width, el.height) == (None, None)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_iframe_dimensions.py -q`
Expected: FAIL — `TypeError: 'width' is an invalid keyword argument` (the fields don't exist yet).

- [ ] **Step 3: Add the model fields**

In `courses/models.py`, the `IframeElement` class currently is:

```python
class IframeElement(ElementBase):
    url = models.URLField(validators=[validate_embed_url])
    title = models.CharField(max_length=255, blank=True)
    elements = GenericRelation(Element)
```

Add the two fields after `title`:

```python
class IframeElement(ElementBase):
    url = models.URLField(validators=[validate_embed_url])
    title = models.CharField(max_length=255, blank=True)
    # Pasted <iframe> intrinsic size; drives the render aspect ratio (16:9 fallback
    # when null). Null = unknown (plain-URL paste). Not form fields — captured in
    # IframeElementForm.clean_url.
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    elements = GenericRelation(Element)
```

- [ ] **Step 4: Create the migration**

Create `courses/migrations/0030_iframeelement_dimensions.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0029_backfill_geogebra_urls"),
    ]

    operations = [
        migrations.AddField(
            model_name="iframeelement",
            name="width",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="iframeelement",
            name="height",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
```

- [ ] **Step 5: Verify tests pass and there is no migration drift**

Run: `uv run pytest tests/test_iframe_dimensions.py -q`
Expected: PASS (2 passed). If the Postgres test DB errors with "already exists / used by other users", re-run with `--create-db`.

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (the hand-written migration matches the model).

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff format courses/models.py courses/migrations/0030_iframeelement_dimensions.py tests/test_iframe_dimensions.py
uv run ruff check courses/models.py courses/migrations/0030_iframeelement_dimensions.py tests/test_iframe_dimensions.py
git add courses/models.py courses/migrations/0030_iframeelement_dimensions.py tests/test_iframe_dimensions.py
git commit -m "feat(embed): add nullable width/height to IframeElement"
```

---

### Task 2: `parse_iframe_dimensions` capture helper

**Files:**
- Modify: `courses/embed.py`
- Test: `tests/test_embed.py`

**Interfaces:**
- Consumes: the existing `_IframeCollector` HTML parser in `courses/embed.py`.
- Produces: `parse_iframe_dimensions(raw: str) -> tuple[int | None, int | None]` — the sole `<iframe>`'s `width`/`height` as positive ints ≤ 2147483647, or `None` per dimension; `(None, None)` when there isn't exactly one `<iframe>` or on any parse failure. Never raises.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_embed.py`:

```python
from courses.embed import parse_iframe_dimensions

_REAL_TAG = (
    '<iframe scrolling="no" title="Pythagoras" '
    'src="https://www.geogebra.org/material/iframe/id/dc2j6xqt/width/800/height/760" '
    'width="800px" height="760px" style="border:0px;"> </iframe>'
)


def test_dimensions_from_px_attributes():
    assert parse_iframe_dimensions(_REAL_TAG) == (800, 760)


def test_dimensions_from_bare_integer_attributes():
    raw = '<iframe src="https://www.geogebra.org/material/iframe/id/a" width="560" height="315"></iframe>'
    assert parse_iframe_dimensions(raw) == (560, 315)


def test_dimension_junk_values_become_none():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" '
        'width="100%" height="800.5"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimension_zero_and_negative_become_none():
    raw = '<iframe src="https://www.geogebra.org/material/iframe/id/a" width="0" height="-5"></iframe>'
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimension_over_int_ceiling_becomes_none():
    raw = '<iframe src="https://www.geogebra.org/material/iframe/id/a" width="9999999999" height="300"></iframe>'
    assert parse_iframe_dimensions(raw) == (None, 300)


def test_dimensions_missing_attributes_are_none():
    raw = '<iframe src="https://www.geogebra.org/material/iframe/id/a"></iframe>'
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimensions_plain_url_is_none_none():
    assert parse_iframe_dimensions("https://www.geogebra.org/m/abc") == (None, None)


def test_dimensions_two_iframes_is_none_none():
    raw = (
        '<iframe src="https://www.geogebra.org/material/iframe/id/a" width="800" height="600"></iframe>'
        '<iframe src="https://www.geogebra.org/material/iframe/id/b" width="400" height="300"></iframe>'
    )
    assert parse_iframe_dimensions(raw) == (None, None)


def test_dimensions_empty_input_is_none_none():
    assert parse_iframe_dimensions("") == (None, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_embed.py -k dimension -q`
Expected: FAIL — `ImportError: cannot import name 'parse_iframe_dimensions'`.

- [ ] **Step 3: Implement the helper**

In `courses/embed.py`, add after the `_IframeCollector` class definition:

```python
_INT_MAX = 2147483647  # PositiveIntegerField ceiling


def _dimension(value):
    """A positive int (1.._INT_MAX) from an iframe width/height attribute, else None.

    Strips a trailing 'px'; rejects '', '%', negatives, zero, non-integers
    (e.g. '800.5'), and values above the DB column ceiling.
    """
    value = (value or "").strip()
    if value.lower().endswith("px"):
        value = value[:-2].strip()
    if not value.isdigit():  # rejects '', '%', '-5', '800.5', any non-digit run
        return None
    n = int(value)
    if n <= 0 or n > _INT_MAX:
        return None
    return n


def parse_iframe_dimensions(raw):
    """Return (width, height) from the sole pasted <iframe>'s attributes, or (None, None).

    Reads the `width`/`height` HTML attributes only (not any provider-specific URL
    path). Anything but exactly one <iframe> — a plain URL, zero, or many — yields
    (None, None). Never raises, like the rest of this module.
    """
    parser = _IframeCollector()
    try:
        parser.feed((raw or "").strip())
        parser.close()
    except Exception:  # stdlib html.parser rarely raises; treat as unparseable
        return None, None
    if len(parser.iframes) != 1:
        return None, None
    attrs = parser.iframes[0]
    return _dimension(attrs.get("width")), _dimension(attrs.get("height"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_embed.py -q`
Expected: PASS (the new dimension tests plus all existing `test_embed.py` tests).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format courses/embed.py tests/test_embed.py
uv run ruff check courses/embed.py tests/test_embed.py
git add courses/embed.py tests/test_embed.py
git commit -m "feat(embed): parse width/height from a pasted iframe tag"
```

---

### Task 3: Form capture wiring + edit rule

**Files:**
- Modify: `courses/element_forms.py` (`IframeElementForm.clean_url`)
- Test: `tests/test_iframe_dimensions.py`

**Interfaces:**
- Consumes: `parse_iframe_dimensions` (Task 2); `IframeElement.width`/`.height` (Task 1); the existing `extract_embed_url`.
- Produces: `IframeElementForm` that, on save, stores captured dimensions on the instance. `Meta.fields` stays `["url", "title"]` — `width`/`height` are set on `self.instance` directly, never as form fields.

- [ ] **Step 1: Write the failing form tests**

Add to `tests/test_iframe_dimensions.py`:

```python
from courses.element_forms import IframeElementForm

_FULL_TAG = (
    '<iframe title="Pythagoras" '
    'src="https://www.geogebra.org/material/iframe/id/dc2j6xqt/width/800/height/760" '
    'width="800px" height="760px" style="border:0px;"> </iframe>'
)
_OTHER_TAG = (
    '<iframe src="https://www.geogebra.org/material/iframe/id/other" '
    'width="640" height="480"></iframe>'
)
_OVERSIZED_TAG = (
    '<iframe src="https://www.geogebra.org/material/iframe/id/big" '
    'width="9999999999px" height="500px"></iframe>'
)


@pytest.mark.django_db
def test_form_captures_dimensions_from_full_iframe():
    form = IframeElementForm(data={"url": _FULL_TAG, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert (obj.width, obj.height) == (800, 760)


@pytest.mark.django_db
def test_form_plain_url_edit_preserves_existing_dimensions():
    obj = IframeElement.objects.create(url=URL, title="P", width=800, height=760)
    # Re-open to edit only the title; the field shows the canonical plain URL.
    form = IframeElementForm(
        data={"url": URL, "title": "renamed"}, instance=obj
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (800, 760)  # unchanged
    assert saved.title == "renamed"


@pytest.mark.django_db
def test_form_re_paste_overwrites_dimensions():
    obj = IframeElement.objects.create(url=URL, title="P", width=800, height=760)
    form = IframeElementForm(data={"url": _OTHER_TAG, "title": "P"}, instance=obj)
    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.width, saved.height) == (640, 480)


@pytest.mark.django_db
def test_form_bare_url_paste_leaves_dimensions_none():
    form = IframeElementForm(data={"url": URL, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert (obj.width, obj.height) == (None, None)


@pytest.mark.django_db
def test_form_oversized_paste_degrades_without_500():
    form = IframeElementForm(data={"url": _OVERSIZED_TAG, "title": "P"})
    assert form.is_valid(), form.errors
    obj = form.save()  # must not raise "integer out of range"
    assert (obj.width, obj.height) == (None, None)  # falls back to 16:9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_iframe_dimensions.py -k form -q`
Expected: FAIL — the capture tests see `(None, None)` (or the re-paste/oversized assertions mismatch) because `clean_url` does not yet capture dimensions.

- [ ] **Step 3: Wire capture into the form**

In `courses/element_forms.py`, add the import near the existing `from courses.embed import extract_embed_url`:

```python
from courses.embed import extract_embed_url
from courses.embed import parse_iframe_dimensions
```

Change `IframeElementForm.clean_url` from:

```python
    def clean_url(self):
        return extract_embed_url(self.cleaned_data.get("url", ""))
```

to:

```python
    def clean_url(self):
        raw = self.cleaned_data.get("url", "")
        url = extract_embed_url(raw)
        width, height = parse_iframe_dimensions(raw)
        # Capture only a usable pair (a full <iframe> with numeric width & height);
        # a plain-URL / dimensionless input leaves stored dims unchanged so a
        # title-only edit never wipes a captured ratio. width/height are not form
        # fields, so full_clean excludes them — the ceiling is enforced in
        # parse_iframe_dimensions, not here.
        if width and height:
            self.instance.width = width
            self.instance.height = height
        return url
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_iframe_dimensions.py -q`
Expected: PASS (all model + form tests). Also run the embed form tests to confirm no regression: `uv run pytest tests/test_embed.py -q` → PASS.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff format courses/element_forms.py tests/test_iframe_dimensions.py
uv run ruff check courses/element_forms.py tests/test_iframe_dimensions.py
git add courses/element_forms.py tests/test_iframe_dimensions.py
git commit -m "feat(embed): capture pasted iframe dimensions in the form"
```

---

### Task 4: Render — dynamic aspect ratio + `.embed-frame` rename

**Files:**
- Modify: `templates/courses/elements/iframeelement.html`
- Modify: `courses/static/courses/css/courses.css` (lines 8-11: the comment and the `.embed-16x9` rules)
- Test: `tests/test_iframe_dimensions.py`

**Interfaces:**
- Consumes: `IframeElement.width`/`.height` (Task 1).
- Produces: consumption HTML that carries `style="aspect-ratio: W / H"` on the wrapper when both dimensions are set, else the 16:9-default `.embed-frame` wrapper.

- [ ] **Step 1: Write the failing render tests**

Add to `tests/test_iframe_dimensions.py`:

```python
from django.template.loader import render_to_string


def _render(width, height):
    el = IframeElement(url=URL, title="P", width=width, height=height)
    return render_to_string("courses/elements/iframeelement.html", {"el": el})


def test_render_uses_aspect_ratio_when_dimensions_known():
    html = _render(800, 760)
    assert "embed-frame" in html
    assert "aspect-ratio: 800 / 760" in html


def test_render_falls_back_to_16x9_when_dimensions_unknown():
    html = _render(None, None)
    assert "embed-frame" in html
    assert "aspect-ratio:" not in html  # no inline override → CSS default 16:9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_iframe_dimensions.py -k render -q`
Expected: FAIL — the template still emits `embed-16x9` and never an inline `aspect-ratio` (`"embed-frame" in html` fails).

- [ ] **Step 3: Update the template**

Replace the whole body of `templates/courses/elements/iframeelement.html` with:

```html
{% load i18n %}
<div class="el el--iframe">
  <div class="embed-frame"{% if el.width and el.height %} style="aspect-ratio: {{ el.width }} / {{ el.height }}"{% endif %}>
    {% comment %}referrerpolicy: send the page origin to the embed provider; Django's
    default Referrer-Policy: same-origin would otherwise strip the Referer cross-origin.{% endcomment %}
    <iframe src="{{ el.url }}" loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            title="{{ el.title|default:_('embedded content') }}"></iframe>
  </div>
</div>
```

- [ ] **Step 4: Update the CSS (rename + comment)**

In `courses/static/courses/css/courses.css`, replace these three lines:

```css
/* --- Responsive embed (#13): 16:9 wrapper, ignore pasted width/height --- */
.embed-16x9 { position: relative; width: 100%; aspect-ratio: 16 / 9; }
.embed-16x9 > iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
```

with:

```css
/* --- Responsive embed: wrapper uses the pasted aspect ratio when known, else 16:9 --- */
.embed-frame { position: relative; width: 100%; aspect-ratio: 16 / 9; }
.embed-frame > iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
```

Leave the shared `.el--video iframe, .el--iframe iframe { … aspect-ratio: 16 / 9 }` rule (line 5) untouched — the `.el--iframe iframe` is absolutely positioned inside `.embed-frame`, so its own `aspect-ratio` is inert there.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_iframe_dimensions.py -q`
Expected: PASS (render tests plus the Task 1/3 tests).

Confirm the rename is complete (only doc files should still mention the old class):

Run: `uv run python -c "import pathlib,sys; roots=[pathlib.Path('courses'),pathlib.Path('templates')]; hits=[str(p) for r in roots for p in r.rglob('*') if p.suffix in {'.html','.css','.js'} and 'embed-16x9' in p.read_text(encoding='utf-8',errors='ignore')]; print(hits); sys.exit(1 if hits else 0)"`
Expected: `[]` (exit 0) — no code file under `courses/`/`templates/` references `embed-16x9`.

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff format tests/test_iframe_dimensions.py
uv run ruff check tests/test_iframe_dimensions.py
git add templates/courses/elements/iframeelement.html courses/static/courses/css/courses.css tests/test_iframe_dimensions.py
git commit -m "feat(embed): render pasted embed aspect ratio, rename .embed-16x9 to .embed-frame"
```

---

### Task 5: Course export/import round-trip

**Files:**
- Modify: `courses/transfer/schema.py` (`FORMAT_VERSION`)
- Modify: `courses/transfer/export.py` (`_ser_iframe`)
- Modify: `courses/transfer/payloads.py` (`_val_iframe`)
- Modify: `courses/transfer/importer.py` (`_build_iframe`)
- Modify: `tests/test_transfer_schema.py` (version assertion), `tests/test_transfer_export.py` (version assertion)
- Test: `tests/test_transfer_validation.py` (new iframe cases)

**Interfaces:**
- Consumes: `IframeElement.width`/`.height` (Task 1); the existing `check_int_or_null`, `_exact_keys`, `_canonical_embed`, `_clean_save`.
- Produces: iframe transfer payload `{"url", "title", "width", "height"}` (width/height nullable); `FORMAT_VERSION == 2`.

- [ ] **Step 1: Write the failing tests and update the two existing version assertions**

In `tests/test_transfer_schema.py`, change the existing `assert FORMAT_VERSION == 1` to:

```python
    assert FORMAT_VERSION == 2
```

In `tests/test_transfer_export.py`, change the existing `assert manifest["format_version"] == 1` to:

```python
    assert manifest["format_version"] == 2
```

Add to `tests/test_transfer_validation.py`. It already imports `pytest` and `TransferError` (from `courses.transfer.schema`) — do NOT re-import those (ruff flags the duplicate as F811). Add only the imports below, then the test functions:

```python
from django.core.exceptions import ValidationError

from courses.models import IframeElement
from courses.transfer.export import _ser_iframe
from courses.transfer.importer import _build_iframe
from courses.transfer.payloads import _val_iframe

_IFRAME_URL = "https://www.geogebra.org/material/iframe/id/abc"


def test_ser_iframe_emits_dimensions():
    el = IframeElement(url=_IFRAME_URL, title="t", width=800, height=760)
    assert _ser_iframe(el, {}) == {
        "url": _IFRAME_URL,
        "title": "t",
        "width": 800,
        "height": 760,
    }


def test_val_iframe_accepts_version1_archive_without_dimension_keys():
    data = {"url": _IFRAME_URL, "title": "t"}  # legacy v1 payload
    _val_iframe(data, "el1", set())
    assert data["width"] is None and data["height"] is None  # defaulted


def test_val_iframe_accepts_dimensions_and_a_single_dimension():
    data = {"url": _IFRAME_URL, "title": "t", "width": 800, "height": 760}
    _val_iframe(data, "el1", set())
    assert (data["width"], data["height"]) == (800, 760)
    lone = {"url": _IFRAME_URL, "title": "t", "width": 800}  # accepted asymmetry
    _val_iframe(lone, "el2", set())
    assert (lone["width"], lone["height"]) == (800, None)


def test_val_iframe_rejects_unknown_key():
    data = {"url": _IFRAME_URL, "title": "t", "bogus": 1}
    with pytest.raises(TransferError):
        _val_iframe(data, "el1", set())


@pytest.mark.django_db
def test_build_iframe_sets_dimensions():
    obj, _ = _build_iframe(
        {"url": _IFRAME_URL, "title": "t", "width": 800, "height": 760}, {}
    )
    assert (obj.width, obj.height) == (800, 760)


@pytest.mark.django_db
def test_build_iframe_rejects_oversized_dimension_via_full_clean():
    with pytest.raises(ValidationError):  # _create_elements maps this to TransferError
        _build_iframe(
            {"url": _IFRAME_URL, "title": "t", "width": 9999999999, "height": 100}, {}
        )
```

(`pytest` is already imported in `tests/test_transfer_validation.py`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_transfer_validation.py -k "iframe" tests/test_transfer_schema.py tests/test_transfer_export.py -q`
Expected: FAIL — `_ser_iframe` lacks width/height, `_val_iframe` still uses strict `_exact_keys(["url","title"])` (KeyError/TransferError on the new keys), `_build_iframe` ignores dimensions, and the version assertions expect 2 but the code still says 1.

- [ ] **Step 3: Bump `FORMAT_VERSION`**

In `courses/transfer/schema.py`, change:

```python
FORMAT_VERSION = 1
```

to:

```python
FORMAT_VERSION = 2
```

- [ ] **Step 4: Emit dimensions on export**

In `courses/transfer/export.py`, change `_ser_iframe` from:

```python
def _ser_iframe(el, ids):
    return {"url": el.url, "title": el.title}
```

to:

```python
def _ser_iframe(el, ids):
    return {"url": el.url, "title": el.title, "width": el.width, "height": el.height}
```

- [ ] **Step 5: Accept optional dimensions on import validation**

In `courses/transfer/payloads.py`, change `_val_iframe` from:

```python
def _val_iframe(data, elid, media_kinds):
    _exact_keys(data, ["url", "title"], _("iframe data"))
    check_str(data["url"], "url", required=True)
    check_str(data["title"], "title", max_length=255)
    data["url"] = _canonical_embed(data["url"], elid, extract_embed_url)
    return set()
```

to:

```python
def _val_iframe(data, elid, media_kinds):
    # width/height are optional (added in FORMAT_VERSION 2). setdefault first so a
    # legacy v1 archive (which has neither) gains them and passes the exact-keys
    # check, and so downstream _build_iframe never KeyErrors.
    data.setdefault("width", None)
    data.setdefault("height", None)
    _exact_keys(data, ["url", "title", "width", "height"], _("iframe data"))
    check_str(data["url"], "url", required=True)
    check_str(data["title"], "title", max_length=255)
    check_int_or_null(data["width"], "width")
    check_int_or_null(data["height"], "height")
    data["url"] = _canonical_embed(data["url"], elid, extract_embed_url)
    return set()
```

- [ ] **Step 6: Construct with dimensions on import**

In `courses/transfer/importer.py`, change `_build_iframe` from:

```python
def _build_iframe(data, assets):
    return _clean_save(IframeElement(url=data["url"], title=data["title"])), ()
```

to:

```python
def _build_iframe(data, assets):
    return (
        _clean_save(
            IframeElement(
                url=data["url"],
                title=data["title"],
                width=data["width"],
                height=data["height"],
            )
        ),
        (),
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_transfer_validation.py tests/test_transfer_schema.py tests/test_transfer_export.py tests/test_transfer_import.py -q`
Expected: PASS — the new iframe cases, the two updated version assertions, and the existing transfer suites (the pre-existing round-trip test's iframe now serializes two extra keys and imports them as `None`, which is unchanged behavior for that test).

- [ ] **Step 8: Lint, format, commit**

```bash
uv run ruff format courses/transfer/schema.py courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_transfer_validation.py tests/test_transfer_schema.py tests/test_transfer_export.py
uv run ruff check courses/transfer/schema.py courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_transfer_validation.py tests/test_transfer_schema.py tests/test_transfer_export.py
git add courses/transfer/ tests/test_transfer_validation.py tests/test_transfer_schema.py tests/test_transfer_export.py
git commit -m "feat(embed): carry iframe width/height through course export/import"
```

---

## Definition of Done (run after Task 5)

- [ ] Full suite green: `uv run pytest -q --create-db`
- [ ] Lint/format clean: `uv run ruff format --check .` and `uv run ruff check .`
- [ ] Migrations consistent: `uv run python manage.py makemigrations --check --dry-run` → "No changes detected"
- [ ] Manual smoke (recommended): add an Embed/iframe element, paste the real GeoGebra `<iframe ... width="800px" height="760px">` — the consumption page renders the worksheet at ~1.05:1 (not letterboxed in 16:9); paste a bare `…/m/<ID>` URL — renders 16:9. Verify light + dark via a throwaway Playwright screenshot if styling is in question.
