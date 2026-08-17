# Media Image Derivatives

## Purpose

The media library is unusable on a large course. Entering it leaves the grid without
image previews for minutes.

Measured against the real local `mat-pp` database (2026-08-17):

| Measurement | Value |
| --- | --- |
| Assets in `mat-pp` | 1185 (953 images, 232 videos) |
| Server render of `/manage/courses/mat-pp/media/` | 2.2 s, 14 queries, 2.1 MB of HTML |
| Serving one media file through the stack | 4 ms |
| Image bytes on disk | 58.6 MB (median 38 KB, p90 77 KB) |
| Median image resolution | ~925,000 px (roughly 1100x840) |
| Thumbnail display size | ~180x135 = 24,300 px |
| Median oversampling factor | **38x** |
| Total decoded bitmap if all images load | **~3.7 GB** of RGBA |

Image composition of those 953 (measured, Pillow): 485 `RGB`, 449 `RGBA`, 19 `P`
(palette); 18 are animated. 928 are PNG; the remaining 25 are JPEG/GIF/WebP —
`SAFE_IMAGE_EXTENSIONS` (`courses/validators.py:34`) permits `png, jpg, jpeg, gif, webp`.

The bytes are not the problem; the **decode** is. `_asset_cell.html:7` sets the
thumbnail `src` to the full-resolution original, so the browser decompresses and
downscales ~950 images totalling ~3.7 GB of bitmap, exceeds its image-cache ceiling, and
begins evicting and re-decoding on scroll. There is no derivative image, no
`loading="lazy"`, and no pagination.

**Goal:** serve appropriately-sized images on every in-scope surface, without changing a
single rendered layout, and without a commit at which any surface is degraded.

### Measured cost of the change

Derivatives for all 953 images, measured by generating both widths over a random
60-image sample and projecting:

| | Bytes |
| --- | --- |
| Originals on disk today | 58.6 MB |
| `thumb` set (320px, all 953) | ~9 MB |
| `web` set (896px, all 953) | ~21 MB |
| **Added disk** | **~30 MB** |

Measured at both candidate `web` widths: 648px yields ~20 MB and 896px ~21 MB. The wider
derivative is therefore effectively free, because the originals wide enough to exceed 896
are the same ones that dominated the 648 set.

## Scope

### In scope — nine `<img>` sites across seven templates

Verified inventory (confirmed exhaustive by grepping every `<img` under `templates/`):

| Template | Line(s) | Surface |
| --- | --- | --- |
| `templates/courses/manage/media/_asset_cell.html` | 7 | Media manager grid |
| `templates/courses/manage/media/_picker_grid.html` | 6 | Editor's image picker grid |
| `templates/courses/elements/imageelement.html` | 2 | Student image element |
| `templates/courses/elements/_table_cell.html` | 1 | Student table cell |
| `templates/courses/elements/_filltable_cell.html` | 1 | Student fill-table cell |
| `templates/courses/elements/dragtoimagequestionelement.html` | 9 **and** 32 | Student drag-to-image (two `<img>`, not one) |
| `templates/courses/elements/galleryelement.html` | 14 | Student gallery |

The **picker grid** is not a secondary surface: it renders the same
`assets_with_usage(course)` result set through the same `.asset-grid` / `.asset-thumb`
CSS (`editor.css:349,360`), so it exhibits the reported symptom identically, and every
author opens it whenever they insert an image.

The **gallery** needs a Python change as well as a template change.
`galleryelement.html:14` reads `{{ f.url }}`, and `GalleryElement.render()`
(`courses/models.py:1649-1651`) builds `figures.append({"url": img["media"].file.url, ...})`
— the `MediaAsset` is discarded before the template sees it. `render()` must keep the
asset in the figure dict (`{"asset": img["media"], ...}`).

Each of the seven templates needs its own `{% load courses_media_extras %}`. Django does
**not** inherit `{% load %}` across `{% include %}`, and today `imageelement.html`,
`galleryelement.html` and `_table_cell.html` load nothing at all, while
`_filltable_cell.html` and `_picker_grid.html` load only `i18n`. A missed load is a
`TemplateSyntaxError` at render.

### Out of scope — stated, with reasons

- **Editor preview twins**: `_edit_table.html:93,100`, `_edit_filltable.html:114,121`,
  `_edit_gallery.html:30`. These render originals into 40–200px boxes and have the same
  waste. Deferred **deliberately**, because four JavaScript modules rebuild that markup
  client-side from the picker's `data-url` — `table_editor.js:302-305`,
  `filltable_editor.js:475-483`, `gallery_editor.js:115`, `zone-editor.js:74-75`.
  Changing the server-rendered half without the JS half is exactly the editor twin-drift
  this repo has been bitten by before. Leaving **both** halves untouched keeps them
  consistent, costs only author-side bytes on a surface showing a handful of images, and
  keeps this change reviewable. Recorded as a follow-up.
