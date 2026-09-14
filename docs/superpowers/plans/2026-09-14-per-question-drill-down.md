# Per-question drill-down (demo access PR 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A teacher-facing page showing one pupil's answers to one quiz — stem, the pupil's answer, the correct answer, the mark, the attempt count — reached from the per-pupil analytics breakdown, behind the same gate as the rest of analytics; plus the grid-types rollup fix (D9).

**Architecture:** A new view `analytics_student_quiz` in `courses/views_analytics.py` resolves course → reviewer gate → reviewable pupil → quiz node → submission (404 on every failure). Each question row reuses `courses.views._results_row` for the outcome and marks, then a new side-effect-free module `courses/answer_summary.py` turns `(question, response, mark_result)` into teacher-voice display `Part`s. The breakdown's quiz pill moves into a shared partial so the new page's header says exactly what the breakdown says; the breakdown's quiz titles become links.

**Tech Stack:** Django 5 templates, pytest + pytest-django, BeautifulSoup for rendered-HTML assertions, Playwright (sync) for the one e2e, gettext (`locale/pl`).

**Spec:** `docs/superpowers/specs/2026-09-14-per-question-drill-down-design.md` (below: "the spec"). Read it alongside this plan; every task cites the spec section it implements. The spec's `file:line` citations describe master `d432245a`.

## Global Constraints

- **Every failure of the new view is 404, never 403** (spec D7). Anonymous → login redirect (302).
- **No student template is modified** except `templates/courses/manage/_breakdown_node.html` (a teacher template) and the comment in `templates/courses/_katex_js.html`. `quiz_results.html`, `views_review.py` and every `templates/courses/elements/*` file stay byte-identical (spec §3.6).
- **No catch-all fail-open** in `answer_summary` (spec D6): a missing registry entry raises `KeyError`.
- **No migration, no FORMAT_VERSION bump** (spec §7). Run `uv run python manage.py makemigrations --check --dry-run` in the final task.
- **Code never cites a stylesheet by line** — no `<name>.css:<digits>` in any `.css`, `.py`, `.js` or `.html` file (`tests/test_css_citations_are_durable.py`). Cite by selector.
- **CSS comments naming class stems** must not contain `*/` mid-sentence (memory: css-comment-early-terminator-eats-next-rule).
- **Django `{# #}` comments are single-line only.** Multi-line template comments use `{% comment %}…{% endcomment %}`.
- **Muted text uses `--text-secondary`, never `--text-tertiary`** (spec §5.3).
- **Teacher voice:** no rendered string on the new page says "you"/"your".
- **Every pupil viewed by a Platform Admin or course owner in a test needs `EnrollmentFactory(student=…, course=…)`** — `reviewable_students` serves PA/owner from `Enrollment` alone (spec §6 preamble). Group-teacher reach comes from `GroupMembership`.
- **Test users who log in must be verified**: use `make_login` / `make_pa` / `make_teacher` / `make_verified_user` + `client.force_login`, never a bare `UserFactory` for a logged-in viewer (allauth's mandatory verification redirects it).
- **pk sequences are independent per model** — never assert a pk as a substring of HTML; select elements with BeautifulSoup and compare exact attribute values (memory: independent-pk-sequences-make-substring-assertions-flaky).
- **Tooling runs through uv**: `uv run pytest …`, `uv run ruff check --no-cache .`, `uv run ruff format --check .`, `uv run python manage.py …`. **Never pass `-q` to pytest** (addopts already has it). e2e tests need `-m e2e`.
- **Lint before every commit:** `uv run ruff check --no-cache --fix <files the task touched> && uv run ruff format <files the task touched>`, then re-run the task's tests. `pyproject.toml` selects `I` (isort) and `E`: the plan's code blocks are not guaranteed sorted or wrapped, so let ruff fix import order and line length rather than hand-editing.
- **Test DB preflight (once per session, before any pytest):** a git worktree has no `.env` — copy it from the main checkout (`cp ../libli/.env .env`); start the container with `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`; run ONE pytest process at a time. Read the pass/fail counts from the summary line, not the exit code.
- **Falsify steps:** each mutant is applied BY HAND, the named test is run and observed RED, then the mutant is reverted BY HAND and `git diff` is read to confirm the revert. **Never `git checkout -- <file>` to revert a mutant** (it discards the task's own uncommitted work).
- **Commit messages** end with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m
  ```

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `courses/rollups.py` | D9 swap; `_course_results_row` extraction; `_quiz_pill` gains `submission_pk` | 1, 2 |
| `courses/views.py` | `prefetch_question_children` helper replacing two copies; `course_results` comment | 2, 3 |
| `courses/answer_summary.py` (new) | `Part`, `summarise`, per-type adapters, `stem_html` / `gap_marked_stem` | 4, 5 |
| `courses/views_analytics.py` | `_drill_params`; `analytics_student_quiz` view; `_quiz_answer_rows`; `analytics_student` passes `drill_qs` | 6, 7, 9 |
| `courses/urls.py` | route `manage_analytics_student_quiz` | 6 |
| `templates/courses/manage/_quiz_pill.html` (new) | the five pill spans, shared | 6 |
| `templates/courses/manage/_breakdown_node.html` | include the pill partial; quiz title link | 6, 9 |
| `templates/courses/manage/analytics_student_quiz.html` (new) | the page | 6, 7, 8 |
| `templates/courses/_katex_js.html` | comment reworded (line-count neutral) | 8 |
| `core/static/core/css/app.css` | `answers__*`, `.breakdown-unit__link` rules | 10 |
| `locale/pl/LC_MESSAGES/django.po` / `.mo`, `locale/en/…` | new msgids | 11 |
| `docs/help/teacher/drill-down.md`, `.pl.md` | "Per-question answers" section | 11 |
| `tests/test_analytics_rollups.py` | T41 rollup cases; moving pill dicts | 1, 2 |
| `tests/test_prefetch_question_children.py` (new) | helper query guard | 3 |
| `tests/answer_summary_fixtures.py` (new) | builders for all ten question types | 4 |
| `tests/test_answer_summary.py` (new) | T32, T33 (pure), T34 | 4, 5 |
| `tests/test_analytics_student_quiz.py` (new) | T30, T31, T31b, T33 (page), T35, T36, T37, T38, T39, T41 (page) | 6–10 |
| `tests/test_title_math_markers.py` | per-branch breakdown marker + citations | 6, 9 |
| `tests/test_e2e_analytics.py` | T40 | 12 |

Task order: 1 D9 → 2 row/pill extraction → 3 prefetch helper → 4 answer summary (single-part types + registry) → 5 answer summary (multi-part types + stems) → 6 route, access, pill partial → 7 rows, override, header → 8 rendering details → 9 breakdown links → 10 query budget + CSS → 11 i18n + help → 12 e2e → 13 citation sweep, gates, manual pass.

---

### Task 1: D9 — the rollups see both grid question types

Implements spec D9, §2.5 (`_QUESTION_MODELS`), T41 (rollup half). Kept as its own commit so it could be split out.

**Files:**
- Modify: `courses/rollups.py:10-36` (imports + `_QUESTION_MODELS`)
- Test: `tests/test_analytics_rollups.py` (append)

**Interfaces:**
- Consumes: `courses.richtext.CONCRETE_QUESTION_MODELS` (a list of the ten concrete question model classes).
- Produces: `rollups._QUESTION_MODELS` now contains all ten; `_quiz_review_maps` and `quiz_gradeable_max` count grids. No signature changes.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_analytics_rollups.py`:

```python
# --- D9: both grid types reach the rollups (spec T41) -----------------------
def _choicegrid_q(unit, max_marks, mode):
    from courses.models import GridColumn
    from courses.models import GridRow
    from courses.models import ChoiceGridQuestionElement

    q = ChoiceGridQuestionElement.objects.create(
        stem="Grid", marking_mode=mode, max_marks=Decimal(max_marks)
    )
    yes = GridColumn.objects.create(question=q, label="yes")
    GridColumn.objects.create(question=q, label="no")
    GridRow.objects.create(question=q, statement="r1", correct_column=yes)
    return Element.objects.create(unit=unit, content_object=q)


def _multigrid_q(unit, max_marks, mode):
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow

    q = MultiGridQuestionElement.objects.create(
        stem="MultiGrid", marking_mode=mode, max_marks=Decimal(max_marks)
    )
    a = MultiGridColumn.objects.create(question=q, label="a")
    MultiGridColumn.objects.create(question=q, label="b")
    row = MultiGridRow.objects.create(question=q, statement="r1")
    row.correct_columns.set([a])
    return Element.objects.create(unit=unit, content_object=q)


def _pills(course, student):
    from courses.rollups import build_student_breakdown

    by_unit = {}

    def collect(nodes):
        for d in nodes:
            by_unit[d["node"].pk] = d
            collect(d["children"])

    collect(build_student_breakdown(course, student, drafts="keep")["tree"])
    return {pk: d.get("pill") for pk, d in by_unit.items()}


@pytest.mark.django_db
def test_grid_only_auto_quiz_pills_scored():
    from courses.models import QuestionElement

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _choicegrid_q(qz, "2", QuestionElement.MarkingMode.AUTO)
    s = UserFactory()
    QuizSubmission.objects.create(
        student=s,
        unit=qz,
        status="submitted",
        score=Decimal("2"),
        max_score=Decimal("2"),
    )
    assert _pills(course, s)[qz.pk]["kind"] == "scored"


@pytest.mark.django_db
def test_unreviewed_review_multigrid_pills_awaiting_then_submitted():
    from django.utils import timezone

    from courses.models import QuestionElement

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    el = _multigrid_q(qz, "1", QuestionElement.MarkingMode.REVIEW)
    s = UserFactory()
    sub = QuizSubmission.objects.create(
        student=s,
        unit=qz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    assert _pills(course, s)[qz.pk]["kind"] == "awaiting"
    QuestionResponse.objects.create(
        submission=sub,
        element=el,
        latest_answer=[[]],
        attempt_count=1,
        locked=True,
        earned_marks=Decimal("1"),
        fraction=Decimal("1.0000"),
        reviewed_at=timezone.now(),
    )
    # Behaviour check, NOT a D9 guard: under the 8-model list the multigrid is
    # absent from total_review AND reviewed_counts, so this pills "submitted"
    # either way (spec T41).
    assert _pills(course, s)[qz.pk]["kind"] == "submitted"


@pytest.mark.django_db
def test_gradeable_max_counts_a_grid():
    from courses.models import QuestionElement
    from courses.rollups import quiz_gradeable_max

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _choicegrid_q(qz, "2", QuestionElement.MarkingMode.AUTO)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", max_marks=Decimal("1")
    )
    Element.objects.create(unit=qz, content_object=q)
    assert quiz_gradeable_max([qz]) == {qz.pk: Decimal("3")}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k "grid_only_auto or unreviewed_review_multigrid or gradeable_max_counts_a_grid" -v`
Expected: `test_grid_only_auto_quiz_pills_scored` FAILS (`'submitted' == 'scored'`), `test_unreviewed_review_multigrid_pills_awaiting_then_submitted` FAILS at the first assert (`'submitted' == 'awaiting'`), `test_gradeable_max_counts_a_grid` FAILS (`Decimal('1')` vs `Decimal('3')`).

- [ ] **Step 3: Implement.** In `courses/rollups.py`:

1. Replace the block from the comment `# The 8 concrete QuestionElement subclasses…` through the closing `]` of `_QUESTION_MODELS` with:

```python
# Every concrete QuestionElement subclass -- the SAME source builder.py's
# unit_has_nested_question uses. A hand list here once omitted both grid types.
_QUESTION_MODELS = CONCRETE_QUESTION_MODELS
```

2. Add `from courses.richtext import CONCRETE_QUESTION_MODELS` to the import block (alphabetical position, after the `courses.models` imports).

3. Grep each of the eight concrete-model names for other uses in the file before deleting its import:

Run: `grep -nE "\b(ChoiceQuestionElement|ShortTextQuestionElement|ShortNumericQuestionElement|FillBlankQuestionElement|DragFillBlankQuestionElement|MatchPairQuestionElement|DragToImageQuestionElement|ExtendedResponseQuestionElement)\b" courses/rollups.py`

Delete the `from courses.models import X` line for every name whose ONLY remaining hit is its import line. Keep `ContentNode`, `Element`, `QuestionElement`, `QuestionResponse`, `QuizSubmission`, `UnitProgress` and any name still used.

- [ ] **Step 4: Run the tests and lint**

Run: `uv run pytest tests/test_analytics_rollups.py tests/test_courses_rollups.py tests/test_analytics_views.py tests/test_courses_views.py -v`
Expected: all PASS (read the summary line). `tests/test_courses_rollups.py` holds the main `build_course_results` tests (statuses, url names, done count, query count).
Run: `uv run ruff check --no-cache courses/rollups.py` — Expected: no F401.
Run: `uv run python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test'); django.setup(); import courses.rollups"` — Expected: no ImportError (no cycle).

- [ ] **Step 5: Falsify.** Temporarily restore the old 8-model list (paste the eight names back as a list literal, re-adding their imports). Run the Step 2 command. Expected RED: `test_grid_only_auto_quiz_pills_scored`, the first assert of `test_unreviewed_review_multigrid_pills_awaiting_then_submitted`, `test_gradeable_max_counts_a_grid`. Revert by hand; `git diff courses/rollups.py` shows only the Step 3 change.

- [ ] **Step 6: Commit**

```bash
git add courses/rollups.py tests/test_analytics_rollups.py
git commit -m "fix(analytics): rollups count both grid question types (D9)

_QUESTION_MODELS listed 8 models and omitted ChoiceGrid/MultiGrid, so a
grid-only AUTO quiz pilled 'submitted', a REVIEW grid never armed the
awaiting gate, and quiz_gradeable_max omitted grid marks. Now derived
from richtext.CONCRETE_QUESTION_MODELS.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 2: `_course_results_row` extraction and `submission_pk` on every pill

Implements spec §3.4 (row extraction, `course_results` comment) and §3.5 (`_quiz_pill` carries `submission_pk`), plus the moving tests in §6.

**Files:**
- Modify: `courses/rollups.py` — `build_course_results` loop and `_quiz_pill`
- Modify: `courses/views.py` — the comment inside `course_results` that begins `# build_course_results builds "rows" with three rows.append calls`
- Test: `tests/test_analytics_rollups.py:522-576` (bind + extend), append one test

**Interfaces:**
- Produces: `rollups._course_results_row(unit, sub, has_auto, total_review, reviewed_counts) -> dict` with exactly the keys `build_course_results` rows carry today: `unit, status, graded, score, max_score, pending, submission_pk, url_name`. `sub` may be `None` (not started).
- Produces: `rollups._quiz_pill(row)` returns `submission_pk` for kinds `scored`, `submitted`, `awaiting`, `in_progress`; `not_started` stays `{"kind": "not_started"}`.

- [ ] **Step 1: Update the moving tests first (they go red).** In `tests/test_analytics_rollups.py`, `test_build_student_breakdown_pills`: bind the scored submission and extend its dict:

```python
    sub_scored = QuizSubmission.objects.create(
        student=s,
        unit=scored,
        status="submitted",
        score=Decimal("9"),
        max_score=Decimal("10"),
    )
```

```python
    assert by_unit[scored.pk]["pill"] == {
        "kind": "scored",
        "score": Decimal("9"),
        "max_score": Decimal("10"),
        "percent": 90,
        "submission_pk": sub_scored.pk,
    }
```

In `test_build_student_breakdown_submitted_ungraded_no_percent`: bind `sub = QuizSubmission.objects.create(...)` and assert `pill == {"kind": "submitted", "submission_pk": sub.pk}`. Leave the `not_started` assert unchanged.

Append:

```python
@pytest.mark.django_db
def test_in_progress_pill_carries_submission_pk():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    s = UserFactory()
    sub = QuizSubmission.objects.create(student=s, unit=qz, status="in_progress")
    assert _pills(course, s)[qz.pk] == {
        "kind": "in_progress",
        "submission_pk": sub.pk,
    }
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_rollups.py -k "breakdown_pills or submitted_ungraded or in_progress_pill" -v`
Expected: 3 FAIL (dicts lack `submission_pk`).

- [ ] **Step 3: Extract the row.** In `courses/rollups.py`, add above `build_course_results`:

```python
def _course_results_row(unit, sub, has_auto, total_review, reviewed_counts):
    """One build_course_results row for `unit` and its submission `sub` (or None).
    Shared by build_course_results and the per-question page's header pill, so
    the header can never re-derive the pill differently from the breakdown."""
    if sub is None:
        return {
            "unit": unit,
            "status": "not_started",
            "graded": False,
            "score": None,
            "max_score": None,
            "pending": False,
            "submission_pk": None,
            "url_name": "courses:quiz_unit",
        }
    if sub.status == QuizSubmission.Status.IN_PROGRESS:
        return {
            "unit": unit,
            "status": "in_progress",
            "graded": False,
            "score": None,
            "max_score": None,
            "pending": False,
            "submission_pk": sub.pk,
            "url_name": "courses:quiz_unit",
        }
    graded = has_auto.get(unit.pk, False)  # ≡ max_score > 0 (max_marks >= 0.01)
    pending = not submission_is_counted(sub, total_review, reviewed_counts)
    return {
        "unit": unit,
        "status": "awaiting_review" if pending else "submitted",
        "graded": graded,
        "score": sub.score,
        "max_score": sub.max_score,
        "pending": pending,
        "submission_pk": sub.pk,
        "url_name": "courses:quiz_results",
    }
```

Replace the whole `for unit in units:` loop body in `build_course_results` with:

```python
    for unit in units:
        sub = submissions.get(unit.pk)
        row = _course_results_row(unit, sub, has_auto, total_review, reviewed_counts)
        rows.append(row)
        if row["status"] in ("submitted", "awaiting_review"):
            done_count += 1  # unchanged: pending still counts as submitted
            if not row["pending"]:
                score_sum += sub.score or Decimal("0")
                max_sum += sub.max_score or Decimal("0")
```

- [ ] **Step 4: Pill `submission_pk`.** Replace `_quiz_pill` with:

```python
def _quiz_pill(row):
    """Map a build_course_results row to a single-sourced status pill (spec §6).
    Every kind that has a submission carries its pk: the breakdown links the
    quiz title to the per-question page with it."""
    status = row["status"]
    if status == "submitted":
        if row["graded"] and row["max_score"]:
            # reuse the single-source percent rule (_pct guarantees b > 0, met here)
            return {
                "kind": "scored",
                "score": row["score"],
                "max_score": row["max_score"],
                "percent": _pct(row["score"], row["max_score"]),
                "submission_pk": row["submission_pk"],
            }
        # submitted but ungraded (max_score == 0): no percent
        return {"kind": "submitted", "submission_pk": row["submission_pk"]}
    if status == "awaiting_review":
        return {"kind": "awaiting", "submission_pk": row["submission_pk"]}
    if status == "in_progress":
        return {"kind": "in_progress", "submission_pk": row["submission_pk"]}
    return {"kind": "not_started"}
```

- [ ] **Step 5: Reword the stale comment, line-count neutral.** In `courses/views.py` `course_results`, replace the first line of the five-line comment

`    # build_course_results builds "rows" with three rows.append calls, so it is`

with

`    # build_course_results appends one row per unit to a real list, so it is`

The comment stays five lines. Check: `git diff --stat courses/views.py` shows `1 insertion(+), 1 deletion(-)`.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_analytics_rollups.py tests/test_courses_rollups.py tests/test_analytics_views.py tests/test_courses_views.py tests/test_e2e_results.py tests/test_review_services.py -v`
(`test_e2e_results.py` is `-m e2e`-marked and will be deselected; that is fine here — it runs in Task 13.)
Expected: all PASS.

- [ ] **Step 7: Falsify.** (a) In `_quiz_pill`, drop `"submission_pk"` from the `in_progress` return → `test_in_progress_pill_carries_submission_pk` RED. (b) In the loop, move `done_count += 1` under `if not row["pending"]` → `tests/test_courses_rollups.py::test_awaiting_review_until_all_reviewed` RED (`assert res["done_count"] == 1`). Revert both by hand; read `git diff`.

- [ ] **Step 7b: Commit**

```bash
git add courses/rollups.py courses/views.py tests/test_analytics_rollups.py
git commit -m "refactor(analytics): extract _course_results_row; pill carries submission_pk

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 3: `prefetch_question_children` replaces both prefetch copies

Implements spec §3.3 (extraction) and §5.1 (dragimage `media`). Behaviour-preserving for lesson and quiz pages except that dragimage `media` is now prefetched (N queries → 1).

**Files:**
- Modify: `courses/views.py` — `build_lesson_context` (the seven `if …_qs:` blocks after `questions = [...]`) and `build_quiz_context` (the identical blocks after its `questions = [...]`)
- Test: `tests/test_prefetch_question_children.py` (create)

**Interfaces:**
- Produces: `courses.views.prefetch_question_children(questions) -> None` — takes a list of concrete question instances (any mix of the ten types), prefetches per type: choice `choices`; fillblank `blanks`; dragfill `dragblanks`; matchpair `pairs`; dragimage `zones`, `media`; choicegrid `columns`, `rows`; multigrid `columns`, `rows`, `rows__correct_columns`. Types with no children (shorttext, shortnumeric, extendedresponse) cost nothing.

- [ ] **Step 1: Write the failing test** — create `tests/test_prefetch_question_children.py`:

```python
"""prefetch_question_children loads every child row mark()/the templates read,
so touching them afterwards issues ZERO queries (spec §3.3, §5.1)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import Blank
from courses.models import Choice
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MultiGridColumn
from courses.models import MultiGridRow
from courses.views import prefetch_question_children
from tests.factories import DragBlankFactory
from tests.factories import DragZoneFactory
from tests.factories import MatchPairFactory

pytestmark = pytest.mark.django_db


def _questions():
    """One question of each child-bearing type (self-contained on purpose:
    the answer_summary fixtures arrive in a later task)."""
    choice = ChoiceQuestionElement.objects.create(stem="c")
    Choice.objects.create(question=choice, text="a", is_correct=True)
    fb = FillBlankQuestionElement.objects.create(stem="x")
    Blank.objects.create(question=fb, accepted="1")
    cg = ChoiceGridQuestionElement.objects.create(stem="g")
    col = GridColumn.objects.create(question=cg, label="y")
    GridRow.objects.create(question=cg, statement="r", correct_column=col)
    mg = MultiGridQuestionElement.objects.create(stem="m")
    mcol = MultiGridColumn.objects.create(question=mg, label="a")
    MultiGridRow.objects.create(question=mg, statement="r").correct_columns.set([mcol])
    return [
        choice,
        fb,
        DragBlankFactory().question,
        DragZoneFactory().question,
        MatchPairFactory().question,
        cg,
        mg,
    ]


def _touch(q):
    if isinstance(q, ChoiceQuestionElement):
        list(q.choices.all())
    elif isinstance(q, FillBlankQuestionElement):
        list(q.blanks.all())
    elif isinstance(q, DragFillBlankQuestionElement):
        list(q.dragblanks.all())
    elif isinstance(q, MatchPairQuestionElement):
        list(q.pairs.all())
    elif isinstance(q, DragToImageQuestionElement):
        list(q.zones.all())
        _ = q.media.file.name
    elif isinstance(q, ChoiceGridQuestionElement):
        list(q.columns.all())
        list(q.rows.all())
    elif isinstance(q, MultiGridQuestionElement):
        list(q.columns.all())
        for row in q.rows.all():
            list(row.correct_columns.all())


def test_children_and_media_need_no_query_after_prefetch():
    # Fresh instances: the builders' own objects may carry caches.
    fresh = [type(q).objects.get(pk=q.pk) for q in _questions()]
    prefetch_question_children(fresh)
    with CaptureQueriesContext(connection) as captured:
        for q in fresh:
            _touch(q)
    assert len(captured) == 0, [c["sql"] for c in captured]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_prefetch_question_children.py -v`
Expected: FAIL with `ImportError: cannot import name 'prefetch_question_children'`.

- [ ] **Step 3: Implement.** In `courses/views.py`, add above `build_lesson_context`:

```python
def prefetch_question_children(questions):
    """Prefetch every child row a question's mark()/templates read, one query per
    type present. THE single copy: build_lesson_context, build_quiz_context and
    the per-question analytics page all call it. Adds dragimage `media` (a FK
    the element template dereferences) to what the two old copies loaded."""
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    dragimage_qs = [q for q in questions if isinstance(q, DragToImageQuestionElement)]
    choicegrid_qs = [q for q in questions if isinstance(q, ChoiceGridQuestionElement)]
    multigrid_qs = [q for q in questions if isinstance(q, MultiGridQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
    if dragimage_qs:
        prefetch_related_objects(dragimage_qs, "zones", "media")
    if choicegrid_qs:
        prefetch_related_objects(choicegrid_qs, "columns", "rows")
    if multigrid_qs:
        prefetch_related_objects(
            multigrid_qs, "columns", "rows", "rows__correct_columns"
        )
```

In `build_lesson_context`, the comment beginning `# SECOND ACCEPTED LIMITATION, same shape:` names `choice_qs`/`fill_qs`, which stop existing there. Reword its five lines to (still five lines):

```python
    # SECOND ACCEPTED LIMITATION, same shape: prefetch_question_children(questions)
    # takes `questions` from `elements` (parent__isnull=True), so a NESTED choice
    # question re-queries choices.all() per render. Bounded (per-unit question counts
    # are small) and pre-existing for nested fill_blank's `blanks`. Closing it would
    # cost an extra flat query on EVERY lesson render, most of which have no nesting.
```

In `build_lesson_context`, replace the seven `…_qs = [...]` lines and the seven `if …_qs:` blocks (keep the `questions = [...]` list above them) with the single line:

```python
    prefetch_question_children(questions)
```

Do the same in `build_quiz_context`, keeping its two-line comment `# Mirror build_lesson_context: the GFK prefetch does NOT fetch choices/blanks,` / `# so prefetch them explicitly (avoids N+1 in render/scoring/results).` above the call. **Do not delete `questions` in either builder** — later code in both reads it (`build_quiz_context` uses it for `has_math`). Verify: `grep -n "questions" courses/views.py` still shows uses after each call.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_prefetch_question_children.py courses/tests/test_callout_has_math.py courses/tests/test_nested_question_nojs_feedback.py tests/test_quiz_results_render.py tests/test_questions_2d_consumption.py tests/test_context_choicegrid.py tests/test_context_multigrid.py -v`
Expected: all PASS.

Then find pinned query budgets that could move with the new `media` prefetch:
Run: `grep -rln "CaptureQueriesContext\|assertNumQueries\|django_assert_num_queries" tests courses/tests`
For each file that exercises a lesson or quiz page containing a drag-to-image question, run it. Expected: PASS. If one fails on an exact count, confirm the difference is the dragimage `media` query (N → 1), update the pinned number, and say so in the commit body.

- [ ] **Step 5: Falsify.** Remove `"media"` from the dragimage prefetch → `test_children_and_media_need_no_query_after_prefetch` RED (one captured query). Revert by hand; `git diff`.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py tests/test_prefetch_question_children.py
git commit -m "refactor(courses): one prefetch_question_children for lesson, quiz and analytics

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

⚠️ This commit shifts every later line in `courses/views.py`. Task 13 re-points the citations into it; do not chase them here.

---

### Task 4: `answer_summary` — contract, registry, single-part types

Implements spec §4.1, §4.2, §4.3 (choice, shorttext, shortnumeric, extendedresponse rows), §4.4, T32/T33/T34 for those types.

**Files:**
- Create: `tests/answer_summary_fixtures.py`
- Create: `courses/answer_summary.py`
- Create: `tests/test_answer_summary.py`

**Interfaces:**
- Produces (`courses/answer_summary.py`):
  - `ANSWER = "answer"`, `KEYWORD = "keyword"`
  - `@dataclass(frozen=True) class Part: kind: str; label_is_content: bool; label: str | None; given: str | None; expected: str | None; ok: bool | None` with property `mark -> "correct" | "incorrect" | None` (None when `ok is None`, or when `kind == ANSWER and given is None and ok is True`).
  - `summarise(question, response, mark_result) -> list[Part]` — `response` needs only `.latest_answer` (or is `None`); `mark_result` is `_results_row`'s `reveal_result` (a `MarkResult` for AUTO, else `None`).
  - `_ADAPTERS: dict[type, callable]` — Task 5 adds the six multi-part types.
- Produces (`tests/answer_summary_fixtures.py`): `build_all_types(mode=QuestionElement.MarkingMode.AUTO) -> dict[str, QuestionElement]` keyed `"choice", "shorttext", "shortnumeric", "extendedresponse", "fillblank", "dragfill", "dragimage", "matchpair", "choicegrid", "multigrid"`; and `summarise_stored(question, stored, *, unanswered=False) -> list[Part]` which builds `mark_result` exactly as `_results_row` does.

- [ ] **Step 1: Fixture module** — create `tests/answer_summary_fixtures.py`:

```python
"""One question of every concrete type, for answer_summary and query-budget tests.

Shapes mirror tests/demo/test_builders.py::_fixtures. GridRow/MultiGridRow use
`statement`; only the *Column models have `label`."""

from decimal import Decimal
from types import SimpleNamespace

from django.http import QueryDict

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.quiz import answer_from_json
from tests.factories import MediaAssetFactory

AUTO = QuestionElement.MarkingMode.AUTO
TOKEN0 = "￿0￿"
TOKEN1 = "￿1￿"


def build_all_types(mode=AUTO):
    common = {"marking_mode": mode, "max_marks": Decimal("1")}
    made = {}

    choice = ChoiceQuestionElement.objects.create(stem="Primes?", multiple=True, **common)
    for order, (text, ok) in enumerate((("2", True), ("3", True), ("4", False))):
        Choice.objects.create(question=choice, text=text, is_correct=ok, order=order)
    made["choice"] = choice

    made["shorttext"] = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Warszawa\nWarsaw", **common
    )
    made["shortnumeric"] = ShortNumericQuestionElement.objects.create(
        stem="Half?", value="1/2", tolerance="", **common
    )
    made["extendedresponse"] = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.", required_keywords="alpha\nbeta", forbidden_keywords="gamma",
        **common,
    )

    fb = FillBlankQuestionElement.objects.create(
        stem=f"2 + {TOKEN0} = {TOKEN1}", **common
    )
    Blank.objects.create(question=fb, accepted="2", order=0)
    Blank.objects.create(question=fb, accepted="4", order=1)
    made["fillblank"] = fb

    df = DragFillBlankQuestionElement.objects.create(
        stem=f"{TOKEN0} and {TOKEN1}", distractors="x", **common
    )
    DragBlank.objects.create(question=df, correct_token="cat", order=0)
    DragBlank.objects.create(question=df, correct_token="dog", order=1)
    made["dragfill"] = df

    di = DragToImageQuestionElement.objects.create(
        stem="", media=MediaAssetFactory(), alt="A heart", distractors="", **common
    )
    DragZone.objects.create(question=di, correct_label="Heart", x=0.1, y=0.1, w=0.2, h=0.2, order=0)
    DragZone.objects.create(question=di, correct_label="Liver", x=0.5, y=0.5, w=0.2, h=0.2, order=1)
    made["dragimage"] = di

    mp = MatchPairQuestionElement.objects.create(stem="Match", distractors="", **common)
    for order, (left, right) in enumerate((("a", "1"), ("b", "2"), ("c", "3"))):
        MatchPair.objects.create(question=mp, left=left, right=right, order=order)
    made["matchpair"] = mp

    cg = ChoiceGridQuestionElement.objects.create(stem="Grid", **common)
    yes = GridColumn.objects.create(question=cg, label="yes", order=0)
    no = GridColumn.objects.create(question=cg, label="no", order=1)
    GridRow.objects.create(question=cg, statement="r1", correct_column=yes, order=0)
    GridRow.objects.create(question=cg, statement="r2", correct_column=no, order=1)
    made["choicegrid"] = cg

    mg = MultiGridQuestionElement.objects.create(stem="MultiGrid", **common)
    cols = [
        MultiGridColumn.objects.create(question=mg, label=label, order=i)
        for i, label in enumerate(("a", "b", "c"))
    ]
    r1 = MultiGridRow.objects.create(question=mg, statement="r1", order=0)
    r1.correct_columns.set(cols[:2])
    r2 = MultiGridRow.objects.create(question=mg, statement="r2", order=1)
    r2.correct_columns.set(cols[2:])
    made["multigrid"] = mg

    return made


