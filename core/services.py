"""Cached, read-only access to the singleton institution's render-time config.

Read on every request (theming, nav, i18n seeding), so it is cached in Django's
cache framework with a short TTL and invalidated by signals (see core/apps.py).
It NEVER writes — `Institution.load()` does get_or_create (a write) and must not
run on the GET render path; this uses a plain read with a default fallback."""

from django.core.cache import cache

from courses.validators import MAX_IMAGE_MIB_CEILING
from courses.validators import MAX_VIDEO_MIB_CEILING
from courses.validators import SAFE_IMAGE_EXTENSIONS
from courses.validators import SAFE_VIDEO_EXTENSIONS
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
    "allowed_image_extensions": list(SAFE_IMAGE_EXTENSIONS),
    "allowed_video_extensions": list(SAFE_VIDEO_EXTENSIONS),
    "max_image_mib": MAX_IMAGE_MIB_CEILING,
    "max_video_mib": MAX_VIDEO_MIB_CEILING,
    "onboarded": False,
    "favicon_url": None,
    "favicon_size": None,
}


def _safe_color(value):
    """Return the stored color iff it passes validation, else None (absent)."""
    return value if (value and is_valid_css_color(value)) else None


def _favicon_fields(field):
    """(url, "<W>x<H>") for a readable stored image, else (None, None).

    Opens the stored file, so it runs here -- once per cache rebuild -- never per
    render. Two distinct failure modes: a missing file RAISES (OSError), while an
    unreadable image header makes get_image_dimensions return (None, None)
    WITHOUT raising, which would otherwise stringify to "NonexNone".

    Resolves both keys from the SAME existence check so they cannot drift apart:
    a missing file must fail favicon_url closed too, or {% favicon_links %} takes
    the override branch on a dead URL and suppresses the default SVG/ICO links
    entirely, leaving the site with no favicon at all instead of falling back.
    """
    if not field:
        return None, None
    try:
        width, height = field.width, field.height
    except (OSError, ValueError):
        return None, None
    if not width or not height:
        return None, None
    return field.url, f"{width}x{height}"


def _build():
    from institution.models import Institution

    inst = Institution.objects.filter(pk=1).prefetch_related("brand_colors").first()
    if inst is None:
        return dict(_DEFAULTS)
    colors = {c.key: c.value for c in inst.brand_colors.all()}
    favicon_url, favicon_size = _favicon_fields(inst.favicon)
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
        "allowed_image_extensions": (
            inst.allowed_image_extensions or _DEFAULTS["allowed_image_extensions"]
        ),
        "allowed_video_extensions": (
            inst.allowed_video_extensions or _DEFAULTS["allowed_video_extensions"]
        ),
        "max_image_mib": inst.max_image_mib or _DEFAULTS["max_image_mib"],
        "max_video_mib": inst.max_video_mib or _DEFAULTS["max_video_mib"],
        "onboarded": inst.onboarded,
        "favicon_url": favicon_url,
        "favicon_size": favicon_size,
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


def mark_onboarded():
    """Flip the institution's onboarded flag True. Saving fires the post_save
    signal in core/apps.py, which invalidates the site-config cache. Idempotent."""
    from institution.models import Institution

    inst = Institution.load()
    if not inst.onboarded:
        inst.onboarded = True
        inst.save(update_fields=["onboarded"])


FAVICON_DIR = "core/img/favicon/"


def effective_primary(cfg=None):
    """The brand primary if it is present and valid, else PRIMARY_DEFAULT."""
    cfg = cfg or get_site_config()
    value = cfg.get("primary")
    return value if (value and is_valid_css_color(value)) else PRIMARY_DEFAULT


def default_name():
    """The fallback institution name, for callers that must not import _DEFAULTS."""
    return _DEFAULTS["name"]
