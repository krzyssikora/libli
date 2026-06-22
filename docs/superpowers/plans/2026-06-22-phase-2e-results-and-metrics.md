# Phase 2e — Results & metrics (student per-course quiz summary) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a student-facing per-course quiz summary — a lean page listing each quiz unit's score + status with drill-down to the existing per-quiz results page — plus the pure aggregation helper behind it.

**Architecture:** A read-only aggregate slice. A new pure helper `build_course_results(course, student)` in `courses/rollups.py` walks the content tree (its own `parent_id`-grouped pre-order flatten) and folds in the student's frozen `QuizSubmission` rows; `awaiting_review` is detected **element-driven** (the unit has an `[R]` question), matching `quiz_results`' own `pending_count`. A new `@login_required` view `course_results` renders it; the existing per-quiz `quiz_results` page, scoring, and `QuizSubmission.score` are reused unchanged. One inert nullable column (`submitted_by`) is reserved for a Phase-3 teacher force-submit.

**Tech Stack:** Django 5.2, PostgreSQL, server-rendered templates (bespoke token CSS, no JS), pytest + factory_boy, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-06-22-phase-2e-results-and-metrics-design.md` (reviewed; 5 spec-review rounds).

## Global Constraints

- **Read-only slice:** no change to `_score_submission`, `courses/scoring.py`, `QuizSubmission.score`/`max_score`, or the per-quiz `quiz_results` page/`_results_row`. The only schema change is the inert `submitted_by` column.
- **No new dependency.** Bespoke token CSS in the existing `courses/css/courses.css`; no JS (page is plain server-rendered links — works identically JS on/off).
- **i18n EN/PL** for every new user-visible string, with real Polish, matching prior passes. Reuse existing msgids where they exist (`"Awaiting review"` → `"Oczekuje na ocenę"`, `"Back to course"` → `"Powrót do kursu"`).
- **IDOR:** the view derives the student **only** from `request.user`; never a URL parameter.
- **Access guard:** reuse `courses.access.can_access_course` (admits enrolled OR `is_staff` OR course owner — access.py:12–18).
- **Headline basis:** course total sums **only over `SUBMITTED`** quizzes; untaken quizzes are listed but excluded. `percent = int(round(100 * Σscore / Σmax_score))`, guarded to `None` (rendered "—") when `Σmax_score in (None, 0)`.
- **Tests:** pytest + factory_boy against real PostgreSQL; `tests/` at repo root; factories in `tests/factories.py`. e2e marked `@pytest.mark.e2e` (run with `-m e2e`).
- **Migration:** generate with `makemigrations` (never hand-write — `submitted_by` → `AUTH_USER_MODEL` needs the auto-added `swappable_dependency`). Expected number `0020` (latest at plan time is `0019_extendedresponsequestionelement_and_more`) — re-check at build.

---

## File Structure

- **`courses/models.py`** — add the inert `submitted_by` FK to `QuizSubmission` (Task 1).
- **`courses/migrations/0020_quizsubmission_submitted_by.py`** — generated migration (Task 1).
- **`courses/rollups.py`** — add `quiz_units_in_order(course)` (Task 2) and `build_course_results(course, student)` (Task 3), sibling to the existing `build_outline`.
- **`courses/views.py`** — add the `course_results` view (Task 4).
- **`courses/urls.py`** — add the `course_results` URL (Task 4).
- **`templates/courses/course_results.html`** — new page template (Task 4).
- **`templates/courses/outline.html`**, **`templates/courses/my_courses.html`** — add the "My results" entry links (Task 5).
- **`locale/pl/LC_MESSAGES/django.po`** (+ compiled `.mo`) — Polish for new strings (Task 6).
- **Tests:** `tests/test_courses_models.py` (Task 1), `tests/test_courses_rollups.py` (Tasks 2–3), `tests/test_courses_views.py` (Tasks 4–5), `tests/test_i18n_results.py` (Task 6), `tests/test_e2e_results.py` (Task 7).

---

## Task 1: Reserved `submitted_by` seam on `QuizSubmission` + migration

**Files:**
- Modify: `courses/models.py` (the `QuizSubmission` model, after `max_score`/`created`/`updated` — around models.py:912–917)
- Create: `courses/migrations/0020_quizsubmission_submitted_by.py` (generated)
- Test: `tests/test_courses_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `QuizSubmission.submitted_by` (nullable FK to `settings.AUTH_USER_MODEL`, `related_name="+"`). **No other task reads or writes it** — it is an inert Phase-3 hook.

- [ ] **Step 1: Write the failing test**

In `tests/test_courses_models.py` add:

