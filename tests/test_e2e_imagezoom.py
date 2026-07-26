"""Playwright e2e for click-to-enlarge images.

Media IS served under live_server, regardless of DEBUG: django.test.testcases.
LiveServerThread.run() (django/test/testcases.py:1755) unconditionally builds
`self.static_handler(_MediaFilesHandler(WSGIHandler()))` -- no DEBUG check anywhere in
that chain. `_MediaFilesHandler.get_base_dir()`/`get_base_url()`
(django/test/testcases.py:1716-1726) return `settings.MEDIA_ROOT`/`settings.MEDIA_URL`
at request time, so `/media/<path>` is served straight from `MEDIA_ROOT` via
django.views.static.serve, entirely bypassing this project's own config/urls.py (whose
DEBUG-gated route only matters for a real dev/prod server). This means `_isolated_media`
is not just about not polluting the developer's real media/ tree: it is *also* what
makes the fixture images resolve at all, because `_MediaFilesHandler` reads
`settings.MEDIA_ROOT` per request -- point it at tmp_path and that is what gets served.
No Playwright-level route interception is needed or present; every `naturalWidth`
assertion below is a live guard against a MEDIA_ROOT misconfiguration or a
wrongly-sized fixture, not a workaround for a serving gap that does not exist.

Focus placement via locator.focus()/blur() is sanctioned SETUP here: several cases need
a trigger focused but not activated, and a real click on an armed image opens the
overlay. The interaction under test -- the click, the keypress, the wheel -- is always
real. The one exception is the Tab-traversal cases, which must use real Tab presses
because the tab order IS what they test.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND -- a
background `-m e2e` sweep spawns runaway browsers.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 800}
BIG = (1400, 900)
MAGENTA = "#FF00FF"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists. Two independent reasons, both real:

    1. make_image_asset writes its bytes through the FileField at create() time, so an
       override applied later would drop a 1400x900 PNG into the developer's real
       media/ tree.
    2. live_server's `_MediaFilesHandler` (see the module docstring) reads
       `settings.MEDIA_ROOT` per request to decide what `/media/<path>` serves -- this
       fixture pointing it at tmp_path is what makes a freshly created fixture image
       resolve at all, not an optional convenience.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


# _student / _lesson_url / _login are defined here rather than imported from
# tests/test_e2e_gallery.py: this module needs a user OBJECT (for EnrollmentFactory),
# not a username, and every e2e module in this repo is deliberately self-contained.
# The login helper is the same scoped-form version that module uses.
def _student(username="zoomstudent"):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _login(page, live_server, user):
    # Scope to the login form. base.html renders one <button type="submit"
    # name="language"> per enabled language in the header (templates/base.html:60-67),
    # and page.click is non-strict -- an unscoped click POSTs the language switcher and
    # reloads the login page with nobody authenticated. Mirrors the proven helper at
    # tests/test_e2e_editor.py:38-47.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _image_unit(
    course, size=BIG, color=MAGENTA, alt="A labelled diagram", name="z.png"
):
    from courses.models import ImageElement

    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename=name, size=size, color=color)
    add_element(unit, ImageElement.objects.create(media=asset, alt=alt))
    return unit


@pytest.fixture
def zoom_lesson(db, _isolated_media):
    """One lesson unit, one ImageElement, 1400x900 magenta, non-empty alt.

    _isolated_media is listed explicitly, not relied on as autouse-ordering: the asset
    is written through the FileField at create() time, and a silent mis-ordering would
    drop a 1400x900 PNG into the developer's real media/ tree.
    """
    course = CourseFactory()
    unit = _image_unit(course)
    user = _student()
    EnrollmentFactory(course=course, student=user)
    return unit, user


def _goto(page, live_server, unit, user):
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))


def _trigger(page):
    return page.locator("[data-zoomable]").first


def _open(page, trigger):
    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")
    # The [open] attribute is set synchronously, but the overlay <img> still has to
    # request and decode its bytes, so measuring immediately can read naturalWidth == 0
    # and a zero-area box regardless of who serves the file. Wait for the decode before
    # any geometry is taken.
    page.wait_for_function(
        "() => { const i = document.querySelector('.imgzoom__img');"
        " return i && i.complete && i.naturalWidth > 0; }"
    )
    return page.locator("dialog.imgzoom")


def _await_decoded(page, locator):
    """Wait for an <img> to actually have pixels before measuring it.

    locator.wait_for() defaults to state="visible", which only needs a non-empty box --
    and an <img> whose bytes have not arrived still gets one from its alt text, so
    naturalWidth can legitimately read 0. This race is real independent of who serves
    the bytes (see the module docstring): a fresh request always needs a round trip and
    a decode, and it applies to the inline trigger exactly as it does to the overlay
    image.
    """
    locator.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=locator.element_handle()
    )


def _box(locator):
    box = locator.bounding_box()
    assert box is not None, "expected a laid-out box"
    return box


def _natural_width(locator):
    return locator.evaluate("el => el.naturalWidth")


def test_harness_serves_the_real_fixture_image(page, live_server, zoom_lesson):
    """The precondition every geometry case depends on.

    Django's live_server serves /media/ from MEDIA_ROOT on its own (see the module
    docstring), so this assertion is not a workaround for a serving gap -- it is a live
    guard against a MEDIA_ROOT misconfiguration (e.g. _isolated_media mis-ordered
    relative to asset creation) or a fixture built at the wrong size: either would
    surface here as naturalWidth != 1400 instead of silently measuring the wrong image.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    assert _natural_width(trigger) == 1400


