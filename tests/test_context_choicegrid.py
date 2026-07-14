import pytest
from django.urls import reverse

from courses.models import ChoiceGridQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import GridColumn
from courses.models import GridRow
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


def _grid(unit, *, statement="2+2=4"):
    q = ChoiceGridQuestionElement.objects.create(stem="Pick the truths")
    t = GridColumn.objects.create(question=q, label="True")
    f = GridColumn.objects.create(question=q, label="False")
    GridRow.objects.create(question=q, statement=statement, correct_column=t)
    GridRow.objects.create(question=q, statement="5 is even", correct_column=f)
    Element.objects.create(unit=unit, content_object=q)
    return q


def _lesson_body(client, course, unit):
    return client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()


def test_matrix_only_lesson_sets_has_questions(client):
    # A lesson whose sole element is a matrix must load question.js (inline feedback +
    # KaTeX typesetting of the grid). has_questions is driven solely by question_models.
    course, unit = _enrolled_lesson(client)
    _grid(unit)
    body = _lesson_body(client, course, unit)
    assert "courses/js/question.js" in body


def test_matrix_math_in_statement_sets_has_math(client):
    # KaTeX delimiters in a row statement must flip has_math on the lesson path so the
    # KaTeX assets load and the grid statement renders as math, not raw LaTeX.
    course, unit = _enrolled_lesson(client)
    _grid(unit, statement=r"\(x^2\)")
    body = _lesson_body(client, course, unit)
    assert "katex.min.js" in body
