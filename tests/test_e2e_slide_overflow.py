"""A slide that does not fit its stage must SAY so, and a tall window must not
waste its height.

The stage is deliberately a fixed height (the deck's footer bar has to sit at a
constant y on every slide), so a tall slide is clipped. Two things follow:

  * the clip has to be signalled. A clipped table shows half a column, but a
    slide can end on the whitespace between two blocks and read as finished --
    the reported case cut a "Sprawdz" button in half, and half a button is a
    better hint than most slides get. `.scroll-y` shades whichever edge has
    content beyond it, the block-axis twin of `.scroll-x`.

  * the fixed height should not be wasteful. `clamp(360px, 62vh, 640px)` threw
    away 176px of viewport on a 1255px-tall window while the slide clipped by
    33px; the cap is now 900px so the 62vh term governs there instead.

Marked e2e (run with `-m e2e`).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, *, tall_first=True):
    """Two slides: the first optionally taller than any stage, the second tiny."""
    from courses.models import SlideBreakElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    for i in range(20 if tall_first else 1):
        add_element(
            unit,
            TextElement.objects.create(body=f"<p>Akapit {i} " + "slowo " * 60 + "</p>"),
        )
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="<p>krotka plansza</p>"))
    EnrollmentFactory(student=student, course=course)
    return unit


def _goto(page, live_server, unit, width=1280, height=800):
    from django.urls import reverse

    page.set_viewport_size({"width": width, "height": height})
    page.goto(
        live_server.url
        + reverse(
            "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    )
    page.wait_for_selector(".slideshow-stage")
    # The affordance is armed by slideshow.js after it builds the deck.
    page.wait_for_function(
        "() => document.querySelector('.slideshow-stage').dataset.scrollYReady === '1'"
    )


def _stage(page):
    return page.locator(".slideshow-stage")


@pytest.mark.django_db(transaction=True)
def test_clipped_slide_shades_its_bottom_edge(page, live_server):
    unit = _seed("sl_shade")
    _login(page, live_server, "sl_shade")
    _goto(page, live_server, unit)

    # Premise: the slide really is clipped.
    assert (
        page.evaluate(
            """() => {
             const s = document.querySelector('.slide.is-active');
             return s.scrollHeight - s.clientHeight;
           }"""
        )
        > 50
    )

    stage = _stage(page)
    assert "is-scroll-bottom" in stage.get_attribute("class"), (
        "a clipped slide gave the student no hint that content continues below"
    )
    assert "is-scroll-top" not in stage.get_attribute("class"), (
        "the top edge is shaded while sitting at scroll position 0"
    )
    # The shade must be PAINTED, not merely classed. Poll rather than read once:
    # the opacity is transitioned (.15s), so a single read lands mid-fade.
    page.wait_for_function(
        """() => getComputedStyle(
             document.querySelector('.slideshow-stage'), '::after').opacity === '1'"""
    )


@pytest.mark.django_db(transaction=True)
def test_edges_swap_when_the_slide_is_scrolled_to_the_bottom(page, live_server):
    unit = _seed("sl_swap")
    _login(page, live_server, "sl_swap")
    _goto(page, live_server, unit)

    page.evaluate(
        """() => {
             const s = document.querySelector('.slide.is-active');
             s.scrollTop = s.scrollHeight;
           }"""
    )
    page.wait_for_function(
        "() => document.querySelector('.slideshow-stage')"
        ".classList.contains('is-scroll-top')"
    )
    assert "is-scroll-bottom" not in _stage(page).get_attribute("class"), (
        "the bottom edge stays shaded on a slide scrolled fully down"
    )


@pytest.mark.django_db(transaction=True)
def test_affordance_follows_the_active_slide(page, live_server):
    """The stage holds every slide and swaps which one renders, so the affordance
    must re-resolve the scroller rather than measure the one it started with."""
    unit = _seed("sl_next")
    _login(page, live_server, "sl_next")
    _goto(page, live_server, unit)
    assert "is-scroll-bottom" in _stage(page).get_attribute("class")

    page.get_by_role("button", name="Next slide").click()
    page.wait_for_function(
        "() => !document.querySelector('.slideshow-stage')"
        ".classList.contains('is-scroll-bottom')"
    )
    assert "is-scroll-top" not in _stage(page).get_attribute("class"), (
        "a short slide is shaded as though it had content above the fold"
    )


@pytest.mark.django_db(transaction=True)
def test_a_short_slide_shades_neither_edge(page, live_server):
    unit = _seed("sl_short", tall_first=False)
    _login(page, live_server, "sl_short")
    _goto(page, live_server, unit)

    cls = _stage(page).get_attribute("class")
    assert "is-scroll-top" not in cls and "is-scroll-bottom" not in cls, cls


@pytest.mark.django_db(transaction=True)
def test_the_shade_never_swallows_a_click(page, live_server):
    """pointer-events:none — a control under a lit edge must still be clickable."""
    unit = _seed("sl_click")
    _login(page, live_server, "sl_click")
    _goto(page, live_server, unit)
    assert "is-scroll-bottom" in _stage(page).get_attribute("class")

    # elementFromPoint 4px above the stage's bottom edge, i.e. inside the shade,
    # must resolve to the slide content rather than the stage itself.
    hit = page.evaluate(
        """() => {
             const st = document.querySelector('.slideshow-stage');
             const r = st.getBoundingClientRect();
             const el = document.elementFromPoint(r.left + r.width / 2, r.bottom - 4);
             return el ? el.tagName + '.' + el.className : null;
           }"""
    )
    assert hit and "slideshow-stage" not in hit, (
        f"the edge shade is intercepting the pointer: hit {hit}"
    )


@pytest.mark.django_db(transaction=True)
def test_a_tall_window_is_not_capped_at_640px(page, live_server):
    """The reported window: 640px of stage under 1255px of viewport left 176px of
    page empty while the slide clipped. 62vh must govern up to a 900px ceiling."""
    unit = _seed("sl_tall")
    _login(page, live_server, "sl_tall")
    _goto(page, live_server, unit, width=987, height=1255)

    h = page.evaluate(
        "() => Math.round("
        "document.querySelector('.slideshow-stage').getBoundingClientRect().height)"
    )
    assert h == pytest.approx(0.62 * 1255, abs=2), (
        f"stage is {h}px on a 1255px viewport; expected the 62vh term to govern"
    )
    # ...and the deck plus the unit footer still fit above the fold, which is the
    # whole point of not simply removing the cap.
    assert page.evaluate(
        """() => {
             const de = document.documentElement;
             return de.scrollHeight <= de.clientHeight + 1;
           }"""
    ), "the taller stage pushed the unit footer below the fold"
