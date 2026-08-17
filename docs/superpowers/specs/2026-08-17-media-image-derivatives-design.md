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
| `web` set (648px, all 953) | ~20 MB |
| **Added disk** | **~29 MB** |

## Scope

### In scope — nine `<img>` sites across seven templates

Verified inventory. Every site below renders a `MediaAsset` image and is changed:

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

The **gallery** needs a Python change as well as a template change. `galleryelement.html:14`
reads `{{ f.url }}`, and `GalleryElement.render()` (`courses/models.py:1649-1651`) builds
`figures.append({"url": img["media"].file.url, ...})` — the `MediaAsset` is discarded
before the template sees it. `render()` must keep the asset in the figure dict
(`{"asset": img["media"], ...}`) so the tag can resolve derivatives. A gallery is many
images in one element, making it among the worst offenders.

### Out of scope — stated, with reasons

- **Editor preview twins**: `_edit_table.html:93,100`, `_edit_filltable.html:114,121`,
  `_edit_gallery.html:30`. These render originals into 40–200px boxes
  (`.table-editor__img--*` `editor.css:958`, `.filltable-editor__img--*`
  `courses.css:1361`, `.gallery-editor__thumb` 64x64 `editor.css:1028`) and have the same
  waste. They are deferred **deliberately**, because four JavaScript modules rebuild that
  same markup client-side from the picker's `data-url` —
  `table_editor.js:302-305`, `filltable_editor.js:475-483`, `gallery_editor.js:115`,
  `zone-editor.js:74-75`. Changing the server-rendered half without the JS half would
  produce exactly the editor twin-drift this repo has been bitten by before. Leaving
  **both** halves untouched keeps them consistent, costs only author-side bytes on a
  surface that shows a handful of images at a time, and keeps this change reviewable.
  Recorded as a follow-up.
- **Video poster frames** — would add ffmpeg as a system dependency for 232 videos; the
  `▶` glyph is adequate.
- **Grid pagination** — addresses the 2.2 s TTFB, a lesser annoyance, and is better
  judged after this lands. See "HTML growth" below, which makes that decision worse, not
  better, and is therefore quantified here.

## Architecture

### Storage model

Five new fields on `MediaAsset`, all optional:

| Field | Type | Meaning |
| --- | --- | --- |
| `width` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel width of the original |
| `height` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel height of the original |
| `thumb` | `FileField(upload_to="courses/media/derivatives/", blank=True)` | 320px-wide derivative |
| `web` | `FileField(upload_to="courses/media/derivatives/", blank=True)` | 648px-wide derivative |
| `derivatives_state` | `CharField(max_length=10, blank=True, default="")` | `""` pending, `ok`, `skipped`, `failed` |

`file` stays a `FileField`, deliberately **not** promoted to `ImageField` with
`width_field`/`height_field`: the same column carries the 232 video assets, which
`ImageField` validation would reject.

`derivatives_state` exists because the other four fields cannot express the difference
between *declined*, *interrupted*, and *failed*. `width` populated with both derivatives
blank is the stored shape of all three, so without this field the backfill can be
idempotent or self-healing but not both. Its values:

- `""` — never attempted. The backfill processes it.
- `ok` — derivatives generated (one or both; a narrow original legitimately yields one).
- `skipped` — deliberately declined: animated, or narrower than both targets. Backfill
  leaves it alone unless `--force`.
- `failed` — generation raised. Backfill retries it (a re-run may succeed after a Pillow
  upgrade or a repaired file).

**Migration `0059`** — schema-only, five `AddField` operations, no data migration (the
backfill is a separate management command), fully reversible.

### Derivative widths

Chosen from the CSS the images actually land in:

- **320px** covers the library and picker grids (`.asset-grid` is
  `repeat(auto-fill, minmax(8rem, 1fr))`, `editor.css:349`) and the table-cell presets
  (`.cell-img--small/medium/large` = 80/160/240px, `courses.css:1326-1328`).
- **648px** is the content column, which `.el--image--full` fills; `large`/`medium`/`small`
  are 75/50/25% of it (486/324/162px, `courses.css:61-63`).

