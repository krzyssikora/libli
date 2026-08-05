"""Playwright e2e for the four image size presets (plan slice C1, Task 8).

The CSS source tests (courses/tests/test_image_size_css.py) only prove a rule is
*present* in courses.css. They cannot prove what the browser actually computes for a
given fixture at a given viewport, because that number is the output of a `min()` over
three quantities (a width cap, a height cap, and the image's own intrinsic size) that
only a real layout engine resolves. This module is the load-bearing measurement: it
seeds one tall and one wide image at each of the four presets, opens the real lesson
page at two viewports, and asserts the rendered `getBoundingClientRect()` against the
same formula the CSS is supposed to implement.

Both fixtures are required, not one: at the desktop viewport the tall fixture is
height-bound at every preset (and intrinsic-bound at `full`), so `max-width` is never
exercised by it there — only the wide fixture exercises the width caps. Conversely at
the phone viewport the wide fixture is width-bound at all four presets. Neither fixture
alone would touch every rule this slice added.
"""

import os

import pytest

from courses.models import ImageElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

PA_USERNAME = "pa-imgsize"

# Presets x their percentage caps (as fractions), read here only to build the RUNTIME
# formula in the browser — never to assert a literal pixel number of our own.
WIDTH_FRACTIONS = {"small": 0.25, "medium": 0.50, "large": 0.75, "full": 1.0}
HEIGHT_FRACTIONS = {"small": 0.30, "medium": 0.45, "large": 0.60, "full": 1.00}

DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 360, "height": 640}


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    live_server's `_MediaFilesHandler` reads `settings.MEDIA_ROOT` per request to
    decide what `/media/<path>` serves -- pointing it at tmp_path before
    make_image_asset writes any bytes is what makes a freshly created fixture image
    resolve at all, not an optional convenience.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


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


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_unit(owner, slug):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _save_open_form(page):
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()


def _await_decoded(page, locator):
    """Wait for an <img> to actually have pixels before measuring it.

    locator.wait_for() defaults to state="visible", which only needs a non-empty box --
    and an <img> whose bytes have not arrived still gets one from its alt text, so
    naturalWidth can legitimately read 0. Measuring before this resolves races the
    decode: every box read below depends on it running first.
    """
    locator.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=locator.element_handle()
    )


@pytest.fixture
def seeded(db, _isolated_media):
    """(owner, course, unit, tall, wide).

    Both dependencies are declared explicitly rather than relied on for autouse
    ordering, matching every seeding fixture in tests/test_e2e_imagezoom.py.
    `_isolated_media` must run BEFORE make_image_asset writes any bytes; `db` must run
    before any ORM call.
    """
    owner = _make_pa_user(PA_USERNAME)
    course, unit = _seed_unit(owner, "imgsize")
    tall = make_image_asset(course, "tall.png", size=(297, 719), color="magenta")
    wide = make_image_asset(course, "wide.png", size=(948, 719), color="magenta")
    for shape, asset in (("tall", tall), ("wide", wide)):
        for preset in ("small", "medium", "large", "full"):
            el = ImageElement.objects.create(
                media=asset, alt=f"{shape}-{preset}", size=preset
            )
            add_element(unit, el)
    return owner, course, unit, tall, wide


def _measure(page, shape, preset):
    """getBoundingClientRect() of the <img> identified by `alt="{shape}-{preset}"`,
    plus everything the formula needs read at runtime: the containing block's content
    width, the viewport height, and the image's own intrinsic size."""
    img = page.locator(f"img[alt='{shape}-{preset}']")
    _await_decoded(page, img)
    natural = img.evaluate("el => [el.naturalWidth, el.naturalHeight]")
    fig = img.locator("xpath=..")
    container = fig.locator("xpath=..")
    cw = container.evaluate("el => parseFloat(getComputedStyle(el).width)")
    vh = page.evaluate("window.innerHeight")
    rect = img.evaluate(
        "el => { const r = el.getBoundingClientRect(); return [r.width, r.height]; }"
    )
    return natural, cw, vh, rect


def _check_preset(page, shape, preset):
    """Return None if `shape-preset` matches the formula, else a description of the
    mismatch. A non-raising check (rather than a bare assert) so the caller can run
    every one of the sixteen combinations in one pass instead of stopping at the
    first failure -- the falsification step needs to see the WHOLE pass/fail matrix
    per mutant, not just its first casualty."""
    (nw, nh), cw, vh, (rw, rh) = _measure(page, shape, preset)
    ratio = nw / nh
    wcap = cw * WIDTH_FRACTIONS[preset]
    hcap = vh * HEIGHT_FRACTIONS[preset]
    h = min(hcap, wcap / ratio, nh)
    w = h * ratio
    if abs(rh - h) > 1 or abs(rw - w) > 1:
        return f"{shape}-{preset}: got {rw:.1f}x{rh:.1f}, want {w:.1f}x{h:.1f}"
    return None


def _assert_harness(page, tall, wide):
    """A 404'd image reports 0x0, so this distinguishes 'the preset is wrong' from
    'the fixture never loaded' -- without it every box assertion below would fail
    identically and uninformatively."""
    for shape, (want_w, want_h) in (("tall", (297, 719)), ("wide", (948, 719))):
        img = page.locator(f"img[alt='{shape}-small']")
        _await_decoded(page, img)
        nw, nh = img.evaluate("el => [el.naturalWidth, el.naturalHeight]")
        assert (nw, nh) == (want_w, want_h), f"{shape}: harness image is {nw}x{nh}"


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_preset_bounding_boxes(page, live_server, seeded, viewport):
    owner, course, unit, tall, wide = seeded
    _login(page, live_server, owner.username)
    page.set_viewport_size(viewport)
    page.goto(_lesson_url(live_server, unit))

    _assert_harness(page, tall, wide)

    failures = [
        msg
        for shape in ("tall", "wide")
        for preset in ("small", "medium", "large", "full")
        if (msg := _check_preset(page, shape, preset)) is not None
    ]
    assert not failures, "\n".join(failures)
