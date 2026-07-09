# Gallery / Carousel element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GalleryElement` content element — an author-authored set of 2–20 course images shown to students as a single-image-at-a-time **carousel**, each image carrying an optional rich-text + math **description**.

**Architecture:** A new concrete `GalleryElement(ElementBase)` storing a JSON `data = {desc_pos, images:[{media:int, desc:str}]}` — modeled on `TableElement` for the model/JSON/editor shape, and on the unit slideshow's `slideshow.js` for the student carousel navigation. Images reference existing `MediaAsset` rows by id inside the JSON; descriptions reuse the table cells' math-protected `sanitize_cell`. A new self-contained, **multi-instance** `gallery.js` progressively enhances the server-rendered figure stack into a carousel.

**Tech Stack:** Django (Python), server-rendered templates, vanilla ES5 JS (no build step), nh3 sanitiser, KaTeX (math), Playwright (e2e), `uv` for tooling.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — always invoke via `uv run` (e.g. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run python manage.py ...`).
- **Element bounds:** `MIN_IMAGES = 2`, `MAX_IMAGES = 20`. `desc_pos ∈ {"above","below"}`, default `"below"`. `DOTS_MAX = 12` (≤12 → dots, >12 → text counter). These are copied verbatim into code where referenced.
- **Sanitisation:** every image `desc` is sanitised via the existing `courses.sanitize.sanitize_cell` (math-protected, allow-list `strong/b/em/i/u/br`) at `GalleryElement.save()`, over `normalize_data` first so hostile JSON can't raise.
- **i18n:** every user-visible string is translatable; EN + PL catalogs. Module-level translatable dicts use `gettext_lazy` (never eager `gettext`). The string `"Image {n} of {total}"` is a **single shared msgid** used by both the server `alt` fallback and the JS status region.
- **Icons:** monochrome `currentColor` SVG only (no emoji/multicolour).
- **Django comments:** `{# #}` must be single-line; use `{% comment %}…{% endcomment %}` for multi-line.
- **JS:** ES5 IIFE style matching `slideshow.js`/`table_editor.js` (no `let`/`const`/arrow functions in shipped `.js`), self-guarding on its data-hook.
- **Never crop images:** frame is a responsive `aspect-ratio: 4/3; max-height: 70vh` box; images `object-fit: contain`.
- **Test-passwords:** any test needing a password uses `tests.factories.TEST_PASSWORD`, never a literal.

---

## File structure

**Create:**
- `courses/migrations/0034_galleryelement_alter_element_content_type.py` — model + content_type choices.
- `templates/courses/elements/galleryelement.html` — student render (figure stack).
- `templates/courses/manage/editor/_edit_gallery.html` — author editor partial.
- `courses/static/courses/js/gallery.js` — student carousel (multi-instance).
- `courses/static/courses/js/gallery_editor.js` — author editor enhancement.
- Test files under `tests/` (per task).

**Modify:**
- `courses/models.py` — `GalleryElement`, `ELEMENT_MODELS`.
- `courses/sanitize.py` — `desc_to_alt` helper.
- `courses/element_forms.py` — `GalleryElementForm`, `FORM_FOR_TYPE`.
- `courses/views.py` — `_gallery_has_math` + `has_math` OR-branches (lesson + quiz).
- `courses/views_manage.py` — `_EDITOR_TYPE_LABELS`, two `type_key` allow-lists, two course-scope tuples.
- `courses/builder.py` — generic-branch course-scope tuple.
- `courses/transfer/export.py` — `_ser_gallery`, `SERIALIZERS`, Pass 2/4 media-list accounting.
- `courses/transfer/payloads.py` — `_val_gallery`, `VALIDATORS`.
- `courses/transfer/importer.py` — `_build_gallery`, `BUILDERS`.
- `courses/static/courses/js/math.js` — add `.el--gallery` to the inline-math selector.
- `courses/static/courses/js/media_picker.js` — additive append-mode callback for multi-image pick.
- `templates/courses/manage/editor/_add_menu.html` — gallery type card.
- `templates/courses/manage/_icon_sprite.html` — `el-gallery` symbol.
- `templates/courses/manage/editor/editor.html` — load `gallery_editor.js`.
- `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html` — load `gallery.js` + `GALLERY_I18N`.
- `courses/static/courses/css/courses.css` — student carousel styles (+ editor styles alongside the table editor's).

---

### Task 1: `desc_to_alt` sanitiser helper

Derives a plain-text `alt` string from a sanitised rich/math description: strip math spans, strip tags, unescape, collapse whitespace. Empty result → `""` (the caller supplies the "Image n of m" fallback).

**Files:**
- Modify: `courses/sanitize.py`
- Test: `tests/test_sanitize_gallery.py` (create)

**Interfaces:**
- Produces: `desc_to_alt(value: str) -> str` — plain text with all tags and `\(...\)`/`\[...\]` math removed; whitespace-collapsed; `""` when the input has no textual content.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sanitize_gallery.py
from courses.sanitize import desc_to_alt


def test_desc_to_alt_strips_tags_and_math():
    assert desc_to_alt("<strong>Cell</strong> shape") == "Cell shape"
    assert desc_to_alt(r"A \(x^2\) curve") == "A curve"          # math removed
    assert desc_to_alt(r"\(x^2\)") == ""                          # math-only -> empty
    assert desc_to_alt("") == ""
    assert desc_to_alt("   ") == ""
    assert desc_to_alt("<b>bold</b>&amp;<i>it</i>") == "bold&it"  # unescaped, tags gone
    assert desc_to_alt("line<br>two") == "line two"              # br -> space, collapsed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sanitize_gallery.py -v`
Expected: FAIL with `ImportError: cannot import name 'desc_to_alt'`

- [ ] **Step 3: Implement `desc_to_alt` in `courses/sanitize.py`**

Add after `sanitize_cell` (reusing the existing module-level `_MATH_SPAN`, `html`, `re`, `nh3`):

```python
_WS = re.compile(r"\s+")


def desc_to_alt(value):
    """Plain-text alt derived from a sanitised gallery description: drop math
    spans and all tags, unescape entities, collapse whitespace. Empty string
    when the description carries no textual content (e.g. math-only) — the
    caller substitutes a generic "Image n of m" alt in that case."""
    value = value or ""
    no_math = _MATH_SPAN.sub(" ", value)
    # tags=set() strips every tag but keeps (escaped) text content.
    text = nh3.clean(no_math, tags=set(), attributes={}, link_rel=None)
    return _WS.sub(" ", html.unescape(text)).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sanitize_gallery.py -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/sanitize.py tests/test_sanitize_gallery.py
uv run ruff format courses/sanitize.py tests/test_sanitize_gallery.py
git add courses/sanitize.py tests/test_sanitize_gallery.py
git commit -m "feat(gallery): desc_to_alt plain-text helper (strip tags+math)"
```

---

### Task 2: `GalleryElement` model + migration

The concrete model: JSON `data`, constants, `normalize_data` (never raises), `save()` (normalize-then-sanitise each desc), `resolved_images()` (mids → `MediaAsset`, skipping unresolved), `normalized_data` property. Register in `ELEMENT_MODELS` and add migration `0034`.

**Files:**
- Modify: `courses/models.py`
- Create: `courses/migrations/0034_galleryelement_alter_element_content_type.py`
- Test: `tests/test_gallery_model.py` (create)

**Interfaces:**
- Consumes: `sanitize_cell` (existing), `MediaAsset` (existing).
- Produces:
  - `GalleryElement.CAPTION_POSITIONS = {"above","below"}`, `DEFAULT_POS = "below"`, `MIN_IMAGES = 2`, `MAX_IMAGES = 20`.
  - `GalleryElement.normalize_data(data) -> {"desc_pos": str, "images": [{"media": int, "desc": str}]}` (staticmethod; never raises; drops non-int media / non-dict entries).
  - `GalleryElement.normalized_data` (property).
  - `GalleryElement.resolved_images() -> list[{"media": MediaAsset, "desc": str}]` in stored order, skipping ids that no longer resolve.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gallery_model.py
import pytest
from courses.models import GalleryElement, MediaAsset
from tests.factories import make_course, make_image_asset  # existing helpers

pytestmark = pytest.mark.django_db


def test_normalize_data_defaults_and_coercion():
    n = GalleryElement.normalize_data(None)
    assert n == {"desc_pos": "below", "images": []}
    n = GalleryElement.normalize_data(
        {"desc_pos": "sideways", "images": [{"media": 5, "desc": "x"}, "junk", {"desc": "no id"}, {"media": "s"}]}
    )
    assert n["desc_pos"] == "below"                      # bad pos -> default
    assert n["images"] == [{"media": 5, "desc": "x"}]    # only the valid int-media dict survives


def test_normalize_data_keeps_above_and_duplicates():
    n = GalleryElement.normalize_data(
        {"desc_pos": "above", "images": [{"media": 1, "desc": ""}, {"media": 1, "desc": ""}]}
    )
    assert n["desc_pos"] == "above"
    assert len(n["images"]) == 2                          # duplicates permitted


def test_save_sanitises_each_desc():
    course = make_course()
    a1 = make_image_asset(course)
    a2 = make_image_asset(course)
    el = GalleryElement(
        data={"desc_pos": "below", "images": [
            {"media": a1.pk, "desc": "<script>x</script><b>ok</b>"},
            {"media": a2.pk, "desc": r"keep \(x<5\)"},
        ]}
    )
    el.save()
    assert el.data["images"][0]["desc"] == "<b>ok</b>"       # script stripped
    assert r"\(x<5\)" in el.data["images"][1]["desc"]        # math preserved


def test_save_never_raises_on_hostile_data():
    el = GalleryElement(data={"images": "not-a-list"})
    el.save()  # must not raise
    assert GalleryElement.objects.filter(pk=el.pk).exists()


def test_resolved_images_skips_missing():
    course = make_course()
    a1 = make_image_asset(course)
    el = GalleryElement.objects.create(
        data={"desc_pos": "below", "images": [
            {"media": a1.pk, "desc": "one"},
            {"media": 999999, "desc": "gone"},
        ]}
    )
    resolved = el.resolved_images()
    assert [r["media"].pk for r in resolved] == [a1.pk]
    assert resolved[0]["desc"] == "one"
```

> If `make_image_asset` does not exist in `tests/factories.py`, add a minimal factory there that creates a `MediaAsset(course=course, kind="image", file=..., original_filename="x.png")` using a tiny in-memory PNG (mirror whatever the image-element tests already use — grep `MediaAsset(` under `tests/`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gallery_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'GalleryElement'`

- [ ] **Step 3: Add `GalleryElement` to `courses/models.py`**

Place it next to `TableElement` (after it). `sanitize_cell` is already imported at module top.

```python
class GalleryElement(ElementBase):
    """Image carousel: an ordered list of course-image references, each with an
    optional rich-text + math description. Descriptions are sanitised at save()."""

    CAPTION_POSITIONS = {"above", "below"}
    DEFAULT_POS = "below"
    MIN_IMAGES = 2
    MAX_IMAGES = 20

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def _image(raw):
        if not isinstance(raw, dict):
            return None
        media = raw.get("media")
        if not isinstance(media, int) or isinstance(media, bool):
            return None
        desc = raw.get("desc")
        return {"media": media, "desc": desc if isinstance(desc, str) else ""}

    @staticmethod
    def normalize_data(data):
        """Well-formed dict for arbitrary stored data; never raises. Drops any
        image entry without a valid int `media`. Duplicates are preserved."""
        data = data if isinstance(data, dict) else {}
        raw = data.get("images")
        raw = raw if isinstance(raw, list) else []
        images = [img for img in (GalleryElement._image(r) for r in raw) if img]
        pos = data.get("desc_pos")
        return {
            "desc_pos": pos if pos in GalleryElement.CAPTION_POSITIONS else GalleryElement.DEFAULT_POS,
            "images": images,
        }

    def save(self, *args, **kwargs):
        self.data = self._sanitized_data(self.data)
        super().save(*args, **kwargs)

    @staticmethod
    def _sanitized_data(data):
        """Normalise first (so hostile shapes can't raise), then sanitise every
        description. Defense-in-depth on all write paths (form, import, admin)."""
        norm = GalleryElement.normalize_data(data)
        for img in norm["images"]:
            img["desc"] = sanitize_cell(img.get("desc", ""))
        return norm

    def resolved_images(self):
        """Ordered [{media: MediaAsset, desc: str}] for image ids that still
        resolve; unresolved ids are skipped (never 500s a lesson page)."""
        norm = self.normalize_data(self.data)
        ids = [img["media"] for img in norm["images"]]
        assets = MediaAsset.objects.in_bulk(ids)  # {pk: MediaAsset}
        out = []
        for img in norm["images"]:
            asset = assets.get(img["media"])
            if asset is not None:
                out.append({"media": asset, "desc": img["desc"]})
        return out

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)
```

Add `"galleryelement"` to `ELEMENT_MODELS` (append after `"tableelement"`).

- [ ] **Step 4: Create the migration**

`courses/migrations/0034_galleryelement_alter_element_content_type.py` — mirror `0033` exactly, swapping `TableElement`→`GalleryElement`, depending on `0033`, and appending `"galleryelement"` to `model__in`:

```python
import django.db.models.deletion
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("courses", "0033_tableelement_alter_element_content_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="GalleryElement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("data", models.JSONField(default=dict)),
            ],
            options={"abstract": False},
        ),
        migrations.AlterField(
            model_name="element",
            name="content_type",
            field=models.ForeignKey(
                limit_choices_to={
                    "app_label": "courses",
                    "model__in": [
                        "textelement",
                        "imageelement",
                        "videoelement",
                        "iframeelement",
                        "mathelement",
                        "htmlelement",
                        "choicequestionelement",
                        "shorttextquestionelement",
                        "extendedresponsequestionelement",
                        "shortnumericquestionelement",
                        "fillblankquestionelement",
                        "dragfillblankquestionelement",
                        "matchpairquestionelement",
                        "dragtoimagequestionelement",
                        "slidebreakelement",
                        "tableelement",
                        "galleryelement",
                    ],
                },
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
    ]
```

Verify no drift: `uv run python manage.py makemigrations courses --check --dry-run` must report **no** changes (the hand-written migration matches the model). If it wants a new migration, reconcile the hand-written file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_gallery_model.py -v`
Expected: PASS (all 5)

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check courses/models.py
uv run ruff format courses/models.py courses/migrations/0034_galleryelement_alter_element_content_type.py
git add courses/models.py courses/migrations/0034_galleryelement_alter_element_content_type.py tests/test_gallery_model.py tests/factories.py
git commit -m "feat(gallery): GalleryElement model, normalize/save/resolve, migration 0034"
```

---

### Task 3: Student render template + `render()` + math gating

The `galleryelement.html` figure-stack template, the model `render()` that feeds it resolved images + per-image alt, the `.el--gallery` math scope, and the `has_math` OR-branches.

**Files:**
- Create: `templates/courses/elements/galleryelement.html`
- Modify: `courses/models.py` (`GalleryElement.render`), `courses/static/courses/js/math.js`, `courses/views.py`
- Test: `tests/test_gallery_render.py` (create)

**Interfaces:**
- Consumes: `GalleryElement.resolved_images()`, `desc_to_alt` (Task 1).
- Produces: `GalleryElement.render()` returns HTML; `_gallery_has_math(el) -> bool` in `views.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gallery_render.py
import pytest
from django.utils.translation import gettext as _
from courses.models import GalleryElement
from courses.views import _gallery_has_math
from tests.factories import make_course, make_image_asset

pytestmark = pytest.mark.django_db


def _gallery(desc_pos, descs):
    course = make_course()
    imgs = []
    for d in descs:
        a = make_image_asset(course)
        imgs.append({"media": a.pk, "desc": d})
    return GalleryElement.objects.create(data={"desc_pos": desc_pos, "images": imgs})


def test_render_two_images_emits_figures_and_root_class():
    html = _gallery("below", ["<b>one</b>", ""]).render()
    assert "el el--gallery" in html
    assert "data-gallery" in html
    assert html.count("gallery__item") == 2
    assert html.count("gallery__frame") == 2
    # a .gallery__desc is emitted for EVERY figure (empty for the 2nd)
    assert html.count("gallery__desc") == 2
    assert "<b>one</b>" in html


def test_render_alt_fallback_for_math_only_desc():
    html = _gallery("below", [r"\(x^2\)", "plain"]).render()
    assert 'alt="Image 1 of 2"' in html   # math-only -> generic fallback
    assert 'alt="plain"' in html


def test_render_zero_resolvable_omits_container():
    el = GalleryElement.objects.create(data={"desc_pos": "below", "images": [{"media": 999999, "desc": "x"}]})
    assert el.render().strip() == ""       # nothing rendered


def test_render_desc_pos_above_orders_desc_before_frame():
    html = _gallery("above", ["cap", "cap2"]).render()
    assert html.index("gallery__desc") < html.index("gallery__frame")


def test_gallery_has_math():
    assert _gallery_has_math(_gallery("below", [r"\(a\)", ""])) is True
    assert _gallery_has_math(_gallery("below", ["plain", ""])) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gallery_render.py -v`
Expected: FAIL (`_gallery_has_math` import error / template missing)

- [ ] **Step 3: Add `render()` to `GalleryElement`**

Replace the default render by overriding it (add to the model class):

```python
    def render(self):
        from django.template.loader import render_to_string
        from courses.sanitize import desc_to_alt

        norm = self.normalize_data(self.data)
        resolved = self.resolved_images()
        total = len(resolved)
        figures = []
        for i, img in enumerate(resolved, start=1):
            alt = desc_to_alt(img["desc"])
            if not alt and img["desc"]:
                # non-empty but strips to empty (math-only) -> generic alt
                alt = _("Image {n} of {total}").format(n=i, total=total)
            figures.append({"url": img["media"].file.url, "desc": img["desc"], "alt": alt})
        if not figures:
            return ""  # 0 resolvable images -> render nothing
        return render_to_string(
            "courses/elements/galleryelement.html",
            {"el": self, "desc_pos": norm["desc_pos"], "figures": figures},
        )
```

Add `from django.utils.translation import gettext as _` inside the method if `_` is not already module-imported (grep — `models.py` likely imports `gettext_lazy as _`; if so, use a local `from django.utils.translation import gettext as _t` and call `_t(...)` to avoid shadowing the lazy alias). Prefer the local-alias form to avoid confusion:

```python
        from django.utils.translation import gettext as _t
        ...
                alt = _t("Image {n} of {total}").format(n=i, total=total)
```

- [ ] **Step 4: Create `templates/courses/elements/galleryelement.html`**

```django
{% comment %}Student-facing image carousel. `figures` is the resolved, ordered
list ({url, alt, desc}) from GalleryElement.render(); unresolved ids are already
dropped. `desc` is sanitised at save() and emitted with |safe (math stays as raw
\(...\) text, typeset client-side by math.js over .el--gallery). A .gallery__desc
is emitted for EVERY figure (empty when no desc) so gallery.js can reserve a
uniform height. No JS: figures show stacked; gallery.js enhances into a carousel.
{% endcomment %}
<div class="el el--gallery" data-gallery data-desc-pos="{{ desc_pos }}">
  {% for f in figures %}
    <figure class="gallery__item">
      {% if desc_pos == "above" %}
        <div class="gallery__desc">{{ f.desc|safe }}</div>
      {% endif %}
      <div class="gallery__frame"><img src="{{ f.url }}" alt="{{ f.alt }}"></div>
      {% if desc_pos == "below" %}
        <div class="gallery__desc">{{ f.desc|safe }}</div>
      {% endif %}
    </figure>
  {% endfor %}
</div>
```

- [ ] **Step 5: Add `.el--gallery` to `math.js`**

In `courses/static/courses/js/math.js`, change the `renderInlineText` selector (currently `".el--text, .el--table"`) to include gallery descriptions:

```javascript
    (root || document).querySelectorAll(".el--text, .el--table, .el--gallery").forEach(function (el) {
```

- [ ] **Step 6: Add `_gallery_has_math` + OR-branches in `courses/views.py`**

Add next to `_table_has_math`:

```python
def _gallery_has_math(el):
    from courses.models import GalleryElement

    if not isinstance(el, GalleryElement):
        return False
    data = el.normalize_data(el.data)
    return any(has_math_delimiters(img.get("desc", "")) for img in data["images"])
```

In `build_lesson_context` `has_math` (the `or any(_table_has_math(...))` line ~165) append:

```python
        or any(_gallery_has_math(el.content_object) for el in elements)
```

Do the same in the quiz-consumption `has_math` (the `or any(_table_has_math(...))` line ~490). Leave the results-page builder untouched (content elements excluded there).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_gallery_render.py -v`
Expected: PASS (all 5)

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check courses/models.py courses/views.py tests/test_gallery_render.py
uv run ruff format courses/models.py courses/views.py tests/test_gallery_render.py
git add courses/models.py courses/views.py courses/static/courses/js/math.js templates/courses/elements/galleryelement.html tests/test_gallery_render.py
git commit -m "feat(gallery): student render template, render(), math scope + has_math gating"
```

---

### Task 4: `GalleryElementForm` + validation + `editor_rows`

The form: optional `data` JSONField, `clean_data` enforcing bounds + course-scoped image ids (duplicates allowed), and an `editor_rows` helper that resolves ids → `{id, thumb_url, desc}` for the editor partial (from submitted data when bound, else from the instance).

**Files:**
- Modify: `courses/element_forms.py`
- Test: `tests/test_gallery_form.py` (create)

**Interfaces:**
- Consumes: `GalleryElement.normalize_data`, `_CourseScopedMediaForm`, `MediaAsset`.
- Produces: `GalleryElementForm` (registered in `FORM_FOR_TYPE["gallery"]`); `GalleryElementForm(course=...).editor_rows -> list[{"id": int, "thumb_url": str, "desc": str}]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gallery_form.py
import pytest
from courses.element_forms import GalleryElementForm, FORM_FOR_TYPE
from tests.factories import make_course, make_image_asset

pytestmark = pytest.mark.django_db


def _post(images, desc_pos="below"):
    import json
    return {"data": json.dumps({"desc_pos": desc_pos, "images": images})}


def test_registered():
    assert FORM_FOR_TYPE["gallery"] is GalleryElementForm


def test_valid_two_images():
    course = make_course()
    a1, a2 = make_image_asset(course), make_image_asset(course)
    form = GalleryElementForm(data=_post([{"media": a1.pk, "desc": "x"}, {"media": a2.pk, "desc": ""}]), course=course)
    assert form.is_valid(), form.errors
    assert len(form.cleaned_data["data"]["images"]) == 2


def test_rejects_fewer_than_two():
    course = make_course()
    a1 = make_image_asset(course)
    form = GalleryElementForm(data=_post([{"media": a1.pk, "desc": "x"}]), course=course)
    assert not form.is_valid()


def test_rejects_more_than_twenty():
    course = make_course()
    imgs = [{"media": make_image_asset(course).pk, "desc": ""} for _ in range(21)]
    form = GalleryElementForm(data=_post(imgs), course=course)
    assert not form.is_valid()


def test_rejects_foreign_or_non_image_media():
    course, other = make_course(), make_course()
    a1 = make_image_asset(course)
    foreign = make_image_asset(other)
    form = GalleryElementForm(data=_post([{"media": a1.pk, "desc": ""}, {"media": foreign.pk, "desc": ""}]), course=course)
    assert not form.is_valid()


def test_rejects_non_list_images():
    course = make_course()
    import json
    form = GalleryElementForm(data={"data": json.dumps({"desc_pos": "below", "images": "nope"})}, course=course)
    assert not form.is_valid()


def test_duplicates_allowed():
    course = make_course()
    a1 = make_image_asset(course)
    form = GalleryElementForm(data=_post([{"media": a1.pk, "desc": ""}, {"media": a1.pk, "desc": ""}]), course=course)
    assert form.is_valid(), form.errors


def test_editor_rows_from_instance():
    from courses.models import GalleryElement
    course = make_course()
    a1 = make_image_asset(course)
    el = GalleryElement.objects.create(data={"desc_pos": "below", "images": [{"media": a1.pk, "desc": "cap"}]})
    rows = GalleryElementForm(instance=el, course=course).editor_rows
    assert rows == [{"id": a1.pk, "thumb_url": a1.file.url, "desc": "cap"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gallery_form.py -v`
Expected: FAIL (`ImportError: cannot import name 'GalleryElementForm'`)

- [ ] **Step 3: Implement `GalleryElementForm` in `courses/element_forms.py`**

Add the import `from courses.models import GalleryElement` near the other model imports. Add the form (place after `TableElementForm`):

```python
class GalleryElementForm(_CourseScopedMediaForm):
    """Image gallery/carousel. `data` JSON holds {desc_pos, images:[{media,desc}]};
    course-scoping is enforced against the referenced image ids in clean_data."""

    media_kind = "image"

    class Meta:
        model = GalleryElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same rationale as TableElementForm: JSONField(default=dict) is required
        # and {} is empty, so an unedited add would fail before clean_data.
        self.fields["data"].required = False

    def clean_data(self):
        data = GalleryElement.normalize_data(self.cleaned_data.get("data"))
        # normalize_data already dropped entries without a valid int media, so a
        # count shortfall here also catches "some ids were malformed".
        raw = self.cleaned_data.get("data")
        if isinstance(raw, dict) and not isinstance(raw.get("images"), list):
            raise forms.ValidationError(_("A gallery needs a list of images."))
        images = data["images"]
        if len(images) < GalleryElement.MIN_IMAGES:
            raise forms.ValidationError(
                _("A gallery needs at least %(n)d images.") % {"n": GalleryElement.MIN_IMAGES}
            )
        if len(images) > GalleryElement.MAX_IMAGES:
            raise forms.ValidationError(
                _("A gallery is limited to %(n)d images.") % {"n": GalleryElement.MAX_IMAGES}
            )
        ids = {img["media"] for img in images}
        allowed = set(
            MediaAsset.objects.filter(course=self.course, kind="image", pk__in=ids).values_list("pk", flat=True)
        )
        if ids - allowed:
            raise forms.ValidationError(_("A gallery image is not an image in this course."))
        return data

    @property
    def editor_rows(self):
        """Resolved [{id, thumb_url, desc}] for the editor: from submitted data
        when bound (so an invalid re-render keeps the author's picks), else from
        the instance. Unresolved ids are dropped."""
        if self.is_bound:
            source = GalleryElement.normalize_data(self._raw_data_json())
        else:
            source = GalleryElement.normalize_data(getattr(self.instance, "data", {}))
        ids = [img["media"] for img in source["images"]]
        assets = MediaAsset.objects.in_bulk(ids)
        rows = []
        for img in source["images"]:
            asset = assets.get(img["media"])
            if asset is not None:
                rows.append({"id": asset.pk, "thumb_url": asset.file.url, "desc": img["desc"]})
        return rows

    def _raw_data_json(self):
        import json

        try:
            return json.loads(self.data.get("data") or "{}")
        except (ValueError, TypeError):
            return {}
```

Register in `FORM_FOR_TYPE`: add `"gallery": GalleryElementForm,` after `"table": TableElementForm,`.

> Note: `_CourseScopedMediaForm.__init__` only touches a `media` field if present; `GalleryElementForm` has none, so subclassing simply gives us `self.course`. That is intentional.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gallery_form.py -v`
Expected: PASS (all 8)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/element_forms.py tests/test_gallery_form.py
uv run ruff format courses/element_forms.py tests/test_gallery_form.py
git add courses/element_forms.py tests/test_gallery_form.py
git commit -m "feat(gallery): GalleryElementForm (2-20 bounds, course-scoped ids) + editor_rows"
```

---

### Task 5: Manage-UI plumbing (dispatch, labels, icon, add-menu)

Wire `"gallery"` through every dispatch/allow-list site so the add-card opens the editor and save persists. Add the icon symbol and add-menu card.

**Files:**
- Modify: `courses/views_manage.py`, `courses/builder.py`, `templates/courses/manage/editor/_add_menu.html`, `templates/courses/manage/_icon_sprite.html`
- Test: `tests/test_gallery_manage.py` (create)

**Interfaces:**
- Consumes: `GalleryElementForm`, `_render_open_form`.
- Produces: `type_key == "gallery"` accepted by `element_add`/`element_save`; `_EDITOR_TYPE_LABELS["gallery"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gallery_manage.py
import json
import pytest
from django.template.loader import render_to_string
from django.urls import reverse
from courses.models import Element, GalleryElement
from tests.factories import make_course, make_unit, make_image_asset, make_editor_user, TEST_PASSWORD

pytestmark = pytest.mark.django_db


def _login(client, user):
    client.login(username=user.username, password=TEST_PASSWORD)


def test_add_menu_has_gallery_card():
    # Partial-independent: the add-menu card is what routes to element_add.
    html = render_to_string("courses/manage/editor/_add_menu.html")
    assert 'data-add-type="gallery"' in html


def test_save_persists_gallery(client):
    course = make_course()
    unit = make_unit(course)
    a1, a2 = make_image_asset(course), make_image_asset(course)
    user = make_editor_user(course)
    _login(client, user)
    payload = {
        "type": "gallery",
        "title": "My gallery",
        "data": json.dumps({"desc_pos": "below", "images": [{"media": a1.pk, "desc": "x"}, {"media": a2.pk, "desc": ""}]}),
    }
    resp = client.post(reverse("courses:element_save", args=[unit.pk, "new"]), payload)
    assert resp.status_code in (200, 201)
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, GalleryElement)
    assert len(el.content_object.data["images"]) == 2
```

> Adapt `reverse(...)` arg names and the exact POST shape to match the existing `tests/test_table_*` manage tests (grep `element_add`/`element_save` in tests). Reuse existing factory helpers; add `make_unit`/`make_editor_user` only if absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gallery_manage.py -v`
Expected: FAIL (`test_add_menu_has_gallery_card`: no gallery card yet; `test_save_persists_gallery`: `element_save` returns `HttpResponseBadRequest("bad type")`)

- [ ] **Step 3: Add `"gallery"` to the allow-lists and scope tuples**

In `courses/views_manage.py`:
- `element_add` allow-list (~845): add `"gallery",`.
- `element_save` allow-list (~876): add `"gallery",`.
- `_render_open_form` scope tuple (~759): change `("image", "video", "dragtoimagequestion")` → `("image", "video", "dragtoimagequestion", "gallery")`.
- `element_form` scope tuple (~946): same change.
- `_EDITOR_TYPE_LABELS`: add `"gallery": gettext_lazy("Gallery"),`.

In `courses/builder.py` generic branch (~304): change `("image", "video")` → `("image", "video", "gallery")`.

- [ ] **Step 4: Add the icon symbol**

In `templates/courses/manage/_icon_sprite.html`, add (monochrome `currentColor`, `viewBox="0 0 16 16"` to match `el-image`, its nearest sibling — a stacked-photos glyph; the frontend-design pass may refine it):

```django
  <symbol id="el-gallery" viewBox="0 0 16 16"><path fill="currentColor" d="M3 2a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1zm9 1a.5.5 0 0 1 .5.5V8l-2.2-1.6a.5.5 0 0 0-.57.03L7 8.5 5.5 7.5a.5.5 0 0 0-.6.03L3.5 8.7V3.5A.5.5 0 0 1 4 3z"/><path fill="currentColor" d="M4 13v1a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1v9z"/></symbol>
```

- [ ] **Step 5: Add the add-menu card**

In `templates/courses/manage/editor/_add_menu.html`, next to the table card:

```django
      <button type="button" class="typecard" data-add-type="gallery"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-gallery"/></svg>{% trans "Gallery" %}</button>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_gallery_manage.py -v`
Expected: PASS
(Both checks are partial-independent — `element_save`'s success path refreshes the element list and closes the open form; it does not re-render `_edit_gallery.html`. If this codebase's `element_save` DOES re-render the editor on success, run Task 6 first, since the host form includes `_edit_gallery.html`.)

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check courses/views_manage.py courses/builder.py tests/test_gallery_manage.py
uv run ruff format courses/views_manage.py courses/builder.py tests/test_gallery_manage.py
git add courses/views_manage.py courses/builder.py templates/courses/manage/_icon_sprite.html templates/courses/manage/editor/_add_menu.html tests/test_gallery_manage.py
git commit -m "feat(gallery): manage-UI plumbing (dispatch, labels, icon, add card)"
```

---

### Task 6: Editor partial `_edit_gallery.html` + editor CSS

The server-rendered editor: hidden `data` input, desc-position toggle, add-image button, and a list of image rows (thumbnail + contenteditable description with a B/I/U + math toolbar + remove + up/down), seeded from `form.editor_rows`.

**Files:**
- Create: `templates/courses/manage/editor/_edit_gallery.html`
- Modify: `courses/static/courses/css/courses.css` (editor styles)
- Test: `tests/test_gallery_editor_partial.py` (create)

**Interfaces:**
- Consumes: `form.editor_rows` (Task 4). Produces the DOM contract `gallery_editor.js` (Task 7) enhances: `[data-gallery-editor]`, `input[name="data"]`, `[data-gallery-rows]`, `[data-gallery-add]`, `[data-desc-pos]`, row template `[data-gallery-row]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gallery_editor_partial.py
import pytest
from django.template.loader import render_to_string
from courses.element_forms import GalleryElementForm
from courses.models import GalleryElement
from tests.factories import make_course, make_image_asset

pytestmark = pytest.mark.django_db


def test_partial_seeds_rows_and_controls():
    course = make_course()
    a1, a2 = make_image_asset(course), make_image_asset(course)
    el = GalleryElement.objects.create(
        data={"desc_pos": "above", "images": [{"media": a1.pk, "desc": "<b>one</b>"}, {"media": a2.pk, "desc": ""}]}
    )
    form = GalleryElementForm(instance=el, course=course)
    html = render_to_string("courses/manage/editor/_edit_gallery.html", {"form": form})
    assert "data-gallery-editor" in html
    assert 'name="data"' in html
    assert html.count("data-gallery-row") >= 2      # two seeded rows
    assert "<b>one</b>" in html                       # desc seeded into contenteditable
    assert a1.file.url in html                        # thumbnail
    assert 'value="above"' in html or "above" in html # desc_pos toggle reflects stored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gallery_editor_partial.py -v`
Expected: FAIL (template does not exist)

- [ ] **Step 3: Create `templates/courses/manage/editor/_edit_gallery.html`**

```django
{% load i18n %}
{% comment %}Gallery editor. The hidden name="data" field (bound to the form) is
the SOLE authoritative input; the rows + toggle are name-less JS UI that
gallery_editor.js mirrors into it. Rows are server-rendered from form.editor_rows
so an existing gallery shows its saved state (and an invalid re-render keeps the
author's picks). One row is a template for JS-cloned new rows.{% endcomment %}
<div class="el-editor el-editor--gallery" data-gallery-editor>
  <input type="hidden" name="data" value="{{ form.data.data|default:'' }}">

  <div class="gallery-editor__controls">
    <label>{% trans "Description position" %}
      <select data-desc-pos>
        <option value="below" {% if form.instance.normalized_data.desc_pos == "below" %}selected{% endif %}>{% trans "Below image" %}</option>
        <option value="above" {% if form.instance.normalized_data.desc_pos == "above" %}selected{% endif %}>{% trans "Above image" %}</option>
      </select>
    </label>
    <button type="button" class="btn btn--small" data-gallery-add data-pick-media="image" data-pick-mode="append">{% trans "Add image" %}</button>
  </div>

  <div class="gallery-editor__toolbar" data-gallery-toolbar hidden>
    <button type="button" data-cmd="bold" title="{% trans 'Bold' %}"><b>B</b></button>
    <button type="button" data-cmd="italic" title="{% trans 'Italic' %}"><i>I</i></button>
    <button type="button" data-cmd="underline" title="{% trans 'Underline' %}"><u>U</u></button>
    <button type="button" data-cmd="math" title="{% trans 'Insert math' %}">∑</button>
  </div>

  <ol class="gallery-editor__rows" data-gallery-rows>
    {% for row in form.editor_rows %}
    <li class="gallery-editor__row" data-gallery-row data-media-id="{{ row.id }}">
      <img class="gallery-editor__thumb" src="{{ row.thumb_url }}" alt="">
      <div class="gallery-editor__desc" contenteditable="true" data-gallery-desc>{{ row.desc|safe }}</div>
      <span class="gallery-editor__ctl">
        <button type="button" data-gallery-up title="{% trans 'Move up' %}">↑</button>
        <button type="button" data-gallery-down title="{% trans 'Move down' %}">↓</button>
        <button type="button" data-gallery-remove title="{% trans 'Remove' %}">✕</button>
      </span>
    </li>
    {% endfor %}
  </ol>

  {% comment %}Hidden prototype row cloned by gallery_editor.js for new picks.{% endcomment %}
  <template data-gallery-row-template>
    <li class="gallery-editor__row" data-gallery-row data-media-id="">
      <img class="gallery-editor__thumb" src="" alt="">
      <div class="gallery-editor__desc" contenteditable="true" data-gallery-desc></div>
      <span class="gallery-editor__ctl">
        <button type="button" data-gallery-up title="{% trans 'Move up' %}">↑</button>
        <button type="button" data-gallery-down title="{% trans 'Move down' %}">↓</button>
        <button type="button" data-gallery-remove title="{% trans 'Remove' %}">✕</button>
      </span>
    </li>
  </template>

  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  {% for e in form.data.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 4: Add editor CSS to `courses/static/courses/css/courses.css`**

Add alongside the table-editor styles (thumbnails, row layout, toolbar). Keep it minimal here; the frontend-design pass (Task 10) refines:

```css
.el-editor--gallery .gallery-editor__rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .5rem; }
.el-editor--gallery .gallery-editor__row { display: flex; align-items: flex-start; gap: .5rem; padding: .5rem; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); }
.el-editor--gallery .gallery-editor__thumb { width: 64px; height: 64px; object-fit: cover; border-radius: var(--radius-sm); flex: 0 0 auto; }
.el-editor--gallery .gallery-editor__desc { flex: 1 1 auto; min-height: 2.5rem; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: .25rem .5rem; }
.el-editor--gallery .gallery-editor__ctl { display: flex; flex-direction: column; gap: .25rem; flex: 0 0 auto; }
.el-editor--gallery [data-gallery-row-template] { display: none; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_gallery_editor_partial.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_edit_gallery.html courses/static/courses/css/courses.css tests/test_gallery_editor_partial.py
git commit -m "feat(gallery): editor partial (rows, toggle, toolbar) + editor CSS"
```

---

### Task 7: `gallery_editor.js` + media-picker append mode + editor e2e

Progressive enhancement of the editor: mirror UI → hidden `data`, add images via the picker (append mode), reorder, per-row B/I/U + math. Adds a small additive `media_picker.js` callback so a multi-image gallery can reuse the picker modal.

**Files:**
- Create: `courses/static/courses/js/gallery_editor.js`
- Modify: `courses/static/courses/js/media_picker.js`, `templates/courses/manage/editor/editor.html`
- Test: `tests/test_e2e_gallery.py` (create; the editor half)

**Interfaces:**
- Consumes: the `_edit_gallery.html` DOM contract, `window.libliMathInput`.
- Produces: `window.libliInitGalleryEditor(root)`; `window.libliGalleryAdd(editor, id, name, url)` (called by media_picker append mode).

- [ ] **Step 1: Write the failing e2e (editor half)**

```python
# tests/test_e2e_gallery.py
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_gallery_editor_add_reorder_save(live_server, page, editor_course_with_images):
    """Drive the REAL editor UI: add two images, type a math description,
    reorder, save; assert the gallery persists with two images."""
    ctx = editor_course_with_images  # fixture: course + unit + >=2 image assets + logged-in editor page
    page.goto(ctx.editor_url)
    page.get_by_role("button", name="Gallery").click()          # add-menu card
    # add two images via the picker (fixture images appear in the modal)
    page.get_by_role("button", name="Add image").click()
    page.locator(".asset-pick").first.click()
    page.get_by_role("button", name="Add image").click()
    page.locator(".asset-pick").nth(1).click()
    # type a description with math into the first row
    first_desc = page.locator("[data-gallery-row] [data-gallery-desc]").first
    first_desc.click()
    first_desc.type("area ")
    # (math insert via toolbar covered by the student-side e2e; keep editor test focused)
    page.get_by_role("button", name="Save").click()
    # assert persisted
    from courses.models import GalleryElement
    assert GalleryElement.objects.count() == 1
    assert len(GalleryElement.objects.get().data["images"]) == 2
```

> Model the fixture and login flow on the existing `tests/test_e2e_table.py` / `tests/test_e2e_slideshow.py` (grep for `live_server`, `page`, and the editor-login fixture). Reuse them; only add a `editor_course_with_images` fixture if none is close enough.

- [ ] **Step 2: Run e2e to verify it fails**

Run: `uv run pytest tests/test_e2e_gallery.py -v -m e2e`
Expected: FAIL (no gallery_editor.js; picker append mode absent)

- [ ] **Step 3: Add append mode to `media_picker.js`**

Minimal additive change. In the `[data-pick-media]` click handler, detect append mode and remember the gallery editor; in `selectAsset`, branch to the gallery hook when in append mode. Concretely:

- At the top of `wireEditorPicker`, add a module var `var appendTarget = null;`.
- In the pick handler, after computing `kind`, before the fetch:

```javascript
      appendTarget = pick.getAttribute("data-pick-mode") === "append"
        ? pick.closest("[data-gallery-editor]")
        : null;
```

- At the very start of `selectAsset(id, name, url)`:

```javascript
      if (appendTarget && window.libliGalleryAdd) {
        window.libliGalleryAdd(appendTarget, id, name, url);
        var t = appendTarget; appendTarget = null;
        closeModal();
        return;
      }
```

(The existing `<select name='media'>` path is untouched when `appendTarget` is null.)

- [ ] **Step 4: Create `courses/static/courses/js/gallery_editor.js`**

```javascript
(function () {
  "use strict";

  // Gallery editor: progressively enhance [data-gallery-editor] blocks. The
  // hidden input[name="data"] is the SOLE authoritative field; rows + the
  // desc-position select are name-less JS UI mirrored into it via serialize().
  // New rows are cloned from the <template data-gallery-row-template>; images are
  // added via media_picker.js "append mode" (window.libliGalleryAdd below).

  var editors = [];

  function wire(editor) {
    if (editor.dataset.galleryWired) return;
    editor.dataset.galleryWired = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var rows = editor.querySelector("[data-gallery-rows]");
    var posSel = editor.querySelector("[data-desc-pos]");
    var toolbar = editor.querySelector("[data-gallery-toolbar]");
    var tmpl = editor.querySelector("[data-gallery-row-template]");
    if (!hidden || !rows) return;
    editor._galleryTmpl = tmpl;

    function rowEls() {
      return Array.prototype.slice.call(rows.querySelectorAll("[data-gallery-row]"));
    }

    function serialize() {
      var images = rowEls().map(function (li) {
        var desc = li.querySelector("[data-gallery-desc]");
        return {
          media: parseInt(li.getAttribute("data-media-id"), 10),
          desc: desc ? desc.innerHTML : "",
        };
      }).filter(function (img) { return !isNaN(img.media); });
      hidden.value = JSON.stringify({
        desc_pos: (posSel && posSel.value) || "below",
        images: images,
      });
    }
    editor._gallerySerialize = serialize;

    // Focus tracking for the shared toolbar (which desc box commands apply to).
    var focusedDesc = null;
    rows.addEventListener("focusin", function (e) {
      var d = e.target.closest("[data-gallery-desc]");
      if (d) { focusedDesc = d; if (toolbar) toolbar.hidden = false; }
    });

    rows.addEventListener("input", serialize);

    rows.addEventListener("click", function (e) {
      var li = e.target.closest("[data-gallery-row]");
      if (!li) return;
      if (e.target.closest("[data-gallery-remove]")) { li.remove(); serialize(); return; }
      if (e.target.closest("[data-gallery-up]")) {
        var prev = li.previousElementSibling;
        if (prev) rows.insertBefore(li, prev);
        serialize(); return;
      }
      if (e.target.closest("[data-gallery-down]")) {
        var next = li.nextElementSibling;
        if (next) rows.insertBefore(next, li);
        serialize(); return;
      }
    });

    if (posSel) posSel.addEventListener("change", serialize);

    if (toolbar) {
      toolbar.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-cmd]");
        if (!btn || !focusedDesc) return;
        var cmd = btn.getAttribute("data-cmd");
        focusedDesc.focus();
        if (cmd === "bold" || cmd === "italic" || cmd === "underline") {
          document.execCommand("styleWithCSS", false, false);
          document.execCommand(cmd, false, null);
          serialize();
        } else if (cmd === "math") {
          if (!window.libliMathInput) return;
          var sel = window.getSelection();
          var range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
          var cell = focusedDesc;
          window.libliMathInput.open(function (latex) {
            cell.focus();
            var node = document.createTextNode("\\(" + latex + "\\)");
            if (range) {
              range.deleteContents(); range.insertNode(node);
              range.setStartAfter(node); range.collapse(true);
              sel.removeAllRanges(); sel.addRange(range);
            } else {
              cell.appendChild(node);
            }
            serialize();
          });
        }
      });
    }

    // Serialize on init only when the hidden field is empty (add path); an
    // invalid re-render already carries the submitted JSON.
    if (hidden.value === "") serialize();
    editors.push(editor);
  }

  // Called by media_picker.js append mode when the author picks an image.
  window.libliGalleryAdd = function (editor, id, name, url) {
    var tmpl = editor._galleryTmpl;
    var rows = editor.querySelector("[data-gallery-rows]");
    if (!tmpl || !rows) return;
    var li = tmpl.content.firstElementChild.cloneNode(true);
    li.setAttribute("data-media-id", String(id));
    var img = li.querySelector(".gallery-editor__thumb");
    if (img && url) img.src = url;
    rows.appendChild(li);
    if (editor._gallerySerialize) editor._gallerySerialize();
  };

  function initGalleryEditor(root) {
    (root || document).querySelectorAll("[data-gallery-editor]").forEach(wire);
  }

  window.libliInitGalleryEditor = initGalleryEditor;
  initGalleryEditor(document);
})();
```

- [ ] **Step 5: Load `gallery_editor.js` in the editor page**

In `templates/courses/manage/editor/editor.html`, next to the `table_editor.js`/`media_picker.js` `<script>` tags, add:

```django
  <script src="{% static 'courses/js/gallery_editor.js' %}" defer></script>
