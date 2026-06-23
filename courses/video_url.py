"""Canonicalize a pasted YouTube/Vimeo link into a working embed URL.

The single parser for video-element URLs. Recognized hosts are rebuilt from
scratch (host + path + only the start/hash we keep), dropping all tracking
cruft; unrecognized hosts pass through unchanged for the allow-list to judge.
"""

import re

_BARE_SECONDS = re.compile(r"^\d+$")
# At least one of h/m/s, in that fixed order, each component a run of digits.
_HMS = re.compile(r"^(?=\d+[hms])(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def _parse_duration(value):
    """Return total seconds for a start value, or 0 if absent/unparseable/zero."""
    value = (value or "").strip()
    if _BARE_SECONDS.match(value):
        return int(value)
    m = _HMS.match(value)
    if not m:
        return 0
    h, mm, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mm * 60 + s
