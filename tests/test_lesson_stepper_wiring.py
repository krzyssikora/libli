import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import StepperElement
from courses.models import StepperStep
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _body(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    el = StepperElement.objects.create(prompt="")
    StepperStep.objects.create(stepper=el, content="a")
    StepperStep.objects.create(stepper=el, content="b")
    Element.objects.create(unit=unit, content_object=el)
    return client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()


def test_lesson_loads_stepper_js():
    assert "courses/js/stepper.js" in _body(pytest.importorskip("django.test").Client())


def test_lesson_arms_and_watchdog_present():
    body = _body(pytest.importorskip("django.test").Client())
    assert "stepper-armed" in body
    assert "__stepperBooted" in body


def test_mathjs_selector_includes_stepper():
    from django.contrib.staticfiles import finders

    path = finders.find("courses/js/math.js")
    assert ".stepper" in open(path, encoding="utf-8").read()


def test_lesson_loads_state_js_for_stepper():
    # A stepper-only lesson must load state.js (window.libliState.saveFlag), not
    # only stepper.js. Guards the has_stepper addition to the state.js load gate.
    assert "courses/js/state.js" in _body(pytest.importorskip("django.test").Client())
