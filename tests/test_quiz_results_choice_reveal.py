"""The results page must show WHICH option the student chose, not just the key.

`_reveal_choice.html` was the only reveal partial of seven that never marked the
student's own answer — its siblings (_reveal_fillblank, _reveal_dragfill,
_reveal_dragimage, _reveal_matchpair, _reveal_choicegrid, _reveal_multigrid) all
emit answer-correct OR answer-wrong per row, while this one only ever emitted
answer-correct. It received `mark_result.reveal` (the key) but never the selection,
so it structurally could not show the pick.

On top of that, quiz_results.html gated the whole reveal on `outcome != "correct"`,
so a correct answer showed nothing at all — and the results page is the ONLY place a
finished student can review, because a submitted quiz redirects here.

Both are fixed for choice questions only; the other six types keep the
correct-outcome gate, since their reveals print the key alone.
"""

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import Element
from courses.models import Enrollment
from courses.models import ShortTextQuestionElement
from tests.factories import ChoiceQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

M_CORRECT = "question__reveal-mark--correct"
M_WRONG = "question__reveal-mark--wrong"
M_MISSED = "question__reveal-mark--missed"


def _quiz(client, multiple=False):
    user = make_login(client, "stu")
    course = CourseFactory(slug="rcr")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(
        stem="Capital of France?", multiple=multiple, max_attempts=1
    )
    right = Choice.objects.create(question=q, text="Paris", is_correct=True, order=0)
    wrong = Choice.objects.create(question=q, text="London", is_correct=False, order=1)
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el, right, wrong


def _answer_and_finish(client, course, unit, el, *choice_pks):
    base = f"/courses/{course.slug}/u/{unit.pk}/quiz"
    if choice_pks:
        client.post(
            f"{base}/q/{el.pk}/answer/",
            {"choice": [str(p) for p in choice_pks]},
            HTTP_X_REQUESTED_WITH="fetch",
        )
    client.post(f"{base}/finish/")
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return client.get(url).content.decode()


@pytest.mark.django_db
def test_a_correct_answer_shows_what_the_student_chose(client):
    """Previously the whole reveal was suppressed on a correct outcome."""
    course, unit, el, right, wrong = _quiz(client)

    body = _answer_and_finish(client, course, unit, el, right.pk)

    assert "Correct" in body
    assert M_CORRECT in body, "a correct answer still reveals nothing on results"


@pytest.mark.django_db
def test_a_wrong_answer_separates_the_pick_from_the_key(client):
    course, unit, el, right, wrong = _quiz(client)

    body = _answer_and_finish(client, course, unit, el, wrong.pk)

    assert M_WRONG in body, "the student's wrong pick is not marked"
    assert M_MISSED in body, "the correct option they missed is not marked"


@pytest.mark.django_db
def test_multi_select_marks_each_option_by_its_own_outcome(client):
    course, unit, el, right, wrong = _quiz(client, multiple=True)
    Choice.objects.create(
        question=el.content_object, text="Lyon", is_correct=True, order=2
    )

    body = _answer_and_finish(client, course, unit, el, right.pk, wrong.pk)

    # Without a per-option pick marker, a picked-correct option and a missed-correct
    # one both render as a bare tick — the exact ambiguity this closes.
    assert M_CORRECT in body
    assert M_WRONG in body
    assert M_MISSED in body


@pytest.mark.django_db
def test_an_unanswered_question_still_reveals_the_key(client):
    """Pre-existing "reveal all" behaviour must survive: no answer, key still shown."""
    course, unit, el, right, wrong = _quiz(client)

    body = _answer_and_finish(client, course, unit, el)  # never answered

    assert M_MISSED in body  # the correct option, flagged as not chosen
    assert M_CORRECT not in body
    assert M_WRONG not in body


@pytest.mark.django_db
def test_a_non_choice_type_keeps_the_correct_outcome_gate(client):
    """Scope guard: only choice relaxed the gate; short-text reveals the key alone,
    which on a correct answer would just echo what the student already got right."""
    user = make_login(client, "stu")
    course = CourseFactory(slug="rcr2")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=1
    )
    el = Element.objects.create(unit=unit, content_object=q)
    base = f"/courses/{course.slug}/u/{unit.pk}/quiz"
    client.post(
        f"{base}/q/{el.pk}/answer/", {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    client.post(f"{base}/finish/")
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    body = client.get(url).content.decode()

    assert "Correct" in body
    assert "question__reveal" not in body
