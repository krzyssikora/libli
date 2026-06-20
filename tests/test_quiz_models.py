from decimal import Decimal

import pytest
from django.db import IntegrityError

from courses.models import ShortTextQuestionElement
from tests.factories import AttemptFactory
from tests.factories import ContentNodeFactory
from tests.factories import QuestionResponseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_question_marking_fields_defaults():
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    assert q.marking_mode == "A"
    assert q.max_attempts == 1
    assert q.max_marks == Decimal("1.00")


@pytest.mark.django_db
def test_question_max_attempts_nullable_for_unlimited():
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", max_attempts=None
    )
    q.refresh_from_db()
    assert q.max_attempts is None


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
