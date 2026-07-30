# Interactive Quiz Preview for Non-Enrolled Viewers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A non-enrolled previewer (staff, course owner, group teacher) gets a live, gradeable quiz that persists nothing, plus a banner explaining why Finish is absent.

**Architecture:** The ephemeral grading path already ships as the authoring "try it" preview (`views_manage.py:1732-1761`). Extract it into `courses/quiz.py` as `parse_attempt` + `ephemeral_quiz_feedback`, then call it from a new previewer branch in `quiz_answer`. The previewer's response — fragment *and* no-JS full page — routes through the existing `_quiz_render_feedback`, which is why the helper returns a `(stand_in, result, validation)` triple rather than a finished context.

**Tech Stack:** Django 5, PostgreSQL, vanilla JS (no framework), pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-07-30-quiz-previewer-interactive-design.md`

## Global Constraints

- **All tooling runs through `uv run`.** Bare `pytest` / `ruff` / `python` are not on PATH. `uv run ruff format --check` too.
- **e2e needs `-m e2e` explicitly** or the tests are silently deselected (pytest exits 5).
- **Never run two pytest invocations at once** — worktrees share the Postgres test database. This worktree's `.env` pins `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_qpi`.
- **Falsify every new test.** After it passes, break the behaviour it guards and confirm it goes RED. A test that cannot go red is a plan failure, not a passing test.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD` (the `make_*` helpers already do).
- **`courses/views.py` comment tripwire:** `tests/test_element_state_write_routes.py` regexes **raw source including comments** and asserts `EXPECTED_WRITE_COUNT = 3` for `courses/views.py`. Patterns include `\.element_state\s*=(?!=)` and `element_state[…] =`. New comments in that file must not contain those shapes.
- **`quiz_finish` keeps `raise PermissionDenied` for non-enrolled users.** Do not touch it.
- **The previewer branch condition is `not is_enrolled(request.user, course)` and nothing else** — never `is_staff`, never `can_manage_course`.
- **Persist nothing on the previewer path:** no `QuizSubmission`, no `QuestionResponse`, no `Attempt`.

---

### Task 1: Extract the ephemeral grader into `courses/quiz.py`

Pure refactor. `views_manage.element_try`'s observable behaviour must not change.

**Files:**
- Modify: `courses/quiz.py` (add imports at top, two new functions after `answer_is_empty`)
- Modify: `courses/views_manage.py:1736-1761`
- Test: `tests/test_ephemeral_quiz_feedback.py` (create)
- Test: `tests/test_element_try.py` (append equivalence tests)

**Interfaces:**
- Consumes: `quiz_feedback_context`, `answer_is_empty`, `answer_to_json`, `QuestionElement` — all already in `courses/quiz.py`.
- Produces:
  - `parse_attempt(post) -> int` (>= 1, never raises)
  - `ephemeral_quiz_feedback(question, answer, attempt) -> (stand_in, result, validation)` where `stand_in` is a `SimpleNamespace` with `.locked: bool`, `.attempt_count: int`, `.latest_answer: Any`; `result` is a mark result or `None`; `validation` is `bool`.

- [ ] **Step 1: Write the failing unit tests for the new helpers**

Create `tests/test_ephemeral_quiz_feedback.py`:

```python
import pytest

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ShortTextQuestionElement
from courses.quiz import ephemeral_quiz_feedback
from courses.quiz import parse_attempt


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"attempt": "1"}, 1),
        ({"attempt": "3"}, 3),
        ({"attempt": "0"}, 1),
        ({"attempt": "-5"}, 1),
        ({"attempt": ""}, 1),
        ({"attempt": "abc"}, 1),
        ({}, 1),
    ],
)
def test_parse_attempt_floors_to_one(raw, expected):
    assert parse_attempt(raw) == expected


@pytest.mark.django_db
def test_empty_answer_is_validation_and_never_locks():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, result, validation = ephemeral_quiz_feedback(q, "", attempt=2)
    assert validation is True
    assert result is None
    # locked=False on the validation branch is load-bearing: quiz_feedback_context
    # copies .locked into the context BEFORE its `if validation: return ctx` exit,
    # so a locked stand-in would emit data-quiz-locked inside the validation panel.
    assert stand_in.locked is False
    assert stand_in.attempt_count == 1  # attempt - 1: an empty answer consumes none


@pytest.mark.django_db
def test_auto_wrong_with_attempts_left_does_not_lock():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, result, validation = ephemeral_quiz_feedback(q, "London", attempt=1)
    assert validation is False
    assert result is not None and result.correct is False
    assert stand_in.locked is False
    assert stand_in.attempt_count == 1


@pytest.mark.django_db
def test_auto_locks_when_correct():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, result, _ = ephemeral_quiz_feedback(q, "Paris", attempt=1)
    assert result.correct is True
    assert stand_in.locked is True


@pytest.mark.django_db
def test_auto_locks_at_max_attempts():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, _, _ = ephemeral_quiz_feedback(q, "London", attempt=3)
    assert stand_in.locked is True


@pytest.mark.django_db
def test_unlimited_attempts_never_locks_on_wrong_answer():
    """max_attempts=None means unlimited. Without the `is not None` guard this
    raises TypeError: '>=' not supported between 'int' and 'NoneType'."""
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=None
    )
    stand_in, _, _ = ephemeral_quiz_feedback(q, "London", attempt=99)
    assert stand_in.locked is False


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_lock_on_first_submit_without_marking(mode):
    q = ShortTextQuestionElement.objects.create(
        stem="Discuss", accepted="", marking_mode=mode
    )
    stand_in, result, validation = ephemeral_quiz_feedback(q, "anything", attempt=1)
    assert validation is False
    assert result is None  # never marked
    assert stand_in.locked is True


@pytest.mark.django_db
def test_latest_answer_is_normalised_via_answer_to_json():
    """rehydrate() is specified against a STORED latest_answer (answer_to_json
    output), not raw build_answer output. A choice question's raw `set` would
    survive set(...) by accident; this pins the normalisation explicitly."""
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=True)
    a = Choice.objects.create(question=q, text="A", is_correct=True)
    b = Choice.objects.create(question=q, text="B", is_correct=False)
    stand_in, _, _ = ephemeral_quiz_feedback(q, {b.pk, a.pk}, attempt=1)
    assert stand_in.latest_answer == sorted([a.pk, b.pk])
    assert isinstance(stand_in.latest_answer, list)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_ephemeral_quiz_feedback.py -q`
Expected: FAIL — `ImportError: cannot import name 'ephemeral_quiz_feedback' from 'courses.quiz'`

- [ ] **Step 3: Add the two helpers to `courses/quiz.py`**

Add to the imports at the top of the file (after `from decimal import Decimal`):

```python
from types import SimpleNamespace
```

Then insert both functions immediately after `answer_is_empty` (which currently ends at line 64):

