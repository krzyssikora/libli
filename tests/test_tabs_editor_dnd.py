"""Static-contract + e2e regression tests for four editor drag/state fixes:

  1. The drop-line indicator is a visible bar, not a 2px hairline.
  2. Drag-drop reorder preserves the editor pane scroll (was resetting to top).
  3. Dragging near a pane edge auto-scrolls, so an off-screen target is reachable.
  4. A tab's open/closed state survives a fragment rebuild (was always re-opening
     the first tab, discarding which tab the author had open).

The mechanisms are pinned as static-contract assertions (fast, drift-proof, the same
style as test_tabs_css.py) plus one e2e that drives the real open-tab-survives-edit
gesture. The two drag behaviours were reproduced by hand during the fix; the static
contracts guard them from silently regressing.
"""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EDITOR_JS = ROOT / "courses/static/courses/js/editor.js"
EDITOR_DND_JS = ROOT / "courses/static/courses/js/editor_dnd.js"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"
ELEMENT_ROW = ROOT / "templates/courses/manage/editor/_element_row.html"


def test_details_carry_a_stable_tab_id_key():
    """State preservation keys each <details> by (element pk, tab id); the tab id
    must be on the details element."""
    html = ELEMENT_ROW.read_text(encoding="utf-8")
    assert re.search(r"<details[^>]*\bdata-tab-id=", html)


def test_editor_preserves_open_tabs_across_a_swap():
    js = EDITOR_JS.read_text(encoding="utf-8")
    # applyFragments must read + restore the open <details.tabs-rows> state, keyed by
    # the tab id, or every rebuild snaps back to the template's first-open default.
    assert "tabs-rows" in js
    assert "data-tab-id" in js


def test_editor_preserves_pane_scroll_across_a_swap():
    js = EDITOR_JS.read_text(encoding="utf-8")
    assert "scrollTop" in js  # capture/restore the pane-body scroll around the swap


def test_editor_exposes_applyfragments_for_the_dnd_handler():
    js = EDITOR_JS.read_text(encoding="utf-8")
    assert "__libliApplyFragments" in js


def test_dnd_drop_routes_through_applyfragments():
    """The drop handler must reuse applyFragments (which re-inits galleries/tabs/RTE
    and restores scroll + open tabs) instead of a bespoke replaceWith that swaps the
    panes but skips all of that."""
    js = EDITOR_DND_JS.read_text(encoding="utf-8")
    assert "__libliApplyFragments" in js


def test_dnd_autoscrolls_near_pane_edges():
    """Dragging toward an off-screen target must auto-scroll the pane; dragover stops
    firing when the pointer is still, so an animation-frame loop is required."""
    js = EDITOR_DND_JS.read_text(encoding="utf-8")
    assert "requestAnimationFrame" in js
    assert "pane-body" in js or "paneBody" in js


def test_drop_line_is_a_visible_bar_not_a_hairline():
    """A 2px border-top hairline is what made 'where will it land' unreadable. The
    indicator must have real height."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    m = re.search(r"\.el-drop-line\s*\{([^}]*)\}", css)
    assert m, "no .el-drop-line rule"
    block = m.group(1)
    hm = re.search(r"height:\s*(\d+)px", block)
    assert hm and int(hm.group(1)) >= 3, f".el-drop-line too thin: {block!r}"


# --------------------------------------------------------------------------- e2e


pytestmark_e2e = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    from tests.factories import TEST_PASSWORD

    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.e2e
@pytest.mark.django_db(transaction=True)
def test_open_tab_survives_an_edit_elsewhere(page, live_server):
    """Symptom 4: close tab 1 / open tab 2, then edit another element. After the
    rebuild the author's tab state must persist, NOT snap back to first-open."""
    from courses.models import Element
    from courses.models import TabsElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    pa = _make_pa_user("tabstate")
    course = CourseFactory(slug="tab-state", owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="child in tab 2"),
        parent=join,
        tab_id="t000002",
    )
    # A separate top-level element to edit (its edit triggers the pane rebuild).
    other = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="top level")
    )

    _login(page, live_server, "tabstate")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs')

    d1 = page.locator('[data-scope="editor"] details.tabs-rows[data-tab-id="t000001"]')
    d2 = page.locator('[data-scope="editor"] details.tabs-rows[data-tab-id="t000002"]')
    # Seed state: first tab open (default), second closed. Flip them.
    d1.locator("summary").click()  # close first
    d2.locator("summary").click()  # open second
    assert d1.evaluate("e => e.open") is False
    assert d2.evaluate("e => e.open") is True

    # Edit the top-level element -> full pane rebuild.
    page.locator(
        f'[data-scope="editor"] .element-list > '
        f'[data-element="{other.pk}"] .el-act-edit'
    ).click()
    page.wait_for_selector('[data-scope="editor"] [data-edit-slot] form')

    # Tab state must be preserved, not reset to first-open.
    d1 = page.locator('[data-scope="editor"] details.tabs-rows[data-tab-id="t000001"]')
    d2 = page.locator('[data-scope="editor"] details.tabs-rows[data-tab-id="t000002"]')
    assert d1.evaluate("e => e.open") is False, "first tab was force-reopened"
    assert d2.evaluate("e => e.open") is True, "second (author-opened) tab was closed"