def test_closed_dialog_is_not_rendered(page, live_server, zoom_lesson):
    """Open, close, THEN assert -- the dialog is created lazily.

    Asserting "absent or invisible" before the first open would be vacuous: it passes
    even with `display: grid` unscoped, which is the very bug this case exists to catch.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    dialog.click()
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")

    assert dialog.evaluate("el => el.checkVisibility()") is False
    assert dialog.bounding_box() is None  # display:none -> None, not a zero-area box


def test_overlay_enlarges_without_upscaling_and_fits_the_viewport(
    page, live_server, zoom_lesson
):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)  # or inline_width is measured pre-load and the
    assert _natural_width(trigger) == 1400, "media route must serve the real image"
    # "overlay is wider" would pass for the wrong reason if measured before decode.
    inline_width = _box(trigger)["width"]

    dialog = _open(page, trigger)
    img = page.locator(".imgzoom__img")
    box = _box(img)

    assert box["width"] > inline_width, "the overlay must actually enlarge"
    assert box["width"] <= _natural_width(img) + 0.5, "never upscaled past natural size"

    # Half-pixel tolerance is not decoration: for this fixture the vertical axis sits
    # EXACTLY at the 800px cap and the 0.888... scale factor rounds at device-pixel
    # resolution. Only the horizontal axis has real slack.
    assert box["x"] >= -0.5 and box["y"] >= -0.5
    assert box["x"] + box["width"] <= VIEWPORT["width"] + 0.5
    assert box["y"] + box["height"] <= VIEWPORT["height"] + 0.5

    # The dialog itself must fill the scrollbar-EXCLUDED ICB. This, not the image box,
    # is what a `100vw` regression violates: with width:100vw the dialog spans 1280
    # while the ICB is ~1265, yet the height-capped image still centres inside it and
    # every image-box assertion above stays green.
    client_width = page.evaluate("() => document.documentElement.clientWidth")
    assert abs(_box(dialog)["width"] - client_width) <= 0.5

    # Centred in the VIEWPORT, not merely inside the dialog: an in-dialog check is
    # invariant to a fit-content dialog (both of its internal bands are 0) sitting
    # flush left.
    right_band = client_width - box["x"] - box["width"]
    assert abs(box["x"] - right_band) <= 1

    # Aspect ratio survives, so a stretched image is caught however an engine treats
    # grid stretching of a replaced element.
    assert abs(box["width"] / box["height"] - 1400 / 900) < 0.01


def test_nothing_but_the_image_is_visible(page, live_server, zoom_lesson, tmp_path):
    """checkVisibility() cannot express this -- a modal <dialog> makes the rest of the
    document inert, not unrendered, so the lesson article still reports visible. Assert
    occlusion two independent ways instead.
    """
    from PIL import Image

    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    img = page.locator(".imgzoom__img")
    box = _box(img)

    # (a) the resolved scrim colour, read from the token rather than hardcoded so a
    # design-pass retune cannot turn this red.
    token = page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--scrim-solid').trim()"
    )
    expected = [int(n) for n in token.split("(")[1].split(")")[0].split(",")[:3]]
    alpha = float(token.split(",")[-1].strip(") "))
    assert alpha >= 0.95, f"scrim must be near-opaque, got {token}"

    resolved = dialog.evaluate("el => getComputedStyle(el).backgroundColor")
    got = [int(n) for n in resolved.split("(")[1].split(")")[0].split(",")[:3]]
    assert all(abs(a - b) <= 12 for a, b in zip(got, expected, strict=True)), (
        resolved,
        token,
    )
    # Relative luminance, the third spec invariant: it is what catches a retune to a
    # LIGHT scrim that still matches its own token.
    lum = (0.2126 * got[0] + 0.7152 * got[1] + 0.0722 * got[2]) / 255
    assert lum < 0.05, f"scrim must be dark, luminance {lum:.3f}"
    # Asserting alpha alone would be untestable: the UA gives dialog an OPAQUE
    # `background-color: Canvas`, so deleting the author background leaves alpha at 1.0
    # and renders an opaque WHITE panel. Hence the channel check.

    # (b) pixel sampling in the letterbox bands beside the measured image box -- NOT
    # where the article text sits, which at this viewport is entirely behind the image.
    # Pin the assumption the coordinate mapping rests on rather than trusting a default.
    assert page.evaluate("() => devicePixelRatio") == 1
    assert box["x"] >= 6, f"letterbox band too narrow to sample: x={box['x']}"
    shot = tmp_path / "imgzoom-occlusion.png"  # never the repo root
    dialog.screenshot(path=str(shot))
    frame = Image.open(shot).convert("RGB")
    xs = [2, int(box["x"] / 2), int(box["x"]) - 3]
    ys = [2, int(box["height"] / 2), int(box["height"]) - 3]
    for x in xs:
        for y in ys:
            px = frame.getpixel((x, y))
            assert all(abs(a - b) <= 12 for a, b in zip(px, expected, strict=True)), (
                x,
                y,
                px,
            )
