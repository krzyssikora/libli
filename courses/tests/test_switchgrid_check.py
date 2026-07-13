import json

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGridElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


@pytest.fixture
def enrolled_unit():
    course = CourseFactory()
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )


@pytest.fixture
def enrolled_client(client, enrolled_unit):
    user = make_login(client, "switchgrid-student")
    EnrollmentFactory(student=user, course=enrolled_unit.course)
    return client


@pytest.fixture
def client_without_access(client):
    make_login(client, "switchgrid-outsider")
    return client


def _make_grid(enrolled_unit, lines):
    el = SwitchGridElement.objects.create(lines=lines)
    join = Element.objects.create(
        unit=enrolled_unit,
        content_type=ContentType.objects.get_for_model(SwitchGridElement),
        object_id=el.pk,
    )
    return join


def _url(pk):
    return reverse("courses:switchgrid_check", args=[pk])


_LINES = [
    {"stem": "s", "cyclers": []},  # static line -> []
    {"stem": "t", "cyclers": [{"options": ["+", "-", "x"], "answer": 2}]},
    {"stem": "u", "cyclers": [{"options": [":", "-"], "answer": 0}]},
]


def test_all_correct(enrolled_client, enrolled_unit):
    join = _make_grid(enrolled_unit, _LINES)
    r = enrolled_client.post(_url(join.pk), {"indices": json.dumps([[], [2], [0]])})
    assert r.status_code == 200
    assert r.json() == {"correct": True, "cells": [[], [True], [True]]}


def test_one_wrong(enrolled_client, enrolled_unit):
    join = _make_grid(enrolled_unit, _LINES)
    r = enrolled_client.post(_url(join.pk), {"indices": json.dumps([[], [0], [0]])})
    data = r.json()
    assert data["correct"] is False
    assert data["cells"] == [[], [False], [True]]


def test_unresolved_pk_soft_200(enrolled_client):
    r = enrolled_client.post(_url(999999), {"indices": "[[2]]"})
    assert r.status_code == 200
    assert r.json() == {"correct": False, "cells": []}


def test_wrong_type_pk_soft_200(enrolled_client, enrolled_unit):
    # a REAL Element join whose content_object is a *different* element type ->
    # the isinstance(...) check misses -> soft 200 {correct:false, cells:[]} (NOT 404).
    text = TextElement.objects.create(body="<p>hi</p>")
    join = Element.objects.create(
        unit=enrolled_unit,
        content_type=ContentType.objects.get_for_model(TextElement),
        object_id=text.pk,
    )
    r = enrolled_client.post(_url(join.pk), {"indices": "[[2]]"})
    assert r.status_code == 200
    assert r.json() == {"correct": False, "cells": []}


@pytest.mark.parametrize("bad", ["not json", "{}", "[1,2,3]", ""])
def test_ill_shaped_indices_no_500(enrolled_client, enrolled_unit, bad):
    join = _make_grid(enrolled_unit, _LINES)
    r = enrolled_client.post(_url(join.pk), {"indices": bad})
    assert r.status_code == 200
    assert r.json()["correct"] is False


def test_short_payload_and_out_of_range_count_incorrect(enrolled_client, enrolled_unit):
    join = _make_grid(enrolled_unit, _LINES)
    # missing 3rd sublist entirely + out-of-range index in the one supplied
    r = enrolled_client.post(_url(join.pk), {"indices": json.dumps([[], [], [99]])})
    data = r.json()
    assert data["correct"] is False
    assert data["cells"] == [[], [False], [False]]


def test_get_405(enrolled_client, enrolled_unit):
    join = _make_grid(enrolled_unit, _LINES)
    assert enrolled_client.get(_url(join.pk)).status_code == 405


def test_access_denied_non_200(client_without_access, enrolled_unit):
    join = _make_grid(enrolled_unit, _LINES)
    indices = json.dumps([[], [2], [0]])
    r = client_without_access.post(_url(join.pk), {"indices": indices})
    assert r.status_code in (403, 302)


def test_no_marks_persisted(enrolled_client, enrolled_unit):
    from courses.models import QuestionResponse

    join = _make_grid(enrolled_unit, _LINES)
    before = QuestionResponse.objects.count()
    enrolled_client.post(_url(join.pk), {"indices": json.dumps([[], [2], [0]])})
    assert QuestionResponse.objects.count() == before
