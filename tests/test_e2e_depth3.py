"""Playwright e2e for depth-3 nesting (plan Task 12) — the ONE test that proves the
cap lift is reachable through the real authoring UI.

Everything else in this slice is server-side: the containment rule, the delete/export/
import walks, the template guards. All of it can be green while the author still cannot
*get there*: the add-menu cards that make depth 3 authorable are template-guarded, and a
guard that hides a card ships broken UX green (this repo's standing lesson: an e2e that
bypasses the real gesture proves nothing about the gesture).

So this file drives the whole chain with real clicks and real typing — no page.evaluate
shortcut, no ORM-seeded tree, no direct POST:

    top-level add-menu   -> Tabs      (depth 1)   container level 1
    tab 1's nested menu  -> Spoiler   (depth 2)   container level 2 <- the card the
                                                                       mutant suppresses
    the spoiler's menu   -> Tabs      (depth 3)   container level 3
    inner tab 1's menu   -> Text      (depth 4)   the content inside the third level

and then reads the result as a STUDENT: the marker string must be inside the spoiler's
rendered body on the lesson page. Authoring that the reader never sees is not a feature.

Login/course/editor setup is copied from tests/test_e2e_tabs.py (same PA-user helper,
same login form drive, same CourseFactory/ContentNodeFactory seed, same editor URL
shape) rather than invented.

Every add-menu locator is scoped to its own [data-add-menu]:
  * the top-level menu by `:not(.addwrap--nested)`;
  * each nested menu by the `data-parent`/`data-tab` scope attributes it carries.
Unscoped is not merely untidy here — since this slice a nested menu also emits the
Spoiler and Tabs cards, so `page.locator("[data-add-type='spoiler']")` matches both the
top-level and the nested menu and fails Playwright strict mode.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

MARKER = "DEPTH3-UI-MARKER-4b7e"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Shared login / seed helpers (mirrors tests/test_e2e_tabs.py)
# ---------------------------------------------------------------------------


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_unit(owner, slug):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


# ---------------------------------------------------------------------------
# Add-menu drivers — each one scoped to exactly one [data-add-menu]
# ---------------------------------------------------------------------------


def _open_card(menu, add_type):
    """Open `menu` and click its `add_type` card. `menu` is ONE [data-add-menu].

    The cards live inside `<div class="typemenu" hidden>`, so the toggle click is not
    decoration: without it Playwright waits for visibility and times out."""
    menu.locator("[data-add-toggle]").click()
    menu.locator(f"[data-add-type='{add_type}']").click()


def _top_menu(page):
    """The single non-nested add-menu (_editor_scope.html includes it with depth=0 and
    no `nested`, so its wrapper carries no .addwrap--nested)."""
    return page.locator("[data-add-menu]:not(.addwrap--nested)")


def _nested_menu(page, parent_pk, tab_id):
    """The nested add-menu belonging to one container slot. _add_menu.html stamps
    data-parent/data-tab on the wrapper for exactly this purpose — those attributes are
    what land the child in the right slot, so scoping by them also asserts the scope."""
    return page.locator(
        f"[data-add-menu][data-parent='{parent_pk}'][data-tab='{tab_id}']"
    )


def _save_open_form(page):
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()


def _wait_nested_row_count(page, container_selector, expected):
    """Poll until `container_selector` holds exactly `expected` nested rows.

    A Save is fire-and-forget from the caller's point of view: the click returns at once
    and the pane is swapped only when the response lands. Waiting on a selector that
    ALREADY matched the stale pane returns instantly and proves nothing, and acting on
    the stale pane detaches the node the next gesture is mid-click on. Counting the rows
    that only the swapped pane can have is the race-free checkpoint. (No sleeps: this
    repo's sleep-based e2e tests fail only under parallel load.)"""
    page.wait_for_function(
        """([sel, n]) => {
            const host = document.querySelector(sel);
            if (!host) return false;
            const rows = host.querySelectorAll('.element-list--nested > .el-row');
            return rows.length === n;
        }""",
        arg=[container_selector, expected],
    )


# ---------------------------------------------------------------------------
# The gesture
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_author_a_depth_4_text_through_the_ui(page, live_server):
    """Author tabs > spoiler > tabs > text with real clicks, then read it as a student.

    THREE container levels with content inside the third -- the shape the cap lift
    exists for ("a spoiler with child tabs with child spoiler, but this is it").

    Falsified by reverting the Spoiler card's guard in _add_menu.html to
    `{% if not nested %}`: that suppresses the Spoiler card in EVERY nested menu, so the
    second hop of the gesture has no card to click and the test times out. (Deleting the
    guard instead would make the card render unconditionally — a widened guard leaves
    the gesture completable and this test green, which is why the mutant is the revert,
    not the deletion.)"""
    from courses import builder
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TextElement
    from tests.factories import EnrollmentFactory

    pa = _make_pa_user("d3_ui")
    course, unit = _seed_unit(pa, "d3-ui")
    # The lesson view is enrollment-gated; the author reads their own work as a student.
    EnrollmentFactory(student=pa, course=course)
    _login(page, live_server, "d3_ui")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # --- depth 1: Tabs, from the TOP-LEVEL menu ------------------------------------
    _open_card(_top_menu(page), "tabs")
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor]")
    _save_open_form(page)
    page.wait_for_function(
        """() => document.querySelectorAll(
             '[data-scope="editor"] .el-row--tabs .el-row__tabs > details.tabs-rows'
           ).length === 2"""
    )

    tabs_join = Element.objects.get(unit=unit, parent__isnull=True)
    tab_id = tabs_join.content_object.data["tabs"][0]["id"]

    # --- depth 2: Spoiler, from TAB 1's OWN nested menu ----------------------------
    # This is the hop the cap lift unlocks: before it, a container card never appeared
    # in a nested menu at all.
    tab1_menu = _nested_menu(page, tabs_join.pk, tab_id)
    expect(tab1_menu).to_have_count(1)
    _open_card(tab1_menu, "spoiler")
    page.wait_for_selector("[data-edit-slot] .el-editor--spoiler")
    _save_open_form(page)  # a blank spoiler is valid; the children are what matter
    _wait_nested_row_count(
        page, '[data-scope="editor"] .el-row--tabs .el-row__tabs > details.tabs-rows', 1
    )
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs .el-row--spoiler')

    spoiler_join = Element.objects.get(unit=unit, parent=tabs_join)
    assert isinstance(spoiler_join.content_object, SpoilerElement)
    assert builder.element_depth(spoiler_join) == 2

    # --- depth 3: Tabs, from THE SPOILER's own nested menu --------------------------
    # The THIRD container level. Before the cap lift this menu offered no container
    # card at all.
    spoiler_menu = _nested_menu(page, spoiler_join.pk, SpoilerElement.SLOT_ID)
    expect(spoiler_menu).to_have_count(1)
    _open_card(spoiler_menu, "tabs")
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor]")
    _save_open_form(page)
    _wait_nested_row_count(
        page, '[data-scope="editor"] .el-row--tabs .el-row--spoiler', 1
    )
    page.wait_for_selector('[data-scope="editor"] .el-row--spoiler .el-row--tabs')

    inner_tabs_join = Element.objects.get(unit=unit, parent=spoiler_join)
    assert builder.element_depth(inner_tabs_join) == 3
    inner_tab_id = inner_tabs_join.content_object.data["tabs"][0]["id"]

    # --- depth 4: Text, from the INNER tabs' own nested menu ------------------------
    inner_menu = _nested_menu(page, inner_tabs_join.pk, inner_tab_id)
    expect(inner_menu).to_have_count(1)
    # A depth-3 menu must NOT offer containers any more (that would be a fourth
    # container level) — the same template guard, read from the other side.
    for card in ("tabs", "twocolumn", "spoiler"):
        expect(inner_menu.locator(f"[data-add-type='{card}']")).to_have_count(0)
    _open_card(inner_menu, "text")

    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type(MARKER)
    _save_open_form(page)
    _wait_nested_row_count(
        page, '[data-scope="editor"] .el-row--spoiler .el-row--tabs', 1
    )

    # --- it really is depth 4, in the right slots ----------------------------------
    leaf_join = Element.objects.get(unit=unit, parent=inner_tabs_join)
    assert isinstance(leaf_join.content_object, TextElement)
    assert leaf_join.tab_id == inner_tab_id
    assert leaf_join.unit_id == unit.pk
    assert builder.element_depth(leaf_join) == 4
    assert MARKER in leaf_join.content_object.body

    # --- and the reader can actually see it ----------------------------------------
    page.goto(_lesson_url(live_server, unit))
    # ATTACHED, not visible: the third-level tabs element sits inside a still-CLOSED
    # spoiler, so tabs.js initialises it while it has no layout box at all. Waiting for
    # visibility here would time out against correct code.
    inner_sel = f"[data-tabs-eid='{inner_tabs_join.pk}']"
    page.wait_for_selector(f"{inner_sel}.tabs--js", state="attached")

    spoiler = page.locator("[data-tabs] details.spoiler").first
    spoiler.locator("summary").click()  # real reveal gesture
    child = spoiler.locator(".spoiler__child")
    expect(child).to_have_count(1)
    expect(child).to_contain_text(MARKER)
    expect(child).to_be_visible()
    # The third level really is a live tabs widget, not just markup: its own strip is
    # built and shows its own two tabs, and the depth-4 text is in the active panel.
    expect(page.locator(f"{inner_sel} > .tabs__bar .tabs__tab")).to_have_count(2)
    expect(page.locator(f"{inner_sel} .tabs__child", has_text=MARKER)).to_be_visible()


