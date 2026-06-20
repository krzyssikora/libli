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
