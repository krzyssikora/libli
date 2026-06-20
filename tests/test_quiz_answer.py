import pytest

from courses.models import Attempt, QuestionResponse, QuizSubmission
from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


def _setup(client, max_attempts=1, accepted="Paris"):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted=accepted, explanation="It's Paris.", max_attempts=max_attempts
    )
    el = add_element(unit, q)
    return user, unit, el


def _answer_url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


@pytest.mark.django_db
def test_correct_answer_reveals_locks_and_persists(client):
    user, unit, el = _setup(client, max_attempts=3)
    resp = client.post(_answer_url(unit, el), {"answer": "Paris"},
                       HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"Correct" in resp.content
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.attempt_count == 1
    assert r.fraction == 1 and r.earned_marks == 1
    assert Attempt.objects.filter(response=r).count() == 1


@pytest.mark.django_db
def test_wrong_with_attempts_left_withholds(client):
    user, unit, el = _setup(client, max_attempts=3)
    resp = client.post(_answer_url(unit, el), {"answer": "London"},
                       HTTP_X_REQUESTED_WITH="fetch")
    body = resp.content.decode()
    assert "Paris" not in body            # NO leak while attempts remain
    assert "It's Paris." not in body      # explanation withheld too
    assert "2" in body                    # attempts-left shown
    r = QuestionResponse.objects.get(element=el)
    assert not r.locked and r.attempt_count == 1


@pytest.mark.django_db
def test_wrong_on_last_attempt_reveals_and_locks(client):
    user, unit, el = _setup(client, max_attempts=1)
    resp = client.post(_answer_url(unit, el), {"answer": "London"},
                       HTTP_X_REQUESTED_WITH="fetch")
    body = resp.content.decode()
    assert "Paris" in body                # reveal on exhaustion
    r = QuestionResponse.objects.get(element=el)
    assert r.locked


@pytest.mark.django_db
def test_attempt_cap_rejects_after_exhaustion(client):
    user, unit, el = _setup(client, max_attempts=1)
    client.post(_answer_url(unit, el), {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.post(_answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409
    assert QuestionResponse.objects.get(element=el).attempt_count == 1


@pytest.mark.django_db
def test_empty_answer_does_not_burn_attempt(client):
    user, unit, el = _setup(client, max_attempts=2)
    resp = client.post(_answer_url(unit, el), {"answer": "   "}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"Enter an answer" in resp.content
    assert QuestionResponse.objects.filter(element=el).first() is None \
        or QuestionResponse.objects.get(element=el).attempt_count == 0


@pytest.mark.django_db
def test_empty_numeric_answer_does_not_burn_attempt(client):
    # Cross-type uniformity (spec §3.1 step 3): numeric empty submit is also guarded.
    from decimal import Decimal

    from tests.factories import ShortNumericQuestionElement
    user = make_login(client, "stunum")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortNumericQuestionElement.objects.create(
        stem="2+2?", value=Decimal("4"), tolerance=Decimal("0"), max_attempts=2
    )
    el = add_element(unit, q)
    resp = client.post(_answer_url(unit, el), {"answer": ""}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200 and b"Enter an answer" in resp.content
    assert not QuestionResponse.objects.filter(element=el, attempt_count__gt=0).exists()


@pytest.mark.django_db
def test_answer_after_submitted_is_rejected(client):
    user, unit, el = _setup(client)
    # Ensure the QuizSubmission exists before marking it submitted (the view's
    # get_or_create would create a fresh in_progress row if none exists).
    QuizSubmission.objects.get_or_create(student=user, unit=unit)
    QuizSubmission.objects.filter(student=user, unit=unit).update(status="submitted")
    resp = client.post(_answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409


@pytest.mark.django_db
def test_not_marked_records_without_score_and_locks(client):
    user = make_login(client, "stu2")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Reflect", accepted="", marking_mode="N", max_attempts=3
    )
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, {"answer": "my thoughts"}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"Answer recorded" in resp.content
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.fraction is None and r.earned_marks is None
    assert r.attempt_count == 1
    a = Attempt.objects.get(response=r)
    assert a.fraction is None and a.correct is None


@pytest.mark.django_db
def test_not_marked_second_submit_rejected_despite_high_cap(client):
    user = make_login(client, "stu3")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Reflect", accepted="", marking_mode="N", max_attempts=5)
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    client.post(url, {"answer": "first"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.post(url, {"answer": "second"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409  # locked after first, cap irrelevant