- **Video poster frames** — would add ffmpeg as a system dependency for 232 videos.
- **Grid pagination** — addresses the 2.2 s TTFB. See "Server cost" below, which
  quantifies what this change does to that metric so the deferral is made on real numbers.

## Architecture

### Storage model

Five new fields on `MediaAsset`, all optional:

| Field | Type | Meaning |
| --- | --- | --- |
| `width` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel width of the original |
| `height` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel height of the original |
| `thumb` | `FileField(upload_to="courses/media/derivatives/", max_length=200, blank=True)` | 320px-wide derivative |
| `web` | `FileField(upload_to="courses/media/derivatives/", max_length=200, blank=True)` | 896px-wide derivative |
| `derivatives_state` | `CharField(max_length=10, choices=DerivativesState.choices, blank=True, default="")` | `""` pending, `ok`, `skipped`, `failed` |

`file` stays a `FileField`, deliberately **not** promoted to `ImageField` with
`width_field`/`height_field`: the same column carries the 232 video assets, which
`ImageField` validation would reject.

**`max_length=200`, not Django's default 100.** `MediaAsset.file` uses the default, and
its stored names already sit close to it; `courses/media/derivatives/` is 12 characters
longer than `courses/media/`, plus a `-896.webp` suffix and any storage collision suffix.
At 100 Django's `get_available_name` would silently truncate stems for the long-named
assets the LAL import produced — raising collision pressure — and can raise
`SuspiciousFileOperation` outright.

`derivatives_state` is a **`TextChoices` class** (`DerivativesState`), not bare string
literals, and the backfill filters against it. The four values are load-bearing for
idempotency, so a typo'd `"skiped"` written by a future call site must be a hard error,
not a row silently reprocessed forever.

It exists because the other four fields cannot express the difference between *declined*,
*interrupted*, and *failed*: `width` populated with both derivatives blank is the stored
shape of all three.

- `""` — never attempted. Backfill processes it.
- `ok` — derivatives generated (one or both; a narrow original legitimately yields one).
- `skipped` — deliberately declined: animated, or narrower than both targets. Backfill
  leaves it alone unless `--force`.
- `failed` — generation raised. Backfill retries it.

**Migration `0059`** — schema-only, five `AddField` operations, no data migration, fully
reversible.

### Derivative widths

**The content column is not a single number, and the spec must not pretend it is.**
`.el--image` is deliberately **absent** from the collapsed-TOC prose-cap allow-list
(`courses.css:1141-1157`, which lists `.el--text`, the question parts,
`.lesson-unit__title`, `.unit-crumbs`, `.markdone`, `.fillgate`, `.stepper`,
`.switchgate`, `.guessnumber` — no image root). So `html.unit-tree-collapsed` — a
persisted global toggle — widens the box an image fills well beyond 46rem. Separately,
`.lesson { max-width: 46rem }` (`courses.css:292`) is 736px wherever a lesson renders
outside the unit shell, including the editor preview whose `.prev-inner` is also
`max-width: 46rem` (`editor.css:66`).

**Required measurement.** Implementation must measure and record, in the plan:

1. `.el--image--full`'s rendered width with the TOC expanded,
2. the same with `html.unit-tree-collapsed`,
3. the same in the editor preview,
4. `.asset-thumb`'s rendered width in the manager grid, and
5. the same in the picker grid.

`.asset-grid` is `repeat(auto-fill, minmax(8rem, 1fr))` (`editor.css:349`) with no
container `max-width`, and `1fr` stretches tracks to fill, so (4) and (5) are genuinely
unknown rather than assumed.

**Provisional widths, pending those measurements:**

- **`thumb` = 320px** — covers the grids and the table-cell presets
  (`.cell-img--small/medium/large` = 80/160/240px, `courses.css:1326-1328`). If either
  measured grid width exceeds 320 CSS px at DPR 1, this must be raised.
- **`web` = 896px** — chosen to cover the widest measured box rather than the narrowest.
  If measurement (2) exceeds 896, this must be raised. A `web` of 648px would under-declare
  by up to 35% in the collapsed-TOC state and the browser would upscale a 648px derivative
  into a wider box — a visible-blur regression on the primary student surface, in a state
  the user can toggle globally.

Both derivatives are **lossless WebP**. The content is maths diagrams — thin strokes,
small labels, subscripts — where lossy ringing is precisely the artifact that would hurt
legibility.

**A derivative that is not smaller than its source is discarded** (field left blank).
25 of the 953 images are JPEG/GIF/WebP, and a lossless-WebP derivative of a photographic
JPEG can exceed the JPEG original's bytes, in which case serving it would be a strict
regression. The check is a byte comparison at encode time and costs nothing.

### Generation module: `courses/derivatives.py`

Public surface:

```
generate_derivatives(asset) -> str       # returns the new derivatives_state; sets fields
delete_derivative_files(names, storage)  # names: iterable of storage names, may be blank
```

`delete_derivative_files` takes **names, not an asset**, because its two callers both need
to delete files that are no longer the asset's: `replace_asset` deletes the *superseded*
names captured before reassignment, and `post_delete` runs when the row is already gone.
An asset-shaped argument would delete the wrong files in the first case. It does not touch
model fields; clearing them is the caller's job where a live row survives.

