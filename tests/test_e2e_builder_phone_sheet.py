"""Phone bottom sheet (Task 3): open/close, modality, scroll lock, Kurs sheet tools.

Real phone contexts (touch + mobile + coarse pointer), so the phone media query is
the one under test, never a forced class. Marked e2e -- foreground."""

import os

import pytest
from playwright.sync_api import expect

from tests.helpers_builder_phone import assert_phone
from tests.helpers_builder_phone import builder_url
from tests.helpers_builder_phone import login
from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import phone_context
from tests.helpers_builder_phone import seed_course

pytestmark = pytest.mark.e2e

TOO_LARGE = "This course is too large to expand at once."


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
    assert_phone(page)
    return context, page


def _drag_scroll(page, x, y_from, y_to):
    """A touch drag that HOLDS at its end before lifting, so it leaves no fling.

    cdp_touch_scroll lifts at full speed and starts a fling, and Chromium then
    swallows the next tap as a fling-cancel (no click) -- however long ago the
    fling visibly stopped -- so the first Kurs tap after it would do nothing."""
    cdp = page.context.new_cdp_session(page)

    def touch(kind, y):
        points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    touch("touchStart", y_from)
    for i in range(1, 9):
        touch("touchMove", y_from + (y_to - y_from) * i / 8)
    for _ in range(6):
        page.wait_for_timeout(50)
        touch("touchMove", y_to)
    touch("touchEnd", y_to)


def _scroll_to(page, minimum):
    for _ in range(12):
        if page.evaluate("() => window.scrollY") >= minimum:
            break
        _drag_scroll(page, 200, 700, 250)
        page.wait_for_timeout(150)
    y = page.evaluate("() => window.scrollY")
    assert y >= minimum, y
    return y


def _scopes(page):
    return sorted(
        page.evaluate(
            "() => [...document.querySelectorAll('ol[data-scope]')]"
            ".map((o) => o.dataset.scope)"
        )
    )


def _active_matches(page, selector):
    return page.evaluate(
        "(s) => !!document.activeElement && document.activeElement.matches(s)",
        selector,
    )


def _element_at(page, x, y):
    return page.evaluate(
        """([x, y]) => { const el = document.elementFromPoint(x, y);
             return el ? el.matches('[data-sheet-dim]') : false; }""",
        [x, y],
    )


def _open_kurs(page):
    # A raw tap at the button's centre, not locator.tap(): Playwright's
    # scroll-into-view on the STICKY Kurs button scrolls the page back towards
    # the button's static slot, which would wreck every scrollY assertion.
    box = page.locator("[data-sheet-course]").bounding_box()
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("[data-sheet].is-open")).to_be_visible()


