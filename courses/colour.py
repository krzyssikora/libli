"""The one canonical definition of the author-selectable text palette.

Colour reaches this module in three vocabularies — a hex literal from the token
file, an `rgb(...)` serialisation read back out of the DOM, and a CSS keyword from
imported markup — so everything is keyed on a canonical (r, g, b) triple. A map
keyed on source-form literals would match nothing on the JS paths, because browsers
always serialise `el.style.color` as `rgb(...)`.

Mirrored in courses/static/courses/js/text_colour.js; tests/test_colour_map_drift.py
holds the two copies together.
"""

import re

TC_CLASS_VALUES = {"tc-red", "tc-blue", "tc-green", "tc-orange"}

# Tags allowed to carry a tc-* class. span is the normal carrier; the inline
# emphasis tags are here because execCommand("foreColor") may colour an existing
# wrapper instead of creating a span, and `a` because a selection covering a link's
# text commonly styles the <a> itself -- without it the colour would be stripped on
# save with no feedback.
TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}

# Applied by the Clear control, then dropped. Must be a colour the browser accepts
# (inherit/unset are rejected or inconsistent across engines), must not collide with
# any mapped triple, and must be one no author would plausibly type.
SENTINEL_RGB = (1, 2, 3)

_PALETTE = {
    "red": ("#B2372A", "#EA8A82", "red"),
    "blue": ("#1F61AD", "#8FBCE8", "blue"),
    "green": ("#3F6B24", "#9FBF7B", "green"),
    "orange": ("#8A5514", "#E8B761", "orange"),
}

_KEYWORDS = {
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "green": (0, 128, 0),
    "orange": (255, 165, 0),
}

_HEX = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6})$")
_RGB = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,[^)]*)?\)$")


def normalise_colour(value):
    """Any accepted colour form -> an (r, g, b) triple, or None."""
    if not value:
        return None
    text = str(value).strip().lower()
    if text in _KEYWORDS:
        return _KEYWORDS[text]
    if _HEX.match(text):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
    match = _RGB.match(text)
    if match:
        channels = tuple(int(g) for g in match.groups())
        return channels if all(c <= 255 for c in channels) else None
    return None


def _build_slots():
    slots = {}
    for slot, values in _PALETTE.items():
        for value in values:
            triple = normalise_colour(value)
            assert triple is not None, f"unparseable palette value {value!r}"
            slots[triple] = slot
    return slots


SLOTS = _build_slots()


def parse_style_colour(style):
    """The `color` declaration's value from a style attribute, canonicalised.

    Property matching is EXACT, never a suffix: an unanchored `color:` search also
    matches `background-color:` and `border-color:`, which would invent a text
    colour the author never set. The LAL corpus contains both.
    """
    if not style:
        return None
    for declaration in str(style).split(";"):
        name, sep, value = declaration.partition(":")
        if not sep:
            continue
        if name.strip().lower() != "color":
            continue
        return normalise_colour(value)
    return None


def slot_for_style(style):
    """The palette slot named by a style attribute's `color` declaration, or None.

    None means "no slot", never "delete". The caller decides what an unmapped
    colour means, and the two callers decide differently: the backfill drops it
    (it cannot be stored anyway), while the render path leaves it exactly as-is
    so existing \\color{purple} content keeps rendering as it does today.
    """
    return SLOTS.get(parse_style_colour(style))
