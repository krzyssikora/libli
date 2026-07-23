"""Pure-Python numeric-token detector matching courses.marking.parse_number rules."""

import re

_NUM_RE = re.compile(r"^[+-]?\d+([.,]\d+)?$")


def normalize_numeric(token):
    """Canonical decimal string if `token` is a single number, else None."""
    token = (token or "").strip()
    if not _NUM_RE.match(token):
        return None
    return token.replace(",", ".")
