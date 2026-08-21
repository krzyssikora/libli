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


# Byte-equivalent to alignTopInPane's own arithmetic (editor.js): the pane's
# CONTENT top is the .pane-body rect top PLUS its computed padding-top, not the
# bare rect top -- that would be off by the padding, which can exceed the 4px
# poll tolerance and turn a correct build red. Defined ONCE at module level so
# Task 9 reuses it rather than duplicating the logic block.
_PANE_DELTA_JS = """(sel) => {
  const t = document.querySelector(sel);
  const b = t.closest(".pane-body");
  const pad = parseFloat(getComputedStyle(b).paddingTop) || 0;
  return t.getBoundingClientRect().top - b.getBoundingClientRect().top - pad;
}"""


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
def test_click_reveals_a_child_in_a_non_first_carousel_slide(page, live_server):
    """e2e 2. Mutant (b2): delete the whole `data-display === "carousel"` block so
    the code falls through to the strip lookup -- which finds no [aria-controls]
    button in carousel mode and silently no-ops -> RED.

    Click path: .el-select (the .el-row__label button), which rebuilds both panes.

    Assert on the TARGET's OWN section only (is-active gained, inert/aria-hidden
    lost) -- never via visibility/geometry: an inactive carousel slide is
    position:absolute; opacity:0 with an INTACT rect, and Playwright calls
    opacity:0 visible.
    """
    pa = _make_pa_user("locate_c2")
    course, unit = _seed_unit(pa, "locate-c2")

    # display="carousel"; child TEXT in slide 2 (NOT slide 1 -- show() early-returns
    # on target === idx, and a first-slide target is revealed by initOne anyway).
    slide1_id, slide2_id = "t000001", "t000002"
    child = _seed_text("nested in slide two")
    tabs_obj, tabs_join = _seed_tabs_element(
        unit,
        [(slide1_id, "Slide One"), (slide2_id, "Slide Two")],
        {slide2_id: [child]},
        display="carousel",
    )
    child_join = _child_join(tabs_join, slide2_id)

    _login(page, live_server, "locate_c2")
    # MANDATORY: the nested row lives in a collapsed <details class="tabs-rows">.
    # Opened via _open_slots BEFORE page.goto -- never by clicking the <summary>,
    # which would fire scrollPreviewTo on the tabs row itself and pre-reveal it.
    _open_slots(page, [(tabs_join.pk, slide2_id)])
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    eid = str(tabs_join.pk)
    idx = 1  # slide two is ownSections()[1], 0-based

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    # Explicit child chain, NOT a descendant combinator: a bare descendant matches a
    # nested instance's sections too. Safe for this single carousel, but it is
    # copy-paste bait for case 9 and contradicts the spec's ownership rule -- and it
    # would trip Playwright strict mode the moment the fixture grows an inner
    # instance. Mirrors initCarousel's own `:scope > .tabs__stage`.
    sect_sel = (
        f'[data-scope="preview"] [data-tabs][data-tabs-eid="{eid}"] '
        f'> .tabs__stage > .tabs__section:nth-of-type({idx + 1})'
    )
    page.wait_for_selector(f"{sect_sel}.is-active")
    assert page.get_attribute(sect_sel, "inert") is None
    assert page.get_attribute(sect_sel, "aria-hidden") is None


