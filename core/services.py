"""Cached, read-only access to the singleton institution's render-time config.

Read on every request (theming, nav, i18n seeding), so it is cached in Django's
cache framework with a short TTL and invalidated by signals (see core/apps.py).
It NEVER writes — `Institution.load()` does get_or_create (a write) and must not
run on the GET render path; this uses a plain read with a default fallback."""

from django.core.cache import cache

from institution.validators import is_valid_css_color

CACHE_KEY = "core:site_config"
CACHE_TTL = 300  # seconds; bounds cross-worker staleness under the default LocMemCache

PRIMARY_DEFAULT = "#147E78"
ACCENT_DEFAULT = "#C77B2A"

_DEFAULTS = {
    "name": "My Institution",
    "logo_url": None,
    "primary": PRIMARY_DEFAULT,
    "accent": ACCENT_DEFAULT,
    "enabled_languages": ["en", "pl"],
    "default_language": "en",
    "default_theme": "auto",
    "signup_policy": "invite",
}


def _safe_color(value):
    """Return the stored color iff it passes validation, else None (absent)."""
    return value if (value and is_valid_css_color(value)) else None


def _build():
    from institution.models import Institution

    inst = Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()
    if inst is None:
        return dict(_DEFAULTS)
    colors = {c.key: c.value for c in inst.brand_colors.all()}
    return {
        "name": inst.name or _DEFAULTS["name"],
        # Guard: dereferencing .url on an empty ImageField raises ValueError.
        "logo_url": inst.logo.url if inst.logo else None,
        "primary": _safe_color(colors.get("primary")),
        "accent": _safe_color(colors.get("accent")),
        "enabled_languages": inst.enabled_languages or _DEFAULTS["enabled_languages"],
        "default_language": inst.default_language or _DEFAULTS["default_language"],
        "default_theme": inst.default_theme or _DEFAULTS["default_theme"],
        "signup_policy": inst.signup_policy or _DEFAULTS["signup_policy"],
    }


def get_site_config():
    """The cached site-config bundle. Read-only; safe on the GET render path."""
    cfg = cache.get(CACHE_KEY)
    if cfg is None:
        cfg = _build()
        cache.set(CACHE_KEY, cfg, CACHE_TTL)
    return cfg


def invalidate_site_config(*args, **kwargs):
    """Signal receiver: drop the cached bundle so the next read rebuilds it."""
    cache.delete(CACHE_KEY)
