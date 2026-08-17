# Media image derivatives — measured box geometry (PR 1 scope: thumb boxes only)

**Scope note.** Task 1 was split across two PRs. This branch (`pipeline/media-image-derivatives`,
PR 1: media library + picker) measures only the two `.asset-thumb` boxes — the brief's
`asset-thumb manager` and `asset-thumb picker` rows. The other eleven boxes from the brief
(`el-full` expanded/collapsed, editor preview, gallery frame/collapsed, dragimage stage/collapsed,
and the three `td` column rows) are **out of scope for this document** and are measured in PR 2.

Of the brief's Step 4 deliverables, this document contains:

- **Item 1** — the raw table (thumb rows only, including the 300px narrow column).
- **Item 4** — the thumb raise-condition check (`box x 3 > 512` at any viewport, including 300px).

**Deliberately omitted here, deferred to PR 2** (every one of them depends on a box this PR does
not measure):

- **Item 2** — derived `sizes` values for `el-full`/`el-large`/`el-medium`/`el-small`, the
  641–1039 `vw`/`calc()` fit, the mobile clause, and the `gallery`/`dragimage` equivalents.
- **Item 3** — the `WEB_WIDTH` (896) raise-condition check and byte-cost re-measurement.
- **Item 5** — band-fixture width AND height per preset.

A later reader should not mistake this omission for "nothing to declare" — it is scope, not an
oversight.

## Measurement conditions

Playwright, headless Chromium, DPR 1 (overlay scrollbars — `document.documentElement.clientWidth`
equals the viewport width; the script asserts this on every page load). Driven against a real
`runserver` dev instance at `http://127.0.0.1:8009`, not a CSS harness, so every stylesheet rule
participates.

Seed: a throwaway course (`measure-tmp`) owned by a generated staff user, containing one unit
with one `ImageElement`, plus three image `MediaAsset`s at **2000x1500px** — chosen to be
comfortably wider AND taller than any measured `.asset-thumb` box, so `width:100%` +
`aspect-ratio:4/3` + `object-fit:cover` (the grid track), not the asset's intrinsic size,
decides the box.

**CSS-vs-intrinsic-size guard.** The measurement script asserts, for every sample, that the
measured box width is strictly less than the `<img>`'s `naturalWidth`. This assertion held at
every viewport across both boxes (max measured width 240px vs. `naturalWidth` 2000px) — the
guard did not trip, confirming `.asset-thumb`'s CSS is what decides the box, not the seeded
asset. See "`.asset-thumb` CSS" below for what that rule actually is.

`.asset-thumb` CSS (`courses/static/courses/css/editor.css:360-365`):

```css
.asset-thumb {
  display: flex; align-items: center; justify-content: center;
  width: 100%; aspect-ratio: 4 / 3; object-fit: cover;
  background: var(--surface-sunken); border-radius: var(--radius-sm);
  color: var(--text-secondary); font-size: 1.5rem;
}
```

