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


def _enrolled_unit(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


@pytest.mark.django_db
def test_dragfill_lesson_render_has_selects_and_no_leak_of_explanation(client):
    course, unit = _enrolled_unit(client)
    q = DragFillBlankQuestionElement.objects.create(stem="A ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    Element.objects.create(unit=unit, content_object=q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert body.count('name="slot"') == 1  # one <select> per gap
    assert '<option value="">' in body  # empty placeholder
    assert (
        'value="Paris"' in body and 'value="Rome"' in body
    )  # pool options (not a leak — both are pool members shown to choose from)


@pytest.mark.django_db
def test_matchpair_lesson_render_two_rows(client):
    course, unit = _enrolled_unit(client)
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    MatchPair.objects.create(question=q, left="Spain", right="Madrid")
    Element.objects.create(unit=unit, content_object=q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert body.count('name="slot"') == 2
    assert "France" in body and "Spain" in body
