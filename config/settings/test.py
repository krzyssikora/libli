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
import ipaddress  # noqa: E402  (settings module)
import socket  # noqa: E402  (settings module)

from django.core.exceptions import ImproperlyConfigured  # noqa: E402  (settings module)


def _canon_addr(addr: str) -> str:
    """Fold every address that names "this machine" onto one canonical marker.

    getaddrinfo() resolves DNS/hostname spellings and IPv4-vs-IPv6 loopback
    forms, but it does NOT know that the entire 127.0.0.0/8 block (not just
    127.0.0.1) is loopback, nor that connecting to the unspecified address
    (0.0.0.0 / ::) lands on the local machine on many platforms -- MEASURED:
    a live connection to 127.0.0.2 reached the real dev Postgres. Fold both
    cases onto "loopback" so the set-intersection check in `_same_server`
    catches them.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return addr  # not a literal IP (a real hostname): compare as-is
    if ip.is_loopback or ip.is_unspecified:
        return "loopback"
    mapped = getattr(ip, "ipv4_mapped", None)  # e.g. ::ffff:127.0.0.1
    if mapped is not None and mapped.is_loopback:
        return "loopback"
    return str(ip)


def _resolve_addrs(host: str) -> frozenset:
    """Resolve a host spelling to the set of canonical addresses it names.

    A raw string compare only catches the handful of spellings someone thought
    to list -- it lets "127.0.0.2", "localhost." (trailing dot), the IPv6
    loopback written out in full, "0.0.0.0", etc. all past a check for
    "127.0.0.1" -- MEASURED. Resolving addresses instead is what libpq itself
    effectively does. Unresolvable input falls back to the literal string, so
    it still compares (in)equal to itself.
    """
    h = (host or "localhost").strip("[]").rstrip(".").lower()
    try:
        addrs = frozenset(info[4][0] for info in socket.getaddrinfo(h, None))
    except OSError:
        addrs = frozenset({h})
    return frozenset(_canon_addr(a) for a in addrs)


def _same_server(a: dict, b: dict) -> bool:
    """Whether two DATABASES configs name the same Postgres server.

    Compares resolved addresses and port only. NAME is deliberately excluded:
    pointing at the dev server under a different database name is equally
    wrong, because the test run would create and drop databases on the
    developer's real instance.

    Both PORT values are defaulted to 5432 before comparing: a socket-style or
    port-less DATABASE_URL (e.g. "postgres://libli@localhost/libli") parses to
    PORT '' -- MEASURED -- and without this default that empty string would
    never equal an explicit 5432, silently disabling the whole guard.
    """
    port_a = int(a.get("PORT") or 5432)
    port_b = int(b.get("PORT") or 5432)
    if port_a != port_b:
        return False
    return bool(_resolve_addrs(a.get("HOST")) & _resolve_addrs(b.get("HOST")))


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
        # instance. _same_server below now defaults a missing PORT to 5432 on
        # both sides, so it WOULD catch this case too -- but requiring an
        # explicit port here is still the clearer, earlier failure.
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
    # Fail fast when the container is not running. psycopg's default
    # connect_timeout is 130s and Django attempts two databases in sequence
    # (the `postgres` maintenance DB, then the app DB), so a stopped container
    # costs ~4m21s of silence before erroring -- MEASURED at 261.71s. That
    # reads as a hung suite, not a stopped container, and the container being
    # down is the expected daily failure for an opt-in server.
    #
    # setdefault, not assignment: `?connect_timeout=...` in the URL is already
    # parsed into OPTIONS by django-environ, and an explicit choice wins.
    cfg.setdefault("OPTIONS", {}).setdefault("connect_timeout", 5)
    return {"default": cfg}


_resolved_test_db = _resolve_databases(
    env("TEST_DATABASE_URL", default=""),  # noqa: F405
    DATABASES["default"],  # noqa: F405
)
if _resolved_test_db is not None:
    DATABASES = _resolved_test_db
