import pytest

from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


def _enrolled_q(client, max_attempts=3):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", explanation="It's Paris.", max_attempts=max_attempts
    )
    el = add_element(unit, q)
    return user, unit, el


@pytest.mark.django_db
def test_resume_prefills_last_answer(client):
    user, unit, el = _enrolled_q(client)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.get(f"{base}/")
    assert b'value="London"' in resp.content


@pytest.mark.django_db
def test_resume_does_not_leak_for_unrevealed_question(client):
    user, unit, el = _enrolled_q(client)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.get(f"{base}/")          # reload
    assert b"Paris" not in resp.content    # withhold survives reload
