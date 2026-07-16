import json

import pytest
from django.urls import reverse

from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _url(course, unit):
    return reverse("courses:markdone_save", args=[course.slug, unit.pk])


def _setup():
    course, unit = make_course_with_unit()
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    i1 = MarkDoneItem.objects.create(element=el, content="a")
    i2 = MarkDoneItem.objects.create(element=el, content="b")
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    return course, unit, el, i1, i2, student


def test_enrolled_json_persists(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    r = client.post(
        _url(course, unit),
        data=json.dumps({"element": el.pk, "items": [i1.pk]}),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json() == {"element": el.pk, "items": [i1.pk]}
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.checklist_state == {str(el.pk): [i1.pk]}


def test_no_js_form_persists(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    r = client.post(_url(course, unit), data={"element": el.pk, "item": [i1.pk, i2.pk]})
    assert r.status_code in (302, 303)
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert set(up.checklist_state[str(el.pk)]) == {i1.pk, i2.pk}


def test_empty_selection_drops_key(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    UnitProgress.objects.create(
        student=student, unit=unit, checklist_state={str(el.pk): [i1.pk]}
    )
    r = client.post(
        _url(course, unit),
        data=json.dumps({"element": el.pk, "items": []}),
        content_type="application/json",
    )
    assert r.status_code == 200
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(el.pk) not in up.checklist_state


def test_forged_item_filtered_and_forged_element_400(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    # forged item pk dropped
    r = client.post(
        _url(course, unit),
        data=json.dumps({"element": el.pk, "items": [i1.pk, 999999]}),
        content_type="application/json",
    )
    assert r.json()["items"] == [i1.pk]
    # forged element pk -> 400
    r2 = client.post(
        _url(course, unit),
        data=json.dumps({"element": 999999, "items": []}),
        content_type="application/json",
    )
    assert r2.status_code == 400


def test_non_list_items_never_500(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    r = client.post(
        _url(course, unit),
        data=json.dumps({"element": el.pk, "items": "abc"}),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["items"] == []


def test_non_enrolled_can_access_writes(client):
    # A viewer (staff) who can_access_course but is NOT enrolled persists their own
    # ticks too — a checklist is personal self-tracking, so authors/teachers previewing
    # their own lesson can use it (diverges from the seen/quiz previewer no-write rule).
    course, unit, el, i1, i2, _student = _setup()
    previewer = make_verified_user(username="prev", email="prev@school.edu")
    previewer.is_staff = True
    previewer.save()
    client.force_login(previewer)
    r = client.post(
        _url(course, unit),
        data=json.dumps({"element": el.pk, "items": [i1.pk]}),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["items"] == [i1.pk]
    up = UnitProgress.objects.get(unit=unit, student=previewer)
    assert up.checklist_state == {str(el.pk): [i1.pk]}


def test_merge_not_clobber(client):
    """Two elements' saves both survive -> read-modify-write, not clobber."""
    course, unit, el, i1, i2, student = _setup()
    el2 = MarkDoneElement.objects.create(prompt="P2")
    add_element(unit, el2)
    j1 = MarkDoneItem.objects.create(element=el2, content="x")
    client.force_login(student)
    client.post(
        _url(course, unit),
        data=json.dumps({"element": el.pk, "items": [i1.pk]}),
        content_type="application/json",
    )
    client.post(
        _url(course, unit),
        data=json.dumps({"element": el2.pk, "items": [j1.pk]}),
        content_type="application/json",
    )
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.checklist_state == {str(el.pk): [i1.pk], str(el2.pk): [j1.pk]}
