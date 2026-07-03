# Gradebook Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a teacher / course admin / platform admin export their students' course results from the analytics-matrix page as CSV, XLSX, or a print-optimised HTML page, in two shapes (matrix-mirror and per-quiz raw marks).

**Architecture:** Two pure builders in `courses/gradebook.py` produce one neutral `Table` dict (matrix-mirror reshapes the existing analytics matrix; quiz gradebook aggregates per-quiz raw marks via a new `quiz_gradeable_max` helper in `rollups.py`). Three DB-free renderers in `courses/exporters.py` (CSV, XLSX, HTML) consume that `Table`. One thin scoped view in `courses/views_export.py` gates via `scoping`, resolves the same scope∩subset as `analytics_matrix`, fills `title`/`subtitle`, and dispatches. An Export `<details>` panel on `analytics_matrix.html` drives it over GET.

**Tech Stack:** Django 5.2, Python 3.13 + uv, PostgreSQL, pytest + factory_boy, `openpyxl` (new), `csv` stdlib, gettext (EN/PL).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — always use `uv run ruff`, `uv run pytest`, `uv run python manage.py`.
- **Lint/format gate:** every task ends with `uv run ruff format <files>` AND `uv run ruff check <files>` clean (CI runs `ruff format --check`).
- **Tests:** pytest + factory_boy against real PostgreSQL. Every test module starts with `@pytest.mark.django_db` on DB-touching tests.
- **No new migrations** — the feature is read-only over existing results data.
- **New dependency:** `openpyxl` only (pure-Python, added via `uv add openpyxl`).
- **i18n:** all user-facing strings via `gettext` / `{% trans %}`, EN + PL, compile `.mo`. After `makemessages`, clear spurious `#, fuzzy` flags and verify new msgids by grep.
- **Every view ships styled** — the print template is styled per `courses/manage/` conventions and verified light+dark + print preview via a throwaway Playwright screenshot harness (delete after).
- **Commit trailer:** end each commit message body with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01Y3PMizmctCAMpfW88vcRou`
- **Purity boundaries:** builders never touch `request`/permissions; renderers never query the DB (the HTML renderer may take `request` for `render()` only).

---

### Task 1: Add the `openpyxl` dependency

**Files:**
- Modify: `pyproject.toml` (dependencies) + `uv.lock` (generated)

**Interfaces:**
- Produces: `openpyxl` importable in the project venv (consumed by Task 6).

- [ ] **Step 1: Add the dependency**

Run: `uv add openpyxl`
Expected: `pyproject.toml` gains `openpyxl` under `[project] dependencies`; `uv.lock` updates; no error.

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "import openpyxl; print(openpyxl.__version__)"`
Expected: prints a version string (e.g. `3.1.x`), no ImportError.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add openpyxl for gradebook XLSX export"
```

---

### Task 2: `quiz_gradeable_max` helper in `rollups.py`

**Files:**
- Modify: `courses/rollups.py` (add one function near `_quiz_review_maps`)
- Test: `tests/test_gradebook.py` (new file)

**Interfaces:**
- Consumes: existing `rollups._QUESTION_MODELS`, `Element`, `QuestionElement`, `ContentType` (already imported in `rollups.py`).
- Produces: `quiz_gradeable_max(units: list[ContentNode]) -> dict[int, Decimal]` — maps every unit pk to the sum of `max_marks` over its AUTO+REVIEW question elements (NOT_MARKED excluded); a unit with no gradeable questions maps to `Decimal("0")`. Consumed by Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gradebook.py` with the shared helpers copied from `tests/test_analytics_rollups.py` (`_chapter`, `_quiz`, `_auto_q`, `_review_q`) so this module is self-contained:

```python
# tests/test_gradebook.py
from decimal import Decimal

import pytest

from courses.models import Element
from courses.models import QuestionElement
from courses.models import ShortTextQuestionElement
from courses.rollups import quiz_gradeable_max
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


def _chapter(course, **kw):
    kw.setdefault("unit_type", None)
    return ContentNodeFactory(course=course, kind="chapter", parent=None, **kw)


def _quiz(course, parent, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=parent, **kw
    )


def _q(unit, mode, marks):
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode=mode, max_marks=Decimal(marks)
    )
    return Element.objects.create(unit=unit, content_object=q)


@pytest.mark.django_db
def test_quiz_gradeable_max_sums_auto_and_review_excludes_not_marked():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _q(qz, QuestionElement.MarkingMode.AUTO, "3")
    _q(qz, QuestionElement.MarkingMode.REVIEW, "7")
    _q(qz, QuestionElement.MarkingMode.NOT_MARKED, "5")  # excluded
    result = quiz_gradeable_max([qz])
    assert result == {qz.pk: Decimal("10")}


@pytest.mark.django_db
def test_quiz_gradeable_max_zero_when_no_gradeable_questions():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _q(qz, QuestionElement.MarkingMode.NOT_MARKED, "5")
    empty = _quiz(course, ch)  # no questions at all
    result = quiz_gradeable_max([qz, empty])
    assert result == {qz.pk: Decimal("0"), empty.pk: Decimal("0")}


@pytest.mark.django_db
def test_quiz_gradeable_max_empty_units():
    assert quiz_gradeable_max([]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gradebook.py -v`
Expected: FAIL with `ImportError: cannot import name 'quiz_gradeable_max'`.

- [ ] **Step 3: Implement the helper**

In `courses/rollups.py`, add after `_quiz_review_maps` (it reuses the same imports already at the top of the module):

```python
def quiz_gradeable_max(units):
    """Map every unit pk to the sum of `max_marks` over its AUTO+REVIEW question
    elements (NOT_MARKED excluded) — the "fully gradeable maximum", independent of
    any submission (mirrors compute_scores's `possible` for a fully-reviewed
    submission, courses/quiz.py). Units with no gradeable questions map to 0.
    One batched Element scan (no N+1)."""
    unit_pks = [u.pk for u in units]
    result = {pk: Decimal("0") for pk in unit_pks}
    if not unit_pks:
        return result
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS
    }
    elements = Element.objects.filter(
        unit_id__in=unit_pks, content_type_id__in=question_ct_ids
    ).prefetch_related("content_object")
    gradeable = {
        QuestionElement.MarkingMode.AUTO,
        QuestionElement.MarkingMode.REVIEW,
    }
    for el in elements:
        q = el.content_object
        if isinstance(q, QuestionElement) and q.marking_mode in gradeable:
            result[el.unit_id] += q.max_marks
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gradebook.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/rollups.py tests/test_gradebook.py
uv run ruff check courses/rollups.py tests/test_gradebook.py
git add courses/rollups.py tests/test_gradebook.py
git commit -m "feat(exports): quiz_gradeable_max rollup helper"
```

---

### Task 3: `build_matrix_table` builder

**Files:**
- Create: `courses/gradebook.py`
- Test: `tests/test_gradebook.py` (extend)

