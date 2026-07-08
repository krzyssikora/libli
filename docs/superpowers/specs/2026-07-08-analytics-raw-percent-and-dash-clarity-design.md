# Analytics matrix: raw/percent toggle + dash clarity

## Purpose

Teachers viewing the course analytics matrix (`/manage/courses/<slug>/analytics/`) in
**Results** mode currently see only percentages per cell. They have no way to see the
underlying raw marks (points scored out of the maximum) without going to the separate
gradebook export. This work adds an in-page **Percent / Raw** toggle so a teacher can
flip the Results matrix between `68%` and `34/50` without leaving the page.

Separately, the same page overloads the em-dash `—` to mean several unrelated things,
which teachers find confusing:

- Progress mode, a quiz column → "not applicable, quizzes aren't lesson-progress"
- Progress mode, a section with no required lessons → "no required lessons here"
- Results mode, a student with no counted submission → "not attempted / awaiting review"
- Results mode, a pure-lesson column → "no quizzes here"

A teacher sees the identical dash for "this column isn't measured in this mode" and "no
data yet." This work disambiguates the dash with (A) a mode-aware caption under the matrix
and (B) a small badge on the columns a mode structurally cannot measure.

Both parts touch the same view and template, so they ship together.

### Scope / non-goals

- **In scope:** the main analytics matrix view (`analytics_matrix`), Results-mode raw/percent
  toggle, the dash caption, the column badges, and one export-panel label rename.
- **Out of scope / unchanged:** Progress-mode numbers, the per-student drill-down view
  (`analytics_student`), band colours (they stay percent-driven), and the CSV/XLSX/print
  exports. The raw-marks *export* already exists as the "Quiz gradebook (raw marks)" option;
  the matrix-view export stays percentages-only and its label is clarified to say so.

## Architecture / components

### 1. Raw/percent toggle (Results mode only)

**A new URL parameter `values`** (`percent` | `raw`, default `percent`), parsed and
guarded the same way `mode` is (any value other than `raw` collapses to `percent`). It is
only meaningful when `mode == "results"`; in Progress mode it is ignored (and the toggle
control is not rendered).

**View — `courses/views_analytics.py`:**

- `analytics_matrix` parses `values` from `request.GET`, passes it to the results builder,
  and renders two new URLs — `percent_url` and `raw_url` — that mirror the existing
  `progress_url` / `results_url` pattern (they preserve `scope`, `mode`, expand pks, and the
  student subset, differing only in `values`).
- `_expand_qs(scope, mode, expand_pks, subset_pks)` gains a **required** `values` argument
  (mirroring how `subset_pks` was made required so every call site fails loudly until it
  threads the new param). It emits `values` into the querystring **only when it is `raw`**,
  so percent (the default) keeps today's clean URLs and existing links/bookmarks are
  unaffected.
- Every call site of `_expand_qs` threads `values`: `clear_url`, `progress_url`,
  `results_url`, `colours_url`, the expand/collapse hrefs and the per-student `breakdown_url`
  in `_decorate_links`, and the POST redirect in `_matrix_redirect` (which reads `values`
  from `request.POST`). This is what keeps the chosen mode sticky when the teacher expands a
  drill-down column, picks a student subset, clicks "Show all", or edits colour bands.
- `breakdown_url` threads `values` for URL consistency, but the per-student view itself
  ignores it (out of scope) — so a teacher returning from a breakdown keeps their toggle
  state in the matrix URL.

**Builder — `courses/rollups.py`:**

- `build_results_matrix(course, students, expanded=frozenset(), values="percent")` gains the
  `values` parameter.
- Per cell, `earned` and `mx` are already computed (today at lines ~555–561) and discarded.
  In `raw` mode the cell's `label` becomes `"<earned>/<mx>"` (e.g. `34/50`) using a new
  `_fmt_mark` helper; `cell["percent"]` is **still populated exactly as today** so band
  colouring via `_decorate` is untouched and the heatmap is identical between modes. An empty
  cell (`mx == 0`) stays `percent=None`, `label="—"` in both modes.
