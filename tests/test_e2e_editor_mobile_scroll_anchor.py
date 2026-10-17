"""Stacked (phone) unit editor: an element op keeps the author's place on screen.

Below 70rem the editor panes stop being scroll containers and the WINDOW scrolls
(editor.css), so editor.js's pane-only alignment silently did nothing and the row
the author just acted on drifted by the height of whatever it moved past. The fix
(editor.js, form[data-op] handler) records anchor candidates just before the swap
and restores the winner with window.scrollBy. Spec:
docs/superpowers/specs/2026-10-17-mobile-editor-scroll-anchor-design.md.

Every seed is built so the asserted position is reachable by construction: each
test asserts, before its click, that the window has room to scroll the expected
correction in the expected direction (_assert_unclamped), so neither end-of-document
clamp can make a correct build fail or a broken one pass.
"""

import os

import pytest

from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}
EDITOR = '[data-scope="editor"]'


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# --- seeding ---------------------------------------------------------------------


def _seed_texts(unit, n, prefix):
    from courses.models import TextElement
    from tests.factories import add_element

    return [
        add_element(unit, TextElement.objects.create(body=f"<p>{prefix} {i}</p>"))
        for i in range(n)
    ]


def _seed_callout(unit, children, parent=None):
    """A callout (top-level, or nested under the `parent` join) with `children`
    short text children. A text row is a one-line label in the editor, so a
    callout's height is the only seeded way to get a TALL row."""
    from courses.models import SINGLE_SLOT_ID
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import add_element

    obj = CalloutElement.objects.create(kind="note", heading="Box")
    if parent is None:
        co = add_element(unit, obj)
    else:
        co = Element.objects.create(
            unit=unit, content_object=obj, parent=parent, tab_id=SINGLE_SLOT_ID
        )
    kids = [
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>child {i}</p>"),
            parent=co,
            tab_id=SINGLE_SLOT_ID,
        )
        for i in range(children)
    ]
    return co, kids


# --- page helpers ----------------------------------------------------------------


def _open(page, live_server, user, viewport=PHONE, view="editor"):
    _make_pa_user(user)
    _login(page, live_server, user)
    return lambda unit: _goto(page, live_server, unit, viewport, view)


def _goto(page, live_server, unit, viewport, view):
    page.set_viewport_size(viewport)
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector(EDITOR)
    page.locator(f'[data-view="{view}"]').click()
    _settle(page)


def _settle(page):
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


PANE_JS = "document.querySelector('[data-scope=\"editor\"]')"
BODY_JS = "document.querySelector('[data-scope=\"editor\"] .pane-body')"
# Element row by data-element id, inside the editor pane.
ROW_JS = (
    "document.querySelector("
    "'[data-scope=\"editor\"] .el-row[data-element=\"' + id + '\"]')"
)


def _arm_swap(page):
    page.evaluate("() => { window.__oldPane = " + PANE_JS + "; }")


def _wait_swap(page):
    page.wait_for_function(
        "() => { const p = document.querySelector('[data-scope=\"editor\"]');"
        " return p && p !== window.__oldPane; }"
    )
    _settle(page)


def _swap_click(page, locator):
    _arm_swap(page)
    locator.click()
    _wait_swap(page)


ROW_RECT = (
    "(id) => { const r = "
    + ROW_JS
    + """;
  if (!r) return null;
  const b = r.getBoundingClientRect();
  return {top: b.top, bottom: b.bottom, height: b.height};
}"""
)


def _rect(page, eid):
    return page.evaluate(ROW_RECT, str(eid))


def _row_top(page, eid):
    return _rect(page, eid)["top"]


def _row_control(page, eid, selector):
    return page.locator(
        f'{EDITOR} .el-row[data-element="{eid}"] > .el-row__head {selector}'
    ).first


def _up(page, eid):
    return _row_control(page, eid, 'button[name="direction"][value="up"]')


def _select(page, eid):
    return _row_control(page, eid, 'button[aria-label="Select"]')


def _paste_form(page, parent_pk):
    return page.locator(
        f'{EDITOR} form[data-op="element-paste"]'
        f':has(input[name="parent"][value="{parent_pk}"])'
    ).first


def _scroll_by(page, dy):
    page.evaluate("(dy) => window.scrollBy(0, dy)", dy)
    _settle(page)


def _scroll_window_to_row(page, eid, y_in_viewport):
    _scroll_by(page, _row_top(page, eid) - y_in_viewport)


