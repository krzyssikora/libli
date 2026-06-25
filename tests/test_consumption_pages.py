import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_quiz_results_uses_result_vocabulary(client):
    user = make_login(client, "qr")
    course = CourseFactory(slug="qrc")
    EnrollmentFactory(student=user, course=course)
    unit = make_quiz_unit(course=course, title="Quiz One")
    QuizSubmissionFactory(student=user, unit=unit, status="submitted")
    resp = client.get(
        reverse("courses:quiz_results", kwargs={"slug": "qrc", "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "result-summary" in body
    assert "Quiz One" in body
