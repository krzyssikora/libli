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
    correct choice ids.
    """

    correct: bool
    fraction: float
    reveal: frozenset = frozenset()


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
