"""Desktop guard for the builder phone layout (Task 1).

A desktop MOUSE window between 720 and 960 px wide must keep today's layout: the
phone scaffolding is server-rendered everywhere, so this pins that it stays
layout-neutral (display: contents wrappers, display: none phone pieces) and that
every desktop behaviour it could disturb still works. Marked e2e -- foreground."""

import os
import re

import pytest

from tests.helpers_builder_phone import assert_desktop
from tests.helpers_builder_phone import builder_url
from tests.helpers_builder_phone import login
from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import seed_course

pytestmark = pytest.mark.e2e

PANEL_RE = re.compile(r"/build/node/(\d+)/$")

# Tabbable elements in document order (no positive tabindex exists in the builder).
_TAB_INDEX_JS = """([fromSel, toSel]) => {
  const all = [...document.querySelectorAll(
    'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]'
  )].filter(el => !el.disabled && el.tabIndex >= 0 && !el.closest('[inert]')
                  && el.checkVisibility());
  return all.indexOf(document.querySelector(toSel))
       - all.indexOf(document.querySelector(fromSel));
}"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_desktop_window_keeps_desktop_layout(page, live_server):
    make_pa_user("pa")
    # 60, not the plan's 30: measured, 30 extra rows give a 1,762 px document at this
    # viewport -- a 962 px maximum scrollY, so `scrollY > 1000` below could never pass.
    seeded = seed_course(extra_lessons=60)
    lesson0, lesson1 = seeded["lessons"][0], seeded["lessons"][1]

    page.set_viewport_size({"width": 945, "height": 800})
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, seeded["course"]))
    page.wait_for_selector(".builder")
    assert_desktop(page)

    # Phone-only pieces stay hidden; the desktop title input shows.
    for sel in (
        ".tree__ptitle",
        ".tree__more",
        ".builder__kurs",
        "[data-sheet-grab]",
        "[data-toast]",
    ):
        loc = page.locator(sel)
        assert loc.count() >= 1, sel
        for i in range(loc.count()):
            assert not loc.nth(i).is_visible(), f"{sel} #{i} is visible on desktop"
    assert page.locator("input.tree__title").first.is_visible()

    # Two columns, no new grid row: the panel is the second grid item, beside the tree.
    tree_box = page.locator(".builder__tree").bounding_box()
    panel_box = page.locator("[data-panel]").bounding_box()
    assert panel_box["x"] > tree_box["x"] + tree_box["width"]
    cols = page.evaluate(
        "() => getComputedStyle(document.querySelector('.builder'))"
        ".gridTemplateColumns.split(' ').length"
    )
    assert cols == 2
    assert abs(panel_box["y"] - tree_box["y"]) <= 2

    # Sticky still works once the long tree is scrolled.
    page.mouse.move(200, 400)
    page.mouse.wheel(0, 2500)
    page.wait_for_function("() => window.scrollY > 1000")
    top = page.evaluate(
        "() => document.querySelector('[data-panel]').getBoundingClientRect().top"
    )
    assert 0 <= top <= 40, f"panel top {top} -- sticky lost"

    # No phone-only semantics leak onto the desktop panel.
    attrs = page.evaluate(
        """() => {
      const s = document.querySelector('[data-sheet]');
      const p = document.querySelector('[data-panel]');
      return {sheetInert: s.hasAttribute('inert'), panelInert: p.hasAttribute('inert'),
              role: s.getAttribute('role'), modal: s.getAttribute('aria-modal'),
              vis: getComputedStyle(p).visibility};
    }"""
    )
    assert attrs == {
        "sheetInert": False,
        "panelInert": False,
        "role": None,
        "modal": None,
        "vis": "visible",
    }

    # Tab from the last row's last control reaches the panel.
    page.locator("li.tree__row").last.locator("a[data-delete]").focus()
    reached = False
    for _ in range(20):
        page.keyboard.press("Tab")
        if page.evaluate("() => !!document.activeElement.closest('[data-panel]')"):
            reached = True
            break
    assert reached, "Tab from the tree never reached the panel"

    # Drag intact: every grip is visible and draggable.
    grips = page.locator(".ica--grip")
    assert grips.count() == page.locator("li.tree__row").count()
    for i in range(grips.count()):
        assert grips.nth(i).is_visible()
        assert grips.nth(i).get_attribute("draggable") == "true"

    # Rename-in-place + focus loader intact: a click on a title focuses it and loads
    # the unit panel.
    page.evaluate("() => window.scrollTo(0, 0)")
    title0 = page.locator(f"#node-{lesson0.pk} > form .tree__title")
    title0.click()
    page.wait_for_selector(f'[data-panel] .panel[data-panel-for="{lesson0.pk}"]')
    assert title0.evaluate("el => el === document.activeElement")

    # Tab debounce intact: tabbing across a row issues ONE fetch, for the row landed on.
    title1_sel = f"#node-{lesson1.pk} > form .tree__title"
    title0_sel = f"#node-{lesson0.pk} > form .tree__title"
    n = page.evaluate(_TAB_INDEX_JS, [title0_sel, title1_sel])
    assert n > 1
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    page.locator(title0_sel).focus()
    # expect_request, not wait_for_request after the loop: the debounced fetch can
    # fire before a later wait starts listening.
    with page.expect_request(
        lambda r: (m := PANEL_RE.search(r.url)) and m.group(1) == str(lesson1.pk)
    ):
        for _ in range(n):
            page.keyboard.press("Tab")
    assert page.evaluate(
        "(sel) => document.activeElement === document.querySelector(sel)", title1_sel
    )
    pks = [m.group(1) for u in requests if (m := PANEL_RE.search(u))]
    others = [pk for pk in pks if pk != str(lesson0.pk)]
    assert others == [str(lesson1.pk)], pks
