"""Phone row menu (Task 6): the shared ⋯ menu and Move… in the sheet.

Real phone contexts (touch + mobile + coarse pointer), so the phone media query is
the one under test, never a forced class. Marked e2e -- foreground."""

import os
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.helpers_builder_phone import assert_phone
from tests.helpers_builder_phone import builder_url
from tests.helpers_builder_phone import login
from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import phone_context
from tests.helpers_builder_phone import seed_course

pytestmark = pytest.mark.e2e

ACTIONS = ["rename", "up", "down", "move", "duplicate", "export", "delete"]
REASON = "Clear the filter to reorder."
ILLEGAL = "That move isn't allowed here."


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open(browser, live_server, **seed):
    make_pa_user("pa")
    seeded = seed_course(**seed)
    context = phone_context(browser)
    page = context.new_page()
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, seeded["course"]))
    page.wait_for_selector(".builder")
    assert_phone(page)
    return context, page, seeded


def _more(page, pk):
    return page.locator(f"#node-{pk} > form.tree__rowhead > .tree__more")


def _item(page, action):
    return page.locator(f'[data-row-menu] [data-menu-action="{action}"]')


def _open_menu(page, pk):
    _more(page, pk).tap()
    expect(page.locator("[data-row-menu]")).to_be_visible()


def _choose(page, action):
    _item(page, action).tap()


def _menu_closed(page):
    expect(page.locator("[data-row-menu]")).to_be_hidden()


def _focus_is_more(page, pk):
    page.wait_for_function(
        "(pk) => { const a = document.activeElement;"
        " return !!a && a.isConnected && a.matches('.tree__more')"
        " && a.closest('li.tree__row').dataset.node === String(pk); }",
        arg=pk,
    )


def _active_matches(page, selector):
    return page.evaluate(
        "(s) => !!document.activeElement && document.activeElement.matches(s)",
        selector,
    )


def _sheet_open(page):
    expect(page.locator("[data-sheet].is-open")).to_be_visible()


def _sheet_closed(page):
    expect(page.locator("[data-sheet].is-open")).to_have_count(0)
    expect(page.locator("[data-sheet-shell]")).to_be_hidden()


def _picker(page):
    return page.locator("[data-sheet] [data-panel] form.move-picker")


def _open_move(page, pk):
    _open_menu(page, pk)
    _choose(page, "move")
    _sheet_open(page)


def _open_kurs(page):
    box = page.locator("[data-sheet-course]").bounding_box()
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    _sheet_open(page)


def _two_frames(page):
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


