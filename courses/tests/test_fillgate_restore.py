import html
import json
import re

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillGateElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def test_canonical_answers_first_alternative_per_blank():
    el = FillGateElement(answers=[["color", "colour"], ["x"]])
    assert el.canonical_answers == ["color", "x"]


def test_canonical_answers_handles_empty_shapes():
    assert FillGateElement(answers=[]).canonical_answers == []
    assert FillGateElement(answers=[[]]).canonical_answers == [""]
    assert FillGateElement(answers=None).canonical_answers == []


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_fillgate(unit, student, author, blob):
    """Attach a FillGateElement (built from author {{answer}} markup) and, if `blob`
    is given, seed the student's UnitProgress.element_state for its join-row pk."""
    stem, answers = parse(author)
    obj = FillGateElement.objects.create(stem=stem, answers=answers)
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row


def test_fillgate_stored_open_renders_locked_with_data_state(client):
    student = make_student(client, "fg_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    row = _seed_fillgate(unit, student, "City: {{Constantinople}}", {"open": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"open": True}
    assert "fillgate--done" in body
    assert 'value="Constantinople"' in body
    assert "readonly" in body and "is-correct" in body
    assert 'size="14"' in body
    assert "fillgate__confirm" not in body  # Confirm suppressed when open
    assert f'data-element-pk="{row.pk}"' in body


def test_fillgate_unanswered_renders_editable(client):
    student = make_student(client, "fg_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_fillgate(unit, student, "City: {{Paris}}", None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "fillgate--done" not in body
    assert "readonly" not in body
    assert "fillgate__confirm" in body


def test_fillgate_barrier_div_is_direct_child_of_body(client):
    student = make_student(client, "fg_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_fillgate(unit, student, "City: {{Paris}}", {"open": True})

    body = client.get(_lesson_url(unit)).content.decode()

    # isGateWrapper + the prepaint CSS require the barrier as a DIRECT child of
    # .lesson-block__body -- no wrapper element. Falsify by wrapping the div.
    assert re.search(
        r'<div class="lesson-block__body">\s*<div[^>]*data-reveal-gate', body
    )