- **Footer/averages in raw mode** show class column totals rather than an average of
  percentages: for each column, `Σ earned / Σ mx` across the displayed students (label via
  `_fmt_mark`), and the overall footer sums across everything. Each footer cell still carries
  a `percent` computed from those totals (`_pct(Σearned, Σmx)`) purely so it colours
  consistently with the body. In `percent` mode the footer keeps today's average-of-percent
  behaviour unchanged.
- `_fmt_mark(value)` — formats a `Decimal` mark for display: integer values render without a
  decimal point (`4`, not `4.0`), fractional values drop trailing zeros (`4.5`, not `4.50`).
  Used for both cell numerator/denominator and footer totals.

**Cell construction.** `_cell(percent)` currently returns
`{"percent": percent, "label": "<n>%"|"—"}`. It gains an optional label override
(e.g. `_cell(percent, label=...)`) so the raw path can supply `"34/50"` while keeping
`percent` for colouring. The percent path is unchanged.

**Template — `templates/courses/manage/analytics_matrix.html`:**

- A second segmented control cloned from the existing `.analytics__toggle` (two
  `.btn.btn--small` links, one `is-active`), labelled **Percent** / **Raw**, driven by
  `percent_url` / `raw_url`, rendered **only when `mode == "results"`**. It sits alongside the
  existing Progress/Results toggle in `.analytics__controls`. No JavaScript — same server
  round-trip pattern as the existing toggle.
- No per-cell template change is needed: cells already render `{{ cell.label }}`, and the
  builder now supplies the raw label in raw mode.

### 2. Dash clarity

**A) Mode-aware caption.** A short caption rendered beneath the matrix, its text chosen by
`mode`:

- Progress: *"— = no required lessons in this section. Quiz scores appear under Results."*
- Results: *"— = not attempted yet (or awaiting review)."*

Both strings are wrapped for i18n (EN + PL, matching the project's bilingual convention).
Placed near the existing colour legend, styled as muted helper text.

**B) Badge the columns a mode structurally can't measure.** Each **leaf** analytics column
already derives from a frontier node that carries `lesson_pks` and `quiz_pks`. Expose two
booleans per leaf column — `has_lessons` (`bool(lesson_pks)`) and `has_quizzes`
(`bool(quiz_pks)`) — computed in `frontier_columns` (`courses/rollups.py`) where the nodes
are known, and attached to **both** the public leaf column dict and its corresponding leaf
header cell (both are built from the same node in that function).

The template then renders a small monochrome badge (a `currentColor` line SVG per the
project's icon convention, plus muted column styling) on the leaf header cell for columns
the **active** mode cannot measure:

- Progress mode: columns with quizzes but no required lessons (`has_quizzes and not
  has_lessons`) → a "Quiz" badge.
- Results mode: columns with required lessons but no quizzes (`has_lessons and not
  has_quizzes`) → a "Lesson" badge.

This turns a bare `—` in those columns from "mystery blank" into "this column isn't part of
this view." Non-leaf (spanning) header cells are never badged. Columns that a mode *can*
measure are never badged, even if they also contain the other content type (e.g. a mixed
chapter with both lessons and quizzes shows a real number in both modes and gets no badge).

### 3. Export label

In the export panel of `analytics_matrix.html`, rename the radio choice
**"This matrix view"** → **"This matrix view (percentages)"** (i18n, EN + PL), making it
explicit that the matrix-view export is percentages regardless of the new toggle. No export
code changes.

## Data flow

1. Teacher opens `…/analytics/?mode=results` → `values` absent → defaults `percent` →
   matrix renders today's percentages; the Percent/Raw toggle shows with **Percent** active.
2. Teacher clicks **Raw** → `raw_url` = same querystring + `values=raw` → `analytics_matrix`
   parses `values="raw"` → `build_results_matrix(..., values="raw")` → each cell `label` is
   `earned/mx`, `percent` unchanged → `_decorate` colours by `percent` as before → footer
   shows column totals `Σearned/Σmx`.
3. Teacher expands a drill-down column / picks a subset / clicks Show all → those hrefs were
   built by `_decorate_links` / the view threading `values` through `_expand_qs`, so
   `values=raw` is preserved and the view re-renders in raw mode.
4. Teacher switches to **Progress** → `progress_url` carries `values` but the builder is
   `build_progress_matrix`, which ignores it; the Percent/Raw toggle is not rendered.
5. Badges + caption: on every render, `frontier_columns` supplies `has_lessons`/`has_quizzes`
   per leaf column/header cell; the template badges the columns the active mode can't measure
   and prints the mode-appropriate dash caption.

## Error handling

- **Unknown `values`** (typo, tampering): treated as `percent` (single guarded parse, same as
  `mode`). Never errors.
- **`mx == 0` / no counted submissions** for a cell: `percent=None`, `label="—"` in both
  modes; excluded from footer totals (a column with all-zero max contributes 0/0 → the footer
  shows `—` when its `Σmx == 0`, guarded by the existing `_pct` "caller guarantees b>0"
  contract).
- **Decimal formatting:** `_fmt_mark` handles integer and fractional `Decimal` scores without
  locale/`parseFloat` hazards (pure Decimal → string), avoiding the trailing-zero and
  Polish-locale pitfalls noted in project history.
- **Missing `values` at a call site:** `_expand_qs`'s new argument is required (not
  defaulted), so any un-threaded call site is a hard failure in tests, not a silent
  percent-mode fallback — the same discipline already used for `subset_pks`.