@pytest.mark.django_db(transaction=True)
def test_nested_carousel_reveals_the_outer_instance(page, live_server):
    """e2e 9. The fixture for mutant (d), which no other case can kill.

    Mutant (d): change `ownNodes(hit.c, ".tabs__dot", "[data-tabs]")` to
    `hit.c.querySelectorAll(".tabs__dot")`. On an unscoped build the OUTER
    container's dot query returns the INNER carousel's dots first -- they sit
    inside .tabs__stage, appended by tabs.js BEFORE the outer's own <nav> (which
    initCarousel appends LAST to `container`) -- so indexing by the outer's own
    slide position grabs one of the inner's dots instead, and the outer carousel
    never advances -> case 9 RED. Case 2 (a single carousel, no inner dots to
    steal) stays GREEN under the same mutant, which is exactly why this fixture
    exists -- no other case can tell the two apart.

    Outer carousel: target's slide is non-first (index 1). That slide holds an
    INNER carousel with >= 2 slides of its own (index 1 must exist among the
    inner's dots too, so an unscoped dots[1] resolves to a real -- wrong -- inner
    dot rather than silently no-oping). The target text lives in the inner
    carousel's own non-first slide. Slide-id sets are disjoint between the two
    instances.
    """
    pa = _make_pa_user("locate_c9")
    course, unit = _seed_unit(pa, "locate-c9")

    outer1_id, outer2_id = "t000001", "t000002"
    inner1_id, inner2_id = "t000011", "t000012"  # disjoint from the outer's ids

    child = _seed_text("nested two carousels deep")
    outer_obj, outer_join = _seed_tabs_element(
        unit,
        [(outer1_id, "Outer One"), (outer2_id, "Outer Two")],
        display="carousel",
    )
    inner_obj, inner_join = _seed_tabs_element(
        unit,
        [(inner1_id, "Inner One"), (inner2_id, "Inner Two")],
        {inner2_id: [child]},
        display="carousel",
        parent=outer_join,
        tab_id=outer2_id,
    )
    child_join = _child_join(inner_join, inner2_id)

    _login(page, live_server, "locate_c9")
    # TWO levels of collapsed <details class="tabs-rows"> to open: the outer's
    # slide-2 group (which holds the inner carousel's own row) and the inner's
    # own slide-2 group (which holds the target's row). Both BEFORE goto -- never
    # via a <summary> click, which would fire scrollPreviewTo on a container row
    # and pre-reveal its ancestors, silently disarming this mutant.
    _open_slots(
        page,
        [(outer_join.pk, outer2_id), (inner_join.pk, inner2_id)],
    )
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    # The OUTER container's data-tabs-active must equal the data-tab-id of the
    # target section's own [data-tab-panel] -- that is what show() stamps
    # (ids[idx]), a model-level tab id, NOT the tabs-<eid>-<tid>-panel DOM id the
    # strip lookup uses.
    outer_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{outer_join.pk}"]'
    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[outer_sel, outer2_id],
    )


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


@pytest.mark.django_db(transaction=True)
def test_click_flips_before_after_to_the_panel_holding_the_child(page, live_server):
    """e2e 4. Mutant (b4): drop the before/after toggle click -> RED.

    Click path: .el-row__label (.el-select). No <details> precondition -- ba rows are
    always-open divs (templates/courses/manage/editor/_element_row.html:243).
    """
    from courses.models import BeforeAfterElement

    pa = _make_pa_user("locate_c4")
    course, unit = _seed_unit(pa, "locate-c4")

    child = _seed_text("nested in the after panel")
    ba_obj = BeforeAfterElement.objects.create()
    _container_join, kids = _seed_container(
        unit, ba_obj, [(child, BeforeAfterElement.SLOT_IDS[1])]
    )
    child_join = kids[0]

    _login(page, live_server, "locate_c4")
    # Before/after rows are always-open divs (no nested <details> to collapse), so no
    # _open_slots call is needed here -- unlike tabs and two-column.
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    ba = '[data-scope="preview"] [data-beforeafter]'
    after = f'{ba} .ba__panel[data-ba-side="after"]'
    before = f'{ba} .ba__panel:not([data-ba-side="after"])'
    # state="hidden"/"visible", NOT a `[hidden]`-in-selector + default "visible"
    # wait: the `hidden` attribute maps to `display: none` in the UA stylesheet, so
    # a locator whose OWN selector requires `[hidden]` can never satisfy Playwright's
    # default "visible" wait -- it would time out on a correct build too.
    page.wait_for_selector(after, state="hidden")  # starts on Before

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    page.wait_for_selector(after, state="visible")
    page.wait_for_selector(before, state="hidden")


