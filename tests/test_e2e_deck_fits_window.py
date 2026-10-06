"""A first-time student must SEE the deck's own Prev/Next bar without scrolling.

The reported window (1900x916, dark, quiz of five one-line questions): the stage
was `clamp(360px, 62vh, 900px)` tall, so the deck's dots + arrows sat under the
sticky unit footer. The only "next" on screen was the unit footer's Next, which
leaves the quiz -- a student answering question 1 and pressing it never saw
questions 2-5. slideshow.js now fits the stage to the window: the deck's bar ends
just above the sticky unit footer.

On the last slide of a quiz the deck's Next arrow becomes "Finish quiz" -- the
form used to sit BELOW the deck, i.e. always below the fold once the deck fills
the window.

Marked e2e (run with `-m e2e`).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user
from tests.factories import seed_slideshow_unit

pytestmark = pytest.mark.e2e

# Bar fully above the footer, and not floating far above it either: the gap is
# the deck's own breathing room, not wasted window.
_MAX_GAP = 48


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


def _seed(username, unit_type="quiz"):
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = seed_slideshow_unit(
        course, unit_type, layout=["q", "brk", "q", "brk", "q", "brk", "q", "brk", "q"]
    )
    EnrollmentFactory(student=student, course=course)
    return unit


def _goto(page, live_server, unit, width, height):
    from django.urls import reverse

    name = "courses:quiz_unit" if unit.unit_type == "quiz" else "courses:lesson_unit"
    page.set_viewport_size({"width": width, "height": height})
    page.goto(
        live_server.url
        + reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    )
    page.wait_for_selector(".slideshow-bar")


def _gap(page):
    """Footer top minus the deck bar's bottom, at the page top (no scrolling)."""
    return page.evaluate(
        """() => {
             window.scrollTo(0, 0);
             const bar = document.querySelector('.slideshow-bar')
                           .getBoundingClientRect();
             const foot = document.querySelector('.unit-foot').getBoundingClientRect();
             return Math.round(foot.top - bar.bottom);
           }"""
    )


def _assert_bar_fits(page, where):
    # Poll: the fit runs after layout settles (fonts, KaTeX titles), so read the
    # condition until true rather than sampling one frame.
    deadline = 50
    gap = None
    for _ in range(deadline):
        gap = _gap(page)
        if 0 <= gap <= _MAX_GAP:
            return
        page.wait_for_timeout(100)
    raise AssertionError(
        f"{where}: deck bar ends {gap}px above the sticky unit footer "
        f"(negative = hidden under it); expected 0..{_MAX_GAP}"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("unit_type", ["quiz", "lesson"])
def test_deck_bar_visible_without_scrolling_in_reported_window(
    page, live_server, unit_type
):
    unit = _seed(f"fit_{unit_type}", unit_type)
    _login(page, live_server, f"fit_{unit_type}")
    _goto(page, live_server, unit, 1900, 916)
    _assert_bar_fits(page, f"{unit_type} at 1900x916")


@pytest.mark.django_db(transaction=True)
def test_deck_refits_when_the_window_resizes(page, live_server):
    unit = _seed("fit_resize")
    _login(page, live_server, "fit_resize")
    _goto(page, live_server, unit, 1900, 916)
    _assert_bar_fits(page, "before resize")
    page.set_viewport_size({"width": 1400, "height": 1100})
    _assert_bar_fits(page, "after growing to 1400x1100")
    page.set_viewport_size({"width": 1280, "height": 760})
    _assert_bar_fits(page, "after shrinking to 1280x760")


@pytest.mark.django_db(transaction=True)
def test_finish_replaces_the_next_arrow_on_the_last_slide(page, live_server):
    unit = _seed("fit_finish")
    _login(page, live_server, "fit_finish")
    _goto(page, live_server, unit, 1900, 916)
    bar = page.locator(".slideshow-bar")
    arrow = bar.get_by_role("button", name="Next slide")
    finish = page.locator("[data-finish-btn]")

    # The Finish form lives IN the deck bar, not below the deck.
    assert page.locator(".slideshow-bar [data-quiz-finish]").count() == 1
    expect(finish).to_be_hidden()
    expect(arrow).to_be_visible()
    for _ in range(4):
        arrow.click()
    expect(finish).to_be_visible()
    expect(arrow).to_be_hidden()
    _assert_bar_fits(page, "last slide")
    # Back off the last slide: the arrow returns, Finish goes away again.
    bar.get_by_role("button", name="Previous slide").click()
    expect(arrow).to_be_visible()
    expect(finish).to_be_hidden()

    # It still finishes the quiz (quiz.js's confirm + flush handler moved with it).
    arrow.click()
    page.once("dialog", lambda d: d.accept())
    finish.click()
    page.wait_for_url("**/results/**")
