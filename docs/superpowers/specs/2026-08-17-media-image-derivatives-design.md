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

The bytes are not the problem; the **decode** is. `_asset_cell.html:7` sets the
thumbnail `src` to the full-resolution original, so the browser decompresses and
downscales 928 PNGs totalling ~3.7 GB of bitmap, exceeds its image-cache ceiling, and
begins evicting and re-decoding on scroll. There is no derivative image, no
`loading="lazy"`, and no pagination.

The same waste exists on student-facing renders — `imageelement.html:2`,
`_table_cell.html:1`, `_filltable_cell.html:1`, `dragtoimagequestionelement.html` — where
a ~1100px original is painted into a 648px content column, on worse connections than a
course author's.

**Goal:** serve appropriately-sized images everywhere, without changing a single
rendered layout, and without a window in which the site is broken or degraded.

**Out of scope:** video poster frames (would add ffmpeg as a system dependency for the
232 videos; the `▶` glyph is adequate), grid pagination (it addresses the 2.2 s TTFB, a
lesser annoyance, and is better judged after this lands).

## Architecture

### Storage model

Four new fields on `MediaAsset`, all optional:

| Field | Type | Meaning |
| --- | --- | --- |
| `width` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel width of the original |
| `height` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel height of the original |
| `thumb` | `FileField(upload_to="courses/media/derivatives/", blank=True)` | 320px-wide derivative |
| `web` | `FileField(upload_to="courses/media/derivatives/", blank=True)` | 648px-wide derivative |

`file` stays a `FileField`, deliberately **not** promoted to `ImageField` with
`width_field`/`height_field`: the same column carries the 232 video assets, which
`ImageField` validation would reject.

Widths are chosen from the CSS the images actually land in:

- **320px** covers the library grid (`.asset-grid` is `minmax(8rem, 1fr)`, so cells run
  128–200px) and the table-cell presets (`.cell-img--small/medium/large` = 80/160/240px).
- **648px** is the content column, which `.el--image--full` fills; `large`/`medium`/`small`
  are 75/50/25% of it (486/324/162px).

Both derivatives are **lossless WebP**. The content is maths diagrams — thin strokes,
small labels, subscripts — where lossy ringing is precisely the artifact that would hurt
legibility. Lossless WebP is typically 25–35% smaller than the source PNG with no
quality question to argue about.

### Generation module: `courses/derivatives.py`

A single new module owns all image processing. Its public surface is two functions:

```
generate_derivatives(asset) -> bool     # populate width/height/thumb/web on `asset`
clear_derivatives(asset)                # delete derivative FILES from storage
```

`generate_derivatives` is **best-effort and never raises**: it returns `True` when it
populated something and `False` when it declined or failed, logging the reason. Rules,
in order:

1. `asset.kind != "image"` → decline (videos have no derivatives).
2. Open with Pillow; apply `ImageOps.exif_transpose` (a JPEG with an orientation tag
   would otherwise produce a sideways derivative).
3. Record `width`/`height` from the transposed image.
4. `getattr(img, "is_animated", False)` → record dimensions only, generate **no**
   derivatives. Downscaling an animated GIF flattens it to a single frame; the 18 GIFs
   in `mat-pp` must keep animating. This check is on the animation flag, not the file
   extension, so a single-frame GIF still gets derivatives.
5. For each target width, skip if `img.width <= target` — a 300px original gets no
   320px derivative, because upscaling adds bytes and no detail. This means small
   originals legitimately end with blank `thumb`/`web`, which the render path already
   handles.
6. Resample with `Image.LANCZOS`, preserving alpha (WebP supports it), and save with
   `format="WEBP", lossless=True`.
7. Any Pillow exception (`UnidentifiedImageError`, `OSError`, `DecompressionBombError`)
   → log and return `False`, leaving fields blank.

Derivative filenames are `<original-stem>-320.webp` / `-648.webp`, written through
`FieldFile.save(name, content, save=False)` so Django's storage applies its own
collision suffix. **Each row therefore owns its derivative files outright.** This is
load-bearing: migration `0008` copied storage references verbatim, so two `MediaAsset`
rows can share one `file.name` — the hazard `_delete_file_if_unshared` exists to
guard. Derivatives are generated per row and never shared, so their deletion needs no
such guard and must not borrow one.

### Render path: one template tag

Five call sites need srcset logic. Duplicating it five times guarantees drift, so a
single inclusion tag in `courses/templatetags/courses_media_extras.py` owns it:

```
{% media_img asset preset="full" alt=el.alt zoomable=True %}
```

The tag resolves `asset` (a `MediaAsset`) plus a **preset** naming the CSS box the image
lands in, and renders one `<img>`.