def summarise_stored(question, stored, *, unanswered=False):
    """summarise() fed exactly as views._results_row feeds it."""
    from courses.answer_summary import summarise

    response = None if unanswered else SimpleNamespace(latest_answer=stored)
    if question.marking_mode != AUTO:
        mark_result = None
    elif response is None or stored is None:
        mark_result = question.mark(question.build_answer(QueryDict()))
    else:
        mark_result = question.mark(answer_from_json(question, stored))
    return summarise(question, response, mark_result)
```

If any `order=` keyword raises because the model's `order` is an `OrderField` that rejects explicit values, drop the explicit `order=` arguments — creation order already yields `(order, pk)` order.

- [ ] **Step 2: Write the failing tests** — create `tests/test_answer_summary.py`:

```python
"""courses.answer_summary (spec §4; tests T32, T33, T34)."""

import pytest

from courses.answer_summary import ANSWER
from courses.answer_summary import KEYWORD
from courses.answer_summary import Part
from courses.models import Choice
from courses.models import QuestionElement
from tests.answer_summary_fixtures import build_all_types
from tests.answer_summary_fixtures import summarise_stored

pytestmark = pytest.mark.django_db
REVIEW = QuestionElement.MarkingMode.REVIEW


def _answer(given, expected, ok, label=None, label_is_content=False):
    return Part(
        kind=ANSWER,
        label_is_content=label_is_content,
        label=label,
        given=given,
        expected=expected,
        ok=ok,
    )


def _pks(q, *texts):
    return sorted(c.pk for c in q.choices.all() if c.text in texts)


# --- choice ------------------------------------------------------------------
def test_choice_correct_wrong_unanswered():
    q = build_all_types()["choice"]
    assert summarise_stored(q, _pks(q, "2", "3")) == [_answer("2, 3", None, True)]
    assert summarise_stored(q, _pks(q, "2", "4")) == [_answer("2, 4", "2, 3", False)]
    assert summarise_stored(q, None, unanswered=True) == [_answer(None, "2, 3", False)]


def test_choice_single_select():
    q = build_all_types()["choice"]
    q.multiple = False
    q.save()
    assert summarise_stored(q, _pks(q, "4")) == [_answer("4", "2, 3", False)]


def test_choice_review_mode_has_no_expected_or_ok():
    q = build_all_types(mode=REVIEW)["choice"]
    assert summarise_stored(q, _pks(q, "4")) == [_answer("4", None, None)]


