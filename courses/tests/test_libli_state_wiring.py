"""Wiring for the shared `libliState` JS helper (student-practice-state graded
self-checks slice): state.js must load on a lesson page whenever ANY of the six
gate/self-check families is present, and it must load BEFORE every widget
script that depends on it (deferred scripts execute in document order). See
the design doc's "load order is a hard requirement" note."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGridElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_state_js_loads_before_switchgrid_js_in_isolation(client):
    # ONE new-family element present, no gate -- guards the six-flag OR gate in
    # isolation (a bug that gated state.js on only the three gate flags would
    # pass a page that ALSO has a gate but fail this one).
    course = CourseFactory()
    unit = _lesson_unit(course)
    grid = SwitchGridElement.objects.create(prompt="P", lines=[])
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGridElement),
        object_id=grid.pk,
    )
    user = make_login(client, "liblistate-wiring-student")
    EnrollmentFactory(student=user, course=course)

    body = client.get(
        reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    ).content.decode()

    assert "courses/js/state.js" in body
    assert body.index("courses/js/state.js") < body.index("courses/js/switchgrid.js")


def test_state_js_absent_when_no_family_present(client):
    course = CourseFactory()
    unit = _lesson_unit(course)
    user = make_login(client, "liblistate-wiring-student2")
    EnrollmentFactory(student=user, course=course)

    body = client.get(
        reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    ).content.decode()

    assert "courses/js/state.js" not in body
