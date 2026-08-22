"""Playwright e2e for .embed-frame's three width bounds (never overflow the column,
never enlarge past the authored size, never grow taller than the window).

MEASURED, not string-matched. A CSS test that greps courses.css for `85dvh` passes on
a build where the rule never applies -- wrong selector, unset custom property, a
min() whose arguments are in an order that makes one inert. Every assertion here
reads a real getBoundingClientRect() from a real student unit page.

The fixtures are the two REAL shapes from the mat-pp database that motivated the
change: 450x780 (element 31, the most extreme portrait of the 139 sized embeds --
1123px tall in the 648px column, 1512px in the 872px collapsed one) and 350x391
(element 106, small enough that the old unconditional `width: 100%` blew it up 1.85x).

Every external request is aborted. The wrapper's geometry is pure CSS and does not
depend on the provider ever answering; letting the real geogebra.org/youtube.com
loads through would only add latency and flake. Modeled on
tests/test_e2e_html_element.py (seed + login idiom); marked e2e (run with -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# The dvh share and the floor in courses.css's .embed-frame--sized rule. Restated
# rather than parsed: these tests exist to pin the POLICY, so a change to the CSS
# should turn them red and be re-confirmed here deliberately.
VIEWPORT_SHARE = 0.85
FLOOR_PX = 320

PORTRAIT = (450, 780)  # element 31
SMALL = (350, 391)  # element 106


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


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


def _seed(username, slug):
    """A lesson unit carrying, in order: the portrait embed, the small embed, and a
    dimensionless one. The third is the regression guard -- it must keep the
    historical full-width 16:9 geometry that the --sized modifier does not touch."""
    from courses.models import Element
    from courses.models import IframeElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = _make_pa_user(username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Embeds"
    )
    for name, (w, h) in (("portrait", PORTRAIT), ("small", SMALL)):
        Element.objects.create(
            unit=unit,
            content_object=IframeElement.objects.create(
                url=f"https://www.geogebra.org/material/iframe/id/{name}",
                title=name,
                width=w,
                height=h,
            ),
        )
    Element.objects.create(
        unit=unit,
        content_object=IframeElement.objects.create(
            url="https://www.youtube.com/embed/dQw4w9WgXcQ", title="unsized"
        ),
    )
    return course, unit


def _open(page, live_server, username, slug, width, height):
    course, unit = _seed(username, slug)
    page.set_viewport_size({"width": width, "height": height})
    # No provider is ever contacted; see the module docstring.
    page.route("**://www.geogebra.org/**", lambda route: route.abort())
    page.route("**://www.youtube.com/**", lambda route: route.abort())
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/courses/{slug}/u/{unit.pk}/", wait_until="domcontentloaded"
    )
    page.wait_for_selector(".embed-frame")
    return course, unit


def _boxes(page):
    """[{w, h, col}] for every .embed-frame, col being the column it sits in."""
    return page.evaluate(
        """() => [...document.querySelectorAll('.embed-frame')].map(e => {
            const r = e.getBoundingClientRect();
            return {
              w: r.width,
              h: r.height,
              col: e.parentElement.getBoundingClientRect().width,
            };
        })"""
    )


@pytest.mark.django_db(transaction=True)
def test_portrait_embed_never_grows_taller_than_the_window(live_server, page):
    # THE reported defect. At 1280x800 the old rule gave the 450x780 applet the full
    # 648px column and a 1123px height -- 1.4x the window.
    _open(page, live_server, "ef1", "efslug1", 1280, 800)
    portrait = _boxes(page)[0]

    assert portrait["h"] <= VIEWPORT_SHARE * 800 + 1, (
        f"portrait frame is {portrait['h']}px tall in an 800px window "
        f"(cap {VIEWPORT_SHARE * 800}px); box={portrait}"
    )
    # Not vacuous: a collapsed frame would satisfy the cap above trivially.
    assert portrait["w"] > FLOOR_PX - 1, f"frame collapsed: {portrait}"


@pytest.mark.django_db(transaction=True)
def test_no_embed_is_enlarged_past_the_size_it_was_authored_at(live_server, page):
    # A window tall enough that the viewport bound cannot bind (0.85*1400*450/780 =
    # 686px, well past both natural widths), so this measures the natural-size bound
    # ALONE. Old build: both render at the 648px column.
    _open(page, live_server, "ef2", "efslug2", 1280, 1400)
    portrait, small, _ = _boxes(page)

    assert portrait["col"] > PORTRAIT[0], (
        f"column {portrait['col']} must exceed the natural width for this to measure "
        "anything"
    )
    assert abs(portrait["w"] - PORTRAIT[0]) <= 1, f"portrait: {portrait}"
    assert abs(small["w"] - SMALL[0]) <= 1, f"small: {small}"


@pytest.mark.django_db(transaction=True)
def test_a_squat_window_shrinks_the_frame_only_to_the_operable_floor(live_server, page):
    # Phone held sideways. The viewport bound alone would give 0.85*380*450/780 =
    # 186px, at which an applet's sliders and buttons stop being operable; the floor
    # holds it at 320 and the page scrolls instead. EQUALITY, not >=: a build that
    # dropped the viewport bound entirely would also pass a >= check here.
    _open(page, live_server, "ef3", "efslug3", 900, 380)
    portrait = _boxes(page)[0]

    assert abs(portrait["w"] - FLOOR_PX) <= 1, (
        f"expected the {FLOOR_PX}px floor to bind in a 380px-tall window; got "
        f"{portrait}"
    )


@pytest.mark.django_db(transaction=True)
def test_the_column_still_bounds_the_frame_on_a_phone(live_server, page):
    # 390x844 is chosen so BOTH other bounds exceed the column (natural 450, viewport
    # 0.85*844*450/780 = 414, column ~326). That makes this a real test of `100%`
    # staying inside the min() -- at a shorter phone viewport the dvh bound would
    # mask its removal.
    _open(page, live_server, "ef4", "efslug4", 390, 844)
    portrait = _boxes(page)[0]

    assert portrait["col"] < PORTRAIT[0], (
        f"column {portrait['col']} must be narrower than the natural width for this "
        "to measure anything"
    )
    assert portrait["w"] <= portrait["col"] + 1, (
        f"frame overflows its column: {portrait}"
    )


@pytest.mark.django_db(transaction=True)
def test_a_dimensionless_embed_keeps_its_full_width_16_9_geometry(live_server, page):
    # The untouched path. --sized is absent, so none of the three bounds apply and
    # this embed must render exactly as it did before the change. Goes red if the
    # modifier ever leaks onto a frame with no dimensions.
    _open(page, live_server, "ef5", "efslug5", 1280, 800)
    unsized = _boxes(page)[2]

    assert abs(unsized["w"] - unsized["col"]) <= 1, f"not full width: {unsized}"
    assert abs(unsized["h"] - unsized["col"] * 9 / 16) <= 2, f"not 16:9: {unsized}"
    # The geometry above CANNOT catch a leaked modifier on its own: with --embed-w
    # unset, calc(var(--embed-w) * 1px) makes the whole width declaration invalid at
    # computed-value time, so width falls back to auto -- which for this block fills
    # the column and measures identically to the correct build. Asserting the class
    # is absent is what actually makes this test falsifiable.
    assert (
        page.evaluate(
            "() => document.querySelectorAll('.embed-frame')[2]"
            ".classList.contains('embed-frame--sized')"
        )
        is False
    )