def test_choice_removed_option_appended_after_live_texts():
    q = build_all_types()["choice"]
    gone = Choice.objects.get(question=q, text="3")
    stored = sorted([gone.pk, *_pks(q, "2")])
    gone.delete()
    parts = summarise_stored(q, stored)
    assert parts[0].given == "2, (removed option)"


def test_choice_with_no_correct_option_expects_none_label():
    q = build_all_types()["choice"]
    Choice.objects.filter(question=q).update(is_correct=False)
    assert summarise_stored(q, _pks(q, "4")) == [_answer("4", "(none)", False)]


# --- shorttext / shortnumeric ------------------------------------------------
def test_shorttext_correct_wrong_unanswered_review():
    made = build_all_types()
    q = made["shorttext"]
    assert summarise_stored(q, "warsaw") == [_answer("warsaw", None, True)]
    assert summarise_stored(q, "Krakow") == [_answer("Krakow", "Warszawa", False)]
    assert summarise_stored(q, None, unanswered=True) == [
        _answer(None, "Warszawa", False)
    ]
    r = build_all_types(mode=REVIEW)["shorttext"]
    assert summarise_stored(r, "Krakow") == [_answer("Krakow", None, None)]


def test_shortnumeric_ok_is_read_from_mark_not_string_compare():
    q = build_all_types()["shortnumeric"]
    # "0,5" != "1/2" as strings, but mark() accepts it (spec T32 mutant).
    assert summarise_stored(q, "0,5") == [_answer("0,5", None, True)]
    assert summarise_stored(q, "3") == [_answer("3", "1/2", False)]


def test_shortnumeric_expected_carries_tolerance():
    q = build_all_types()["shortnumeric"]
    q.tolerance = "1/10"
    q.save()
    assert summarise_stored(q, "3")[0].expected == "1/2 ± 1/10"


# --- extendedresponse --------------------------------------------------------
def _kw(label, ok):
    return Part(
        kind=KEYWORD, label_is_content=False, label=label, given=None, expected=None, ok=ok
    )


def test_extendedresponse_partial_text_part_is_not_ok():
    q = build_all_types()["extendedresponse"]
    parts = summarise_stored(q, "alpha only")
    assert parts == [
        _answer("alpha only", None, False),
        _kw("Required: alpha", True),
        _kw("Required: beta", False),
        _kw("Avoid: gamma", True),
    ]


def test_extendedresponse_unanswered_keyword_parts_are_unjudged():
    q = build_all_types()["extendedresponse"]
    assert summarise_stored(q, None, unanswered=True) == [
        _answer(None, None, False),
        _kw("Required: alpha", None),
        _kw("Required: beta", None),
        _kw("Avoid: gamma", None),
    ]


def test_extendedresponse_no_keywords_unanswered_is_still_not_ok():
    q = build_all_types()["extendedresponse"]
    q.required_keywords = ""
    q.forbidden_keywords = ""
    q.save()
    # mark_keywords("", [], []) is correct=True; rule 3 wins (spec §4.2).
    assert summarise_stored(q, None, unanswered=True) == [_answer(None, None, False)]


def test_extendedresponse_review_mode_keeps_keywords_but_emits_one_part():
    q = build_all_types(mode=REVIEW)["extendedresponse"]
    assert q.required_keywords  # stale keywords really are on the row
    assert summarise_stored(q, "some text") == [_answer("some text", None, None)]


# --- Part.mark: the glyph unit ----------------------------------------------
def test_part_mark_suppresses_tick_on_an_empty_answer_part():
    assert _answer(None, None, True).mark is None
    assert _answer(None, "x", False).mark == "incorrect"
    assert _answer("x", None, True).mark == "correct"
    assert _answer("x", None, None).mark is None
    assert _kw("Required: a", True).mark == "correct"
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_answer_summary.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'courses.answer_summary'`.

- [ ] **Step 4: Implement** — create `courses/answer_summary.py`:

```python
"""Teacher-side display of one pupil's stored quiz answer (spec §4).

Side-effect free: no writes, no RNG. Reads only the child rows
courses.views.prefetch_question_children loads. `mark_result` is always the
caller's (views._results_row's reveal_result) -- `ok` is read from it, never
re-derived. No catch-all fail-open: an unregistered type raises KeyError.
"""

from dataclasses import dataclass

from django.utils.translation import gettext as _

from courses.models import ChoiceQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement

ANSWER = "answer"
KEYWORD = "keyword"


@dataclass(frozen=True)
class Part:
    kind: str
    label_is_content: bool
    label: str | None
    given: str | None
    expected: str | None
    ok: bool | None

    @property
    def mark(self):
        """The ✓/✗ glyph AND its sr-only label, as one unit (spec §5.1)."""
        if self.ok is None:
            return None
        if self.ok and self.kind == ANSWER and self.given is None:
            return None
        return "correct" if self.ok else "incorrect"


def _is_auto(question):
    return question.marking_mode == QuestionElement.MarkingMode.AUTO


def _answered(response):
    return response is not None and response.latest_answer is not None


def _text_or_none(value):
    """A string part is empty iff blank after strip (spec §4.2 rule 4)."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _answer_part(*, given, expected, ok, label=None, label_is_content=False):
    return Part(
        kind=ANSWER,
        label_is_content=label_is_content,
        label=label,
        given=given,
        # rule 2: the hint only where the part is not right
        expected=None if ok is True else expected,
        ok=ok,
    )


def _single(question, response, given, expected_when_auto, correct):
    """One answer part for a single-part type, applying rules 1-3."""
    if not _is_auto(question):
        return [_answer_part(given=given, expected=None, ok=None)]
    ok = bool(correct) if _answered(response) else False
    return [_answer_part(given=given, expected=expected_when_auto, ok=ok)]


def _choice(question, response, mark_result):
    choices = list(question.choices.all())
    given = None
    if _answered(response):
        picked = set(response.latest_answer or [])
        live = {c.pk for c in choices}
        texts = [c.text for c in choices if c.pk in picked]
        texts += [_("(removed option)")] * len(picked - live)
        given = ", ".join(texts) or None
    expected = None
    correct = None
    if _is_auto(question):
        correct_set = set(mark_result.reveal or ())
        expected = ", ".join(c.text for c in choices if c.pk in correct_set) or _(
            "(none)"
        )
        correct = mark_result.correct
    return _single(question, response, given, expected, correct)


def _shorttext(question, response, mark_result):
    given = _text_or_none(response.latest_answer) if _answered(response) else None
    if not _is_auto(question):
        return _single(question, response, given, None, None)
    return _single(question, response, given, mark_result.reveal, mark_result.correct)


def _shortnumeric(question, response, mark_result):
    given = _text_or_none(response.latest_answer) if _answered(response) else None
    if not _is_auto(question):
        return _single(question, response, given, None, None)
    reveal = mark_result.reveal
    expected = reveal["value"]
    if reveal["tolerance"]:
        expected = f"{expected} ± {reveal['tolerance']}"
    return _single(question, response, given, expected, mark_result.correct)


def _extendedresponse(question, response, mark_result):
    answered = _answered(response)
    given = _text_or_none(response.latest_answer) if answered else None
    if not _is_auto(question):
        # keyword parts are AUTO-only: stale keywords on a REVIEW row are ignored
        return [_answer_part(given=given, expected=None, ok=None)]
    parts = [
        _answer_part(
            given=given, expected=None, ok=bool(mark_result.correct) if answered else False
        )
    ]
    for item in mark_result.reveal:
        required = item["kind"] == "required"
        prefix = _("Required") if required else _("Avoid")
        if not answered:
            ok = None
        else:
            ok = item["found"] if required else not item["found"]
        parts.append(
            Part(
                kind=KEYWORD,
                label_is_content=False,
                label=f"{prefix}: {item['keyword']}",
                given=None,
                expected=None,
                ok=ok,
            )
        )
    return parts


_ADAPTERS = {
    ChoiceQuestionElement: _choice,
    ShortTextQuestionElement: _shorttext,
    ShortNumericQuestionElement: _shortnumeric,
    ExtendedResponseQuestionElement: _extendedresponse,
}


def summarise(question, response, mark_result):
    """Display parts for one question's stored answer (spec §4.1)."""
    return _ADAPTERS[type(question)](question, response, mark_result)
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_answer_summary.py -v`
Expected: every test PASSES. (The registry drift guard is written in Task 5, once all ten types are registered — committing a red guard here would leave the branch red between tasks.)

- [ ] **Step 6: Falsify** (each by hand, run `tests/test_answer_summary.py`, observe RED, revert, read `git diff`):
  - (a) `_answer_part`: `expected=expected` (drop rule 2) → `test_choice_correct_wrong_unanswered` RED.
  - (b) `_shortnumeric`: `ok = given == expected` instead of `mark_result.correct` → `test_shortnumeric_ok_is_read_from_mark_not_string_compare` RED.
  - (c) `_single` non-AUTO branch: `return [_answer_part(given=given, expected=None, ok=False)]` (a REVIEW copy judged wrong) → `test_shorttext_correct_wrong_unanswered_review` RED (`ok` False vs None). (Passing `expected_when_auto` there would be an equivalent mutant: every caller already passes `None` for non-AUTO.)
  - (d) `_extendedresponse`: text part `ok=mark_result.fraction > 0` → `test_extendedresponse_partial_text_part_is_not_ok` RED.
  - (e) `_extendedresponse` non-AUTO branch: before returning, append one `Part(kind=KEYWORD, label_is_content=False, label=f"Required: {line}", given=None, expected=None, ok=None)` per line of `question.required_keywords.splitlines()` → `test_extendedresponse_review_mode_keeps_keywords_but_emits_one_part` RED on the part-list assertion (three parts instead of one). (Moving the reveal loop above the return instead would crash on `mark_result=None` — red for the wrong reason.)
  - (f) `_choice`: `expected = ", ".join(...)` without `or _("(none)")` → `test_choice_with_no_correct_option_expects_none_label` RED.
  - (g) `Part.mark`: delete the `given is None` line → `test_part_mark_suppresses_tick_on_an_empty_answer_part` RED.

- [ ] **Step 7: Commit**

```bash
git add courses/answer_summary.py tests/test_answer_summary.py tests/answer_summary_fixtures.py
git commit -m "feat(analytics): answer_summary contract and single-part question types

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 5: `answer_summary` — multi-part types, token stems, drift guard

Implements spec §4.3 (fillblank, dragfill, dragimage, matchpair, choicegrid, multigrid rows; content-drift bullets that are pure), §4.4, §5.1 (`gap_marked_stem`, `stem_html`), T32/T33/T34.

**Files:**
- Modify: `courses/answer_summary.py`
- Modify: `tests/test_answer_summary.py` (append)