- **Badge/caption with no quizzes or no lessons in the course:** flags are simply all-false or
  all-true; no badge renders where a mode measures everything. The caption always renders
  (it explains the dash generally), which is harmless when no dash is present.

## Testing (TDD)

**`courses/rollups.py` unit tests:**

- Raw-mode cell labels: a student with `34` of `50` across a column's quizzes → cell label
  `"34/50"`; `percent` still present and equal to the percent-mode value (colouring parity).
- Student-specific denominator: two students in the same column where one took 3 of 4 quizzes
  and the other took all 4 → their raw labels carry **different** denominators (the max only
  sums attempted/counted quizzes).
- Empty cell: a student with no counted submission in a column → `label="—"`, `percent=None`,
  in raw mode too.
- Raw footer: per-column footer = `Σearned/Σmx` across displayed students; overall footer sums
  across all; footer `percent` computed from the totals (colouring); a column with `Σmx==0`
  footer shows `—`.
- `_fmt_mark`: `4` → `"4"`, `4.0` → `"4"`, `4.5` → `"4.5"`, `4.50` → `"4.5"`.
- Column flags: `frontier_columns` exposes `has_lessons` / `has_quizzes` per leaf column with
  the expected values for lesson-only, quiz-only, and mixed columns.

**`courses/views_analytics.py` view tests:**

- `values=raw` round-trips: rendering `?mode=results&values=raw` produces raw cell labels; the
  Percent/Raw toggle appears with **Raw** active.
- Default: `?mode=results` (no `values`) → percent labels, **Percent** active.
- Preservation: `values=raw` is preserved through the Results/Progress toggle URLs, the
  expand/collapse drill-down hrefs, the subset selection, the "Show all" clear link, and the
  colours link (assert the generated URLs contain `values=raw`).
- Progress mode: `?mode=progress&values=raw` ignores `values` (no raw labels; the Percent/Raw
  toggle is not rendered).
- Badges: Progress mode renders a Quiz badge on a quiz-only column header; Results mode renders
  a Lesson badge on a lesson-only column header; a mixed column is unbadged in both.
- Caption: the mode-appropriate dash caption text is present in each mode.

**e2e (click-path):** on the Results matrix, click **Raw**, assert a known cell shows the
`n/m` form; click **Percent**, assert it returns to `n%`. Drive the real link, not a
`page.evaluate` shortcut (per project e2e convention).

**i18n:** run the catalog checks; add EN + PL translations for the new strings (caption text,
badge labels, toggle labels, the renamed export option). No obsolete `#~` entries.
