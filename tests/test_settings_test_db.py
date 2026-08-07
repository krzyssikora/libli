"""`TEST_DATABASE_URL` resolution for the disposable test server.

Tests the pure helper directly. Do NOT re-import `config.settings.test` the way
`test_settings_production.py` re-imports production: that pattern is safe only
because production is not the active settings module. Re-executing test.py runs
its `TEMPLATES[0]["DIRS"] = [...]` line again, and because `base` is not popped,
`TEMPLATES[0]` is the same dict object `django.conf.settings` references -- every
re-import appends another copy of the test-templates dir to live global state.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings.test import _resolve_databases

# Mirrors the real .env, which uses the "localhost" spelling.
DEV = {"HOST": "localhost", "PORT": 5432, "NAME": "libli"}
TUNED = "postgres://libli@127.0.0.1:55433/libli"


def test_empty_value_means_no_override():
    assert _resolve_databases("", DEV) is None


def test_valid_url_yields_a_databases_dict():
    resolved = _resolve_databases(TUNED, DEV)

    assert set(resolved) == {"default"}
    assert resolved["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert resolved["default"]["PORT"] == 55433


def test_unparseable_value_is_rejected():
    # django-environ returns {} rather than raising for garbage. MEASURED: the
    # resulting config has no PORT either, so the port check is what actually
    # fires -- assert the specific message rather than merely "it raised".
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("not-a-url", DEV)

    assert "explicit port" in str(exc.value)


def test_a_non_postgres_url_without_a_port_is_rejected():
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("sqlite:///tmp/x.db", DEV)

    assert "explicit port" in str(exc.value)


def test_a_non_postgres_url_WITH_a_port_is_rejected_by_the_engine_check():
    # The only test that pins the ENGINE check. MEASURED: without it, this URL
    # is silently ACCEPTED -- it has an explicit non-5432 port on a loopback
    # host, so neither the port check nor the same-server check catches it.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("mysql://libli@127.0.0.1:3306/libli", DEV)

    assert "must be a postgres" in str(exc.value)


def test_pointing_at_the_dev_instance_is_rejected():
    # The whole point of the guard: this parses cleanly and would run the suite
    # against the developer's real database.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("postgres://libli@localhost:5432/libli", DEV)

    # Assert the distinctive fragment: every message in this helper starts with
    # "TEST_DATABASE_URL", which contains "DATABASE_URL" as a substring, so
    # asserting on that would not discriminate between the three messages.
    assert "points at the same server" in str(exc.value)


def test_the_dev_instance_is_rejected_under_a_host_alias():
    # MEASURED: .env spells the host "localhost" but this URL spells it
    # "127.0.0.1", so a raw string compare passes and the suite runs against the
    # developer's real Postgres. This is the spec's own exemplar.
    with pytest.raises(ImproperlyConfigured):
        _resolve_databases("postgres://libli@127.0.0.1:5432/libli", DEV)


def test_the_dev_server_is_rejected_even_under_a_different_database_name():
    # Same server, different NAME: still the dev instance, still wrong.
    with pytest.raises(ImproperlyConfigured):
        _resolve_databases("postgres://libli@127.0.0.1:5432/something_else", DEV)


def test_a_port_less_url_is_rejected():
    # MEASURED: this parses to PORT '', so the same-server check cannot catch
    # it -- yet Django would connect on the default 5432, the dev instance.
    with pytest.raises(ImproperlyConfigured) as exc:
        _resolve_databases("postgres://libli@localhost/libli", DEV)

    assert "explicit port" in str(exc.value)
