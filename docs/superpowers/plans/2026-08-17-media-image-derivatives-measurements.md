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

**Raised value: `THUMB_WIDTH` should be raised from 512 to at least 720** (per the spec's
"rounding is upward, always" convention — 720 is already an integer, so no further rounding is
needed). This value, and the consequent re-run of the byte-cost measurement it triggers per the
spec ("their raise condition covers DPR 3 … raise `THUMB_WIDTH` and re-measure the byte-cost
table"), is recorded here as PR 1's finding but the re-measurement itself is deferred to whichever
PR implements `courses/derivatives.py`'s constants (out of this PR's scope — no `THUMB_WIDTH`
code exists yet on this branch).