```python
@pytest.mark.django_db
def test_quizsubmission_submitted_by_is_nullable_and_defaults_none():
    from tests.factories import QuizSubmissionFactory

    sub = QuizSubmissionFactory()
    assert sub.submitted_by is None  # never written by 2e
    field = sub._meta.get_field("submitted_by")
    assert field.null is True
    assert field.remote_field.on_delete.__name__ == "SET_NULL"
```

(If `tests/test_courses_models.py` does not already `import pytest`, add it at the top.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_courses_models.py::test_quizsubmission_submitted_by_is_nullable_and_defaults_none -v`
Expected: FAIL — `FieldDoesNotExist: QuizSubmission has no field named 'submitted_by'`.

- [ ] **Step 3: Add the model field**

In `courses/models.py`, inside `class QuizSubmission`, add after the `max_score` field (before `created`):

```python
    # Reserved, inert hook for Phase-3 teacher "force-submit" (set by Phase 3 only;
    # 2e never writes it). related_name="+" avoids a reverse-accessor clash with the
    # other AUTH_USER_MODEL FKs (student, QuestionResponse.reviewed_by).
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
```

(`settings` and `models` are already imported in `courses/models.py`.)

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations courses`
Expected: creates `courses/migrations/0020_quizsubmission_submitted_by.py` containing one `AddField` plus an auto-added `swappable_dependency(settings.AUTH_USER_MODEL)`. Do not hand-edit it.

- [ ] **Step 5: Run the test + migration check to verify they pass**

Run: `python -m pytest tests/test_courses_models.py::test_quizsubmission_submitted_by_is_nullable_and_defaults_none -v`
Expected: PASS.
Run: `python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (migration is complete/consistent).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations/0020_quizsubmission_submitted_by.py tests/test_courses_models.py
git commit -m "feat(2e): reserve inert QuizSubmission.submitted_by seam for Phase-3 force-submit"
```

---

## Task 2: `quiz_units_in_order(course)` — pre-order quiz-unit flatten

**Files:**
- Modify: `courses/rollups.py`
- Test: `tests/test_courses_rollups.py`

**Interfaces:**
- Consumes: `ContentNode` (kinds/unit-types).
- Produces: `quiz_units_in_order(course) -> list[ContentNode]` — the course's quiz units (`kind == UNIT and unit_type == QUIZ`) in **depth-first pre-order**, one DB query (`course.nodes.all()`), `parent_id`-grouped recursion. Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

In `tests/test_courses_rollups.py` add (the imports `CourseFactory`, `ContentNodeFactory` are already present at the top of that file):

```python
@pytest.mark.django_db
def test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes():
    from courses.rollups import quiz_units_in_order

    course = CourseFactory()
    # Two chapters; ch1 (order 0) contains a quiz at LOCAL order 9 and a lesson at 0;
    # ch2 (order 1) contains a quiz at order 0. A naive flat scan of course.nodes.all()
    # (sorted globally by order,pk) would yield [q_b, q_a] — pre-order yields [q_a, q_b].
    ch1 = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None, order=0)
    ch2 = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None, order=1)
    q_a = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch1, order=9)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch1, order=0)
    q_b = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch2, order=0)

    units = quiz_units_in_order(course)
    assert [u.pk for u in units] == [q_a.pk, q_b.pk]  # pre-order; lesson + chapters excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_courses_rollups.py::test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes -v`
Expected: FAIL — `ImportError: cannot import name 'quiz_units_in_order'`.

- [ ] **Step 3: Implement the flatten**

In `courses/rollups.py`, the existing top imports are `from courses.models import ContentNode` and `from courses.models import UnitProgress`. Add the function (after `build_outline`):

```python
def quiz_units_in_order(course):
    """Quiz units (kind=UNIT, unit_type=QUIZ) in depth-first pre-order of the content
    tree — the order they appear walking the outline top to bottom. ONE query
    (course.nodes.all(), ordered by ContentNode.Meta.ordering = ["order","pk"]);
    parent_id-grouped recursion. A flat iteration of course.nodes.all() is NOT
    pre-order (sibling `order` is only locally monotonic) and must not be used.
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    result = []

    def walk(parent_id):
        for node in children.get(parent_id, []):
            if (
                node.kind == ContentNode.Kind.UNIT
                and node.unit_type == ContentNode.UnitType.QUIZ
            ):
                result.append(node)
            walk(node.pk)

    walk(None)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_courses_rollups.py::test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/rollups.py tests/test_courses_rollups.py
git commit -m "feat(2e): add quiz_units_in_order pre-order flatten helper"
```

---

## Task 3: `build_course_results(course, student)` — the aggregation helper

**Files:**
- Modify: `courses/rollups.py`
- Test: `tests/test_courses_rollups.py`

**Interfaces:**
- Consumes: `quiz_units_in_order` (Task 2); `QuizSubmission`, `Element`, `QuestionElement` and the 8 concrete question models; `ContentType`.
- Produces: `build_course_results(course, student) -> dict` with keys `course`, `rows` (list), `done_count: int`, `total_count: int`, `score: Decimal|None`, `max_score: Decimal|None`, `percent: int|None`. Each **row** is `{"unit": ContentNode, "status": str, "graded": bool, "score": Decimal|None, "max_score": Decimal|None, "pending": bool, "url_name": str}` where `status ∈ {"not_started","in_progress","submitted","awaiting_review"}` and `url_name ∈ {"courses:quiz_unit","courses:quiz_results"}`. Consumed by Task 4 (view/template).

- [ ] **Step 1: Write the failing tests**

In `tests/test_courses_rollups.py`, add the imports at the top of the file:

```python
from decimal import Decimal

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory  # noqa: F401  (used by later tasks' tests)
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
```

Then add a small local builder and the tests:

```python
def _quiz_with_questions(course, modes):
    """A quiz unit (root-level) whose questions have the given marking modes.
    modes: list of (mode, max_marks_decimal). Returns the unit."""
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    for i, (mode, mm) in enumerate(modes):
        q = ShortTextQuestionElement.objects.create(
            stem=f"q{i}", accepted="a", marking_mode=mode, max_marks=mm
        )
        Element.objects.create(unit=unit, content_object=q)
    return unit


@pytest.mark.django_db
def test_build_course_results_combined_headline_and_statuses():
    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()
    # A: submitted [A] 6/10
    a = _quiz_with_questions(course, [("A", Decimal("10"))])
    QuizSubmissionFactory(student=student, unit=a, status="submitted",
                          score=Decimal("6.00"), max_score=Decimal("10.00"))
    # B: awaiting_review [A+R], frozen [A] portion 3/5
    b = _quiz_with_questions(course, [("A", Decimal("5")), ("R", Decimal("4"))])
    QuizSubmissionFactory(student=student, unit=b, status="submitted",
                          score=Decimal("3.00"), max_score=Decimal("5.00"))
    # C: fully-[N] 0/0
    c = _quiz_with_questions(course, [("N", Decimal("1"))])
    QuizSubmissionFactory(student=student, unit=c, status="submitted",
                          score=Decimal("0.00"), max_score=Decimal("0.00"))
    # D: in_progress
    d = _quiz_with_questions(course, [("A", Decimal("1"))])
    QuizSubmissionFactory(student=student, unit=d, status="in_progress")
    # E: not_started (no submission)
    _quiz_with_questions(course, [("A", Decimal("1"))])

    s = build_course_results(course, student)
    assert s["done_count"] == 3
    assert s["total_count"] == 5
    assert s["score"] == Decimal("9.00")
    assert s["max_score"] == Decimal("15.00")
    assert s["percent"] == 60
    assert isinstance(s["percent"], int)
    assert isinstance(s["done_count"], int)
    by_pk = {r["unit"].pk: r for r in s["rows"]}
    assert by_pk[a.pk]["status"] == "submitted" and by_pk[a.pk]["graded"] is True
    assert by_pk[b.pk]["status"] == "awaiting_review" and by_pk[b.pk]["pending"] is True
    assert by_pk[b.pk]["graded"] is True
    assert by_pk[c.pk]["status"] == "submitted" and by_pk[c.pk]["graded"] is False
    assert by_pk[d.pk]["status"] == "in_progress"


@pytest.mark.django_db
def test_awaiting_review_is_element_driven_even_for_unanswered_review_question():
    # C1 regression: QuestionResponse rows are lazy; an unanswered [R] has no row.
    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()
    unit = _quiz_with_questions(course, [("R", Decimal("4"))])  # all-[R], nothing answered
    QuizSubmissionFactory(student=student, unit=unit, status="submitted",
                          score=Decimal("0.00"), max_score=Decimal("0.00"))

    row = build_course_results(course, student)["rows"][0]
    assert row["status"] == "awaiting_review"
    assert row["pending"] is True
    assert row["graded"] is False  # no [A] question


@pytest.mark.django_db
def test_build_course_results_empty_and_zero_guards():
    from courses.rollups import build_course_results

    # No quizzes at all → empty rows, percent None.
    empty_course = CourseFactory()
    s0 = build_course_results(empty_course, UserFactory())
    assert s0["rows"] == [] and s0["total_count"] == 0 and s0["percent"] is None

    # One quiz, none submitted → not_started, percent None.
    course = CourseFactory()
    student = UserFactory()
    _quiz_with_questions(course, [("A", Decimal("1"))])
    s1 = build_course_results(course, student)
    assert s1["done_count"] == 0 and s1["total_count"] == 1
    assert s1["rows"][0]["status"] == "not_started"
    assert s1["percent"] is None and s1["score"] is None


@pytest.mark.django_db
def test_build_course_results_row_url_names():
    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()
    sub_unit = _quiz_with_questions(course, [("A", Decimal("1"))])
    QuizSubmissionFactory(student=student, unit=sub_unit, status="submitted",
                          score=Decimal("1.00"), max_score=Decimal("1.00"))
    _quiz_with_questions(course, [("A", Decimal("1"))])  # not started

    by_status = {r["status"]: r for r in build_course_results(course, student)["rows"]}
    assert by_status["submitted"]["url_name"] == "courses:quiz_results"
    assert by_status["not_started"]["url_name"] == "courses:quiz_unit"


@pytest.mark.django_db
def test_build_course_results_query_count_is_size_independent():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()

    def add(n):
        for _ in range(n):
            u = _quiz_with_questions(course, [("A", Decimal("1"))])
            QuizSubmissionFactory(student=student, unit=u, status="submitted",
                                  score=Decimal("1.00"), max_score=Decimal("1.00"))

    add(3)
    build_course_results(course, student)  # warm the ContentType cache
    with CaptureQueriesContext(connection) as c1:
        build_course_results(course, student)
    add(20)
    with CaptureQueriesContext(connection) as c2:
        build_course_results(course, student)
    assert len(c1) == len(c2)  # N-independent: no per-unit / per-submission N+1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_courses_rollups.py -k build_course_results -v`
Expected: FAIL — `ImportError: cannot import name 'build_course_results'`.

- [ ] **Step 3: Implement the helper**

In `courses/rollups.py`, extend the imports:

```python
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress

# The 8 concrete QuestionElement subclasses (the roadmap's "9 types" — single+multi
# MCQ share ChoiceQuestionElement). Mirrors courses/views.py:91-100.
_QUESTION_MODELS = [
    ChoiceQuestionElement,
    ShortTextQuestionElement,
    ShortNumericQuestionElement,
    FillBlankQuestionElement,
    DragFillBlankQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    ExtendedResponseQuestionElement,
]
```

Then add the function (after `quiz_units_in_order`):

```python
def build_course_results(course, student):
    """Per-course quiz summary for one student (the viewing user). Pure of side
    effects. Sums the headline over SUBMITTED quizzes only; awaiting_review is
    element-driven (the unit has an [R] question) — NOT a QuestionResponse scan,
    since responses are lazy and an unanswered [R] has no row."""
    units = quiz_units_in_order(course)
    unit_pks = [u.pk for u in units]

    submissions = {
        s.unit_id: s
        for s in QuizSubmission.objects.filter(student=student, unit__course=course)
    }

    # Per-unit marking-mode presence, resolved via the Element GFK. Filter to
    # question content-types so the GFK batch only pulls questions (Element can
    # point at Text/Image/Math too).
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS
    }
    has_auto = {}
    has_review = {}
    elements = Element.objects.filter(
        unit_id__in=unit_pks, content_type_id__in=question_ct_ids
    ).prefetch_related("content_object")
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):  # defensive parity with quiz_results
            continue
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            has_auto[el.unit_id] = True
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            has_review[el.unit_id] = True

    rows = []
    score_sum = Decimal("0")
    max_sum = Decimal("0")
    done_count = 0
    for unit in units:
        sub = submissions.get(unit.pk)
        if sub is None:
            rows.append({
                "unit": unit, "status": "not_started", "graded": False,
                "score": None, "max_score": None, "pending": False,
                "url_name": "courses:quiz_unit",
            })
            continue
        if sub.status == QuizSubmission.Status.IN_PROGRESS:
            rows.append({
                "unit": unit, "status": "in_progress", "graded": False,
                "score": None, "max_score": None, "pending": False,
                "url_name": "courses:quiz_unit",
            })
            continue
        # SUBMITTED
        graded = has_auto.get(unit.pk, False)  # ≡ max_score > 0 (max_marks >= 0.01)
        pending = has_review.get(unit.pk, False)
        rows.append({
            "unit": unit,
            "status": "awaiting_review" if pending else "submitted",
            "graded": graded,
            "score": sub.score,
            "max_score": sub.max_score,
            "pending": pending,
            "url_name": "courses:quiz_results",
        })
        done_count += 1
        score_sum += sub.score or Decimal("0")
        max_sum += sub.max_score or Decimal("0")

    percent = None
    if max_sum and max_sum > 0:
        percent = int(round(Decimal(100) * score_sum / max_sum))

    return {
        "course": course,
        "rows": rows,
        "done_count": done_count,
        "total_count": len(units),
        "score": score_sum if done_count else None,
        "max_score": max_sum if done_count else None,
        "percent": percent,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_courses_rollups.py -k build_course_results -v`
Expected: PASS (all 5).
Run: `python -m pytest tests/test_courses_rollups.py -v`
Expected: PASS (existing `build_outline` tests still green).

- [ ] **Step 5: Commit**

```bash
git add courses/rollups.py tests/test_courses_rollups.py
git commit -m "feat(2e): add build_course_results aggregation helper (element-driven awaiting_review)"
```

---

## Task 4: `course_results` view + URL + template

**Files:**
- Modify: `courses/views.py` (new view, near `course_outline` ~views.py:161)
- Modify: `courses/urls.py` (new path, near the `course_outline` line ~urls.py:11)
- Create: `templates/courses/course_results.html`
- Test: `tests/test_courses_views.py`

**Interfaces:**
- Consumes: `build_course_results` (Task 3); `can_access_course`, `Course`, `get_object_or_404`, `login_required`, `PermissionDenied` (all already imported in `courses/views.py`); `build_course_results` must be imported.
- Produces: the route `courses:course_results` (`courses/<slug>/results/`) and the rendered page.

- [ ] **Step 1: Write the failing tests**

In `tests/test_courses_views.py` add (check the file's existing imports; add any missing — `pytest`, and from `tests.factories`: `CourseFactory`, `ContentNodeFactory`, `EnrollmentFactory`, `UserFactory`, `QuizSubmissionFactory`, `make_login`; from `courses.models`: `Element`, `ShortTextQuestionElement`; `from decimal import Decimal`):

```python
def _quiz_with_auto_q(course, max_marks=Decimal("10")):
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=max_marks
    )
    Element.objects.create(unit=unit, content_object=q)
    return unit


@pytest.mark.django_db
def test_course_results_requires_login(client):
    course = CourseFactory()
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 302
    assert "login" in resp.url


@pytest.mark.django_db
def test_course_results_403_for_outsider(client):
    course = CourseFactory()  # owner None, not open
    make_login(client, "outsider")  # not enrolled, not staff, not owner
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_course_results_staff_preview_empty(client):
    course = CourseFactory()
    user = make_login(client, "staff1")
    user.is_staff = True
    user.save()
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 200
    assert "Done 0 of 0" in resp.content.decode()


@pytest.mark.django_db
def test_course_results_enrolled_renders_rows_and_drilldown(client):
    course = CourseFactory()
    user = make_login(client, "stud")
    EnrollmentFactory(student=user, course=course)
    unit = _quiz_with_auto_q(course)
    QuizSubmissionFactory(student=user, unit=unit, status="submitted",
                          score=Decimal("8.00"), max_score=Decimal("10.00"))
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Done 1 of 1" in body
    assert "8 / 10" in body
    assert f"/courses/{course.slug}/u/{unit.pk}/quiz/results/" in body


@pytest.mark.django_db
def test_course_results_only_own_submissions(client):
    course = CourseFactory()
    me = make_login(client, "me")
    EnrollmentFactory(student=me, course=course)
    other = UserFactory()
    unit = _quiz_with_auto_q(course)
    QuizSubmissionFactory(student=other, unit=unit, status="submitted",
                          score=Decimal("9.00"), max_score=Decimal("10.00"))
    body = client.get(f"/courses/{course.slug}/results/").content.decode()
    assert "Done 0 of 1" in body   # I submitted nothing
    assert "9 / 10" not in body     # never leak another student's score
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_courses_views.py -k course_results -v`
Expected: FAIL — 404 (no URL) / `NoReverseMatch` / `AttributeError: module 'courses.views' has no attribute 'course_results'`.

- [ ] **Step 3: Add the view**

In `courses/views.py`, near `course_outline` (after it, ~views.py:169). First ensure the rollups import includes the helper — find the existing `from courses.rollups import build_outline` and add:

```python
from courses.rollups import build_course_results
```

Then add the view:

```python
@login_required
def course_results(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    # student is always request.user — no IDOR surface. `course` is passed
    # top-level as the template's canonical source (summary also carries it).
    summary = build_course_results(course, request.user)
    return render(
        request, "courses/course_results.html",
        {"course": course, "summary": summary},
    )
```

- [ ] **Step 4: Add the URL**

In `courses/urls.py`, add immediately after the `course_outline` line (urls.py:11):

```python
    path("courses/<slug:slug>/results/", views.course_results, name="course_results"),
```

- [ ] **Step 5: Create the template**

Create `templates/courses/course_results.html`:

```django
{% extends "base.html" %}
{% load i18n static courses_extras %}
{% block head_title %}{{ course.title }} — {% trans "My results" %} — libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">{% endblock %}
{% block content %}
<article class="course-results" lang="{{ course.language }}">
  <h1>{{ course.title }} — {% trans "My results" %}</h1>
  <p class="course-results__headline">
    {% blocktrans with done=summary.done_count total=summary.total_count %}Done {{ done }} of {{ total }} quizzes{% endblocktrans %} ·{% if summary.percent is None %} —{% else %} {{ summary.percent }}% · {{ summary.score|marks }} / {{ summary.max_score|marks }}{% endif %}
  </p>
  {% if summary.rows %}
  <ol class="course-results__list">
    {% for row in summary.rows %}
    <li class="course-results__item is-{{ row.status }}">
      <span class="course-results__title">{{ row.unit.title }}</span>
      {% if row.status == "submitted" %}
        {% if row.graded %}
          <span class="course-results__score">{{ row.score|marks }} / {{ row.max_score|marks }}</span>
        {% else %}
          <span class="course-results__cue">{% trans "submitted — not graded" %}</span>
        {% endif %}
        <a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "details" %}</a>
      {% elif row.status == "awaiting_review" %}
        {% if row.graded %}<span class="course-results__score">{{ row.score|marks }} / {{ row.max_score|marks }}</span>{% endif %}
        <span class="course-results__cue">⏳ {% trans "Awaiting review" %}</span>
        <a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "details" %}</a>
      {% elif row.status == "in_progress" %}
        <span class="course-results__cue">{% trans "in progress" %}</span>
        <a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "resume" %}</a>
      {% else %}
        <span class="course-results__cue">— · {% trans "not started" %}</span>
        <a href="{% url row.url_name slug=course.slug node_pk=row.unit.pk %}">{% trans "start" %}</a>
      {% endif %}
    </li>
    {% endfor %}
  </ol>
  {% else %}
    <p class="empty">{% trans "No quizzes in this course yet" %}</p>
  {% endif %}
  <a class="btn" href="{% url 'courses:course_outline' slug=course.slug %}">{% trans "Back to course" %}</a>
</article>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_courses_views.py -k course_results -v`
Expected: PASS (all 5).

- [ ] **Step 7: Commit**

```bash
git add courses/views.py courses/urls.py templates/courses/course_results.html tests/test_courses_views.py
git commit -m "feat(2e): course_results view, URL, and template"
```

---

## Task 5: Entry-point links (course outline + My-courses)

**Files:**
- Modify: `templates/courses/outline.html` (header `<section class="outline">`, outline.html:5–7)
- Modify: `templates/courses/my_courses.html` (per-course `<li>`, my_courses.html:10)
- Test: `tests/test_courses_views.py`

**Interfaces:**
- Consumes: the `courses:course_results` route (Task 4).
- Produces: a "My results" link on both pages. No score data on either page (just the link).

- [ ] **Step 1: Write the failing tests**

In `tests/test_courses_views.py` add:

```python
@pytest.mark.django_db
def test_outline_has_my_results_link(client):
    course = CourseFactory()
    user = make_login(client, "s1")
    EnrollmentFactory(student=user, course=course)
    body = client.get(f"/courses/{course.slug}/").content.decode()
    assert f"/courses/{course.slug}/results/" in body


@pytest.mark.django_db
def test_my_courses_has_my_results_link(client):
    course = CourseFactory()
    user = make_login(client, "s2")
    EnrollmentFactory(student=user, course=course)
    body = client.get("/courses/").content.decode()
    assert f"/courses/{course.slug}/results/" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_courses_views.py -k my_results_link -v`
Expected: FAIL (assertion: link substring not found).

- [ ] **Step 3: Add the outline link**

In `templates/courses/outline.html`, replace the header section (lines 5–7):

```django
<section class="outline" lang="{{ course.language }}">
  <h1>{{ course.title }}</h1>
</section>
```

with:

```django
<section class="outline" lang="{{ course.language }}">
  <h1>{{ course.title }}</h1>
  <p class="outline__links"><a href="{% url 'courses:course_results' slug=course.slug %}">📊 {% trans "My results" %}</a></p>
</section>
```

- [ ] **Step 4: Add the My-courses link**

In `templates/courses/my_courses.html`, replace the list item (line 10):

```django
        <li><a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a></li>
```

with:

```django
        <li>
          <a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
          — <a href="{% url 'courses:course_results' slug=course.slug %}">{% trans "My results" %}</a>
        </li>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_courses_views.py -k "my_results_link or course_results" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/outline.html templates/courses/my_courses.html tests/test_courses_views.py
git commit -m "feat(2e): add 'My results' entry links on outline and my-courses"
```

---

## Task 6: i18n — Polish for the new strings

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ generated `.mo`)
- Test: `tests/test_i18n_results.py` (create)

**Interfaces:**
- Consumes: the template strings from Task 4/5.
- Produces: Polish translations so a `pl` render shows Polish.

New msgids and their Polish (reuse existing `"Awaiting review"` and `"Back to course"` — already translated):

| msgid | msgstr (pl) |
|---|---|
| `My results` | `Moje wyniki` |
| `Done %(done)s of %(total)s quizzes` | `Ukończono %(done)s z %(total)s quizów` |
| `submitted — not graded` | `przesłano — bez oceny` |
| `in progress` | `w toku` |
| `not started` | `nie rozpoczęto` |
| `details` | `szczegóły` |
| `resume` | `wznów` |
| `start` | `rozpocznij` |
| `No quizzes in this course yet` | `Ten kurs nie ma jeszcze quizów` |

- [ ] **Step 1: Write the failing test**

Create `tests/test_i18n_results.py`:

```python
import pytest
from django.utils import translation

from tests.factories import EnrollmentFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_course_results_polish(client):
    user = make_login(client, "plstu")
    from tests.factories import CourseFactory

    course = CourseFactory()
    EnrollmentFactory(student=user, course=course)
    session = client.session
    session["_language"] = "pl"
    session.save()
    with translation.override("pl"):
        resp = client.get(
            f"/courses/{course.slug}/results/", HTTP_ACCEPT_LANGUAGE="pl"
        )
    assert "Moje wyniki".encode() in resp.content
    assert "Ten kurs nie ma jeszcze quizów".encode() in resp.content  # empty-state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_i18n_results.py -v`
Expected: FAIL — the page renders the English msgids (no Polish yet).

- [ ] **Step 3: Extract messages**

Run: `python manage.py makemessages -l pl`
Expected: `locale/pl/LC_MESSAGES/django.po` gains the new `msgid` entries (empty `msgstr ""`).

- [ ] **Step 4: Fill in the Polish**

Edit `locale/pl/LC_MESSAGES/django.po`, setting each new `msgstr` from the table above. Example entries:

```po
msgid "My results"
msgstr "Moje wyniki"

#, python-format
msgid "Done %(done)s of %(total)s quizzes"
msgstr "Ukończono %(done)s z %(total)s quizów"

msgid "submitted — not graded"
msgstr "przesłano — bez oceny"

msgid "No quizzes in this course yet"
msgstr "Ten kurs nie ma jeszcze quizów"
```

(Fill the remaining rows — `in progress`, `not started`, `details`, `resume`, `start` — likewise. Leave `Awaiting review` / `Back to course` as already translated.)

- [ ] **Step 5: Compile and run the test**

Run: `python manage.py compilemessages -l pl`
Run: `python -m pytest tests/test_i18n_results.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_results.py
git commit -m "i18n(2e): Polish for the course-results summary strings"
```

---

## Task 7: e2e — student takes one quiz, views the summary

**Files:**
- Create: `tests/test_e2e_results.py`
- Test: itself (Playwright, `@pytest.mark.e2e`)

**Interfaces:**
- Consumes: the full stack (Tasks 1–6). Mirrors the harness conventions of `tests/test_e2e_quiz.py` (`_allow_async_unsafe`, `_make_student`, `_login`, `live_server`).

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_results.py`:

```python
"""Playwright e2e for Phase-2e: the per-course quiz summary page.

Student in a 2-quiz course finishes ONE quiz, opens "My results" from the
outline, and sees: "Done 1 of 2", the taken quiz's score with a working
drill-down to its /quiz/results/ page, and the untaken quiz as "not started".

Marked e2e (run with -m e2e). Harness mirrors test_e2e_quiz.py.
"""

import os
from decimal import Decimal

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _build_two_quiz_course(student):
    from courses.models import Element
    from courses.models import ShortTextQuestionElement
    from tests.factories import CourseFactory
    from tests.factories import ContentNodeFactory
    from tests.factories import EnrollmentFactory

    course = CourseFactory()
    EnrollmentFactory(student=student, course=course)
    units = []
    for i in range(2):
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type="quiz", parent=None,
            title=f"Quiz {i + 1}",
        )
        q = ShortTextQuestionElement.objects.create(
            stem="2+2?", accepted="4", marking_mode="A", max_marks=Decimal("1")
        )
        Element.objects.create(unit=unit, content_object=q)
        units.append(unit)
    return course, units


