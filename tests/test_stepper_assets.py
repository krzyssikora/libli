import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _read(rel):
    return open(finders.find(rel), encoding="utf-8").read()


def test_stepper_js_exports_and_boot():
    src = _read("courses/js/stepper.js")
    assert "window.__stepperBooted" in src
    assert "window.libliInitStepper" in src
    assert "initStepper(document)" in src  # self-boot


def test_css_has_layer_b_and_hidden_rules():
    css = _read("courses/css/courses.css")
    assert ".stepper.is-stepping [data-stepper-step]:not(.stepper-shown)" in css
    assert ".stepper__next[hidden]" in css
    assert ".stepper__line" in css
    assert ".stepper-row" in css  # editor rows are styled (M2)


def test_editor_page_loads_stepper_js(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert b"courses/js/stepper.js" in resp.content
