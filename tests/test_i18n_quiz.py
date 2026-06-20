import pytest
from django.utils import translation

from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


@pytest.mark.django_db
def test_quiz_finish_label_translated_pl(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="a")
    add_element(unit, q)
    # This project's SessionLocaleMiddleware reads the session language key;
    # set it to "pl" so the view renders in Polish (mirrors make_login + language-switch flow).
    session = client.session
    session["_language"] = "pl"
    session.save()
    with translation.override("pl"):
        resp = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/",
                          HTTP_ACCEPT_LANGUAGE="pl")
    # The PL translation of "Finish quiz" (set in Step 3) must appear.
    assert "Zakończ quiz".encode() in resp.content
