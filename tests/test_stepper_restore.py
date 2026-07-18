"""Stepper restore render tests (student-practice-state). Behavioural assertions
go through the LESSON VIEW (str-keyed UnitProgress seed), never obj.render() with a
str key -- the int/str-key seam. See courses.state._val_stepper."""

import html
import json
import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import StepperElement
from courses.models import StepperStep
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_stepper(unit, student, n_steps, blob):
    obj = StepperElement.objects.create(prompt="P")
    for i in range(n_steps):
        StepperStep.objects.create(stepper=obj, content=f"s{i}")
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


def test_stored_shown_renders_data_state(client):
    student = make_student(client, "stp_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_stepper(unit, student, 4, {"shown": 3})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'class="stepper"[^>]*data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"shown": 3}
    assert "data-element-pk=" in body
    assert "data-state-url=" in body


def test_unseeded_stepper_renders_empty_state(client):
    student = make_student(client, "stp_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_stepper(unit, student, 3, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert re.search(r'class="stepper"[^>]*data-state="\{\}"', body)