```

Ensure whatever re-init hook re-wires editor fragments also calls `window.libliInitGalleryEditor` (grep for `libliInitTableEditor` — add a sibling call wherever it is invoked after an editor fragment swap).

- [ ] **Step 6: Run the e2e to verify it passes**

Run: `uv run pytest tests/test_e2e_gallery.py -v -m e2e`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/gallery_editor.js courses/static/courses/js/media_picker.js templates/courses/manage/editor/editor.html tests/test_e2e_gallery.py
git commit -m "feat(gallery): gallery_editor.js + media-picker append mode + editor e2e"
```

---

### Task 8: `gallery.js` student carousel + student CSS + script wiring + carousel e2e

The multi-instance carousel: `querySelectorAll`, per-instance state, arrow + interactive dots, clamp/no-wrap boundary, cross-fade, `aria-hidden` inactive figures, sr-only status, focus-scoped keys, and ResizeObserver-driven stable-frame reservations (covers resize + KaTeX re-typeset).

**Files:**
- Create: `courses/static/courses/js/gallery.js`
- Modify: `courses/static/courses/css/courses.css`, `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html`
- Test: `tests/test_e2e_gallery.py` (add the student-carousel cases)

**Interfaces:**
- Consumes: `[data-gallery]` DOM (Task 3), `window.GALLERY_I18N`.