`sizes` is the load-bearing half. `srcset` **without** `sizes` defaults to `100vw`, which
makes the browser select the largest candidate — the opposite of the goal. Each preset
therefore carries an explicit `sizes` matched to its CSS:

| Preset | CSS box | `sizes` |
| --- | --- | --- |
| `grid` | `.asset-thumb` (128–200px cell) | `200px` |
| `cell-small` | `.cell-img--small` (80px) | `80px` |
| `cell-medium` | `.cell-img--medium` (160px) | `160px` |
| `cell-large` | `.cell-img--large` (240px) | `240px` |
| `cell-full` | `.cell-img--full` (column) | `(max-width: 700px) 100vw, 648px` |
| `el-small` | `.el--image--small` (25%) | `(max-width: 700px) 25vw, 162px` |
| `el-medium` | `.el--image--medium` (50%) | `(max-width: 700px) 50vw, 324px` |
| `el-large` | `.el--image--large` (75%) | `(max-width: 700px) 75vw, 486px` |
| `el-full` | `.el--image--full` (column) | `(max-width: 700px) 100vw, 648px` |

The preset table and the CSS max-widths are a **deliberate coupling**; the tag module
carries a comment saying so, naming the CSS selectors, so a future change to
`.cell-img--large` has a chance of finding its `sizes` counterpart.

`srcset` candidates are emitted only for derivatives that exist, always with the original
as the largest candidate so high-DPR displays and click-to-enlarge still have full
resolution available:

```
srcset="<thumb> 320w, <web> 648w, <original> {asset.width}w"
```

The tag also emits `loading="lazy"` (except where a preset opts out) and `width`/`height`
from the stored dimensions.

### Lazy loading is not optional

The derivative bounds cost **per image**; `loading="lazy"` bounds **how many** decode.
928 thumbs at 320px is still ~285 MB of bitmap if they all decode at once. With lazy
loading only the ~24 on screen decode — about 7 MB. Both are required; either alone
leaves the reported symptom substantially in place.

`width`/`height` attributes ship alongside, so the grid stops reflowing as images land.

### Client-side audit — the silent regressions

Two JavaScript modules independently reconstruct a "big image" from the rendered
element's *effective* source:

- `courses/static/courses/js/media_preview.js:171` —
  `var src = anchor.currentSrc || anchor.getAttribute("src")`
- `courses/static/courses/js/imagezoom.js:74` —
  `dialogImg.src = img.currentSrc || img.src`

Point the grid at a 320px thumb and the hover preview becomes an upscaled blur. Add a
`srcset` to student images and `currentSrc` resolves to the 648px derivative, so
**click-to-enlarge stops enlarging** — it shows the size already on screen. Neither
fails loudly. Both would pass a "the page still looks fine" check.

Both modules must read an **explicit full-resolution URL** instead:

- `media_preview.js` reads `data-url` from the closest `.asset-cell`, which already
  carries the original's URL (`_asset_cell.html:3`).
- `imagezoom.js` reads a new `data-zoom-src` attribute emitted by the `media_img` tag,
  falling back to `currentSrc || src` when absent so non-tag `<img data-zoomable>`
  markup keeps working.

**Ordering is a requirement, not a preference:** this JS change lands and is verified
*before* any template starts emitting a derivative `src` or `srcset`. Done in that order
there is never a commit at which zoom or hover preview is degraded.

## Data flow

### Asset creation

Three construction sites exist, and all three must populate derivatives:

| Site | Caller |
| --- | --- |
| `courses/media.py:create_asset` | manager upload (`views_media.media_upload`), transfer import (`transfer/importer.py:887`) |
| `courses/media.py:replace_asset` | manager replace (`views_media.media_replace`) |
| `courses/lal_loader/media.py:get_or_create_asset` | LAL content import |

Generation is **synchronous**, inside the existing save path. The project has no task
queue (no Celery/RQ/dramatiq in `pyproject.toml`), and adding one for two ~1 MP
downscales would be disproportionate. A lossless-WebP downscale of a median `mat-pp`
image costs tens of milliseconds; an upload already pays a multipart round-trip.

- **`create_asset`** — after `asset.save()`, call `generate_derivatives(asset)` and save
  the populated fields with an explicit `update_fields`.
- **`replace_asset`** — the superseded derivatives must go. Capture the old derivative
  names *before* reassigning, regenerate from the new bytes, and delete the old files
  unconditionally (per-row ownership, per above). This runs inside the existing
  `@transaction.atomic`, with file deletion deferred via `transaction.on_commit` exactly
  as `_delete_file_if_unshared` already does, so a rolled-back replace cannot strand a
  live row whose derivative is already gone.
- **`get_or_create_asset`** — the dedup early-return path (an existing row matched by
  `content_hash`) must **not** regenerate; only the newly-created branch does.

### Asset deletion

