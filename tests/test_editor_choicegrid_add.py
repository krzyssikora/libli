import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _quiz_unit(course):
    return ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")


def test_manage_element_add_renders_choicegrid_editor_200(client):
    # element_add fully renders the open-form host, which auto-includes
    # templates/courses/manage/editor/_edit_choicegridquestion.html. POST is required --
    # the view reads request.POST["type"] / request.POST["unit"] (a GET 404s at the unit
    # lookup), mirroring test_filltable_manage_plumbing.py.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "choicegridquestion", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"columns-TOTAL_FORMS" in resp.content
    assert b"rows-TOTAL_FORMS" in resp.content
    assert b"data-choicegrid-editor" in resp.content
