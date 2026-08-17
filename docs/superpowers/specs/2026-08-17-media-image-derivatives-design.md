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

Projected over all 953 images from a random 60-image sample, net of the animated and
narrower-than-target skips:

| | Bytes |
| --- | --- |
| Originals on disk today | 58.6 MB |
| `thumb` set (512px) | ~15 MB |
| `web` set (896px) | ~21 MB |
| **Added disk** | **~36 MB** |

Alternatives measured and rejected: `thumb` at 320px costs ~9 MB but does not cover a
fixed box at DPR 2 (see "Derivative widths"); `web` at 648px costs ~20 MB — only 1 MB
less than 896px, because the originals wide enough to exceed 896 are the same ones that
dominated the 648 set — while under-serving the collapsed-TOC column.

## Scope

### In scope — eight `<img>` sites across seven templates

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

Eight tags, seven templates — drag-to-image contributes two.

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
**not** inherit `{% load %}` across `{% include %}`. Current state of all seven:

| Template | Today | Change |
| --- | --- | --- |
| `imageelement.html` | *(no load tag)* | new line |
| `galleryelement.html` | *(no load tag)* | new line |
| `_table_cell.html` | *(no load tag)* | **inline** on line 1 |
| `_filltable_cell.html` | `{% load i18n %}` | **inline**, append to line 1 |
| `_picker_grid.html` | `{% load i18n %}` | append |
| `_asset_cell.html` | `{% load i18n courses_manage_extras %}` | append |
| `dragtoimagequestionelement.html` | `{% load i18n l10n courses_extras %}` | append |

**`_table_cell.html` and `_filltable_cell.html` are deliberately newline-free** — each is a
single line with no trailing newline, and `_filltable_cell.html` already writes
`{% load i18n %}{% if … %}` with no separator, so the repo treats their output whitespace as
load-bearing (they render into table cells). The load tag goes **inline on the existing
first line** for those two, never on a line of its own.

### Out of scope — stated, with reasons

- **Editor preview twins**: `_edit_table.html:93,100`, `_edit_filltable.html:114,121`,
  `_edit_gallery.html:30,44` (`:44` is the empty-`src` template row `gallery_editor.js:115`
  clones). Deferred **deliberately**, because four JavaScript modules rebuild that markup
  client-side from the picker's `data-url` — `table_editor.js:302-305`,
  `filltable_editor.js:475-483`, `gallery_editor.js:115`, `zone-editor.js:74-75`.
  Changing the server-rendered half without the JS half is exactly the editor twin-drift
  this repo has been bitten by before. Leaving **both** halves untouched keeps them
  consistent. Recorded as a follow-up.
- **Video poster frames** — would add ffmpeg as a system dependency for 232 videos.
- **Grid pagination** — see "Server cost" below.

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
produced, and can raise `SuspiciousFileOperation`.

`derivatives_state` is a **`TextChoices` class** (`DerivativesState`), and the backfill
filters against it. It exists because the other four fields cannot express the difference
between *declined*, *interrupted*, and *failed*: `width` populated with both derivatives
blank is the stored shape of all three.

- `""` — never attempted. Backfill processes it.
- `ok` — derivatives generated (one or both).
- `skipped` — deliberately declined: not an image, animated, or narrower than both targets.
- `failed` — generation raised. Backfill retries it.

**Both derivative fields share one storage backend** (same `upload_to`, default storage),
which is why `delete_derivative_files` takes a single `storage`.

**Migration `0059`** — schema-only, five `AddField` operations, no data migration, fully
reversible.

### Derivative widths

**The content column is not a single number.** `.el--image` is deliberately **absent** from
the collapsed-TOC prose-cap allow-list (`courses.css:1141-1157`, which lists `.el--text`,
the question parts, `.lesson-unit__title`, `.unit-crumbs`, `.markdone`, `.fillgate`,
`.stepper`, `.switchgate`, `.guessnumber` — no image root). So `html.unit-tree-collapsed` —
a persisted global toggle — widens the box an image fills well beyond 46rem. Separately,
`.lesson { max-width: 46rem }` (`courses.css:292`) is 736px wherever a lesson renders
outside the unit shell, including the editor preview whose `.prev-inner` is also
`max-width: 46rem` (`editor.css:66`).

**Required measurement.** Implementation must measure and record in the plan, **at two
named viewports — 1280x720 (the e2e default) and 1920x1080** — since every box scales with
window width:

1. `.el--image--full`'s rendered width with the TOC expanded,
2. the same with `html.unit-tree-collapsed`,
3. the same in the editor preview,
4. `.asset-thumb`'s rendered width in the manager grid,
5. the same in the picker grid,
6. `.cell-img--full`'s rendered width in a 2-, 3- and 4-column table,
7. `.gallery__frame`'s rendered width,
8. `.dragimage__img` / `.dragimage__stage`'s rendered width.

The raise condition is "exceeds at either named viewport". (7) and (8) are listed because
`gallery` and `dragimage` are currently assigned 896px **by analogy** with the image
element, and neither is the same box: `.dragimage__stage` is `display: inline-block;
max-width: 100%`, so its used width is the image's own contribution rather than the column,
and `.gallery__frame` is `width: 100%` of whatever the gallery's ancestor is. Their `sizes`
values are recomputed from those measurements.

**Widths:**

- **`thumb` = 512px.** `.asset-grid` is `repeat(auto-fill, minmax(8rem, 1fr))`
  (`editor.css:349`) with no container `max-width`. With `auto-fill` the track count is
  `floor(container / 128)`, so a track is `container / n < 128(n+1)/n`, maximised at
  `n = 1` → **under 256 CSS px**. A fixed box under 256 CSS px needs at most 512 device px
  at DPR 2, so one thumb covers every fixed-box preset at DPR ≤ 2 — the grid, the picker,
  and the 240px table cell (480 ≤ 512). 320px was rejected: it covers DPR 1 but leaves the
  grid 1.25x soft at DPR 2 on exactly the retina hardware the complaint came from, and
  forcing a second candidate there would make the grid fetch the 896px `web` derivative
  into a ~180px box — a 5x linear oversample, ~950 times.
