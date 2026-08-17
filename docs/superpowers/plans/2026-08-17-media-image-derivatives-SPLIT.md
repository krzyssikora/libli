# Media Image Derivatives — two-PR split

**Decision (2026-08-17, user):** split execution into two PRs. The spec
(`2026-08-17-media-image-derivatives-design.md`) and the 13-task plan
(`2026-08-17-media-image-derivatives.md`) are unchanged and authoritative — this
document only says which task goes in which PR, and what each PR may safely omit.

## Why this seam

PR 1 needs **no `sizes` values at all**, because the only preset it ships is `grid`,
which uses a single candidate (`src` = thumb, no `srcset`). That collapses three
otherwise-expensive dependencies:

- it needs only measurements **(4)** and **(5)** (`.asset-thumb` in the manager and
  picker), not the six student-surface boxes;
- it needs **no** `imagezoom.js` work, because neither grid template carries
  `data-zoomable` — the hover preview (`media_preview.js`) is the only client-side
  module the grids touch;
- it has no `srcset`, so the omission rule, the three-clause `sizes`, the band
  fixtures and the geometry-baseline suite are all PR 2's problem.

PR 1 therefore fixes the reported symptom — the media library taking minutes to paint —
with roughly half the surface area and none of the layout risk.

## PR 1 — media library and picker

**Branch:** `pipeline/media-image-derivatives` (this one).
**Title:** `feat(media): serve thumbnails in the media library and picker`

| Task | Scope in PR 1 |
| --- | --- |
| 1 | **Partial** — measurements **(4)** and **(5)** only, at `THUMB_VIEWPORTS` including the 300px narrow case. Skip boxes (1), (2), (3), (6), (7), (8). The measurements doc records only the thumb rows and the DPR-3 raise-condition check. |
| 2 | Full — model fields, `DerivativesState`, migration `0059` |
| 3 | Full — `courses/derivatives.py` |
| 4 | Full — `post_delete` cleanup |
| 5 | Full — `create_asset` / `get_or_create_asset` / importer `generate=False` |
| 6 | Full — `replace_asset` resequencing |
| 7 | Full — `backfill_media_derivatives` |
| 8 | **Omit** — `imagezoom.js` is untouched; no PR-1 surface emits `srcset` or `data-zoomable` |
| 9 | Full — `media_preview.js` repoint (the grid converts, so this is required and must land first) |
| 10 | **Partial** — the tag ships with **one preset: `grid`**. `PRESETS` contains only that entry; `_DECLARED_MAX` is empty. Keep the FIXED/FLUID/ORIGINAL strategy constants and the unknown-preset raise. Drop the tag tests that exercise fluid presets; keep grid, degenerate-input, `extra` allow-list, `alt`, `loading=lazy`, and the no-`width`/`height` test. |
| 11 | Full — convert `_asset_cell.html` and `_picker_grid.html`, extend `_seed_assets`, invert the hover e2e |
| 12 | **Omit** |
| 13 | **Partial** — acceptance criteria **1** (grid selects the thumb at DPR 1 and 3) and **3** (grid initial-viewport bytes under a measured threshold), plus the before/after HTML-size and render-time figures. Omit criterion 2 (`web` is selected) and the geometry-baseline suite. |

**Ordering inside PR 1:** Task 9 (JS) lands and is verified before Task 11 (template
conversion). Same rule, smaller scope.

**PR-1 body must state:** the `web` derivative is generated and backfilled but not yet
consumed by any surface — that is deliberate, and PR 2 consumes it.

## PR 2 — student surfaces

**Branch:** `pipeline/media-image-derivatives-students`, cut from PR 1's merge commit.
**Title:** `feat(media): serve derivatives on student image surfaces`

| Task | Scope in PR 2 |
| --- | --- |
| 1 | **Remainder** — measurements (1), (2), (3), (6), (7), (8) at 640/641/900/1039/1040/1280, both TOC states, gallery measured **after `gallery.js` enhances**, (6)/(8) with a ≥2000px fixture. Then derive every `sizes` value, the three-clause forms, and the band-fixture dimensions. |
| 8 | Full — `imagezoom.js` repoint, its four constraints (i18n across three blobs, three CSS source-level invariants, named markup, reset-on-close). **Lands before Task 12.** |
| 10 | **Remainder** — add `cell-small/medium/large/full`, `el-*`, `gallery`, `dragimage` to `PRESETS`, fill `_DECLARED_MAX`, and add the fluid-preset tag tests including both omission mutants. |
| 12 | Full — convert the five student templates, the `GalleryElement.render()` figure-dict change, and the existing-test audit |
| 13 | **Remainder** — the geometry baseline probe on master, the geometry suite (both TOC states, 640/641/1280, landscape **and** portrait fixtures), and acceptance criterion 2 |

**Everything in the spec that PR 1 omits is PR 2's**, unchanged — the three-strategy
taxonomy, the omission rules, `cell-full`'s original-only treatment, the `cell-large`
DPR-3 exception, and all nine falsification mutants that touch fluid presets.

## What must NOT be dropped in the split

These are the findings that cost the most to discover; a split is exactly where they get
lost:

1. **PR 1 still needs the full `generate_derivatives` implementation**, including the
   `is_animated`-before-`exif_transpose` ordering, the mode-`P` normalisation, the
   `max(1, round(...))` clamp and the 16383 cap, the buffer-first encode with
   `ContentFile(buffer.getvalue())`, and the rule-9 re-blank. The backfill writes `web`
   derivatives in PR 1 even though nothing renders them.
2. **PR 1's tag must still emit no `width`/`height`.** The grid measurement (130x841 vs
   130x98) is a PR-1 surface.
3. **PR 2 must re-run PR 1's grid acceptance checks** after adding the fluid presets — a
   regression there would be invisible otherwise.
4. **Neither PR may quote a hand-derived geometry number.** Every `sizes` value and
   fixture threshold comes from the measurement protocol. Two separate attempts to derive
   these by inspection were wrong (a missing `.el { margin: 1rem 0 }`, then a missing
   `.app-main` mobile-padding override).
