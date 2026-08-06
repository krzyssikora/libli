"""Shared answer-marking primitives: MarkResult plus text and number normalization."""

import re
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation
from fractions import Fraction

_WS_RE = re.compile(r"\s+")
# Optional sign; then either int part with optional [.,]frac, OR a leading-bare
# decimal (.5 / ,5). No thousands separators, no internal whitespace.
_NUM_RE = re.compile(r"^[+-]?(\d+([.,]\d+)?|[.,]\d+)$")
# Signed integer numerator over an unsigned integer denominator. No decimals on
# either side; the sign belongs in front, never on the denominator.
_FRAC_RE = re.compile(r"^([+-]?\d+)\s*/\s*(\d+)$")
# Mixed number: whole part, then a REQUIRED whitespace run, then a proper-or-not
# fraction. The \s+ is load-bearing — with \s* this would swallow '11/2' and read
# eleven halves as one-and-a-half. One sign only, in front, applying to the whole
# quantity: '-1 1/2' is -(1 + 1/2), so the parts are summed then negated.
_MIXED_RE = re.compile(r"^([+-]?)(\d+)\s+(\d+)\s*/\s*(\d+)$")


@dataclass(frozen=True)
class MarkResult:
    """The normalized result every question type's mark() returns.

    `reveal` is a per-type, type-opaque presentation payload consumed by the
    feedback template. For ChoiceQuestionElement it is a frozenset[int] of the
    correct choice ids. `annotated` is a second per-type presentation payload: for
    ChoiceQuestionElement, the frozenset[int] of choice ids whose per-choice
    feedback should be shown — the symmetric difference between the student's
    selection and the correct set (a selected distractor OR a missed correct
    option), restricted to options carrying feedback; empty for every other type.
    """

    correct: bool
    fraction: float
    reveal: frozenset = frozenset()
    annotated: frozenset = frozenset()


def normalize_text(s, *, case_sensitive=False):
    """Trim, collapse internal whitespace runs to one space, and (unless
    case_sensitive) casefold. The shared text-match primitive for short-text and
    fill-blank marking."""
    s = _WS_RE.sub(" ", (s or "").strip())
    return s if case_sensitive else s.casefold()


def parse_number(s):
    """Parse a single number to Decimal, or None if malformed. Accepts a single
    '.' OR ',' decimal separator (',' normalized to '.'); rejects thousands
    separators and any internal whitespace. See the spec §2.1 boundary table."""
    s = (s or "").strip()
    if not _NUM_RE.match(s):
        return None
    try:
        return Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None


def parse_numeric_value(s):
    """Parse to an exact Fraction — a decimal (parse_number's grammar), a simple
    'a/b' fraction, or a mixed number 'w a/b' — or None if malformed. The
    COMPARISON-side parser.

    Deliberately separate from parse_number, which returns a Decimal and feeds the
    persistence path (ShortNumericQuestionElement.value/tolerance, GuessNumber's
    target — all DecimalField(max_digits=20, decimal_places=8)). 1/3 has no exact
    Decimal form, so admitting fractions there would silently store a rounded,
    different number and break the editor round-trip. Comparison has no such
    constraint: Fraction is exact, so 2/4 == 1/2 == 0,5 while 0.333 != 1/3.

    Spaces around the slash are allowed. parse_number bans internal whitespace to
    kill thousands-separator ambiguity ('1 234'), which a slash cannot create."""
    s = (s or "").strip()
    m = _MIXED_RE.match(s)
    if m:
        sign, whole, numerator, denominator = m.groups()
        if int(denominator) == 0:
            return None
        value = int(whole) + Fraction(int(numerator), int(denominator))
        return -value if sign == "-" else value
    m = _FRAC_RE.match(s)
    if m:
        denominator = int(m.group(2))
        if denominator == 0:
            return None
        return Fraction(int(m.group(1)), denominator)
    dec = parse_number(s)
    return None if dec is None else Fraction(dec)


def blank_matches(got_raw, accepted_lines, *, case_sensitive=False):
    """True if got_raw matches any accepted line, by normalized text OR — when both
    the input and that accepted line parse as numbers — by numeric value equality.

    The numeric branch fires only when *both* sides parse (parse_numeric_value
    accepts a '.' or ',' decimal separator, an 'a/b' fraction, or a mixed 'w a/b'),
    so a number never cross-matches a text answer that merely starts with digits or
    contains a slash ('and/or'), and text blanks are unaffected. Equality is by exact
    rational value, so trailing zeros and a leading sign are irrelevant
    (3,14 == 3.14 == 3.140) and every spelling of a value meets every other
    (1/2 == 2/4 == 0,5; 1 1/2 == 3/2 == 1.5)."""
    got_text = normalize_text(got_raw, case_sensitive=case_sensitive)
    if got_text == "":
        return False
    got_num = parse_numeric_value(got_raw)
    for line in accepted_lines:
        if normalize_text(line, case_sensitive=case_sensitive) == got_text:
            return True
        if got_num is not None:
            acc_num = parse_numeric_value(line)
            if acc_num is not None and acc_num == got_num:
                return True
    return False
