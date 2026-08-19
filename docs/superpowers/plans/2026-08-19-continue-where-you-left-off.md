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
  | separator between crumbs | `span.resume__sep` (`aria-hidden="true"`) |
- **Every test is written failing-first and falsified** against the mutant named in its task. A test that cannot go RED does not ship. Where a task says a fixture detail is load-bearing, it is because the obvious fixture makes the test vacuous.
- **`translation.override` must NOT be used** for client-render language tests — `core/middleware.py::SessionLocaleMiddleware.process_request` re-activates per request and discards it. Use `session["_language"] = "pl"; session.save()` plus `HTTP_ACCEPT_LANGUAGE="pl"`.
- **Ties need `freeze_time`.** `updated_at`, `updated`, `last_attempt_at` and `completed_at` are all stamped Python-side; writes in one transaction differ by microseconds and produce no tie.
- **Cite `courses/views.py` by FUNCTION, never by line number.** Task 6 inserts ~14 lines into
  that file (an import, the `resume = (...)` block, and the context key), so any numeric
  `views.py:NNN` written into `rollups.py` or a test docstring is wrong the moment this branch
  lands — self-inflicted citation rot, on the very branch that writes it. `models.py`,
  `rollups.py` and `seed_demo_course.py` citations are untouched by this change and may stay
  numeric.
- **Test DB:** the worktree `.env` already points `TEST_DATABASE_URL` at `libli_resume`. Start the test-DB container before any pytest run. Run pytest via `uv run`.
- **Imports go at the TOP of the file, never beside the test that needs them.** Several tasks say
  "append to `tests/test_resume_target.py`" and show new imports — those imports must be **hoisted
  into the single top-of-file block**, sorted, one per line. `pyproject.toml` selects `["E", "F", "I", "UP", "B", "S"]`
  (ignoring `S101`, with `S105`/`S106`/`S107` per-file-ignored under `tests/**`) and sets
  `force-single-line = true`, so an import sitting after a function definition fails Task 11's
  `ruff check` with E402 **and** I001. The same applies to the `from tests.factories import ...`
  lines shown inside the `tests/test_courses_views.py` tests: match that file's existing convention
  rather than the illustrative inline form. Ruff is not run until Task 11, so these accumulate
  silently — hoist as you go.

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

Append to `courses/rollups.py`, after `build_unit_nav`.

**Executor notes — these belong to the plan, NOT to the source file.** Do not paste them as
comments; `rollups.py` must not ship referring to "Task 2" or "Task 11".

- Task 2 inserts its query block immediately **below** the `flight, ts_f = None, None` line;
  Task 3 immediately **below** the `done, ts_d = None, None` line. Leave both lines in place.
- `open_pks` and `leaf_pks` are unused until Tasks 2-3, so ruff would flag F841 if run now. That
  is why lint is deferred to Task 11. Do not delete them — and note the warning is gone by the
  end of the change, since both become used.

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

    # Both names are read unconditionally by steps 3 and 4 below, so any edit that
    # REPLACES rather than extends either line raises UnboundLocalError on every
    # cold path.
    flight, ts_f = None, None
    done, ts_d = None, None

    # STEP 3. Both names are already bound, so this runs correctly in every task.
    # The ts comparison is ESSENTIAL: views.py::build_lesson_context mints a
    # UnitProgress row on EVERY enrolled lesson GET, so without it one stray click
    # a year ago pins the card to that unit forever. >= (not >) keeps an in-flight
    # unit winning a tie -- the friendlier reading of "where you left off".
    if flight is not None and (done is None or ts_f >= ts_d):
        return {"node": flight, "state": "resume", "ancestors": []}

    # STEP 4. `done` is a pk; its POSITION in the outline is what matters. Dead
    # until source D assigns `done`; laid down here so the control flow is final.
    if done is not None:
        idx = next(i for i, leaf in enumerate(leaves) if leaf["node"].pk == done)
        # No default on next(): source D filters unit_id__in=leaf_pks, so a missing
        # index is an invariant break and should raise StopIteration loudly rather
        # than degrade into a TypeError four lines later. Same house style as
        # _current_ancestors raising KeyError on an unstamped tree.
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
from freezegun import freeze_time

from courses.models import Element
from courses.models import QuestionResponse
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress


def _backdate_progress(unit, user, when):
    """updated_at is auto_now, so save() cannot backdate it -- only .update() can."""
    UnitProgress.objects.filter(student=user, unit=unit).update(updated_at=when)


def _answered_question(unit, submission, when):
    """A QuestionResponse with last_attempt_at set -- source C's only input."""
    q = ShortTextQuestionElement.objects.create(stem="q", accepted="a")
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
    answer path (views.py::quiz_answer) never saves the submission -- so B measures
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

