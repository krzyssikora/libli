"""Switch grid restore tests (student-practice-state graded self-checks slice).
Server-rendered locked appearance is asserted via the LESSON VIEW (str-keyed
UnitProgress seed, never obj.render() with a str key -- that misses the int
element.pk lookup build_lesson_context performs and silently renders the
unanswered branch). See courses.state._val_done and
courses.templatetags.courses_extras.render_switch_grid."""

import html
import json
import re

import pytest
from django.urls import reverse

from courses import fillblank
from courses.models import Element
from courses.models import Enrollment
from courses.models import SwitchGridElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_grid(unit, student, lines, blob):
    obj = SwitchGridElement.objects.create(prompt="", lines=lines)
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj


_ONE_CYCLER_LINE = [
    {
        "stem": f"3 {_tok(0)} 3 = 9",
        "cyclers": [{"options": ["+", "-", "x"], "answer": 2}],
    }
]


def test_switchgrid_stored_done_renders_locked_with_data_state(client):
    student = make_student(client, "sgrid_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_grid(unit, student, _ONE_CYCLER_LINE, {"done": True})

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True}
    assert re.search(r"data-switchgrid-cycler[^>]*\bdisabled\b", body)
    assert "switchgrid--locked" in body
    assert "switchgrid__confirm" not in body  # Confirm omitted when done
    assert "switchgrid--success" in body
    assert "Great!" in body
    # options[2] ("x") is the visible one; option[0] ("+") is hidden.
    assert re.search(
        r'<span class="switchgrid__option switchgrid__option--current">x</span>', body
    )
    assert re.search(r'<span class="switchgrid__option" hidden>\+</span>', body)


def test_switchgrid_unanswered_renders_editable(client):
    student = make_student(client, "sgrid_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_grid(unit, student, _ONE_CYCLER_LINE, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "switchgrid--locked" not in body
    assert "switchgrid__confirm" in body
    assert not re.search(r"data-switchgrid-cycler[^>]*\bdisabled\b", body)
    assert re.search(
        r'<span class="switchgrid__option switchgrid__option--current">\+</span>', body
    )


def test_switchgrid_out_of_range_answer_shows_nothing_no_crash(client):
    # A transfer/import could persist an out-of-range answer; render must not 500.
    student = make_student(client, "sgrid_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    bad_line = [
        {"stem": f"pick {_tok(0)}", "cyclers": [{"options": ["a", "b"], "answer": 5}]}
    ]
    _seed_grid(unit, student, bad_line, {"done": True})

    resp = client.get(_lesson_url(unit))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "switchgrid__option--current" not in body  # none un-hidden