def _scroll_box_to(page, locator, y_in_viewport):
    _scroll_by(page, locator.bounding_box()["y"] - y_in_viewport)


def _inner_h(page):
    return page.evaluate(
        "() => (window.visualViewport && visualViewport.height) || innerHeight"
    )


def _assert_on_screen(page, locator):
    box = locator.bounding_box()
    assert box is not None
    assert 0 <= box["y"] < _inner_h(page), f"control not on-screen: {box}"


def _assert_unclamped(page, max_up, max_down):
    y, room = page.evaluate(
        "() => [scrollY, document.documentElement.scrollHeight - innerHeight - scrollY]"
    )
    assert y >= max_up + 100, f"scrollY {y} cannot absorb an upward fix of {max_up}"
    assert room >= max_down + 100, f"room below {room} < downward fix {max_down}"


FIRST_VISIBLE = """() => {
  const vh = (window.visualViewport && visualViewport.height) || innerHeight;
  const sel = '[data-scope="editor"] .el-row[data-element]';
  for (const r of document.querySelectorAll(sel)) {
    const vis = r.checkVisibility
      ? r.checkVisibility() : r.getClientRects().length > 0;
    const b = r.getBoundingClientRect();
    if (vis && b.height > 0 && b.top >= 0 && b.top < vh) {
      return r.getAttribute('data-element');
    }
  }
  return null;
}"""


def _first_visible_row_id(page):
    return page.evaluate(FIRST_VISIBLE)


def _put_row_top_just_above(page, eid, control):
    """Scroll so the row's top is a few px ABOVE the viewport while `control`
    (a button in the row's head) is still on-screen."""
    box = control.bounding_box()
    delta = box["y"] - _row_top(page, eid)
    assert delta > 2, f"control sits {delta}px below the row top; cannot straddle"
    _scroll_by(page, _row_top(page, eid) + min(5, delta - 1))
    assert _row_top(page, eid) < 0
    _assert_on_screen(page, control)


# --- phone: candidate 2 / catch-all / safety net ---------------------------------


