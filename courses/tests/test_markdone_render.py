import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import TabsElement
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _markdone(prompt="Prep", items=("one", "two")):
    el = MarkDoneElement.objects.create(prompt=prompt)
    made = [MarkDoneItem.objects.create(element=el, content=c) for c in items]
    return el, made


def _lesson_url(course, unit):
    return reverse(
        "courses:lesson_unit",
        kwargs={"slug": course.slug, "node_pk": unit.pk},
    )


def test_enrolled_student_sees_checked_items(client):
    student = make_login(client, "stu")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    el, (i1, i2) = _markdone()
    add_element(unit, el)
    UnitProgress.objects.create(
        student=student, unit=unit, checklist_state={str(el.pk): [i1.pk]}
    )

    body = client.get(_lesson_url(course, unit)).content.decode()

    assert f'name="element" value="{el.pk}"' in body
    # i1 is checked and its row carries the `on` class.
    assert f'value="{i1.pk}"' in body
    assert "checked" in body
    assert "markdone__item on" in body


def test_nested_in_tabs_checklist_resolves_checked(client):
    # Proves Task 3's container injection reaches a tab-nested checklist: the checked
    # set is resolved from checklist_state and rendered `checked` + `on`.
    student = make_login(client, "stu")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    parent = Element.objects.create(unit=unit, content_object=tabs)
    el, (i1, i2) = _markdone()
    Element.objects.create(
        unit=unit, content_object=el, parent=parent, tab_id="t000001"
    )
    UnitProgress.objects.create(
        student=student, unit=unit, checklist_state={str(el.pk): [i1.pk]}
    )

    body = client.get(_lesson_url(course, unit)).content.decode()

    assert f'name="element" value="{el.pk}"' in body
    assert "checked" in body
    assert "markdone__item on" in body
