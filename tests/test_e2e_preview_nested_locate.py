"""Playwright e2e: locating NESTED elements in the editor's live preview.

Spec: docs/superpowers/specs/2026-08-20-preview-nested-element-locate-design.md

Drives real gestures -- clicks the actual controls, never page.evaluate shortcuts.

STANDING TRAPS (the spec's "Assertion traps that make a test vacuous"):
  * Carousel slides are position:absolute; opacity:0 with an INTACT rect, and
    Playwright calls opacity:0 VISIBLE -- so never assert carousel reveal via
    visibility or geometry. Assert on the TARGET's own section: is-active gained,
    inert/aria-hidden lost, or data-tabs-active on the owning [data-tabs-eid].
  * show() adds is-active to the incoming slide synchronously but calls
    settleHidden(out) only after FADE_MS (320ms), so "exactly one .is-active" is
    flaky for 320ms. Never assert about the OUTGOING slide during the fade.
  * Capture any "before" tab value BEFORE the click: applyFragments'
    captureActiveTabs/restoreActiveTabs re-stamp the pre-click tab onto the rebuilt
    preview, so it cannot be inferred from the post-swap DOM.
  * Never assert prev-el--hl after a CLICK. That class comes only from setHighlight
    on mouseenter; on the .el-select path applyFragments destroys the highlighted
    node before scrollPreviewTo runs. Only the hover case (e2e 7) asserts it.
"""

import json
import os

import pytest

from tests.test_e2e_tabs import _editor_url
from tests.test_e2e_tabs import _login
from tests.test_e2e_tabs import _make_pa_user
from tests.test_e2e_tabs import _seed_tabs_element
from tests.test_e2e_tabs import _seed_unit

# MANDATORY. There is no auto-marking hook -- neither conftest.py nor
# tests/conftest.py defines pytest_collection_modifyitems, and all 106 e2e modules
# declare this by hand. Without it `-m e2e` DESELECTS every case and pytest exits 5,
# which reads as "no failures" and would let a red step look green.
pytestmark = pytest.mark.e2e


# Per-module, NOT in a shared conftest -- every sibling e2e module defines its own
# (tests/test_e2e_tabs.py:44-48). Without it sync-ORM calls under Playwright can fail
# depending on collection order.
@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Shared seed helpers -- Tasks 4-10 call these by name; do not rename or reshape.
# ---------------------------------------------------------------------------


def _seed_container(unit, obj, children, parent=None, tab_id=""):
    """Create the container's join row, then one join row per child.

    `children` is a list of (content_object, slot_id). Mirrors the shape of
    courses/tests/test_preview_nested_markers.py::_containers -- direct
    Element(parent=...) rows, NOT builder.resolve_scope.

    Returns (container_join, [child_join, ...]).
    """
    from courses.models import Element

    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab_id
    )
    kids = [
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id=slot
        )
        for child, slot in children
    ]
    return join, kids


def _seed_text(body="x"):
    from courses.models import TextElement

    return TextElement.objects.create(body=f"<p>{body}</p>")


def _seed_filler(unit, n):
    """n top-level text elements, each tall enough to push the pane well past a
    viewport. Used by Tasks 7 and 9 to make a scroll observable."""
    from courses.models import Element

    for i in range(n):
        Element.objects.create(
            unit=unit,
            content_object=_seed_text(("filler %d<br>" % i) * 40),
            parent=None,
        )


def _child_join(container_join, slot_id):
    """The child Element join row inside `container_join`'s `slot_id`.

    REQUIRED after _seed_tabs_element: that helper (test_e2e_tabs.py:101-143) creates
    its child rows inside its own loop but returns only `(obj, join)` for the
    CONTAINER -- the child Element rows are discarded. Every snippet below keys on
    `child_join.pk`, so tabs and carousel fixtures obtain it through here. (The
    non-tabs containers use _seed_container, which returns its children directly, but
    _seed_container cannot build a display="carousel" blob.)
    """
    from courses.models import Element

    return Element.objects.get(parent=container_join, tab_id=slot_id)