@pytest.mark.django_db(transaction=True)
def test_phone_up_past_tall_container_keeps_row(page, live_server):
    """(a) ↑ past a callout holding 8 children keeps the row where it was tapped
    (master: ~-730px)."""
    go = _open(page, live_server, "msa_a")
    unit = _seed_course_and_unit("msa_a", slug="msa-a")
    _seed_texts(unit, 10, "lead")
    co, _ = _seed_callout(unit, 8)
    target = _seed_texts(unit, 1, "TARGET")[0]
    _seed_texts(unit, 25, "tail")
    go(unit)

    _scroll_window_to_row(page, target.pk, PHONE["height"] / 2)
    _assert_unclamped(page, _rect(page, co.pk)["height"], 0)
    btn = _up(page, target.pk)
    _assert_on_screen(page, btn)
    t0 = _row_top(page, target.pk)
    _swap_click(page, btn)
    assert abs(_row_top(page, target.pk) - t0) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_up_with_row_top_just_above_viewport(page, live_server):
    """(b2) The row's top is a few px above the viewport but its ↑ is visible:
    the head-op rule still holds the row."""
    go = _open(page, live_server, "msa_b2")
    unit = _seed_course_and_unit("msa_b2", slug="msa-b2")
    _seed_texts(unit, 10, "lead")
    co, _ = _seed_callout(unit, 8)
    target = _seed_texts(unit, 1, "TARGET")[0]
    _seed_texts(unit, 25, "tail")
    go(unit)

    _scroll_window_to_row(page, target.pk, PHONE["height"] / 2)
    btn = _up(page, target.pk)
    _put_row_top_just_above(page, target.pk, btn)
    _assert_unclamped(page, _rect(page, co.pk)["height"], 0)
    t0 = _row_top(page, target.pk)
    _swap_click(page, btn)
    assert abs(_row_top(page, target.pk) - t0) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_repeated_up_keeps_row(page, live_server):
    """(b) Four ↑ presses in a row: the ↑ button stays under the thumb. Each press
    is compared with the top recorded just before THAT press."""
    go = _open(page, live_server, "msa_b")
    unit = _seed_course_and_unit("msa_b", slug="msa-b")
    lead = _seed_texts(unit, 10, "lead")
    m = _seed_texts(unit, 1, "MOVER")[0]
    _seed_texts(unit, 25, "tail")
    go(unit)

    _scroll_window_to_row(page, m.pk, PHONE["height"] / 2)
    for _ in range(4):
        btn = _up(page, m.pk)
        _assert_on_screen(page, btn)
        _assert_unclamped(page, _rect(page, lead[0].pk)["height"], 0)
        t = _row_top(page, m.pk)
        _swap_click(page, btn)
        assert abs(_row_top(page, m.pk) - t) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_select_keeps_tapped_row(page, live_server):
    """(l) Select (⊹) inserts the banner above every row and grows the callout by
    its paste buttons; the tapped row P stays put. P is not the first visible row,
    so a build that leaves select to the catch-all shifts P by the callout growth."""
    go = _open(page, live_server, "msa_l")
    unit = _seed_course_and_unit("msa_l", slug="msa-l")
    _seed_texts(unit, 10, "lead")
    co, _ = _seed_callout(unit, 2)
    p = _seed_texts(unit, 1, "P")[0]
    _seed_texts(unit, 25, "tail")
    go(unit)

    _scroll_window_to_row(page, co.pk, 10)
    first = _first_visible_row_id(page)
    assert first == str(co.pk), first
    assert 0 < _row_top(page, p.pk) < PHONE["height"]
    _assert_unclamped(page, 0, 250)
    btn = _select(page, p.pk)
    _assert_on_screen(page, btn)
    t0 = _row_top(page, p.pk)
    _swap_click(page, btn)
    assert abs(_row_top(page, p.pk) - t0) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_cancel_keeps_first_visible_row(page, live_server):
    """(d) Cancelling the clipboard removes the banner and every paste button; the
    first visible row (the catch-all's first record) stays put. The banner sits
    above every row, so the room above it is page chrome, not seeded rows."""
    go = _open(page, live_server, "msa_d")
    unit = _seed_course_and_unit("msa_d", slug="msa-d")
    texts = _seed_texts(unit, 4, "head")
    _seed_texts(unit, 25, "tail")
    go(unit)

    _swap_click(page, _select(page, texts[0].pk))
    banner_h = page.evaluate(
        "() => { const b = document.getElementById('clip-banner');"
        " const cs = getComputedStyle(b);"
        " return b.getBoundingClientRect().height + parseFloat(cs.marginTop)"
        " + parseFloat(cs.marginBottom); }"
    )
    cancel = page.locator('#clip-banner button[aria-label="Cancel selection"]')
    cancel_doc_y = page.evaluate(
        "() => document.querySelector('#clip-banner button')"
        ".getBoundingClientRect().top + scrollY"
    )
    assert cancel_doc_y >= banner_h + 100, (cancel_doc_y, banner_h)
    _scroll_by(page, banner_h + 100 - page.evaluate("scrollY"))
    _assert_on_screen(page, cancel)
    _assert_unclamped(page, banner_h, 0)
    r = _first_visible_row_id(page)
    assert r
    t0 = _row_top(page, r)
    _swap_click(page, cancel)
    assert abs(_row_top(page, r) - t0) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_delete_tall_container_keeps_trailing_row(page, live_server):
    """(i) Deleting a callout whose top is just above the viewport keeps the
    first trailing row still. Five or more of its children are on-screen, so the
    catch-all must not spend its cap on rows the delete removes."""
    go = _open(page, live_server, "msa_i")
    unit = _seed_course_and_unit("msa_i", slug="msa-i")
    _seed_texts(unit, 15, "lead")
    co, kids = _seed_callout(unit, 5)
    tail = _seed_texts(unit, 25, "tail")
    go(unit)

    _scroll_window_to_row(page, co.pk, PHONE["height"] / 3)
    btn = _row_control(page, co.pk, 'form[data-op="element-delete"] button')
    _put_row_top_just_above(page, co.pk, btn)
    vh = PHONE["height"]
    on = [k for k in kids if 0 <= _row_top(page, k.pk) < vh]
    assert len(on) >= 5, len(on)
    d = next(t for t in tail if 0 <= _row_top(page, t.pk) < vh)
    _assert_unclamped(page, _rect(page, co.pk)["height"], 0)
    t0 = _row_top(page, d.pk)
    _swap_click(page, btn)
    assert abs(_row_top(page, d.pk) - t0) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_nested_create_lands_at_pane_top(page, live_server):
    """(e) A create inside a callout, saved from a form ~2 viewports tall with no
    row top on-screen: there is no anchor, and the collapsed new row would land
    entirely above the viewport. The safety net aligns it to the pane padding.
    The form's top is <= -viewport and the trailing content exceeds the form, so
    neither clamp can bring the row into view by accident."""
    go = _open(page, live_server, "msa_e")
    unit = _seed_course_and_unit("msa_e", slug="msa-e")
    co, _ = _seed_callout(unit, 2)
    _seed_texts(unit, 70, "tail")
    go(unit)

    corow = page.locator(f'{EDITOR} .el-row[data-element="{co.pk}"]')
    menu = corow.locator("[data-add-menu].addwrap--nested").first
    menu.locator("[data-add-toggle]").click()
    menu.locator("[data-add-type='text']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    surface = corow.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Nested new text")
    form = corow.locator("[data-edit-slot] form[data-op='element-save']").first
    vh = _inner_h(page)
    while form.bounding_box()["height"] < 2 * vh:
        for _ in range(10):
            page.keyboard.press("Enter")
    save = form.locator("button[type=submit]").last
    _scroll_box_to(page, save, vh - 60)
    _assert_on_screen(page, save)
    box = form.bounding_box()
    assert box["y"] <= -vh, box
    assert _first_visible_row_id(page) is None
    room = page.evaluate(
        "() => document.documentElement.scrollHeight - (scrollY + innerHeight)"
    )
    assert room >= box["height"] + 100, (room, box["height"])
    _swap_click(page, save)
    new = page.evaluate(
        "() => document.querySelector('[data-scope=\"editor\"]')"
        ".getAttribute('data-saved-element')"
    )
    assert new
    pad = page.evaluate(
        "() => parseFloat(getComputedStyle("
        "document.querySelector('[data-scope=\"editor\"] .pane-body')).paddingTop)"
    )
    assert abs(_row_top(page, new) - pad) <= 2