- **`web` = 896px.** Chosen to cover the widest measured box. A `web` of 648px would
  under-declare by up to 35% in the collapsed-TOC state and the browser would upscale into
  a wider box — a visible-blur regression on the primary student surface.

**`web`'s benefit is DPR-1-only, and that is accepted.** With `sizes` topping out at 896px,
a DPR-2 client needs ~1792 device px, finds no candidate that large, and selects the widest
available — the original (~1100px median). So on retina hardware the student surfaces fetch
what they do today. This is correct rather than regrettable: at a 1100px original and an
896px box, the original *is* the appropriate resource, and downscaling it further would
lose real detail. The consequence to state plainly is that the 21 MB `web` set is justified
by DPR-1 clients alone; the 15 MB `thumb` set carries the grid at both densities.

Both widths live as **module-level constants in `courses/derivatives.py`**
(`THUMB_WIDTH`, `WEB_WIDTH`), imported by the template tag, so a future width change cannot
drift the tag away from the bytes on disk.

Both derivatives are **lossless WebP**, saved with pinned encoder kwargs:
`format="WEBP", lossless=True, method=4, exact=True`. `method` (0–6) swings lossless encode
time several-fold and matters because generation runs synchronously inside an upload request
and in a management-command loop over 953 images; `exact=True` preserves RGB values under
fully-transparent pixels. The content is maths diagrams — thin strokes, small labels,
subscripts — where lossy ringing is precisely the artifact that would hurt legibility.

**The skip rule is width-only, and that is justified by measurement.** Decode cost is
width x height, so a tall narrow image escapes a width-only predicate. Measured in
`mat-pp`: only **7 of 953** images are at most 512px wide yet exceed 250k px (the largest
508x1486), and images at most 512px wide hold **0.8% of total pixels**. A height- or
area-aware predicate would complicate the derivative's dimensions for under one percent of
the decode budget.

### Generation module: `courses/derivatives.py`

```
generate_derivatives(asset) -> str       # assigns asset.derivatives_state AND returns it
delete_derivative_files(names, storage)  # deletes IMMEDIATELY; deferral is the caller's job
                                         # skips falsy names and already-missing files
```

**The falsy-name guard belongs to the function, not to its call sites.** Every caller can
pass blanks, and `post_delete` does so routinely: it passes
`[instance.thumb.name, instance.web.name]`, both blank for every video (232 in `mat-pp`)
and for every `skipped` or `failed` row. `FileSystemStorage.delete("")` raises
`ValueError("The name must be given to delete().")`, and `storage.exists("")` is *truthy*
because it stats `MEDIA_ROOT` — so an implementation that guards at only one call site
breaks ordinary video deletion. A test covers deleting a video asset with both derivative
fields blank.

`generate_derivatives` **assigns `asset.derivatives_state` on the instance** in addition to
returning it. Callers list that field in `update_fields`, so a version that only returned
the value would persist the stale one while the correct one was discarded as an unused
return.

`delete_derivative_files` takes **names, not an asset**, because its callers all need to
delete files that are no longer the asset's. **It deletes immediately and does not defer
internally.** This is stated explicitly because the neighbouring `_delete_file_if_unshared`
in the same module *does* call `transaction.on_commit` itself, so local precedent points the
wrong way — and the two call classes need opposite behaviour:

| Caller | Deferral |
| --- | --- |
| `post_delete` signal | Caller wraps in `transaction.on_commit` |
| `replace_asset` step 6 | Caller wraps in `transaction.on_commit` |
| `replace_asset` failure handler | **Immediate** — an `on_commit` callback registered on a transaction that is about to roll back never runs |
| Backfill `--force` | Immediate (no enclosing transaction) |
| `generate_derivatives`' own failure handler | Immediate |

`generate_derivatives` is **best-effort and never raises**. Rules, in order:

0. **Reset first.** Clear `thumb`/`web` field values to `""` (the *fields*, not the files —
   the caller owns file deletion), set `width`/`height` to `None`, and set
   `derivatives_state` to `""`, before any branch can return. The `""` matters: it is the
   sentinel the backfill uses to pick a row up, so steps 1–9 must each assign a terminal
   value (`ok` / `skipped` / `failed`) before returning — a path that returned with `""`
   still set would leave the row permanently re-processable. Without this, every early-return path leaves the **previous**
   image's values in place: on a replace where the new original is 500px wide, step 6 skips
   `web`, and `asset.web` would still point at the old picture's `-896.webp`. The same
   applies to stale `width`/`height` and to the non-image, animated and failed paths.
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
   Measured prevalence is low — 19 of 953 are mode `P`, 18 of them animated and excluded at
   step 4, leaving one — so this is a correctness fix against future PNG-8 uploads and the
   spec's own single-frame-GIF case.
