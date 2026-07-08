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
- **Out of scope / unchanged:** Progress-mode numbers, the per-student drill-down view's own
  rendering (`analytics_student` does **not** gain raw/percent display — its one minimal change
  is parsing `values` to re-thread into its `back_url`), band colours (they stay
  percent-driven), and the CSV/XLSX/print exports. The raw-marks *export* already exists as the
  "Quiz gradebook (raw marks)" option; the matrix-view export stays percentages-only and its
  label is clarified to say so.

## Architecture / components

### 1. Raw/percent toggle (Results mode only)

**A new URL parameter `values`** (`percent` | `raw`, default `percent`), parsed and
guarded the same way `mode` is (any value other than `raw` collapses to `percent`). It is
only meaningful when `mode == "results"`; in Progress mode it is ignored (and the toggle
control is not rendered).

**View — `courses/views_analytics.py`:**

- `analytics_matrix` parses `values` from `request.GET` (guarded to `percent`/`raw`), adds it
  to the template context (needed by the main GET form's hidden input — see Template), and
  renders two new URLs — `percent_url` and `raw_url` — built via `_expand_qs`:
  `_expand_qs(scope, mode, base_pks, subset_pks, "percent")` and `…, "raw")` respectively.
  They mirror the existing `progress_url` / `results_url` pattern (preserving `scope`, `mode`,
  expand pks, and the student subset, differing only in the pinned `values` argument).
- **Builder call branches on mode** (not the shared `builder` alias): only
  `build_results_matrix` gains a `values` parameter, so the view calls
  `build_results_matrix(course, students, expand_pks, values)` in results mode and
  `build_progress_matrix(course, students, expand_pks)` (no `values`) in progress mode.
  Passing `values` through the shared alias would `TypeError` in progress mode.
- `_expand_qs` gains a **required** 5th positional `values` argument — new signature
  `_expand_qs(scope, mode, expand_pks, subset_pks, values)` (mirroring how `subset_pks` was
  made required so every call site fails loudly until it threads the new param). It emits
  `values` into the querystring **only when it is `raw`**, so percent (the default) keeps
  today's clean URLs and existing links/bookmarks are unaffected.
- **Every call site of `_expand_qs` threads `values`.** In `analytics_matrix`: `clear_url`,
  `progress_url`, `results_url`, `colours_url`, and the new `percent_url` / `raw_url`. In
  `_decorate_links`: the expand/collapse hrefs and the per-student `breakdown_url`. In
  `_matrix_redirect`: the POST redirect (reads `values` from `request.POST`). In
  `analytics_student`: the `back_qs` that builds `back_url`. This is what keeps the chosen mode
  sticky when the teacher expands a drill-down column, picks a student subset, clicks "Show
  all", or edits colour bands.
- **`_decorate_links` gains a `values` parameter** — it reads nothing from `request`, so
  `values` must be threaded in. New signature
  `_decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks, values)`, and the
  `analytics_matrix` call site (views_analytics.py:72) passes the parsed `values`; the three
  inner `_expand_qs` calls then thread it through.
- **Sticky state on the two non-href round-trips.** Subset **Apply** and the scope
  `<select onchange>` submit the main `<form method="get">`, not a pre-built href; and the
  colour-bands page saves via a POST. Both must carry `values` explicitly (a hidden input on
  the GET form — see Template; and `values` in the bands view/template — see §"Colour-bands
  form" below), or the reload/redirect would drop back to percent.
- **`analytics_student` (per-student view) parses `values` from `request.GET` solely to
  re-thread it into `back_url`** (via the `back_qs` call above). Its own logic is otherwise
  unchanged — it does not render raw/percent — so returning from a breakdown preserves the
  teacher's toggle state in the matrix URL. This is the one deliberate, minimal exception to
  "the per-student view is unchanged."

**Colour-bands form — `courses/views_analytics.py` `analytics_bands` + `analytics_bands.html`:**

- `_matrix_redirect` reading `request.POST.get("values")` only works if the bands form
  actually posts a `values` field. So `analytics_bands` parses `values` from its source
  querystring **with a string default** (`src.get("values", "")`, never `None`, so the hidden
  field renders empty — not the literal `"None"` autoescape produces from a `None` context
  value) and adds it to the context, and `analytics_bands.html` renders a hidden
  `<input name="values" value="{{ values }}">`. Saving or resetting colours then round-trips
  the teacher back into raw mode. (`values` is emitted/read as a plain string; guarding to
  `percent`/`raw` happens where the matrix consumes it.)

**Builder — `courses/rollups.py`:**

- `build_results_matrix(course, students, expanded=frozenset(), values="percent")` gains the
  `values` parameter.
- Per cell, `earned` and `mx` are already computed (today at lines ~555–561) and discarded.
  In `raw` mode the cell's `label` becomes `"<earned>/<mx>"` (e.g. `34/50`) using a new
  `_fmt_mark` helper; `cell["percent"]` is **still populated exactly as today** so band
  colouring via `_decorate` is untouched and the **body-cell** heatmap is identical between
  modes. An empty cell (`mx == 0`) stays `percent=None`, `label="—"` in both modes.
- **Per-student "Overall" cell** (the rightmost `row["overall"]`, built at ~line 568) also
  switches to raw in raw mode: `label = _fmt_mark(tot_e)/_fmt_mark(tot_m)`, with the
  `tot_m == 0 → "—"` guard, and `percent` unchanged for colouring. Leaving it as a percent
  would produce a visibly inconsistent row (raw cells + a `68%` overall) that reads as a bug.
- **Footer/averages in raw mode** show class column totals rather than an average of
  percentages: for each column, `Σ earned / Σ mx` across the displayed students (label via
  `_fmt_mark`), and the overall footer sums across everything. Each footer cell still carries
  a `percent` computed from those totals (`_pct(Σearned, Σmx)`) purely so it colours
  consistently with the body. Note this means the **footer/average colours intentionally
  differ** between modes (percent mode averages the per-student percentages; raw mode colours
  by the class-total ratio) — the "identical heatmap" guarantee is scoped to body cells only.
  In `percent` mode the footer keeps today's average-of-percent behaviour unchanged.
- `_fmt_mark(value)` — formats a `Decimal` mark for display: integer values render without a
  decimal point (`4`, not `4.0`), fractional values drop trailing zeros (`4.5`, not `4.50`).
  **It must not emit exponent notation** — the naïve `Decimal.normalize()` yields
  `"1E+2"` for `Decimal("100")` and `"1.5E+2"` for `Decimal("150")`, and footer class-totals
  are routinely ≥ 100. Use an exponent-safe approach (e.g. `normalize()` then correct a
  positive exponent via `quantize(Decimal(1))`, or format-and-strip trailing zeros/point on
  the plain `str`). Used for cell numerator/denominator, the overall cell, and footer totals.

**Cell construction.** `_cell(percent)` currently returns
`{"percent": percent, "label": "<n>%"|"—"}`. It gains an optional label override
(e.g. `_cell(percent, label=...)`) so the raw path can supply `"34/50"` while keeping
`percent` for colouring. The percent path is unchanged.

**Template — `templates/courses/manage/analytics_matrix.html`:**

- A second segmented control cloned from the existing `.analytics__toggle` (two
  `.btn.btn--small` links, one `is-active`), labelled **Percent** / **Raw**, driven by
  `percent_url` / `raw_url`, rendered **only when `mode == "results"`**. It sits alongside the
  existing Progress/Results toggle in `.analytics__controls`. It gets its **own** i18n
  `role="group" aria-label` (e.g. "Number format") — distinct from the existing group's
  "Metric" — so screen-reader users don't hear two identically-named groups. No JavaScript —
  same server round-trip pattern as the existing toggle.
- **Hidden `values` input on the main GET form.** The main `<form method="get">` (which
  carries hidden `mode`, `scope_rendered`, `expand`) gains
  `<input type="hidden" name="values" value="{{ values }}">` so that submitting it — via a
  subset **Apply** or the scope `<select onchange="this.form.submit()">` — preserves the
  toggle. (Emitting it always is fine: an empty/`percent` value guards to percent on read.)
- No per-cell template change is needed: cells already render `{{ cell.label }}`, and the
  builder now supplies the raw label in raw mode.

### 2. Dash clarity

**A) Mode-aware caption.** A short caption, its text chosen by `mode`, rendered **outside**
the `{% if not matrix.rows %}…{% else %}…{% endif %}` branch (right after the colour legend
`<ul>`), so it always renders regardless of the no-rows / no-columns state:

- Progress: *"— = not tracked as progress here (badged columns aren't part of progress; quiz
  scores appear under Results)."*
