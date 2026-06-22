import pytest
from django.utils import translation

from tests.factories import EnrollmentFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_course_results_polish(client):
    user = make_login(client, "plstu")
    from tests.factories import CourseFactory

    course = CourseFactory()
    EnrollmentFactory(student=user, course=course)
    session = client.session
    session["_language"] = "pl"
    session.save()
    with translation.override("pl"):
        resp = client.get(
            f"/courses/{course.slug}/results/", HTTP_ACCEPT_LANGUAGE="pl"
        )
    assert "Moje wyniki".encode() in resp.content
    assert "Ten kurs nie ma jeszcze quizów".encode() in resp.content  # empty-state
