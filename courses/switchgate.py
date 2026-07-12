"""Single-token stem helper for the Choose & confirm gate (SwitchGateElement).

The stem carries exactly one placeholder marking where the inline cycler renders.
Authors type the literal ``{{choice}}``; it is stored as the ￿0￿ sentinel token
(reusing courses.fillblank.SENTINEL), and split back out at render time. Unlike
fillblank, the token carries no answer data — the options live in a separate field.
"""

from django.utils.safestring import SafeString
from django.utils.safestring import mark_safe

from courses import fillblank

SENTINEL_TOKEN = fillblank.SENTINEL + "0" + fillblank.SENTINEL
CHOICE_MARKER = "{{choice}}"


class SwitchGateError(ValueError):
    """Raised when the stem does not contain exactly one {{choice}} marker."""


def parse_stem(clean: str) -> str:
    """Return the token-stem: exactly one {{choice}} replaced by SENTINEL_TOKEN."""
    count = clean.count(CHOICE_MARKER)
    if count != 1:
        raise SwitchGateError(f"expected exactly one {CHOICE_MARKER}, found {count}")
    return clean.replace(CHOICE_MARKER, SENTINEL_TOKEN)


def to_author_stem(token_stem: str) -> str:
    """Inverse of parse_stem, for populating the edit form."""
    return (token_stem or "").replace(SENTINEL_TOKEN, CHOICE_MARKER)


def render_stem(token_stem: str, widget_html: str) -> SafeString:
    """Split the token-stem on the sentinel and splice the widget in its place.

    The stem segments are author HTML already sanitised at clean() time, so they
    are marked safe; widget_html is built by the render tag (already safe)."""
    before, _, after = (token_stem or "").partition(SENTINEL_TOKEN)
    return (
        mark_safe(before)  # noqa: S308 — stem segment sanitized at clean() time
        + mark_safe(widget_html)  # noqa: S308 — widget built by the render tag
        + mark_safe(after)  # noqa: S308 — stem segment sanitized at clean() time
    )