@pytest.mark.django_db(transaction=True)
def test_results_summary_after_one_quiz(page, live_server):
    student = _make_student("e2eresults")
    course, units = _build_two_quiz_course(student)
    first = units[0]

    _login(page, live_server, "e2eresults")

    # Take the first quiz: answer correctly, then finish (accept the confirm dialog).
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{first.pk}/quiz/")
    page.locator("input[name='answer'], textarea[name='answer']").first.fill("4")
    page.locator("button[type='submit']").first.click()
    page.on("dialog", lambda d: d.accept())
    page.locator("form[action*='finish'] button, button[name='finish']").first.click()
    page.wait_for_url("**/quiz/results/")

    # Open My results from the outline.
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    page.locator("a[href$='/results/']").first.click()
    page.wait_for_url(f"**/courses/{course.slug}/results/")

    body = page.content()
    assert "Done 1 of 2" in body
    # The taken quiz drills down to its per-quiz results page.
    details = page.locator(f"a[href='/courses/{course.slug}/u/{first.pk}/quiz/results/']")
    assert details.count() == 1
    # The untaken quiz shows the not-started cue.
    assert "not started" in body
```

> **Note:** the quiz-taking selectors (`input[name='answer']`, the finish button) mirror the live Phase-2c quiz UI exercised by `test_e2e_quiz.py`. If a selector differs in the running app, align it with `test_e2e_quiz.py`'s verified locators rather than inventing new ones — do not bypass the real UI (drive the actual click path).

- [ ] **Step 2: Run the e2e test**

Run: `python -m pytest tests/test_e2e_results.py -m e2e -v`
Expected: PASS (browser drives login → take quiz → results summary).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_results.py
git commit -m "test(2e): e2e for the course-results summary + drill-down"
```

