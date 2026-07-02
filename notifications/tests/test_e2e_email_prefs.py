"""Playwright e2e for notifications slice 2: toggle an email preference on /settings/.

Real browser gestures only (project lesson: e2e that bypasses the real gesture ships
broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_email_pref_toggle_persists(page, live_server):
    from institution.roles import seed_roles
    from tests.factories import make_verified_user

    seed_roles()
    make_verified_user(username="e2e_prefs", email="e2e_prefs@test.example.com")
    _login(page, live_server, "e2e_prefs")

    page.goto(f"{live_server.url}/settings/")
    box = page.locator("input[name='quiz_graded']")
    expect(box).to_be_checked()  # default on
    box.uncheck()
    page.get_by_role("button", name="Save changes").click()

    # Reload and confirm the toggle stuck.
    page.goto(f"{live_server.url}/settings/")
    expect(page.locator("input[name='quiz_graded']")).not_to_be_checked()