def _sheet_closed(page):
    expect(page.locator("[data-sheet].is-open")).to_have_count(0)
    expect(page.locator("[data-sheet-shell]")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_kurs_sheet_shows_course_panel_and_tools(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    try:
        _open_kurs(page)
        expect(
            page.locator('[data-panel] .panel[data-panel-for="course"]')
        ).to_be_visible()
        tools = page.locator("[data-sheet-tools]")
        for sel in (
            "[data-phone-move='io'] a >> nth=0",  # Import content
            "[data-phone-move='io'] a >> nth=1",  # Export
            "[data-expand-all]",
            "[data-collapse-all]",
            "p.builder__legend",  # structure legend
            "details.flag-legend",
            "p.helptext",
        ):
            expect(tools.locator(sel).first).to_be_visible()
        head = page.locator("header.manage__head")
        expect(head.locator("h1")).to_be_visible()
        expect(head.locator("[data-sheet-course]")).to_be_visible()
        expect(head.locator("form.builder__filter")).to_be_visible()
        assert _active_matches(page, "[data-sheet-close]")
        sheet = page.locator("[data-sheet]")
        assert sheet.get_attribute("role") == "dialog"
        assert sheet.get_attribute("aria-modal") == "true"
        details = page.locator(".builder").get_attribute("data-msg-details")
        assert details
        assert sheet.get_attribute("aria-label") == details
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_sheet_close_paths_restore_scroll_and_scopes(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course(extra_lessons=40)
    context, page = _open(browser, live_server, seeded["course"])
    try:
        y0 = _scroll_to(page, 400)
        scopes0 = _scopes(page)
        assert len(scopes0) > 1, scopes0

        def close_x():
            page.locator("[data-sheet-close]").tap()

        def close_dim():
            assert _element_at(page, 195, 60)
            page.touchscreen.tap(195, 60)

        def close_escape():
            page.keyboard.press("Escape")

        for close in (close_x, close_dim, close_escape):
            _open_kurs(page)
            close()
            _sheet_closed(page)
            y = page.evaluate("() => window.scrollY")
            assert abs(y - y0) <= 1, (close.__name__, y, y0)
            assert _scopes(page) == scopes0, close.__name__
            assert _active_matches(page, "[data-sheet-course]"), close.__name__
            sheet = page.locator("[data-sheet]")
            for attr in ("role", "aria-modal", "aria-label"):
                assert sheet.get_attribute(attr) is None, (close.__name__, attr)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_modality_while_open(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course(extra_lessons=40)
    context, page = _open(browser, live_server, seeded["course"])
    try:
        _scroll_to(page, 400)
        _open_kurs(page)
        tree = page.locator(".builder__tree")
        assert tree.get_attribute("inert") is not None
        assert page.evaluate(
            "() => document.querySelector('.builder__tree').matches('[inert]')"
        )
        assert _active_matches(page, "[data-sheet-close]")
        for _ in range(10):
            page.keyboard.press("Shift+Tab")
            inside = page.evaluate(
                "() => !!document.activeElement"
                " && !!document.activeElement.closest('.builder__tree')"
            )
            assert not inside

        # Scroll lock: a touch drag on the dim leaves the tree where it was.
        row_sel = f"#node-{seeded['extra'][20].pk}"
        top_js = (
            f"() => document.querySelector('{row_sel}').getBoundingClientRect().top"
        )
        top0 = page.evaluate(top_js)
        assert _element_at(page, 195, 150)
        # Held at its end like every drag here, so the dim tap below is not
        # swallowed as a fling-cancel (see _drag_scroll).
        _drag_scroll(page, 195, 250, 40)
        page.wait_for_timeout(400)
        assert page.evaluate(top_js) == top0
        expect(
            page.locator("[data-sheet].is-open")
        ).to_be_visible()  # a drag never closes
        assert page.evaluate(
            "() => document.documentElement.classList.contains('builder-sheet-lock')"
        )
        assert (
            page.evaluate("() => getComputedStyle(document.body).position") == "fixed"
        )

        # A dim tap closes the sheet and does nothing to the tree underneath.
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        assert _element_at(page, 195, 120)
        page.touchscreen.tap(195, 120)
        _sheet_closed(page)
        page.wait_for_timeout(300)
        assert not [u for u in requests if "/build/node/" in u], requests
        assert not _active_matches(page, "#builder-q")
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_closed_sheet_is_unreachable(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    try:
        page.evaluate(
            "() => { const m = document.querySelectorAll('.tree__more');"
            " m[m.length - 1].focus(); }"
        )
        assert _active_matches(page, ".tree__more")
        for _ in range(15):
            page.keyboard.press("Tab")
            assert page.evaluate(
                "() => !document.activeElement"
                " || document.activeElement.closest('[data-sheet]') === null"
            )
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_expand_collapse_close_sheet(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    try:
        chapter = seeded["chapter"].pk
        expect(page.locator(f'ol[data-scope="{chapter}"]')).to_have_count(1)

        _open_kurs(page)
        page.locator("[data-sheet-tools] [data-collapse-all]").tap()
        _sheet_closed(page)
        assert _scopes(page) == ["top"]

        _open_kurs(page)
        page.locator("[data-sheet-tools] [data-expand-all]").tap()
        _sheet_closed(page)
        expect(page.locator(f'ol[data-scope="{chapter}"]')).to_have_count(1)

        with page.expect_response(lambda r: "q=Izo" in r.url):
            page.locator("#builder-q").fill("Izo")
            page.locator("#builder-q").press("Enter")
        _open_kurs(page)
        href = page.locator("[data-sheet-tools] [data-expand-all]").get_attribute(
            "href"
        )
        assert "q=Izo" in href, href
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_disabled_expand_all_keeps_sheet_open(browser, live_server, monkeypatch):
    from courses import builder_open

    # views_manage reads builder_open.CEILING through the module (_expand_all_disabled).
    monkeypatch.setattr(builder_open, "CEILING", 1)
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    try:
        _open_kurs(page)
        expand_all = page.locator("[data-sheet-tools] [data-expand-all]")
        assert expand_all.get_attribute("aria-disabled") == "true"
        expand_all.tap()
        page.wait_for_timeout(300)
        expect(page.locator("[data-sheet].is-open")).to_be_visible()
        display, content = page.evaluate(
            """() => {
                 const el = document.querySelector(
                   '[data-sheet-tools] [data-expand-all]');
                 const cs = getComputedStyle(el, '::after');
                 return [cs.display, cs.content]; }"""
        )
        assert display == "block"
        assert content in ("attr(title)", f'"{TOO_LARGE}"'), content
        assert expand_all.get_attribute("title") == TOO_LARGE
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_fresh_phone_load_moves_toolbar(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    try:
        parents = page.evaluate(
            "() => [...document.querySelectorAll('[data-phone-move]')]"
            ".map((n) => [n.dataset.phoneMove,"
            " n.parentElement.matches('[data-sheet-tools]')])"
        )
        assert parents == [["io", True], ["bulk", True], ["legends", True]], parents
        head_h = page.evaluate(
            "() => document.documentElement.style.getPropertyValue('--phone-head-h')"
        )
        assert head_h.endswith("px") and float(head_h[:-2]) > 0, head_h
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_focus_return_without_checkvisibility(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    errors = []
    page.on("pageerror", lambda e: errors.append(e))
    try:
        page.evaluate("() => { delete Element.prototype.checkVisibility; }")
        assert page.evaluate("() => 'checkVisibility' in Element.prototype") is False
        _open_kurs(page)
        page.locator("[data-sheet-close]").tap()
        _sheet_closed(page)
        assert _active_matches(page, "[data-sheet-course]")
        assert errors == []
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_pageshow_persisted_closes_sheet(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context, page = _open(browser, live_server, seeded["course"])
    try:
        _open_kurs(page)
        page.evaluate(
            "() => window.dispatchEvent("
            "new PageTransitionEvent('pageshow', {persisted: true}))"
        )
        _sheet_closed(page)
        assert page.locator(".builder__tree").get_attribute("inert") is None
    finally:
        context.close()


# ---- Task 4: a title tap opens that node's panel in the sheet ----------------

NETWORK_ERROR = "Network error — please reload."


def _ptitle(page, pk):
    return page.locator(f"#node-{pk} > form.tree__rowhead > .tree__ptitle")


def _panel_path(course, pk):
    return f"/manage/courses/{course.slug}/build/node/{pk}/"


def _node_panel(page, pk):
    return page.locator(f'[data-panel] .panel[data-panel-for="{pk}"]')


def _hold(page, course, pk):
    """Hold the panel GET for `pk` (a fetch, never a navigation). Returns the list
    the held route lands in; `_release` continues it."""
    held = []
    page.route(f"**{_panel_path(course, pk)}", lambda route: held.append(route))
    return held


def _release(held):
    assert len(held) == 1, held
    held[0].continue_()


def _two_frames(page):
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


def _focus_in_sheet(page):
    return page.evaluate(
        "() => !!document.activeElement"
        " && !!document.activeElement.closest('[data-sheet]')"
    )


def _focus_is_ptitle(page, pk):
    return page.evaluate(
        "(pk) => document.activeElement === document.querySelector("
        "'#node-' + pk + ' > form.tree__rowhead > .tree__ptitle')",
        pk,
    )


def _close_x(page):
    page.locator("[data-sheet-close]").tap()
    _sheet_closed(page)


@pytest.mark.django_db(transaction=True)
def test_tap_title_opens_that_units_panel(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    izo = seeded["lessons"][1]
    context, page = _open(browser, live_server, seeded["course"])
    try:
        # A Kurs round trip first, so a stale data-mode="course" could linger.
        _open_kurs(page)
        _close_x(page)

        _ptitle(page, izo.pk).tap()
        expect(page.locator("[data-sheet].is-open")).to_be_visible()
        expect(_node_panel(page, izo.pk)).to_be_visible()
        expect(_node_panel(page, izo.pk).locator("h2")).to_contain_text("Izometria")
        expect(page.locator("[data-sheet-tools]")).to_be_hidden()
        assert not _active_matches(page, "input, textarea, [contenteditable]")
        assert _focus_in_sheet(page)

        _close_x(page)
        assert _focus_is_ptitle(page, izo.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_placeholder_never_shows_previous_panel(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    course = seeded["course"]
    a, b = seeded["lessons"][0], seeded["lessons"][1]
    context, page = _open(browser, live_server, course)
    try:
        _ptitle(page, a.pk).tap()
        expect(_node_panel(page, a.pk)).to_be_visible()
        _close_x(page)

        held = _hold(page, course, b.pk)
        _ptitle(page, b.pk).tap()
        expect(page.locator("[data-sheet].is-open")).to_be_visible()
        expect(page.locator("[data-panel] [data-panel-loading]")).to_be_visible()
        expect(page.locator(f'.panel[data-panel-for="{a.pk}"]')).to_have_count(0)

        _release(held)
        expect(_node_panel(page, b.pk)).to_be_visible()
        expect(page.locator("[data-panel] [data-panel-loading]")).to_have_count(0)
        assert _focus_in_sheet(page)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_late_panel_response_is_dropped(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    course = seeded["course"]
    a, b = seeded["lessons"][0], seeded["lessons"][1]
    a_glob = f"**{_panel_path(course, a.pk)}"
    context, page = _open(browser, live_server, course)
    try:
        # Variant 1: A held, sheet closed, Kurs opened -> A's late reply is dropped.
        held = _hold(page, course, a.pk)
        _ptitle(page, a.pk).tap()
        expect(page.locator("[data-panel] [data-panel-loading]")).to_be_visible()
        _close_x(page)
        _open_kurs(page)
        course_panel = page.locator('[data-panel] .panel[data-panel-for="course"]')
        expect(course_panel).to_be_visible()
        with page.expect_response(lambda r: _panel_path(course, a.pk) in r.url):
            _release(held)
        _two_frames(page)
        expect(course_panel).to_be_visible()
        expect(page.locator(f'.panel[data-panel-for="{a.pk}"]')).to_have_count(0)
        _close_x(page)
        page.unroute(a_glob)

        # Variant 2: A held, sheet closed, B tapped (unheld) -> B stays.
        held = _hold(page, course, a.pk)
        _ptitle(page, a.pk).tap()
        expect(page.locator("[data-panel] [data-panel-loading]")).to_be_visible()
        _close_x(page)
        _ptitle(page, b.pk).tap()
        expect(_node_panel(page, b.pk)).to_be_visible()
        with page.expect_response(lambda r: _panel_path(course, a.pk) in r.url):
            _release(held)
        _two_frames(page)
        expect(_node_panel(page, b.pk)).to_be_visible()
        expect(page.locator(f'.panel[data-panel-for="{a.pk}"]')).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_panel_network_error_shows_in_sheet(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    course = seeded["course"]
    izo = seeded["lessons"][1]
    context, page = _open(browser, live_server, course)
    try:
        page.route(f"**{_panel_path(course, izo.pk)}", lambda route: route.abort())
        _ptitle(page, izo.pk).tap()
        expect(page.locator("[data-sheet].is-open")).to_be_visible()
        error = page.locator("[data-sheet] [data-panel] .op-error")
        expect(error).to_be_visible()
        expect(error).to_have_text(NETWORK_ERROR)
        expect(page.locator("[data-panel] [data-panel-loading]")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_keyboard_enter_opens_sheet(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    izo = seeded["lessons"][1]
    context, page = _open(browser, live_server, seeded["course"])
    try:
        _ptitle(page, izo.pk).focus()
        page.keyboard.press("Enter")
        expect(page.locator("[data-sheet].is-open")).to_be_visible()
        expect(_node_panel(page, izo.pk)).to_be_visible()
        page.keyboard.press("Escape")
        _sheet_closed(page)
        assert _focus_is_ptitle(page, izo.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_sheet_scroll_resets_between_opens(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    izo = seeded["lessons"][1]
    # Landscape: the Kurs sheet's content fits a portrait 67dvh sheet unscrolled,
    # so only the short landscape sheet body can be scrolled to set up the state.
    context, page = _open(
        browser, live_server, seeded["course"], orientation="landscape"
    )
    try:
        _open_kurs(page)
        # Sets up state (a scrolled sheet body); it asserts no behaviour itself.
        scrolled = page.evaluate(
            "() => { const b = document.querySelector('[data-sheet-body]');"
            " b.scrollTop = 200; return b.scrollTop; }"
        )
        assert scrolled > 0, scrolled
        _close_x(page)
        _ptitle(page, izo.pk).tap()
        expect(_node_panel(page, izo.pk)).to_be_visible()
        body_top = page.evaluate(
            "() => document.querySelector('[data-sheet-body]').scrollTop"
        )
        assert body_top == 0, body_top
        # The sheet body is the one phone scroll container: no own panel scroll.
        heights = page.evaluate(
            "() => { const p = document.querySelector('[data-panel]');"
            " return [p.scrollHeight, p.clientHeight]; }"
        )
        assert heights[0] <= heights[1] + 1, heights
    finally:
        context.close()
