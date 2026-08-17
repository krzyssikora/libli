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

Derivatives for all 953 images, measured by generating each width over a random 60-image
sample and projecting:

| | Bytes |
| --- | --- |
| Originals on disk today | 58.6 MB |
| `thumb` set (512px, all 953) | ~15 MB |
| `web` set (896px, all 953) | ~21 MB |
| **Added disk** | **~36 MB** |

Alternatives measured and rejected: `thumb` at 320px costs ~9 MB but does not cover a
fixed box at DPR 2 (see "Derivative widths"); `web` at 648px costs ~20 MB — only 1 MB
less than 896px, because the originals wide enough to exceed 896 are the same ones that
dominated the 648 set — while under-serving the collapsed-TOC column.

## Scope

### In scope — nine `<img>` sites across seven templates

Verified inventory (confirmed exhaustive by grepping every `<img` under `templates/`):

| Template | Line(s) | Surface | Preset |
| --- | --- | --- | --- |
| `templates/courses/manage/media/_asset_cell.html` | 7 | Media manager grid | `grid` |
| `templates/courses/manage/media/_picker_grid.html` | 6 | Editor's image picker grid | `grid` |
| `templates/courses/elements/imageelement.html` | 2 | Student image element | `el-{size}` |
| `templates/courses/elements/_table_cell.html` | 1 | Student table cell | `cell-{size}` |
| `templates/courses/elements/_filltable_cell.html` | 1 | Student fill-table cell | `cell-{size}` |
| `templates/courses/elements/dragtoimagequestionelement.html` | 9 (interactive `{% if element %}` branch) | Student drag-to-image | `dragimage` |
| `templates/courses/elements/dragtoimagequestionelement.html` | 32 (`{% else %}` fallback branch) | Student drag-to-image | `dragimage` |
| `templates/courses/elements/galleryelement.html` | 14 | Student gallery | `gallery` |

The **picker grid** is not a secondary surface: it renders the same
`assets_with_usage(course)` result set through the same `.asset-grid` / `.asset-thumb`
CSS (`editor.css:349,360`), so it exhibits the reported symptom identically, and every
author opens it whenever they insert an image.

The **gallery** needs a Python change as well as a template change.
`galleryelement.html:14` reads `{{ f.url }}`, and `GalleryElement.render()`
(`courses/models.py:1649-1651`) builds `figures.append({"url": img["media"].file.url, ...})`
— the `MediaAsset` is discarded before the template sees it. `render()` emits
**`{"asset": img["media"], "alt": ..., "desc": ...}`**, dropping `url` entirely (verified:
`figures` has no consumer outside this template). The template's docblock (lines 1–7)
documents the shape as `{url, alt, desc}` and **must be updated** with it.

Each of the seven templates needs its own `{% load courses_media_extras %}`. Django does
**not** inherit `{% load %}` across `{% include %}`, and today `imageelement.html`,
`galleryelement.html` and `_table_cell.html` load nothing at all, while
`_filltable_cell.html` and `_picker_grid.html` load only `i18n`. A missed load is a
`TemplateSyntaxError` at render.

### Out of scope — stated, with reasons

- **Editor preview twins**: `_edit_table.html:93,100`, `_edit_filltable.html:114,121`,
  `_edit_gallery.html:30`. Deferred **deliberately**, because four JavaScript modules
  rebuild that markup client-side from the picker's `data-url` — `table_editor.js:302-305`,
  `filltable_editor.js:475-483`, `gallery_editor.js:115`, `zone-editor.js:74-75`.
  Changing the server-rendered half without the JS half is exactly the editor twin-drift
  this repo has been bitten by before. Leaving **both** halves untouched keeps them
  consistent. Recorded as a follow-up.
- **Video poster frames** — would add ffmpeg as a system dependency for 232 videos.
- **Grid pagination** — see "Server cost" below, which quantifies what this change does to
  the 2.2 s TTFB so the deferral is made on real numbers.

## Architecture

### Storage model

Five new fields on `MediaAsset`, all optional:

| Field | Type | Meaning |
| --- | --- | --- |
| `width` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel width of the original |
| `height` | `PositiveIntegerField(null=True, blank=True)` | Intrinsic pixel height of the original |
| `thumb` | `FileField(upload_to="courses/media/derivatives/", max_length=200, blank=True)` | 512px-wide derivative |
| `web` | `FileField(upload_to="courses/media/derivatives/", max_length=200, blank=True)` | 896px-wide derivative |
| `derivatives_state` | `CharField(max_length=10, choices=DerivativesState.choices, blank=True, default="")` | `""` pending, `ok`, `skipped`, `failed` |

`file` stays a `FileField`, deliberately **not** promoted to `ImageField` with
`width_field`/`height_field`: the same column carries the 232 video assets, which
`ImageField` validation would reject.

**`max_length=200`, not Django's default 100.** `MediaAsset.file` uses the default and its
stored names already sit close to it; `courses/media/derivatives/` is 12 characters longer
than `courses/media/`, plus a `-896.webp` suffix and any storage collision suffix. At 100,
`get_available_name` would silently truncate stems for the long-named assets the LAL import
produced — raising collision pressure — and can raise `SuspiciousFileOperation` outright.

