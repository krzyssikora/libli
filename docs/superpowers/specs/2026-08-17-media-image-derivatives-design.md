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

**Goal:** serve appropriately-sized images on every in-scope surface **except `cell-full`**,
without changing a single rendered layout, and without a commit at which any surface is
degraded.

`cell-full` (a full-width image in a table cell) is a named, permanent exception: it sits in
an auto-layout table whose column width derives from the image's intrinsic contribution, so
*any* change to what it loads moves the column. Measured and held back deliberately — see
"`cell-full` gets NO derivative at all". Every other in-scope surface is covered.

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
**`{"asset": img["media"], "alt": ..., "desc": ...}`**, dropping `url` entirely. The
template's docblock (lines 1–7) documents the shape as `{url, alt, desc}` and **must be
updated** with it.

`figures` has no *production* consumer outside this template, but it does have a **test**
consumer: `tests/test_imagezoom_render.py:58-67` hand-builds a `figures` list of
`{url, alt, desc}` dicts. That test must be migrated to the new shape — see "Existing test
fixtures".

Each of the seven templates needs its own `{% load courses_media_extras %}`. Django does
**not** inherit `{% load %}` across `{% include %}`. Current state of all seven:

| Template | Today | Change |
| --- | --- | --- |
| `imageelement.html` | *(no load tag)* | new line — safe, see below |
| `galleryelement.html` | *(no load tag)* | new line — safe, see below |
| `_table_cell.html` | *(no load tag)* | **inline** on line 1 |
| `_filltable_cell.html` | `{% load i18n %}` | **inline**, append to line 1 |
| `_picker_grid.html` | `{% load i18n %}` | append |
| `_asset_cell.html` | `{% load i18n courses_manage_extras %}` | append |
| `dragtoimagequestionelement.html` | `{% load i18n l10n courses_extras %}` | append |