`generate_derivatives` is **best-effort and never raises**. Rules, in order:

1. `asset.kind != "image"` → return `skipped`.
2. Open with Pillow; apply `ImageOps.exif_transpose`.
3. Record `width`/`height` from the transposed image.
4. `getattr(img, "is_animated", False)` → record dimensions, generate no derivatives,
   return `skipped`. Downscaling an animated GIF flattens it to one frame; the 18
   animated images in `mat-pp` must keep animating. The check is on the animation flag,
   not the extension, so a single-frame GIF still gets derivatives.
5. **Normalise the mode before resizing.** Convert to `RGBA` when the source has alpha
   (`mode in ("RGBA", "LA", "PA")` or `"transparency" in img.info`), otherwise `RGB`.
   Load-bearing and non-obvious: `Image.resize` downgrades `resample` to `NEAREST` for
   modes `"1"` and `"P"`, silently ignoring `LANCZOS`. Verified against the project's
   Pillow 12.2.0 — `Image.new("P",(1000,800)).resize((320,256), Image.LANCZOS)` returns
   mode `P`, nearest-neighbour aliased, i.e. *worse* than the browser's own downscale.
   Measured prevalence in `mat-pp` is low — 19 of 953 are mode `P`, and 18 of those are
   animated and excluded at step 4, leaving one — so this is a correctness fix against
   future PNG-8 uploads and the spec's own single-frame-GIF case, not a fix for a
   widespread current defect.
6. For each target width, skip if `img.width <= target`.
7. Resample with `Image.LANCZOS`, save with `format="WEBP", lossless=True`; discard the
   result if it is not smaller than the source file.
8. Return `ok` if anything was written, `skipped` if steps 6–7 declined both.
9. **The entire body — decode, resize, encode, and both storage writes — sits inside one
   guard catching broad `Exception`, logging, and returning `failed`.** Not a fixed tuple
   of Pillow exceptions: the riskiest step is not the decode but
   `FieldFile.save(name, content, save=False)`, a storage write that can raise
   `SuspiciousFileOperation`, permission or quota errors, or backend-specific exceptions.
   A narrow catch would let a storage failure propagate out of an upload request, breaking
   the stated invariant.

Derivative filenames are `<original-stem>-320.webp` / `-896.webp`, written through
`FieldFile.save(name, content, save=False)` so Django's storage applies its own collision
suffix. **Each row therefore owns its derivative files outright.** This is load-bearing:
migration `0008` copied storage references verbatim, so two `MediaAsset` rows can share
one `file.name` — the hazard `_delete_file_if_unshared` exists to guard. Derivatives are
generated per row and never shared, so their deletion needs no such guard and must not
borrow one.

### Render path: one template tag

Nine call sites need this logic. Duplicating it nine times guarantees drift, so a single
tag in `courses/templatetags/courses_media_extras.py` owns it.

**A `simple_tag` returning `format_html(...)`, not an `inclusion_tag`.** An
`inclusion_tag` performs a full template load-and-render per invocation — ~950 nested
renders on the manager grid where there are currently zero, plausibly adding hundreds of
milliseconds to the very TTFB metric against which pagination is being deferred.

```
{% media_img asset preset="el-full" alt=el.alt css_class="cell-img cell-img--full" extra="data-asset-preview" %}
```

#### The tag must emit per-site classes and attributes

The nine sites carry different, load-bearing attributes, and **every layout invariant in
this spec depends on those classes surviving**:

| Site | Required attributes |
| --- | --- |
| `_asset_cell.html:7` | `class="asset-thumb"`, `data-asset-preview` |
| `_picker_grid.html:6` | `class="asset-thumb"` (no `data-asset-preview`) |
| `imageelement.html:2` | no class; `data-zoomable` |
| `_table_cell.html:1` | `class="cell-img cell-img--{size}"`, `data-zoomable` |
| `_filltable_cell.html:1` | `class="filltable__img cell-img cell-img--{size}"`, `data-zoomable` |
| `dragtoimagequestionelement.html:9,32` | `class="dragimage__img"` |
| `galleryelement.html:14` | no class; `data-zoomable` |

`media_preview.js` is armed off `[data-asset-preview]`, so dropping it silently disables
the hover preview. The tag therefore takes an explicit `css_class` and an `extra`
attribute string; the preset governs sizing only, never the class list.

#### Presets composed from data

Five sites need the preset derived at render time, not written as a literal:
`imageelement.html` renders `el--image--{{ el.size }}`, and the table and fill-table cells
render `cell-img--{{ cell.size|default:'full' }}`. The tag accepts a composed value
(`preset="el-"|add:el.size` in the template, or an equivalent expression).