@pytest.mark.django_db(transaction=True)
def test_phone_split_mode_keeps_row_after_preview_timers(page, live_server):
    """(k) Split is the default view; on a phone the preview renders below the
    editor. The row holds after the swap AND after scrollPreviewTo's 500 ms timer
    (the 700 ms Promise is registered later, so it resolves strictly after)."""
    go = _open(page, live_server, "msa_k", view="split")
    unit = _seed_course_and_unit("msa_k", slug="msa-k")
    _seed_texts(unit, 10, "lead")
    co, _ = _seed_callout(unit, 8)
    target = _seed_texts(unit, 1, "TARGET")[0]
    _seed_texts(unit, 25, "tail")
    go(unit)

    _scroll_window_to_row(page, target.pk, PHONE["height"] / 2)
    _assert_unclamped(page, _rect(page, co.pk)["height"], 0)
    btn = _up(page, target.pk)
    _assert_on_screen(page, btn)
    t0 = _row_top(page, target.pk)
    _swap_click(page, btn)
    assert abs(_row_top(page, target.pk) - t0) <= 2
    page.evaluate("() => new Promise(r => setTimeout(r, 700))")
    assert abs(_row_top(page, target.pk) - t0) <= 2


# --- desktop: unchanged ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_desktop_up_aligns_to_pane_top_without_window_scroll(page, live_server):
    """(f)+(g) At >=70rem the pane scrolls: the row is aligned to the pane top as
    before, and the window-scroll path never runs (spies installed after the
    start position is set; window.scrollY is useless there, the page is locked)."""
    go = _open(page, live_server, "msa_f", viewport=DESKTOP)
    unit = _seed_course_and_unit("msa_f", slug="msa-f")
    _seed_texts(unit, 10, "lead")
    _seed_callout(unit, 8)
    target = _seed_texts(unit, 1, "TARGET")[0]
    _seed_texts(unit, 25, "tail")
    go(unit)

    page.evaluate(
        "(id) => { const b = " + BODY_JS + "; const r = " + ROW_JS + ";"
        " b.scrollTop += r.getBoundingClientRect().top"
        " - b.getBoundingClientRect().top - b.clientHeight / 2; }",
        str(target.pk),
    )
    _settle(page)
    page.evaluate(
        """() => { window.__ws = 0;
          const by = window.scrollBy, to = window.scrollTo;
          window.scrollBy = function () {
            window.__ws++; return by.apply(this, arguments); };
          window.scrollTo = function () {
            window.__ws++; return to.apply(this, arguments); }; }"""
    )
    _swap_click(page, _up(page, target.pk))
    off = page.evaluate(
        "(id) => { const r = " + ROW_JS + ".getBoundingClientRect();"
        " const b = " + BODY_JS + ";"
        " return r.top - b.getBoundingClientRect().top"
        " - parseFloat(getComputedStyle(b).paddingTop); }",
        str(target.pk),
    )
    assert abs(off) <= 2
    assert page.evaluate("window.__ws") == 0