- [ ] **Step 1: Write the failing e2e (student half)**

```python
# add to tests/test_e2e_gallery.py

def test_student_carousel_nav_and_math(live_server, page, lesson_with_gallery):
    """A lesson with a gallery (one desc has math): carousel shows one figure,
    next advances, inactive figures are aria-hidden, math renders (.katex)."""
    ctx = lesson_with_gallery  # fixture: unit with a 2-image gallery, first desc = r"\(x^2\)"
    page.goto(ctx.lesson_url)
    gallery = page.locator("[data-gallery]").first
    # exactly one visible figure
    assert gallery.locator(".gallery__item:not([aria-hidden='true'])").count() == 1
    # math typeset in a description
    assert gallery.locator(".gallery__desc .katex").count() >= 1
    # next advances the status
    page.get_by_role("button", name="Next image").click()
    assert "2" in gallery.locator("[role='status']").inner_text()
    # boundary: next is disabled on the last image
    assert page.get_by_role("button", name="Next image").is_disabled()


def test_two_galleries_are_independent(live_server, page, lesson_with_two_galleries):
    ctx = lesson_with_two_galleries
    page.goto(ctx.lesson_url)
    galleries = page.locator("[data-gallery]")
    # advance the first only
    galleries.nth(0).get_by_role("button", name="Next image").click()
    assert "2" in galleries.nth(0).locator("[role='status']").inner_text()
    assert "1" in galleries.nth(1).locator("[role='status']").inner_text()
```