**An unknown preset raises at render time** — degrading silently to a plain `src` would be
the exact silent no-op this design exists to prevent. That raise is unreachable from
stored data, and this must stay true: `ImageElement.size` is a `TextChoices` field, and
`TableElement._cell` (`models.py:1157-1167`) and `FillTableElement._cell` (`:1343-1353`)
both normalise `size` against `CellImageSize.values`. **The preset key set is a superset of
`ImageElement.Size.values` and `TableElement.CellImageSize.values`**, asserted by a test,
so a drifted stored value can never 500 a student lesson page.

`alt` **defaults to `""`**: `_asset_cell.html` and `_picker_grid.html` pass nothing
(decorative — the name is in the adjacent label), `imageelement.html` and both
`dragtoimagequestionelement.html` sites pass `el.alt`, the table cells pass `cell.alt`,
the gallery passes `f.alt`.

#### Two descriptor strategies, chosen by box type

**Fixed-size boxes use `x` descriptors**, because a fixed box's required pixel width is
fully determined by DPR — no `sizes` guess is involved. This also avoids a defect `w`
descriptors would introduce: with `w` descriptors the browser multiplies `sizes` by DPR
and picks the smallest candidate at or above the result, so a `sizes` of `200px` at DPR 2
would select the **896w** candidate and the `thumb` would never be used on precisely the
retina laptops the complaint came from.

**Descriptors are derived from each box's CSS width, not copied uniformly.** An 80px box
needs 160 device px at DPR 2, which the 320px thumb already covers twice over; assigning
it `web 2x` would fetch the 896px derivative for an 80px image — an 11x linear oversample.

| Preset | CSS box | Strategy |
| --- | --- | --- |
| `grid` | `.asset-thumb` (measured; provisionally ~180px) | `x`: `thumb 1x, web 2x` |
| `cell-small` | `.cell-img--small` (80px both axes) | `x`: `thumb 4x` |
| `cell-medium` | `.cell-img--medium` (160px both axes) | `x`: `thumb 2x` |
| `cell-large` | `.cell-img--large` (240px both axes) | `x`: `thumb 1x, web 2x` |
| `cell-full` | `.cell-img--full` (100% of its `<td>`) | `w` + `sizes` — see below |
| `el-small` | `.el--image--small` (25%, `max-height: 30dvh`) | `w` + `sizes="(max-width: 640px) 25vw, 224px"` |
| `el-medium` | `.el--image--medium` (50%, `max-height: 45dvh`) | `w` + `sizes="(max-width: 640px) 50vw, 448px"` |
| `el-large` | `.el--image--large` (75%, `max-height: 60dvh`) | `w` + `sizes="(max-width: 640px) 75vw, 672px"` |
| `el-full` | `.el--image--full` (`max-height: 100dvh`) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |
| `gallery` | `.gallery__frame` (100%, `aspect-ratio: 4/3`, `max-height: 70vh`) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |
| `dragimage` | `.dragimage__img` (column) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |

The `el-*` pixel values are 25/50/75/100% of the **widest** measured column, so they must
be recomputed once the required measurements above are taken; the values shown assume 896.

**When `web` is blank, the original becomes the top `x` candidate.** Step 6 skips `web`
whenever the original is no wider than 896, so a 500px original would otherwise yield
`srcset="<thumb> 1x"` alone — and `src` is **not** treated as an implicit 1x candidate
when the srcset already carries a 1x entry, so a DPR-2 display would get the 320px thumb
upscaled where today it gets a crisp 500px original. The rule: for `x` presets, if `web`
is blank the original is emitted as the highest density candidate its intrinsic width
supports.

**640px, not 700px.** The dominant breakpoint in this codebase is `max-width: 640px`
(13 occurrences across `core/css/app.css` and `courses.css:609,978,1231`), with a
`min-width: 641px` complement; `720px` governs only `editor.css:397,666` and
`builder.css:2,21`. No `700px` breakpoint exists anywhere in the project's CSS.

The preset table and the CSS are a **deliberate coupling**; the tag module carries a
comment saying so and naming the selectors.

**`cell-full` and the width axis.** `.cell-img--full` is `max-width: 100%` **of its
`<td>`**, not of the content column, so a four-column table gives each cell roughly a
quarter of the column and a `sizes` of `896px` would over-declare by ~4x. Implementation
must measure a representative multi-column table cell and set `cell-full`'s `sizes` from
it. This is a distinct, larger error than the height-axis over-fetch accepted below and is
not covered by it.

**Known height-axis over-fetch, accepted.** Every preset is a two-axis bounding box —
`.el--image--*` cap at `30/45/60/100dvh` (`courses.css:90-93`), `.cell-img--*` at
80/160/240px in *both* axes — but `sizes` describes width only. A portrait image at
`el-full` renders far narrower than its declared width because the height cap binds first,
yet `sizes` still declares the full width. Accepted: the worst case is fetching `web`
instead of `thumb`, still far below the original, and a height-aware rule cannot be
expressed in `sizes`.

`srcset` candidates are emitted only for derivatives that exist. For `w`-descriptor
presets the original is always included as the largest candidate. **The `srcset` and
`sizes` attributes are omitted entirely when the candidate list would hold fewer than two
entries** — an animated GIF in the grid has both fields blank, and `srcset=""` is a
degenerate candidate list.