**Interfaces:**
- Consumes: `rollups.build_progress_matrix(course, students, expanded)` / `build_results_matrix(...)` — each returns `{"columns": [{"node","title","expandable"}], "rows": [{"student", "cells": [_cell], "overall": _cell}], "averages": [_cell], "overall_average": _cell, ...}` where a `_cell` is `{"percent": int|None, "label": str}`.
- Produces: `build_matrix_table(course, students, mode, expanded) -> Table` (the dict shape below). Consumed by Task 8.

The `Table` dict (shared by both builders):
```python
{
  "title": str, "subtitle": str,              # "" from builders; view fills
  "columns": [{"label": str, "max": Decimal|None, "kind": "score"|"percent"}],
  "total_kind": "score"|"percent",
  "total_label": str,
  "meta_row": {"label": str, "values": [...], "total": ...} | None,
  "rows": [{"name": str, "username": str, "cells": [...], "total": ...}],
  "footer": [{"label": str, "values": [...], "total": ...}],
}
```

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gradebook.py` (imports + helpers `_lesson`, `UnitProgressFactory`, `UserFactory` as needed):

```python
from courses.gradebook import build_matrix_table
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


def _lesson(course, parent, obligatory=True, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=parent,
        obligatory=obligatory, **kw,
    )


@pytest.mark.django_db
def test_build_matrix_table_mirrors_progress_matrix():
    course = CourseFactory()
    ch = _chapter(course)
    les = _lesson(course, ch)
    s1, s2 = UserFactory(username="aaa"), UserFactory(username="bbb")
    UnitProgressFactory(student=s1, unit=les, completed=True)  # s1 100%, s2 0%
    table = build_matrix_table(course, [s1, s2], mode="progress", expanded=frozenset())
    assert table["total_kind"] == "percent"
    assert table["meta_row"] is None
    assert [c["kind"] for c in table["columns"]] == ["percent"]
    # rows carry integer percents pulled out of the _cell dicts, not the dicts
    assert table["rows"][0]["cells"] == [100]
    assert table["rows"][0]["total"] == 100
    assert table["rows"][1]["cells"] == [0]
    # participants average of [100, 0] = 50
    assert table["footer"][0]["values"] == [50]
    assert table["title"] == "" and table["subtitle"] == ""


@pytest.mark.django_db
def test_build_matrix_table_neutral_cell_is_none():
    course = CourseFactory()
    ch = _chapter(course)
    _quiz(course, ch)  # results mode, no submissions -> neutral
    s1 = UserFactory()
    table = build_matrix_table(course, [s1], mode="results", expanded=frozenset())
    assert table["rows"][0]["cells"] == [None]  # neutral -> None, not "—", not 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gradebook.py::test_build_matrix_table_mirrors_progress_matrix -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'courses.gradebook'`.

- [ ] **Step 3: Implement `build_matrix_table`**

Create `courses/gradebook.py`:

```python
from django.utils.translation import gettext as _

from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix


def build_matrix_table(course, students, mode, expanded):
    """Reshape the analytics matrix into the neutral Table (spec §3.1). Pure
    re-shaping — no new aggregation. Reads ["percent"] out of the matrix's _cell
    dicts; a neutral cell (None) passes through unchanged. title/subtitle left ""."""
    builder = build_results_matrix if mode == "results" else build_progress_matrix
    matrix = builder(course, students, expanded)

    columns = [
        {"label": c["title"], "max": None, "kind": "percent"}
        for c in matrix["columns"]
    ]
    rows = [
        {
            "name": r["student"].display_name or r["student"].username,
            "username": r["student"].username,
            "cells": [cell["percent"] for cell in r["cells"]],
            "total": r["overall"]["percent"],
        }
        for r in matrix["rows"]
    ]
    footer = [
        {
            "label": _("Average"),
            "values": [a["percent"] for a in matrix["averages"]],
            "total": matrix["overall_average"]["percent"],
        }
    ]
    return {
        "title": "",
        "subtitle": "",
        "columns": columns,
        "total_kind": "percent",
        "total_label": _("Overall"),
        "meta_row": None,
        "rows": rows,
        "footer": footer,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gradebook.py -v`