```python
@pytest.mark.django_db
def test_exact_cross_source_tie_prefers_the_answered_quiz():
    """The source_rank tie-break (C=2 > B=1 > A=0). With rank dropped, max() over an
    untied key returns the FIRST maximal element, and the assembly order is A,B,C --
    so the mutant answers the LESSON. Assembling [C, B, A] would make the mutant
    coincidentally right, which is why the order is normative.

    The tie must be FORCED: all four timestamps are stamped Python-side, so two
    writes in one transaction differ by microseconds and produce no tie at all.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="t1", email="t1@test.example.com")
    EnrollmentFactory(student=user, course=course)

    moment = timezone.now() - timedelta(days=5)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=lesson)
        sub = QuizSubmissionFactory(
            student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
        )
        _answered_question(quiz, sub, timezone.now())

    a_ts = UnitProgress.objects.get(student=user, unit=lesson).updated_at
    c_ts = QuestionResponse.objects.get(submission=sub).last_attempt_at
    assert a_ts == c_ts  # the tie is real, not assumed

    r = _resume(course, user)
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_within_source_tie_prefers_the_higher_unit_id():
    """Source A's -unit_id secondary key. INSERTION ORDER IS LOAD-BEARING: create the
    LOWER-pk unit's row FIRST. Postgres's order among equal sort keys is unspecified
    but follows scan order in practice, so the mutant (no -unit_id) returns the
    first-inserted row. Insert the higher pk first and the mutant is coincidentally
    right and the test is GREEN on a broken build.
    """
    course, units = _course_with_units(3)
    user = make_verified_user(username="t2", email="t2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    lo, hi = sorted((units[0], units[1]), key=lambda u: u.pk)

    moment = timezone.now() - timedelta(days=5)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=lo)  # lower pk FIRST
        UnitProgressFactory(student=user, unit=hi)

    rows = UnitProgress.objects.filter(student=user, unit__in=(lo, hi))
    assert len({r.updated_at for r in rows}) == 1  # the tie is real

    assert _resume(course, user)["node"].pk == hi.pk
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_resume_target.py -v -k "in_flight or answered_quiz or opened_but or submitted_quiz or invisible_newer or cross_source_tie or within_source_tie"
```

Expected: all **7** FAIL. `flight` is hardcoded `None`, so each lands on `start`/`next`. The two
tie tests fail on the *node* assertion specifically — Task 1 returns `open_leaves[0]`, which is the
lesson in the cross-source fixture and `lo` in the within-source one.

- [ ] **Step 3: Write the implementation**

**Do NOT replace the `flight, ts_f = None, None` line — insert immediately BELOW it**, and leave
both it and the `done, ts_d = None, None` line untouched. The block below only *reassigns* `flight`
and `ts_f` when a candidate exists; deleting the initialisation makes every cold path raise
`UnboundLocalError`, and moving anything above the `done` line makes step 3 read `done` before it
is bound. Step 3 and step 4 are already in place from Task 1; this task adds no control flow.

Insert after `flight, ts_f = None, None` and before `done, ts_d = None, None`:

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
    # A -- lesson work. updated_at is auto_now: the first open in
    # views.py::build_lesson_context, every `seen` batch, every practice-state write.
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
    # auto_now (models.py:3008) and the answer path (views.py::quiz_answer) saves the
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

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: **12** passed (Task 1's 5 + this task's 7).

- [ ] **Step 5: Falsify — six mutants (seven applications), by hand**

1. Delete source **C** from the `candidates` tuple. Expected: `test_answered_quiz_beats_a_later_opened_lesson` FAILS.
2. Restore C; delete source **B**. Expected: `test_opened_but_unanswered_quiz_is_the_target` FAILS.
3. Restore B; drop `status=IN_PROGRESS` from **B**, then (separately) from **C**. Expected: `test_submitted_quiz_with_no_progress_row_is_not_the_target` FAILS both times.
4. Restore; change source A's filter to `unit__course=course` and add a post-`.first()` membership check. Expected: `test_invisible_newer_row_does_not_discard_the_visible_candidate` FAILS.
5. Restore; drop `t[1]` from the `max` key (i.e. `key=lambda t: t[0]`). Expected: `test_exact_cross_source_tie_prefers_the_answered_quiz` FAILS (answers the lesson).
6. Restore; drop `-unit_id` from source A's `order_by`. Expected: `test_within_source_tie_prefers_the_higher_unit_id` FAILS.

   If it does **not** fail, do not just re-check the insertion order — with `ORDER BY updated_at
   DESC LIMIT 1` Postgres uses a top-N heapsort whose order among equal keys is genuinely
   unspecified, so the mutant may return `hi` by chance. Force the issue instead: add a third tied
   row, or assert directly on
   `UnitProgress.objects.filter(student=user).order_by("-updated_at").values_list("unit_id", flat=True)[0]`.

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

Append to `tests/test_resume_target.py` (`freeze_time` is already imported from Task 2):