**Degenerate inputs.** `asset.file.url` raises `ValueError` on a blank `FileField`:

- `asset is None` → render nothing.
- `not asset.file.name` → render nothing.
- `asset.width is None` → emit a plain `src` with **no** `srcset`. A `w` descriptor
  without a real pixel width is a lie the browser acts on.

These guards are only reachable on the seven element-template sites. `_asset_cell.html:3`
and `_picker_grid.html:5` both emit `data-url="{{ asset.file.url }}"` on the wrapper
*before* the `<img>`, so a blank-file asset 500s those pages before the tag is reached.
Those two `data-url` attributes are left as they are — the pre-existing behaviour is out
of scope — and the guard's tests must therefore target an element template.

### Layout invariants

The tag emits `loading="lazy"` and `width`/`height` from the stored dimensions.

**`height: auto` is required per preset and is not globally provided.**
`core/static/core/css/reset.css:11` is `img, picture, svg { display: block; max-width: 100%; }`
— no `height: auto`. Where a binding `max-width`/`max-height` meets `width`/`height`
attributes without `height: auto`, the image distorts. Audit: `.el--image img`
(`courses.css:46`), `.cell-img` (`:1325`), `.dragimage__img` (`:538`) declare it;
**`.gallery__frame img` (`:1647`) does not** — it has `max-width:100%; max-height:100%;
object-fit: contain`, and relies on its frame's `aspect-ratio: 4/3`. Invariant to state
and test: *every preset's CSS declares `height: auto` or an explicit `aspect-ratio`.*

**The reflow benefit does not apply to the grid.** `.asset-thumb` already declares
`width: 100%; aspect-ratio: 4 / 3; object-fit: cover` (`editor.css:360-365`), so its box
is fully determined before any image loads and the CSS `aspect-ratio` overrides the
attribute-derived ratio. The grid does not reflow today. The benefit is real only on
`.el--image`, `.cell-img*` and `.dragimage__img`, and is claimed only there.

### Lazy loading is not optional

The derivative bounds cost **per image**; `loading="lazy"` bounds **how many** decode.
At DPR 1 the grid selects the 320w thumb: ~950 of them is still ~285 MB of bitmap if all
decode at once. At DPR 2 the grid selects the 896w candidate. With lazy loading only the
~24 on screen decode. Both mechanisms are required; either alone leaves the reported
symptom substantially in place.

### Print

`courses.css:103-108` and `:1349-1351` are hand-tuned `@media print` blocks capping images
at 45/75/110/170 mm, with a comment explaining the reasoning — print is intended to work.
A browser prints whichever candidate is already loaded, so a `full` image printed at
170 mm will come from the `web` derivative rather than the original.

**Accepted, with the reason stated:** `sizes` accepts a `<media-condition>`, which does
**not** admit media *types*, so `sizes="print 170mm, …"` is not valid and there is no
`sizes`-level fix. At 896px across 170 mm the effective density is ~134 dpi, above the
~96 dpi a browser assumes for CSS-px-to-physical mapping, so the printed result is not
upscaled relative to the layout. Recorded here so the trade-off is deliberate rather than
discovered.

### Server cost

Two before/after measurements are required, because this change pushes on the metric
against which pagination is being deferred:

- **HTML size** of `/manage/courses/mat-pp/media/` — adding up to three candidate URLs
  plus `sizes`, `width`, `height`, `loading`, `data-zoom-src` and a class to ~950 `<img>`
  tags materially increases the measured 2.1 MB.
- **Server render time** of the same URL, currently 2.2 s.

Both recorded in the PR, so the deferred pagination decision is taken on real numbers.

### Client-side audit — the silent regressions

Two JavaScript modules independently reconstruct a "big image" from the rendered
element's *effective* source:

- `courses/static/courses/js/media_preview.js:171` —
  `var src = anchor.currentSrc || anchor.getAttribute("src")`
- `courses/static/courses/js/imagezoom.js:74` —
  `dialogImg.src = img.currentSrc || img.src`

Point the grid at a 320px thumb and the hover preview loads the thumb. Add a `srcset` to
student images and `currentSrc` resolves to the `web` derivative, so **click-to-enlarge
stops enlarging** — it shows the size already on screen. Neither fails loudly.

Both modules must read an **explicit full-resolution URL**:

- `media_preview.js` reads `data-url` from the closest `.asset-cell`, which already
  carries the original's URL (`_asset_cell.html:3`).
- `imagezoom.js` reads a new `data-zoom-src` attribute emitted by the tag, falling back
  to `currentSrc || src` when absent so non-tag `<img data-zoomable>` markup keeps working.

Two second-order consequences, handled in the same commit:

- `media_preview.js:172` guards with `anchor.complete && anchor.naturalWidth === 0` →
  caption-only. After the repoint that guard interrogates the *thumb* while a different
  URL is loading, so a broken original would yield a silently empty overlay. The guard
  moves to the overlay image's own `error` handler, which already exists (`:54-58`).
