# Gallery / Carousel element

**Slice 2 of 3 new course-content elements** (table → **gallery/carousel** → tabs). Slice 1 (table)
is merged (PR #87). This slice adds a `GalleryElement`: an author-authored set of images shown to
students as a single-image-at-a-time **carousel**, each image carrying an optional rich-text + math
**description**.

## Purpose

Authors frequently want to present a *sequence of related images* (worked-example steps, a set of
diagrams, photos of an experiment) as one cohesive, navigable widget rather than a long vertical
stack of separate `ImageElement`s. The existing building blocks don't cover this:

- `ImageElement` is a single image.
- The unit-level "slideshow" is *pagination of whole lessons*, not an in-lesson image element.

The gallery fills that gap. It is a **content element** (not a question), embedded in a lesson like
any other element, reusing the course's existing `MediaAsset` image library.

### Student-facing behaviour

- One image visible at a time inside a **stable, responsive frame**; arrow buttons + clickable
  progress dots move between images (galleries above 12 images show an "N / M" text counter instead of
  dots); keyboard `←`/`→` work **when focus is within the gallery**; a screen-reader live region
  announces "Image N of M".
- Each image may have an optional **description** (rich text + inline math), shown either **above**
  or **below** the frame — a single position choice for the whole gallery.
- Images are **never cropped**: the frame is a responsive `4:3` box (`max-height: 70vh`) and each
  image is letterboxed inside it with `object-fit: contain`.

### Author-facing behaviour

- Add images from the course's existing media picker (upload-or-choose, `kind="image"`).
- Give each image an optional rich description (bold/italic/underline + inline LaTeX), reorder the
  images, and remove images.
- Choose the description position (above/below) for the gallery.
- A gallery must have **at least 2 images** (a single-image "carousel" is just an `ImageElement`)
  and **at most 20**.

## Architecture / components

The element rides the established content-element machinery. `TableElement` is the closest model
for the *element/JSON/editor* shape; the unit slideshow's `slideshow.js` is the closest model for the
*student carousel navigation*. Nothing in the delicate slideshow completion path is touched.

### Data model — `courses/models.py`

New concrete `GalleryElement(ElementBase)`:

- `data = models.JSONField(default=dict)` with shape:

  ```json
  {
    "desc_pos": "below",
    "images": [
      { "media": 42, "desc": "<sanitised html>" },
      { "media": 43, "desc": "" }
    ]
  }
  ```

  - `desc_pos` ∈ `{"above", "below"}`, default `"below"`.
  - `images` is an **ordered list**; each item references a `MediaAsset` id (`media`) and holds a
    sanitised rich-text/math `desc` (may be empty string).
- Class constants: `DESC_POSITIONS`, `MIN_IMAGES = 2`, `MAX_IMAGES = 20`.
- `elements = GenericRelation(Element)` (cascade delete of the join row), per `ElementBase`.
- `@staticmethod normalize_data(data)` — defensively coerces arbitrary stored JSON into a
  well-formed dict: valid `desc_pos` or default; `images` a list of `{media:int, desc:str}` with
  non-int / non-dict entries dropped; never raises. Used by form `clean_data`, importer, and render
  (mirrors `TableElement.normalize_data`).
- `save()` runs a `_sanitized_data()` pass that **first calls `normalize_data(self.data)`** (so it can
  never `KeyError`/`TypeError` on hostile non-dict/non-list stored JSON from the admin/import paths
  that bypass form `clean_data`), then sanitises every image's `desc` via the existing math-protected
  sanitiser — defense-in-depth on all write paths (form, importer, admin).
- `@property normalized_data` for the editor partial.
- Overrides `render()` to pass `normalize_data(self.data)` into the template.

Registered in `ELEMENT_MODELS`, with a migration altering `Element.content_type`'s
`limit_choices_to` (precedent: `0033_tableelement_alter_element_content_type.py`).

**Images reference `MediaAsset` by id inside JSON** — the gallery owns no file field, exactly as
`ImageElement` references a single `MediaAsset` via FK. Because the references live in JSON (not FKs),
`normalize_data`/render resolve ids to `MediaAsset` rows at render time and **skip ids that no longer
resolve** (an asset deleted out from under the gallery must not 500 the lesson page).

### Description sanitisation — `courses/sanitize.py`

Descriptions reuse the **same math-protected sanitiser** the table cells use: extract balanced
`\(...\)` / `\[...\]` behind nonce placeholders, canonicalise, allow only
`<strong>/<b>/<em>/<i>/<u>/<br>`, restore math. The table slice implemented this as `sanitize_cell`;
this slice **reuses that function** for descriptions (no new sanitiser). (Generalising its name to
`sanitize_html` is a noted pre-existing follow-up and explicitly **out of scope** here.)

**Alt text** is derived, not stored: a helper strips tags **and** math from the sanitised `desc` to a
plain-text alt string. A **blank** `desc` yields `alt=""` (decorative). A `desc` that is **non-empty
but strips to empty** (e.g. math-only) is *not* decorative, so the render falls back to a generic
translated `alt` of "Image {n} of {total}" rather than an empty string. This helper is used by the
render template.

**Index basis (shared server↔client).** Everywhere an image is numbered — the server alt fallback and
the client's `role="status"` region — `{n}`/`N` is the **1-based position within the resolvable image
set** and `{total}`/`M` is the **resolvable count**. Skipped (unresolved) ids are never counted, so
the numbering can never read "Image 3 of 2" and the server-rendered alt agrees with the
client-rendered status.

### Form + validation — `courses/element_forms.py`

`GalleryElementForm(_CourseScopedMediaForm-style)`:

- Modeled on `TableElementForm`: the `data` JSONField is optional; `clean_data` normalises and
  validates.
- **Validation rules** in `clean_data`:
  - `data` must normalise to `{desc_pos, images}`.
  - `2 ≤ len(images) ≤ 20` → else `ValidationError` (distinct messages for too-few / too-many).
  - Every `images[i].media` must be a `MediaAsset` belonging to **this course** with `kind="image"`
    (course scoping, like `_CourseScopedMediaForm`) → else `ValidationError`. This is the
    server-side authority; the editor only *offers* course images.
  - Non-list `images` / non-dict entries are rejected (guard against the `clean_data` 500 class of
    bug the table slice hit — see its `28d9b97` fix).
  - **Duplicate images are permitted** — the same `MediaAsset` id may appear more than once; each
    occurrence is a distinct slide (counts toward the 2–20 bound, gets its own dot). Neither the
    editor nor the validator dedupes.
- Registered in `FORM_FOR_TYPE` under `"gallery"`.

### Manage-UI plumbing

- `templates/courses/manage/editor/_add_menu.html` — a `data-add-type="gallery"` card in the Content
  group with `<use href="#el-gallery"/>`.
- `templates/courses/manage/_icon_sprite.html` — a new `id="el-gallery"` monochrome `currentColor`
  symbol, **`viewBox="0 0 16 16"`** to match its siblings (the table slice shipped a mismatched 24×24
  viewBox — do not repeat).
- `courses/views_manage.py`:
  - Add `"gallery"` to the media-scoped-form tuple in `_render_open_form` (it references media, so the
    form needs `course=`).
  - Add `"gallery"` to the add/save `type_key` allow-lists.
  - Add a `_EDITOR_TYPE_LABELS["gallery"]` heading.
- Editor partial `templates/courses/manage/editor/_edit_gallery.html` is auto-wired by the
  `_edit_<type_key>.html` naming convention (no dispatch code needed).

### Author editor — `_edit_gallery.html` + `courses/static/courses/js/gallery_editor.js`

- The partial renders a hidden `<input name="data">` (mirrored by JS) plus a UI region: the
  description-position toggle and a vertical list of **image rows**. Because `normalized_data` holds
  only image **ids**, the editor view resolves each id to its `MediaAsset` and passes **resolved rows**
  (`{id, thumb_url, desc}`) to the partial for seeding; an id that no longer resolves is **dropped**
  from the seed (consistent with render-time skipping — the author can re-add it). Fresh picks get
  their thumbnail from `media_picker.js` as today.
- Each row: a **thumbnail** (`MediaAsset.file.url`), a **contenteditable description box** with a
  B/I/U + inline-LaTeX toolbar (reusing the table editor's per-cell editing approach —
  `execCommand` with `styleWithCSS=false`, mousedown `preventDefault`, and `window.libliMathInput`
  for math), and a **remove** button.
- **Add image**: an existing `[data-pick-media="image"]` button opens `media_picker.js`
  (upload-or-choose). The picked `MediaAsset` id + thumbnail become a new row appended to the list.
- **Reorder**: drag rows (HTML5 drag-and-drop) to reorder; **up/down buttons** are provided as a
  keyboard-accessible / drag-fallback path.
- **State mirroring**: on every change (add/remove/reorder/description-edit/position-toggle),
  `gallery_editor.js` serialises the UI into the hidden `data` field as the JSON above — exactly the
  `table_editor.js` pattern. No per-image form fields; the single `data` field is the source of truth.

### Student render — `templates/courses/elements/galleryelement.html` + `gallery.js`

- **DOM structure (pinned).** The template renders a `[data-gallery]` container whose **root element
  carries `class="el el--gallery"`** (alongside `data-gallery`) — matching the hand-written
  `class="el el--<type>"` convention every element template uses (e.g. `el el--table`), and the exact
  hook `math.js`'s `.el--gallery` render scope keys on, so math descriptions actually typeset. The
  container holds one `<figure class="gallery__item">` **per resolvable image**, in order. Each figure
  contains a `.gallery__frame` (the image) and a sibling `.gallery__desc` block placed **before or
  after** the frame according to the gallery's `desc_pos`. The `.gallery__desc` is emitted for
  **every** figure — **empty** (no visible text) when the image has no description — so the
  reserved-height slot (see Stage sizing) is uniform and the frame offset can't jump between described
  and un-described slides. The description is thus **per-image**, lives *outside* the frame (never
  eating image space), and moves with its image. There is **no** single shared description block —
  `desc_pos` sets the desc's order *within each figure*, not a page-level slot.
- The frame is the responsive **4:3 aspect-ratio** box (`aspect-ratio: 4/3; max-height: 70vh`); its
  `<img>` uses `object-fit: contain` and `alt` from the stripped-description helper (see above). Image
  ids that fail to resolve to a `MediaAsset` are **skipped** — no figure is emitted for them.
- **Resolvable-count outcomes** (validation bounds apply at author time, not render time, so render
  shows whatever still resolves): **0** resolvable images → the element renders **nothing** (the
  `[data-gallery]` container is omitted entirely); exactly **1** → the lone figure is shown but the
  carousel bar (prev/next/dots/status) is **suppressed** (readable, just not navigable); **≥2** → a
  normal carousel.
- **No-JS fallback**: without JS the container shows every figure stacked in order, each with its
  description positioned above/below its image per `desc_pos`, so the content is fully reachable —
  `gallery.js` progressively enhances the stack into a carousel.
- `courses/static/courses/js/gallery.js` — a **new, self-contained** module modeled on
  `slideshow.js`'s carousel core, but **multi-instance** (a lesson can contain many galleries, unlike
  the single unit-level slideshow, so the single-instance `querySelector` pattern must NOT be copied
  verbatim):
  - Uses `querySelectorAll("[data-gallery]")` and initialises **each** container independently; every
    instance closes over its **own** state (`idx`, dots, `.gallery__stage`, `role="status"` region).
    No module-level singletons.
  - Per instance: moves that container's `<figure>`s into a `.gallery__stage`, builds a
    `.gallery__bar` with prev/next `iconBtn` (**inline `currentColor` chevron SVG**, not the
    editor-only sprite — same rationale documented in `slideshow.js`), progress **dots** for
    ≤ `DOTS_MAX` images (**`DOTS_MAX = 12`**, inheriting `slideshow.js`) else a text counter, an
    sr-only `role="status"` live region ("Image N of M"), and a `show(n)` cross-fade state machine
    (`FADE_MS` kept in lockstep with the CSS transition).
  - **Stage sizing (delivers the "stable frame"):** the `.gallery__stage` overlays its figures for
    the cross-fade; JS sets the stage `min-height` to the **tallest figure** (measured on init,
    recomputed on resize) so navigating never reflows the page, and gives each `.gallery__desc` a
    reserved `min-height` equal to the **tallest description** in that gallery, so the aspect-ratio
    frame sits at a **constant vertical offset** across slides for both `desc_pos` values (short
    descriptions simply leave reserved whitespace). The frame's own size is already stable via its
    fixed aspect-ratio + `max-height`.
  - **Measure after math typesets:** descriptions may contain KaTeX-rendered math whose height
    differs from the un-typeset source, so the height measurement above must run **after** `math.js`
    finishes typesetting this gallery's descriptions — not on a bare `DOMContentLoaded`. Concretely:
    re-measure on the math-render completion hook (or a `requestAnimationFrame` sequenced after
    `math.js`, or a `ResizeObserver` on the `.gallery__desc` blocks), so reserved heights reflect
    typeset math and the frame doesn't shift once math renders. (This is the KaTeX-timing bug class
    the table slice's testing lesson warns about.)
  - **Interactive dots:** dots are real controls, not mere indicators (the student-facing text says
    they *move between images*). Each dot is a `<button>` that calls `show(n)`, carries an accessible
    label ("Go to image {n}"), exposes active state via `aria-current="true"`, and is keyboard-
    reachable. The > `DOTS_MAX` text counter is a non-interactive indicator (arrows still navigate).
  - **Active-slide a11y:** `show(n)` keeps only the current figure in the accessibility tree — it sets
    `aria-hidden="true"` (and/or `inert`) on the inactive overlaid figures — so a screen-reader user
    hears one image's `alt` + description at a time, consistent with the "Image N of M" live region.
    (The no-JS stack legitimately exposes all figures; the enhanced carousel must not.)
  - **Enhancement guard:** an instance no-ops (leaves the DOM as the no-JS stack, no bar) when it
    finds **fewer than 2** `<figure>`s — mirroring `slideshow.js`'s `slides.length <= 1` bail — so
    0-image (already omitted server-side) and 1-image galleries never build a meaningless bar.
  - **Keyboard scoping:** `ArrowLeft`/`ArrowRight` act on a gallery **only when focus is within that
    gallery's container or bar** (the `container.contains(target)` guard `slideshow.js` uses), so
    arrows never cross between sibling galleries or hijack the page.
  - i18n injected via a `window.GALLERY_I18N` object (labels: "Previous image", "Next image",
    "Image {n} of {total}").
  - **Loaded unconditionally** in `lesson_unit.html` / `quiz_unit.html`, self-guarding on
    `[data-gallery]` presence (same load strategy as `slideshow.js`).
