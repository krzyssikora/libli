"""Playwright e2e for the light plate behind author-uploaded content images.

Almost the whole media corpus was authored for Open edX, which had no dark mode.
About 6% of the ~6.8k PNGs carry real alpha and are dark line art on transparency
(measured over a 200-file random sample). In dark mode their ink is composited
straight onto --surface-base (#1A1816) and disappears -- axes, tick labels and
gridlines vanish while only the saturated strokes survive, which is worse than
unreadable on a coordinate diagram.

The fix is a light plate painted behind the <img>. The `filter: invert(1)
hue-rotate(180deg)` trick that normally serves this case is ruled OUT for this
corpus and is not what is asserted here: these diagrams are colour-coded, the
baked-in labels are tinted to match their lines, and the surrounding prose refers
to the lines by colour -- inverting collapses a red line and a blue line to the
same magenta, so the diagram renders a statement that is false rather than merely
faint.

WHY A PIXEL TEST AND NOT A COMPUTED-STYLE ONE. Reading `backgroundColor` off the
<img> proves a declaration resolved, not that anything was painted. It cannot
distinguish the fix from a plate that is drawn but fully occluded, sized to zero,
or overpainted by a later rule -- and it says nothing about whether the ink
SURVIVED the treatment, which is the half of the spec a filter-based fix would
break. Sampling the rendered bitmap is the only assertion that covers both halves.

WHY LIGHT IS MEASURED TOO. The spec is not "dark mode is bright somewhere", it is
"the picture reads the same in both themes". A dark-only assertion passes just as
happily on a plate retuned to some arbitrary colour that no longer matches the
light ground. The two themes are captured from the same fixture and compared to
each other, so the light run is the control -- that A/B is the test, and a
single-theme measurement would not be one.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND -- a
background `-m e2e` sweep spawns runaway browsers.
"""

import os
from io import BytesIO

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 900}

# The fixture is a scale model of the real defect: a transparent ground carrying
# near-black ink. INK_FRAC is the side of the centred opaque square as a fraction
# of the image, chosen so that both sample regions below sit a wide margin clear
# of the ink edge -- a sampler landing on an antialiased boundary pixel is the one
# way this test could flake, and 0.40 vs the 0.08/0.50 samplers leaves ~22% of the
# image between each sampler and the nearest edge.
FIXTURE_SIZE = (400, 300)
INK_FRAC = 0.40
INK_RGB = (17, 17, 17)

# Fraction-of-the-box coordinates for the two samplers. CORNER_FRAC lands in the
# transparent margin, CENTRE_FRAC in the ink. Fractions, not pixels: in dark mode
# the plate's padding is inside the img's border box, so the picture is drawn a
# few px smaller than the box -- absolute coordinates would drift between themes
# for a reason unrelated to the invariant.
CORNER_FRAC = 0.08
CENTRE_FRAC = 0.50

# Channel tolerance for "the same colour", matching the imagezoom occlusion test.
TOL = 12


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    live_server's `_MediaFilesHandler` reads `settings.MEDIA_ROOT` per request to
    decide what `/media/<path>` serves, so pointing it at tmp_path is what makes a
    freshly created fixture image resolve at all -- not just tree hygiene. See the
    module docstring of tests/test_e2e_imagezoom.py for the full chain.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _transparent_ink_png():
    """A fully transparent PNG with a centred near-black opaque square.

    RGBA with a genuine alpha=0 ground, not white pixels: white would composite
    identically over any background and the test would pass on the broken build.
    """
    from PIL import Image
    from PIL import ImageDraw

    w, h = FIXTURE_SIZE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dw, dh = w * INK_FRAC, h * INK_FRAC
    ImageDraw.Draw(img).rectangle(
        [(w - dw) / 2, (h - dh) / 2, (w + dw) / 2, (h + dh) / 2],
        fill=(*INK_RGB, 255),
    )
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def plate_lesson(db, _isolated_media):
    """One lesson unit holding one transparent-ground ImageElement, plus a student.

    _isolated_media is listed explicitly rather than relied on as autouse ordering:
    the asset is written through the FileField at create() time, so a silent
    mis-ordering would drop the fixture PNG into the developer's real media/ tree.
    """
    from courses.models import ImageElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(
        course, filename="transparent-diagram.png", raw=_transparent_ink_png()
    )
    add_element(
        unit,
        ImageElement.objects.create(media=asset, alt="A labelled diagram", size="full"),
    )
    user = make_verified_user(
        username="plate-student",
        email="plate-student@test.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(course=course, student=user)
    return unit, user


def _login(page, live_server, user):
    # Scope to the login form: base.html renders one <button type="submit"
    # name="language"> per enabled language in the header, and page.click is
    # non-strict -- an unscoped click POSTs the language switcher instead.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _sample(page, live_server, unit, user, theme, tmp_path):
    """Re-open the lesson under `theme` and return (corner_rgb, centre_rgb).

    Expects an already-authenticated page: both tests sample the SAME fixture
    twice, and /accounts/login/ redirects an authed session away, so logging in
    per sample would leave the second call waiting on a form that is not there.

    The theme is switched on the User rather than through the header toggle: an
    authed User.theme is what bakes data-theme into the server-rendered <html>, so
    the reload below is correct on first paint with no client-side settle to race
    against.
    """
    user.theme = theme
    user.save(update_fields=["theme"])
    page.goto(_lesson_url(live_server, unit))

    # A mis-wired fixture must fail loudly rather than silently measure the wrong
    # theme twice and compare a page against itself.
    assert page.evaluate("document.documentElement.dataset.theme") == theme

    img = page.locator(".el--image img")
    img.wait_for()
    # state="visible" only needs a non-empty box, and an <img> whose bytes have
    # not arrived still gets one from its alt text -- so measuring here can catch
    # a decoded-nothing image and read the page ground through it in BOTH themes.
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=img.element_handle()
    )
    # The screenshot is in device pixels; every sampler below is a fraction of the
    # returned bitmap, so this only has to hold for the box/bitmap sizes to agree.
    assert page.evaluate("() => devicePixelRatio") == 1

    from PIL import Image

    shot = tmp_path / f"plate-{theme}.png"  # never the repo root
    img.screenshot(path=str(shot))
    frame = Image.open(shot).convert("RGB")
    w, h = frame.size
    corner = frame.getpixel((int(w * CORNER_FRAC), int(h * CORNER_FRAC)))
    centre = frame.getpixel((int(w * CENTRE_FRAC), int(h * CENTRE_FRAC)))
    return corner, centre