```python
def parse_attempt(post):
    """1-based attempt number from a client-supplied `attempt` field, floored at 1.

    The ephemeral grading paths (student previewer, authoring 'try it') are
    STATELESS, so the client owns the attempt counter. Junk, absent, and
    out-of-range values all floor to 1; this never raises.

    `attempt` is a RESERVED answer-POST field name, consumed only here. quiz.js
    appends it to every answer POST including the enrolled path, where the server
    ignores it entirely (attempt state comes from the persisted QuestionResponse).
    NO QuestionElement.build_answer implementation may read it -- all ten read only
    choice / answer / blank / slot / row_<pk>. A build_answer that claimed the name
    would silently take a client-controlled value as answer data.
    """
    try:
        return max(1, int(post.get("attempt", "1")))
    except (TypeError, ValueError):
        return 1


def ephemeral_quiz_feedback(question, answer, attempt):
    """Grade `answer` without persisting anything.

    Returns the triple (stand_in, result, validation) -- NOT a finished context --
    so callers can feed it to whichever renderer they need. The student previewer
    path passes stand_in straight to _quiz_render_feedback in place of a
    QuestionResponse; views_manage.element_try builds its own context from it.

    Persists NOTHING: no QuizSubmission, no QuestionResponse, no Attempt.

    Mirrors quiz_answer's state machine exactly:
      - empty answer        -> (stand_in, None, True); mark() is NOT called
      - AUTO                -> mark(); locked iff correct, or
                               (max_attempts is not None and attempt >= max_attempts)
      - NOT_MARKED / REVIEW -> result None, locked True (single submission)

    ONE three-attribute stand-in is built on every branch. `.latest_answer` is
    always present because _quiz_render_feedback's no-JS branch calls
    rehydrate(question, response.latest_answer); a stand-in missing it raises
    AttributeError there. It must be answer_to_json(answer), not the raw
    build_answer payload, because rehydrate is specified against a STORED value.
    """
    latest = answer_to_json(answer)
    if answer_is_empty(answer):
        # locked=False is load-bearing, not a default: quiz_feedback_context copies
        # .locked into the context before its `if validation: return ctx` exit, so a
        # locked stand-in would emit data-quiz-locked inside the VALIDATION panel and
        # freeze the question on an empty submit.
        return (
            SimpleNamespace(
                locked=False, attempt_count=attempt - 1, latest_answer=latest
            ),
            None,
            True,
        )
    is_auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
    result = question.mark(answer) if is_auto else None
    if is_auto:
        # `max_attempts is not None` is mandatory: null means UNLIMITED attempts.
        locked = bool(result.correct) or (
            question.max_attempts is not None and attempt >= question.max_attempts
        )
    else:
        locked = True  # [N]/[R]: single submission
    return (
        SimpleNamespace(locked=locked, attempt_count=attempt, latest_answer=latest),
        result,
        False,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_ephemeral_quiz_feedback.py -q`
Expected: PASS, no failures (15 test items: 7 parse_attempt params + 6 functions, one of which is a 2-way parametrize)

- [ ] **Step 5: Falsify — confirm each guard is load-bearing**

Temporarily make these three edits one at a time, run the suite, confirm RED, then revert:

1. Change `locked=False` on the validation branch to `locked=True` → `test_empty_answer_is_validation_and_never_locks` must FAIL.
2. Drop `question.max_attempts is not None and` from the AUTO guard → `test_unlimited_attempts_never_locks_on_wrong_answer` must FAIL with `TypeError`.
3. Change `latest = answer_to_json(answer)` to `latest = answer` → `test_latest_answer_is_normalised_via_answer_to_json` must FAIL (a `set` is not a sorted `list`).

Run after each: `uv run pytest tests/test_ephemeral_quiz_feedback.py -q`

- [ ] **Step 6: Add the five element_try equivalence tests**

Append to `tests/test_element_try.py`. These are characterization tests — they pass against the CURRENT code and must still pass after Step 7's refactor. Note `_question`'s helper defaults to `max_attempts=1`, so state 1 sets it explicitly or the assertion is vacuous.

The file's existing helpers and idioms (verified, use these verbatim — do not invent new ones): `make_pa(client, "pa")` then `CourseFactory(owner=pa)`, `_quiz_unit(course)`, `_question(unit, *, multiple=False, max_attempts=1)` returning `(el, a, b)` where `a` is correct, and `_url(course, el)`. `CourseFactory` and `make_pa` are already imported at the top of the file.

```python
@pytest.mark.django_db
def test_try_quiz_malformed_attempt_floors_to_one(client):
    """State 1: absent/garbage `attempt` floors to 1. Exercised at max_attempts=3 --
    at the model default of 1, attempt=1/""/5 all lock and render identically, so
    the assertion could not tell a working parse_attempt from a broken one."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, a, b = _question(unit, max_attempts=3)
    for payload in ({"choice": str(b.pk)}, {"choice": str(b.pk), "attempt": "junk"}):
        resp = client.post(_url(course, el), payload)
        body = resp.content.decode()
        assert "2 attempts left" in body, body
        assert "data-quiz-locked" not in body  # floored to 1, so 2 attempts remain


@pytest.mark.django_db
def test_try_quiz_empty_answer_is_validation_no_fetch_header(client):
    """State 2: empty answer -> validation panel, attempt not consumed.

    NAME MATTERS: `test_try_quiz_empty_answer_is_validation` (no suffix) already
    exists at tests/test_element_try.py:180. Appending a same-named function
    rebinds the name, pytest collects only the later definition, and the
    pre-existing test is silently DELETED from the suite. This variant differs by
    omitting the fetch header, so it is worth keeping alongside rather than
    replacing."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, a, b = _question(unit, max_attempts=3)
    resp = client.post(_url(course, el), {"attempt": "1"})
    body = resp.content.decode()
    assert "is-validation" in body
    assert "data-quiz-locked" not in body


@pytest.mark.django_db
def test_try_quiz_auto_wrong_with_attempts_left_withholds(client):
    """State 3: withhold -- no reveal, attempts_left shown, not locked."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, a, b = _question(unit, max_attempts=3)
    resp = client.post(_url(course, el), {"choice": str(b.pk), "attempt": "1"})
    body = resp.content.decode()
    assert "is-incorrect" in body
    assert "2 attempts left" in body
    assert "data-quiz-locked" not in body


@pytest.mark.django_db
def test_try_quiz_auto_wrong_at_max_attempts_locks_and_reveals(client):
    """State 4: locked + reveal."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, a, b = _question(unit, max_attempts=3)
    resp = client.post(_url(course, el), {"choice": str(b.pk), "attempt": "3"})
    body = resp.content.decode()
    assert "is-incorrect" in body
    assert "data-quiz-locked" in body


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_try_quiz_neutral_modes_lock_without_marking(client, mode):
    """State 5: [N]/[R] -> locked, neutral 'recorded' panel, no mark result."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, a, b = _question(unit, max_attempts=3)
    q = el.content_object
    q.marking_mode = mode
    q.save()
    resp = client.post(_url(course, el), {"choice": str(b.pk), "attempt": "1"})
    body = resp.content.decode()
    assert "is-recorded" in body
    assert "data-quiz-locked" in body
    assert "is-incorrect" not in body
```

- [ ] **Step 7: Run them against the CURRENT code — they must already pass**

Run: `uv run pytest tests/test_element_try.py -q`
Expected: PASS. If any fails, the test is wrong about current behaviour — fix the test before refactoring, or the refactor's safety net is calibrated to fiction.

- [ ] **Step 8: Rewire `views_manage.element_try` to the shared helpers**

In `courses/views_manage.py`, replace everything from `from types import SimpleNamespace` (line 1736) through the end of the function (line 1761) with:

```python
    from courses.quiz import ephemeral_quiz_feedback
    from courses.quiz import parse_attempt
    from courses.quiz import quiz_feedback_context

    attempt = parse_attempt(request.POST)
    stand_in, result, validation = ephemeral_quiz_feedback(question, answer, attempt)
    ctx = quiz_feedback_context(
        question, stand_in, result=result, validation=validation
    )
    return render(request, "courses/elements/_quiz_question_feedback.html", ctx)
```

Keep the explanatory comment block above it (lines 1732-1735) — it still describes what this branch does.

- [ ] **Step 9: Run the full element_try + inline-feedback suites**

Run: `uv run pytest tests/test_element_try.py tests/test_choice_inline_feedback.py tests/test_ephemeral_quiz_feedback.py -q`
Expected: PASS, no failures. The five equivalence tests passing before AND after is the proof the extraction is behaviour-preserving.

- [ ] **Step 10: Format and commit**