Expected: all passed (Task 2 + Task 3 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/gradebook.py tests/test_gradebook.py
uv run ruff check courses/gradebook.py tests/test_gradebook.py
git add courses/gradebook.py tests/test_gradebook.py
git commit -m "feat(exports): build_matrix_table (matrix-mirror shape)"
```

---

### Task 4: `build_quiz_gradebook` builder

**Files:**
- Modify: `courses/gradebook.py`
- Test: `tests/test_gradebook.py` (extend)

**Interfaces:**
- Consumes: `rollups.quiz_units_in_order(course)`, `rollups.quiz_gradeable_max(units)` (Task 2), `rollups._quiz_review_maps(unit_pks, submissions)`, `rollups.submission_is_counted(sub, total_review, reviewed_counts)`, `courses.models.QuizSubmission` (with `.Status.IN_PROGRESS`/`.SUBMITTED`, `.score`, `.status`, `.student_id`, `.unit_id`).
- Produces: `build_quiz_gradebook(course, students, numbers_only) -> Table`. Consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gradebook.py`:

```python
from courses.gradebook import build_quiz_gradebook
from courses.models import QuizSubmission


def _submit(student, unit, score, max_score, status="submitted"):
    return QuizSubmission.objects.create(
        student=student, unit=unit, status=status,
        score=Decimal(score), max_score=Decimal(max_score),
    )


@pytest.mark.django_db
def test_quiz_gradebook_scores_markers_max_and_total():
    course = CourseFactory()
    ch = _chapter(course)
    qz1 = _quiz(course, ch, title="Quiz")
    qz2 = _quiz(course, ch, title="Quiz")  # duplicate title
    _q1 = _q(qz1, QuestionElement.MarkingMode.AUTO, "10")
    _q2 = _q(qz2, QuestionElement.MarkingMode.AUTO, "10")
    s_done = UserFactory(username="done")
    s_prog = UserFactory(username="prog")
    s_none = UserFactory(username="none")
    _submit(s_done, qz1, "7", "10")                     # counted -> 7
    _submit(s_prog, qz1, "0", "0", status="in_progress")  # -> "…"
    # s_none: nothing -> "—"
    table = build_quiz_gradebook(course, [s_done, s_prog, s_none], numbers_only=False)
    assert [c["label"] for c in table["columns"]] == ["1. Quiz", "2. Quiz"]
    assert [c["max"] for c in table["columns"]] == [Decimal("10"), Decimal("10")]
    assert table["meta_row"]["label"] == "Max"
    assert table["meta_row"]["total"] == Decimal("20")
    assert table["total_kind"] == "score"
    r0, r1, r2 = table["rows"]
    assert r0["cells"][0] == Decimal("7") and r0["cells"][1] == "—"
    assert r0["total"] == Decimal("7")
    assert r1["cells"][0] == "…" and r1["total"] is None
    assert r2["cells"][0] == "—" and r2["total"] is None


@pytest.mark.django_db
def test_quiz_gradebook_numbers_only_blanks_markers_not_scores():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="Q")
    _q(qz, QuestionElement.MarkingMode.AUTO, "10")
    s1, s2 = UserFactory(username="a"), UserFactory(username="b")
    _submit(s1, qz, "5", "10")  # counted
    # s2 not started
    table = build_quiz_gradebook(course, [s1, s2], numbers_only=True)
    assert table["rows"][0]["cells"][0] == Decimal("5")  # real score untouched
    assert table["rows"][1]["cells"][0] is None           # marker blanked


@pytest.mark.django_db
def test_quiz_gradebook_awaiting_review_marker_R():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="Q")
    _q(qz, QuestionElement.MarkingMode.REVIEW, "10")  # one [R], never reviewed
    s1 = UserFactory()
    _submit(s1, qz, "0", "10")  # SUBMITTED but the [R] is unreviewed -> pending
    table = build_quiz_gradebook(course, [s1], numbers_only=False)
    assert table["rows"][0]["cells"][0] == "R"
    assert table["rows"][0]["total"] is None


@pytest.mark.django_db
def test_quiz_gradebook_participants_only_average_quantized():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="Q")
    _q(qz, QuestionElement.MarkingMode.AUTO, "10")
    s1, s2, s3 = (UserFactory(username=u) for u in ("a", "b", "c"))
    _submit(s1, qz, "10", "10")
    _submit(s2, qz, "5", "10")
    # s3 not taken -> excluded from denominator
    table = build_quiz_gradebook(course, [s1, s2, s3], numbers_only=False)
    # mean(10, 5) over 2 participants = 7.50, quantized to 2dp
    assert table["footer"][0]["values"][0] == Decimal("7.50")
    assert table["footer"][0]["total"] == Decimal("7.50")


@pytest.mark.django_db
def test_quiz_gradebook_non_gradeable_column_blank_and_excluded():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="NM")
    _q(qz, QuestionElement.MarkingMode.NOT_MARKED, "5")  # max 0 -> non-gradeable
    s1 = UserFactory()
    _submit(s1, qz, "0", "0")  # a counted submission exists
    table = build_quiz_gradebook(course, [s1], numbers_only=False)
    assert table["columns"][0]["max"] == Decimal("0")
    assert table["rows"][0]["cells"][0] is None      # blanked
    assert table["rows"][0]["total"] is None          # excluded from total
    assert table["footer"][0]["values"][0] is None    # excluded from average


@pytest.mark.django_db
def test_quiz_gradebook_no_quizzes_and_empty_students():
    course = CourseFactory()
    _chapter(course)
    assert build_quiz_gradebook(course, [], numbers_only=False)["rows"] == []
    empty = build_quiz_gradebook(course, [UserFactory()], numbers_only=False)
    assert empty["columns"] == [] and empty["rows"][0]["cells"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gradebook.py -k quiz_gradebook -v`
Expected: FAIL with `ImportError: cannot import name 'build_quiz_gradebook'`.

- [ ] **Step 3: Implement `build_quiz_gradebook`**

Append to `courses/gradebook.py` (add the imports at the top of the file):

```python
from decimal import ROUND_HALF_UP
from decimal import Decimal

from courses.models import QuizSubmission
from courses.rollups import _quiz_review_maps
from courses.rollups import quiz_gradeable_max
from courses.rollups import quiz_units_in_order
from courses.rollups import submission_is_counted

_CENT = Decimal("0.01")


def _avg(total, count):
    """Participants-only mean, quantized to 2dp; None when no participants."""
    if count == 0:
        return None
    return (total / count).quantize(_CENT, rounding=ROUND_HALF_UP)


def build_quiz_gradebook(course, students, numbers_only):
    """Per-quiz raw-marks register (spec §3.2). One column per quiz leaf unit;
    cells are raw counted sub.score or a —/…/R marker; a dedicated Max row; a
    per-student Total and a participants-only class Average. title/subtitle "" ."""
    students = list(students)
    units = quiz_units_in_order(course)
    maxes = quiz_gradeable_max(units)

    columns = [
        {"label": f"{i}. {u.title}", "max": maxes[u.pk], "kind": "score"}
        for i, u in enumerate(units, start=1)
    ]
    meta_total = sum((c["max"] for c in columns), Decimal("0"))
    meta_row = {
        "label": _("Max"),
        "values": [c["max"] for c in columns],
        "total": meta_total,
    }

    subs = {
        (s.student_id, s.unit_id): s
        for s in QuizSubmission.objects.filter(unit__in=units, student__in=students)
    }
    _, total_review, reviewed_counts = _quiz_review_maps([u.pk for u in units], subs.values())

    col_sums = [Decimal("0")] * len(columns)
    col_counts = [0] * len(columns)
    total_sum = Decimal("0")
    total_count = 0

    rows = []
    for s in students:
        cells = []
        row_total = Decimal("0")
        row_has_counted = False
        for idx, u in enumerate(units):
            if columns[idx]["max"] == 0:  # non-gradeable column
                cells.append(None)
                continue
            sub = subs.get((s.id, u.pk))
            if sub is None:
                cells.append(None if numbers_only else "—")
            elif sub.status == QuizSubmission.Status.IN_PROGRESS:
                cells.append(None if numbers_only else "…")
            elif submission_is_counted(sub, total_review, reviewed_counts):
                score = sub.score or Decimal("0")
                cells.append(score)
                row_total += score
                row_has_counted = True
                col_sums[idx] += score
                col_counts[idx] += 1
            else:  # SUBMITTED but pending [R]
                cells.append(None if numbers_only else "R")
        total = row_total if row_has_counted else None
        if total is not None:
            total_sum += total
            total_count += 1
        rows.append(
            {
                "name": s.display_name or s.username,
                "username": s.username,
                "cells": cells,
                "total": total,
            }
        )

    footer = [
        {
            "label": _("Average"),
            "values": [_avg(col_sums[i], col_counts[i]) for i in range(len(columns))],
            "total": _avg(total_sum, total_count),
        }
    ]
    return {
        "title": "",
        "subtitle": "",
        "columns": columns,
        "total_kind": "score",
        "total_label": _("Total"),
        "meta_row": meta_row,
        "rows": rows,
        "footer": footer,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_gradebook.py -v`
Expected: all passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/gradebook.py tests/test_gradebook.py
uv run ruff check courses/gradebook.py tests/test_gradebook.py
git add courses/gradebook.py tests/test_gradebook.py
git commit -m "feat(exports): build_quiz_gradebook (per-quiz raw marks)"
```

---

### Task 5: `to_csv` renderer + `_sanitize_text_cell` + `build_filename`

**Files:**
- Create: `courses/exporters.py`
- Test: `tests/test_exporters.py` (new file)

**Interfaces:**
- Consumes: a `Table` dict (Tasks 3/4).
- Produces:
  - `_sanitize_text_cell(value) -> str` — prefixes `'` if the text starts with `= + - @` / Tab / CR.
  - `build_filename(slug, shape, mode, numbers_only, today, ext) -> str` — `{slug}-{shape}-{mode?}-{numbers?}-{ISO date}.{ext}`.
  - `to_csv(table, filename) -> HttpResponse`.
  - Internal `_fmt_cell(value, kind) -> str` (shared cell formatter). Consumed by Task 6 conceptually (XLSX re-implements numeric handling; the sanitizer is shared).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exporters.py`:

```python
# tests/test_exporters.py
import csv
import datetime
import io
from decimal import Decimal

from courses.exporters import _sanitize_text_cell
from courses.exporters import build_filename
from courses.exporters import to_csv


def _matrix_table():
    return {
        "title": "Algebra — All my students — Progress",
        "subtitle": "Generated 2026-07-03 · Scope: All my students",
        "columns": [{"label": "Chapter 1", "max": None, "kind": "percent"}],
        "total_kind": "percent",
        "total_label": "Overall",
        "meta_row": None,
        "rows": [{"name": "Ada", "username": "ada", "cells": [85], "total": 85}],
        "footer": [{"label": "Average", "values": [85], "total": 85}],
    }


def _quiz_table():
    return {
        "title": "Algebra — Quiz gradebook",
        "subtitle": "Generated 2026-07-03 · Scope: All my students",
        "columns": [{"label": "1. Quiz", "max": Decimal("10"), "kind": "score"}],
        "total_kind": "score",
        "total_label": "Total",
        "meta_row": {"label": "Max", "values": [Decimal("10")], "total": Decimal("10")},
        "rows": [{"name": "=cmd()", "username": "ada", "cells": [Decimal("7")], "total": Decimal("7")}],
        "footer": [{"label": "Average", "values": [Decimal("7")], "total": Decimal("7")}],
    }


def _read_csv(resp):
    body = b"".join(resp).decode("utf-8-sig")  # strips BOM
    return list(csv.reader(io.StringIO(body)))


def test_sanitize_neutralises_formula_prefixes():
    assert _sanitize_text_cell("=cmd()") == "'=cmd()"
    assert _sanitize_text_cell("+1") == "'+1"
    assert _sanitize_text_cell("-1") == "'-1"
    assert _sanitize_text_cell("@x") == "'@x"
    assert _sanitize_text_cell("Ada") == "Ada"
    assert _sanitize_text_cell(None) == ""


def test_build_filename():
    d = datetime.date(2026, 7, 3)
    assert build_filename("algebra-i", "matrix", "results", False, d, "csv") == "algebra-i-matrix-results-2026-07-03.csv"
    assert build_filename("algebra-i", "quiz", "progress", False, d, "xlsx") == "algebra-i-quiz-2026-07-03.xlsx"
    assert build_filename("algebra-i", "quiz", "progress", True, d, "xlsx") == "algebra-i-quiz-numbers-2026-07-03.xlsx"


def test_to_csv_matrix_percent_and_headers():
    resp = to_csv(_matrix_table(), "x.csv")
    assert resp["Content-Type"].startswith("text/csv")
    assert 'attachment; filename="x.csv"' in resp["Content-Disposition"]
    assert resp.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    rows = _read_csv(resp)
    assert rows[0] == ["Algebra — All my students — Progress"]
    assert rows[1] == ["Generated 2026-07-03 · Scope: All my students"]
    assert rows[3] == ["Name", "Username", "Chapter 1", "Overall"]
    assert rows[4] == ["Ada", "ada", "85%", "85%"]
    assert rows[5] == ["Average", "", "85%", "85%"]


def test_to_csv_quiz_scores_and_injection_guard():
    rows = _read_csv(to_csv(_quiz_table(), "q.csv"))
    assert rows[3] == ["Name", "Username", "1. Quiz", "Total"]
    assert rows[4] == ["Max", "", "10", "10"]           # meta Max row
    assert rows[5] == ["'=cmd()", "ada", "7", "7"]       # name neutralised, score numeric
    assert rows[6] == ["Average", "", "7", "7"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_exporters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'courses.exporters'`.

- [ ] **Step 3: Implement the CSV renderer + helpers**

Create `courses/exporters.py`:

```python
import csv

from django.http import HttpResponse
from django.utils.text import slugify
from django.utils.translation import gettext as _

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_text_cell(value):
    """Neutralise CSV/XLSX formula injection: prefix a ' when a text token starts
    with a formula trigger. Numeric cells never pass through here."""
    text = "" if value is None else str(value)
    if text and text[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text


def build_filename(slug, shape, mode, numbers_only, today, ext):
    """{slug}-{shape}-{mode? matrix only}-{numbers? quiz+numbers_only}-{ISO date}.{ext}"""
    parts = [slugify(slug) or "export", shape]
    if shape == "matrix":
        parts.append(mode)
    if shape == "quiz" and numbers_only:
        parts.append("numbers")
    parts.append(today.isoformat())
    return f"{'-'.join(parts)}.{ext}"


def _fmt_cell(value, kind):
    """Format a data/summary value by column kind for text output (CSV/HTML)."""
    if value is None:
        return ""
    if kind == "percent":
        return f"{value}%"
    if isinstance(value, str):  # a marker (—/…/R) — our own constant, safe
        return value
    return str(value)  # Decimal / int score


def to_csv(table, filename):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("﻿")  # UTF-8 BOM for Excel
    writer = csv.writer(resp)
    cols = table["columns"]
    tk = table["total_kind"]

    writer.writerow([_sanitize_text_cell(table["title"])])
    writer.writerow([_sanitize_text_cell(table["subtitle"])])
    writer.writerow([])
    writer.writerow(
        [_("Name"), _("Username")]
        + [_sanitize_text_cell(c["label"]) for c in cols]
        + [_sanitize_text_cell(table["total_label"])]
    )
    meta = table["meta_row"]
    if meta:
        writer.writerow(
            ["", ""]
            + [_fmt_cell(v, c["kind"]) for v, c in zip(meta["values"], cols)]
            + [_fmt_cell(meta["total"], tk)]
        )
    for row in table["rows"]:
        writer.writerow(
            [_sanitize_text_cell(row["name"]), _sanitize_text_cell(row["username"])]
            + [_fmt_cell(v, c["kind"]) for v, c in zip(row["cells"], cols)]
            + [_fmt_cell(row["total"], tk)]
        )
    for frow in table["footer"]:
        writer.writerow(
            [_sanitize_text_cell(frow["label"]), ""]
            + [_fmt_cell(v, c["kind"]) for v, c in zip(frow["values"], cols)]
            + [_fmt_cell(frow["total"], tk)]
        )
    return resp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_exporters.py -v`
Expected: all passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/exporters.py tests/test_exporters.py
uv run ruff check courses/exporters.py tests/test_exporters.py
git add courses/exporters.py tests/test_exporters.py
git commit -m "feat(exports): CSV renderer + sanitizer + filename helper"
```

---

### Task 6: `to_xlsx` renderer

**Files:**
- Modify: `courses/exporters.py`
- Test: `tests/test_exporters.py` (extend)

**Interfaces:**
- Consumes: a `Table`, `_sanitize_text_cell` (Task 5), `openpyxl` (Task 1).
- Produces: `to_xlsx(table, filename) -> HttpResponse`. Consumed by Task 8.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_exporters.py`:

```python
import openpyxl

from courses.exporters import to_xlsx


def _load_xlsx(resp):
    return openpyxl.load_workbook(io.BytesIO(resp.content))


def test_to_xlsx_scores_are_numeric_and_headers_present():
    resp = to_xlsx(_quiz_table(), "q.xlsx")
    assert resp["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'attachment; filename="q.xlsx"' in resp["Content-Disposition"]
    ws = _load_xlsx(resp).active
    # find the score cell for the student row (value 7 as a real number, not text)
    values = [c.value for col in ws.iter_cols() for c in col]
    assert 7 in values or 7.0 in values
    # injection guard applied to the =cmd() name
    assert any(isinstance(v, str) and v.startswith("'=cmd()") for v in values)


def test_to_xlsx_percent_cells_have_percent_format():
    resp = to_xlsx(_matrix_table(), "m.xlsx")
    ws = _load_xlsx(resp).active
    pct_cells = [c for col in ws.iter_cols() for c in col if c.number_format == "0%"]
    assert pct_cells and any(abs((c.value or 0) - 0.85) < 1e-9 for c in pct_cells)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_exporters.py -k xlsx -v`
Expected: FAIL with `ImportError: cannot import name 'to_xlsx'`.

- [ ] **Step 3: Implement `to_xlsx`**

Add to `courses/exporters.py` (add the openpyxl imports at the top):

```python
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font


def _xlsx_value(cell_value, kind):
    """Return (value, number_format) for an XLSX cell. Score -> float; percent ->
    fraction with a 0% format; marker/None -> sanitised text/empty."""
    if cell_value is None:
        return "", None
    if kind == "percent":
        return float(cell_value) / 100.0, "0%"
    if isinstance(cell_value, str):  # marker — safe constant
        return cell_value, None
    return float(cell_value), None  # Decimal/int score -> real number


def to_xlsx(table, filename):
    wb = Workbook()
    ws = wb.active
    ws.title = "Gradebook"
    cols = table["columns"]
    tk = table["total_kind"]
    bold = Font(bold=True)

    ws.append([_sanitize_text_cell(table["title"])])
    ws.append([_sanitize_text_cell(table["subtitle"])])
    ws.append([])

    header = (
        [_("Name"), _("Username")]
        + [_sanitize_text_cell(c["label"]) for c in cols]
        + [_sanitize_text_cell(table["total_label"])]
    )
    ws.append(header)
    header_row_idx = ws.max_row
    for cell in ws[header_row_idx]:
        cell.font = bold

    def _write_data_row(label_cells, values, total_value):
        ws.append(label_cells + [""] * (len(cols) + 1))  # placeholder, fill typed
        r = ws.max_row
        for j, (v, c) in enumerate(zip(values, cols), start=len(label_cells) + 1):
            value, fmt = _xlsx_value(v, c["kind"])
            ws.cell(row=r, column=j, value=value)
            if fmt:
                ws.cell(row=r, column=j).number_format = fmt
        value, fmt = _xlsx_value(total_value, tk)
        tcell = ws.cell(row=r, column=len(cols) + 3, value=value)
        if fmt:
            tcell.number_format = fmt
        return r

    meta = table["meta_row"]
    if meta:
        r = _write_data_row([_sanitize_text_cell(meta["label"]), ""], meta["values"], meta["total"])
        for cell in ws[r]:
            cell.font = bold
    for row in table["rows"]:
        _write_data_row(
            [_sanitize_text_cell(row["name"]), _sanitize_text_cell(row["username"])],
            row["cells"],
            row["total"],
        )
    for frow in table["footer"]:
        r = _write_data_row([_sanitize_text_cell(frow["label"]), ""], frow["values"], frow["total"])
        for cell in ws[r]:
            cell.font = Font(italic=True, bold=True)

    ws.freeze_panes = ws.cell(row=header_row_idx + 1, column=3)  # below header, right of identity cols

    resp = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(resp)
    return resp
```

Note: `_xlsx_value` and the header/label cells all route user text through `_sanitize_text_cell`; markers and numbers are typed, not sanitised. The `Decimal` import may already be present from Task 5's additions — if so, don't duplicate it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_exporters.py -v`
Expected: all passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format courses/exporters.py tests/test_exporters.py
uv run ruff check courses/exporters.py tests/test_exporters.py
git add courses/exporters.py tests/test_exporters.py
git commit -m "feat(exports): XLSX renderer via openpyxl"
```

---

### Task 7: Print HTML renderer + template

**Files:**
- Create: `templates/courses/manage/gradebook_print.html`
- Modify: `courses/exporters.py` (add `render_gradebook_print`)
- Test: `tests/test_exporters.py` (extend)

**Interfaces:**
- Consumes: a `Table`, a `request`.
- Produces: `render_gradebook_print(request, table) -> HttpResponse`. Consumed by Task 8.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_exporters.py`:

```python
import pytest
from django.test import RequestFactory

from courses.exporters import render_gradebook_print


@pytest.mark.django_db
def test_render_print_contains_table():
    req = RequestFactory().get("/x")
    resp = render_gradebook_print(req, _quiz_table())
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Algebra — Quiz gradebook" in body
    assert "1. Quiz" in body
    assert "&#x27;=cmd()" in body or "'=cmd()" in body  # sanitised name rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_exporters.py -k print -v`
Expected: FAIL with `ImportError: cannot import name 'render_gradebook_print'`.

- [ ] **Step 3: Create the print template**

Create `templates/courses/manage/gradebook_print.html`:

```django
{% load i18n %}<!-- gradebook print page: standalone, print-optimised -->
<section class="gb-print">
  <header class="gb-print__head">
    <h1 class="gb-print__title">{{ table.title }}</h1>
    <p class="gb-print__subtitle muted">{{ table.subtitle }}</p>
    <button type="button" class="btn btn--primary gb-print__btn" onclick="window.print()">
      {% trans "Print" %}</button>
  </header>
  <div class="gb-print__scroll">
    <table class="gb-print__table">
      <thead>
        <tr>
          <th>{% trans "Name" %}</th>
          <th>{% trans "Username" %}</th>
          {% for c in table.columns %}<th>{{ c.label }}</th>{% endfor %}
          <th>{{ table.total_label }}</th>
        </tr>
      </thead>
      <tbody>
        {% if table.meta_row %}
          <tr class="gb-print__meta">
            <th colspan="2">{{ table.meta_row.label }}</th>
            {% for v in table.meta_row.values %}<td>{{ v|default_if_none:"" }}</td>{% endfor %}
            <td>{{ table.meta_row.total|default_if_none:"" }}</td>
          </tr>
        {% endif %}
        {% for row in table.rows %}
          <tr>
            <td>{{ row.name }}</td>
            <td>{{ row.username }}</td>
            {% for cell in row.cells %}<td>{{ cell|default_if_none:"" }}</td>{% endfor %}
            <td>{{ row.total|default_if_none:"" }}</td>
          </tr>
        {% endfor %}
      </tbody>
      <tfoot>
        {% for frow in table.footer %}
          <tr class="gb-print__avg">
            <th colspan="2">{{ frow.label }}</th>
            {% for v in frow.values %}<td>{{ v|default_if_none:"" }}</td>{% endfor %}
            <td>{{ frow.total|default_if_none:"" }}</td>
          </tr>
        {% endfor %}
      </tfoot>
    </table>
  </div>
</section>

<style>
  .gb-print { max-width: 100%; padding: 1rem; color: #111; }
  .gb-print__title { margin: 0 0 .25rem; }
  .gb-print__subtitle { margin: 0 0 1rem; }
  .gb-print__scroll { overflow-x: auto; }
  .gb-print__table { border-collapse: collapse; width: 100%; font-size: .9rem; }
  .gb-print__table th, .gb-print__table td {
    border: 1px solid #999; padding: .25rem .5rem; text-align: left; white-space: nowrap;
  }
  .gb-print__meta th, .gb-print__meta td,
  .gb-print__avg th, .gb-print__avg td { font-weight: 600; background: #f2f2f2; }
  @media print {
    .gb-print__btn { display: none; }
    .gb-print { padding: 0; }
    .gb-print__table thead { display: table-header-group; }
    .gb-print__table tr { page-break-inside: avoid; }
    .gb-print__table th, .gb-print__table td { color: #000; }
  }
</style>
```

Note: cells (percent `85%`, score, markers) arrive already-formatted as strings from the renderer — see Step 4; the template prints them verbatim via `|default_if_none`.

- [ ] **Step 4: Implement `render_gradebook_print`**

The template expects display-ready cell strings, so the renderer formats the `Table` into a display copy first (reusing `_fmt_cell` and `_sanitize_text_cell`). Add to `courses/exporters.py`:

```python
from django.shortcuts import render


def _display_table(table):
    """A copy of `table` with every cell pre-formatted to a display string
    (percent -> "85%", score -> "7", marker verbatim, None -> ""), and user text
    sanitised — so the print template prints verbatim."""
    cols = table["columns"]
    tk = table["total_kind"]

    def cells(values):
        return [_fmt_cell(v, c["kind"]) for v, c in zip(values, cols)]

    disp = {
        "title": _sanitize_text_cell(table["title"]),
        "subtitle": _sanitize_text_cell(table["subtitle"]),
        "columns": [{"label": _sanitize_text_cell(c["label"])} for c in cols],
        "total_label": _sanitize_text_cell(table["total_label"]),
        "meta_row": None,
        "rows": [
            {
                "name": _sanitize_text_cell(r["name"]),
                "username": _sanitize_text_cell(r["username"]),
                "cells": cells(r["cells"]),
                "total": _fmt_cell(r["total"], tk),
            }
            for r in table["rows"]
        ],
        "footer": [
            {
                "label": _sanitize_text_cell(f["label"]),
                "values": cells(f["values"]),
                "total": _fmt_cell(f["total"], tk),
            }
            for f in table["footer"]
        ],
    }
    if table["meta_row"]:
        m = table["meta_row"]
        disp["meta_row"] = {
            "label": _sanitize_text_cell(m["label"]),
            "values": cells(m["values"]),
            "total": _fmt_cell(m["total"], tk),
        }
    return disp


def render_gradebook_print(request, table):
    return render(
        request,
        "courses/manage/gradebook_print.html",
        {"table": _display_table(table)},
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_exporters.py -v`
Expected: all passed.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff format courses/exporters.py tests/test_exporters.py
uv run ruff check courses/exporters.py tests/test_exporters.py
git add courses/exporters.py tests/test_exporters.py templates/courses/manage/gradebook_print.html
git commit -m "feat(exports): print HTML renderer + template"
```

---

### Task 8: The export view + URL route

**Files:**
- Create: `courses/views_export.py`
- Modify: `courses/urls.py` (add route + import)
- Test: `tests/test_views_export.py` (new file)

**Interfaces:**
- Consumes: `courses.gradebook.build_matrix_table` / `build_quiz_gradebook`; `courses.exporters.to_csv` / `to_xlsx` / `render_gradebook_print` / `build_filename`; `grouping.scoping` (`can_review_course`, `students_in_scope`, `analytics_scope_choices`); `courses.views_analytics._clean_expand` (shared, not duplicated); `django.utils.timezone.localdate`.
- Produces: `gradebook_export(request, slug)` view; URL name `courses:manage_analytics_export`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_views_export.py`:

```python
# tests/test_views_export.py
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory


def _chapter(course):
    return ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None)


def _quiz(course, parent, **kw):
    return ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=parent, **kw)


def _url(course):
    return reverse("courses:manage_analytics_export", kwargs={"slug": course.slug})


@pytest.mark.django_db
def test_export_requires_review_reach(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    outsider = UserFactory()
    client.force_login(outsider)
    resp = client.get(_url(course), {"shape": "matrix", "format": "csv"})
    assert resp.status_code == 404


@pytest.mark.django_db
def test_export_csv_content_type_and_disposition(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    _chapter(course)
    client.force_login(owner)
    resp = client.get(_url(course), {"shape": "matrix", "format": "csv", "mode": "progress"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]
    assert course.slug in resp["Content-Disposition"]


@pytest.mark.django_db
def test_export_xlsx_and_html_dispatch(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    _chapter(course)
    client.force_login(owner)
    xlsx = client.get(_url(course), {"shape": "quiz", "format": "xlsx"})
    assert xlsx["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    html = client.get(_url(course), {"shape": "quiz", "format": "html"})
    assert html.status_code == 200
    assert b"Quiz gradebook" in html.content or b"gb-print" in html.content


@pytest.mark.django_db
def test_export_title_reflects_resolved_scope_not_forged(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    _chapter(course)
    client.force_login(owner)
    # forged group scope the owner can't reach -> falls back to "all my students"
    resp = client.get(_url(course), {"shape": "matrix", "format": "csv", "scope": "group:99999"})
    body = resp.content.decode("utf-8-sig")
    assert "All my students" in body
    assert "group:99999" not in body


@pytest.mark.django_db
def test_export_unknown_params_coerce_to_defaults(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    _chapter(course)
    client.force_login(owner)
    resp = client.get(_url(course), {"shape": "junk", "format": "junk", "mode": "junk"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")  # format defaulted to csv
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_views_export.py -v`
Expected: FAIL — `NoReverseMatch` for `courses:manage_analytics_export`.

- [ ] **Step 3: Implement the view**

Create `courses/views_export.py`:

```python
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _

from courses.exporters import build_filename
from courses.exporters import render_gradebook_print
from courses.exporters import to_csv
from courses.exporters import to_xlsx
from courses.gradebook import build_matrix_table
from courses.gradebook import build_quiz_gradebook
from courses.models import Course
from courses.views_analytics import _clean_expand
from grouping import scoping

_SHAPES = {"matrix", "quiz"}
_FORMATS = {"csv", "xlsx", "html"}


def _scope_label(user, course, scope):
    for choice in scoping.analytics_scope_choices(user, course):
        if choice["value"] == scope:
            return choice["label"]
    return _("All my students")


@login_required
def gradebook_export(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404

    shape = request.GET.get("shape")
    shape = shape if shape in _SHAPES else "matrix"
    fmt = request.GET.get("format")
    fmt = fmt if fmt in _FORMATS else "csv"
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    scope = request.GET.get("scope", "all")
    expanded = set(_clean_expand(request.GET.getlist("expand")))
    numbers_only = request.GET.get("numbers_only") == "1" and shape == "quiz"

    # scope ∩ subset — identical resolution to analytics_matrix (no scope_changed).
    pool = scoping.students_in_scope(request.user, course, scope)
    raw_subset = set(_clean_expand(request.GET.getlist("student")))
    subset_pks = (
        (raw_subset & set(pool.values_list("pk", flat=True))) if raw_subset else set()
    )
    students = (
        pool.filter(pk__in=subset_pks).order_by("username")
        if subset_pks
        else pool.order_by("username")
    )

    if shape == "quiz":
        table = build_quiz_gradebook(course, students, numbers_only)
        shape_label = _("Quiz gradebook")
    else:
        table = build_matrix_table(course, students, mode, expanded)
        shape_label = _("Results") if mode == "results" else _("Progress")

    label = _scope_label(request.user, course, scope)
    today = timezone.localdate()
    table["title"] = f"{course.title} — {label} — {shape_label}"
    table["subtitle"] = _("Generated %(date)s · Scope: %(scope)s") % {
        "date": today.isoformat(),
        "scope": label,
    }

    if fmt == "html":
        return render_gradebook_print(request, table)
    ext = "csv" if fmt == "csv" else "xlsx"
    filename = build_filename(course.slug, shape, mode, numbers_only, today, ext)
    return (to_csv if fmt == "csv" else to_xlsx)(table, filename)
```

- [ ] **Step 4: Add the URL route**

In `courses/urls.py`, add the import alongside `from courses import views_analytics`:

```python
from courses import views_export
```

And add the route inside the analytics block (after the `manage_analytics_student` path, before the `catalog/` paths):

```python
    path(
        "manage/courses/<slug:slug>/analytics/export/",
        views_export.gradebook_export,
        name="manage_analytics_export",
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_views_export.py -v`
Expected: all passed.

- [ ] **Step 6: Run the full builder/renderer/view suite**

Run: `uv run pytest tests/test_gradebook.py tests/test_exporters.py tests/test_views_export.py -v`
Expected: all passed.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff format courses/views_export.py courses/urls.py tests/test_views_export.py
uv run ruff check courses/views_export.py courses/urls.py tests/test_views_export.py
git add courses/views_export.py courses/urls.py tests/test_views_export.py
git commit -m "feat(exports): scoped gradebook export view + route"
```

---

### Task 9: Export panel on the analytics page

**Files:**
- Modify: `templates/courses/manage/analytics_matrix.html`
- Test: `tests/test_views_export.py` (extend — assert the panel renders on the matrix page)

**Interfaces:**
- Consumes: existing `analytics_matrix` context (`course`, `scope`, `mode`, `expand_pks`, `subset_pks`). The panel is a second `<form>` (GET) posting to `courses:manage_analytics_export`, so it does not disturb the existing wrapping form.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_views_export.py`:

```python
@pytest.mark.django_db
def test_analytics_page_shows_export_panel(client):
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    _chapter(course)
    client.force_login(owner)
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    resp = client.get(url)
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'name="shape"' in body           # export shape radio present
    assert "manage_analytics_export" in body or "/analytics/export/" in body
    assert 'name="numbers_only"' in body     # only-numbers checkbox present
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_views_export.py -k export_panel -v`
Expected: FAIL (no `name="shape"` in the page).

- [ ] **Step 3: Add the Export panel to the template**

In `templates/courses/manage/analytics_matrix.html`, inside `<header class="manage__head">` (after the "Configure colours" `{% endif %}` on line 11, before `</header>`), add:

```django
    <details class="analytics__export">
      <summary class="btn btn--ghost btn--small">{% trans "Export" %}</summary>
      <form method="get"
            action="{% url 'courses:manage_analytics_export' slug=course.slug %}"
            class="analytics__export-form">
        <input type="hidden" name="scope" value="{{ scope }}">
        <input type="hidden" name="mode" value="{{ mode }}">
        {% for pk in expand_pks %}<input type="hidden" name="expand" value="{{ pk }}">{% endfor %}
        {% for pk in subset_pks %}<input type="hidden" name="student" value="{{ pk }}">{% endfor %}
        <fieldset>
          <legend>{% trans "What to export" %}</legend>
          <label><input type="radio" name="shape" value="matrix" checked>
            {% trans "This matrix view" %}</label>
          <label><input type="radio" name="shape" value="quiz">
            {% trans "Quiz gradebook (raw marks)" %}</label>
        </fieldset>
        <label class="analytics__export-numbers">
          <input type="checkbox" name="numbers_only" value="1">
          {% trans "Only numbers" %}
          <span class="muted">{% trans "Leave marks blank for not-taken / in-progress / awaiting-review, so the file imports cleanly into a register." %}</span>
        </label>
        <div class="row-actions">
          <button type="submit" name="format" value="csv" class="btn btn--small">{% trans "CSV" %}</button>
          <button type="submit" name="format" value="xlsx" class="btn btn--small">{% trans "Excel (.xlsx)" %}</button>
          <button type="submit" name="format" value="html" class="btn btn--small">{% trans "Print" %}</button>
        </div>
      </form>
    </details>
    <script>
      // Progressive enhancement: the "Only numbers" checkbox applies to the quiz
      // shape only; disable it while "This matrix view" is selected.
      (function () {
        var form = document.querySelector('.analytics__export-form');
        if (!form) return;
        var numbers = form.querySelector('input[name="numbers_only"]');
        function sync() {
          var quiz = form.querySelector('input[name="shape"]:checked').value === 'quiz';
          numbers.disabled = !quiz;
        }
        form.querySelectorAll('input[name="shape"]').forEach(function (r) {
          r.addEventListener('change', sync);
        });
        sync();
      })();
    </script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_views_export.py -k export_panel -v`
Expected: PASS.

- [ ] **Step 5: Style + screenshot-verify the panel and the print page**

Add minimal styling for `.analytics__export`, `.analytics__export-form`, `.analytics__export-numbers` in `courses/static/courses/css/courses.css` (or the app CSS the analytics page already loads) following existing `.analytics__*` conventions (a raised panel under the summary, stacked controls, mobile-friendly). Then, using a throwaway Playwright harness (delete after review), screenshot **light + dark** of: the analytics page with the Export panel open, and the print page (`?format=html`) in normal + print-emulation. Self-critique contrast and layout; fix issues.

Run: `uv run pytest tests/test_courses_views.py tests/test_views_export.py -v`
Expected: all passed (no regression on the analytics page).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff format tests/test_views_export.py
uv run ruff check tests/test_views_export.py
git add templates/courses/manage/analytics_matrix.html courses/static/courses/css/courses.css tests/test_views_export.py
git commit -m "feat(exports): Export panel on analytics matrix page"
```

---

### Task 10: i18n (EN/PL) for all new strings

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_views_export.py` (extend — a PL request produces a localized header)

**Interfaces:**
- Consumes: the `gettext`/`{% trans %}` msgids introduced in Tasks 3–9 (`Name`, `Username`, `Average`, `Overall`, `Total`, `Max`, `Progress`, `Results`, `Quiz gradebook`, `Generated %(date)s · Scope: %(scope)s`, `Export`, `What to export`, `This matrix view`, `Quiz gradebook (raw marks)`, `Only numbers`, the helper text, `CSV`, `Excel (.xlsx)`, `Print`, `All my students`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_views_export.py`:

```python
@pytest.mark.django_db
def test_export_localized_pl_header(client):
    owner = UserFactory(language="pl")
    course = CourseFactory(owner=owner)
    _chapter(course)
    client.force_login(owner)
    resp = client.get(
        _url(course),
        {"shape": "quiz", "format": "csv"},
        HTTP_ACCEPT_LANGUAGE="pl",
    )
    body = resp.content.decode("utf-8-sig")
    assert "Imię" in body or "Nazwa" in body   # localized "Name" header
```

(Confirm the exact PL msgstr you set for `Name` and align the assertion to it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_views_export.py -k localized_pl -v`
Expected: FAIL (header still English).

- [ ] **Step 3: Regenerate message catalogs**

Run: `uv run python manage.py makemessages -l pl -l en`
Then open both `.po` files and fill PL `msgstr` for every new msgid (e.g. `Name` → `Imię`, `Username` → `Nazwa użytkownika`, `Average` → `Średnia`, `Overall` → `Ogółem`, `Total` → `Suma`, `Max` → `Maks.`, `Progress` → `Postępy`, `Results` → `Wyniki`, `Quiz gradebook` → `Dziennik quizów`, `Export` → `Eksport`, `Only numbers` → `Tylko liczby`, `Print` → `Drukuj`, `All my students` → `Wszyscy moi uczniowie`, etc.). **Clear any `#, fuzzy` flags** on copied entries and verify each new msgid with:

Run: `grep -n "msgid \"Quiz gradebook\"" locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 4: Compile catalogs**

Run: `uv run python manage.py compilemessages`
Expected: writes `django.mo` for en + pl, no error.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_views_export.py -k localized_pl -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.mo tests/test_views_export.py
git commit -m "i18n(exports): EN/PL strings for gradebook export"
```

---

### Task 11: Full-suite gate + DoD

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `uv run pytest -q`
Expected: all pass (existing suite + the new `test_gradebook.py`, `test_exporters.py`, `test_views_export.py`); 0 failures.

- [ ] **Step 2: Ruff gate (format-check + lint) over the whole tree**

Run: `uv run ruff format --check .` then `uv run ruff check .`
Expected: both clean.

- [ ] **Step 3: Migration sanity (should be a no-op)**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (the feature adds no models/fields).

- [ ] **Step 4: Manual smoke (optional, recommended)**

Start the app and, as a course owner with some quiz submissions, open `/manage/courses/<slug>/analytics/`, open the Export panel, and download CSV, XLSX, and Print for both shapes; open the CSV/XLSX in a spreadsheet and confirm numbers are numeric, the Max row and averages read correctly, and a student named `=x` appears apostrophe-guarded.

- [ ] **Step 5: Final commit (if any lint/format fixups were needed)**

```bash
git add -A
git commit -m "chore(exports): full-suite + ruff gate green"
```

---

## Self-Review

**Spec coverage:**
- §2 file layout → Tasks 3–9 (gradebook.py, exporters.py, views_export.py, print template, urls, panel). ✓
- §2 `Table` shape incl. `total_kind`/`total_label`/`meta_row.total` → Tasks 3/4 build it, Tasks 5–7 consume it. ✓
- §3.1 matrix-mirror incl. `_cell["percent"]` extraction, neutral→None → Task 3 + `test_build_matrix_table_neutral_cell_is_none`. ✓
- §3.2 quiz gradebook: `quiz_gradeable_max` (Task 2), ordinal labels, markers by `QuizSubmission.Status`, `numbers_only`, non-gradeable columns, participants-only 2dp averages, Max-row total → Task 4 tests cover each. ✓
- §4.1 CSV: BOM, subtitle line, `total_label` header, `_fmt_cell` percent/score, formula-injection guard over all text tokens → Task 5. ✓
- §4.2 XLSX: numeric score (Decimal→float), percent `0%` format, freeze panes, sanitizer incl. headers → Task 6. ✓
- §4.3 print page + `@media print` + no auto-print → Task 7. ✓
- §4 filenames incl. `numbers` token, date from view → Task 5 `build_filename`, Task 8 passes `timezone.localdate()`. ✓
- §5 view: gate, scope∩subset (no scope_changed), param coercion, `numbers_only` parse, resolved-scope label/title/subtitle, route → Task 8. ✓
- §6 export panel + hidden inputs (scope/mode/expand/student) + PE JS → Task 9. ✓
- §7 tests: builders, renderers (CSV+XLSX injection), view/permissions, i18n → Tasks 2–10. ✓
- §8 i18n EN/PL + `.mo` → Task 10. ✓
- §9 `openpyxl`, no migrations → Task 1 + Task 11 Step 3. ✓
- §10 edge cases: zero quizzes, empty students, non-gradeable/retro-edit, awaiting-review, duplicate titles, junk params, forged scope → covered across Task 4 + Task 8 tests. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every command has an expected result. ✓

**Type consistency:** `Table` keys identical across Tasks 3–7; `build_filename(slug, shape, mode, numbers_only, today, ext)` signature matches its Task 8 caller; `_fmt_cell(value, kind)` / `_xlsx_value(value, kind)` / `_sanitize_text_cell(value)` names consistent between definition (Tasks 5/6) and use (Task 7); `quiz_gradeable_max(units)` return type (`dict[int, Decimal]`) matches Task 4 consumption. ✓
