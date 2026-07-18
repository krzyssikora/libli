"""Fill-in table restore tests (student-practice-state graded self-checks
slice). The locked-appearance behavioural assertions go through the LESSON
VIEW (str-keyed UnitProgress seed, never obj.render() with a str key). The
self.data no-mutation guard is a pure Python-level invariant and calls
obj.render() directly with an INT-keyed state dict -- render()'s own contract,
not the str/int UnitProgress.element_state seam. See courses.state._val_done,
FillTableElement.canonical_cells, and FillTableElement.render()."""

import html
import json
import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import FillTableElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


_CELLS = [
    [{"kind": "static", "html": "czas"}, {"kind": "static", "html": "woda"}],
    [{"kind": "static", "html": "0"}, {"kind": "answer", "answer": "4 | four"}],
]


def _seed_filltable(unit, student, cells, blob):
    obj = FillTableElement(data={"cells": cells})
    obj.save()
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


def test_filltable_stored_done_renders_locked_with_data_state(client):
    student = make_student(client, "ftbl_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, _CELLS, {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True}
    assert (
        '<input type="text" class="filltable__input filltable__input--correct" '
        'data-r="1" data-c="1" value="4" readonly' in body
    )
    assert "filltable__confirm" not in body  # Confirm omitted when done
    assert "filltable__summary--success" in body
    assert "Great!" in body


def test_filltable_unanswered_renders_editable(client):
    student = make_student(client, "ftbl_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, _CELLS, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "filltable__input--correct" not in body
    assert "filltable__confirm" in body
    assert (
        '<input type="text" class="filltable__input" data-r="1" data-c="1" '
        "aria-label=" in body
    )


def test_filltable_done_render_empty_alternatives_shows_empty_value(client):
    student = make_student(client, "ftbl_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, [[{"kind": "answer", "answer": ""}]], {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'value=""' in body
    assert "filltable__input--correct" in body


def test_filltable_render_does_not_mutate_self_data_on_done():
    course, unit = make_course_with_unit()
    obj = FillTableElement(data={"cells": [[{"kind": "answer", "answer": "4 | four"}]]})
    obj.save()
    row = Element.objects.create(unit=unit, content_object=obj)
    before = json.dumps(obj.data, sort_keys=True)

    obj.render(
        element=row,
        state={row.pk: {"done": True}},
        slug=unit.course.slug,
        node_pk=unit.pk,
    )

    assert json.dumps(obj.data, sort_keys=True) == before