```python
def _complete(unit, user, days_ago):
    """A completed UnitProgress whose completed_at is `days_ago` days back.

    save() stamps completed_at itself, so freeze the clock rather than backdating.

    RELATIVE, never a hard-coded calendar date: mixing literal dates with
    `timezone.now() - timedelta(...)` in one fixture makes the ordering
    clock-dependent, and such a test silently INVERTS once the wall clock passes
    those dates. Larger days_ago == older.
    """
    with freeze_time(timezone.now() - timedelta(days=days_ago)):
        UnitProgressFactory(student=user, unit=unit, completed=True)


@pytest.mark.django_db
def test_most_recent_unit_completed_advances_to_the_next_open_unit():
    """FIXTURE IS LOAD-BEARING: units[0] stays OPEN so open_leaves[0] is units[0]
    while forward is units[3]. Complete 0 and 1 instead and both step 4 and step 5
    answer units[2] -- deleting step 4 entirely would leave the test green via
    step 5, which also returns state "next".
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d1", email="d1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[1], user, 30)
    _complete(units[2], user, 20)
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[3].pk


@pytest.mark.django_db
def test_stray_visit_does_not_pin_the_card_forever():
    """THE bug the ts_f >= ts_d comparison exists to stop. Opening unit 0 once
    leaves a permanent completed=False row -- views.py::build_lesson_context does a
    get_or_create on every enrolled lesson GET. Without the comparison it outranks
    every completion made since and the card says "Pick up where you left off -
    unit 0" forever.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d2", email="d2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=units[0])
    _backdate_progress(units[0], user, timezone.now() - timedelta(days=90))
    _complete(units[1], user, 20)
    _complete(units[2], user, 10)
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
    moment = timezone.now() - timedelta(days=5)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=units[0], completed=True)
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
    calls progress.save() UNCONDITIONALLY, including for an already
    completed unit -- so re-reading unit 0 re-dates its updated_at while
    completed_at stays put. Anchor on updated_at and the mutant answers units[1].

    Do NOT try to build this with force_submit_quiz: it is guarded by
    `if not progress.completed`, so it can never re-date a completed row, and on
    the path where it does save, save() stamps completed_at in the same instant.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d4", email="d4@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, 30)
    _complete(units[2], user, 20)
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
    _complete(units[0], user, 30)
    _complete(units[2], user, 20)
    _complete(units[3], user, 10)
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
    _complete(units[0], user, 30)
    _complete(units[1], user, 20)
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
    _complete(lesson, user, 30)
    _complete(quiz, user, 20)
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
    _complete(required, user, 30)
    r = _resume(course, user)
    assert r["node"].pk == extra.pk
```

```python
@pytest.mark.django_db
def test_in_flight_strictly_newer_than_a_real_completion_resumes():
    """The plain `ts_f > ts_d` arm, which nothing else covers: the existing tests
    exercise `done is None` (no completion at all), `==` (the tie test) and `<`
    (stray_visit). Kills a mutant that reversed the comparison to `ts_d >= ts_f`,
    and one that made step 3 fire only when `done is None`.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d10", email="d10@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, 30)
    UnitProgressFactory(student=user, unit=units[2])
    _backdate_progress(units[2], user, timezone.now() - timedelta(days=10))
    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[2].pk


@pytest.mark.django_db
def test_submitted_quiz_without_progress_can_surface_as_next():
    """DOCUMENTS AN ACCEPTED LIMITATION, deliberately -- this is not a bug report.

    build_outline's `completed` flag derives solely from UnitProgress.completed
    (rollups.py:244-250, leaf key at :265) and knows nothing about
    QuizSubmission.status, so a SUBMITTED submission whose unit lacks a completed
    UnitProgress row -- the seed_demo_course.py shape -- stays in `open` and can be
    offered under "Up next".

    The violated invariant is "a SUBMITTED submission always has a completed
    UnitProgress", which every production path upholds and only the demo seeder
    breaks. The repair belongs in the seeder, NOT in this card: adding a fifth query
    to compensate for a fixture-only state was explicitly rejected. This test exists
    so that decision is recorded and cannot evaporate silently.

    EXEMPT FROM FALSIFICATION, like the query-budget guards: its only "mutant" is a
    design change this spec explicitly rejected (adding a fifth query to exclude
    submitted quizzes from `open`). Do not hunt for one.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="d9", email="d9@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(lesson, user, 30)
    QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == quiz.pk
```

- [ ] **Step 2: Run the tests — FOUR must fail, the rest are guards**

```bash
uv run pytest tests/test_resume_target.py -v -k "most_recent or stray_visit or exact_tie or reseeing or wraps_back or all_units or completed_quiz_that or additional_lesson or without_progress_can_surface or strictly_newer"
```

Expected: exactly **four** RED — `test_most_recent_unit_completed_advances_to_the_next_open_unit`,
`test_stray_visit_does_not_pin_the_card_forever`, `test_reseeing_a_finished_unit_does_not_rewind_the_anchor`,
and `test_finished_the_last_unit_wraps_back_to_the_earliest_gap`.

