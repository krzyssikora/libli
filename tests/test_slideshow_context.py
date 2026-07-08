import pytest

from courses.views import build_lesson_context
from courses.views import build_quiz_context
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_student
from tests.factories import seed_slideshow_unit


@pytest.mark.django_db
def test_lesson_context_slides(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    # layout below -> two slides
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t"])
    ctx = build_lesson_context(unit, student)
    assert [len(s) for s in ctx["slides"]] == [1, 1]
    assert "is_slideshow" not in ctx  # taking context gates on slide count only


@pytest.mark.django_db
def test_quiz_context_single_slide_when_no_break(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "q"])  # no break
    ctx = build_quiz_context(unit, student)
    assert len(ctx["slides"]) == 1
    assert len(ctx["slides"][0]) == len(ctx["elements"])