- [ ] **Step 2: Run e2e to verify it fails**

Run: `uv run pytest tests/test_e2e_gallery.py -v -m e2e`
Expected: FAIL (no gallery.js)

- [ ] **Step 3: Create `courses/static/courses/js/gallery.js`**

```javascript
(function () {
  "use strict";

  var galleries = document.querySelectorAll("[data-gallery]");
  if (!galleries.length) return;

  var i18n = window.GALLERY_I18N ||
    { prev: "Previous image", next: "Next image", nav: "Gallery", go: "Go to image {n}", pos: "Image {n} of {total}" };
  var DOTS_MAX = 12;
  var FADE_MS = 320; // MUST match the .el--gallery cross-fade transition in courses.css

  function iconBtn(cls, pathD, label) {
    var b = document.createElement("button");
    b.type = "button"; b.className = cls;
    b.setAttribute("aria-label", label);
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }

  function initOne(container) {
    var items = Array.prototype.slice.call(container.querySelectorAll(".gallery__item"));
    if (items.length < 2) return; // 0/1 figure: leave the no-JS stack, no bar
    container.classList.add("gallery--js");

    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
    var idx = -1;
    var pending = null;

    // Stage overlays the figures; bar is the controls.
    var stage = document.createElement("div");
    stage.className = "gallery__stage";
    items[0].parentNode.insertBefore(stage, items[0]);
    // At rest every item is aria-hidden; show(0) reveals the first. Items stay
    // laid out (CSS: absolute, height auto) so measure() can read their natural
    // height even while invisible.
    items.forEach(function (it) { stage.appendChild(it); it.setAttribute("aria-hidden", "true"); });

    var prev = iconBtn("gallery__prev", "M15 6l-6 6 6 6", i18n.prev);
    var next = iconBtn("gallery__next", "M9 6l6 6-6 6", i18n.next);

    var useDots = items.length <= DOTS_MAX;
    var dots = [];
    var indicator;
    if (useDots) {
      indicator = document.createElement("div");
      indicator.className = "gallery__dots";
      items.forEach(function (_it, k) {
        var d = document.createElement("button");
        d.type = "button"; d.className = "gallery__dot";
        d.setAttribute("aria-label", i18n.go.replace("{n}", k + 1));
        d.addEventListener("click", function () { show(k); });
        indicator.appendChild(d);
        dots.push(d);
      });
    } else {
      indicator = document.createElement("span");
      indicator.className = "gallery__counter";
      indicator.setAttribute("aria-hidden", "true");
    }

    var status = document.createElement("span");
    status.className = "gallery__status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    var bar = document.createElement("nav");
    bar.className = "gallery__bar";
    bar.setAttribute("aria-label", i18n.nav);
    bar.appendChild(prev);
    bar.appendChild(indicator);
    bar.appendChild(next);
    bar.appendChild(status);
    container.appendChild(bar);

    function posText() { return i18n.pos.replace("{n}", idx + 1).replace("{total}", items.length); }
    function updateIndicator() {
      if (useDots) {
        dots.forEach(function (d, k) {
          d.classList.toggle("is-active", k === idx);
          if (k === idx) { d.setAttribute("aria-current", "true"); } else { d.removeAttribute("aria-current"); }
        });
      } else {
        indicator.textContent = (idx + 1) + " / " + items.length;
      }
      status.textContent = posText();
    }

    function clamp(n) { return Math.max(0, Math.min(items.length - 1, n)); }
    function settleHidden(it) {
      it.classList.remove("is-active");
      it.style.opacity = "";
      it.setAttribute("aria-hidden", "true");
    }
    function finalizePending() {
      if (!pending) return;
      clearTimeout(pending.timer);
      if (pending.out && pending.out !== pending.inn) settleHidden(pending.out);
      pending.inn.classList.add("is-active");
      pending.inn.style.opacity = "";
      pending = null;
    }
    function show(n) {
      var target = clamp(n);
      if (idx !== -1 && target === idx) return;
      finalizePending();
      var out = items[idx];
      idx = target;
      var inn = items[idx];
      updateIndicator();
      prev.disabled = idx === 0;
      prev.setAttribute("aria-disabled", idx === 0 ? "true" : "false");
      next.disabled = idx === items.length - 1;
      next.setAttribute("aria-disabled", idx === items.length - 1 ? "true" : "false");
      inn.removeAttribute("aria-hidden");
      if (!out) {
        inn.style.opacity = "";
        inn.classList.add("is-active");
        return;
      }
      out.setAttribute("aria-hidden", "true");  // AT sees only the incoming slide during the fade
      inn.style.opacity = "0";
      void inn.offsetWidth;
      inn.classList.add("is-active");
      inn.style.opacity = "1";
      out.style.opacity = "0";
      var delay = reduce && reduce.matches ? 0 : FADE_MS;
      pending = { out: out, inn: inn, timer: null };
      pending.timer = setTimeout(function () { settleHidden(out); inn.style.opacity = ""; pending = null; }, delay);
    }

    prev.addEventListener("click", function () { show(idx - 1); });
    next.addEventListener("click", function () { show(idx + 1); });

    container.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      var t = e.target, tag = t && t.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.isContentEditable)) return;
      if (!container.contains(t)) return;
      e.preventDefault();
      show(idx + (e.key === "ArrowRight" ? 1 : -1));
    });

    // Stable-frame reservation: reserve the tallest figure + tallest desc so the
    // frame offset is constant across slides. Recompute on resize AND whenever a
    // figure changes size (fonts / KaTeX typeset) via ResizeObserver. Clear the
    // reservation before measuring so we read natural heights, not the reserve.
    var descs = Array.prototype.slice.call(container.querySelectorAll(".gallery__desc"));
    function measure() {
      stage.style.minHeight = "";
      descs.forEach(function (d) { d.style.minHeight = ""; });
      var maxDesc = 0;
      descs.forEach(function (d) { maxDesc = Math.max(maxDesc, d.offsetHeight); });
      descs.forEach(function (d) { d.style.minHeight = maxDesc + "px"; });
      var maxItem = 0;
      items.forEach(function (it) { maxItem = Math.max(maxItem, it.offsetHeight); });
      stage.style.minHeight = maxItem + "px";
    }
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { measure(); });
      items.forEach(function (it) { ro.observe(it); });
    }
    window.addEventListener("resize", measure);

    show(0);
    measure();
  }

  Array.prototype.forEach.call(galleries, initOne);
})();
```

