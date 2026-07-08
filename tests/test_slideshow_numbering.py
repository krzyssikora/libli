import re

import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_student
from tests.factories import seed_slideshow_unit


@pytest.mark.django_db
def test_quiz_numbers_in_markup_contiguous_across_break(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    # layout -> 3 questions
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "q", "q"])
    url = reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    html = client.get(url).content.decode()
    assert re.findall(r'data-qnum="(\d+)"', html) == ["1", "2", "3"]


@pytest.mark.django_db
def test_lesson_questions_have_no_qnum(client):
    # A quiz-type question element embedded in a LESSON must NOT be numbered.
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["q", "q"])
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    html = client.get(url).content.decode()
    assert "data-qnum" not in html
