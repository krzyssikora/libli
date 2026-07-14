import pytest

from courses import builder as builder_svc
from courses.models import Element
from courses.models import StepperElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def _mgmt(n, initial=0):
    return {
        "steps-TOTAL_FORMS": str(n),
        "steps-INITIAL_FORMS": str(initial),
        "steps-MIN_NUM_FORMS": "0",
        "steps-MAX_NUM_FORMS": "1000",
    }


def _unit():
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _post(unit, **extra):
    return {"unit_token": unit.updated.isoformat(), **extra}


def test_create_stepper_assigns_row_order():
    course, unit = _unit()
    data = _post(
        unit,
        prompt="Follow",
        **_mgmt(2),
        **{"steps-0-content": "first", "steps-1-content": "second"},
    )
    builder_svc.save_element(course, unit.pk, "stepper", "new", data, {})
    el = StepperElement.objects.get()
    assert [s.content for s in el.steps.all()] == ["first", "second"]
    assert [s.order for s in el.steps.all()] == [0, 1]
    assert Element.objects.filter(object_id=el.pk).exists()


def test_edit_reorders_and_deletes():
    course, unit = _unit()
    data = _post(
        unit,
        prompt="",
        **_mgmt(2),
        **{"steps-0-content": "a", "steps-1-content": "b"},
    )
    builder_svc.save_element(course, unit.pk, "stepper", "new", data, {})
    el = StepperElement.objects.get()
    s0, s1 = list(el.steps.all())
    join = Element.objects.get(object_id=el.pk)
    unit.refresh_from_db()
    # Delete the first row, keep the second, add a third.
    data2 = _post(
        unit,
        prompt="",
        **_mgmt(3, initial=2),
        **{
            "steps-0-id": str(s0.pk),
            "steps-0-content": "a",
            "steps-0-DELETE": "on",
            "steps-1-id": str(s1.pk),
            "steps-1-content": "b",
            "steps-2-content": "c",
        },
    )
    builder_svc.save_element(course, unit.pk, "stepper", str(join.pk), data2, {})
    el.refresh_from_db()
    assert [s.content for s in el.steps.all()] == ["b", "c"]
    assert [s.order for s in el.steps.all()] == [0, 1]
