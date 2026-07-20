# FillTable image cells

## Purpose

`FillTableElement` is the ungraded self-check grid: each cell is either a
**static** cell (rich HTML/math, sanitised at save) or an **answer** cell (a
fill-in input checked server-side). A common LAL teaching shape puts an *image*
in a grid cell as a visual prompt beside/above an input — e.g. a row of five
slope graphs over five answer cells (`010_funkcja_liniowa/f_lin_023`), or five
`[vector image][answer]` rows (`110.../wykresy_20`). Today that image is **lost**:
static cells are sanitised at save by `courses/sanitize.py:sanitize_cell`, whose
`CELL_TAGS` allowlist has no `img`, so the `<img>` is stripped.

This is the largest single remaining image-loss bucket in the matematyka import:
**31 images across 7 files** (measured recursion-aware; see the project memory).
It is also a genuine authoring capability — "put a figure in a grid cell as a
visual prompt" is a shape a teacher would plausibly author directly — so this is
built as a **first-class, editor-authorable** feature, not an import-only hack.

This spec covers **sub-spec A** of the "remaining image-loss" slice. Sub-spec B
(a parser-only extraction pass for reveal-cell / question-stem / figure-in-spoiler
images into existing `ImageElement`s) is a separate spec, sequenced after this one.

## Chosen approach (user-approved)

Add a third cell **kind**, `image`, storing a `MediaAsset` primary key inside the
element's `data` JSON — following the **proven `GalleryElement` media-in-JSON
precedent** (`data.images = [{media: <pk int>, desc}]` + `resolved_images()` which
does `MediaAsset.objects.in_bulk(ids)` at render time). No new model, no new table,
**no migration** (`FillTableElement.data` is already a `JSONField`).

User-approved scope decisions:
- **Editor authoring is in scope now**: teachers can add/change an image cell in
  the grid editor via the existing media picker (not import-only).
- **Optional per-cell alt text**: a small optional alt input per image cell; the
  loader carries the source `<img>`'s `alt` on import.

## Background: the pieces this touches

- **`FillTableElement`** (`courses/models.py` ~903). `data` JSON is
  `{header_row, header_col, case_sensitive, border, prompt, cells}` where `cells`
  is a row-major grid. `_cell(raw)` normalises one cell to either
  `{kind:"answer", answer, halign, valign}` or `{kind:"static", html, halign, valign}`.
  `normalize_data` reshapes the grid (read-side, destructive padding to a rectangle).
  `_sanitized_data` (called by `save()`) trims answers and runs `sanitize_cell` on
  static html. `render()` builds ctx and renders `filltableelement.html`;
  `canonical_cells` is the restore-path grid (answers replaced by first alternative).
- **`GalleryElement`** (`courses/models.py` ~1036) — the media-in-JSON precedent.
  `_image(raw)` validates `media` is an `int` (rejecting `bool`); `normalize_data`
  drops entries without a valid int media; `resolved_images()` resolves pks →
  `MediaAsset` via `in_bulk`, **skipping unresolved ids** so a deleted asset never
  500s a lesson. `_sanitized_data` normalises then sanitises descriptions.
- **`_filltable_cell.html`** (`templates/courses/elements/`) — the per-cell partial:
  branches `answer` (renders `<input>`, or readonly locked value when `mine.done`)
  vs static (`{{ cell.html|safe }}`).
- **`filltableelement.html`** — the table template; iterates `data.cells`, wrapping
  each cell in `<th>`/`<td>` and `{% include %}`-ing the partial.
- **Parser** `scripts/lal_import/tables.py:fill_table_element(table, answer_by_input)`
  — input cell → `{kind:"answer", answer}`; every other cell →
  `{kind:"static", html: c.decode_contents().strip()}`. Falls back to a flagged
  HtmlElement on span/nested/ragged grids.
- **Loader** `courses/lal_loader/builders.py` `fill_table` branch (~190) — currently
  `FillTableElement.objects.create(data=FillTableElement.normalize_data(el["data"]))`.
  The `image` branch (~234) shows the media path: `resolve_source(...)` +
  `get_or_create_asset(course, "image", path)` (content-hash dedup in
  `courses/lal_loader/media.py`).
