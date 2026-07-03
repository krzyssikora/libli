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
  "title":    str,              # "Algebra I — Group B — Results"  (course · scope · shape/mode)
  "subtitle": str,              # e.g. "Generated 2026-07-03 · Scope: Group B"  (for the print header)
  "columns": [                  # data columns, after the two identity columns
     {"label": str, "max": Decimal|None, "kind": "score"|"percent"},
  ],
  "meta_row": {"label": str, "values": [Decimal|None, ...]} | None,   # the "Max" row (quiz shape); None for matrix
  "rows": [                     # one per student, already ordered by username
     {"name": str, "username": str,
      "cells": [Decimal|str|None, ...],   # aligned with columns
      "total": Decimal|str|None},
  ],
  "footer": [                   # summary rows (e.g. class Average)
     {"label": str, "values": [Decimal|str|None, ...], "total": Decimal|str|None},
  ],
}
```

Identity columns (`Name`, `Username`) are implied and rendered by every renderer;
they are not part of `columns`. `name` is the student's `display_name` falling back
to `username` (`accounts.User.__str__` already does this); `username` is the stable
disambiguator.

---

## 3. The builders (`courses/gradebook.py`)

Both take `course` and an already-scoped, already-ordered `students` iterable. Neither
knows about `request`, permissions, or scope strings.

### 3.1 `build_matrix_table(course, students, mode, expanded)`

Pure re-shaping of the existing matrix — **no new aggregation**.

1. Call `build_progress_matrix(course, students, expanded)` or
   `build_results_matrix(course, students, expanded)` per `mode`.
2. `columns` ← the matrix's flat leaf `columns` (`_public_columns` shape), each
   `{"label": title, "max": None, "kind": "percent"}`.
3. `meta_row` ← `None` (percent columns need no Max row).
4. `rows` ← for each matrix row: `cells` are the per-column **integer percent**
   (e.g. `85`, or `None` for the neutral `—`); `total` ← the row's `overall` integer
   percent. The value stored is always the whole number; each renderer formats it per
   the column `kind` (§4) — `None` never becomes `0`.
5. `footer` ← a single **Average** row from the matrix `averages` + `overall_average`.
6. `title`/`subtitle` ← course title + scope label + `mode` label.

Because it linearizes the *already-computed* matrix, the export is guaranteed to match
the screen cell-for-cell, including the current expand frontier. Nested header rows are
**not** carried — the export flattens to leaf columns (a spreadsheet has no rowspans);
the leaf `title` alone labels each column. When a nested column's title is ambiguous
out of context, that ambiguity already exists on screen at the leaf level and is
acceptable for the matrix shape (the quiz shape below disambiguates explicitly).

### 3.2 `build_quiz_gradebook(course, students, numbers_only)`

New aggregation, assembled from primitives already in `rollups.py` (no duplication of
the counting rule):

1. `units = quiz_units_in_order(course)` — quiz **leaf** units in outline order.
2. `columns` ← one per quiz unit: `label` = an **ordinal-prefixed title**
   (`f"{i}. {unit.title}"`, `i` 1-based in outline order) so duplicate "Quiz" titles
   stay unique in a CSV/register; `max` = the quiz's summed `max_marks`; `kind` =
   `"score"`.
3. `meta_row` ← `{"label": _("Max"), "values": [col.max for col in columns]}`.
4. Fetch submissions once: `QuizSubmission.objects.filter(unit__in=units,
   student__in=students)`, keyed `(student_id, unit_id)`. Compute
   `_quiz_review_maps` + `submission_is_counted` **once** over the whole set (same
   batched approach as `build_results_matrix`; no N+1).
5. For each student, each quiz cell resolves to:
   - **counted** submission → the raw `score` (a `Decimal`).
   - **not started / no submission** → marker `–` (or `None`/blank if `numbers_only`).
   - **in progress** → marker `…` (or blank if `numbers_only`).
   - **awaiting review** (submitted but a pending `[R]`) → marker `R` (or blank if
     `numbers_only`). Consistent with the matrix rule that excludes awaiting-review
     from a final score.
   - **submitted + counted but ungraded** (`max_marks == 0`, no auto questions) →
     blank in both modes (there is no numeric mark to show; it still counts as done).
6. `row.total` = sum of the student's **counted** scores (`Decimal`); markers never
   contribute. Blank if the student has no counted score.
7. `footer` ← a single **Average** row: per quiz column, the mean of counted scores
   across the shown students (blank where no student has a counted score); `total` =
   mean of student totals.

`numbers_only` only ever blanks the **markers**; it never blanks or alters a real
numeric score. Its default is `False` (markers shown).

---

## 4. The renderers (`courses/exporters.py`)

Each consumes a `Table`. Pure of DB.

### 4.1 `to_csv(table, filename) -> HttpResponse`

`csv.writer` over an `HttpResponse(content_type="text/csv")` with
`Content-Disposition: attachment; filename="…"`. A **UTF-8 BOM** (`﻿`) is written
first so Excel on a Polish Windows opens accented names in the right encoding. Row
order: title line; blank; header (`Name`, `Username`, then column labels, then
`Total`); the Max meta row if present (identity columns blank); one row per student;
footer rows. Cell formatting by column `kind`: `score` → plain number string
(`Decimal`); `percent` → the integer percent with a trailing `%` (e.g. `85%`), matching
the on-screen matrix. `None`/blank cells → empty string.

### 4.2 `to_xlsx(table, filename) -> HttpResponse`

Via **`openpyxl`** (pure-Python, no system libraries; added with `uv add openpyxl`).
`content_type =
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, attachment
disposition. One worksheet named after the shape.