`derivatives_state` is a **`TextChoices` class** (`DerivativesState`), not bare string
literals, and the backfill filters against it. It exists because the other four fields
cannot express the difference between *declined*, *interrupted*, and *failed*: `width`
populated with both derivatives blank is the stored shape of all three.

- `""` — never attempted. Backfill processes it.
- `ok` — derivatives generated (one or both).
- `skipped` — deliberately declined: not an image, animated, or narrower than both targets.
  Backfill leaves it alone unless `--force`.
- `failed` — generation raised. Backfill retries it.

**Both derivative fields share one storage backend** (same `upload_to`, default storage),
which is why `delete_derivative_files` below takes a single `storage`.

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

**Required measurement.** Implementation must measure and record in the plan, **at two
named viewports — the e2e default (1280x720) and one wide case (1920x1080)** — since every
box below scales with window width:

1. `.el--image--full`'s rendered width with the TOC expanded,
2. the same with `html.unit-tree-collapsed`,
3. the same in the editor preview,
4. `.asset-thumb`'s rendered width in the manager grid,
5. the same in the picker grid,
6. `.cell-img--full`'s rendered width in a 2-, 3- and 4-column table.

The raise condition is "exceeds at either named viewport".

**`.asset-grid` is analytically bounded below 256px.** It is
`repeat(auto-fill, minmax(8rem, 1fr))` (`editor.css:349`) with no container `max-width`.
With `auto-fill`, the track count is `floor(container / 128)`, so a track is
`container / n < 128(n+1)/n`, maximised at `n = 1` → **under 256 CSS px**. Measurements
(4) and (5) confirm the real value rather than discover the bound.

**Widths:**

- **`thumb` = 512px.** A fixed box under 256 CSS px needs at most 512 device px at DPR 2,
  so one thumb covers every fixed-box preset at DPR ≤ 2 — the grid, the picker, and the
  240px table cell (480 ≤ 512). This is why 320px was rejected: it covers DPR 1 but leaves
  the grid 1.25x soft at DPR 2 on exactly the retina hardware the complaint came from, and
  forcing a second candidate there would make the grid fetch the 896px `web` derivative
  into a ~180px box — a 5x linear oversample, ~950 times.
- **`web` = 896px.** Chosen to cover the widest measured box rather than the narrowest. A
  `web` of 648px would under-declare by up to 35% in the collapsed-TOC state and the
  browser would upscale into a wider box — a visible-blur regression on the primary
  student surface, in a state the user can toggle globally.

Both widths live as **module-level constants in `courses/derivatives.py`**
(`THUMB_WIDTH`, `WEB_WIDTH`), imported by the template tag. They appear in the generator,
the filenames, and the `w` descriptors, so a future change must not be able to drift the
tag away from the bytes on disk.

Both derivatives are **lossless WebP**, saved with pinned encoder kwargs:
`format="WEBP", lossless=True, method=4, exact=True`. `method` (0–6) swings lossless
encode time several-fold and matters because generation runs synchronously inside an
upload request and in a management-command loop over 953 images; `exact=True` preserves
RGB values under fully-transparent pixels. The content is maths diagrams — thin strokes,
small labels, subscripts — where lossy ringing is precisely the artifact that would hurt
legibility.

**A derivative that is not smaller than its source is discarded** (field left blank).
25 of the 953 images are JPEG/GIF/WebP, and a lossless-WebP derivative of a photographic
JPEG can exceed the JPEG original's bytes.

**The skip rule is width-only, and that is justified by measurement.** Decode cost is
width x height, so a tall narrow image escapes a width-only predicate. Measured in
`mat-pp`: only **7 of 953** images are at most 512px wide yet exceed 250k px (the largest
508x1486), and images at most 512px wide hold **0.8% of total pixels**. A height- or
area-aware predicate would complicate the derivative's dimensions for under one percent of
the decode budget, so the width-only rule stands and this measurement is the reason.

### Generation module: `courses/derivatives.py`

```
generate_derivatives(asset) -> str       # assigns asset.derivatives_state AND returns it
delete_derivative_files(names, storage)  # names: iterable of storage names, may be blank
```

`generate_derivatives` **assigns `asset.derivatives_state` on the instance** in addition to
returning it. Callers list that field in `update_fields`, so a version that only returned
the value would persist the stale one while the correct one was discarded as an unused
return — precisely the class of silent bug the `update_fields` trap below exists to prevent.

`delete_derivative_files` takes **names, not an asset**, because its callers all need to
delete files that are no longer the asset's: `replace_asset` and backfill `--force` delete
*superseded* names captured before regeneration, and `post_delete` runs when the row is
already gone. It does not touch model fields.

`generate_derivatives` is **best-effort and never raises**. Rules, in order:

0. **Reset first.** Clear `thumb`/`web` field values (the *fields*, not the files — the
   caller owns file deletion), null `width`/`height`, and reset `derivatives_state`, before
   any branch can return. Without this, every early-return path leaves the **previous**
   image's values in place: on a replace where the new original is 500px wide, step 6 skips
   `web`, and `asset.web` would still point at the old picture's `-896.webp` — the tag would
   emit the previous image as a candidate for the new asset. The same applies to stale
   `width`/`height` (wrong attributes → distorted box) and to the non-image, animated and
   failed paths.
