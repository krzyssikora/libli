# Phase 3c-i — Quiz Review Queue + Force-Submit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give teachers a per-course surface to grade `[R]` (requires-review) quiz responses and force-submit a student's open quiz, unfolding the quiz's frozen score once every `[R]` is reviewed.

**Architecture:** New `courses/review.py` service module (`review_response`, `force_submit_quiz`, `pending_reviews_for`, `submission_review_state`) + new `courses/views_review.py` (three views) under the existing `manage/courses/<slug>/` URL space. The score recompute is a shared `compute_scores`/`finalize_submission` pair extracted into `courses/quiz.py` and reused by the existing student `quiz_finish` path (behavior-identical at submit) and by force-submit. Review authority is a new `grouping/scoping.py` pair (`reviewable_students`, `can_review_course`) broader than `can_manage_course` (group teachers reach their group's students). `build_course_results` becomes review-state-aware so `awaiting_review` clears only when all `[R]` are graded. Answers are rendered read-only by reusing the existing per-type `render()` path with `locked=True`.

**Tech Stack:** Django (server-rendered, token-driven CSS — no Bootstrap/React), pytest + factory_boy, Playwright (e2e), `uv` for tooling, Django i18n (EN + PL).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff ...`, `uv run pytest ...`, `uv run python manage.py ...`.
- **Lint every task:** run `uv run ruff check .` AND `uv run ruff format .` before each commit (CI runs `ruff format --check`).
- **i18n:** every new user-facing string is wrapped (`{% trans %}`/`{% blocktrans %}` in templates, `gettext`/`gettext_lazy as _` in Python) AND given a PL translation in `locale/pl/LC_MESSAGES/django.po`; recompile `.mo`. makemessages re-marks copied PL strings `#, fuzzy` (ignored at runtime) — clear the flag and verify each new msgid.
- **Review surfaces 404, never 403:** any scope/ownership/course-mismatch in a review view raises `Http404` (not `PermissionDenied`) — avoids leaking cohort-/group-gated existence. (This deliberately differs from `can_manage_course` views, which raise 403.)
- **Field-name footguns:** `Enrollment.student`, `GroupMembership.student`, but `CohortMembership.user`. `QuizSubmission.student`, `QuestionResponse.reviewed_by`/`reviewed_at`.
- **Marks are `Decimal`:** marks/fractions are `Decimal`, never float. `earned_marks` column is `max_digits=7, decimal_places=2`; `fraction` is `max_digits=5, decimal_places=4`; `max_marks` is `max_digits=7, decimal_places=2` with `MinValueValidator(Decimal("0.01"))`.
- **Commits:** each commit ends with the repo trailers:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_019mQaCmD1zxvjunhtQKit9e
  ```
  (Omitted from the short commit lines below for brevity — add them.)
- **Branch:** all work on a `phase-3c-i-quiz-review-queue` branch off `master` (not on `master`).

## File Structure

- **Create** `courses/review.py` — review domain services (no view/HTTP concerns).
- **Create** `courses/views_review.py` — the three review views (HTTP/gates/render).
- **Create** templates `templates/courses/manage/review_queue.html`, `.../review_submission.html`.
- **Create** tests `tests/test_review_services.py`, `tests/test_review_views.py`, `tests/test_e2e_review.py`. Add scoping tests to `tests/test_grouping_scoping.py`; rollup tests to the existing results-rollup test file; scoring tests alongside the existing quiz-scoring tests.
- **Modify** `courses/models.py` (one field), `courses/quiz.py` (add `compute_scores`/`finalize_submission`), `courses/views.py` (rewire `quiz_finish` to the shared helper; remove `_score_submission`), `courses/rollups.py` (`build_course_results`), `courses/forms.py` (`ReviewResponseForm`), `courses/urls.py` (3 routes), `grouping/scoping.py` (2 functions), `templates/courses/manage/_course_panel.html` (Review link), the student `quiz_results.html` + its view (show `review_feedback`), `locale/pl/LC_MESSAGES/django.po`.

---

### Task 1: Schema — `QuestionResponse.review_feedback`

**Files:**
- Modify: `courses/models.py` (class `QuestionResponse`, near the `reviewed_by` field ~line 977-984)
- Create: `courses/migrations/00XX_questionresponse_review_feedback.py` (generated)
- Test: `tests/test_review_services.py`

**Interfaces:**
- Produces: `QuestionResponse.review_feedback` — `TextField(blank=True, default="")`, read by Task 6 (write) and Task 12 (student display).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_services.py
import pytest
from courses.models import QuestionResponse
from tests.factories import QuestionResponseFactory

pytestmark = pytest.mark.django_db


def test_review_feedback_defaults_to_empty_string():
    r = QuestionResponseFactory()
    r.refresh_from_db()
    assert r.review_feedback == ""
    # field is editable plain text
    r.review_feedback = "Nice working."
    r.save()
    r.refresh_from_db()
    assert r.review_feedback == "Nice working."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_review_services.py::test_review_feedback_defaults_to_empty_string -v`
Expected: FAIL — `AttributeError`/`FieldError`: `QuestionResponse` has no `review_feedback`.

- [ ] **Step 3: Add the field**

In `courses/models.py`, inside `class QuestionResponse`, after the `reviewed_by` FK:

```python
    review_feedback = models.TextField(blank=True, default="")
```

- [ ] **Step 4: Make the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/00XX_questionresponse_review_feedback.py` adding the field with `default=""` (no interactive prompt, because the field carries a default).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_review_services.py::test_review_feedback_defaults_to_empty_string -v`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/models.py courses/migrations/ tests/test_review_services.py
git commit -m "feat(review): add QuestionResponse.review_feedback field"
```

---

### Task 2: Scoring — `compute_scores` + `finalize_submission`, generalized for `[R]`

**Files:**
- Modify: `courses/quiz.py` (add two functions)
- Modify: `courses/views.py` (`quiz_finish` ~line 569-588 calls the new helper; delete `_score_submission` ~line 540-564)
- Test: `tests/test_review_services.py` (or the existing quiz-scoring test file)

**Interfaces:**
- Produces:
  - `quiz.compute_scores(node, submission) -> tuple[Decimal, Decimal]` — pure read-only `(score, max_score)`. AUTO question: `max_marks` always into max_score; `earned_marks(r.fraction, max_marks)` into score only when a response exists with `fraction is not None`. REVIEW question: into BOTH only when its response has `reviewed_at is not None`, taking the stored `r.earned_marks` directly (NOT re-derived from `fraction`). NOT_MARKED: never counted.
  - `quiz.finalize_submission(node, submission) -> None` — locks all responses, sets `score`/`max_score` from `compute_scores`, sets status SUBMITTED, saves (model `save()` stamps `submitted_at`). Replaces the old `_score_submission`.
- Consumes (from existing code): `courses.scoring.earned_marks`, `QuestionElement`, `Decimal`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_services.py (append)
from decimal import Decimal
from django.utils import timezone
from courses import quiz as quiz_svc
from courses.models import (
    Element, QuestionElement, QuestionResponse, QuizSubmission,
    ShortTextQuestionElement, ExtendedResponseQuestionElement,
)
from tests.factories import QuizSubmissionFactory


def _auto_q(unit, *, max_marks="2"):
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?", accepted="4",
        marking_mode=QuestionElement.MarkingMode.AUTO, max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _review_q(unit, *, max_marks="5"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def test_compute_scores_auto_only_at_submit():
    sub = QuizSubmissionFactory()
    unit = sub.unit
    auto = _auto_q(unit, max_marks="2")
    _review_q(unit, max_marks="5")  # unreviewed -> excluded from both
    QuestionResponse.objects.create(
        submission=sub, element=auto, fraction=Decimal("1.0000"),
        earned_marks=Decimal("2.00"), locked=True,
    )
    score, max_score = quiz_svc.compute_scores(unit, sub)
    assert score == Decimal("2.00")
    assert max_score == Decimal("2.00")  # the [R] max is NOT counted until reviewed


def test_compute_scores_includes_reviewed_review_in_both():
    sub = QuizSubmissionFactory()
    unit = sub.unit
    rev = _review_q(unit, max_marks="5")
    QuestionResponse.objects.create(
        submission=sub, element=rev, earned_marks=Decimal("3.00"),
        fraction=Decimal("0.6000"), reviewed_at=timezone.now(), locked=True,
    )
    score, max_score = quiz_svc.compute_scores(unit, sub)
    assert score == Decimal("3.00")
    assert max_score == Decimal("5.00")


def test_finalize_submission_freezes_auto_only(client):
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.IN_PROGRESS)
    unit = sub.unit
    auto = _auto_q(unit, max_marks="2")
    QuestionResponse.objects.create(
        submission=sub, element=auto, fraction=Decimal("0.5000"),
        earned_marks=Decimal("1.00"), locked=False,
    )
    quiz_svc.finalize_submission(unit, sub)
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.submitted_at is not None
    assert sub.score == Decimal("1.00")
    assert sub.max_score == Decimal("2.00")
    assert sub.responses.filter(locked=False).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_services.py -k "compute_scores or finalize_submission" -v`
Expected: FAIL — `module 'courses.quiz' has no attribute 'compute_scores'`.

- [ ] **Step 3: Implement in `courses/quiz.py`**

Add imports at top if missing (`from decimal import Decimal`, `from courses.scoring import earned_marks`, `from courses.models import QuestionElement`), then:

```python
def compute_scores(node, submission):
    """Pure (no writes): return (score, max_score) for a submission.

    AUTO question: max_marks always counts toward max_score; earned counts toward
    score only when a response exists with a non-null fraction (matches the old
    _score_submission guard). REVIEW question: counts toward BOTH only once its
    response is reviewed (reviewed_at set), taking the stored earned_marks directly
    (never re-derived from fraction). NOT_MARKED: never counted.
    """
    responses = {r.element_id: r for r in submission.responses.all()}
    total = Decimal("0.00")
    possible = Decimal("0.00")
    for el in node.elements.all().prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            possible += q.max_marks
            if r is not None and r.fraction is not None:
                total += earned_marks(r.fraction, q.max_marks)
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            if r is not None and r.reviewed_at is not None:
                possible += q.max_marks
                total += r.earned_marks or Decimal("0.00")
        # NOT_MARKED: excluded from both, always.
    return total, possible


def finalize_submission(node, submission):
    """Freeze a submission: lock all responses, cache score/max_score, mark
    SUBMITTED, save. The shared submit path for both the student finish and the
    teacher force-submit. Caller holds select_for_update on the submission.

    The final save() MUST remain a full save (no update_fields): force-submit
    (Task 7) pre-sets submission.submitted_by in memory and relies on this single
    save to persist it. Do not narrow the save to update_fields.
    """
    score, max_score = compute_scores(node, submission)
    submission.responses.update(locked=True)
    submission.score = score
    submission.max_score = max_score
    submission.status = QuizSubmission.Status.SUBMITTED
    submission.save()  # model save() stamps submitted_at
```

(Add `from courses.models import QuizSubmission` to `quiz.py`'s imports if not already present — used for `QuizSubmission.Status.SUBMITTED`, matching the old `_score_submission` convention.)

- [ ] **Step 4: Rewire `quiz_finish` and delete `_score_submission`**

In `courses/views.py`: add the import `from courses import quiz as quiz_svc` near the other `courses` imports (views.py currently imports individual symbols like `from courses.quiz import answer_from_json, rehydrate` — it does NOT import the module, so this new import is required, not optional). Delete the `_score_submission` function (~line 540-564). In `quiz_finish` (~line 581) replace `_score_submission(node, submission)` with `quiz_svc.finalize_submission(node, submission)`.

Run: `git grep -n "_score_submission"` — after the edit, expect ZERO references (the definition and its one call are both gone); if any other reference exists, update it to `quiz_svc.finalize_submission`.

- [ ] **Step 5: Run the new tests AND the existing quiz-finish regression suite**

Run: `uv run pytest tests/test_review_services.py -k "compute_scores or finalize_submission" -v`
Expected: PASS
Run: `uv run pytest -k "quiz" -q`
Expected: PASS (the existing finish/freeze tests are unchanged — the refactor is behavior-identical at submit).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/quiz.py courses/views.py tests/test_review_services.py
git commit -m "refactor(review): extract compute_scores/finalize_submission, generalize for [R]"
```

---

### Task 3: Scoping — `reviewable_students` + `can_review_course`

**Files:**
- Modify: `grouping/scoping.py`
- Test: `tests/test_grouping_scoping.py`

**Interfaces:**
- Produces:
  - `scoping.reviewable_students(user, course) -> QuerySet[User]` — PA (`courses.change_course`) or course owner → all students with an `Enrollment` in the course; else group teacher → students in NON-archived groups (`groups_visible_to(user).filter(course=course, archived=False)`) via `GroupMembership.student`; else empty.
  - `scoping.can_review_course(user, course) -> bool` — PA/owner True; else `groups_visible_to(...).filter(course=course, archived=False).exists()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_grouping_scoping.py (append; _with_role helper already defined at top)
from tests.factories import (
    EnrollmentFactory, GroupFactory, GroupMembershipFactory, UserFactory, CourseFactory,
)


def test_pa_reviews_all_enrolled_students():
    pa = _with_role(UserFactory(), "Platform Admin")
    course = CourseFactory(owner=UserFactory())
    s1 = UserFactory(); s2 = UserFactory()
    EnrollmentFactory(student=s1, course=course)
    EnrollmentFactory(student=s2, course=course)
    ids = set(scoping.reviewable_students(pa, course).values_list("pk", flat=True))
    assert ids == {s1.pk, s2.pk}
    assert scoping.can_review_course(pa, course) is True


def test_owner_reviews_all_enrolled_students():
    owner = _with_role(UserFactory(), "Course Admin")
    course = CourseFactory(owner=owner)
    s1 = UserFactory()
    EnrollmentFactory(student=s1, course=course)
    assert list(scoping.reviewable_students(owner, course)) == [s1]
    assert scoping.can_review_course(owner, course) is True


def test_group_teacher_reviews_only_their_group_students():
    teacher = _with_role(UserFactory(), "Teacher")
    course = CourseFactory(owner=UserFactory())  # not owned by the teacher
    g = GroupFactory(course=course)
    g.teachers.add(teacher)
    mine = UserFactory(); GroupMembershipFactory(group=g, student=mine)
    other = UserFactory(); EnrollmentFactory(student=other, course=course)  # enrolled, not in group
    ids = set(scoping.reviewable_students(teacher, course).values_list("pk", flat=True))
    assert ids == {mine.pk}  # the self/other-enrolled student is invisible to the teacher
    assert scoping.can_review_course(teacher, course) is True


def test_archived_group_gives_no_review_reach():
    teacher = _with_role(UserFactory(), "Teacher")
    course = CourseFactory(owner=UserFactory())
    g = GroupFactory(course=course, archived=True)
    g.teachers.add(teacher)
    GroupMembershipFactory(group=g, student=UserFactory())
    assert list(scoping.reviewable_students(teacher, course)) == []
    assert scoping.can_review_course(teacher, course) is False


def test_unrelated_teacher_cannot_review():
    teacher = _with_role(UserFactory(), "Teacher")
    course = CourseFactory(owner=UserFactory())
    assert scoping.can_review_course(teacher, course) is False
    assert list(scoping.reviewable_students(teacher, course)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_grouping_scoping.py -k review -v`
Expected: FAIL — `module 'grouping.scoping' has no attribute 'reviewable_students'`.

- [ ] **Step 3: Implement in `grouping/scoping.py`**

Add imports at top: `from django.contrib.auth import get_user_model`, `from courses.models import Enrollment`, `from grouping.models import GroupMembership`. Then:

```python
def reviewable_students(user, course):
    """Students whose quiz submissions `user` may review/force-submit in `course`.

    PA or course owner -> all enrolled students (Enrollment is the superset of
    anyone who could have a QuizSubmission). Group teacher -> students in the
    non-archived groups they teach/manage on this course. Else -> none.
    """
    User = get_user_model()
    if _is_platform_admin(user) or course.owner_id == user.id:
        student_ids = Enrollment.objects.filter(course=course).values("student_id")
        return User.objects.filter(pk__in=student_ids)
    group_ids = (
        groups_visible_to(user).filter(course=course, archived=False).values("pk")
    )
    student_ids = GroupMembership.objects.filter(group_id__in=group_ids).values(
        "student_id"
    )
    return User.objects.filter(pk__in=student_ids)


def can_review_course(user, course):
    """Whether `user` has any review reach on `course` (the page-level gate)."""
    if _is_platform_admin(user) or (
        course.owner_id is not None and course.owner_id == user.id
    ):
        return True
    return (
        groups_visible_to(user).filter(course=course, archived=False).exists()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_grouping_scoping.py -k review -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add grouping/scoping.py tests/test_grouping_scoping.py
git commit -m "feat(review): reviewable_students + can_review_course scoping"
```

---

### Task 4: Rollups — `build_course_results` review-state-aware

**Files:**
- Modify: `courses/rollups.py` (`build_course_results` ~line 106-201, including the docstring)
- Test: the existing results-rollup test file (find it: `git grep -l build_course_results tests/`)

**Interfaces:**
- Consumes: `QuestionResponse.reviewed_at`; the existing `has_review`/`has_auto` element maps.
- Produces (unchanged signature): `build_course_results(course, student) -> dict`. Behavior change: a SUBMITTED quiz is `pending`/`awaiting_review` only while ≥1 of its `[R]` elements is unreviewed for this submission (`reviewed_R_count < total_R_count`); the headline `score`/`max_score` exclude still-pending submissions; `done_count` still counts every SUBMITTED row.

- [ ] **Step 1: Write the failing test**

```python
# in the results-rollup test file
import pytest
from decimal import Decimal
from django.utils import timezone
from courses.models import (
    Element, QuestionElement, QuestionResponse, QuizSubmission,
    ExtendedResponseQuestionElement,
)
from courses.rollups import build_course_results
from tests.factories import (
    ContentNodeFactory, CourseFactory, EnrollmentFactory, UserFactory,
)

pytestmark = pytest.mark.django_db


def _review_quiz_with_submission(course, student, *, reviewed):
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    el = Element.objects.create(unit=unit, content_object=q)
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0.00"), max_score=Decimal("0.00"),
    )
    if reviewed:
        QuestionResponse.objects.create(
            submission=sub, element=el, earned_marks=Decimal("4.00"),
            fraction=Decimal("0.8000"), reviewed_at=timezone.now(), locked=True,
        )
        sub.score = Decimal("4.00"); sub.max_score = Decimal("5.00"); sub.save()
    return unit, sub


def test_awaiting_review_until_all_reviewed():
    course = CourseFactory(); student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    _review_quiz_with_submission(course, student, reviewed=False)
    res = build_course_results(course, student)
    row = res["rows"][0]
    assert row["status"] == "awaiting_review"
    # All-pending: the pending quiz is excluded from the headline sums, so they are
    # 0 and percent is None. (The "score" key is `score_sum if done_count else None`
    # and done_count counts the submitted-but-pending row, so score == Decimal("0"),
    # NOT None — the spec only pins percent to None for all-pending; Task 12's
    # template renders "awaiting review" when max_score is 0.)
    assert res["score"] == Decimal("0")
    assert res["percent"] is None
    assert res["done_count"] == 1  # still counts as submitted


def test_graded_after_review_unfolds_score():
    course = CourseFactory(); student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    _review_quiz_with_submission(course, student, reviewed=True)
    res = build_course_results(course, student)
    row = res["rows"][0]
    assert row["status"] == "submitted"
    assert res["score"] == Decimal("4.00")
    assert res["max_score"] == Decimal("5.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -k "awaiting_review_until_all_reviewed or graded_after_review" -v`
Expected: FAIL — current code marks `awaiting_review` purely on element presence, and the headline still includes the pending row, so `res["score"]` is not `None`.

- [ ] **Step 3: Implement the changes in `build_course_results`**

(a) Rewrite the docstring (it currently claims "NOT a QuestionResponse scan" — now it IS a batched reviewed-row scan).

(b) While building the element marking-mode maps, also count `[R]` elements per unit:

```python
    total_review = {}  # unit_id -> count of [R] elements
    ...
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            has_auto[el.unit_id] = True
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            has_review[el.unit_id] = True
            total_review[el.unit_id] = total_review.get(el.unit_id, 0) + 1
```

(c) After the submissions dict is built, add ONE batched query for reviewed-`[R]` counts per submission:

```python
    from django.db.models import Count
    reviewed_counts = dict(
        QuestionResponse.objects.filter(
            submission__in=submissions.values(),
            reviewed_at__isnull=False,
            element__content_type_id__in=question_ct_ids,
        )
        .values_list("submission_id")
        .annotate(n=Count("id"))
    )
```

(d) In the SUBMITTED branch, make `pending` review-state-aware and guard the headline adds (but NOT `done_count`):

```python
        # SUBMITTED
        graded = has_auto.get(unit.pk, False)
        total_r = total_review.get(unit.pk, 0)
        reviewed_r = reviewed_counts.get(sub.pk, 0)
        pending = total_r > 0 and reviewed_r < total_r
        rows.append(
            {
                "unit": unit,
                "status": "awaiting_review" if pending else "submitted",
                "graded": graded,
                "score": sub.score,
                "max_score": sub.max_score,
                "pending": pending,
                "url_name": "courses:quiz_results",
            }
        )
        done_count += 1  # unchanged: pending still counts as submitted
        if not pending:
            score_sum += sub.score or Decimal("0")
            max_sum += sub.max_score or Decimal("0")
```

The existing `percent` guard (`if max_sum and max_sum > 0`) already yields `None` in the all-pending case — leave it; Task 12's template renders that intentionally.

- [ ] **Step 4: Update the existing rollup regression test (intended behavior change)**

The "exclude pending from the headline" change is a deliberate semantics shift, so one existing test now asserts the OLD (include-pending) headline and WILL fail. Find it:

Run: `git grep -n "build_course_results" tests/ | grep -i headline` (it is `tests/test_courses_rollups.py::test_build_course_results_combined_headline_and_statuses`, ~lines 105-156). It builds a course where quiz B is `awaiting_review` with a frozen score (3.00/5.00) and currently asserts the headline *includes* B (`score == Decimal("9.00")`, `max_score == Decimal("15.00")`).

Update that test to the new exclude-pending headline: the pending quiz B no longer contributes, so `score` drops by 3.00 → `Decimal("6.00")` and `max_score` drops by 5.00 → `Decimal("10.00")`; recompute the expected `percent` from the new sums (`int(round(100 * 6 / 10)) == 60`) and update that assertion too. Leave the per-row status assertions (B still `awaiting_review`) unchanged. Read the test first to confirm the exact frozen values before editing — if quiz B's score differs from 3.00/5.00, adjust the deltas accordingly.

- [ ] **Step 5: Run tests to verify they pass + regression**

Run: `uv run pytest -k "awaiting_review_until_all_reviewed or graded_after_review" -v`
Expected: PASS
Run: `uv run pytest tests/test_courses_rollups.py -q`
Expected: PASS — the updated `..._combined_headline_and_statuses` test now matches the exclude-pending headline; pre-3c cases still hold (a SUBMITTED quiz with NO `[R]` element derives `submitted`; one with an unanswered `[R]` and zero reviewed rows derives `awaiting_review`).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/rollups.py tests/
git commit -m "feat(review): build_course_results clears awaiting_review only when all [R] reviewed"
```

---

### Task 5: Form — `ReviewResponseForm`

**Files:**
- Modify: `courses/forms.py`
- Test: `tests/test_review_views.py`

**Interfaces:**
- Produces: `ReviewResponseForm(data=None, *, max_marks)` — a plain `forms.Form` with `earned_marks = DecimalField(min_value=0, max_value=max_marks, decimal_places=2, max_digits=7)` and `feedback = CharField(widget=Textarea, required=False)`. Cleaned data: `{"earned_marks": Decimal, "feedback": str}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_views.py
import pytest
from decimal import Decimal
from courses.forms import ReviewResponseForm

pytestmark = pytest.mark.django_db


def test_review_form_accepts_marks_within_bounds():
    form = ReviewResponseForm({"earned_marks": "3.50", "feedback": "ok"}, max_marks=Decimal("5"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["earned_marks"] == Decimal("3.50")
    assert form.cleaned_data["feedback"] == "ok"


def test_review_form_rejects_over_max():
    form = ReviewResponseForm({"earned_marks": "6", "feedback": ""}, max_marks=Decimal("5"))
    assert not form.is_valid()
    assert "earned_marks" in form.errors


def test_review_form_rejects_negative():
    form = ReviewResponseForm({"earned_marks": "-1", "feedback": ""}, max_marks=Decimal("5"))
    assert not form.is_valid()


def test_review_form_feedback_optional():
    form = ReviewResponseForm({"earned_marks": "0"}, max_marks=Decimal("5"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["feedback"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_views.py -k review_form -v`
Expected: FAIL — `cannot import name 'ReviewResponseForm'`.

- [ ] **Step 3: Implement in `courses/forms.py`**

```python
from decimal import Decimal


class ReviewResponseForm(forms.Form):
    """Grade one [R] response: marks 0..max_marks + an optional comment."""

    earned_marks = forms.DecimalField(
        label=_("Marks awarded"),
        min_value=Decimal("0"),
        decimal_places=2,
        max_digits=7,
    )
    feedback = forms.CharField(
        label=_("Feedback (optional)"),
        widget=forms.Textarea(attrs={"rows": 4}),
        required=False,
    )

    def __init__(self, *args, max_marks, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["earned_marks"].max_value = max_marks
        # DecimalField with max_value set after construction still validates on clean.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_views.py -k review_form -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/forms.py tests/test_review_views.py
git commit -m "feat(review): ReviewResponseForm (marks + optional comment)"
```

---

### Task 6: Service — `review_response`

**Files:**
- Create: `courses/review.py`
- Test: `tests/test_review_services.py`

**Interfaces:**
- Produces: `review.review_response(*, submission, element, earned_marks, feedback, reviewer) -> QuestionResponse`. Validates `element` is an `[R]` `QuestionElement` in `submission.unit` (raises `ValueError` on a programming error — the view maps to 404); `get_or_create`s the row (creating it for an unanswered `[R]`); writes `earned_marks` (stored directly), `fraction = earned_marks/max_marks` (4dp, display-only), `review_feedback`, `reviewed_at`, `reviewed_by`, saves the response; then recomputes `submission.score`/`max_score` via `quiz.compute_scores` and saves the submission (status untouched). Atomic with `select_for_update` on the submission.
- Consumes: `quiz.compute_scores` (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_services.py (append)
from courses import review as review_svc


def test_review_response_creates_row_for_unanswered_review():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    el = _review_q(sub.unit, max_marks="5")  # no QuestionResponse exists yet
    teacher = QuizSubmissionFactory().student  # any user
    r = review_svc.review_response(
        submission=sub, element=el, earned_marks=Decimal("4.00"),
        feedback="good", reviewer=teacher,
    )
    assert r.earned_marks == Decimal("4.00")
    assert r.fraction == Decimal("0.8000")
    assert r.review_feedback == "good"
    assert r.reviewed_at is not None
    assert r.reviewed_by_id == teacher.pk
    sub.refresh_from_db()
    assert sub.score == Decimal("4.00")
    assert sub.max_score == Decimal("5.00")  # [R] now counted in max


def test_review_response_rejects_over_max_is_caller_guard():
    # bounds are the form's job; the service asserts as a programming guard
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    el = _review_q(sub.unit, max_marks="5")
    with pytest.raises(Exception):
        review_svc.review_response(
            submission=sub, element=el, earned_marks=Decimal("6.00"),
            feedback="", reviewer=sub.student,
        )


def test_review_response_rejects_non_review_element():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    auto = _auto_q(sub.unit, max_marks="2")
    with pytest.raises(ValueError):
        review_svc.review_response(
            submission=sub, element=auto, earned_marks=Decimal("1.00"),
            feedback="", reviewer=sub.student,
        )


def test_review_response_remark_overwrites():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    el = _review_q(sub.unit, max_marks="5")
    review_svc.review_response(submission=sub, element=el, earned_marks=Decimal("2.00"), feedback="", reviewer=sub.student)
    r = review_svc.review_response(submission=sub, element=el, earned_marks=Decimal("5.00"), feedback="better", reviewer=sub.student)
    assert r.earned_marks == Decimal("5.00")
    assert r.review_feedback == "better"
    sub.refresh_from_db()
    assert sub.score == Decimal("5.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_services.py -k review_response -v`
Expected: FAIL — `No module named 'courses.review'`.

- [ ] **Step 3: Implement `courses/review.py`**

```python
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from courses import quiz as quiz_svc
from courses.models import QuestionElement, QuestionResponse


def review_response(*, submission, element, earned_marks, feedback, reviewer):
    """Grade one [R] response and recompute the submission score.

    `element` must be an [R] QuestionElement in submission.unit (else ValueError —
    a programming error the view maps to 404). Bounds (0..max_marks) are the form's
    responsibility; here we assert them as a guard. Stores earned_marks directly and
    derives fraction (4dp) for display only.
    """
    question = element.content_object
    if not isinstance(question, QuestionElement) or element.unit_id != submission.unit_id:
        raise ValueError("element is not a question on this submission's unit")
    if question.marking_mode != QuestionElement.MarkingMode.REVIEW:
        raise ValueError("element is not a [R] (requires-review) question")
    assert Decimal("0") <= earned_marks <= question.max_marks, "marks out of bounds"

    with transaction.atomic():
        # Lock the submission row: serializes concurrent reviews so each recompute
        # sees all prior reviewed rows.
        submission.__class__.objects.select_for_update().get(pk=submission.pk)
        # Creating the row for an unanswered [R] is safe: the columns not in
        # `defaults` (fraction, earned_marks, last_attempt_at, reviewed_at,
        # reviewed_by) are all nullable, and review_feedback defaults to "".
        response, _ = QuestionResponse.objects.get_or_create(
            submission=submission, element=element,
            defaults={"latest_answer": None, "attempt_count": 0, "locked": True},
        )
        response.earned_marks = earned_marks
        response.fraction = (earned_marks / question.max_marks).quantize(Decimal("0.0001"))
        response.review_feedback = feedback or ""
        response.reviewed_at = timezone.now()
        response.reviewed_by = reviewer
        response.save()  # persist BEFORE the recompute query below

        score, max_score = quiz_svc.compute_scores(submission.unit, submission)
        submission.score = score
        submission.max_score = max_score
        submission.save()
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_services.py -k review_response -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/review.py tests/test_review_services.py
git commit -m "feat(review): review_response service (grade [R] + recompute)"
```

---

### Task 7: Service — `force_submit_quiz`

**Files:**
- Modify: `courses/review.py`
- Test: `tests/test_review_services.py`

**Interfaces:**
- Produces: `review.force_submit_quiz(submission, *, by) -> None`. No-op unless `status == IN_PROGRESS`. Sets `submitted_by = by` (in memory), calls `quiz.finalize_submission(submission.unit, submission)` (single save persists `submitted_by`), and creates/updates `UnitProgress(student=submission.student, unit=submission.unit)` with `completed=True` — keyed on the **student**, never `by`. Atomic, `select_for_update`. Deliberately omits the student `is_enrolled`/`can_access_course` guards (the teacher isn't enrolled).
- Consumes: `quiz.finalize_submission` (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_services.py (append)
from courses.models import UnitProgress


def test_force_submit_closes_in_progress_and_stamps_by():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.IN_PROGRESS)
    _auto_q(sub.unit, max_marks="2")
    teacher = UserFactory()
    review_svc.force_submit_quiz(sub, by=teacher)
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.submitted_by_id == teacher.pk
    assert sub.submitted_at is not None
    # progress recorded for the STUDENT, not the teacher
    assert UnitProgress.objects.filter(
        student=sub.student, unit=sub.unit, completed=True
    ).exists()
    assert not UnitProgress.objects.filter(student=teacher).exists()


def test_force_submit_already_submitted_is_noop():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    teacher = UserFactory()
    review_svc.force_submit_quiz(sub, by=teacher)
    sub.refresh_from_db()
    assert sub.submitted_by_id is None  # untouched


def test_force_submit_review_quiz_becomes_awaiting():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.IN_PROGRESS)
    _review_q(sub.unit, max_marks="5")
    review_svc.force_submit_quiz(sub, by=UserFactory())
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.max_score == Decimal("0.00")  # [R] not yet reviewed -> excluded
```

(Add `from tests.factories import UserFactory` to the imports if not present.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_services.py -k force_submit -v`
Expected: FAIL — `module 'courses.review' has no attribute 'force_submit_quiz'`.

- [ ] **Step 3: Implement in `courses/review.py`**

Add `from courses.models import QuizSubmission, UnitProgress` to the imports, then:

```python
def force_submit_quiz(submission, *, by):
    """Teacher closes a student's IN_PROGRESS quiz so it can be graded/reviewed.

    Reuses the shared finalize path (AUTO-only freeze at submit time). Records the
    STUDENT's UnitProgress completion (never the acting teacher's). No-op if already
    submitted. Deliberately omits the student enrollment guard."""
    with transaction.atomic():
        locked = QuizSubmission.objects.select_for_update().get(pk=submission.pk)
        if locked.status != QuizSubmission.Status.IN_PROGRESS:
            return
        locked.submitted_by = by
        quiz_svc.finalize_submission(locked.unit, locked)  # single save persists submitted_by
        progress, _ = UnitProgress.objects.get_or_create(
            student=locked.student, unit=locked.unit
        )
        if not progress.completed:
            progress.completed = True
            progress.save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_services.py -k force_submit -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/review.py tests/test_review_services.py
git commit -m "feat(review): force_submit_quiz service (in_progress only)"
```

---

### Task 8: Service — `pending_reviews_for` + `submission_review_state`

**Files:**
- Modify: `courses/review.py`
- Test: `tests/test_review_services.py`

**Interfaces:**
- Produces:
  - `review.pending_reviews_for(user, course) -> dict` → `{"awaiting": [QuizSubmission...], "in_progress": [QuizSubmission...]}`, scoped to `scoping.reviewable_students(user, course)`. `awaiting` = SUBMITTED quizzes in the course's quiz units with ≥1 unreviewed `[R]` (element-count-minus-reviewed-count, so an all-unanswered-`[R]` quiz still appears). `in_progress` = IN_PROGRESS quizzes in the course's quiz units.
  - `review.submission_review_state(submission) -> dict` → `{"total": int, "reviewed": int, "remaining": int, "fully_reviewed": bool}` for one submission (used by the review screen + POST re-render).
- Consumes: `scoping.reviewable_students` (Task 3); `rollups.quiz_units_in_order` (existing).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_services.py (append)
from courses.models import Element  # already imported above


def _two_quiz_units(course):
    from tests.factories import ContentNodeFactory
    return [
        ContentNodeFactory(course=course, kind="unit", unit_type="quiz"),
        ContentNodeFactory(course=course, kind="unit", unit_type="quiz"),
    ]


def test_submission_review_state_counts_unanswered_review():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    _review_q(sub.unit, max_marks="5")  # one [R], unanswered (no response)
    _review_q(sub.unit, max_marks="5")  # second [R]
    st = review_svc.submission_review_state(sub)
    assert st == {"total": 2, "reviewed": 0, "remaining": 2, "fully_reviewed": False}


def test_pending_reviews_for_lists_awaiting_and_in_progress():
    from tests.factories import CourseFactory, EnrollmentFactory, UserFactory
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    u1, u2 = _two_quiz_units(course)
    # u1: submitted with an unanswered [R] -> awaiting
    _review_q(u1, max_marks="5")
    QuizSubmission.objects.create(student=student, unit=u1, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    # u2: in progress
    QuizSubmission.objects.create(student=student, unit=u2, status=QuizSubmission.Status.IN_PROGRESS)
    data = review_svc.pending_reviews_for(owner, course)
    assert [s.unit_id for s in data["awaiting"]] == [u1.pk]
    assert [s.unit_id for s in data["in_progress"]] == [u2.pk]


def test_pending_reviews_excludes_fully_reviewed_and_out_of_scope():
    from django.utils import timezone
    from tests.factories import CourseFactory, EnrollmentFactory, UserFactory
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    # A SUBMITTED quiz whose only [R] is reviewed -> NOT awaiting.
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    rev = _review_q(unit, max_marks="5")
    done = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("5"), max_score=Decimal("5"))
    QuestionResponse.objects.create(submission=done, element=rev, earned_marks=Decimal("5.00"), fraction=Decimal("1.0000"), reviewed_at=timezone.now(), locked=True)
    # A submission for a student the owner cannot reach is invisible — here, the
    # owner CAN reach all enrolled, so use a different course's submission as the
    # out-of-scope case (its student is not enrolled in `course`).
    other_course = CourseFactory(owner=UserFactory())
    other_unit = ContentNodeFactory(course=other_course, kind="unit", unit_type="quiz")
    _review_q(other_unit, max_marks="5")
    QuizSubmission.objects.create(student=UserFactory(), unit=other_unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    data = review_svc.pending_reviews_for(owner, course)
    assert data["awaiting"] == []  # fully-reviewed dropped; other-course excluded
    assert data["in_progress"] == []
```

(`ContentNodeFactory` and `QuestionResponse` are imported earlier in this file; `_review_q` is the Task 2 helper.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_services.py -k "pending_reviews or submission_review_state" -v`
Expected: FAIL — attributes don't exist.

- [ ] **Step 3: Implement in `courses/review.py`**

Add imports: `from django.contrib.contenttypes.models import ContentType`, `from courses.rollups import quiz_units_in_order, _QUESTION_MODELS`, `from grouping import scoping`. Then:

```python
def _question_ct_ids():
    return {ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS}


def _review_element_ids(unit):
    ids = []
    for el in unit.elements.all().prefetch_related("content_object"):
        q = el.content_object
        if isinstance(q, QuestionElement) and q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            ids.append(el.pk)
    return ids


def submission_review_state(submission):
    review_ids = _review_element_ids(submission.unit)
    total = len(review_ids)
    reviewed = QuestionResponse.objects.filter(
        submission=submission, element_id__in=review_ids, reviewed_at__isnull=False
    ).count()
    return {
        "total": total,
        "reviewed": reviewed,
        "remaining": total - reviewed,
        "fully_reviewed": total > 0 and reviewed >= total,
    }


def pending_reviews_for(user, course):
    student_ids = scoping.reviewable_students(user, course).values("pk")
    units = quiz_units_in_order(course)
    unit_pks = [u.pk for u in units]
    subs = list(
        QuizSubmission.objects.filter(unit_id__in=unit_pks, student_id__in=student_ids)
        .select_related("student", "unit")
        .order_by("unit__title", "student__username")
    )
    awaiting, in_progress = [], []
    for sub in subs:
        if sub.status == QuizSubmission.Status.IN_PROGRESS:
            in_progress.append(sub)
        elif sub.status == QuizSubmission.Status.SUBMITTED:
            st = submission_review_state(sub)
            if st["total"] > 0 and not st["fully_reviewed"]:
                sub.remaining_reviews = st["remaining"]  # attach for the template label
                awaiting.append(sub)
    return {"awaiting": awaiting, "in_progress": in_progress}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_services.py -k "pending_reviews or submission_review_state" -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/review.py tests/test_review_services.py
git commit -m "feat(review): pending_reviews_for + submission_review_state services"
```

---

### Task 9: View + template + URL + nav — `review_queue` (GET)

**Files:**
- Create: `courses/views_review.py`, `templates/courses/manage/review_queue.html`
- Modify: `courses/urls.py`, `templates/courses/manage/_course_panel.html`
- Test: `tests/test_review_views.py`

**Interfaces:**
- Produces: view `review_queue(request, slug)` → URL name `courses:manage_review_queue`. Renders awaiting + in-progress sections from `review.pending_reviews_for`. 404 when `not can_review_course`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_views.py (append)
from decimal import Decimal
from django.urls import reverse
from courses.models import (
    Element, QuestionElement, QuizSubmission, ExtendedResponseQuestionElement,
)
from tests.factories import (
    ContentNodeFactory, CourseFactory, EnrollmentFactory, UserFactory, make_pa, make_login,
)


def _review_quiz(course):
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    return unit, Element.objects.create(unit=unit, content_object=q)


def test_review_queue_lists_awaiting(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, _ = _review_quiz(course)
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    resp = client.get(reverse("courses:manage_review_queue", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    assert student.username in resp.content.decode()


def test_review_queue_404_for_unrelated_user(client):
    make_login(client, "nobody")
    course = CourseFactory(owner=UserFactory())
    resp = client.get(reverse("courses:manage_review_queue", kwargs={"slug": course.slug}))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_views.py -k review_queue -v`
Expected: FAIL — `NoReverseMatch` (URL not registered).

- [ ] **Step 3: Create the view in `courses/views_review.py`**

```python
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from courses import review as review_svc
from courses.models import Course
from grouping import scoping


@login_required
def review_queue(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    data = review_svc.pending_reviews_for(request.user, course)
    return render(
        request,
        "courses/manage/review_queue.html",
        {"course": course, "awaiting": data["awaiting"], "in_progress": data["in_progress"]},
    )
```

- [ ] **Step 4: Register the URL**

In `courses/urls.py`, add `from courses import views_review` and inside `urlpatterns`:

```python
    path(
        "manage/courses/<slug:slug>/review-queue/",
        views_review.review_queue,
        name="manage_review_queue",
    ),
```

- [ ] **Step 5: Create `templates/courses/manage/review_queue.html`**

```html
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Quiz review" %} · {{ course.title }} · libli{% endblock %}
{% block content %}
<section class="manage">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Quiz review" %} — {{ course.title }}</h1>
  </header>

  <h2>{% trans "Awaiting review" %} <span class="manage__count">{{ awaiting|length }}</span></h2>
  {% if awaiting %}
    <ul class="card-list">
      {% for sub in awaiting %}
        <li class="card-list__row">
          <span>{{ sub.student.display_name|default:sub.student.username }} · {{ sub.unit.title }}</span>
          <span class="badge">{% blocktrans count n=sub.remaining_reviews %}{{ n }} to review{% plural %}{{ n }} to review{% endblocktrans %}</span>
          <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=sub.pk %}">{% trans "Review" %}</a>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="muted">{% trans "Nothing awaiting review." %}</p>
  {% endif %}

  <h2>{% trans "Open (in progress)" %} <span class="manage__count">{{ in_progress|length }}</span></h2>
  {% if in_progress %}
    <ul class="card-list">
      {% for sub in in_progress %}
        <li class="card-list__row">
          <span>{{ sub.student.display_name|default:sub.student.username }} · {{ sub.unit.title }}</span>
          <form method="post" action="{% url 'courses:manage_review_force_submit' slug=course.slug submission_pk=sub.pk %}">
            {% csrf_token %}
            <button class="btn btn--ghost btn--small" type="submit">{% trans "Force-submit" %}</button>
          </form>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="muted">{% trans "No quizzes in progress." %}</p>
  {% endif %}
</section>
{% endblock %}
```

**Register ALL THREE URL names in THIS task.** The queue template above calls
`{% url 'courses:manage_review_submission' ... %}` and `{% url 'courses:manage_review_force_submit' ... %}`; a `{% url %}` of an unregistered name raises `NoReverseMatch` at render time, which would fail the Task 9 GET test. So the two later routes must already resolve now — point them at `raise Http404` stub views in `views_review.py` that Tasks 10 and 11 flesh out. (Do NOT point them at `review_queue` — that would 200 instead of 404 for those URLs.)

Add the two stub views to `courses/views_review.py`:

```python
@login_required
def review_submission(request, slug, submission_pk):  # fleshed out in Task 10/11
    raise Http404


@login_required
def force_submit(request, slug, submission_pk):  # fleshed out in Task 11
    raise Http404
```

And the two extra URLs in `courses/urls.py`:

```python
    path(
        "manage/courses/<slug:slug>/review/<int:submission_pk>/",
        views_review.review_submission,
        name="manage_review_submission",
    ),
    path(
        "manage/courses/<slug:slug>/review/<int:submission_pk>/force-submit/",
        views_review.force_submit,
        name="manage_review_force_submit",
    ),
```

- [ ] **Step 6: Add the nav link in `_course_panel.html`**

After the existing "Media library" link:

```html
  <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_review_queue' slug=course.slug %}">{% trans "Quiz review" %}</a>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_views.py -k review_queue -v`
Expected: PASS

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_review.py courses/urls.py templates/courses/manage/review_queue.html templates/courses/manage/_course_panel.html tests/test_review_views.py
git commit -m "feat(review): review queue page + per-course Review nav link"
```

---

### Task 10: View + template — `review_submission` (GET) with read-only answers

**Files:**
- Modify: `courses/views_review.py` (flesh out `review_submission` GET)
- Create: `templates/courses/manage/review_submission.html`
- Test: `tests/test_review_views.py`

**Interfaces:**
- Produces: `review_submission(request, slug, submission_pk)` GET renders, per `[R]` element: stem, the student's answer **read-only**, and a `ReviewResponseForm`. Gates: course-match assert + per-submission gate → 404. Builds each answer's read-only HTML via `question.render(element=el, feedback_for_pk=el.pk, selected_ids=..., submitted_values=..., mode="quiz", quiz_submitted=True, locked=True)` after `quiz.rehydrate(question, response.latest_answer)`.
- Consumes: `review.submission_review_state`, `quiz.rehydrate`, `ReviewResponseForm`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_views.py (append)
def test_review_submission_shows_review_questions(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, el = _review_quiz(course)
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    resp = client.get(reverse("courses:manage_review_submission", kwargs={"slug": course.slug, "submission_pk": sub.pk}))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Explain." in body  # the [R] stem
    assert "Marks awarded" in body  # the form label


def test_review_submission_cross_course_404(client):
    pa = make_pa(client)
    course_a = CourseFactory(owner=pa)
    course_b = CourseFactory(owner=pa)
    unit_b, _ = _review_quiz(course_b)
    student = UserFactory(); EnrollmentFactory(student=student, course=course_b)
    sub = QuizSubmission.objects.create(student=student, unit=unit_b, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    # submission belongs to course_b but we ask via course_a's slug
    resp = client.get(reverse("courses:manage_review_submission", kwargs={"slug": course_a.slug, "submission_pk": sub.pk}))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_views.py -k review_submission_shows -v`
Expected: FAIL — the stub raises 404, so the 200 assertion fails.

- [ ] **Step 3: Flesh out `review_submission` GET in `courses/views_review.py`**

Add imports: `from django.shortcuts import get_object_or_404`, `from courses.models import QuestionElement, QuizSubmission, QuestionResponse`, `from courses import quiz as quiz_svc`, `from courses.forms import ReviewResponseForm`. Add a gate helper and the GET body:

```python
def _resolve_for_review(request, slug, submission_pk):
    course = get_object_or_404(Course, slug=slug)
    submission = get_object_or_404(QuizSubmission, pk=submission_pk)
    if submission.unit.course_id != course.id:
        raise Http404
    if not scoping.reviewable_students(request.user, course).filter(
        pk=submission.student_id
    ).exists():
        raise Http404
    return course, submission


def _review_rows(submission):
    rows = []
    responses = {r.element_id: r for r in submission.responses.all()}
    for el in submission.unit.elements.all().prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement) or q.marking_mode != QuestionElement.MarkingMode.REVIEW:
            continue
        r = responses.get(el.pk)
        if r is not None and r.latest_answer is not None:
            selected_ids, submitted_values = quiz_svc.rehydrate(q, r.latest_answer)
        else:
            selected_ids, submitted_values = set(), None
        answer_html = q.render(
            element=el, feedback_for_pk=el.pk, selected_ids=selected_ids,
            submitted_values=submitted_values, mode="quiz", quiz_submitted=True, locked=True,
        )
        rows.append({
            "element": el, "question": q, "response": r, "answer_html": answer_html,
            "max_marks": q.max_marks,
            "reviewed": r is not None and r.reviewed_at is not None,
            "earned_marks": r.earned_marks if r else None,
            "feedback": r.review_feedback if r else "",
            "form": ReviewResponseForm(max_marks=q.max_marks),
        })
    return rows


@login_required
def review_submission(request, slug, submission_pk):
    course, submission = _resolve_for_review(request, slug, submission_pk)
    if request.method == "POST":
        return _review_submission_post(request, course, submission)  # Task 11
    state = review_svc.submission_review_state(submission)
    return render(request, "courses/manage/review_submission.html", {
        "course": course, "submission": submission,
        "rows": _review_rows(submission), "state": state,
    })
```

(Leave `_review_submission_post` referenced; Task 11 defines it. For Task 10's tests, only GET is exercised. To keep imports resolvable, add a temporary `def _review_submission_post(request, course, submission): raise Http404` stub at the bottom, replaced in Task 11.)

- [ ] **Step 4: Create `templates/courses/manage/review_submission.html`**

```html
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Review" %} · {{ submission.unit.title }} · libli{% endblock %}
{% block content %}
<section class="manage">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Review" %}: {{ submission.student.display_name|default:submission.student.username }} — {{ submission.unit.title }}</h1>
    {% if state.fully_reviewed %}
      <p class="badge badge--open">{% trans "Fully reviewed" %}</p>
    {% else %}
      <p class="muted">{% blocktrans with done=state.reviewed total=state.total %}{{ done }} of {{ total }} reviewed{% endblocktrans %}</p>
    {% endif %}
  </header>

  {% for row in rows %}
  <article class="card">
    <div class="question__stem">{{ row.question.stem|safe }}</div>
    <div class="review__answer">{{ row.answer_html|safe }}</div>
    <form method="post" action="{% url 'courses:manage_review_submission' slug=course.slug submission_pk=submission.pk %}">
      {% csrf_token %}
      <input type="hidden" name="element_pk" value="{{ row.element.pk }}">
      <label>{% trans "Marks awarded" %} <span class="muted">/ {{ row.max_marks }}</span>
        <input type="number" step="0.01" min="0" max="{{ row.max_marks }}" name="earned_marks"
               value="{% if row.earned_marks is not None %}{{ row.earned_marks }}{% endif %}">
      </label>
      <label>{% trans "Feedback (optional)" %}
        <textarea name="feedback" rows="4">{{ row.feedback }}</textarea>
      </label>
      <button class="btn btn--primary btn--small" type="submit">{% trans "Save" %}</button>
    </form>
  </article>
  {% endfor %}
</section>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_views.py -k "review_submission_shows or cross_course_404" -v`
Expected: PASS
Run: `uv run pytest tests/test_review_views.py -q` (whole file still green)
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_review.py templates/courses/manage/review_submission.html tests/test_review_views.py
git commit -m "feat(review): review screen (GET) with read-only student answers"
```

---

### Task 11: View — `review_submission` (POST) + `force_submit` (POST)

**Files:**
- Modify: `courses/views_review.py` (replace the two stubs)
- Test: `tests/test_review_views.py`

**Interfaces:**
- Produces:
  - `review_submission` POST: reads `element_pk` + `ReviewResponseForm`, calls `review.review_response`, redirects (PRG) back to the GET on success; re-renders with `status=422` on an invalid form. A foreign/`non-[R]` `element_pk` → 404.
  - `force_submit` POST: `@require_POST`, gate, calls `review.force_submit_quiz`, `messages.success`, redirects to `manage_review_queue`.
- Consumes: `review.review_response`, `review.force_submit_quiz`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_views.py (append)
from courses.models import QuestionResponse


def test_review_post_grades_and_redirects(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, el = _review_quiz(course)
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    url = reverse("courses:manage_review_submission", kwargs={"slug": course.slug, "submission_pk": sub.pk})
    resp = client.post(url, {"element_pk": el.pk, "earned_marks": "4.00", "feedback": "well done"})
    assert resp.status_code == 302
    r = QuestionResponse.objects.get(submission=sub, element=el)
    assert r.earned_marks == Decimal("4.00")
    assert r.review_feedback == "well done"
    sub.refresh_from_db()
    assert sub.score == Decimal("4.00")


def test_review_post_invalid_marks_422(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, el = _review_quiz(course)
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("0"), max_score=Decimal("0"))
    url = reverse("courses:manage_review_submission", kwargs={"slug": course.slug, "submission_pk": sub.pk})
    resp = client.post(url, {"element_pk": el.pk, "earned_marks": "99", "feedback": ""})
    assert resp.status_code == 422


def test_force_submit_post_closes_and_redirects(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.IN_PROGRESS)
    url = reverse("courses:manage_review_force_submit", kwargs={"slug": course.slug, "submission_pk": sub.pk})
    resp = client.post(url)
    assert resp.status_code == 302
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.submitted_by_id == pa.pk


def test_force_submit_get_not_allowed(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    student = UserFactory(); EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.IN_PROGRESS)
    resp = client.get(reverse("courses:manage_review_force_submit", kwargs={"slug": course.slug, "submission_pk": sub.pk}))
    assert resp.status_code == 405
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_review_views.py -k "review_post or force_submit_post or force_submit_get" -v`
Expected: FAIL — stubs return 404.

- [ ] **Step 3: Implement the POST handlers in `courses/views_review.py`**

Add imports: `from django.contrib import messages`, `from django.shortcuts import redirect`, `from django.utils.translation import gettext as _`, `from django.views.decorators.http import require_POST`. Replace the stubs:

```python
def _review_submission_post(request, course, submission):
    element_pk = request.POST.get("element_pk")
    el = submission.unit.elements.filter(pk=element_pk).first()
    if el is None:
        raise Http404
    question = el.content_object
    if not isinstance(question, QuestionElement) or question.marking_mode != QuestionElement.MarkingMode.REVIEW:
        raise Http404
    form = ReviewResponseForm(request.POST, max_marks=question.max_marks)
    if not form.is_valid():
        state = review_svc.submission_review_state(submission)
        return render(request, "courses/manage/review_submission.html", {
            "course": course, "submission": submission,
            "rows": _review_rows(submission), "state": state,
        }, status=422)
    review_svc.review_response(
        submission=submission, element=el,
        earned_marks=form.cleaned_data["earned_marks"],
        feedback=form.cleaned_data["feedback"], reviewer=request.user,
    )
    return redirect("courses:manage_review_submission", slug=course.slug, submission_pk=submission.pk)


@require_POST
@login_required
def force_submit(request, slug, submission_pk):
    course, submission = _resolve_for_review(request, slug, submission_pk)
    review_svc.force_submit_quiz(submission, by=request.user)
    messages.success(request, _("Quiz submitted for %(student)s.") % {
        "student": submission.student.display_name or submission.student.username
    })
    return redirect("courses:manage_review_queue", slug=course.slug)
```

(Delete the temporary `force_submit`/`_review_submission_post` stubs from Tasks 9-10.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_review_views.py -q`
Expected: PASS (whole review-views file)

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_review.py tests/test_review_views.py
git commit -m "feat(review): grade [R] POST + force-submit POST"
```

---

### Task 12: Student results — show `review_feedback`

**Files:**
- Modify: the student `quiz_results` view (`courses/views.py` ~line 592+) and `templates/courses/quiz_results.html`
- Test: `tests/test_review_views.py` (or the existing quiz-results test file)

**Interfaces:**
- Consumes: `QuestionResponse.review_feedback`, `earned_marks`.
- Produces: the per-question results row for a reviewed `[R]` carries `review_feedback` + awarded marks, shown under the question.

- [ ] **Step 1: Inspect the existing row builder**

The per-question row dict is built in the helper **`_results_row(question, response)`** (`courses/views.py` ~line 631), NOT in the `quiz_results` view body (which only does `rows.append(_results_row(q, r))`). Read `_results_row` and confirm it has a `response` parameter (it does) and returns a dict with keys like `question`, `outcome`, `earned`, `possible`, `reveal_template`. The `[R]` rows have `outcome == "review"`. The new keys go into THIS function's returned dict.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_review_views.py (append)
from django.utils import timezone


def test_student_sees_review_feedback_after_grading(client):
    course = CourseFactory()
    student = make_login(client, "stu12")
    EnrollmentFactory(student=student, course=course)
    unit, el = _review_quiz(course)
    sub = QuizSubmission.objects.create(student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED, score=Decimal("5"), max_score=Decimal("5"))
    QuestionResponse.objects.create(
        submission=sub, element=el, earned_marks=Decimal("5.00"),
        fraction=Decimal("1.0000"), review_feedback="Excellent analysis.",
        reviewed_at=timezone.now(), locked=True, latest_answer="my essay",
    )
    resp = client.get(reverse("courses:quiz_results", kwargs={"slug": course.slug, "node_pk": unit.pk}))
    assert resp.status_code == 200
    assert "Excellent analysis." in resp.content.decode()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_review_views.py -k review_feedback_after_grading -v`
Expected: FAIL — the feedback string is not rendered.

- [ ] **Step 4: Implement**

In **`_results_row(question, response)`** (`courses/views.py` ~line 631), add to the returned `row` dict (alongside the existing keys; the function already has `response` in scope):

```python
            "review_feedback": (response.review_feedback if response else ""),
            "review_earned": (response.earned_marks if response else None),
```

In `templates/courses/quiz_results.html`, the `review` outcome is handled by a single inline `{% elif row.outcome == "review" %}<span class="badge">...</span>` that ends the badge `{% if %}/{% elif %}/{% endif %}` chain (~line 26). Insert the feedback block **after that `{% endif %}` and before the `{% if row.reveal_template ... %}` block, still inside the `question__feedback-panel` div** (do NOT nest it inside the if/elif chain — that is a template syntax error). The template already `{% load %}`s `courses_extras`, so the `|marks` filter resolves. Add:

```html
    {% if row.review_feedback %}
      <div class="question__feedback question__feedback--review">
        {% if row.review_earned is not None %}<span class="badge">{{ row.review_earned|marks }}/{{ row.question.max_marks|marks }}</span>{% endif %}
        <p>{{ row.review_feedback }}</p>
      </div>
    {% endif %}
```

(`{{ row.review_feedback }}` is autoescaped — plain text, no `|safe`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_review_views.py -k review_feedback_after_grading -v`
Expected: PASS
Run: `uv run pytest -k "quiz_results" -q`
Expected: PASS

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views.py templates/courses/quiz_results.html tests/test_review_views.py
git commit -m "feat(review): show teacher feedback on the student results page"
```

---

### Task 13: i18n — Polish translations + compile

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`

**Interfaces:** none (string catalog only).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: new `msgid`s for every string added in Tasks 5/9/10/11/12 (e.g. "Quiz review", "Awaiting review", "Open (in progress)", "Force-submit", "Marks awarded", "Feedback (optional)", "Fully reviewed", "%(done)s of %(total)s reviewed", "Quiz submitted for %(student)s.", "Nothing awaiting review.", "No quizzes in progress.", "Review", "Save", the blocktrans "%(n)s to review").

- [ ] **Step 2: Translate the new msgids in `locale/pl/LC_MESSAGES/django.po`**

Fill each new `msgstr` with the Polish translation, e.g.:
```
msgid "Quiz review"
msgstr "Sprawdzanie quizów"

msgid "Awaiting review"
msgstr "Oczekujące na sprawdzenie"

msgid "Marks awarded"
msgstr "Przyznane punkty"

msgid "Feedback (optional)"
msgstr "Informacja zwrotna (opcjonalnie)"

msgid "Fully reviewed"
msgstr "W pełni sprawdzone"
```

The queue's "N to review" badge is a `blocktrans count`, so its catalog entry is a PLURAL form — fill **every** Polish plural slot (`pl` has 3: `msgstr[0]`/`[1]`/`[2]`), e.g.:

```
msgid "%(n)s to review"
msgid_plural "%(n)s to review"
msgstr[0] "%(n)s do sprawdzenia"
msgstr[1] "%(n)s do sprawdzenia"
msgstr[2] "%(n)s do sprawdzenia"
```

(Translate ALL new msgids — including every plural slot; an empty `msgstr[1]`/`[2]` renders blank at runtime for those counts.) **Clear any `#, fuzzy` flag** that `makemessages` added to a copied string, and grep the new msgids to confirm none were mis-guessed:
Run: `git diff locale/pl/LC_MESSAGES/django.po | grep -A2 "msgid \"Quiz review\""` (spot-check several).

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages`
Expected: writes `locale/pl/LC_MESSAGES/django.mo` with no errors.

- [ ] **Step 4: Verify rendering (PL)**

Run: `uv run pytest tests/test_review_views.py -q`
Expected: PASS (unchanged — translations don't break the English-substring assertions, which use the default locale).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(review): Polish translations for the quiz review surfaces"
```

---

### Task 14: e2e — teacher review journey (incl. unanswered `[R]`)

**Files:**
- Create: `tests/test_e2e_review.py`

**Interfaces:** none (full-stack browser test). Harness mirrors `tests/test_e2e_results.py`.

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_e2e_review.py
"""Playwright e2e for Phase-3c-i: the teacher quiz-review journey.

A student submits a quiz containing an UNANSWERED [R] question; the teacher
(course owner) opens the review queue, grades the [R] with marks + a comment,
the quiz finalizes; the student then sees the score and the comment on results.
Exercises the subtle unanswered-[R] finalization path with real gestures.
"""
import os
from decimal import Decimal

import pytest

from tests.factories import TEST_PASSWORD, make_pa, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _build_course_with_review_quiz(owner):
    from courses.models import (
        Element, QuestionElement, ExtendedResponseQuestionElement,
    )
    from tests.factories import ContentNodeFactory, CourseFactory, EnrollmentFactory, UserFactory

    course = CourseFactory(owner=owner)
    student = make_verified_user(
        username="e2erevstu", email="e2erevstu@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None, title="Essay quiz")
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss the causes.", required_keywords="", forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW, max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    return course, unit, student


@pytest.mark.django_db(transaction=True)
def test_teacher_reviews_unanswered_review_question(page, live_server, client):
    # Owner is a Platform Admin (so make_pa wires the role); reuse for course ownership.
    owner = make_pa(client, "e2erevowner")
    course, unit, student = _build_course_with_review_quiz(owner)

    # 1) Student opens the quiz and finishes WITHOUT answering the [R] question.
    _login(page, live_server, "e2erevstu")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    page.wait_for_selector("[data-question]")
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)

    # 2) Teacher logs in, opens the review queue, opens the submission.
    from courses.models import QuizSubmission
    sub = QuizSubmission.objects.get(student=student, unit=unit)
    _login(page, live_server, "e2erevowner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review-queue/")
    assert "Essay quiz" in page.content()
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review/{sub.pk}/")

    # 3) Grade the unanswered [R]: enter marks + a comment, save.
    page.locator("input[name='earned_marks']").fill("4")
    page.locator("textarea[name='feedback']").fill("Solid, expand the second point.")
    page.locator("button[type='submit']").click()
    page.wait_for_url(f"**/review/{sub.pk}/")

    # 4) Student sees the score + comment on their results page.
    _login(page, live_server, "e2erevstu")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/results/")
    body = page.content()
    assert "Solid, expand the second point." in body
```

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_review.py -m e2e -v`
Expected: PASS (a Playwright browser drives the real click/submit path; no `page.evaluate` shortcuts). If the quiz-taking finish selector differs, align it with `tests/test_e2e_quiz.py`.

- [ ] **Step 3: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tests/test_e2e_review.py
git commit -m "test(review): e2e teacher review journey incl unanswered [R]"
```

---

## Final verification

- [ ] Run the full suite: `uv run pytest -q` (expect all green, including pre-3c regression).
- [ ] Run e2e: `uv run pytest -m e2e -q`.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` both clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` reports no missing migrations.
- [ ] `uv run python manage.py migrate` + a manual smoke: a course owner force-submits an in-progress quiz, grades its `[R]`, the student's results page shows the unfolded score and comment.
