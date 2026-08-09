"""Shared answer-marking primitives: MarkResult plus text and number normalization."""

import re
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation
from decimal import localcontext
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


# The storage cap for ShortNumericQuestionElement.value/tolerance. MUST equal those
# fields' max_length — that equality is what makes an oversized transfer payload
# produce a clean TransferError instead of a ValidationError deep in _clean_save.
MAX_STORED_NUMERIC_CHARS = 64
# The comparison-side cap, used only by parse_numeric_value. Deliberately NOT the
# same constant: parse_numeric_value is blank_matches' parser, so a 64-char cap here
# would silently stop 65-4300 character numbers matching in fill-blank, fill-in-table
# and fill-&-confirm. 256 stays far below the 4300-digit int() limit while changing
# no plausible existing content.
MAX_PARSED_NUMERIC_CHARS = 256

# Returned by canonical_numeric_text/canonical_tolerance_text when the input parses
# but its canonical form will not fit the column, so the form can say "too long"
# rather than "enter a number or fraction". Compared by identity. NEVER stored or
# rendered: a sentinel reaching a CharField is stringified into "<object object ...>".
# Note TOO_LONG is not None, so `if x is not None` is never a sufficient guard.
TOO_LONG = object()


def format_decimal_plain(d):
    """Format a Decimal as plain notation with trailing zeros stripped.

    Takes a Decimal (or anything Decimal() accepts) — NEVER raw author text:
    Decimal("1,5") raises InvalidOperation, so the comma must already be gone.

    Two load-bearing details:
    - "f" forces fixed-point. Decimal("40401").normalize() is Decimal("4.0401E+4"),
      whose plain str() the parsers reject, making the element uneditable.
    - localcontext raises the precision. normalize() applies the CURRENT context,
      whose default precision is 28, so a 29+ significant-digit value would be
      silently rounded — reachable now that the column is a 64-char CharField.
      The +16 is headroom if the storage cap is ever raised.
    """
    with localcontext() as ctx:
        ctx.prec = MAX_STORED_NUMERIC_CHARS + 16
        return format(Decimal(d).normalize(), "f")


def _coerce_numeric_input(s):
    """Coerce arbitrary input to text the grammars can match.

    A bare str() is wrong for every numeric type. str(Decimal("0.00000000")) is
    '0E-8'; Python switches floats to exponent form below 1e-4 and above 1e16, so
    str(0.00001) is '1e-05'. _NUM_RE has no exponent branch, so all of those would
    parse as None. Reachable two ways: every Decimal read from the old numeric(20,8)
    column below 1e-6, and JSON numbers in a LAL manifest.
    """
    if s is None:
        return ""
    if isinstance(s, Decimal):
        return format(s, "f")
    # bool must be excluded explicitly: isinstance(True, int) is True and
    # Decimal("True") raises InvalidOperation. A JSON `true` falls through to
    # str() -> "True" -> no grammar matches -> None, which is what callers expect.
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        # Decimal(str(f)), never Decimal(f): Decimal(0.1) is 55 digits of binary
        # noise, which would blow the storage cap and change the stored value.
        return format(Decimal(str(s)), "f")
    return str(s)


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
    kill thousands-separator ambiguity ('1 234'), which a slash cannot create.

    parse_number deliberately does NOT get the same length guard: it goes through
    Decimal, which has no digit limit, and guarding it would regress
    views.py:1162 and element_forms.py:314/338."""
    s = _coerce_numeric_input(s).strip()
    if len(s) > MAX_PARSED_NUMERIC_CHARS:
        # Guard BEFORE any regex: the branches below call int() on captured digit
        # runs, and int() raises ValueError above 4300 digits (CPython >=3.11).
        # blank_matches feeds this student input, so an unguarded call is a live 500.
        return None
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


def canonical_numeric_text(s):
    """Canonical storage text for a number or fraction; None if it does not parse;
    TOO_LONG if it parses but its canonical form will not fit the column.

    Tries the three grammars in the SAME ORDER as parse_numeric_value (mixed,
    fraction, decimal). Sharing the regexes is not enough to prevent drift — the
    order is, because the load-bearing \\s+ in _MIXED_RE interacts with greediness.

    Structural form is preserved (mixed stays mixed, fraction stays fraction) and
    fractions are NOT reduced: an author who writes 6/4 reopens the editor and sees
    6/4. Reduction happens only at comparison time, inside Fraction.
    """
    s = _coerce_numeric_input(s).strip()
    if len(s) > MAX_STORED_NUMERIC_CHARS:
        return None

    result = None
    m = _MIXED_RE.match(s)
    if m:
        sign, whole, numerator, denominator = m.groups()
        if int(denominator) == 0:
            return None
        # _MIXED_RE carries the sign in its OWN group and leaves the whole part
        # unsigned, unlike _FRAC_RE where the sign lives inside the numerator.
        # Dropping this re-prepend silently stores "1 1/2" for "-1 1/2".
        value = int(whole) + Fraction(int(numerator), int(denominator))
        if sign == "-":
            value = -value
        if value == 0:
            return "0"
        prefix = "-" if sign == "-" else ""
        result = f"{prefix}{int(whole)} {int(numerator)}/{int(denominator)}"
    else:
        m = _FRAC_RE.match(s)
        if m:
            numerator, denominator = int(m.group(1)), int(m.group(2))
            if denominator == 0:
                return None
            if numerator == 0:
                return "0"
            result = f"{numerator}/{denominator}"
        else:
            dec = parse_number(s)
            if dec is None:
                return None
            if dec == 0:
                # Covers "0", "00", "-0", "-0.0" — never store "-0".
                return "0"
            result = format_decimal_plain(dec)

    # Canonicalisation is NOT length-preserving: "." + 63 digits is a legal 64-char
    # input whose canonical form is "0.111..." at 65. Without this re-check that
    # input dies in _post_clean's full_clean with a max-length error the author
    # cannot act on, or reaches _clean_save's unwrapped full_clean as a 500.
    if len(result) > MAX_STORED_NUMERIC_CHARS:
        return TOO_LONG
    return result


def canonical_tolerance_text(s):
    """Canonical storage text for a tolerance.

    Zero has exactly ONE encoding: the empty string. Blank input and every spelling
    of zero both map to "". Without this, an author typing 0 would store the truthy
    string "0" and the reveal would start printing "+/- 0" where a zero tolerance is
    hidden today. This helper is the single place that decision is made.

    Returns "" for blank-or-zero, the canonical text for a positive value, TOO_LONG
    propagated from canonical_numeric_text, and None for unparseable OR negative.
    """
    text = _coerce_numeric_input(s).strip()
    if text == "":
        return ""
    canonical = canonical_numeric_text(text)
    if canonical is None or canonical is TOO_LONG:
        return canonical
    if canonical == "0":
        return ""
    if parse_numeric_value(canonical) < 0:
        return None
    return canonical


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
