from decimal import Decimal

import pytest
from django.urls import reverse

from courses.forms import ReviewResponseForm
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_review_form_accepts_marks_within_bounds():
    form = ReviewResponseForm(
        {"earned_marks": "3.50", "feedback": "ok"}, max_marks=Decimal("5")
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["earned_marks"] == Decimal("3.50")
    assert form.cleaned_data["feedback"] == "ok"


def test_review_form_rejects_over_max():
    form = ReviewResponseForm(
        {"earned_marks": "6", "feedback": ""}, max_marks=Decimal("5")
    )
    assert not form.is_valid()
    assert "earned_marks" in form.errors


def test_review_form_rejects_negative():
    form = ReviewResponseForm(
        {"earned_marks": "-1", "feedback": ""}, max_marks=Decimal("5")
    )
    assert not form.is_valid()


def test_review_form_feedback_optional():
    form = ReviewResponseForm({"earned_marks": "0"}, max_marks=Decimal("5"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["feedback"] == ""


def _review_quiz(course):
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    return unit, Element.objects.create(unit=unit, content_object=q)


def test_review_queue_lists_awaiting(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, _ = _review_quiz(course)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    resp = client.get(
        reverse("courses:manage_review_queue", kwargs={"slug": course.slug})
    )
    assert resp.status_code == 200
    # Template renders display_name (set by UserFactory via Faker); fall back to
    # username only when display_name is blank. Assert on display_name since that
    # is what the template outputs for a factory-created user.
    assert student.display_name in resp.content.decode()


def test_review_queue_404_for_unrelated_user(client):
    make_login(client, "nobody")
    course = CourseFactory(owner=UserFactory())
    resp = client.get(
        reverse("courses:manage_review_queue", kwargs={"slug": course.slug})
    )
    assert resp.status_code == 404


def test_review_submission_shows_review_questions(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, el = _review_quiz(course)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    resp = client.get(
        reverse(
            "courses:manage_review_submission",
            kwargs={"slug": course.slug, "submission_pk": sub.pk},
        )
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Explain." in body  # the [R] stem
    assert "Marks awarded" in body  # the form label


def test_review_submission_cross_course_404(client):
    pa = make_pa(client)
    course_a = CourseFactory(owner=pa)
    course_b = CourseFactory(owner=pa)
    unit_b, _ = _review_quiz(course_b)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course_b)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit_b,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    # submission belongs to course_b but we ask via course_a's slug
    resp = client.get(
        reverse(
            "courses:manage_review_submission",
            kwargs={"slug": course_a.slug, "submission_pk": sub.pk},
        )
    )
    assert resp.status_code == 404


def test_review_post_grades_and_redirects(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, el = _review_quiz(course)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    resp = client.post(
        url, {"element_pk": el.pk, "earned_marks": "4.00", "feedback": "well done"}
    )
    assert resp.status_code == 302
    r = QuestionResponse.objects.get(submission=sub, element=el)
    assert r.earned_marks == Decimal("4.00")
    assert r.review_feedback == "well done"
    sub.refresh_from_db()
    assert sub.score == Decimal("4.00")


def test_review_post_invalid_marks_422(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit, el = _review_quiz(course)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    resp = client.post(url, {"element_pk": el.pk, "earned_marks": "99", "feedback": ""})
    assert resp.status_code == 422


def test_force_submit_post_closes_and_redirects(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.IN_PROGRESS
    )
    url = reverse(
        "courses:manage_review_force_submit",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    resp = client.post(url)
    assert resp.status_code == 302
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.submitted_by_id == pa.pk


def test_force_submit_get_not_allowed(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.IN_PROGRESS
    )
    resp = client.get(
        reverse(
            "courses:manage_review_force_submit",
            kwargs={"slug": course.slug, "submission_pk": sub.pk},
        )
    )
    assert resp.status_code == 405