**Interfaces:**
- Consumes: Task 4's `Part`, `_answer_part`, `_answered`, `_is_auto`, `_text_or_none`, `_ADAPTERS`; `courses.fillblank._TOKEN_RE` (compiled `"￿(\d+)￿"`, group 1 = 0-based gap index).
- Produces: `_ADAPTERS` holds all ten concrete types; `gap_marked_stem(question) -> SafeString`; `stem_html(question) -> SafeString` (token types → `gap_marked_stem`, every other type → `mark_safe(question.stem)`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_answer_summary.py` (add `from django.apps import apps` and `from courses import answer_summary` to its module imports — **not** `mock`, which only the temporary Falsify test uses and which ruff's F401 would flag; `stem_html` is imported **inside** the two stem tests, so its absence fails those two tests instead of breaking collection of the whole file):

```python
# --- T34 drift guard ---------------------------------------------------------
def _derived_question_models():
    # issubclass only -- NOT also filtering _meta.abstract (spec §4.4, T34).
    return {m for m in apps.get_models() if issubclass(m, QuestionElement)}


def test_registry_covers_every_concrete_question_model():
    assert _derived_question_models() == set(answer_summary._ADAPTERS)


# --- fillblank ---------------------------------------------------------------
def _gap(i, given, expected, ok):
    return _answer(given, expected, ok, label=f"Gap {i}")


def test_fillblank_correct_partial_unanswered_review():
    q = build_all_types()["fillblank"]
    assert summarise_stored(q, ["2", "4"]) == [
        _gap(1, "2", None, True),
        _gap(2, "4", None, True),
    ]
    assert summarise_stored(q, ["2", "5"]) == [
        _gap(1, "2", None, True),
        _gap(2, "5", "4", False),
    ]
    assert summarise_stored(q, None, unanswered=True) == [
        _gap(1, None, "2", False),
        _gap(2, None, "4", False),
    ]
    r = build_all_types(mode=REVIEW)["fillblank"]
    assert summarise_stored(r, ["2", "5"]) == [
        _gap(1, "2", None, None),
        _gap(2, "5", None, None),
    ]


def test_fillblank_whitespace_gap_is_empty():
    q = build_all_types()["fillblank"]
    assert summarise_stored(q, ["2", "  "])[1] == _gap(2, None, "4", False)


def test_fillblank_fewer_and_more_stored_values_follow_current_blanks():
    q = build_all_types()["fillblank"]
    assert summarise_stored(q, ["2"]) == [
        _gap(1, "2", None, True),
        _gap(2, None, "4", False),
    ]
    assert len(summarise_stored(q, ["2", "4", "9"])) == 2


def test_fillblank_with_no_blanks_left_yields_no_parts():
    q = build_all_types()["fillblank"]
    q.blanks.all().delete()
    assert summarise_stored(q, ["2", "4"]) == []


# --- drag types --------------------------------------------------------------
def test_dragfill_parts():
    q = build_all_types()["dragfill"]
    assert summarise_stored(q, ["dog", "dog"]) == [
        _gap(1, "dog", "cat", False),
        _gap(2, "dog", None, True),
    ]


def test_dragimage_parts_are_labelled_by_zone():
    q = build_all_types()["dragimage"]
    assert summarise_stored(q, ["Heart", "Heart"]) == [
        _answer("Heart", None, True, label="Zone 1"),
        _answer("Heart", "Liver", False, label="Zone 2"),
    ]


def test_matchpair_labels_are_course_content():
    q = build_all_types()["matchpair"]
    parts = summarise_stored(q, ["1", "3", "2"])
    assert parts == [
        _answer("1", None, True, label="a", label_is_content=True),
        _answer("3", "2", False, label="b", label_is_content=True),
        _answer("2", "3", False, label="c", label_is_content=True),
    ]


# --- grids -------------------------------------------------------------------
def _cols(q):
    return {c.label: c.pk for c in q.columns.all()}


def test_choicegrid_parts_empty_row_and_removed_column():
    q = build_all_types()["choicegrid"]
    cols = _cols(q)
    assert summarise_stored(q, [cols["yes"], ""]) == [
        _answer("yes", None, True, label="r1", label_is_content=True),
        _answer(None, "no", False, label="r2", label_is_content=True),
    ]
    missing = max(cols.values()) + 1000
    parts = summarise_stored(q, [missing, cols["no"]])
    # reveal["chosen_label"] is None for BOTH "" and a removed pk (spec §4.3):
    assert parts[0] == _answer(
        "(removed option)", "yes", False, label="r1", label_is_content=True
    )


def test_multigrid_parts_removed_pk_and_empty_set():
    q = build_all_types()["multigrid"]
    cols = _cols(q)
    missing = max(cols.values()) + 1000
    assert summarise_stored(q, [[cols["a"], cols["b"]], [cols["c"]]]) == [
        _answer("a, b", None, True, label="r1", label_is_content=True),
        _answer("c", None, True, label="r2", label_is_content=True),
    ]
    assert summarise_stored(q, [[cols["a"], missing], []]) == [
        _answer(
            "a, (removed option)", "a, b", False, label="r1", label_is_content=True
        ),
        _answer(None, "c", False, label="r2", label_is_content=True),
    ]


def test_multigrid_row_with_empty_correct_set_expects_none_label():
    q = build_all_types()["multigrid"]
    cols = _cols(q)
    r2 = q.rows.get(statement="r2")
    r2.correct_columns.set([])
    parts = summarise_stored(q, [[cols["a"], cols["b"]], [cols["c"]]])
    assert parts[1] == _answer("c", "(none)", False, label="r2", label_is_content=True)


def test_review_matchpair_and_choicegrid_take_labels_from_child_rows():
    made = build_all_types(mode=REVIEW)
    mp = summarise_stored(made["matchpair"], ["1", "3", "2"])
    assert [p.label for p in mp] == ["a", "b", "c"]
    assert all(p.ok is None and p.expected is None for p in mp)
    cg = made["choicegrid"]
    parts = summarise_stored(cg, [_cols(cg)["no"], ""])
    assert [(p.label, p.given, p.ok) for p in parts] == [
        ("r1", "no", None),
        ("r2", None, None),
    ]


# --- T32 matrix: the remaining unanswered-AUTO, REVIEW-copy and partial cases -----
def test_unanswered_auto_parts_for_every_remaining_type():
    made = build_all_types()

    def run(key):
        return summarise_stored(made[key], None, unanswered=True)

    assert run("shortnumeric") == [_answer(None, "1/2", False)]
    assert run("dragfill") == [_gap(1, None, "cat", False), _gap(2, None, "dog", False)]
    assert run("dragimage") == [
        _answer(None, "Heart", False, label="Zone 1"),
        _answer(None, "Liver", False, label="Zone 2"),
    ]
    assert run("matchpair") == [
        _answer(None, right, False, label=left, label_is_content=True)
        for left, right in (("a", "1"), ("b", "2"), ("c", "3"))
    ]
    assert run("choicegrid") == [
        _answer(None, "yes", False, label="r1", label_is_content=True),
        _answer(None, "no", False, label="r2", label_is_content=True),
    ]
    assert run("multigrid") == [
        _answer(None, "a, b", False, label="r1", label_is_content=True),
        _answer(None, "c", False, label="r2", label_is_content=True),
    ]


def test_review_copies_of_every_remaining_type_carry_given_only():
    made = build_all_types(mode=REVIEW)
    assert summarise_stored(made["shortnumeric"], "3") == [_answer("3", None, None)]
    assert summarise_stored(made["dragfill"], ["dog", "cat"]) == [
        _gap(1, "dog", None, None),
        _gap(2, "cat", None, None),
    ]
    assert summarise_stored(made["dragimage"], ["Liver", "Heart"]) == [
        _answer("Liver", None, None, label="Zone 1"),
        _answer("Heart", None, None, label="Zone 2"),
    ]
    mg = made["multigrid"]
    cols = _cols(mg)
    assert summarise_stored(mg, [[cols["a"]], []]) == [
        _answer("a", None, None, label="r1", label_is_content=True),
        _answer(None, None, None, label="r2", label_is_content=True),
    ]


def test_multigrid_partial_one_row_right_one_wrong():
    q = build_all_types()["multigrid"]
    cols = _cols(q)
    assert summarise_stored(q, [[cols["a"], cols["b"]], [cols["a"]]]) == [
        _answer("a, b", None, True, label="r1", label_is_content=True),
        _answer("a", "c", False, label="r2", label_is_content=True),
    ]


# --- token stems --------------------------------------------------------------
def test_token_stems_are_gap_marked_like_the_part_labels():
    from courses.answer_summary import stem_html

    made = build_all_types()
    for key in ("fillblank", "dragfill"):
        html = str(stem_html(made[key]))
        assert "￿" not in html
        assert html.index("[1]") < html.index("[2]")
        assert '<span class="answers__gap">[1]</span>' in html


def test_other_stems_render_unchanged():
    from courses.answer_summary import stem_html

    q = build_all_types()["shorttext"]
    assert str(stem_html(q)) == q.stem
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_answer_summary.py -v`
Expected: the new tests FAIL — `KeyError` for the multi-part types, `ImportError: cannot import name 'stem_html'` inside the two stem tests; the drift guard FAILS listing six models. Task 4's tests still PASS.

- [ ] **Step 3: Implement** — in `courses/answer_summary.py` add the imports

```python
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from courses.fillblank import _TOKEN_RE
from courses.models import ChoiceGridQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
```

and, above `_ADAPTERS`:

```python
def _padded(stored, count, empty):
    """Pad/truncate a stored positional answer to the question's CURRENT part
    count, exactly as each mark() does, so parts and reveal align by index."""
    values = list(stored) if isinstance(stored, (list, tuple)) else []
    return (values + [empty] * count)[:count]


def _multi(question, response, mark_result, *, labels, content_labels, convert,
           empty, expected_of, ok_of):
    """One answer part per child row. Labels and the part count come from the
    CURRENT child rows in every mode; reveal[i] is read only for AUTO."""
    count = len(labels)
    answered = _answered(response)
    values = _padded(response.latest_answer if answered else None, count, empty)
    auto = _is_auto(question)
    parts = []
    for i, label in enumerate(labels):
        given = convert(values[i]) if answered else None
        if not auto:
            expected, ok = None, None
        else:
            item = mark_result.reveal[i]
            expected = expected_of(item)
            ok = bool(ok_of(item)) if answered else False
        parts.append(
            _answer_part(
                label=label,
                label_is_content=content_labels,
                given=given,
                expected=expected,
                ok=ok,
            )
        )
    return parts


def _numbered(label, count):
    return [label % {"n": i + 1} for i in range(count)]


def _fillblank(question, response, mark_result):
    return _multi(
        question, response, mark_result,
        labels=_numbered(_("Gap %(n)s"), len(question.blanks.all())),
        content_labels=False, convert=_text_or_none, empty=None,
        expected_of=lambda item: item["accepted"], ok_of=lambda item: item["correct"],
    )


def _dragfill(question, response, mark_result):
    return _multi(
        question, response, mark_result,
        labels=_numbered(_("Gap %(n)s"), len(question.dragblanks.all())),
        content_labels=False, convert=_text_or_none, empty=None,
        expected_of=lambda item: item["accepted"], ok_of=lambda item: item["correct"],
    )


def _dragimage(question, response, mark_result):
    return _multi(
        question, response, mark_result,
        labels=_numbered(_("Zone %(n)s"), len(question.zones.all())),
        content_labels=False, convert=_text_or_none, empty=None,
        expected_of=lambda item: item["accepted"], ok_of=lambda item: item["correct"],
    )


def _matchpair(question, response, mark_result):
    return _multi(
        question, response, mark_result,
        labels=[pair.left for pair in question.pairs.all()],
        content_labels=True, convert=_text_or_none, empty=None,
        expected_of=lambda item: item["accepted"], ok_of=lambda item: item["correct"],
    )


def _choicegrid(question, response, mark_result):
    by_pk = {c.pk: c.label for c in question.columns.all()}

    def convert(value):
        if value in ("", None):
            return None
        return by_pk.get(value, _("(removed option)"))

    return _multi(
        question, response, mark_result,
        labels=[row.statement for row in question.rows.all()],
        content_labels=True, convert=convert, empty="",
        expected_of=lambda item: item["correct_label"],
        ok_of=lambda item: item["is_correct"],
    )


def _multigrid(question, response, mark_result):
    columns = list(question.columns.all())
    live = {c.pk for c in columns}

    def convert(value):
        chosen = set(value) if isinstance(value, (list, tuple)) else set()
        if not chosen:
            return None
        texts = [c.label for c in columns if c.pk in chosen]
        texts += [_("(removed option)")] * len(chosen - live)
        return ", ".join(texts)

    return _multi(
        question, response, mark_result,
        labels=[row.statement for row in question.rows.all()],
        content_labels=True, convert=convert, empty=[],
        expected_of=lambda item: ", ".join(item["correct_labels"]) or _("(none)"),
        ok_of=lambda item: item["is_correct"],
    )


def gap_marked_stem(question):
    """A fillblank/dragfill TOKEN stem with each U+FFFF n U+FFFF token replaced by a
    visible [n+1] marker, numbered like the "Gap i" part labels (spec §5.1)."""

    def _swap(match):
        return str(
            format_html(
                '<span class="answers__gap">[{}]</span>', int(match.group(1)) + 1
            )
        )

    # The stem was sanitised on save; the inserted markup is digits only.
    return mark_safe(_TOKEN_RE.sub(_swap, question.stem or ""))  # noqa: S308


_TOKEN_STEM_TYPES = (FillBlankQuestionElement, DragFillBlankQuestionElement)


def stem_html(question):
    """The stem as the page renders it: gap-marked for token types, else as-is
    (sanitised on save, rendered |safe exactly as quiz_results does)."""
    if isinstance(question, _TOKEN_STEM_TYPES):
        return gap_marked_stem(question)
    return mark_safe(question.stem)  # noqa: S308
```

Extend `_ADAPTERS`:

```python
_ADAPTERS = {
    ChoiceQuestionElement: _choice,
    ShortTextQuestionElement: _shorttext,
    ShortNumericQuestionElement: _shortnumeric,
    ExtendedResponseQuestionElement: _extendedresponse,
    FillBlankQuestionElement: _fillblank,
    DragFillBlankQuestionElement: _dragfill,
    DragToImageQuestionElement: _dragimage,
    MatchPairQuestionElement: _matchpair,
    ChoiceGridQuestionElement: _choicegrid,
    MultiGridQuestionElement: _multigrid,
}
```

Then `uv run ruff format courses/answer_summary.py tests/test_answer_summary.py tests/answer_summary_fixtures.py` (the call sites above are compacted for the plan; let ruff lay them out).

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_answer_summary.py -v`
Expected: all PASS.
Run: `uv run ruff check --no-cache courses/answer_summary.py tests/test_answer_summary.py tests/answer_summary_fixtures.py`
Expected: clean.

- [ ] **Step 5: Falsify** (each by hand → RED → revert → `git diff`):
  - (a) Delete `MultiGridQuestionElement: _multigrid` from `_ADAPTERS` → `test_registry_covers_every_concrete_question_model` RED (and the multigrid tests).
  - (b) **Growth case** — temporarily append this test, run it, observe RED, then delete it:

    ```python
    def test_TEMP_registry_guard_sees_a_new_type():
        from unittest import mock

        class _Stub(QuestionElement):
            class Meta:
                abstract = True
                app_label = "courses"

        real = apps.get_models()
        with mock.patch.object(apps, "get_models", lambda *a, **k: [*real, _Stub]):
            assert _derived_question_models() == set(answer_summary._ADAPTERS)
    ```
    Expected: FAIL — **read the failure**: it must be the set-inequality `AssertionError` whose diff names `_Stub`, not a `NameError`/`ImportError`/`RuntimeError` (those are red for the wrong reason). The stub is abstract and declared inside the test body, so it never registers (spec T34).
  - (c) `_padded`: `return values` (no pad/truncate) → `test_fillblank_fewer_and_more_stored_values_follow_current_blanks` RED.
  - (d) `_choicegrid.convert`: `return by_pk.get(value)` → `test_choicegrid_parts_empty_row_and_removed_column` RED.
  - (e) `_matchpair`: labels from `mark_result.reveal[i]["left"]` → `test_review_matchpair_and_choicegrid_take_labels_from_child_rows` RED (`TypeError` on `None`).
  - (f) `_text_or_none`: `return text if text != "" else None` → `test_fillblank_whitespace_gap_is_empty` RED.
  - (g) `stem_html`: always `mark_safe(question.stem)` → `test_token_stems_are_gap_marked_like_the_part_labels` RED.
  - (h) `_multigrid` `expected_of`: drop `or _("(none)")` → `test_multigrid_row_with_empty_correct_set_expects_none_label` RED.

- [ ] **Step 6: Commit**

```bash
git add courses/answer_summary.py tests/test_answer_summary.py
git commit -m "feat(analytics): answer_summary multi-part types, gap-marked stems, drift guard

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 6: Route, access gate, shared pill partial

Implements spec §3.1, §3.2, §3.4 (status pill + awaiting Review link; `_drill_params`), D7, D8, and tests T30, T31, T31b. The page body arrives in Task 7.

**Files:**
- Create: `templates/courses/manage/_quiz_pill.html`
- Modify: `templates/courses/manage/_breakdown_node.html` (pill spans → include)
- Modify: `courses/views_analytics.py` (`_drill_params`; `analytics_student` uses it; new view)
- Modify: `courses/urls.py` (after the `manage_analytics_student` path)
- Create: `templates/courses/manage/analytics_student_quiz.html`
- Create: `tests/test_analytics_student_quiz.py`
- Modify: `tests/test_title_math_markers.py` (line citations into `_breakdown_node.html`)

**Interfaces:**
- Consumes: Task 2's `rollups._course_results_row`, `rollups._quiz_pill`; `rollups._quiz_review_maps(unit_pks, submissions)`.
- Produces: URL name `courses:manage_analytics_student_quiz` with kwargs `slug`, `student_pk`, `node_pk`; view `views_analytics.analytics_student_quiz(request, slug, student_pk, node_pk)`; `views_analytics._drill_params(request) -> (scope, mode, expand_pks, subset_pks, values)`; template partial `courses/manage/_quiz_pill.html` reading context variable `p` (a pill dict). Template context keys: `course, student, unit, submission, pill, back_url, has_math` (Task 7 adds `rows, answered_count, question_count`).
- Test helpers in `tests/test_analytics_student_quiz.py` reused by Tasks 7–10: `_url(course, student_pk, node_pk, qs="")`, `_quiz_with_question(course, *, published=True, title="Quiz")`, `_submitted(student, quiz, **kw)`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_analytics_student_quiz.py`:

```python
"""The per-question drill-down page (spec §3, §5; T30, T31, T31b, T33, T35-T39, T41).

Every PA/owner-viewed pupil gets an Enrollment row: reviewable_students serves
PA and owner from Enrollment alone, and GroupMembershipFactory creates none."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.urls import reverse

from courses.models import Element
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _url(course, student_pk, node_pk, qs=""):
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student_pk, "node_pk": node_pk},
    )
    return f"{path}{qs}"


def _quiz_with_question(course, *, published=True, title="Quiz"):
    quiz = ContentNodeFactory(
        course=course,
        parent=None,
        kind="unit",
        unit_type="quiz",
        published=published,
        title=title,
    )
    q = ShortTextQuestionElement.objects.create(
        stem="<p>Capital?</p>", accepted="Warsaw", max_marks=Decimal("1")
    )
    Element.objects.create(unit=quiz, content_object=q)
    return quiz


def _submitted(student, quiz, **kw):
    kw.setdefault("status", QuizSubmission.Status.SUBMITTED)
    return QuizSubmission.objects.create(student=student, unit=quiz, **kw)


def _soup(response):
    return BeautifulSoup(response.content.decode(), "html.parser")


# --- T30 access --------------------------------------------------------------
def test_t30_access_matrix(client):
    pa = make_pa(client, "pa")
    owner = make_verified_user(username="owner", email="owner@test.example.com")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    pupil_a = make_verified_user(username="pupila", email="pupila@test.example.com")
    pupil_b = UserFactory()
    for pupil in (pupil_a, pupil_b):
        EnrollmentFactory(student=pupil, course=course)
        _submitted(pupil, quiz)
    group_a = GroupFactory(course=course)
    group_b = GroupFactory(course=course)
    GroupMembershipFactory(group=group_a, student=pupil_a)
    GroupMembershipFactory(group=group_b, student=pupil_b)
    teacher_a = make_teacher(client, "teachera")
    group_a.teachers.add(teacher_a)
    teacher_b = make_teacher(client, "teacherb")
    group_b.teachers.add(teacher_b)
    archived_teacher = make_teacher(client, "archivedteacher")
    group_b.teachers.add(archived_teacher)  # active group, so step 2 passes
    old_group = GroupFactory(course=course, archived=True)
    old_group.teachers.add(archived_teacher)
    GroupMembershipFactory(group=old_group, student=pupil_a)
    staff = make_teacher(client, "staffnogroup")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    # Pinned up front so every mutant's flip is real (spec T30).
    assert not pa.is_staff and not owner.is_staff and not teacher_a.is_staff
    assert staff.is_staff

    url = _url(course, pupil_a.pk, quiz.pk)
    expected = [
        (pa, 200),
        (owner, 200),
        (teacher_a, 200),
        (teacher_b, 404),
        (archived_teacher, 404),
        (staff, 404),
        (pupil_a, 404),
    ]
    actual = {}
    for viewer, _status in expected:
        client.force_login(viewer)
        actual[viewer.username] = client.get(url).status_code
    # ONE dict comparison, so a failure lists EVERY flipped row (spec T30).
    assert actual == {viewer.username: status for viewer, status in expected}
    client.logout()
    anonymous = client.get(url)
    assert anonymous.status_code == 302
    assert "/accounts/login/" in anonymous.url


# --- T31 resolution ----------------------------------------------------------
def test_t31_each_path_segment_404s_on_its_own(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    _submitted(pupil, quiz)
    assert client.get(_url(course, pupil.pk, quiz.pk)).status_code == 200

    # Submissions exist on these nodes, so step 5 cannot be what 404s them.
    other = CourseFactory(owner=owner)
    other_quiz = _quiz_with_question(other)
    _submitted(pupil, other_quiz)
    assert client.get(_url(course, pupil.pk, other_quiz.pk)).status_code == 404
    lesson = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    _submitted(pupil, lesson)
    assert client.get(_url(course, pupil.pk, lesson.pk)).status_code == 404

    missing = get_user_model().objects.order_by("-pk").first().pk + 1000
    assert client.get(_url(course, missing, quiz.pk)).status_code == 404

    no_submission = UserFactory()
    EnrollmentFactory(student=no_submission, course=course)
    assert client.get(_url(course, no_submission.pk, quiz.pk)).status_code == 404


def test_t31b_group_teacher_opens_a_draft_quiz_the_pupil_has_data_on(client):
    teacher = make_teacher(client, "draftteacher")
    course = CourseFactory(owner=UserFactory())
    quiz = _quiz_with_question(course, published=False)
    pupil = UserFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    GroupMembershipFactory(group=group, student=pupil)
    _submitted(pupil, quiz)
    client.force_login(teacher)
    assert client.get(_url(course, pupil.pk, quiz.pk)).status_code == 200


# --- header pill + Review link (full parity is T36, Task 7) -------------------
def test_awaiting_header_has_one_review_link(client):
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement

    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("1"),
    )
    Element.objects.create(unit=quiz, content_object=q)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    status = soup.select_one(".answers__status")
    assert status.select_one(".pill--awaiting") is not None
    links = status.select("a.answers__review")
    assert [a["href"] for a in links] == [
        reverse(
            "courses:manage_review_submission",
            kwargs={"slug": course.slug, "submission_pk": sub.pk},
        )
    ]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py -v`
Expected: all FAIL with `NoReverseMatch: Reverse for 'manage_analytics_student_quiz' not found`.

- [ ] **Step 3: Pill partial.** Create `templates/courses/manage/_quiz_pill.html` holding exactly the five pill spans now in `_breakdown_node.html` (the lines between `{% with p=item.pill %}` and `{% endwith %}`, **minus** the `<a class="breakdown-unit__review" …>` line):

```django
{% load i18n %}
{% comment %}The quiz status pill, shared by the analytics breakdown and the
per-question page header (spec D8). Reads `p`, a rollups._quiz_pill dict. The
awaiting-review "Review" link is NOT here: each caller renders its own after
this include, so no page shows it twice.{% endcomment %}
{% if p.kind == "scored" %}
  <span class="pill pill--scored">{% blocktrans with s=p.score|floatformat m=p.max_score|floatformat %}scored {{ s }}/{{ m }}{% endblocktrans %} ({{ p.percent }}%)</span>
{% elif p.kind == "submitted" %}
  <span class="pill pill--submitted">{% trans "submitted" %}</span>
{% elif p.kind == "awaiting" %}
  <span class="pill pill--awaiting">{% trans "awaiting review" %}</span>
{% elif p.kind == "in_progress" %}
  <span class="pill pill--progress">{% trans "in progress" %}</span>
{% else %}
  <span class="pill pill--none">{% trans "not started" %}</span>
{% endif %}
```

In `_breakdown_node.html` replace the whole `{% with p=item.pill %} … {% endwith %}` block with:

```django
        {% with p=item.pill %}
          {% include "courses/manage/_quiz_pill.html" %}
          {% if p.kind == "awaiting" %}
            <a class="breakdown-unit__review" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=p.submission_pk %}">{% trans "Review" %}</a>
          {% endif %}
        {% endwith %}
```

The msgids are unchanged (same strings, new file), so no translation is lost.

- [ ] **Step 4: `_drill_params` + the view.** In `courses/views_analytics.py`:

Add imports `from courses.access import get_node_or_404` and `from courses.rollups import _course_results_row`, `from courses.rollups import _quiz_pill`, `from courses.rollups import _quiz_review_maps`.

Add below `_expand_qs`:

```python
def _drill_params(request):
    """(scope, mode, expand_pks, subset_pks, values) from a drill-down page's GET:
    the breakdown and the per-question page round-trip the matrix's state with it.
    analytics_matrix parses its own (it also reads scope_rendered)."""
    scope = request.GET.get("scope", "all")
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    values = "raw" if request.GET.get("values") == "raw" else "percent"
    expand_pks = _clean_expand(request.GET.getlist("expand"))
    subset_pks = _clean_expand(request.GET.getlist("student"))
    return scope, mode, expand_pks, subset_pks, values
```

In `analytics_student`, replace its five parse lines (`scope = …` through `subset_pks = …`) with:

```python
    scope, mode, expand_pks, subset_pks, values = _drill_params(request)
```

Add after `analytics_student`:

```python
@login_required
def analytics_student_quiz(request, slug, student_pk, node_pk):
    """One pupil's answers to one quiz (spec §3). Every failure is 404."""
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    student = (
        scoping.reviewable_students(request.user, course).filter(pk=student_pk).first()
    )
    if student is None:
        raise Http404
    # No viewer=: an author-facing surface keeps drafts that carry data (a
    # submission IS data), exactly as the breakdown does.
    unit = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    submission = QuizSubmission.objects.filter(student=student, unit=unit).first()
    if submission is None:
        raise Http404
    has_auto, total_review, reviewed_counts = _quiz_review_maps(
        [unit.pk], [submission]
    )
    pill = _quiz_pill(
        _course_results_row(unit, submission, has_auto, total_review, reviewed_counts)
    )
    scope, mode, expand_pks, subset_pks, values = _drill_params(request)
    student_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
    return render(
        request,
        "courses/manage/analytics_student_quiz.html",
        {
            "course": course,
            "student": student,
            "unit": unit,
            "submission": submission,
            "pill": pill,
            "back_url": f"{student_path}?{back_qs}",
            "has_math": False,
        },
    )
```

In `courses/urls.py`, directly after the `manage_analytics_student` `path(...)`:

```python
    path(
        "manage/courses/<slug:slug>/analytics/student/<int:student_pk>/"
        "quiz/<int:node_pk>/",
        views_analytics.analytics_student_quiz,
        name="manage_analytics_student_quiz",
    ),
```

- [ ] **Step 5: Skeleton template** — create `templates/courses/manage/analytics_student_quiz.html`:

```django
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Answers" %} · {{ course.title }} · libli{% endblock %}
{% block extra_css %}
  <link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">
  {% if has_math %}{% include "courses/_katex_css.html" %}{% endif %}
{% endblock %}
{% block content %}
<section class="manage answers">
  <header class="manage__head">
    <h1 class="manage__title"><span lang="{{ course.language }}" data-math-title>{{ unit.title }}</span> — {{ student.display_name|default:student.username }}</h1>
    <a class="btn btn--ghost btn--small" href="{{ back_url }}">← {% trans "Breakdown" %}</a>
  </header>
  <p class="answers__status">
    {% with p=pill %}
      {% include "courses/manage/_quiz_pill.html" %}
      {% if p.kind == "awaiting" %}
        <a class="answers__review" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=submission.pk %}">{% trans "Review" %}</a>
      {% endif %}
    {% endwith %}
  </p>
</section>
{% endblock %}
```

- [ ] **Step 6: Re-point the template citations** in `tests/test_title_math_markers.py`. Find the new line numbers:

Run: `grep -n "breakdown-unit__title" templates/courses/manage/_breakdown_node.html`
(first hit = quiz branch, second = lesson branch). Then:
Run: `grep -n "_breakdown_node.html:\|(:24)\|(:6)\|:4-21\|:24 lesson" tests/test_title_math_markers.py`
Update every hit to the new numbers (the `_analytics_bodies` docstring's `(:4-21, holding the :6 marker)` / `:24 lesson branch`, the breakdown test's docstring `(:6)` / `(:24)`, and both assertion messages). Keep each edited line's line count unchanged.

- [ ] **Step 7: Run**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_analytics_views.py tests/test_analytics_rollups.py tests/test_title_math_markers.py -v`
Expected: all PASS.

- [ ] **Step 8: Falsify** (each by hand → run `tests/test_analytics_student_quiz.py` → RED → revert → `git diff`):
  For (a)–(d) read the **whole dict diff** pytest prints; it must name exactly the rows listed.
  - (a) step 2 gate `if not request.user.is_staff:` instead of `can_review_course` → `test_t30_access_matrix` RED, flipped rows exactly `pa`, `owner`, `teachera` (200 → 404).
  - (b) step 3 `get_user_model().objects.filter(pk=student_pk).first()` (import `get_user_model` for the mutant) → RED, flipped rows exactly `teacherb`, `archivedteacher` (404 → 200).
  - (c) replace step 3 with a copy of `reviewable_students`' body that keeps the PA/owner `Enrollment` branch and drops only `archived=False` from the group-teacher branch → RED, flipped row exactly `archivedteacher`.
  - (d) `can_review_course(...) or request.user.is_staff` at step 2 **combined with** (b) → RED, flipped rows exactly `teacherb`, `archivedteacher`, `staffnogroup` — `staffnogroup` is the row (b) alone does not flip, and is what this mutant exists to show.
  - (e) drop `require_quiz=True` → `test_t31_each_path_segment_404s_on_its_own` RED (lesson case).
  - (f) replace step 4 with `unit = get_object_or_404(ContentNode, pk=node_pk, kind="unit", unit_type="quiz")` (bypasses the slug check; add `from courses.models import ContentNode` for the mutant) → T31 RED (other-course case: 200 instead of 404).
  - (g) step 5: `if submission is None: raise PermissionDenied` (import it for the mutant) → T31 RED (no-submission case: 403 instead of 404). (An unsaved stand-in `QuizSubmission` would not "render an empty page": Django raises on an unsaved instance in `submission__in`, which errors the test for a different reason.)
  - (h) add `viewer=request.user` to `get_node_or_404` → `test_t31b_…` RED.
  - (i) add `<a class="answers__review" href="#">Review</a>` to the `awaiting` branch of `_quiz_pill.html`, keeping the page's own link → the header holds two `a.answers__review` → `test_awaiting_header_has_one_review_link` RED. (A copy carrying the breakdown's `breakdown-unit__review` class would not be counted and the test would stay green.)

- [ ] **Step 9: Commit**

```bash
git add courses/views_analytics.py courses/urls.py templates/courses/manage/_quiz_pill.html templates/courses/manage/_breakdown_node.html templates/courses/manage/analytics_student_quiz.html tests/test_analytics_student_quiz.py tests/test_title_math_markers.py
git commit -m "feat(analytics): per-question drill-down route and access gate

404 for every failure: reviewer gate, reviewable pupil, course-bound quiz
node, existing submission. The breakdown's pill moves into a shared partial
the new header reuses.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 7: Question rows, outcome override, header count

Implements spec §3.3 (rows, outcome override, attempts), §3.4 (in-progress count), §5.1 (list markup, badges, per-row Review link, parts, glyph unit, language tagging, review feedback), tests T33 (page cases), T35 (core), T36, T41 (page).

**Files:**
- Modify: `courses/views_analytics.py` (`_override_outcome`, `_quiz_answer_rows`; view context)
- Modify: `templates/courses/manage/analytics_student_quiz.html`
- Modify: `tests/test_analytics_student_quiz.py` (append)

**Interfaces:**
- Consumes: `courses.views._results_row(question, response) -> dict` (keys used: `question, response, outcome, earned, possible, reveal_result, answered, review_feedback`); `courses.views.prefetch_question_children` (Task 3); `courses.answer_summary.summarise`, `stem_html`, `Part.mark` (Tasks 4–5).
- Produces: row dict keys added by the view: `outcome` (overridden), `parts: list[Part]`, `qnum: int`, `stem_html: SafeString`, `attempt_count: int`, `attempt_max: int | None` (None = print "attempt n" without "of max"). Context adds `rows`, `answered_count`, `question_count`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_analytics_student_quiz.py` (add imports `from django.utils import timezone`, `from courses.models import ExtendedResponseQuestionElement`, `from courses.models import QuestionElement`, `from courses.models import QuestionResponse`, `from courses.models import ShortNumericQuestionElement`):

```python
AUTO = QuestionElement.MarkingMode.AUTO
REVIEW = QuestionElement.MarkingMode.REVIEW
NOT_MARKED = QuestionElement.MarkingMode.NOT_MARKED


def _empty_quiz(course, title):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title=title
    )