- **Editor** `courses/static/courses/js/filltable_editor.js` +
  `templates/courses/manage/editor/_edit_filltable.html` + `FillTableElementForm`
  (there is currently **no** `FillTableElementForm`; the grid is authored entirely
  by the JS editor writing a hidden `input[name="data"]` JSON — confirm during
  planning whether a form exists or the view consumes `data` directly).
- **Media picker** `courses/static/courses/js/media_picker.js` — a reusable modal.
  `[data-pick-media]` buttons target a `select[name='media']`; gallery "append mode"
  (`data-pick-mode="append"`) instead calls `window.libliGalleryAdd(host, id, name, url)`.
  This append-callback hook is the exact precedent for an image-cell target hook.

## Data model

A new cell kind. The canonical shapes of a normalised cell become:

```
{kind: "answer", answer: <str>,  halign, valign}
{kind: "static", html:   <str>,  halign, valign}
{kind: "image",  media:  <int>,  alt: <str>, halign, valign}   # NEW
```

`FillTableElement._cell(raw)` gains an image branch, placed before the static
fallback:
- `raw.get("kind") == "image"` → validate `media` is an `int` and **not** a
  `bool` (mirroring `GalleryElement._image`). Valid → `{kind:"image", media:int,
  alt:str, halign, valign}`. **Invalid media** (missing / non-int / bool) →
  degrade to an empty **static** cell `{kind:"static", html:"", …}` (never raise,
  never render a broken image). `alt` coerced to `""` if not a str.
- Existing answer/static branches unchanged.

`_sanitized_data`: image cells have no `html` to sanitise; trim `alt` to a string
(defensive). Leave `media` untouched. Answer/static handling unchanged.

`canonical_cells` (restore path): image cells pass through unchanged (they hold no
answer). Only answer cells are rewritten.

New method **`resolved_cells()`** (the Gallery `resolved_images()` analog): return
the normalised grid with every image cell's `media` **pk replaced by its
`MediaAsset`** (resolved in one `MediaAsset.objects.in_bulk(all_image_pks)` pass).
An image cell whose pk does not resolve degrades to an empty static cell for
rendering (never 500s). Static/answer cells pass through. `render()` uses
`resolved_cells()` in place of `normalize_data(self.data)["cells"]` for the ctx
`data.cells`, keeping the `mine.done` canonical swap for answer cells.

Rationale for resolving in the model, not the template: the template must never
run a query per cell, and an unresolved pk must be handled once, centrally — same
reasons Gallery resolves in `resolved_images()`.

## Rendering

`_filltable_cell.html` gains an image branch (before the static `else`):

```
{% if cell.kind == "answer" %}… (unchanged) …
{% elif cell.kind == "image" %}<img class="filltable__img" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
{% else %}{{ cell.html|safe }}{% endif %}
```

- `cell.media` is a resolved `MediaAsset` (from `resolved_cells()`); a cell that
  failed to resolve was degraded to static `html:""` upstream, so this branch only
  ever sees a real asset.
- Responsive sizing reuses the ImageElement rule (`max-width:100%`); add a
  `.filltable__img` CSS rule (max-width 100%, height auto, sensible display) if the
  existing cell styles don't already cover an `<img>`.
- Image cells never render an input and are not part of the answer-checking flow
  (`courses/filltable.py:answer_cells` already selects only `kind=="answer"` —
  confirm it ignores the new kind, which it will since it matches on `answer`).

## Parser

`scripts/lal_import/tables.py:fill_table_element` — in the cell loop, before the
static fallback, detect a **pure image cell**: the cell has no answer input, its
`get_text(strip=True)` is empty, and it contains exactly one `<img>`. Emit
`{kind:"image", media_src: <img src>, alt: <img alt or "">}`.

- All 7 affected files' image cells are verified **pure single-`<img>`** cells
  (only a stray `<br>` besides the image), so a mixed image+text cell does not
  occur in the corpus. If a future cell mixes meaningful text with an image, it
  falls through to the existing **static** branch (the image is dropped, exactly as
  today) — no regression, and re-measurement will surface it. Do **not** try to
  split mixed cells in this spec.