def _luminance(rgb):
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def test_transparent_image_reads_the_same_in_both_themes(
    page, live_server, plate_lesson, tmp_path
):
    """The whole spec, as one A/B: dark must render what light renders.

    Three independent things have to hold, and each is the mutant for one half of
    the fix:

    (a) the transparent ground paints LIGHT in dark mode -- without the plate it
        composites onto #1A1816 and this is the assertion that goes red;
    (b) the ink stays DARK in dark mode -- this is what a filter-based fix breaks,
        and what a plate painted over (rather than behind) the image would break;
    (c) both samples match the light theme's own values -- this is what catches a
        plate retuned to a colour that is bright but no longer the light ground,
        which (a) alone would happily accept.
    """
    unit, user = plate_lesson
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)

    light_corner, light_centre = _sample(
        page, live_server, unit, user, "light", tmp_path
    )
    dark_corner, dark_centre = _sample(page, live_server, unit, user, "dark", tmp_path)

    # Pin the control itself. If the light run were somehow dark-on-dark, (c) would
    # pass by both sides being equally wrong.
    assert _luminance(light_corner) > 0.7, (
        f"control is not a light ground: light corner {light_corner}"
    )
    assert _luminance(light_centre) < 0.15, (
        f"control has no dark ink: light centre {light_centre}"
    )

    # (a) + (b)
    assert _luminance(dark_corner) > 0.7, (
        f"transparent ground did not get a light plate in dark mode: {dark_corner}"
    )
    assert _luminance(dark_centre) < 0.15, (
        f"the image's own dark ink did not survive dark mode: {dark_centre}"
    )

    # (c)
    assert all(
        abs(a - b) <= TOL for a, b in zip(dark_corner, light_corner, strict=True)
    ), f"plate {dark_corner} does not match the light ground {light_corner}"
    assert all(
        abs(a - b) <= TOL for a, b in zip(dark_centre, light_centre, strict=True)
    ), f"ink renders differently in dark {dark_centre} vs light {light_centre}"


def test_plate_matches_the_light_page_ground(page, live_server, plate_lesson, tmp_path):
    """The plate is the LIGHT theme's --surface-base, read from the theme itself.

    Asserting the literal #F4F1EA here would pin the value twice and turn any
    design-pass retune of the page ground into a red test for no defect. What
    matters is the relationship: whatever a light-theme page is painted with is
    what a dark-theme transparent image must be composited onto, because that is
    the surface the corpus was authored against.
    """
    unit, user = plate_lesson

    user.theme = "light"
    user.save(update_fields=["theme"])
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    ground = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    expected = [int(n) for n in ground.split("(")[1].split(")")[0].split(",")[:3]]

    dark_corner, _ = _sample(page, live_server, unit, user, "dark", tmp_path)
    assert all(abs(a - b) <= TOL for a, b in zip(dark_corner, expected, strict=True)), (
        f"plate {dark_corner} is not the light page ground {expected}"
    )