`.asset-thumb` sits inside `.asset-cell` (`width:100%` of that cell's content box), which itself
is one track of `.asset-grid`'s `repeat(auto-fill, minmax(8rem, 1fr))` grid
(`courses/static/courses/css/editor.css:349-359`). So the box width is: grid-track width, minus
`.asset-cell`'s `padding: var(--space-2)` and 1px border on each side. Manager and picker share
this CSS and markup (`_asset_cell.html`, `_picker_grid.html`) but sit in differently-sized
containers — the manager grid lives in the page's `.app-main` content column, the picker grid
lives inside `.picker-card` (`width: min(40rem, 100%)`, its own `padding: var(--space-5)`,
and at ≤720px viewport the overlay padding drops to 0 and the card goes full-width) — which is
why the two rows diverge sharply at the 300px sample.

## 1. Raw table

| Box | 640px | 641px | 900px | 1039px | 1040px | 1280px | 300px |
| --- | --- | --- | --- | --- | --- | --- | --- |
| asset-thumb manager | 125 | 123.25 | 115.33 | 125.33 | 125.33 | 125.33 | 110 |
| asset-thumb picker | 122.5 | 122.75 | 122.5 | 122.5 | 122.5 | 122.5 | 240 |

Reproduced twice (two independent script runs against the same seeded server); both runs
produced byte-identical numbers.

## 4. Thumb check (`box x 3 > 512`)

`THUMB_WIDTH` (current value 512, per `docs/superpowers/plans/2026-08-17-media-image-derivatives.md:771`)
must cover the DPR-3 device-pixel requirement of every fixed-size thumb box: `box_css_px x 3`.

| Box | max measured width (across all 7 samples) | x 3 | > 512? |
| --- | --- | --- | --- |
| asset-thumb manager | 125.33 (at 1039/1040/1280px) | 375.99 | No |
| asset-thumb picker | 240 (at 300px) | 720 | **Yes** |

**Verdict: the raise condition fires.** `asset-thumb manager` stays comfortably under the
threshold at every sampled width (max x3 = 375.99). `asset-thumb picker` clears it only at the
300px narrow sample — exactly the case the brief's comment predicted ("the DPR-3 raise condition
… fire[s]" near the single-track supremum). At 641–1280px the picker box is a stable ~122.5px
(the picker grid has settled into a multi-track layout inside the `min(40rem, 100%)` card and
does not narrow further), so the 300px sample is not a redundant data point — it is the only
one that exercises the picker's single-track state, which only happens when the viewport itself
is narrow enough to force `.picker-card` to `width: 100%` under the `@media (max-width: 720px)`
override.

**Decision: accepted, not raised.** The spec permits either raising `THUMB_WIDTH` or recording and
accepting the shortfall; the project owner chose the latter for `courses/derivatives.py` (Task 3,
`pipeline/media-image-derivatives`). Raising to 720 would multiply every thumbnail's area by
1.98x (the library's thumb set ~15 MB → ~30 MB, worst-case decode memory ~750 MB → ~1.5 GB across
~950 assets) — working against the very symptom this feature fixes — while Section 6 below found
the shortfall is reachable only at viewports **≤308px**, below every mainstream phone's narrowest
common CSS width (320px), and only on the staff-only media picker, which at that width already
shows one thumbnail per row.

**Magnitude of the accepted shortfall:** 512/720 = 0.711x, i.e. effective DPR 2.13 delivered
against a DPR-3 requirement, not the full 3.0.

**Cheaper remedy left open for PR 2:** give the picker a fluid `srcset` preset at zero
regeneration cost — the same treatment the spec already applies to `cell-large`'s identically
undershooting 240px box — rather than paying the doubled storage/decode cost across the whole
library to cover a sub-320px window.

`THUMB_WIDTH` itself, and this reasoning, live in `courses/derivatives.py` next to the constant.

## 6. Addendum: DPR-3 shortfall reachability window (controller-commissioned)

**Why this addendum exists.** Section 4 found the raise condition fires for `asset-thumb picker`
at the single 300px narrow sample. Raising `THUMB_WIDTH` to 720 roughly doubles every
thumbnail's bytes across the whole library (~15 MB → ~30 MB), working against the very symptom
this feature fixes — so the choice between raising `THUMB_WIDTH` and accepting the shortfall
(recording its magnitude) hinges on how narrow a viewport must be before the shortfall is
reachable at all. That threshold is not derivable by inspection (this plan's standing rule: no
geometry number may be hand-derived — two prior attempts to derive numbers in this feature by
inspection were wrong), so it is measured directly here with a dense viewport sweep.

**Method.** Same measurement conditions as the rest of this document (headless Chromium,
`device_scale_factor=1`, driven against a real `runserver` dev instance at
`http://127.0.0.1:8009`, asserting `document.documentElement.clientWidth` equals the viewport
width on every page load) and the same seed shape (one throwaway course, one unit, one
`ImageElement`, three 2000×1500px `MediaAsset`s — comfortably larger than any measured box in
both axes; the measured-width-vs-`naturalWidth` guard held at every sample, confirming CSS still
decides the box). The sweep covers 14 viewports chosen to bracket both boxes' `auto-fill`
track-count boundaries densely: 240, 260, 280, 300, 305, 307, 308, 310, 320, 340, 360, 375, 390,
414px. Reproduced twice (two independent script runs against the same seeded server); both runs
produced byte-identical numbers.

### 6.1 Sweep table

| Viewport | manager width | manager ×3 | manager >512? | picker width | picker ×3 | picker >512? |
| --- | --- | --- | --- | --- | --- | --- |
| 240px | 190 | 570 | Yes | 180 | 540 | Yes |
| 260px | 210 | 630 | Yes | 200 | 600 | Yes |
| 280px | 230 | 690 | Yes | 220 | 660 | Yes |
| 300px | 110 | 330 | No | 240 | 720 | Yes |
| 305px | 112.5 | 337.5 | No | 245 | 735 | Yes |
| 307px | 113.5 | 340.5 | No | 247 | 741 | Yes |
| 308px | 114 | 342 | No | 248 | 744 | Yes |
| 310px | 115 | 345 | No | 110 | 330 | No |
| 320px | 120 | 360 | No | 115 | 345 | No |
| 340px | 130 | 390 | No | 125 | 375 | No |
| 360px | 140 | 420 | No | 135 | 405 | No |
| 375px | 147.5 | 442.5 | No | 142.5 | 427.5 | No |
| 390px | 155 | 465 | No | 150 | 450 | No |
| 414px | 167 | 501 | No | 162 | 486 | No |

Both boxes show the expected sharp discontinuity rather than a smooth curve — `.asset-grid` is
`repeat(auto-fill, minmax(8rem, 1fr))`, so each box jumps upward the moment its container's track
count drops from 2 to 1, then shrinks smoothly again as the viewport widens within the new
track count.

### 6.2 Measured cliffs (largest viewport at which `box × 3 > 512`)

- **`asset-thumb picker`: cliff = 308px.** The shortfall is reachable at every sampled width from
  240px up to and including 308px, and stops being reachable at 310px (110px box, 2-track). The
  single-track/2-track boundary for the picker's grid (inside `.picker-card`, which itself flips
  to `width: 100%` under the `@media (max-width: 720px)` overlay rule) sits strictly between
  308px and 310px.
