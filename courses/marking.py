"""Shared answer-marking primitives: MarkResult plus text and number normalization."""

import re
from dataclasses import dataclass
from decimal import Decimal
from decimal import InvalidOperation

_WS_RE = re.compile(r"\s+")
# Optional sign; then either int part with optional [.,]frac, OR a leading-bare
# decimal (.5 / ,5). No thousands separators, no internal whitespace.
_NUM_RE = re.compile(r"^[+-]?(\d+([.,]\d+)?|[.,]\d+)$")


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


def blank_matches(got_raw, accepted_lines, *, case_sensitive=False):
    """True if got_raw matches any accepted line, by normalized text OR — when both
    the input and that accepted line parse as numbers — by numeric value equality.

    The numeric branch fires only when *both* sides parse (parse_number accepts a
    '.' or ',' decimal separator), so a number never cross-matches a text answer
    that merely starts with digits, and text blanks are unaffected. Value equality
    means trailing zeros and a leading sign are irrelevant (3,14 == 3.14 == 3.140)."""
    got_text = normalize_text(got_raw, case_sensitive=case_sensitive)
    if got_text == "":
        return False
    got_num = parse_number(got_raw)
    for line in accepted_lines:
        if normalize_text(line, case_sensitive=case_sensitive) == got_text:
            return True
        if got_num is not None:
            acc_num = parse_number(line)
            if acc_num is not None and acc_num == got_num:
                return True
    return False
