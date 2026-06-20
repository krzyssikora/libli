"""Pure scoring helpers for the quiz engine (Phase 2c, spec §3.5).

MarkResult.fraction is a float upstream; it is converted to Decimal HERE and
nowhere else. Storage is deterministic and quantized — exactness is impossible
for thirds, so we quantize rather than pretend to store an exact ratio.
"""

from decimal import ROUND_HALF_UP
from decimal import Decimal

_FRACTION_Q = Decimal("0.0001")  # 4 dp — matches the fraction DecimalField
_MARKS_Q = Decimal("0.01")  # 2 dp — matches the marks DecimalFields
_ZERO = Decimal("0")
_ONE = Decimal("1")


def to_stored_fraction(raw):
    """float fraction -> Decimal, 4dp, clamped to [0, 1].

    `str()` first avoids binary-float artifacts (Decimal(str(2/3)) ==
    "0.6666666666666666", not the 55-digit Decimal(2/3)). The clamp guards the
    no-headroom field (max_digits=5) against a future buggy mark() returning >1.
    """
    f = Decimal(str(raw)).quantize(_FRACTION_Q, rounding=ROUND_HALF_UP)
    if f < _ZERO:
        return _ZERO.quantize(_FRACTION_Q)
    if f > _ONE:
        return _ONE.quantize(_FRACTION_Q)
    return f


def earned_marks(fraction, max_marks):
    """Stored 4dp fraction × max_marks, quantized to 2dp. The single source of
    truth used by BOTH the per-attempt cache and the Finish recompute."""
    return (fraction * max_marks).quantize(_MARKS_Q, rounding=ROUND_HALF_UP)