- **Why a separate module, not shared with `slideshow.js`:** the slideshow is coupled to unit-level
  completion (`progress.js` IntersectionObserver, `markSlideSeen`/`unitMarkDone`). A gallery drives
  none of that. Copying the ~150-line carousel core keeps the just-shipped slideshow untouched;
  extracting a shared core is a clean future refactor if a third carousel ever appears.

### Capability gating — `courses/views.py`

- Add a `has_gallery_math` scan (mirroring `_table_has_math`): walk each gallery's descriptions —
  over `normalize_data(self.data)` (never raw `self.data`), so hostile/legacy JSON can't raise or be
  missed — for `\(`/`\[` math delimiters. OR it into the existing `has_math` flag at **exactly the
  `courses/views.py` call sites where `_table_has_math` is already OR'd in** — the lesson and quiz
  context builders (`build_lesson_context` and its quiz analog). Locate them by grepping for
  `_table_has_math`; the gallery scan is added at the same spots, so the set stays in lockstep with
  tables.
- The **results page** renders only question rows and already excludes content elements → no gallery
  gating needed there, same as tables.

### Export / import — `courses/transfer/`

This is the one place the existing **scalar-`media`** assumption breaks; the gallery's `media` lives
in a **list**. All three lockstep registries are extended:

- `export.py` — a `_ser_gallery` serializer (registered in `SERIALIZERS`) that walks `images`,
  registering each `MediaAsset` via `MediaIdMap` and emitting `{desc_pos, images:[{media:<mid>,
  desc}]}`. The exporter's Pass 2/3/4 media accounting (which currently assumes `data["media"]` is a
  scalar mid) is extended to also handle a gallery's **list** of mids: each missing image resolves to
  the bundled **placeholder PNG** (same mechanism as `ImageElement`), so a partial gallery survives
  export/import rather than dropping the whole element.
