from decimal import Decimal

from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from courses.templatetags.courses_extras import marks_filter


def test_to_stored_fraction_exact_endpoints():
    assert to_stored_fraction(1.0) == Decimal("1.0000")
    assert to_stored_fraction(0.0) == Decimal("0.0000")


def test_to_stored_fraction_thirds_quantized_4dp():
    # 2/3 float -> 0.6666666666666666 -> 4dp half-up
    assert to_stored_fraction(2 / 3) == Decimal("0.6667")


def test_to_stored_fraction_clamps_out_of_range():
    assert to_stored_fraction(1.5) == Decimal("1.0000")
    assert to_stored_fraction(-0.2) == Decimal("0.0000")


def test_earned_marks_partial_thirds():
    # stored 0.6667 * 3 marks -> 2.0001 -> 2dp -> 2.00
    assert earned_marks(Decimal("0.6667"), Decimal("3")) == Decimal("2.00")


def test_earned_marks_full_and_zero():
    assert earned_marks(Decimal("1.0000"), Decimal("2.5")) == Decimal("2.50")
    assert earned_marks(Decimal("0.0000"), Decimal("2.5")) == Decimal("0.00")


def test_marks_filter_trims_trailing_zeros():
    assert marks_filter(Decimal("2.00")) == "2"
    assert marks_filter(Decimal("1.50")) == "1.5"
    assert marks_filter(Decimal("0.67")) == "0.67"


def test_marks_filter_whole_tens_not_scientific():
    # regression: Decimal.normalize() would give "1E+1" — must be "10"
    assert marks_filter(Decimal("10.00")) == "10"


def test_marks_filter_none_is_dash():
    assert marks_filter(None) == "—"