```bash
uv run ruff format courses/quiz.py courses/views_manage.py tests/test_ephemeral_quiz_feedback.py tests/test_element_try.py
# Lint the TEST files too, in the task that creates them: ruff's F811
# (redefinition of unused name) is what catches a test-name collision that would
# otherwise silently shadow existing coverage. Deferring this to Task 5's
# `ruff check .` surfaces it three commits later, where the natural "fix" is to
# delete the new test rather than notice the old one was being clobbered.
uv run ruff check courses/quiz.py courses/views_manage.py tests/test_ephemeral_quiz_feedback.py tests/test_element_try.py
git add courses/quiz.py courses/views_manage.py tests/test_ephemeral_quiz_feedback.py tests/test_element_try.py
git commit -m "refactor(quiz): extract ephemeral grader into courses/quiz.py

parse_attempt + ephemeral_quiz_feedback now own the stateless grading path that
views_manage.element_try had inline. Returns a (stand_in, result, validation)
triple so the student previewer branch can feed it to _quiz_render_feedback.
No behaviour change: five characterization tests pin element_try's states."
```

---

### Task 2: The previewer answer branch in `quiz_answer`

Server-side only. Question forms still render `disabled` after this task, so nothing reaches the new branch from the UI yet — deliberate ordering, so there is never a commit where live forms 403.

**Files:**
- Modify: `courses/views.py` — `_quiz_render_feedback` (edit inside 1248-1268), `quiz_answer` (edit at 1276-1286; the function runs 1271-1347)
- Test: `tests/test_quiz_previewer_answer.py` (create)

**Interfaces:**
- Consumes: `parse_attempt`, `ephemeral_quiz_feedback` from Task 1.
- Produces: `quiz_answer` accepts previewer POSTs and returns the same fragment/full-page shapes as the student path.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_quiz_previewer_answer.py`:

```python
import pytest

from courses.models import Attempt
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import EnrollmentFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _previewer_quiz(client, *, max_attempts=3, marking_mode="A"):
    """A non-enrolled STAFF viewer + a quiz unit with one question.

    is_staff is what makes can_access_course pass without enrollment:
    accessible_courses is staff | owned | enrolled | taught.
    """
    user = make_login(client, "prev")
    user.is_staff = True
    user.save()
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?",
        accepted="Paris",
        max_attempts=max_attempts,
        marking_mode=marking_mode,
    )
    el = add_element(unit, q)
    return user, unit, el


