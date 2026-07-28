"""{% brand_vars %} — emits a tiny inline <style> overriding the two raw brand
vars when (and only when) the institution's stored colors differ from the
defaults and pass color validation. Placed in <head> AFTER tokens.css so the
override wins. Values are re-validated here as defense-in-depth."""

from django import template
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

from core.services import ACCENT_DEFAULT
from core.services import FAVICON_DIR
from core.services import PRIMARY_DEFAULT
from core.services import effective_primary
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


@register.simple_tag
def favicon_links():
    """The head's icon block: static libli assets, or the PA's uploaded override.

    Every URL goes through static()/reverse(): production runs
    CompressedManifestStaticFilesStorage, under which a hardcoded
    /static/core/img/favicon/... path 404s. That cannot be caught by a test --
    config/settings/test.py deliberately swaps in plain StaticFilesStorage -- so it
    is a review-enforced invariant.

    format_html, never mark_safe: a simple_tag's plain-string return is
    auto-escaped in full (the markup would render as visible text), and mark_safe
    on an f-string would inject a filename-bearing media URL into an href
    unescaped. format_html escapes each interpolated URL as an attribute value.
    """
    cfg = get_site_config()
    url = cfg.get("favicon_url")
    if url:
        size = cfg.get("favicon_size")
        if size:
            icon = format_html(
                '<link rel="icon" href="{}" type="image/png" sizes="{}">',
                url,
                size,
            )
        else:
            icon = format_html('<link rel="icon" href="{}" type="image/png">', url)
        parts = [icon, format_html('<link rel="apple-touch-icon" href="{}">', url)]
    else:
        parts = [
            # SVG first, with sizes="any" -- see the ordering test.
            format_html(
                '<link rel="icon" href="{}" type="image/svg+xml" sizes="any">',
                static(FAVICON_DIR + "favicon.svg"),
            ),
            format_html(
                '<link rel="icon" href="{}" sizes="16x16 32x32 48x48">',
                static(FAVICON_DIR + "favicon.ico"),
            ),
            format_html(
                '<link rel="apple-touch-icon" href="{}">',
                static(FAVICON_DIR + "apple-touch-icon.png"),
            ),
        ]
    parts.append(
        format_html('<link rel="manifest" href="{}">', reverse("core:webmanifest"))
    )
    parts.append(
        format_html('<meta name="theme-color" content="{}">', effective_primary(cfg))
    )
    return format_html_join("\n  ", "{}", ((part,) for part in parts))
