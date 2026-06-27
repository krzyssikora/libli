"""Per-course analytics color bands (Phase 3c-ii).

A band table is a 5-entry list of {key, label, min, color}. The matrix and
legend read it ONLY through course_color_bands(), which validates the stored
value and falls back to defaults — only the validated ColorBandsForm normally
writes the field, but raw/admin JSON edits are possible.
"""

import re

from django.utils.translation import gettext_lazy as _

# Fixed semantic order: a band's key tracks its position in ascending `min`.
BAND_KEYS = ["none", "weak", "ok", "good", "excellent"]

_LABELS = {
    "none": _("None"),
    "weak": _("Weak"),
    "ok": _("OK"),
    "good": _("Good"),
    "excellent": _("Excellent"),
}

# Defaults derived from the accepted mockup (neutral low -> green high).
_DEFAULT_MINS = [0, 40, 60, 75, 90]
_DEFAULT_COLORS = ["#e5e5e7", "#e98b5a", "#f1c453", "#52b06a", "#1e8e4a"]


def default_color_bands():
    return [
        {"key": k, "label": _LABELS[k], "min": m, "color": c}
        for k, m, c in zip(BAND_KEYS, _DEFAULT_MINS, _DEFAULT_COLORS, strict=False)
    ]


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_valid_stored(raw):
    """True iff `raw` is a usable 5-band table: exactly the 5 fixed keys, each
    with an int-coercible min and a #rrggbb color, mins strictly ascending from
    0, AND key order tracking ascending min (so an inverted edit is rejected)."""
    if not isinstance(raw, list) or len(raw) != 5:
        return False
    try:
        rows = sorted(raw, key=lambda b: int(b["min"]))
    except (KeyError, TypeError, ValueError):
        return False
    mins, keys = [], []
    for b in rows:
        if not isinstance(b, dict) or "color" not in b or "key" not in b:
            return False
        if not isinstance(b["color"], str) or not _HEX.match(b["color"]):
            return False
        mins.append(int(b["min"]))
        keys.append(b["key"])
    if mins[0] != 0 or mins != sorted(set(mins)) or len(set(mins)) != 5:
        return False
    return keys == BAND_KEYS  # key order must track ascending min


def course_color_bands(course):
    raw = course.color_bands
    if not raw or not _is_valid_stored(raw):
        return default_color_bands()
    rows = sorted(raw, key=lambda b: int(b["min"]))
    # Re-resolve label from the fixed key (stored label, if any, is ignored).
    return [
        {
            "key": b["key"],
            "label": _LABELS[b["key"]],
            "min": int(b["min"]),
            "color": b["color"],
        }
        for b in rows
    ]


def band_for(percent, bands):
    if percent is None:
        return None
    matching = [b for b in bands if int(b["min"]) <= percent]
    if matching:
        return max(matching, key=lambda b: int(b["min"]))
    # No band <= percent (impossible for course_color_bands output): lowest band.
    return min(bands, key=lambda b: int(b["min"]))


def text_on(color):
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


def band_style(percent, bands):
    band = band_for(percent, bands)
    if band is None:
        return {"bg": None, "fg": None}
    return {"bg": band["color"], "fg": text_on(band["color"])}


def legend_rows(bands):
    rows = []
    for i, b in enumerate(bands):
        hi = 100 if i == len(bands) - 1 else int(bands[i + 1]["min"]) - 1
        rows.append(
            {"label": b["label"], "color": b["color"], "lo": int(b["min"]), "hi": hi}
        )
    return rows