- `imagezoom.js:74` carries the comment `// already fetched: served from cache`,
  load-bearing documentation of why there is no loading state. Pointing at `data-zoom-src`
  makes it a genuine network fetch. The comment must be corrected and the dialog given a
  loading state (the `load`/`error` handlers to hang it on already exist).

**Ordering is a requirement, not a preference:** this JS change lands and is verified
*before* any template emits a derivative `src` or `srcset`. Done in that order there is
never a commit at which zoom or hover preview is degraded.

## Data flow

### Asset creation

| Site | Caller | Generates? |
| --- | --- | --- |
| `courses/media.py:create_asset` | manager upload (`views_media.media_upload`) | yes |
| `courses/media.py:create_asset` | transfer import (`courses/transfer/importer.py:887`) | **no** (`generate=False`) |
| `courses/media.py:replace_asset` | manager replace (`views_media.media_replace`) | yes |
| `courses/lal_loader/media.py:get_or_create_asset` | LAL content import | yes |

The project has no task queue (no Celery/RQ/dramatiq in `pyproject.toml`), and adding one
for two downscales would be disproportionate.

**The transfer importer is the exception.** `_create_media` loops over up to
`TRANSFER_MAX_MEDIA_ENTRIES = 1000` entries (`config/settings/base.py:179`), and the whole
loop runs inside `transaction.atomic()` (`_run_import`, `:1036`). At tens of milliseconds
per image that is 20–60 s of CPU added to one HTTP request holding an open write
transaction — a plausible worker timeout and a real lock-contention risk. So:

- `create_asset` gains a `generate=True` keyword; the importer passes `generate=False`.
- Imported assets land with `derivatives_state=""` and serve originals, which
  blank-is-safe makes correct rather than broken.
- The import completion message tells the user to run `backfill_media_derivatives`; the
  command's `--course` flag exists for exactly this.

**The LAL loader is bulk too, but generates inline.** `get_or_create_asset` is called from
`builders.py:307/396/410` and created `mat-pp`'s 953 images in the first place. It is
reached only from the `import_lal_content` management command
(`courses/management/commands/import_lal_content.py`), never from a request, so there is
no worker timeout to trip and no user waiting on a response; `courses/lal_loader/` opens
no `transaction.atomic` around the loop, so no write transaction is held open either.
Generating inline there is therefore safe and saves a backfill pass. Only the newly-created
branch generates — the `content_hash` dedup early-return must **not** regenerate.

- **`create_asset`** — after `asset.save()`, when `generate` is true call
  `generate_derivatives(asset)` and persist with an explicit
  `update_fields=["width","height","thumb","web","derivatives_state"]`.

### `replace_asset` — the exact sequence

The existing function (`courses/media.py:150-184`) ends with
`asset.save(update_fields=["file", "original_filename", "content_hash"])`. Generating
derivatives *after* that save without extending `update_fields` would silently drop the
five new fields from the UPDATE. Generating them *before* it would read `asset.file` while
it is still an uncommitted `UploadedFile`: Pillow advances the stream, and Django then
writes to storage from the current position, truncating the stored original.
(`_validate_file`'s `getattr(file, "_committed", False)` short-circuit,
`courses/validators.py:83-95`, is sensitive to when the file is touched for the same
reason.)

Required order, inside the existing `@transaction.atomic`:

1. Capture `old_thumb_name`, `old_web_name` and the storages, **before** reassigning.
2. Assign the new file; `full_clean(...)` as today.
3. `asset.save(update_fields=["file", "original_filename", "content_hash"])` — the
   original is now committed to storage.
4. `generate_derivatives(asset)` — reads the **committed** `FieldFile`, so no stream
   position is shared with a pending write. Any read must `seek(0)` regardless.
