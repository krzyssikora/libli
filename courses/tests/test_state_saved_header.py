"""check_answer tells question.js whether it STORED practice state (spec §4).

The header is the only signal question.js gets: the response body is HTML. It must be
set on BOTH fragment return points -- the INLINE_LESSON_FEEDBACK full-element render
(choice, short text, ...) and the _question_feedback.html render (extended response).
"""

import pytest
from django.urls import reverse

from courses import views
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

H = views.STATE_SAVED_HEADER


def _enrolled(client):
    student = make_verified_user()
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student, course, unit


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _choice(unit):
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=False)
    right = Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    Choice.objects.create(question=q, text="B", is_correct=False, order=1)
    row = Element.objects.create(unit=unit, content_object=q)
    return row, right


def test_header_constant_is_the_agreed_name():
    assert H == "X-Libli-State-Saved"


def test_inline_type_nonempty_answer_sets_header(client):
    _s, _c, unit = _enrolled(client)
    row, right = _choice(unit)
    assert ChoiceQuestionElement.INLINE_LESSON_FEEDBACK is True  # anti-vacuity
    r = client.post(
        _check_url(unit, row.pk), {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert r.status_code == 200
    assert r.headers.get(H) == "1"


def test_non_inline_restorable_type_nonempty_answer_sets_header(client):
    _s, _c, unit = _enrolled(client)
    q = ExtendedResponseQuestionElement.objects.create(stem="Explain")
    row = Element.objects.create(unit=unit, content_object=q)
    # anti-vacuity: this is the _question_feedback.html return point
    assert not ExtendedResponseQuestionElement.INLINE_LESSON_FEEDBACK
    assert ExtendedResponseQuestionElement.RESTORABLE_IN_LESSON
    r = client.post(
        _check_url(unit, row.pk),
        {"answer": "some words"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert r.status_code == 200
    assert r.headers.get(H) == "1"


def test_empty_answer_sets_no_header(client):
    _s, _c, unit = _enrolled(client)
    row, _right = _choice(unit)
    r = client.post(_check_url(unit, row.pk), {}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 200
    assert H not in r.headers


def test_non_restorable_question_sets_no_header(client, monkeypatch):
    _s, _c, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = Element.objects.create(unit=unit, content_object=q)
    monkeypatch.setattr(ShortTextQuestionElement, "RESTORABLE_IN_LESSON", False)
    r = client.post(
        _check_url(unit, row.pk), {"answer": "paris"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert r.status_code == 200
    assert H not in r.headers


def test_no_js_branch_sets_no_header(client):
    # The no-JS full-page branch never carries the header (no client reads it). The
    # render half of Review Focus 3 lives in test_reset_controls.py (Task 2).
    _s, _c, unit = _enrolled(client)
    row, right = _choice(unit)
    r = client.post(_check_url(unit, row.pk), {"choice": [right.pk]})
    assert r.status_code == 200
    assert H not in r.headers