- **`asset-thumb manager`: cliff = 280px.** The shortfall is reachable at 240–280px and stops at
  300px (110px box, already 2-track). The manager's single-track/2-track boundary sits strictly
  between 280px and 300px.

**Measured fact, for the raise-vs-accept decision.** Both cliffs sit below 310px: the picker's
shortfall is reachable up to 308px (not at 310px or above), and the manager's up to 280px (not at
300px or above). At the sampled granularity, neither box's shortfall reaches the 310–414px band
this sweep also covers (which brackets mainstream current phone CSS-viewport widths, e.g. 320,
360, 375, 390, 414px — all measured "No" for both boxes above). The sweep does not sample between
308px and 310px, or between 280px and 300px, so it does not pin the boundary to sub-pixel
precision — only that each cliff falls in that gap.

### 6.3 Disclosure — the manager's 300px conclusion is knife-edge, not comfortable

Section 4's narrative (manager stays "comfortably under the threshold" while picker fires only at
300px) is directionally right but understates how close the manager comes to firing at exactly
the sample it was previously measured at. This sweep shows the manager has its **own** cliff, at
280px — only 20px below the single 300px sample Section 4 relied on. At 300px the manager's grid
container computes to almost exactly the 2-track/1-track `auto-fill` boundary: one step narrower
(280px) and the manager box jumps from 110px to 230px, immediately tripping the same `× 3 > 512`
condition the picker trips. The 300px measurement in Section 1/4 is therefore not a robust
"comfortably clear" data point — it is close enough to the manager's own track-count boundary that
a future padding change to `.asset-cell`, `.app-main`, or the manager grid's container width could
flip it without any change to `THUMB_WIDTH` itself. This does not change Section 4's verdict (the
raise condition still fires only via the picker at the widths that were sampled there), but the
margin is narrower than "comfortably under the threshold" suggests.

### 6.4 Provenance note — a third brief-script bug, not previously recorded

Task 1's report (`.superpowers/sdd/2026-08-17-media-image-derivatives/task-1-report.md`) recorded
two brief-script bugs it fixed (the dead `[data-edit-element]` selector, and the bare
`button[type='submit']` login selector that hit the language-switch button first). It omitted a
third, present in the same brief script: the brief's `main()` printed rows only for `label in
[r for r in rows if r[0] == VIEWPORTS[0][0]]`, and its header/body loop iterated only
`VIEWPORTS` (the six wide viewports), never `THUMB_VIEWPORTS`. Since 300px is appended only to
`THUMB_VIEWPORTS` and is not a member of `VIEWPORTS`, the brief's print loop would have silently
produced a table with no 300px column at all — dropping exactly the sample that trips the raise
condition, even though the measurement loop itself did sample it. This is recorded here for
completeness of the provenance record of what was changed from the brief; it did not affect
Section 1's committed table, which builds its columns explicitly rather than reusing the brief's
print loop.
