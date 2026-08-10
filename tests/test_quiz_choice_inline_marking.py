"""A locked quiz choice question marks its OPTIONS LIST inline.

Before this, a quiz choice question conveyed the student's selection only through
the native radio dot — and locking the question disables every input, which
Chromium paints as a grey dot on a grey ring, visually identical to an unchecked
option at body size. A correct answer therefore produced a green "Correct" panel
next to three options that all looked untouched.

The rule pinned here: once a quiz question LOCKS, the options list itself carries
the marking — the pick is tinted, correct options get a tick, a wrong pick a
cross, a missed correct option a plus — and the duplicate bottom reveal list goes
away. While attempts remain NOTHING is marked (the withhold rule is unchanged),
and lesson mode is untouched.
"""

import pytest

from courses.models import Choice
from tests.factories import ChoiceQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

PICKED = "question__choice--picked"
M_CORRECT = "question__choice-marker--correct"
M_WRONG = "question__choice-marker--wrong"
M_MISSED = "question__choice-marker--missed"
REVEAL_LIST = "question__reveal"


def _quiz(client, max_attempts=1, multiple=False):
    """Enrolled student + quiz unit holding one choice question.

    Returns (unit, element_join_row, right, wrong). `right` is correct.
    """
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ChoiceQuestionElement.objects.create(
        stem="Capital of France?", multiple=multiple, max_attempts=max_attempts
    )
    right = Choice.objects.create(question=q, text="Paris", is_correct=True)
    wrong = Choice.objects.create(question=q, text="London", is_correct=False)
    return unit, add_element(unit, q), right, wrong


def _answer(client, unit, el, *choice_pks):
    """POST an answer the way quiz.js does (fragment request). Returns the body."""
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(
        url, {"choice": [str(p) for p in choice_pks]}, HTTP_X_REQUESTED_WITH="fetch"
    )
    return resp.content.decode()


def _reload(client, unit):
    """GET the quiz page (the resume render)."""
    return client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/").content.decode()


# ---------------------------------------------------------------------------
# The reported bug: a correct answer must show WHICH option was chosen.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_correct_answer_marks_the_chosen_option_on_reload(client):
    unit, el, right, wrong = _quiz(client)
    _answer(client, unit, el, right.pk)

    html = _reload(client, unit)

    assert PICKED in html, "the student's pick carries no visible marker"
    assert M_CORRECT in html, "the correct option is not ticked"


@pytest.mark.django_db
def test_correct_answer_marks_the_chosen_option_in_the_live_fragment(client):
    """The JS path must re-render the options list, not just the feedback box."""
    unit, el, right, wrong = _quiz(client)

    html = _answer(client, unit, el, right.pk)

    assert PICKED in html
    assert M_CORRECT in html


# ---------------------------------------------------------------------------
# A wrong answer, once locked, distinguishes the pick from the answer key.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_wrong_locked_answer_crosses_the_pick_and_flags_the_missed_option(client):
    unit, el, right, wrong = _quiz(client)  # max_attempts=1 -> locks immediately

    html = _answer(client, unit, el, wrong.pk)

    assert M_WRONG in html, "the wrong pick is not crossed"
    assert M_MISSED in html, "the missed correct option is not flagged"


@pytest.mark.django_db
def test_locked_choice_question_drops_the_duplicate_reveal_list(client):
    """The options list now carries the marking, so the bottom echo is redundant."""
    unit, el, right, wrong = _quiz(client)

    html = _answer(client, unit, el, wrong.pk)

    assert REVEAL_LIST not in html


# ---------------------------------------------------------------------------
# Withholding while attempts remain is UNCHANGED.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_marking_while_attempts_remain(client):
    unit, el, right, wrong = _quiz(client, max_attempts=3)

    html = _answer(client, unit, el, wrong.pk)

    assert M_CORRECT not in html
    assert M_MISSED not in html
    assert M_WRONG not in html
    assert PICKED not in html


@pytest.mark.django_db
def test_answer_key_still_withheld_from_the_page_while_attempts_remain(client):
    """The un-picked correct option must not become identifiable mid-quiz."""
    unit, el, right, wrong = _quiz(client, max_attempts=3)
    _answer(client, unit, el, wrong.pk)

    html = _reload(client, unit)

    assert M_CORRECT not in html
    assert M_MISSED not in html


@pytest.mark.django_db
def test_a_submitted_quiz_never_renders_its_options_again(client):
    """Why "answered but never locked" needs no marking rule of its own.

    `quiz_submitted` disables every input independently of `locked`, so a question
    the student answered without exhausting its attempts would render disabled AND
    unmarked — the original invisible-pick defect by another route. It is
    unreachable only because a submitted quiz redirects to the results page, which
    renders no options list at all. If that redirect is ever removed, this fails and
    the marking rule in _choice_marks has to widen from `locked` to
    `locked or quiz_submitted`.
    """
    unit, el, right, wrong = _quiz(client, max_attempts=3)
    _answer(client, unit, el, wrong.pk)  # 2 attempts still remain -> NOT locked
    client.post(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/finish/")

    resp = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/")

    assert resp.status_code == 302
    assert resp["Location"].endswith(f"/u/{unit.pk}/quiz/results/")


# ---------------------------------------------------------------------------
# Multi-select: a missed correct option is flagged alongside the wrong pick.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_multi_select_flags_each_option_by_its_own_outcome(client):
    unit, el, right, wrong = _quiz(client, multiple=True)
    q = el.content_object
    second_right = Choice.objects.create(question=q, text="Lyon", is_correct=True)

    html = _answer(client, unit, el, right.pk, wrong.pk)

    assert M_CORRECT in html, f"picked correct option {right.pk} not ticked"
    assert M_WRONG in html, f"picked wrong option {wrong.pk} not crossed"
    assert M_MISSED in html, f"missed correct option {second_right.pk} not flagged"


# ---------------------------------------------------------------------------
# Lesson mode is untouched.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lesson_correct_answer_does_not_gain_a_tick(client):
    """Lessons keep the author-feedback-driven marking designed in #132."""
    user = make_login(client, "stu")
    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    EnrollmentFactory(student=user, course=unit.course)
    q = ChoiceQuestionElement.objects.create(stem="Capital?", multiple=False)
    right = Choice.objects.create(question=q, text="Paris", is_correct=True)
    Choice.objects.create(question=q, text="London", is_correct=False)
    el = add_element(unit, q)

    url = f"/courses/{unit.course.slug}/u/{unit.pk}/q/{el.pk}/check/"
    html = client.post(
        url, {"choice": str(right.pk)}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()

    assert M_CORRECT not in html
    assert PICKED not in html
