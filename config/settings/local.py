from config.settings.base import *  # noqa: F403

# DEBUG is driven by DJANGO_DEBUG in .env (read in base.py); .env.example sets it true.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Dev: print confirmation / password-reset emails to the runserver console.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Dev: serve static from source so CSS/JS edits show on a plain refresh, with no
# collectstatic step. base.py uses CompressedManifestStaticFilesStorage (correct for
# production), which serves hashed names from the collected staticfiles/ tree — in dev
# that means every edit needs a re-collect. Override to the plain storage here (mirrors
# config.settings.test). Dev-only; production.py is unaffected.
STORAGES = {
    **STORAGES,  # noqa: F405  (imported via `from base import *`)
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Dev: let WhiteNoise serve /static/ instead of runserver's StaticFilesHandler, so
# static responses carry a Cache-Control header and the browser revalidates.
#
# The problem this fixes: runserver's handler sends ONLY Last-Modified -- no
# Cache-Control, no ETag. With no explicit freshness a browser invents one, roughly
# 10% of the file's age, so a file untouched for months is treated as fresh for days
# and a plain refresh never asks the server. Conditional GET works fine (the server
# answers 304); the browser simply does not ask. That contradicts the note above,
# which promises edits "show on a plain refresh" -- true of the server, not the
# browser. MEASURED before this change: courses.css, editor.js, tokens.css and
# math.js all responded with Last-Modified alone.
#
# `whitenoise.runserver_nostatic` must precede django.contrib.staticfiles: it exists
# to suppress that app's runserver override, and Django resolves a duplicated
# management command in favour of the app listed FIRST. Prepending is also why this
# does not disturb template or static-finder precedence for any existing app -- the
# relative order of everything already in the list is unchanged.
INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]  # noqa: F405

WHITENOISE_USE_FINDERS = True  # serve from the source tree; no collectstatic in dev
WHITENOISE_AUTOREFRESH = True  # re-stat on every request, so an edit is picked up
WHITENOISE_MAX_AGE = 0  # emit a Cache-Control that forces revalidation