**`.asset-grid` has no container `max-width`**, and `1fr` stretches tracks to fill, so
"cells are 128–200px" is an assumption, not a measurement. Implementation **must measure**
the rendered `.asset-thumb` width at the manager's and the picker's real container widths
and cite both numbers in the plan. If either exceeds 320 CSS px at DPR 1, the thumb width
must be raised to cover it — the 320 figure is provisional until measured.

Both derivatives are **lossless WebP**. The content is maths diagrams — thin strokes,
small labels, subscripts — where lossy ringing is precisely the artifact that would hurt
legibility. (No size claim is made against the source PNG: the derivative is downscaled,
so almost all of its size advantage comes from pixel count, not the codec. The measured
totals are in the table above.)

### Generation module: `courses/derivatives.py`

A single new module owns all image processing. Public surface:

```
generate_derivatives(asset) -> str       # returns the new derivatives_state; sets fields
delete_derivative_files(names, storage)  # names: iterable of storage names, may be blank
```

`delete_derivative_files` takes **names, not an asset**, because its two callers both need
to delete files that are no longer the asset's: `replace_asset` deletes the *superseded*
names it captured before reassignment, and `post_delete` runs when the row is already
gone. An asset-shaped argument would delete the wrong files in the first case. It does not
touch model fields; clearing them is the caller's job where a live row survives.

`generate_derivatives` is **best-effort and never raises**. Rules, in order:

1. `asset.kind != "image"` → return `skipped` (videos have no derivatives).
2. Open with Pillow; apply `ImageOps.exif_transpose` (a JPEG with an orientation tag
   would otherwise produce a sideways derivative).
3. Record `width`/`height` from the transposed image.
4. `getattr(img, "is_animated", False)` → record dimensions, generate no derivatives,
   return `skipped`. Downscaling an animated GIF flattens it to one frame; the 18
   animated images in `mat-pp` must keep animating. The check is on the animation flag,
   not the extension, so a single-frame GIF still gets derivatives.
5. **Normalise the mode before resizing.** Convert to `RGBA` when the source has alpha
   (`mode in ("RGBA", "LA", "PA")` or `"transparency" in img.info`), otherwise `RGB`.
   This is load-bearing and non-obvious: `Image.resize` downgrades `resample` to
   `NEAREST` for modes `"1"` and `"P"`, silently ignoring `LANCZOS`. Verified against the
   project's Pillow 12.2.0 — `Image.new("P",(1000,800)).resize((320,256), Image.LANCZOS)`
   returns mode `P`, nearest-neighbour aliased, i.e. *worse* than the browser's own
   downscale of the original. Measured prevalence in `mat-pp` is low — 19 of 953 images
   are mode `P`, and 18 of those are animated and already excluded at step 4, leaving one
   — so this is a correctness fix against future PNG-8 uploads and the spec's own
   single-frame-GIF case, not a fix for a widespread current defect.
6. For each target width, skip if `img.width <= target` — a 300px original gets no 320px
   derivative, because upscaling adds bytes and no detail. Small originals therefore
   legitimately end with one or both derivatives blank.
7. Resample with `Image.LANCZOS`, save with `format="WEBP", lossless=True`.
8. Return `ok` if anything was written, `skipped` if step 6 declined both.
9. Any Pillow exception (`UnidentifiedImageError`, `OSError`, `DecompressionBombError`)
   → log and return `failed`, leaving derivative fields blank.

Derivative filenames are `<original-stem>-320.webp` / `-648.webp`, written through
`FieldFile.save(name, content, save=False)` so Django's storage applies its own collision
suffix. **Each row therefore owns its derivative files outright.** This is load-bearing:
migration `0008` copied storage references verbatim, so two `MediaAsset` rows can share
one `file.name` — the hazard `_delete_file_if_unshared` exists to guard. Derivatives are
generated per row and never shared, so their deletion needs no such guard and must not
borrow one.

### Render path: one template tag

Nine call sites need this logic. Duplicating it nine times guarantees drift, so a single
inclusion tag in `courses/templatetags/courses_media_extras.py` owns it:

```
{% media_img asset preset="el-full" alt=el.alt zoomable=True %}
```

An **unknown preset raises at render time**. Degrading silently to a plain `src` would be
the exact silent no-op this design exists to prevent.

