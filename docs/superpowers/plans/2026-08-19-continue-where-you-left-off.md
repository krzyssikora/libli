# Continue where you left off — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resume card at the top of the student course-outline page that points at the one unit the student should open next.

**Architecture:** One new pure function `build_resume(course, user, tree)` in `courses/rollups.py` consumes the outline tree `course_outline` already builds (zero extra tree queries) and runs a 6-step ordered algorithm over five recency sources. The view calls it behind an enrolled-only gate and passes the result to a new `_resume_card.html` partial. No model, no migration, no endpoint, no JavaScript.

**Tech Stack:** Django 5, PostgreSQL, pytest + pytest-django, factory_boy, freezegun, BeautifulSoup, Playwright (not needed here), Django templates, token-driven CSS.

**Spec:** `docs/superpowers/specs/2026-08-19-continue-where-you-left-off-design.md`

## Global Constraints

- **No migration.** `manage.py makemigrations --check` must stay clean. No model field is added or changed.
- **Warm-path query budget: exactly 4** queries inside `build_resume`. Cold path: 5 or 6. The view adds 1 (`is_enrolled`).
- **Four** new translatable strings, no more: `"Pick up where you left off"`, `"Up next"`, `"Still to do"`, `"Start the course"`.
- **Normative DOM contract** (four sites depend on it — template, CSS, marker tests, render tests):
  | Element | Tag + class |
  |---|---|
  | wrapping link | `a.resume` |
  | eyebrow | `span.resume__eyebrow` |
  | ancestor path container | `span.resume__path` |
  | one ancestor label | `span.resume__crumb` |
  | unit title | `span.resume__title` |
