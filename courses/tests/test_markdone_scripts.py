import pytest
from django.urls import reverse

from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_lesson_includes_markdone_js_when_present(client):
    course, unit = make_course_with_unit()
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")

    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)

    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "courses/js/markdone.js" in body


def test_lesson_omits_markdone_js_when_absent(client):
    course, unit = make_course_with_unit()

    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)

    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "courses/js/markdone.js" not in body
