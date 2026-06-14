"""i18n + theme-cookie middleware.

Django 4.0 removed session-based language selection (and LANGUAGE_SESSION_KEY).
libli restores it: the seeder writes a session key and SessionLocaleMiddleware
activates it, so the switch persists per-session/per-user. The seeder also keeps
anonymous requests within the institution's enabled languages."""

from django.middleware.locale import LocaleMiddleware
from django.utils import translation

from core.context_processors import COOKIE_THEME
from core.services import get_site_config

LANGUAGE_SESSION_KEY = "_language"


class LanguageSeederMiddleware:
    """Anonymous / no-session-language requests: keep the active language within the
    institution's enabled set (default = default_language). Runs BEFORE
    SessionLocaleMiddleware. Uses only the session + Accept-Language — never
    request.user (AuthenticationMiddleware has not run yet at this position)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.session.get(LANGUAGE_SESSION_KEY):
            cfg = get_site_config()
            candidate = translation.get_language_from_request(request)
            if candidate not in cfg["enabled_languages"]:
                request.session[LANGUAGE_SESSION_KEY] = cfg["default_language"]
        response = self.get_response(request)
        if getattr(request, "_libli_clear_theme", False):
            response.delete_cookie(COOKIE_THEME, path="/", samesite="Lax")
        return response


class SessionLocaleMiddleware(LocaleMiddleware):
    """LocaleMiddleware that prefers the session language key (Django 4.0+ dropped
    session-based selection), falling back to the stock cookie/Accept-Language
    behavior."""

    def process_request(self, request):
        lang = request.session.get(LANGUAGE_SESSION_KEY)
        if lang and translation.check_for_language(lang):
            translation.activate(lang)
            request.LANGUAGE_CODE = translation.get_language()
        else:
            super().process_request(request)
