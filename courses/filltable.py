"""Shared helpers for the Fill-in table self-check element. Used by BOTH the
form's answer validation and the check view, so authoring and checking agree on
what counts as an alternative and what counts as blank."""

import html as _html
import re

import nh3

from courses.fillblank import _MARKER_RE
from courses.fillblank import _TOKEN_RE
from courses.fillblank import SENTINEL
from courses.fillblank import FillBlankError
from courses.fillblank import mask_math
from courses.fillblank import restore_math
from courses.fillblank import strip_sentinel

# Inline answer boxes typed as {{answer}} inside a static cell's text (spec
# 2026-09-24-filltable-inline-gaps §2/§4). The LAL corpus peaks at 2 per cell.
MAX_GAPS_PER_CELL = 10

_TOKEN = SENTINEL + "{}" + SENTINEL
# fillblank.mask_math's placeholder: SENTINEL + "M<n>" + SENTINEL.
_MATH_PLACEHOLDER_RE = re.compile(SENTINEL + r"M\d+" + SENTINEL)


class GapMathError(FillBlankError):
    """A {{…}} marker whose interior holds a maths span. Its own class so the form
    picks the maths message by type, never by the exception's text."""


def is_static_cell(cell):
    return isinstance(cell, dict) and cell.get("kind") not in ("answer", "image")


def _marker_text(interior):
    # A real parser, never a <[^>]*> regex: nh3 leaves `>` unescaped inside
    # attribute values, so a regex would leak `b">` out of <span title="a>b">.
    return _html.unescape(nh3.clean(interior, tags=set()))


def parse_cell_gaps(cell_html):
    """Sanitised static-cell html -> (token_html, gaps). Each {{a|b}} marker outside
    \\(…\\)/\\[…\\] becomes a U+FFFF token; its alternatives (tags stripped, entities
    decoded, trimmed, blanks dropped) go into `gaps`. Zero markers is fine.

    Raises GapMathError for maths inside a marker, FillBlankError for an empty or
    unterminated one."""
    s = strip_sentinel(cell_html if isinstance(cell_html, str) else "")
    masked, spans = mask_math(s)
    gaps = []

    def _swap(m):
        interior = m.group(1)
        if _MATH_PLACEHOLDER_RE.search(interior):
            raise GapMathError("math in marker")
        pieces = [p.strip() for p in _marker_text(interior).split("|")]
        pieces = [p for p in pieces if p]
        if not pieces:
            raise FillBlankError("empty marker")
        gaps.append(pieces)
        return _TOKEN.format(len(gaps) - 1)

    token_masked = _MARKER_RE.sub(_swap, masked)
    if "{{" in token_masked:
        raise FillBlankError("unterminated marker")
    return restore_math(token_masked, spans), gaps


def author_cell_html(cell):
    """The editor's view of a static cell: tokens back to {{alt|alt}}, alternatives
    html-escaped (mirrors fillblank.to_author_stem). Identity without `gaps`."""
    h = cell.get("html") or ""
    gaps = cell.get("gaps")
    if not gaps:
        return h

    def _swap(m):
        n = int(m.group(1))
        pieces = gaps[n] if 0 <= n < len(gaps) else []
        return "{{" + "|".join(_html.escape(p, quote=False) for p in pieces) + "}}"

    return _TOKEN_RE.sub(_swap, h)


def _clean_entry(entry):
    if not isinstance(entry, list):
        return []
    return [a.strip() for a in entry if isinstance(a, str) and a.strip()]


def reconcile_gaps(cell_html, gaps):
    """Read-side repair so tokens and `gaps` always agree (spec §4). Never raises;
    idempotent; returns [] for gaps when no box survives."""
    h = cell_html if isinstance(cell_html, str) else ""
    entries = [_clean_entry(e) for e in gaps] if isinstance(gaps, list) else []
    seen = set()
    kept = []

    def _swap(m):
        n = int(m.group(1))
        if (
            n in seen
            or n >= len(entries)
            or not entries[n]
            or len(kept) >= MAX_GAPS_PER_CELL
        ):
            return ""
        seen.add(n)
        kept.append(entries[n])
        return _TOKEN.format(len(kept) - 1)

    return _TOKEN_RE.sub(_swap, h), kept


def gap_cells(cells):
    """Yield (row, col, gap_index, alternatives) for every inline gap, 0-based."""
    for r, row in enumerate(cells or []):
        if not isinstance(row, list):
            continue
        for c, cell in enumerate(row):
            if not is_static_cell(cell):
                continue
            for g, alts in enumerate(cell.get("gaps") or []):
                yield r, c, g, alts


def split_alternatives(answer):
    """Split a stored answer string on '|' into trimmed, non-empty alternatives."""
    if not isinstance(answer, str):
        return []
    return [part.strip() for part in answer.split("|") if part.strip()]


def is_blank_answer(answer):
    """True iff the answer yields zero non-empty alternatives (blank or pipe-only)."""
    return not split_alternatives(answer)


def answer_cells(cells):
    """Yield (row_index, col_index, answer_string) for every answer cell, 0-based."""
    for r, row in enumerate(cells or []):
        if not isinstance(row, list):
            continue
        for c, cell in enumerate(row):
            if isinstance(cell, dict) and cell.get("kind") == "answer":
                yield r, c, cell.get("answer", "")


def cell_parts(cell, r, c, *, done):
    """A static cell's html with each token replaced by its inline <input>, as ONE
    safe string. Text segments are trusted (sanitised at save); every input is
    built with format_html, the ONLY escaping they get (spec §5). In the done state
    each box shows its gaps_display value, readonly, sized to fit -- `readonly` (not
    `disabled`) is what the CSS width release keys on."""
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe
    from django.utils.translation import gettext as _

    n_gaps = len(cell.get("gaps") or [])
    display = cell.get("gaps_display") or []
    out = []
    for i, part in enumerate(_TOKEN_RE.split(cell.get("html") or "")):
        if i % 2 == 0:
            out.append(part)
            continue
        g = int(part)
        if n_gaps == 1:
            # Reuses the answer-cell template's msgid exactly.
            label = _("Answer, row %(r)s, column %(c)s") % {"r": r + 1, "c": c + 1}
        else:
            label = _("Answer, row %(r)s, column %(c)s, box %(g)s") % {
                "r": r + 1,
                "c": c + 1,
                "g": g + 1,
            }
        if done:
            v = display[g] if 0 <= g < len(display) else ""
            out.append(
                format_html(
                    '<input type="text" class="filltable__input '
                    'filltable__input--inline filltable__input--correct" '
                    'data-r="{}" data-c="{}" data-g="{}" value="{}" size="{}" '
                    'readonly aria-label="{}">',
                    r,
                    c,
                    g,
                    v,
                    max(len(v), 2),
                    label,
                )
            )
        else:
            out.append(
                format_html(
                    '<input type="text" class="filltable__input '
                    'filltable__input--inline" data-r="{}" data-c="{}" '
                    'data-g="{}" aria-label="{}">',
                    r,
                    c,
                    g,
                    label,
                )
            )
    return mark_safe("".join(str(p) for p in out))  # noqa: S308 — see docstring
