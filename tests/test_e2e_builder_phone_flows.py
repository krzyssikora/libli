"""Phone notices as a toast (Task 5); end-to-end flows, layout flips, the confirm
strip and landscape (Task 9). Real touch contexts; e2e -- foreground."""

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

CONFLICT = "This changed elsewhere — reloaded to the latest."
NETWORK = "Network error — please try again."


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open(browser, live_server):
    make_pa_user("pa")
    seeded = seed_course()
    context = phone_context(browser)
    page = context.new_page()
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, seeded["course"]))
    page.wait_for_selector(".builder")
    assert_phone(page)
    return context, page, seeded


def _flag(page, node):
    return page.locator(
        f'[data-node="{node.pk}"] > form.tree__rowhead button[data-flag="published"]'
    )


def test_conflict_notice_visible_with_sheet_closed(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        lesson = seeded["lessons"][0]
        lesson.save()  # bumps `updated`: the row's token is now stale
        _flag(page, lesson).tap()
        toast = page.locator("[data-toast]")
        expect(toast).to_be_visible()
        expect(toast).to_have_text(CONFLICT)
        assert page.locator("[data-panel] .op-error").count() == 0
    finally:
        context.close()


def test_network_notice_toast(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        page.route("**/build/node/flag/**", lambda r: r.abort())
        _flag(page, seeded["lessons"][0]).tap()
        toast = page.locator("[data-toast]")
        expect(toast).to_be_visible()
        expect(toast).to_have_text(NETWORK)
        assert page.locator("[data-panel] .op-error").count() == 0
    finally:
        context.close()


def test_toast_hides_after_six_seconds(browser, live_server):
    context, page, seeded = _open(browser, live_server)
    try:
        page.route("**/build/node/flag/**", lambda r: r.abort())
        _flag(page, seeded["lessons"][0]).tap()
        toast = page.locator("[data-toast]")
        expect(toast).to_be_visible()
        expect(toast).to_be_hidden(timeout=8000)
    finally:
        context.close()


# --- Task 9: end-to-end flows, layout flips, confirm strip, landscape ----------

EDITING = re.compile(r"(^|\s)is-editing(\s|$)")
PHONE_VP = {"width": 900, "height": 800}
DESKTOP_VP = {"width": 1000, "height": 800}
# test_builder_phone_markup.py::test_header_order_unchanged, checked at runtime.
HEADER_ORDER = ["h1", "kurs", "import", "export", "filter", "expand", "collapse"]


def _is_rename_post(request):
    return request.method == "POST" and request.url.endswith("/build/node/rename/")


def _open_at(browser, live_server, orientation="portrait", viewport=None):
    """A touch context (coarse pointer) at `viewport`; rename POSTs are counted."""
    make_pa_user("pa")
    seeded = seed_course()
    context = phone_context(browser, orientation, viewport=viewport)
    page = context.new_page()
    login(page, live_server, "pa")
    page.goto(builder_url(live_server, seeded["course"]))
    page.wait_for_selector(".builder")
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


def _menu(page):
    return page.locator("[data-row-menu]")


def _choose(page, pk, action):
    _more(page, pk).tap()
    expect(_menu(page)).to_be_visible()
    page.locator(f'[data-row-menu] [data-menu-action="{action}"]').tap()


def _node_panel(page, pk):
    return page.locator(f'[data-panel] .panel[data-panel-for="{pk}"]')


def _sheet_open(page):
    expect(page.locator("[data-sheet].is-open")).to_be_visible()


def _sheet_closed(page):
    expect(page.locator("[data-sheet].is-open")).to_have_count(0)


def _force_layout(page):
    page.evaluate("() => document.body.offsetHeight")


def _toolbar_in_sheet(page):
    page.wait_for_function(
        "() => [...document.querySelectorAll('[data-phone-move]')]"
        ".every((n) => n.parentElement.matches('[data-sheet-tools]'))"
    )


def _header_order(page):
    return page.evaluate(
        """() => {
          const head = document.querySelector('header.manage__head');
          const sel = 'h1, .builder__kurs, a.btn, form.builder__filter, '
            + '[data-expand-all], [data-collapse-all]';
          const out = [];
          for (const el of head.querySelectorAll(sel)) {
            if (el.hasAttribute('data-filter-clear')) continue;
            if (el.matches('h1')) out.push('h1');
            else if (el.classList.contains('builder__kurs')) out.push('kurs');
            else if (el.matches('form')) out.push('filter');
            else if (el.hasAttribute('data-expand-all')) out.push('expand');
            else if (el.hasAttribute('data-collapse-all')) out.push('collapse');
            else if (el.getAttribute('href').includes('import')) out.push('import');
            else if (el.getAttribute('href').includes('export')) out.push('export');
            else out.push(el.getAttribute('href'));
          }
          return out;
        }"""
    )


@pytest.mark.django_db(transaction=True)
def test_split_a_unit_flow(browser, live_server):
    from courses.models import ContentNode

    context, page, seeded, posts = _open_at(browser, live_server)
    try:
        assert_phone(page)
        course, izo = seeded["course"], seeded["lessons"][1]
        with page.expect_response(lambda r: "q=Izometria" in r.url):
            page.locator("#builder-q").fill("Izometria")
            page.locator("#builder-q").press("Enter")
        expect(_ptitle(page, izo.pk)).to_be_visible()

        rows_js = (
            "() => [...document.querySelectorAll('li.tree__row')]"
            ".map((r) => r.dataset.node)"
        )
        before = set(page.evaluate(rows_js))
        _choose(page, izo.pk, "duplicate")
        # duplicate_unit keeps the title verbatim: the copy is identified by pk --
        # the one new row, which sits directly after the original. (The filter
        # also matches "…izometrią?", so a next sibling exists before the copy.)
        page.wait_for_function(
            "(n) => document.querySelectorAll('li.tree__row').length > n",
            arg=len(before),
        )
        (copy_pk,) = set(page.evaluate(rows_js)) - before
        copy_pk = int(copy_pk)
        assert page.evaluate(
            "(pk) => document.querySelector('#node-' + pk)"
            ".nextElementSibling.dataset.node",
            izo.pk,
        ) == str(copy_pk)
        assert ContentNode.objects.get(pk=copy_pk).title == izo.title

        _choose(page, copy_pk, "rename")
        expect(_input(page, copy_pk)).to_be_focused()
        _input(page, copy_pk).fill("Izometria II")
        with page.expect_response(lambda r: _is_rename_post(r.request)):
            page.keyboard.press("Enter")
        expect(_ptitle(page, copy_pk)).to_have_text("Izometria II")
        expect(_ptitle(page, izo.pk)).to_have_text("Izometria")

        _ptitle(page, copy_pk).tap()
        _sheet_open(page)
        panel = _node_panel(page, copy_pk)
        expect(panel).to_be_visible()
        expect(panel.locator("h2")).to_contain_text("Izometria II")
        expect(_node_panel(page, izo.pk)).to_have_count(0)

        edit_path = f"/manage/courses/{course.slug}/build/unit/{copy_pk}/edit/"
        link = panel.locator(f'a[href="{edit_path}"]')
        expect(link).to_be_visible()
        link.tap()
        page.wait_for_url(f"{live_server.url}{edit_path}")
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_confirm_strip_on_phone(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server)
    try:
        assert_phone(page)
        chapter = seeded["chapter"]
        anchor = page.locator(
            f"#node-{chapter.pk} > form.tree__rowhead"
            ' > a[data-flag-confirm][data-flag="published"]'
        )
        strip = page.locator(f'[data-flag-strip="{chapter.pk}"]')

        anchor.tap()
        expect(strip).to_be_visible()
        box = strip.bounding_box()
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
        strip.locator("[data-flag-dismiss]").tap()
        expect(strip).to_have_count(0)

        anchor.tap()
        expect(strip).to_be_visible()
        expect(strip).to_be_focused()
        page.keyboard.press("Escape")
        expect(strip).to_have_count(0)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_flip_phone_to_desktop_with_sheet_open(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, viewport=PHONE_VP)
    try:
        assert_phone(page)
        lesson = seeded["lessons"][0]
        _ptitle(page, lesson.pk).tap()
        _sheet_open(page)
        expect(_node_panel(page, lesson.pk)).to_be_visible()

        page.set_viewport_size(DESKTOP_VP)
        assert_desktop(page)
        _sheet_closed(page)
        state = page.evaluate(
            """() => {
              const sheet = document.querySelector('[data-sheet]');
              const head = document.querySelector('header.manage__head');
              return {
                treeInert: document.querySelector('.builder__tree').inert,
                sheetInert: sheet.inert,
                lock: document.documentElement.classList.contains('builder-sheet-lock'),
                bodyFixed: getComputedStyle(document.body).position === 'fixed',
                role: sheet.getAttribute('role'),
                modal: sheet.getAttribute('aria-modal'),
                label: sheet.getAttribute('aria-label'),
                legendsAfterHead: head.nextElementSibling
                  .matches('[data-phone-move="legends"]'),
                inHead: ['io', 'bulk'].map((k) => document.querySelector(
                  '[data-phone-move="' + k + '"]').parentElement === head),
              };
            }"""
        )
        assert state == {
            "treeInert": False,
            "sheetInert": False,
            "lock": False,
            "bodyFixed": False,
            "role": None,
            "modal": None,
            "label": None,
            "legendsAfterHead": True,
            "inHead": [True, True],
        }, state
        expect(
            page.locator('[data-panel] .panel[data-panel-for="course"]')
        ).to_be_visible()
        expect(page.locator("[data-panel]")).to_be_visible()
        assert _header_order(page) == HEADER_ORDER

        page.locator("li.tree__row").last.locator(
            ":scope > form.tree__rowhead a[data-delete]"
        ).focus()
        reached = False
        for _ in range(20):
            page.keyboard.press("Tab")
            if page.evaluate(
                "() => !!document.activeElement"
                " && !!document.activeElement.closest('[data-panel]')"
            ):
                reached = True
                break
        assert reached, "Tab never reached the desktop panel"
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_flip_phone_to_desktop_with_menu_open(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, viewport=PHONE_VP)
    try:
        assert_phone(page)
        lesson = seeded["lessons"][0]
        _more(page, lesson.pk).tap()
        expect(_menu(page)).to_be_visible()
        expect(_more(page, lesson.pk)).to_have_attribute("aria-expanded", "true")

        page.set_viewport_size(DESKTOP_VP)
        assert_desktop(page)
        expect(_menu(page)).to_have_attribute("hidden", "")
        expect(page.locator('.tree__more[aria-expanded="true"]')).to_have_count(0)

        page.set_viewport_size(PHONE_VP)
        assert_phone(page)
        _force_layout(page)
        expect(_menu(page)).to_have_attribute("hidden", "")
        expect(_menu(page)).to_be_hidden()
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_flip_desktop_to_phone_with_node_panel(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, viewport=DESKTOP_VP)
    try:
        assert_desktop(page)
        lesson = seeded["lessons"][0]
        _input(page, lesson.pk).click()
        expect(_node_panel(page, lesson.pk)).to_be_visible()

        page.set_viewport_size(PHONE_VP)
        assert_phone(page)
        _toolbar_in_sheet(page)
        _sheet_closed(page)
        assert (
            page.evaluate("() => document.querySelector('.builder__tree').inert")
            is False
        )
        expect(page.locator("[data-sheet-course]")).to_be_visible()
        expect(_node_panel(page, lesson.pk)).to_have_count(1)
        expect(_input(page, lesson.pk)).to_be_hidden()
        expect(_ptitle(page, lesson.pk)).to_be_visible()
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_flip_desktop_to_phone_with_picker(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, viewport=DESKTOP_VP)
    try:
        assert_desktop(page)
        lesson = seeded["lessons"][0]
        page.locator(f"#node-{lesson.pk} > form.tree__rowhead a[data-move]").click()
        expect(page.locator("[data-panel] form.move-picker")).to_be_visible()

        page.set_viewport_size(PHONE_VP)
        assert_phone(page)
        expect(page.locator("form.move-picker")).to_have_count(0)
        expect(page.locator(".moving")).to_have_count(0)
        _sheet_closed(page)
        _toolbar_in_sheet(page)
        expect(page.locator("[data-sheet-course]")).to_be_visible()
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_flip_desktop_to_phone_mid_rename(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, viewport=DESKTOP_VP)
    try:
        assert_desktop(page)
        lesson = seeded["lessons"][0]
        field = _input(page, lesson.pk)
        field.click()
        page.keyboard.press("End")
        page.keyboard.type("abc")
        assert field.input_value() == lesson.title + "abc"

        page.set_viewport_size(PHONE_VP)
        assert_phone(page)
        _force_layout(page)
        page.wait_for_timeout(300)
        assert posts == []
        expect(field).to_be_visible()
        expect(field).to_be_focused()
        assert field.input_value() == lesson.title + "abc"
        expect(_head(page, lesson.pk)).to_have_class(EDITING)
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_flip_phone_to_desktop_mid_rename(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, viewport=PHONE_VP)
    try:
        assert_phone(page)
        lesson = seeded["lessons"][0]
        field = _input(page, lesson.pk)
        _choose(page, lesson.pk, "rename")
        expect(field).to_be_focused()
        page.keyboard.type("xyz")  # startPhoneRename selected the whole title

        page.set_viewport_size(DESKTOP_VP)
        assert_desktop(page)
        _force_layout(page)
        page.wait_for_timeout(300)
        assert posts == []
        expect(field).to_be_focused()
        assert field.input_value() == "xyz"

        with page.expect_response(lambda r: _is_rename_post(r.request)):
            page.keyboard.press("Enter")
        assert len(posts) == 1
        expect(field).to_have_value("xyz")

        page.set_viewport_size(PHONE_VP)
        assert_phone(page)
        _force_layout(page)
        expect(_head(page, lesson.pk)).not_to_have_class(EDITING)
        expect(_ptitle(page, lesson.pk)).to_be_visible()
        expect(_ptitle(page, lesson.pk)).to_have_text("xyz")
        expect(field).to_be_hidden()
    finally:
        context.close()


@pytest.mark.django_db(transaction=True)
def test_landscape_split_flow_smoke(browser, live_server):
    context, page, seeded, posts = _open_at(browser, live_server, "landscape")
    try:
        assert_phone(page)
        lesson = seeded["lessons"][1]
        _ptitle(page, lesson.pk).tap()
        _sheet_open(page)
        expect(_node_panel(page, lesson.pk)).to_be_visible()
        height = page.evaluate(
            "() => document.querySelector('[data-sheet-shell]').offsetHeight"
        )
        assert height >= 0.9 * 410, height
    finally:
        context.close()