- **Every test is written failing-first and falsified** against the mutant named in its task. A test that cannot go RED does not ship. Where a task says a fixture detail is load-bearing, it is because the obvious fixture makes the test vacuous.
- **`translation.override` must NOT be used** for client-render language tests — `core/middleware.py::SessionLocaleMiddleware.process_request` re-activates per request and discards it. Use `session["_language"] = "pl"; session.save()` plus `HTTP_ACCEPT_LANGUAGE="pl"`.
- **Ties need `freeze_time`.** `updated_at`, `updated`, `last_attempt_at` and `completed_at` are all stamped Python-side; writes in one transaction differ by microseconds and produce no tie.
- **Test DB:** the worktree `.env` already points `TEST_DATABASE_URL` at `libli_resume`. Start the test-DB container before any pytest run. Run pytest via `uv run`.

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/rollups.py` | **Modify.** New `build_resume` beside `build_unit_nav`. All five queries and the 6-step algorithm live here and nowhere else. |
| `courses/views.py` | **Modify, two functions.** `course_outline`: one call + one context key. `progress_reset`: one stale comment clause (Task 10). |
| `templates/courses/_resume_card.html` | **Create.** The card's entire markup. |
| `templates/courses/outline.html` | **Modify.** One `{% include %}` line. |
| `core/static/core/css/app.css` | **Modify.** A `.resume` block in the existing "Course outline (syllabus)" section. |
| `locale/*/LC_MESSAGES/django.po` + `.mo` | **Modify.** Four strings. |
| `tests/test_resume_target.py` | **Create.** All `build_resume` unit tests, the query-count guards, and the inert-stamping A/B. |
| `tests/test_courses_views.py` | **Modify.** Render tests (link target, four eyebrows, enrolled gate, tag independence, `lang`). |
| `tests/test_title_math_markers.py` | **Modify.** Marker coverage for `span.resume__title` and `span.resume__crumb`. |

---

### Task 1: `build_resume` skeleton — steps 1, 5, 6 and source E

Establishes the function, its return shape, and the three paths that need no in-flight or completion candidate. `flight` and `done` are explicitly `None` here; Tasks 2 and 3 fill them in.

**Files:**
- Modify: `courses/rollups.py` (add after `build_unit_nav`)
- Test: `tests/test_resume_target.py` (create)

**Interfaces:**
- Consumes: `_flatten_unit_leaves(tree)` and `build_outline(course, user, drafts=...)`, both already in `courses/rollups.py`.
- Produces: `build_resume(course, user, tree) -> dict | None` with keys `"node"` (a `ContentNode`), `"state"` (one of `"resume" | "next" | "gap" | "start"`), `"ancestors"` (a list of `ContentNode`, filled in Task 4 — return `[]` here).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resume_target.py`:

```python
import pytest

from courses.models import QuizSubmission
from courses.rollups import build_outline
from courses.rollups import build_resume
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


def _tree(course, user):
    return build_outline(course, user, drafts="hide")


def _resume(course, user):
    return build_resume(course, user, _tree(course, user))


def _course_with_units(n, **kw):
    """A course with n published lesson units at root level, in order."""
    course = CourseFactory(**kw)
    units = [
        ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=i)
        for i in range(n)
    ]
    return course, units


@pytest.mark.django_db
def test_no_visible_units_returns_none():
    course = CourseFactory()
    user = make_verified_user(username="s1", email="s1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_no_rows_at_all_starts_the_course():
    course, units = _course_with_units(3)
    user = make_verified_user(username="s2", email="s2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert r["state"] == "start"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_history_only_on_an_unpublished_unit_is_next_not_start():
    """Step 5. The student HAS history, so `start` would be a lie -- but every row
    sits on a unit that is no longer visible, so sources A-D see nothing.

    Unpublishing is the ONLY mechanism that reaches step 5: the unit FKs are
    CASCADE, so DELETING a unit destroys its rows and correctly lands on step 6.
    """
    course, units = _course_with_units(3)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="s3", email="s3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=ghost)
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_history_only_on_an_unpublished_quiz_also_reaches_step_5():
    """Source E's SECOND probe. A student whose only artefact is a QuizSubmission
    must not be told to start the course."""
    course, units = _course_with_units(3)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", order=9, published=False
    )
    user = make_verified_user(username="s4", email="s4@test.example.com")
    EnrollmentFactory(student=user, course=course)
    QuizSubmissionFactory(
        student=user, unit=ghost, status=QuizSubmission.Status.IN_PROGRESS
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_returned_node_is_a_contentnode_not_a_leaf_dict():
    """A leaf dict would blow up at {% url %} with NoReverseMatch (<int:node_pk>),
    after quietly rendering no kind chip and sending every link to lesson_unit."""
    from courses.models import ContentNode

    course, units = _course_with_units(2)
    user = make_verified_user(username="s5", email="s5@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert isinstance(r["node"], ContentNode)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: FAIL — `ImportError: cannot import name 'build_resume' from 'courses.rollups'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `courses/rollups.py`, after `build_unit_nav`:

```python
def build_resume(course, user, tree):
    """The outline resume card's target, or None when there is nothing to resume.

    Consumes the caller's ALREADY-BUILT build_outline tree -- never rebuilds it, so
    the card costs no extra tree queries. Returns
    {"node": ContentNode, "state": str, "ancestors": [ContentNode]} or None.

    `node` is the ContentNode (leaf["node"]), NEVER the build_outline leaf dict:
    a dict reaches {% url ... node_pk=resume.node.pk %} as "" against urls.py's
    <int:node_pk> and raises NoReverseMatch, 500-ing the whole outline.

    The 6 steps are ordered and their precedence is load-bearing; see the spec's
    "Definition of the target".
    """
    leaves = _flatten_unit_leaves(tree)
    open_leaves = [d for d in leaves if not d["completed"]]
    # STEP 1, first so no later step can index an empty candidate set. Covers both
    # "course has no visible units" and "student completed everything".
    if not open_leaves:
        return None

    open_pks = [d["node"].pk for d in open_leaves]
    leaf_pks = [d["node"].pk for d in leaves]

    flight, ts_f = None, None  # Task 2 fills these in (sources A/B/C)
    done, ts_d = None, None  # Task 3 fills these in (source D)

    # STEP 5: the student has history, but all of it is on units that are no longer
    # visible. Deliberately UNFILTERED by open/leaves and by status -- that is the
    # whole point: these two probes are the only thing that can see such rows, and
    # they are what stops step 6 lying to the student. Lazy: only reached when
    # steps 3-4 both fail. `or` short-circuits, so this costs 1 query or 2.
    has_history = (
        UnitProgress.objects.filter(student=user, unit__course=course).exists()
        or QuizSubmission.objects.filter(student=user, unit__course=course).exists()
    )
    if has_history:
        return {"node": open_leaves[0]["node"], "state": "next", "ancestors": []}

    # STEP 6: genuinely nothing.
    return {"node": open_leaves[0]["node"], "state": "start", "ancestors": []}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Falsify — the step-5/step-6 distinction**

Temporarily replace the `has_history` expression with `False` **by hand** (do not `git checkout`; see the repo's reverting-a-mutant hazard). Re-run.

Expected: `test_history_only_on_an_unpublished_unit_is_next_not_start` and `test_history_only_on_an_unpublished_quiz_also_reaches_step_5` both FAIL (`"start" != "next"`). Then drop only the `QuizSubmission` arm and confirm the quiz test alone fails. Restore both by hand and re-run to green.

- [ ] **Step 6: Commit**

```bash
git add courses/rollups.py tests/test_resume_target.py
git commit -m "feat(resume): build_resume skeleton with the no-live-work paths"
```

---

### Task 2: Sources A, B, C and step 3 (the in-flight candidate)

**Files:**
- Modify: `courses/rollups.py` (`build_resume`)
- Test: `tests/test_resume_target.py`

**Interfaces:**
- Consumes: `build_resume`'s `open_pks` local from Task 1.
- Produces: `flight` (a `ContentNode` or `None`) and `ts_f` (that candidate's timestamp) consumed by Task 3's step 3 comparison.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resume_target.py`:

```python
from datetime import timedelta

from django.utils import timezone

from courses.models import Element
from courses.models import QuestionResponse
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress


def _backdate_progress(unit, user, when):
    """updated_at is auto_now, so save() cannot backdate it -- only .update() can."""
    UnitProgress.objects.filter(student=user, unit=unit).update(updated_at=when)


def _answered_question(unit, submission, when):
    """A QuestionResponse with last_attempt_at set -- source C's only input."""
    q = ShortTextQuestionElement.objects.create(stem="q", accepted_answers="a")
    el = Element.objects.create(unit=unit, content_object=q)
    return QuestionResponse.objects.create(
        submission=submission, element=el, last_attempt_at=when
    )


@pytest.mark.django_db
def test_in_flight_lesson_is_the_resume_target():
    course, units = _course_with_units(3)
    user = make_verified_user(username="a1", email="a1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=units[1])
    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[1].pk


@pytest.mark.django_db
def test_answered_quiz_beats_a_later_opened_lesson():
    """SOURCE C EXISTS FOR THIS TEST. QuizSubmission.updated is auto_now and the
    answer path (views.py:1614-1665) never saves the submission -- so B measures
    "opened", not "worked". Drop C and this student is resumed to the lesson they
    glanced at afterwards instead of the quiz they spent an hour on.
    """
    course = CourseFactory()
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=0)
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=1)
    user = make_verified_user(username="a2", email="a2@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
    )
    QuizSubmission.objects.filter(pk=sub.pk).update(updated=now - timedelta(hours=3))
    # The lesson was OPENED after the quiz was opened...
    UnitProgressFactory(student=user, unit=lesson)
    _backdate_progress(lesson, user, now - timedelta(hours=2))
    # ...but the quiz was ANSWERED most recently.
    _answered_question(quiz, sub, now - timedelta(minutes=5))

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_opened_but_unanswered_quiz_is_the_target():
    """Source B's own reason to exist: a quiz opened and not yet answered has no
    QuestionResponse, so source C cannot see it. Needs an OLDER rival, else the
    mutant falls through to step 5 and may return the same node anyway."""
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="a3", email="a3@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    UnitProgressFactory(student=user, unit=lesson)
    _backdate_progress(lesson, user, now - timedelta(hours=2))
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
    )
    QuizSubmission.objects.filter(pk=sub.pk).update(updated=now - timedelta(minutes=1))

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_submitted_quiz_with_no_progress_row_is_not_the_target():
    """THE seed_demo_course.py SHAPE. That command calls finalize_submission at
    lines 346 and 414 and has ZERO UnitProgress references, so a SUBMITTED
    submission whose unit is still in open_pks is a state this repo really ships.

    The competing OLDER lesson is load-bearing: without it the correct build
    reaches step 5 and returns open[0] -- possibly the quiz itself -- so the
    assertion would fail on a CORRECT build.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="a4", email="a4@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    UnitProgressFactory(student=user, unit=lesson)
    _backdate_progress(lesson, user, now - timedelta(hours=2))
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )
    QuizSubmission.objects.filter(pk=sub.pk).update(updated=now - timedelta(minutes=2))
    # Also give it an answered question, so source C's filter is exercised too.
    _answered_question(quiz, sub, now - timedelta(minutes=1))

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == lesson.pk


@pytest.mark.django_db
def test_invisible_newer_row_does_not_discard_the_visible_candidate():
    """Membership must be a FILTER INSIDE the query, not a post-check on LIMIT 1.
    Unit 30's row is strictly NEWER -- that is what makes the mutant fire. With a
    post-check, source A returns unit 30, fails the membership test, yields
    nothing, and the student is thrown back to unit 1.
    """
    course, units = _course_with_units(5)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="a5", email="a5@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    UnitProgressFactory(student=user, unit=units[2])
    _backdate_progress(units[2], user, now - timedelta(hours=1))
    UnitProgressFactory(student=user, unit=ghost)
    _backdate_progress(ghost, user, now)

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[2].pk
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_resume_target.py -v -k "in_flight or answered_quiz or opened_but or submitted_quiz or invisible_newer"
```

Expected: all 5 FAIL — `flight` is hardcoded `None`, so every one lands on `start`/`next`.

- [ ] **Step 3: Write the implementation**

In `build_resume`, replace the `flight, ts_f = None, None` placeholder with:

```python
    # SOURCES A/B/C -- the in-flight candidate. Membership is a filter INSIDE each
    # query (unit_id__in=open_pks), never a post-check on the LIMIT 1 result: each
    # source returns one row, so one row for a since-unpublished unit at the head of
    # the ordering would discard every older still-valid candidate behind it. It
    # also removes the join to ContentNode -- open_pks is already course-scoped and
    # visibility-filtered.
    #
    # Each ordering carries a deterministic secondary key. For A/B the (student,
    # unit) unique constraint makes -unit_id pin the row; for C it pins the UNIT,
    # which is all the algorithm needs.
    #
    # A -- lesson work. updated_at is auto_now: first open (views.py:511), every
    # `seen` batch, every practice-state write.
    # NOTE: completed=False here is DELIBERATE REDUNDANCY and is NOT falsifiable --
    # open_pks is derived from exactly this filter (build_outline's completed set,
    # rollups.py:244-250, leaf key at :265), so no mutant of it can go RED. It
    # states the intent locally; do not spend a falsification round on it.
    a = (
        UnitProgress.objects.filter(
            student=user, unit_id__in=open_pks, completed=False
        )
        .order_by("-updated_at", "-unit_id")
        .values_list("unit_id", "updated_at")
        .first()
    )
    # B -- WHEN THE QUIZ WAS OPENED, and nothing more. QuizSubmission.updated is
    # auto_now (models.py:3008) and the answer path (views.py:1614-1665) saves the
    # QuestionResponse and creates an Attempt but NEVER saves the submission, so for
    # an IN_PROGRESS row updated == created in practice.
    # status=IN_PROGRESS here IS load-bearing and IS tested: closing a submission
    # normally writes UnitProgress.completed, but seed_demo_course.py:346/414
    # finalizes without any UnitProgress row, so a SUBMITTED submission's unit can
    # still be in open_pks.
    b = (
        QuizSubmission.objects.filter(
            student=user,
            unit_id__in=open_pks,
            status=QuizSubmission.Status.IN_PROGRESS,
        )
        .order_by("-updated", "-unit_id")
        .values_list("unit_id", "updated")
        .first()
    )
    # C -- ACTUAL quiz answering, and the only source that can see it. The
    # values_list projection is NORMATIVE: C's unit_id lives on the joined
    # QuizSubmission, so `.first()` then `row.submission.unit_id` would cost a
    # SECOND query and silently break the 4-query budget.
    # last_attempt_at__isnull=False is required: Postgres sorts NULLs FIRST under
    # DESC, so without it a null row wins the LIMIT 1 and the step-3 comparison
    # raises TypeError against None.
    c = (
        QuestionResponse.objects.filter(
            submission__student=user,
            submission__unit_id__in=open_pks,
            submission__status=QuizSubmission.Status.IN_PROGRESS,
            last_attempt_at__isnull=False,
        )
        .order_by("-last_attempt_at", "-submission__unit_id")
        .values_list("submission__unit_id", "last_attempt_at")
        .first()
    )

    # Assembly order A, B, C is NORMATIVE. max() returns the FIRST maximal element,
    # so with source_rank dropped an A-then-C order yields A while the correct build
    # yields C -- that ordering is what makes the rank mutant killable. Assembling
    # [C, B, A] would make the mutant coincidentally right.
    by_pk = {d["node"].pk: d["node"] for d in open_leaves}
    candidates = [
        (row[1], rank, row[0]) for rank, row in enumerate((a, b, c)) if row is not None
    ]
    if candidates:
        ts_f, _rank, flight_pk = max(candidates, key=lambda t: (t[0], t[1]))
        flight = by_pk[flight_pk]
```

Also add the step-3 return, immediately after that block:

```python
    # STEP 3. The ts comparison is ESSENTIAL: views.py:511 mints a UnitProgress row
    # on EVERY enrolled lesson GET, so without it one stray click a year ago pins
    # the card to that unit forever. >= (not >) keeps an in-flight unit winning a
    # tie -- the friendlier reading of "where you left off".
    if flight is not None and (done is None or ts_f >= ts_d):
        return {"node": flight, "state": "resume", "ancestors": []}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Falsify — three mutants, by hand**

1. Delete source **C** from the `candidates` tuple. Expected: `test_answered_quiz_beats_a_later_opened_lesson` FAILS.
2. Restore C; delete source **B**. Expected: `test_opened_but_unanswered_quiz_is_the_target` FAILS.
3. Restore B; drop `status=IN_PROGRESS` from **B**, then (separately) from **C**. Expected: `test_submitted_quiz_with_no_progress_row_is_not_the_target` FAILS both times.
4. Restore; change source A's filter to `unit__course=course` and add a post-`.first()` membership check. Expected: `test_invisible_newer_row_does_not_discard_the_visible_candidate` FAILS.

Restore each by hand and re-run to green.

- [ ] **Step 6: Commit**

```bash
git add courses/rollups.py tests/test_resume_target.py
git commit -m "feat(resume): in-flight sources A/B/C and the step-3 comparison"
```

---

### Task 3: Source D and step 4 (the completion anchor, `next` and `gap`)

**Files:**
- Modify: `courses/rollups.py` (`build_resume`)
- Test: `tests/test_resume_target.py`

**Interfaces:**
- Consumes: `flight` / `ts_f` from Task 2; `leaf_pks`, `open_leaves`, `leaves` from Task 1.
- Produces: the `"next"` and `"gap"` states.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resume_target.py`:

```python
from freezegun import freeze_time


def _complete(unit, user, when):
    """A completed UnitProgress with completed_at pinned. save() stamps
    completed_at itself, so freeze the clock rather than trying to backdate."""
    with freeze_time(when):
        UnitProgressFactory(student=user, unit=unit, completed=True)


@pytest.mark.django_db
def test_most_recent_unit_completed_advances_to_the_next_open_unit():
    course, units = _course_with_units(4)
    user = make_verified_user(username="d1", email="d1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, "2026-08-01 10:00:00")
    _complete(units[1], user, "2026-08-02 10:00:00")
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[2].pk


@pytest.mark.django_db
def test_stray_visit_does_not_pin_the_card_forever():
    """THE bug the ts_f >= ts_d comparison exists to stop. Opening unit 0 once
    leaves a permanent completed=False row (views.py:511 get_or_create on every
    enrolled lesson GET). Without the comparison it outranks every completion
    made since and the card says "Pick up where you left off - unit 0" forever.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d2", email="d2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=units[0])
    _backdate_progress(units[0], user, timezone.now() - timedelta(days=365))
    _complete(units[1], user, "2026-08-02 10:00:00")
    _complete(units[2], user, "2026-08-03 10:00:00")
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[3].pk


@pytest.mark.django_db
def test_exact_tie_between_in_flight_and_completion_resumes():
    """The >= arm. Without a FORCED tie this test is vacuous: ts_f > ts_d passes on
    BOTH builds and ts_f < ts_d fails on the correct one. All four timestamps are
    stamped Python-side, so only freeze_time (or .update) can make them equal."""
    course, units = _course_with_units(4)
    user = make_verified_user(username="d3", email="d3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    moment = "2026-08-05 12:00:00"
    _complete(units[0], user, moment)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=units[2])

    row_f = UnitProgress.objects.get(student=user, unit=units[2])
    row_d = UnitProgress.objects.get(student=user, unit=units[0])
    assert row_f.updated_at == row_d.completed_at  # the tie is real

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[2].pk


@pytest.mark.django_db
def test_reseeing_a_finished_unit_does_not_rewind_the_anchor():
    """THE ONLY scenario that separates completed_at from updated_at. views.py::seen
    calls progress.save() UNCONDITIONALLY (line 924), including for an already
    completed unit -- so re-reading unit 0 re-dates its updated_at while
    completed_at stays put. Anchor on updated_at and the mutant answers units[1].

    Do NOT try to build this with force_submit_quiz: it is guarded by
    `if not progress.completed`, so it can never re-date a completed row, and on
    the path where it does save, save() stamps completed_at in the same instant.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d4", email="d4@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, "2026-08-01 10:00:00")
    _complete(units[2], user, "2026-08-02 10:00:00")
    # Re-read unit 0 today: seen's unconditional save bumps updated_at only.
    UnitProgress.objects.filter(student=user, unit=units[0]).update(
        updated_at=timezone.now()
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[3].pk


@pytest.mark.django_db
def test_finished_the_last_unit_wraps_back_to_the_earliest_gap():
    course, units = _course_with_units(4)
    user = make_verified_user(username="d5", email="d5@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, "2026-08-01 10:00:00")
    _complete(units[2], user, "2026-08-02 10:00:00")
    _complete(units[3], user, "2026-08-03 10:00:00")
    r = _resume(course, user)
    assert r["state"] == "gap"
    assert r["node"].pk == units[1].pk


@pytest.mark.django_db
def test_all_units_completed_returns_none():
    """Step 1. Deleting it does NOT "return the last unit" -- flight is None, done
    is the last completed leaf, forward is None, and step 4 indexes an empty list,
    so the symptom is the same IndexError as the no-visible-units case."""
    course, units = _course_with_units(2)
    user = make_verified_user(username="d6", email="d6@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, "2026-08-01 10:00:00")
    _complete(units[1], user, "2026-08-02 10:00:00")
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_completed_quiz_that_is_the_last_open_unit_yields_none():
    """Mutant: treating unit_type == quiz as never-complete -> `gap` on the quiz.
    The fixture MUST make the quiz the last remaining unit. The obvious
    "quiz mid-course, assert we advance past it" fixture is VACUOUS: under that
    mutant the quiz re-enters `open`, but A still excludes it (completed=False) and
    B/C still exclude it (SUBMITTED), so flight stays None, done is the quiz, and
    forward is the same unit the correct build returns.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="d7", email="d7@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(lesson, user, "2026-08-01 10:00:00")
    _complete(quiz, user, "2026-08-02 10:00:00")
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_additional_lesson_still_counts_as_a_target():
    """`open` is every uncompleted VISIBLE unit -- the rule deliberately does not
    inherit build_outline's required/additional distinction."""
    course = CourseFactory()
    required = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=0, obligatory=True
    )
    extra = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=1, obligatory=False
    )
    user = make_verified_user(username="d8", email="d8@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(required, user, "2026-08-01 10:00:00")
    r = _resume(course, user)
    assert r["node"].pk == extra.pk
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_resume_target.py -v -k "most_recent or stray_visit or exact_tie or reseeing or wraps_back or all_units or completed_quiz_that or additional_lesson"
```

Expected: FAIL — `done` is still hardcoded `None`, so these land on `start`/`resume`.

- [ ] **Step 3: Write the implementation**

Replace the `done, ts_d = None, None` placeholder with source D (it must be computed **before** the step-3 comparison):

```python
    # SOURCE D -- the completion anchor. completed_at, NEVER updated_at:
    # completed_at is stamped exactly once in UnitProgress.save() when `completed`
    # first flips and is never re-stamped, whereas views.py::seen calls
    # progress.save() UNCONDITIONALLY on every batch (line 924) including for an
    # already-completed unit -- so simply re-reading a finished unit re-dates
    # updated_at. Ordering on updated_at would rewind the student to just after
    # whichever old unit they last skimmed.
    # completed_at__isnull=False guards the NULLs-first DESC ordering (see source C).
    d_row = (
        UnitProgress.objects.filter(
            student=user,
            unit_id__in=leaf_pks,
            completed=True,
            completed_at__isnull=False,
        )
        .order_by("-completed_at", "-unit_id")
        .values_list("unit_id", "completed_at")
        .first()
    )
    if d_row is not None:
        done, ts_d = d_row
```

Note `done` here is a **pk**, not a node — step 4 needs its outline position. After the step-3 return, add step 4:

```python
    # STEP 4. `done` is a pk; its POSITION in the outline is what matters.
    if done is not None:
        idx = next(
            (i for i, leaf in enumerate(leaves) if leaf["node"].pk == done), None
        )
        forward = next(
            (
                leaf
                for i, leaf in enumerate(leaves)
                if i > idx and not leaf["completed"]
            ),
            None,
        )
        if forward is not None:
            return {"node": forward["node"], "state": "next", "ancestors": []}
        # The wrap-around: they finished the last unit but skipped something. A card
        # that vanishes while unfinished units remain is worse than one pointing
        # back. Its own state, because "Up next" is false about an EARLIER unit.
        return {"node": open_leaves[0]["node"], "state": "gap", "ancestors": []}
```

- [ ] **Step 4: Run the full file**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: 18 passed.

- [ ] **Step 5: Falsify — by hand**

1. Change source D's ordering to `("-updated_at", "-unit_id")`. Expected: `test_reseeing_a_finished_unit_does_not_rewind_the_anchor` FAILS (returns `units[1]`).
2. Restore; change step 3's `ts_f >= ts_d` to `ts_f > ts_d`. Expected: `test_exact_tie_between_in_flight_and_completion_resumes` FAILS.
3. Restore; drop the `done is None or ts_f >= ts_d` condition entirely (i.e. `if flight is not None:`). Expected: `test_stray_visit_does_not_pin_the_card_forever` FAILS.
4. Restore; replace the `gap` return with `return None`. Expected: `test_finished_the_last_unit_wraps_back_to_the_earliest_gap` FAILS.
5. Restore; delete step 1's `if not open_leaves: return None`. Expected: `test_all_units_completed_returns_none` and `test_no_visible_units_returns_none` FAIL with `IndexError`.

Restore each by hand; re-run to green.

- [ ] **Step 6: Commit**

```bash
git add courses/rollups.py tests/test_resume_target.py
git commit -m "feat(resume): completion anchor and the next/gap branches"
```

---

### Task 4: Ancestors, and the inert-stamping guard

**Files:**
- Modify: `courses/rollups.py` (`build_resume`)
- Test: `tests/test_resume_target.py`

**Interfaces:**
- Consumes: `_stamp_current_chain(tree, pk)` and `_current_ancestors(tree)`, both already in `courses/rollups.py`.
- Produces: a populated `"ancestors"` list on every returned dict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resume_target.py`:

```python
from django.template.loader import render_to_string

from courses.rollups import _stamp_current_chain


@pytest.mark.django_db
def test_ancestors_are_the_root_to_parent_chain_excluding_the_unit():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, order=0)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, order=0
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, order=0
    )
    user = make_verified_user(username="n1", email="n1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert [a.pk for a in r["ancestors"]] == [part.pk, chapter.pk]
    assert unit.pk not in [a.pk for a in r["ancestors"]]


@pytest.mark.django_db
def test_root_level_unit_has_no_ancestors():
    """_current_ancestors legitimately returns [] for a depth-1 unit."""
    course, units = _course_with_units(2)
    user = make_verified_user(username="n2", email="n2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    assert _resume(course, user)["ancestors"] == []


@pytest.mark.django_db
def test_stamping_the_tree_does_not_change_the_outline_html():
    """build_resume mutates the tree the outline template then renders, adding
    contains_current to every dict. That key is read ONLY by _unit_tree_node.html
    (the unit-page rail); _outline_node.html never reads it.

    TREE SHAPE IS LOAD-BEARING: ` open` lives in the container arm, which renders
    only for a non-unit node WITH children. Stamp a root-level unit and no stamped
    dict reaches that branch, so the mutant produces identical output and the test
    is GREEN on a broken build. Hence the unit is nested under a surviving chapter.

    Mutant: add `{% if item.contains_current %} open{% endif %}` to the <details>
    in _outline_node.html.
    """
    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", unit_type=None, order=0)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, order=0
    )
    user = make_verified_user(username="n3", email="n3@test.example.com")
    EnrollmentFactory(student=user, course=course)

    def _render(tree):
        return "".join(
            render_to_string(
                "courses/_outline_node.html",
                {
                    "item": item,
                    "course": course,
                    "note_counts": {},
                    "active_tag_ids": [],
                },
            )
            for item in tree
        )

    tree = _tree(course, user)
    before = _render(tree)
    _stamp_current_chain(tree, unit.pk)
    after = _render(tree)
    assert before == after
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_resume_target.py -v -k "ancestors or root_level or stamping"
```

Expected: the two ancestor tests FAIL (`[] != [part.pk, chapter.pk]`). `test_stamping_...` should already PASS — that is expected; it is a **regression guard**, and its falsification in Step 5 is what proves it works.

- [ ] **Step 3: Write the implementation**

Replace each of the five `"ancestors": []` literals with a single helper call. Add this just before the first `return` that yields a node:

```python
    def _with_ancestors(node, state):
        # Pure dict traversal over the already-materialised tree -- NO queries. Reuses
        # the unit-page breadcrumb machinery rather than adding a third ancestor walk:
        # views_manage.py::_unit_ancestors is already a documented deliberate twin of
        # _current_ancestors, and a third copy would be one too many.
        # _current_ancestors reads contains_current directly and raises KeyError on an
        # unstamped tree by design, so the stamp call must immediately precede it.
        _stamp_current_chain(tree, node.pk)
        return {"node": node, "state": state, "ancestors": _current_ancestors(tree)}
```

Then rewrite the five returns as `return _with_ancestors(flight, "resume")`, `return _with_ancestors(forward["node"], "next")`, `return _with_ancestors(open_leaves[0]["node"], "gap")`, `return _with_ancestors(open_leaves[0]["node"], "next")`, and `return _with_ancestors(open_leaves[0]["node"], "start")`.

- [ ] **Step 4: Run the full file**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: 21 passed.

- [ ] **Step 5: Falsify**

1. Change `_with_ancestors` to append the node itself (`_current_ancestors(tree) + [node]`). Expected: `test_ancestors_are_the_root_to_parent_chain_excluding_the_unit` FAILS.
2. Restore; **temporarily** add `{% if item.contains_current %} open{% endif %}` to the `<details class="outline-node__group"` tag in `templates/courses/_outline_node.html`. Expected: `test_stamping_the_tree_does_not_change_the_outline_html` FAILS. Remove it by hand.

- [ ] **Step 6: Commit**

```bash
git add courses/rollups.py tests/test_resume_target.py
git commit -m "feat(resume): ancestor chain, with the inert-stamping guard"
```

---

### Task 5: Query-count guards

**Files:**
- Test: `tests/test_resume_target.py`

**Interfaces:**
- Consumes: `build_resume` as completed in Task 4. No production change unless a count is wrong.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resume_target.py`:

```python
@pytest.mark.django_db
def test_warm_path_costs_exactly_four_queries(django_assert_num_queries):
    """FIXTURE IS LOAD-BEARING. The student needs a live UnitProgress AND an
    IN_PROGRESS QuizSubmission on an open quiz carrying a QuestionResponse with
    last_attempt_at set -- so source C actually returns a row. With a lone
    UnitProgress, C's .first() returns None, the `row.submission.unit_id`
    dereference mutant never fires, and the count stays 4 on a broken build.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="q1", email="q1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=lesson)
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
    )
    _answered_question(quiz, sub, timezone.now())

    tree = _tree(course, user)  # built OUTSIDE the assertion
    with django_assert_num_queries(4):
        build_resume(course, user, tree)


@pytest.mark.django_db
def test_cold_path_with_no_rows_costs_six_queries(django_assert_num_queries):
    """Both source-E probes run. (A `Q(...) | Q(...)` collapse is NOT a
    constructible mutant -- the probes hit two different models.)"""
    course, units = _course_with_units(2)
    user = make_verified_user(username="q2", email="q2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    tree = _tree(course, user)
    with django_assert_num_queries(6):
        build_resume(course, user, tree)


@pytest.mark.django_db
def test_cold_path_short_circuits_after_the_first_probe(django_assert_num_queries):
    """source E's `or` short-circuits: history on a UnitProgress costs ONE probe."""
    course, units = _course_with_units(2)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="q3", email="q3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=ghost)
    tree = _tree(course, user)
    with django_assert_num_queries(5):
        build_resume(course, user, tree)
```

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/test_resume_target.py -v -k "warm_path or cold_path"
```

Expected: PASS. If any fails, the count is genuinely wrong — fix `build_resume`, do not adjust the number to match.

- [ ] **Step 3: Falsify**

1. In source C, replace the `values_list(...)` projection with `.first()` + `row.submission.unit_id`. Expected: `test_warm_path_costs_exactly_four_queries` FAILS with 5.
2. Restore; make source E eager (assign both `.exists()` calls to locals before the `or`). Expected: **`test_warm_path...` FAILS with 6** — the eager mutant is caught on the *warm* path, not the cold one, where an eager E costs the same 2 probes either way.
3. Restore; drop the `QuizSubmission` arm of source E. Expected: `test_cold_path_with_no_rows_costs_six_queries` FAILS with 5.

Restore each by hand.

- [ ] **Step 4: Commit**

```bash
git add tests/test_resume_target.py
git commit -m "test(resume): pin the warm and cold query budgets"
```

---

### Task 6: Wire `build_resume` into `course_outline`

**Files:**
- Modify: `courses/views.py` (`course_outline`, around lines 644-677)
- Test: `tests/test_courses_views.py`

**Interfaces:**
- Consumes: `build_resume` (Task 4), `is_enrolled` from `courses.access`.
- Produces: a `resume` template context variable — `dict` or `None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_courses_views.py` (match the file's existing import style):

```python
@pytest.mark.django_db
def test_outline_passes_a_resume_target_for_an_enrolled_student(client):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "res1")
    course = CourseFactory(slug="res-course")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    EnrollmentFactory(student=user, course=course)
    r = client.get(reverse("courses:course_outline", kwargs={"slug": "res-course"}))
    assert r.status_code == 200
    assert r.context["resume"]["node"].pk == unit.pk


@pytest.mark.django_db
def test_outline_offers_no_resume_target_to_a_non_enrolled_viewer(client):
    """can_access_course also admits authors/teachers/staff previewing a course they
    are not taking; a "Start the course" CTA would be noise for them. This is also
    the guard that pins the WIRING -- calling build_resume unconditionally.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_login

    user = make_login(client, "res2")
    course = CourseFactory(slug="res-course-2", owner=user)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    r = client.get(reverse("courses:course_outline", kwargs={"slug": "res-course-2"}))
    assert r.status_code == 200
    assert r.context["resume"] is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_courses_views.py -v -k "resume_target"
```

Expected: FAIL — `KeyError: 'resume'`.

- [ ] **Step 3: Implement**

In `courses/views.py`, add to the imports if absent: `from courses.rollups import build_resume` and confirm `is_enrolled` is imported from `courses.access`. Then in `course_outline`, after the `has_math = tree_titles_have_math(outline)` line:

```python
    # Enrolled-only: can_access_course also admits authors, teachers and staff
    # previewing a course they are not taking, and a "Start the course" CTA would be
    # noise for them. Mirrors the `seen` write route, which is enrolled-only by
    # design. Runs AFTER outline_with_tags, but the target is deliberately
    # INDEPENDENT of the active tag filter: outline_with_tags annotates without
    # pruning, and the filter hides rows rather than restricting scope, so filtering
    # to one tag must not change where "Continue" sends you.
    resume = (
        build_resume(course, request.user, outline)
        if is_enrolled(request.user, course)
        else None
    )
```

And add to the `render(...)` context dict — **this second edit is the one that fails silently if forgotten**, because `{% if resume %}` on a missing variable is simply falsy:

```python
            "resume": resume,
```

- [ ] **Step 4: Run**

```bash
uv run pytest tests/test_courses_views.py -v -k "resume_target"
```

Expected: 2 passed.

- [ ] **Step 5: Falsify**

Drop the `if is_enrolled(...) else None` guard (call unconditionally). Expected: `test_outline_offers_no_resume_target_to_a_non_enrolled_viewer` FAILS. Restore by hand.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py tests/test_courses_views.py
git commit -m "feat(resume): wire build_resume into course_outline behind the enrolled gate"
```

---

### Task 7: The card template, the include, and the render tests

**Files:**
- Create: `templates/courses/_resume_card.html`
- Modify: `templates/courses/outline.html`
- Modify: `tests/test_courses_views.py`, `tests/test_title_math_markers.py`

**Interfaces:**
- Consumes: the `resume` context variable (Task 6); `_unit_kind_chip.html`.
- Produces: the DOM contract in Global Constraints.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_courses_views.py`:

```python
def _resume_soup(client, slug):
    from bs4 import BeautifulSoup

    r = client.get(reverse("courses:course_outline", kwargs={"slug": slug}))
    return BeautifulSoup(r.content, "html.parser").select_one("a.resume")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state,expected",
    [
        ("resume", "Pick up where you left off"),
        ("next", "Up next"),
        ("gap", "Still to do"),
        ("start", "Start the course"),
    ],
)
def test_each_state_renders_its_own_eyebrow(client, state, expected, monkeypatch):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, f"eb-{state}")
    course = CourseFactory(slug=f"eb-{state}")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    EnrollmentFactory(student=user, course=course)
    monkeypatch.setattr(
        "courses.views.build_resume",
        lambda c, u, t: {"node": unit, "state": state, "ancestors": []},
    )
    card = _resume_soup(client, f"eb-{state}")
    assert card.select_one("span.resume__eyebrow").get_text(strip=True) == expected


@pytest.mark.django_db
def test_card_links_to_quiz_unit_for_a_quiz_target(client):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "lq")
    course = CourseFactory(slug="lq")
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=0)
    EnrollmentFactory(student=user, course=course)
    card = _resume_soup(client, "lq")
    assert card["href"] == reverse(
        "courses:quiz_unit", kwargs={"slug": "lq", "node_pk": quiz.pk}
    )


@pytest.mark.django_db
def test_card_links_to_lesson_unit_for_a_lesson_target(client):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "ll")
    course = CourseFactory(slug="ll")
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    EnrollmentFactory(student=user, course=course)
    card = _resume_soup(client, "ll")
    assert card["href"] == reverse(
        "courses:lesson_unit", kwargs={"slug": "ll", "node_pk": lesson.pk}
    )


@pytest.mark.django_db
def test_tag_filter_does_not_move_the_resume_target(client):
    """The target is computed independently of the active tag filter. Mutant:
    filtering `leaves` on tag_hidden. The failure would be invisible -- the card
    still renders, just pointing somewhere else."""
    from tags.models import Tag
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "tf")
    course = CourseFactory(slug="tf")
    target = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    other = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=1)
    EnrollmentFactory(student=user, course=course)
    tag = Tag.objects.create(owner=user, course=course, name="t", color="blue")
    tag.units.add(other)

    r = client.get(
        reverse("courses:course_outline", kwargs={"slug": "tf"}), {"tags": tag.pk}
    )
    assert r.context["resume"]["node"].pk == target.pk


@pytest.mark.django_db
def test_eyebrow_carries_the_active_ui_language(client):
    """MUST use the session pattern, NOT translation.override: SessionLocaleMiddleware
    calls translation.activate() on every request and discards an outer override, so
    an override test would render lang="en" and go RED on a CORRECT build. Precedents:
    tests/test_i18n_catalog.py, tests/test_editor_count_i18n.py.

    Read lang off the eyebrow, never off the page -- outline.html already emits
    lang="{{ course.language }}" on <section class="outline">.
    Mutant: dropping {% get_current_language %}, which yields lang="".
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "lang1")
    course = CourseFactory(slug="lang1", language="en")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    EnrollmentFactory(student=user, course=course)
    session = client.session
    session["_language"] = "pl"
    session.save()
    r = client.get(
        reverse("courses:course_outline", kwargs={"slug": "lang1"}),
        HTTP_ACCEPT_LANGUAGE="pl",
    )
    from bs4 import BeautifulSoup

    card = BeautifulSoup(r.content, "html.parser").select_one("a.resume")
    assert card.select_one("span.resume__eyebrow")["lang"] == "pl"
```

And in `tests/test_title_math_markers.py`, add to the outline section (matching that file's `_marked(body, selector)` helper style):

```python
@pytest.mark.django_db
def test_resume_card_title_and_crumbs_are_marked(client):
    """math.js typesets [data-math-title] and nothing else, so an ancestor titled
    with LaTeX would otherwise render its delimiters literally."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "mm")
    course = CourseFactory(slug="mm")
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, order=0, title=r"Rozdz \(x^2\)"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        order=0,
        title=r"Unit \(y\)",
    )
    EnrollmentFactory(student=user, course=course)
    body = client.get(
        reverse("courses:course_outline", kwargs={"slug": "mm"})
    ).content.decode()
    assert _marked(body, "span.resume__title")
    assert _marked(body, "span.resume__crumb")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_courses_views.py tests/test_title_math_markers.py -v -k "resume or eyebrow or card_links or tag_filter"
```

Expected: FAIL — `a.resume` does not exist, so `card` is `None` (`TypeError`/`AttributeError`).

- [ ] **Step 3: Create the template**

`templates/courses/_resume_card.html`:

```django
{% load i18n %}{% get_current_language as LANGUAGE_CODE %}
{% comment %}The outline's resume card. `courses_extras` is deliberately NOT loaded:
this card uses no filter from it (unit_marker/marker_label are consumed inside
_unit_kind_chip.html, which loads the library itself) and no author title lands in an
attribute here, so strip_math_delimiters has no site. A future tooltip would need both.

{% get_current_language %} is MANDATORY: django.template.context_processors.i18n is not
in settings, so without it LANGUAGE_CODE resolves to "" and the eyebrow ships lang="" --
valid HTML meaning "undetermined", so the failure is silent.

lang is split the way _unit_crumbs.html splits it: the eyebrow is UI text and takes the
UI language, while the title and crumbs are author content and keep the course language
inherited from <section class="outline">.{% endcomment %}
<a class="resume" href="{% if resume.node.unit_type == 'quiz' %}{% url 'courses:quiz_unit' slug=course.slug node_pk=resume.node.pk %}{% else %}{% url 'courses:lesson_unit' slug=course.slug node_pk=resume.node.pk %}{% endif %}">
  <span class="resume__eyebrow" lang="{{ LANGUAGE_CODE }}">
    {% if resume.state == "resume" %}{% trans "Pick up where you left off" %}
    {% elif resume.state == "next" %}{% trans "Up next" %}
    {% elif resume.state == "gap" %}{% trans "Still to do" %}
    {% else %}{% trans "Start the course" %}{% endif %}
  </span>
  {% if resume.ancestors %}
    <span class="resume__path">
      {% for a in resume.ancestors %}{% if not forloop.first %}<span class="resume__sep" aria-hidden="true">›</span>{% endif %}<span class="resume__crumb" data-math-title>{{ a.title }}</span>{% endfor %}
    </span>
  {% endif %}
  <span class="resume__title" data-math-title>{{ resume.node.title }}</span>
  {% include "courses/_unit_kind_chip.html" with node=resume.node only %}
</a>
```

- [ ] **Step 4: Add the include**

In `templates/courses/outline.html`, between the closing `</div>` of `.outline__head` and `{% include "courses/_tags_filter_bar.html" %}`:

```django
  {% if resume %}{% include "courses/_resume_card.html" with resume=resume course=course only %}{% endif %}
```

`only` **and** the explicit `course=course` are both load-bearing: with `only` and no `course`, both `{% url %}` branches raise `NoReverseMatch` and 500 the outline; without `only`, the partial silently inherits the whole context.

- [ ] **Step 5: Run**

```bash
uv run pytest tests/test_courses_views.py tests/test_title_math_markers.py -v
```

Expected: all pass.

- [ ] **Step 6: Falsify**

1. Point both `{% url %}` branches at `lesson_unit`. Expected: `test_card_links_to_quiz_unit_for_a_quiz_target` FAILS.
2. Restore; collapse the four eyebrow branches to a single `{% trans "Up next" %}`. Expected: three of the four parametrized cases FAIL.
3. Restore; delete `{% get_current_language as LANGUAGE_CODE %}`. Expected: `test_eyebrow_carries_the_active_ui_language` FAILS with `lang=""`.
4. Restore; remove `data-math-title` from `span.resume__crumb`. Expected: `test_resume_card_title_and_crumbs_are_marked` FAILS.

Restore each by hand.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/_resume_card.html templates/courses/outline.html tests/test_courses_views.py tests/test_title_math_markers.py
git commit -m "feat(resume): the card partial, its include, and render coverage"
```

---

### Task 8: CSS

**Files:**
- Modify: `core/static/core/css/app.css` (the "Course outline (syllabus)" section, after `.outline__title` / `.outline__results` around line 500)

**Interfaces:** Consumes the DOM contract from Task 7. Produces no Python surface.

- [ ] **Step 1: Add the block**

Insert after `.outline__results { margin-left: auto; }`:

```css
/* Resume card: the one thing a returning student should be able to hit without
   reading the tree. Ground it on --surface-raised and cut the border against THAT,
   never against the page base. Width comes from .outline (max-width: 52rem). */
