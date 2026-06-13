from config.settings.base import *  # noqa: F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # faster tests

# Tests assert on django.core.mail.outbox, which only the locmem backend populates.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
