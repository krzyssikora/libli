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
