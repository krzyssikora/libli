import html
import json
import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import SwitchGateElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed_switchgate(unit, student, stem, options, answer, blob):
    obj = SwitchGateElement.objects.create(stem=stem, options=options, answer=answer)
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row


# The stem is a single-token stem (courses.switchgate.SENTINEL_TOKEN marks the
# cycler slot). Build it the way render_stem expects: text + sentinel + text.
def _stem():
    from courses.switchgate import SENTINEL_TOKEN

    return f"The answer is {SENTINEL_TOKEN}."


def test_switchgate_stored_open_shows_correct_option_locked(client):
    student = make_student(client, "sg_ro1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(
        unit,
        student,
        _stem(),
        ["<b>alpha</b>", "<b>beta</b>", "<b>gamma</b>"],
        2,
        {"open": True},
    )

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"open": True}
    assert "switchgate--done" in body
    assert re.search(
        r"data-switchgate-cycler[^>]*\bdisabled\b", body
    )  # cycler disabled (scoped, not the footer nav)
    assert "switchgate__confirm" not in body  # Confirm omitted when open
    # options[2] ("gamma") is the visible one; placeholder + others hidden.
    assert re.search(r'<span class="switchgate__option">\s*<b>gamma</b>', body)
    assert re.search(r'<span class="switchgate__option" hidden>\s*<b>alpha</b>', body)


def test_switchgate_unanswered_hides_all_options(client):
    student = make_student(client, "sg_ro2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(unit, student, _stem(), ["a", "b"], 1, None)

    body = client.get(_lesson_url(unit)).content.decode()

    assert 'data-state="{}"' in body
    assert "switchgate--done" not in body
    assert "switchgate__confirm" in body
    # Every option hidden (today's behaviour), placeholder visible.
    assert not re.search(r'<span class="switchgate__option">', body)
    assert re.search(
        r'<span class="switchgate__placeholder">', body
    )  # placeholder visible when unanswered


def test_switchgate_out_of_range_answer_shows_nothing_no_crash(client):
    # A transfer/import could persist an out-of-range answer; render must not 500.
    student = make_student(client, "sg_ro3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(unit, student, _stem(), ["a", "b"], 5, {"open": True})

    resp = client.get(_lesson_url(unit))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert not re.search(r'<span class="switchgate__option">', body)  # none un-hidden


def test_switchgate_barrier_div_is_direct_child_of_body(client):
    student = make_student(client, "sg_ro4")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_switchgate(unit, student, _stem(), ["a", "b"], 0, {"open": True})

    body = client.get(_lesson_url(unit)).content.decode()

    assert re.search(
        r'<div class="lesson-block__body">\s*<div[^>]*data-reveal-gate', body
    )
