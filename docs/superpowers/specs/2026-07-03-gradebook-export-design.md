# Gradebook export — design

*Drafted 2026-07-03. First slice of the roadmap's deferred **Exports (CSV / printable
gradebook)** capability. Lets a teacher / course admin download or print their
students' course results from the analytics matrix page.*

Companion docs: [`../../roadmap.md`](../../roadmap.md) (Deferred → Exports row),
the Phase 3c analytics specs (the substrate this rides on).

---

## 1. Goal & scope

A teacher, course admin, or platform admin — anyone with review reach on a course —
can export their students' results as a **CSV**, an **XLSX (Excel)**, or a
**print-optimised HTML page** (browser → paper or Save-as-PDF). Two gradebook
**shapes** are offered:

- **Matrix mirror** — exactly what the analytics matrix currently shows: students ×
  the current columns (which may be aggregated Parts/Chapters), per-cell `%`,
  per-student overall `%`, per-column averages. Honours the on-screen scope, mode
  (Progress/Results), and expand state.
- **Quiz gradebook (raw marks)** — one column per **quiz leaf unit**, each cell the
  student's raw earned marks, the quiz's max in a dedicated **Max** row, a per-student
  **Total**, and a per-quiz class **Average**. This is the school-register format.

Both shapes reuse the existing scope resolution and permission gate, so an export can
never reveal a student outside the exporter's reach.

**Non-goals (YAGNI, deferrable later):** server-side PDF generation; scheduled or
emailed exports; per-question (element-level) breakdown; cross-course gradebooks;
the SIS/e-register webhook (a separate deferred capability).

---

## 2. Architecture

All new code lives in `courses/`, mirroring where analytics already sits
(`views_analytics.py`, `rollups.py`, `color_bands.py`). No new Django app.

Three focused files plus a template and a view:

| File | Responsibility | Purity |
|---|---|---|
| `courses/gradebook.py` | The two **builders** → one neutral `Table` dict | Pure (takes an already-scoped `students` queryset; no permission logic) |
| `courses/exporters.py` | The three **renderers** (CSV / XLSX / HTML) → `HttpResponse`/context | Pure of DB (consumes a `Table`) |
| `courses/views_export.py` | One thin **view** — gate, scope, dispatch | Impure (DB + auth) |
| `templates/courses/manage/gradebook_print.html` | The print page | — |

### The shared `Table` structure

Both builders emit the same dict; all three renderers consume only this. Adding a
format never touches a builder; adding a shape never touches a renderer. This is the
key isolation boundary.

```python
Table = {
  "title":    str,              # "Algebra I — Group B — Results"  — SET BY THE VIEW (see §3, §5)
  "subtitle": str,              # e.g. "Generated 2026-07-03 · Scope: Group B" — SET BY THE VIEW
  "columns": [                  # data columns, after the two identity columns
     {"label": str, "max": Decimal|None, "kind": "score"|"percent"},
  ],
  "total_kind": "score"|"percent",   # how renderers format the per-row Total + footer totals
  "meta_row": {"label": str, "values": [Decimal|None, ...], "total": Decimal|None} | None,  # the "Max" row (quiz shape); None for matrix
  "rows": [                     # one per student, already ordered by username
     {"name": str, "username": str,
      "cells": [int|Decimal|str|None, ...],   # aligned with columns (matrix % stored as int; quiz score as Decimal; markers as str)
      "total": int|Decimal|str|None},
  ],
  "footer": [                   # summary rows (e.g. class Average)
     {"label": str, "values": [int|Decimal|str|None, ...], "total": int|Decimal|str|None},
  ],
}
```

Identity columns (`Name`, `Username`) are implied and rendered by every renderer;
they are not part of `columns`. `name` is the student's `display_name` falling back
to `username` (`accounts.User.__str__` already does this); `username` is the stable
disambiguator.

**`title`/`subtitle` are populated by the view, not the builders** (§3). The builders
have no access to `request`, the human-readable scope label, or the current date, so
they leave these two keys empty (`""`) and the view fills them after building — see §5.
`total_kind` is `"percent"` for the matrix shape and `"score"` for the quiz shape;
every renderer formats the Total column and footer totals by it (I3), since the Total is
not part of `columns` and so has no per-column `kind` of its own.

---

## 3. The builders (`courses/gradebook.py`)

Both take `course` and an already-scoped, already-ordered `students` iterable. Neither
knows about `request`, permissions, or scope strings; both leave `title`/`subtitle`
empty for the view to fill (§2, §5). The `students` iterable the view passes has
**already had any on-screen cherry-pick subset applied** (Phase 3c-iii-b, §5), so the
builders never re-derive scope or subset — they just tabulate exactly the students they
are handed.

