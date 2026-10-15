"""Playwright e2e for the strikethrough button in the text-element RTE.
Marked e2e (run with `-m e2e`)."""

import os

import pytest
from playwright.sync_api import expect

from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_strikethrough_saves_as_s(page, live_server):
    """The browser emits <strike>; the toolbar must rename it to <s>, or the
    sanitizer drops the strike on save."""
    from courses.models import TextElement

    _make_pa_user("st_on")
    _login(page, live_server, "st_on")
    unit = _seed_course_and_unit("st_on", slug="st-on")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Skreslone")
    page.keyboard.press("Control+A")
    button = page.locator('[data-edit-slot] [data-cmd="strikethrough"]')
    button.click()
    page.wait_for_function(
        "() => document.querySelector('[data-edit-slot] [data-cmd=\"strikethrough\"]')"
        ".classList.contains('is-on')"
    )
    page.locator("[data-edit-slot] button[type='submit']").click()

    preview = page.locator('[data-scope="preview"]')
    preview.locator("s", has_text="Skreslone").wait_for()

    body = TextElement.objects.order_by("-id").first().body
    assert "<s>Skreslone</s>" in body, body
    assert "strike" not in body, body


@pytest.mark.django_db(transaction=True)
def test_strikethrough_toggles_off_stored_s(page, live_server):
    """A stored <s> reloads as struck and the button removes it again."""
    from courses.models import TextElement
    from tests.factories import add_element

    _make_pa_user("st_off")
    _login(page, live_server, "st_off")
    unit = _seed_course_and_unit("st_off", slug="st-off")
    el = TextElement.objects.create(body="<p><s>Skreslone</s></p>")
    add_element(unit, el)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(".el-row").first.locator(".el-act-edit").first.click()
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="strikethrough"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()

    # The preview showed the struck text BEFORE the save, so wait for the strike
    # to go rather than for the text to appear.
    preview = page.locator('[data-scope="preview"]')
    expect(preview.locator("s")).to_have_count(0)
    preview.get_by_text("Skreslone").wait_for()

    el.refresh_from_db()
    assert "Skreslone" in el.body, el.body
    assert "<s>" not in el.body and "strike" not in el.body, el.body
