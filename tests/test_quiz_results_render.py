"""Quiz results detail page (quiz_results): loads KaTeX when a question carries
math, and the heading is lowercase 'results'."""

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _submitted_quiz(client, *, stem):
    user = make_login(client, "stu")
    course = CourseFactory(slug="rc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(stem=stem, multiple=False)
    Choice.objects.create(question=q, text="Yes", is_correct=True, order=0)
    Element.objects.create(unit=unit, content_object=q)
    QuizSubmission.objects.create(
        student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    return course, unit


def _results_url(course, unit):
    return reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


@pytest.mark.django_db
def test_results_loads_katex_when_stem_has_math(client):
    course, unit = _submitted_quiz(client, stem=r"<p>Is \(x^2 \ge 0\)?</p>")
    body = client.get(_results_url(course, unit)).content.decode()
    assert "katex.min.js" in body
    assert "data-question" in body


@pytest.mark.django_db
def test_results_no_katex_without_math(client):
    course, unit = _submitted_quiz(client, stem="<p>Plain question?</p>")
    body = client.get(_results_url(course, unit)).content.decode()
    assert "katex.min.js" not in body


@pytest.mark.django_db
def test_results_heading_is_lowercase(client):
    user = make_login(client, "stu")
    course = CourseFactory(slug="rc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title="Algebra"
    )
    q = ShortTextQuestionElement.objects.create(stem="<p>q</p>", accepted="a")
    Element.objects.create(unit=unit, content_object=q)
    QuizSubmission.objects.create(
        student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    body = client.get(_results_url(course, unit)).content.decode()
    assert "— results" in body
    assert "— Results" not in body