@pytest.mark.django_db(transaction=True)
def test_stacked_tabs_reveal_outermost_first(page, live_server):
    """e2e 5. Two nested strip-mode tabs elements. Mutants (e) and (f).

    Click path: .el-row__label (.el-select).

    (e) reverses the reveal loop in revealAncestors to innermost-first: the
    inner tabs element sits in the outer's NON-FIRST tab, so at load the outer
    conceals it (display:none), zeroing offsetLeft/offsetWidth/scrollLeft/
    clientWidth. Revealing the inner strip before the outer measures that
    zeroed geometry and leaves scrollLeft stuck at 0 -- RED on the final
    assertion. The outer must be STRIP mode (not carousel): a carousel keeps
    an inactive slide's rect intact at opacity:0, so it would not zero
    anything and (e) would be unfalsifiable.

    (f) resolves `s` via closest() from the target instead of the ownership
    filter (owningNode). closest() returns the INNERMOST section for every
    ancestor in the chain, so the OUTER container ends up indexing the
    INNER's own section -- its data-tabs-active never advances to the tab
    that actually holds the inner instance. Two nested tabs elements are
    required to observe this: with only one tabs ancestor, closest() and the
    ownership filter agree.

    The target also sits in a LATE, NON-FIRST tab of the INNER instance, and
    the inner strip must OVERFLOW the preview pane -- select() early-returns
    on i === active, so a first-tab target proves nothing, and scrollLeft
    can only move if there is somewhere to scroll TO.
    """
    pa = _make_pa_user("locate_c5")
    course, unit = _seed_unit(pa, "locate-c5")

    # Disjoint tab-id sets. Outer: 2 tabs, inner instance lives in the
    # non-first one. Inner: 10 tabs (<= TabsElement.MAX_TABS) with long
    # (<= LABEL_MAX=80) labels -- long labels, not many tabs, drive the strip
    # past its max-width(18rem) cap into real horizontal overflow, without
    # tripping normalize_data's destructive MAX_TABS truncation.
    outer1_id, outer2_id = "t000001", "t000002"
    inner_ids = [f"t1{i:05d}" for i in range(1, 11)]  # t100001 .. t100010
    inner_late_tab_id = inner_ids[-1]

    def _long_label(n):
        label = (
            "Inner strip tab number %02d carries an unusually long "
            "descriptive label so the tab strip overflows the preview "
            "pane width" % n
        )
        return label[:80]

    inner_tabs = [(tid, _long_label(i)) for i, tid in enumerate(inner_ids, start=1)]

    child = _seed_text("nested two tabs deep, late tab of the inner strip")

    outer_obj, outer_join = _seed_tabs_element(
        unit, [(outer1_id, "Outer One"), (outer2_id, "Outer Two")]
    )
    inner_obj, inner_join = _seed_tabs_element(
        unit,
        inner_tabs,
        {inner_late_tab_id: [child]},
        parent=outer_join,
        tab_id=outer2_id,
    )
    child_join = _child_join(inner_join, inner_late_tab_id)

    _login(page, live_server, "locate_c5")
    # TWO nested collapsed <details class="tabs-rows"> to open: the outer's
    # tab-two row group (holds the inner tabs element's own row) and the
    # inner's late-tab row group (holds the target's row). Both BEFORE
    # goto, via the stored-preference mechanism -- never a <summary> click,
    # which would fire scrollPreviewTo on a container row and pre-reveal its
    # ancestors, disarming both mutants (see _open_slots' docstring).
    _open_slots(
        page,
        [(outer_join.pk, outer2_id), (inner_join.pk, inner_late_tab_id)],
    )
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # Pre-flight: the target's tab actually survived normalize_data's
    # destructive MAX_TABS truncation. If this fails the fixture is broken,
    # not the product -- catch it here rather than as a mysterious "child
    # row not found" failure below.
    assert page.locator(
        f'[data-tabs][data-tabs-eid="{inner_join.pk}"] '
        f'[data-tab-panel][data-tab-id="{inner_late_tab_id}"]'
    ).count() == 1, "target tab was truncated by normalize_data (MAX_TABS)"

    inner_scroller = (
        f'[data-scope="preview"] [data-tabs][data-tabs-eid="{inner_join.pk}"] '
        f'> .tabs__bar .tabs__scroller'
    )
    outer_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{outer_join.pk}"]'
    inner_sel = f'[data-scope="preview"] [data-tabs][data-tabs-eid="{inner_join.pk}"]'

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    # BOTH ancestors revealed.
    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[outer_sel, outer2_id],
    )
    page.wait_for_function(
        """([sel, want]) => document.querySelector(sel)
              ?.getAttribute("data-tabs-active") === want""",
        arg=[inner_sel, inner_late_tab_id],
    )

    # POST-CLICK pre-flight, not pre-click: the inner subtree is
    # display:none at load (constraint 2), so scrollWidth/clientWidth are
    # both 0 there and a pre-click wait would time out on a CORRECT build.
    # If the strip stops overflowing this goes RED rather than silently
    # vacuous.
    assert page.evaluate(
        "(sel) => { const s = document.querySelector(sel);"
        "  return s.scrollWidth > s.clientWidth; }",
        inner_scroller,
    ), "fixture no longer overflows -- mutant (e) would be unfalsifiable"

    page.wait_for_function(
        "(sel) => document.querySelector(sel).scrollLeft > 0", arg=inner_scroller
    )


