import pytest

from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


@pytest.mark.django_db
def test_no_leak_fragment_pre_reveal(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris", max_attempts=3)
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"Paris" not in resp.content


@pytest.mark.django_db
def test_no_leak_on_resume_render(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris", max_attempts=3)
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.get(f"{base}/")
    assert b"Paris" not in resp.content
