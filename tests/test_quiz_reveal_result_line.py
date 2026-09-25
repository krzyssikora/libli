"""Result line (spec 2026-09-25 §1, §2.5): real outcome + marks, every quiz type."""

from decimal import Decimal

import pytest

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _enrolled_quiz(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _fb(unit, accepted, **kw):
    token_stem, _ = parse(" ".join("{{%s}}" % a for a in accepted))  # noqa: UP031
    q = FillBlankQuestionElement.objects.create(stem=token_stem, **kw)
    for i, a in enumerate(accepted):
        Blank.objects.create(question=q, order=i, accepted=a)
    return Element.objects.create(unit=unit, content_object=q)


def _post(client, unit, el, data):
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    return client.post(url, data, HTTP_X_REQUESTED_WITH="fetch").content.decode()


@pytest.mark.django_db
def test_partial_reads_partly_correct_with_marks_and_attempts(client):
    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9", "2", "22"], max_attempts=3)
    body = _post(client, unit, el, {"blank": ["11", "", "", ""]})
    assert "Partly correct" in body
    assert "0.25 / 1" in body
    assert "2 attempts left" in body
    assert "Incorrect" not in body


@pytest.mark.django_db
def test_unlimited_attempts_line_omits_count(client):
    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9"], max_attempts=None)
    body = _post(client, unit, el, {"blank": ["11", "5"]})
    assert "Partly correct" in body
    assert "attempts left" not in body and "attempt left" not in body


@pytest.mark.django_db
def test_rounding_to_full_marks_while_unlocked_reads_partial(client):
    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9"], max_attempts=3, max_marks=Decimal("0.01"))
    body = _post(client, unit, el, {"blank": ["11", "5"]})  # 0.5 * 0.01 -> 0.01
    assert "Partly correct" in body
    assert "is-correct" not in body.split("question__verdict")[1][:40]


@pytest.mark.django_db
def test_resume_survives_auto_answer_switched_to_not_marked(client):
    # An AUTO attempt with attempts left, then the author switches the question to
    # N: resume reaches quiz_feedback_context with result=None and locked=False.
    from django.urls import reverse

    from courses.models import QuestionElement

    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9"], max_attempts=3)
    _post(client, unit, el, {"blank": ["11", "5"]})
    q = el.content_object
    q.marking_mode = QuestionElement.MarkingMode.NOT_MARKED
    q.save()
    page = client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    )
    assert page.status_code == 200


@pytest.mark.django_db
def test_incorrect_unconverted_type_gets_new_line_too(client):
    # Choice stays unconverted through PR 1-2 -- the line is ungated (spec §2.1).
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    unit = _enrolled_quiz(client)
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    Choice.objects.create(question=q, text="A", is_correct=True)
    wrong = Choice.objects.create(question=q, text="B", is_correct=False)
    el = add_element(unit, q)
    body = _post(client, unit, el, {"choice": [str(wrong.pk)]})
    assert "Incorrect" in body and "0 / 1" in body


@pytest.mark.django_db
def test_incorrect_unconverted_non_inline_type_gets_new_line_too(client):
    # Drag the words is neither SUPPORTS_REVEAL nor INLINE_QUIZ_REVEAL: its response
    # is the bare feedback fragment, which must carry the new line with marks too.
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement

    unit = _enrolled_quiz(client)
    q = DragFillBlankQuestionElement.objects.create(
        stem=parse("{{cat}} and {{dog}}")[0], distractors="x", max_attempts=3
    )
    DragBlank.objects.create(question=q, correct_token="cat", order=0)
    DragBlank.objects.create(question=q, correct_token="dog", order=1)
    el = add_element(unit, q)
    body = _post(client, unit, el, {"slot": ["dog", "cat"]})
    assert "data-question-inline" not in body  # the fragment, not the element
    assert "question__verdict is-incorrect" in body
    assert "Incorrect" in body and "0 / 1" in body and "2 attempts left" in body
