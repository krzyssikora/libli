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

HTMLEL_SANDBOX_ORIGIN = "http://testserver"

# --- optional: run against the disposable tuned server (docker-compose.test.yml) ---
# Unset, everything below is a no-op and behaviour is identical to before.
# See docs/development/testing.md.
from django.core.exceptions import ImproperlyConfigured  # noqa: E402  (settings module)

# "localhost", "127.0.0.1", "::1" and "" all name the same machine. Comparing the
# raw strings would let postgres://...@127.0.0.1:5432/... past a .env that spells
# the same host "localhost" -- MEASURED, and exactly the case the guard exists for.
_LOOPBACK = {"", "localhost", "127.0.0.1", "::1"}


def _same_server(a: dict, b: dict) -> bool:
    """Whether two DATABASES configs name the same Postgres server.

    Compares (host, port) only. NAME is deliberately excluded: pointing at the
    dev server under a different database name is equally wrong, because the
    test run would create and drop databases on the developer's real instance.
    """

    def host(cfg):
        h = (cfg.get("HOST") or "").lower()
        return "localhost" if h in _LOOPBACK else h

    return (host(a), a.get("PORT")) == (host(b), b.get("PORT"))


def _resolve_databases(env_value: str, current: dict) -> dict | None:
    """Return a DATABASES-shaped dict for `env_value`, or None for "no override".

    Raises ImproperlyConfigured when a value is set but unusable. django-environ
    does NOT raise for garbage -- `db_url_config("not-a-url")` returns `{}` --
    so the explicit checks below, not the try/except, do the real work.
    """
    if not env_value:
        return None
    try:
        cfg = env.db_url_config(env_value)  # noqa: F405
    except Exception as exc:  # defensive: non-string input, future parser changes
        raise ImproperlyConfigured(
            f"TEST_DATABASE_URL could not be parsed: {env_value!r}"
        ) from exc
    # ORDER MATTERS: the PORT check runs FIRST. Both "not-a-url" and
    # "sqlite:///tmp/x.db" parse to an empty PORT, so with the ENGINE check
    # first they raise the postgres message instead -- MEASURED, and it makes
    # two of this task's own tests fail.
    if not cfg.get("PORT"):
        # MEASURED: db_url_config("postgres://libli@localhost/libli") yields
        # PORT ''. Django would then connect on the default 5432 -- the dev
        # instance -- and _same_server below would not catch it, because ''
        # != 5432. An explicit port is the only safe form here.
        raise ImproperlyConfigured(
            "TEST_DATABASE_URL must name an explicit port (the tuned server "
            f"listens on 55433, not the default 5432); got {env_value!r}"
        )
    if cfg.get("ENGINE") != "django.db.backends.postgresql":
        raise ImproperlyConfigured(
            f"TEST_DATABASE_URL must be a postgres:// URL; got {env_value!r}"
        )
    if _same_server(cfg, current):
        raise ImproperlyConfigured(
            "TEST_DATABASE_URL points at the same server as DATABASE_URL "
            f"({env_value!r}). It must be a separate, disposable server -- "
            "see docker-compose.test.yml."
        )
    return {"default": cfg}


_resolved_test_db = _resolve_databases(
    env("TEST_DATABASE_URL", default=""),  # noqa: F405
    DATABASES["default"],  # noqa: F405
)
if _resolved_test_db is not None:
    DATABASES = _resolved_test_db
