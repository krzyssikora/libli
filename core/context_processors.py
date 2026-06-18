"""Template context processors for the app shell: branding bundle + UI prefs."""

from django.conf import settings
from django.utils import translation

from core.services import get_site_config

THEME_VALUES = {"light", "dark", "auto"}
COOKIE_THEME = "libli_theme"


def institution_branding(request):
    """Expose the cached site bundle (name/logo/palette) to every template.

    Exposed as both ``site`` (used by base.html on non-allauth pages) and
    ``institution`` (used by auth templates where allauth shadows ``site``
    with a Django Site object from django.contrib.sites)."""
    cfg = get_site_config()
    return {"site": cfg, "institution": cfg}


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
    rm = getattr(request, "resolver_match", None)
    view_name = getattr(rm, "view_name", "") or ""
    # allauth login etc. resolve to "account_login"/"account_*"; the invite/SSO
    # pages resolve to "accounts:accept_invite"/"accounts:sso_not_provisioned".
    hide_auth_cta = (
        view_name.startswith(("account_", "accounts:")) or view_name == "landing"
    )
    return {
        "theme_pref": pref,
        "data_theme": data_theme,
        "active_language": active,
        "languages": languages,
        "hide_auth_cta": hide_auth_cta,
    }


def user_roles(request):
    """Group-based role flags for the dashboard sections + account menu.

    Early-returns all-False for anonymous (never touches .groups). One cheap
    query per authed request. Group names come from institution.roles constants
    (re-sliceable; no inline magic strings)."""
    from institution.roles import COURSE_ADMIN
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import STUDENT
    from institution.roles import TEACHER

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "is_student": False,
            "is_teacher": False,
            "is_course_admin": False,
            "is_platform_admin": False,
        }
    names = set(user.groups.values_list("name", flat=True))
    return {
        "is_student": STUDENT in names,
        "is_teacher": TEACHER in names,
        "is_course_admin": COURSE_ADMIN in names,
        "is_platform_admin": PLATFORM_ADMIN in names,
    }