---

## Final verification

- [ ] **Run the full non-e2e suite**

Run: `python -m pytest -m "not e2e" -q`
Expected: all green (new + existing).

- [ ] **Run the e2e suite**

Run: `python -m pytest -m e2e -q`
Expected: green.

- [ ] **Migration consistency**

Run: `python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

---

## Self-Review (author's check against the spec)

**Spec coverage:**
- §1.2 deliverable (view + helper, course→per-quiz, drill to existing results) → Tasks 3–4. ✓
- §2.1 headline rule (submitted-only, percent int, zero-guard) → Task 3 (`build_course_results`) + tests. ✓
- §2.2/§2.3 reserved `submitted_by` + migration → Task 1. ✓
- §3.1 flatten (pre-order, parent_id recursion, not flat scan) → Task 2; element-driven `awaiting_review`, `graded`, query N-independence → Task 3. ✓
- §3.2 view (access guard, IDOR, staff preview, top-level `course`) → Task 4. ✓
- §3.3 template (graded branch, None-percent single dash, ⏳ outside trans, empty state, drill-down URLs) → Task 4. ✓
- §3.4 entry links (outline + my-courses) → Task 5. ✓
- §4.1 invariants (read-only, IDOR, terminal submission, current-mode) → covered by reuse + tests in Tasks 3–4. ✓
- §4.2 edge cases (zero submitted, no quizzes, fully-[N], mixed, in-progress, seam inert) → Task 3 tests + Task 1 test + combined headline. ✓
- §4.3 i18n → Task 6. ✓
- §4.4 tests (status matrix, locked headline numbers, row order, query budget, element-driven incl. unanswered [R], terminal, URLs, drill-down reuse, access 302/403/staff-200, IDOR, seam) → Tasks 1–5 tests. ✓
- §4.4 e2e → Task 7. ✓
- §4.5 migration → Task 1. ✓

**Drill-down reuse (spec §3.1 "known-good") note:** the spec asks for an explicit test that `quiz_results` renders an unreviewed-`[R]` SUBMITTED submission with the "review" outcome. This page already exists from 2c/2d-iii and its behavior is covered by its own suite (`test_e2e_quiz.py` / 2d-iii tests); Task 3's `test_awaiting_review_is_element_driven...` pins the summary side (our new code), and Task 7's e2e exercises a real drill-down click. If the implementer wants belt-and-suspenders, add a `test_courses_views.py` case GETting `quiz_results` for an `[R]`-bearing SUBMITTED submission and asserting `is-review` in the body — optional, as it tests pre-existing code.

**Type consistency:** `build_course_results` return keys and row keys (Task 3 Produces) match the template field reads (Task 4) and the test assertions (Tasks 3–5): `status`, `graded`, `score`, `max_score`, `pending`, `url_name`, `done_count`, `total_count`, `percent`. `url_name` values `"courses:quiz_unit"`/`"courses:quiz_results"` match the `{% url %}` calls and the existing routes. ✓

**Placeholder scan:** no TBD/TODO; every step carries concrete code/commands. ✓
