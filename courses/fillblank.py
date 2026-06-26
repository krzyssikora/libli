"""Fill-blank stem parsing and render-time token substitution.

Author flow (in the form): sanitize_html(raw) -> strip_sentinel -> parse(). parse()
masks balanced KaTeX spans, extracts {{a|b}} markers into ordered Blank answer
lists, and replaces each marker with an opaque token `\\uffff{n}\\uffff`. The
sentinel U+FFFF is stripped from author input first (strip_sentinel), so a stored
token can never be forged from prose. Render flow (in the tag): render_inputs()
splits the token-stem and safe-joins server-built <input>s — the only unescaped
insertions.
"""

import re

from django.utils.html import format_html
from django.utils.safestring import mark_safe

SENTINEL = "￿"
_TOKEN = SENTINEL + "{}" + SENTINEL
_TOKEN_RE = re.compile(SENTINEL + r"(\d+)" + SENTINEL)
# Parse-time, never-persisted math placeholder. 'M' prefix keeps it disjoint from
# the digits-only blank token regex, so the two never cross-match.
_MATH_PLACEHOLDER = SENTINEL + "M{}" + SENTINEL
_MATH_PLACEHOLDER_RE = re.compile(SENTINEL + r"M(\d+)" + SENTINEL)
# Balanced KaTeX spans, non-greedy, may span lines (display math).
_MATH_RE = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)
# Marker: non-greedy, allows empty interior (so {{}} is matched then rejected);
# NOT DOTALL → a marker may not span lines (single-line invariant).
_MARKER_RE = re.compile(r"\{\{(.*?)\}\}")


class FillBlankError(ValueError):
    """Raised on a malformed/empty/unterminated marker or a stem with no blanks."""


def strip_sentinel(s):
    return (s or "").replace(SENTINEL, "")


def _mask_math(s):
    spans = []

    def _grab(m):
        spans.append(m.group(0))
        return _MATH_PLACEHOLDER.format(len(spans) - 1)

    return _MATH_RE.sub(_grab, s), spans


def _restore_math(s, spans):
    return _MATH_PLACEHOLDER_RE.sub(lambda m: spans[int(m.group(1))], s)


def parse(clean_stem):
    """clean_stem: sanitized author stem with the sentinel already stripped.
    Returns (token_stem, blanks). Raises FillBlankError on a bad stem."""
    masked, spans = _mask_math(clean_stem)
    blanks = []

    def _swap(m):
        pieces = [p.strip() for p in m.group(1).split("|")]
        pieces = [p for p in pieces if p]
        if not pieces:
            raise FillBlankError("empty marker")
        blanks.append(pieces)
        return _TOKEN.format(len(blanks) - 1)

    token_masked = _MARKER_RE.sub(_swap, masked)
    if "{{" in token_masked:
        raise FillBlankError("unterminated marker")
    if not blanks:
        raise FillBlankError("no blanks")
    return _restore_math(token_masked, spans), blanks


def to_author_stem(token_stem, blanks):
    """Inverse of parse() for the editor: turn a stored token-stem back into the
    author's `{{answer}}` markup so a teacher edits what they originally typed, not
    the opaque ￿n￿ tokens. `blanks` is the parse() answer-list (list[list[str]]);
    token ￿n￿ becomes `{{` + the n-th blank's alternatives joined by `|` + `}}`.
    Text and KaTeX segments are already literal in token_stem, so only tokens move."""

    def _swap(m):
        n = int(m.group(1))
        pieces = blanks[n] if 0 <= n < len(blanks) else []
        return "{{" + "|".join(pieces) + "}}"

    return _TOKEN_RE.sub(_swap, token_stem or "")


def render_inputs(token_stem, submitted_values=None):
    """Split a stored token-stem and safe-join server-built <input>s. The text
    segments are already-sanitized HTML (trusted); only the <input>s are inserted,
    with the repopulation value HTML-escaped."""
    vals = list(submitted_values or [])
    parts = _TOKEN_RE.split(token_stem or "")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)  # trusted sanitized HTML
        else:
            n = int(part)
            v = vals[n] if 0 <= n < len(vals) else ""
            out.append(
                str(
                    format_html(
                        '<input type="text" name="blank" value="{}" '
                        'class="question__blank-input" autocomplete="off">',
                        v,
                    )
                )
            )
    return mark_safe("".join(out))  # noqa: S308 — segments sanitized; inputs escaped
