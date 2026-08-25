"""Playwright e2e for the two callout-body defects, driven through the REAL RTE.

The trigger is a browser behaviour, so no server-side test can reach it: clearing a
contenteditable with Ctrl+A + Delete leaves `<p><br></p>` behind, and it is that
markup -- not an empty string -- that reached `body` and made the callout render a
blank line while the editor row claimed it had text. Backspacing every character
instead leaves "", which is why the defect only shows up on the select-all route.

Marked e2e (excluded from the default run; run with `-m e2e`).
"""

import os

import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Copied, not imported: a module-level fixture is invisible outside its module.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open_callout_form(page, join_pk):
    """Open the callout's edit form and wait for the RTE surface to mount.

    Waits on `.rte-surface`, the div text_toolbar.js INSERTS beside the textarea --
    not on the textarea itself, which is in the swapped fragment immediately and
    would let the test type into an unenhanced field."""
    page.locator(f"[data-element='{join_pk}'] .el-act-edit").click()
    surface = page.locator(f"[data-element='{join_pk}'] .rte-surface").first
    surface.wait_for(state="visible")
    return surface


def _save(page, join_pk):
    page.locator(
        f"[data-element='{join_pk}'] [data-edit-slot] button[type='submit']"
    ).first.click()
    # The save swaps the editor fragment; the form collapsing is the completion
    # signal. Waiting on a fixed timeout here would sample a race.
    page.locator(f"[data-element='{join_pk}'] .rte-surface").first.wait_for(
        state="detached"
    )


@pytest.mark.django_db(transaction=True)
def test_clearing_the_rte_leaves_no_blank_line_and_no_has_text_claim(page, live_server):
    """Defect 1, the user's exact gesture: type text into a callout, save, clear it
    with Ctrl+A + Delete, save again."""
    username = "pa-callout-body"
    _make_pa_user(username)
    unit = _seed_course_and_unit(username, slug="callout-body", unit_title="Body")
    _login(page, live_server, username)

    callout = CalloutElement.objects.create(kind="example")
    join = add_element(unit, callout)
    page.goto(_editor_url(live_server, unit))

    surface = _open_callout_form(page, join.pk)
    surface.click()
    page.keyboard.type("Some text that will be removed")
    _save(page, join.pk)
    callout.refresh_from_db()
    # Precondition, asserted rather than assumed: if typing never reached the
    # textarea, every assertion below would pass on an always-empty body.
    assert "Some text" in callout.body

    surface = _open_callout_form(page, join.pk)
    surface.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    # The surface must actually be blank markup, not "" -- otherwise this test is
    # exercising the backspace route and cannot fail on the reported defect.
    assert page.evaluate(
        "document.querySelector('.rte-surface').innerHTML"
    ).strip() in ("<p><br></p>", "<div><br></div>", "<br>")
    _save(page, join.pk)

    callout.refresh_from_db()
    assert callout.body == ""
    # The editor's claim, and the blank line, are INDEPENDENT consequences of the
    # same stored value -- both are asserted, because a fix to one alone is possible.
    assert page.locator(".el-bodyrow").count() == 0
    assert "has text" not in page.content()
    assert page.locator(".callout__body").count() == 0


@pytest.mark.django_db(transaction=True)
def test_the_editor_shows_the_callout_s_text_alongside_its_children(page, live_server):
    """Defect 2: with a child present the old hint was unreachable, so the editor
    showed nothing at all about the callout's own text."""
    username = "pa-callout-both"
    _make_pa_user(username)
    unit = _seed_course_and_unit(username, slug="callout-both", unit_title="Both")
    _login(page, live_server, username)

    callout = CalloutElement.objects.create(
        kind="example", body="<p>Consider a right triangle.</p>"
    )
    join = add_element(unit, callout)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>NESTED-CHILD</p>"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    page.goto(_editor_url(live_server, unit))

    row = page.locator(f"[data-element='{join.pk}'] .el-bodyrow").first
    row.wait_for(state="visible")
    assert "Consider a right triangle." in row.inner_text()

    # It must sit ABOVE the children list, mirroring where the body renders on the
    # student page. Compared by geometry, not DOM order: a rule that visually
    # reorders them (flex `order`, say) would leave source order asserting nothing.
    body_box = row.bounding_box()
    child_box = page.locator(
        f"[data-element='{join.pk}'] .el-row__callout .el-row"
    ).first.bounding_box()
    assert body_box["y"] < child_box["y"]

    # And it opens THIS callout's own form -- the only route to the body now that a
    # child exists. Asserted by the form actually mounting, not by the attributes.
    row.click()
    page.locator(f"[data-element='{join.pk}'] .rte-surface").first.wait_for(
        state="visible"
    )