`courses/signals.py:_delete_mediaasset_file` currently removes `instance.file`. It gains
the two derivative files, deferred through the same `transaction.on_commit` and guarded
the same way (blank or already-missing is a no-op). The `post_delete` receiver — rather
than `Model.delete()` — remains the right hook for the same reason documented there: a
cascade delete (removing a Course) bulk-deletes rows and never calls `Model.delete()`.

### Transfer export / import

Derivatives are **excluded from the transfer archive**. They are fully reproducible from
the original, so shipping them would inflate every archive against
`TRANSFER_MAX_UNCOMPRESSED_BYTES` for no gain, and would need a new archive-manifest
field with its own validation and version bump. On import, `create_asset` regenerates
them — no importer change is required beyond confirming this holds.

### Backfill

A `backfill_media_derivatives` management command covers the 953 existing `mat-pp`
images:

- Idempotent — skips rows that already have both derivatives (or that legitimately
  declined, tracked by `width` being populated with no derivative needed).
- `--dry-run` reports what it would do and writes nothing.
- `--start-at <pk>` for resuming a long run; `--course <slug>` to scope it.
- `--force` regenerates existing derivatives (needed only if a width changes).
- Reports a running count and a final tally of generated / skipped / failed.
- A failure on one asset logs and continues — one corrupt file must not abort a
  953-row run.

Because blank is the safe state, the command may be interrupted, re-run, or never run at
all; the only consequence is that un-backfilled assets keep serving originals.

## Error handling

The governing principle is **blank-is-safe**. A missing derivative is falsy, so every
render path falls back to `asset.file.url`. There is no state in which a failed or
partial derivative breaks a page.

| Condition | Behaviour |
| --- | --- |
| Pillow cannot open the file | Log; `thumb`/`web`/`width`/`height` stay blank; original served |
| Animated GIF | Dimensions recorded, derivatives skipped; original served, animation intact |
| Original narrower than a target width | That derivative skipped; original served |
| Derivative file missing from storage | Template falls back to the original |
| `width`/`height` unknown (null) | Tag omits `srcset` entirely and emits a plain `src` — a `w` descriptor without a real pixel width would be a lie the browser acts on |
| Backfill hits a bad row | Logged, counted, run continues |
| Replace rolls back | `on_commit` never fires; old derivatives survive with the live row |

Generation never propagates an exception into an upload request: a valid image that
Pillow happens to dislike must still upload successfully and simply serve unoptimised.

## Testing

Ordered so the client audit is verified before anything can regress.

### JS repointing (lands first)

- Playwright: with a derivative present, hover preview in the media manager loads the
  **original** URL, not the thumb. Asserted on the overlay img's resolved `src`, not on
  "an overlay appeared".
- Playwright: click-to-enlarge on a student image with a `srcset` opens the **original**,
  not the 648px candidate.
- Both are **A/B tests**: they must be shown failing against the un-repointed JS.
  Measuring only the fixed build proves nothing, and a final-state assertion here would
  pass on a broken build because the overlay opens either way — the assertion must be on
  the URL.

### `courses/derivatives.py`

- Downscales a wide image to exactly 320/648 px, output decodes as WebP, alpha preserved.
- Declines for `kind="video"`.
- Skips derivatives for an animated GIF but still records dimensions; asserts the source
  is still animated afterwards.
- Skips the derivative when the original is narrower than the target.
- Returns `False` and leaves fields blank on a corrupt file, without raising.
- Applies EXIF orientation.

### Service layer

- `create_asset` populates all four fields.
- `replace_asset` regenerates derivatives **and** deletes the superseded files; a
  rolled-back replace leaves the originals in place.
- `get_or_create_asset` does not regenerate on the `content_hash` dedup hit.
- `post_delete` removes both derivative files.
- Two rows sharing one `file.name` (the migration-`0008` shape) each get their own
  derivative files, and deleting one leaves the other's intact.

### Template tag

- Emits `srcset` + `sizes` per preset; omits `srcset` when `width` is null.
- Emits `loading="lazy"` and `width`/`height`.
- Emits `data-zoom-src` pointing at the original.
- Falls back to the original `src` with blank derivatives.

### Backfill command

- Populates a course's assets; `--dry-run` writes nothing; a second run is a no-op;
  `--start-at` skips lower pks; one corrupt asset does not abort the run.

### Rendering

- Every touched template renders unchanged **layout** — the visual result is identical;
  only the bytes differ.
- Screenshots of the media manager and a student unit in light and dark, judged
  separately.

### Falsification

Every test above is written to fail first. Mutants are chosen from the failure mode each
test claims to defend, not from convenience — in particular, the `sizes` attribute must
have a test that fails when `sizes` is removed, since a `srcset` without `sizes` is the
exact silent-no-op this design is built to avoid.
