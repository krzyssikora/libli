# Student results page: a Results table with section sums — design

**Status:** draft for the owner's review, 2026-09-17. **Spec-review rounds applied: see the `spec(analytics-results-table)` commits**; open owner
questions are listed in §0. The owner-decisions
table below is protected: a review catch that would change a row is **not applied**. It goes back to
the owner as a question.

**Follows:** `2026-09-16-analytics-student-pages-design.md` (#326, #327, both merged). That spec's §4
page is the starting point; this one changes its Results view, its heading and one Progress chip.

---

## 0. Owner decisions (protected)

Verbatim quotes, 2026-09-17. „Proposal" rows are mine, and the owner accepted them as written.

| # | Decision | Owner's words |
|---|---|---|
| O1 | The Results view of the student page is a **table**: quiz · quiz count or status · score · % | "it is a lot easier to see results in a table" |
| O2 | A **summary for every section containing more than one quiz** | "summary for each component containing more than 1 quiz" |
| O3 | A summary is **Σ score ÷ Σ max** over that section's quizzes, counting **exactly the quizzes the grid counts** (not started, in progress and awaiting review are left out, never counted as 0) | "Why is it not the same as sum of scores for this section / sum of max?" — confirmed: it is the grid's own rule (`build_results_matrix`) |
| O4 | The **% cells use the grid's colour bands** (the course's `color_bands`) | "yes, colours too" |
| O5 | The **Progress view keeps its current layout** | "progress can stay as it is" |
| O6 | The chapter lesson chip reads **„lekcje: 1/2"** (no grammatical-number forms) | "to avoid gramatic forms: "lekcje: 1/2"" |
| O7 | The **heading names the view**: „Wyniki — Imię Nazwisko" / „Postęp — Imię Nazwisko". No „ucznia", which is wrong for a girl | "is better than "Wyniki ucznia", as in the latter case for a girl it should be "Wyniki uczennicy"" |
| O8 | Proposal: the per-question page's back link names the same view, „← Wyniki" / „← Postęp" | "All good" |
| O9 | The options table's pick marker stays the same for single- and multiple-answer questions | "This is not that important, I can accept the current form." |
| O10 | Options table: **only the icons are coloured**, not the whole row. **Already true in the merged CSS — no change** (§6) | "only the icons coloured would be better than the whole row"; after §6 was shown: "you are right, it is already fine" |
| O11 | **Sums sit on the section's own heading row**, with the course total („Cały kurs") at the top. There are no „Razem" rows underneath | "yes, this is clever" |
| O12 | The **student's course outline** chip reads „lekcje: 1/2" too (one wording for the one shared chip) | "1 yes" |
| O13 | Review-waiting wording uses **„sprawdzanie"**, not „ocena": `Awaiting review` → „Oczekuje na sprawdzenie", `awaiting review` → „oczekuje na sprawdzenie", `Submitted for review` → „Przesłano do sprawdzenia" | "\"Sprawdzanie\" sounds better than \"ocena\"" |
| O14 | The two plural „awaiting review" entries on the student's `quiz_results.html` also use „sprawdzenie" (six Polish forms: „oczekuje/oczekują na sprawdzenie") | "Q4 yes" |
| O15 | The student's own `course_results.html` uses `quiz_score_view`, so a marked REVIEW-only quiz shows its score there too (test mirroring T10b) | "Q5 yes" |
| O16 | Q3 → a heading's score and % are Σ score ÷ Σ max over the section's **marked** quizzes only (the grid's figure); not-started and awaiting-review quizzes are left out, never counted as zero | "1 a" (asked with the example: A marked 8/10, B awaiting review, C not started → (a) „8 / 10 · 80%" vs (b) „8 / 30 · 27%") |
| O17 | Q3 → heading rows **keep** the quiz count „1/3" (quizzes whose score is in the sum / quizzes in the section) | "2. Yes, keep, please" |

**Open questions for the owner:** none — all answered 2026-09-17 (Q1 → O12, Q2 → O10, Q3 → O16/O17, Q4 → O14, Q5 → O15).

- **Q3** answered 2026-09-17 → O16, O17.
- **Q4** answered → O14.
- **Q5** answered → O15.

---

## 1. What the page does today (merged #327)

`templates/courses/manage/analytics_student.html` renders `breakdown.tree` as a nested `<ul>` through
`_breakdown_node.html`. In Results mode, `build_student_breakdown(..., mode="results")` has already
pruned the tree to quizzes and the chapters that contain one (`rollups._keep_quizzes`). A quiz row is
its title plus the `_quiz_pill.html` pill („wynik 4/5 (80%)", „nie rozpoczęto", …). There are no sums
and no colours. The heading is `{% trans "Student results" %} — {{ student.list_display_name }}`.

The figures a sum needs already exist per quiz. `build_course_results` returns one row per quiz with
`status`, `pending`, `graded`, `score` and `max_score`. Its "this score counts" rule is
`submission_is_counted`, the **single rule the matrix shares** (docstring, `rollups.py`). `_quiz_pill`
maps each row to the pill.

---

## 2. The Results view becomes a table (O1–O4, O11)

### 2.1 Data: sums are computed in the builder, never in the template

`build_student_breakdown(..., mode="results")` additionally stamps **every container node** and
returns a **course total**:

- `quiz_total` — the number of quiz units in the node's (pruned) subtree.
- `counted` — how many of those quizzes have a submission whose score counts (`submission_is_counted`
  true **and** `max_score > 0`). A submitted quiz with no gradeable marks has no score, so it is in
  `quiz_total` but not in `counted`.
- ⚠️ **One rule for "this quiz shows a score", and it is the grid's.** A quiz row shows `score/max`
  and a % **iff** its row is counted (`status == "submitted"`, i.e. not pending) **and**
  `max_score > 0`. It is **not** today's `_quiz_pill` rule (`kind == "scored"` only when `graded`, i.e. at least one
  AUTO question): the grid counts a REVIEW-only quiz that is fully reviewed with `max_score > 0`, and
  under today's pill rule its row would say „przesłano" while its marks sat in the heading's sum. §4
  moves `_quiz_pill` onto the same helper, so in the finished code the two agree. The builder stamps each quiz node with `shows_score` (bool), `score`, `max_score` and
  `percent` **from `quiz_score_view(row)`** for that node's `build_course_results` row (the raw row has no
  `percent`, and its `score` / `max_score` may be `None`), and the table reads those for its **numbers**,
  never the pill kind. The title link still keys on `item.pill.submission_pk`, as `_breakdown_node.html`
  does today. **Invariant:**
  the pruned tree's quiz nodes are exactly `build_course_results`'s rows, because both apply
  `is_quiz_unit` with the same `drafts` / `with_data`; the builder indexes the row directly
  (`rows_by_unit[node.pk]`), so a missing row raises instead of silently rendering an unscored quiz. A
  `NULL` `score` is coerced to `Decimal("0")` in the shared helper, exactly as `build_results_matrix`
  and `build_course_results` do (`sub.score or Decimal("0")`); `_pct(None, …)` would raise.
  The reverse case (`graded`, but a stored `max_score == 0`) shows no score and is not counted, again
  matching the grid.
