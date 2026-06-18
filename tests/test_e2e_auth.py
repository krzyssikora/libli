"""Playwright e2e for the auth/login redesign. Marked e2e (run with -m e2e)."""

import os

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_login_card_renders_and_logs_in(page, live_server):
    make_verified_user(
        username="alice", email="alice@school.edu", password=TEST_PASSWORD
    )
    page.goto(f"{live_server.url}/accounts/login/")
    assert page.locator(".auth-card").is_visible()
    assert page.locator(".auth-card__wordmark").is_visible()
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("alice")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(f"{live_server.url}/**")
    # Landed on an authenticated page (the app shell header renders).
    assert page.locator(".app-header").is_visible()


@pytest.mark.django_db(transaction=True)
def test_login_language_switch_renders_polish(page, live_server):
    page.goto(f"{live_server.url}/accounts/login/")
    # The corner lang-switch (scoped past any other forms) flips to PL.
    page.locator(".auth-chrome form.lang-switch button[value='pl']").click()
    page.wait_for_load_state("networkidle")
    assert "Zaloguj" in page.content()


@pytest.mark.django_db(transaction=True)
def test_login_sso_button_visible_when_provider_seeded(page, live_server):
    app = SocialApp.objects.create(
        provider="openid_connect",
        provider_id="testidp",
        name="Test IdP",
        client_id="cid",
        secret="sec",
    )
    app.sites.add(Site.objects.get_current())
    page.goto(f"{live_server.url}/accounts/login/")
    assert page.locator(".auth-sso").is_visible()


@pytest.mark.django_db(transaction=True)
def test_login_dark_theme_card(page, live_server):
    page.goto(f"{live_server.url}/accounts/login/")
    toggle = page.locator(".auth-chrome [data-theme-toggle]")
    # THEMES cycle is light → dark → auto (→ light …). Starting pref is "auto",
    # so two clicks reach "dark": auto→light (click 1), light→dark (click 2).
    toggle.click()
    toggle.click()
    assert page.locator("html[data-theme='dark']").count() == 1
    assert page.locator(".auth-card").is_visible()
