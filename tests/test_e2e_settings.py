"""Playwright e2e for WS4 settings redesign. Marked e2e (run with -m e2e).
Mirrors tests/test_e2e_editor_ws3.py: session async-ORM fixture + allauth login."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa(username):
    # NOTE: factories.make_pa(client, username) takes a test *client* (it force_logins);
    # e2e drives a real browser via Playwright login, so we need a client-less variant.
    # That's why this re-declares the PA setup instead of reusing factories.make_pa.
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_user_settings_controls_and_roundtrip(page, live_server):
    make_verified_user(username="e2eu", email="e2eu@t.example.com", password=TEST_PASSWORD)
    _login(page, live_server, "e2eu")
    page.goto(f"{live_server.url}/settings/")
    # styled controls present, no raw <select>
    assert page.locator("select").count() == 0
    assert page.locator(".seg").count() >= 1
    assert page.locator(".tile").count() >= 1
    # pick Polski + dark, save, reload, assert it stuck
    page.locator('.seg input[value="pl"]').check(force=True)
    page.locator('.tile input[value="dark"]').check(force=True)
    page.locator('.settings-save-bar button[type="submit"]').click()
    page.goto(f"{live_server.url}/settings/")
    assert page.locator('.seg input[value="pl"]').is_checked()
    assert page.locator('.tile input[value="dark"]').is_checked()


@pytest.mark.django_db(transaction=True)
def test_institution_settings_controls(page, live_server):
    _make_pa("e2epa")
    _login(page, live_server, "e2epa")
    page.goto(f"{live_server.url}/settings/institution/")
    assert page.locator("select").count() == 0
    for sel in (".chip", ".seg", ".tile", ".rcard"):
        assert page.locator(sel).count() >= 1, f"missing {sel}"
