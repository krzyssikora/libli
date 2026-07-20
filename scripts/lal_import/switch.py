"""Convert a LAL `.switch_line` into a token stem + cyclers.

A switch_line interleaves static operands (bare text, `.switch_around`) with one
or more runs of clickable `.switch_value` options. Each contiguous run of
switch_values becomes ONE cycler, marked in the stem by the fillblank sentinel
token `SENTINEL + i + SENTINEL` (matches courses.switchgrid / courses.switchgate).
The trailing `.switch_confirm` / `.switch_show_next` button is not content.
"""

import re

from bs4 import NavigableString
from bs4 import Tag

from scripts.lal_import.mathsafe import escape_math_delimited

SENTINEL = "￿"  # == courses.fillblank.SENTINEL (U+FFFF)
_BUTTON_CLASSES = {"switch_confirm", "switch_show_next"}
_LEAD_PROMPT_RE = re.compile(r"wybierz", re.IGNORECASE)


def strip_lead_prompt(options, answer):
    """LAL cyclers carry a leading '>> wybierz >>' prompt as option 0; the libli
    cycler supplies its own initial prompt, so drop it and shift the 0-based
    answer index down to match. No-op when the first option is a real choice."""
    if options and _LEAD_PROMPT_RE.search(options[0]):
        return options[1:], max(0, answer - 1)
    return options, answer


def _token(i):
    return SENTINEL + str(i) + SENTINEL


def switch_line_stem_cyclers(line):
    """Return (token_stem, cyclers) for a `.switch_line`. cyclers is a list of
    {"options": [html, ...]} in document order; the stem carries one sentinel
    token per cycler at its position."""
    parts, cyclers = [], []
    pending = []  # a run of consecutive switch_value options

    def flush_cycler():
        if pending:
            parts.append(_token(len(cyclers)))
            cyclers.append({"options": list(pending)})
            pending.clear()

    for c in line.children:
        if isinstance(c, NavigableString):
            # bare static text: NavigableString is decoded, so re-escape math.
            text = escape_math_delimited(str(c))
            if text.strip():
                flush_cycler()
            parts.append(text)
            continue
        if not isinstance(c, Tag):
            continue
        classes = c.get("class") or []
        if "switch_value" in classes:
            # sanitized field -> keep &lt;/&gt; entities; strip source indentation.
            pending.append(c.decode_contents().strip())
            continue
        if any(b in classes for b in _BUTTON_CLASSES):
            continue  # the confirm/reveal button is not part of the stem
        # static operand (.switch_around or any other inline wrapper)
        flush_cycler()
        parts.append(c.decode_contents())
    flush_cycler()
    return "".join(parts), cyclers
