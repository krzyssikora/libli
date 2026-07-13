import pytest
from django.test import Client
from django.urls import reverse

from courses.models import FillTableElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _post(client, pk, fields):
    return client.post(reverse("courses:filltable_check", args=[pk]), fields)


@pytest.fixture
def auth_client():
    """A logged-in client for the owner user (fresh Client — never shares session
    state with other_auth_client, which also logs in on its own fresh Client)."""
    c = Client()
    c.user = make_login(c, "filltable-owner")
    return c


@pytest.fixture
def other_auth_client():
    """A logged-in client for an unrelated user: never the course owner, never
    enrolled, never a teacher — always denied by can_access_course."""
    c = Client()
    c.user = make_login(c, "filltable-outsider")
    return c


@pytest.fixture
def filltable_on_unit(auth_client):
    """Factory fixture: build a lesson unit owned by auth_client's user with a
    FillTableElement attached, and return its Element join row + course.

    `private` is accepted for interface/documentation parity with the brief
    (a course an outsider must never access) — access here is always owner-only
    (no enrollment, no teaching group is ever granted to anyone else), so both
    values behave identically today; the flag exists so call sites read as
    intent ("this must stay private") rather than silently relying on the
    default.
    """

    def _make(cells, private=False):
        course = CourseFactory(owner=auth_client.user)
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=None
        )
        el = FillTableElement(data={"cells": cells})
        el.save()
        element = add_element(unit, el)
        return element, course

    return _make


def test_all_correct_non_00_cell(filltable_on_unit, auth_client):
    element, _course = filltable_on_unit(
        [[{"kind": "static", "html": "t"}, {"kind": "answer", "answer": "4"}]]
    )
    r = _post(auth_client, element.pk, {"r0c1": "4"})
    body = r.json()
    assert body["all_correct"] is True
    assert {"r": 0, "c": 1, "correct": True} in body["cells"]


def test_partial_is_not_all_correct(filltable_on_unit, auth_client):
    element, _ = filltable_on_unit(
        [[{"kind": "answer", "answer": "1"}, {"kind": "answer", "answer": "2"}]]
    )
    r = _post(auth_client, element.pk, {"r0c0": "1", "r0c1": "99"})
    body = r.json()
    assert body["all_correct"] is False
    got = {(d["r"], d["c"]): d["correct"] for d in body["cells"]}
    assert got == {(0, 0): True, (0, 1): False}


def test_soft_pk_miss_returns_200_empty_set(auth_client):
    r = _post(auth_client, 999999, {"r0c0": "x"})
    assert r.status_code == 200
    assert r.json() == {"cells": [], "all_correct": False}


def test_zero_answer_cells_returns_all_correct_false(filltable_on_unit, auth_client):
    element, _ = filltable_on_unit([[{"kind": "static", "html": "a"}]])
    r = _post(auth_client, element.pk, {})
    assert r.json() == {"cells": [], "all_correct": False}


def test_missing_post_key_is_incorrect_not_500(filltable_on_unit, auth_client):
    element, _ = filltable_on_unit([[{"kind": "answer", "answer": "4"}]])
    r = _post(auth_client, element.pk, {})  # no r0c0
    assert r.status_code == 200
    assert r.json()["all_correct"] is False


def test_forbidden_user_denied(filltable_on_unit, other_auth_client):
    element, _ = filltable_on_unit([[{"kind": "answer", "answer": "4"}]], private=True)
    r = other_auth_client.post(
        reverse("courses:filltable_check", args=[element.pk]), {"r0c1": "4"}
    )
    # PermissionDenied surfaces per project convention
    assert r.status_code in (403, 404)


def test_get_not_allowed(auth_client):
    r = auth_client.get(reverse("courses:filltable_check", args=[1]))
    assert r.status_code == 405