The others PASS on the Task-2 build and that is CORRECT, not a broken task: `test_exact_tie...`
already returns `resume` via step 3 with `done is None`; `test_all_units_completed_returns_none` and
`test_completed_quiz_that_is_the_last_open_unit_yields_none` are step-1 cases; `test_additional_lesson...`
and `test_submitted_quiz_without_progress_can_surface_as_next` reach step 5; and
`test_in_flight_strictly_newer_than_a_real_completion_resumes` returns `resume` via step 3 with
`done is None`. That is **six** green. Five are **guards** whose value is proven by the Step-5
falsification rather than by failing first; the sixth,
`test_submitted_quiz_without_progress_can_surface_as_next`, is a **decision record** and is
exempt from falsification (see its docstring).

- [ ] **Step 3: Write the implementation**

**Do NOT replace the `done, ts_d = None, None` line — insert immediately BELOW it**, above the
step-3 `if flight is not None ...`. Step 3 and step 4 already exist from Task 1; this task adds no
control flow, only the query that makes step 4 reachable.

```python
    # SOURCE D -- the completion anchor. completed_at, NEVER updated_at:
    # completed_at is stamped exactly once in UnitProgress.save() when `completed`
    # first flips and is never re-stamped, whereas views.py::seen calls
    # progress.save() UNCONDITIONALLY on every batch including for an
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

Note `done` is a **pk**, not a node — Task 1's step 4 already resolves its outline index. `flight`,
by contrast, is a **node**. Do not mix them.

- [ ] **Step 4: Run the full file**

```bash
uv run pytest tests/test_resume_target.py -v
```

Expected: **22** passed (12 + this task's 10).

- [ ] **Step 5: Falsify — by hand**

1. Change source D's ordering to `("-updated_at", "-unit_id")`. Expected: `test_reseeing_a_finished_unit_does_not_rewind_the_anchor` FAILS (returns `units[1]`).
2. Restore; change step 3's `ts_f >= ts_d` to `ts_f > ts_d`. Expected: `test_exact_tie_between_in_flight_and_completion_resumes` FAILS.
3. Restore; drop the `done is None or ts_f >= ts_d` condition entirely (i.e. `if flight is not None:`). Expected: `test_stray_visit_does_not_pin_the_card_forever` FAILS.
4. Restore; replace the `gap` return with `return None`. Expected: `test_finished_the_last_unit_wraps_back_to_the_earliest_gap` FAILS.
5. Restore; delete step 1's `if not open_leaves: return None`. Expected: **three** tests FAIL with `IndexError` — `test_all_units_completed_returns_none`, `test_no_visible_units_returns_none`, and `test_completed_quiz_that_is_the_last_open_unit_yields_none` (same shape: both units completed, `open_leaves` empty, `done` set, `forward` `None`, then `open_leaves[0]`). This mutant is also what earns the completed-quiz test its place; its docstring's own "quiz never completes" mutant is not applied anywhere.
6. Restore; **reverse the step-3 comparison** to `done is None or ts_d >= ts_f`. Expected: `test_in_flight_strictly_newer_than_a_real_completion_resumes` FAILS. This is the mutant that test exists for — none of mutants 1-5 can kill it (2 and 3 leave it green, because its timestamps are strictly ordered), so without this step it ships unfalsified, violating the Global Constraint.
7. Restore; **narrow step 3** to `if flight is not None and done is None:`. Expected: the same test FAILS again, returning `next`/`units[1]`.
8. Restore; **narrow `open_leaves` to obligatory lessons** — `[d for d in leaves if not d["completed"] and is_obligatory_lesson(d["node"])]`. Expected: `test_additional_lesson_still_counts_as_a_target` FAILS (`open_leaves` is empty, step 1 returns `None`, and `r["node"]` raises `TypeError`). This is the ONLY mutant that reddens that test — mutants 1-7 all leave it green — so without this step the flat-leaf rule ships untested.

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
    # THREE levels, not two. A depth-0 container already renders ` open` from the
    # existing {% if item.depth == 0 %}, so stamping a unit under a root chapter
    # makes the mutant emit `<details ... open open>` -- the strings still differ, so
    # the test is not vacuous, but it proves the point via a duplicated attribute
    # rather than the branch the guard is about. Nesting deeper makes the chapter's
    # ` open` appear ONLY under the mutant.
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, order=0)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, order=0
    )
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

Expected: **one** RED — `test_ancestors_are_the_root_to_parent_chain_excluding_the_unit`
(`[] != [part.pk, chapter.pk]`).

`test_root_level_unit_has_no_ancestors` asserts `ancestors == []`, which is exactly what Tasks 1-3
hardcode, so it is green before any Task-4 code exists. It is a **no-crash guard**, as is
`test_stamping_the_tree_does_not_change_the_outline_html`. Both earn their place through the Step-5
falsification, not by failing first.

- [ ] **Step 3: Write the implementation**

Replace each of the five `"ancestors": []` literals with a single helper call.

**Anchor, stated the way Tasks 2 and 3 state theirs:** define `_with_ancestors` at **function-body
indent (4 spaces)**, immediately **after** Task 3's `if d_row is not None: done, ts_d = d_row`
block and immediately **before** the `# STEP 3` comment.

