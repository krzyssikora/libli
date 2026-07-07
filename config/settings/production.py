from config.settings.base import *  # noqa: F403

DEBUG = False

# --- Transport security ---
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# CSRF trusted origins are required behind HTTPS; supply scheme+host entries.
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# When running behind a TLS-terminating reverse proxy, trust its forwarded-proto
# header so Django knows the original request arrived over HTTPS.
if env.bool("DJANGO_BEHIND_PROXY", default=False):  # noqa: F405
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# allauth builds verification / invitation / password-reset links with this scheme.
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# --- Email ---
# SMTP is opt-in: set DJANGO_EMAIL_HOST to enable it. Left unconfigured, mail is
# written to the console (visibly unconfigured) rather than silently attempting
# SMTP-to-localhost — Django's own default — and black-holing it.
DEFAULT_FROM_EMAIL = env(  # noqa: F405
    "DJANGO_DEFAULT_FROM_EMAIL", default="libli <no-reply@localhost>"
)
SERVER_EMAIL = DEFAULT_FROM_EMAIL

_email_host = env("DJANGO_EMAIL_HOST", default="")  # noqa: F405
if _email_host:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _email_host
    EMAIL_PORT = env.int("DJANGO_EMAIL_PORT", default=587)  # noqa: F405
    EMAIL_HOST_USER = env("DJANGO_EMAIL_HOST_USER", default="")  # noqa: F405
    EMAIL_HOST_PASSWORD = env("DJANGO_EMAIL_HOST_PASSWORD", default="")  # noqa: F405
    EMAIL_USE_TLS = env.bool("DJANGO_EMAIL_USE_TLS", default=True)  # noqa: F405
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