6. For each target width, skip if `img.width <= target`.
7. **Encode to an in-memory buffer first.** Resample with `Image.LANCZOS`, save into a
   `BytesIO` with the pinned kwargs, then compare `buffer.tell()` against
   **`asset.file.size`** (the original's bytes on disk, not the decoded bitmap). Only if
   the buffer is smaller does a `FieldFile.save(name, ContentFile(buffer), save=False)`
   happen. Encoding straight to storage and "discarding" by blanking the field would leave
   orphaned bytes and burn a collision-suffix slot against the `max_length=200` budget for
   every discarded derivative — expected among the 25 JPEG/GIF/WebP originals, where a
   lossless-WebP derivative can exceed a photographic JPEG's size.
8. Return `ok` if anything was written, `skipped` if steps 6–7 declined both.
9. **The entire body — decode, resize, encode, and both storage writes — sits inside one
   guard catching broad `Exception`, logging, and returning `failed`.** Not a fixed tuple
   of Pillow exceptions: the riskiest step is `FieldFile.save(...)`, a storage write that
   can raise `SuspiciousFileOperation`, permission or quota errors, or backend-specific
   exceptions. **The handler must delete any derivative file it already wrote during this
   call** — track written names locally — before returning `failed`. Otherwise a successful
   `thumb` write followed by a raising `web` write leaves the thumb bytes on disk with
   rule 0 having cleared the field that referenced them; in `replace_asset` this compounds,
   because step 6 then compares the now-blank name against `old_thumb_name`, deletes the old
   file, and the orphan survives forever.

Derivative filenames are `<original-stem>-512.webp` / `-896.webp`, where the stem is
**`os.path.splitext(os.path.basename(asset.file.name))[0]`**. The basename matters:
`asset.file.name` is a storage-relative *path* (`courses/media/foo_AbC.png`), and passing its
full stem to `FieldFile.save` would nest it under `upload_to`, producing
`courses/media/derivatives/courses/media/foo_AbC-512.webp` — plausible-looking, and it
silently eats the `max_length=200` budget. Written through `FieldFile.save(...)` so Django's
storage applies its own collision suffix. **Each row
therefore owns its derivative files outright.** Load-bearing: migration `0008` copied
storage references verbatim, so two `MediaAsset` rows can share one `file.name` — the
hazard `_delete_file_if_unshared` exists to guard. Derivatives are generated per row and
never shared, so their deletion needs no such guard and must not borrow one.

### Render path: one template tag

A single tag in `courses/templatetags/courses_media_extras.py` owns this for all eight sites.
**The module is new** — the package currently holds only `courses_extras.py` and
`courses_manage_extras.py`. A third library rather than an addition to either existing one,
because the tag is shared by manage-side templates (`_asset_cell`, `_picker_grid`) and
student-side templates alike, so neither `courses_extras` nor `courses_manage_extras` is the
right home.

**A `simple_tag` returning `format_html(...)`, not an `inclusion_tag`.** An
`inclusion_tag` performs a full template load-and-render per invocation — ~950 nested
renders on the manager grid where there are currently zero.

```
{% media_img asset preset="el-full" alt=el.alt css_class="cell-img cell-img--full" extra="data-zoomable" %}
```

**Argument contract:**

- `asset` — a `MediaAsset` or `None`.
- `preset` — a key from the table below; unknown raises.
- `alt` — defaults to `""`; escaped normally by `format_html`.
- `css_class` — a string; escaped normally.
- `extra` — a whitespace-separated list of **boolean attribute names only**, validated
  against an allow-list (`data-asset-preview`, `data-zoomable`), which covers all five real
  uses. Not a raw-HTML sink: `format_html` escapes interpolated arguments, so a valued
  attribute like `data-x="1"` would be escaped into visible text, and marking the argument
  safe would make the tag an injection point. Names outside the allow-list raise.
  `loading`, `width`, `height`, `src`, `srcset`, `sizes` and `data-zoom-src` are owned by
  the tag and cannot be passed through `extra`.

#### Per-site classes and attributes

Every layout invariant depends on these classes surviving, and `media_preview.js` is armed
off `[data-asset-preview]`:

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

- `imageelement.html` — `{% media_img el.media preset="el-"|add:el.size ... %}`.
  `ImageElement.size` is a `TextChoices` field, always populated.
- `_table_cell.html` and `_filltable_cell.html` —
  `{% media_img cell.media preset="cell-"|add:cell.size ... %}`.

**The existing `|default:'full'` is dropped, not relocated.** `TableElement._cell`
(`models.py:1148-1152`) documents that `size` is *always* written, and
`FillTableElement._cell` (`:1343-1353`) mirrors it, so the default is vestigial. It must
not be naively carried across: `"cell-"|add:cell.size|default:"full"` applies `default` to
the already-concatenated string, which is non-empty and so never fires, producing an unknown
preset that **raises on a student lesson page**.

**An unknown preset raises at render time**, and a test pins that this is unreachable from
stored data: **for every `v` in `ImageElement.Size.values`, `f"el-{v}"` is a preset key; for
every `v` in `TableElement.CellImageSize.values`, `f"cell-{v}"` is a preset key.** (Stated
per-value deliberately — the preset keys are prefixed, so the raw key set is *not* literally
a superset of `{"small","medium","large","full"}`, and a test written from that looser
wording would fail and then be weakened.)

#### `src`, `srcset`, and the two strategies

**`src` is always emitted:**

- **Fixed-box presets:** `src` = **`thumb`**, falling back to the original when `thumb` is
  blank. No `srcset` at all. One 512px thumb covers every fixed box at DPR ≤ 2, so there is
  no second candidate to offer, and this guarantees the derivative is what actually loads.
- **Fluid presets:** `src` = **the original**. When `srcset` uses `w` descriptors the
  browser ignores `src` for selection, so this only serves a client that does not understand
  `srcset`, which should get full quality.

| Preset | CSS box | Strategy |
| --- | --- | --- |
| `grid` | `.asset-thumb` (analytically < 256px) | `src` = thumb, no `srcset` |
| `cell-small` | `.cell-img--small` (80px both axes) | `src` = thumb, no `srcset` |
| `cell-medium` | `.cell-img--medium` (160px both axes) | `src` = thumb, no `srcset` |
| `cell-large` | `.cell-img--large` (240px both axes) | `src` = thumb, no `srcset` |
| `cell-full` | `.cell-img--full` (100% of its `<td>`, `max-height: 60dvh`) | `w` + `sizes="(max-width: 640px) 100vw, 45vw"` |
| `el-small` | `.el--image--small` (25%, `max-height: 30dvh`) | `w` + `sizes="(max-width: 640px) 25vw, 224px"` |
| `el-medium` | `.el--image--medium` (50%, `max-height: 45dvh`) | `w` + `sizes="(max-width: 640px) 50vw, 448px"` |
| `el-large` | `.el--image--large` (75%, `max-height: 60dvh`) | `w` + `sizes="(max-width: 640px) 75vw, 672px"` |
| `el-full` | `.el--image--full` (`max-height: 100dvh`) | `w` + `sizes="(max-width: 640px) 100vw, 896px"` |
| `gallery` | `.gallery__frame` (100%, `aspect-ratio: 4/3`, `max-height: 70vh`) | `w` + `sizes` from measurement (7) |
| `dragimage` | `.dragimage__img` (`.dragimage__stage` is inline-block) | `w` + `sizes` from measurement (8) |

The `el-*` pixel values are 25/50/75/100% of the widest measured column and must be
recomputed once measurements (1)–(3) are taken; the values shown assume 896.

**The `srcset` candidate list, literally.** For `w`-descriptor (fluid) presets:

```
srcset="{thumb.url} 512w, {web.url} 896w, {file.url} {asset.width}w"
```

Each derivative appears only when its field is non-blank; the original appears only when
`asset.width` is known. Order is ascending by width. Note that a non-blank `web` implies a
non-blank `thumb` (896 > 512, so anything wide enough for `web` is wide enough for
`thumb`), which is why "`src` = thumb, falling back to the original" is exhaustive for
fixed-box presets — there is no state with `web` present and `thumb` absent.

**`srcset` and `sizes` are omitted entirely whenever no derivative exists** — i.e. whenever
the only available candidate would be the original. This covers the animated GIF, the
`failed` row, and every original narrower than both targets. It is not merely tidiness:
see the `width`/`height` invariant below.

**`cell-full` cannot be a single measured constant.** `.cell-img--full` is `max-width: 100%`
of its `<td>` in an auto-layout table, so the used width varies with column count,
per-column content and viewport. Its `sizes` is therefore viewport-relative (`45vw`
approximating a mid-range column count). Measurement (6) records the real used widths at 2,
3 and 4 columns, and the plan states the maximum over- and under-declaration accepted across
them. This is a width-axis error and is explicitly *not* covered by the height-axis
acceptance below.

**Known height-axis over-fetch, accepted.** Every preset is a two-axis bounding box, but
`sizes` describes width only. The full list of height caps:
`.el--image--small/medium/large/full` at `30/45/60/100dvh` (`courses.css:90-93`),
`.cell-img--small/medium/large` at 80/160/240px in both axes (`:1326-1328`),
`.cell-img--full` at `60dvh` (`:1329`), and `.gallery__frame` at `70vh` with
`object-fit: contain` (`:1640-1647`) — the gallery is the largest of these. Accepted: the
worst case is fetching `web` instead of `thumb`, still far below the original.

**Degenerate inputs.** `asset.file.url` raises `ValueError` on a blank `FileField`:

- `asset is None` → render nothing.
- `not asset.file.name` → render nothing.
- `asset.width is None` → emit a plain `src` with **no** `srcset`.

These guards are only reachable on the six element-template sites. `_asset_cell.html:3` and
`_picker_grid.html:5` both emit `data-url="{{ asset.file.url }}"` on the wrapper *before*
the `<img>`, so a blank-file asset 500s those pages before the tag is reached. Those two
`data-url` attributes are left as they are — pre-existing behaviour, out of scope — and the
guard's tests must therefore target an element template.

### Layout invariants

#### `width`/`height` are load-bearing against `sizes`, not a reflow nicety

With `w` descriptors, an `<img>` whose CSS `width` is `auto` takes its **density-corrected
intrinsic size**, which equals the declared `sizes` width — *not* the selected resource's
pixel width. Every fluid-preset box has no author width: `.el--image img` is only
`max-width: 100%; height: auto`; `.el--image--small/medium/large` put `width: fit-content`
on the **figure**; `.el--image--full` has no cap; `.cell-img--full` is `max-width: 100%`;
`.dragimage__stage` is `display: inline-block` shrink-wrapping the image.

So a 200px-wide original carrying `sizes="…896px"` would render at 896 CSS px — a 4.5x
upscale where today it renders at 200px. Two rules prevent it, and both are required:

1. **`srcset`/`sizes` are omitted whenever no derivative exists** (above), which covers
   exactly the narrow originals most at risk.
2. **`width`/`height` are emitted on every preset whenever `asset.width` is known.** The
   presentational hint pins the used width to a definite value instead of letting `sizes`
   supply it. This — not reflow — is the reason they exist.

**The attributes always carry `asset.width` / `asset.height` — the *original's* dimensions
— on every preset, including the fixed-box ones where the loaded resource is the 512px
thumb.** No derivative dimensions are stored, and none need to be. This is safe because
every fixed box carries a binding `max-width` or `aspect-ratio` that overrides the hint, and
because the rounded derivative ratio differs from the original's only in the fourth decimal
(1100x841 → 896x685 is 1.3080 vs 1.3079), inside the ±1 px geometry tolerance. Stated
explicitly so no implementer concludes the thumb's own dimensions are required and goes
looking for a field that does not exist.

The reflow benefit, separately, is real only on `.el--image`, `.cell-img*` and
`.dragimage__img`. It does **not** apply to the grid: `.asset-thumb` already declares
`width: 100%; aspect-ratio: 4 / 3; object-fit: cover` (`editor.css:360-365`), so its box is
fully determined before any image loads.

#### The gallery preset omits `width`/`height`

`.el--gallery .gallery__frame img` (`courses.css:1647`) is
`max-width: 100%; max-height: 100%; object-fit: contain` with **no `height: auto`**, sized
by its frame's `aspect-ratio: 4/3`.

Today, with no dimension attributes, CSS's replaced-element min/max algorithm applies both
clamps *ratio-preserving*. Once `width`/`height` hints are present they compute to lengths
and `max-width`/`max-height` clamp **independently**. Worked example in a 736px frame
(4/3 → 552px tall) with an 1100x841 original: today the element box is ~722x552; with the
attributes it becomes 736x552. `object-fit: contain` keeps the *painted* image identical, so
nothing looks different — but the element box moves ~14px, far outside the ±1 px geometry
tolerance below.

**Therefore the `gallery` preset emits no `width`/`height`.** The reflow benefit is not
claimed there anyway (the frame's `aspect-ratio` already reserves the space), and the
alternative — adding `height: auto` to that CSS rule — would be an unmeasured layout change
the Goal forbids. The `srcset`-omission rule alone protects the gallery from the `sizes`
upscale, since a gallery image with no derivative gets no `sizes` at all.

#### `height: auto` audit

`.el--image img` (`courses.css:46`), `.cell-img` (`:1325`) and `.dragimage__img` (`:538`)
declare `height: auto`. `.gallery__frame img` (`:1647`) does not, and is handled above. No
CSS is changed. The invariant, stated to match reality: *every preset's CSS declares
`height: auto`, an explicit `aspect-ratio`, or an ancestor `aspect-ratio` together with
`object-fit`.*

### Lazy loading — grid and picker only

The derivative bounds cost **per image**; `loading="lazy"` bounds **how many** decode.
~950 thumbs at 512px is ~750 MB of bitmap if all decode at once; with lazy loading only the
~24 on screen decode, about 19 MB.

**`loading="lazy"` is emitted on the `grid` preset only.** The student element templates do
**not** get it: a unit page carries tens of images rather than ~950, so the derivative alone
suffices there; and `courses.css:103-108` and `:1349-1351` are hand-tuned `@media print`
blocks capping images at 45/75/110/170 mm, so a printed lesson is an intended surface — and
a printed document is by definition below the fold. Rather than depend on per-browser
force-load-before-print behaviour, the risk is removed by not deferring those images. The
grid and picker are never printed.

### Print

A browser prints whichever candidate is already loaded, so a `full` image printed at 170 mm
comes from the `web` derivative at DPR 1 (and from the original at DPR 2, per the widths
section). **Accepted, with the reason stated:** `sizes` accepts a `<media-condition>`, which
does not admit media *types*, so `sizes="print 170mm, …"` is not valid and there is no
`sizes`-level fix. At 896px across 170 mm the effective density is ~134 dpi, above the
~96 dpi a browser assumes for CSS-px-to-physical mapping.

### Server cost

Two before/after measurements are required, because this change pushes on the metric against
which pagination is being deferred: **HTML size** of `/manage/courses/mat-pp/media/`
(currently 2.1 MB) and **server render time** of the same URL (currently 2.2 s). Both
recorded in the PR.

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

- `media_preview.js:172` is `if (!src || (anchor.complete && anchor.naturalWidth === 0))` —
  **two conditions, and only the second moves.** The `complete && naturalWidth === 0` branch
  interrogates the *thumb* after the repoint, while a different URL is loading, so a broken
  original would yield a silently empty overlay; that branch moves to the overlay image's
  own `error` handler, which **does** already exist (`:54-58`). The `!src` branch is
  **retained**, now testing the `data-url` read, because its own in-file comment states why
  it cannot be delegated: assigning `""` does not reliably fire `error` and can leave the
  *previous* asset's image showing in the overlay.
- **The hover preview becomes a real fetch.** Today the overlay copies the grid `<img>`'s
  already-loaded original and paints instantly; after the repoint it fetches an uncached
  original on every hover. Verified in `open()`: `overlayImg.hidden = true` until `load`, so
  it degrades to caption-first-then-image rather than breaking. **Accepted and stated** —
  that is the existing cold-open path, not a new state — and a test pins caption-first.
- **`imagezoom.js` has no `load`/`error` handlers and must gain them.** Verified by reading
  the module end to end: it registers exactly a `dialog` `click`, a `dialog` `close`, a
  document `click`, a document `keydown`, and the capture-phase Escape — nothing on
  `dialogImg`. (The handlers that "already exist" are `media_preview.js`'s; the fact does not
  transfer.) The comment at `:74`, `// already fetched: served from cache`, is load-bearing
  documentation of why there is no loading state, and pointing at `data-zoom-src` makes it a
  genuine network fetch. Required: correct the comment; add `load` and `error` handlers on
  `dialogImg` with a stale-source guard mirroring `media_preview.js`'s `expectedSrc` pattern
  (`:49-58`); show the dialog in a loading state until `load` fires; on `error`, keep the
  dialog open with a message rather than closing, so a broken original is visible rather than
  a dialog that flickers shut. A test pins the loading state and the `error` path.

  **This new UI has three constraints the spec must carry, because it is the only
  deliberate visual departure from the Goal:**

  1. **i18n.** `imagezoom.js` holds no inline strings; every user-visible string goes through
     `label(key, fallback)` off `window.IMAGEZOOM_I18N` (`imagezoom.js:17`), and that blob is
     declared **three times** — `templates/courses/lesson_unit.html:84`,
     `templates/courses/manage/editor/editor.html:206`,
     `templates/courses/quiz_unit.html:38` — each as
     `{ enlarge: "{% trans … %}", dialog: "{% trans … %}" }`, with
     `tests/test_imagezoom_render.py:147` asserting the blob is present on every arming
     page. The loading label and the error message therefore need **new keys added to all
     three declarations**, read via the existing `label()` helper, plus `{% trans %}` markup
     and regenerated `.po`/`.mo` Polish entries. A hardcoded English string on a Polish
     product is the failure mode being prevented.
  2. **CSS scoping.** `tests/test_imagezoom_render.py:117-123` pins
     `dialog.imgzoom:not([open]) { display: none; }`, requires box rules to be
     `.imgzoom[open]`-scoped, and asserts that **no unscoped `^\.imgzoom\s*\{` rule exists**
     in `courses.css`. Any new rule must be `[open]`-scoped or carry a new class, or that
     source-level invariant breaks.
  3. **Named markup.** The plan states the added element and class names (a child of
     `dialog.imgzoom`, not a reuse of `dialogImg.alt`), so the CSS and the test have a fixed
     target.

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
`derivatives_state=""` and serve originals, and the import completion message tells the user
to run `backfill_media_derivatives --course <slug>`.

**Implementation per site:**

- **`create_asset`** — after `asset.save()`, when `generate` is true call
  `generate_derivatives(asset)` and persist with
  `update_fields=["width","height","thumb","web","derivatives_state"]`.
- **`get_or_create_asset`** — this path **does not call `create_asset`**; it constructs
  `MediaAsset(...)` directly (`courses/lal_loader/media.py:42-46`), so the `generate`
  keyword never reaches it. Call `generate_derivatives(asset)` *before* the existing
  `asset.save()` — a full save with no `update_fields`, so it persists the new fields
  without further change. Only this newly-created branch generates; the `content_hash` dedup
  early-return at `:39-41` must **not** regenerate.

  **Why generate-before-save is safe here but forbidden in `replace_asset`.** The real
  constraint is *"generate only against a committed file"*, not *"generate after
  `Model.save()`"*. At `courses/lal_loader/media.py:45` the line
  `asset.file.save(path.name, ContentFile(data), save=False)` has already written the bytes
  to storage and set `_committed = True`, so by line 46 `asset.file` is a committed
  `FieldFile` and Pillow reading it cannot disturb a pending write. `replace_asset` differs
  because its file is still an uncommitted `UploadedFile` until its own step 3. Stated
  explicitly because the two orderings otherwise read as a contradiction.

  Reached only from the `import_lal_content` management command, never from a request, so
  there is no worker timeout to trip and no user awaiting a response; `courses/lal_loader/`
  opens no `transaction.atomic` around the loop, so no write transaction is held open.

### `replace_asset` — the exact sequence

The existing function (`courses/media.py:150-184`) ends with
`asset.save(update_fields=["file", "original_filename", "content_hash"])`. Generating
derivatives *after* that save without extending `update_fields` would silently drop the five
new fields. Generating them *before* it would read `asset.file` while it is still an
uncommitted `UploadedFile`: Pillow advances the stream, and Django then writes to storage
from the current position, truncating the stored original. (`_validate_file`'s
`getattr(file, "_committed", False)` short-circuit, `courses/validators.py:83-95`, is
sensitive to when the file is touched for the same reason.)

Required order:

1. Capture `old_thumb_name`, `old_web_name` and the shared storage, **before** reassigning.
2. Assign the new file; `full_clean(...)` as today.
3. `asset.save(update_fields=["file", "original_filename", "content_hash"])`.
4. `generate_derivatives(asset)` — reads the **committed** `FieldFile`, so no stream position
   is shared with a pending write. Any read must `seek(0)` regardless.
5. `asset.save(update_fields=["width","height","thumb","web","derivatives_state"])`.
6. `transaction.on_commit(...)` deleting each captured old derivative name **only if it
   differs from the newly written one** — `if asset.thumb.name != old_thumb_name`, likewise
   for `web`. This mirrors the guard already applied to the original at
   `courses/media.py:180-183` ("Storage hands back the SAME name when the old file was
   already missing, in which case the 'old' file is the one just written"). Without the
   comparison, a replace whose old derivative was absent from storage would delete the file
   step 4 just wrote. Plus the existing `_delete_file_if_unshared` call for the old original.

### Orphaned bytes on failure

`generate_derivatives` writes to storage *inside* the atomic block, so a rollback discards
the field values but leaves the bytes on disk.

**Django 5.2 provides `transaction.on_commit` but no `on_rollback`** — and because
`replace_asset` is decorated `@transaction.atomic`, the rollback happens at the decorator
boundary, after control has already left the function body, so there would be nowhere for
such a callback to run even if one existed. Do not go looking for that API.

The mechanism is an explicit `try/except` that **begins at step 4, not at the top of the
function**. This scoping is required: `replace_asset` raises before step 4 on at least two
paths — the empty-file `ValidationError` and `full_clean(exclude=[...])` — and at that point
`asset.thumb.name` / `asset.web.name` still hold the **old, live** names. A handler wrapping
the whole body and "deleting the newly-written derivative names" off the instance would
destroy the surviving row's derivatives, producing exactly the non-blank-field-pointing-at-
absent-bytes state named as the one honest limit below.

The handler deletes only names read from `asset.thumb.name`/`asset.web.name` *after*
`generate_derivatives` returned, and only where they differ from the captured `old_*` names
— the same `!=` guard as step 6 — then re-raises. It calls `delete_derivative_files`
directly (immediate, not deferred).

**It also deletes the newly written original.** Because `generate_derivatives` never raises,
the only real raiser inside the `try` is **step 5's `asset.save(update_fields=[…])` — a DB
write this change introduces**; today's `replace_asset` has no DB write after step 3. When
step 5 raises, `@transaction.atomic` rolls the row back to the old file, but the *new*
original's bytes were already written to storage at step 3 and nothing references them. The
handler must therefore also delete `asset.file.name` when it differs from the captured
`old_name` — the same guard again. Without this, the section's exhaustiveness claim is false
for the one window this change creates.

**Position of the other three creation sites**, so this section is exhaustive rather than
apparently so:

- **`create_asset` under `media_upload`** — `create_asset` is not itself
  `@transaction.atomic`; the view is not wrapped either, and `ATOMIC_REQUESTS` is not
  enabled. A failure after the derivative write leaves the row too, so there is no
  orphan-without-row case. No cleanup prescribed.
- **`create_asset` under the transfer importer** — passes `generate=False` and writes no
  derivatives. `_create_media` (`:880-892`) appends only `asset.file.name` to
  `created_files`, and `_run_import` (`:1036`) calls `_cleanup_files` on every failure path
  (lines `1042/1045/1052/1062`). Closed by construction, but the invariant is stated and
  tested so a later change re-enabling generation there cannot silently reintroduce up to
  2,000 orphaned files.
- **`get_or_create_asset`** — runs in a management command with no enclosing atomic block;
  a raise aborts the import and the operator re-runs it. The orphan is accepted here, on the
  same footing as the original file's orphan today.

### Asset deletion

`courses/signals.py:_delete_mediaasset_file` currently removes `instance.file`. It gains
`delete_derivative_files([instance.thumb.name, instance.web.name], storage)`, wrapped by the
caller in the same `transaction.on_commit` and guarded the same way (blank or already-missing
is a no-op). `post_delete` — rather than `Model.delete()` — remains correct: a cascade delete
(removing a Course) bulk-deletes rows and never calls `Model.delete()`.

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
- **Persists each row individually, immediately after `generate_derivatives`, with
  `update_fields=["width","height","thumb","web","derivatives_state"]`** — the same
  five-field list every other call site uses, so the highest-volume writer cannot be the one
  that silently drops them.
- `--dry-run` **writes nothing to storage or the database** — it must not call
  `generate_derivatives`, which writes files. Its report is therefore **counts of rows per
  `derivatives_state` that would be processed, plus the total, with no per-row decode**.
  This limit is stated because "what it would do" cannot mean more: whether a given row
  would produce derivatives, be skipped as animated or narrow, or fail, is only knowable by
  decoding it. An implementer chasing a richer report would re-introduce exactly the decode
  and storage writes this flag exists to avoid. The test asserts the counts, not only the
  absence of writes.
- `--start-at <pk>` for resuming; `--course <slug>` to scope it.
- `--force` regenerates existing derivatives — needed if a target width, the encoder kwargs,
  or the resampling behaviour changes (the mode-normalisation rule in particular requires
  regenerating any palette-sourced derivative already on disk).
- **`--force` must capture the old `thumb`/`web` names and call `delete_derivative_files`
  with the same `!=` guard as `replace_asset` step 6.** Because derivatives are written via
  `FieldFile.save(...)`, storage hands back a collision-suffixed name (`x-512_AbC.webp`),
  the field repoints, and the previous file would be orphaned — with repeated `--force` runs
  multiplying orphans and lengthening names against the `max_length=200` budget.
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
404. What prevents that state is the `!=` guard, applied in `replace_asset` step 6, the
`replace_asset` failure handler, and backfill `--force` — the only code paths that could
delete a live row's current derivative.

| Condition | Behaviour |
| --- | --- |
| Pillow or storage raises anywhere in generation | Log; fields cleared by rule 0; **any file already written this call is deleted**; state `failed`; original served |
| Not an image / animated | Fields cleared, dimensions recorded where known, state `skipped`; original served, animation intact |
| Palette (`P`) / `1` mode source | Converted to `RGB`/`RGBA` before resize, so `LANCZOS` is honoured |
| Original narrower than a target width | That derivative skipped |
| Derivative encodes no smaller than the source | Buffer discarded before any storage write |
| `asset is None` or blank `file.name` | Tag renders nothing (never `asset.file.url`, which raises `ValueError`) |
| `width`/`height` unknown (null) | Tag omits `srcset` and emits a plain `src` |
| No derivative exists | `srcset` and `sizes` omitted entirely — required, not tidiness (see the `width`/`height` invariant) |
| Unknown preset | Raises at render time; unreachable from stored data by the per-value rule |
| Backfill hits a bad row | Logged, counted, run continues |
| Replace raises before step 4 | `try` has not begun; old derivatives untouched |
| Replace raises at or after step 4 | Handler deletes only names written this call and differing from the old ones; re-raises |

Generation never propagates an exception into an upload request.

## Testing

Ordered so the client audit is verified before anything can regress.

### JS repointing (lands and is verified first)

**These tests use synthetic markup, not converted production templates.** The ordering rule
puts this commit *before* any template emits a derivative `src` or `srcset`, which makes the
obvious formulation impossible: until `_asset_cell.html` is converted the thumb `src` *is*
the original, so "the overlay loads the original" passes identically on the un-repointed JS
and the required A/B cannot be red. Each test therefore builds the
`srcset` / `data-zoom-src` / derivative-`src` markup by page evaluation (or a test-only
fixture template) before acting.

- Hover preview loads the **original** URL when the grid `<img>`'s `src` is a thumb. Assert
  on the overlay image's resolved `src` — the overlay opens either way.
- Click-to-enlarge on an image with a `srcset` and `data-zoom-src` opens the **original**,
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
- The zoom dialog shows its loading state until `load` fires, and on `error` stays open with
  a message rather than closing.

### `courses/derivatives.py`

Fixture discipline: `make_image_asset(course, filename="x.png", size=(1, 1), ...)`
(`tests/factories.py:150`) defaults to a **1x1** PNG, narrower than both targets, so
generation returns `skipped` with blank fields — indistinguishable from
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
- Discards a derivative that encodes no smaller than its source **without writing it to
  storage** (asserted on the storage backend, not just the field).
- Returns `failed` without raising on a corrupt file **and** on a storage write failure
  (forced by patching the backend) — and in the latter case **leaves no file behind** when
  the first write succeeded and the second raised.
- Applies EXIF orientation.
- Assigns `asset.derivatives_state` on the instance, not only as a return value.

### Service layer

- `create_asset` populates all five fields; with `generate=False`, `derivatives_state`,
  `thumb` and `web` are blank (`""`) and `width`/`height` are **`None`** — they are
  `PositiveIntegerField(null=True)`, so a test written as "all five stay `''`" asserts the
  wrong thing for two of them.
- `delete_derivative_files` is a no-op for a video asset with both derivative fields blank,
  and does not raise (`FileSystemStorage.delete("")` would).
- `replace_asset` regenerates **and** deletes superseded derivative files; asserts the new
  field values persist (the `update_fields` trap); asserts that when the old derivative name
  is reused the file is **not** deleted (the `!=` guard); a raise *before* step 4 leaves the
  old derivatives intact; a raise *at* step 4 deletes only what that call wrote; **a raise
  at step 5 (forced by patching `save`) leaves neither the new derivatives nor the new
  original's bytes behind** — the window this change introduces.
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
- **A sub-`sizes`-width original renders at its own intrinsic width** in `el-full`,
  `cell-full` and `dragimage` — the `sizes`-upscale guard, asserted on measured geometry.
- Omits `srcset`/`sizes` whenever no derivative exists; omits `srcset` when `width` is null;
  renders nothing for `asset=None` and blank `file.name` (tested on an element template, the
  only place those guards are reachable).
- Raises on an unknown preset; **per-value key test** for `ImageElement.Size.values` and
  `TableElement.CellImageSize.values`.
- Emits the exact per-site class and attribute set, including `data-asset-preview` on the
  manager cell and *not* on the picker cell.
- `extra` rejects a non-allow-listed name and rejects a valued attribute.
- Emits `loading="lazy"` on `grid` **and not** on the student element presets.
- Emits `width`/`height` on every preset **except `gallery`**, always carrying the
  *original's* dimensions.
- Emits `data-zoom-src` **only where the tag also emits `data-zoomable`** (i.e. driven by
  `extra`), with a negative assertion that the `grid` preset does **not** carry it.
  `data-zoom-src` is consumed only by `imagezoom.js`, which is armed off `[data-zoomable]`
  — a preset the zoom never touches has no use for it, and emitting one full media URL into
  each of ~950 grid cells would inflate exactly the 2.1 MB HTML figure this change makes a
  required before/after measurement and the basis for deferring pagination.
- Every preset's CSS declares `height: auto`, an explicit `aspect-ratio`, or an ancestor
  `aspect-ratio` plus `object-fit` — asserted against the stylesheet, with the gallery
  exercising the third case.

### Per-template conversion

**One rendering assertion per in-scope template** that the emitted HTML references a
derivative (or at minimum a `srcset`). Without these, a build that left
`imageelement.html`, both table cells, the gallery and both drag-to-image `<img>` tags
untouched would pass every other test: the tag unit tests pass, the geometry tests pass
trivially, and the acceptance check only touches the manager grid. A forgotten template must
be RED, not invisible.

**Existing assertions must be audited, not just new ones added.** `tests/test_table_render.py:94`
asserts `f'src="{asset.file.url}" in html'`, which directly contradicts the new `cell-*` rule
(`src` = thumb) — and worse, it will **keep passing** if its fixture is narrow enough that no
thumb exists, so the conversion would look verified while the assertion silently measures the
fallback path. The plan sweeps the existing assertions over all eight sites —
`tests/test_table_render.py`, `test_gallery_render.py`, `test_imagezoom_render.py`,
`test_media_manager.py`, and the e2e image/media files — and states, per assertion, which is
updated to expect a derivative and which is deliberately left on the fallback path.

### Backfill command

Populates a course's assets; `--dry-run` writes nothing to storage or the DB; a second run
is a no-op; `--start-at` skips lower pks; `--force` regenerates `ok` rows **and leaves no
orphaned derivative files**; `skipped` rows are not retried without `--force`; `failed` rows
are; one corrupt asset does not abort the run.

### Rendering and layout

**Fixture discipline applies here too, and its absence would make this whole section
vacuous.** `make_image_asset` defaults to a 1x1 PNG; with a narrow fixture no derivative
exists, so `srcset`/`sizes` are omitted, `src` falls back to the original, and the geometry
test measures a page byte-identical to today's — unable to detect a `sizes`-driven upscale,
a wrong `w` descriptor, or the gallery's ~14 px box shift, which is the one thing this
section is named as catching. **Every asset in a geometry assertion has an original wider
than 896 px with both derivatives generated**, so the measured page actually carries
`srcset`, `sizes` and `width`/`height`.

**The baseline is measured, not remembered.** "Unchanged" is relative to something, and a
test that measures the post-change page and compares it to itself is unfalsifiable. The
reference geometry is captured **on the pre-change build**, at both named viewports, and
recorded as explicit per-template, per-axis constants in the plan — so the assertion is a
real A/B against prior geometry.

- Every touched template renders unchanged **layout**, asserted on measured box geometry
  (`bounding_box()`) against those recorded constants **with a ±1 px tolerance per axis**.
  The tolerance is required, not slack: a derivative's height is a rounded proportional
  scale of the original's, so their intrinsic ratios differ slightly (1100x841 → 896x685 is
  1.3080 vs 1.3079), and where a height cap binds the used width can shift sub-pixel.
- The gallery is included in this assertion, which is what would catch the ~14px box shift
  if `width`/`height` were ever added to that preset.
- Screenshots of the media manager, the picker, and a student unit in light and dark, judged
  separately.

### Acceptance — tied to the measured symptom

**Fixture discipline extends here:** every grid asset used by an acceptance assertion has an
original wider than 896px. Otherwise no thumb exists, `src` falls back to the original, and
the assertion either has to be written against the original or stops discriminating.

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
removal, the `update_fields` truncation, the `!=` guard removal, and the
`srcset`-omission-when-no-derivative removal — each of which produces a build that looks
correct and measures wrong.