### 3.1 `build_matrix_table(course, students, mode, expanded)`

Pure re-shaping of the existing matrix — **no new aggregation**.

1. Call `build_progress_matrix(course, students, expanded)` or
   `build_results_matrix(course, students, expanded)` per `mode`.
2. `columns` ← the matrix's **current frontier `columns`** (`_public_columns` shape —
   aggregated Part/Chapter columns when un-expanded, leaf units where expanded, exactly
   the on-screen set), each `{"label": title, "max": None, "kind": "percent"}`.
3. `meta_row` ← `None` (percent columns need no Max row).
4. `rows` ← for each matrix row: `cells` are the per-column **integer percent**
   (e.g. `85`, or `None` for the neutral `—`); `total` ← the row's `overall` integer
   percent. The value stored is always the whole number; each renderer formats it per
   the column `kind` (§4) — `None` never becomes `0`.
5. `footer` ← a single **Average** row from the matrix `averages` + `overall_average`.
6. `total_kind` ← `"percent"`. (`title`/`subtitle` are left empty — the view fills them.)

Because it linearizes the *already-computed* matrix over the **same students the view
resolved** (scope ∩ subset), the export matches the screen cell-for-cell, including the
current expand frontier and the active cherry-pick subset (the matrix averages are over
that subset, and so are the export's — §5, §6 thread the `student` param). "Flatten" here
means **dropping the multi-row nested `header_rows`** (a spreadsheet has no rowspans),
**not** reducing to leaf units — the frontier columns are kept exactly as on screen, each
labelled by its own `title`. When a frontier column's title is ambiguous out of context,
that ambiguity already exists on screen and is accepted for the matrix shape (the quiz
shape below disambiguates explicitly).

### 3.2 `build_quiz_gradebook(course, students, numbers_only)`

New aggregation, assembled from primitives already in `rollups.py` (no duplication of
the counting rule):

1. `units = quiz_units_in_order(course)` — quiz **leaf** units in outline order.
2. **Column Max — a new helper `quiz_gradeable_max(units)`** in `rollups.py`. There is
   no existing primitive that yields a quiz's max independent of a submission, so this is
   new (small) aggregation. It returns `{unit_id: Decimal}` where each value is the sum
   of the **per-question `max_marks`** (the field on `QuestionElement`) over that unit's
   `AUTO` **and** `REVIEW` questions, **excluding `NOT_MARKED`** — i.e. the "fully
   gradeable maximum", matching `compute_scores`'s `possible` for a fully-reviewed
   submission (`courses/quiz.py:92`). Computed by one batched Element scan over all
   `unit_pks` (mirrors `_quiz_review_maps`'s query — no N+1), **not** from submissions
   (so a quiz with zero submissions still has a Max).
3. `columns` ← one per quiz unit: `label` = an **ordinal-prefixed title**
   (`f"{i}. {unit.title}"`, `i` 1-based in outline order) so duplicate "Quiz" titles
   stay unique in a CSV/register; `max` = `quiz_gradeable_max(units)[unit.pk]`; `kind`
   = `"score"`. A column whose `max` is `0` is a **non-gradeable column** (no AUTO/REVIEW
   questions): it still appears (the register shows the quiz exists) but every cell is
   blank and it is excluded from Totals and Averages (step 6/7).
4. `meta_row` ← `{"label": _("Max"), "values": [col["max"] for col in columns],
   "total": <sum of gradeable-column maxes>}` (the dedicated **Max** row; its `total` is
   the total marks available, the register denominator — non-gradeable `0` columns add
   nothing).
5. Fetch submissions once: `QuizSubmission.objects.filter(unit__in=units,
   student__in=students)`, keyed `(student_id, unit_id)`. Compute
   `_quiz_review_maps` + `submission_is_counted` **once** over the whole set (same
   batched approach as `build_results_matrix`; no N+1).
6. For each student, look up the submission in the `(student_id, unit_id)` map and
   resolve the cell **in this order**, keyed on `QuizSubmission.Status`
   (`courses/models.py`):
   - **non-gradeable column** (`col.max == 0`) → always blank (no numeric mark exists),
     regardless of submission state.
   - **no row in the map** (never started) → marker `—` (or blank if `numbers_only`).
   - **`status == IN_PROGRESS`** → marker `…` (or blank if `numbers_only`).
   - **`status == SUBMITTED` and `submission_is_counted` false** (a pending `[R]`) →
     marker `R` (or blank if `numbers_only`). Consistent with the matrix rule that
     excludes awaiting-review from a final score.
   - **`status == SUBMITTED` and `submission_is_counted` true** (counted) → the raw
     **`sub.score`** (a `Decimal`; the per-submission cached earned total,
     `courses/quiz.py:130`). The cell basis is the cached `sub.score`, while the column
     Max is the *current* quiz definition; if a quiz is edited **after** a student
     submitted, the cell may not align with the Max (I5) — accepted, and mirrors the
     analytics matrix which also reads cached scores. `sub.score == 0` is a real mark (a
     bad result) and counts.

   The `—` marker deliberately matches the matrix's neutral `_cell` label
   (`rollups.py:437`) so a mixed export reads consistently. Note this builder makes a
   **three-way** non-counted distinction (`—` / `…` / `R`) that the matrix collapses to
   a single neutral cell — that is intentional (a register wants to see *why* a mark is
   missing).
7. `row.total` = sum of the student's **counted `sub.score`** over gradeable columns
   only; markers and non-gradeable columns never contribute. Blank if the student has no
   counted score in any gradeable column.
8. `footer` ← a single **Average** row, **participants-only** (matching the matrix's
   `_avg_cell`, `rollups.py:440`, which averages only non-`None` values): per **gradeable**
   quiz column, the mean of counted `sub.score` **over the students who have a counted
   submission in that column** (denominator = count of counted submissions, *not* the
   count of shown students; blank when no student has a counted score); non-gradeable
   columns render blank; `total` = mean of the student `row.total` values **over the
   students who have a numeric total** — the same participants-only basis. `total_kind`
   ← `"score"`.

`numbers_only` only ever blanks the **markers**; it never blanks or alters a real
numeric score. Its default is `False` (markers shown).

---

## 4. The renderers (`courses/exporters.py`)

Each consumes a `Table` and is DB-free. Two (`to_csv`, `to_xlsx`) take only the `Table`
+ filename; the HTML renderer additionally takes `request` (it needs it for
`render()`/i18n), which is still DB-free — the isolation boundary is "no queries", not
"no `request`".

### 4.1 `to_csv(table, filename) -> HttpResponse`

`csv.writer` over an `HttpResponse(content_type="text/csv")` with
`Content-Disposition: attachment; filename="…"`. A **UTF-8 BOM** (`﻿`) is written
first so Excel on a Polish Windows opens accented names in the right encoding. Row
order: title line; **subtitle line** (provenance — generated date + resolved scope, for
parity with XLSX/HTML); blank; header (`Name`, `Username`, then column labels, then
`Total`); the Max meta row if present (identity columns blank, its `total` in the Total
column); one row per student; footer rows. Cell formatting by column `kind` (and by
`table["total_kind"]` for the Total column + footer totals): `score` → plain number
string (`Decimal`); `percent` → the integer percent with a trailing `%` (e.g. `85%`),
matching the on-screen matrix. `None`/blank cells → empty string.

**CSV formula-injection guard.** Because the CSV is explicitly optimised to open in
Excel/LibreOffice and carries user-authored strings (`display_name`, unit/quiz titles),
any **text** cell whose first character is `= + - @` (or a leading Tab / CR) is
neutralised by prefixing a single apostrophe `'`, so a name like `=cmd()` cannot execute
on open. This applies to text cells only — numeric score/percent cells are unaffected.
Covered by a test (§7).

### 4.2 `to_xlsx(table, filename) -> HttpResponse`

Via **`openpyxl`** (pure-Python, no system libraries; added with `uv add openpyxl`).
`content_type =
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, attachment
disposition. One worksheet named after the shape.

- Title + subtitle in the first rows.
- Bold header row; **freeze panes** below the header and right of the identity columns
  so a big class scrolls cleanly.
- **Score cells** (`kind == "score"`, incl. a `score` Total column) **written as real
  numbers** (not strings) so a teacher can sum/average them in Excel. **Percent cells**
  (`kind == "percent"`) are written as the fractional value (integer percent ÷ 100)
  carrying a `0%` number format, so the cell *displays* `85%` while holding `0.85` — this
  is for correct display, not because summing a percent column is meaningful. Markers and
  blanks are text/empty. The Total column + footer totals follow `table["total_kind"]`.
- Max/Average summary rows styled (bold/italic) but numeric where numeric.

### 4.3 `render_gradebook_print(request, table) -> HttpResponse`

Renders `templates/courses/manage/gradebook_print.html`: a standalone print-optimised
page — course/institution header (title + subtitle), the full table, and a **Print**
button the teacher clicks (we do **not** auto-fire `window.print()`). `@media print`
CSS hides nav/buttons, forces black-on-white, repeats `<thead>` across pages, and
avoids row page-breaks. Save-as-PDF is the browser's job — no server PDF dependency.
This template follows the existing `courses/manage/` styling conventions and ships
styled (per the project's "every view ships styled" rule), verified light + dark and
in print preview via a throwaway screenshot harness.

### Filenames

`{slug}-{shape}-{mode?}-{numbers?}-{YYYY-MM-DD}.{ext}`, e.g.
`algebra-i-quiz-2026-07-03.xlsx`, `algebra-i-quiz-numbers-2026-07-03.xlsx` (a
`numbers` token is appended for the quiz shape when `numbers_only` is set, so the two
quiz variants don't collide on the same day), or `algebra-i-matrix-results-2026-07-03.csv`.
The date is passed in **from the view** (`django.utils.timezone.localdate()`), never
computed in the renderer, and the slug is sanitised to a safe filename token.

---

## 5. The view (`courses/views_export.py`) & URL

One endpoint:

```
GET manage/courses/<slug:slug>/analytics/export/
    ?shape=matrix|quiz
    &format=csv|xlsx|html
    &mode=progress|results        (matrix shape only)
    &scope=all|group:N|collection:N
    &expand=<pk>&expand=<pk>       (matrix shape only — mirrors on-screen frontier)
    &student=<pk>&student=<pk>     (cherry-pick subset — mirrors on-screen subset, Phase 3c-iii-b)
    &numbers_only=1                (quiz shape only)
```

`scoping` is imported from the **`grouping`** app (`from grouping import scoping`,
matching `views_analytics.py`) — it lives in `grouping/scoping.py`, not `courses/` (M1).

`@login_required`. Steps:

1. `course = get_object_or_404(Course, slug=slug)`.
2. `if not scoping.can_review_course(request.user, course): raise Http404` — same
   convention as `analytics_matrix`.
3. **Resolve the student set exactly as `analytics_matrix` does** (views_analytics.py:52-64):
   `pool = scoping.students_in_scope(request.user, course, scope)`; intersect a
   `student`-param subset with the pool's pks (`raw_subset & pool_pks`); the resulting
   `students` is `pool.filter(pk__in=subset).order_by("username")` when a valid subset is
   present, else `pool.order_by("username")`. This is the sole scope/subset gate — the
   export can never include a student outside the exporter's reach, and it matches the
   matrix's own averages basis (C3).
4. Coerce params to safe defaults exactly as `analytics_matrix` does
   (`shape` → `matrix`, `format` → `csv`, `mode` → `progress`, `scope` → `all`,
   unknown/junk `expand`/`student` dropped via the existing `_clean_expand` helper —
   factor it out of `views_analytics.py` to a shared import rather than duplicate).
5. Dispatch: `shape` → builder (`build_matrix_table` / `build_quiz_gradebook`), then
   `format` → renderer. `csv`/`xlsx` return attachments; `html` returns the print page.
6. **The view fills `title`/`subtitle`** on the returned `Table` (the builders leave them
   empty — §2, §3). The scope label is derived from the **resolved** scope, not the raw
   `scope` param: look it up in `scoping.analytics_scope_choices(...)`; a forged /
   out-of-reach scope that `students_in_scope` silently fell back to "all" is labelled
   **"All my students"**, never a group name the data doesn't actually reflect (I2). The
   same resolved label + `timezone.localdate()` feed the filename (§4).

New URL route `manage_analytics_export` next to the existing analytics routes in
`courses/urls.py`.

---

## 6. UI surface — Export panel on `analytics_matrix.html`

Alongside the existing scope / mode / colours controls, add an **Export** disclosure
(`<details>` — no new JS framework) containing a small GET form:

- **Shape** radio: *This matrix view* (uses current `mode` + `expand`) · *Quiz
  gradebook (raw marks)*.
- **Only numbers** checkbox with short helper text ("Leave the marks blank for
  not-taken / in-progress / awaiting-review, so the file imports cleanly into a
  register."). Relevant to the quiz shape only; progressive-enhancement JS
  enables/disables it with the shape radio, and the server ignores it for the matrix
  shape regardless. Default unchecked.
- Three submit buttons — **CSV**, **Excel (.xlsx)**, **Print** — each sets the
  `format` value and submits.

Hidden inputs carry the current `scope`, `mode`, `expand` pks, **and the `student`
cherry-pick subset pks** (Phase 3c-iii-b) so the export always matches what's on screen —
same students, same averages. The panel is plain HTML and fully functional **without
JS**; the only enhancement is the checkbox enable/disable, whose default-unchecked state
is safe.

---

## 7. Testing

pytest + factory_boy against real PostgreSQL (Phase-0 discipline). Bulk of coverage is
on the pure builders.

**Builders**
- `quiz_gradeable_max(units)`: sums `max_marks` over AUTO **and** REVIEW questions,
  excludes NOT_MARKED; a quiz of only NOT_MARKED questions → `0`; independent of any
  submission (a quiz with zero submissions still returns its max).
- `build_matrix_table`: linearized cells/total/averages match the underlying
  `build_progress_matrix` / `build_results_matrix` 1:1, for both modes and with an
  expand set applied; `total_kind == "percent"`.
- `build_quiz_gradebook`: raw `sub.score` for a counted submission; `—` / `…` / `R`
  markers for not-started / in-progress / awaiting-review; those markers blanked under
  `numbers_only` while real scores are untouched; correct **Max** row; ordinal
  disambiguation of duplicate titles; `total` = sum of counted scores over gradeable
  columns; **Max row** `total` = sum of gradeable-column maxes; the class **Average** is
  **participants-only** (a column with one 10/10 and two not-taken averages to `10`, not
  `10/3`); a **non-gradeable column** (`quiz_gradeable_max == 0`) appears but is all-blank
  and excluded from Total/Average; `total_kind == "score"`.
- Edge: course with zero quizzes; empty student set; a student with no submissions.

**Renderers**
- CSV parses back to the expected rows; BOM present; attachment header + content-type;
  subtitle line present; a `display_name`/title beginning with `= + - @` is apostrophe-
  neutralised (formula-injection guard) while numeric cells are untouched.
- XLSX loads via `openpyxl.load_workbook`; score cells are numeric (not text); percent
  cells carry the `0%` format; freeze panes set.
- HTML renders the print template containing the table.

**View / permissions**
- A group teacher's export contains only that group's students (scope enforcement);
  `can_review_course` failure → 404; unknown params coerce to defaults; each `format`
  returns the correct content-type.
- An export taken with a `student` cherry-pick subset active contains exactly that
  subset and averages over it (C3); a forged/out-of-reach `scope` yields the "All my
  students" label, not the forged group's name (I2); the view sets a non-empty
  `title`/`subtitle` on the `Table` (C1).

**i18n**
- EN vs PL requests produce localized headers (`Name`/`Imię`, `Max`, `Average`/`Średnia`,
  `Progress`/`Postępy`, `Results`/`Wyniki`) and the "Only numbers" helper text.

---

## 8. i18n

All headers, shape/format labels, the "Only numbers" helper text, and the printable
page chrome go through `gettext`, with EN + PL entries in `locale/*/LC_MESSAGES/`.
Follow the notifications-slice i18n discipline: after `makemessages`, clear spurious
`#, fuzzy` flags and verify new msgids by grep (the fuzzy re-mark + mis-guess gotcha).
Compile `.mo` before shipping.

Note: student `display_name` and quiz/unit **titles** are monolingual user content —
they appear verbatim in every locale, unchanged by this feature (consistent with the
rest of the app).

---

## 9. Dependencies & deploy

- **`openpyxl`** — new pure-Python dependency (`uv add openpyxl`). No system libraries,
  so no deploy/CI change beyond the lockfile. It is the only new runtime dependency.
- No new migrations (the feature is read-only over existing results data).

---

## 10. Edge cases (explicitly handled)

| Case | Behaviour |
|---|---|
| Course with zero quizzes | Quiz gradebook renders identity columns + empty Max row + no data columns; no crash. |
| Student with no submissions | All cells blank/markers; total blank. |
| Non-gradeable quiz column (`quiz_gradeable_max == 0`: no AUTO/REVIEW questions) | Column still appears; all its cells blank; excluded from Totals and Averages. |
| Quiz edited after a student submitted | Cell shows the cached `sub.score`; Max row shows the current gradeable max — they may not align (accepted; mirrors the analytics matrix reading cached scores). |
| Awaiting-review submission | `R` marker (or blank under `numbers_only`); excluded from Total/Average, matching the matrix. |
| Duplicate quiz titles | Ordinal-prefixed column labels keep headers unique. |
| Junk `expand` / `student` / `scope` / `format` params | Coerced to safe defaults (mirrors `analytics_matrix`). |
| Out-of-reach / forged `scope` | `students_in_scope` re-derives from the user's reach → falls back to "all my students"; the title/filename label reflects the **resolved** scope, never the forged one. |
| Accented names in Excel/CSV | UTF-8 BOM in CSV; XLSX is Unicode-native. |
