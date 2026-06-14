"""Login/logout UI-pref side effects: seed the session language from the user
(clamped to enabled languages, without mutating the stored value) at login; flag
the theme cookie for clearing at logout (the middleware deletes it on the response)."""

from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.signals import user_logged_out
from django.dispatch import receiver

from core.middleware import LANGUAGE_SESSION_KEY
from core.services import get_site_config


@receiver(user_logged_in)
def seed_language_on_login(sender, request, user, **kwargs):
    cfg = get_site_config()
    if user.language in cfg["enabled_languages"]:
        lang = user.language
    else:
        lang = cfg["default_language"]
    if request is not None and hasattr(request, "session"):
        request.session[LANGUAGE_SESSION_KEY] = lang


@receiver(user_logged_out)
def clear_theme_cookie_on_logout(sender, request, user, **kwargs):
    if request is not None:
        request._libli_clear_theme = True
