"""Playwright e2e: the dashboard "Last edited" card works at phone width.

Long unbroken titles must not push the dashboard into horizontal scroll, and a
tap on the card's label (which sits OUTSIDE the link) must still reach the live
lesson page through the stretched-link overlay. Marked e2e (run with -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_last_edited_card_at_phone_width_with_long_unbroken_titles(page, live_server):
    owner = make_verified_user(
        username="e2e_author", email="e2e_author@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Kurs" + "x" * 80, owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Lekcja" + "y" * 80,
        published=False,
    )
    ElementFactory(unit=unit)

    page.set_viewport_size({"width": 360, "height": 800})
    _login(page, live_server, "e2e_author")
    page.locator('[data-section="manage"]').wait_for()  # login lands on home
    page.locator("[data-last-edited]").wait_for()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    box = page.locator("[data-last-edited] .dash-recent__label").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    assert page.evaluate(
        "([x, y]) => !!document.elementFromPoint(x, y).closest('[data-last-edited] a')",
        [cx, cy],
    )
    page.mouse.click(cx, cy)
    page.locator(".lesson-unit__title").wait_for()
    page.locator(".draft-banner").wait_for()


@pytest.mark.django_db(transaction=True)
def test_last_edited_focus_ring_shows_for_keyboard_not_pointer(page, live_server):
    """The card's ring belongs to keyboard focus only. A pointer press focuses
    the link too (Chromium focuses links on mousedown), so a `:focus-within`
    ring would linger on the card after a tap -- e.g. when the PWA restores the
    dashboard from bfcache on Back."""
    owner = make_verified_user(
        username="e2e_focus", email="e2e_focus@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Algebra", owner=owner)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Macierze"
    )
    ring = (
        "() => getComputedStyle(document.querySelector('[data-last-edited]'))"
        ".outlineStyle"
    )
    focused_card_link = (
        "() => document.activeElement === "
        "document.querySelector('[data-last-edited] a')"
    )

    _login(page, live_server, "e2e_focus")
    page.locator("[data-last-edited]").wait_for()

    # Pointer: press on the card, then release elsewhere, so no click navigates.
    box = page.locator("[data-last-edited]").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    assert page.evaluate(focused_card_link)  # the press really focused the link
    assert page.evaluate(ring) == "none"
    page.mouse.move(0, 0)
    page.mouse.up()

    # Keyboard: Tab onto the card link from a cleared focus.
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    for _ in range(40):
        page.keyboard.press("Tab")
        if page.evaluate(focused_card_link):
            break
    assert page.evaluate(focused_card_link)
    assert page.evaluate(ring) == "solid"