def _answer_url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _assert_nothing_persisted():
    assert QuizSubmission.objects.count() == 0
    assert QuestionResponse.objects.count() == 0
    assert Attempt.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "Paris", "attempt": "1"},   # correct
        {"answer": "London", "attempt": "1"},  # incorrect, attempts remain
        {"answer": "", "attempt": "1"},        # empty -> validation
        {"answer": "London", "attempt": "9"},  # beyond max_attempts
    ],
)
def test_previewer_answer_persists_nothing(client, payload):
    """The load-bearing invariant. All THREE models are asserted: checking only
    QuizSubmission would miss a partial write."""
    user, unit, el = _previewer_quiz(client)
    resp = client.post(
        _answer_url(unit, el), payload, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200
    _assert_nothing_persisted()


@pytest.mark.django_db
def test_previewer_gets_graded_feedback(client):
    user, unit, el = _previewer_quiz(client)
    resp = client.post(
        _answer_url(unit, el),
        {"answer": "Paris", "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"is-correct" in resp.content


@pytest.mark.django_db
def test_previewer_no_leak_while_attempts_remain(client):
    """max_attempts=3 + attempt=1 is mandatory: at the model default of 1 the
    first wrong answer locks and reveals, so there is no withhold state to test
    and the assertion would be vacuous.

    Asserts the attempts_left NUMBER, not just absence of the answer: an
    off-by-one that showed a previewer "3 attempts left" where a student sees "2"
    would otherwise only be caught by the stand_in unit test, never at the
    endpoint. "2 attempts left" is the exact rendered English string."""
    user, unit, el = _previewer_quiz(client, max_attempts=3)
    resp = client.post(
        _answer_url(unit, el),
        {"answer": "London", "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"Paris" not in resp.content
    assert b"data-quiz-locked" not in resp.content
    assert "2 attempts left" in resp.content.decode()


@pytest.mark.django_db
def test_previewer_dragfill_no_leak_while_attempts_remain(client):
    """The spec names tests/test_questions_2d_quiz_noleak.py too: the 2D reveal
    templates are a different rendering path from short text, so a
    short-text-only no-leak test does not cover them.

    Fixture and POST shape mirrored verbatim from
    tests/test_questions_2d_quiz_noleak.py:22-42 (verified) -- `{"slot": [...]}`,
    max_attempts=2, and "Correct token:" as the reveal marker. Do not invent a
    payload shape for these types."""
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement

    user = make_login(client, "prev2d")
    user.is_staff = True
    user.save()
    unit = make_quiz_unit()
    # The stem's blank-placeholder sentinel is irrelevant here: the withhold branch
    # never renders the stem, so any stem passes. (Measured -- the source fixture at
    # tests/test_questions_2d_quiz_noleak.py:25 uses a ￿-delimited placeholder;
    # this test's two assertions hold either way.)
    q = DragFillBlankQuestionElement.objects.create(
        stem="Cap is X", distractors="Rome", marking_mode="A", max_attempts=2
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = add_element(unit, q)

    resp = client.post(
        _answer_url(unit, el),
        {"slot": ["Rome"], "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    # The status + positive assertions are load-bearing: with only the two "not in"
    # checks plus the persistence check, a 403 body satisfies all three, so the test
    # would stay green through a COMPLETE revert of the feature.
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "is-incorrect" in body
    assert "Correct token:" not in body
    assert "question__reveal" not in body
    _assert_nothing_persisted()


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["A", "N", "R"])
def test_previewer_fragment_covers_every_marking_mode(client, mode):
    """All three marking modes must work at the endpoint, not just AUTO. Without
    this, REVIEW mode has no view-level previewer coverage at all."""
    user, unit, el = _previewer_quiz(client, max_attempts=3, marking_mode=mode)
    resp = client.post(
        _answer_url(unit, el),
        {"answer": "London", "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    if mode == "A":
        assert b"is-incorrect" in resp.content
    else:
        assert b"is-recorded" in resp.content  # [N]/[R]: neutral, never marked
    _assert_nothing_persisted()


@pytest.mark.django_db
def test_previewer_gets_404_for_element_in_another_unit(client):
    """The spec's deliberate 403 -> 404 change. Element resolution now precedes the
    enrollment branch; a future reader who "restores" the old order would revert
    this silently with the whole suite green."""
    user, unit, el = _previewer_quiz(client)
    other = make_quiz_unit(course=unit.course)
    resp = client.post(
        _answer_url(other, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_previewer_gets_404_for_non_question_element(client):
    from courses.models import TextElement

    user, unit, el = _previewer_quiz(client)
    text_el = add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    resp = client.post(
        _answer_url(unit, text_el), {"answer": "x"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_previewer_cannot_finish_a_quiz(client):
    """quiz_finish keeps its enrollment gate. With quiz_answer's gate removed and
    the Finish button hidden only by a template {% if %}, this untested check two
    functions away is the only thing stopping a previewer finishing."""
    user, unit, el = _previewer_quiz(client)
    resp = client.post(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/finish/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_previewer_empty_answer_does_not_lock(client):
    """Regression test for stand_in.locked=False on the validation branch."""
    user, unit, el = _previewer_quiz(client)
    resp = client.post(
        _answer_url(unit, el), {"answer": "", "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"is-validation" in resp.content
    assert b"data-quiz-locked" not in resp.content


@pytest.mark.django_db
def test_previewer_no_js_locked_state_reaches_render_state(client):
    """Regression test for the st["locked"] fix, asserted on the CONTEXT.

    It cannot be asserted on the markup in this task: the template still passes
    quiz_submitted=read_only, and read_only is True for every previewer, so the
    inputs render `disabled` whether or not st["locked"] is set. The markup
    assertion only becomes discriminating after Task 3 rewires line 12, and it
    lives there (test_previewer_locked_question_freezes_inputs).

    Without the fix, render_states[el.pk]["locked"] is False for a [N]/[R]
    question that the fragment has already marked locked -- which after Task 3
    means "Answer recorded" beside a LIVE Check button, resubmittable forever.
    """
    user, unit, el = _previewer_quiz(client, marking_mode="N")
    resp = client.post(_answer_url(unit, el), {"answer": "whatever"})  # no fetch header
    assert resp.status_code == 200
    assert b"is-recorded" in resp.content
    assert resp.context["render_states"][el.pk]["locked"] is True


@pytest.mark.django_db
def test_previewer_no_js_re_render_carries_unit_nav(client):
    """Previewer twin of test_crumb_survives_the_no_js_quiz_answer_re_render.
    A hand-rolled branch that forgot build_unit_nav would ship a nav-less page.

    The unit MUST hang off a parent part and the assertion MUST be the part
    title. `_unit_crumbs.html:16` emits <nav class="unit-crumbs"> unconditionally,
    so `assert b"unit-crumbs" in content` is true even with unit_nav absent
    entirely -- verified. Only the {% for a in unit_nav.ancestors %} loop depends
    on unit_nav, and a parentless unit leaves that loop empty. This mirrors why
    the test it twins asserts `part.title in nav.get_text()`.
    """
    from bs4 import BeautifulSoup

    from tests.factories import ContentNodeFactory

    user, unit, el = _previewer_quiz(client)
    part = ContentNodeFactory(
        course=unit.course, parent=None, kind="part", title="Part One"
    )
    unit.parent = part
    unit.save()

    resp = client.post(_answer_url(unit, el), {"answer": "London"})
    assert resp.status_code == 200
    nav = BeautifulSoup(resp.content, "html.parser").select_one("nav.unit-crumbs")
    assert nav is not None
    assert "Part One" in nav.get_text()


@pytest.mark.django_db
def test_non_privileged_user_still_denied(client):
    """Access invariant, LOWER bound. A plain authenticated user -- not enrolled,
    not staff, not owner, not a group teacher -- must never reach the ephemeral
    branch. This pins the accessible_courses invariant that makes a
    client-supplied `attempt` safe."""
    make_login(client, "outsider")
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)
    resp = client.post(
        _answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_enrolled_staff_still_persists(client):
    """Access invariant, UPPER bound -- the one a mis-keyed branch breaks silently.
    No existing enrolled-path quiz test asserts a row was written for a privileged
    actor, so a branch keyed on is_staff (or can_manage_course) instead of
    `not is_enrolled` would pass the whole suite while stopping grade capture for
    every enrolled teacher."""
    user = make_login(client, "staffstu")
    user.is_staff = True
    user.save()
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    el = add_element(unit, q)
    resp = client.post(
        _answer_url(unit, el),
        {"answer": "London"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert QuizSubmission.objects.filter(student=user, unit=unit).count() == 1
    assert QuestionResponse.objects.count() == 1
    assert Attempt.objects.count() == 1


@pytest.mark.django_db
def test_enrolled_path_ignores_client_supplied_attempt(client):
    """`quiz.js` will send a client-controlled `attempt` on EVERY answer POST.
    Today quiz_answer never reads it. Once parse_attempt lives in courses/quiz.py,
    plumbing it into the shared path looks like an obvious tidy-up -- and would let
    a student POST attempt=99 to force locked=True and the reveal. Pin it."""
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    el = add_element(unit, q)
    resp = client.post(
        _answer_url(unit, el),
        {"answer": "London", "attempt": "99"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = resp.content.decode()
    assert "2 attempts left" in body
    assert "Paris" not in body
    assert QuestionResponse.objects.get().attempt_count == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_previewer_answer.py -q`
Expected: the previewer tests FAIL with 403 (the branch does not exist yet). Measured: **19 collected, 15 FAILED, 4 passed.**

Exactly **four** tests should already PASS — they pin behaviour that must survive: `test_non_privileged_user_still_denied`, `test_enrolled_staff_still_persists`, `test_enrolled_path_ignores_client_supplied_attempt`, and `test_previewer_cannot_finish_a_quiz` (`quiz_finish` is untouched by this task, so a previewer already gets 403 there).

`test_previewer_dragfill_no_leak_while_attempts_remain` **must be RED here, and that is the point.** Its `assert resp.status_code == 200` is precisely what stops it passing vacuously against the pre-change 403 — its other assertions are all negatives that an error page satisfies. If you see it red at this step, that is correct; do **not** "reconcile" it by deleting the status assertion, which would restore the vacuous version.

- [ ] **Step 3: Add `st["locked"]` to `_quiz_render_feedback`**

In `courses/views.py`, inside `_quiz_render_feedback`'s no-JS branch, add ONE line after `st["feedback_html"] = fragment`:

```python
    st = ctx["render_states"].get(element.pk)
    if st is not None:
        st["feedback_html"] = fragment
        # A previewer has responses == {}, so build_quiz_context derives locked=False
        # for every question while the injected fragment still emits data-quiz-locked
        # -- "Answer recorded" beside a live Check button. True no-op for a student:
        # writes the value build_quiz_context already derived from the saved response.
        st["locked"] = response.locked
        selected, submitted = rehydrate(question, response.latest_answer)
        st["selected_ids"] = selected
        st["submitted_values"] = submitted
```

Do **not** also write `st["attempts_left"]`. On the enrolled validation branch `quiz_feedback_context` returns early with `attempts_left=None`, which would clobber the real number `build_quiz_context` derived — and it is dead in quiz mode anyway.

- [ ] **Step 4: Move element resolution above the enrollment check, and add the branch**

In `quiz_answer`, replace this (lines 1276-1286):

```python
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied  # previewers cannot persist

    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")
```

with:

```python
    if not can_access_course(request.user, course):
        raise PermissionDenied

    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    if not is_enrolled(request.user, course):
        # Previewer: grade ephemerally, persist NOTHING (no QuizSubmission, no
        # QuestionResponse, no Attempt). Returns before the transaction below, so
        # no write path is reachable.
        #
        # SAFETY INVARIANT for the client-supplied `attempt`: can_access_course
        # above delegates to accessible_courses (courses/access.py), which is
        # staff | owned | enrolled | taught. So reaching here implies staff, owner,
        # or group teacher -- a plain student is either enrolled (persisted path
        # below) or already denied. If accessible_courses ever widens, this becomes
        # a student-reachable answer oracle. Pinned by
        # tests/test_quiz_previewer_answer.py::test_non_privileged_user_still_denied.
        #
        # Resolution now precedes this branch, so a previewer gets the student's 404
        # rules instead of a blanket 403. Deliberate.
        attempt = parse_attempt(request.POST)
        stand_in, result, validation = ephemeral_quiz_feedback(
            question, question.build_answer(request.POST), attempt
        )
        return _quiz_render_feedback(
            request,
            node,
            element,
            question,
            stand_in,
            result=result,
            validation=validation,
        )
```

Add the imports near the other `courses.quiz` imports at the top of `courses/views.py`:

```python
from courses.quiz import ephemeral_quiz_feedback
from courses.quiz import parse_attempt
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_quiz_previewer_answer.py -q`
Expected: PASS, no failures

- [ ] **Step 6: Falsify the two regression tests**

1. Revert `st["locked"] = response.locked` → `test_previewer_no_js_locked_state_reaches_render_state` must FAIL (`locked` is `False`). Note this is a **context** assertion by design — the markup cannot discriminate until Task 3, see that test's docstring.
2. Change the branch condition to `if request.user.is_staff:` → `test_enrolled_staff_still_persists` must FAIL (the enrolled staff user would stop persisting).

Run after each: `uv run pytest tests/test_quiz_previewer_answer.py -q`. Revert both.

- [ ] **Step 7: Confirm no regression in the existing quiz suite**

Run: `uv run pytest tests/test_quiz_answer.py tests/test_quiz_noleak.py tests/test_questions_2d_quiz_noleak.py tests/test_quiz_finish.py tests/test_quiz_resume.py -q`
Expected: PASS

- [ ] **Step 8: Format and commit**

```bash
uv run ruff format courses/views.py tests/test_quiz_previewer_answer.py
uv run ruff check courses/views.py
git add courses/views.py tests/test_quiz_previewer_answer.py
git commit -m "feat(quiz): grade previewer answers ephemerally instead of 403ing

quiz_answer now branches to ephemeral_quiz_feedback for non-enrolled viewers,
persisting nothing. Element resolution moves above the enrollment check so a
previewer gets the student's 404 rules. _quiz_render_feedback learns
st[\"locked\"] so the no-JS re-render freezes a locked question."
```

---

### Task 3: `previewing` flag, live forms, and the preview banner

**Files:**
- Modify: `courses/views.py` — `build_quiz_context` (~1133-1213)
- Modify: `templates/courses/_quiz_article.html`
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_quiz_previewer_render.py` (create)
- Test: `tests/test_quiz_views.py:61-63` (the assertions; the test's `def` is at :53)

**Interfaces:**
- Consumes: nothing new.
- Produces: context key `previewing: bool`; template hook `data-quiz-preview-notice`.

- [ ] **Step 1: Write the failing render tests**

Create `tests/test_quiz_previewer_render.py`:

```python
import pytest
from django.template.loader import render_to_string

from courses.models import QuizSubmission
from courses.views import build_quiz_context
from tests.factories import EnrollmentFactory
from tests.factories import ExtendedResponseQuestionElementFactory
from tests.factories import MatchPairFactory
from tests.factories import MatchPairQuestionElementFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _previewer(client):
    user = make_login(client, "prev")
    user.is_staff = True
    user.save()
    return user


def _quiz_url(unit):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"


@pytest.mark.django_db
def test_previewer_sees_banner_and_no_finish(client):
    _previewer(client)
    unit = make_quiz_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    ))
    resp = client.get(_quiz_url(unit))
    assert resp.status_code == 200
    assert b"data-quiz-preview-notice" in resp.content
    assert b"Finish quiz" not in resp.content
    assert not QuizSubmission.objects.filter(unit=unit).exists()


@pytest.mark.django_db
def test_previewer_control_level_inputs_are_live(client):
    """Family 1: `disabled` sits on the <input>/<button> itself."""
    _previewer(client)
    unit = make_quiz_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    ))
    body = client.get(_quiz_url(unit)).content.decode()
    field = body.split('name="answer"')[1][:200]
    assert "disabled" not in field


@pytest.mark.django_db
def test_previewer_fieldset_wrapped_inputs_are_live(client):
    """Family 2: `disabled` sits on a wrapping <fieldset>
    (matchpairquestionelement.html:7). A test that only checks the <input> is
    vacuous for every 2D/grid type.

    MatchPair is used rather than MultiGrid because there is no
    MultiGridQuestionElementFactory (verified); DragToImage would also work but
    drags in a MediaAsset via SubFactory."""
    _previewer(client)
    unit = make_quiz_unit()
    q = MatchPairQuestionElementFactory()
    MatchPairFactory(question=q)
    add_element(unit, q)
    body = client.get(_quiz_url(unit)).content.decode()
    fieldset = body.split("<fieldset")[1][:120]
    assert "disabled" not in fieldset


@pytest.mark.django_db
def test_previewer_bare_textarea_is_live(client):
    """Family 3: extended response has NO wrapping fieldset, so it is missed by
    both of the other checks."""
    _previewer(client)
    unit = make_quiz_unit()
    add_element(unit, ExtendedResponseQuestionElementFactory())
    body = client.get(_quiz_url(unit)).content.decode()
    textarea = body.split("<textarea")[1][:250]
    assert "disabled" not in textarea


@pytest.mark.django_db
def test_banner_renders_once_outside_every_slide(client):
    """slideshow.js shows one .slide at a time, so a banner inside the loop would
    render per-slide, and one inside the first slide would vanish on advance."""
    from courses.models import SlideBreakElement

    _previewer(client)
    unit = make_quiz_unit()
    add_element(unit, ShortTextQuestionElement.objects.create(
        stem="Q1?", accepted="a"
    ))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, ShortTextQuestionElement.objects.create(
        stem="Q2?", accepted="b"
    ))
    body = client.get(_quiz_url(unit)).content.decode()
    assert body.count("data-quiz-preview-notice") == 1
    assert body.index("data-quiz-preview-notice") < body.index('class="slide"')


@pytest.mark.django_db
def test_enrolled_student_sees_finish_and_no_banner(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    add_element(unit, ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    ))
    resp = client.get(_quiz_url(unit))
    assert b"Finish quiz" in resp.content
    assert b"data-quiz-preview-notice" not in resp.content


@pytest.mark.django_db
def test_previewer_locked_question_freezes_inputs(client):
    """The MARKUP half of Task 2's st["locked"] fix. It lives here, not in Task 2:
    until line 12 passes quiz_submitted (not read_only), read_only=True disables a
    previewer's inputs regardless of st["locked"], so the assertion could not fail
    there. Now that inputs are live by default, `locked` is the only thing that can
    freeze them -- and it must, or a previewer resubmits an [N]/[R] question forever.
    """
    _previewer(client)
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Discuss", accepted="", marking_mode="N"
    )
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, {"answer": "whatever"})  # no fetch header -> full page
    body = resp.content.decode()
    assert "is-recorded" in body
    field = body.split('name="answer"')[1][:200]
    assert "disabled" in field


@pytest.mark.django_db
def test_submitted_quiz_still_freezes_inputs(client):
    """Rendered directly: quiz_unit redirects to results before rendering a
    SUBMITTED quiz (views.py:1224), so a GET would return 302 and assert nothing.

    Honest scope: read_only = quiz_submitted or previewing, so read_only superset
    quiz_submitted -- there is NO context state with quiz_submitted=True and
    read_only=False. This passes whether line 12 says `read_only` or
    `quiz_submitted`. It guards "a SUBMITTED quiz still freezes"; the test that
    actually falsifies the argument-source change is the previewer-liveness one
    above, since previewing=True is the only discriminating state.
    """
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    add_element(unit, ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    ))
    QuizSubmission.objects.create(student=user, unit=unit, status="submitted")
    ctx = build_quiz_context(unit, user)
    body = render_to_string("courses/_quiz_article.html", ctx)
    field = body.split('name="answer"')[1][:200]
    assert "disabled" in field
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_previewer_render.py -q`
Expected: FAIL — banner assertions fail (no `data-quiz-preview-notice`), liveness assertions fail (inputs still `disabled`).

`test_previewer_locked_question_freezes_inputs` will already PASS here, vacuously: until the `render_element` line is rewired, `read_only=True` disables a previewer's inputs regardless of `locked`. That green is expected, not a sign the work is done — Step 6's Mutation B is what actually exercises it.

All factories referenced above were verified to exist. If a question type fails to render for want of child rows, add them via the matching child factory (`MatchPairFactory`, `DragZoneFactory`) — the fieldset is emitted regardless, so the assertion holds either way. To re-check the roster:
`uv run python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); django.setup(); import tests.factories as f; print([n for n in dir(f) if n.endswith('Factory')])"`

- [ ] **Step 3: Add `previewing` to `build_quiz_context`**

In `courses/views.py`, change the submission block (~1133-1135) to hoist the enrollment result:

```python
    submission = None
    # Hoisted: is_enrolled was already called here and its result discarded.
    # `previewing` must not cost a second Enrollment query -- this builder is
    # otherwise carefully prefetched.
    enrolled = is_enrolled(user, node.course)
    if enrolled:
        submission, _ = QuizSubmission.objects.get_or_create(student=user, unit=node)
```

Then replace the `read_only` entry in the `ctx` dict (currently lines 1201-1204, comment included) with:

```python
        # A non-enrolled previewer gets LIVE question forms: their answers are graded
        # ephemerally by quiz_answer and nothing is persisted. `read_only` now gates
        # exactly ONE thing -- the Finish form -- and does NOT mean "the page is
        # inert". Inputs freeze on `quiz_submitted` alone.
        "previewing": not enrolled,
        "read_only": quiz_submitted or not enrolled,
```

- [ ] **Step 4: Add the banner and rewire `quiz_submitted` in the template**

In `templates/courses/_quiz_article.html`. **Line 1 needs no edit** — it is already `{% load i18n static courses_extras %}`, and `get_current_language` ships in the `i18n` library. Do not add another `{% load %}`.

After the `<h1 class="lesson-unit__title">` on line 5, insert:

```html
  {% if previewing %}
    {% get_current_language as LANGUAGE_CODE %}
    {% comment %}Rendered ONCE, outside the {% for slide %} loop: slideshow.js shows
    one .slide at a time, so a banner inside the loop would repeat per slide and one
    inside the first slide would vanish when the previewer advances.

    lang="{{ LANGUAGE_CODE }}" is required because this sits inside
    <article lang="{{ course.language }}"> -- without it a Polish UI string is
    announced as English inside an English course. LANGUAGE_CODE must come from
    {% get_current_language %}; the i18n context processor is not enabled.

    No role="status": a server-rendered live region announces nothing (live regions
    only report post-insertion mutations), and role="status" would OVERRIDE <aside>'s
    implicit complementary role, removing it from landmark navigation.{% endcomment %}
    <aside class="alert alert--info" data-quiz-preview-notice
           lang="{{ LANGUAGE_CODE }}" aria-label="{% trans 'Preview notice' %}">
      <strong>{% trans "Preview" %}</strong> —
      {% trans "you are not enrolled in this course, so your answers are not recorded and the quiz cannot be finished." %}
    </aside>
  {% endif %}
```

Then on the `{% render_element … %}` line inside the `{% for slide in slides %}` loop (line 12 *before* the banner insertion; roughly line 32 after it — locate it by content, not by number), change `quiz_submitted=read_only` to `quiz_submitted=quiz_submitted`:

```html
          {% render_element el mode="quiz" feedback_for_pk=el.pk quiz_submitted=quiz_submitted action_url=el|quiz_answer_url locked=st.locked selected_ids=st.selected_ids submitted_values=st.submitted_values attempts_left=st.attempts_left feedback_html=st.feedback_html %}
```

Leave the `{% if not read_only %}` Finish block untouched.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_quiz_previewer_render.py -q`
Expected: PASS, no failures

- [ ] **Step 6: Falsify — TWO separate mutations, because one test needs the other**

**Mutation A.** Revert the `render_element` line to `quiz_submitted=read_only`. `test_previewer_control_level_inputs_are_live`, `test_previewer_fieldset_wrapped_inputs_are_live`, and `test_previewer_bare_textarea_is_live` must all FAIL. Revert.

**Mutation B.** Temporarily delete `st["locked"] = response.locked` from `_quiz_render_feedback` (added in Task 2). `test_previewer_locked_question_freezes_inputs` must FAIL. Revert.

Mutation B is required and is **not** covered by Mutation A: under A that test stays GREEN (a previewer's `read_only` disables the input anyway), and its real falsifier could not run in Task 2 because the test did not exist there yet. Without this step the plan's "falsify every new test" constraint is unmet for exactly one test.

Run after each: `uv run pytest tests/test_quiz_previewer_render.py -q`

- [ ] **Step 7: Update the one existing test that pins the old behaviour**

In `tests/test_quiz_views.py`, replace lines 61-63:

```python
    # Read-only preview: no Finish button, inputs disabled (no live forms that 403).
    assert b"Finish quiz" not in resp.content
    assert b"disabled" in resp.content
```

with:

```python
    # Live preview: no Finish button (nothing to submit), but the question forms are
    # LIVE -- quiz_answer grades a previewer's answers ephemerally. Asserted against
    # the question input specifically: a bare `b"disabled" not in content` search
    # would be vacuous, since unrelated markup elsewhere may carry the attribute.
    assert b"Finish quiz" not in resp.content
    assert b"data-quiz-preview-notice" in resp.content
    field = resp.content.decode().split('name="answer"')[1][:200]
    assert "disabled" not in field
```

Leave `assert not QuizSubmission.objects.filter(unit=unit).exists()` unchanged — it is load-bearing.

- [ ] **Step 8: Regenerate the i18n catalogues**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

**Only `locale/pl` gets translations. `locale/en` msgstrs stay empty** — that is deliberate here: `tests/test_i18n_po_health.py::test_pl_has_no_untranslated_msgid` is pl-only by design, because English falls back to the msgid. Writing `Podgląd` into `locale/en` would serve Polish to English users and **no guard would catch it**.

**There are only TWO new msgids, not three.** `msgid "Preview"` already exists — `locale/pl/LC_MESSAGES/django.po:5745` with `msgstr "Podgląd"` (and `locale/en/…:5524`), from `editor.html:93`. `makemessages` will only append a new `#:` reference line to it; leave its msgstr alone.

In `locale/pl/LC_MESSAGES/django.po` only, fill in the two genuinely new entries:

- `Preview notice` → `Informacja o podglądzie`
- the sentence → `nie jesteś zapisany/a na ten kurs, więc Twoje odpowiedzi nie są zapisywane, a quizu nie można zakończyć.`

Then **check for `#, fuzzy` markers.** `makemessages` pre-fills fuzzy entries from unrelated msgids. Clearing one means deleting **BOTH** the `#, fuzzy` line and the `#| msgid` line above the entry.

```bash
grep -n "fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
uv run python manage.py compilemessages
uv run pytest tests/test_i18n_po_health.py -q
```

Expected: no fuzzy entries remain; `test_i18n_po_health.py` PASSES.

- [ ] **Step 9: Run the affected suites**

Run: `uv run pytest tests/test_quiz_views.py tests/test_quiz_render.py tests/test_quiz_previewer_render.py tests/test_slideshow_context.py -q`
Expected: PASS

- [ ] **Step 10: Format and commit**

```bash
uv run ruff format courses/views.py tests/test_quiz_previewer_render.py tests/test_quiz_views.py
git add courses/views.py templates/courses/_quiz_article.html tests/test_quiz_previewer_render.py tests/test_quiz_views.py locale/
git commit -m "feat(quiz): live forms + preview banner for non-enrolled viewers

build_quiz_context gains `previewing`; _quiz_article.html now passes
quiz_submitted (not read_only) to the question templates, so a previewer's inputs
render live. read_only survives to gate the Finish form only. A banner renders
once outside the slide loop explaining that answers are not recorded."
```

---

### Task 4: Client-side attempt counter and widened lock selectors

**Files:**
- Modify: `courses/static/courses/js/quiz.js:29-50`
- Modify: `courses/static/courses/js/editor.js:261`

**Interfaces:**
- Consumes: `parse_attempt` on the server reads the `attempt` field this task starts sending.
- Produces: no Python interface.

- [ ] **Step 1: Add the attempt counter and widen the lock selector in `quiz.js`**

Replace the `forEach` block at lines 29-50 with:

```javascript
  document.querySelectorAll("form.question__form").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      // The ephemeral (previewer) grading path is STATELESS, so the client owns the
      // attempt counter -- mirrors editor.js's authoring "try it" preview. No server
      // template emits data-attempts-made; it is created here on the first response.
      // The enrolled path ignores `attempt` entirely (its count comes from the
      // persisted QuestionResponse), so this is inert for students.
      const qEl = form.closest("[data-question]");
      const made = qEl
        ? parseInt(qEl.getAttribute("data-attempts-made") || "0", 10)
        : 0;
      const body = new FormData(form);
      body.append("attempt", String(made + 1));
      const res = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
        body: body,
      });
      if (res.status === 409) {
        window.location.reload();
        return;
      }
      const box = form.querySelector("[data-question-feedback]");
      box.innerHTML = await res.text();
      // An empty-answer validation doesn't consume an attempt; everything else does.
      if (qEl && !box.querySelector(".is-validation")) {
        qEl.setAttribute("data-attempts-made", String(made + 1));
      }
      // Disable inputs on ANY terminal state (correct, exhausted-incorrect, or
      // [N]/[R] recorded) — the server emits [data-quiz-locked] iff response.locked.
      // The selector covers three shapes: control-level (input/button), the
      // fieldset the 2D/grid types wrap their controls in, and the extended-response
      // <textarea>, which has NO wrapping fieldset and was previously left editable
      // beside "Submitted for review" until the next page load — on the ENROLLED
      // path too. `select` is defensive (those already sit inside the fieldset).
      if (box.querySelector("[data-quiz-locked]")) {
        form
          .querySelectorAll("input, button, select, textarea, fieldset")
          .forEach((n) => (n.disabled = true));
      }
      typeset(box);
    });
  });
```

Leave the Finish flush block (`quiz.js` 52-76; its inner `Promise.all` is 65-73) untouched — it deliberately does not append `attempt`.

- [ ] **Step 2: Widen the twin selector in `editor.js`**

At `courses/static/courses/js/editor.js:261`, change:

```javascript
          qEl.querySelectorAll("input, button[type=submit]").forEach(function (n) {
```

to:

```javascript
          // Same three shapes as quiz.js's freeze; kept in lockstep deliberately.
          // The [type=submit] qualifier stays: this root is the whole [data-question]
          // element, not the form, so bare `button` could reach controls the quiz
          // freeze never touches.
          qEl
            .querySelectorAll("input, button[type=submit], select, textarea, fieldset")
            .forEach(function (n) {
```

- [ ] **Step 3: Verify the JS parses**

```bash
uv run python -c "import pathlib; [pathlib.Path(p).read_text(encoding='utf-8') for p in ['courses/static/courses/js/quiz.js','courses/static/courses/js/editor.js']]; print('read ok')"
node --check courses/static/courses/js/quiz.js && node --check courses/static/courses/js/editor.js
```

Expected: `read ok`, then no output from `node --check` (success). If `node` is unavailable, skip the syntax check — the e2e test in Task 6 is the real gate.

- [ ] **Step 4: Confirm no Python-side regression**

Run: `uv run pytest tests/test_quiz_previewer_answer.py tests/test_quiz_answer.py -q`
Expected: PASS (the server already floors a missing `attempt` to 1, so nothing here changes server behaviour)

- [ ] **Step 5: Run the e2e suites that actually exercise this JavaScript**

**This step is the only regression coverage these two files get.** The `quiz.js` submit handler and the `editor.js` "try it" freeze are exercised *exclusively* by e2e; `pyproject.toml` sets `addopts = -m 'not e2e'`, so Task 5's "full unit suite" run excludes every test that loads them. 22 e2e modules touch `question__form` / `data-quiz-locked` / `data-scope="preview"` — notably `tests/test_e2e_quiz.py:141`, which asserts `input[name='answer']` is disabled after lock, and `tests/test_e2e_questions.py:421`.

Run: `uv run pytest tests/test_e2e_quiz.py tests/test_e2e_quiz_finish.py tests/test_e2e_questions.py tests/test_e2e_questions_2d.py tests/test_e2e_editor.py -m e2e -q`
Expected: PASS. `-m e2e` is mandatory — without it pytest deselects everything and exits 5, which reads as success.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/quiz.js courses/static/courses/js/editor.js
git commit -m "feat(quiz-js): client attempt counter + widen the lock selector

quiz.js now sends `attempt` from data-attempts-made (client-owned, since the
ephemeral path is stateless) and skips the increment on a validation response.
Both freeze selectors widen to input/button/select/textarea/fieldset, fixing a
pre-existing defect where a locked extended-response textarea stayed editable on
the enrolled path. editor.js is widened in the same commit so the twins do not
drift."
```

---

### Task 5: Update the five stale prose sites

None of these change behaviour; all of them are now false or misleading. Leaving them is worse than the original bug, because the next reader trusts them.

**Files:**
- Modify: `courses/views.py:860-866` (the `check_answer` comment)
- Modify: `tests/test_unit_edit_link.py:328`
- Modify: `tests/test_unit_nav_render.py:800`
- (`courses/views.py:1201-1203` and `tests/test_quiz_views.py:61` were already rewritten in Task 3)

- [ ] **Step 1: Append a clarifying clause to the `check_answer` comment**

At `courses/views.py:860-866`. **Do NOT narrow `seen/quiz` to `seen`, and do not touch "those two".** The comment's sense of *ignore* is **persistence** — "so authors don't pollute their own SCROLL-tracking and quiz analytics" — and under that sense it stays TRUE: the previewer quiz path persists nothing, so previewer quiz data still never reaches analytics. Narrowing it would delete an accurate statement.

Change the sentence:

```python
    # students. This deliberately diverges from seen/quiz, which ignore previewers so
    # authors don't pollute their own SCROLL-tracking and quiz analytics. It is those
    # two specifically, NOT progress writes in general: an explicit "Mark as done"
```

to:

```python
    # students. This deliberately diverges from seen/quiz, which ignore previewers so
    # authors don't pollute their own SCROLL-tracking and quiz analytics -- quiz now
    # SERVES previewers live forms, but still records nothing for them. It is those
    # two specifically, NOT progress writes in general: an explicit "Mark as done"
```

- [ ] **Step 2: Fix the two test docstrings**

At `tests/test_unit_edit_link.py:328` and `tests/test_unit_nav_render.py:800`, both docstrings justify enrolling the actor by claiming `quiz_answer` raises `PermissionDenied` for previewers. Read each, then replace that claim with:

> the actor is enrolled so this exercises the PERSISTED answer path; a non-enrolled viewer would take `quiz_answer`'s ephemeral previewer branch instead, which writes nothing.

Keep the surrounding docstring text and the enrollment itself unchanged.

- [ ] **Step 3: Verify the comment tripwire did not fire**

`tests/test_element_state_write_routes.py` regexes raw source including comments and asserts `EXPECTED_WRITE_COUNT = 3` for `courses/views.py`.

Run: `uv run pytest tests/test_element_state_write_routes.py -q`
Expected: PASS

- [ ] **Step 4: Run the full unit suite**

Run: `uv run pytest -q -x`
Expected: PASS. Note the exit code — a `grep`-piped run hides pytest's verdict line, so read the exit code directly (`echo $?` → 0).

- [ ] **Step 5: Lint and format check**

```bash
uv run ruff format --check .
uv run ruff check .
```

Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py tests/test_unit_edit_link.py tests/test_unit_nav_render.py
git commit -m "docs(quiz): update prose that described the old previewer behaviour

Five sites asserted that quiz rejects previewers. The check_answer comment keeps
its seen/quiz persistence contrast (still true -- the previewer path persists
nothing) and gains a clause noting quiz now serves live forms."
```

---

### Task 6: e2e and UI verification

**Files:**
- Test: `tests/test_e2e_quiz_previewer.py` (create)

- [ ] **Step 1: Write the e2e test**

Read `tests/test_e2e_quiz.py` first for this repo's e2e conventions. Two of them are load-bearing and both were verified:

1. **The `DJANGO_ALLOW_ASYNC_UNSAFE` fixture is mandatory.** All **75 of 75** `tests/test_e2e_*.py` modules define it themselves, and **nothing in `conftest.py` or `tests/conftest.py` sets it**. This test calls the ORM under Playwright's sync API, so without the fixture the first ORM call raises `SynchronousOnlyOperation` — and Step 2 runs this file *alone*, so no sibling module can set it first.
2. **No existing login helper produces the user this test needs.** `test_e2e_quiz.py`'s `_make_student` yields a plain user (`is_staff = False`) and gets access by making them the course **owner and enrolling them** — enrolled is exactly what we must not be. `tests/test_e2e_editor._make_pa_user` builds a Platform Admin **group** member, which per `courses/access.py:17-29` is *not* `is_staff`, *not* the owner, and *not* a group teacher — so `can_access_course` returns `False` and the page 403s. **Do not reuse `_make_pa_user` here.** Set `is_staff` explicitly, as below.

Create `tests/test_e2e_quiz_previewer.py`:

```python
import os

import pytest

from courses.models import Attempt
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import TEST_PASSWORD
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_quiz_unit
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    """Mandatory: all 75 sibling e2e modules define this and no conftest does.
    Without it, ORM calls under Playwright's sync API raise
    SynchronousOnlyOperation."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def test_previewer_answers_quiz_and_nothing_persists(live_server, page):
    """Drives the REAL gesture (type + click), never page.evaluate -- an e2e that
    bypasses the gesture ships broken UX green."""
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    add_element(unit, q)  # not bound: ruff F841 flags an unused local

    # Non-enrolled but access-bearing: is_staff is what makes can_access_course
    # pass without an Enrollment. No existing e2e helper yields this combination.
    user = make_verified_user(
        username="e2e_qprev", email="e2e_qprev@test.example.com"
    )
    user.is_staff = True
    user.save()

    # Log in through the real form. The locators MUST be scoped to the login form:
    # templates/allauth/layouts/entrance.html renders a `lang-switch` form with one
    # <button type="submit"> per language, so the page has THREE submit buttons and
    # page.click('button[type="submit"]') (legacy, non-strict) clicks the FIRST --
    # the "EN" language button -- which POSTs set_ui_language, reloads, and wipes the
    # filled fields. The failure then surfaces misleadingly at the banner assertion.
    # Block copied verbatim from tests/test_e2e_editor.py:44-48.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("e2e_qprev")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()

    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/quiz/")
    assert page.locator("[data-quiz-preview-notice]").is_visible()

    page.fill('input[name="answer"]', "London")
    page.click('form.question__form button[type="submit"]')
    page.wait_for_selector("[data-question-feedback] .is-incorrect")

    assert QuizSubmission.objects.count() == 0
    assert QuestionResponse.objects.count() == 0
    assert Attempt.objects.count() == 0
```

Do **not** "simplify" the scoped locators back to `page.fill(...)` / `page.click('button[type="submit"]')`. Those selectors *match* — they just match the language switcher first, so the failure looks like a feature bug rather than a login bug. `tests/test_e2e_editor.py:41-43` carries the same warning in a comment.

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_quiz_previewer.py -m e2e -q`
Expected: PASS. **`-m e2e` is mandatory** — without it pytest deselects everything and exits 5, which reads as success.

- [ ] **Step 3: Capture screenshots in both themes**

Add a temporary screenshot step (or use an existing screenshot helper) to capture the previewer quiz page in light and dark mode. Dark mode needs `user.theme` set on the user record, **not** a cookie.

Save to the scratchpad, then view both:
- `.../scratchpad/previewer-quiz-light.png`
- `.../scratchpad/previewer-quiz-dark.png`

- [ ] **Step 4: Judge the screenshots separately**

Read both images. Judge dark mode on its own evidence — never infer it from light. Check specifically:
- the banner's contrast against `--surface-*` in both themes (`.alert--info` uses `--primary-subtle` / `--primary`);
- that the banner does not read as authored content sitting inside the quiz;
- that the question forms visibly look interactive (not greyed).

If the banner fails contrast or reads wrong in either theme, fix the styling and re-shoot before proceeding.

- [ ] **Step 5: Lint and format the new file**

Task 5's `ruff check .` / `ruff format --check .` ran *before* this file existed, so nothing else in the plan lints it. Without this step the branch's final commit is lint-red and CI catches it after the PR is open.

```bash
uv run ruff format tests/test_e2e_quiz_previewer.py
uv run ruff check tests/test_e2e_quiz_previewer.py
```

Expected: both clean.

- [ ] **Step 6: Commit**

Stage the test **plus any stylesheet touched in Step 4** — a contrast fix left unstaged is silently dropped at PR time.

```bash
git add tests/test_e2e_quiz_previewer.py
# If Step 4 required a styling fix, stage it too, e.g.:
#   git add core/static/core/css/app.css
git commit -m "test(e2e): previewer answers a quiz and nothing persists"
```

---

## Self-Review

**Spec coverage** — every spec section maps to a task:

| Spec section | Task |
|---|---|
| Component 1 (extract the grader) | 1 |
| Component 2 (`previewing` / `read_only` split) | 3 |
| Component 3 (previewer answer branch, access invariant comment) | 2 |
| Component 4 (banner, markup, placement, i18n) | 3 |
| Component 5 (attempt counter, both lock selectors) | 4 |
| Data flow: `st["locked"]`, no-JS routing | 2 |
| Testing: persistence invariant | 2 |
| Testing: render / three markup families / banner placement / submitted | 3 |
| Testing: grading parity | 2 (covered by the per-mode feedback tests + the `attempt=99` oracle test) |
| Testing: enrolled path ignores `attempt` | 2 |
| Testing: access invariant, both bounds | 2 |
| Testing: no-leak with `max_attempts >= 2` | 2 |
| Testing: no-JS previewer (3 cases) | 2 |
| Testing: existing test to update | 3 |
| Testing: shared-helper equivalence (5 states) | 1 |
| Testing: e2e + UI verification | 6 |
| Five stale prose sites | 3 (two) + 5 (three) |

**Known deviation, stated rather than hidden:** the spec's "Grading parity" section describes driving a previewer and a student through an identical answer sequence and diffing the fragments. Task 2 instead pins each side's observable behaviour separately. This covers the same failure modes with simpler, more falsifiable tests and avoids the desynchronisation traps the spec spends three paragraphs warning about (the `N`-advancement rule, the empty-POST shift, the post-lock 409-vs-200 divergence) — and both sides funnel through the one `quiz_feedback_context`, so a genuine parity bug would have to live in the `stand_in` values, which Task 1's unit tests pin directly.

The two coverage gaps this deviation originally left are now closed inside Task 2 rather than by a separate task: `test_previewer_fragment_covers_every_marking_mode` parametrises over `A`/`N`/`R` (REVIEW previously had no view-level coverage at all), and `test_previewer_no_leak_while_attempts_remain` now asserts the `attempts_left` **number**, so a previewer/student off-by-one is caught at the endpoint rather than only in a unit test.

**Placeholder scan:** none. Every code step carries complete, copy-ready code. One stated exception remains: Task 5 Step 2 asks the implementer to read two docstrings before rewriting them, which cannot be pre-written without their current text. One step carries a conditional fallback — `node --check` availability in Task 4 Step 3 — with the stated consequence if it is unavailable. (The Task 6 e2e login block and the dragfill `stem=` value were both placeholders in earlier drafts; both are now literal.)

**Factory/helper verification (done, not assumed):** every factory and helper named in test code was checked against the running app. `MultiGridQuestionElementFactory` **does not exist** and was replaced with `MatchPairQuestionElementFactory` + `MatchPairFactory`. `test_element_try.py` has **no `_course` helper** — the real idiom is `make_pa(client, "pa")` + `CourseFactory(owner=pa)`, now used verbatim. Confirmed present: `ExtendedResponseQuestionElementFactory`, `MatchPairQuestionElementFactory`, `MatchPairFactory`, `DragToImageQuestionElementFactory`, `ShortTextQuestionElement`, `EnrollmentFactory`, `add_element`, `make_login`, `make_quiz_unit`, `make_pa`, `CourseFactory`, `SlideBreakElement`. Marking-mode codes verified as `A` / `N` / `R`.

**Type consistency:** `ephemeral_quiz_feedback` returns `(stand_in, result, validation)` in Task 1 and is unpacked in that order at both call sites (Task 1 Step 8, Task 2 Step 4). `parse_attempt(post)` takes the POST mapping in both. `stand_in`'s three attributes are written in Task 1 and read in Task 2 (`.locked` via `st["locked"]`, `.latest_answer` via `rehydrate`). Context key `previewing` is written in Task 3 Step 3 and read in Task 3 Step 4. The hook `data-quiz-preview-notice` is emitted in Task 3 Step 4 and located in Tasks 3, 5, and 6.
