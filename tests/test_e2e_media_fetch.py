"""Playwright e2e for fetch-an-image-by-URL: the manager form and the picker's
"From URL" tab.

Separate from test_e2e_media_manager.py (replace) and test_e2e_media_picker.py
(library pick): this module drives the two NEW client surfaces Task 11 wired up,
plus the server-side rejection path and both in-flight guards. It copies its
fixtures and helpers from those two sibling files rather than importing them --
see the module-local docstrings below for why each copy exists.

Marked e2e (excluded from the default run; run with `-m e2e`).
"""

import os
import threading
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from courses import media_fetch
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    THIS feature writes fetched image files, so without the redirect every run
    leaves real bytes in the working tree's media/ directory -- more so than any
    other e2e module, since every test here exercises an actual fetch-and-store.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


# The ACCEPTED fixture: an existing 17,883-byte PNG served by live_server's own
# staticfiles handler, so the round trip is genuinely end-to-end over a real
# socket while staying hermetic (no outbound internet). Host is derived from
# live_server.url, never hardcoded: pytest-django resolves to "localhost" here
# (config/settings/test.py sets neither `liveserver` nor
# DJANGO_LIVE_TEST_SERVER_ADDRESS), and a hardcoded "127.0.0.1" would be REJECTED
# by validate_fetch_url's allow-list before a socket ever opened, even though
# both spellings are allow-listed -- because the two hostnames don't match.
FIXTURE_PATH = "/static/core/img/learner.png"
# The REJECTED fixture is a DIFFERENT url and, deliberately, off the allow-list:
# validate_fetch_url raises before _open is ever called, so no socket opens and
# there is no live round trip to depend on for the negative case.
REJECT_URL = "https://example.com/x.png"


def fixture_url(live_server):
    return f"{live_server.url}{FIXTURE_PATH}"


# ---------------------------------------------------------------------------
# Helpers copied (and, where noted, adapted) from the sibling e2e modules.
# Neither _open_manager nor _login nor _setup lives in tests/conftest.py --
# that file holds only element-editor openers.
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_empty_manager(username, slug):
    """A course with NO media assets -- scenario 1 needs the grid to start
    empty so the post-fetch cell can be asserted on specifically, rather than
    matching a pre-existing one."""
    from tests.factories import CourseFactory

    owner = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=owner)
    return owner, course


