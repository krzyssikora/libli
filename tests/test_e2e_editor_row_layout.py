"""Playwright e2e: at the editor pane's 1130px floor, does the Task 8 "applet size
unknown" badge push the action bar onto an extra wrapped line or outside the card?

Marked e2e (excluded from the default run; run with `-m e2e`)."""

import os

import pytest

from courses.models import IframeElement
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


@pytest.mark.django_db(transaction=True)
def test_badge_does_not_grow_the_editor_row_at_the_pane_floor(page, live_server):
    """At 1130px -- the editor pane's floor, the width the existing .el-actions
    overflow was measured at -- adding the badge must not push the action bar onto an
    extra wrapped line or grow the row.

    .el-actions already carries flex-wrap: wrap (editor.css:572), the fix for the
    measured 41px escape, so the badge's cost is VERTICAL rather than horizontal.
    """
    page.set_viewport_size({"width": 1130, "height": 900})
    username = "pa-layout"
    _make_pa_user(username)
    unit = _seed_course_and_unit(username, slug="badge-layout", unit_title="Layout")
    _login(page, live_server, username)

    # Build BOTH elements directly via the ORM -- no form, so no dependence on
    # IframeElementForm or on GEOGEBRA_API_LOOKUP, and no possibility of a live GET.
    # Identical titles and identical element type mean the ONLY difference between the
    # two rows is the badge, so a measured height delta has exactly one possible cause.
    canonical = "https://www.geogebra.org/material/iframe/id/dcjktevj"
    badged = IframeElement.objects.create(url=canonical, title="Identical title")
    control = IframeElement.objects.create(
        url=canonical, title="Identical title", width=880, height=660
    )
    # KEEP THE JOIN ROWS: _element_row.html:302 emits data-element="{{ el.pk }}" where
    # `el` is the Element JOIN row, never the IframeElement. Locating on the concrete
    # pk would match nothing -- or, worse, a DIFFERENT element's row whose join pk
    # happens to collide, silently measuring the wrong two rows.
    badged_join = add_element(unit, badged)
    control_join = add_element(unit, control)

    page.goto(_editor_url(live_server, unit))

    badged_row = page.locator(f"[data-element='{badged_join.pk}'] .el-row__top")
    control_row = page.locator(f"[data-element='{control_join.pk}'] .el-row__top")
    badged_actions = badged_row.locator(".el-actions")
    control_actions = control_row.locator(".el-actions")

    # 1 (load-bearing): the badge changes neither the row height nor the action bar's.
    assert badged_row.bounding_box()["height"] == control_row.bounding_box()["height"]
    assert (
        badged_actions.bounding_box()["height"]
        == control_actions.bounding_box()["height"]
    )
    # Count wrapped lines by distinct child-button top offsets. Do NOT use
    # getClientRects().length on .el-actions -- it is inline-flex AND a flex item, so
    # it is blockified and the count is 1 on a broken build too.
    wrapped_lines = badged_actions.evaluate(
        "el => new Set([...el.children]"
        ".map(c => Math.round(c.getBoundingClientRect().top))).size"
    )
    assert wrapped_lines == control_actions.evaluate(
        "el => new Set([...el.children]"
        ".map(c => Math.round(c.getBoundingClientRect().top))).size"
    )

    # 2 (load-bearing): nothing overflows .el-row__top.
    assert badged_row.evaluate("el => el.scrollWidth <= el.clientWidth")

    # 3 (load-bearing): the direct regression guard on the original 41px escape --
    # the action bar's right edge stays inside the card.
    card = page.locator(f"[data-element='{badged_join.pk}']")
    actions_box, card_box = badged_actions.bounding_box(), card.bounding_box()
    assert (
        actions_box["x"] + actions_box["width"] <= card_box["x"] + card_box["width"] + 1
    )

    # Assertion 4 (the original text-badge "ellipsised rather than pushed" check) is
    # DELETED, not weakened. It only made sense against the text badge Step 2 started
    # with. The layout fix taken here (see Step 2 in the PR/report) replaced that
    # shrinking text with a fixed 14x14 icon plus a nested .visually-hidden label, so
    # there is no longer any text to ellipsise -- clientWidth < scrollWidth is now
    # FALSE on every correct build (confirmed: it failed here before deletion), which
    # is exactly the "cannot discriminate, so delete rather than weaken" case the
    # plan's own rule calls for.
    badge = badged_row.locator(".el-row__flag")

    # 4 (load-bearing, replaces old 5): the warning icon itself is actually painted,
    # not display:none/0x0 -- readability for an icon means "visible", not "wide".
    icon_box = badge.locator(".ic").bounding_box()
    assert icon_box["width"] > 0
    assert icon_box["height"] > 0

    # 5 (load-bearing): the accessible label text survives for screen readers. It
    # lives in a NESTED .visually-hidden span (position: absolute -- see editor.css),
    # so it contributes nothing to the row's flex layout, but it must still be
    # present verbatim. Playwright reports .visually-hidden as VISIBLE (a clipped
    # element still has a non-empty box), so to_be_visible() cannot be used here --
    # check the text content directly instead.
    hidden_label = badge.locator(".visually-hidden")
    assert hidden_label.text_content() == "applet size unknown"
