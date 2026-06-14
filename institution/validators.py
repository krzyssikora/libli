"""Strict CSS-color validation shared by the BrandColor model (admin-time) and
the branding template tag (render-time). Anchored so nothing but a color string
can pass — closing the inline-<style> injection vector."""

import re

from django.core.exceptions import ValidationError

# Anchored: #rgb / #rrggbb, or rgb()/rgba()/hsl()/hsla() with numeric args.
_HEX = r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})"
_NUM = r"[0-9]{1,3}(?:\.[0-9]+)?%?"
_ALPHA = r"(?:0|1|0?\.[0-9]+)"
_RGB = rf"rgba?\(\s*{_NUM}\s*,\s*{_NUM}\s*,\s*{_NUM}\s*(?:,\s*{_ALPHA}\s*)?\)"
_HSL = rf"hsla?\(\s*{_NUM}\s*,\s*{_NUM}\s*,\s*{_NUM}\s*(?:,\s*{_ALPHA}\s*)?\)"
CSS_COLOR_RE = re.compile(rf"^(?:{_HEX}|{_RGB}|{_HSL})$")


def is_valid_css_color(value):
    """True iff `value` (after stripping surrounding whitespace) is a safe CSS color."""
    return bool(CSS_COLOR_RE.match((value or "").strip()))


def validate_css_color(value):
    """Django field validator raising ValidationError on a non-color value."""
    if not is_valid_css_color(value):
        raise ValidationError(
            "Enter a valid CSS color (hex like #147E78, or rgb()/hsl()).",
            code="invalid_css_color",
        )