- `score_sum`, `max_sum` — Σ `score`, Σ `max_score` over the counted quizzes (`Decimal`). With
  `counted == 0` both are `Decimal("0")` (never `None`), and `percent` is `None`.
- `percent` — `_pct(score_sum, max_sum)` when `max_sum > 0`, else `None`. This is the one percent rule
  the grid uses, so a heading's % equals the grid's Results cell for that section **by construction**.
- `summary` — `True` iff `quiz_total > 1` (O2). The template renders numbers only when it is true.

The wrapper gains `total`, built the same way over the whole pruned tree (`summary` true iff the
course has more than one quiz). Progress mode stamps **none** of these keys — neither the container keys
(`quiz_total`, `counted`, `score_sum`, `max_sum`, `percent`, `summary`) nor the quiz-node keys
(`shows_score`, `score`, `max_score`, `percent`) — and returns no `total`, so Progress is untouched (O5).
Progress pills still get their scored kind from `quiz_score_view` **through `_quiz_pill`** (§4), not from
node keys.

The per-quiz `score`, `max_score` and whether it counts are read from the **same
`build_course_results` rows** the pills are built from. There is no second query and no second
counting rule. `counted` (on containers) is exactly the number of quiz nodes below with
`shows_score` true.

**A summary section with no counted quiz.** When `summary` is true but `counted == 0` (every quiz below
is not started, in progress or awaiting review), the heading shows the count („0/3") and leaves the
score and % cells empty and uncoloured. It never renders „0/0". **On a heading row the template renders the
count cell iff `summary`, and the score and % cells iff `summary and percent is not None`** (equivalently
`summary and max_sum > 0`); it never branches on `counted` for the number cells. A single-quiz section
has a `percent` too (its one quiz may be scored), but `summary` is false, so its cells stay empty (O2).
The course total follows the same condition with `total.summary`.

⚠️ **Drafts.** The page calls the builder with `drafts="keep-with-data"`, exactly as the matrix does
(`views_analytics.py`, both call sites). The two therefore see the same quiz set, so the sums match
the grid's cells. A test pins this (§7, T4).

### 2.2 Colour (O4)

**Only when `mode == "results"`**, the view resolves `bands = course_color_bands(course)`, the same call the matrix makes, and paints
every `percent` it renders with `color_bands.band_style(percent, bands)`. It walks the pruned tree
**recursively** and sets `color = style["bg"]` / `text_color = style["fg"]` (from `band_style`'s
`{"bg", "fg"}`) on **every node dict in the pruned tree** (every quiz
node and every container node, whatever its `shows_score` / `summary`) and on `breakdown["total"]`.
Unrendered cells simply ignore it; a `None` percent paints nothing. The matrix's
`_decorate` walks a flat structure, so it is not reused; the new walk is a small helper in
`views_analytics.py`. A `None` percent gets `color = text_color = None` and renders neutral. The
template only reads `color` / `text_color`.

### 2.3 Markup

One `<table class="results-table">` replaces the `<ul class="breakdown__tree">` **in Results mode
only**. Progress mode keeps the `<ul>` and `_breakdown_node.html` unchanged (O5). The table is built
by flattening the pruned tree in pre-order (a new recursive include, `_results_table_rows.html`).
Each row carries its depth, so indentation shows nesting:

| Row kind | First cell | Count / status cell | Score | % |
|---|---|---|---|---|
| Course total (first row, only if `total.summary`; whenever a container's figures equal those of its only child (the course total over one top-level section, or a chapter holding a single summary section), both rows show the same figures; this is accepted per O11 and **not suppressed** at any level) | „Cały kurs" | `counted/quiz_total` | `score_sum/max_sum` | coloured `percent` |
| Section heading with `summary` | section title | `counted/quiz_total` | `score_sum/max_sum` | coloured `percent` |
| Section heading without `summary` (one quiz below) | section title | empty | empty | empty |
| Quiz | quiz title, linked to the per-question page when it has a submission: `<a class="breakdown-unit__link" href="{% url 'courses:manage_analytics_student_quiz' … %}?{{ drill_qs }}">`, the **same class and href** as today, so the accent colour + underline rule and existing selectors keep working | **empty** when `shows_score`; otherwise the status pill (below) | `score/max` when `shows_score`, else empty | coloured `percent` when `shows_score`, else empty |

- **Status cell (a quiz row without a score):** the existing pill span for the row's status, rendered
  by `{% with p=item.pill %}{% include "courses/manage/_quiz_pill.html" %}…{% endwith %}` (the partial
  reads only `p`; a bare include would render every quiz as `pill--none`), with the awaiting row's
  „Sprawdź" link inside the same `with`, as in `_breakdown_node.html`: `pill--none` „nie rozpoczęto" (inside the table
  `.results-table .pill--none{color:var(--text-secondary)}`, because the base `--text-tertiary` fails AA
  and the ≤480px pill is smaller still; the design pass checks its contrast), `pill--progress` „w toku",
  `pill--awaiting` „oczekuje na sprawdzenie", `pill--submitted` „przesłano". Its `scored` branch never
  fires here, because a scored row leaves this cell empty. On an awaiting-review row the „Sprawdź" link
  (the `breakdown-unit__review` markup and URL, as today) follows the pill **on its own line** in the
  same cell. A REVIEW-only quiz that `shows_score` shows its score like any other row, with no pill.
- **Header:** `<thead>` with column headers „Tytuł", „Quizy", „Wynik", „%". The first is „Tytuł"
  (existing msgid `Title`), not „Quiz", because most rows in that column are sections or the course total. The second column's header
  counts quizzes, since that is what a heading row shows there; a quiz row puts its status in it.
- **What „1/3" means.** The fraction is **quizzes whose score is in the sum / quizzes in the section**.
  It is **not** "quizzes done": a submitted quiz still awaiting review is not in the numerator. The help
  page must say this in one sentence (§8), because a teacher will otherwise read „1/3" as "did 1 of 3".
  The owner kept this count (O17) and confirmed the sums count marked quizzes only (O16).
  Final wording is in §5.
- **"Section" / "heading row" in §2.3–§2.5 means any container node** (part, chapter or section) —
  §2.1 stamps every container, and a chapter with more than one quiz gets its sums exactly like a section.
- **Headings are row headers:** `<th scope="row">` in the first cell of every heading row (quiz rows
  use a non-bold `<th scope="row">` too, §2.5), and a
  `results-table__section` class that gives the whole row a light neutral tint and bold text (O11). Quiz rows have plain `<td>` number cells.
- **Course total row:** marked up and styled exactly like a summary heading row: `<th scope="row">`,
  `results-table__section`, tint and bold. A `results-table__total` class adds a separator below it that
  **wins the collapsed-border conflict by width**: `.results-table__total > th, .results-table__total > td
  {border-bottom:2px solid var(--border-strong)}` on the row's **cells** (in `border-collapse`, a wider
  border beats the next row's 1px `border-top`; a same-width row border would lose to the cell border). Its first cell reads „Cały kurs" at depth 0 and carries **neither** `lang="{{ course.language }}"` nor
  `data-math-title`: it is an interface string, not course content.
- **Indentation:** the first cell gets `padding-inline-start` from the node dict's **`depth`** (as
  `build_outline` stamps it: 0 for any root node, so in a course without parts a chapter is d0), not
  from its kind. Rows keep their own depth; they are **not** shifted under „Cały kurs", which is
  already set apart by its tint and border. The indent is **added to** the cell's base inline
  padding, never a replacement for it, and each level differs from the one above it at every width.
  The class is `results-table__d0` … `__d3`. Computed `padding-inline-start` of the title cell:

  | band | base | d0 | d1 | d2 | d3 |
  |---|---|---|---|---|---|
  | wider than 640px (unconditional rules) | .5rem | .5rem | 1.5rem | 2.5rem | 3.5rem |
  | `max-width:640px` block | .5rem | .5rem | 1rem | 1.5rem | 2rem |
  | `max-width:480px` block | .25rem | .25rem | .75rem | 1.25rem | 1.75rem |

  **Selectors and specificity.** Base padding: `.results-table th, .results-table td{padding:.375rem .5rem}`
  (0,1,1). Depth: `.results-table .results-table__title.results-table__d1{padding-inline-start:1.5rem}` …
  (0,3,0), which beats the base (0,1,1) wherever it is written. The bands follow `app.css`'s own
  pattern: the desktop padding and depth rules are **unconditional**, then `@media (max-width:640px)` and
  then `@media (max-width:480px)` repeat the padding shorthand and all four depth rules with the **same
  selectors**. Nested `max-width` queries leave no fractional-width gap (at 480.5px the 640px block
  applies and the 480px block does not) and need no range-syntax support (Safari < 16.4 ignores range
  queries). Because the selectors are equal, **source order decides: the unconditional rules first, the
  640px block after them, the 480px block last**, all three in one place in `app.css`. Everything that is
  not padding or indentation (`border-top`, `border-collapse`, backgrounds, weights, alignments) stays
  outside the media blocks. The other ≤480px rules (font size, pill size and wrapping) sit in the same
  `@media (max-width:480px)` block. `ContentNode.RANK` (part 0, chapter 1, section 2, unit 3) only bounds
  the maximum at 3. No inline style.
- **Numbers:** marks go through the `marks` filter (decimal comma in Polish, #327). Percent renders as
  `{{ percent }}%`. An empty summary cell is empty; it never shows „—".
- **Maths in titles:** the title cells keep `lang` and `data-math-title`, as the breakdown rows do, and
  `has_math` is still computed from the pruned tree.
- **Colour cells:** `style="background:…;color:…"` from §2.2, the same inline pattern as
  `_analytics_cell.html`.

**Empty Results view.** If the pruned tree is empty (the course has no visible quiz), no table is
rendered. Instead the page shows `<p class="results-table-empty">{% trans "No quizzes in this course yet" %}</p>`, styled
`color: var(--text-secondary)` in `app.css` (not `.helptext` or `.muted`, whose `--text-tertiary` fails
AA at that size)
under the view switch. That msgid **already exists** (it is used by `course_results.html`).

### 2.4 CSS

Every rule goes in `core/static/core/css/app.css`: the student page links no page stylesheet (known
trap, previous spec §2). No stylesheet line citations anywhere.

- `.results-table { width:100%; border-collapse:collapse; }`. Cells get `border-top:1px solid
  var(--border-subtle)` (unconditional) and the band padding of §2.3 (`.375rem .5rem` above 480px).
- **Narrow phones (≤ 480px)** get a denser table, within O1's four columns (no column is dropped or
  merged — that would change O1): cell padding `.25rem .25rem` (same (0,1,1) selector); `.results-table{font-size:.875rem}`;
  the pill inside the table `font-size:.7rem; padding:.05rem .3rem` (and it wraps, below). Estimate at
  390px (358px table): status column at min-content ≈ „sprawdzenie" at .7rem/600 + pill padding ≈ 75px;
  score „812,5/960,5" at .875rem ≈ 75px; „100%" ≈ 35px; padding 4 × 8px = 32px → title column ≈ 141px ≈
  **39%**, of which a depth-3 title's padding-inline-start takes 1.75rem (28px, rem is not scaled by the
  table's `font-size`), leaving its text ≈ 109px. If the design-pass render still misses the
  30% floor, the plan **stops and asks the owner**: the remaining levers (merging or dropping a column)
  touch O1.
- **Cell classes** (every body row, every kind): the title cell `results-table__title`, the count/status
  cell `results-table__status`, the score and % cells `results-table__num`. Rules target these classes.
- **Wrapper and backgrounds.** The table sits in `<div class="results-table-wrap">` with
  `overflow-x:auto; position:relative` (the `position` is required: KaTeX's `.katex-mathml` is
  `position:absolute` and would otherwise escape a static scroller and widen the page — a known trap).
  The table has `background: var(--surface-raised)`. Heading and total rows use `var(--surface-base)`,
  which differs from raised in **both** themes (light `#F4F1EA` on `#FFFFFF`, dark `#1A1816` on
  `#2C2925`); `--surface-sunken` is **not** used, because in light mode it is lighter than the page
  (`#FAF8F3` on `#F4F1EA`) and in dark mode darker, so it would not read as a tint.
- The title cell takes the free width and wraps (`overflow-wrap:anywhere`). The `results-table__num`
  cells are `width:1%; white-space:nowrap; text-align:right`.
- **Maths titles.** KaTeX renders inline maths as unbreakable inline-blocks, so a long formula sets the
  title column's minimum width and `overflow-wrap:anywhere` cannot split it. That is **accepted by
  design**: the page never scrolls sideways, and the **table** scrolls inside `.results-table-wrap`
  instead.
- **`<th>` browser defaults are overridden, by specificity, not by source order** (`reset.css` has no
  `th` rule, so a `<th>` is bold and centred by default):
  - `.results-table tbody th{text-align:start;font-weight:normal}` (0,1,2) — every row-header title.
  - `.results-table tbody .results-table__section th, .results-table tbody .results-table__section td
    {font-weight:600}` (0,2,2) — heading and total rows; it beats the reset wherever it is written.
  - `<thead>`: `.results-table thead th{font-weight:600;text-align:start}` (0,1,2), and
    `.results-table thead th.results-table__num{text-align:right}` (0,2,2) on „Wynik" and „%", whose
    `<th>` carry the `results-table__num` class. The four `<thead>` cells carry the same column classes as
    the body: „Tytuł" `results-table__title`, „Quizy" `results-table__status` (so the column's
    `width:1%; white-space:nowrap` applies to its header too), „Wynik" and „%" `results-table__num`.
    „Tytuł" and „Quizy" stay start-aligned.
- The **status column** is `width:1%; white-space:nowrap; text-align:start` by default, so at desktop
  width every pill stays on one line and the column takes its max-content width. Its cells (the „1/3"
  fractions on heading rows and the pills on quiz rows) are start-aligned, matching the „Quizy" header.
  **Only inside the `@media (max-width:480px)` block** does the pill wrap (moved down from 640px: a
  `width:1%` column shrinks to min-content, so a wrappable pill breaks at every space at **every** width
  under the breakpoint, including ~600px where it would fit; at ≤480px that narrowest form is what the
  space needs, and the design pass checks both ~600px (pills on one line) and 390px (wrapped)). The rule is
  (`.results-table .pill{white-space:normal; border-radius:.5rem;text-align:center}`); the cell's own
  `white-space` is not changed there (its content is a space-free fraction, an inline-block pill that sets
  its own `white-space`, or a block link, so a cell-level rule would be dead CSS). The „Sprawdź" link is `display:block` at every width, via `.results-table .breakdown-unit__review
  {display:block}`, scoped to the table so the Progress view's inline link is unchanged (O5). The
  longest content is „oczekuje na sprawdzenie" plus „Sprawdź": a nowrap pill is ~160–175px at `.75rem`/600,
  which at 390px (358px table) would leave the title column 30–60px, so on phones wrapping it is the lesser
  cost. In a `width:1%` column the pill shrinks to its widest word and **breaks at every space**
  („oczekuje / na / sprawdzenie", „nie / rozpoczęto", „w / toku"); the 390px design-pass screenshot judges
  whether three-line pills are acceptable, and if not the plan stops and asks the owner. A wrapped pill with the base `border-radius:999px`
  becomes an oval whose corners touch the text, hence the smaller radius there. The design-pass
  screenshots check it.
- `.results-table__section` gets `background: var(--surface-base)` (weight is set by the specificity rules
  above). A coloured
  % cell's inline background paints over it, which is intended.
- **Phone (≤ 640px):** the table stays a table. The title wraps; the score and % columns shrink to their
  content and never wrap; the status column wraps its pill only at ≤ 480px. At 390px a 4-level title plus „16,5/22" and „100%" must not scroll the page
  sideways (T8).

### 2.5 Accessibility

- `<caption class="sr-only">` naming the table, e.g. „Wyniki quizów".
- Headings **and quiz titles** are `<th scope="row">` (quiz titles not bold), so a screen reader names
  every row while moving across its cells. The column headers are `<th scope="col">`.
- The section hierarchy is shown visually (indent, tint) and is **deliberately not** exposed as ARIA
  tree structure: row headers plus the section names read in document order are enough, and
  `aria-level` on table rows is poorly supported.
- Colour is never the only carrier: the % text is always present.
- The scrolling wrapper is reachable by keyboard **only when it can scroll**: when `has_math` (the one
  case §2.4 says can scroll) it is `<div class="results-table-wrap" role="region" aria-labelledby="…"
  tabindex="0">`, pointing at the table's caption id, so Firefox and Safari users can scroll a table
  widened by a long formula (axe `scrollable-region-focusable`). Without maths it is a plain
  `<div class="results-table-wrap">`: no landmark, no Tab stop, and no name announced twice. On a maths
  render the duplicate name (region and table both „Wyniki quizów") is accepted as the cost of a
  scrollable region's required label.
- A heading row with no summary has empty cells. It gets no „brak" text, because a screen reader
  reads the quiz row just below it.

---

## 3. Headings and labels (O6–O8)

### 3.1 Student page heading (O7)

`<h1>` reads `{% trans "Results" %} — {{ student.list_display_name }}` in Results mode and
`{% trans "Progress" %} — …` in Progress mode. It reuses the existing msgids („Wyniki", „Postęp"),
the same words the switch under the heading uses. `<title>` names the view but **not** the student, as today's title has no student name (a name in the
title would land in browser history, tabs and bookmarks, which no owner row asks for):
`{% trans "Results" %} · {{ course.title }} · libli` and `{% trans "Progress" %} · {{ course.title }} · libli`.

### 3.2 Per-question back link (O8)

`analytics_student_quiz.html`'s back link reads `← {% trans "Results" %}` or `← {% trans "Progress" %}`
for the mode in `_drill_params`. The view already parses `mode` there, but its `render()` context does not include it, so the view
**adds `"mode": mode`** to that context alongside the template change (a template-only edit would always
render „← Postęp"). The `Student results` msgid
becomes unused and is dropped with `makemessages --no-obsolete` (the repo forbids `#~` entries;
`tests/test_i18n_po_health.py`).

