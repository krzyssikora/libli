import pytest
from django.urls import reverse

from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
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
    # PR 2 (spec 2026-09-25 §5a, D13): replaces `"Paris" in body  # lesson is
    # always-reveal → correct token shown` -- the lesson paints the select in place
    # and no longer lists (or preselects) the correct token.
    assert paint("dragfill", body) == ["incorrect"]
    assert 'aria-invalid="true"' in parts("dragfill", body)[0]
    assert "question__reveal" not in body
    assert 'value="Paris" selected' not in body


@pytest.mark.django_db
def test_matchpair_reveal_lists_left_labels(client):
    course, unit = _enrolled_unit(client)
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    body = client.post(
        _check_url(course, unit, el), {"slot": ["Wrong"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    # PR 2 (spec 2026-09-25 §5a, D13): replaces `"France" in body and "Paris" in
    # body` -- the left label stays, the select is painted wrong, no list.
    assert "France" in body
    assert paint("matchpair", body) == ["incorrect"]
    assert 'aria-invalid="true"' in parts("matchpair", body)[0]
    assert "question__reveal" not in body
    assert 'value="Paris" selected' not in body
