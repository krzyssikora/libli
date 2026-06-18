from config.settings.base import *  # noqa: F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # faster tests

# Tests assert on django.core.mail.outbox, which only the locmem backend populates.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Tests render {% static %} without running collectstatic, so avoid the manifest
# storage (which needs staticfiles.json) — use the plain finder-backed storage.
STORAGES = {
    **STORAGES,  # noqa: F405  (imported via `from base import *`)
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Pin the cache backend so the site-config cache-timing tests (Task 3) are stable
# regardless of any future production CACHES override. LocMemCache is per-process;
# the autouse `_clear_site_cache` fixture isolates each test.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

# Let render_to_string find route-free test-only templates (e.g. the extra_body probe).
TEMPLATES[0]["DIRS"] = [*TEMPLATES[0]["DIRS"], BASE_DIR / "tests" / "templates"]  # noqa: F405