- Title + subtitle in the first rows.
- Bold header row; **freeze panes** below the header and right of the identity columns
  so a big class scrolls cleanly.
- **Score cells written as real numbers** (not strings) so Excel sums them; **percent
  cells** written as the fractional value (the integer percent ÷ 100) carrying a `0%`
  number format, so the cell *displays* `85%` while summing as `0.85`; markers and
  blanks are text/empty.
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

`{slug}-{shape}-{mode?}-{YYYY-MM-DD}.{ext}`, e.g.
`algebra-i-quiz-2026-07-03.xlsx` or `algebra-i-matrix-results-2026-07-03.csv`. The date
is passed in **from the view** (`django.utils.timezone.localdate()`), never computed in
the renderer, and the slug is sanitised to a safe filename token.

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
    &numbers_only=1                (quiz shape only)
```

`@login_required`. Steps:

1. `course = get_object_or_404(Course, slug=slug)`.
2. `if not scoping.can_review_course(request.user, course): raise Http404` — same
   convention as `analytics_matrix`.
3. `students = scoping.students_in_scope(request.user, course, scope).order_by("username")`
   — identical resolution to the matrix view; the sole scope gate. An export therefore
   can never include a student outside the exporter's reach.
4. Coerce params to safe defaults exactly as `analytics_matrix` does
   (`shape` → `matrix`, `format` → `csv`, `mode` → `progress`, `scope` → `all`,
   unknown/junk `expand` dropped via the existing `_clean_expand` helper — factor it to
   a shared import rather than duplicate).
5. Dispatch: `shape` → builder (`build_matrix_table` / `build_quiz_gradebook`), then
   `format` → renderer. `csv`/`xlsx` return attachments; `html` returns the print page.

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

Hidden inputs carry the current `scope`, `mode`, and `expand` pks so the export always
matches what's on screen. The panel is plain HTML and fully functional **without JS**;
the only enhancement is the checkbox enable/disable, whose default-unchecked state is
safe.

---

## 7. Testing

pytest + factory_boy against real PostgreSQL (Phase-0 discipline). Bulk of coverage is
on the pure builders.

**Builders**
- `build_matrix_table`: linearized cells/total/averages match the underlying
  `build_progress_matrix` / `build_results_matrix` 1:1, for both modes and with an
  expand set applied.
- `build_quiz_gradebook`: raw score for a counted submission; `–` / `…` / `R` markers
  for not-started / in-progress / awaiting-review; those markers blanked under
  `numbers_only` while real scores are untouched; correct **Max** row; ordinal
  disambiguation of duplicate titles; `total` = sum of counted; class **Average** row;
  ungraded-but-submitted (`max_marks == 0`) counts as done and shows blank.
- Edge: course with zero quizzes; empty student set; a student with no submissions.

**Renderers**
- CSV parses back to the expected rows; BOM present; attachment header + content-type.
- XLSX loads via `openpyxl.load_workbook`; score cells are numeric (not text); percent
  cells carry the `0%` format; freeze panes set.
- HTML renders the print template containing the table.

**View / permissions**
- A group teacher's export contains only that group's students (scope enforcement);
  `can_review_course` failure → 404; unknown params coerce to defaults; each `format`
  returns the correct content-type.

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
| Ungraded submitted quiz (`max_marks == 0`, no auto questions) | Counts as done; contributes 0; shown blank (both modes). |
| Awaiting-review submission | `R` marker (or blank under `numbers_only`); excluded from total, matching the matrix. |
| Duplicate quiz titles | Ordinal-prefixed column labels keep headers unique. |
| Junk `expand` / `scope` / `format` params | Coerced to safe defaults (mirrors `analytics_matrix`). |
| Out-of-reach `scope` | `students_in_scope` re-derives from the user's reach → falls back to "all my students". |
| Accented names in Excel/CSV | UTF-8 BOM in CSV; XLSX is Unicode-native. |