1. `asset.kind != "image"` → return `skipped`.
2. Open with Pillow; apply `ImageOps.exif_transpose`.
3. Record `width`/`height` from the transposed image.
4. `getattr(img, "is_animated", False)` → record dimensions, generate no derivatives,
   return `skipped`. Downscaling an animated GIF flattens it to one frame; the 18 animated
   images in `mat-pp` must keep animating. The check is on the animation flag, not the
   extension, so a single-frame GIF still gets derivatives.
5. **Normalise the mode before resizing.** Convert to `RGBA` when the source has alpha
   (`mode in ("RGBA", "LA", "PA")` or `"transparency" in img.info`), otherwise `RGB`.
   Load-bearing and non-obvious: `Image.resize` downgrades `resample` to `NEAREST` for
   modes `"1"` and `"P"`, silently ignoring `LANCZOS`. Verified against the project's
   Pillow 12.2.0 — `Image.new("P",(1000,800)).resize((320,256), Image.LANCZOS)` returns
   mode `P`, nearest-neighbour aliased, i.e. *worse* than the browser's own downscale.
   Measured prevalence is low — 19 of 953 are mode `P`, and 18 of those are animated and
   excluded at step 4, leaving one — so this is a correctness fix against future PNG-8
   uploads and the spec's own single-frame-GIF case, not a fix for a widespread defect.
6. For each target width, skip if `img.width <= target`.
7. Resample with `Image.LANCZOS`, save with the pinned encoder kwargs; discard the result
   if it is not smaller than the source file.
8. Return `ok` if anything was written, `skipped` if steps 6–7 declined both.
9. **The entire body — decode, resize, encode, and both storage writes — sits inside one
   guard catching broad `Exception`, logging, and returning `failed`.** Not a fixed tuple
   of Pillow exceptions: the riskiest step is `FieldFile.save(name, content, save=False)`,
   a storage write that can raise `SuspiciousFileOperation`, permission or quota errors, or
   backend-specific exceptions. A narrow catch would let a storage failure propagate out of
   an upload request.

Derivative filenames are `<original-stem>-512.webp` / `-896.webp`, written through
`FieldFile.save(name, content, save=False)` so Django's storage applies its own collision
suffix. **Each row therefore owns its derivative files outright.** Load-bearing: migration
`0008` copied storage references verbatim, so two `MediaAsset` rows can share one
`file.name` — the hazard `_delete_file_if_unshared` exists to guard. Derivatives are
generated per row and never shared, so their deletion needs no such guard and must not
borrow one.

### Render path: one template tag

Nine call sites need this logic. A single tag in
`courses/templatetags/courses_media_extras.py` owns it.

**A `simple_tag` returning `format_html(...)`, not an `inclusion_tag`.** An
`inclusion_tag` performs a full template load-and-render per invocation — ~950 nested
renders on the manager grid where there are currently zero, plausibly adding hundreds of
milliseconds to the very TTFB metric against which pagination is being deferred.

```
{% media_img asset preset="el-full" alt=el.alt css_class="cell-img cell-img--full" extra="data-zoomable" %}
```

**Argument contract:**

- `asset` — a `MediaAsset` or `None`.
- `preset` — a key from the table below; unknown raises (see below).
- `alt` — defaults to `""`; escaped normally by `format_html`.
- `css_class` — a string; escaped normally.
- `extra` — a whitespace-separated list of **boolean attribute names only**, validated
  against an allow-list (`data-asset-preview`, `data-zoomable`), which covers all four real
  uses. This is not a raw-HTML sink: `format_html` escapes interpolated arguments, so a
  valued attribute like `data-x="1"` would be escaped into visible text, and marking the
  argument safe would make the tag an injection point. Names outside the allow-list raise.
  `loading`, `width`, `height`, `src`, `srcset`, `sizes` and `data-zoom-src` are owned by
  the tag and cannot be passed through `extra`.

#### Per-site classes and attributes

Every layout invariant in this spec depends on these classes surviving, and
`media_preview.js` is armed off `[data-asset-preview]`:

| Site | `css_class` | `extra` |
| --- | --- | --- |
| `_asset_cell.html:7` | `asset-thumb` | `data-asset-preview` |
| `_picker_grid.html:6` | `asset-thumb` | *(none)* |
| `imageelement.html:2` | *(none)* | `data-zoomable` |
| `_table_cell.html:1` | `cell-img cell-img--{size}` | `data-zoomable` |
| `_filltable_cell.html:1` | `filltable__img cell-img cell-img--{size}` | `data-zoomable` |
| `dragtoimagequestionelement.html:9,32` | `dragimage__img` | *(none)* |
| `galleryelement.html:14` | *(none)* | `data-zoomable` |

#### Presets composed from data

Five sites derive the preset at render time. The exact expressions:

- `imageelement.html` — `{% media_img el.media preset="el-"|add:el.size ... %}`.
  `ImageElement.size` is a `TextChoices` field, always populated.
- `_table_cell.html` and `_filltable_cell.html` —
  `{% media_img cell.media preset="cell-"|add:cell.size ... %}`.

