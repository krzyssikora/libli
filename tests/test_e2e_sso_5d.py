"""Playwright e2e for Phase 5d: a PA configures + enables SSO via the settings tab,
then an anonymous visitor sees the landing SSO button; disabling hides it.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    """Seed a Platform Admin with a verified email so allauth lets them log in."""
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@school.edu",
        password=TEST_PASSWORD,
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    """Log in via the real allauth login form. Waits for the form to detach."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_selector("form[action*='login']", state="detached")


def _logout(page, live_server):
    """Log out via the real allauth logout confirm page (real UI gesture)."""
    page.goto(f"{live_server.url}/accounts/logout/")
    page.get_by_role("button", name="Sign Out").click()
    page.wait_for_url("**/login/**", timeout=5000)


@pytest.mark.django_db(transaction=True)
def test_sso_enable_shows_landing_button_then_disable_hides_it(page, live_server):
    """PA drives two sub-flows via the real /manage/settings/?tab=sso UI:

    1. Fills + enables SSO credentials; asserts the anonymous landing page
       shows the "Continue with SSO" button (href contains 'oidc/sso/login/').
    2. Unchecks enabled and saves; asserts the button is gone.

    The landing view redirects authenticated users to /home, so we log out
    before each landing assertion (real allauth logout confirm gesture).
    """
    _make_pa_user("e2e_5d_pa")
    _login(page, live_server, "e2e_5d_pa")

    # ── Sub-flow 1: fill + enable SSO, assert landing shows the button ────────
    page.goto(f"{live_server.url}/manage/settings/?tab=sso")
    page.wait_for_selector("[data-tab='sso']:not([hidden])")

    # Scope every selector to the SSO <form>: settings.html renders all four
    # tab forms at once, and BrandingForm also has input[name='name'] — a bare
    # selector would be strict-mode-ambiguous.
    sso = "form[action*='settings/sso/'] "
    page.check(sso + "input[name='enabled']")
    page.fill(sso + "input[name='name']", "Acme IdP")
    page.fill(sso + "input[name='server_url']", "https://idp.example.com")
    page.fill(sso + "input[name='client_id']", "client-123")
    page.fill(sso + "input[name='client_secret']", "shh-secret")
    page.click(sso + "button[type='submit']")
    page.wait_for_load_state("networkidle")
    assert "tab=sso" in page.url

    _logout(page, live_server)
    page.goto(f"{live_server.url}/")
    sso_btn = page.locator("a[href*='oidc/sso/login/']")
    assert sso_btn.count() == 1, (
        "Expected 1 SSO login button on the anonymous landing page after enabling "
        f"SSO; got {sso_btn.count()}"
    )

    # ── Sub-flow 2: disable SSO, assert landing button disappears ─────────────
    _login(page, live_server, "e2e_5d_pa")
    page.goto(f"{live_server.url}/manage/settings/?tab=sso")
    page.wait_for_selector("[data-tab='sso']:not([hidden])")
    page.uncheck(sso + "input[name='enabled']")
    page.click(sso + "button[type='submit']")
    page.wait_for_load_state("networkidle")

    _logout(page, live_server)
    page.goto(f"{live_server.url}/")
    sso_btn = page.locator("a[href*='oidc/sso/login/']")
    assert sso_btn.count() == 0, (
        "Expected 0 SSO login buttons on the anonymous landing page after disabling "
        f"SSO; got {sso_btn.count()}"
    )
