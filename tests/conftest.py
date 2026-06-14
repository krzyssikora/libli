import pytest


@pytest.fixture(autouse=True)
def _enable_db_access(db):
    """Give every test DB access (small project; convenient default).

    Consequence: every test — including the /healthz smoke test — needs a
    running PostgreSQL. That coupling is intentional for this project."""


@pytest.fixture(autouse=True)
def _clear_site_cache():
    """LocMemCache is not transaction-scoped; clear it around every test so a
    cached site-config (palette / signup_policy / enabled_languages) from one test
    never leaks into the next."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
