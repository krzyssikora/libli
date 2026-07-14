import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_manage_element_add_renders_stepper_editor_200(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "stepper", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"steps-TOTAL_FORMS" in resp.content  # management form present
    assert b"data-stepper-editor" in resp.content  # editor mounted
    assert resp.content.count(b"data-stepper-row") >= 1  # one blank starter row
