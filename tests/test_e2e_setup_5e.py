"""Playwright e2e for Phase 5e: a freshly-bootstrapped PA is auto-redirected into
the wizard on login, walks Welcome -> Identity -> Access -> Team -> SSO -> Finish
with real gestures, and afterwards lands on home without being re-redirected.

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
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db(transaction=True)
def test_first_run_wizard_full_flow(page, live_server):
    _make_pa_user("pa")

    # Log in -> the home gate auto-redirects the unonboarded PA into the wizard.
    # Scope to the login form: base.html renders per-language lang-switch submit
    # buttons on every page, so a bare button[type='submit'] is strict-mode-ambiguous.
    page.goto(live_server.url + "/accounts/login/")
    login = "form[action*='login'] "
    page.fill(login + "input[name='login']", "pa")
    page.fill(login + "input[name='password']", TEST_PASSWORD)
    page.click(login + "button[type='submit']")
    page.wait_for_url("**/manage/setup/")
    assert "Step 1 of 5" in page.content()

    # Welcome -> Get started
    page.click("text=Get started")
    page.wait_for_url("**/manage/setup/identity/")

    # Identity: set the name, Next
    ident = "form[action*='setup/identity/'] "
    page.fill(ident + "input[name='name']", "Acme Academy")
    page.click(ident + "button[value='next']")
    page.wait_for_url("**/manage/setup/access/")

    # Access: choose open signup, Next
    page.click("form[action*='setup/access/'] button[value='next']")
    page.wait_for_url("**/manage/setup/team/")

    # Team: Next (skip inviting) -> SSO
    page.click("form[action*='setup/team/'] button[value='next']")
    page.wait_for_url("**/manage/setup/sso/")

    # SSO: Finish without configuring SSO
    page.click("form[action*='setup/sso/'] button[value='finish']")
    page.wait_for_url("**/home/")  # _finish redirects to "home" (config/urls: /home/)

    # Re-visiting the root does NOT redirect back into the wizard (landing sends an
    # authed user to /home/, and the gate no longer fires now onboarded is True).
    page.goto(live_server.url + "/")
    assert "/manage/setup/" not in page.url