- [ ] **Step 4: Add student CSS to `courses/static/courses/css/courses.css`**

```css
.el--gallery .gallery__frame { width: 100%; aspect-ratio: 4 / 3; max-height: 70vh; display: flex; align-items: center; justify-content: center; }
.el--gallery .gallery__frame img { max-width: 100%; max-height: 100%; object-fit: contain; }
.el--gallery .gallery__desc { text-align: center; }
/* No-JS: figures simply stack. JS overlays them for the cross-fade. Inactive
   items stay laid out (absolute, height auto) so gallery.js can measure their
   natural height for the stable-frame reservation; opacity + aria-hidden hide
   them, pointer-events:none keeps them non-interactive. */
.el--gallery.gallery--js .gallery__stage { position: relative; }
.el--gallery.gallery--js .gallery__item { position: absolute; top: 0; left: 0; width: 100%; opacity: 0; pointer-events: none; transition: opacity 320ms ease; }  /* 320ms == FADE_MS */
.el--gallery.gallery--js .gallery__item.is-active { opacity: 1; pointer-events: auto; }
.el--gallery .gallery__bar { display: flex; align-items: center; justify-content: center; gap: .5rem; margin-top: .5rem; }
.el--gallery .gallery__dots { display: flex; gap: .35rem; }
.el--gallery .gallery__dot { width: .6rem; height: .6rem; padding: 0; border-radius: 50%; border: 1px solid var(--border-strong); background: transparent; }
.el--gallery .gallery__dot.is-active { background: currentColor; }
.el--gallery .gallery__status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (prefers-reduced-motion: reduce) { .el--gallery.gallery--js .gallery__item { transition: none; } }
```