# ---------------------------------------------------------------------------
# SAME-TYPE nesting (final-review Finding 2)
#
# Every depth-3 fixture in this slice -- Tasks 7, 8 and 12 -- independently chose
# `tabs > spoiler > leaf`. Nothing rendered a container inside a container of its OWN
# type, which is exactly the shape that collides with per-element DOM enhancement: a
# nested instance's nodes are DESCENDANTS of the outer instance's container, so any
# unscoped querySelectorAll (or descendant CSS selector) swallows them.
#
# These two tests must be e2e, not Django render tests. The defects they pin do not
# exist in the server's HTML at all:
#   * the tab strip (.tabs__bar / .tabs__tab) is built entirely by tabs.js in the
#     browser -- the server emits only sections, labels and panels, byte-identical
#     before and after the fix, so no assertion on `resp.content` can see the bug;
#   * the spoiler label swap is pure CSS ([open] descendant vs child combinator), which
#     needs a real cascade and computed styles.
# ---------------------------------------------------------------------------

NESTED_TABS_MARKER = "DEPTH3-TABSINTABS-MARKER-7c02"
NESTED_SPOILER_MARKER = "DEPTH3-SPOILER2-MARKER-a19d"


def _tabs_data(labels):
    """TabsElement.default_data() (two tabs) with the labels renamed.

    Distinct labels per instance are load-bearing: with the default "Tab 1"/"Tab 2" on
    both elements a leaked-button assertion could not tell WHOSE buttons it found.
    """
    from courses.models import TabsElement

    data = TabsElement.default_data()
    for entry, label in zip(data["tabs"], labels, strict=True):
        entry["label"] = label
    return data