def _open_slots(page, pairs):
    """Open editor row-groups WITHOUT clicking their <summary>. Call BEFORE goto.

    NEVER click a <summary> to open a nested row group. `<summary>` is NOT in the
    row-body handler's exclusion list (editor.js:463 excludes button, a, input,
    textarea, select, label, form, [draggable], [data-edit-slot] -- not summary), so
    the click reaches scrollPreviewTo(<the CONTAINER row's pk>) and runs the reveal
    walk. After Task 1 that container is itself a .prev-el, so the walk reveals ITS
    ancestors -- pre-revealing exactly the state a fixture is trying to keep hidden,
    and silently disarming mutants (e), (f) and (i).

    Seed the stored preference instead: editor.js's applyStoredSlots (called at load,
    :606) reads "libli:tabopen:<row data-element>:<data-tab-id|data-column-id>".

    `pairs` is [(container_row_pk, slot_id), ...].
    """
    keys = [f"libli:tabopen:{pk}:{slot}" for pk, slot in pairs]
    page.add_init_script(
        "(() => { const ks = %s;"
        " try { ks.forEach(k => localStorage.setItem(k, '1')); } catch (e) {} })()"
        % json.dumps(keys)
    )


# ---------------------------------------------------------------------------
# e2e cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_click_reveals_a_child_in_a_non_first_strip_tab(page, live_server):
    """e2e 1. Mutant (b1): drop the strip reveal step -> RED.

    Click path: .el-select (the .el-row__label button), which rebuilds both panes.
    """
    pa = _make_pa_user("locate_c1")
    course, unit = _seed_unit(pa, "locate-c1")

    # seed: tabs element, child TEXT in tab 2 (NOT tab 1 -- select() early-returns
    # on i === active, and a first-tab target is revealed by initOne anyway).
    tab1_id, tab2_id = "t000001", "t000002"
    child = _seed_text("nested in tab two")
    tabs_obj, tabs_join = _seed_tabs_element(
        unit,
        [(tab1_id, "Tab One"), (tab2_id, "Tab Two")],
        {tab2_id: [child]},
    )
    child_join = _child_join(tabs_join, tab2_id)

    _login(page, live_server, "locate_c1")
    # MANDATORY: the nested row lives in a collapsed <details class="tabs-rows">.
    # Opened by _open_slots(page, [(tabs_join.pk, tab2_id)]) BEFORE page.goto -- never
    # by clicking the <summary>, which would fire scrollPreviewTo on the tabs row.
    _open_slots(page, [(tabs_join.pk, tab2_id)])
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    eid = str(tabs_join.pk)
    tabs_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{eid}"]'
    before = page.get_attribute(tabs_sel, "data-tabs-active")   # BEFORE the click
    assert before == tab1_id

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[tabs_sel, tab2_id],
    )
    box = page.locator(
        f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'
    ).bounding_box()
    assert box and box["height"] > 0 and box["width"] > 0


@pytest.mark.django_db(transaction=True)
def test_click_opens_a_closed_spoiler_around_the_child(page, live_server):
    """e2e 3. Mutant (b3): drop the spoiler `open = true` step -> RED.

    CLICK PATH: the ROW BODY (editor.js:463, NO fragment swap) -- this is the case
    that covers the second path, so the target must not be a button.

    Target `.el-tag` (a <span>), NOT `.el-row__top`: that is a display:flex row
    (editor.css:580) whose `.el-actions` carries margin-left:auto over ~250px of icon
    buttons (editor.css:606), so Playwright's centre-of-box click lands INSIDE
    .el-actions on a narrow nested row and routes to .el-select instead. A spoiler
    opens on either path, so the mis-route would be silent.
    """
    from courses.models import SpoilerElement

    pa = _make_pa_user("locate_c3")
    course, unit = _seed_unit(pa, "locate-c3")

    child = _seed_text("nested in the spoiler")
    spoiler = SpoilerElement.objects.create(label="Reveal me", body="")
    _container_join, kids = _seed_container(
        unit, spoiler, [(child, SpoilerElement.SLOT_ID)]
    )
    child_join = kids[0]

    _login(page, live_server, "locate_c3")
    # Spoiler rows are always-open divs (no nested <details> for the single slot),
    # so no _open_slots call is needed here.
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    det = '[data-scope="preview"] details.spoiler'
    assert page.get_attribute(det, "open") is None      # closed to begin with

    # Prove NO fragment swap occurred: hold a handle on a preview node and assert it
    # is still connected afterwards. applyFragments replaces the whole pane, so a
    # swapped-in build detaches it.
    handle = page.query_selector('[data-scope="preview"]')
    page.click(f'.el-row[data-element="{child_join.pk}"] .el-tag')
    page.wait_for_selector(f"{det}[open]")
    assert page.evaluate("(n) => n.isConnected", handle), "unexpected fragment swap"