`alt` **defaults to `""`** and is passed per site: `_asset_cell.html` and
`_picker_grid.html` pass nothing (decorative — the name is in the adjacent label),
`imageelement.html` and both `dragtoimagequestionelement.html` sites pass `el.alt`, the
table/fill-table cells pass `cell.alt`, the gallery passes `f.alt`.

#### Two descriptor strategies, chosen by box type

**Fixed-size boxes use `x` descriptors.** The grid cell is a fixed box, so its required
pixel width is fully determined by DPR — no `sizes` guess is involved:

```
srcset="<thumb> 1x, <web> 2x"
```

This is exact, needs no `sizes`, and removes the grid's dependence on the unverified cell
bound above. It also fixes a defect that `w` descriptors would introduce: with `w`
descriptors the browser multiplies `sizes` by DPR and picks the smallest candidate at or
above the result, so a `sizes` of `200px` at DPR 2 selects the **648w** candidate and the
`thumb` is never used on precisely the retina laptops the complaint came from.

**Fluid boxes use `w` descriptors plus `sizes`.** `sizes` is the load-bearing half:
`srcset` **without** `sizes` defaults to `100vw`, making the browser select the largest
candidate — the opposite of the goal.

| Preset | CSS box | Strategy |
| --- | --- | --- |
| `grid` | `.asset-thumb` | `x`: `thumb 1x, web 2x` |
| `cell-small` | `.cell-img--small` (80px both axes) | `x`: `thumb 1x, web 2x` |
| `cell-medium` | `.cell-img--medium` (160px both axes) | `x`: `thumb 1x, web 2x` |
| `cell-large` | `.cell-img--large` (240px both axes) | `x`: `thumb 1x, web 2x` |
| `cell-full` | `.cell-img--full` (column, `max-height: 60dvh`) | `w` + `sizes="(max-width: 640px) 100vw, 648px"` |
| `el-small` | `.el--image--small` (25%, `max-height: 30dvh`) | `w` + `sizes="(max-width: 640px) 25vw, 162px"` |
| `el-medium` | `.el--image--medium` (50%, `max-height: 45dvh`) | `w` + `sizes="(max-width: 640px) 50vw, 324px"` |
| `el-large` | `.el--image--large` (75%, `max-height: 60dvh`) | `w` + `sizes="(max-width: 640px) 75vw, 486px"` |
| `el-full` | `.el--image--full` (column, `max-height: 100dvh`) | `w` + `sizes="(max-width: 640px) 100vw, 648px"` |
| `gallery` | `.gallery__frame` (100%, `aspect-ratio: 4/3`, `max-height: 70vh`) | `w` + `sizes="(max-width: 640px) 100vw, 648px"` |
| `dragimage` | `.dragimage__img` (column) | `w` + `sizes="(max-width: 640px) 100vw, 648px"` |

**640px, not 700px.** The dominant breakpoint in this codebase is `max-width: 640px`
(13 occurrences across `core/css/app.css` and `courses.css:609,978,1231`), with a
`min-width: 641px` complement; `720px` governs only `editor.css:397,666` and
`builder.css:2,21`. No `700px` breakpoint exists anywhere in the project's CSS.

The preset table and the CSS are a **deliberate coupling**; the tag module carries a
comment saying so and naming the selectors, so a future change to `.cell-img--large` has
a chance of finding its `sizes` counterpart.

**Known over-fetch, accepted.** Every preset is a two-axis bounding box — `.el--image--*`
cap at `30/45/60/100dvh` (`courses.css:90-93`), `.cell-img--*` at 80/160/240px in *both*
axes — but `sizes` describes width only. A portrait image at `el-full` renders far
narrower than 648px because the height cap binds first, yet `sizes` still declares 648px
and the browser fetches the larger candidate. This is accepted rather than corrected:
the worst case is fetching the 648px derivative instead of the 320px one, which is still
far below the original, and encoding a height-aware rule in `sizes` is not possible.

`srcset` candidates are emitted only for derivatives that exist. For `w`-descriptor
presets the original is always included as the largest candidate, so high-DPR displays
still have full resolution:

```
srcset="<thumb> 320w, <web> 648w, <original> {asset.width}w"
```

