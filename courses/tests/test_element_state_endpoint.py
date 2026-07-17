import json

import pytest
from django.urls import reverse

from courses.models import ChoiceQuestionElement
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import TextElement
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _url(course, unit):
    return reverse("courses:element_state_save", args=[course.slug, unit.pk])


def _setup():
    course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    i2 = MarkDoneItem.objects.create(element=obj, content="b")
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    return course, unit, obj, row, i1, i2, student


def _post(client, course, unit, payload):
    return client.post(
        _url(course, unit), data=json.dumps(payload), content_type="application/json"
    )


def test_json_persists_under_the_join_row_pk(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": [i1.pk]}})
    assert r.status_code == 200
    assert r.json() == {"element": row.pk, "state": {"items": [i1.pk]}}
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"items": [i1.pk]}}


def test_empty_selection_drops_the_key_and_echoes_empty(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": []}})
    assert r.status_code == 200 and r.json()["state"] == {}
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(row.pk) not in up.element_state


def test_rejected_blob_echoes_the_stored_blob_and_leaves_it_untouched(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )
    client.force_login(student)
    # "items": "abc" -> REJECT (not EMPTY): the stored key must SURVIVE.
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": "abc"}})
    assert r.status_code == 200
    assert r.json()["state"] == {"items": [i1.pk]}  # echo = what is STORED
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"items": [i1.pk]}}


def test_rejected_blob_creates_no_unitprogress_row(client):
    # validate BEFORE get_or_create: a garbage POST must not spawn a row.
    course, unit, _obj, row, _i1, _i2, student = _setup()
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": "abc"}})
    assert r.status_code == 200 and r.json()["state"] == {}
    assert not UnitProgress.objects.filter(student=student, unit=unit).exists()


def test_unknown_content_type_is_skipped_not_500(client):
    course, unit = make_course_with_unit()
    obj = TextElement.objects.create(body="hi")
    row = add_element(unit, obj)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"x": 1}})
    assert r.status_code == 200 and r.json()["state"] == {}


def test_forged_element_400(client):
    course, unit, _obj, _row, _i1, _i2, student = _setup()
    client.force_login(student)
    assert (
        _post(client, course, unit, {"element": 999999, "state": {}}).status_code == 400
    )


def test_element_from_another_unit_400(client):
    course, unit, _obj, _row, _i1, _i2, student = _setup()
    _c2, unit2 = make_course_with_unit()
    other = MarkDoneElement.objects.create(prompt="X")
    row2 = add_element(unit2, other)
    client.force_login(student)
    assert (
        _post(client, course, unit, {"element": row2.pk, "state": {}}).status_code
        == 400
    )


def test_state_and_fields_both_present_400(client):
    course, unit, _obj, row, _i1, _i2, student = _setup()
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {}, "fields": {}})
    assert r.status_code == 400


def test_fields_on_a_non_question_400(client):
    course, unit, _obj, row, _i1, _i2, student = _setup()
    client.force_login(student)
    assert (
        _post(client, course, unit, {"element": row.pk, "fields": {}}).status_code
        == 400
    )


def test_fields_on_a_question_400_slice_1_gate(client):
    # SLICE-1 ONLY: no question validator is registered yet. Slice 3 REPLACES this
    # assertion (it is the one endpoint test slice 3 does not keep).
    course, unit = make_course_with_unit()
    q = ChoiceQuestionElement.objects.create(stem="s")
    row = add_element(unit, q)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    assert (
        _post(client, course, unit, {"element": row.pk, "fields": {}}).status_code
        == 400
    )


def test_previewer_persists(client):
    # PR #136 rule: ANY viewer with can_access_course persists their own practice
    # state — the write gate is can_access_course, NOT is_enrolled. The author is
    # NOT enrolled; under an is_enrolled gate this silently no-ops.
    # NB make_course_with_unit(owner=...) — it mints its own UserFactory owner by
    # default, and force_login on an unverified user is intercepted by allauth's
    # mandatory-verification middleware. Pass a verified one.
    author = make_verified_user(username="author", email="author@school.edu")
    course, unit = make_course_with_unit(owner=author)
    obj = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    client.force_login(author)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": [i1.pk]}})
    assert r.status_code == 200
    assert UnitProgress.objects.filter(student=author, unit=unit).exists()


def test_stranger_denied(client):
    course, unit, _obj, row, _i1, _i2, _student = _setup()
    stranger = make_verified_user(username="stranger", email="stranger@school.edu")
    client.force_login(stranger)
    assert (
        _post(client, course, unit, {"element": row.pk, "state": {}}).status_code == 403
    )


def test_quiz_node_404s(client):
    from courses.models import ContentNode

    course, unit, _obj, row, _i1, _i2, student = _setup()
    unit.unit_type = ContentNode.UnitType.QUIZ
    unit.save()
    client.force_login(student)
    assert (
        _post(client, course, unit, {"element": row.pk, "state": {}}).status_code == 404
    )


def test_foreign_course_node_404s(client):
    course, _unit, _obj, _row, _i1, _i2, student = _setup()
    _c2, unit2 = make_course_with_unit()
    client.force_login(student)
    r = client.post(
        reverse("courses:element_state_save", args=[course.slug, unit2.pk]),
        data=json.dumps({"element": 1, "state": {}}),
        content_type="application/json",
    )
    assert r.status_code == 404


def test_concurrent_two_element_save_does_not_clobber(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    obj2 = MarkDoneElement.objects.create(prompt="Q")
    row2 = add_element(unit, obj2)
    j1 = MarkDoneItem.objects.create(element=obj2, content="c")
    client.force_login(student)
    _post(client, course, unit, {"element": row.pk, "state": {"items": [i1.pk]}})
    _post(client, course, unit, {"element": row2.pk, "state": {"items": [j1.pk]}})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {
        str(row.pk): {"items": [i1.pk]},
        str(row2.pk): {"items": [j1.pk]},
    }


def test_no_js_form_persists_and_anchors_to_the_join_row_pk(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    client.force_login(student)
    r = client.post(_url(course, unit), data={"element": row.pk, "item": [str(i1.pk)]})
    assert r.status_code == 302 and r.url.endswith(f"#markdone-{row.pk}")
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"items": [i1.pk]}}


def test_anonymous_is_redirected_by_login_required(client):
    # [S1] spec requirement. UnitProgress.student is a non-null FK; an AnonymousUser
    # is not a valid value, so @login_required must reject BEFORE the body runs.
    course, unit, _obj, row, _i1, _i2, _student = _setup()
    r = _post(client, course, unit, {"element": row.pk, "state": {}})
    assert r.status_code == 302 and "/login" in r.url


def test_no_js_form_on_a_non_markdone_element_400(client):
    course, unit = make_course_with_unit()
    obj = TextElement.objects.create(body="hi")
    row = add_element(unit, obj)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    assert client.post(_url(course, unit), data={"element": row.pk}).status_code == 400
