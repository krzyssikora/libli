# Student results page: a Results table with section sums — design

**Status:** draft for the owner's review, 2026-09-17. **No review round has run.** The owner-decisions
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

**Open questions for the owner:** none (Q1 → O12, Q2 → O10, both answered 2026-09-17).

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
  `max_score > 0`. It is **not** `_quiz_pill`'s `kind == "scored"`, which also requires `graded`
  (`has_auto`: at least one AUTO question). The grid counts a REVIEW-only quiz that is fully reviewed
  with `max_score > 0`. Under the pill rule its row would say „przesłano" while its marks sat in the
  heading's sum. The builder stamps each quiz node with `shows_score` (bool), `score`, `max_score` and
  `percent` from the `build_course_results` row, and the table reads those, never the pill kind.
  The reverse case (`graded`, but a stored `max_score == 0`) shows no score and is not counted, again
  matching the grid.
- `score_sum`, `max_sum` — Σ `score`, Σ `max_score` over the counted quizzes (`Decimal`).
- `percent` — `_pct(score_sum, max_sum)` when `max_sum > 0`, else `None`. This is the one percent rule
  the grid uses, so a heading's % equals the grid's Results cell for that section **by construction**.
- `summary` — `True` iff `quiz_total > 1` (O2). The template renders numbers only when it is true.

The wrapper gains `total`, built the same way over the whole pruned tree (`summary` true iff the
course has more than one quiz). Progress mode stamps none of these keys and returns no `total`, so
Progress is untouched (O5).

The per-quiz `score`, `max_score` and whether it counts are read from the **same
`build_course_results` rows** the pills are built from. There is no second query and no second
counting rule. `counted` (on containers) is exactly the number of quiz nodes below with
`shows_score` true.

**A summary section with no counted quiz.** When `summary` is true but `counted == 0` (every quiz below
is not started, in progress or awaiting review), the heading shows the count („0/3") and leaves the
score and % cells empty and uncoloured. It never renders „0/0". The course total follows the same rule.

⚠️ **Drafts.** The page calls the builder with `drafts="keep-with-data"`, exactly as the matrix does
(`views_analytics.py`, both call sites). The two therefore see the same quiz set, so the sums match
the grid's cells. A test pins this (§7, T4).

### 2.2 Colour (O4)

The view resolves `bands = course_color_bands(course)`, the same call the matrix makes, and paints
every `percent` it renders with `color_bands.band_style(percent, bands)`. It walks the pruned tree
**recursively** and sets `color` / `text_color` on **every node dict** that carries `percent` (quiz
nodes with `shows_score`, container nodes with `summary`), and on `breakdown["total"]`. The matrix's
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
| Course total (first row, only if `total.summary`) | „Cały kurs" | `counted/quiz_total` | `score_sum/max_sum` | coloured `percent` |
| Section heading with `summary` | section title | `counted/quiz_total` | `score_sum/max_sum` | coloured `percent` |
| Section heading without `summary` (one quiz below) | section title | empty | empty | empty |
| Quiz | quiz title (linked to the per-question page when it has a submission, as today) | **empty** when `shows_score`; otherwise the status pill (below) | `score/max` when `shows_score`, else empty | coloured `percent` when `shows_score`, else empty |

- **Status cell (a quiz row without a score):** the existing pill span for the row's status, rendered
  by including `_quiz_pill.html`: `pill--none` „nie rozpoczęto", `pill--progress` „w toku",
  `pill--awaiting` „oczekuje na sprawdzenie", `pill--submitted` „przesłano". Its `scored` branch never
  fires here, because a scored row leaves this cell empty. On an awaiting-review row the „Sprawdź" link
  (the `breakdown-unit__review` markup and URL, as today) follows the pill **on its own line** in the
  same cell. A REVIEW-only quiz that `shows_score` shows its score like any other row, with no pill.
- **Header:** `<thead>` with column headers „Quiz", „Quizy", „Wynik", „%". The second column's header
  counts quizzes, since that is what a heading row shows there; a quiz row puts its status in it.
- **What „1/3" means.** The fraction is **quizzes whose score is in the sum / quizzes in the section**.
  It is **not** "quizzes done": a submitted quiz still awaiting review is not in the numerator. The help
  page must say this in one sentence (§8), because a teacher will otherwise read „1/3" as "did 1 of 3".
  ⚠️ **Owner question:** O1 fixes the column's role ("quiz count or status"), but not which count. Is
  "counted in the sum" what the owner wants, or "submitted" (which would put awaiting-review quizzes in
  the numerator while their marks stay out of the sum)? This spec uses "counted in the sum", because it
  describes the numbers beside it.
  Final wording is in §5.
- **Headings are row headers:** `<th scope="row">` in the first cell of every heading row (quiz rows
  use a non-bold `<th scope="row">` too, §2.5), and a
  `results-table__section` class that gives the whole row a light neutral tint and bold text (O11
  rule 1). Quiz rows have plain `<td>` number cells.
- **Course total row:** marked up and styled exactly like a summary heading row: `<th scope="row">`,
  `results-table__section`, tint and bold. A `results-table__total` class only adds a slightly stronger
  bottom border to separate it from the first section. Its first cell reads „Cały kurs" at depth 0 and carries **neither** `lang="{{ course.language }}"` nor
  `data-math-title`: it is an interface string, not course content.
- **Indentation:** the first cell gets `padding-inline-start` from the node dict's **`depth`** (as
  `build_outline` stamps it: 0 for any root node, so in a course without parts a chapter is d0), not
  from its kind. Rows keep their own depth; they are **not** shifted under „Cały kurs", which is
  already set apart by its tint and border. The class is
  `results-table__d0` … `__d3`. `ContentNode.RANK` (part 0, chapter 1, section 2, unit 3) only bounds
  the maximum at 3.. No inline style.