5. `asset.save(update_fields=["width","height","thumb","web","derivatives_state"])`.
6. `transaction.on_commit(...)` deleting each captured old derivative name **only if it
   differs from the newly written one** — `if asset.thumb.name != old_thumb_name`, and
   likewise for `web`. This mirrors the guard the module already applies to the original
   at `courses/media.py:180-183` ("Storage hands back the SAME name when the old file was
   already missing, in which case the 'old' file is the one just written"). Without the
   comparison, a replace whose old derivative was absent from storage would delete the
   file step 4 just wrote, leaving a non-blank field pointing at nothing. Plus the existing
   `_delete_file_if_unshared` call for the old original.

Deferring deletion to `on_commit` matches what the module already does, and for the same
reason: a rolled-back replace must not strand a live row whose files are already gone.

### Orphaned bytes on rollback

`generate_derivatives` writes to storage *inside* the atomic block, so a rollback discards
the field values but leaves the bytes on disk, unreferenced.

- **`replace_asset`** — register the newly-written derivative names for cleanup on the
  rollback path.
- **The importer** — `_create_media` (`:880-892`) appends only `asset.file.name` to
  `created_files`, and `_run_import` (`:1036`) calls `_cleanup_files(created_files)` on
  *every* failure path (lines `1042/1045/1052/1062`). Because the importer passes
  `generate=False` it writes no derivatives, so this is closed by construction — but the
  invariant is stated and tested, so a later change re-enabling generation on the import
  path cannot silently reintroduce up to 2,000 orphaned files.

### Asset deletion

`courses/signals.py:_delete_mediaasset_file` currently removes `instance.file`. It gains
`delete_derivative_files([instance.thumb.name, instance.web.name], ...)`, deferred through
the same `transaction.on_commit` and guarded the same way (blank or already-missing is a
no-op). `post_delete` — rather than `Model.delete()` — remains correct: a cascade delete
(removing a Course) bulk-deletes rows and never calls `Model.delete()`.

### Transfer export / import

Derivatives are **excluded from the transfer archive**. They are fully reproducible from
the original, so shipping them would inflate every archive against
`TRANSFER_MAX_UNCOMPRESSED_BYTES` for no gain and would need a new manifest field with its
own validation and version bump. Import creates assets with `generate=False`, so no
serialization change is required — only the `created_files` invariant test.

### Backfill

`backfill_media_derivatives` covers the 953 existing `mat-pp` images:

- Processes rows by `derivatives_state`, filtering against the `DerivativesState` choices:
  `""` and `failed` are processed; `ok` and `skipped` are left alone unless `--force`.
- `--dry-run` reports what it would do and writes nothing.
- `--start-at <pk>` for resuming; `--course <slug>` to scope it.
- `--force` regenerates existing derivatives — needed if a target width, the encoder
  settings, or the resampling behaviour changes (in particular the mode-normalisation rule
  would require regenerating any palette-sourced derivative already on disk).
- Reports a running count and a final tally of generated / skipped / failed.
- A failure on one asset logs and continues.

Because blank is the safe state, the command may be interrupted, re-run, or never run.

## Error handling

The governing principle is **blank-is-safe**. A missing derivative *field* is falsy, so
every render path falls back to `asset.file.url`.

**The one honest limit:** a non-blank field pointing at absent bytes yields a broken image,
not a fallback. The tag's only signal is field truthiness, which reflects the database, not
the filesystem; detecting absent bytes would need a `storage.exists()` per derivative —
~1900 stat calls on the manager grid, against a page whose TTFB this change is already
trying not to worsen. Browsers do not retry another `srcset` candidate on a 404. What
prevents that state is the `!=` guard in `replace_asset` step 6, which is the only code
path that could delete a live row's current derivative.

| Condition | Behaviour |
| --- | --- |
| Pillow or storage raises anywhere in generation | Log; fields stay blank; state `failed`; original served |
| Animated image | Dimensions recorded, derivatives skipped, state `skipped`; original served, animation intact |
| Palette (`P`) / `1` mode source | Converted to `RGB`/`RGBA` before resize, so `LANCZOS` is honoured |
| Original narrower than a target width | That derivative skipped |
| Derivative encodes no smaller than the source | Discarded; field left blank |
| `asset is None` or blank `file.name` | Tag renders nothing (never `asset.file.url`, which raises `ValueError`) |
| `width`/`height` unknown (null) | Tag omits `srcset` and emits a plain `src` |
| Fewer than two `srcset` candidates | `srcset` and `sizes` omitted entirely |
| Unknown preset | Raises at render time; unreachable from stored data by the superset rule |
| Backfill hits a bad row | Logged, counted, run continues |
| Replace rolls back | `on_commit` never fires; old derivatives survive with the live row |
| New derivative bytes written, transaction rolls back | Names registered for cleanup; importer closes this by construction (`generate=False`) |

Generation never propagates an exception into an upload request.

## Testing

Ordered so the client audit is verified before anything can regress.

### JS repointing (lands and is verified first)

- Playwright: with a derivative present, the media-manager hover preview loads the
  **original** URL. Assert on the overlay image's resolved `src` — the overlay opens
  either way.
- Playwright: click-to-enlarge on a student image with a `srcset` opens the **original**,
  not the `web` candidate.
- Both are **A/B tests**: shown failing against the un-repointed JS.
- No test asserts a *visible* blur. `.asset-preview` is `width: min(320px, calc(100vw - 16px))`
  with padding and a border (`editor.css:1370-1394`), so the preview renders at roughly
  302 CSS px — a 320w thumb is essentially correct at DPR 1, and headless Chromium runs at
  DPR 1 by default. The URL assertion is the real check.
- Hover preview on an asset whose original is missing shows the caption-only state, via the
  overlay's `error` handler rather than the thumb's `naturalWidth`.

### `courses/derivatives.py`

Fixture discipline: `make_image_asset(course, filename="x.png", size=(1, 1), ...)`
(`tests/factories.py:150`) defaults to a **1x1** PNG. Under step 6 a 1x1 original is
narrower than both targets, so generation returns `skipped` with both fields blank —
indistinguishable from `failed`-with-blank-fields. A test that merely asserts "no crash" or
"original still served" would pass on a completely broken generator. **Every derivative
test passes an explicit `size=` wider than 896px**, except one deliberate narrow case that
asserts `skipped` *specifically*, not merely blank fields. `MediaAssetFactory`
(`tests/factories.py:122-129`) sets a bare storage name with **no bytes on disk** and is
unusable for these tests entirely.

- Downscales to exactly 320/896 px; output decodes as WebP; alpha preserved.
- **A mode-`P` source produces a non-`P` derivative.** This is the test that catches the
  silent `LANCZOS`→`NEAREST` downgrade; it must fail if the conversion is removed.
- Declines for `kind="video"` (`skipped`).
- Skips derivatives for an animated GIF but records dimensions, returns `skipped`, and the
  source is still animated afterwards.
- Skips the derivative when the original is narrower than the target.
- Discards a derivative that encodes no smaller than its source.
- Returns `failed` without raising on a corrupt file **and** on a storage write failure
  (the latter forced by patching the storage backend).
- Applies EXIF orientation.

### Service layer

- `create_asset` populates all five fields; `generate=False` leaves them at `""`.
- `replace_asset` regenerates **and** deletes the superseded derivative files; asserts the
  new field values actually persist (the `update_fields` trap); asserts that when the old
  derivative name is reused the file is **not** deleted (the `!=` guard); a rolled-back
  replace leaves the old files in place.
- `get_or_create_asset` does not regenerate on the `content_hash` dedup hit.
- `post_delete` removes both derivative files.
- Two rows sharing one `file.name` (the migration-`0008` shape, **with real bytes in
  storage**) each get their own derivative files, and deleting one leaves the other's
  intact.
- A deliberately failed import leaves no orphaned files of any kind.

### Template tag

- Emits `x` descriptors for fixed-box presets, with densities derived from the box width,
  and `w` + `sizes` for fluid ones.
- **A test fails when `sizes` is removed from a `w`-descriptor preset** — a `srcset`
  without `sizes` is the exact silent no-op this design exists to prevent.
- Emits the original as the top `x` candidate when `web` is blank.
- Omits `srcset` and `sizes` when fewer than two candidates exist.
- Omits `srcset` when `width` is null; renders nothing for `asset=None` and for a blank
  `file.name` (tested on an element template, the only place those guards are reachable).
- Raises on an unknown preset, **and** the preset key set is asserted to be a superset of
  `ImageElement.Size.values` and `TableElement.CellImageSize.values`.
- Emits the exact per-site class and attribute set from the table above, including
  `data-asset-preview` on the manager cell and not on the picker cell.
- Emits `loading="lazy"`, `width`/`height`, and `data-zoom-src` pointing at the original.
- Every preset's CSS declares `height: auto` or an explicit `aspect-ratio`, asserted
  against the stylesheet.

### Backfill command

Populates a course's assets; `--dry-run` writes nothing; a second run is a no-op;
`--start-at` skips lower pks; `--force` regenerates `ok` rows; `skipped` rows are not
retried without `--force`; `failed` rows are; one corrupt asset does not abort the run.

### Rendering and layout

- Every touched template renders unchanged **layout**, asserted on measured box geometry
  (`bounding_box()`), not a screenshot eyeball, **with a ±1 px tolerance on each axis**.
  The tolerance is required, not slack: a derivative's height is a rounded proportional
  scale of the original's, so their intrinsic ratios differ slightly (1100x841 → 896x685
  is 1.3080 vs 1.3079), and where a height cap binds the used width can shift sub-pixel.
