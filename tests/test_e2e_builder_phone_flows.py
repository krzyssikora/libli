"""Phone notices as a toast (Task 5). Real phone contexts; e2e -- foreground."""

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