**Degenerate inputs.** `asset.file.url` raises `ValueError` on a blank `FileField`, so
the specified fallback is itself a crash path unless guarded. The tag's rules:

- `asset is None` → render nothing.
- `not asset.file.name` → render nothing. (The codebase already tolerates unresolvable
  media: `export.py:788` handles blank/absent files, and table and gallery cells degrade
  unresolvable pks to empty.)
- `asset.width is None` → emit a plain `src` with **no** `srcset`. A `w` descriptor
  without a real pixel width is a lie the browser acts on.

### Layout invariants

The tag emits `loading="lazy"` and `width`/`height` from the stored dimensions. Two
constraints govern this:

**`height: auto` is required per preset and is not globally provided.**
`core/static/core/css/reset.css:11` is `img, picture, svg { display: block; max-width: 100%; }`
— no `height: auto`. Where a binding `max-width`/`max-height` meets `width`/`height`
attributes without `height: auto`, the image distorts. Audit result: `.el--image img`
(`courses.css:46`), `.cell-img` (`:1325`), `.dragimage__img` (`:538`) all declare it;
**`.gallery__frame img` (`:1647`) does not** — it has `max-width:100%; max-height:100%;
object-fit: contain`. The gallery preset must therefore either gain `height: auto` or
rely on its `aspect-ratio: 4/3` frame. The invariant to state and test: *every preset's
CSS must declare `height: auto` or an explicit `aspect-ratio`.*

**The reflow benefit does not apply to the grid.** `.asset-thumb` already declares
`width: 100%; aspect-ratio: 4 / 3; object-fit: cover` (`editor.css:360-365`), so its box
is fully determined before any image loads and the CSS `aspect-ratio` overrides the
attribute-derived ratio. The grid does not reflow today. The `width`/`height` benefit is
real only on `.el--image`, `.cell-img*` and `.dragimage__img`, and is claimed only there.

### Lazy loading is not optional

The derivative bounds cost **per image**; `loading="lazy"` bounds **how many** decode.
At DPR 1 the grid selects the 320w thumb: ~950 of them is still ~285 MB of bitmap if all
decode at once. At DPR 2 the grid selects the 648w candidate — ~1.2 GB if all decode.
With lazy loading only the ~24 on screen decode: ~7 MB at DPR 1, ~30 MB at DPR 2. Both
mechanisms are required; either alone leaves the reported symptom substantially in place.

### HTML growth

Adding up to three candidate URLs plus `sizes`, `width`, `height`, `loading` and
`data-zoom-src` to ~950 `<img>` tags materially increases the measured 2.1 MB of HTML.
Implementation must measure and record the new figure, because it makes the deferred
pagination decision worse and that decision should be taken with the right number.

### Client-side audit — the silent regressions

Two JavaScript modules independently reconstruct a "big image" from the rendered
element's *effective* source:

- `courses/static/courses/js/media_preview.js:171` —
  `var src = anchor.currentSrc || anchor.getAttribute("src")`
- `courses/static/courses/js/imagezoom.js:74` —
  `dialogImg.src = img.currentSrc || img.src`

Point the grid at a 320px thumb and the hover preview loads the thumb. Add a `srcset` to
student images and `currentSrc` resolves to the 648px derivative, so **click-to-enlarge
stops enlarging** — it shows the size already on screen. Neither fails loudly.

Both modules must read an **explicit full-resolution URL**:

- `media_preview.js` reads `data-url` from the closest `.asset-cell`, which already
  carries the original's URL (`_asset_cell.html:3`).
- `imagezoom.js` reads a new `data-zoom-src` attribute emitted by the tag, falling back
  to `currentSrc || src` when absent so non-tag `<img data-zoomable>` markup keeps working.

Two second-order consequences must be handled in the same commit:

- `media_preview.js:172` guards with `anchor.complete && anchor.naturalWidth === 0` →
  caption-only. After the repoint that guard interrogates the *thumb* while a different
  URL is loading, so a broken original would yield a silently empty overlay. The guard
  must move to the overlay image's own `error` handler, which already exists (`:54-58`).
