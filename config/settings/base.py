from pathlib import Path

import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))
# In CI and production there is no .env file — config comes from real
# environment variables, and environ reads those directly.

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django_extensions",
    "rest_framework",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    "core",
    "accounts",
    "institution",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.LanguageSeederMiddleware",
    "core.middleware.SessionLocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.institution_branding",
                "core.context_processors.ui_prefs",
            ],
        },
    },
]

DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgres://libli:libli@localhost:5432/libli"
    ),
}

AUTH_USER_MODEL = "accounts.User"

# django-allauth (local accounts + OIDC SSO; social/JIT provisioning in Plan 0c-2).
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",  # Django admin / username-password
    "allauth.account.auth_backends.AuthenticationBackend",  # allauth front door
]

# Log in with username OR email + password (spec §1).
ACCOUNT_LOGIN_METHODS = {"username", "email"}
# Self-signup form fields; "*" marks required. Email is required and (below) confirmed.
ACCOUNT_SIGNUP_FIELDS = ["username*", "email*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True
# Open self-signup requires a confirmed email (double opt-in); the policy adapter
# (Task 3) only enables signup when Institution.signup_policy == "open".
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# Bot defense for the open-signup form: a hidden trap field (spec §4). allauth's
# default rate limits are also active out of the box.
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "phone_number"

# Policy-gating adapter: enables self-signup only when Institution.signup_policy
# == "open" (Task 3).
ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
LOGIN_URL = (
    "account_login"  # explicit (Django's default happens to match the allauth mount)
)
LOGIN_REDIRECT_URL = (
    "home"  # home view added in Task 2; not exercised until then, so safe
)
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"

# --- SSO / social (Plan 0c-2) ---
# Custom adapter: JIT provisioning + link-by-email + invite consumption.
SOCIALACCOUNT_ADAPTER = "accounts.adapters.SocialAccountAdapter"
# Link a social login to an existing account that owns a *verified* email
# (auto-connect avoids an interstitial). The adapter additionally links the
# User.email-without-EmailAddress case (admin-created accounts) itself.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
# Provision brand-new identities form-lessly. The trusted IdP's email is
# authoritative and the adapter pre-verifies it, so the account-level mandatory
# verification (above) must NOT interpose a confirmation step on the SSO path.
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"  # noqa: E501
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("pl", _("Polski"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