@pytest.mark.django_db(transaction=True)
def test_position_aligns_the_nested_target_to_the_pane_top(page, live_server):
    """e2e 6. Mutant (g): scrollPreviewTo returns right after revealAncestors(target)
    -- reveal happens, but the pane never scrolls -> RED.

    Fixture: a callout child, ALWAYS visible in the preview (unlike a tab, carousel
    slide, closed spoiler or After panel, which give a zero/degenerate pre-click rect
    and make the `> 400` probe fail on a correct build -- see the spec's assertion
    traps). 8 filler elements before the callout push its pre-click position well
    below the pane fold; 8 filler elements after it give `.pane-body` enough scroll
    room to actually bring it to the top.

    Click path: .el-row__label. Callout editor rows are always-open divs -- no
    _open_slots, no <summary> click.
    """
    from courses.models import CalloutElement

    pa = _make_pa_user("locate_c6")
    course, unit = _seed_unit(pa, "locate-c6")

    _seed_filler(unit, 8)  # leading run: pushes the callout well below the fold
    child = _seed_text("nested in the callout")
    callout = CalloutElement.objects.create(kind="example")
    _container_join, kids = _seed_container(
        unit, callout, [(child, CalloutElement.SLOT_ID)]
    )
    child_join = kids[0]
    _seed_filler(unit, 8)  # trailing run: gives .pane-body room to scroll it to top

    _login(page, live_server, "locate_c6")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    target_sel = (
        f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'
    )

    # BOTH pre-click guards go HERE, before the click. The trailing-run check
    # compares against the PRE-click delta, so after the click it would compare
    # against ~0 and be vacuous.
    assert page.evaluate(_PANE_DELTA_JS, target_sel) > 400  # far below the fold
    scrollable = page.evaluate(
        '() => { const b = document.querySelector('
        '\'[data-scope="preview"] .pane-body\');'
        "  return b.scrollHeight - b.clientHeight; }"
    )
    assert scrollable > page.evaluate(_PANE_DELTA_JS, target_sel), (
        "trailing filler too short -- the target can never reach the pane top"
    )

    page.click(f'.el-row[data-element="{child_join.pk}"] .el-row__label')

    # This case POLLS (no prefers-reduced-motion emulation here): the timeout sits
    # comfortably past scrollPreviewTo's 500ms setTimeout backstop.
    page.wait_for_function(
        f"(sel) => Math.abs(({_PANE_DELTA_JS})(sel)) <= 4",
        arg=target_sel,
        timeout=5000,
    )


@pytest.mark.django_db(transaction=True)
def test_hover_outlines_a_nested_child(page, live_server):
    """e2e 7. Mutant (h): scope setHighlight to `.prev-inner > .prev-el` -> RED.

    Hover path: mouseenter on the nested .el-row[data-element], which calls
    setHighlight to add prev-el--hl to the preview node. A render test cannot
    prove setHighlight reaches a nested node, which is why this e2e case exists.

    Fixture: a callout child, always visible in the preview (unlike a tab,
    carousel slide, closed spoiler or After panel). No scroll needed -- hover
    does NOT trigger the reveal walk, so a hidden target would be outlined
    invisibly and the case would prove nothing.

    Hover is fixed by Task 1 alone (setHighlight needs no change -- the same
    selector now matches nested nodes after the marker is placed on them).
    """
    from courses.models import CalloutElement

    pa = _make_pa_user("locate_c7")
    course, unit = _seed_unit(pa, "locate-c7")

    child = _seed_text("nested in the callout")
    callout = CalloutElement.objects.create(kind="example")
    _container_join, kids = _seed_container(
        unit, callout, [(child, CalloutElement.SLOT_ID)]
    )
    child_join = kids[0]

    _login(page, live_server, "locate_c7")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    target_sel = (
        f'[data-scope="preview"] .prev-el[data-element-id="{child_join.pk}"]'
    )

    page.hover(f'.el-row[data-element="{child_join.pk}"]')
    page.wait_for_selector(f"{target_sel}.prev-el--hl")