- `imagezoom.js:74` carries the comment `// already fetched: served from cache`, which is
  load-bearing documentation of why there is no loading state. Pointing at `data-zoom-src`
  makes it a genuine network fetch. The comment must be corrected, and the dialog given a
  loading state (the `load`/`error` handlers to hang it on already exist).

**Ordering is a requirement, not a preference:** this JS change lands and is verified
*before* any template emits a derivative `src` or `srcset`. Done in that order there is
never a commit at which zoom or hover preview is degraded.

## Data flow

### Asset creation

Three construction sites exist:

| Site | Caller |
| --- | --- |
| `courses/media.py:create_asset` | manager upload (`views_media.media_upload`), transfer import (`courses/transfer/importer.py:887`) |
| `courses/media.py:replace_asset` | manager replace (`views_media.media_replace`) |
| `courses/lal_loader/media.py:get_or_create_asset` | LAL content import |

Generation is **synchronous** for single-file paths. The project has no task queue (no
Celery/RQ/dramatiq in `pyproject.toml`), and adding one for two downscales would be
disproportionate; an upload already pays a multipart round-trip.

**The bulk path is the exception.** `courses/transfer/importer.py:_create_media` loops
over up to `TRANSFER_MAX_MEDIA_ENTRIES = 1000` entries
(`config/settings/base.py:179`), and the whole loop runs inside `transaction.atomic()`
(`_run_import`, `:1036`). At tens of milliseconds per image that is 20–60 s of CPU added
to one HTTP request holding an open write transaction — a plausible worker timeout and a
real lock-contention risk. Therefore:

- `create_asset` gains a `generate=True` keyword.
- The importer passes `generate=False`. Imported assets land with
  `derivatives_state=""` and serve originals, which blank-is-safe makes correct rather
  than broken.
- The import completion message tells the user to run `backfill_media_derivatives`, and
  the command's `--course` flag exists for exactly this.

Per-site behaviour:

- **`create_asset`** — after `asset.save()`, when `generate` is true call
  `generate_derivatives(asset)` and persist with an explicit
  `update_fields=["width","height","thumb","web","derivatives_state"]`.
- **`get_or_create_asset`** — only the newly-created branch generates. The `content_hash`
  dedup early-return must **not** regenerate.
- **`replace_asset`** — ordering is pinned below, because both plausible orders are broken.

### `replace_asset` — the exact sequence

The existing function (`courses/media.py:150-184`) ends with
`asset.save(update_fields=["file", "original_filename", "content_hash"])`. Generating
derivatives *after* that save without extending `update_fields` would silently drop the
five new fields from the UPDATE. Generating them *before* it would read
`asset.file` while it is still an uncommitted `UploadedFile`: Pillow advances the stream,
and Django then writes to storage from the current position, truncating the stored
original. (`_validate_file`'s `getattr(file, "_committed", False)` short-circuit,
`courses/validators.py:83-95`, is sensitive to when the file is touched for the same
reason.)

The required order, inside the existing `@transaction.atomic`:

1. Capture `old_thumb_name`, `old_web_name`, and the storages, **before** reassigning.
2. Assign the new file, `full_clean(...)` as today.
3. `asset.save(update_fields=["file", "original_filename", "content_hash"])` — the
   original is now committed to storage.
4. `generate_derivatives(asset)` — reads the **committed** `FieldFile`, so no stream
   position is shared with the pending write. Any read must `seek(0)` regardless.
5. `asset.save(update_fields=["width","height","thumb","web","derivatives_state"])`.
6. `transaction.on_commit(...)` deleting the captured old derivative names, plus the
   existing `_delete_file_if_unshared` call for the old original.

Deferring deletion to `on_commit` matches what the module already does, and for the same
reason: a rolled-back replace must not strand a live row whose files are already gone.

### Orphaned bytes on rollback

`generate_derivatives` writes to storage *inside* the atomic block, so a rollback discards
the field values but leaves the bytes on disk, unreferenced. Two places need this:

- **`replace_asset`** — register the newly-written derivative names and delete them from
  an `on_commit`-failure path, or equivalently record them for cleanup.
