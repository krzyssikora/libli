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
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