- Results: *"— = not attempted yet, or awaiting review (badged columns aren't scored in this
  view)."*

The caption references the badge (B) so the two together fully explain every dash: a dash in
a **measured** column means "no data yet," and a dash in a **badged** column means "this
column isn't measured in this view." Both strings are i18n (EN + PL), styled as muted helper
text.

**B) Badge the columns a mode structurally can't measure.** Each **leaf** analytics column
derives from a frontier node carrying `lesson_pks` (obligatory lessons only — non-obligatory
lessons are in *neither* set) and `quiz_pks`. Expose two booleans per leaf column —
`has_lessons` (`bool(lesson_pks)`, i.e. has a progress-counted lesson) and `has_quizzes`
(`bool(quiz_pks)`, i.e. has a gradeable quiz) — computed in `frontier_columns`
(`courses/rollups.py`) where the nodes are known, and attached to the corresponding **leaf
header cell** (the cells the template badges). *(No attachment to the public column dict from
`_public_columns` — badges render off the header cells, not `matrix.columns`, so a
column-dict copy would have no consumer.)*

The template renders a small monochrome badge (a `currentColor` line SVG per the project's
icon convention, plus muted column styling) on a leaf header cell whenever the **active mode
cannot measure that column** — i.e. the column would only ever show `—`:

