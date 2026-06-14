"""Template context processors for the app shell: branding bundle + UI prefs."""

from django.conf import settings
from django.utils import translation

from core.services import get_site_config

THEME_VALUES = {"light", "dark", "auto"}
COOKIE_THEME = "libli_theme"


def institution_branding(request):
    """Expose the cached site bundle (name/logo/palette) to every template."""
    return {"site": get_site_config()}


def _resolve_theme_pref(request):
    """Winning-precedence theme preference (raw, may be 'auto').

    User.theme (authed) -> libli_theme cookie -> Institution.default_theme.
    User.theme is never empty, so for an authed user the later rungs are unreachable.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.theme in THEME_VALUES:
        return user.theme
    cookie = request.COOKIES.get(COOKIE_THEME)
    if cookie in THEME_VALUES:
        return cookie
    return get_site_config()["default_theme"]


def ui_prefs(request):
    """Resolved theme attributes + language switch data for the shell."""
    pref = _resolve_theme_pref(request)
    data_theme = "light" if pref == "auto" else pref  # server can't know OS -> light
    cfg = get_site_config()
    active = translation.get_language() or cfg["default_language"]
    # Offer only enabled languages, labelled from settings.LANGUAGES.
    labels = dict(settings.LANGUAGES)
    languages = [
        {"code": code, "label": labels.get(code, code), "active": code == active}
        for code in cfg["enabled_languages"]
    ]
    return {
        "theme_pref": pref,
        "data_theme": data_theme,
        "active_language": active,
        "languages": languages,
    }
