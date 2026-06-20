import pytest

from courses.element_forms import ShortTextQuestionElementForm


@pytest.mark.django_db
def test_quiz_question_form_accepts_marking_fields():
    form = ShortTextQuestionElementForm(data={
        "stem": "Q", "explanation": "", "accepted": "a", "case_sensitive": False,
        "marking_mode": "A", "max_attempts": 2, "max_marks": "3",
    })
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    assert obj.max_attempts == 2 and str(obj.max_marks) == "3"


@pytest.mark.django_db
def test_quiz_question_form_rejects_zero_max_marks():
    form = ShortTextQuestionElementForm(data={
        "stem": "Q", "explanation": "", "accepted": "a", "case_sensitive": False,
        "marking_mode": "A", "max_attempts": 1, "max_marks": "0",
    })
    assert not form.is_valid()
    assert "max_marks" in form.errors