**The existing `|default:'full'` is dropped, not relocated.** `TableElement._cell`
(`models.py:1148-1152`) documents that `size` is *always* written ("unlike kind/header/spans,
which are present-only-when-set, so every reader of normalized cells may subscript
cell['size']"), and `FillTableElement._cell` (`:1343-1353`) mirrors it — so the default is
vestigial. It must not be naively carried across: `"cell-"|add:cell.size|default:"full"`
applies `default` to the already-concatenated string, which is non-empty (`"cell-"`) and so
never fires, producing an unknown preset that **raises on a student lesson page**.

**An unknown preset raises at render time** — degrading silently to a plain `src` would be
the exact silent no-op this design exists to prevent. That raise is unreachable from stored
data, and a test pins it: **for every `v` in `ImageElement.Size.values`, `f"el-{v}"` is a
preset key; for every `v` in `TableElement.CellImageSize.values`, `f"cell-{v}"` is a preset
key.** (Stated this way deliberately — the preset keys are prefixed, so the raw key set is
*not* literally a superset of `{"small","medium","large","full"}`, and a test written from
that looser wording would fail and then be weakened.)

#### `src`, and two descriptor strategies

**`src` is always emitted, and its value depends on the strategy:**

- **Fixed-box presets:** `src` = **`thumb`**, falling back to the original when `thumb` is
  blank. No `srcset` at all. One 512px thumb covers every fixed box at DPR ≤ 2, so there is
  no second candidate to offer, and this guarantees the derivative is what actually loads.
- **Fluid presets:** `src` = **the original** — a pure fallback. When `srcset` uses `w`
  descriptors the browser ignores `src` for selection entirely, so this only serves a client
  that does not understand `srcset`, which should get full quality.

| Preset | CSS box | Strategy |
| --- | --- | --- |
| `grid` | `.asset-thumb` (analytically < 256px) | `src` = thumb, no `srcset` |
| `cell-small` | `.cell-img--small` (80px both axes) | `src` = thumb, no `srcset` |
| `cell-medium` | `.cell-img--medium` (160px both axes) | `src` = thumb, no `srcset` |
| `cell-large` | `.cell-img--large` (240px both axes) | `src` = thumb, no `srcset` |
| `cell-full` | `.cell-img--full` (100% of its `<td>`, `max-height: 60dvh`) | `w` + `sizes` — see below |
| `el-small` | `.el--image--small` (25%, `max-height: 30dvh`) | `w` + `sizes="(max-width: 640px) 25vw, 224px"` |
| `el-medium` | `.el--image--medium` (50%, `max-height: 45dvh`) | `w` + `sizes="(max-width: 640px) 50vw, 448px"` |
| `el-large` | `.el--image--large` (75%, `max-height: 60dvh`) | `w` + `sizes="(max-width: 640px) 75vw, 672px"` |
| `el-full` | `.el--image--full` (`max-height: 100dvh`) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |
| `gallery` | `.gallery__frame` (100%, `aspect-ratio: 4/3`, `max-height: 70vh`) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |
| `dragimage` | `.dragimage__img` (column) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |

Collapsing every fixed box to a single candidate is what removes the DPR branch from the
grid: there is no descriptor arithmetic left to get wrong, and the acceptance criterion can
assert the same thumb at both DPR 1 and DPR 2. The `el-*` pixel values are 25/50/75/100% of
the widest measured column and must be recomputed once measurement (1)–(3) is taken; the
values shown assume 896.

For `w` presets the candidate list is `thumb 512w, web 896w, original {asset.width}w`,
omitting any derivative that is blank. **`srcset` and `sizes` are omitted entirely only
when the list would be empty** — i.e. when no derivative exists at all (an animated GIF).
A single-candidate list is still emitted, because for fluid presets that candidate is the
original and `sizes` still tells the browser the box.

**640px, not 700px.** The dominant breakpoint is `max-width: 640px` (13 occurrences across
`core/css/app.css` and `courses.css:609,978,1231`), with a `min-width: 641px` complement;
`720px` governs only `editor.css:397,666` and `builder.css:2,21`. No `700px` breakpoint
exists anywhere in the project's CSS.

The preset table and the CSS are a **deliberate coupling**; the tag module carries a comment
saying so and naming the selectors.

**`cell-full` cannot be a single measured constant.** `.cell-img--full` is `max-width: 100%`
of its `<td>` in an auto-layout table, so the used width varies with column count, per-column
content and viewport. Its `sizes` is therefore **viewport-relative**:
`sizes="(max-width: 640px) 100vw, 45vw"` — 45vw approximating a mid-range column count at
the measured viewports. Measurement (6) records the real used widths at 2, 3 and 4 columns,
and the plan states the maximum over- and under-declaration accepted across them. This is a
width-axis error and is explicitly *not* covered by the height-axis acceptance below.

**Known height-axis over-fetch, accepted.** Every preset is a two-axis bounding box, but
`sizes` describes width only. The full list of height caps: `.el--image--small/medium/large/full`
at `30/45/60/100dvh` (`courses.css:90-93`), `.cell-img--small/medium/large` at 80/160/240px
in both axes (`:1326-1328`), **`.cell-img--full` at `60dvh` (`:1329`)**, and
**`.gallery__frame` at `70vh` with `object-fit: contain` (`:1640-1647`)** — the gallery is
the largest of these, since a portrait image inside a 4/3 contain-fitted frame renders far
narrower than the frame while `sizes` declares the full 896px. Accepted: the worst case is
fetching `web` instead of `thumb`, still far below the original, and a height-aware rule
cannot be expressed in `sizes`.

**Degenerate inputs.** `asset.file.url` raises `ValueError` on a blank `FileField`:

- `asset is None` → render nothing.
- `not asset.file.name` → render nothing.
- `asset.width is None` → emit a plain `src` with **no** `srcset`.

These guards are only reachable on the seven element-template sites. `_asset_cell.html:3`
and `_picker_grid.html:5` both emit `data-url="{{ asset.file.url }}"` on the wrapper
*before* the `<img>`, so a blank-file asset 500s those pages before the tag is reached.
Those two `data-url` attributes are left as they are — pre-existing behaviour, out of scope
— and the guard's tests must therefore target an element template.

### Layout invariants

**`height: auto` is not globally provided.** `core/static/core/css/reset.css:11` is
`img, picture, svg { display: block; max-width: 100%; }` — no `height: auto`. Where a
binding `max-width`/`max-height` meets `width`/`height` attributes without `height: auto`,
the image distorts.

Audit: `.el--image img` (`courses.css:46`), `.cell-img` (`:1325`) and `.dragimage__img`
(`:538`) declare `height: auto`. **`.gallery__frame img` (`:1647`) does not** — it is
`max-width: 100%; max-height: 100%; object-fit: contain`, sized by its frame's
`aspect-ratio: 4/3`.

**No CSS is changed to satisfy this.** Adding `height: auto` to the gallery rule would be an
unmeasured layout change, which the Goal forbids. The invariant is therefore stated to
match reality, and the test encodes all three cases: *every preset's CSS declares
`height: auto`, an explicit `aspect-ratio`, **or** an ancestor `aspect-ratio` together with
`object-fit`.*

**The reflow benefit does not apply to the grid.** `.asset-thumb` already declares
`width: 100%; aspect-ratio: 4 / 3; object-fit: cover` (`editor.css:360-365`), so its box is
fully determined before any image loads and the CSS `aspect-ratio` overrides the
attribute-derived ratio. The grid does not reflow today. The `width`/`height` benefit is
real only on `.el--image`, `.cell-img*` and `.dragimage__img`, and is claimed only there.

### Lazy loading — grid and picker only

The derivative bounds cost **per image**; `loading="lazy"` bounds **how many** decode.
~950 thumbs at 512px is ~750 MB of bitmap if all decode at once; with lazy loading only the
~24 on screen decode, about 19 MB.

**`loading="lazy"` is emitted on the `grid` preset only.** The student element templates do
**not** get it, for two reasons: a unit page carries tens of images rather than ~950, so the
derivative alone is sufficient there; and `courses.css:103-108` and `:1349-1351` are
hand-tuned `@media print` blocks capping images at 45/75/110/170 mm, so a printed lesson is
an intended surface — and a printed document is by definition below the fold. Rather than
depend on per-browser force-load-before-print behaviour, the risk is removed by not
deferring those images at all. The grid and picker are never printed.

### Print

A browser prints whichever candidate is already loaded, so a `full` image printed at 170 mm
comes from the `web` derivative rather than the original. **Accepted, with the reason
stated:** `sizes` accepts a `<media-condition>`, which does not admit media *types*, so
`sizes="print 170mm, …"` is not valid and there is no `sizes`-level fix. At 896px across
170 mm the effective density is ~134 dpi, above the ~96 dpi a browser assumes for
CSS-px-to-physical mapping, so the printed result is not upscaled relative to the layout.

### Server cost

Two before/after measurements are required, because this change pushes on the metric
against which pagination is being deferred:

- **HTML size** of `/manage/courses/mat-pp/media/`, currently 2.1 MB.
- **Server render time** of the same URL, currently 2.2 s.

Both recorded in the PR.

### Client-side audit — the silent regressions

Two JavaScript modules independently reconstruct a "big image" from the rendered element's
*effective* source:

- `media_preview.js:171` — `var src = anchor.currentSrc || anchor.getAttribute("src")`
- `imagezoom.js:74` — `dialogImg.src = img.currentSrc || img.src`

Point the grid at a thumb and the hover preview loads the thumb. Add a `srcset` to student
images and `currentSrc` resolves to the `web` derivative, so **click-to-enlarge stops
enlarging**. Neither fails loudly.

Both must read an **explicit full-resolution URL**:

- `media_preview.js` reads `data-url` from the closest `.asset-cell`
  (`_asset_cell.html:3` already carries it).
- `imagezoom.js` reads a new `data-zoom-src` emitted by the tag, falling back to
  `currentSrc || src` when absent so non-tag `<img data-zoomable>` markup keeps working.

Three second-order consequences, handled in the same commit:

- `media_preview.js:172` guards with `anchor.complete && anchor.naturalWidth === 0` →
  caption-only. After the repoint that guard interrogates the *thumb* while a different URL
  is loading, so a broken original would yield a silently empty overlay. The guard moves to
  the overlay image's own `error` handler, which already exists (`:54-58`).
- **The hover preview becomes a real fetch.** Today the overlay copies the grid `<img>`'s
  already-loaded original and paints instantly; after the repoint it fetches an uncached
  original on every hover. Verified in `open()`: `overlayImg.hidden = true` until `load`,
  so it degrades to caption-first-then-image rather than breaking. **Accepted and stated**
  — that is the existing cold-open path, not a new state — and a test pins caption-first.
- `imagezoom.js:74` carries the comment `// already fetched: served from cache`,
  load-bearing documentation of why there is no loading state. Pointing at `data-zoom-src`
  makes it a genuine network fetch. The comment must be corrected and the dialog given a
  loading state (the `load`/`error` handlers already exist).

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
`TRANSFER_MAX_MEDIA_ENTRIES = 1000` entries (`config/settings/base.py:179`) inside
`transaction.atomic()` (`_run_import`, `:1036`). At tens of milliseconds per image that is
20–60 s of CPU added to one HTTP request holding an open write transaction — a plausible
worker timeout and a real lock-contention risk. So `create_asset` gains a `generate=True`
keyword, the importer passes `generate=False`, imported assets land with
`derivatives_state=""` and serve originals (blank-is-safe makes that correct rather than
broken), and the import completion message tells the user to run
`backfill_media_derivatives --course <slug>`.

**Implementation per site:**

- **`create_asset`** — after `asset.save()`, when `generate` is true call
  `generate_derivatives(asset)` and persist with
  `update_fields=["width","height","thumb","web","derivatives_state"]`.
- **`get_or_create_asset`** — this path **does not call `create_asset`**; it constructs
  `MediaAsset(...)` directly (`courses/lal_loader/media.py:42-46`), so the `generate`
  keyword never reaches it. Call `generate_derivatives(asset)` *before* the existing
  `asset.save()` — that save is a full save with no `update_fields`, so it persists the new
  fields without further change. Only this newly-created branch generates; the
  `content_hash` dedup early-return at `:39-41` must **not** regenerate.

  It is reached only from the `import_lal_content` management command, never from a
  request, so there is no worker timeout to trip and no user awaiting a response;
  `courses/lal_loader/` opens no `transaction.atomic` around the loop, so no write
  transaction is held open. Generating inline there is safe and saves a backfill pass.

### `replace_asset` — the exact sequence

The existing function (`courses/media.py:150-184`) ends with
`asset.save(update_fields=["file", "original_filename", "content_hash"])`. Generating
derivatives *after* that save without extending `update_fields` would silently drop the
five new fields. Generating them *before* it would read `asset.file` while it is still an
uncommitted `UploadedFile`: Pillow advances the stream, and Django then writes to storage
from the current position, truncating the stored original. (`_validate_file`'s
`getattr(file, "_committed", False)` short-circuit, `courses/validators.py:83-95`, is
sensitive to when the file is touched for the same reason.)

Required order:

1. Capture `old_thumb_name`, `old_web_name` and the shared storage, **before** reassigning.
2. Assign the new file; `full_clean(...)` as today.
3. `asset.save(update_fields=["file", "original_filename", "content_hash"])` — the original
   is now committed to storage.
4. `generate_derivatives(asset)` — reads the **committed** `FieldFile`, so no stream
   position is shared with a pending write. Any read must `seek(0)` regardless.
5. `asset.save(update_fields=["width","height","thumb","web","derivatives_state"])`.
6. `transaction.on_commit(...)` deleting each captured old derivative name **only if it
   differs from the newly written one** — `if asset.thumb.name != old_thumb_name`, likewise
   for `web`. This mirrors the guard already applied to the original at
   `courses/media.py:180-183` ("Storage hands back the SAME name when the old file was
   already missing, in which case the 'old' file is the one just written"). Without the
   comparison, a replace whose old derivative was absent from storage would delete the file
   step 4 just wrote, leaving a non-blank field pointing at nothing. Plus the existing
   `_delete_file_if_unshared` call for the old original.

### Orphaned bytes on rollback

`generate_derivatives` writes to storage *inside* the atomic block, so a rollback discards
the field values but leaves the bytes on disk, unreferenced.

**Django 5.2 provides `transaction.on_commit` but no `on_rollback`** — and because
`replace_asset` is decorated `@transaction.atomic`, the rollback happens at the decorator
boundary, after control has already left the function body, so there would be nowhere for
such a callback to run even if one existed. Do not go looking for that API.

The mechanism is therefore explicit: **wrap the body of `replace_asset` in `try/except`,
delete the newly-written derivative names in the handler, and re-raise.**

For **the importer**, `_create_media` (`:880-892`) appends only `asset.file.name` to
`created_files`, and `_run_import` (`:1036`) calls `_cleanup_files(created_files)` on every
failure path (lines `1042/1045/1052/1062`). Because the importer passes `generate=False` it
writes no derivatives, so this is closed by construction — but the invariant is stated and
tested, so a later change re-enabling generation there cannot silently reintroduce up to
2,000 orphaned files.

### Asset deletion

`courses/signals.py:_delete_mediaasset_file` currently removes `instance.file`. It gains
`delete_derivative_files([instance.thumb.name, instance.web.name], storage)`, deferred
through the same `transaction.on_commit` and guarded the same way (blank or already-missing
is a no-op). `post_delete` — rather than `Model.delete()` — remains correct: a cascade
delete (removing a Course) bulk-deletes rows and never calls `Model.delete()`.

### Transfer export / import

Derivatives are **excluded from the transfer archive**. They are reproducible from the
original, so shipping them would inflate every archive against
`TRANSFER_MAX_UNCOMPRESSED_BYTES` for no gain and would need a new manifest field with its
own validation and version bump. Import creates assets with `generate=False`, so no
serialization change is required — only the `created_files` invariant test.

### Backfill

`backfill_media_derivatives`:

- Processes rows by `derivatives_state`, filtering against `DerivativesState`: `""` and
  `failed` are processed; `ok` and `skipped` are left alone unless `--force`.
- `--dry-run` reports what it would do and writes nothing.
- `--start-at <pk>` for resuming; `--course <slug>` to scope it.
- `--force` regenerates existing derivatives — needed if a target width, the encoder
  kwargs, or the resampling behaviour changes (the mode-normalisation rule in particular
  requires regenerating any palette-sourced derivative already on disk).
- **`--force` must capture the old `thumb`/`web` names and call `delete_derivative_files`
  with the same `!=` guard as `replace_asset` step 6.** Because derivatives are written via
  `FieldFile.save(...)`, storage hands back a collision-suffixed name
  (`x-512_AbC.webp`), the field repoints, and the previous file would be orphaned — with
  repeated `--force` runs multiplying orphans and lengthening names against the
  `max_length=200` budget.
- Reports a running count and a final tally of generated / skipped / failed.
- A failure on one asset logs and continues.

Because blank is the safe state, the command may be interrupted, re-run, or never run.

## Error handling

The governing principle is **blank-is-safe**. A blank derivative *field* is falsy, so every
render path falls back to the original.

**The one honest limit:** a non-blank field pointing at absent bytes yields a broken image,
not a fallback. The tag's only signal is field truthiness, which reflects the database, not
the filesystem; detecting absent bytes would need a `storage.exists()` per derivative —
~1900 stat calls on the manager grid. Browsers do not retry another `srcset` candidate on a
404. What prevents that state is the `!=` guard, applied in both `replace_asset` step 6 and
backfill `--force` — the only code paths that could delete a live row's current derivative.

| Condition | Behaviour |
| --- | --- |
| Pillow or storage raises anywhere in generation | Log; fields **cleared** by rule 0; state `failed`; original served |
| Not an image / animated | Fields cleared, dimensions recorded where known, state `skipped`; original served, animation intact |
| Palette (`P`) / `1` mode source | Converted to `RGB`/`RGBA` before resize, so `LANCZOS` is honoured |
| Original narrower than a target width | That derivative skipped |
| Derivative encodes no smaller than the source | Discarded; field left blank |
| `asset is None` or blank `file.name` | Tag renders nothing (never `asset.file.url`, which raises `ValueError`) |
| `width`/`height` unknown (null) | Tag omits `srcset` and emits a plain `src` |
| Zero `srcset` candidates | `srcset` and `sizes` omitted entirely |
| Unknown preset | Raises at render time; unreachable from stored data by the per-value rule |
| Backfill hits a bad row | Logged, counted, run continues |
| Replace raises | `try/except` deletes newly-written derivatives and re-raises; old files survive |

Generation never propagates an exception into an upload request.

## Testing

Ordered so the client audit is verified before anything can regress.

### JS repointing (lands and is verified first)

- Playwright: with a derivative present, the media-manager hover preview loads the
  **original** URL. Assert on the overlay image's resolved `src` — the overlay opens either
  way.
- Playwright: click-to-enlarge on a student image with a `srcset` opens the **original**,
  not the `web` candidate.
- Both are **A/B tests**: shown failing against the un-repointed JS.
- No test asserts a *visible* blur. `.asset-preview` is
  `width: min(320px, calc(100vw - 16px))` with padding and a border
  (`editor.css:1370-1394`), so the preview renders at roughly 302 CSS px and headless
  Chromium runs at DPR 1. The URL assertion is the real check.
- Hover preview on an asset whose original is missing shows caption-only, via the overlay's
  `error` handler rather than the thumb's `naturalWidth`.
- Hover preview paints the caption before the image arrives (the accepted cold-fetch
  behaviour).

### `courses/derivatives.py`

Fixture discipline: `make_image_asset(course, filename="x.png", size=(1, 1), ...)`
(`tests/factories.py:150`) defaults to a **1x1** PNG, which is narrower than both targets,
so generation returns `skipped` with blank fields — indistinguishable from
`failed`-with-blank-fields. A test asserting only "no crash" would pass on a completely
broken generator. **Every derivative test passes an explicit `size=` wider than 896px**,
except one deliberate narrow case asserting `skipped` *specifically*. `MediaAssetFactory`
(`tests/factories.py:122-129`) sets a bare storage name with **no bytes on disk** and is
unusable for these tests.

- Downscales to exactly 512/896 px; output decodes as WebP; alpha preserved.
- **A mode-`P` source produces a non-`P` derivative** — catches the silent
  `LANCZOS`→`NEAREST` downgrade; must fail if the conversion is removed.
- **Rule 0 clears stale fields**: an asset with existing `thumb`/`web`/`width` regenerated
  from a *narrower* source ends with `web` blank, not pointing at the old file.
- Declines for `kind="video"` (`skipped`).
- Animated GIF: dimensions recorded, `skipped`, source still animated afterwards.
- Skips the derivative when the original is narrower than the target.
- Discards a derivative that encodes no smaller than its source.
- Returns `failed` without raising on a corrupt file **and** on a storage write failure
  (forced by patching the storage backend).
- Applies EXIF orientation.
- Assigns `asset.derivatives_state` on the instance, not only as a return value.

### Service layer

- `create_asset` populates all five fields; `generate=False` leaves them at `""`.
- `replace_asset` regenerates **and** deletes superseded derivative files; asserts the new
  field values persist (the `update_fields` trap); asserts that when the old derivative name
  is reused the file is **not** deleted (the `!=` guard); a raising replace deletes the
  newly-written derivatives and leaves the old files in place.
- `get_or_create_asset` generates on the create branch and **not** on the `content_hash`
  dedup hit.
- `post_delete` removes both derivative files.
- Two rows sharing one `file.name` (the migration-`0008` shape, **with real bytes in
  storage**) each get their own derivative files; deleting one leaves the other's intact.
- A deliberately failed import leaves no orphaned files of any kind.

### Template tag

- `src` = thumb for fixed-box presets, `src` = original for fluid presets.
- **A test fails when `sizes` is removed from a `w`-descriptor preset.**
- **A test pins what an 80px `cell-small` actually loads** (the thumb, not the original) —
  the single-candidate presets are where a broken implementation would otherwise be
  invisible.
- Omits `srcset`/`sizes` only with zero candidates; emits a single-candidate `srcset` for
  fluid presets.
- Omits `srcset` when `width` is null; renders nothing for `asset=None` and blank
  `file.name` (tested on an element template, the only place those guards are reachable).
- Raises on an unknown preset; **per-value key test** for `ImageElement.Size.values` and
  `TableElement.CellImageSize.values`.
- Emits the exact per-site class and attribute set, including `data-asset-preview` on the
  manager cell and *not* on the picker cell.
- `extra` rejects a non-allow-listed name and rejects a valued attribute.
- Emits `loading="lazy"` on `grid` **and not** on the student element presets.
- Emits `width`/`height` and `data-zoom-src` pointing at the original.
- Every preset's CSS declares `height: auto`, an explicit `aspect-ratio`, or an ancestor
  `aspect-ratio` plus `object-fit` — asserted against the stylesheet, with the gallery
  exercising the third case.

### Per-template conversion

**One rendering assertion per in-scope template** that the emitted HTML references a
derivative (or at minimum a `srcset`). Without these, a build that left
`imageelement.html`, both table cells, the gallery and both drag-to-image `<img>` tags
untouched would pass every other test: the tag unit tests pass, the geometry tests pass
trivially, and the acceptance check only touches the manager grid. A forgotten template
must be RED, not invisible.

### Backfill command

Populates a course's assets; `--dry-run` writes nothing; a second run is a no-op;
`--start-at` skips lower pks; `--force` regenerates `ok` rows **and leaves no orphaned
derivative files**; `skipped` rows are not retried without `--force`; `failed` rows are;
one corrupt asset does not abort the run.

### Rendering and layout

- Every touched template renders unchanged **layout**, asserted on measured box geometry
  (`bounding_box()`) **with a ±1 px tolerance per axis**. The tolerance is required, not
  slack: a derivative's height is a rounded proportional scale of the original's, so their
  intrinsic ratios differ slightly (1100x841 → 896x685 is 1.3080 vs 1.3079), and where a
  height cap binds the used width can shift sub-pixel.
- Screenshots of the media manager, the picker, and a student unit in light and dark,
  judged separately.

### Acceptance — tied to the measured symptom

1. **Candidate selection.** On the media-manager grid the URL the browser actually selects
   (`img.currentSrc`) is the **512px thumb at both DPR 1 and DPR 2**, the latter pinned with
   `device_scale_factor=2`. A single fixed-box candidate is precisely what makes this
   assertion identical at both densities.
2. **Bytes over the wire.** Total image bytes for the grid's initial viewport at DPR 1.
   **The threshold derives from a measured baseline, not from the 58.6 MB library total** —
   that figure is the whole library, and with lazy loading alone and no derivatives the
   initial viewport is only ~24 originals at a median 38 KB, under 1 MB. A "under 2 MB"
   threshold would pass with derivatives entirely absent, discriminating only the
   lazy-loading half. Implementation measures today's initial-viewport bytes and sets the
   threshold below it, derived from the measured mean thumb size times the measured
   on-screen count. Recorded in the PR.

### Falsification

Every test is written to fail first. Mutants are chosen from the failure mode each test
claims to defend: the `sizes` removal, the mode-`P` conversion removal, the rule-0 reset
removal, the `update_fields` truncation, and the `!=` guard removal — each of which
produces a build that looks correct and measures wrong.
