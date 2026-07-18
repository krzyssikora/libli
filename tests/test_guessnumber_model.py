from decimal import Decimal

import pytest

from courses.models import ELEMENT_MODELS
from courses.models import GuessNumberElement


def test_guessnumber_in_element_models():
    assert "guessnumberelement" in ELEMENT_MODELS
    assert len(ELEMENT_MODELS) == 31


@pytest.mark.django_db
def test_defaults_tolerance_zero_and_blank_success_message():
    el = GuessNumberElement.objects.create(stem="x", target=Decimal("42"))
    assert el.tolerance == Decimal("0")
    assert el.success_message == ""


@pytest.mark.django_db
def test_success_message_is_sanitised_on_save_and_keeps_math_and_blocks():
    el = GuessNumberElement.objects.create(
        stem="x",
        target=Decimal("42"),
        success_message="<p>Tak, o \\(100\\%\\)</p><script>alert(1)</script>",
    )
    el.refresh_from_db()
    assert "<script>" not in el.success_message
    assert "<p>" in el.success_message  # sanitize_html keeps blocks
    assert "\\(100\\%\\)" in el.success_message  # ...and math


@pytest.mark.django_db
def test_stem_is_NOT_sanitised_on_save():
    # Sanitisation is a form-side ordered pipeline (§2.3.2); save() must not
    # re-run nh3 over an already-tokenised stem.
    raw = "<p>keep me</p>"
    el = GuessNumberElement.objects.create(stem=raw, target=Decimal("42"))
    el.refresh_from_db()
    assert el.stem == raw


def test_canonical_target_strips_trailing_zeros():
    el = GuessNumberElement(target=Decimal("42.50000000"))
    assert el.canonical_target == "42.5"


def test_canonical_target_avoids_e_notation_for_round_numbers():
    # normalize() ALONE yields '4.0401E+4' for 40401 and '1E+2' for 100 --
    # the exact defect format_target's docstring already fixed once.
    assert GuessNumberElement(target=Decimal("40401")).canonical_target == "40401"
    assert GuessNumberElement(target=Decimal("100")).canonical_target == "100"
