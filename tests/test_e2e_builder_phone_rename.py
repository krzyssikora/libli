"""Phone rename (Task 7): ⋯ → Rename edits the title in the row; every exit path.

Real phone contexts (touch + mobile + coarse pointer), plus one desktop mouse page
pinning that the desktop blur-commit 422 is untouched. Marked e2e -- foreground."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.helpers_builder_phone import assert_desktop
from tests.helpers_builder_phone import assert_phone
from tests.helpers_builder_phone import builder_url
from tests.helpers_builder_phone import login
from tests.helpers_builder_phone import make_pa_user
from tests.helpers_builder_phone import phone_context
from tests.helpers_builder_phone import seed_course

pytestmark = pytest.mark.e2e

RENAME_GLOB = "**/build/node/rename/"
INVALID = "Ten tytuł jest nieprawidłowy."
EDITING = re.compile(r"(^|\s)is-editing(\s|$)")


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _is_rename_post(request):
    return request.method == "POST" and request.url.endswith("/build/node/rename/")


def _open(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context = phone_context(browser)
    page = context.new_page()
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, seeded["course"]))
    page.wait_for_selector(".builder")
    assert_phone(page)
    posts = []
    page.on("request", lambda r: posts.append(r.url) if _is_rename_post(r) else None)
    return context, page, seeded, posts


def _head(page, pk):
    return page.locator(f"#node-{pk} > form.tree__rowhead")


def _input(page, pk):
    return page.locator(f"#node-{pk} > form.tree__rowhead > input.tree__title")


def _ptitle(page, pk):
    return page.locator(f"#node-{pk} > form.tree__rowhead > .tree__ptitle")


def _more(page, pk):
    return page.locator(f"#node-{pk} > form.tree__rowhead > .tree__more")


def _active_is(page, selector):
    return page.evaluate(
        "(s) => !!document.activeElement && document.activeElement.matches(s)",
        selector,
    )


def _focus_is_more(page, pk):
    page.wait_for_function(
        "(pk) => { const a = document.activeElement;"
        " return !!a && a.isConnected && a.matches('.tree__more')"
        " && a.closest('li.tree__row').dataset.node === String(pk); }",
        arg=pk,
    )


def _start_rename(page, pk):
    _more(page, pk).tap()
    expect(page.locator("[data-row-menu]")).to_be_visible()
    page.locator('[data-row-menu] [data-menu-action="rename"]').tap()
    expect(page.locator("[data-row-menu]")).to_be_hidden()
    expect(_input(page, pk)).to_be_visible()
    expect(_input(page, pk)).to_be_focused()
    expect(_ptitle(page, pk)).to_be_hidden()


def _tap_center(page, selector):
    """A sticky control is tapped at its centre (no scroll-into-view jitter)."""
    box = page.locator(selector).bounding_box()
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _editing_ended(page, pk):
    expect(_head(page, pk)).not_to_have_class(EDITING)
    expect(_input(page, pk)).to_be_hidden()
    expect(_ptitle(page, pk)).to_be_visible()


def _hold_rename(page):
    held = []
    page.route(RENAME_GLOB, lambda route: held.append(route))
    return held


def _fulfil_422(page):
    page.route(
        RENAME_GLOB,
        lambda route: route.fulfill(
            status=422,
            content_type="text/html",
            body=f"<p>{INVALID}</p>",
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_rename_escape(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        _start_rename(page, izo.pk)
        page.keyboard.type("Nowa")
        page.keyboard.press("Escape")
        _editing_ended(page, izo.pk)
        _focus_is_more(page, izo.pk)
        assert _input(page, izo.pk).input_value() == izo.title
        assert _ptitle(page, izo.pk).text_content() == izo.title
        page.wait_for_timeout(300)
        assert posts == []
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_enter_commits(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        new = "Izometria — część 2"
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill(new)
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            page.keyboard.press("Enter")
        expect(_ptitle(page, izo.pk)).to_have_text(new)
        _editing_ended(page, izo.pk)
        _focus_is_more(page, izo.pk)
        assert len(posts) == 1, posts
        izo.refresh_from_db()
        assert izo.title == new
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_enter_unchanged(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        _start_rename(page, izo.pk)
        page.keyboard.press("Enter")
        _editing_ended(page, izo.pk)
        _focus_is_more(page, izo.pk)
        page.wait_for_timeout(300)
        assert posts == []
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_empty_blur_reverts(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill("")
        _tap_center(page, "#builder-q")
        expect(page.locator("#builder-q")).to_be_focused()
        _editing_ended(page, izo.pk)
        assert _input(page, izo.pk).input_value() == izo.title
        assert _ptitle(page, izo.pk).text_content() == izo.title
        assert _active_is(page, "#builder-q")
        page.wait_for_timeout(300)
        assert posts == []
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_blur_commit_keeps_focus(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        new = "Izometria płaszczyzny"
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill(new)
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            _tap_center(page, "#builder-q")
        expect(_ptitle(page, izo.pk)).to_have_text(new)
        _editing_ended(page, izo.pk)
        assert _active_is(page, "#builder-q")
        assert len(posts) == 1, posts
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_blur_409_keeps_focus_in_sheet(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        intro, izo = seeded["lessons"][0], seeded["lessons"][1]
        izo.save()  # bumps `updated`: the page's token is now stale
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill("Moja zmiana")
        held = _hold_rename(page)
        _ptitle(page, intro.pk).tap()  # blur sends the POST; the tap opens a sheet
        expect(page.locator("[data-sheet].is-open")).to_be_visible()
        assert len(held) == 1, held
        with page.expect_response(lambda r: _is_rename_post(r.request)) as resp:
            held[0].continue_()
        assert resp.value.status == 409
        expect(page.locator("[data-toast]")).to_be_visible()
        _editing_ended(page, izo.pk)
        page.wait_for_timeout(200)
        assert page.evaluate(
            "() => !!document.activeElement"
            " && !!document.activeElement.closest('[data-sheet]')"
        )
        assert len(posts) == 1, posts
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_desktop_blur_422_keeps_typed_text(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    try:
        login(page, live_server, "pa")
        page.goto(builder_url(live_server, seeded["course"]))
        page.wait_for_selector(".builder")
        assert_desktop(page)
        izo = seeded["lessons"][1]
        title = _input(page, izo.pk)
        title.click()
        expect(page.locator(f'.panel[data-panel-for="{izo.pk}"]')).to_have_count(1)
        title.press("Control+a")
        page.keyboard.type("abc")
        _fulfil_422(page)
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            page.locator("h1").first.click()
        expect(page.locator("[data-panel] .op-error")).to_have_text(INVALID)
        page.wait_for_function(
            "(el) => el.readOnly === false", arg=title.element_handle()
        )
        assert title.input_value() == "abc"
        expect(title).to_be_visible()
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_422_after_blur_reverts(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill("Zły tytuł")
        _fulfil_422(page)
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            _tap_center(page, "#builder-q")
        expect(page.locator("[data-toast]")).to_be_visible()
        expect(page.locator("[data-toast]")).to_have_text(INVALID)
        _editing_ended(page, izo.pk)
        assert _input(page, izo.pk).input_value() == izo.title
        assert _ptitle(page, izo.pk).text_content() == izo.title
        assert _active_is(page, "#builder-q")
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_enter_409_focuses_more(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        izo.title = "Zmieniono gdzie indziej"
        izo.save(update_fields=["title", "updated"])
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill("Moja zmiana")
        with page.expect_response(lambda r: _is_rename_post(r.request)) as resp:
            page.keyboard.press("Enter")
        assert resp.value.status == 409
        expect(_ptitle(page, izo.pk)).to_have_text("Zmieniono gdzie indziej")
        _focus_is_more(page, izo.pk)
        _editing_ended(page, izo.pk)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_double_enter_focuses_more(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        new = "Izometria — wersja 2"
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill(new)
        held = _hold_rename(page)
        page.keyboard.press("Enter")
        page.wait_for_function(
            "(el) => el.readOnly === true", arg=_input(page, izo.pk).element_handle()
        )
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        assert len(held) == 1, held
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            held[0].continue_()
        expect(_ptitle(page, izo.pk)).to_have_text(new)
        _focus_is_more(page, izo.pk)
        _editing_ended(page, izo.pk)
        assert len(posts) == 1, posts
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_rename_422_after_enter_stays_editing(browser, live_server):
    context, page, seeded, posts = _open(browser, live_server)
    try:
        izo = seeded["lessons"][1]
        _start_rename(page, izo.pk)
        _input(page, izo.pk).fill("Zły tytuł")
        _fulfil_422(page)
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            page.keyboard.press("Enter")
        expect(page.locator("[data-toast]")).to_have_text(INVALID)
        page.wait_for_function(
            "(el) => el.readOnly === false", arg=_input(page, izo.pk).element_handle()
        )
        expect(_head(page, izo.pk)).to_have_class(EDITING)
        expect(_input(page, izo.pk)).to_be_visible()
        expect(_input(page, izo.pk)).to_be_focused()
        assert _input(page, izo.pk).input_value() == "Zły tytuł"
        expect(_ptitle(page, izo.pk)).to_be_hidden()
    finally:
        context.close()
