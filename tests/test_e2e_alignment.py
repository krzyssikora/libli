"""Playwright e2e for per-block text alignment in the text-element RTE (the
flagship/motivating case). Marked e2e (run with `-m e2e`)."""

import os
import re

import pytest

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


def _latest_text_body():
    from courses.models import TextElement

    el = TextElement.objects.order_by("-id").first()
    return el.body if el else ""


@pytest.mark.django_db(transaction=True)
def test_center_second_block_only(page, live_server):
    """Two Enter-separated blocks; centering the 2nd stores ta-center on it alone,
    and the preview renders that class."""
    _make_pa_user("al_center")
    _login(page, live_server, "al_center")
    unit = _seed_course_and_unit("al_center", slug="al-center")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Skoro")
    page.keyboard.press("Enter")
    page.keyboard.type("Rownanie")  # caret now sits in the second block
    page.locator('[data-edit-slot] [data-cmd="aligncenter"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()

    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Rownanie").wait_for()

    body = _latest_text_body()
    assert body.count("ta-center") == 1, f"expected exactly one ta-center: {body!r}"
    assert "Rownanie" in body and "Skoro" in body
    # The rendered preview carries the class (sanitizer kept it AND it rendered).
    assert "ta-center" in preview.inner_html()

    # Prove placement: ta-center must wrap the SECOND block ("Rownanie"), not
    # the first ("Skoro"). A regression that scopes alignment to the wrong
    # block would still satisfy the count/membership checks above.
    m = re.search(r'<(\w+)[^>]*\bclass="ta-center"[^>]*>(.*?)</\1>', body, re.S)
    assert m and "Rownanie" in m.group(2), (
        f"ta-center not on the second block: {body!r}"
    )
    assert "Skoro" not in m.group(2), (
        f"first line leaked into the centered block: {body!r}"
    )

    assert preview.locator(".ta-center").inner_text().strip() == "Rownanie"


@pytest.mark.django_db(transaction=True)
def test_load_round_trip_preserves_ta_center(page, live_server):
    """A pre-stored ta-center block loads into the editor (classToStyle), and a
    re-save preserves exactly one ta-center (no dup, no leftover inline style)."""
    from courses.models import TextElement
    from tests.factories import add_element

    _make_pa_user("al_rt")
    _login(page, live_server, "al_rt")
    unit = _seed_course_and_unit("al_rt", slug="al-rt")
    el = TextElement.objects.create(body='<div class="ta-center">Centered</div>')
    add_element(unit, el)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # Open the row's editor (the real edit control is .el-act-edit in
    # _element_row.html), tweak, and save.
    page.locator(".el-row").first.locator(".el-act-edit").first.click()
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("!")  # unrelated edit
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_timeout(300)

    el.refresh_from_db()
    assert el.body.count("ta-center") == 1, f"round-trip corrupted: {el.body!r}"
    assert "text-align" not in el.body, f"leftover inline style: {el.body!r}"


@pytest.mark.django_db(transaction=True)
def test_bold_after_align_survives_sanitize(page, live_server):
    """Bolding AFTER an align click must still emit <b>/<strong> (styleWithCSS reset),
    so bold survives sanitization on save."""
    _make_pa_user("al_bold")
    _login(page, live_server, "al_bold")
    unit = _seed_course_and_unit("al_bold", slug="al-bold")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("BoldMe")
    page.locator('[data-edit-slot] [data-cmd="aligncenter"]').click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="bold"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.locator('[data-scope="preview"]').get_by_text("BoldMe").wait_for()

    body = _latest_text_body()
    assert ("<b>" in body) or ("<strong>" in body), f"bold lost: {body!r}"
    assert "<span" not in body, f"styleWithCSS leaked a span: {body!r}"