- **Progress mode:** badge every leaf column with `not has_lessons` (no obligatory lessons) —
  it is not part of progress tracking. This covers quiz-only columns *and* the
  non-obligatory-lesson-only edge case (which has both flags false and would otherwise be an
  unexplained blank).
- **Results mode:** badge every leaf column with `not has_quizzes` (no gradeable quiz) — it is
  not scored. This covers pure-lesson columns *and* the same non-obligatory-lesson-only edge.

The badge is a **neutral "not measured in this view" marker** — not a content-type label — so
it stays correct for the edge column that is neither a lesson-progress nor a quiz-score
column. Its accessible text is mode-specific: Progress → *"Not part of progress tracking"*;
Results → *"Not scored in this view"*.

**Template condition — guard on `is_leaf` explicitly.** Spanning (non-leaf) header cells carry
no `has_lessons`/`has_quizzes` keys, so a bare `{% if not cell.has_quizzes %}` is truthy on
them (missing key → falsy → `not` → true) and would badge every spanning cell. The badge
condition must therefore be `cell.is_leaf AND <mode-specific flag>` (Progress:
`is_leaf and not has_lessons`; Results: `is_leaf and not has_quizzes`), excluding spanning
cells structurally rather than relying on flag presence. Columns the active mode *can* measure
are never badged, even if they also contain the other content type (a mixed chapter with both
obligatory lessons and quizzes shows a real number in both modes and gets no badge).

**Suppress badges when the whole matrix is unmeasurable in the mode.** Results mode already
shows a standalone "No quizzes in this course yet." paragraph when `not matrix.has_quizzes`; in
that case do **not** also badge every column (the paragraph plus caption already explain it) —
badge only when *some* columns are measurable and others aren't. This avoids triply-redundant
"not scored" messaging on a quiz-less course.

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
3. Teacher expands a drill-down column / clicks Show all → those **hrefs** were built by
   `_decorate_links` / the view threading `values` through `_expand_qs`, so `values=raw` is
   preserved. Teacher applies a **new subset** or changes **scope** → these submit the main
   GET **form**, whose hidden `values` input carries `values=raw` back. Teacher saves **colour
   bands** → the bands POST carries `values`, and `_matrix_redirect` re-emits it. Every path
   re-renders in raw mode.
4. Teacher switches to **Progress** → `progress_url` carries `values` but the view calls
   `build_progress_matrix` (without `values`), which ignores it; the Percent/Raw toggle is not
   rendered.
