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
    "courses",
    "grouping",
    "notes",
    "notifications",
    "tags",
    "integrations",
    "support",
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
                "core.context_processors.user_roles",
                "core.context_processors.notifications_badge",
                "core.context_processors.help_availability",
                "core.context_processors.support_availability",
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
# Binds Institution.allowed_email_domains to the self-signup form. Only the
# "signup" key is overridden: allauth's AddEmailForm and the invite-accept flow
# must stay unrestricted -- see the PolicySignupForm docstring.
ACCOUNT_FORMS = {"signup": "accounts.forms.PolicySignupForm"}
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

# Root-absolute (leading slash) so the configured value does not depend on
# Django's script-prefix normalization. At a root deployment this is identical
# to a relative value; the explicit slash states the intent and is robust if the
# setting is ever read outside a request. See MEDIA_URL below (issue #153).
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Root-absolute (leading slash), matching STATIC_URL above (issue #153). NOTE: a
# request STILL needs something serving /media/<path> — Django's `static()` route in
# config/urls.py is DEBUG-gated and returns [] under DEBUG=False, so production must
# serve MEDIA via the web server (nginx alias) or a cloud storage backend. The
# leading slash does not change that; it only pins the URL as domain-root-absolute.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Course transfer (export/import) — spec 2026-07-05. Deployment guardrails,
# not product limits; deployments hosting bigger courses raise them (and must
# raise proxy body-size + worker timeout limits to match — see docs note).
#
# The caps split into two kinds, and they are sized on OPPOSITE principles:
#
#  - COUNT caps (nodes, elements, media entries, course.json bytes) are
#    memory-bound and reachable only by an authenticated user who already holds
#    the import permission. They are sized so they are NEVER the binding
#    constraint on a real course: the largest real course measures 1,021 nodes /
#    20,608 elements / 1,191 media / 5.79 MiB of course.json, and does not yet
#    cover a full national curriculum, so the defaults leave roughly 5x headroom
#    over it. A count cap that a legitimate course trips is a bug in the cap.
#  - BYTE caps (compressed/uncompressed archive size) cost real disk on the
#    host — staging, the upload spill dir and the media volume each need room
#    for one — so they stay deliberately modest and are raised only by an
#    operator who has sized the storage to match. A course too large for one
#    archive is moved with `migrate_course_content`, whose per-part archives are
#    each far under these, NOT by inflating them.
#
# TRANSFER_MAX_COURSE_JSON_BYTES is what actually bounds import memory: it is a
# byte cap on the decoded document, so no count cap can let an unbounded
# document through. That is WHY the count caps can be generous.
# tests/test_transfer_caps_env.py pins both halves.
#
# All six are env-overridable. Previously COURSE_JSON_BYTES and NODES were not,
# justified by headroom against a course that has since grown into it — a fixed
# cap with no escape hatch is the one an operator cannot route around at 3am.
TRANSFER_MAX_COMPRESSED_BYTES = env.int(
    "LIBLI_TRANSFER_MAX_COMPRESSED_BYTES", default=1 * 1024**3
)  # 1 GiB zip upload
TRANSFER_MAX_UNCOMPRESSED_BYTES = env.int(
    "LIBLI_TRANSFER_MAX_UNCOMPRESSED_BYTES", default=1536 * 1024**2
)  # 1.5 GiB declared/actual total
TRANSFER_MAX_COURSE_JSON_BYTES = env.int(
    "LIBLI_TRANSFER_MAX_COURSE_JSON_BYTES", default=64 * 1024**2
)  # 64 MiB decoded document — the real memory bound
TRANSFER_MAX_MANIFEST_BYTES = 64 * 1024
TRANSFER_MAX_NODES = env.int("LIBLI_TRANSFER_MAX_NODES", default=5000)
# Enforced on IMPORT (courses/transfer/schema.py). Export does not REFUSE on
# these — it cannot, because the importing deployment's caps are the ones that
# decide and are unknowable from here — but it does report the archive's numbers
# against the local caps before writing, so an oversize archive is diagnosed
# before the upload rather than after it. See courses/transfer/export.py.
TRANSFER_MAX_ELEMENTS = env.int("LIBLI_TRANSFER_MAX_ELEMENTS", default=100000)
TRANSFER_MAX_MEDIA_ENTRIES = env.int("LIBLI_TRANSFER_MAX_MEDIA_ENTRIES", default=5000)
TRANSFER_STAGING_MAX_AGE_HOURS = 6
# NOT under MEDIA_ROOT: staged archives must never be web-served (spec §4.3/§6).
TRANSFER_STAGING_DIR = BASE_DIR / "transfer_staging"

# Where Django spills an upload too large for memory, BEFORE the view moves it to
# TRANSFER_STAGING_DIR. None = the system temp dir, correct for local dev. A
# container sets this to a path on sized storage, or a multi-GB upload lands on
# the overlay filesystem. Deliberately NOT TRANSFER_STAGING_DIR: staging.sweep()
# unlinks any file there past its age cap, which would orphan-reap spill files
# and blur the disk accounting between two independently-sized concerns.
# Not under MEDIA_ROOT either, for the same reason as above.
FILE_UPLOAD_TEMP_DIR = env("DJANGO_FILE_UPLOAD_TEMP_DIR", default=None)

# NOT under MEDIA_ROOT: report screenshots may contain another student's name,
# answers or grades and must never be web-served. Served only by the PA-only
# support:screenshot view. Mirrors TRANSFER_STAGING_DIR above.
SUPPORT_SCREENSHOT_DIR = BASE_DIR / "support_screenshots"

# Whitelisted hosts for video/iframe embeds (validated in clean()). Bare lowercase
# hosts; a host matches iff it equals one OR is a subdomain of one. Phase 5 makes
# this admin-configurable.
ALLOWED_EMBED_DOMAINS = env.list(
    "LIBLI_ALLOWED_EMBED_DOMAINS",
    default=[
        "www.youtube.com",
        "youtube.com",
        "youtu.be",
        "player.vimeo.com",
        "www.geogebra.org",
        "geogebra.org",
        "edpuzzle.com",
        "app.lumi.education",
    ],
)

# Hosts this server will CONNECT TO to fetch an image. Deliberately separate from
# ALLOWED_EMBED_DOMAINS: that list authorises what a browser may load in an iframe,
# this one authorises server-side egress, and conflating them would silently widen
# a privilege. NOTE: the allow-list is the ONLY SSRF defence -- there is no IP-range
# check behind it, and the match accepts every subdomain, so each entry must be a
# host whose ENTIRE subdomain tree is trusted (never s3.amazonaws.com, github.io, a
# shared CDN, ...).
ALLOWED_IMAGE_FETCH_DOMAINS = env.list(
    "LIBLI_ALLOWED_IMAGE_FETCH_DOMAINS",
    default=["upload.wikimedia.org", "commons.wikimedia.org"],
)
# Test-only escape hatch: pytest-django's live_server speaks plain http, so an
# https-only rule would make a real end-to-end fetch test impossible. Default OFF,
# and that default is itself asserted by a test.
ALLOW_HTTP_IMAGE_FETCH = env.bool("LIBLI_ALLOW_HTTP_IMAGE_FETCH", default=False)

# Absolute origin (scheme+host, no trailing slash) baked into the HTML-element
# sandbox CSP + <base href>. Trusted/configured — never derived from request Host.
HTMLEL_SANDBOX_ORIGIN = env(
    "DJANGO_HTMLEL_SANDBOX_ORIGIN", default="http://localhost:8000"
)

# Kill switch for the GeoGebra applet-size lookup (courses/geogebra.py). env-backed so
# a deployment behind an egress-restricted network can disable a per-save outbound call
# that would otherwise always time out.
GEOGEBRA_API_LOOKUP = env.bool("LIBLI_GEOGEBRA_API_LOOKUP", default=True)

# The allocation grid posts two fields per student row (the radio's single value
# plus its hidden state token) plus a small fixed overhead, so Django's default
# of 1000 would 400 with TooManyFieldsSent past roughly 500 students — losing
# every pending edit on the one screen built for a whole year group.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
