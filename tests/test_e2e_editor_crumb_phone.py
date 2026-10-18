"""Playwright e2e: the editor's crumb bar fits a phone.

The "View live" and "Media library" actions must wrap below the breadcrumb on a
narrow screen instead of pushing the page into horizontal scroll, and stay on
the breadcrumb's line on a wide one. Polish, because its labels are the longest
("Biblioteka multimediów"). Marked e2e (run with -m e2e)."""

import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect

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


def _open_editor(page, live_server, width):
    owner = make_verified_user(
        username="e2e_crumb", email="e2e_crumb@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="matematyka", owner=owner)
    section = ContentNodeFactory(
        course=course, kind="section", unit_type=None, title="Geometria analityczna 2"
    )
    group = ContentNodeFactory(
        course=course, parent=section, kind="section", unit_type=None, title="Zadania"
    )
    unit = ContentNodeFactory(
        course=course, parent=group, title="Zadanie 7", published=False
    )
    ElementFactory(unit=unit)

    page.set_viewport_size({"width": width, "height": 800})
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("e2e_crumb")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.locator('[data-section="manage"]').wait_for()  # login lands on home
    page.goto(
        live_server.url
        + reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    # The header switch POSTs the UI language and reloads; the long Polish
    # label is the one under test.
    page.locator("form.lang-switch button[value='pl']").first.click()
    expect(page.locator(".editor-crumb__media")).to_contain_text(
        "Biblioteka multimediów"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [360, 412])
def test_crumb_actions_wrap_without_horizontal_scroll_on_a_phone(
    page, live_server, width
):
    _open_editor(page, live_server, width)

    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    for sel in (".editor-crumb__live", ".editor-crumb__media"):
        box = page.locator(sel).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width, (sel, box)
    # The actions sit BELOW the breadcrumb, not squeezed beside it.
    path = page.locator(".editor-crumb__path").bounding_box()
    live = page.locator(".editor-crumb__live").bounding_box()
    assert live["y"] >= path["y"] + path["height"] - 1, (path, live)


@pytest.mark.django_db(transaction=True)
def test_crumb_actions_share_the_breadcrumb_line_on_desktop(page, live_server):
    _open_editor(page, live_server, 1280)

    path = page.locator(".editor-crumb__path").bounding_box()
    for sel in (".editor-crumb__live", ".editor-crumb__media"):
        box = page.locator(sel).bounding_box()
        assert box["y"] < path["y"] + path["height"], (sel, path, box)
        assert box["x"] > path["x"] + path["width"] - 1, (sel, path, box)