- **Numbers:** marks go through the `marks` filter (decimal comma in Polish, #327). Percent renders as
  `{{ percent }}%`. An empty summary cell is empty; it never shows „—".
- **Maths in titles:** the title cells keep `lang` and `data-math-title`, as the breakdown rows do, and
  `has_math` is still computed from the pruned tree.
- **Colour cells:** `style="background:…;color:…"` from §2.2, the same inline pattern as
  `_analytics_cell.html`.

**Empty Results view.** If the pruned tree is empty (the course has no visible quiz), no table is
rendered. Instead the page shows `<p class="helptext">{% trans "No quizzes in this course yet" %}</p>`
under the view switch. That msgid **already exists** (it is used by `course_results.html`).

### 2.4 CSS

Every rule goes in `core/static/core/css/app.css`: the student page links no page stylesheet (known
trap, previous spec §2). No stylesheet line citations anywhere.

- `.results-table { width:100%; border-collapse:collapse; }`. Cells get `padding` and a
  `border-top:1px solid var(--border-subtle)`.
- The title column takes the free width and wraps (`overflow-wrap:anywhere`). The score and %
  columns are `width:1%; white-space:nowrap; text-align:right`.
- The **status column may wrap** (`width:1%`, `white-space:normal`, so it takes only what it needs).
  The pill itself keeps `white-space:nowrap`, and the „Sprawdź" link is `display:block`. Its longest
  content is „oczekuje na sprawdzenie" plus „Sprawdź".
- `.results-table__section` gets `background: var(--surface-sunken)` and `font-weight:600`. A coloured
  % cell's inline background paints over it, which is intended.
- **Phone (≤ 640px):** the table stays a table. Only the title wraps, and the three number columns
  shrink to their content. At 390px a 4-level title plus „16,5/22" and „100%" must not scroll the page
  sideways (T8).

### 2.5 Accessibility

- `<caption class="sr-only">` naming the table, e.g. „Wyniki quizów".
- Headings **and quiz titles** are `<th scope="row">` (quiz titles not bold), so a screen reader names
  every row while moving across its cells. The column headers are `<th scope="col">`.
- The section hierarchy is shown visually (indent, tint) and is **deliberately not** exposed as ARIA
  tree structure: row headers plus the section names read in document order are enough, and
  `aria-level` on table rows is poorly supported.
- Colour is never the only carrier: the % text is always present.
- A heading row with no summary has empty cells. It gets no „brak" text, because a screen reader
  reads the quiz row just below it.

---

## 3. Headings and labels (O6–O8)

### 3.1 Student page heading (O7)

`<h1>` reads `{% trans "Results" %} — {{ student.list_display_name }}` in Results mode and
`{% trans "Progress" %} — …` in Progress mode. It reuses the existing msgids („Wyniki", „Postęp"),
the same words the switch under the heading uses. `<title>` follows the same pattern, one per mode:
`{% trans "Results" %} · {{ student.list_display_name }} · {{ course.title }} · libli` and
`{% trans "Progress" %} · {{ student.list_display_name }} · {{ course.title }} · libli`.

### 3.2 Per-question back link (O8)

`analytics_student_quiz.html`'s back link reads `← {% trans "Results" %}` or `← {% trans "Progress" %}`
for the mode in `_drill_params`. The view already parses `mode` there. The `Student results` msgid
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
- ⚠️ **Exception: the per-question header's score follows §2.1's rule.** Today
  `analytics_student_quiz` shows „4 / 5 pkt · 80%" only when `p.kind == "scored"`, which needs an AUTO
  question. Left alone, a fully reviewed REVIEW-only quiz would show „4/5 · 80%" in the table and
  „przesłano" one click away. The header therefore shows the score whenever the row is counted and
  `max_score > 0` (the same `shows_score` predicate, taken from one shared helper in `rollups.py`, not
  re-derived), and falls back to the pill otherwise. Test **T10b**.
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

Reused, never re-created (all verified present in `locale/pl` on 2026-09-17): `Quiz` („Quiz"),
`Quizzes` („Quizy"), `Score` („Wynik") for the column headers; `Results` („Wyniki"), `Progress`
(„Postęp"); the pill status words `not started` („nie rozpoczęto"), `in progress` („w toku"),
`awaiting review` („oczekuje na ocenę"), `submitted` („przesłano"); `Review` („Sprawdź").
The status words above include `awaiting review`, whose msgstr O13 changes.
Dropped as unused: `Student results`, `required`.

Changed msgstr only (O13), msgids untouched: `Awaiting review` → „Oczekuje na sprawdzenie" (review queue, per-question page, the student's own `quiz_results.html`), `awaiting review` → „oczekuje na sprawdzenie" (pill), `Submitted for review` → „Przesłano do sprawdzenia" (the student's question feedback). `Awaiting review` also renders on the student's own **`course_results.html`**, so the change reaches that page too.

⚠️ **Owner question (not applied, because O13 is protected).** `quiz_results.html` also shows two
**plural** entries, `%(n)s question awaiting review (up to 1 more mark)` and `… (up to %(m)s more
marks)`. Their six Polish forms say „oczekuje/oczekują na ocenę", and they are not in O13's list.
Should they say „oczekuje/oczekują na sprawdzenie" as well? Until the owner answers, the plan changes
only the three msgids O13 names, and T14 asserts only those. The **graded** msgids (`Your quiz was graded`, `Quiz graded`, `submitted — not graded`) keep „ocena": grading is what they mean.
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
  a top-level section **and** a nested one. Call `build_results_matrix(..., values="raw")`: its cells
  carry only `percent` and `label`, and only raw mode puts the marks in `label`. Compare `percent`
  directly, and compare `label` with `f"{_fmt_mark(score_sum)}/{_fmt_mark(max_sum)}"`, so that a wrong
  sum which happens to round to the same % still goes red. Include a not-started, an in-progress and an awaiting-review quiz,
  which both must leave out. *Mutant:* count awaiting-review scores → red.
- **T1b** — a REVIEW-only quiz, fully reviewed, with `max_score > 0`: its row shows `score/max` and a
  %, and its marks are in the heading's sum, matching the grid. *Mutant:* decide the row's score by
  `pill.kind == "scored"` → red.
- **T1c** — a summary section with no counted quiz renders „0/N" with empty, uncoloured score and %
  cells, never „0/0". The same holds for the course total.
- **T2** — `summary` only when `quiz_total > 1`: a section with one quiz renders an empty count, score
  and % in its heading row. *Mutant:* `>= 1` → red.
- **T3** — the course total row is first and matches the grid's `overall` cell for the student, compared
  the same way as T1 (raw mode, `percent` and `label`). A course with **exactly one quiz** renders
  **no** total row. *Mutant:* `total.summary` true for `>= 1` quiz → red.
- **T4** — drafts: a draft quiz with data counts on both pages, and a draft quiz without data on
  neither. *Mutant:* call the builder with `drafts="hide"` → red.
- **T5** — `counted` leaves out a submitted quiz with `max_score == 0` but keeps it in `quiz_total`.
- **T6** — colour: a summary % cell's **and a quiz row's** % cell's inline background equals `band_style(percent,
  course_color_bands(course))["bg"]` for a course with **custom** bands. With the default bands, a
  hard-coded palette would pass. *Mutant:* use `default_color_bands()` → red. *Mutant:* paint only container nodes → red on the
  quiz row.
- **T7** — Progress mode renders no `results-table` class anywhere and still renders
  `ul.breakdown__tree` with `_breakdown_node.html` rows (the lesson ✓/○ markers are present).
- **T7b** — an empty Results view: a course whose only units are lessons renders no table and shows the
  „No quizzes in this course yet" text.
- **T9** — heading and `<title>` in both modes, in Polish, for a female student („Wyniki — Anna
  Nowak"), with no „ucznia" anywhere on either page.
- **T10** — the per-question back link reads „← Wyniki" / „← Postęp" to match the mode.
- **T10b** — the per-question header of a fully reviewed REVIEW-only quiz with `max_score > 0` shows
  „score / max pkt · %", the same figures as its table row. *Mutant:* keep `p.kind == "scored"` → red.
- **T11** — the chip reads „lekcje: 1/2" on the teacher page and on the student outline, and the `.po`
  has no `required` or `Student results` entry left.
- **T14** — O13: in Polish, the three msgids O13 names render their new msgstrs wherever they appear:
  the pill, the review queue, the per-question page, the student's `quiz_results.html` and
  `course_results.html`, and the question feedback. The test asserts **those strings**, not the absence
  of „ocenę", because the plural entries are an open owner question. The graded notification strings
  stay unchanged.
- **Constraint for every test:** assertions never rest on database ids (known trap).

**Existing tests written for the merged tree view.** Before writing new tests, the plan lists every
existing assertion on text or markup this spec changes (the Results-mode tree and pills, the heading,
the `<title>`, the back link, the lesson chip, the O13 strings), and says for each one whether it
is **re-pointed at Progress mode** (where `.breakdown-unit` still exists), **replaced** by a test named
here, or **retired**, with the reason. None is deleted silently. At least:
`tests/test_analytics_student_page.py` (pill selectors such as `.pill.pill--none`, and the
Results-mode prune tests) and `tests/test_e2e_analytics_student_pages.py` (the `.breakdown-unit` pill
and Review-link geometry, and its `_neutralise(".breakdown-unit .pill…")` A/B), plus
`tests/test_analytics_student_quiz.py` (it asserts „← Wyniki ucznia") and the heading/`<title>`
assertions in `tests/test_analytics_student_page.py` („Wyniki ucznia — Anna Nowak", „Wyniki ucznia ·").

e2e (Playwright, `tests/test_e2e_analytics_student_pages.py`):

- **T8** — at 390px there is no horizontal page scroll with a depth-3 quiz title, wide numbers
  („16,5/22", „100%") **and an awaiting-review row with its „Sprawdź" link at depth 3**. The score and %
  columns do not wrap, and the title column keeps a usable width (at least 40% of the table). At 1280px, number columns are right-aligned. A/B: neutralise
  `white-space:nowrap` → red.
- **T13** — a section row's computed background equals `--surface-sunken` (probe token) and its first
  cell is bold. A coloured % cell's background equals its band colour, not the tint.

Screenshots (design pass, as in B11): mat-pp Results view, light and dark, 1280 and 390. Judge whether
the sums read clearly at full depth; that is the owner's stated worry.

---

## 8. Help and screenshots

`docs/help/teacher/drill-down.md`: the "Student results" section heading becomes "Results and
progress". `docs/help/teacher/drill-down.pl.md`: the „Wyniki ucznia" heading becomes „Wyniki i postęp",
and the image alt text `![Wyniki ucznia](…)` becomes `![Wyniki quizów w kursie](…)` (no „ucznia", O7). It describes the table, the sums on heading rows,
the course total and the colours, and in one sentence what the quiz fraction on a heading row means
(quizzes whose score is included / quizzes in the section; a quiz awaiting review is not yet included). The **← Student results** link text changes to „← Wyniki" /
„← Postęp". The `drill-down.{en,pl}.png` capture shows Results mode.

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
