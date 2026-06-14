import pytest
from django.urls import reverse

from tests.factories import make_verified_user


@pytest.fixture(autouse=True)
def _clear_site_cache():
    # Defined here in Task 1 ON PURPOSE (forward reference) so every later task's
    # tests inherit it. It is a harmless no-op until Task 3 adds the cached
    # site-config, which uses LocMemCache (NOT transaction-scoped) — without this a
    # BrandColor set in one test would leak into the next.
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_home_url_name_resolves_and_path_unchanged():
    assert reverse("home") == "/home/"


@pytest.mark.django_db
def test_home_requires_login_anonymous_redirects(client):
    resp = client.get("/home/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_home_authenticated_returns_200(client):
    user = make_verified_user(username="alice", email="alice@school.edu")
    client.force_login(user)
    resp = client.get("/home/")
    assert resp.status_code == 200
    assert b"alice" in resp.content