**Neither `_table_cell.html` nor `_filltable_cell.html` may gain a *leading* newline.** (The
load-bearing property is leading whitespace, not trailing: measured, `_table_cell.html` is
200 bytes ending `{% endif %}` with no terminator, while `_filltable_cell.html` is 890 bytes
ending `{% endif %}\r\n` — that trailing byte is already part of today's output.) Both write
`{% load … %}{% if … %}` with no separator, so the repo treats their output whitespace as
load-bearing (they render into table cells). The load tag goes **inline on the existing
first line** for those two, never on a line of its own.

`imageelement.html` and `galleryelement.html` take a standalone load line safely: both
render block-level elements (`<figure class="el el--image">`, `<div class="el el--gallery">`)
where a leading newline in the fragment collapses in HTML whitespace processing and reaches
no text node. The distinction is worth stating because this repo already treats render bytes
as load-bearing in this area — `tests/test_table_render.py:122`,
`test_text_cell_bytes_are_unchanged_by_the_partial_factoring`, exists precisely to catch a
stray newline in a cell partial.

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
filters against it. **It lives in `courses/models.py`**, next to `MediaAsset.Kind`, and
`courses/derivatives.py` imports it from there — not the reverse. The direction matters:
`models.py` needs it at module scope for `choices=`, so defining it in `derivatives.py`
would set up a circular import the moment `derivatives.py` needs anything from `models`. It exists because the other four fields cannot express the difference
between *declined*, *interrupted*, and *failed*: `width` populated with both derivatives
blank is the stored shape of all three.

- `""` — never attempted. Backfill processes it.
- `ok` — derivatives generated (one or both).
- `skipped` — deliberately declined, by any of **five** routes: not an image, animated,
  narrower than both targets, every candidate encoded no smaller than the source (rule 7),
  or every candidate structurally impossible (derived height would be 0, or would exceed
  WebP's 16383 px cap — rule 6). Backfill leaves it alone unless `--force`. The last two
  routes matter operationally: this definition is what an operator reads to decide whether
  `--force` is needed after an encoder-kwargs change, and routing the impossible cases here
  rather than to `failed` is what stops the backfill retrying them on every run forever.
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

### A note on the measurements quoted in this spec

**Every absolute pixel figure quoted below is A/B evidence from an isolated CSS harness, not
a measurement of the real surface, and none of it may seed a `sizes` value.** The harness
reproduced the preset rules in isolation; it did **not** reproduce `.el { margin: 1rem 0 }`
(`courses.css:4`), which is what overrides the UA default `figure { margin: 1em 40px }`. So
harness figures for `.el--image` boxes are 80 px narrower than the real ones — the quoted
"567.98" is `648 − 80`, an artifact of the missing rule.

**What survives and what does not:**

- **Survives — every A/B conclusion**, because both arms ran in the same harness and the
  findings are differential: dimension attributes distort portrait images; the
  no-attributes design moves nothing; `cell-full` moves its `<td>` under both alternatives;
  `cell-large`'s `srcset` moves nothing at DPR 1 and 3.
- **Does not survive — every absolute number**, as an input to a `sizes` value or a fixture
  threshold. Those come only from measurements taken on the real surface, per the protocol
  below.

For orientation only — **not as an input to anything** — the expanded-TOC column works out at
`.app-main` 960 − 2x20 = 920, minus `.unit-tree`'s `flex: 0 0 14rem` = 224 (the 1px border is
*inside* that basis, since `reset.css:2` sets `box-sizing: border-box`), minus
`.unit-shell__main > .lesson` padding 2x24 = 48 → **648 px**, matching this repo's prior
figure. It is quoted to show that the harness's 568 was an artifact, and for no other purpose:
every `sizes` value comes from the protocol below.

**Required measurement.** Implementation must measure and record in the plan, **naming the
surface and DOM state for each**, since a box measured on the wrong surface is the failure
this section exists to prevent:

| # | Box | Surface and DOM state |
| --- | --- | --- |
| 1 | `.el--image--full` width | student lesson unit page, **inside `.unit-shell__main`**, TOC **expanded** |
| 2 | `.el--image--full` width | same page, `html.unit-tree-collapsed` **set** |
| 3 | `.el--image--full` width | editor preview pane (`.prev-inner`) |
| 4 | `.asset-thumb` width | media manager grid |
| 5 | `.asset-thumb` width | editor image-picker grid |
| 6 | `<td>` **content width** (not the image's) | student lesson unit page, 2-, 3- and 4-column tables |
| 7 | `.gallery__frame` width | student lesson unit page, inside `.unit-shell__main`, **both** TOC states, **after `gallery.js` has enhanced** — assert `.el--gallery.gallery--js` and the injected `.gallery__stage` are present before reading the box |
| 8 | `.dragimage__stage` width | student lesson unit page, inside `.unit-shell__main`, **both** TOC states |

Row 7's enhancement clause is load-bearing: `gallery.js:28,35-36` adds `gallery--js` and
**injects a `.gallery__stage` wrapper that does not exist in `galleryelement.html`**, after
which `.el--gallery.gallery--js .gallery__item` becomes `position: absolute; width: 100%`
(`courses.css:1657-1658`). Server-rendered and enhanced are structurally different DOMs for
the box being measured, and the geometry baseline capture can otherwise race the enhancement
and silently record whichever state won.

Naming the surface is not bookkeeping. A `.lesson` rendered *outside* `.unit-shell__main`
keeps its standalone `max-width: 46rem` (`courses.css:292`) = 736 px, while inside the shell
that cap is removed (`:660-661`) and the column is materially narrower; measuring the wrong one silently
seeds every `el-*` and `gallery` value with a number from a surface no student sees.

**Viewports.** For (1)–(3), (6) and (7)–(8): **640x800, 641x800, 900x800, 1039x800,
1040x800, 1280x720**. For (4) and (5): **the desktop case (1280x720, under `.app-main`'s
960px cap) and one narrow case near the 268px single-track supremum**.

1920x1080 is **deliberately absent** — `.app-main`'s `max-width: 960px` (`app.css:34`) caps
the lesson surface, so those boxes are provably identical at 1280 and 1920 and the second
viewport can never produce a different number. (The earlier claim that "every box scales with
window width" was false, and was the reason 1920 was chosen.)

The viewports that matter are the ones bracketing **three discontinuities**, not a scaling:

- **640/641** — `.unit-tree` is hidden below 641 (`courses.css:980`) and the lesson padding
  changes.
- **1039/1040** — this one is easy to miss: `.unit-toc-pin { flex: 0 0 2.4rem }` is revealed
  at `min-width: 641px` (`courses.css:1092-1096`), while the compensating
  `html.unit-tree-collapsed [data-unit-shell] { margin-inline-start: -2.4rem }` applies only
  at `min-width: 1040px` (`:1106`). Between 641 and 1039 those two 38.4px terms do **not**
  cancel, so the collapsed column steps at 1040. The commonly-quoted "~872" collapsed figure
  is the *cancelled* result and holds only above 1040; it is **not** derived in this spec and
  must not be assumed — measurement (2) produces it.
- **~900** — the column does not reach its cap until ~1040, so a mid-band sample is needed
  for the `sizes` middle clause below.

**Measurement conditions.** Playwright headless Chromium at DPR 1, which uses overlay
scrollbars (`document.documentElement.clientWidth` equals the viewport width). A real browser
window on Windows reserves ~15px for a classic scrollbar, which would move a 641px probe onto
the mobile side of the media query while `100vw` stayed at 641 — so the boundary probes
assume no layout-consuming scrollbar, and that assumption is recorded rather than left
implicit.

**(6) and (8) need a pinned fixture; the others do not.** Boxes (1)–(5) and (7) are
container-determined, but `.cell-img--full` is `max-width: 100%` (`courses.css:1329`), so its
used width is `min(original width, td width)`, and `.dragimage__stage` is
`display: inline-block` shrink-wrapping its image. Measure those two with a narrow asset and
the derived `sizes` under-declares for every wide one; measure with a wide asset and it
reports the container. **Both are measured with an original ≥ 2000 px wide**, so the box
reports its container-imposed cap — and (6) is read off the `<td>`, which is
container-determined, rather than off the image.

**The raise condition, stated so it cannot fork silently:** if a box **that feeds a `sizes`
value** — that is (1), (2), (3), (7) or (8), and *only* those — exceeds `WEB_WIDTH` (896) at
any named viewport, then `WEB_WIDTH` is **raised to cover it and the byte-cost table is
re-measured**.

**(4) and (5) get the symmetric rule, not a free pass.** They are excluded from the
`WEB_WIDTH` condition but they are not decorative: if either measures such that
**`thumb_box x 3 > THUMB_WIDTH`** — DPR 3, not merely DPR 2, since DPR 3 is the common phone
density and is the case the analytic argument does *not* settle — the argument is
**falsified**, and the action is the same shape: raise `THUMB_WIDTH`, re-measure the
byte-cost table, or record and accept with the magnitude stated. A mandated measurement whose
only permitted outcome is "confirms the argument" is not a check.

**(6) is explicitly excluded**, because `cell-full` consumes no derivative at all and (6) is
mandated to be taken with an original ≥ 2000 px wide; `courses.css:1305-1318` documents that
`.cell-img--full`'s `max-width: 100%` collapses out of intrinsic sizing so the image
contributes its full intrinsic width to the column, meaning (6) would report ~2000 px and the
rule as previously worded would mandate `WEB_WIDTH = 2000` and a far larger derivative set to
serve a preset that uses none. **(4) and (5) are also excluded**: they bound `THUMB_WIDTH`
under the separate, already-satisfied argument above — the ~36 MB figure and the `el-*` `sizes` values
(defined as 25/50/75/100% of the widest measured column) are all computed
from it, so they are recomputed together. The alternative — knowingly under-declaring
`sizes` — is permitted only if the author explicitly accepts it with the magnitude recorded.
Silently choosing either is what this sentence exists to prevent.

**Why no wide viewport is needed.** The lesson column does not scale with window width above
~1000px: `.app-main { max-width: 960px }` (`app.css:34`) caps it, with
`.unit-shell { max-width: 72rem }` (`courses.css:658`) and `.lesson`/`.prev-inner` at `46rem`
binding earlier still. This is recorded because under-declaration is the one direction the
omission rule cannot detect — it fires only when the asset is *narrower* than the
declaration. **Invariant: any box whose width is not capped by an ancestor `max-width` must
be re-measured at the widest supported viewport before its `sizes` value is set.**

**Rounding is upward, always.** Every derived `sizes` value and the omission threshold are
the same integer, and it is the measured maximum **rounded up** — never rounded down, never
"tidied" to a nicer number. Measured boxes are fractional (567.98, 735.98, 434.25), and
erring high is always safe because a clamp binds; erring low opens a band of asset widths
that clear the omission threshold and then render *narrower* than today, with nothing else to
catch them.

(7) and (8) are listed because
`gallery` and `dragimage` are currently assigned 896px **by analogy** with the image
element, and neither is the same box: `.dragimage__stage` is `display: inline-block;
max-width: 100%`, so its used width is the image's own contribution rather than the column,
and `.gallery__frame` is `width: 100%` of whatever the gallery's ancestor is. Their `sizes`
values are recomputed from those measurements.

**Widths:**

- **`thumb` = 512px.** `.asset-grid` is `repeat(auto-fill, minmax(8rem, 1fr))` with
  `gap: var(--space-3)` = **12px** (`editor.css:349-351`, `core/css/tokens.css:75`).
  `.asset-grid` sets no `max-width` itself, but its container does — `.app-main` is capped at
  **960px** (`core/static/core/css/app.css:34`; the editor page raises it to `102rem`,
  `editor.css:36`) — which strengthens rather than weakens the conclusion below, since the
  track never approaches the bound on the manager. With `auto-fill` and a gap `g`, the track
  count is
  `floor((container + g) / (128 + g))`, so `n = 1` persists up to `container < 256 + g = 268`
  and the track is then the full container — **under 268 CSS px**, not 256. (The gap is
  easy to drop from this derivation and changes the answer, so it is spelled out.) That needs
  536 device px at DPR 2 — but the **thumb is not the track**. `.asset-thumb` sits inside
  `.asset-cell`, which carries `padding: var(--space-2)` (8px) and a 1px border
  (`editor.css:353-357`), so the thumb is `track − 18` px: at the 268px supremum it never
  exceeds **~250 CSS px**, i.e. 500 device px at DPR 2, comfortably under `THUMB_WIDTH`.
  **DPR-2 coverage of the grid is therefore complete at every container width**, and the
  shortfall an earlier draft accepted here does not exist.

  **DPR 3 is not settled analytically and must come from measurement.** An earlier draft
  asserted a "~148px realistic track → 444 device px, also covered"; that figure had no
  provenance, conflated the *track* with the *thumb*, and does not reproduce from the CSS
  constants (at the 920px container, `n = floor(932/140) = 6` gives a 143.3px track and a
  125.3px thumb). It also sat against this spec's own measured "~180x135" thumbnail display
  size, at which DPR 3 needs 540 device px and the "covered" conclusion would be false.
  Measurements (4) and (5) settle it, and **their raise condition covers DPR 3, not only
  DPR 2**: if `thumb_box x 3 > THUMB_WIDTH` at either measured viewport, raise `THUMB_WIDTH`
  and re-measure the byte-cost table, or record and accept with the magnitude stated. Everywhere else one thumb covers every fixed-box
  preset at DPR ≤ 2 — the grid, the picker,
  `cell-small` and `cell-medium` (480 ≤ 512). **`cell-large` is not in that list** — it is a
  fluid preset under the three-strategy taxonomy, precisely because 240px at DPR 3 needs 720
  device px and the thumb does not reach it. 320px was rejected: it covers DPR 1 but leaves the
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
2. Open with Pillow. **Probe `is_animated` on the handle as opened, BEFORE any transpose**,
   and keep it in a local. Only then apply `ImageOps.exif_transpose`, binding the result to
   a *second* name.

   **This ordering is load-bearing and the obvious ordering is silently broken.**
   `ImageOps.exif_transpose` returns a new **base `Image`** (via `transpose()` or `copy()`),
   not the format subclass — so `is_animated` is not merely `False` on the result, it is
   **absent entirely**, and `getattr(transposed, "is_animated", False)` is unconditionally
   `False`. Verified against the project's Pillow 12.2.0 on a real `mat-pp` asset:
   `fibonacci_spiral.gif` opens as `GifImageFile` with `is_animated=True, n_frames=22`;
   after `exif_transpose` it is class `Image` with the attribute gone. Probing after the
   transpose would therefore flatten **every one of the 18 animated GIFs** into a static
   WebP that the grid, and student surfaces at DPR 1, would then serve — exactly the harm
   rule 4 exists to prevent. This note stays in the code, or someone will "tidy" the two
   names back into one.
3. Record `width`/`height` from the transposed image.
4. If the probe from step 2 is true → record dimensions, generate no derivatives, return
   `skipped`. Downscaling an animated GIF flattens it to one frame; the 18 animated images
   in `mat-pp` must keep animating. The check is on the animation flag, not the extension,
   so a single-frame GIF still gets derivatives.
5. **Normalise the mode before resizing.** Convert to `RGBA` when the source has alpha
   (`mode in ("RGBA", "LA", "PA")` or `"transparency" in img.info`), otherwise `RGB`.
   Load-bearing and non-obvious: `Image.resize` downgrades `resample` to `NEAREST` for
   modes `"1"` and `"P"`, silently ignoring `LANCZOS`. Verified against the project's
   Pillow 12.2.0 — `Image.new("P",(1000,800)).resize((320,256), Image.LANCZOS)` returns
   mode `P`, nearest-neighbour aliased, i.e. *worse* than the browser's own downscale.
   Measured prevalence is low — 19 of 953 are mode `P`, 18 of them animated and excluded at
   step 4, leaving one — so this is a correctness fix against future PNG-8 uploads and the
   spec's own single-frame-GIF case.
6. For each target width, skip if `img.width <= target`. The derived height is
   **`max(1, round(img.height * target / img.width))`**, and additionally the target is
   skipped if that height exceeds **16383**.

   Both bounds are real, verified against the project's Pillow 12.2.0, and both would
   otherwise land in `failed` — which the backfill **retries on every run**, forever, for a
   structurally impossible image:
   - a 3000x1 or 1200x1 source rounds to height 0 → `ValueError: height and width must be > 0`
     (wide 1–2 px rules and spacers are ordinary in imported content);
   - a 600x20000 source scales to (512, 17067) → `ValueError: encoding error 5: Image size
     exceeds WebP limit of 16383 pixels`.

   With the clamp and the cap these become ordinary `skipped` outcomes — a **fifth** skipped
   route — rather than permanent retry-forever failures. Note the 1200x1 case also shows why
   the per-target decision matters: `(896, 1)` encodes fine at 38 bytes, so a single guard
   around both targets would have discarded a working derivative along with the impossible one.
7. **Encode to an in-memory buffer first.** The target size is
   `(target, round(img.height * target / img.width))` — Python's banker's rounding, matching
   the 1100x841 → 896x685 worked example that the ±1 px geometry tolerance is derived from.
   Resample with `Image.LANCZOS`, save into a
   `BytesIO` with the pinned kwargs, then compare **`len(buffer.getvalue())`** against
   **`asset.file.size`** (the original's bytes on disk, not the decoded bitmap). Only if the
   buffer is smaller does a **`FieldFile.save(name, ContentFile(buffer.getvalue()), save=False)`**
   happen.

   Both `getvalue()` calls are deliberate. `ContentFile(buffer)` — passing the `BytesIO`
   itself — **raises `TypeError: a bytes-like object is required, not '_io.BytesIO'`**,
   verified against the project's Django; since this is the only place a derivative is
   written, that form would fail on every call. And sizing via `len(getvalue())` rather than
   `buffer.tell()` removes the ordering trap where an intervening `seek(0)` makes `tell()`
   return 0 and every derivative look infinitely small. Encoding straight to storage and "discarding" by blanking the field would leave
   orphaned bytes and burn a collision-suffix slot against the `max_length=200` budget for
   every discarded derivative — expected among the 25 JPEG/GIF/WebP originals, where a
   lossless-WebP derivative can exceed a photographic JPEG's size.
8. Return `ok` if anything was written, `skipped` if steps 6–7 declined both.
9. **The entire body — decode, resize, encode, and both storage writes — sits inside one
   guard catching broad `Exception`, logging, and returning `failed`.** Not a fixed tuple
   of Pillow exceptions: the riskiest step is `FieldFile.save(...)`, a storage write that
   can raise `SuspiciousFileOperation`, permission or quota errors, or backend-specific
   exceptions. **The handler must delete any derivative file it already wrote during this
   call — tracking written names locally — AND then re-blank `asset.thumb` / `asset.web`
   and null `width`/`height` itself.**

   **It cannot rely on rule 0 for that, and this is the subtle part.** Rule 0 runs before
   step 7, and `FieldFile.save(name, content, save=False)` ends by writing the name back
   onto the instance (`setattr(self.instance, self.field.attname, name)`), so a successful
   `thumb` write **re-populates** `asset.thumb` after rule 0 cleared it. Without an explicit
   re-blank, a successful `thumb` followed by a raising `web` leaves the field non-blank
   while the handler has just deleted the bytes — and the caller then persists that field
   through `update_fields`. That is the "non-blank field pointing at absent bytes" state the
   Error-handling section names as its one honest limit, reached from a **fourth** path. In
   `replace_asset` it compounds in the opposite direction to the naive reading: step 6
   compares the *populated* new name against `old_thumb_name`, finds them different, and
   deletes the surviving old file too.

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

- `asset` — a **real `MediaAsset`** (or `None`). This list is the fixture spec, so it is
  exhaustive: the tag reads `.file.name`, `.file.url`, `.kind`, `.width`, `.height`,
  `.thumb` + `.thumb.url`, and `.web` + `.web.url`. **Duck-typed fixtures are therefore no
  longer viable** — a breaking change for existing tests, not an assertion update; see
  "Existing test fixtures" below. `.height` null while `.width` is not is treated the same
  as `.width is None` (plain `src`, no `srcset`, no attributes): the two are written together
  by rule 3 and a half-populated pair means the row predates or failed generation.
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

| Site | `css_class` | `extra` | `alt` |
| --- | --- | --- | --- |
| `_asset_cell.html:7` | `asset-thumb` | `data-asset-preview` | `""` (decorative) |
| `_picker_grid.html:6` | `asset-thumb` | *(none)* | `""` (decorative) |
| `imageelement.html:2` | *(none)* | `data-zoomable` | `el.alt` |
| `_table_cell.html:1` | `cell-img cell-img--{size}` | `data-zoomable` | `cell.alt` |
| `_filltable_cell.html:1` | `filltable__img cell-img cell-img--{size}` | `data-zoomable` | `cell.alt` |
| `dragtoimagequestionelement.html:9,32` | `dragimage__img` | *(none)* | `el.alt` |
| `galleryelement.html:14` | *(none)* | `data-zoomable` | `f.alt` |

**`alt` is part of the contract, not a nicety.** All eight current tags carry one, and the
tag defaults to `""` — so a conversion that simply omits `alt=` on an element site silently
blanks author-supplied alt text on a student surface, with nothing to notice it. It
compounds: `imagezoom.js:92` (`armOne`) falls back to a generic aria-label when the trimmed
alt is empty, so a blanked alt also converts a described image into an unlabelled "Enlarge
image" button. A test asserts each converted template round-trips its alt expression,
including the two decorative empty-alt grids.

#### Presets composed from data

All three composed sites use the **same inline `{% with %}` + `|default:` shape**, for
symmetry and because the failure mode below is identical:

- `imageelement.html` — `{% with sz=el.size|default:"full" %}{% media_img el.media preset="el-"|add:sz ... %}{% endwith %}`.
  **The `{% with %}` wraps the `<img>` line only; line 1 is untouched.** Line 1 is
  `class="el el--image el--image--{{ el.size }}"` with no `|default:`, so on a `size`-less
  context the figure keeps rendering `el--image--` while the tag is told `el-full`. Those
  agree geometrically (a class-less figure has no cap, matching `el-full`'s `sizes`) but
  differ on `max-height` (`el--image--` has none, `el--image--full` has `100dvh`). Extending
  the `{% with %}` over line 1 would look like a tidy-up and would silently change rendered
  bytes on that context, so the boundary is stated rather than left to judgement.
- `_table_cell.html` and `_filltable_cell.html` —
  `{% with sz=cell.size|default:"full" %}{% media_img cell.media preset="cell-"|add:sz ... %}{% endwith %}`

**The failure mode for a missing `size` is `VariableDoesNotExist`, not the tag's
unknown-preset raise.** Verified against the project's Django: a missing lookup in a filter
**argument** position is not substituted with `string_if_invalid` — `FilterExpression`
catches `VariableDoesNotExist` only for the *head* variable — so
`preset="el-"|add:el.size` on an `el` without `size` raises
`VariableDoesNotExist: Failed lookup for key [size]` and never reaches the tag. The composed
`"el-"` string is never produced. The `{% with %}` form is safe for the opposite reason:
there `el.size` *is* the head variable, so `|default:` fires (verified: renders `cell-full`
on a `size`-less context). Without this, `imageelement.html` would be the one conversion that
hard-errors on a `size`-less context — which is exactly the shape
`tests/test_imagezoom_render.py:52` uses.

**The existing `|default:'full'` is RETAINED, and must be applied *before* the prefix.**
`TableElement._cell` (`models.py:1148-1152`) documents that `size` is always written for
elements rendered through `render()`, which makes the default look vestigial — but it is
**live at the partial level**, and a deliberate existing test pins it:
`tests/test_table_render.py:99-119`
(`test_partial_defaults_size_when_the_key_is_absent`) renders `_table_cell.html` directly
with `{"cell": {"kind": "image", "media": asset, "alt": ""}}` — **no `size` key** — and
asserts `cell-img--full`. Its docstring states outright that the filter cannot be falsified
through `el.render()` and that the partial-level context is the only place it is live.

Dropping it would turn that test from a failed assertion into a hard **error** — though not
the one it first appears. The render raises `VariableDoesNotExist: Failed lookup for key
[size]` from the filter-argument position, *before* the tag is called, so the composed
`"cell-"` preset is never produced and the tag's unknown-preset raise never fires. A test
written to expect the latter would assert the wrong exception. The correct form uses a
`{% with %}` so the default lands on the size before concatenation, where it is the head
variable and `|default:` can fire:

```
{% with sz=cell.size|default:"full" %}{% media_img cell.media preset="cell-"|add:sz css_class="cell-img cell-img--"|add:sz ... %}{% endwith %}
```

**Written entirely inline, with no newline or indentation between the tags** — the expanded
three-line form would inject `\n  ` before the `<img>` and `\n` after it, *inside the
`<td>`*. `tableelement.html:25-40` wraps its includes in `{% spaceless %}` so
`_table_cell.html` would survive, but `filltableelement.html` has **no `{% spaceless %}` at
all** — a fact `tableelement.html:19-21` states outright — so every fill-table image cell
would change bytes. The existing byte-guard (`test_table_render.py:122`) covers only a *text*
cell, so nothing would catch it.

What must **not** happen is the naive carry-across `"cell-"|add:cell.size|default:"full"`,
which applies `default` to the already-concatenated string — non-empty, so it never fires —
producing exactly the unknown preset that raises on a student lesson page.

**An unknown preset raises at render time**, and a test pins that this is unreachable from
stored data: **for every `v` in `ImageElement.Size.values`, `f"el-{v}"` is a preset key; for
every `v` in `TableElement.CellImageSize.values`, `f"cell-{v}"` is a preset key.** (Stated
per-value deliberately — the preset keys are prefixed, so the raw key set is *not* literally
a superset of `{"small","medium","large","full"}`, and a test written from that looser
wording would fail and then be weakened.)

#### `src`, `srcset`, and the two strategies

**`src` is always emitted. There are three strategies, not two** — the third exists because
`cell-full` must not be classified as fixed-box by its `cell-` prefix:

- **Fixed-box presets (`grid`, `cell-small`, `cell-medium`):** `src` = **`thumb`**, falling
  back to the original when `thumb` is blank. No `srcset` at all. The 512px thumb covers
  these boxes at DPR ≤ 3, so there is no second candidate worth offering, and this guarantees
  the derivative is what actually loads.
- **Fluid presets (`el-*`, `gallery`, `dragimage`, and `cell-large`):** `src` = **the
  original**, plus a `w`-descriptor `srcset` and `sizes`. When `srcset` uses `w` descriptors
  the browser ignores `src` for selection, so `src` only serves a client that does not
  understand `srcset`, which should get full quality.
- **Original-only preset (`cell-full`):** `src` = **the original**, no `srcset`, no `sizes`.
  Emitting the thumb there was measured to move the `<td>` from 580.28 to 574.25 px on every
  existing table — see the auto-layout table measurement below.

**Why `cell-large` is fluid despite being a fixed 240px box.** At DPR 3 — the common phone
density — a 240px box needs 720 device px, and the 512px thumb is only 0.71x of that. Those
cells serve the ~1100px original today, so a thumb-only strategy would be a *quality
regression* on exactly the thin-stroke maths diagrams this design is built to protect.
`cell-medium` (480 ≤ 512) and `cell-small` (240 ≤ 512) stay covered, and the grid's realistic
track (~148px under `.app-main`'s 960px cap → 444 device px) stays covered, so `cell-large`
is the only fixed box needing the escape hatch. Giving it `sizes="240px"` was A/B measured at
DPR 1 **and** 3, landscape and portrait (1100x841, 400x1200, 508x1486): **no box moved**.

| Preset | CSS box | Strategy |
| --- | --- | --- |
| `grid` | `.asset-thumb` (analytically ≤ ~250px; track < 268px — see Derivative widths) | `src` = thumb, no `srcset` |
| `cell-small` | `.cell-img--small` (80px both axes) | `src` = thumb, no `srcset` |
| `cell-medium` | `.cell-img--medium` (160px both axes) | `src` = thumb, no `srcset` |
| `cell-large` | `.cell-img--large` (240px both axes) | `w` + `sizes="240px"` — DPR-3 coverage, see above |
| `cell-full` | `.cell-img--full` (100% of its `<td>`, `max-height: 60dvh`) | **`src` = original, no `srcset`** — auto-layout table, see below |
| `el-small` | `.el--image--small` (25%, `max-height: 30dvh`) | `w` + three-clause `sizes`, all from measurement |
| `el-medium` | `.el--image--medium` (50%, `max-height: 45dvh`) | `w` + three-clause `sizes`, all from measurement |
| `el-large` | `.el--image--large` (75%, `max-height: 60dvh`) | `w` + three-clause `sizes`, all from measurement |
| `el-full` | `.el--image--full` (`max-height: 100dvh`) | `w` + three-clause `sizes`, all from measurement |
| `gallery` | `.gallery__frame` (100%, `aspect-ratio: 4/3`, `max-height: 70vh`) | `w` + `sizes` from measurement (7) |
| `dragimage` | `.dragimage__img` (`.dragimage__stage` is inline-block) | `w` + `sizes` from measurement (8) |

**Single source for the `el-*` values, stated once here and nowhere else:** each is
`25/50/75/100%` of **`max(measurement 1, measurement 2, measurement 3)`, rounded up** — the
widest the box reaches across every named surface, DOM state and viewport. (`.el--image--small
/medium/large` really are `max-width: 25/50/75%` of the lesson content box,
`courses.css:61-63`, so the percentage derivation is exact.) Taking the expanded column alone
would under-declare by the full expanded-to-collapsed delta for every user with the persisted collapsed-TOC toggle on, and
acceptance criterion 2 cannot catch it — both 648 and 872 select the `web` derivative at
DPR 1. The values must be
recomputed once measurements (1)–(3) are taken; the values shown assume 896.

**The `srcset` candidate list, literally.** For `w`-descriptor (fluid) presets:

```
srcset="{thumb.url} 512w, {web.url} 896w, {file.url} {asset.width}w"
```

Each derivative appears only when its field is non-blank; the original appears only when
`asset.width` is known. Order is ascending by width.

**Invariant: a non-blank `web` implies a non-blank `thumb`**, which is why "`src` = thumb,
falling back to the original" is exhaustive for fixed-box presets — there is no state with
`web` present and `thumb` absent. Three rules could break it and none does:

- **Rule 6** (width skip): 896 > 512, so anything wide enough for `web` is wide enough for
  `thumb`.
- **Rule 7** (discard-if-not-smaller): a 512px lossless WebP is never larger than the 896px
  one of the same source, so if the thumb was discarded for exceeding `asset.file.size`, the
  web candidate was too. This monotonicity is the load-bearing half and is stated because it
  is not obvious.
- **Rule 9** (failure handler): it re-blanks **both** fields, never one — see rule 9.

**`srcset` and `sizes` are omitted entirely whenever no derivative exists** — i.e. whenever
the only available candidate would be the original. This covers the animated GIF, the
`failed` row, and every original narrower than both targets. It is not merely tidiness:
see the `sizes` upscale rule below.

**`cell-full` gets NO derivative at all: `src` = the original, no `srcset`, no `sizes`.**

This is the one preset where the change cannot be made without moving layout, and it was
settled by measurement rather than argument. `.cell-img--full` sits in an **auto-layout**
table, so the `<td>`'s width is derived from the image's max-content contribution — i.e.
from its intrinsic width. Anything that changes the intrinsic width moves the column.
Measured, a 1100x841 image in a 3-column table at 1280x720:

| Strategy | Image box | `<td>` width |
| --- | --- | --- |
| today (plain `src` = original) | 565.03 x 432 | 580.28 |
| `w` `srcset` + `sizes="213px"` | 212.98 x 162.84 | **498.72** |
| `src` = 512px thumb | 512 x 391 | **574.25** |

Both alternatives move the column, in opposite directions. Note this is the **shrink**
direction — the spec's whole upscale analysis is about `sizes` being *larger* than the
content, and `cell-full` fails the other way, so neither the omission rule nor anything else
here protects it.

The cost is explicit: full-width table-cell images keep serving originals. It is bounded —
`cell-small/medium/large` (80/160/240px) are the common table sizes and they do get the
thumb — and the alternative is a measured table-layout change on every existing table, which
the Goal forbids. Recorded as a follow-up: fixing this properly needs `table-layout: fixed`
or explicit column widths, which is a separate change with its own review.

Measurement (6) is retained for the record but no longer feeds a `sizes` value.

**The two remaining measurement-derived presets (`gallery`, `dragimage`) carry a
`(max-width: 640px) NNvw` clause, exactly as the `el-*` rows do** — not bare px values. A
bare px `sizes` at the widest desktop column over-declares a gallery frame on a 360 px phone by roughly 2.5x, so the
browser demands 872 device px and selects `web` (or the original) for **every** carousel
figure, on the surface where bandwidth matters most and where the gallery renders N images at
once.

**The mobile clause is derived from the 640px end of its own range, never the 360px end**,
and it comes from a **measurement**, not a formula. Below 640 the container is
`viewport − (constant)`, so the box-to-viewport ratio *increases* with viewport width across
the range; a clause fitted at 360 under-declares at 640, and under-declaration is precisely
the direction the omission rule cannot detect.

**No `calc()` formula is prescribed here, deliberately.** An earlier draft prescribed
`calc(100vw - 72px)` and called it exact. It was wrong by 34 px on the gallery, because the
hand-derivation missed two rules: `.app-main`'s padding is overridden to
`var(--space-5) var(--space-4)` — 16 px horizontal, not 20 — inside
`@media (max-width: 640px)` (`app.css:262`), and `.gallery__item` adds
`padding: var(--space-5)` plus a 1 px border (`courses.css:1628-1633`). That is the same
failure as the harness figures: a derivation that misses one rule, stated as surface truth,
in the one place telling the implementer to trust arithmetic over the protocol.

**So the mobile clause is read off measurements (7) and (8) taken at 640x800**, rounded up,
exactly like every other `sizes` value. If a `calc()` form is preferred for exactness across
the range, it must be *fitted to those measurements* and cite every rule it is composed
from — never derived from the stylesheet by inspection.

#### A middle clause is required for 641–1039px

A two-clause `sizes` applies the desktop value at every viewport above 640, but the column
does not reach its cap until ~1040 (the `.unit-toc-pin` / negative-margin discontinuity
above). In that band the real box is a fraction of what the desktop clause declares — the
over-declaration there is *larger* than the ~2.5x this spec calls unacceptable on phones, and
it covers the entire small-laptop and tablet range, so every fluid-preset image in it fetches
`web` or the original.

**Every fluid preset therefore carries three clauses:**

```
sizes="(max-width: 640px) <from the 640 measurement>,
       (max-width: 1039px) <see below — NOT the 900 measurement alone>,
       <from the widest measurement>"
```

**The middle clause must not be a bare px value taken from the 900px measurement**, for two
reasons that pull in opposite directions and together force a `vw`/`calc()` form:

- **Sourcing it at 900 under-declares.** The clause covers 641–1039, and the box is widest at
  the *top* of that band. `.app-main`'s inner width is `min(vw, 960) − 40`, so the expanded
  column is `860 − 224 − 48 = 588` at vw=900 but `920 − 224 − 48 = 648` at vw=1039
  (collapsed: 773.6 → 833.6). A clause fitted at 900 under-declares by ~60px — the direction
  this spec says nothing can detect, and a direct violation of "every derived `sizes` value is
  the measured maximum rounded up". **The 1039 measurement is what the upper end of this
  clause is fitted to**; it is not there merely to bracket the discontinuity.
- **A bare px value at 1039 then over-declares at the bottom.** The expanded column at vw=641
  is `601 − 224 − 48 = 329`, so declaring 833.6 across the band is a **2.53x**
  over-declaration — indistinguishable from the ~2.5x that this spec cites as the reason a
  bare px *mobile* clause is unacceptable. It would defeat the purpose the clause was added
  for across the lower half of its own range.

**So the middle clause is a `vw` or `calc()` form fitted to BOTH the 641 and 1039
measurements**, citing every rule it composes — the same requirement already placed on the
mobile clause. If implementation finds that impractical and falls back to a bare px value,
the residual over-fetch at 641 must be recorded with its measured magnitude rather than
discovered later and improvised around.

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
- **`asset.kind != "image"` → render nothing.** Stated because `.kind` is in the tag's read
  set and would otherwise have no rule: without it, one implementer renders nothing and
  another emits `<img src="…mp4">`. It is a live question rather than hypothetical —
  `_asset_cell.html:7` guards with `{% if asset.kind == "image" %}` in the template, while
  `imageelement.html` and `galleryelement.html` rely on the model's `limit_choices_to`, so
  where the guard lives differs per site. A test covers it.
- `asset.width is None` → emit a plain `src` with **no** `srcset`. **This rule dominates**
  the candidate-list clause above, which says the original appears "only when `asset.width`
  is known" and could be read as permitting a derivatives-only `srcset` here. It cannot: no
  `srcset` at all. (The state is unreachable in practice — rule 3 records dimensions before
  any derivative is written — but the two sentences would otherwise prescribe different
  code.)

These guards are only reachable on the six element-template sites. `_asset_cell.html:3` and
`_picker_grid.html:5` both emit `data-url="{{ asset.file.url }}"` on the wrapper *before*
the `<img>`, so a blank-file asset 500s those pages before the tag is reached. Those two
`data-url` attributes are left as they are — pre-existing behaviour, out of scope — and the
guard's tests must therefore target an element template.

### Layout invariants

#### The `sizes` upscale, and the single rule that prevents it

With `w` descriptors, an `<img>` whose CSS `width` is `auto` takes its **density-corrected
intrinsic size**, which equals the declared `sizes` width — *not* the selected resource's
pixel width. Every fluid-preset box has no author width: `.el--image img` is only
`max-width: 100%; height: auto`; `.el--image--small/medium/large` put `width: fit-content`
on the **figure**; `.el--image--full` has no cap; `.dragimage__stage` is
`display: inline-block` shrink-wrapping the image. (`.cell-img--full` is **not** in this
list: `cell-full` emits no `sizes`, so the density-correction mechanism cannot reach it — it
is handled separately for the auto-layout table reason below.)

So a 200px-wide original carrying `sizes="…896px"` would render at 896 CSS px — a 4.5x
upscale where today it renders at 200px.

**One rule prevents it: `srcset`/`sizes` are omitted whenever `asset.width` is at most the
preset's declared desktop `sizes` width.**

**The two checks are independent — the width comparison does NOT subsume the no-derivative
check, and both must be implemented.** The subsumption argument would need "narrower than
both targets ⇒ narrower than any `sizes` width", and that is false: `cell-large` declares
`sizes="240px"`, which is *below* `THUMB_WIDTH` (512). A 400 px original is narrower than
both targets (so no derivative exists) yet wider than 240, so the width comparison does not
fire and only the no-derivative check catches it. Both mutants in the falsification list are
therefore live, and neither check may be dropped as redundant.

Beyond these two there is no further protection — the `width`/`height`
attributes that used to be the second one are gone, for the reasons measured below.

#### No `width`/`height` attributes are emitted, anywhere

This was tried and **measured to be unsafe on every preset**. Two independent failures:

**(a) `aspect-ratio` is discarded once both axes are definite.** It applies only while one
axis is `auto`; a `height` attribute supplies a definite height. Measured in Chromium
against the real rules (`.asset-grid` + `.asset-thumb` + the reset), 700px container:

| `.asset-thumb` | Box |
| --- | --- |
| **with** `width="1100" height="841"` | 130.4 x **841.0** |
| **without** | 130.4 x 97.8 |

8.6x taller, on ~950 cells across the manager and picker.

**(b) `height: auto` does not save the other presets either — nothing neutralises the
*width* hint.** With a definite width, a binding `max-height` clamps height *independently*
and the ratio breaks. This is invisible on landscape sources, which is why it survived
several rounds of reasoning; it appears on **portrait** ones. Measured at 1280x720 against
the real CSS:

| Preset, source | No attributes | With attributes |
| --- | --- | --- |
| `el-full` 508x1486 (a real `mat-pp` asset) | 246.12 x 720 | **508 x 720** |
| `el-large` 400x1200 | 144 x 432 | **400 x 432** |
| `el-small` 400x1200 | 72 x 216 | **162 x 216** |
| `cell-small` 400x1200 | 26.66 x 80 | **80 x 80** |
| `cell-large` 400x1200 | 80 x 240 | **240 x 240** |
| `el-full` 1100x841 (landscape) | 567.98 x 434.25 | 567.98 x 434.25 |

Every `el-*` and `cell-*` preset carries a `max-height` (30/45/60/100dvh, 80/160/240px,
60dvh), so every one of them is affected. These are 100–260 px violations of a ±1 px Goal on
the primary student surface, and they fire on the **fallback path too** — the attributes need
only `asset.width`, so they would land on every image the moment the backfill records
dimensions, derivative or not.

**The replacement is the omission rule alone, and it is measured to move nothing.** Density
correction scales *both* axes, so with both axes `auto` the intrinsic **ratio** is invariant;
the only box that can move is one where neither clamp binds, which is exactly what the
omission rule excludes. A/B measured, today (plain `src`) vs proposed (`w`-descriptor
`srcset` + `sizes`, no attributes), across landscape and portrait at every preset —
`el-full` 1100x841 and 508x1486, `el-large` 1100x841 and 400x1200, `el-small` 1100x841 and
2000x900, `cell-small` 1100x841: **zero boxes moved**.

Consequences to carry: no `width`/`height` means no reflow reservation, which the spec never
claimed on the grid (`.asset-thumb`'s `aspect-ratio` already reserves it) and now claims
nowhere; and the `height: auto` audit below becomes descriptive only, since no rule depends
on it.

(Under the **rejected** attribute design, a reflow benefit would have applied to
`.el--image`, `.cell-img*` and `.dragimage__img`, and not to the grid, whose box
`.asset-thumb` already reserves via `aspect-ratio: 4 / 3` (`editor.css:360-365`). Recorded in
the past tense deliberately: no preset emits dimension attributes, so this benefit is
delivered nowhere, and the sentence must not read as licence to re-add them on those three
selectors — which is exactly what the 508x1486 → 508x720 measurement forbids.)

#### The gallery

`.el--gallery .gallery__frame img` (`courses.css:1647`) is
`max-width: 100%; max-height: 100%; object-fit: contain` with **no `height: auto`**, sized by
its frame's `aspect-ratio: 4/3`. It was the first preset where the attribute hazard was
found — the two `max-*` clamps stop being ratio-preserving once dimension hints make both
axes definite, moving the element box ~14px in a 736px frame — and it turned out to
generalise to every preset (above).

Since no preset emits `width`/`height`, the gallery needs no special case beyond the general
omission rule. It is still the preset where that rule's *test* matters most, because
`.gallery__frame` is `aspect-ratio: 4/3` with `max-height: 70vh` — a shape that hides the
defect unless the fixture is chosen deliberately.

**The omission rule is general, not gallery-only** (it began as a gallery special case and
was generalised once `width`/`height` were dropped): on **every fluid preset**, `srcset` and
`sizes` are omitted whenever `asset.width` is at most the preset's declared `sizes` width,
falling back to a plain `src` on the original. This is the sole upscale protection.

"The declared `sizes` width" means **the largest width any `sizes` clause can resolve to at
the named measurement viewports** — the widest desktop px value, not the mobile or middle
clause. The two readings give different behaviour for the same fixture, and the mandated
gallery band test is precisely where they diverge.

**Consequence for where the band tests run:** because the threshold is pinned to the widest
case, the omission rule is *inert by construction* at narrow viewports — at 641px an `el-full`
box is a fraction of the declared width, so every band asset keeps its `srcset` there and the
density-corrected width is clamped back down by `max-width: 100%`. Layout-safe, but it means
a band test written at 641px is **green on the width-comparison mutant**. The band fixtures
and that mutant are therefore asserted at **the viewport and DOM state where the preset's box
is widest** — 1280x720 with `html.unit-tree-collapsed` for the `el-*` presets — and the plan
states that viewport explicitly per fixture.

The geometry suite must include a gallery asset with an original **in the 513–895 px band**
— an explicit, named exception to the "> 896 px fixture" rule below, which would otherwise
structurally exclude the band where this defect is observable.

**The fixture's shape is pinned too, not just its width.** The box only moves when the
density-corrected intrinsic size fits inside the frame in **both** axes, so a 4:3 asset — the
natural choice for a 4:3 frame — produces an unfalsifiable test. Demonstrated in the harness
(frame 736x504 there): a **700x525** band asset rendered 672x504 both with and without the
omission rule, i.e. green on the broken build, while a **560x300** asset moved and was red.

**The rule, not those numbers, is what carries over:** the fixture must be smaller than the
frame **in both axes** at the measurement viewport, and comfortably so. The concrete
dimensions are re-derived from measurement (7) on the real surface — the harness frame was
the standalone `46rem` gallery, not the in-shell one, so 560x300 is illustrative of the
*shape* requirement and not a value to copy.

#### `height: auto` audit

`.el--image img` (`courses.css:46`), `.cell-img` (`:1325`) and `.dragimage__img` (`:538`)
declare `height: auto`. `.gallery__frame img` (`:1647`) does not, and is handled above. No
CSS is changed. The invariant, stated to match reality: *every preset's CSS declares
`height: auto`, an explicit `aspect-ratio`, or an ancestor `aspect-ratio` together with
`object-fit`.*

**This invariant is now descriptive, not load-bearing.** It described which presets could
safely take dimension attributes, and no preset takes them. It is retained because it
documents a real property of the stylesheet worth not breaking, but nothing in this design
depends on it — the assertion that matters is that **no `<img>` the tag emits carries
`width` or `height`**, which is a single unconditional test.

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
- `imagezoom.js` reads a new **`data-zoom-src="{{ asset.file.url }}"`** emitted by the tag,
  falling back to `currentSrc || src` when absent so non-tag `<img data-zoomable>` markup
  keeps working. On fluid presets this is deliberately the same URL as `src` — the attribute
  is not redundant there, because once `srcset` is present `currentSrc` diverges from `src`,
  and `currentSrc` is what the old code read.

Three second-order consequences, handled in the same commit:

- `media_preview.js:172` is `if (!src || (anchor.complete && anchor.naturalWidth === 0))` —
  **two conditions, and only the second moves.** The `complete && naturalWidth === 0` branch
  interrogates the *thumb* after the repoint, while a different URL is loading, so a broken
  original would yield a silently empty overlay; that branch moves to the overlay image's
  own `error` handler, which **does** already exist (`:54-58`). The `!src` branch is
  **retained**, now testing the `data-url` read, because its own in-file comment states why
  it cannot be delegated: assigning `""` does not reliably fire `error` and can leave the
  *previous* asset's image showing in the overlay.

  **It is retained as defence only** — after the repoint `src` comes from
  `_asset_cell.html:3`'s `data-url` (`{{ asset.file.url }}`), which is never empty, since a
  blank-file asset 500s that page before the `<img>` is reached. Consequence for the existing
  suite: `tests/test_e2e_media_manager.py:1226-1237`,
  `test_a_thumbnail_that_never_loaded_shows_the_caption_only`, keeps passing **for a
  different reason** — its `page.route(…, abort)` also kills the overlay's own fetch, so it
  now exercises the `error` handler and duplicates
  `test_a_404_source_shows_the_caption_and_no_image_box` (`:1200`). That is the same
  "passes while silently measuring another path" hazard flagged for `test_table_render.py:94`.
  The plan either rewrites it to drive the genuinely-empty case (stripping `data-url` by page
  evaluation) or merges it into the 404 test with the reason recorded.
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

  **This new UI has four constraints the spec must carry, because it is the only
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
  4. **Reset on close.** The existing `close` handler (`imagezoom.js:54-65`) resets exactly
     three things: `dialogImg.removeAttribute("src")`, focus restore, and the
     `imgzoom-open` class. The new loading indicator, error element and `expectedSrc` guard
     are additional visible state that nothing currently clears — so opening a broken image,
     closing, then opening a good one would leave the previous error message painted until
     (or unless) `load` fires. The `close` handler, or the top of `openOverlay`, must reset
     all of it to a defined initial value, with a test that a failed open followed by a
     successful one shows no residual error.

  A **third** source-level invariant applies alongside the two above:
  `test_overlay_image_can_only_shrink` (same file) slices `courses.css` from the first
  occurrence of `.imgzoom-trigger` **to end of file** and asserts `"100vw" not in block`.
  Any loading- or error-state rule added after that anchor must therefore avoid `100vw` — a
  natural choice for a full-bleed overlay or spinner, and so a likely accident.

**An existing e2e asserts the exact equality this repoint must break.**
`tests/test_e2e_media_manager.py:866-890`,
`test_hover_opens_the_overlay_with_the_thumbnails_source`, evaluates
`img.currentSrc === thumb.currentSrc` over `[data-asset-preview-img]` and
`[data-asset-preview]` and asserts it. Its fixture is `("wide_0_1.png", (800, 200))`, and it **must be
re-created with `derivatives=True`** — width alone generates nothing, since
`make_image_asset` never routes through `create_asset`. That is the same dimensional
inference this spec declares false elsewhere, and it matters here more than usually: if the
fixture stays on the fallback path, the *inverted* assertion ("overlay `currentSrc` differs
from the thumb's") is **false on a correct build** — a test that is red on green. The
mechanical `derivatives=True` rule below is stated for four assertion classes; it extends to
**any assertion that depends on a derivative existing**, of which this is one. After `_asset_cell.html`
converts, the thumb's `currentSrc` is the derivative and the overlay's is the original, so
the assertion is false **by construction**; the test's name encodes the contract being
deliberately reversed.

It must be inverted: renamed, and asserting that the overlay's `currentSrc` equals the cell's
`data-url` and **differs** from the thumb's `currentSrc`. **The inverted assertion lands in
the template-conversion commit, not the JS commit** — through the JS commit the thumb `src`
is still the original, so the old assertion stays green there and the ordering rule below
does not surface it. Called out here so it is a planned step rather than a mid-task surprise
in a commit whose diff contains no JavaScript.

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

1. Capture `old_name` (the original's, already a local in the current function),
   `old_thumb_name`, `old_web_name`, and **two storages** — the original's
   (`asset.file.storage`, also already a local) and the shared derivative storage
   (`asset.thumb.storage`) — **before** reassigning.
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

**It also deletes the newly written original — through a different function.** Because
`generate_derivatives` never raises, the only real raiser inside the `try` is **step 5's
`asset.save(update_fields=[…])` — a DB write this change introduces**; today's
`replace_asset` has no DB write after step 3. When step 5 raises, `@transaction.atomic`
rolls the row back to the old file, but the *new* original's bytes were already written to
storage at step 3 and nothing references them.

The handler must therefore also delete `asset.file.name` when it differs from the captured
`old_name`. **It must NOT reuse `_delete_file_if_unshared` for this**, which would be a
guaranteed no-op for two independent reasons, both readable at `courses/media.py:128-147`:

1. It ends in `transaction.on_commit(_remove)`. The deferral table above says of this exact
   caller: *immediate* — a callback registered on a transaction that is about to roll back
   never runs.
2. Even ignoring deferral, it early-returns on
   `if MediaAsset.objects.filter(file=name).exists()`. By handler time, step 3 has already
   written `file=<new name>` on this row inside the still-open transaction, so that query
   sees the row's **own uncommitted write**, returns `True`, and the helper returns before
   scheduling anything.

The share concern is still real — the original is the one object that *can* be shared
between rows (the migration-`0008` shape), unlike derivatives. So the handler performs an
**immediate, un-deferred delete with a share check that excludes the failing row**:
`MediaAsset.objects.filter(file=new_name).exclude(pk=asset.pk).exists()` → if false,
`storage.delete(new_name)` inline. Excluding `asset.pk` is what makes the guard answer the
question actually being asked — "does any *other* live row point at these bytes?" — rather
than being answered by the row being rolled back.

**Position of the other three creation sites**, so this section is exhaustive rather than
apparently so:

- **`create_asset` under `media_upload`** — `create_asset` is not itself
  `@transaction.atomic`; the view is not wrapped either, and `ATOMIC_REQUESTS` is not
  enabled. If the five-field save raises after `generate_derivatives` wrote both files, the
  **bytes are orphaned but the row survives** with `thumb`/`web` blank (rule 0 cleared them,
  the save never landed) — the row's existence does not make the bytes reachable. No
  automatic cleanup is prescribed because the surviving row makes them recoverable with
  `backfill_media_derivatives --force`, which is the existing remedy.
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
`delete_derivative_files([instance.thumb.name, instance.web.name], instance.thumb.storage)`,
wrapped by the caller in the same `transaction.on_commit`.

**Two details the placement depends on.** The receiver's first two statements are
`file = instance.file` / `if not file: return` (`courses/signals.py:22-24`), so an asset with
a blank `file` returns before any derivative cleanup could run. That early return is
**deliberately kept**: a derivative cannot exist without an original, since generation reads
`asset.file`, so there is nothing to clean up on that path. And the storage passed is
`instance.thumb.storage` — the *derivative* fields' storage, which is a different field's
storage from `instance.file.storage` even though both currently resolve to the default
backend. It is available on a blank `FieldFile`, so reading it is safe regardless. `post_delete` — rather than `Model.delete()` — remains correct: a cascade delete
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
404. Four code paths could delete a live row's current derivative, and each is guarded:
`replace_asset` step 6, the `replace_asset` failure handler, and backfill `--force` by the
`!=` comparison; and **`generate_derivatives`' own rule-9 handler by its explicit re-blank**
(without which `FieldFile.save`'s write-back would leave the field pointing at bytes the
handler just deleted).

| Condition | Behaviour |
| --- | --- |
| Pillow or storage raises anywhere in generation | Log; fields cleared by rule 0; **any file already written this call is deleted**; state `failed`; original served |
| Not an image / animated | Fields cleared, dimensions recorded where known, state `skipped`; original served, animation intact |
| Palette (`P`) / `1` mode source | Converted to `RGB`/`RGBA` before resize, so `LANCZOS` is honoured |
| Original narrower than a target width | That derivative skipped |
| Derivative encodes no smaller than the source | Buffer discarded before any storage write |
| `asset is None`, blank `file.name`, or `kind != "image"` | Tag renders nothing — all **three** guards (never `asset.file.url`, which raises `ValueError`) |
| `width`/`height` unknown (null) | Tag omits `srcset` and emits a plain `src` |
| No derivative exists | `srcset` and `sizes` omitted entirely — required, not tidiness (see the `sizes` upscale rule) |
| Unknown preset | Raises at render time; unreachable from stored data by the per-value rule |
| Backfill hits a bad row | Logged, counted, run continues |
| Replace raises before step 4 | `try` has not begun; old derivatives untouched |
| Replace raises after step 4 (in practice, step 5's save) | Handler deletes only names written this call and differing from the old ones; re-raises |

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
- Animated GIF: dimensions recorded, `skipped`, **and both derivative fields blank**.
  "Source still animated afterwards" is **not** a sufficient assertion — the source file on
  disk is never rewritten, so that clause passes on the broken build too. The assertion that
  discriminates is that no derivative was produced. The mutant is moving the `is_animated`
  probe to after `exif_transpose`.
- Skips the derivative when the original is narrower than the target.
- Discards a derivative that encodes no smaller than its source **without writing it to
  storage** (asserted on the storage backend, not just the field).
- Returns `failed` without raising on a corrupt file **and** on a storage write failure
  (forced by patching the backend) — and in the latter case, when the first write succeeded
  and the second raised, **leaves no file behind AND leaves both fields blank**. The field
  half is not optional: `FieldFile.save` writes the name back onto the instance, so a test
  asserting only "no file behind" passes on a build that persists a field pointing at the
  bytes it just deleted.
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
  old derivatives intact; **a raise at step 5 (forced by patching `save`) leaves neither the
  new derivatives nor the new original's bytes behind** — the window this change introduces.
  There is deliberately **no "raise at step 4" case**: `generate_derivatives` never raises,
  so such a test could only be written by patching it to violate its own contract, and a
  test that cannot go red honestly is one an implementer will eventually weaken.
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
  `gallery` and `dragimage` — the `sizes`-upscale guard, asserted on measured geometry, with
  the band fixtures described above. **`cell-full` is deliberately not in this list**: it
  emits no `srcset` and no `sizes` under any condition, so deleting the omission rule changes
  nothing about a `cell-full` render and the assertion would pass identically on the broken
  build.
- **`cell-full` is covered by its own assertion instead**: `src` is the original, **no**
  `srcset` and no `sizes` are present, and `data-zoom-src` **is** present — the last being
  the only tag-emitted marker that distinguishes a converted `cell-full` from an unconverted
  one.
- Omits `srcset`/`sizes` whenever no derivative exists; omits `srcset` when `width` is null;
  renders nothing for `asset=None` and blank `file.name` (tested on an element template, the
  only place those guards are reachable).
- Raises on an unknown preset; **per-value key test** for `ImageElement.Size.values` and
  `TableElement.CellImageSize.values`.
- Emits the exact per-site class and attribute set, including `data-asset-preview` on the
  manager cell and *not* on the picker cell.
- `extra` rejects a non-allow-listed name and rejects a valued attribute.
- Emits `loading="lazy"` on `grid` **and not** on the student element presets.
- **Emits no `width` or `height` attribute on any preset** — one unconditional assertion
  over every preset, since the measured distortion appears only on portrait sources and a
  per-preset spot check would miss it.
- `cell-full` emits `src` = the original with **no** `srcset` (the auto-layout table case).
- Emits `data-zoom-src` **only where the tag also emits `data-zoomable`** (i.e. driven by
  `extra`), with a negative assertion that the `grid` preset does **not** carry it.
  `data-zoom-src` is consumed only by `imagezoom.js`, which is armed off `[data-zoomable]`
  — a preset the zoom never touches has no use for it, and emitting one full media URL into
  each of ~950 grid cells would inflate exactly the 2.1 MB HTML figure this change makes a
  required before/after measurement and the basis for deferring pagination.
- Every preset's CSS declares `height: auto`, an explicit `aspect-ratio`, or an ancestor
  `aspect-ratio` plus `object-fit` — asserted against the stylesheet, with the gallery
  exercising the third case. **Retained deliberately even though the design no longer depends
  on it**: it is the precondition any future re-introduction of dimension attributes would
  have to satisfy, so losing it silently would remove the guard rail in front of the defect
  this spec had to reverse. Stated here so its presence reads as intentional rather than
  residual.

### Per-template conversion

**One rendering assertion per in-scope template** that the emitted HTML references a
derivative (or at minimum a `srcset`).

**The two cell partials need their assertion pinned to a size, or it is unsatisfiable.**
`full` is what both fall back to (`|default:'full'`, pinned by `test_table_render.py:99-119`)
and is the size an implementer reaches for first — but a `cell-full` render emits neither a
derivative URL nor a `srcset`, so the generic assertion would fail on a *correct* build. Per
this spec's own note about implementers weakening tests they cannot satisfy, the likely
outcome is that the guard for the two hardest templates gets dropped and a forgotten cell
conversion becomes invisible. So: `_table_cell.html` and `_filltable_cell.html` assert
against a **`small`/`medium`/`large`** cell, where the derivative is observable, and
`cell-full` gets the separate original-`src` assertion described under the template-tag tests. Without these, a build that left
`imageelement.html`, both table cells, the gallery and both drag-to-image `<img>` tags
untouched would pass every other test: the tag unit tests pass, the geometry tests pass
trivially, and the acceptance check only touches the manager grid. A forgotten template must
be RED, not invisible.

**Existing assertions must be audited, not just new ones added.** `tests/test_table_render.py:94`
asserts `f'src="{asset.file.url}" in html'`, which directly contradicts the new `cell-*` rule
(`src` = thumb) — and worse, it will **keep passing** if its fixture is narrow enough that no
thumb exists, so the conversion would look verified while the assertion silently measures the
fallback path.

**The audit cannot be keyed on template paths alone.** Grepping the seven template paths
across `tests/` and `courses/tests/` is necessary — it is what catches
`courses/tests/test_image_size_render.py` and `tests/test_table_cell_images.py`, both outside
the obvious set — but it is **not sufficient**, because the e2e suites render these templates
through the real UI without ever naming them. The audit key is therefore "any test that
renders an in-scope template, by any route": the seven paths, **plus** `ImageElement`,
`GalleryElement`, `TableElement`/`resolved_cells`, `naturalWidth`, `data-zoomable` and
`asset-thumb`.

**Four e2e suites are named explicitly, because they assert precisely what this change
alters and none of them contains a template path:**

| Suite | What it pins | Disposition |
| --- | --- | --- |
| `tests/test_e2e_image_size.py` | `wide` = 948x719, `tall` = 297x719 (`:162-163`); `_assert_harness` (`:214`) asserts `(naturalWidth, naturalHeight) == (948, 719)`; `_check_preset` (`:199`) and `_check_nested_small` (`:609`) derive the whole 16-combination expected-box matrix from `nw/nh`. Also renders `_table_cell.html` (`:871`) and `galleryelement.html` (`:560`) | **Unchanged, still green** — fixtures stay on the fallback path |
| `tests/test_e2e_imagezoom.py` | `BIG = (1400, 900)` (`:44`); `assert _natural_width(trigger) == 1400` (`:223`, `:249`) | **Unchanged, still green** — same reason |
| `tests/test_e2e_table_cell_images.py` | `_rendered_box` (`:186-196`) reads `naturalWidth`/`naturalHeight` and derives boxes from `min(cap, cap*ratio, natural)` across ~15 fixtures (`:153, 225, 331, 379, 523, 578, 635, 727, 760`). The **only** e2e for `cell-small/medium/large` — the presets whose `src` changes most (original → thumb, no `srcset`) | **Unchanged, still green** — same reason |
| `tests/test_e2e_media_manager.py:866` | overlay/thumb `currentSrc` equality | **Inverted**, in the template-conversion commit (see the JS section) |

**Why "unchanged" is the right disposition, and what it costs.** These suites build fixtures
with plain `make_image_asset(...)`, and `derivatives` defaults to `False` — so their assets
have no `thumb`/`web`, `srcset`/`sizes` are omitted, `src` falls back to the original, and
`naturalWidth` still reads 948 / 1400 / the fixture width. They do not go red and need no
rewrite. Rewriting them was considered and **rejected**: the natural formulation
(substituting `el.width`/`el.height` for `nw`/`nh`) is tautological, because
`HTMLImageElement.width` returns the **rendered** width, not the attribute — measured, an
`<img width="948">` in `.el--image--small` reports `el.width = 130` while
`getAttribute('width')` reports `1100`. Under that substitution `ratio = rw/rh`, the cap
`min(hcap, wcap/ratio, nh)` collapses to `rh`, and the 16-combination matrix becomes
unfalsifiable — trading real coverage for the appearance of it. (Any future rewrite must use
`getAttribute("width")` parsed to a number, and keep a separate `naturalWidth > 0` liveness
check, since `_assert_harness` exists to distinguish "wrong preset" from "fixture never
loaded" and attributes report fine for an image that never loaded.)

**The cost is stated, not hidden:** leaving them on the fallback path means these suites give
no e2e coverage of the *derivative* path on the student surfaces. That gap is closed
deliberately elsewhere — by the new geometry suite (which uses `derivatives=True` fixtures)
and by acceptance criterion 2, which asserts `web` is actually selected on a student unit.

For each hit the plan states whether it is updated to expect a derivative or deliberately
left on the fallback path.

#### Existing test fixtures

Four existing tests do not merely assert the old `src` — their **fixtures stop working**,
because the tag requires a real `MediaAsset`:

| Test | Fixture problem |
| --- | --- |
| `test_imagezoom_render.py:52-55` | `SimpleNamespace(media=_media(), alt=…, figcaption="")` — `_media()` (`:25`) is `SimpleNamespace(file=SimpleNamespace(url=…))`. The missing `size` is survivable once `imageelement.html` adopts `{% with %}`+`|default:` (above); the duck-typed `media` is not |
| `test_imagezoom_render.py:58-67` | hand-built `figures` list of `{url, alt, desc}` — the new shape is `{asset, alt, desc}` |
| `test_imagezoom_render.py:69-74` | `_media()` duck-type passed as `cell.media` |
| `test_table_render.py:99-119` | renders the partial with no `size` key — kept working by retaining `|default:'full'` (above), but its fixture must still be a real asset |

The plan replaces `_media()` with a DB-backed factory asset and gives `el` an explicit
`size`. **This also changes what those tests are:** all three (`:52`, `:58`, `:69`) are
currently deliberate DB-free template unit tests — no `@pytest.mark.django_db`, no module
`pytestmark`. Each therefore gains the marker and a course fixture. Their assets are
deliberately **narrow** (no `derivatives=True`): they assert only that the `data-zoomable`
hook is present, so the fallback path is the right one to exercise and a wide fixture would
add cost without adding discrimination.

These are enumerated here because "which assertion is updated" does not describe this class
of breakage, and an implementer who discovers it mid-task is likely to weaken the tests
rather than migrate them.

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
a wrong `w` descriptor, or the gallery's ~14 px box shift.

**Width alone is NOT sufficient, and this is the trap.** `make_image_asset`
(`tests/factories.py:150-173`) ends in `MediaAsset.objects.create(course=course, **kw)` — it
does **not** route through `create_asset`, so `generate_derivatives` is never called no
matter how wide `size=` is. "Wider than 896 px ⇒ a thumb exists" is therefore false for the
only factory this spec sanctions, and a whole suite written to that rule would render the
fallback path and be exactly as vacuous as the 1x1 case it was added to prevent — passing
even on a build where the tag emits no `srcset` at all.

**The rule is therefore mechanical, not dimensional.** `make_image_asset` gains a
`derivatives=False` parameter — **an explicit named parameter alongside `size` and `color`,
never via `**kw`**, because the factory's own docstring records that `**kw` is splatted
straight into `MediaAsset.objects.create()` and an unknown key raises on a model field.
Passing `derivatives=True` calls `generate_derivatives(asset)` and persists the five fields. **Every asset in a geometry, tag, per-template or acceptance
assertion is created with `derivatives=True`**, and — with one named exception below — with
`size=` wider than 896 px.

**The exception: omission-rule fixtures, on every preset the guard is asserted against.**
The guard is "renders at its own intrinsic width when the asset is sub-`sizes`-width", and a
sub-`sizes`-width asset is by definition **not** wider than 896 px — so the two rules
contradict each other, and left unqualified the mandatory-sounding one wins, the omission
rule never fires, and the test measures the ordinary `srcset` path: green on a build with the
sole remaining layout protection deleted.

Those fixtures are instead **wider than 512 px** (so a thumb exists and the no-derivative
branch is not what is being exercised) and **narrower than the preset's measured box at the
test viewport** — note *measured box*, not declared `sizes` width. The distinction is not
pedantic: in the harness `el-full` came out at 567.98 px, so an 800 px fixture would sit
inside the 513–895 band and *still* exceed the box, both builds clamping identically — green
on the broken build. **The usable band differs per preset and per TOC state, and is taken
from that preset's own measurement — never from the band's nominal 513–895, and never from a
column figure quoted elsewhere in this document.** No numbers are given here deliberately:
this is the paragraph that seeds fixture thresholds, so quoting a convenient column width
here is exactly how an un-measured number becomes a test threshold. The gallery case is worked through concretely below (560x300, not 700x525);
every other fluid preset needs its own fixture chosen the same way from its own measurement.

**The baseline is measured, not remembered.** "Unchanged" is relative to something, and a
test that measures the post-change page and compares it to itself is unfalsifiable. The
reference geometry is captured **on the pre-change build** and recorded as explicit
per-template, per-axis constants in the plan — so the assertion is a real A/B against prior
geometry.

**Captured in both TOC states, and at 640px.** Two gaps would otherwise make the suite green
against the defects it exists to catch:

- **`html.unit-tree-collapsed` must be one of the captured states.** Measurement (2) exists
  because the collapsed TOC materially widens the column (measurement (2) against (1)), and that is exactly where a
  `sizes` set too low shrinks the rendered box. With only the default expanded TOC, a `sizes`
  wrongly derived at 647 produces a box identical to today's while every `el-full` image is
  ~225 px narrower for every user who has that persisted global toggle on.
- **640x800 must be one of the captured viewports**, with a `derivatives=True` fixture, or an
  under-declared mobile `vw` clause is untested. The geometry suite otherwise runs only at
  desktop widths, and the one existing suite that uses a 360x640 phone viewport
  (`tests/test_e2e_image_size.py:45,218`) is deliberately left on the no-derivative fallback
  path, so it cannot cover this either.

- Every touched template renders unchanged **layout**, asserted on measured box geometry
  (`bounding_box()`) against those recorded constants **with a ±1 px tolerance per axis**.
  The tolerance is required, not slack: a derivative's height is a rounded proportional
  scale of the original's, so their intrinsic ratios differ slightly (1100x841 → 896x685 is
  1.3080 vs 1.3079), and where a height cap binds the used width can shift sub-pixel.
- **Portrait fixtures are mandatory, not optional.** The attribute distortion that this
  design exists to avoid is invisible on landscape sources — measured, `el-full` 1100x841 is
  identical with and without attributes while 508x1486 moves 246→508 px. Every preset is
  therefore asserted against **both** a landscape and a portrait fixture; a landscape-only
  suite would have passed the design this spec had to reverse.
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
2. **`web` is actually selected on a student surface.** At DPR 1, `img.currentSrc` for an
   `el-full` image whose original exceeds 896 px is the **`web` derivative**; at DPR 2 it is
   the original (per the DPR paragraph above), asserted density-explicitly. Without this,
   the 21 MB `web` set — 58% of the added disk — has no measurement anywhere: both other
   criteria exercise the grid, which uses `thumb` only, and the tag tests assert the
   *presence* of a candidate list, which is not selection. A build with an over-declared
   `sizes` or wrong `w` descriptors would pass everything else while every student image
   still fetched the original, making the whole `web` set pure cost.
3. **Bytes over the wire.** Total image bytes for the grid's initial viewport at DPR 1.
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
removal, the `update_fields` truncation, the `!=` guard removal, the
`srcset`-omission-when-no-derivative removal, and — **most importantly** — **the omission
rule's width comparison removed, leaving only the no-derivative check**. Both omission
mutants are live and neither is redundant (see the independence argument above:
`cell-large`'s 240px `sizes` sits below `THUMB_WIDTH`, so each check catches cases the other
misses). The width-comparison mutant is the one that matters most, because a build that
deletes it passes every other mutant in this list; it is red only against the band fixtures
above, which is why those fixtures and this mutant are specified as a pair.

Each of these produces a build that looks correct and measures wrong.
