import pytest

from courses.models import Element
from courses.models import Enrollment
from courses.models import StepperElement
from courses.models import StepperStep
from courses.models import TabsElement
from courses.views import build_lesson_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _enrolled_lesson(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit, user


def _stepper(steps=("a",), prompt=""):
    el = StepperElement.objects.create(prompt=prompt)
    for c in steps:
        StepperStep.objects.create(stepper=el, content=c)
    return el


def test_toplevel_stepper_sets_has_stepper(client):
    course, unit, user = _enrolled_lesson(client)
    Element.objects.create(unit=unit, content_object=_stepper())
    assert build_lesson_context(unit, user)["has_stepper"] is True


def test_tab_nested_stepper_sets_has_stepper(client):
    # Flat query must see a stepper nested inside a tab (NOT scoped to
    # parent__isnull=True). Use the canonical minted tab-id format.
    course, unit, user = _enrolled_lesson(client)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    parent = Element.objects.create(unit=unit, content_object=tabs)
    Element.objects.create(
        unit=unit, content_object=_stepper(), parent=parent, tab_id="t000001"
    )
    assert build_lesson_context(unit, user)["has_stepper"] is True


def test_stepper_math_sets_has_math(client):
    course, unit, user = _enrolled_lesson(client)
    Element.objects.create(unit=unit, content_object=_stepper(steps=(r"\(x^2\)",)))
    assert build_lesson_context(unit, user)["has_math"] is True
