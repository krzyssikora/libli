import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _login(client):
    # make_login force_logins (bypasses allauth's mandatory-verification middleware —
    # the gotcha documented in tests/factories.py). Do NOT use client.login here.
    return make_login(client, "stu")


def _question_in_lesson(course, *, multiple=False):
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    q = ChoiceQuestionElement.objects.create(stem="2+2?", multiple=multiple)
    right = Choice.objects.create(question=q, text="4", is_correct=True)
    wrong = Choice.objects.create(question=q, text="5", is_correct=False)
    el = Element.objects.create(unit=unit, content_object=q)
    return unit, el, q, right, wrong


@pytest.mark.django_db
def test_initial_render_has_no_correctness_signal(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert 'name="choice"' in body
    assert f'value="{right.pk}"' in body and f'value="{wrong.pk}"' in body
    # No correctness leaks to the initial page:
    assert "is_correct" not in body
    assert "data-correct" not in body
    assert "answer-correct" not in body  # the feedback CSS class (Task 5)


@pytest.mark.django_db
def test_check_answer_correct_fragment(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    # Assert on the locale-independent verdict CSS class, not the English word
    # (the verdict text is {% trans %}'d; "is-correct" is not a substring of
    # "is-incorrect" or "answer-correct", so it's a clean discriminator).
    assert b"is-correct" in resp.content


@pytest.mark.django_db
def test_correct_fragment_suppresses_reveal_keeps_explanation(client):
    # A fully-correct lesson answer is terse: verdict only, no per-item reveal
    # (no redundant ✓ per choice). The author explanation is still shown.
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    q.explanation = "<p>Because two plus two is four.</p>"
    q.save()
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    body = resp.content.decode()
    assert "is-correct" in body  # verdict still shown
    assert "Because two plus two is four." in body  # explanation kept
    # The per-item reveal block is suppressed on a fully-correct answer:
    assert "answer-correct" not in body
    assert "question__tick" not in body
    assert "question__reveal" not in body


@pytest.mark.django_db
def test_check_answer_incorrect_and_reveals(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [wrong.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content


@pytest.mark.django_db
def test_check_answer_empty_submission_is_incorrect(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content


@pytest.mark.django_db
def test_check_answer_drops_foreign_choice_ids(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    other_q = ChoiceQuestionElement.objects.create(stem="x", multiple=False)
    foreign = Choice.objects.create(question=other_q, text="z", is_correct=True)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    # foreign id is dropped -> treated as empty -> incorrect (never errors)
    resp = client.post(url, {"choice": [foreign.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content


@pytest.mark.django_db
def test_check_answer_404s_on_quiz_unit(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    Choice.objects.create(question=q, text="a", is_correct=True)
    el = Element.objects.create(unit=unit, content_object=q)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": []}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_check_answer_404s_for_element_in_other_unit(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    other_unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": other_unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_no_js_post_rerenders_whole_lesson_with_feedback(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]})  # no X-Requested-With → full page
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "lesson-unit__title" in body  # whole lesson page, not just a fragment
    assert "is-correct" in body


@pytest.mark.django_db
def test_post_submit_page_reveals_only_the_answered_question(client):
    # Spec §4(b): on a post-submit page, reveal data appears for the answered
    # question ONLY — every other question stays clean. Answer WRONG so the
    # reveal still renders (fully-correct now suppresses the per-item reveal).
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    q2 = ChoiceQuestionElement.objects.create(stem="3+3?", multiple=False)
    Choice.objects.create(question=q2, text="6", is_correct=True)
    Choice.objects.create(question=q2, text="7", is_correct=False)
    Element.objects.create(
        unit=unit, content_object=q2
    )  # a SECOND, unanswered question
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [wrong.pk]})  # no-JS full page
    body = resp.content.decode()
    # Exactly one reveal block (the answered question's correct choice still
    # marked answer-correct); the second question renders no feedback / no signal.
    assert body.count("answer-correct") == 1
