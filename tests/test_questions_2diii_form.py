import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import ExtendedResponseQuestionElementForm

pytestmark = pytest.mark.django_db


def _data(**over):
    base = {
        "stem": "Explain.",
        "explanation": "",
        "required_keywords": "",
        "forbidden_keywords": "",
        "marking_mode": "A",
        "max_attempts": "1",
        "max_marks": "1",
    }
    base.update(over)
    return base


def test_registered_in_form_for_type():
    assert (
        FORM_FOR_TYPE["extendedresponsequestion"] is ExtendedResponseQuestionElementForm
    )


def test_auto_with_no_keywords_rejected():
    form = ExtendedResponseQuestionElementForm(data=_data(marking_mode="A"))
    assert not form.is_valid()
    assert "at least one" in str(form.errors).lower()


def test_auto_with_marking_mode_omitted_from_post_rejected():
    # Hidden-field lesson path: marking_mode absent -> effective AUTO -> reject.
    data = _data()
    data.pop("marking_mode")
    form = ExtendedResponseQuestionElementForm(data=data)
    assert not form.is_valid()


def test_review_with_no_keywords_accepted():
    form = ExtendedResponseQuestionElementForm(data=_data(marking_mode="R"))
    assert form.is_valid(), form.errors


def test_auto_with_required_keyword_accepted():
    form = ExtendedResponseQuestionElementForm(data=_data(required_keywords="alpha"))
    assert form.is_valid(), form.errors