- `payloads.py` — a `VALIDATORS` entry validating the serialized gallery shape (desc_pos in set,
  images a list of `{media:str-mid, desc:str}`).
- `importer.py` — a `BUILDERS` entry that maps each `mid` back to the imported `MediaAsset` id and
  reconstructs `data`, then saves through the model (so `save()`-time sanitisation runs on import,
  matching the table slice's sanitise-on-import).

### i18n

EN + PL catalog entries for every new string: element label, add-menu card, editor labels/buttons
(add image, remove, move up/down, description, position above/below), and the `window.GALLERY_I18N`
nav strings ("Previous image", "Next image", "Go to image {n}", "Image {n} of {total}"). Follow the
table slice's `gettext_lazy` discipline for module-level translatable strings.

**Single source for shared wording.** "Image {n} of {total}" appears in **both** the server-side `alt`
fallback and the client `role="status"` region. These must share **one msgid and identical wording** —
concretely, the server translates it and injects the result into `GALLERY_I18N` (the JS never
hard-codes its own copy) — so `alt` and status text can never drift across locales.

## Data flow

**Authoring:** author clicks the gallery add-card → `views_manage` opens `GalleryElementForm` (with
`course=`) → `_edit_gallery.html` renders an empty editor → author picks images (`media_picker.js`),
types descriptions, reorders, sets position → `gallery_editor.js` mirrors UI → hidden `data` JSON →
submit → `GalleryElementForm.clean_data` normalises + validates (2–20, course-scoped image ids) →
`GalleryElement.save()` sanitises each `desc` → persisted.

**Consumption (lesson/quiz):** view builds context, `has_math` includes `has_gallery_math` → element
renders via `galleryelement.html` (resolvable images only, alt from stripped desc, `[data-gallery]`
container) → `gallery.js` enhances into a carousel; descriptions with math are typeset by the
already-loaded KaTeX (`.el--gallery` added to `math.js`'s inline-text render scope, like `.el--table`).

**Transfer:** export serializes `images` list + registers each asset in `MediaIdMap` (missing →
placeholder); import validates the shape and rebuilds `data`, saving through the model.

## Error handling

- **Malformed / hostile stored JSON** — `normalize_data` never raises; it coerces to a well-formed
  dict, dropping bad entries. Render always operates on normalized data.
- **Non-list `images` / non-dict entries in the form** — rejected explicitly in `clean_data` (the
  table slice's 500-class bug is guarded against by design here).
- **Fewer than 2 / more than 20 images** — `ValidationError` with distinct, translated messages.
- **Image id not in this course / not an image** — `ValidationError` (server-side authority; the
  editor only offers course images but must not trust the client).
- **Asset deleted after authoring** — render resolves ids to `MediaAsset` rows and **skips**
  unresolved ids; it never 500s. Validation bounds (2–20) apply at *author* time, not render time, so
  render shows whatever still resolves: **0** resolvable → the element is **omitted entirely** (no
  `[data-gallery]` container); **1** resolvable → the lone image is shown with the carousel bar
  **suppressed**; **≥2** → a normal carousel. `gallery.js` independently no-ops on any container with
  fewer than 2 figures, so the client never builds a bar the server didn't intend.
- **XSS via description** — prevented by the math-protected `sanitize_cell` at `save()` and on import
  (unescape-once-then-escape-once so `<` inside math survives nh3 and cannot inject).
- **Missing media on export** — bundled placeholder PNG per missing image; the gallery is not dropped.
- **No JS** — the element degrades to a stacked list of all images + descriptions; fully readable.

## Testing

TDD throughout (test-first per task):

- **Model**: `normalize_data` coercion (valid, missing keys, bad `desc_pos`, non-list images,
  non-dict/non-int entries); `save()`-time description sanitisation (tags stripped to the allow-list,
  math preserved, XSS neutralised); render skips unresolved image ids.
- **Alt helper**: strips tags and math to plain text; blank desc → `alt=""`; non-empty-but-strips-to-
  empty desc (math-only) → generic "Image {n} of {total}" fallback.
- **Render edge counts**: a gallery with 0 resolvable images omits the container; with exactly 1 shows
  the image and suppresses the bar; with ≥2 emits one `<figure>` per image with the `.gallery__desc`
  positioned per `desc_pos`. The container root carries `class="el el--gallery"`.
- **Multi-instance isolation** (guards the CRITICAL multi-instance decision — the regression class the
  single-`querySelector` pattern would reintroduce): a JS/e2e test with **two galleries on one page**
  asserts that advancing/keyboarding one does **not** move the other (independent `idx` and dots), and
  that `←`/`→` are ignored unless focus is within a given gallery's container/bar.
- **Carousel a11y**: `show(n)` keeps only the active figure in the accessibility tree (inactive figures
  `aria-hidden`/`inert`); a dot click navigates to its image and the active dot exposes
  `aria-current`; the stable-frame reservation holds after math typesets (frame offset unchanged once
  KaTeX renders).
- **Form**: accepts a valid 2–20 gallery; rejects <2, >20, non-list images, non-dict entries, and
  image ids from another course / non-image assets.
- **Editor render**: `_edit_gallery.html` seeds rows from `normalized_data`, emits the hidden `data`
  field and the position toggle.
- **Capability gating**: `has_gallery_math` true iff a description contains math; wired into the
  lesson and quiz context builders.
- **Export/import round-trip**: a multi-image gallery survives export→import with order, descriptions,
  and caption position intact; a **missing image** round-trips to the placeholder rather than dropping
  the element; the three registries stay in lockstep.
- **e2e** (`-m e2e`, Chromium): drive the **real UI** — add a gallery, pick ≥2 images, add a
  description containing math, reorder, save; on the student page assert the carousel renders, nav
  advances the image, and a **rendered `.katex`** node appears in the description (per the table
  slice's KaTeX-consumption lesson). After any task that changes rendering/JS, re-run the **full**
  `-m e2e` suite (pytest deselects e2e by default — the table slice's CI lesson).

### Frontend-design pass

Before the PR, run the **frontend-design** skill on the editor (image-row list, thumbnails, toolbar)
and the student carousel (frame, bar, dots, cross-fade) and **screenshot-verify light + dark** — this
proactively covers the polish the table slice deferred (`.ic` SVG icons in the toolbar, consistent
sprite viewBox, matching JS/CSS handle classnames).

## Out of scope (YAGNI — clean additive follow-ups)

- Autoplay / timed advance.
- Per-image alt override (alt is derived from the description).
- Author-selectable aspect ratio (fixed 4:3 for v1).
- Grid / lightbox display mode; thumbnail-strip navigation.
- Generalising `sanitize_cell` → `sanitize_html` (pre-existing, separate).