### 3.3 The lesson chip (O6, O12)

`{{ done }}/{{ total }} {% trans "required" %}` becomes one translatable string with its numbers
inside: `{% blocktrans with done=… total=… %}lessons: {{ done }}/{{ total }}{% endblocktrans %}`,
pl „lekcje: %(done)s/%(total)s". It changes in `_breakdown_node.html` and in both `_outline_node.html` sites (O12). In
`_breakdown_node.html` the `and mode != "results"` guard is **removed** while that line is rewritten:
Results mode no longer renders this template, so the guard is dead code. The `required` msgid then becomes unused and is dropped. The chip counts
**required** lessons only, as today. The owner accepted that a chapter with an „Dodatkowa" lesson
shows fewer in the chip than it has rows.

---

## 4. What does not change

- Progress mode's tree, markers, „Dodatkowa" tags and view switch (O5).
- The matrix, the export and the per-question page body.
- The pill markup (`_quiz_pill.html`) where it is still used: the Progress view, the per-question
  header, and the Results table's status cell (§2.3).
- ⚠️ **This deliberately overrides the previous spec's §2.8** („`reviewed` resolves to `submitted`, not
  to `scored`"). That line recorded today's code (a code finding, not an owner decision); the plan must
  not "restore" it.
- ⚠️ **Exception: every pill follows §2.1's scoring rule.** Today `_quiz_pill` returns `kind == "scored"`
  only when `graded` (at least one AUTO question). Left alone, a fully reviewed REVIEW-only quiz would
  show „4/5 · 80%" in the Results table but „przesłano" in the Progress view (one click on the switch)
  and in the per-question header (one click on the title). So the rule lives in **one helper in `courses/rollups.py`, next to
  `_quiz_pill`** (both callers live there; the view imports from `rollups`, never the reverse), and
  `_quiz_pill` uses it:

  ```python
  def quiz_score_view(row):
      """The grid's "this quiz shows a score" rule for one _course_results_row row."""
      # returns {"shows_score": bool, "score": Decimal, "max_score": Decimal, "percent": int | None}
  ```

  `shows_score` is `row["status"] == "submitted" and (row["max_score"] or 0) > 0` (a `submitted` row is
  already not pending). `score` is `row["score"] or Decimal("0")` and `max_score` is `row["max_score"] or Decimal("0")` (both
  always `Decimal`, never `None`, including not-started and in-progress rows). Containers sum only the
  nodes whose `shows_score` is true. `percent` is `_pct(score, max_score)`
  when `shows_score`, else `None`. `_quiz_pill` returns `kind == "scored"` (with `score`, `max_score`,
  `percent` from this helper) **iff** `shows_score`; a submitted row without it stays `submitted`. Every
  pill kind other than `not_started` **keeps `submission_pk`**, including the scored one (the helper does
  not return it; `_quiz_pill` copies it from the row), because the quiz title link depends on it.
  `build_student_breakdown` stamps its quiz nodes from the same helper **in Results mode only** (§2.1). Consequently the Progress pills,
  the per-question header (which keeps branching on `p.kind`) and the Results table all agree, and no
  caller re-derives the rule. This changes what a pill **says** for REVIEW-only quizzes, not the Progress
  **layout** (O5). The student's own `course_results.html` follows too (O15): in its `row.status == "submitted"` branch
  it shows `score / max_score` iff `quiz_score_view(row)["shows_score"]` (instead of `row.graded`), else
  „przesłano — bez oceny"; the view passes each row's helper result alongside the row (e.g. a
  `score_view` key added to every row by `build_course_results`, computed by the same helper). Its
  `awaiting_review` branch is unchanged (it keeps showing the partial auto score when `row.graded`).
  Test **T15**. Tests **T10b** and **T10d**. The same PR corrects the misleading comment in `_course_results_row`,
  `graded = has_auto.get(unit.pk, False)  # ≡ max_score > 0`: `graded` means "has a top-level AUTO
  question", which a REVIEW-only quiz with `max_score > 0` does not, and that difference is exactly
  what this section is about.
