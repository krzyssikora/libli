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
        {"answer": "Paris", "attempt": "1"},  # correct
        {"answer": "London", "attempt": "1"},  # incorrect, attempts remain
        {"answer": "", "attempt": "1"},  # empty -> validation
        {"answer": "London", "attempt": "9"},  # beyond max_attempts
    ],
)
def test_previewer_answer_persists_nothing(client, payload):
    """The load-bearing invariant. All THREE models are asserted: checking only
    QuizSubmission would miss a partial write."""
    user, unit, el = _previewer_quiz(client)
    resp = client.post(_answer_url(unit, el), payload, HTTP_X_REQUESTED_WITH="fetch")
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
        _answer_url(unit, el),
        {"answer": "", "attempt": "1"},
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
    _assert_nothing_persisted()


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
    _assert_nothing_persisted()


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
