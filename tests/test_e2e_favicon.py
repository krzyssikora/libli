"""e2e: a PA replaces and clears the school favicon.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup
from PIL import Image

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


def _png(tmp_path, name="school.png", size=(256, 256)):
    path = tmp_path / name
    Image.new("RGB", size, (200, 40, 40)).save(path, "PNG")
    return str(path)


def _save_branding(page):
    """Click the real Save button and wait for the redirect render to land.

    The locator is `Save branding`, not `Save`: settings.html renders all six tab
    partials on every load and six buttons substring-match "Save".
    """
    with page.expect_navigation():
        page.get_by_role("button", name="Save branding").click()
    page.wait_for_load_state()


@pytest.mark.django_db(transaction=True)
def test_pa_uploads_then_clears_the_favicon(page, live_server, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    _make_pa_user("favicon-pa")
    _login(page, live_server, "favicon-pa")
    page.goto(f"{live_server.url}/manage/settings/?tab=branding")

    wrapper = page.locator('[data-file-field="favicon"]')
    assert wrapper.count() == 1

    # Pick twice on the same field: the first pick REPLACES the empty <div> thumb
    # with an <img>, and a handler that cached the old reference would leave every
    # subsequent pick doing nothing. One pick would ship that green.
    wrapper.locator("[data-file-input]").set_input_files(_png(tmp_path))
    page.wait_for_selector('[data-file-field="favicon"] img[data-file-thumb]')
    # Capture the first pick's src, then require the SECOND pick to change it.
    # Asserting on the filename echo instead would be vacuous: that text is written
    # by the change handler independently of the thumb swap, so it updates even
    # when the thumb reference is stale -- and every later assertion here reads the
    # SAVED file, which is the last-picked one either way.
    first_src = wrapper.locator("img[data-file-thumb]").get_attribute("src")
    wrapper.locator("[data-file-input]").set_input_files(
        _png(tmp_path, "school2.png", (300, 300))
    )
    page.wait_for_function(
        "prev => {"
        " const sel = '[data-file-field=\"favicon\"] img[data-file-thumb]';"
        " const el = document.querySelector(sel);"
        " return el && el.getAttribute('src') !== prev;"
        "}",
        arg=first_src,
    )
    assert wrapper.locator("img[data-file-thumb]").count() == 1

    _save_branding(page)

    head = page.locator('link[rel="icon"]').first
    assert "/media/branding/" in head.get_attribute("href")

    # This runs after _save_branding()'s full page reload, so the logo thumb is
    # always a freshly rendered <div> with no src regardless of whether the
    # in-page JS was scoped per wrapper -- it cannot prove scoping. What it does
    # prove: saving the favicon field did not also write the logo model field.
    # In-page scoping of the change handler is covered above, by the thumb-swap
    # falsification (the second pick changing `src` on the SAME field's thumb).
    logo_thumb = page.locator('[data-file-field="logo"] [data-file-thumb]')
    assert logo_thumb.get_attribute("src") in (None, "")

    page.locator('[data-file-field="favicon"] [data-file-remove]').check()
    _save_branding(page)
    # Scoped by href, not by position: clearing restores TWO icon links (ICO first,
    # SVG last -- the order is what makes the browser pick the vector). `.first` would
    # be the ICO and `.last` would silently pass again if the order were flipped back,
    # so assert on the element that actually carries the SVG.
    svg_link = page.locator('link[rel="icon"][href*="favicon.svg"]')
    assert svg_link.count() == 1
    assert "favicon.svg" in svg_link.get_attribute("href")


@pytest.mark.django_db(transaction=True)
def test_logo_upload_and_clear_still_work(page, live_server, tmp_path, settings):
    """Task 4 rewrote the logo field's hooks, classes and change handler wholesale,
    so the flow most likely to regress is the logo's -- drive it end to end."""
    settings.MEDIA_ROOT = tmp_path
    _make_pa_user("logo-pa")
    _login(page, live_server, "logo-pa")
    page.goto(f"{live_server.url}/manage/settings/?tab=branding")

    wrapper = page.locator('[data-file-field="logo"]')
    wrapper.locator("[data-file-input]").set_input_files(_png(tmp_path, "logo.png"))
    page.wait_for_selector('[data-file-field="logo"] img[data-file-thumb]')
    assert wrapper.locator("img[data-file-thumb]").get_attribute("src")

    _save_branding(page)
    assert page.locator(".brand-preview__logo").first.get_attribute("src")

    page.locator('[data-file-field="logo"] [data-file-remove]').check()
    _save_branding(page)
    cleared = page.locator('[data-file-field="logo"] [data-file-thumb]')
    assert cleared.get_attribute("src") in (None, "")
