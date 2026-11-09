"""Playwright e2e for the superscript and subscript buttons.

The browser's own superscript/subscript commands produce the tags, so these run
the real gesture in each editor that has its own command path. Marked e2e."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit
from tests.test_e2e_filltable import _editor_context
from tests.test_e2e_filltable import _goto_editor
from tests.test_e2e_filltable import _open_edit
from tests.test_e2e_filltable import _seed_filltable_for_images
from tests.test_e2e_table_editor import _add_table
from tests.test_e2e_table_editor import _save
from tests.test_e2e_table_editor import _unit

pytestmark = pytest.mark.e2e

CASES = [("superscript", "sup"), ("subscript", "sub")]
IS_ON = re.compile(r"(^|\s)is-on(\s|$)")
CELL = "[data-edit-slot] [data-table-grid] td[contenteditable]"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("cmd", "tag"), CASES)
def test_prose_button_formats_only_the_selection_and_saves(page, live_server, cmd, tag):
    from courses.models import TextElement

    user = f"ss_prose_{tag}"
    _make_pa_user(user)
    _login(page, live_server, user)
    unit = _seed_course_and_unit(user, slug=f"ss-prose-{tag}")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("H2")
    page.keyboard.press("Shift+ArrowLeft")

    button = page.locator(f'[data-edit-slot] [data-cmd="{cmd}"]')
    button.click()
    expect(button).to_have_class(IS_ON)
    page.locator("[data-edit-slot] button[type='submit']").click()

    page.locator(f'[data-scope="preview"] {tag}', has_text="2").wait_for()
    body = TextElement.objects.order_by("-id").first().body
    assert f"H<{tag}>2</{tag}>" in body, body


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("cmd", "tag"), CASES)
def test_prose_button_removes_a_stored_tag(page, live_server, cmd, tag):
    from courses.models import TextElement
    from tests.factories import add_element

    user = f"ss_off_{tag}"
    _make_pa_user(user)
    _login(page, live_server, user)
    unit = _seed_course_and_unit(user, slug=f"ss-off-{tag}")
    el = TextElement.objects.create(body=f"<p>H<{tag}>2</{tag}></p>")
    add_element(unit, el)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(".el-row").first.locator(".el-act-edit").first.click()
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.press("End")
    page.keyboard.press("Shift+ArrowLeft")
    button = page.locator(f'[data-edit-slot] [data-cmd="{cmd}"]')
    expect(button).to_have_class(IS_ON)
    button.click()
    page.locator("[data-edit-slot] button[type='submit']").click()

    # The preview showed the tag BEFORE the save, so wait for it to go.
    expect(page.locator(f'[data-scope="preview"] {tag}')).to_have_count(0)
    el.refresh_from_db()
    assert "H2" in el.body, el.body
    assert f"<{tag}>" not in el.body, el.body


@pytest.mark.django_db(transaction=True)
def test_switching_from_superscript_to_subscript_replaces_it(page, live_server):
    from courses.models import TextElement

    _make_pa_user("ss_swap")
    _login(page, live_server, "ss_swap")
    unit = _seed_course_and_unit("ss_swap", slug="ss-swap")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("H2")
    page.keyboard.press("Shift+ArrowLeft")

    sup = page.locator('[data-edit-slot] [data-cmd="superscript"]')
    sub = page.locator('[data-edit-slot] [data-cmd="subscript"]')
    sup.click()
    expect(sup).to_have_class(IS_ON)
    sub.click()
    expect(sub).to_have_class(IS_ON)
    expect(sup).not_to_have_class(IS_ON)
    page.locator("[data-edit-slot] button[type='submit']").click()

    page.locator('[data-scope="preview"] sub', has_text="2").wait_for()
    body = TextElement.objects.order_by("-id").first().body
    assert "H<sub>2</sub>" in body, body


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("cmd", "tag"), CASES)
def test_table_cell_button_lights_up_and_saves(page, live_server, cmd, tag):
    from courses.models import TableElement

    user = f"ss_tbl_{tag}"
    _make_pa_user(user)
    _login(page, live_server, user)
    unit = _unit(user, f"ss-tbl-{tag}")
    _add_table(page, live_server, unit)

    page.locator(CELL).first.click()
    page.keyboard.type("CO2")
    page.keyboard.press("Shift+ArrowLeft")
    button = page.locator(f"[data-edit-slot] [data-table-toolbar] [data-cmd='{cmd}']")
    button.click()
    expect(button).to_have_class(IS_ON)
    _save(page)

    html = TableElement.objects.order_by("-id").first().data["cells"][0][0]["html"]
    assert html == f"CO<{tag}>2</{tag}>"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("cmd", "tag"), CASES)
def test_filltable_cell_button_lights_up_and_saves(page, live_server, cmd, tag):
    # Twin of the table test: test_editor_twin_drift pins shared function BODIES,
    # not this file's click branch.
    user = f"ss_ft_{tag}"
    unit, _a, _b = _editor_context(page, live_server, user, f"ss-ft-{tag}")
    element = _seed_filltable_for_images(unit)
    _goto_editor(page, live_server, user, unit)
    _open_edit(page, element.pk)

    page.locator(CELL).first.click()
    page.keyboard.press("End")
    page.keyboard.press("Shift+ArrowLeft")
    button = page.locator(f"[data-edit-slot] [data-table-toolbar] [data-cmd='{cmd}']")
    button.click()
    expect(button).to_have_class(IS_ON)
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]", state="detached")

    filltable = element.content_object
    filltable.refresh_from_db()
    assert filltable.data["cells"][0][0]["html"] == f"on<{tag}>e</{tag}>"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("tag", ["sup", "sub"])
def test_the_tag_is_rendered_small_without_spreading_its_line(page, live_server, tag):
    from courses.models import TextElement
    from tests.factories import add_element

    user = f"ss_css_{tag}"
    _make_pa_user(user)
    _login(page, live_server, user)
    unit = _seed_course_and_unit(user, slug=f"ss-css-{tag}")
    add_element(
        unit, TextElement.objects.create(body=f"<p>m</p><p>m<{tag}>2</{tag}></p>")
    )

    page.goto(_editor_url(live_server, unit))
    mark = page.locator(f'[data-scope="preview"] {tag}')
    mark.wait_for()
    metrics = mark.evaluate(
        """el => {
          const with_mark = el.parentElement;
          const plain = with_mark.previousElementSibling;
          const s = getComputedStyle(el);
          return {
            with_mark: with_mark.getBoundingClientRect().height,
            plain: plain.getBoundingClientRect().height,
            size: parseFloat(s.fontSize),
            parent_size: parseFloat(getComputedStyle(with_mark).fontSize),
            position: s.position,
          };
        }"""
    )
    assert metrics["with_mark"] == pytest.approx(metrics["plain"], abs=0.01), metrics
    assert metrics["size"] == pytest.approx(0.75 * metrics["parent_size"], abs=0.1), (
        metrics
    )
    # The mat-pp course theme carries `sup { top: -1.5em !important }`, inert only
    # while the element stays statically positioned.
    assert metrics["position"] == "static", metrics
