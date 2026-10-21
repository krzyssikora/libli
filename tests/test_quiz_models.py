from decimal import Decimal

import pytest
from django.db import IntegrityError

from courses.models import ShortTextQuestionElement
from tests.factories import AttemptFactory
from tests.factories import ContentNodeFactory
from tests.factories import QuestionResponseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import attempts


@pytest.mark.django_db
def test_question_marking_fields_defaults():
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    assert q.marking_mode == "A"
    # a fresh question INHERITS (spec 2026-10-20 D9); the quiz/course decides
    assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    assert q.max_marks == Decimal("1.00")


@pytest.mark.django_db
def test_question_attempts_nullable_for_unlimited():
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", **attempts(None)
    )
    q.refresh_from_db()
    assert (q.attempts_mode, q.attempts_limit) == ("unlimited", None)


@pytest.mark.django_db
def test_quizsubmission_stamps_submitted_at():
    sub = QuizSubmissionFactory(status="submitted", submitted_at=None)
    assert sub.submitted_at is not None


@pytest.mark.django_db
def test_quizsubmission_unique_student_unit():
    student = UserFactory()
    unit = ContentNodeFactory(unit_type="quiz")
    QuizSubmissionFactory(student=student, unit=unit)
    with pytest.raises(IntegrityError):
        QuizSubmissionFactory(student=student, unit=unit)


@pytest.mark.django_db
def test_attempt_fraction_correct_nullable():
    a = AttemptFactory(fraction=None, correct=None)
    a.refresh_from_db()
    assert a.fraction is None and a.correct is None


@pytest.mark.django_db
def test_attempt_unique_response_n():
    resp = QuestionResponseFactory()
    AttemptFactory(response=resp, n=1)
    with pytest.raises(IntegrityError):
        AttemptFactory(response=resp, n=1)


@pytest.mark.django_db
def test_questionresponse_unique_submission_element():
    resp = QuestionResponseFactory()
    with pytest.raises(IntegrityError):
        QuestionResponseFactory(submission=resp.submission, element=resp.element)