Do **not** put it "just before the first return that yields a node" — that return is nested inside
the step-3 `if`, so defining the helper there lands it at 8-space indent inside that branch and the
four later call sites (`next`, `gap`, step-5 `next`, step-6 `start`) raise `UnboundLocalError`. No
later edit may move it inside a branch.

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

Expected: **25** passed (22 + this task's 3).

- [ ] **Step 5: Falsify**

1. Change `_with_ancestors` to append the node itself (`_current_ancestors(tree) + [node]`). Expected: **both** `test_ancestors_are_the_root_to_parent_chain_excluding_the_unit` **and** `test_root_level_unit_has_no_ancestors` FAIL — the latter returns `[unit]` instead of `[]`. This is the mutant that earns the root-level test its place, since it cannot fail first.
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

- [ ] **Step 1: Write the query-budget guards**

These are the documented exception to the failing-first rule — budget guards written after the
implementation exists, so they pass immediately. They earn their place through Step 3's
falsification, not by going RED first.

**Do not add a view-level query-count test.** Only the `build_resume`-level counts are pinned;
the view-level numbers (5 warm, 6-or-7 cold) are deliberately unpinned. The spec records the
decision and the three hazards that killed three separate attempts — a fixture-dependent
baseline, two-user arms that do not cancel, and `conftest.py`'s autouse `_clear_site_cache`
making a same-user A/B exceed the delta on a *correct* build. See **"There is deliberately NO
view-level query-count test"** in the spec before writing one.

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

1. In source C, replace the projection with a **shape-preserving** dereference — otherwise the
   mutant dies on a `TypeError` before it can issue the extra query, and proves nothing about the
   budget. Write it as:

   ```python
   _row = (
       QuestionResponse.objects.filter(
           submission__student=user,
           submission__unit_id__in=open_pks,
           submission__status=QuizSubmission.Status.IN_PROGRESS,
           last_attempt_at__isnull=False,
       )
       .order_by("-last_attempt_at", "-submission__unit_id")
       .first()
   )
   c = (_row.submission.unit_id, _row.last_attempt_at) if _row else None
   ```

   Expected: `test_warm_path_costs_exactly_four_queries` FAILS with **5** — the extra query is the
   lazy load of `_row.submission`.
2. Restore; make source E eager (assign both `.exists()` calls to locals before the `or`). Expected: **`test_cold_path_short_circuits_after_the_first_probe` FAILS with 6**, not 5. The warm path CANNOT catch this: source E sits *after* the step-3 and step-4 returns, so on a warm fixture it never executes at all and the count stays 4 on both builds. Do not chase a warm-path failure here — seeing one would mean E had been wrongly hoisted above the returns.
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
    # The context assertion alone would still pass if the template later grew a
    # fallback card, and it never exercises the {% if resume %} guard. This test is
    # what pins the WIRING (it replaces the abandoned view-level query test), so it
    # must assert on the rendered DOM as well.
    from bs4 import BeautifulSoup

    assert BeautifulSoup(r.content, "html.parser").select_one("a.resume") is None
```

```python
@pytest.mark.django_db
def test_tag_filter_does_not_move_the_resume_target(client):
    """The target is computed independently of the active tag filter. Mutant:
    filtering `leaves` on tag_hidden. The failure would be INVISIBLE -- the card
    still renders, just pointing somewhere else.

    Tag has `author` (not owner), NO course field at all (course scoping runs
    through UnitTag -> ContentNode), and `color` must come from TAG_PALETTE
    (teal/amber/indigo/rose/green/violet/slate/cyan -- "blue" is not a member).
    Use the shipped factories rather than Tag.objects.create.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import TagFactory
    from tests.factories import UnitTagFactory
    from tests.factories import make_login

    user = make_login(client, "tf")
    course = CourseFactory(slug="tf")
    target = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    other = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=1)
    EnrollmentFactory(student=user, course=course)
    tag = TagFactory(author=user, name="t", color="teal")
    UnitTagFactory(tag=tag, unit=other)

    r = client.get(
        reverse("courses:course_outline", kwargs={"slug": "tf"}), {"tags": tag.pk}
    )
    # Guard the guard: course_outline drops any ?tags= pk not in course_tag_ids, so
    # if the tag did not reach tags_for_outline the filter is silently inert and the
    # test would pass for the wrong reason.
    assert r.context["active_tag_ids"] == [tag.pk]
    assert r.context["resume"]["node"].pk == target.pk
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_courses_views.py -v -k "resume_target or tag_filter"
```

Expected: all three FAIL — `KeyError: 'resume'`.

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

Expected: **3** passed. `-k` is a substring match, so this also selects
`test_tag_filter_does_not_move_the_resume_target` — all three of this task's tests.

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

Expected RED: the **four** parametrized eyebrow cases, both `card_links` tests, the `lang` test,
and `test_resume_card_title_and_crumbs_are_marked` — `a.resume` does not exist yet, so `card` is
`None` (`TypeError`/`AttributeError`).

Expected GREEN, and that is correct: Task 6's three tests, which this `-k` also selects.
`test_outline_offers_no_resume_target_to_a_non_enrolled_viewer` in particular passes **trivially**
right now — its `select_one("a.resume") is None` assertion cannot fail while no template exists.
It only becomes meaningful after Step 3, which is why Step 5 re-runs the whole file.

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

- [ ] **Step 7: Re-scope the outline assertions the card now shadows**

The card injects a second `.unit-kind-chip`, a second `<a>`, and two more `[data-math-title]`
elements **ahead of** every existing outline selector in the DOM, so any unscoped `select_one`
on the outline page now hits the card first.

`tests/test_unit_marker.py:195` is the live case:

```python
chip = _outline_soup(client, course).select_one(".unit-kind-chip")
assert chip["lang"] == "en"
```

Its fixture is exactly one enrolled student and one quiz unit, so `build_resume` targets that
quiz (`state == "start"`) and the card's chip precedes the outline row's. The assertion **still
passes** — the card's chip also emits `lang="{{ LANGUAGE_CODE }}"` — so the test goes green while
no longer asserting anything about the outline row it exists to guard. **No per-task review can
see this, because the diff touches no test file.**

Re-scope it — **two edits in that test, not one**. Its fixture never binds the node to a name
(`ContentNodeFactory(course=course, unit_type="quiz", title="Lang")` at line 193), so the
scoped selector needs a variable first or you get `NameError: name 'quiz' is not defined`:

```python
# line 193 -- add the binding
quiz = ContentNodeFactory(course=course, unit_type="quiz", title="Lang")

# line 195 -- scope the selector
chip = _outline_soup(client, course).select_one(
    f"li#node-{quiz.pk} a.outline-unit .unit-kind-chip"
)
```

(`test_unit_marker.py:173` is already scoped as `li#node-{quiz.pk} a.outline-unit` — leave it.)

**The same shadowing applies to bare substring assertions, which no selector sweep can find.**
The card renders the target unit's *title* in `span.resume__title` above the tree, so any
`assert "<title>" in body` over the outline page is now satisfied by the card and would stay
green even if `_outline_node.html` stopped rendering unit rows entirely. Two live cases:

- `tests/test_courses_views.py::test_outline_renders_for_enrolled` — `assert "Lesson A" in
  resp.content.decode()`. One enrolled
  student, one lesson, so the card is `state="start"` on "Lesson A".
- `tests/test_tags_outline.py::test_filter_hides_non_matching_unit` — `assert "Photosynthesis" in html` in
  `test_filter_hides_non_matching_unit`. u1 is `open[0]`, so that title is the card's.
  (The sibling `assert "Membranes" in html` on line 54 is unaffected — the card renders one
  title, and it is not that one.)

Re-scope both to the outline row rather than the page. **`tests/test_courses_views.py` needs two
edits, same as the chip site above**: its node is created unbound at line 46, so a scoped selector
has nothing to reference. (`tests/test_tags_outline.py` is fine — `u1` is already bound.) Neither
file imports `bs4`; add it to each top-of-file import block per the Global Constraint on hoisting
imports.

```python
# tests/test_courses_views.py -- top-of-file imports
from bs4 import BeautifulSoup

# line 46 -- add the binding
unit = ContentNodeFactory(
    course=course, kind="unit", unit_type="lesson", title="Lesson A"
)

# the assertion -- scope it to the outline ROW, not the page
# (its line number shifts when the binding above is added; anchor on the assert)
soup = BeautifulSoup(resp.content.decode(), "html.parser")
row = soup.select_one(f'li[data-unit="{unit.pk}"] span.outline-unit__title')
assert row is not None and "Lesson A" in row.get_text(strip=True)
```

Apply the same shape to `test_filter_hides_non_matching_unit`, scoping on `u1.pk`.

Verify each re-scope is real: on the current build the assertion must still pass, and it must
**fail** if you point the selector at a unit pk that is not in the outline — that is what proves it
now reads the row rather than the whole page.

Then sweep the other outline-rendering suites for **both** unscoped selectors and bare substring
assertions over the outline body, and run them:

```bash
uv run pytest tests/test_unit_marker.py tests/test_outline_collapsible.py tests/test_outline_anchors.py tests/test_tags_outline.py tests/test_courses_views.py -v
```

All must pass.

For the **chip** assertion only, one extra probe proves the original form was genuinely
ambiguous: temporarily point it at `a.resume .unit-kind-chip` and confirm `chip["lang"] == "en"`
passes there too. Do **not** apply that probe to the two substring re-scopes — they assert
`row is not None`, so pointing them at the chip yields `None` and fails, which would read as a
broken re-scope. Their check is the per-site one above: point at a unit pk that is not in the
outline and confirm the assertion fails.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/_resume_card.html templates/courses/outline.html tests/test_courses_views.py tests/test_title_math_markers.py tests/test_unit_marker.py tests/test_tags_outline.py
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
.resume__crumb { color: inherit; }  /* in the DOM contract; inherits __path's scale */
.resume__sep { margin: 0 var(--space-1); }
.resume__title { font-size: 1.15rem; font-weight: 600; color: var(--text-primary); }
.resume:hover { border-color: var(--border-strong); }
.resume:hover .resume__title { text-decoration: underline; }
.resume:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
```

`var(--primary)` for the focus ring is not a free choice — it is what every `:focus-visible` rule
in `app.css` that paints a ring uses (606, 1037, 1069, 1177, 1270, 1306, 1405, 1454, 1707, 1739).
The only exceptions are the two destructive-control rings at 1594 and 1627, which use
`var(--danger)`, and two link rules (361, 401) that paint no outline at all.
There is **no** `--focus-ring` token in this repo, and an unresolvable `var()` invalidates the
whole `outline` shorthand, shipping the card with no ring at all.

Before writing, confirm every other token resolves and **substitute the repo's real name for any
that does not — never invent one**.

- [ ] **Step 2: Verify the tokens resolve**

```bash
grep -nE -- "--(radius-md|border-subtle|border-strong|primary|text-secondary|text-primary|surface-raised|space-1|space-3|space-4|space-5)[[:space:]]*:" core/static/core/css/tokens.css
```

Tokens are **declared in `tokens.css`**, not `app.css` — `app.css` only consumes them, so grepping
`app.css` for declarations returns nothing and proves nothing. Every token used above must appear
here; substitute the repo's real name for any that does not.

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
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

- [ ] **Step 2: Translate**

This repo maintains **both** `locale/en` and `locale/pl` in lockstep — the most recent locale
commit (`555525f4`) touched all four `.po`/`.mo` files. Extracting only `pl` leaves the English
source catalog missing the new msgids, which is exactly the drift that commit repaired.

Fill in the four msgids in `locale/pl/LC_MESSAGES/django.po`:

| msgid | msgstr |
|---|---|
| `Pick up where you left off` | `Wróć tam, gdzie skończyłeś` |
| `Up next` | `Następnie` |
| `Still to do` | `Do zrobienia` |
| `Start the course` | `Rozpocznij kurs` |

`--no-obsolete` is **mandatory**: `docs/development/conventions.md:51` pins the invocation and
line 71 records that the project forbids obsolete `#~` entries —
`tests/test_i18n_po_health.py::test_no_obsolete_entries` enforces it, so omitting the flag turns
Task 11's sweep red with no diagnosis.

Check each entry for a `#, fuzzy` flag — `makemessages` pre-fills fuzzy entries with a **wrong**
translation. Clearing one means **three** edits, not two: delete the `#, fuzzy` flag line, delete
the `#| msgid "<old string>"` previous-msgid line that `msgmerge --previous` writes (it holds the
retired msgid verbatim, so anything grepping for an old string still finds it), and replace the
bogus `msgstr` with the real translation.

- [ ] **Step 3: Compile**

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 4: Verify catalog health and the eyebrow test**

```bash
uv run pytest tests/test_i18n_po_health.py
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

- [ ] **Step 1: Read the current comment — the whole paragraph**

```bash
grep -n "nothing reads updated_at" -B 2 -A 3 courses/views.py
```

- [ ] **Step 2: Correct the false clause, line-count neutral**

The comment currently says reset is safe partly because *"nothing reads updated_at for practice state"*. `build_resume`'s source A now reads it. Replace that clause — keeping the **same number of lines** so line-number citations in surrounding untouched code do not rot:

```python
        # .update() deliberately bypasses save(): it fires neither auto_now on
        # updated_at nor the completed => completed_at invariant. Both are fine --
        # reset does not touch `completed`, and leaving updated_at alone keeps
        # build_resume's source A pointing where the student was. IDOR-safe against
        # other STUDENTS by construction (student=request.user); the cross-COURSE
        # hole is closed by get_node_or_404 above, not by this filter.
```

The clause is the **six-line** comment paragraph Step 1's grep locates, and the replacement is also
six. Count both before committing; a net +1 is exactly the citation rot this rule exists to
prevent. (Do not go looking for it at a fixed line number — it is at 761-766 on master, but
Task 6 has already inserted ~14 lines above it by the time this task runs.)

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
        _complete(units[i], user, 40 - i)
    UnitProgressFactory(student=user, unit=units[6])
    _backdate_progress(units[6], user, timezone.now() - timedelta(days=90))

    # Guard the guard: a POST that 302s to login or 403s would leave the correct
    # build passing and the Step-4 mutant "not firing", sending you to debug the
    # mutant instead of the fixture. Prove the reset actually wrote.
    row = UnitProgress.objects.get(student=user, unit=units[6])
    row.element_state = {"1": {"open": True}}
    row.save()
    _backdate_progress(units[6], user, timezone.now() - timedelta(days=90))

    before = _resume(course, user)
    assert before["state"] == "next" and before["node"].pk == units[5].pk

    resp = client.post(reverse("courses:progress_reset_course", kwargs={"slug": "sf"}))
    assert resp.status_code == 302
    row.refresh_from_db()
    assert row.element_state == {}

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
uv run ruff format .
uv run ruff check --no-cache .
uv run ruff format --check .
```

Run the **formatter** before the check gate: this plan's snippets illustrate structure, not final
formatting, and several would be collapsed onto one line by `ruff format` (e.g. the
`UnitProgress.objects.filter(...)` call in source A fits within the line limit). `--check` alone
would report a diff the plan never tells you to resolve.

Both must be clean. `--no-cache` matters: the `noqa` warning is otherwise cached away, and `format --check` is a separate gate from `check`.

- [ ] **Step 2: No migration, no system-check regression**

```bash
uv run python manage.py makemigrations --check
uv run python manage.py check
```

`makemigrations --check` must report nothing to create — this change adds no model field.

- [ ] **Step 3: Targeted suite**

```bash
uv run pytest tests/test_resume_target.py tests/test_courses_views.py tests/test_title_math_markers.py tests/test_courses_progress.py tests/test_unit_marker.py tests/test_outline_collapsible.py tests/test_outline_anchors.py tests/test_tags_outline.py courses/tests/test_progress_reset.py -v
```

The outline-rendering suites are in this list because the card inserts a new element at the top
of `.outline`; `courses/tests/test_progress_reset.py` because Task 10 edits `progress_reset`.

- [ ] **Step 4: Courses non-e2e sweep**

```bash
uv run pytest tests/ courses/tests/ -m "not e2e" -ra
```

**No `-q`.** `pyproject.toml:49` already sets `addopts = "-q -m 'not e2e'"`, so passing another
makes it `-qq`, which suppresses the short test summary — the very thing the next sentence tells
you to read. Grep the summary line for `failed`: the exit code alone has lied before on a
backgrounded run.

- [ ] **Step 5: Rebase onto master and REGENERATE the `.mo` files**

The spec requires this and nothing else in the plan covers it. Both `locale/en` and `locale/pl`
ship compiled `.mo` binaries; a `.mo` conflict **cannot be text-merged**, and the most recent
locale commit on master (`555525f4`) touched all four catalog files, so concurrent locale work
collides.

```bash
git fetch origin
git rebase origin/master
uv run python manage.py compilemessages
git add locale
git commit -m "i18n(resume): regenerate catalogs after rebase"
```

**Regenerate, never hand-resolve.** If the rebase reports a conflict in a `.mo`, take either
side, finish the rebase, and let `compilemessages` rebuild it from the merged `.po`.

- [ ] **Step 6: Commit any fixes**

```bash
git add -A
git commit -m "chore(resume): definition-of-done fixes"
```

---

## Self-Review

**Spec coverage.** Walked each spec section against the tasks: steps 1–6 → Tasks 1/2/3; sources A–E → Tasks 1/2/3; cross-source tie-break and assembly order → Task 2; `completed_at` anchoring → Task 3; ancestors and inert stamping → Task 4; query budgets → Task 5; enrolled gate and context key → Task 6; DOM contract, four eyebrows, link branching, `lang`, tag independence, marker coverage → Task 7; hover/focus/screenshots → Task 8; four strings → Task 9; **change site 7** → Task 10; DoD → Task 11. All seven enumerated change sites have a task. The spec's non-falsifiable item (source A's `completed=False`) is carried as a comment in Task 2 with an explicit instruction not to falsify it, and the spec's accepted limitation (a submitted quiz with no `UnitProgress` can surface as `next`) is pinned by **Task 3's** `test_submitted_quiz_without_progress_can_surface_as_next` (not Task 2's
similarly-named `test_submitted_quiz_with_no_progress_row_is_not_the_target`, which documents the
opposite case — the status filter keeping a submitted quiz out of the in-flight sources).

**Placeholder scan.** No TBD/TODO, no "add error handling", no "similar to Task N" — each task repeats the code it needs.

**Type consistency.** `build_resume(course, user, tree)` returns `{"node": ContentNode, "state": str, "ancestors": list}` in every task; `done` is a **pk** in Task 3 (the code resolves its index) while `flight` is a **node** — called out in Task 3 Step 3 so an implementer does not mix them; template reads `resume.node`, `resume.state`, `resume.ancestors`, matching Task 1's contract.

**No deviation from the spec's test list.** Both tie tests the spec prescribes ship in Task 2 — `test_exact_cross_source_tie_prefers_the_answered_quiz` and `test_within_source_tie_prefers_the_higher_unit_id`, the latter with the spec's pinned lower-pk-first insertion order — and Task 3 covers the `>=` boundary tie. Do **not** add a duplicate cross-source tie test in Task 3.
