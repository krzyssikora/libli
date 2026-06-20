from decimal import Decimal

from courses.scoring import earned_marks, to_stored_fraction


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
