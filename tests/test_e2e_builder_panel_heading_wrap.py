"""A long unbroken word in the detail panel's heading wraps instead of escaping.

`.builder__panel .panel h2` carries `overflow-wrap: anywhere`. Without it the
60-character LONG_WORD in a unit title makes the phone bottom sheet scroll
sideways, and on desktop the panel clips the word. The course panel is a
flex column with `align-items: flex-start`, so its h2 is sized from its
min-content -- only `anywhere` (not `break-word`) shrinks that. Marked e2e."""

import os

import pytest
from playwright.sync_api import expect

from tests.helpers_builder_phone import LONG_WORD
from tests.helpers_builder_phone import assert_desktop
from tests.helpers_builder_phone import assert_phone
from tests.helpers_builder_phone import builder_url
from tests.helpers_builder_phone import login
from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import phone_context
from tests.helpers_builder_phone import seed_course

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


_GEOMETRY_JS = """(scope) => {
  const box = document.querySelector(scope);
  const h2 = box.querySelector('.panel h2');
  const b = box.getBoundingClientRect();
  const h = h2.getBoundingClientRect();
  return {
    boxScroll: box.scrollWidth, boxClient: box.clientWidth,
    h2Scroll: h2.scrollWidth, h2Client: h2.clientWidth,
    h2Right: h.right, boxRight: b.right,
    docScroll: document.documentElement.scrollWidth,
    docClient: document.documentElement.clientWidth,
  };
}"""


def _assert_fits(geo):
    assert geo["boxScroll"] <= geo["boxClient"], geo
    assert geo["h2Scroll"] <= geo["h2Client"] + 1, geo
    assert geo["h2Right"] <= geo["boxRight"] + 1, geo
    assert geo["docScroll"] <= geo["docClient"], geo


def _long_word_course(slug):
    seeded = seed_course(slug=slug, long_title=True)
    course = seeded["course"]
    course.title = f"Kurs {LONG_WORD} geometrii"
    course.save(update_fields=["title"])
    return seeded


@pytest.mark.django_db(transaction=True)
def test_phone_sheet_wraps_long_heading_word(browser, live_server):
    make_pa_user("pa")
    seeded = _long_word_course("phone-wrap")
    long_unit = seeded["lessons"][0]
    context = phone_context(browser)
    page = context.new_page()
    try:
        login(page, live_server, "pa")
        page.goto(builder_url(live_server, seeded["course"]))
        page.wait_for_selector(".builder")
        assert_phone(page)

        page.locator(f"#node-{long_unit.pk} > form.tree__rowhead > .tree__ptitle").tap()
        panel = page.locator(f'[data-panel] .panel[data-panel-for="{long_unit.pk}"]')
        expect(panel.locator("h2")).to_contain_text(LONG_WORD)
        _assert_fits(page.evaluate(_GEOMETRY_JS, "[data-sheet-body]"))

        page.locator("[data-sheet-close]").tap()
        expect(page.locator("[data-sheet].is-open")).to_have_count(0)
        box = page.locator("[data-sheet-course]").bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        course_panel = page.locator('[data-panel] .panel[data-panel-for="course"]')
        expect(course_panel.locator("h2")).to_contain_text(LONG_WORD)
        _assert_fits(page.evaluate(_GEOMETRY_JS, "[data-sheet-body]"))
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_desktop_panel_does_not_clip_long_heading_word(page, live_server):
    make_pa_user("pa")
    seeded = _long_word_course("desk-wrap")
    long_unit = seeded["lessons"][0]
    page.set_viewport_size({"width": 1280, "height": 900})
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, seeded["course"]))
    page.wait_for_selector(".builder")
    assert_desktop(page)

    course_panel = page.locator('[data-panel] .panel[data-panel-for="course"]')
    expect(course_panel.locator("h2")).to_contain_text(LONG_WORD)
    _assert_fits(page.evaluate(_GEOMETRY_JS, "[data-panel]"))

    page.locator(f"#node-{long_unit.pk} > form.tree__rowhead > .tree__title").click()
    panel = page.locator(f'[data-panel] .panel[data-panel-for="{long_unit.pk}"]')
    expect(panel.locator("h2")).to_contain_text(LONG_WORD)
    _assert_fits(page.evaluate(_GEOMETRY_JS, "[data-panel]"))