- **The importer** — `_create_media` (`:880-892`) appends only `asset.file.name` to
  `created_files`, and `_run_import` (`:1036`) calls `_cleanup_files(created_files)` on
  *every* failure path (`TransferError`, `ValidationError`, `IntegrityError`, bare
  `Exception`, lines `1042/1045/1052/1062`). Because the importer passes `generate=False`
  it writes no derivatives, so this is closed by construction — but the invariant must be
  stated and tested, so that a later change re-enabling generation on the import path
  cannot silently reintroduce up to 2,000 orphaned files.

### Asset deletion

`courses/signals.py:_delete_mediaasset_file` currently removes `instance.file`. It gains
`delete_derivative_files([instance.thumb.name, instance.web.name], ...)`, deferred through
the same `transaction.on_commit` and guarded the same way (blank or already-missing is a
no-op). `post_delete` — rather than `Model.delete()` — remains correct for the reason
documented there: a cascade delete (removing a Course) bulk-deletes rows and never calls
`Model.delete()`.

### Transfer export / import

Derivatives are **excluded from the transfer archive**. They are fully reproducible from
the original, so shipping them would inflate every archive against
`TRANSFER_MAX_UNCOMPRESSED_BYTES` for no gain and would need a new manifest field with
its own validation and version bump. Import creates assets with `generate=False` (above),
so no importer serialization change is required — only the `created_files` invariant test.

### Backfill

A `backfill_media_derivatives` management command covers the 953 existing `mat-pp` images:

- Processes rows by `derivatives_state`: `""` and `failed` are processed; `ok` and
  `skipped` are left alone unless `--force`.
- `--dry-run` reports what it would do and writes nothing.
- `--start-at <pk>` for resuming a long run; `--course <slug>` to scope it.
- `--force` regenerates existing derivatives — needed if a target width, the encoder
  settings, or the resampling behaviour changes (in particular, the mode-normalisation
  rule above would require regenerating any palette-sourced derivative already on disk).
- Reports a running count and a final tally of generated / skipped / failed.
- A failure on one asset logs and continues — one corrupt file must not abort a 953-row
  run.

Because blank is the safe state, the command may be interrupted, re-run, or never run;
the only consequence is that un-backfilled assets keep serving originals.

## Error handling

The governing principle is **blank-is-safe**. A missing derivative is falsy, so every
render path falls back to `asset.file.url`. There is no state in which a failed or
partial derivative breaks a page.

| Condition | Behaviour |
| --- | --- |
| Pillow cannot open the file | Log; fields stay blank; `derivatives_state="failed"`; original served |
| Animated image | Dimensions recorded, derivatives skipped, state `skipped`; original served, animation intact |
| Palette (`P`) / `1` mode source | Converted to `RGB`/`RGBA` before resize, so `LANCZOS` is honoured |
| Original narrower than a target width | That derivative skipped; state `ok` if the other was written, else `skipped` |
| Derivative file missing from storage | Template falls back to the original |
| `asset is None` or blank `file.name` | Tag renders nothing (never `asset.file.url`, which raises `ValueError`) |
| `width`/`height` unknown (null) | Tag omits `srcset` and emits a plain `src` |
| Unknown preset | Raises at render time — never a silent plain-`src` degrade |
| Backfill hits a bad row | Logged, counted, run continues |
| Replace rolls back | `on_commit` never fires; old derivatives survive with the live row |
| New derivative bytes written, transaction rolls back | Names registered for cleanup; importer closes this by construction (`generate=False`) |

Generation never propagates an exception into an upload request: a valid image Pillow
happens to dislike must still upload successfully and simply serve unoptimised.

## Testing

Ordered so the client audit is verified before anything can regress.

### JS repointing (lands and is verified first)

- Playwright: with a derivative present, the media-manager hover preview loads the
  **original** URL. Assert on the overlay image's resolved `src`, not on "an overlay
  appeared" — the overlay opens either way.
- Playwright: click-to-enlarge on a student image with a `srcset` opens the **original**,
  not the 648px candidate. Assert on the dialog image's URL.
- Both are **A/B tests**: shown failing against the un-repointed JS. Measuring only the
  fixed build proves nothing.
- No test asserts a *visible* blur. `.asset-preview` is `width: min(320px, calc(100vw - 16px))`
  with padding and a border (`editor.css:1370-1394`), so the preview renders at roughly
  302 CSS px — a 320w thumb is essentially correct at DPR 1, and headless Chromium runs at
  DPR 1 by default. The URL assertion is the real check.