- Screenshots of the media manager, the picker, and a student unit in light and dark,
  judged separately.

### Acceptance — tied to the measured symptom

Two measured checks, each with a threshold:

1. **Candidate selection.** On the media-manager grid, the URL the browser actually
   selects (`img.currentSrc`) is the **320px thumb at DPR 1** and the **896px web
   derivative at DPR 2** — the latter pinned with `device_scale_factor=2`. This proves the
   derivative is reached at all; the DPR-2 case is the one that silently regresses under
   `w` descriptors.
2. **Bytes over the wire.** Total image bytes transferred for the media-manager grid's
   initial viewport at DPR 1. **The threshold is derived from a measured baseline, not
   from the 58.6 MB library total** — that figure is the whole library, and with lazy
   loading alone and no derivatives the initial viewport is only ~24 originals at a median
   38 KB, i.e. under 1 MB. A threshold of "under 2 MB" would therefore pass with
   derivatives entirely absent, discriminating only the lazy-loading half of the change.
   Implementation must measure today's initial-viewport bytes (originals + lazy) and set
   the threshold below it, derived from the measured mean thumb size times the measured
   on-screen count. Recorded in the PR.

### Falsification

Every test is written to fail first. Mutants are chosen from the failure mode each test
claims to defend, not from convenience — specifically the `sizes` removal, the mode-`P`
conversion removal, the `update_fields` truncation in `replace_asset`, and the `!=` guard
removal in step 6, each of which produces a build that looks correct and measures wrong.
