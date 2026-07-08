import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_student
from tests.factories import seed_slideshow_unit


def _take_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


@pytest.mark.django_db
def test_multi_slide_marks_article_and_wraps(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t"])  # two slides
    html = client.get(_take_url(unit)).content.decode()
    assert "data-slideshow" in html
    assert html.count('class="slide"') == 2


@pytest.mark.django_db
def test_single_slide_not_marked(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(
        course, "lesson", layout=["t", "t", "brk"]
    )  # lone trailing break
    html = client.get(_take_url(unit)).content.decode()
    assert "data-slideshow" not in html  # one slide -> flat


@pytest.mark.django_db
def test_multi_slide_has_no_server_side_active_state(client):
    course = CourseFactory()
    student = make_student(client)
    EnrollmentFactory(student=student, course=course)
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t"])  # two slides
    html = client.get(_take_url(unit)).content.decode()
    import re

    for match in re.finditer(r'<div class="slide"[^>]*>', html):
        tag = match.group(0)
        assert "is-active" not in tag
        assert "hidden" not in tag
