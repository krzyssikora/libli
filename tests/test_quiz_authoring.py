from decimal import Decimal

import pytest

from courses.element_forms import ShortTextQuestionElementForm
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_quiz_question_form_accepts_marking_fields():
    form = ShortTextQuestionElementForm(
        unit=make_quiz_unit(),
        data={
            "stem": "Q",
            "explanation": "",
            "accepted": "a",
            "case_sensitive": False,
            "marking_mode": "A",
            "attempts_mode": "limited",
            "attempts_limit": "2",
            "max_marks": "3",
        },
    )
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    assert (obj.attempts_mode, obj.attempts_limit) == ("limited", 2) and str(
        obj.max_marks
    ) == "3"


@pytest.mark.django_db
def test_quiz_question_form_rejects_zero_max_marks():
    form = ShortTextQuestionElementForm(
        unit=make_quiz_unit(),
        data={
            "stem": "Q",
            "explanation": "",
            "accepted": "a",
            "case_sensitive": False,
            "marking_mode": "A",
            "attempts_mode": "limited",
            "attempts_limit": "1",
            "max_marks": "0",
        },
    )
    assert not form.is_valid()
    assert "max_marks" in form.errors


@pytest.mark.django_db
def test_question_form_valid_without_marking_fields_uses_model_defaults():
    form = ShortTextQuestionElementForm(
        unit=make_quiz_unit(),
        data={
            "stem": "Q",
            "explanation": "",
            "accepted": "a",
            "case_sensitive": False,
        },
    )
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    obj.save()
    obj.refresh_from_db()
    assert obj.marking_mode == "A"
    assert obj.attempts_mode == "inherit"
    assert obj.max_marks == Decimal("1.00")
