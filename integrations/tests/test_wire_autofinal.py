import pytest
from django.urls import reverse

from courses.models import Enrollment
from courses.models import QuizSubmission
from courses.review import force_submit_quiz
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def _enrolled_student(client, course):
    """Create a verified+logged-in user enrolled in `course`.

    Uses make_login (not a bare UserFactory + force_login) because it builds a
    verified EmailAddress row, matching the existing precedent in
    notifications/tests/test_wire_review.py::test_quiz_finish_by_student_emits_needs_review
    for driving the real quiz_finish view through the test client under
    ACCOUNT_EMAIL_VERIFICATION = "mandatory".
    """
    student = make_login(client, "wire_autofinal_student")
    Enrollment.objects.create(student=student, course=course, source="manual")
    return student


def test_force_submit_autograded_enqueues_from_locked_instance():
    """force_submit passes the finalized `locked` row, not the un-finalized
    parameter — so score/max_score are non-null and the enqueue succeeds."""
    _enable()
    unit = make_quiz_unit()  # no [R] questions → auto-final on submit
    unit.course.external_id = "MATH-A"
    unit.course.save(update_fields=["external_id"])
    student = UserFactory()
    sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.IN_PROGRESS
    )
    teacher = UserFactory()
    force_submit_quiz(sub, by=teacher)
    assert WebhookDelivery.objects.count() == 1
    row = WebhookDelivery.objects.get()
    assert row.payload["score"]["earned"] is not None


def test_quiz_finish_enqueues_once_and_rehit_does_not_duplicate(client):
    """Student self-finish of an auto-graded quiz emits exactly one delivery; a
    second POST to the finish URL (already SUBMITTED) does NOT re-emit — proving
    the emit sits inside the `status != SUBMITTED` guard, not merely in atomic()."""
    _enable()
    unit = make_quiz_unit()  # no [R] questions → auto-final
    course = unit.course
    course.external_id = "MATH-A"
    course.save(update_fields=["external_id"])
    _enrolled_student(client, course)
    url = reverse(
        "courses:quiz_finish", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    client.post(url)
    assert WebhookDelivery.objects.count() == 1
    client.post(url)  # re-hit: submission already SUBMITTED
    assert WebhookDelivery.objects.count() == 1  # no duplicate
