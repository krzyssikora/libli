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


@pytest.mark.django_db
def test_course_results_uses_result_rows(client):
    from tests.factories import make_quiz_unit

    user = make_login(client, "cr")
    course = CourseFactory(slug="crc", title="Course X")
    EnrollmentFactory(student=user, course=course)
    # one quiz unit → build_course_results yields one row (status "not started"),
    # which exercises the result-row branch and the {% url row.url_name %} path.
    make_quiz_unit(course=course, title="Quiz Alpha")
    resp = client.get(reverse("courses:course_results", kwargs={"slug": "crc"}))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "result-summary" in body
    assert "result-row" in body
    assert "Quiz Alpha" in body
    assert "Course X" in body


@pytest.mark.django_db
def test_my_courses_renders_cards(client):
    user = make_login(client, "mc")
    course = CourseFactory(slug="mcc", title="Algebra")
    EnrollmentFactory(student=user, course=course)
    resp = client.get(reverse("courses:my_courses"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "dash-card" in body
    assert "Algebra" in body
