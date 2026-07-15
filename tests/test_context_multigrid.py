import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _enrolled_lesson(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _grid(unit, *, label="B"):
    q = MultiGridQuestionElement.objects.create(stem="Pick the truths")
    a = MultiGridColumn.objects.create(question=q, label="A")
    MultiGridColumn.objects.create(question=q, label=label)
    r1 = MultiGridRow.objects.create(question=q, statement="2+2=4")
    r1.correct_columns.set([a])
    Element.objects.create(unit=unit, content_object=q)
    return q


def _lesson_body(client, course, unit):
    return client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()


def test_multigrid_only_lesson_sets_has_questions(client):
    course, unit = _enrolled_lesson(client)
    _grid(unit)
    body = _lesson_body(client, course, unit)
    assert "courses/js/question.js" in body
    assert "multigrid" in body


def test_multigrid_math_in_column_sets_has_math(client):
    course, unit = _enrolled_lesson(client)
    _grid(unit, label=r"\(x^2\)")  # math in a column label
    body = _lesson_body(client, course, unit)
    assert "katex.min.js" in body
