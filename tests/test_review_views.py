from decimal import Decimal

import pytest

from courses.forms import ReviewResponseForm

pytestmark = pytest.mark.django_db


def test_review_form_accepts_marks_within_bounds():
    form = ReviewResponseForm(
        {"earned_marks": "3.50", "feedback": "ok"}, max_marks=Decimal("5")
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["earned_marks"] == Decimal("3.50")
    assert form.cleaned_data["feedback"] == "ok"


def test_review_form_rejects_over_max():
    form = ReviewResponseForm(
        {"earned_marks": "6", "feedback": ""}, max_marks=Decimal("5")
    )
    assert not form.is_valid()
    assert "earned_marks" in form.errors


def test_review_form_rejects_negative():
    form = ReviewResponseForm(
        {"earned_marks": "-1", "feedback": ""}, max_marks=Decimal("5")
    )
    assert not form.is_valid()


def test_review_form_feedback_optional():
    form = ReviewResponseForm({"earned_marks": "0"}, max_marks=Decimal("5"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["feedback"] == ""
