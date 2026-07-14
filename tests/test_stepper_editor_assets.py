import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_stepper_editor_js_exports():
    src = open(finders.find("courses/js/stepper_editor.js"), encoding="utf-8").read()
    assert "window.libliInitStepperEditor" in src
    assert "steps-TOTAL_FORMS" in src
    assert "__prefix__" in src


def test_editor_page_loads_stepper_editor_js(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert b"courses/js/stepper_editor.js" in resp.content
