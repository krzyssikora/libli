import pytest
from django.test import Client
from django.urls import reverse

from courses.models import FillTableElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db

S = "\uffff"


@pytest.fixture
def client_and_element():
    c = Client()
    user = make_login(c, "ftgap-owner")

    def _make(cells, **kw):
        course = CourseFactory(owner=user)
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=None
        )
        el = FillTableElement(data={"cells": cells, **kw})
        el.save()
        return c, add_element(unit, el)

    return _make


CELLS = [
    [
        {
            "kind": "static",
            "html": f"{S}0{S} and {S}1{S}",
            "gaps": [["9"], ["Ab", "x"]],
        },
        {"kind": "answer", "answer": "4"},
    ]
]


def _check(client, element, fields):
    r = client.post(reverse("courses:filltable_check", args=[element.pk]), fields)
    return r.json()


def test_each_gap_marked_separately(client_and_element):
    client, element = client_and_element(CELLS)
    data = _check(client, element, {"r0c0g0": "8", "r0c0g1": "x", "r0c1": "4"})
    by_key = {(d["r"], d["c"], d.get("g")): d["correct"] for d in data["cells"]}
    assert by_key == {(0, 0, 0): False, (0, 0, 1): True, (0, 1, None): True}
    assert data["all_correct"] is False


def test_all_correct_needs_answer_cells_and_gaps(client_and_element):
    client, element = client_and_element(CELLS)
    data = _check(client, element, {"r0c0g0": "9", "r0c0g1": "ab", "r0c1": "4"})
    assert data["all_correct"] is True
    data = _check(client, element, {"r0c0g0": "9", "r0c0g1": "ab", "r0c1": "5"})
    assert data["all_correct"] is False


def test_case_sensitivity_applies_to_gaps(client_and_element):
    client, element = client_and_element(CELLS, case_sensitive=True)
    data = _check(client, element, {"r0c0g0": "9", "r0c0g1": "ab", "r0c1": "4"})
    g1 = [d for d in data["cells"] if d.get("g") == 1][0]
    assert g1["correct"] is False


def test_gaps_only_table(client_and_element):
    client, element = client_and_element(
        [[{"kind": "static", "html": f"{S}0{S}", "gaps": [["9"]]}]]
    )
    data = _check(client, element, {"r0c0g0": "9"})
    assert data == {
        "cells": [{"r": 0, "c": 0, "g": 0, "correct": True}],
        "all_correct": True,
    }
