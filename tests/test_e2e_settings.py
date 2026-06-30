"""Playwright e2e for WS4 settings redesign. Marked e2e (run with -m e2e).
Mirrors tests/test_e2e_editor_ws3.py: session async-ORM fixture + allauth login.

The styled radio/checkbox controls (.seg/.tile/.chip/.rcard) hide their real
<input> with the .vh visually-hidden class (position:absolute; clip:rect(0 0 0 0)),
so a user clicks the *label*. Playwright refuses to interact with clipped inputs by
default, so .check(force=True) targets the input directly — the subsequent reload +
is_checked() round-trip proves the whole save path actually persisted."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

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
def test_user_settings_controls_and_roundtrip(page, live_server):
    make_verified_user(
        username="e2eu", email="e2eu@t.example.com", password=TEST_PASSWORD
    )
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
    # click() does not await the POST/302; gate on the post-save redirect landing
    # back on /settings/ before reloading, so the DB write has committed (mirrors
    # the wait_for_url pattern in test_e2e_smoke.py). Then goto for a fresh render.
    page.wait_for_url(f"{live_server.url}/settings/")
    page.goto(f"{live_server.url}/settings/")
    assert page.locator('.seg input[value="pl"]').is_checked()
    assert page.locator('.tile input[value="dark"]').is_checked()
