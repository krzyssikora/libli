"""Playwright screenshots of the illustrated error pages.

Seven shots covering BOTH watermark regimes -- see the spec's shot matrix.
Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in test_e2e_html_element.py.
"""

import os
import tempfile
from pathlib import Path

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_course
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# Outside the repository on purpose: these are verification artifacts, not
# shipped content, and the spec says they stay out of the diff. (Contrast the
# help-shot substrate, which writes into core/static/core/img/help/ because
# those PNGs ARE page content.) A repo-root _shots/ would be untracked litter --
# .gitignore has no entry for it.
SHOTS = Path(tempfile.gettempdir()) / "libli-error-page-shots"


@pytest.fixture(scope="session", autouse=True)
def _fresh_shot_dir():
    # Wipe first. Step 3 explicitly contemplates "fix, re-shoot, re-check" -- and
    # if a case fails on the re-run, ITS png from the previous run survives and
    # would be reviewed as though it were current.
    import shutil

    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    # Wait for the post-login navigation to land before the caller's goto().
    # Without it a lost race turns into a 30 s wait_for_selector timeout instead
    # of a fast, legible failure. Matches test_e2e_auth.py / test_e2e_catalog.py.
    page.wait_for_url(f"{live_server.url}/home/**", timeout=10_000)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "name,theme,width,height",
    [
        ("404-light-1280x900", "light", 1280, 900),
        ("404-dark-1280x900", "dark", 1280, 900),
        ("404-light-390x844", "light", 390, 844),
        ("404-light-1280x720-clamped", "light", 1280, 720),
    ],
)
def test_shoot_404(page, live_server, name, theme, width, height):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({"width": width, "height": height})
    # Anonymous: _resolve_theme_pref reads the libli_theme cookie SERVER-side
    # and renders data-theme accordingly. (It is not the pre-paint script's
    # `if (!pref)` branch doing the work -- that branch never runs, because
    # theme_pref falls through to the cookie and then Institution.default_theme,
    # so data-theme-pref is never empty.)
    page.context.add_cookies(
        [{"name": "libli_theme", "value": theme, "url": live_server.url}]
    )
    page.goto(f"{live_server.url}/no-such-page/")
    # Prove the shot is of the intended page: goto() does NOT throw on a 404,
    # and would happily screenshot a redirect target.
    page.wait_for_selector(".error-page__code", timeout=10_000)
    assert page.locator(".error-page__code").inner_text() == "404"
    page.screenshot(path=str(SHOTS / f"{name}.png"))


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "name,theme,width,height",
    [
        ("403-light-1280x900", "light", 1280, 900),
        ("403-dark-1280x900", "dark", 1280, 900),
        ("403-light-390x844", "light", 390, 844),
    ],
)
def test_shoot_403(page, live_server, name, theme, width, height):
    from tests.factories import UserFactory

    SHOTS.mkdir(parents=True, exist_ok=True)
    user = make_verified_user(
        username="outsider", email="outsider@t.example.com", password=TEST_PASSWORD
    )
    # An AUTHENTICATED user's User.theme wins outright -- _resolve_theme_pref's
    # docstring: "User.theme is never empty, so for an authed user the later
    # rungs are unreachable". The cookie would be silently ignored here and the
    # dark shot would come out light.
    user.theme = theme
    user.save(update_fields=["theme"])
    # Explicit owner: a bare make_course() is UNOWNED. (Kept on its own line --
    # as a trailing comment this call is 91 chars and trips ruff's E501 at 88.)
    course = make_course(owner=UserFactory())
    assert course.owner is not None and course.owner != user and not user.is_staff

    page.set_viewport_size({"width": width, "height": height})
    _login(page, live_server, "outsider")
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    # Without this, a raced login would bounce to /accounts/login/ and the test
    # would still "pass" while screenshotting the login form.
    page.wait_for_selector(".error-page__code", timeout=10_000)
    assert page.locator(".error-page__code").inner_text() == "403"
    page.screenshot(path=str(SHOTS / f"{name}.png"))

    # Eighth capture, once: the account dropdown open on an error page. This is
    # the ONLY artifact that can show the z-index invariant actually holding --
    # the CSS test just parses three integers and cannot prove the z-index: 50
    # panel is still usable inside the header's new stacking context.
    if name == "403-light-1280x900":
        page.locator("[data-account-menu] [data-menu-trigger]").click()
        page.wait_for_selector("[data-account-menu] [data-menu-panel]", timeout=10_000)
        page.screenshot(path=str(SHOTS / "403-light-1280x900-menu-open.png"))
