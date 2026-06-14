"""{% brand_vars %} — emits a tiny inline <style> overriding the two raw brand
vars when (and only when) the institution's stored colors differ from the
defaults and pass color validation. Placed in <head> AFTER tokens.css so the
override wins. Values are re-validated here as defense-in-depth."""

from django import template
from django.utils.safestring import mark_safe

from core.services import ACCENT_DEFAULT
from core.services import PRIMARY_DEFAULT
from core.services import get_site_config
from institution.validators import is_valid_css_color

register = template.Library()


def _override(value, default):
    """The value iff it is valid AND differs (case-insensitively) from default."""
    if not value or not is_valid_css_color(value):
        return None
    if value.strip().lower() == default.lower():
        return None
    return value.strip()


@register.simple_tag
def brand_vars():
    cfg = get_site_config()
    decls = []
    primary = _override(cfg.get("primary"), PRIMARY_DEFAULT)
    accent = _override(cfg.get("accent"), ACCENT_DEFAULT)
    if primary:
        decls.append(f"--brand-primary: {primary};")
    if accent:
        decls.append(f"--brand-accent: {accent};")
    if not decls:
        return ""
    return mark_safe(  # noqa: S308 — values are validated against an anchored color regex
        "<style>:root{" + "".join(decls) + "}</style>"
    )