def _open_manager(page, live_server, username, course):
    """Adapted from tests/test_e2e_media_manager.py:96.

    The original ends with `page.wait_for_selector(".asset-cell")`, which
    blocks until timeout on the empty course scenario 1 seeds -- and would
    prove nothing about the fetch even seeded a pre-existing asset to get past
    it, since a fetched cell and a pre-existing cell both satisfy that
    selector. Wait on `.asset-grid` instead: _asset_grid.html renders it
    unconditionally, empty or not.
    """
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/media/")
    page.wait_for_selector(".asset-grid")


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _setup(page, live_server, username, slug, unit_type):
    """Copied from tests/test_e2e_media_picker.py:50 -- a course + one unit +
    a login, landed on the editor page."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import MediaAssetFactory

    _make_pa_user(username)
    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )
    asset = MediaAssetFactory(course=course, kind="image", file="courses/media/x.png")
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')
    return asset


def _open_picker_for_image(page, live_server, username, slug):
    """The picker setup every mid-flow scenario below needs, written out
    (rather than reusing test_e2e_media_picker.py's `_add_and_pick`, which
    clicks a library asset -- the wrong tab for this module entirely).

    Adds an image element, opens its "Choose media" picker, and switches to
    the "From URL" tab -- the panel ships `hidden` by design, so its controls
    are unreachable until that click runs.

    Every test below queries the URL box as `input[data-picker-url]`, tag-
    qualified -- editor.html's `.editor` section ALSO carries a bare
    `data-picker-url` attribute (the endpoint the picker's own HTML is fetched
    from, media_picker.js:118), and it sits earlier in the DOM than the
    overlay, which is appended to document.body only once opened. A bare
    `[data-picker-url]` resolves to that `<section>` first, not the picker's
    `<input>`, and `page.fill` then rejects it as not fillable.
    """
    _setup(page, live_server, username, slug, "lesson")
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='image']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    page.locator("[data-edit-slot] [data-pick-media]").click()
    page.wait_for_selector(".picker-overlay", timeout=5000)
    page.click('[data-tab="fetch"]')


# ---------------------------------------------------------------------------
# 1. Manager paste -> the asset appears in the grid.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_manager_paste_adds_the_asset(page, live_server):
    # Assert the fixture serves 200 FIRST: a staticfiles-serving regression
    # then fails loudly here rather than as a confusing fetch rejection below.
    assert page.request.get(fixture_url(live_server)).status == 200

    _, course = _seed_empty_manager("mgr-paste", "mgr-paste")
    _open_manager(page, live_server, "mgr-paste", course)

    page.fill(".media-fetch input[name=url]", fixture_url(live_server))
    page.click("[data-fetch-submit]")
    page.wait_for_selector(".asset-cell")

    # Exactly one cell -- the grid started empty, so this is the fetched one
    # and only it.
    expect(page.locator(".asset-cell")).to_have_count(1)
    host = urlsplit(live_server.url).hostname
    assert page.locator(".asset-cell .asset-source").inner_text() == host


# ---------------------------------------------------------------------------
# 2. Picker "From URL" tab -> the asset is selected into an image element.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_picker_from_url_selects_into_an_image_element(page, live_server):
    assert page.request.get(fixture_url(live_server)).status == 200

    _open_picker_for_image(page, live_server, "pick-url", "pick-url")
    page.fill("input[data-picker-url]", fixture_url(live_server))
    page.click("[data-picker-fetch]")
    page.wait_for_selector(".picker-overlay", state="detached")

    sel = page.locator("[data-edit-slot] select[name='media']").input_value()
    assert sel != ""


# ---------------------------------------------------------------------------
# 3. Rejected URL -> the SERVER's message text appears in the picker flash.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_rejected_url_shows_the_server_reason_in_the_picker_flash(page, live_server):
    _open_picker_for_image(page, live_server, "pick-rej", "pick-rej")
    page.fill("input[data-picker-url]", REJECT_URL)
    page.click("[data-picker-fetch]")

    # DIRECT-CHILD combinator, not descendant: openModal sets card.className =
    # "picker-card" and injects a <div class="picker"> INSIDE it, and the JS
    # flashes into `.picker-card`, not `.picker`. A wrong-host mutant that
    # prepended into `.picker` instead would still match a descendant selector
    # (".picker-card .op-error") and stay green here.
    flash = page.wait_for_selector(".picker-card > .op-error")
    assert "allow-list" in flash.inner_text()


# ---------------------------------------------------------------------------
# 4. Picker Enter key (positive) -> fetches without touching the button.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_picker_enter_key_fetches(page, live_server):
    """The POSITIVE Enter scenario -- what actually falsifies "drop the Enter
    handler". The in-flight test below cannot: dropping the handler makes
    Enter a no-op there, `calls` stays at 1, and its assertion still passes.
    The panel has no <form> ancestor (the overlay is appended to
    document.body), so there is no implicit submission to fall back on --
    without the keydown handler, Enter is silently dead.
    """
    assert page.request.get(fixture_url(live_server)).status == 200

    _open_picker_for_image(page, live_server, "pick-enter", "pick-enter")
    page.fill("input[data-picker-url]", fixture_url(live_server))
    page.locator("input[data-picker-url]").press("Enter")  # NO button click
    page.wait_for_selector(".picker-overlay", state="detached")

    # Assert the select's VALUE, not an option count. ImageElementForm.media is
    # a ModelChoiceField that keeps its empty_label (required is flipped to
    # True in __init__, AFTER the field is built, and initial is None), so
    # _edit_image.html always renders <option value="">---------</option> and
    # there is ALWAYS exactly one :checked option -- before the fetch and
    # after it. A count assertion would be 1 on every build, including one
    # where selectAsset never ran.
    assert page.locator("[data-edit-slot] select[name=media]").input_value() != ""


# ---------------------------------------------------------------------------
# 5. Two in-flight tests: a second activation issues no second request.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_second_activation_while_in_flight_issues_no_second_request(
    page, live_server, monkeypatch
):
    """The picker half. Hold the window open deliberately -- the loopback
    fixture completes in single-digit ms, so a plain double-click observes one
    request either way and passes GREEN with no guard at all.

    The hold must NOT be `page.wait_for_timeout` inside the route handler:
    with the sync API, handlers are dispatched on the SAME thread that runs
    the test, so sleeping there blocks the dispatcher and the ordering of the
    assertions below relative to the hold is not guaranteed. Block Django's
    worker thread instead by monkeypatching media_fetch._open -- live_server
    runs in-process, so this leaves Playwright itself fully responsive.
    """
    calls = []
    release = threading.Event()
    real_open = media_fetch._open

    def blocking_open(req, timeout):
        release.wait(10)
        return real_open(req, timeout)

    _open_picker_for_image(page, live_server, "pick-inflight", "pick-inflight")
    monkeypatch.setattr(media_fetch, "_open", blocking_open)
    # Count requests with a NON-blocking route handler.
    page.route(
        "**/media/fetch/", lambda r: (calls.append(r.request.url), r.continue_())
    )

    page.fill("input[data-picker-url]", fixture_url(live_server))
    page.click("[data-picker-fetch]")

    btn = page.locator("[data-picker-fetch]")
    expect(btn).to_be_disabled()  # the guard's visible expression
    # force=True: Playwright's actionability check includes ENABLED, so a
    # plain click() would block until timeout on a CORRECT build -- inverting
    # the assertion below.
    btn.click(force=True)
    page.locator("input[data-picker-url]").press("Enter")  # the SECOND activation
    # route, which bypasses the button entirely -- the DOM-disabled state
    # alone can never intercept it.
    release.set()

    # The picker's real success signal: selectAsset closes the modal. There is
    # no .asset-cell on the editor page (the grid left with the overlay) and
    # no .picker-card either, so waiting on those would hang to timeout.
    page.wait_for_selector(".picker-overlay", state="detached")
    # Count AFTER a yielding barrier. playwright-python's sync API dispatches
    # route handlers only when the test greenlet yields inside an API call, so
    # a bare assert placed before this line could count 1 on a broken build
    # too, with the second request still parked at the browser, unintercepted.
    assert len(calls) == 1


@pytest.mark.django_db(transaction=True)
def test_manager_second_submit_while_in_flight_issues_no_second_request(
    page, live_server, monkeypatch
):
    """The manager half. Task 11 gives it a SEPARATE mgrInFlight flag on a
    SEPARATE listener, so the picker test above does not cover it -- removing
    the manager guard (and with it form.reset()'s duplicate protection) would
    otherwise pass everything else in this module.
    """
    calls = []
    release = threading.Event()
    real_open = media_fetch._open

    def blocking_open(req, timeout):
        release.wait(10)
        return real_open(req, timeout)

    _, course = _seed_empty_manager("mgr-inflight", "mgr-inflight")
    _open_manager(page, live_server, "mgr-inflight", course)
    monkeypatch.setattr(media_fetch, "_open", blocking_open)
    page.route(
        "**/media/fetch/", lambda r: (calls.append(r.request.url), r.continue_())
    )

    page.fill(".media-fetch input[name=url]", fixture_url(live_server))
    page.click("[data-fetch-submit]")
    expect(page.locator("[data-fetch-submit]")).to_be_disabled()
    # A forced click on a DISABLED button dispatches nothing at all, so that
    # alone cannot falsify the mgrInFlight flag. Bypass the button entirely:
    page.eval_on_selector(".media-fetch", "f => f.requestSubmit()")
    release.set()
    page.wait_for_selector(".asset-cell")
    assert len(calls) == 1  # counted after a yielding barrier -- see above
    # form.reset() ran, so a further submit cannot silently duplicate the
    # asset.
    assert page.input_value(".media-fetch input[name=url]") == ""