def _visible_actions(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-row-menu] [data-menu-action]')]
             .filter((b) => b.checkVisibility())
             .map((b) => b.dataset.menuAction)"""
    )


def _is_picker_get(request):
    return request.method == "GET" and "/build/node/move/" in request.url


def _is_move_post(request):
    return request.method == "POST" and "/build/node/move/" in request.url


def _panel_path(course, pk):
    return f"/manage/courses/{course.slug}/build/node/{pk}/"


@pytest.mark.django_db(transaction=True)
def test_menu_lists_items_in_order(browser, live_server):
    context, page, seeded = _open(browser, live_server, long_title=True)
    try:
        lesson = seeded["lessons"][0]
        assert len(lesson.title) == 180
        _open_menu(page, lesson.pk)
        assert page.locator("[data-menu-title]").text_content() == lesson.title
        expect(page.locator("[data-menu-title]")).to_be_visible()
        assert _visible_actions(page) == ACTIONS
        # The first lesson's Move up is disabled; Rename is the first enabled item.
        assert _active_matches(page, '[data-menu-action="rename"]')
        assert _more(page, lesson.pk).get_attribute("aria-expanded") == "true"

        page.keyboard.press("Escape")
        _menu_closed(page)
        chapter = seeded["chapter"]
        _open_menu(page, chapter.pk)
        assert _visible_actions(page) == [a for a in ACTIONS if a != "duplicate"]
        assert page.locator("[data-menu-title]").text_content() == chapter.title
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_menu_opener_expanded_state(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        a, b = seeded["lessons"][0], seeded["lessons"][1]
        _open_menu(page, a.pk)
        assert _more(page, a.pk).get_attribute("aria-expanded") == "true"
        _more(page, b.pk).tap()
        expect(_more(page, b.pk)).to_have_attribute("aria-expanded", "true")
        assert _more(page, a.pk).get_attribute("aria-expanded") == "false"
        assert page.locator("[data-menu-title]").text_content() == b.title
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_first_and_last_disabled(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        _open_menu(page, seeded["lessons"][0].pk)
        expect(_item(page, "up")).to_be_disabled()
        expect(_item(page, "down")).to_be_enabled()
        page.keyboard.press("Escape")
        _menu_closed(page)

        _open_menu(page, seeded["quiz"].pk)  # the section's last unit
        expect(_item(page, "down")).to_be_disabled()
        expect(_item(page, "up")).to_be_enabled()
        expect(page.locator("[data-menu-reason]")).to_be_hidden()
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_filter_reason_visible(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        _open_menu(page, izo.pk)
        expect(_item(page, "up")).to_be_enabled()
        expect(_item(page, "down")).to_be_enabled()
        expect(page.locator("[data-menu-reason]")).to_be_hidden()
        page.keyboard.press("Escape")
        _menu_closed(page)

        with page.expect_response(lambda r: "q=Izo" in r.url):
            page.locator("#builder-q").fill("Izo")
            page.locator("#builder-q").press("Enter")
        _open_menu(page, izo.pk)
        expect(_item(page, "up")).to_be_disabled()
        expect(_item(page, "down")).to_be_disabled()
        reason = page.locator("[data-menu-reason]")
        expect(reason).to_be_visible()
        expect(reason).to_have_text(REASON)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_move_up_via_menu_keeps_focus(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        section, izo = seeded["section"], seeded["lessons"][1]
        _open_menu(page, izo.pk)
        _choose(page, "up")
        first = page.locator(f'ol[data-scope="{section.pk}"] > li.tree__row').first
        expect(first).to_have_attribute("data-node", str(izo.pk))
        _menu_closed(page)
        _focus_is_more(page, izo.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_duplicate_via_menu(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        section, lesson = seeded["section"], seeded["lessons"][0]
        rows = page.locator(f'ol[data-scope="{section.pk}"] > li.tree__row')
        expect(rows).to_have_count(4)
        _open_menu(page, lesson.pk)
        _choose(page, "duplicate")
        expect(rows).to_have_count(5)
        assert rows.nth(0).get_attribute("data-node") == str(lesson.pk)
        copy = rows.nth(1)
        assert copy.get_attribute("data-node") != str(lesson.pk)
        # duplicate_unit keeps the title verbatim (no suffix).
        ptitle = copy.locator(":scope > form.tree__rowhead > .tree__ptitle")
        expect(ptitle).to_have_text(lesson.title)
        _focus_is_more(page, lesson.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_delete_href_carries_open_set(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson, chapter = seeded["lessons"][0], seeded["chapter"]
        _open_menu(page, lesson.pk)
        _choose(page, "delete")
        page.wait_for_url(lambda u: "/build/node/delete/" in u and "open=" in u)
        open_param = parse_qs(urlparse(page.url).query)["open"][0]
        assert str(chapter.pk) in open_param.split(","), open_param
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_menu_open_commits_typed_add_row(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        section = seeded["section"]
        add = page.locator(f'form.tree__add[data-add-scope="{section.pk}"]')
        add.locator('button[data-add-kind="lesson"]').tap()
        title = add.locator("[data-add-title]")
        expect(title).to_be_visible()
        title.fill("Nowa lekcja")
        _open_menu(page, seeded["lessons"][0].pk)
        expect(
            page.locator('li.tree__row input.tree__title[value="Nowa lekcja"]')
        ).to_have_count(1)
    finally:
        context.close()


def _header_background_point(page):
    """A point inside the sticky header that hits the header element itself."""
    return page.evaluate(
        """() => {
             const head = document.querySelector('header.manage__head');
             const r = head.getBoundingClientRect();
             for (let y = r.top + 2; y < r.bottom - 1; y += 3) {
               for (let x = r.right - 3; x > r.left; x -= 5) {
                 if (document.elementFromPoint(x, y) === head) return [x, y];
               }
             }
             return null; }"""
    )


@pytest.mark.django_db(transaction=True)
def test_menu_escape_and_outside_tap(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson = seeded["lessons"][1]
        _open_menu(page, lesson.pk)
        page.keyboard.press("Escape")
        _menu_closed(page)
        _focus_is_more(page, lesson.pk)
        assert _more(page, lesson.pk).get_attribute("aria-expanded") == "false"

        _open_menu(page, lesson.pk)
        point = _header_background_point(page)
        assert point, "no bare header background found"
        page.touchscreen.tap(point[0], point[1])
        _menu_closed(page)
        _focus_is_more(page, lesson.pk)
        assert not _active_matches(page, "body")
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_menu_escape_over_strip(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        chapter = seeded["chapter"]
        page.locator(
            f"#node-{chapter.pk} > form.tree__rowhead"
            ' > a[data-flag-confirm][data-flag="published"]'
        ).tap()
        strip = page.locator("[data-flag-strip]")
        expect(strip).to_have_count(1)
        _open_menu(page, chapter.pk)
        page.keyboard.press("Escape")
        _menu_closed(page)
        expect(strip).to_have_count(1)
        _focus_is_more(page, chapter.pk)

        strip.focus()
        page.keyboard.press("Escape")
        expect(strip).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_move_via_menu_in_sheet(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson, chapter2 = seeded["lessons"][0], seeded["chapter2"]
        _open_move(page, lesson.pk)
        assert page.locator("[data-sheet]").get_attribute("data-mode") == "move"
        expect(_picker(page)).to_be_visible()
        expect(page.locator("[data-sheet-tools]")).to_be_hidden()
        page.locator(f'[data-panel] .move-dest[data-dest="{chapter2.pk}"]').tap()
        page.locator("[data-panel] .move-picker__submit").tap()
        _sheet_closed(page)
        expect(
            page.locator(f'ol[data-scope="{chapter2.pk}"] > #node-{lesson.pk}')
        ).to_have_count(1)
        _focus_is_more(page, lesson.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_move_sheet_escape_dismisses_picker(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson = seeded["lessons"][1]
        _open_move(page, lesson.pk)
        expect(_picker(page)).to_be_visible()
        expect(page.locator(".moving")).to_have_count(1)
        page.keyboard.press("Escape")
        _sheet_closed(page)
        expect(page.locator(".moving")).to_have_count(0)
        _focus_is_more(page, lesson.pk)

        _open_kurs(page)
        expect(
            page.locator('[data-panel] .panel[data-panel-for="course"]')
        ).to_be_visible()
        expect(page.locator("form.move-picker")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_move_sheet_close_by_dim_cleans_up(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson = seeded["lessons"][1]
        _open_move(page, lesson.pk)
        expect(_picker(page)).to_be_visible()
        expect(page.locator(".moving")).to_have_count(1)
        assert page.evaluate(
            "() => document.elementFromPoint(195, 60).matches('[data-sheet-dim]')"
        )
        page.touchscreen.tap(195, 60)
        _sheet_closed(page)
        expect(page.locator(".moving")).to_have_count(0)
        _focus_is_more(page, lesson.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_late_picker_is_dropped(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson = seeded["lessons"][1]
        held = []

        def hold(route):
            if _is_picker_get(route.request):
                held.append(route)
            else:
                route.continue_()

        page.route("**/build/node/move/**", hold)
        _open_move(page, lesson.pk)
        expect(page.locator("[data-panel] [data-panel-loading]")).to_be_visible()
        page.locator("[data-sheet-close]").tap()
        _sheet_closed(page)
        assert len(held) == 1, held
        with page.expect_response(lambda r: _is_picker_get(r.request)):
            held[0].continue_()
        _two_frames(page)
        expect(page.locator(".moving")).to_have_count(0)
        expect(page.locator("form.move-picker")).to_have_count(0)
        _open_kurs(page)
        expect(
            page.locator('[data-panel] .panel[data-panel-for="course"]')
        ).to_be_visible()
        expect(page.locator("form.move-picker")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_late_panel_dropped_after_move_opens(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        course = seeded["course"]
        a, b = seeded["lessons"][0], seeded["lessons"][1]
        held = []
        page.route(f"**{_panel_path(course, a.pk)}", lambda route: held.append(route))
        page.locator(f"#node-{a.pk} > form.tree__rowhead > .tree__ptitle").tap()
        expect(page.locator("[data-panel] [data-panel-loading]")).to_be_visible()
        page.locator("[data-sheet-close]").tap()
        _sheet_closed(page)

        _open_move(page, b.pk)
        expect(_picker(page)).to_be_visible()
        assert len(held) == 1, held
        with page.expect_response(lambda r: _panel_path(course, a.pk) in r.url):
            held[0].continue_()
        _two_frames(page)
        expect(_picker(page)).to_be_visible()
        expect(page.locator(f'.panel[data-panel-for="{a.pk}"]')).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_picker_422_toast_over_sheet(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson, chapter2 = seeded["lessons"][0], seeded["chapter2"]

        def reject(route):
            if _is_move_post(route.request):
                route.fulfill(
                    status=422,
                    content_type="text/html",
                    body=f"<p>{ILLEGAL}</p>",
                )
            else:
                route.continue_()

        page.route("**/build/node/move/**", reject)
        _open_move(page, lesson.pk)
        expect(_picker(page)).to_be_visible()
        page.locator(f'[data-panel] .move-dest[data-dest="{chapter2.pk}"]').tap()
        page.locator("[data-panel] .move-picker__submit").tap()
        toast = page.locator("[data-toast]")
        expect(toast).to_be_visible()
        expect(toast).to_have_text(ILLEGAL)
        _sheet_open(page)
        expect(_picker(page)).to_be_visible()
        on_top = page.evaluate(
            """() => {
                 const t = document.querySelector('[data-toast]');
                 t.style.pointerEvents = 'auto';
                 const r = t.getBoundingClientRect();
                 const hit = document.elementFromPoint(
                   r.left + r.width / 2, r.top + r.height / 2);
                 t.style.pointerEvents = '';
                 return !!hit && t.contains(hit); }"""
        )
        assert on_top
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_focus_returns_to_replaced_row(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        section, lesson = seeded["section"], seeded["lessons"][1]
        _open_move(page, lesson.pk)
        expect(_picker(page)).to_be_visible()
        page.evaluate(
            "(pk) => { window.__oldRow = document.getElementById('node-' + pk); }",
            lesson.pk,
        )
        page.locator(f'[data-panel] .move-dest[data-dest="{section.pk}"]').tap()
        page.locator('[data-panel] [data-move-slot="0"]').tap()
        page.locator("[data-panel] .move-picker__submit").tap()
        _sheet_closed(page)
        first = page.locator(f'ol[data-scope="{section.pk}"] > li.tree__row').first
        expect(first).to_have_attribute("data-node", str(lesson.pk))
        assert page.evaluate("() => window.__oldRow.isConnected") is False
        _focus_is_more(page, lesson.pk)
    finally:
        context.close()
