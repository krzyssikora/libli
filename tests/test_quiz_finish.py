from decimal import Decimal

import pytest

from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import UnitProgress
from tests.factories import EnrollmentFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _enrolled(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return user, unit


@pytest.mark.django_db
def test_finish_scores_partial_credit_and_unanswered_zero(client):
    user, unit = _enrolled(client)
    q1 = ShortTextQuestionElement.objects.create(stem="A?", accepted="x", max_marks=Decimal("2"))
    el1 = add_element(unit, q1)
    q2 = ShortTextQuestionElement.objects.create(stem="B?", accepted="y", max_marks=Decimal("3"))
    add_element(unit, q2)  # left unanswered

    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el1.pk}/answer/", {"answer": "x"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.post(f"{base}/finish/")
    assert resp.status_code == 302 and resp.url.endswith("/results/")

    sub = QuizSubmission.objects.get(student=user, unit=unit)
    assert sub.status == "submitted" and sub.submitted_at is not None
    assert sub.score == Decimal("2.00")        # q1 full, q2 unanswered=0
    assert sub.max_score == Decimal("5.00")    # 2 + 3
    assert UnitProgress.objects.get(student=user, unit=unit).completed


@pytest.mark.django_db
def test_finish_locks_all_responses_and_scores_wrong_as_zero(client):
    user, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(
        stem="A?", accepted="x", max_attempts=None, max_marks=Decimal("2")
    )
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "wrong"}, HTTP_X_REQUESTED_WITH="fetch")
    assert not QuestionResponse.objects.get(element=el).locked  # unlimited, not locked yet
    client.post(f"{base}/finish/")
    assert QuestionResponse.objects.get(element=el).locked       # Finish locked it
    sub = QuizSubmission.objects.get(student=user, unit=unit)
    # answered-wrong (fraction=0, NOT None) = 0 earned, still counted in max_score —
    # distinct from unanswered (no response) which is also 0/included.
    assert sub.score == Decimal("0.00") and sub.max_score == Decimal("2.00")


@pytest.mark.django_db
def test_results_reveals_correct_answer_for_all_auto_questions(client):
    user, unit = _enrolled(client)
    answered = ShortTextQuestionElement.objects.create(stem="A?", accepted="Paris", max_attempts=1)
    el1 = add_element(unit, answered)
    unanswered = ShortTextQuestionElement.objects.create(stem="B?", accepted="Rome")
    add_element(unit, unanswered)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el1.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content
    # §3.4 "reveal all": both the answered-wrong AND the unanswered question reveal.
    assert b"Paris" in body and b"Rome" in body


@pytest.mark.django_db
def test_finish_idempotent_freezes_score(client):
    user, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="A?", accepted="x", max_marks=Decimal("2"))
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "x"}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/finish/")
    q.max_marks = Decimal("99")  # author edits after submit
    q.save()
    client.post(f"{base}/finish/")  # second finish = no-op
    assert QuizSubmission.objects.get(student=user, unit=unit).max_score == Decimal("2.00")


@pytest.mark.django_db
def test_results_redirects_when_in_progress(client):
    user, unit = _enrolled(client)
    resp = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/results/")
    assert resp.status_code == 302 and resp.url.endswith("/quiz/")


@pytest.mark.django_db
def test_zero_auto_quiz_no_div_by_zero(client):
    user, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="R", accepted="", marking_mode="N")
    add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/finish/")
    sub = QuizSubmission.objects.get(student=user, unit=unit)
    assert sub.max_score == Decimal("0.00") and sub.score == Decimal("0.00")
    resp = client.get(f"{base}/results/")
    assert resp.status_code == 200