- Any number anywhere: this adds sums the grid already shows; it computes nothing new (N1 of the
  previous spec still holds).

---

## 5. Interface text

New:

| msgid | pl | where |
|---|---|---|
| `Whole course` | `Cały kurs` | total row |
| `Quiz results` | `Wyniki quizów` | sr-only caption |
| `lessons: %(done)s/%(total)s` | `lekcje: %(done)s/%(total)s` | chip (O6) |

Reused, never re-created (all verified present in `locale/pl` on 2026-09-17): `Title` („Tytuł"),
`Quizzes` („Quizy"), `Score` („Wynik") for the column headers; `Results` („Wyniki"), `Progress`
(„Postęp"); the pill status words `not started` („nie rozpoczęto"), `in progress` („w toku"),
`awaiting review` („oczekuje na ocenę"), `submitted` („przesłano"); `Review` („Sprawdź").
The status words above include `awaiting review`, whose msgstr O13 changes.
Dropped as unused: `Student results`, `required`.

Changed msgstr only (O13), msgids untouched: `Awaiting review` → „Oczekuje na sprawdzenie" (review queue, per-question page, the student's own `quiz_results.html`), `awaiting review` → „oczekuje na sprawdzenie" (pill), `Submitted for review` → „Przesłano do sprawdzenia" (the student's question feedback). `Awaiting review` also renders on the student's own **`course_results.html`**, so the change reaches that page too.

**O14 — the two plural entries on `quiz_results.html`** also change msgstr only, msgids untouched:
`%(n)s question awaiting review (up to 1 more mark)` → „%(n)s pytanie oczekuje na sprawdzenie (do 1
dodatkowego punktu)" / „%(n)s pytania oczekują na sprawdzenie (do 1 dodatkowego punktu)" / „%(n)s pytań
oczekuje na sprawdzenie (do 1 dodatkowego punktu)", and `%(n)s question awaiting review (up to %(m)s
more marks)` → the same three forms with „(do %(m)s dodatkowych punktów)". Only „na ocenę" becomes „na
sprawdzenie"; the rest of each form stays exactly as it is. The **graded** msgids (`Your quiz was graded`, `Quiz graded`, `submitted — not graded`) keep „ocena": grading is what they mean.
Catalog procedure: as in the previous plan's Global Constraints, **plus `--no-obsolete`**.

---

## 6. O10 — the options table is already icons-only (no change)

In the merged CSS the verdict colour reaches **only the icon cells**
(`.answers__option.is-correct/.is-wrong/.is-missed .answers__options-mark`); the option text keeps
`--text-primary`. The owner confirmed this is what he wants. The options table is **not touched** by
this work.

---

## 7. Tests

View / builder (pytest, `tests/test_analytics_student_page.py`):

- **T1** — the Results summary equals the grid. Build a class, and for one student compare each
  summary heading's `percent`, `score_sum` and `max_sum` with the `build_results_matrix` cell **whose
  column `node` is that section**. To get that column, expand the section's **ancestors, not the section
  itself**: `frontier_columns` turns an expanded node into a spanning header, which has no cell. Cover
  a top-level section **and** a nested one. Call `build_results_matrix(..., values="raw")` exactly as the view calls it
  (`drafts="keep-with-data", with_data=_with_data_for(course)`): its cells
  carry only `percent` and `label`, and only raw mode puts the marks in `label`. Compare `percent`
  directly, and compare `label` with `f"{_fmt_mark(score_sum)}/{_fmt_mark(max_sum)}"`, so that a wrong
  sum which happens to round to the same % still goes red. **When `counted == 0`** the grid returns
  `_cell(None)` (label „—"), so for those sections assert instead that the grid cell has
  `percent is None` and label „—" and the page's `percent` is `None`. The fixture must contain **at least
  one summary section of each kind** (`counted > 0` and `counted == 0`), so both branches run. Include a not-started, an in-progress and an awaiting-review quiz,
  which the page and the grid must each leave out. *Mutant:* count awaiting-review scores → red.
- **T1b** — a REVIEW-only quiz, fully reviewed, with `max_score > 0`: its row shows `score/max` and a
  %, and its marks are in the heading's sum, matching the grid. *Mutant:* in `quiz_score_view`, add `row["graded"]` to the `shows_score` condition → red (T10b and
  T10d go red with it). (Reading `pill.kind` instead of `shows_score` is **not** a usable mutant after
  §4: the two are the same predicate.)
- **T1c** — a summary section with no counted quiz renders „0/N" with empty, uncoloured score and %
  cells, never „0/0". The same holds for the course total.
- **T2** — `summary` only when `quiz_total > 1`: a section with one quiz — **whose quiz is scored**, so
  the section has a non-`None` `percent` — renders an empty count, score and % in its heading row.
  *Mutant:* `>= 1` → red. *Mutant:* drop the `summary` conjunct from the score/% condition → red.
- **T3** — the course total row is first and matches the grid's `overall` cell for the student, compared
  the same way as T1 (raw mode, `percent` and `label`). A course with **exactly one quiz** renders
  **no** total row. *Mutant:* `total.summary` true for `>= 1` quiz → red.
- **T4** — drafts: a draft quiz **with** data counts on both pages (its marks are in the section cell and
  the heading); *Mutant:* call the builder with `drafts="hide"` → red. A draft quiz **without** data has
  no row on the page and is **not** in its heading's `quiz_total` (the grid has nothing to compare, since
  it changes no sum); *Mutant:* call the builder with `drafts="keep"` → red on that denominator. "Data"
  is **course-wide** (`_with_data_for`: any student's `QuizSubmission` or `UnitProgress`), so the
  without-data quiz must have no data from **any** student. A third case is pinned too: a draft quiz
  attempted only by **another** student is shown on this student's page as „nie rozpoczęto" and counts
  in `quiz_total`.
- **T5b** — rendered text, in Polish: for one `counted > 0` summary heading, the course total row and one
  scored quiz row, assert the exact text of the count cell (e.g. „2/3"), the score cell with a decimal
  comma (e.g. „16,5/22") and the % cell (e.g. „75%"). *Mutants:* drop `|marks` from the score cell → red
  („16.5"); swap the score and % cells → red; drop the `%` sign → red.
- **T5c** — row order and indent: for a course with parts, the table body's sequence of (title,
  `results-table__dN` class) pairs is the total first, then the pruned tree in pre-order with each
  class equal to the node's `depth`. *Mutant:* derive the class from `ContentNode.RANK` instead of
  `depth` (differs in a course without parts) → red; include a course without parts.
- **T5d** (e2e) — the class name is not enough: at 1280px, ~600px and 390px (whole-pixel Playwright
  viewports), each d(N+1) title cell's computed `padding-inline-start` is larger than the d(N) cell's, and
  equals §2.3's table value for that band. *A/B:* lower the depth selector to `.results-table__d1` (0,1,0)
  so the base rule out-ranks it → red; remove the `max-width:640px` depth rules → red at ~600px; move the
  `max-width:640px` block **above** the unconditional rules → red at ~600px (order decides).
- **T5e** — the table's status cells show the right pill per status: a not-started, an in-progress and
  an awaiting-review quiz render `pill--none`, `pill--progress` and `pill--awaiting` respectively (the
  last with its „Sprawdź" link). *Mutant:* drop the `{% with p=item.pill %}` → red (all `pill--none`).
- **T5** — `counted` leaves out a submitted quiz with `max_score == 0` but keeps it in `quiz_total`.
  *Mutant:* in the container aggregation only, count a quiz as `counted` when its row's status is
  `submitted` (ignoring `shows_score`) → red, the heading shows 1/N instead of 0/N. (Dropping the conjunct
  from `quiz_score_view` itself would instead raise in `_pct(score, 0)`, a crash rather than the count
  this test targets.)
- **T6** — colour: a summary % cell's **and a quiz row's** % cell's inline background equals `band_style(percent,
  course_color_bands(course))["bg"]` for a course with **custom** bands. With the default bands, a
  hard-coded palette would pass. *Mutant:* use `default_color_bands()` → red. *Mutant:* paint only container nodes → red on the
  quiz row.
- **T7** — Progress mode renders no `results-table` class anywhere and still renders
  `ul.breakdown__tree` with `_breakdown_node.html` rows (the lesson ✓/○ markers are present). In the
  view's context the breakdown has **no `total` key**, and **no node** anywhere in the tree has any of the Results-only keys
  §2.1 lists — `quiz_total`, `counted`, `score_sum`, `max_sum`, `percent`, `summary`, `shows_score`,
  `score`, `max_score` — nor `color` / `text_color` — checked on each node dict's **own top-level keys**,
  walked through `children` only, never inside a node's nested `pill` dict (a scored Progress pill
  legitimately carries `percent`). *Mutant:* run the colour walk in both modes with
  `.get()` guards → red on the `color` check; run it unguarded → the Progress page 500s, red.
- **T8d** (view test, `tests/test_analytics_student_page.py`) — the scroll wrapper's markup on two
  fixtures of its own: with a maths quiz title (`has_math` true) the wrapper has `role="region"`,
  `tabindex="0"` and an `aria-labelledby` equal to the `<caption>`'s `id`; with no maths title it has none
  of the three attributes. *Mutants:* drop the `has_math` guard → red on the no-maths fixture; drop the
  caption `id` → red on the maths fixture.
- **T7b** — an empty Results view, in Polish: a course whose only units are lessons renders no table and
  shows „Ten kurs nie ma jeszcze quizów" inside `p.results-table-empty`.
- **T9** — heading and `<title>` in both modes, in Polish, for a female student („Wyniki — Anna
  Nowak"). On the student page the `<h1>` and `<title>`, and on the per-question page the back link,
  contain no „Wyniki ucznia". The assertion is **scoped to those three elements**: the per-question
  page body keeps „Odpowiedź ucznia", „Wybór ucznia" and „Odpowiedź ucznia:", which O7 does not cover.
- **T10** — the per-question back link reads „← Wyniki" / „← Postęp" to match the mode.
- **T10b** — the per-question header of a fully reviewed REVIEW-only quiz with `max_score > 0` shows
  „score / max pkt · %", the same figures as its table row. *Mutant:* in `_quiz_pill`, keep the old `row["graded"] and row["max_score"]` condition → red.
- **T10d** — the same quiz in **Progress** mode renders the scored pill („wynik 4/5 (80%)"), not
  „przesłano". Same mutant → red.
- **T10c** — maths-title markers in **Results mode**: the section `<th>`, a linked quiz `<th>` and an
  unlinked quiz `<th>` each carry `data-math-title` and `lang="{{ course.language }}"`, asserted
  separately; the „Cały kurs" `<th>` carries neither. The existing
  `tests/test_title_math_markers.py::test_analytics_breakdown_titles_are_marked` loads Progress mode
  only and stays as it is. *Mutant:* drop `data-math-title` from the linked-quiz title → red. The linked quiz in this fixture is
  a **scored** one, so a scored pill that lost `submission_pk` (and with it the link) also goes red.
- **T11** — the chip reads „lekcje: 1/2" on the teacher page and on the student outline, and **both** `locale/pl`
  and `locale/en` `.po` files (regenerated with `--no-obsolete`) have no `required` or `Student results`
  entry left.
- **T14** — O13: in Polish, the three msgids O13 names render their new msgstrs wherever they appear:
  the pill, the review queue, the per-question page, the student's `quiz_results.html` and
  `course_results.html`, and the question feedback. The test also renders `quiz_results.html` with one and with several
  pending questions and asserts the O14 plural forms. On those pages no „na ocenę" remains; the graded
  notification strings (`Quiz graded` etc.) stay unchanged.
- **T15** — O15: the student's own `course_results.html`, in Polish, shows „4 / 5" (not „przesłano — bez
  oceny") for a fully reviewed REVIEW-only quiz with `max_score > 0`, and still shows „przesłano — bez
  oceny" for a submitted quiz with `max_score == 0`. *Mutant:* keep the `row.graded` condition → red.
- **Constraint for every test:** assertions never rest on database ids (known trap).

**Existing tests written for the merged tree view.** Before writing new tests, the plan lists every
existing assertion on text or markup this spec changes (the Results-mode tree and pills, the heading,
the `<title>`, the back link, the lesson chip, the O13 strings), and says for each one whether it
is **re-pointed at Progress mode** (where `.breakdown-unit` still exists), **replaced** by a test named
here, or **retired**, with the reason. None is deleted silently. At least:
`tests/test_analytics_student_page.py` (pill selectors such as `.pill.pill--none`, and the
Results-mode prune tests) and `tests/test_e2e_analytics_student_pages.py` (the `.breakdown-unit` pill
and Review-link geometry, and its `_neutralise(".breakdown-unit .pill…")` A/B), plus
`tests/test_analytics_student_quiz.py` (it asserts „← Wyniki ucznia", and around its Results-mode
breakdown test selects `a.breakdown-unit__link`; **and** `test_t27_header_pill_matches_the_breakdown_pill_except_scored`
maps its `reviewed` fixture — a REVIEW-only quiz, fully reviewed, `max_score=1` — to `pill--submitted`,
with `test_t26_header_by_pill_kind` sharing that fixture: after §4 that quiz is **scored** on both the
header and the breakdown row, so its tuple is **replaced** by T10b/T10d and `reviewed` moves into
T27's "scored" part), `tests/test_e2e_analytics.py` (a
`breakdown-unit__link` selector), `tests/capture_title_math_screenshots.py` (its breakdown row shoots
Progress mode only; add a Results-mode row) and the heading/`<title>`
assertions in `tests/test_analytics_student_page.py` („Wyniki ucznia — Anna Nowak", „Wyniki ucznia ·").

e2e (Playwright, `tests/test_e2e_analytics_student_pages.py`):

- **T8a** — layout at 390px on a render with **no formula title** (an unbreakable KaTeX formula sets the
  title column's minimum width, which would make any share check meaningless): a depth-3 quiz title, a
  course-total row with a realistic wide sum („812,5/960,5": at least three integer digits plus a decimal
  on both sides), and an awaiting-review row with its „Sprawdź" link at depth 3.
  - No horizontal page scroll (`document.documentElement.scrollWidth` equals the viewport width), **and
    the table fits its wrapper** (`wrap.scrollWidth <= wrap.clientWidth`): without a formula the wrapper
    would otherwise absorb an overflowing table and hide the % column while the page check stays green.
    No A/B is claimed for the ≤480px density rules: the title cell's `overflow-wrap:anywhere` lets the
    table fit either way, so their effect is judged in the design-pass screenshots, not asserted. The
    wrapper-fit check is falsified instead by giving the title cell `white-space:nowrap` with the long
    depth-3 title → red (the table outgrows the wrapper).
  - The title column's measured width is at least **30%** of the table's (estimate with §2.4's ≤480px
    density ≈ 141px ≈ 39%). **30% is a floor**: the design-pass render on mat-pp data may confirm or raise
    it, never lower it; if the render falls below it despite §2.4's density, the plan stops and asks the
    owner (the remaining levers touch O1).
  - *A/B:* restore `white-space:nowrap` on `.results-table .pill` → red **on the title-share assertion**
    (a nowrap „oczekuje na sprawdzenie" pill ≈ 130px at .7rem would drop the title to ≈ 86px ≈ 24%). The
    correct build must clear 30% by at least 5 percentage points for this A/B to mean anything; the design
    pass confirms that margin first.
  - The score and % cells are single-line. ⚠️ Their content („812,5/960,5", „100%", and a heading's
    „12/15") has **no line-break opportunity** under Unicode line breaking (UAX #14 LB25), so removing
    `white-space:nowrap` likely changes nothing: the design pass runs that A/B first. If it does not go
    red, the nowrap on number cells is recorded as **defensive only** and the test keeps just the
    single-line assertion, without claiming an A/B.
- **T8b** — a separate render with a depth-3 quiz title containing a **long inline formula** (KaTeX
  loaded): the table may scroll inside `.results-table-wrap`, the **page** may not
  (`scrollWidth` equals the viewport width). No share or wrapping checks run on this render. *A/B:*
  remove `position:relative` from `.results-table-wrap` → the page scrolls sideways, red.
- **T8c** — at 1280px the score and % cells are right-aligned, measured on a cell whose text is
  **visibly narrower than its column** (a quiz row's „4/5" under the total's „812,5/960,5", and „8%" under
  „100%"): its text's right edge sits at the cell's content edge **and** the gap on its left is larger than
  zero. (The widest cell in a `width:1%` column touches both edges whatever the alignment.) *A/B:*
  neutralise `text-align:right` → red.
- **Every container row carries `results-table__section`**, summary or not (a single-quiz section is
  still a heading: tinted and bold, just with empty number cells). T13's fixture includes one of each.
- **T13** — a section row's computed background equals `--surface-base` (probe token) **and differs from
  a quiz row's effective background** (the table's `--surface-raised`), in both themes; a section row's
  `<th>` **and** count/score `<td>`, and the total row's `<th>`, are bold (weight ≥ 600); a quiz row's
  title `<th>` is **not** bold (weight < 600) and is start-aligned; the „Wynik" and „%" column headers are
  right-aligned, on a fixture where a data cell is wider than the header text in both columns
  („812,5/960,5", „100%"), measured by the header's left gap > 0; *A/B:* remove the
  `thead th.results-table__num` (0,2,2) rule → red. *A/B:* set the section background to `var(--surface-sunken)` → red on the token check; remove the
  table's `--surface-raised` background → red on the differs-from check in at least one theme. *A/B:*
  remove the section `font-weight` rule → red on the section `<th>`, `<td>` and total
  `<th>`; lower that rule's specificity to `.results-table__section th` (0,1,1) and place it **after** the
  reset (0,1,2) → red on the section `<th>` (specificity, not order, decides); remove the `tbody th` reset → red on the quiz `<th>` weight and alignment.
- **T13b** — at 1280px every status pill in the table is a single line (its height equals one line box).
  *A/B:* force `.results-table .pill{white-space:normal}` at desktop width → red.
- **T13d** — the border between the total row and the next row is 2px in `--border-strong` (computed on
  the total row's cells). *A/B:* remove the `.results-table__total` rule → red.
- **T13c** — a coloured % cell's computed background equals its band colour, not the section tint.
  *A/B:* remove the inline style on a coloured cell → red on the band check.

Screenshots (design pass, as in B11): mat-pp Results view, light and dark, 1280 and 390. Judge whether
the sums read clearly at full depth; that is the owner's stated worry.

---

## 8. Help and screenshots

`docs/help/teacher/drill-down.md`: the "Student results" section heading becomes "Results and
progress". `docs/help/teacher/drill-down.pl.md`: the „Wyniki ucznia" heading becomes „Wyniki i postęp",
and the image alt text `![Wyniki ucznia](…)` becomes `![Wyniki quizów w kursie](…)` (no „ucznia", O7). It describes the table, the sums on heading rows,
the course total and the colours, and in one sentence what the quiz fraction on a heading row means
(quizzes whose score is included / quizzes in the section; a quiz awaiting review is not yet included). In `drill-down.md` the **← Student results** link text becomes **← Results** / **← Progress**; in
`drill-down.pl.md` **← Wyniki ucznia** becomes **← Wyniki** / **← Postęp**. The English image alt text
"A student's results page" stays. The `drill-down.{en,pl}.png` capture shows Results mode: its entry in
`tests/capture_help_screenshots.py` passes `mode=results` and waits for `.results-table`, and its URL
helper `_u`'s `manage_analytics_student` branch appends `?mode=results` when a `mode` is given, as its
`manage_analytics` branch already does (today it reads only `username`, so the entry alone would still
open Progress mode and the wait would time out). Today the entry opens the page with no `mode`, i.e.
Progress, and waits for `.breakdown__tree`, which Results mode no longer renders.

**Review-queue help (O13).** `docs/help/teacher/quiz-review.pl.md` names the label: line 15
„**Oczekuje na ocenę**" becomes „**Oczekuje na sprawdzenie**", and line 5's „czekają na ocenę" becomes
„czekają na sprawdzenie", so the help matches the page. The plan greps `docs/help` for „na ocenę" and
„do oceny" and lists any other hit (only these two on 2026-09-17). The `quiz-review` help screenshots
(`review-queue.pl.png`, captured by `tests/capture_help_screenshots.py`) are re-captured, because the
Polish one shows the old label.

**Anchors.** Renaming the two help headings changes their generated anchors. The plan greps the repo
(templates, `docs/help`, `.py`) for `#student-results` and `#wyniki-ucznia` and updates any hit; none
was found on 2026-09-17.

---

## 9. Delivery

One PR, off `master`. Execution follows the previous plan's mechanics: a worktree, catalog procedure
with `--no-obsolete`, falsified tests, and a design-pass screenshot step on mat-pp data.

---

## 10. Risks

- **The grid and the page disagree on a number.** T1/T3/T4 compare against `build_results_matrix`
  itself rather than restating its rule, so a later change to the grid's rule turns them red instead
  of silently diverging.
- **O12/O13 change student-facing pages.** The outline chip and the review-waiting words change for every
  student. Screenshot the student outline, `quiz_results.html` and `course_results.html` too.
- **Reviews reversing owner rows.** Any spec-review or plan-review catch touching O1–O11 goes to the
  owner, never applied (a lesson from the previous spec).
