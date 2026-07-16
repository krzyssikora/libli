"""Single-token stem helper for the Guess-the-number element.

The stem carries exactly one placeholder marking where the numeric input renders.
Authors type ``{{42}}``; it is stored as the U+FFFF 0 U+FFFF sentinel token
(reusing courses.fillblank.SENTINEL) and the target is lifted out into its own field.
Unlike switchgate's fixed {{choice}} marker, this token carries a payload; unlike
fillblank, it never splits on '|' into alternatives. See the design doc §2.3.
"""

import re
from decimal import Decimal

from courses import fillblank
from courses.switchgate import render_stem  # noqa: F401 — re-exported; see below

SENTINEL_TOKEN = fillblank.SENTINEL + "0" + fillblank.SENTINEL
_MARKER_RE = re.compile(r"\{\{(.*?)\}\}")


class GuessNumberError(ValueError):
    """Carries a `code` so clean_stem maps each check to its own message (§2.3.3).

    ValueError accepts no keyword arguments, so the code is positional:
    GuessNumberError(code="x") would TypeError."""

    def __init__(self, code, *args):
        self.code = code
        super().__init__(code, *args)


def parse_stem(clean):
    """-> (token_stem, raw_target_str). Math is masked before token scanning.

    Owns checks 1-2 of §2.3.3, each with its own code:
      - not exactly one {{...}} token -> GuessNumberError("token_count")
      - a literal '|' inside the token -> GuessNumberError("alternatives")
    Checks 3-4 (numeric parse, digit bounds) belong to clean_stem, not here.
    """
    masked, spans = fillblank.mask_math(clean or "")
    found = _MARKER_RE.findall(masked)
    if len(found) != 1:
        raise GuessNumberError("token_count")
    if "|" in found[0]:
        raise GuessNumberError("alternatives")
    token_stem = fillblank.restore_math(_MARKER_RE.sub(SENTINEL_TOKEN, masked), spans)
    # NOTE: unlike fillblank.parse, a dangling "{{" left after substitution is
    # NOT an error here — it stays literal stem prose. fillblank raises
    # "unterminated marker" because a lost blank silently drops a question; this
    # element has exactly one token, and if it were the dangling one, check 1
    # already fired. Deliberate, not an oversight.
    return token_stem, found[0].strip()


def format_target(target):
    """Canonical author-facing text for a stored Decimal (§2.6).

    normalize() alone yields Decimal('4.0401E+4') for 40401, which parse_number
    then REJECTS — making the element uneditable. format(..., "f") strips the
    exponent, so 40401.00000000 -> "40401" and 40401.50000000 -> "40401.5".
    """
    return format(Decimal(target).normalize(), "f")


def to_author_stem(token_stem, target):
    """Inverse of parse_stem, for populating the edit form."""
    return (token_stem or "").replace(
        SENTINEL_TOKEN, "{{" + format_target(target) + "}}"
    )