5. Badges + caption: on every render, `frontier_columns` supplies `has_lessons`/`has_quizzes`
   per leaf header cell; the template badges the columns the active mode can't measure (Progress:
   `not has_lessons`; Results: `not has_quizzes`) and prints the mode-appropriate dash caption.

## Error handling

- **Unknown `values`** (typo, tampering): treated as `percent` (single guarded parse, same as
  `mode`). Never errors.
- **`mx == 0` / no counted submissions** for a cell: `percent=None`, `label="—"` in both
  modes; excluded from footer totals (a column with all-zero max contributes 0/0 → the footer
  shows `—` when its `Σmx == 0`, guarded by the existing `_pct` "caller guarantees b>0"
  contract).
- **Decimal formatting:** `_fmt_mark` handles integer and fractional `Decimal` scores without
  locale/`parseFloat` hazards (pure Decimal → string), avoiding the trailing-zero and
  Polish-locale pitfalls noted in project history, and — critically — **never emits exponent
  notation** for values ≥ 100 (see the `_fmt_mark` bullet above); class-total footers commonly
  exceed 100.
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
- Per-student **overall** cell in raw mode: `label` is `tot_e/tot_m` (e.g. `34/50`), and `"—"`
  when `tot_m==0`; `percent` unchanged.
- Raw footer: per-column footer = `Σearned/Σmx` across displayed students; overall footer sums
  across all; footer `percent` computed from the totals (colouring); a column with `Σmx==0`
  footer shows `—`.
- `_fmt_mark`: `4` → `"4"`, `4.0` → `"4"`, `4.5` → `"4.5"`, `4.50` → `"4.5"`, **and the
  exponent-notation guard: `100` → `"100"`, `100.0` → `"100"`, `150` → `"150"`** (not
  `"1E+2"` / `"1.5E+2"`).
- Column flags: `frontier_columns` exposes `has_lessons` / `has_quizzes` per leaf column with
  the expected values for lesson-only (obligatory), quiz-only, mixed, and the
  **non-obligatory-lesson-only** column (both flags `False`).

**`courses/views_analytics.py` view tests:**

- `values=raw` round-trips: rendering `?mode=results&values=raw` produces raw cell labels; the
  Percent/Raw toggle appears with **Raw** active.
- Default: `?mode=results` (no `values`) → percent labels, **Percent** active.
- Preservation (hrefs): `values=raw` is preserved through the Results/Progress toggle URLs, the
  expand/collapse drill-down hrefs, the "Show all" clear link, the colours link, and the
  per-student `breakdown_url` (assert the generated URLs contain `values=raw`).
- Preservation (non-href round-trips): the main GET form renders the hidden
  `values` input with `raw`; `analytics_bands` in raw context renders the hidden `values`
  input, and posting the bands form redirects (via `_matrix_redirect`) back to a URL carrying
  `values=raw`; `analytics_student` rendered with `values=raw` produces a `back_url` containing
  `values=raw`.
- Progress mode: `?mode=progress&values=raw` ignores `values` (no raw labels; the Percent/Raw
  toggle is not rendered).
- Badges: Progress mode badges a quiz-only column header **and** a non-obligatory-lesson-only
  column header; Results mode badges a pure-lesson column header **and** the same
  non-obligatory-lesson-only column; a mixed (obligatory-lesson + quiz) column is unbadged in
  both modes; spanning (non-leaf) header cells are never badged. Assert the mode-specific
  accessible text. Suppression: on a quiz-less course in Results mode (the "No quizzes"
  paragraph shows), no per-column badge is rendered.
- Caption: the mode-appropriate dash caption text is present in each mode, and renders even when
  the matrix has no rows.

**e2e (click-path):** on the Results matrix, click **Raw**, assert a known cell shows the
`n/m` form; click **Percent**, assert it returns to `n%`. Drive the real link, not a
`page.evaluate` shortcut (per project e2e convention).

**i18n:** run the catalog checks; add EN + PL translations for the new strings (caption text,
badge labels, toggle labels, the renamed export option). No obsolete `#~` entries.