.resume {
  display: flex; flex-wrap: wrap; align-items: baseline;
  gap: var(--space-1) var(--space-3);
  padding: var(--space-4); margin-bottom: var(--space-5);
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
  text-decoration: none; color: inherit;
}
.resume__eyebrow {
  flex-basis: 100%; font-size: .8125rem; font-weight: 600;
  letter-spacing: .02em; text-transform: uppercase; color: var(--text-secondary);
}
.resume__path { font-size: .875rem; color: var(--text-secondary); }
.resume__sep { margin: 0 var(--space-1); }
.resume__title { font-size: 1.15rem; font-weight: 600; color: var(--text-primary); }
.resume:hover { border-color: var(--border-strong); }
.resume:hover .resume__title { text-decoration: underline; }
.resume:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
```

Before writing, `grep` `app.css` for the exact token names in use (`--radius-md`, `--border-strong`, `--focus-ring`, `--text-secondary`) and substitute the repo's actual names — **do not invent tokens**.

- [ ] **Step 2: Verify the tokens resolve**

```bash
grep -nE "^\s*--(radius-md|border-strong|focus-ring|text-secondary|surface-raised)\b" core/static/core/css/app.css
```

Expected: every token used above appears. Fix any that do not.

- [ ] **Step 3: Visual check**

Run the app, open a course outline as an enrolled student, and screenshot: **light**, **dark** (judged separately, not assumed from light), and **keyboard focus** (Tab to the card). Also check **640px** — the only outline-scoped `max-width: 640px` block (`app.css:688-690`, which drops `.outline__results`' `margin-left: auto`); `.outline__head` itself wraps continuously rather than reflowing. 832px is the `.unit-crumbs` breakpoint and is not relevant here.

- [ ] **Step 4: Commit**

```bash
git add core/static/core/css/app.css
git commit -m "style(resume): card surface, hover and focus-visible treatment"
```

---

### Task 9: i18n

**Files:**
- Modify: `locale/*/LC_MESSAGES/django.po` and the compiled `.mo`

- [ ] **Step 1: Extract**

```bash
uv run python manage.py makemessages -l pl
```

- [ ] **Step 2: Translate**

Fill in the four msgids in `locale/pl/LC_MESSAGES/django.po`:

| msgid | msgstr |
|---|---|
| `Pick up where you left off` | `Wróć tam, gdzie skończyłeś` |
| `Up next` | `Następnie` |
| `Still to do` | `Do zrobienia` |
| `Start the course` | `Rozpocznij kurs` |

Check each for a `#, fuzzy` flag — `makemessages` pre-fills fuzzy entries with a **wrong** translation, and clearing one means deleting **both** the flag line and the bogus `msgstr`.

- [ ] **Step 3: Compile**

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 4: Verify the eyebrow test still passes**

```bash
uv run pytest tests/test_courses_views.py -v -k "eyebrow"
```

- [ ] **Step 5: Commit**

```bash
git add locale
git commit -m "i18n(resume): Polish strings for the four card states"
```

---

### Task 10: Correct the stale `progress_reset` comment (change site 7)

This is a **separate function** from Task 6's edit and is the change most easily dropped — no test can catch it.

**Files:**
- Modify: `courses/views.py` (`progress_reset`, the `.update() deliberately bypasses save()` comment)

- [ ] **Step 1: Read the current comment**

```bash
grep -n "nothing reads updated_at" -B 4 -A 2 courses/views.py
```

- [ ] **Step 2: Correct the false clause, line-count neutral**

The comment currently says reset is safe partly because *"nothing reads updated_at for practice state"*. `build_resume`'s source A now reads it. Replace that clause — keeping the **same number of lines** so line-number citations in surrounding untouched code do not rot:

```python
        # .update() deliberately bypasses save(): it fires neither auto_now on
        # updated_at nor the completed => completed_at invariant. Both are fine --
        # reset does not touch `completed`, and leaving updated_at alone is what
        # keeps the outline resume card (rollups.build_resume, source A) pointing
        # where the student actually was. IDOR-safe against other STUDENTS by
        # construction (student=request.user); the cross-COURSE hole is closed by
        # get_node_or_404 above, not by this filter.
```

Confirm the replacement has the **same line count** as the original before committing.

- [ ] **Step 3: Add the behavioural test that the comment now describes**

Append to `tests/test_resume_target.py`:

```python
@pytest.mark.django_db
def test_start_fresh_does_not_move_the_resume_target(client):
    """progress_reset writes with rows.update(...), and a queryset .update() does not
    fire auto_now -- so clearing scratch work must not send the student back.

    FIXTURE IS LOAD-BEARING. The stale uncompleted row must be STRICTLY OLDER than
    unit 5's completed_at, and only .update()/freeze_time can backdate it (save()
    cannot). Create it last in the natural order and it becomes the NEWEST row, so
    the correct build already answers `resume` on it and the test fails before the
    mutant is even applied.
    """
    from django.urls import reverse

    from tests.factories import make_login

    user = make_login(client, "sf")
    course, units = _course_with_units(8, slug="sf")
    EnrollmentFactory(student=user, course=course)
    for i in range(5):
        _complete(units[i], user, f"2026-08-0{i + 1} 10:00:00")
    UnitProgressFactory(student=user, unit=units[6])
    _backdate_progress(units[6], user, timezone.now() - timedelta(days=400))

    before = _resume(course, user)
    assert before["state"] == "next" and before["node"].pk == units[5].pk

    client.post(reverse("courses:progress_reset_course", kwargs={"slug": "sf"}))

    after = _resume(course, user)
    assert after["state"] == "next"
    assert after["node"].pk == units[5].pk
```

- [ ] **Step 4: Run and falsify**

```bash
uv run pytest tests/test_resume_target.py -v -k "start_fresh"
```

Expected: PASS. Then change `progress_reset`'s `rows.update(element_state={})` to a loop of `row.element_state = {}; row.save()`. Expected: the test FAILS (the mutant re-dates the stale row, flipping the answer to `resume` on `units[6]`). Restore by hand.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py tests/test_resume_target.py
git commit -m "docs(resume): correct progress_reset's now-false updated_at comment"
```

---

### Task 11: Definition of done

**Files:** none — a gate.

- [ ] **Step 1: Lint and format**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
```

Both must be clean. `--no-cache` matters: the `noqa` warning is otherwise cached away, and `format --check` is a separate gate from `check`.

- [ ] **Step 2: No migration, no system-check regression**

```bash
uv run python manage.py makemigrations --check
uv run python manage.py check
```

`makemigrations --check` must report nothing to create — this change adds no model field.

- [ ] **Step 3: Targeted suite**

```bash
uv run pytest tests/test_resume_target.py tests/test_courses_views.py tests/test_title_math_markers.py tests/test_courses_progress.py -v
```

- [ ] **Step 4: Courses non-e2e sweep**

```bash
uv run pytest tests/ courses/tests/ -m "not e2e" -q
```

Grep the summary line for `failed` — the exit code alone has lied before on a backgrounded run.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "chore(resume): definition-of-done fixes"
```

---

## Self-Review

**Spec coverage.** Walked each spec section against the tasks: steps 1–6 → Tasks 1/2/3; sources A–E → Tasks 1/2/3; cross-source tie-break and assembly order → Task 2; `completed_at` anchoring → Task 3; ancestors and inert stamping → Task 4; query budgets → Task 5; enrolled gate and context key → Task 6; DOM contract, four eyebrows, link branching, `lang`, tag independence, marker coverage → Task 7; hover/focus/screenshots → Task 8; four strings → Task 9; **change site 7** → Task 10; DoD → Task 11. All seven enumerated change sites have a task. The spec's non-falsifiable item (source A's `completed=False`) is carried as a comment in Task 2 with an explicit instruction not to falsify it, and the spec's accepted limitation (a submitted quiz with no `UnitProgress` can surface as `next`) is documented in Task 2's `test_submitted_quiz_with_no_progress_row_is_not_the_target` docstring.

**Placeholder scan.** No TBD/TODO, no "add error handling", no "similar to Task N" — each task repeats the code it needs.

**Type consistency.** `build_resume(course, user, tree)` returns `{"node": ContentNode, "state": str, "ancestors": list}` in every task; `done` is a **pk** in Task 3 (the code resolves its index) while `flight` is a **node** — called out in Task 3 Step 3 so an implementer does not mix them; template reads `resume.node`, `resume.state`, `resume.ancestors`, matching Task 1's contract.

**One deliberate deviation from the spec's test list:** the spec prescribed within-source and cross-source tie tests with a pinned insertion order. Task 2's assembly-order comment makes the `source_rank` mutant killable, and Task 3 covers the `>=` boundary tie. If the executing agent finds the cross-source tie under-covered after Task 3, add it there rather than deferring.
