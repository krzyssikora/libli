"""Multi-token stem helper for the Switch grid element (SwitchGridElement).

Generalizes courses.switchgate (which allows exactly one {{choice}}) to N markers
per line, indexed like courses.fillblank.parse (running count -> token index).
Authors type the literal {{choice}}; each occurrence i is stored as the
fillblank.SENTINEL + str(i) + SENTINEL token, and split back out at render time.
"""

import re

from django.utils.safestring import SafeString
from django.utils.safestring import mark_safe

from courses import fillblank

CHOICE_MARKER = "{{choice}}"
_TOKEN_RE = re.compile(fillblank.SENTINEL + r"(\d+)" + fillblank.SENTINEL)


class SwitchGridError(ValueError):
    """Raised for malformed switch-grid stems (reserved; parse is lenient on count)."""


def _token(i: int) -> str:
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def parse_stem_multi(clean: str) -> tuple[str, int]:
    """Replace the i-th {{choice}} with the i-th sentinel token.

    Returns (token_stem, marker_count)."""
    count = 0

    def _swap(_m):
        nonlocal count
        tok = _token(count)
        count += 1
        return tok

    token_stem = re.sub(re.escape(CHOICE_MARKER), _swap, clean or "")
    return token_stem, count


def to_author_stem_multi(token_stem: str) -> str:
    """Inverse of parse_stem_multi: every sentinel token -> {{choice}}."""
    return _TOKEN_RE.sub(CHOICE_MARKER, token_stem or "")


def count_markers(token_stem: str) -> int:
    """Public: number of sentinel cycler tokens in a stored token stem."""
    return len(_TOKEN_RE.findall(token_stem or ""))


def sanitize_stem_segments(token_stem: str) -> str:
    """Sanitize each non-token segment (sanitize_cell) while preserving the tokens.

    Used by the import builder, which bypasses the form's clean()-time sanitize."""
    from courses.sanitize import sanitize_cell

    parts = _TOKEN_RE.split(token_stem or "")
    # split with one capture group -> [seg, idx, seg, idx, ..., seg]; odd items are
    # the captured index digits, which must be rebuilt back into their sentinel token.
    out = []
    for pos, part in enumerate(parts):
        out.append(_token(int(part)) if pos % 2 else sanitize_cell(part))
    return "".join(out)


def render_stem_multi(
    token_stem: str, widgets_by_index: dict[int, SafeString]
) -> SafeString:
    """Split the token-stem and splice widgets_by_index[i] at each token i.

    Non-token segments are marked safe (sanitized at clean()/import time). A token
    whose index is absent from widgets_by_index renders as empty (safe-degrade)."""
    parts = _TOKEN_RE.split(token_stem or "")
    # re.split with one capture group yields: [seg, idx, seg, idx, ..., seg]
    out = []
    for pos, part in enumerate(parts):
        if pos % 2 == 0:
            out.append(mark_safe(part))  # noqa: S308 — stem segment sanitized upstream
        else:
            out.append(widgets_by_index.get(int(part), mark_safe("")))
    return mark_safe("".join(out))  # noqa: S308 — segments already sanitized/marked above
