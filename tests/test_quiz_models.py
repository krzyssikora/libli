from decimal import Decimal

import pytest

from courses.models import ShortTextQuestionElement


@pytest.mark.django_db
def test_question_marking_fields_defaults():
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    assert q.marking_mode == "A"
    assert q.max_attempts == 1
    assert q.max_marks == Decimal("1.00")


@pytest.mark.django_db
def test_question_max_attempts_nullable_for_unlimited():
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a", max_attempts=None)
    q.refresh_from_db()
    assert q.max_attempts is None


from django.db import IntegrityError

from courses.models import Attempt, QuestionResponse, QuizSubmission
from tests.factories import (
    AttemptFactory,
    ContentNodeFactory,
    QuestionResponseFactory,
    QuizSubmissionFactory,
    UserFactory,
)


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