- Hover preview on an asset whose original is missing shows the caption-only state, via
  the overlay's `error` handler rather than the thumb's `naturalWidth`.

### `courses/derivatives.py`

- Downscales a wide image to exactly 320/648 px; output decodes as WebP; alpha preserved.
- **A mode-`P` source produces a non-`P` derivative.** This is the test that would have
  caught the silent `LANCZOS`→`NEAREST` downgrade, and it must fail if the conversion is
  removed.
- Declines for `kind="video"` (`skipped`).
- Skips derivatives for an animated GIF but records dimensions, returns `skipped`, and
  the source is still animated afterwards.
- Skips the derivative when the original is narrower than the target.
- Returns `failed` and leaves fields blank on a corrupt file, without raising.
- Applies EXIF orientation.

### Service layer

Fixture discipline: `tests/factories.py:122-129` `MediaAssetFactory` sets
`file = f"courses/media/test-{n}.png"` — a bare storage **name with no bytes on disk** —
so a derivatives test written against it would exercise the "Pillow cannot open" branch
and pass for the wrong reason. Every test below uses the real-PNG fixtures
(`tests/factories.py:151`, `tests/conftest.py:377`), and the shared-name test in
particular **requires bytes actually present in storage**.

- `create_asset` populates all five fields; `generate=False` leaves them at `""`.
- `replace_asset` regenerates **and** deletes the superseded derivative files; asserts the
  new field values actually persist (the `update_fields` trap); a rolled-back replace
  leaves the old files in place.
- `get_or_create_asset` does not regenerate on the `content_hash` dedup hit.
- `post_delete` removes both derivative files.
- Two rows sharing one `file.name` (the migration-`0008` shape) each get their own
  derivative files, and deleting one leaves the other's intact.
- The importer registers every file it writes in `created_files`: a deliberately failed
  import leaves no orphaned files of any kind.

### Template tag

- Emits `x` descriptors for fixed-box presets and `w` + `sizes` for fluid ones.
- **A test fails when `sizes` is removed from a `w`-descriptor preset** — a `srcset`
  without `sizes` is the exact silent no-op this design exists to prevent.
- Omits `srcset` when `width` is null; renders nothing for `asset=None` and for a blank
  `file.name`.
- Raises on an unknown preset.
- Emits `loading="lazy"`, `width`/`height`, and `data-zoom-src` pointing at the original.
- Falls back to the original `src` with blank derivatives.
- Every preset's CSS declares `height: auto` or an explicit `aspect-ratio` (the invariant
  above), asserted against the stylesheet.

### Backfill command

Populates a course's assets; `--dry-run` writes nothing; a second run is a no-op;
`--start-at` skips lower pks; `--force` regenerates `ok` rows; `skipped` rows are not
retried without `--force`; `failed` rows are; one corrupt asset does not abort the run.

### Rendering and layout

- Every touched template renders unchanged **layout**. Asserted on measured box geometry
  (`bounding_box()`), not on a screenshot eyeball.
- Screenshots of the media manager, the picker, and a student unit in light and dark,
  judged separately.

### Acceptance — tied to the measured symptom

The Purpose opens with hard numbers; without this section every test above could pass
with the grid still unusable. Two measured checks, each with a threshold:

1. **Candidate selection.** On the media-manager grid, the URL the browser actually
   selects (`img.currentSrc`) is the **320px thumb at DPR 1** and the **648px web
   derivative at DPR 2** — the latter pinned with `device_scale_factor=2`. This is what
   proves the derivative is reached at all; the DPR-2 case is the one that silently
   regresses under `w` descriptors.
2. **Bytes over the wire.** Total image bytes transferred for the media-manager grid's
   initial viewport, measured by intercepting responses, must be **under 2 MB** at DPR 1
   (against ~58 MB of originals available to fetch today). Recorded in the PR.

### Falsification

Every test is written to fail first. Mutants are chosen from the failure mode each test
claims to defend, not from convenience — specifically the `sizes` removal, the mode-`P`
conversion removal, and the `update_fields` truncation in `replace_asset`, each of which
produces a build that looks correct and measures wrong.
