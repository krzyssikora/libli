import pytest
from django.urls import reverse

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import ContentNodeFactory, CourseFactory, make_login


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    return course, unit


def _check_url(course, unit, el):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )


@pytest.mark.django_db
def test_dragfill_reveal_shows_correct_token_on_wrong_answer(client):
    course, unit = _enrolled_unit(client)
    q = DragFillBlankQuestionElement.objects.create(stem="A ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    body = client.post(
        _check_url(course, unit, el), {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "is-incorrect" in body
    assert "Paris" in body  # lesson is always-reveal → correct token shown


@pytest.mark.django_db
def test_matchpair_reveal_lists_left_labels(client):
    course, unit = _enrolled_unit(client)
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    body = client.post(
        _check_url(course, unit, el), {"slot": ["Wrong"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "France" in body and "Paris" in body
