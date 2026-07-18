"""Guess-the-number restore tests (student-practice-state graded self-checks
slice). Server-rendered locked appearance is asserted via the LESSON VIEW
(str-keyed UnitProgress seed, never obj.render() with a str key). See
courses.state._val_done, GuessNumberElement.canonical_target, and
courses.templatetags.courses_extras.render_guess_number."""

import html
import json
import re
from decimal import Decimal

import pytest
from django.urls import reverse

from courses import guessnumber
from courses.models import Element
from courses.models import Enrollment
from courses.models import GuessNumberElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_guessnumber(unit, student, author_stem, blob, success_message=""):
    token_stem, raw = guessnumber.parse_stem(author_stem)
    obj = GuessNumberElement.objects.create(
        stem=token_stem, target=Decimal(raw), success_message=success_message
    )
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


def test_guessnumber_stored_done_renders_locked_with_data_state(client):
    student = make_student(client, "gn_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_guessnumber(unit, student, "Guess: {{40401}}", {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True}
    assert "guessnumber--done" in body
    assert 'value="40401"' in body  # canonical_target -- no E-notation
    assert "readonly" in body
    assert "is-correct" in body
    assert "data-guess-check" not in body  # Check omitted entirely when done
    assert "Correct!" in body  # blank success_message falls back
    assert "<div data-guess-success>" in body  # un-hidden


def test_guessnumber_unanswered_renders_editable(client):
    student = make_student(client, "gn_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_guessnumber(unit, student, "Guess: {{42}}", None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "guessnumber--done" not in body
    assert "data-guess-check" in body
    assert "readonly" not in body
    assert "<div data-guess-success hidden>" in body


def test_guessnumber_canonical_target_avoids_e_notation_end_to_end(client):
    student = make_student(client, "gn_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_guessnumber(unit, student, "Guess: {{40401.5}}", {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'value="40401.5"' in body
    assert "E+" not in body
