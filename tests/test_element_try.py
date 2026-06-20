"""Authoring 'try-it' preview endpoint: a manage-gated, NON-persisting grader that
returns the same feedback partial students get, so an author can test a question in
the live preview without enrolling or writing any QuestionResponse rows."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import QuestionResponse
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _quiz_unit(course):
    return ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")


def _question(unit, *, multiple=False, max_attempts=1):
    q = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", multiple=multiple, max_attempts=max_attempts
    )
    a = Choice.objects.create(question=q, text="A", is_correct=True)
    b = Choice.objects.create(question=q, text="B", is_correct=False)
    return add_element(unit, q), a, b


def _url(course, el):
    return reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk}
    )


@pytest.mark.django_db
def test_try_correct_answer_is_correct_and_persists_nothing(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    el, a, _b = _question(unit)
    resp = client.post(
        _url(course, el), {"choice": str(a.pk)}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200
    assert b"is-correct" in resp.content
    assert b"is-incorrect" not in resp.content
    assert QuestionResponse.objects.count() == 0  # try-it never persists


@pytest.mark.django_db
def test_try_wrong_answer_is_incorrect(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    el, _a, b = _question(unit)
    resp = client.post(
        _url(course, el), {"choice": str(b.pk)}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
def test_try_requires_manage_permission(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    el, a, _b = _question(unit)
    # A user who cannot manage this course must be denied the authoring endpoint.
    other = get_user_model().objects.create_user(
        username="stranger", password="pw12345!"
    )
    client.force_login(other)
    resp = client.post(
        _url(course, el), {"choice": str(a.pk)}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code in (403, 404)
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
def test_try_rejects_non_question_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    el = add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    resp = client.post(_url(course, el), {"choice": "1"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_try_lesson_reveals_answer_immediately(client):
    # Lessons are instant-feedback: a wrong answer reveals the correct one right away.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    el, _a, b = _question(unit)
    resp = client.post(
        _url(course, el), {"choice": str(b.pk)}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert b"is-incorrect" in resp.content
    assert b"answer-correct" in resp.content  # correct choice revealed


@pytest.mark.django_db
def test_try_quiz_withholds_reveal_while_attempts_remain(client):
    # On a quiz, a wrong answer with attempts left shows NO correct answer.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, _a, b = _question(unit, max_attempts=2)
    resp = client.post(
        _url(course, el),
        {"choice": str(b.pk), "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content
    assert b"answer-correct" not in resp.content  # reveal withheld
    assert b"data-quiz-locked" not in resp.content  # not terminal yet
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
def test_try_quiz_reveals_on_last_attempt(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, _a, b = _question(unit, max_attempts=2)
    resp = client.post(
        _url(course, el),
        {"choice": str(b.pk), "attempt": "2"},  # last attempt
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"is-incorrect" in resp.content
    assert b"answer-correct" in resp.content  # revealed now
    assert b"data-quiz-locked" in resp.content
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
def test_try_quiz_reveals_on_correct(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, a, _b = _question(unit, max_attempts=3)
    resp = client.post(
        _url(course, el),
        {"choice": str(a.pk), "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"is-correct" in resp.content
    assert b"answer-correct" in resp.content
    assert b"data-quiz-locked" in resp.content
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
def test_try_quiz_empty_answer_is_validation(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el, _a, _b = _question(unit, max_attempts=2)
    resp = client.post(
        _url(course, el), {"attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert b"is-validation" in resp.content
    assert b"data-quiz-locked" not in resp.content


@pytest.mark.django_db
def test_try_rejects_get(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    el, _a, _b = _question(unit)
    resp = client.get(_url(course, el), HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 405