def _add(quiz, model=ShortTextQuestionElement, **fields):
    fields.setdefault("stem", "<p>Q</p>")
    fields.setdefault("max_marks", Decimal("1"))
    if model is ShortTextQuestionElement:
        fields.setdefault("accepted", "Warsaw")
    if model is ExtendedResponseQuestionElement:
        fields.setdefault("required_keywords", "")
        fields.setdefault("forbidden_keywords", "")
    return Element.objects.create(unit=quiz, content_object=model.objects.create(**fields))


def _respond(sub, element, **fields):
    return QuestionResponse.objects.create(submission=sub, element=element, **fields)


def _owner_view(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    return course, pupil


def _items(soup):
    return soup.select("li.answers__item")


def _badge(item):
    return item.select_one(".answers__verdict .badge").get_text(" ", strip=True)


# --- T35 core: the in-progress fixture -----------------------------------------
def test_t35_in_progress_rows_count_and_overrides(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Live quiz")
    q1 = _add(quiz, max_attempts=2)
    q2 = _add(quiz, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    q3 = _add(quiz, marking_mode=NOT_MARKED)
    q4 = _add(quiz, marking_mode=REVIEW)
    q5 = _add(quiz, max_attempts=None)
    q6 = _add(quiz)
    sub = _submitted(pupil, quiz, status=QuizSubmission.Status.IN_PROGRESS)
    _respond(sub, q1, latest_answer="Krakow", fraction=Decimal("0"), attempt_count=1)
    # q2: no response at all
    _respond(sub, q3, latest_answer=None, attempt_count=0)  # empty-submit row
    _respond(sub, q4, latest_answer="abc", attempt_count=1, locked=True)
    _respond(sub, q5, latest_answer="Warsaw", fraction=Decimal("1"), attempt_count=1)
    _respond(sub, q6, latest_answer=None, attempt_count=0)  # empty-submit row

    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    status = soup.select_one(".answers__status")
    assert status.select_one(".pill--progress") is not None
    assert "3 of 6 questions answered" in status.get_text(" ", strip=True)
    items = _items(soup)
    assert [i.select_one(".answers__qnum").get_text(strip=True) for i in items] == [
        "1.", "2.", "3.", "4.", "5.", "6.",
    ]
    assert _badge(items[0]).startswith("Incorrect")
    assert "attempt 1 of 2" in items[0].get_text(" ", strip=True)
    # D5: the key shows although q1 still has an attempt left (not locked)
    assert "Correct answer: Warsaw" in items[0].get_text(" ", strip=True)
    assert _badge(items[1]) == "Not answered"  # unanswered REVIEW, in progress
    assert _badge(items[2]) == "Not answered"  # empty NOT_MARKED row
    assert _badge(items[3]) == "Answer recorded"  # answered REVIEW, in progress
    assert items[3].select("a.answers__row-review") == []
    assert "attempt 1 of 1" in items[3].get_text(" ", strip=True)
    assert _badge(items[4]).startswith("Correct")
    assert "attempt 1" in items[4].get_text(" ", strip=True)
    assert "attempt 1 of" not in items[4].get_text(" ", strip=True)
    assert _badge(items[5]) == "Not answered"


def test_t35_submitted_unanswered_review_rows_link_with_distinct_names(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Essay quiz")
    _add(quiz, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _add(quiz, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("0"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    items = _items(soup)
    assert [_badge(i).split(" (")[0] for i in items] == [
        "Awaiting review",
        "Awaiting review",
    ]
    links = [i.select_one("a.answers__row-review") for i in items]
    expected_href = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    assert [a["href"] for a in links] == [expected_href, expected_href]
    names = [a.get_text(" ", strip=True) for a in links]
    assert len(set(names)) == 2, names


def test_t35_teacher_voice_only(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Voice quiz")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="Krakow", fraction=Decimal("0"), attempt_count=1)
    text = _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(
        "section.answers"
    ).get_text(" ", strip=True).lower()
    assert "your answer" not in text and "you chose" not in text


# --- T36 header parity ----------------------------------------------------------
def _breakdown_pill(soup, title):
    for unit in soup.select("div.breakdown-unit"):
        if unit.select_one(".breakdown-unit__title").get_text(strip=True) == title:
            return unit.select_one(".pill")
    raise AssertionError(f"no breakdown row titled {title!r}")


def test_t36_header_pill_matches_the_breakdown_pill(client):
    course, pupil = _owner_view(client)
    scored = _empty_quiz(course, "Q scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("1"))
    ungraded = _empty_quiz(course, "Q ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "Q awaiting")
    _add(awaiting)
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _submitted(pupil, awaiting, score=Decimal("1"), max_score=Decimal("1"))
    reviewed = _empty_quiz(course, "Q reviewed")
    rel = _add(reviewed, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    rsub = _submitted(pupil, reviewed, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        rsub, rel, latest_answer="essay", attempt_count=1, locked=True,
        earned_marks=Decimal("1"), fraction=Decimal("1"), reviewed_at=timezone.now(),
    )
    live = _empty_quiz(course, "Q live")
    _add(live)
    _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)

    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    expected_kinds = {
        scored: "pill--scored",
        ungraded: "pill--submitted",
        awaiting: "pill--awaiting",
        reviewed: "pill--submitted",
        live: "pill--progress",
    }
    for quiz, kind in expected_kinds.items():
        header = _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(
            ".answers__status .pill"
        )
        row = _breakdown_pill(breakdown, quiz.title)
        assert kind in header["class"], (quiz.title, header["class"])
        assert header["class"] == row["class"], quiz.title
        assert header.get_text(" ", strip=True) == row.get_text(" ", strip=True)
    awaiting_status = _soup(client.get(_url(course, pupil.pk, awaiting.pk))).select_one(
        ".answers__status"
    )
    assert len(awaiting_status.select("a.answers__review")) == 1
    assert "scored" not in awaiting_status.get_text(" ", strip=True)


# --- T41 on the page: grids reach the header --------------------------------------
def test_t41_grid_quizzes_header_pills(client):
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Grid review")
    q = MultiGridQuestionElement.objects.create(
        stem="<p>Pick</p>", marking_mode=REVIEW, max_marks=Decimal("1")
    )
    col = MultiGridColumn.objects.create(question=q, label="a")
    MultiGridRow.objects.create(question=q, statement="r1").correct_columns.set([col])
    Element.objects.create(unit=quiz, content_object=q)
    _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("0"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    assert soup.select_one(".answers__status .pill--awaiting") is not None
    assert len(soup.select(".answers__status a.answers__review")) == 1
    assert len(soup.select("li.answers__item a.answers__row-review")) == 1


# --- T33 page cases: accepted splits after content edits ---------------------------
def test_t33_key_edited_after_answering_keeps_badge_and_remarks_parts(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Edited key")
    el = _add(quiz, ShortNumericQuestionElement, value="1/2", tolerance="")
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="1/2", fraction=Decimal("1"), attempt_count=1)
    q = el.content_object
    q.value = "3"
    q.save()
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert _badge(item).startswith("Correct")
    assert item.select_one(".answers__glyph--incorrect") is not None
    assert "Correct answer: 3" in item.get_text(" ", strip=True)


def test_t33_switched_to_auto_never_reviewed_badges_answer_recorded(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Switched")
    el = _add(quiz, marking_mode=REVIEW)
    sub = _submitted(pupil, quiz, status=QuizSubmission.Status.IN_PROGRESS)
    _respond(sub, el, latest_answer="Warsaw", attempt_count=1, locked=True)
    q = el.content_object
    q.marking_mode = AUTO
    q.save()
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    item = _items(soup)[0]
    assert _badge(item) == "Answer recorded"
    assert item.select_one(".answers__glyph--correct") is not None
    assert "1 of 1 question answered" in soup.select_one(".answers__status").get_text(
        " ", strip=True
    )


def test_t33_reviewed_then_switched_to_auto_badges_from_the_review(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Reviewed switch")
    answered = _add(quiz, marking_mode=REVIEW)
    blank = _add(quiz, marking_mode=REVIEW)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("2"))
    now = timezone.now()
    _respond(
        sub, answered, latest_answer="Warsaw", attempt_count=1, locked=True,
        earned_marks=Decimal("1"), fraction=Decimal("1"), reviewed_at=now,
    )
    _respond(
        sub, blank, latest_answer=None, attempt_count=0, locked=True,
        earned_marks=Decimal("0"), fraction=Decimal("0"), reviewed_at=now,
    )
    for el in (answered, blank):
        q = el.content_object
        q.marking_mode = AUTO
        q.save()
    items = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert _badge(items[0]).startswith("Correct")
    assert _badge(items[1]).startswith("Incorrect")
    assert "Not answered" in items[1].select_one(".answers__part").get_text(" ", strip=True)
    assert items[1].select_one(".answers__glyph--incorrect") is not None


def test_t33_lowered_max_attempts_never_prints_n_of_smaller_max(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Lowered")
    el = _add(quiz, max_attempts=3)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="Krakow", fraction=Decimal("0"), attempt_count=3)
    q = el.content_object
    q.max_attempts = 1
    q.save()
    text = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0].get_text(
        " ", strip=True
    )
    assert "attempt 3" in text
    assert "attempt 3 of" not in text


# --- review feedback ---------------------------------------------------------------
def test_review_feedback_shows_on_any_row_with_feedback(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Feedback")
    el = _add(quiz)  # AUTO now; feedback left from an earlier review
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        sub, el, latest_answer="Warsaw", fraction=Decimal("1"), attempt_count=1,
        review_feedback="Well argued",
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert "Well argued" in item.get_text(" ", strip=True)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py -v`
Expected: the new tests FAIL (no `li.answers__item`; `.answers__status` has no count) **except** `test_t36_header_pill_matches_the_breakdown_pill` (Task 6 already built the header pill from the shared partial — its red comes from Falsify (i)–(k)) and `test_t35_teacher_voice_only` (passes trivially until rows render; it guards the template's wording afterwards). Task 6's tests still PASS.

- [ ] **Step 3: Rows.** In `courses/views_analytics.py` add imports:

```python
from courses.answer_summary import stem_html
from courses.answer_summary import summarise
from courses.models import QuestionElement
from courses.views import _results_row
from courses.views import prefetch_question_children
```

(`courses.views` never imports `views_analytics`, so this is cycle-free — spec §2.5.)

Add above `analytics_student_quiz`:

```python
def _override_outcome(question, response, row, in_progress):
    """_results_row's outcome vocabulary is post-submit; fix the three cases it
    misreports on this page (spec §3.3). Never applied inside _results_row: the
    pupil's own results page is out of scope."""
    mode = question.marking_mode
    answered = row["answered"]
    if mode == QuestionElement.MarkingMode.NOT_MARKED and not answered:
        return "not_answered"
    if mode == QuestionElement.MarkingMode.REVIEW and in_progress:
        # Nobody can review it until the submission is finished (by the pupil or
        # a teacher's force-submit): the review page opens SUBMITTED work only.
        return "recorded" if answered else "not_answered"
    if (
        mode == QuestionElement.MarkingMode.AUTO
        and answered
        and response.fraction is None
    ):
        # answered while REVIEW/NOT_MARKED, never reviewed, then switched to AUTO
        return "recorded"
    return row["outcome"]


def _quiz_answer_rows(unit, submission):
    """One display row per top-level question, in element order (spec §3.3)."""
    elements = [
        el
        for el in unit.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .prefetch_related("content_object")
        if isinstance(el.content_object, QuestionElement)
    ]
    prefetch_question_children([el.content_object for el in elements])
    responses = {r.element_id: r for r in submission.responses.all()}
    in_progress = submission.status == QuizSubmission.Status.IN_PROGRESS
    rows = []
    for qnum, el in enumerate(elements, start=1):
        question = el.content_object
        response = responses.get(el.pk)
        row = _results_row(question, response)
        row["outcome"] = _override_outcome(question, response, row, in_progress)
        row["parts"] = summarise(question, response, row["reveal_result"])
        row["qnum"] = qnum
        row["stem_html"] = stem_html(question)
        attempts = response.attempt_count if response is not None else 0
        limit = question.max_attempts
        row["attempt_count"] = attempts
        row["attempt_max"] = limit if limit is not None and attempts <= limit else None
        rows.append(row)
    return rows
```

In `analytics_student_quiz`, before `return render(...)`:

```python
    rows = _quiz_answer_rows(unit, submission)
```

and add to the context: `"rows": rows, "answered_count": sum(1 for row in rows if row["answered"]), "question_count": len(rows),`.

- [ ] **Step 4: Template body.** In `analytics_student_quiz.html`, change the load line to `{% load i18n static courses_extras %}`. Inside `<p class="answers__status">`, after `{% endwith %}`, add:

```django
    {% if pill.kind == "in_progress" %}
      <span class="answers__count">{% blocktrans with k=answered_count count n=question_count %}{{ k }} of {{ n }} question answered{% plural %}{{ k }} of {{ n }} questions answered{% endblocktrans %}</span>
    {% endif %}
```

After `</p>`, before `</section>`, add:

```django
  <ol class="answers__list">
    {% for row in rows %}
    <li class="answers__item is-{{ row.outcome }}" data-question>
      <div class="answers__head">
        <span class="answers__qnum">{{ row.qnum }}.</span>
        <div class="answers__stem question__stem" lang="{{ course.language }}">{{ row.stem_html }}</div>
      </div>
      <div class="answers__verdict">
        {% comment %}A deliberate copy of quiz_results.html's badge markup and msgids
        (spec §5.1): extracting a partial would change the pupil's results page.{% endcomment %}
        {% if row.outcome == "correct" %}<span class="badge">{% trans "Correct" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
        {% elif row.outcome == "partial" %}<span class="badge">{% trans "Partial" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
        {% elif row.outcome == "incorrect" %}<span class="badge">{% trans "Incorrect" %} (0/{{ row.possible|marks }})</span>
        {% elif row.outcome == "not_answered" %}<span class="badge badge--muted">{% trans "Not answered" %}</span>
        {% elif row.outcome == "recorded" %}<span class="badge">{% trans "Answer recorded" %}</span>
        {% elif row.outcome == "reviewed" %}<span class="badge">{% trans "Reviewed" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
        {% elif row.outcome == "review" %}<span class="badge badge--review">{% trans "Awaiting review" %} ({% blocktrans with m=row.possible|marks %}up to {{ m }} marks{% endblocktrans %})</span>{% endif %}
        {% if row.outcome == "review" %}
          <a class="answers__row-review" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=submission.pk %}">{% trans "Review" %}<span class="sr-only"> — {% blocktrans with n=row.qnum %}question {{ n }}{% endblocktrans %}</span></a>
        {% endif %}
        {% if row.attempt_count %}
          <span class="answers__attempts">{% if row.attempt_max %}{% blocktrans with n=row.attempt_count max=row.attempt_max %}attempt {{ n }} of {{ max }}{% endblocktrans %}{% else %}{% blocktrans with n=row.attempt_count %}attempt {{ n }}{% endblocktrans %}{% endif %}</span>
        {% endif %}
      </div>
      <div class="answers__parts">
        {% for part in row.parts %}
          <div class="answers__part answers__part--{{ part.kind }}">
            {% if part.label %}<span class="answers__label"{% if part.label_is_content %} lang="{{ course.language }}"{% endif %}>{{ part.label }}</span>{% endif %}
            {% if part.kind == "answer" %}
              {% if part.given is not None %}<span class="answers__given" lang="{{ course.language }}">{{ part.given }}</span>{% else %}<span class="answers__muted">{% trans "Not answered" %}</span>{% endif %}
            {% endif %}
            {% comment %}The glyph and its sr-only label are ONE unit, keyed on
            Part.mark, which already suppresses a tick on an empty part.{% endcomment %}
            {% if part.mark == "correct" %}<span class="answers__glyph answers__glyph--correct" aria-hidden="true">✓</span><span class="sr-only">{% trans "Correct" %}</span>
            {% elif part.mark == "incorrect" %}<span class="answers__glyph answers__glyph--incorrect" aria-hidden="true">✗</span><span class="sr-only">{% trans "Incorrect" %}</span>{% endif %}
            {% if part.expected %}<span class="answers__expected">{% trans "Correct answer:" %} <strong lang="{{ course.language }}">{{ part.expected }}</strong></span>{% endif %}
          </div>
        {% endfor %}
      </div>
      {% if row.review_feedback %}
        <div class="question__feedback question__feedback--review"><p>{{ row.review_feedback }}</p></div>
      {% endif %}
    </li>
    {% endfor %}
  </ol>
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_analytics_views.py -v`
Expected: all PASS.

- [ ] **Step 6: Falsify** (each by hand → RED → revert → `git diff`):
  - (a) context `answered_count`: `submission.responses.count()` → `test_t35_in_progress_rows_count_and_overrides` RED ("5 of 6").
  - (b) `row["outcome"] = row["outcome"]` (drop the override) → `test_t35_in_progress_rows_count_and_overrides` RED (items 2 and 3) and `test_t33_switched_to_auto_never_reviewed_badges_answer_recorded` RED.
  - (c) `_override_outcome`: REVIEW branch without `and in_progress` → `test_t35_submitted_unanswered_review_rows_link_with_distinct_names` RED.
  - (d) `_override_outcome`: `return "not_answered"` instead of `"recorded" if answered else …` → `test_t35_in_progress_rows_count_and_overrides` RED (item 4).
  - (e) `_override_outcome`: delete the AUTO `fraction is None` arm → `test_t33_switched_to_auto_never_reviewed_badges_answer_recorded` RED.
  - (f) template: `{% if part.expected and row.response.locked %}` → T35 core RED ("Correct answer: Warsaw" missing).
  - (g) template: restrict the attempt line to `{% if row.attempt_count and row.question.marking_mode == "A" %}` → T35 core RED (item 4's "attempt 1 of 1").
  - (h) template: delete the `<span class="sr-only">` inside the per-row Review link → `test_t35_submitted_…distinct_names` RED.
  - (i) view: `_quiz_review_maps([unit.pk], [])` → `test_t36_header_pill_matches_the_breakdown_pill` RED ("Q reviewed" header reads awaiting).
  - (j) view: `_quiz_review_maps([], [submission])` → T36 RED ("Q scored" header reads submitted).
  - (k) template header: replace the `_quiz_pill.html` include with an inline copy of its spans, changing `pill--scored` to `pill--score` → T36 RED.
  - (l) template: `{% if row.review_feedback and row.outcome == "reviewed" %}` → `test_review_feedback_shows_on_any_row_with_feedback` RED.
  - (m) view: `row["attempt_max"] = limit` (drop the `attempts <= limit` guard) → `test_t33_lowered_max_attempts_never_prints_n_of_smaller_max` RED ("attempt 3 of 1").
  - (n) **D9 on the page (spec T41):** temporarily restore the 8-model `_QUESTION_MODELS` list in `courses/rollups.py` (paste the eight names back, re-adding their imports) → `test_t41_grid_quizzes_header_pills` RED on the header pill (`.pill--awaiting` missing) and the header Review link. Revert by hand and read `git diff courses/rollups.py`.
  - (o) `courses/answer_summary.py` `_shortnumeric`: pass `response.fraction == 1` as `correct` instead of `mark_result.correct` → `test_t33_key_edited_after_answering_keeps_badge_and_remarks_parts` RED (the part reads ✓).

- [ ] **Step 7: Commit**

```bash
git add courses/views_analytics.py templates/courses/manage/analytics_student_quiz.html tests/test_analytics_student_quiz.py
git commit -m "feat(analytics): per-question rows with teacher-voice answer parts

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 8: Rendering details — drag-to-image stage, empty states, maths

Implements spec §3.4 (zero-question quiz), §4.3 (zero parts), §5.1 (drag-to-image stage, token stems on the page, language tagging), §5.2 (`has_math`, `question.js`, `_katex_js.html` comment), tests T35 (rest), T39.

**Files:**
- Modify: `courses/views_analytics.py` (`_answers_have_math`; `has_math` in context)
- Modify: `templates/courses/manage/analytics_student_quiz.html`
- Modify: `templates/courses/_katex_js.html` (comment only, line-count neutral)
- Modify: `tests/test_analytics_student_quiz.py` (append)

**Interfaces:**
- Consumes: Task 7's rows (`row["question"]`, `row["parts"]`, `row["review_feedback"]`); `courses.views._question_has_math(question) -> bool`; `courses.htmlsandbox.has_math_delimiters(text) -> bool`, `titles_have_math(iterable) -> bool`.
- Produces: `views_analytics._answers_have_math(unit, rows) -> bool`; row key `dragimage` (the question when it is a `DragToImageQuestionElement`, else `None`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_analytics_student_quiz.py`:

```python
# --- T35 rest: stems, stage, empty states, glyph unit, language ------------------
def test_token_stems_render_gap_markers_matching_the_part_labels(client):
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Gaps")
    q = FillBlankQuestionElement.objects.create(
        stem="2 + ￿0￿ = ￿1￿", max_marks=Decimal("1")
    )
    Blank.objects.create(question=q, accepted="2")
    Blank.objects.create(question=q, accepted="4")
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=["2", "5"], fraction=Decimal("0.5"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    stem = item.select_one(".answers__stem")
    assert "￿" not in str(stem)
    assert [g.get_text() for g in stem.select(".answers__gap")] == ["[1]", "[2]"]
    assert [
        p.select_one(".answers__label").get_text(strip=True)
        for p in item.select(".answers__part")
    ] == ["Gap 1", "Gap 2"]


def test_dragimage_row_renders_a_static_numbered_stage(client):
    from tests.factories import DragZoneFactory

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Image")
    zone = DragZoneFactory(correct_label="Heart")
    DragZoneFactory(question=zone.question, correct_label="Liver")
    q = zone.question  # stem is blank: a prompt-less question
    Element.objects.create(unit=quiz, content_object=q)
    _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    stage = item.select_one(".dragimage__stage")
    assert stage is not None
    assert stage.select_one("img.dragimage__img")["alt"] == q.alt
    assert [b.get_text(strip=True) for b in stage.select("span.dragimage__badge")] == [
        "1",
        "2",
    ]
    assert item.select("select, form, [data-dnd], [data-zone]") == []


def test_zero_question_quiz_and_zero_part_question_empty_states(client):
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    course, pupil = _owner_view(client)
    empty = _empty_quiz(course, "Nothing here")
    _submitted(pupil, empty, status=QuizSubmission.Status.IN_PROGRESS)
    soup = _soup(client.get(_url(course, pupil.pk, empty.pk)))
    assert "This quiz has no questions." in soup.select_one("section.answers").get_text(
        " ", strip=True
    )
    assert " of 0 " not in soup.select_one(".answers__status").get_text(" ", strip=True)
    assert soup.select("ol.answers__list") == []

    quiz = _empty_quiz(course, "Emptied")
    q = FillBlankQuestionElement.objects.create(stem="￿0￿", max_marks=Decimal("1"))
    Blank.objects.create(question=q, accepted="2")
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=["2"], fraction=Decimal("1"), attempt_count=1)
    q.blanks.all().delete()
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert "(this question no longer has any parts)" in item.get_text(" ", strip=True)


def test_an_empty_part_that_scores_true_shows_no_tick_and_no_sr_correct(client):
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Empty set")
    q = MultiGridQuestionElement.objects.create(stem="<p>Pick</p>", max_marks=Decimal("1"))
    MultiGridColumn.objects.create(question=q, label="a")
    MultiGridRow.objects.create(question=q, statement="r1")  # empty correct set
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=[[]], fraction=Decimal("1"), attempt_count=1)
    part = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0].select_one(
        ".answers__part"
    )
    assert "Not answered" in part.get_text(" ", strip=True)
    assert part.select(".answers__glyph") == []
    assert [s.get_text(strip=True) for s in part.select(".sr-only")] == []


def test_shorttext_with_empty_expected_renders_no_hint(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "No key")
    el = _add(quiz, accepted="")
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="x", fraction=Decimal("0"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert "Correct answer:" not in item.get_text(" ", strip=True)


def test_course_language_tags_given_expected_and_content_labels(client):
    from courses.models import MatchPair
    from courses.models import MatchPairQuestionElement

    course, pupil = _owner_view(client)
    course.language = "pl"
    course.save(update_fields=["language"])
    quiz = _empty_quiz(course, "Pary")
    q = MatchPairQuestionElement.objects.create(stem="<p>Dopasuj</p>", max_marks=Decimal("1"))
    MatchPair.objects.create(question=q, left="kot", right="cat")
    MatchPair.objects.create(question=q, left="pies", right="dog")
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=["dog", "dog"], fraction=Decimal("0.5"), attempt_count=1)
    part = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0].select(
        ".answers__part"
    )[0]
    assert part.select_one(".answers__label")["lang"] == "pl"
    assert part.select_one(".answers__given")["lang"] == "pl"
    assert part.select_one(".answers__expected strong")["lang"] == "pl"


def test_answered_extendedresponse_keyword_parts_never_say_not_answered(client):
    """Spec T32's rendered check: keyword parts always have given=None, so only
    the kind == "answer" gate keeps "Not answered" off them."""
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Keywords")
    el = _add(
        quiz,
        ExtendedResponseQuestionElement,
        required_keywords="alpha\nbeta",
        forbidden_keywords="gamma",
    )
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="alpha only", fraction=Decimal("0.5"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    keyword_parts = item.select(".answers__part--keyword")
    assert len(keyword_parts) == 3
    for part in keyword_parts:
        assert "Not answered" not in part.get_text(" ", strip=True)


# --- T39 maths ---------------------------------------------------------------
def _script_srcs(soup):
    return [s["src"] for s in soup.select("script[src]")]


def test_t39_pupil_typed_maths_loads_katex_and_question_js(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Plain")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=r"\(x\)", fraction=Decimal("0"), attempt_count=1)
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    katex = [i for i, s in enumerate(srcs) if s.endswith("math.js") and "question" not in s]
    question = [i for i, s in enumerate(srcs) if s.endswith("courses/js/question.js")]
    assert katex and question and question[0] > katex[0], srcs


def test_t39_review_feedback_maths_alone_loads_katex(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Plain feedback")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        sub, el, latest_answer="Warsaw", fraction=Decimal("1"), attempt_count=1,
        review_feedback=r"See \(y\)",
    )
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert any(s.endswith("courses/js/question.js") for s in srcs)


def test_t39_no_maths_anywhere_loads_neither(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Plain none")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="Warsaw", fraction=Decimal("1"), attempt_count=1)
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert not any("katex" in s or s.endswith("question.js") for s in srcs)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py -v`
Expected: exactly **four FAIL** — `test_dragimage_row_renders_a_static_numbered_stage`, `test_zero_question_quiz_and_zero_part_question_empty_states`, `test_t39_pupil_typed_maths_loads_katex_and_question_js`, `test_t39_review_feedback_maths_alone_loads_katex`.

The other **six already PASS** on Task 7's build, by design: `test_t39_no_maths_anywhere_loads_neither` (`has_math` is still `False`), `test_token_stems_render_gap_markers_matching_the_part_labels` (Task 7 sets `stem_html`), `test_an_empty_part_that_scores_true_shows_no_tick_and_no_sr_correct` (Task 7 keys glyph and sr-only on `Part.mark`), `test_shorttext_with_empty_expected_renders_no_hint` (Task 7 uses `{% if part.expected %}`), `test_course_language_tags_given_expected_and_content_labels` (Task 7 sets `lang`), `test_answered_extendedresponse_keyword_parts_never_say_not_answered` (Task 7 gates "Not answered" on `part.kind == "answer"`). **Do not change Task 7's template to make them red** — they guard Task 7's markup, and Step 7's mutants (a), (f), (g), (h), (l) supply their red.

- [ ] **Step 3: Implement the view side.** In `courses/views_analytics.py` add imports:

```python
from courses.htmlsandbox import has_math_delimiters
from courses.models import DragToImageQuestionElement
from courses.views import _question_has_math
```

Add above `analytics_student_quiz`:

```python
def _answers_have_math(unit, rows):
    """KaTeX is needed if the title, any question, any review feedback or any
    displayed part text carries delimiters -- a pupil can type \\(x\\) (spec §5.2)."""
    if titles_have_math([unit.title]):
        return True
    for row in rows:
        if _question_has_math(row["question"]):
            return True
        if has_math_delimiters(row["review_feedback"] or ""):
            return True
        for part in row["parts"]:
            for text in (part.given, part.expected, part.label):
                if text and has_math_delimiters(text):
                    return True
    return False
```

In `_quiz_answer_rows`, add inside the loop:

```python
        row["dragimage"] = (
            question if isinstance(question, DragToImageQuestionElement) else None
        )
```

In the view context replace `"has_math": False,` with `"has_math": _answers_have_math(unit, rows),`.

- [ ] **Step 4: Implement the template side.** In `analytics_student_quiz.html`:

1. Wrap the in-progress count so it disappears for an empty quiz: `{% if pill.kind == "in_progress" and question_count %}`.
2. Wrap the `<ol class="answers__list">…</ol>` in `{% if rows %} … {% else %}<p class="answers__muted answers__empty">{% trans "This quiz has no questions." %}</p>{% endif %}`.
3. Directly after the `answers__head` div, insert the stage:

```django
      {% if row.dragimage %}
        {% comment %}A REDUCED copy of the static stage in dragtoimagequestionelement.html:
        no data-* attributes (they exist for dnd.js), no selects, pool or form.{% endcomment %}
        <div class="dragimage__stage">
          <img class="dragimage__img" src="{{ row.dragimage.media.file.url }}" alt="{{ row.dragimage.alt }}">
          {% for z in row.dragimage.zones.all %}
            <span class="dragimage__badge" style="left:{% widthratio z.x 1 100 %}%; top:{% widthratio z.y 1 100 %}%;">{{ forloop.counter }}</span>
          {% endfor %}
        </div>
      {% endif %}
```

4. Replace `<div class="answers__parts">{% for part in row.parts %} … {% endfor %}</div>` with the same markup whose `{% for %}` carries an `{% empty %}` branch:

```django
        {% empty %}
          <p class="answers__muted">{% trans "(this question no longer has any parts)" %}</p>
```

5. Add, at the end of the file:

```django
{% block extra_js %}
  {% if has_math %}
    {% comment %}question.js typesets the data-question items and MUST follow the
    KaTeX include (see _katex_js.html). The page has no form, so its submit wiring
    is a no-op.{% endcomment %}
    {% include "courses/_katex_js.html" %}
    <script src="{% static 'courses/js/question.js' %}" defer></script>
  {% endif %}
{% endblock %}
```

- [ ] **Step 5: Reword the `_katex_js.html` comment, line-count neutral.** Replace the two lines

```
question.js is deliberately NOT here: only two pages need it, and it must come
AFTER this include on both.{% endcomment %}
```

with

```
question.js is deliberately NOT here: only pages with [data-question] subtrees need
it, and it must come AFTER this include on each.{% endcomment %}
```

Check: `git diff --stat templates/courses/_katex_js.html` → `2 insertions(+), 2 deletions(-)`.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_quiz_results_render.py tests/test_title_math_assets.py -v`
Expected: all PASS.

- [ ] **Step 7: Falsify** (each by hand → RED → revert → `git diff`):
  - (a) `row["stem_html"] = mark_safe(question.stem)` (import `mark_safe`) → `test_token_stems_render_gap_markers_matching_the_part_labels` RED.
  - (b) delete the stage block → `test_dragimage_row_renders_a_static_numbered_stage` RED.
  - (c) copy the element template's interactive stage (add `data-dnd` to the div) → the same test RED.
  - (d) delete the `{% else %}` empty-quiz paragraph → `test_zero_question_quiz_and_zero_part_question_empty_states` RED.
  - (e) delete the `{% empty %}` branch → the same test RED (second half).
  - (f) template: key the sr-only span on `part.ok` (`{% if part.ok %}<span class="sr-only">Correct</span>{% endif %}` beside the glyph) → `test_an_empty_part_that_scores_true_shows_no_tick_and_no_sr_correct` RED.
  - (g) template: `{% if part.expected is not None %}` → `test_shorttext_with_empty_expected_renders_no_hint` RED.
  - (h) template: drop `lang` from `.answers__label` → `test_course_language_tags_given_expected_and_content_labels` RED.
  - (i) `_answers_have_math`: check stems only (`_question_has_math`) → `test_t39_pupil_typed_maths_loads_katex_and_question_js` RED.
  - (j) delete the `question.js` `<script>` → the same test RED.
  - (k) `_answers_have_math`: drop the `review_feedback` line → `test_t39_review_feedback_maths_alone_loads_katex` RED.
  - (l) template: remove the `{% if part.kind == "answer" %}` / `{% endif %}` pair around the given/"Not answered" markup → `test_answered_extendedresponse_keyword_parts_never_say_not_answered` RED.

- [ ] **Step 8: Commit**

```bash
git add courses/views_analytics.py templates/courses/manage/analytics_student_quiz.html templates/courses/_katex_js.html tests/test_analytics_student_quiz.py
git commit -m "feat(analytics): drag-to-image stage, empty states and maths on the answers page

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 9: Breakdown quiz titles link to the page; back link round-trips

Implements spec §3.5 (title link, pinned markup), §3.4 (back link), T37, and the `test_title_math_markers.py` extension in §6.

**Files:**
- Modify: `courses/views_analytics.py` (`analytics_student` context gains `drill_qs`)
- Modify: `templates/courses/manage/_breakdown_node.html` (quiz branch title)
- Modify: `tests/test_analytics_student_quiz.py` (append)
- Modify: `tests/test_title_math_markers.py` (`_analytics_bodies` + `test_analytics_breakdown_titles_are_marked`)

**Interfaces:**
- Consumes: Task 2's pill `submission_pk`; Task 6's `_drill_params`, URL name `courses:manage_analytics_student_quiz`.
- Produces: `analytics_student` context key `drill_qs: str` (the `_expand_qs` querystring, no leading `?`). `_breakdown_node.html` is included only from `analytics_student.html` (verified by grep), so `student` and `drill_qs` are in its context.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_analytics_student_quiz.py` (add `from courses.views_analytics import _expand_qs` to its imports):

```python
# --- T37 breakdown links and the back link -------------------------------------
def _breakdown_title_span(soup, title):
    for unit in soup.select("div.breakdown-unit"):
        span = unit.select_one(":scope > span.breakdown-unit__title")
        if span is not None and span.get_text(strip=True) == title:
            return span
    raise AssertionError(f"no breakdown title {title!r}")


def test_t37_quiz_titles_link_iff_the_pupil_has_a_submission(client):
    course, pupil = _owner_view(client)
    scored = _empty_quiz(course, "L scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("1"))
    ungraded = _empty_quiz(course, "L ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "L awaiting")
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _submitted(pupil, awaiting, score=Decimal("0"), max_score=Decimal("0"))
    live = _empty_quiz(course, "L live")
    _add(live)
    _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)
    notyet = _empty_quiz(course, "L not started")
    _add(notyet)

    qs = f"?scope=all&mode=results&student={pupil.pk}&values=raw"
    breakdown_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    soup = _soup(client.get(breakdown_path + qs))
    drill = _expand_qs("all", "results", [], [pupil.pk], "raw")
    for quiz in (scored, ungraded, awaiting, live):
        link = _breakdown_title_span(soup, quiz.title).select_one(
            "a.breakdown-unit__link"
        )
        assert link is not None, quiz.title
        assert link["href"] == _url(course, pupil.pk, quiz.pk, f"?{drill}")
    assert _breakdown_title_span(soup, notyet.title).select("a") == []


def test_t37_back_link_round_trips_scope_mode_expand_subset_and_values(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Back")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    qs = f"?scope=all&mode=results&expand={quiz.pk}&student={pupil.pk}&values=raw"
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk, qs)))
    back = soup.select_one("section.answers .manage__head a")["href"]
    expected_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    drill = _expand_qs("all", "results", [quiz.pk], [pupil.pk], "raw")
    assert back == f"{expected_path}?{drill}"
```

In `tests/test_title_math_markers.py`, `_analytics_bodies`: the existing quiz becomes the **link** branch (the enrolled student gets an in-progress submission on it) and a second quiz with no submission is the **plain** branch. **Delete** the existing `ContentNodeFactory(... unit_type="quiz" ...)` call **and** the existing `student = UserFactory()` / `EnrollmentFactory(student=student, course=course)` lines below it, and put this block in their place (leaving the old `student` lines would re-bind `student` to a second pupil with no submission, and `linked` would fail for a reason unrelated to the template):

```python
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    linked = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=nodes["part2"],
        order=1,
        title=MATHS_TITLE if maths_on == "far" else "Quiz zwykly",
    )
    QuizSubmission.objects.create(
        student=student, unit=linked, status=QuizSubmission.Status.IN_PROGRESS
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=nodes["part2"],
        order=2,
        title=MATHS_TITLE if maths_on == "far" else "Quiz bez proby",
    )
```

and in `test_analytics_breakdown_titles_are_marked` replace the single `quiz = _marked(...)` assertion with two, selected distinctly:

```python
    linked = _marked(
        breakdown,
        "div.breakdown-unit:has(.pill) > span.breakdown-unit__title:has(a.breakdown-unit__link)",
    )
    plain_quiz = _marked(
        breakdown,
        "div.breakdown-unit:has(.pill) > span.breakdown-unit__title:not(:has(a))",
    )
    assert linked, "the linked quiz title (_breakdown_node.html:N) is unmarked"
    assert plain_quiz, "the not-started quiz title (:N) is unmarked"
```

(`N` = the line of the quiz-branch `<span class="breakdown-unit__title"` after Step 3 — fill it in at Step 5.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_title_math_markers.py -k "t37 or breakdown_titles" -v`
Expected: `test_t37_quiz_titles_link_iff…` FAILS (no `a.breakdown-unit__link`); `test_analytics_breakdown_titles_are_marked` FAILS on `linked`; the back-link test PASSES already (Task 6 built `back_url`) — it is here as the regression guard for its mutants.

- [ ] **Step 3: Implement.** In `analytics_student`, add `"drill_qs": back_qs,` to the render context (it already computes `back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)`).

In `_breakdown_node.html`, replace the quiz-branch title line

```django
        <span class="breakdown-unit__title" lang="{{ course.language }}" data-math-title>{{ item.node.title }}</span>
```

with

```django
        <span class="breakdown-unit__title" lang="{{ course.language }}" data-math-title>{% if item.pill.submission_pk %}<a class="breakdown-unit__link" href="{% url 'courses:manage_analytics_student_quiz' slug=course.slug student_pk=student.pk node_pk=item.node.pk %}?{{ drill_qs }}">{{ item.node.title }}</a>{% else %}{{ item.node.title }}{% endif %}</span>
```

The span stays the direct child of `div.breakdown-unit` and keeps `lang` and `data-math-title` on both branches (spec §3.5); it stays one line, so no line in the file shifts.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_analytics_student_quiz.py tests/test_title_math_markers.py tests/test_analytics_views.py tests/test_e2e_analytics.py -v`
Expected: all non-e2e PASS (`test_e2e_analytics.py` deselects without `-m e2e`).

- [ ] **Step 5: Re-point citations.** Run `grep -n "breakdown-unit__title" templates/courses/manage/_breakdown_node.html` and replace both `N` placeholders from Step 1 with the quiz-branch line number. Then `grep -n "_breakdown_node.html:\|(:[0-9]*)" tests/test_title_math_markers.py` and confirm every citation into `_breakdown_node.html` (docstrings of `_analytics_bodies` and the breakdown test, both assertion messages) names the current line.

- [ ] **Step 6: Falsify** (each by hand → RED → revert → `git diff`):
  - (a) template: `{% if item.pill %}` instead of `{% if item.pill.submission_pk %}` → `test_t37_quiz_titles_link_iff…` RED: the not-started title gains an `<a>`, so `_breakdown_title_span(soup, notyet.title).select("a") == []` fails. (The `{% url %}` uses `node_pk` and `student.pk`, so the reverse itself still works.)
  - (b) view `analytics_student_quiz`: `back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, "percent")` → `test_t37_back_link_round_trips…` RED.
  - (c) the same with `set()` for `subset_pks` → the back-link test RED.
  - (d) template: move `data-math-title` from the span to the `<a>` → `test_analytics_breakdown_titles_are_marked` RED (`linked`).

- [ ] **Step 7: Commit**

```bash
git add courses/views_analytics.py templates/courses/manage/_breakdown_node.html tests/test_analytics_student_quiz.py tests/test_title_math_markers.py
git commit -m "feat(analytics): breakdown quiz titles open the per-question page

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 10: Query budget and styling

Implements spec T38 and §5.3.

**Files:**
- Modify: `tests/test_analytics_student_quiz.py` (append)
- Modify: `core/static/core/css/app.css` (after `.breakdown-unit__review{font-size:.8rem}`)

**Interfaces:**
- Consumes: `tests.answer_summary_fixtures.build_all_types` (Task 4).

- [ ] **Step 1: Write the test** — append to `tests/test_analytics_student_quiz.py` (add `from django.db import connection` and `from django.test.utils import CaptureQueriesContext`):

```python
# --- T38 query budget --------------------------------------------------------------
def _stored_answer(key, q):
    if key == "choice":
        return [q.choices.first().pk]
    if key == "choicegrid":
        return [q.columns.first().pk, ""]
    if key == "multigrid":
        return [[], []]
    return {
        "shorttext": "x",
        "shortnumeric": "1",
        "extendedresponse": "alpha",
        "fillblank": ["2", "5"],
        "dragfill": ["cat", "cat"],
        "dragimage": ["Heart", "Heart"],
        "matchpair": ["1", "3", "2"],
    }[key]


def _every_type_quiz(course, pupil, title, copies):
    from tests.answer_summary_fixtures import build_all_types

    quiz = _empty_quiz(course, title)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("20"))
    for _ in range(copies):
        for key, q in build_all_types().items():
            el = Element.objects.create(unit=quiz, content_object=q)
            _respond(
                sub, el, latest_answer=_stored_answer(key, q),
                fraction=Decimal("0"), attempt_count=1,
            )
    return quiz


def _page_queries(client, url):
    assert client.get(url).status_code == 200  # warm ContentType/session caches
    with CaptureQueriesContext(connection) as captured:
        assert client.get(url).status_code == 200
    return len(captured)


def test_t38_query_count_does_not_grow_with_questions(client):
    course, pupil = _owner_view(client)
    one = _every_type_quiz(course, pupil, "One of each", 1)
    two = _every_type_quiz(course, pupil, "Two of each", 2)
    assert _page_queries(client, _url(course, pupil.pk, one.pk)) == _page_queries(
        client, _url(course, pupil.pk, two.pk)
    )
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_analytics_student_quiz.py -k t38 -v`
Expected: PASS. **If it fails on this (correct) build**, print both captured query lists, find the SQL that repeats per question, and remove the N+1 at its source (a missing prefetch in `prefetch_question_children`, or a per-row lookup in the view) — never loosen the equality.

- [ ] **Step 3: Falsify** (by hand → RED → revert → `git diff`): (a) remove `"rows__correct_columns"` from the multigrid prefetch in `prefetch_question_children`; (b) remove `"media"` from the dragimage prefetch. Each → `test_t38…` RED.

- [ ] **Step 4: Styles.** Insert after the line `.breakdown-unit__review{font-size:.8rem}` in `core/static/core/css/app.css`:

```css
.breakdown-unit__link{color:inherit;text-decoration:none}
.breakdown-unit__link:hover,.breakdown-unit__link:focus-visible{text-decoration:underline}

/* --- Per-question answers page (analytics drill-down, spec PR 5) --- */
/* The number is the visible qnum, so the list draws no marker. Muted text uses
   the secondary token: the tertiary one fails AA at body size. */
.answers__status{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;margin:0 0 1rem}
.answers__count,.answers__attempts,.answers__muted,.answers__expected{color:var(--text-secondary)}
.answers__list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:1rem}
.answers__item{border:1px solid var(--border-default);border-radius:var(--radius-md);
  padding:.75rem 1rem;background:var(--surface-raised)}
.answers__head{display:flex;gap:.5rem;align-items:baseline}
.answers__qnum{font-weight:600}
.answers__verdict{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;margin:.5rem 0}
.answers__part{display:flex;flex-wrap:wrap;align-items:baseline;gap:.25rem .6rem;
  padding:.2rem 0;overflow-wrap:anywhere}
.answers__label{font-weight:500;min-width:6rem}
.answers__part--answer .answers__given{white-space:pre-wrap}
.answers__glyph--correct{color:var(--success)}
.answers__glyph--incorrect{color:var(--danger)}
.answers__gap{font-weight:600}
.answers .dragimage__stage{max-width:32rem;margin:.5rem 0}
@media (max-width:640px){
  .answers__part{flex-direction:column;align-items:flex-start}
  .answers__label{min-width:0}
}
```

Verify every token exists before relying on it: `grep -n "\-\-success:\|\-\-danger:\|\-\-border-default:\|\-\-radius-md:\|\-\-surface-raised:\|\-\-text-secondary:" core/static/core/css/*.css` — each must print a definition. The comments above contain no `*/` before their end and no `<file>.css:<line>` citation.

- [ ] **Step 5: Run** `uv run pytest tests/test_css_citations_are_durable.py tests/test_analytics_student_quiz.py -v` — Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/static/core/css/app.css tests/test_analytics_student_quiz.py
git commit -m "style(analytics): answers page layout; query budget guard

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

(The page is judged visually in Task 13's screenshot pass, light and dark.)

---

### Task 11: Polish translations and the help page

Implements spec §5.4 and §5.5.

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`, `locale/en/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.mo`
- Modify: `docs/help/teacher/drill-down.md`, `docs/help/teacher/drill-down.pl.md`

**Interfaces:** none (strings only).

- [ ] **Step 1: Extract**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

- [ ] **Step 2: Confirm the new msgids and fill Polish.** For each msgid below, `grep -n -A3 'msgid "<text>"' locale/pl/LC_MESSAGES/django.po`. If it carries `#, fuzzy`, delete **all three** of: the `#, fuzzy` line, any `#| msgid …` line, and the pre-filled `msgstr` (memory: makemessages-fuzzy-prefills-wrong-translation). Then set:

| msgid | pl msgstr |
|---|---|
| `Answers` | `Odpowiedzi` |
| `Gap %(n)s` | `Luka %(n)s` |
| `Zone %(n)s` | `Strefa %(n)s` |
| `question %(n)s` | `pytanie %(n)s` |
| `(removed option)` | `(usunięta opcja)` |
| `(this question no longer has any parts)` | `(to pytanie nie ma już żadnych części)` |
| `(none)` | `(brak)` |
| `This quiz has no questions.` | `Ten quiz nie ma pytań.` |
| `attempt %(n)s of %(max)s` | `próba %(n)s z %(max)s` |
| `attempt %(n)s` | `próba %(n)s` |
| `%(k)s of %(n)s question answered` / plural | `msgstr[0] "Odpowiedzi: %(k)s z %(n)s pytania"`, `msgstr[1] "Odpowiedzi: %(k)s z %(n)s pytań"`, `msgstr[2] "Odpowiedzi: %(k)s z %(n)s pytań"` |

The count argument is `n` (spec §5.4). "quiz" matches the existing catalog ("Ten quiz został już przesłany."). ⚠️ These are **non-native drafts** — list them in the PR description for Krzysztof to read.

If a msgid in the table is absent, the template/`gettext` call that should produce it is missing — fix the source, not the catalog. The reused msgids (`Correct`, `Incorrect`, `Partial`, `Not answered`, `Answer recorded`, `Reviewed`, `Awaiting review`, `Correct answer:`, `Breakdown`, `Review`, `Required`, `Avoid`, `up to %(m)s marks`, the pill strings) must still have their existing non-empty `msgstr`.

Run: `grep -c "^#, fuzzy" locale/pl/LC_MESSAGES/django.po` after clearing — it must print **0** (`tests/test_i18n_po_health.py` allows no fuzzy entry, no obsolete entry and no empty Polish msgstr, and checks every plural index).

- [ ] **Step 3: Compile and check**

Run: `uv run python manage.py compilemessages -l pl -l en`
Run: `uv run pytest tests/test_i18n_po_health.py tests/test_analytics_student_quiz.py -v` — Expected: PASS. `test_i18n_po_health.py` is the catalog guard (no fuzzy, no obsolete, every pl msgstr filled, plural indices complete); the page tests use English assertions, which compiling Polish does not change under `LANGUAGE_CODE = "en"`.
Run a Polish render smoke check:

```bash
uv run python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.test'); django.setup(); from django.utils import translation; translation.activate('pl'); from django.utils.translation import gettext, ngettext; print(gettext('Gap %(n)s') % {'n': 1}); print(ngettext('%(k)s of %(n)s question answered', '%(k)s of %(n)s questions answered', 5) % {'k': 2, 'n': 5})"
```

Expected: `Luka 1` and `Odpowiedzi: 2 z 5 pytań`. (Run it through a Python file in the scratchpad if the shell mangles the quoting — memory: python-heredoc-unicode-print-aborts-write; set `PYTHONIOENCODING=utf-8`.)

- [ ] **Step 4: Help text.** In `docs/help/teacher/drill-down.md`, insert before `## Related topics`:

```markdown
## Per-question answers

In a student's breakdown, the title of every quiz they have started is a link.
Click it to see that quiz question by question: the question, what the student
answered, the correct answer where theirs was wrong, the marks, and how many
attempts they used. A quiz still in progress shows the answers given so far. A
question waiting for your review links straight to the review page. The
**← Breakdown** link takes you back to the breakdown with your analytics view
unchanged.
```

In `docs/help/teacher/drill-down.pl.md`, insert before `## Powiązane tematy`:

```markdown
## Odpowiedzi na poszczególne pytania

W rozbiciu ucznia tytuł każdego rozpoczętego przez niego quizu jest odnośnikiem.
Kliknij go, aby zobaczyć quiz pytanie po pytaniu: treść pytania, odpowiedź
ucznia, poprawną odpowiedź tam, gdzie jego była błędna, punkty oraz liczbę
wykorzystanych prób. Quiz w toku pokazuje dotychczasowe odpowiedzi. Pytanie
czekające na sprawdzenie prowadzi prosto do strony sprawdzania. Odnośnik
**← Szczegóły ucznia** wraca do rozbicia bez zmiany widoku analityki.
```

The bold label is the button's real Polish text: `msgid "Breakdown"` → `msgstr "Szczegóły ucznia"` (confirm with `grep -n -A1 'msgid "Breakdown"' locale/pl/LC_MESSAGES/django.po`). The surrounding prose keeps "rozbicie", matching the page's own heading `## Rozbicie na pojedynczego ucznia`. List both help paragraphs among the non-native drafts in the PR. Then run the help tests: `uv run pytest tests -k help -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add locale docs/help/teacher/drill-down.md docs/help/teacher/drill-down.pl.md
git commit -m "i18n(analytics): Polish strings and help for the per-question page

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 12: e2e — a group teacher drills from the matrix to one answer

Implements spec T40.

**Files:**
- Modify: `tests/test_e2e_analytics.py` (append)

**Interfaces:** Consumes the whole feature through real gestures.

- [ ] **Step 1: Write the test** — append:

```python
@pytest.mark.django_db(transaction=True)
def test_group_teacher_drills_from_the_matrix_to_one_answer(page, live_server, client):
    from decimal import Decimal

    from courses.models import Element
    from courses.models import QuestionResponse
    from courses.models import QuizSubmission
    from courses.models import ShortNumericQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import GroupFactory
    from tests.factories import GroupMembershipFactory
    from tests.factories import UserFactory
    from tests.factories import make_teacher

    teacher = make_teacher(client, "e2eanswers")  # NOT staff: the kit-teacher shape
    course = CourseFactory(owner=UserFactory())
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch, title="Fractions quiz"
    )
    question = ShortNumericQuestionElement.objects.create(
        stem="<p>2/3 + 1/6?</p>", value="5/6", tolerance="", max_marks=Decimal("1")
    )
    element = Element.objects.create(unit=quiz, content_object=question)
    pupil = UserFactory(display_name="Ada L.")
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    GroupMembershipFactory(group=group, student=pupil)
    submission = QuizSubmission.objects.create(
        student=pupil,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("1"),
    )
    QuestionResponse.objects.create(
        submission=submission,
        element=element,
        latest_answer="4/9",
        fraction=Decimal("0"),
        attempt_count=1,
        locked=True,
    )

    _login(page, live_server, "e2eanswers")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    page.get_by_role("link", name="Ada L.").click()
    page.locator("a.breakdown-unit__link", has_text="Fractions quiz").click()
    item = page.locator("li.answers__item").first
    expect(item).to_contain_text("4/9")
    expect(item).to_contain_text("Correct answer: 5/6")
    page.locator("section.answers .manage__head").get_by_role("link").click()
    expect(page.locator(".breakdown .manage__title")).to_contain_text("Ada L.")
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_e2e_analytics.py -m e2e -v`
Expected: all PASS (the four existing journeys and the new one).

- [ ] **Step 3: Falsify.** In `_breakdown_node.html` change the link condition to `{% if False %}` → the new test RED (timeout waiting for `a.breakdown-unit__link` — read the failure: it must be the locator, not a login problem). Revert by hand; `git diff`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_analytics.py
git commit -m "test(analytics): e2e matrix -> breakdown -> per-question answer

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

---

### Task 13: Citation sweep, branch gates, manual pass, PR

Implements spec §7 (citation sweep, D9 prod-effect notes, manual pass) and the Global Constraints' gates.

**Files:**
- Modify: whichever files the sweep finds (known list below)

- [ ] **Step 1: Citation sweep.** Tasks 1–3 shifted lines in `courses/views.py` and `courses/rollups.py`; Tasks 6 and 9 touched `_breakdown_node.html`.

Run: `grep -rnE "views\.py:[0-9]|rollups\.py:[0-9]|_breakdown_node\.html:[0-9]" --include=*.py --include=*.html --include=*.js --include=*.css . | grep -v "^./docs/" | grep -v "\.po:"`

(`grep` exits 1 on no match — memory: set-e-pipefail-kills-on-nothing-matched; that is not an error here.)

**Scope: only citations that were ACCURATE at `d432245a`.** The grep also returns citations that were already stale on master and regex false positives, so for each hit:

1. **False positive?** Only citations into `courses/views.py`, `courses/rollups.py` or `templates/courses/manage/_breakdown_node.html` count. A hit such as `test_review_views.py:54` (another file whose name ends in `views.py`) is out of scope — skip it.
2. **Accurate before this branch?** Print the OLD target: `git show d432245a:courses/views.py | sed -n '<N>p'` (substitute the cited file and line). If that line does NOT hold the code the citation describes, the citation was already stale on master — **leave it untouched** and list it under "pre-existing stale citations" in the PR description. Do not guess what it meant.
3. **Re-point.** If the old line does hold the described code, `grep -n` the current file for a distinctive fragment of that old line and change the cited number to the new line, keeping the edited line's line count unchanged.

Candidates from the spec's review (numbers are the OLD targets; each still goes through checks 1–3):
- `demo/generator.py:177` (→ `views.py:1654-1664`) and `:205` (→ `:1674`)
- `courses/templatetags/courses_extras.py:71` (→ `views.py:1394`)
- `tests/test_publish_banners.py:209` (→ `:1372`) and `:231` (→ `:1405`)
- `tests/capture_title_math_screenshots.py:174` (→ `:1411-1417`)
- `tests/test_title_math_assets.py:269` (→ `:1318`)
- `courses/rollups.py:1085` (→ `rollups.py:244-250, :265`)

Also check hits that cite `views.py` for OTHER apps' `views.py` (e.g. `grouping/views.py`): only re-point citations into `courses/views.py` / `courses/rollups.py`.

Run the tests of every file you edited. Commit:

```bash
git commit -am "docs(code): re-point line citations shifted by the prefetch and D9 edits

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m"
```

- [ ] **Step 2: Static gates**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
```

Expected: clean, clean, "No changes detected". If `ruff check` reports fixable violations (I001 import order, formatting-adjacent E rules), run `uv run ruff check --no-cache --fix <those files>`; fix any remaining non-fixable ones by hand. If `ruff format --check` lists files, run `uv run ruff format` on exactly those. Then re-run the affected tests and commit.

- [ ] **Step 3: Branch sweep in chunks** (memory: full-suite-run-is-oom-killed — never one whole-suite run; one pytest process at a time; read each summary line):

```bash
uv run pytest tests/test_analytics_rollups.py tests/test_courses_rollups.py tests/test_analytics_views.py tests/test_analytics_student_quiz.py tests/test_answer_summary.py tests/test_prefetch_question_children.py tests/test_title_math_markers.py tests/test_title_math_assets.py -v
uv run pytest tests/test_i18n_po_health.py tests/test_courses_views.py tests/test_quiz_results_render.py tests/test_publish_banners.py tests/test_css_citations_are_durable.py tests/test_publish_viewer_scan.py tests/test_richtext.py tests/test_richtext_drift.py tests/demo -v
uv run pytest courses/tests -v
uv run pytest tests -k "question or quiz or review or gradebook or export or help" -v
uv run pytest tests/test_e2e_analytics.py tests/test_e2e_results.py tests/test_e2e_questions.py tests/test_e2e_questions_2d.py -m e2e -v
```

Expected: every summary line reports 0 failed, 0 errors. A failure in a file unrelated to this branch: re-run that file alone before believing it (memory: e2e-flakes-under-parallel-load, env-file-cannot-override-an-exported-var).

- [ ] **Step 4: Manual pass on local mat-pp** (spec §6 manual pass, §7). In the worktree with `.env` copied and `LIBLI_VENDOR_INSTANCE=true` exported for the shell:

1. `uv run python manage.py runserver`.
2. **Before D9 numbers:** on a checkout of master (`git stash` is shared across worktrees — use the main checkout on master instead), open the analytics breakdown, the matrix (results mode), a pupil's course results page and the gradebook export for a mat-pp quiz that holds a **choicegrid**; note the pill, the course-results **row**, and the gradebook maximum.
3. **After:** the same pages on this branch. Record the differences; they must match spec §7 (a grid-only AUTO quiz's pill `submitted` → `scored` and its course-results row shows the score; the headline does not move for it; a mixed quiz's gradebook maximum rises by its grid marks).
4. Provision a demo kit for mat-pp (`uv run python manage.py demo_access create …` — see `docs/deployment.md` §7 for the arguments), log in as its Teacher, open the matrix → a pupil → several quiz titles.
5. Take screenshots in **light and dark** (`user.theme`, not the cookie — memory: dialog-does-not-inherit-the-page-theme) of: a submitted quiz with wrong answers, an in-progress quiz, a quiz with a choicegrid, and the breakdown with linked titles. Judge the dark shots separately (memory: verify-ui-with-screenshots). Check: wrong answers **vary between pupils** on the same question (parent T28); no text says "you"/"your"; maths is typeset; the phone width (390px) stacks parts without horizontal page scroll.
6. Revoke the kit (`demo_access revoke …`).

Fix anything found as its own commit with a test that fails first.

- [ ] **Step 5: PR.** Push the branch and open the PR (`gh pr create`), body including:
  - What: the per-question drill-down (spec link), and **D9**.
  - **D9 changes live numbers on deploy** — paste spec §7's bullet list, plus the Step 4 before/after observations.
  - Polish msgstrs from Task 11 as **non-native drafts for review**.
  - Screenshots (light + dark).
  - Local gate results from Steps 2–3 (summary lines).
  - The body ends with:
    ```
    🤖 Generated with [Claude Code](https://claude.com/claude-code)

    https://claude.ai/code/session_01DCW2rRAKD72pPtZZFYGf5m
    ```

After merge, the vendor flag stays **unset**: PR 4 (`/for-schools/` copy) comes next (parent §6).
