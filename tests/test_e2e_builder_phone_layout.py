"""Phone-layout geometry for the builder tree (Task 2): rows, header, sheet chrome.

Real phone contexts (touch + mobile + coarse pointer), so the phone media query is
the one under test, never a forced class. Marked e2e -- foreground."""

import os

import pytest

from tests.helpers_builder_phone import assert_phone
from tests.helpers_builder_phone import builder_url
from tests.helpers_builder_phone import cdp_touch_scroll
from tests.helpers_builder_phone import login
from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import phone_context
from tests.helpers_builder_phone import seed_course

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open(browser, live_server, course, **ctx):
    context = phone_context(browser, **ctx)
    page = context.new_page()
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, course))
    page.wait_for_selector(".builder")
    return context, page


# Per-row visibility of the pieces the phone layout swaps, for every row.
_ROW_STATE_JS = """() => {
  const vis = (el) => !!el && (el.checkVisibility ? el.checkVisibility()
                                                  : el.offsetParent !== null);
  return [...document.querySelectorAll('li.tree__row')].map((row) => {
    const form = row.querySelector(':scope > form.tree__rowhead');
    return {
      pk: row.dataset.node,
      ptitle: vis(form.querySelector(':scope > .tree__ptitle')),
      more: vis(form.querySelector(':scope > .tree__more')),
      input: vis(form.querySelector(':scope > input.tree__title')),
      cluster: vis(form.querySelector(':scope > .tree__cluster')),
      grip: vis(form.querySelector('.ica--grip')),
    };
  });
}"""

# Geometry of one row's phone title: height in lines, overflow, clamp.
_PTITLE_JS = """(pk) => {
  const el = document.querySelector(`#node-${pk} > form > .tree__ptitle`);
  const clampEl = el.querySelector('.tree__ptitle-text') || el;
  const cs = getComputedStyle(clampEl);
  const rects = [...clampEl.getClientRects()];
  const height = rects.reduce((h, r) => Math.max(h, r.bottom), 0)
               - rects.reduce((t, r) => Math.min(t, r.top), Infinity);
  return {
    height, lineHeight: parseFloat(cs.lineHeight), clamp: cs.webkitLineClamp,
    scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
  };
}"""


# A row's phone-title width vs the rendered width of its longest word, measured
# with a temporary nowrap span in the title's own font.
_WORD_FIT_JS = """(pk) => {
  const el = document.querySelector(`#node-${pk} > form > .tree__ptitle`);
  const word = el.textContent.trim().split(/\\s+/)
    .reduce((a, b) => (b.length > a.length ? b : a), "");
  const probe = document.createElement("span");
  probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap";
  probe.textContent = word;
  el.appendChild(probe);
  const wordWidth = probe.getBoundingClientRect().width;
  probe.remove();
  return {pk, text: el.textContent, width: el.clientWidth, word: wordWidth};
}"""


@pytest.mark.django_db(transaction=True)
def test_portrait_rows(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course(long_title=True)
    context, page = _open(browser, live_server, seeded["course"])
    try:
        assert_phone(page)
        assert not page.locator("[data-row-menu]").is_visible()
        assert not page.locator("[data-toast]").is_visible()

        rows = page.evaluate(_ROW_STATE_JS)
        assert len(rows) >= 9
        for row in rows:
            assert row == {
                "pk": row["pk"],
                "ptitle": True,
                "more": True,
                "input": False,
                "cluster": False,
                "grip": False,
            }, row

        badge = page.locator(f"#node-{seeded['part'].pk} > form > .tree__badge")
        assert badge.bounding_box()["width"] <= 26

        long_pk = seeded["lessons"][0].pk
        geo = page.evaluate(_PTITLE_JS, long_pk)
        assert geo["clamp"] == "2", geo
        assert 1.8 * geo["lineHeight"] <= geo["height"] <= 2.3 * geo["lineHeight"], geo
        assert geo["scrollWidth"] <= geo["clientWidth"] + 1, geo

        form = page.locator(f"#node-{long_pk} > form")
        ptitle_x = form.locator(":scope > .tree__ptitle").bounding_box()["x"]
        flags = form.locator(":scope > .tree__flag")
        assert flags.count() == 2
        for i in range(flags.count()):
            assert flags.nth(i).bounding_box()["x"] > ptitle_x

        # Deepest rows (part > chapter > section > unit) stay readable: a floor on
        # the title width, and no row's title narrower than its longest word, so
        # "Przekształcenia" (section) / "przekształcenie" (unit) never break mid-word.
        deep = [seeded["section"], *seeded["lessons"][1:], seeded["quiz"]]
        for node in deep:
            fit = page.evaluate(_WORD_FIT_JS, node.pk)
            assert fit["width"] >= 160, fit
            assert fit["width"] >= fit["word"], fit
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_landscape_geometry(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course(long_title=True)
    context, page = _open(
        browser, live_server, seeded["course"], orientation="landscape"
    )
    try:
        assert_phone(page)

        def ptitle_width(node):
            sel = f"#node-{node.pk} > form > .tree__ptitle"
            return page.locator(sel).bounding_box()["width"]

        vw, vh = page.evaluate("() => [innerWidth, innerHeight]")
        # Part (level 1) and a unit at part > chapter > section > unit (level 4).
        assert ptitle_width(seeded["part"]) > 0.60 * vw
        assert ptitle_width(seeded["lessons"][1]) > 0.45 * vw

        head = page.locator("header.manage__head").bounding_box()
        assert head["height"] <= 0.25 * vh, head
        h1 = page.evaluate(
            """() => { const h = document.querySelector('.builder__title');
                 return [h.getBoundingClientRect().height,
                         parseFloat(getComputedStyle(h).lineHeight)]; }"""
        )
        assert h1[0] <= 1.5 * h1[1], h1

        kurs = page.locator("[data-sheet-course]").bounding_box()
        filt = page.locator("form.builder__filter").bounding_box()
        assert abs(kurs["y"] - filt["y"]) <= 4, (kurs, filt)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_sticky_header(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course(extra_lessons=40)
    context, page = _open(browser, live_server, seeded["course"])
    try:
        assert_phone(page)
        for _ in range(10):
            if page.evaluate("() => window.scrollY") > 600:
                break
            cdp_touch_scroll(page, 200, 700, 200)
            page.wait_for_timeout(150)
        assert page.evaluate("() => window.scrollY") > 600
        top, bg = page.evaluate(
            """() => { const h = document.querySelector('header.manage__head');
                 return [h.getBoundingClientRect().top,
                         getComputedStyle(h).backgroundColor]; }"""
        )
        assert abs(top) <= 1, top
        # rgb(...) is opaque; rgba(..., a) / color(... / a) carries an alpha < 1.
        assert bg.startswith("rgb(") and "/" not in bg, bg
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_without_js_keeps_desktop_rows(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(
        browser, live_server, seeded["course"], java_script_enabled=False
    )
    try:
        assert_phone(page)
        has_js = "() => document.documentElement.classList.contains('js')"
        assert page.evaluate(has_js) is False
        form = page.locator(f"#node-{seeded['lessons'][0].pk} > form")
        assert form.locator(":scope > input.tree__title").is_visible()
        assert not form.locator(":scope > .tree__ptitle").is_visible()
        assert not form.locator(":scope > .tree__more").is_visible()
        assert form.locator(":scope > .tree__cluster").is_visible()
    finally:
        context.close()
