"""Playwright smoke suite — the JS/no-flash critical path the Django test client
cannot observe. Marked `e2e` (excluded from the default run); needs a browser.

Uses pytest-django's `live_server` (transactional DB, committed so the server
thread sees seeded data) + pytest-playwright's `page`."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Playwright's sync API runs an event loop, which trips Django's async-safety
    guard on every ORM call. Enable the escape hatch for the browser suite only —
    as a fixture (not a module/conftest global) it activates solely when an e2e test
    is actually selected, so the default `-m 'not e2e'` run keeps the guard intact."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username, password=TEST_PASSWORD):
    page.goto(f"{live_server.url}/accounts/login/")
    # Scope to the login form — the header also has submit buttons (language-switch
    # EN/PL), so a global button[type='submit'] would click those first.
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_boot_and_static_load(page, live_server):
    failures = []
    page.on("response", lambda r: failures.append(r.url) if r.status >= 400 else None)
    page.goto(f"{live_server.url}/")
    assert page.locator(".brand").first.is_visible()  # shell header booted
    assert page.locator(
        ".landing-hero"
    ).is_visible()  # landing-specific content rendered
    # No head-linked asset (css/js/fonts) 404s — self-adjusting, no hardcoded names.
    asset_failures = [
        u for u in failures if any(u.endswith(ext) for ext in (".css", ".js", ".woff2"))
    ]
    assert asset_failures == [], asset_failures


@pytest.mark.django_db(transaction=True)
def test_login_lands_on_themed_dashboard(page, live_server):
    make_verified_user(username="e2euser", email="e2e@school.edu")
    _login(page, live_server, "e2euser")
    page.wait_for_url(f"{live_server.url}/home/")
    assert page.locator("header.app-header").is_visible()


@pytest.mark.django_db(transaction=True)
def test_theme_toggle_persists_across_reload(page, live_server):
    make_verified_user(username="e2etheme", email="e2et@school.edu")
    # Emulate a DARK OS pref so the seeded user's `auto` theme resolves to a visible
    # "dark" first, and the toggle's auto->light step produces an observable
    # data-theme flip (dark -> light). Without this, `auto` resolves to "light" under
    # Playwright's default light scheme and the first click leaves data-theme unchanged.
    page.emulate_media(color_scheme="dark")
    _login(page, live_server, "e2etheme")
    page.wait_for_url(f"{live_server.url}/home/")
    before = page.locator("html").get_attribute("data-theme")  # "dark"
    page.click("[data-theme-toggle]")  # auto -> light
    after = page.locator("html").get_attribute("data-theme")  # "light"
    assert after != before
    # cookie written client-side
    assert any(c["name"] == "libli_theme" for c in page.context.cookies())
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == after


@pytest.mark.django_db(transaction=True)
def test_language_switch_renders_polish(page, live_server):
    page.goto(f"{live_server.url}/")
    page.click("button[name='language'][value='pl']")
    assert page.locator("html").get_attribute("lang") == "pl"
    # Task 10 pins "Log in" -> "Zaloguj się"; assert that exact translation is live.
    assert "Zaloguj" in page.content()


@pytest.mark.django_db(transaction=True)
def test_no_flash_auto_pref_resolves_dark_before_paint(page, live_server):
    # Guarantee the anonymous default theme is auto — don't rely on cross-test DB
    # state under transactional live_server.
    from institution.models import Institution

    inst = Institution.load()
    inst.default_theme = "auto"
    inst.save()
    # Server renders data-theme="light" for an auto pref; emulating a dark OS pref
    # must flip data-theme to "dark" via the pre-paint script.
    page.emulate_media(color_scheme="dark")
    page.goto(f"{live_server.url}/")
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("html").get_attribute("data-theme-pref") == "auto"