- The image `src` is emitted raw (like `_image_dict`'s `media_src`); the loader
  resolves it to an asset. Do not escape or sanitise it here.
- Span/nested/ragged fallback to flagged HtmlElement is unchanged.

## Loader

`courses/lal_loader/builders.py` `fill_table` branch: before `normalize_data`,
walk `el["data"]["cells"]`; for each cell with `kind == "image"`, resolve its
`media_src` → asset and replace the cell with `{kind:"image", media: asset.pk,
alt: cell.get("alt",""), halign, valign}`:

```
path = resolve_source(source_root, source_dir, cell["media_src"])
asset = get_or_create_asset(course, "image", path)   # content-hash dedup, reused
cell → {kind:"image", media: asset.pk, alt: cell.get("alt",""), ...}
```

Then `FillTableElement.objects.create(data=FillTableElement.normalize_data(<rewritten>))`.
- `get_or_create_asset` already dedups by `(course, content_hash)`, so an image
  reused across cells/files uploads once.
- Idempotency: reloading a part re-resolves the same file → same content hash →
  same asset (no duplicate uploads), and the element is delete-and-rebuilt as today.
- A missing source file surfaces the loader's existing missing-media behaviour
  (unchanged; note the pre-existing "bare FileNotFoundError" deferred-Minor).

## Editor

Add a third cell kind to the grid editor. Reuse the media picker rather than
inventing a new one.

- **`_edit_filltable.html`**: expose the picker's data hooks on the editor root
  (upload/list URLs are already available to `media_picker.js` via the editor page).
  Add an **"Image cell"** toolbar toggle (peer of the existing "Answer cell"
  toggle) and a small optional **alt** input that appears when the focused cell is
  an image cell.
- **`filltable_editor.js`**:
  - A cell can now be in one of three states: static (`td[contenteditable]`),
    answer (`td[data-answer]` with an `<input>`), or **image**
    (`td[data-image]` holding a thumbnail `<img>` + a hidden media id + optional
    alt). Extend `dataCells`/counting to include `td[data-image]` (as `dataCells`
    already must see answer cells, so an image column is not skipped on resize).
  - "Image cell" toggle on the focused static/answer cell → open the media picker
    in a **new cell-target mode**. Add a hook analogous to `libliGalleryAdd`: the
    editor registers the target cell, the picker calls back with `(id, name, url)`,
    the editor renders a thumbnail into the cell, stashes the media id, and
    serialises. (In `media_picker.js`, generalise the append-mode branch to also
    support this cell callback, or add a parallel `window.libliFillTableSetImage`
    hook — decide in planning; prefer the smallest change that doesn't disturb
    gallery append.)
  - The **stash** mechanism (reversible static↔answer toggle) extends to image:
    toggling a cell's kind remembers the other kinds' content so a round-trip does
    not lose the author's work. First-time → image seeds empty; image → static/
    answer restores stashed html/answer.
  - `serialize()` emits `{kind:"image", media: <int id>, alt: <input value>,
    halign, valign}` for image cells. `media` must serialise as a **number**
    (JSON int), matching `_cell`'s int check.
  - **Deserialize / edit path**: the server renders an existing image cell into the
    editor DOM as a `td[data-image]` with its thumbnail + hidden id + alt, so
    re-editing a saved grid round-trips. (`_edit_filltable.html` renders the
    existing grid server-side; add an image branch there mirroring the answer/static
    branches, using `resolved_cells()` so the thumbnail URL is available.)
  - **Submit guard** (`onSubmit`): image cells are **not** answer cells, so the
    "at least one answer cell / no blank answers" checks ignore them. A grid whose
    only fillable cells are answers still validates as today; a grid with image
    cells + ≥1 answer cell is valid. (An all-image / no-answer grid remains invalid
    under the existing "mark at least one answer cell" rule — acceptable; the shape
    always pairs images with answer cells.)
- **Form / validation** (`FillTableElementForm` or the consuming view): the
  hidden `data` JSON is normalised through `FillTableElement.normalize_data` /
  `_sanitized_data` on save, so an image cell with an invalid media id degrades to
  empty static server-side (defence in depth) — the editor should still prevent it
  client-side by only writing a media id the picker returned.

## Wiring & flags

- `has_math` detection (`courses/views.py` ~139): a `FillTableElement` has math
  if any **static** cell contains math. Image cells hold no html → contribute no
  math. Confirm the math-detection helper still only scans static-cell html (it
  does today; the image branch must not break it).
- No `FORMAT_VERSION` bump: the transfer format already round-trips
  `FillTableElement.data`; an extra cell kind rides along.
- **Transfer media registration is a REQUIRED component, not a rider** (verified in
  `courses/transfer/`). Today `_ser_fill_table` returns `dict(el.data)` **raw**,
  and `_build_fill_table` calls `normalize_data(data)` **without touching media** —
  correct while cells hold no media, but an image cell's `media` pk would export as
  a raw local pk and import dangling. Fix, mirroring the gallery path exactly:
  - **Export** `_ser_fill_table` (`export.py` ~170): walk `cells`; for each
    `kind=="image"` cell, resolve its pk and replace `media` with
    `ids.register(asset)` (the bundle-local id), **skipping unresolved** pks by
    degrading that cell to empty static (same "unresolved ids cannot be exported"
    rule `_gallery_assets` uses). Static/answer cells pass through.
  - **Import** `_build_fill_table` (`importer.py` ~589): walk `cells`; for each
    `kind=="image"` cell, remap `media` via `assets[<local id>].pk` (mirroring
    `_build_gallery`'s `assets[img["media"]].pk`), then `normalize_data` + save.
  - **Validator** `courses/transfer/payloads.py`: extend the fill_table cell
    validator to accept an `image` cell shape (an int `media` + optional `alt`),
    alongside the existing static/answer shapes. Keep the three registries
    (`SERIALIZERS`, `VALIDATORS`, `BUILDERS`) in lockstep.
  - Round-trip test: export→import a fill-table with an image cell across a
    fresh asset namespace preserves the image (bundled asset, remapped pk).

## Testing

Follow the established TDD pattern (parser test in `test_lesson.py` /
`test_tables.py`; loader test in `test_lal_loader_units.py`; model/form/render
tests under `courses/tests/`). Each test must be **falsifiable** (RED first — see
the "Falsify tests, don't run them" lesson).

- **Model**: `_cell` accepts a valid image cell; rejects non-int / bool / missing
  media → empty static; `resolved_cells()` resolves pks and skips unresolved;
  `_sanitized_data` leaves image cells' media intact and trims alt; `canonical_cells`
  passes image cells through; a `mine.done` render keeps images.
- **Render**: an image cell renders `<img src=…>` with the resolved asset URL and
  alt; an unresolved pk renders nothing broken (degraded static).
- **Parser**: a `table_input` table with a pure-`<img>` cell emits
  `{kind:"image", media_src, alt}`; a mixed text+img cell stays static (documents
  the deliberate non-split); answer/static unchanged.
- **Loader**: loading a fill-table with an image cell uploads/dedups the asset and
  stores `media: asset.pk`; reloading is idempotent (no duplicate asset).
- **Editor** (JS + form): serialising an image cell yields the right JSON;
  round-trip through the edit path preserves the image; the answer-required submit
  guard ignores image cells. (Editor JS tested at whatever level the repo already
  tests `filltable_editor.js` — e2e if that's the convention, else a form/round-trip
  test.)
- **Regression**: an existing fill-table with only static/answer cells is byte-for-
  byte unchanged through normalize/save/render.

## Verification (end to end)

- Reseed the 7 affected parts (`010_funkcja_liniowa`, `030_kwadratowa`,
  `070_geometria`, `100_geometria_2`, `104_geometria_3_czworokaty`,
  `110_przeksztalcanie_wykresow_funkcji`) with `--force`, reload into `libli_mat`.
- Re-run the recursion-aware `measure_lost_imgs_recursive.py`: the **fill-table
  bucket drops 31 → 0**; total lost drops 76 → ~45 (the sub-spec B tail remains).
- Hand the user live URLs (DEBUG server) for an image-cell grid, e.g. the
  `f_lin_023` / `wykresy_20` units, to confirm images render above/beside the
  inputs and the self-check still works.

## Out of scope

- Mixed image+text cells (none in corpus; would fall through to static).
- Sub-spec B (reveal-cell, question-stem, figure-in-spoiler, inline extraction).
- Any change to answer-checking semantics or marks (image cells are inert prompts).