> Keep the CSS `320ms` and `gallery.js` `FADE_MS = 320` in lockstep (single-source note in both files).

- [ ] **Step 5: Load `gallery.js` + `GALLERY_I18N` on the taking pages**

In both `templates/courses/lesson_unit.html` and `templates/courses/quiz_unit.html`, next to the `slideshow.js` block, add:

```django
  <script>window.GALLERY_I18N = { prev: "{% trans 'Previous image' %}", next: "{% trans 'Next image' %}", nav: "{% trans 'Gallery' %}", go: "{% trans 'Go to image {n}' %}", pos: "{% trans 'Image {n} of {total}' %}" };</script>
  <script src="{% static 'courses/js/gallery.js' %}" defer></script>
```

- [ ] **Step 6: Run the full e2e suite to verify it passes**

Run: `uv run pytest tests/test_e2e_gallery.py -v -m e2e`
Expected: PASS (editor + both carousel cases)

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/gallery.js courses/static/courses/css/courses.css templates/courses/lesson_unit.html templates/courses/quiz_unit.html tests/test_e2e_gallery.py
git commit -m "feat(gallery): multi-instance carousel gallery.js + student CSS + e2e"
```

---

### Task 9: Course export / import round-trip

Add the gallery to all three transfer registries and extend export Pass 2/4 to account for a **list** of media ids (the documented scalar-only assumption). Missing images already resolve to the placeholder PNG at the asset level; import tolerates out-of-bound counts.

**Files:**
- Modify: `courses/transfer/export.py`, `courses/transfer/payloads.py`, `courses/transfer/importer.py`
- Test: `tests/test_gallery_transfer.py` (create)

**Interfaces:**
- Snake_case registry key `"gallery"` in `SERIALIZERS`, `VALIDATORS`, `BUILDERS`.
- Produces serialized `{"desc_pos": str, "images": [{"media": <mid>, "desc": str}]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gallery_transfer.py
import pytest
from courses.transfer.export import SERIALIZERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.importer import BUILDERS

pytestmark = pytest.mark.django_db


def test_registries_lockstep():
    assert "gallery" in SERIALIZERS
    assert "gallery" in VALIDATORS
    assert "gallery" in BUILDERS


def test_round_trip_preserves_order_desc_pos_and_descs(export_import_helper):
    """Build a 2-image gallery, export the course, import into a fresh course,
    assert the gallery survived with order, descriptions, and desc_pos."""
    src = export_import_helper.make_course_with_gallery(
        desc_pos="above", descs=["<b>one</b>", r"two \(x\)"]
    )
    dst = export_import_helper.round_trip(src)
    gal = export_import_helper.only_gallery(dst)
    assert gal.data["desc_pos"] == "above"
    assert [i["desc"] for i in gal.data["images"]] == ["<b>one</b>", r"two \(x\)"]
    assert len(gal.data["images"]) == 2


def test_missing_image_round_trips_to_placeholder(export_import_helper):
    """An exported gallery whose image bytes are missing imports with a
    placeholder asset (element kept, not dropped)."""
    dst = export_import_helper.round_trip_with_missing_image_gallery()
    gal = export_import_helper.only_gallery(dst)
    assert len(gal.data["images"]) == 2   # both slots kept
```

> Model `export_import_helper` on the existing transfer tests (grep `tests/test_transfer*` / `round_trip`). Reuse the real export→zip→import path; only add gallery-specific builders to the helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gallery_transfer.py -v`
Expected: FAIL (`"gallery" not in SERIALIZERS`)

- [ ] **Step 3: Add the serializer + registry entry (`export.py`)**

```python
def _ser_gallery(el, ids):
    norm = el.normalize_data(el.data)
    return {
        "desc_pos": norm["desc_pos"],
        "images": [
            {"media": ids.register(_ma), "desc": img["desc"]}
            for img, _ma in _gallery_assets(el, norm)
        ],
    }


def _gallery_assets(el, norm):
    """Yield (image_dict, MediaAsset) for resolvable ids, in order. Unresolved
    ids are skipped (they cannot be exported)."""
    from courses.models import MediaAsset

    ids = [img["media"] for img in norm["images"]]
    assets = MediaAsset.objects.in_bulk(ids)
    for img in norm["images"]:
        a = assets.get(img["media"])
        if a is not None:
            yield img, a
```

Register in `SERIALIZERS`: add `"gallery": (GalleryElement, _ser_gallery),` (import `GalleryElement` at top of `export.py`).

- [ ] **Step 4: Extend Pass 2 / Pass 4 for the media list**

The generic multi-pass accounting currently reads a scalar `ref_mid = data.get("media")`. Add a helper and use it so a gallery's **list** of mids is registered for the problems list and the dropped-mid filter:

```python
def _element_mids(type_key, data):
    """All media ids an element references, routed by the element TYPE KEY (not
    by sniffing the data shape): a gallery reads its `images[].media` list; every
    other media-bearing type reads the scalar `media`."""
    if type_key == "gallery":
        return [
            img["media"]
            for img in (data.get("images") or [])
            if isinstance(img, dict) and isinstance(img.get("media"), str)
        ]
    m = data.get("media")
    return [m] if isinstance(m, str) else []
```

In Pass 2, replace the scalar registration (note `serialize_element_data` already yields `type_key` here):

```python
                mids = _element_mids(type_key, data)
                for mid in mids:
                    mid_refs.setdefault(mid, []).append((walk_index, n.pk, n.title))
                pending.append(
                    (walk_index, {"unit": node_ids[n.pk], "title": join.title, "type": type_key, "data": data}, mids)
                )
```

In Pass 4, drop the element if **any** referenced mid was dropped (images never drop — they become placeholders — so galleries are kept; videos still drop as before):

```python
        for _wi, edict, mids in pending:
            if any(status.get(mid) == "dropped" for mid in mids):
                continue
            eidx += 1
            element_dicts.append({"id": f"e{eidx}", **edict})
```

> The third tuple slot changed from a scalar `ref_mid` to a `mids` list — update the `pending.append(...)` (done above) and the Pass-4 unpacking together so they stay consistent. Existing scalar-media types now carry a 0- or 1-element list, preserving their behavior.

- [ ] **Step 5: Add the validator (`payloads.py`)**

```python
def _val_gallery(data, elid, media_kinds):
    _exact_keys(data, ["desc_pos", "images"], _("gallery data"))
    if data["desc_pos"] not in ("above", "below"):
        _err(_("Element '%(el)s' has an invalid gallery position."), el=elid)
    if not isinstance(data["images"], list):
        _err(_("Element '%(el)s' has malformed gallery images."), el=elid)
    refs = set()
    for img in data["images"]:
        if not isinstance(img, dict):
            _err(_("Element '%(el)s' has a malformed gallery image."), el=elid)
        _exact_keys(img, ["media", "desc"], _("gallery image"))
        refs |= _require_media(img["media"], elid, media_kinds, "image")
        check_str(img["desc"], "desc", max_length=100000)
    return refs  # shape-only; 2-20 bound is NOT re-enforced on import (see spec)
```

Register: add `"gallery": _val_gallery,` to `VALIDATORS`.

- [ ] **Step 6: Add the builder (`importer.py`)**

```python
def _build_gallery(data, assets):
    images = [{"media": assets[img["media"]].pk, "desc": img["desc"]} for img in data["images"]]
    el = GalleryElement(data={"desc_pos": data["desc_pos"], "images": images})
    return _clean_save(el), ()   # save() normalizes + sanitises each desc
```

Register: add `"gallery": _build_gallery,` to `BUILDERS` (import `GalleryElement` at top of `importer.py`).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_gallery_transfer.py -v`
Expected: PASS

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_gallery_transfer.py
uv run ruff format courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_gallery_transfer.py
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_gallery_transfer.py
git commit -m "feat(gallery): course export/import round-trip (media-list accounting)"
```

---

### Task 10: i18n catalogs (EN + PL) + frontend-design polish

Extract all new strings, translate to Polish, compile, and verify catalog health. Then run the frontend-design pass on the editor + carousel and screenshot-verify light + dark.

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (paths per repo), any CSS/icon refinements from the design pass.
- Test: existing i18n catalog tests (`tests/` — grep `makemessages`/`polib`/`no-obsolete`).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en` (or the repo's exact invocation — check how prior slices ran it; mind the fuzzy-flag gotcha).
Confirm the new msgids appear: `Gallery`, `Add image`, `Description position`, `Below image`, `Above image`, `Move up`, `Move down`, `Remove`, `A gallery needs at least %(n)d images.`, `A gallery is limited to %(n)d images.`, `A gallery image is not an image in this course.`, `A gallery needs a list of images.`, `Previous image`, `Next image`, `Go to image {n}`, `Image {n} of {total}`.

- [ ] **Step 2: Translate to Polish**

Fill each new `msgstr` in `locale/pl/LC_MESSAGES/django.po`. Remove any `#, fuzzy` flags on entries you complete. Keep `{n}`/`{total}` placeholders and `%(n)d` intact in the Polish strings.

- [ ] **Step 3: Compile + verify catalog health**

```bash
uv run python manage.py compilemessages
uv run pytest tests/ -k "i18n or catalog or messages" -v
```
Expected: PASS (no obsolete `#~` entries, no untranslated new strings). Fix any failures.

- [ ] **Step 4: Frontend-design pass**

Invoke the **frontend-design** skill on: the editor (image-row list, thumbnails, toolbar, add button) and the student carousel (frame, bar, dots, cross-fade). Refine `courses.css` and the `el-gallery` icon per its guidance. Then, per the **verify-ui-with-screenshots** practice, Playwright-screenshot both the editor and a student lesson gallery in **light and dark**, self-critique, and adjust. Ensure the toolbar uses `.ic` SVG icons consistent with the rest of the UI (avoid the table slice's Unicode-glyph deferral).

- [ ] **Step 5: Commit**

```bash
git add locale/ courses/static/courses/css/courses.css templates/courses/manage/_icon_sprite.html
git commit -m "i18n(gallery): EN/PL catalogs + frontend-design polish (light/dark verified)"
```

---

## Definition of Done (controller — after all tasks)

Run from the worktree:

1. `uv run ruff check .` and `uv run ruff format --check .` — clean.
2. `uv run python manage.py makemigrations --check --dry-run` — no missing migrations.
3. `uv run pytest` — full non-e2e suite green (deselects e2e by default).
4. `uv run pytest -m e2e` — **full** e2e suite green (not just the gallery e2e — a JS/render change can stale a sibling e2e; this is the table-slice CI lesson).
5. `uv run python manage.py compilemessages` — clean; i18n catalog tests green.

Per the subagent-driven-development learning: task steps above run **focused** tests (fast, avoid implementer stalls); this DoD is where the full-suite gates run once, at the end.

## Notes / risks

- **`media_picker.js` is shared** — the append-mode change (Task 7) is strictly additive and guarded by `data-pick-mode="append"`; the scalar `<select name='media'>` path is untouched when `appendTarget` is null. Re-run the image/video editor e2e in the DoD to confirm no regression.
- **Export Pass 2/4 tuple shape changed** (scalar `ref_mid` → `mids` list) — this touches the generic path shared by all media-bearing types; the transfer round-trip tests for image and video must still pass (they carry a ≤1-element list now). Verify in the DoD.
- **`math.js` selector** — adding `.el--gallery` means galleries load KaTeX only when `has_math` is set (Task 3 gating); a gallery with no math descriptions must NOT force KaTeX (assert in a render/context test if convenient).
- **Frontend-design deferral avoided** — unlike the table slice, the icon/toolbar polish is in-scope here (Task 10 Step 4).