@pytest.mark.django_db(transaction=True)
def test_nested_tabs_do_not_leak_into_the_outer_tab_strip(page, live_server):
    """tabs > tabs > tabs > text, read as a student.

    THREE levels of the same container type, the deepest shape the cap allows. Both
    client-side scoping fixes are depth-independent, but "should hold one level
    deeper" is a claim, so it is measured rather than assumed: the middle instance is
    simultaneously a descendant of the outer and an ancestor of the inner, which is
    the only position an unscoped walk can corrupt from both sides at once.

    Falsified by reverting tabs.js's `ownSections()` to the bare
    `container.querySelectorAll(".tabs__section")`: initTabs visits the outer first, so
    the outer's section list becomes [Outer A, Mid P, Inner X, Inner Y, Mid Q, Outer B]
    and the outer strip renders SIX buttons carrying the nested elements' labels. The
    round trip at the end pins the user-visible consequence -- the outer's `select()`
    puts `hidden` on panels it does not own, and the nested instances (still
    `active === 0`) can never take it off again, so they stay blank forever.
    """
    from courses import builder
    from courses.models import Element
    from courses.models import TabsElement
    from courses.models import TextElement
    from tests.factories import EnrollmentFactory

    pa = _make_pa_user("d3_tabs2")
    course, unit = _seed_unit(pa, "d3-tabs2")
    EnrollmentFactory(student=pa, course=course)

    outer_obj = TabsElement.objects.create(data=_tabs_data(["Outer A", "Outer B"]))
    outer = Element.objects.create(
        unit=unit, content_object=outer_obj, parent=None, tab_id="", order=0
    )
    mid_obj = TabsElement.objects.create(data=_tabs_data(["Mid P", "Mid Q"]))
    outer_obj.refresh_from_db()
    mid = Element.objects.create(
        unit=unit,
        content_object=mid_obj,
        parent=outer,
        tab_id=outer_obj.data["tabs"][0]["id"],
        order=0,
    )
    inner_obj = TabsElement.objects.create(data=_tabs_data(["Inner X", "Inner Y"]))
    mid_obj.refresh_from_db()
    inner = Element.objects.create(
        unit=unit,
        content_object=inner_obj,
        parent=mid,
        tab_id=mid_obj.data["tabs"][0]["id"],
        order=0,
    )
    inner_obj.refresh_from_db()
    leaf_obj = TextElement.objects.create(body=f"<p>{NESTED_TABS_MARKER}</p>")
    leaf = Element.objects.create(
        unit=unit,
        content_object=leaf_obj,
        parent=inner,
        tab_id=inner_obj.data["tabs"][0]["id"],
        order=0,
    )
    assert builder.element_depth(mid) == 2
    assert builder.element_depth(inner) == 3
    assert builder.element_depth(leaf) == 4

    _login(page, live_server, "d3_tabs2")
    page.goto(_lesson_url(live_server, unit))

    # `data-tabs-eid` is the join-row pk (TabsElement.render), so these selectors name
    # the three instances unambiguously. The `>` before .tabs__bar is the whole point:
    # tabs.js inserts each bar as its container's FIRST CHILD, so a descendant locator
    # would match a nested strip from an outer container and hide the bug.
    outer_sel = f"[data-tabs-eid='{outer.pk}']"
    mid_sel = f"[data-tabs-eid='{mid.pk}']"
    inner_sel = f"[data-tabs-eid='{inner.pk}']"
    page.wait_for_selector(f"{outer_sel}.tabs--js")
    page.wait_for_selector(f"{mid_sel}.tabs--js")
    page.wait_for_selector(f"{inner_sel}.tabs--js")

    outer_tabs = page.locator(f"{outer_sel} > .tabs__bar .tabs__tab")
    mid_tabs = page.locator(f"{mid_sel} > .tabs__bar .tabs__tab")
    inner_tabs = page.locator(f"{inner_sel} > .tabs__bar .tabs__tab")

    # THE pin: each strip carries its OWN tabs and only its own.
    expect(outer_tabs).to_have_count(2)
    expect(outer_tabs).to_have_text(["Outer A", "Outer B"])
    expect(mid_tabs).to_have_count(2)
    expect(mid_tabs).to_have_text(["Mid P", "Mid Q"])
    expect(inner_tabs).to_have_count(2)
    expect(inner_tabs).to_have_text(["Inner X", "Inner Y"])

    # ...and every outer button controls a panel the OUTER owns. Under the bug the
    # outer stamps ids on the inner's panels and initOne(inner) restamps them, leaving
    # the outer's aria-controls pointing at ids that no longer exist.
    dangling = page.evaluate(
        """(sel) => {
            const outer = document.querySelector(sel);
            const btns = outer.querySelectorAll(':scope > .tabs__bar .tabs__tab');
            return Array.from(btns).filter((b) => {
                const p = document.getElementById(b.getAttribute('aria-controls'));
                return !p || p.closest('[data-tabs]') !== outer;
            }).length;
        }""",
        outer_sel,
    )
    assert dangling == 0

    # The innermost element's content is reachable, and STAYS reachable across a round
    # trip through the OUTERMOST strip -- two levels above it.
    marker = page.locator(f"{inner_sel} .tabs__child", has_text=NESTED_TABS_MARKER)
    expect(marker).to_be_visible()
    outer_tabs.nth(1).click()  # "Outer B" -- the panel holding the nest is hidden
    expect(page.locator(inner_sel)).to_be_hidden()
    outer_tabs.nth(0).click()  # back to "Outer A"
    expect(page.locator(inner_sel)).to_be_visible()
    expect(marker).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_nested_spoiler_keeps_its_own_open_state_affordances(page, live_server):
    """spoiler > spoiler > spoiler > text, read as a student.

    THREE levels of the same container type. The CSS fix is depth-independent, but a
    descendant-combinator regression reaches every generation below the opened
    element, so the deepest level is where it shows up first and worst -- measured,
    not assumed.

    Falsified by reverting app.css's
    `.spoiler[open] > .spoiler__toggle .spoiler__label--*`
    rules to the descendant form `.spoiler[open] .spoiler__label--*`: opening the OUTER
    spoiler then matches BOTH still-closed descendants' labels, so their summaries read
    "Hide" while their bodies are collapsed.
    """
    from courses import builder
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TextElement
    from tests.factories import EnrollmentFactory

    pa = _make_pa_user("d3_sp2")
    course, unit = _seed_unit(pa, "d3-sp2")
    EnrollmentFactory(student=pa, course=course)

    outer_obj = SpoilerElement.objects.create(label="OUTER-REVEAL")
    outer = Element.objects.create(
        unit=unit, content_object=outer_obj, parent=None, tab_id="", order=0
    )
    mid_obj = SpoilerElement.objects.create(label="MID-REVEAL")
    mid = Element.objects.create(
        unit=unit,
        content_object=mid_obj,
        parent=outer,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    inner_obj = SpoilerElement.objects.create(label="INNER-REVEAL")
    inner = Element.objects.create(
        unit=unit,
        content_object=inner_obj,
        parent=mid,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    leaf_obj = TextElement.objects.create(body=f"<p>{NESTED_SPOILER_MARKER}</p>")
    leaf = Element.objects.create(
        unit=unit,
        content_object=leaf_obj,
        parent=inner,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    assert builder.element_depth(inner) == 3
    assert builder.element_depth(leaf) == 4

    _login(page, live_server, "d3_sp2")
    page.goto(_lesson_url(live_server, unit))

    outer_sp = page.locator("details.spoiler").first
    mid_sp = page.locator("details.spoiler > .spoiler__child > details.spoiler").first
    inner_sp = page.locator(
        "details.spoiler > .spoiler__child > details.spoiler"
        " > .spoiler__child > details.spoiler"
    )
    expect(inner_sp).to_have_count(1)

    outer_sp.locator("summary").first.click()  # real reveal gesture on the OUTER only
    expect(mid_sp).to_be_visible()
    # Both descendants are still CLOSED, so each must advertise ITS OWN state, not an
    # ancestor's. (Each holds one child, so these label locators are unambiguous.)
    assert mid_sp.evaluate("(el) => el.hasAttribute('open')") is False
    expect(mid_sp.locator(".spoiler__label--show").first).to_be_visible()
    expect(mid_sp.locator(".spoiler__label--hide").first).to_be_hidden()
    expect(mid_sp.locator("summary").first).to_contain_text("MID-REVEAL")

    mid_sp.locator("summary").first.click()  # open the SECOND level only
    expect(inner_sp).to_be_visible()
    assert inner_sp.evaluate("(el) => el.hasAttribute('open')") is False
    expect(inner_sp.locator(".spoiler__label--show")).to_be_visible()
    expect(inner_sp.locator(".spoiler__label--hide")).to_be_hidden()
    expect(inner_sp.locator("summary").first).to_contain_text("INNER-REVEAL")

    # ...and opening the third level really does reveal the depth-4 content.
    inner_sp.locator("summary").first.click()
    expect(
        inner_sp.locator(".spoiler__child", has_text=NESTED_SPOILER_MARKER)
    ).to_be_visible()
