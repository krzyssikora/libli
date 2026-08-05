"""Playwright e2e for the tabs content element (plan Task 11). Drives the REAL
user gestures end-to-end — clicks the actual buttons, presses the actual keys — no
page.evaluate shortcuts (this repo's standing lesson: an e2e that bypasses the real
gesture ships broken UX green).

Covers the six scenarios from the task brief:
  1. Authoring: add Tabs via the add-menu, Save; the element list grows two tab
     rows and the LIVE-PREVIEW pane shows a real [role=tablist] (the enhancer runs
     on the preview — the exact bug the gallery slice first shipped).
  2. Nested add: open tab 2's nested "Add element -> Text", type, Save; the child
     lands nested under tab 2 and its body shows in the preview's second panel.
  3. Student click: panel 1 visible / panel 2 hidden; clicking tab 2 swaps the
     `hidden` attribute and `aria-selected` follows.
  4. Student keyboard: focus tab 1, ArrowRight activates+focuses tab 2 (automatic
     activation), Home returns to tab 1.
  5. Multi-instance isolation: two tabs elements that SHARE tab ids; activating a
     tab in the second leaves the first's active panel untouched (namespaced ids).
  6. Reveal handshake: a gallery inside a hidden tab measures zero until revealed;
     clicking the tab fires libli:reveal and the carousel stage gets real height.

A second section at the bottom covers the CAROUSEL display mode (plan Task 11): slide
ARIA, init, advance, inert, height reservation, the status region, the two boundary
cases, focus rescue, nesting in all three directions, arrow-key ownership against a
nested gallery and a scrollable box, the mid-fade reversal, the no-op editor re-save
and the error bail. Read the STANDING RULE on focus preconditions above that section
before touching any keyboard case.

Modeled on tests/test_e2e_editor_ws3.py (editor half) and tests/test_e2e_gallery.py
(student half). Marked e2e (excluded from the default run)."""

import os
import re
import types

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Shared login / seed helpers
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


def _seed_tabs_element(
    unit,
    tabs,
    children=None,
    display="tabs",
    label_pos="above",
    parent=None,
    tab_id="",
):
    """Attach one TabsElement to `unit`.

    `tabs` is [(tab_id, label)]; `children` maps tab_id -> [concrete element obj].
    Returns (obj, join). Fixed 't' + 6-hex ids let two elements deliberately SHARE
    ids (the isolation scenario), which the namespaced DOM ids must survive.

    `display` / `label_pos` are the carousel-mode enums (plan Task 11): the data
    literal below is the SOLE writer of this element's blob, so without threading
    them here no fixture in this file could build a carousel at all. Both keep the
    model defaults, so the seven pre-carousel call sites -- all positional in
    (unit, tabs[, children]) -- are unaffected.

    `parent` / `tab_id` place the join row INSIDE another container's slot, which is
    how the nesting fixtures build tabs-in-carousel and carousel-in-tabs.
    """
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={
            "tabs": [{"id": tid, "label": label} for tid, label in tabs],
            "display": display,
            "label_pos": label_pos,
        }
    )
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab_id
    )
    for tid, objs in (children or {}).items():
        for child_obj in objs:
            Element.objects.create(
                unit=unit, content_object=child_obj, parent=join, tab_id=tid
            )
    return obj, join


# ---------------------------------------------------------------------------
# Editor half: authoring + nested add (real gestures)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_authoring_add_tabs_previews_a_real_tab_strip(page, live_server):
    """Scenario 1. Add Tabs via the real add-menu gesture and Save. The editor list
    grows two tab rows, and the live-preview pane shows an enhanced [role=tablist]
    (NOT the stacked no-JS fallback). This is the exact regression the gallery slice
    first shipped, where the preview never loaded the enhancer."""
    from courses.models import Element
    from courses.models import TabsElement

    pa = _make_pa_user("tabs_auth")
    course, unit = _seed_unit(pa, "tabs-auth")
    _login(page, live_server, "tabs_auth")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # Real add gesture: open the add-menu, click the Tabs card, wait for the editor.
    # Scoped to the TOP-LEVEL menu (the one without .addwrap--nested). Since depth-3
    # nesting a container's nested menu offers the Tabs card too, so an unscoped
    # [data-add-type='tabs'] would match more than one button the moment the unit holds
    # a container and would fail Playwright strict mode.
    top_menu = page.locator("[data-add-menu]:not(.addwrap--nested)")
    top_menu.locator("[data-add-toggle]").click()
    top_menu.locator("[data-add-type='tabs']").click()
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor]")

    # Save with the two default tabs untouched.
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()

    # The saved tabs row carries one <details.tabs-rows> per tab.
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs')
    assert page.locator('[data-scope="editor"] .el-row--tabs .tabs-rows').count() == 2

    # The live preview must render an ENHANCED tab strip, not the no-JS stack.
    page.wait_for_selector('[data-scope="preview"] .el--tabs.tabs--js')
    preview_tabs = page.locator('[data-scope="preview"] .el--tabs')
    assert preview_tabs.locator('[role="tablist"]').count() == 1
    assert preview_tabs.locator('[role="tab"]').count() == 2

    # Persisted as a real TabsElement with two tabs.
    join = Element.objects.get(unit=unit)
    obj = TabsElement.objects.get(pk=join.object_id)
    assert len(obj.data["tabs"]) == 2


@pytest.mark.django_db(transaction=True)
def test_nested_add_text_into_tab_two(page, live_server):
    """Scenario 2. With a tabs element present, expand tab 2, drive its nested
    "Add element -> Text", type a body, and Save. The child lands nested under tab 2
    (not at top level) and its text shows in the preview's second panel."""
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("tabs_nest")
    course, unit = _seed_unit(pa, "tabs-nest")
    obj, join = _seed_tabs_element(unit, [("t000001", "First"), ("t000002", "Second")])
    _login(page, live_server, "tabs_nest")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs')

    # Open tab 2's section, then drive its OWN nested add menu (the second one — the
    # first is tab 1, plus the top-level menu). data-parent/data-tab on that menu are
    # what land the child in tab 2.
    tab2 = page.locator(
        '[data-scope="editor"] .el-row--tabs .el-row__tabs > details.tabs-rows'
    ).nth(1)
    tab2.locator("summary").click()
    tab2.locator("[data-add-toggle]").click()
    tab2.locator("[data-add-type='text']").click()

    # The new text form appears at the bottom of the editor, carrying the hidden
    # parent/tab scope. Type into the RTE surface (syncs to textarea[name=body]).
    surface = page.locator("[data-edit-slot] form[data-op='element-save'] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Nested body text")

    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()

    # The preview's second panel must contain the typed body (panel 2 is hidden after
    # enhancement, so read text_content, which ignores visibility).
    page.wait_for_selector('[data-scope="preview"] .el--tabs.tabs--js')
    panels = page.locator('[data-scope="preview"] .el--tabs [data-tab-panel]')
    page.wait_for_function(
        """() => {
            const p = document.querySelectorAll(
                '[data-scope=\"preview\"] .el--tabs [data-tab-panel]');
            return p.length === 2 && /Nested body text/.test(p[1].textContent);
        }"""
    )
    assert "Nested body text" not in (panels.nth(0).text_content() or "")

    # The child persisted nested under tab 2, keeping its unit FK.
    child = Element.objects.get(parent=join)
    assert child.tab_id == "t000002"
    assert child.unit_id == unit.pk
    assert TextElement.objects.filter(pk=child.object_id).exists()

    # And it renders in tab 2's nested list in the editor (indented, not top level).
    tab2_rows = page.locator(
        '[data-scope="editor"] .el-row--tabs .el-row__tabs > details.tabs-rows'
    ).nth(1)
    assert tab2_rows.locator(".element-list--nested .el-row").count() == 1


@pytest.mark.django_db(transaction=True)
def test_top_level_drag_reorder_survives_an_expanded_tabs_element(page, live_server):
    """Regression: the editor DnD queried `.el-row` with a DESCENDANT selector, which
    now also matches a tabs element's nested child rows. Using a nested row (not a
    child of the top-level list) as the insertBefore reference throws NotFoundError,
    silently breaking reorder whenever an expanded tabs element sits in the unit.

    Drives the real HTML5 drag sequence, hovering FIRST over the nested child zone
    (where the buggy code threw) and then over the top-level target, and asserts no
    page error fired and the top-level rows actually reordered."""
    from courses.models import Element
    from courses.models import TextElement

    pa = _make_pa_user("tabs_dnd")
    course, unit = _seed_unit(pa, "tabs-dnd")
    # Top-level A, then a tabs element whose FIRST tab (open by default) holds a nested
    # child, then top-level B. Creation order == top-level display order.
    a = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="AAA top")
    )
    _seed_tabs_element(
        unit,
        [("t000001", "First"), ("t000002", "Second")],
        children={
            "t000001": [
                TextElement.objects.create(body="nested child one"),
                TextElement.objects.create(body="nested child two"),
            ]
        },
    )
    b = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="BBB top")
    )

    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    _login(page, live_server, "tabs_dnd")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs')

    editor = '[data-scope="editor"]'
    grip = page.locator(f'{editor} .element-list > [data-element="{b.pk}"] .ica--grip')
    nested_list = page.locator(f"{editor} .el-row--tabs .element-list--nested").first
    nested_list.wait_for(state="visible")  # first tab open, so children are on-screen

    # VIEWPORT coords (getBoundingClientRect) — what the dragover handler compares
    # against — NOT bounding_box (page coords), which desync from clientY the moment
    # the pane scrolls (e.g. under the new drag auto-scroll).
    def rect(sel):
        return page.evaluate(
            "(s)=>{const r=document.querySelector(s).getBoundingClientRect();"
            "return {top:r.top, height:r.height};}",
            sel,
        )

    list_sel = page.locator(f"{editor} .element-list").first

    def drive_drag():
        # One real drag gesture: dragstart on the grip, then a SWEEP of dragover clientY
        # across the nested child zone. The buggy descendant query resolves `before` to
        # a nested row in this band, and list.insertBefore(line, nestedRow) throws
        # NotFoundError (a nested row is a descendant, not a child of the list).
        # Sweeping the whole zone is deterministic. Then a dragover+drop in A's upper
        # quarter so `before` == A -> B lands before A. Rects are recomputed each call,
        # so a re-drive stays coordinate-correct after any auto-scroll.
        dt = page.evaluate_handle("() => new DataTransfer()")
        grip.dispatch_event("dragstart", {"dataTransfer": dt})
        nz = rect(f"{editor} .el-row--tabs .element-list--nested")
        for y in range(int(nz["top"] - 4), int(nz["top"] + nz["height"] + 4), 3):
            list_sel.dispatch_event("dragover", {"dataTransfer": dt, "clientY": y})
        ab = rect(f'{editor} .element-list > [data-element="{a.pk}"]')
        a_y = ab["top"] + ab["height"] * 0.25
        list_sel.dispatch_event("dragover", {"dataTransfer": dt, "clientY": a_y})
        list_sel.dispatch_event("drop", {"dataTransfer": dt, "clientY": a_y})
        grip.dispatch_event("dragend", {"dataTransfer": dt})

    # The reorder POSTs to the server and swaps the pane; B must end up before A at top
    # level. That POST is fire-and-forget in editor_dnd.js (no catch/retry), so under
    # CI's parallel e2e (`-m e2e -n 2`) a single request occasionally gets starved on
    # the 2-core runner and never completes — the pane then never swaps and a lone wait
    # hangs the whole budget (widening it to 60s did NOT help — see PR #109). So
    # RE-DRIVE the gesture up to 3 times, each firing a fresh POST, and pass as soon as
    # the order flips. Re-driving is idempotent: B is dragged to position 0 either way.
    reordered = """(pks) => {
        const rows = document.querySelectorAll(
            '[data-scope="editor"] .element-list > .el-row');
        const order = Array.from(rows).map(r => r.getAttribute('data-element'));
        const ia = order.indexOf(String(pks.a)), ib = order.indexOf(String(pks.b));
        return ia !== -1 && ib !== -1 && ib < ia;
    }"""
    last_exc = None
    for _ in range(3):
        drive_drag()
        try:
            page.wait_for_function(reordered, arg={"a": a.pk, "b": b.pk}, timeout=20000)
            last_exc = None
            break
        except PlaywrightTimeoutError as exc:
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    # A dropped reorder POST that gets re-driven surfaces as a 'Failed to fetch'
    # rejection (editor_dnd.js's fetch has no catch) — CI infra noise, not the bug under
    # test. Assert no OTHER page error fired; crucially the descendant-selector
    # NotFoundError this test guards is NOT a fetch failure and would still trip here.
    real_errors = [e for e in errors if "Failed to fetch" not in e]
    assert real_errors == [], f"drag threw a page error: {real_errors}"


# ---------------------------------------------------------------------------
# Student half: click, keyboard, isolation, reveal handshake
# ---------------------------------------------------------------------------


def _seed_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


@pytest.fixture
def lesson_with_tabs(page, live_server):
    """Enrolled student on a lesson with one tabs element: tab 1 ("Overview") and
    tab 2 ("Details"), each holding a distinct text child."""
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student("tabs_click")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    _seed_tabs_element(
        unit,
        [("t000001", "Overview"), ("t000002", "Details")],
        {
            "t000001": [TextElement.objects.create(body="<p>panel one body</p>")],
            "t000002": [TextElement.objects.create(body="<p>panel two body</p>")],
        },
    )
    EnrollmentFactory(student=student, course=course)
    _login(page, live_server, "tabs_click")
    return types.SimpleNamespace(lesson_url=_lesson_url(live_server, unit))


@pytest.mark.django_db(transaction=True)
def test_student_click_swaps_panels_and_aria(live_server, page, lesson_with_tabs):
    """Scenario 3. Panel 1 visible, panel 2 hidden; clicking tab 2 swaps the `hidden`
    attribute and aria-selected follows."""
    page.goto(lesson_with_tabs.lesson_url)
    tabs = page.locator("[data-tabs]").first
    page.wait_for_selector("[data-tabs].tabs--js")

    panels = tabs.locator("[data-tab-panel]")
    # At rest: first panel shown, second hidden.
    assert panels.nth(0).get_attribute("hidden") is None
    assert panels.nth(1).get_attribute("hidden") == ""
    overview = page.get_by_role("tab", name="Overview")
    details = page.get_by_role("tab", name="Details")
    assert overview.get_attribute("aria-selected") == "true"
    assert details.get_attribute("aria-selected") == "false"

    # Real click on tab 2.
    details.click()

    assert panels.nth(0).get_attribute("hidden") == ""
    assert panels.nth(1).get_attribute("hidden") is None
    assert overview.get_attribute("aria-selected") == "false"
    assert details.get_attribute("aria-selected") == "true"


@pytest.mark.django_db(transaction=True)
def test_student_keyboard_arrow_and_home(live_server, page, lesson_with_tabs):
    """Scenario 4. Focus tab 1, ArrowRight activates AND focuses tab 2 (automatic
    activation per ARIA practices); Home returns to tab 1."""
    page.goto(lesson_with_tabs.lesson_url)
    page.wait_for_selector("[data-tabs].tabs--js")
    overview = page.get_by_role("tab", name="Overview")
    details = page.get_by_role("tab", name="Details")

    overview.focus()
    page.keyboard.press("ArrowRight")
    assert details.get_attribute("aria-selected") == "true"
    # Automatic activation also moves focus to the newly-active tab.
    assert page.evaluate("() => document.activeElement.textContent") == "Details"

    page.keyboard.press("Home")
    assert overview.get_attribute("aria-selected") == "true"
    assert page.evaluate("() => document.activeElement.textContent") == "Overview"


@pytest.fixture
def lesson_with_math_tab_label(page, live_server):
    """Enrolled student on a lesson whose FIRST tab label carries inline math and
    whose children carry none — so the page only arms KaTeX if the label itself is
    inspected."""
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student("tabs_label_math")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    _seed_tabs_element(
        unit,
        [("t000001", r"Wzór \(x^2\)"), ("t000002", "Plain")],
        {
            "t000001": [TextElement.objects.create(body="<p>panel one body</p>")],
            "t000002": [TextElement.objects.create(body="<p>panel two body</p>")],
        },
    )
    EnrollmentFactory(student=student, course=course)
    _login(page, live_server, "tabs_label_math")
    return types.SimpleNamespace(lesson_url=_lesson_url(live_server, unit))


@pytest.mark.django_db(transaction=True)
def test_tab_label_math_is_typeset_in_the_strip(
    live_server, page, lesson_with_math_tab_label
):
    """A tab label's inline math must be TYPESET on the strip button — the only place
    a reader ever sees the label on screen (the <h3> it is copied from is sr-only once
    enhanced, surfacing only in print).

    Two independent defects shipped raw source here and both are caught by the same
    assertion: `has_math` never inspected the label, so KaTeX was not even loaded; and
    the strip button was built from `label.textContent`, which — after KaTeX HAS run
    over the <h3> — flattens the rendered math to the mangled "x2x^2x2"."""
    page.goto(lesson_with_math_tab_label.lesson_url)
    page.wait_for_selector("[data-tabs].tabs--js")

    first = page.locator("[data-tabs] .tabs__strip .tabs__tab").first
    # The button holds real KaTeX output, not text.
    page.wait_for_selector("[data-tabs] .tabs__strip .tabs__tab .katex", timeout=5000)
    assert first.locator(".katex").count() == 1

    text = first.text_content() or ""
    assert "\\(" not in text, f"raw math delimiter left in the tab strip: {text!r}"
    assert "Wzór" in text  # the prose around the math is still there

    # The second label has no math and must be left alone.
    second = page.locator("[data-tabs] .tabs__strip .tabs__tab").nth(1)
    assert (second.text_content() or "").strip() == "Plain"
    assert second.locator(".katex").count() == 0


@pytest.fixture
def lesson_with_two_tabs(page, live_server):
    """Enrolled student on a lesson with TWO tabs elements that deliberately SHARE
    their tab ids — the case the namespaced DOM ids exist to protect."""
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student("tabs_iso")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    shared = [("t000001", None), ("t000002", None)]
    _seed_tabs_element(
        unit,
        [("t000001", "A-one"), ("t000002", "A-two")],
        {
            "t000001": [TextElement.objects.create(body="<p>A first</p>")],
            "t000002": [TextElement.objects.create(body="<p>A second</p>")],
        },
    )
    _seed_tabs_element(
        unit,
        [("t000001", "B-one"), ("t000002", "B-two")],
        {
            "t000001": [TextElement.objects.create(body="<p>B first</p>")],
            "t000002": [TextElement.objects.create(body="<p>B second</p>")],
        },
    )
    del shared
    EnrollmentFactory(student=student, course=course)
    _login(page, live_server, "tabs_iso")
    return types.SimpleNamespace(lesson_url=_lesson_url(live_server, unit))


@pytest.mark.django_db(transaction=True)
def test_two_tabs_elements_are_isolated(live_server, page, lesson_with_two_tabs):
    """Scenario 5. Two tabs elements sharing tab ids: activating tab 2 of the SECOND
    leaves the FIRST's active panel unchanged (namespaced ids stop the cross-talk)."""
    page.goto(lesson_with_two_tabs.lesson_url)
    page.wait_for_selector("[data-tabs].tabs--js")
    els = page.locator("[data-tabs]")
    assert els.count() == 2
    first_panels = els.nth(0).locator("[data-tab-panel]")
    second_panels = els.nth(1).locator("[data-tab-panel]")

    # Both start on panel 1.
    assert first_panels.nth(0).get_attribute("hidden") is None
    assert second_panels.nth(0).get_attribute("hidden") is None

    # Activate the SECOND element's tab 2.
    page.get_by_role("tab", name="B-two").click()

    # The second element moved...
    assert second_panels.nth(0).get_attribute("hidden") == ""
    assert second_panels.nth(1).get_attribute("hidden") is None
    # ...the first element did NOT (despite sharing tab ids).
    assert first_panels.nth(0).get_attribute("hidden") is None
    assert first_panels.nth(1).get_attribute("hidden") == ""
    a_one = page.get_by_role("tab", name="A-one")
    assert a_one.get_attribute("aria-selected") == "true"


@pytest.fixture
def lesson_with_gallery_in_tab(page, live_server):
    """Enrolled student on a lesson whose tab 2 holds a 2-image gallery — a carousel
    inside a hidden panel, to exercise the reveal handshake."""
    from courses.models import GalleryElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_image_asset

    student = _seed_student("tabs_reveal")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    img_a = make_image_asset(course, filename="ra.png")
    img_b = make_image_asset(course, filename="rb.png")
    gallery = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": img_a.pk, "desc": ""},
                {"media": img_b.pk, "desc": ""},
            ],
        }
    )
    _seed_tabs_element(
        unit,
        [("t000001", "Intro"), ("t000002", "Pictures")],
        {
            "t000001": [TextElement.objects.create(body="<p>intro text</p>")],
            "t000002": [gallery],
        },
    )
    EnrollmentFactory(student=student, course=course)
    _login(page, live_server, "tabs_reveal")
    return types.SimpleNamespace(lesson_url=_lesson_url(live_server, unit))


@pytest.mark.django_db(transaction=True)
def test_reveal_handshake_gives_the_hidden_gallery_real_height(
    live_server, page, lesson_with_gallery_in_tab
):
    """Scenario 6. A gallery inside a hidden tab panel measures zero. Clicking its tab
    fires libli:reveal, gallery.js re-measures, and the carousel stage gets a real,
    non-zero height. Without the listener the carousel ships visibly collapsed while
    every other test still passes."""
    page.goto(lesson_with_gallery_in_tab.lesson_url)
    page.wait_for_selector("[data-tabs].tabs--js")
    # The gallery enhanced into a carousel (a .gallery__stage exists) but sits in the
    # hidden second panel, so wait for it ATTACHED, not visible.
    page.wait_for_selector("[data-tabs] .el--gallery.gallery--js", state="attached")

    # Reveal tab 2 with a real click.
    page.get_by_role("tab", name="Pictures").click()

    # After the reveal handshake + a frame, the stage has real height.
    page.wait_for_function(
        """() => {
            const s = document.querySelector('[data-tabs] .gallery__stage');
            return s && s.offsetHeight > 0;
        }""",
        timeout=5000,
    )
    stage_height = page.evaluate(
        "() => document.querySelector('[data-tabs] .gallery__stage').offsetHeight"
    )
    assert stage_height > 0


# ===========================================================================
# Carousel display mode (plan Task 11)
# ===========================================================================
#
# STANDING RULE for every keyboard case below: state where focus starts.
# Guard 3 in tabs.js is `e.target.closest("[data-tabs], [data-gallery]") ===
# container`, so a key pressed with focus on <body> returns BEFORE show() runs and
# most mutants named in the plan are unobservable. The natural setup -- focusing the
# nav-bar arrow -- makes rescueFocus() return early instead (its guard is
# `out.contains(document.activeElement)`), silently neutering every focus-movement
# case. So each test states its own precondition:
#   * focus inside a SLIDE for anything whose mutant lives in rescueFocus or in
#     show()'s focus/ordering steps;
#   * focus on the ENABLED ARROW for the two arrow-state cases.
# A slide is `inert` until it is active, so activate it before focusing into it.

CAROUSEL = "[data-tabs][data-display='carousel']"
SECTIONS = " > .tabs__stage > .tabs__section"
NAV = " > .tabs__cbar"

# Element.checkVisibility() defaults BOTH opacityProperty and visibilityProperty to
# false, so a bare call -- and Playwright's to_be_visible(), which shares the blind
# spot -- reports True for every opacity-hidden slide, i.e. for exactly the state the
# carousel parks inactive slides in. Both flags are mandatory in this file.
VISIBLE = (
    "(el) => el.checkVisibility("
    "{opacityProperty: true, visibilityProperty: true})"
)

SLIDE_STATE = """(sel) => [...document.querySelectorAll(sel)].map((s) => ({
  active: s.classList.contains("is-active"),
  inert: s.hasAttribute("inert"),
  ariaHidden: s.getAttribute("aria-hidden") === "true",
  visible: s.checkVisibility({opacityProperty: true, visibilityProperty: true}),
  opacity: s.style.opacity,
}))"""


def _text(html):
    from courses.models import TextElement

    return TextElement.objects.create(body=html)


def _link(slug):
    """A slide's focusable node, as a TextElement holding one real <a href>.

    NOT a link in a table cell (which is what the plan suggests): sanitize_cell's
    CELL_TAGS is {strong,b,em,i,u,br,span} with attributes={}, so every anchor in a
    cell is stripped at TableElement.save() and the cell ends up plain text.
    """
    return _text(f'<p><a href="https://example.com/{slug}">link {slug}</a></p>')


def _table(rows, cols, tag):
    from courses.models import TableElement

    cells = [
        [
            {"html": f"{tag} r{r} c{c} value", "halign": "left", "valign": "top"}
            for c in range(cols)
        ]
        for r in range(rows)
    ]
    return TableElement.objects.create(data={"cells": cells, "border": "grid"})


def _enrolled_lesson(page, live_server, username):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(student=student, course=course)
    return student, course, unit


def _seed_carousel(
    page, live_server, username, slides, *, display="carousel", label_pos="above"
):
    """Enrolled student on a lesson holding ONE tabs element.

    `slides` is [(label, [concrete element objs])]. Returns a namespace carrying the
    lesson url, the join row (for scoping to a top-level element) and the user.
    """
    student, _course, unit = _enrolled_lesson(page, live_server, username)
    tabs, children = [], {}
    for i, (label, objs) in enumerate(slides, start=1):
        tid = f"t{i:06d}"
        tabs.append((tid, label))
        children[tid] = objs
    obj, join = _seed_tabs_element(
        unit, tabs, children, display=display, label_pos=label_pos
    )
    _login(page, live_server, username)
    return types.SimpleNamespace(
        unit=unit,
        obj=obj,
        join=join,
        user=student,
        lesson_url=_lesson_url(live_server, unit),
    )


def _slide_no(page, root=CAROUSEL):
    """The 1-based index show() last committed, read off the live-region status.

    updateIndicator() writes it SYNCHRONOUSLY inside show(), so unlike `.is-active`
    (which both the outgoing and incoming slide carry for 320 ms) it is never smeared
    across the fade window.
    """
    txt = page.locator(f"{root}{NAV} > .tabs__status").inner_text()
    m = re.search(r"\d+", txt)
    assert m, f"unparsable carousel status: {txt!r}"
    return int(m.group())


def _settled(page, root=CAROUSEL):
    """Block until exactly one slide is opaque and every fade has run out.

    Two separate 320 ms windows make an immediate visibility assertion RED against a
    CORRECT build, and BOTH are covered here:

    * after a move, the outgoing section keeps `.is-active` and a computed opacity of
      ~1 until settleHidden() fires; and
    * after INIT, `.tabs--carousel` is added only once show(0) has succeeded, so every
      rest slide starts transitioning 1 -> 0 from that moment and reports a computed
      opacity of ~1 for the first frames of the page's life.

    Sync on the settled state, never on a sleep.
    """
    page.wait_for_function(
        """(sel) => {
             const all = [...document.querySelectorAll(sel)];
             if (all.filter((s) => s.classList.contains("is-active")).length !== 1) {
               return false;
             }
             if (!all.every((s) => s.style.opacity === "")) return false;
             return all.every((s) => {
               const o = parseFloat(getComputedStyle(s).opacity);
               return s.classList.contains("is-active") ? o === 1 : o === 0;
             });
           }""",
        arg=f"{root}{SECTIONS}",
    )


@pytest.mark.django_db(transaction=True)
def test_carousel_slides_are_named_groups_not_landmarks(page, live_server):
    """Every section carries role=group + aria-roledescription=slide, and an
    aria-labelledby resolving to its OWN h3.

    A named bare <section> maps to `region` -- a LANDMARK -- per HTML-AAM, so without
    the role a 10-slide carousel becomes 10 landmarks. (Mutant: delete the
    role="group" assignment.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_aria",
        [
            ("Alpha", [_text("<p>alpha body</p>")]),
            ("Beta", [_text("<p>beta body</p>")]),
        ],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    aria = page.evaluate(
        """(sel) => [...document.querySelectorAll(sel)].map((s) => {
             const id = s.getAttribute("aria-labelledby");
             const named = id ? document.getElementById(id) : null;
             return {
               role: s.getAttribute("role"),
               rd: s.getAttribute("aria-roledescription"),
               own: !!named && named.closest(".tabs__section") === s,
               tag: named ? named.tagName : null,
               name: named ? named.textContent.trim() : null,
             };
           })""",
        f"{CAROUSEL}{SECTIONS}",
    )
    assert [a["role"] for a in aria] == ["group", "group"]
    assert [a["rd"] for a in aria] == ["slide", "slide"]
    assert all(a["own"] for a in aria), f"name resolves outside its own slide: {aria}"
    assert [a["tag"] for a in aria] == ["H3", "H3"]
    assert [a["name"] for a in aria] == ["Alpha", "Beta"]


@pytest.mark.django_db(transaction=True)
def test_carousel_first_slide_is_live_after_init(page, live_server):
    """Slide 1 is .is-active, visible and NOT inert after load.

    (Mutants: initialise `idx` to 0 instead of -1 -- show(0) then hits the
    `target === idx` early return and every slide stays inert; or delete the
    first-show branch -- rescueFocus(undefined, ...) throws and the whole element
    bails. Both are "the feature silently never ran" failures.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_init",
        [("One", [_text("<p>one body</p>")]), ("Two", [_text("<p>two body</p>")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
    _settled(page)

    state = page.evaluate(SLIDE_STATE, f"{CAROUSEL}{SECTIONS}")
    assert len(state) == 2
    assert state[0]["active"], f"slide 1 never activated: {state}"
    assert not state[0]["inert"], f"slide 1 left inert: {state}"
    assert not state[0]["ariaHidden"]
    assert state[0]["visible"]
    assert state[1]["inert"] and state[1]["ariaHidden"]
    assert not state[1]["visible"]


@pytest.mark.django_db(transaction=True)
def test_carousel_next_swaps_which_slide_is_visible(page, live_server):
    """Click the real chevron: slide 2's table becomes visible and slide 1 stops
    being visible. The NEGATIVE direction is the load-bearing half -- the positive
    alone is vacuous, since the stacked fallback shows every slide."""
    car = _seed_carousel(
        page,
        live_server,
        "car_adv",
        [("One", [_table(3, 3, "one")]), ("Two", [_table(3, 3, "two")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
    _settled(page)

    first = page.locator(f"{CAROUSEL}{SECTIONS}").nth(0)
    second = page.locator(f"{CAROUSEL}{SECTIONS}").nth(1)
    assert first.locator("table").evaluate(VISIBLE) is True
    assert second.locator("table").evaluate(VISIBLE) is False

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    # The outgoing slide keeps .is-active and opacity ~1 for the full 320 ms fade, so
    # asserting the negative NOW would be red against a correct build. Sync on settle.
    _settled(page)

    assert second.locator("table").evaluate(VISIBLE) is True
    assert first.locator("table").evaluate(VISIBLE) is False
    assert _slide_no(page) == 2


@pytest.mark.django_db(transaction=True)
def test_carousel_inactive_slide_is_inert_and_untabbable(page, live_server):
    """After advancing, slide 1 is aria-hidden AND inert (both set synchronously at
    show()'s step 8), and a focusable inside an inactive slide cannot be tabbed to.

    A link stands in for the plan's "input": a TabsElement child carrying a real
    <input> also swallows arrow keys via guard 1, which would confound the keyboard
    cases this file shares fixtures with."""
    car = _seed_carousel(
        page,
        live_server,
        "car_inert",
        [("One", [_link("one")]), ("Two", [_link("two")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    # At rest slide 2 is inert: a tab sweep starting inside slide 1 never reaches it.
    page.locator(f"{CAROUSEL}{SECTIONS}").nth(0).locator("a").focus()
    seen = []
    for _ in range(10):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("() => (document.activeElement || {}).href || ''"))
    assert not any("example.com/two" in href for href in seen), (
        f"tabbed into an inert slide: {seen}"
    )

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    state = page.evaluate(SLIDE_STATE, f"{CAROUSEL}{SECTIONS}")
    assert state[0]["inert"], f"outgoing slide not inerted synchronously: {state}"
    assert state[0]["ariaHidden"]


@pytest.mark.django_db(transaction=True)
def test_carousel_stage_reserves_the_tallest_slide(page, live_server):
    """The stage's height is unchanged between slides AND >= the tallest section.

    Slide 1 is a 3-row table, slide 2 a 10-row one: a height check against similar
    slides passes trivially on a broken build. Stability alone is ALSO vacuous --
    once the sections are absolutely positioned the stage's height IS its min-height
    by construction, so a build reserving only slide 1's height passes a stability
    check while the tall slide overflows the nav. Both sides are measured with
    offsetHeight (a rounded integer); mixing in bounding_box()'s fractional height
    makes `412 >= 412.32` fail against a correct build."""
    car = _seed_carousel(
        page,
        live_server,
        "car_height",
        [("Short", [_table(3, 3, "short")]), ("Tall", [_table(10, 3, "tall")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    probe = """(sel) => {
      const c = document.querySelector(sel);
      const stage = c.querySelector(":scope > .tabs__stage");
      const nav = c.querySelector(":scope > .tabs__cbar");
      return {
        stage: stage.offsetHeight,
        sections: [...stage.children].map((s) => s.offsetHeight),
        nav: nav.offsetTop,
      };
    }"""
    before = page.evaluate(probe, CAROUSEL)
    assert before["sections"][1] > before["sections"][0], (
        f"fixture is not differential -- both slides measure alike: {before}"
    )
    assert before["stage"] >= max(before["sections"]), (
        f"stage reserved less than the tallest slide: {before}"
    )

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    _settled(page)
    after = page.evaluate(probe, CAROUSEL)
    assert after["stage"] == before["stage"], f"stage reflowed: {before} -> {after}"
    assert after["stage"] >= max(after["sections"]), after
    assert after["nav"] == before["nav"], f"nav bar moved: {before} -> {after}"


@pytest.mark.django_db(transaction=True)
def test_carousel_status_and_dot_report_the_position(page, live_server):
    """.tabs__status reads "Slide 2 of 3" and the active dot carries
    aria-current="true"."""
    car = _seed_carousel(
        page,
        live_server,
        "car_status",
        [
            ("One", [_text("<p>one</p>")]),
            ("Two", [_text("<p>two</p>")]),
            ("Three", [_text("<p>three</p>")]),
        ],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    status = page.locator(f"{CAROUSEL}{NAV} > .tabs__status")
    assert status.inner_text().strip() == "Slide 1 of 3"

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    assert status.inner_text().strip() == "Slide 2 of 3"

    current = page.evaluate(
        """(sel) => [...document.querySelectorAll(sel)]
             .map((d) => d.getAttribute("aria-current"))""",
        f"{CAROUSEL}{NAV} > .tabs__dots > .tabs__dot",
    )
    assert current == [None, "true", None], current


@pytest.mark.django_db(transaction=True)
def test_carousel_arrows_clamp_at_both_boundaries(page, live_server):
    """prev is disabled on slide 1, next on the last -- and the key that would step
    PAST the end is a no-op with no page error.

    FOCUS PRECONDITION: the ENABLED arrow (a disabled button cannot take focus). From
    <body> guard 3 returns before show() is ever called, and this case would pass on a
    build with clamp deleted. (Mutant: drop clamp / pass `n` straight through ->
    show(-1) -> sections[-1] is undefined -> inn.removeAttribute throws inside a
    keydown handler, outside the init try/catch -> the error assertion goes RED.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_bounds",
        [
            ("One", [_link("one")]),
            ("Two", [_link("two")]),
            ("Three", [_link("three")]),
        ],
    )
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    prev = page.locator(f"{CAROUSEL}{NAV} > .tabs__cprev")
    nxt = page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext")
    assert prev.is_disabled() and not nxt.is_disabled()

    nxt.focus()
    page.keyboard.press("ArrowLeft")
    assert _slide_no(page) == 1
    assert errors == [], f"stepping past the start threw: {errors}"

    nxt.click()
    _settled(page)
    nxt.click()
    _settled(page)
    assert _slide_no(page) == 3
    assert nxt.is_disabled() and not prev.is_disabled()

    prev.focus()
    page.keyboard.press("ArrowRight")
    assert _slide_no(page) == 3
    assert errors == [], f"stepping past the end threw: {errors}"


@pytest.mark.django_db(transaction=True)
def test_carousel_walks_backwards_then_forwards_again(page, live_server):
    """The ONLY case that can falsify show()'s step 4 running BEFORE step 7.

    Slide 1 holds nothing focusable (a plain table) and slide 2 a link. Focus the
    link, ArrowLeft to slide 1, then ArrowRight -- the index must advance again.
    (Mutant: move the four prev/next.disabled / aria-disabled lines below
    rescueFocus(out, inn). Every forward-walking case stays green under it: the
    fallback picks `prev` while it is still enabled, focuses it, and only then does
    `prev.disabled = true` blur focus to <body>, where guard 3 kills the next key.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_back",
        [("Plain", [_table(4, 3, "plain")]), ("Linked", [_link("two")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    _settled(page)
    # FOCUS PRECONDITION: inside the outgoing SLIDE, not on the nav bar -- rescueFocus
    # returns early when focus is already on the bar and the mutant goes unobserved.
    page.locator(f"{CAROUSEL}{SECTIONS}").nth(1).locator("a").focus()

    page.keyboard.press("ArrowLeft")
    assert _slide_no(page) == 1

    page.keyboard.press("ArrowRight")
    assert _slide_no(page) == 2, (
        "focus was blurred to <body> by disabling the arrow it had just been "
        "rescued onto, so the next key never reached the carousel"
    )


@pytest.mark.django_db(transaction=True)
def test_carousel_moves_focus_off_the_arrow_it_disables(page, live_server):
    """The only case that can see step 4b.

    FOCUS PRECONDITION: the ENABLED arrow -- clicking it focuses it. With focus
    inside a slide `focusedArrow` is null, 4b never runs, and the rescue's nav-bar
    fallback picks `prev` anyway (next is disabled at the last slide), so
    activeElement is `prev` WITH 4b deleted too. (Mutant: delete step 4b -> disabling
    the focused `next` blurs to <body> -> RED.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_bfocus",
        [("One", [_text("<p>one</p>")]), ("Two", [_text("<p>two</p>")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    assert _slide_no(page) == 2
    where = page.evaluate(
        "() => document.activeElement ? document.activeElement.className : null"
    )
    assert where == "tabs__cprev", f"focus was dropped to <{where}> at the boundary"

    page.keyboard.press("ArrowLeft")
    assert _slide_no(page) == 1


@pytest.mark.django_db(transaction=True)
def test_carousel_rescues_focus_into_the_incoming_slide(page, live_server):
    """Focus lands INSIDE the incoming section, not on the nav bar.

    FOCUS PRECONDITION: both slides hold a focusable and the test focuses the
    OUTGOING slide's link first. rescueFocus opens with
    `if (!out.contains(document.activeElement)) return;`, so focusing the chevron
    instead makes it return early, activeElement stays on the chevron -- which IS in
    .tabs__cbar -- and this assertion goes RED against CORRECT code. Guards against an
    over-strict focusable() predicate degrading silently to the nav-bar fallback."""
    car = _seed_carousel(
        page,
        live_server,
        "car_rescue",
        [("One", [_link("one")]), ("Two", [_link("two")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    page.locator(f"{CAROUSEL}{SECTIONS}").nth(0).locator("a").focus()
    page.keyboard.press("ArrowRight")

    landed = page.evaluate(
        """(sel) => {
          const a = document.activeElement;
          const secs = document.querySelectorAll(sel);
          return {
            inIncoming: !!a && secs[1].contains(a),
            inNav: !!a && !!a.closest(".tabs__cbar"),
            href: a && a.href ? a.href : null,
          };
        }""",
        f"{CAROUSEL}{SECTIONS}",
    )
    assert landed["inIncoming"], f"focus never reached the incoming slide: {landed}"
    assert not landed["inNav"], f"focus fell back to the nav bar: {landed}"
    assert landed["href"].endswith("/two")


@pytest.mark.django_db(transaction=True)
def test_carousel_two_arrow_presses_advance_twice(page, live_server):
    """A build broken at show()'s steps 5/7/8 survives exactly ONE press.

    Needs THREE slides: with two, the second press hits clamp + the `target === idx`
    early return on CORRECT code, so "advances again" would be red against a healthy
    build. FOCUS PRECONDITION: slide 1 must hold a focusable and the test must focus
    it -- the 5/7/8 breakage only kills the second press when focus was INSIDE the
    outgoing section (step 8 inerts it and focus blurs to <body>). Focus the chevron
    instead and rescueFocus returns early on a correct build too, so both presses
    advance under the very mutant this case exists for."""
    car = _seed_carousel(
        page,
        live_server,
        "car_two",
        [("One", [_link("one")]), ("Two", [_link("two")]), ("Three", [_link("three")])],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    page.locator(f"{CAROUSEL}{SECTIONS}").nth(0).locator("a").focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")

    assert _slide_no(page) == 3
    state = page.evaluate(SLIDE_STATE, f"{CAROUSEL}{SECTIONS}")
    assert state[2]["active"], f"slide 3 never activated: {state}"
    assert state[1]["inert"], f"slide 2 left live behind the fade: {state}"


@pytest.mark.django_db(transaction=True)
def test_carousel_rescue_skips_a_nested_instance(page, live_server):
    """The guard for focusable()'s fourth filter (node OWNERSHIP).

    Slide 1 holds a link, slide 2 a NESTED tabs element, slide 3 plain text; focus the
    link, then ArrowRight twice -- the outer carousel must reach slide 3. The ordering
    is what makes it falsifiable: focus the outer chevron instead and rescueFocus
    returns early, so it passes with or without the filter (vacuous); focus the nested
    panel and guard 3 correctly refuses to advance (RED against correct code).
    (Mutant: delete the `n.closest("[data-tabs], [data-gallery]") !== container`
    filter -> the rescue lands inside the inner instance, whose own strip handler then
    consumes the second ArrowRight -> the outer never moves -> RED.)"""
    student, _course, unit = _enrolled_lesson(page, live_server, "car_nestfocus")
    _obj, join = _seed_tabs_element(
        unit,
        [("t000001", "One"), ("t000002", "Two"), ("t000003", "Three")],
        {
            "t000001": [_link("one")],
            "t000003": [_text("<p>third slide</p>")],
        },
        display="carousel",
    )
    _seed_tabs_element(
        unit,
        [("t000021", "Inner A"), ("t000022", "Inner B")],
        {
            "t000021": [_text("<p>inner a body</p>")],
            "t000022": [_text("<p>inner b body</p>")],
        },
        parent=join,
        tab_id="t000002",
    )
    del student
    _login(page, live_server, "car_nestfocus")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
    page.wait_for_selector(f"{CAROUSEL} .el--tabs.tabs--js [role='tablist']")

    page.locator(f"{CAROUSEL}{SECTIONS}").nth(0).locator("a").focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")

    assert _slide_no(page) == 3, (
        "focus was rescued into the NESTED instance, so guard 3 resolved the second "
        "key to the inner container and the outer carousel stalled"
    )


@pytest.mark.django_db(transaction=True)
def test_nested_gallery_owns_its_own_arrow_keys(page, live_server):
    """One ArrowRight with focus inside a nested gallery moves the GALLERY by one and
    leaves the carousel's index untouched (guard 3 + the defaultPrevented check)."""
    from courses.models import GalleryElement
    from tests.factories import make_image_asset

    student, course, unit = _enrolled_lesson(page, live_server, "car_gal")
    img_a = make_image_asset(course, filename="ca.png")
    img_b = make_image_asset(course, filename="cb.png")
    gallery = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": img_a.pk, "desc": ""},
                {"media": img_b.pk, "desc": ""},
            ],
        }
    )
    _seed_tabs_element(
        unit,
        [("t000001", "Pictures"), ("t000002", "Plain")],
        {"t000001": [gallery], "t000002": [_text("<p>plain</p>")]},
        display="carousel",
    )
    del student
    _login(page, live_server, "car_gal")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
    page.wait_for_selector(f"{CAROUSEL} .el--gallery.gallery--js")

    gal_status = page.locator(f"{CAROUSEL} .el--gallery .gallery__status")
    assert gal_status.inner_text().strip() == "Image 1 of 2"
    assert _slide_no(page) == 1

    page.locator(f"{CAROUSEL} .el--gallery .gallery__next").focus()
    page.keyboard.press("ArrowRight")

    assert gal_status.inner_text().strip() == "Image 2 of 2"
    assert _slide_no(page) == 1, "one key press moved BOTH the gallery and the carousel"


@pytest.mark.django_db(transaction=True)
def test_carousel_reveal_event_reaches_document(page, live_server):
    """show()'s libli:reveal must BUBBLE.

    Deliberately NOT "a nested gallery's stage height is non-zero": that is true with
    `bubbles` deleted, for two independent reasons -- lesson_unit.html loads
    gallery.js BEFORE tabs.js, so the gallery measures during the stacked fallback,
    and this spec keeps inactive slides laid out, so it measures non-zero anyway.
    Instrument the delegated listener instead. The `= 0` initialiser is required:
    without it the first increment yields NaN and every comparison is false, i.e. RED
    against correct code. (Mutant: drop `bubbles: true` -> the event never reaches
    document -> the counter stays 0 -> RED.)"""
    from courses.models import GalleryElement
    from tests.factories import make_image_asset

    student, course, unit = _enrolled_lesson(page, live_server, "car_reveal")
    img_a = make_image_asset(course, filename="rv1.png")
    img_b = make_image_asset(course, filename="rv2.png")
    gallery = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": img_a.pk, "desc": ""},
                {"media": img_b.pk, "desc": ""},
            ],
        }
    )
    _seed_tabs_element(
        unit,
        [("t000001", "Intro"), ("t000002", "Pictures")],
        {"t000001": [_text("<p>intro</p>")], "t000002": [gallery]},
        display="carousel",
    )
    del student
    _login(page, live_server, "car_reveal")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")

    # ONE call: the counter and its listener must be installed together, after the
    # first show() has already fired its own reveal.
    page.evaluate(
        """() => {
          window.__reveals = 0;
          document.addEventListener("libli:reveal", () => { window.__reveals++; });
        }"""
    )
    assert page.evaluate("() => window.__reveals") == 0

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    assert page.evaluate("() => window.__reveals") >= 1, (
        "libli:reveal never reached document -- a nested gallery would never be told "
        "to re-measure"
    )


@pytest.mark.django_db(transaction=True)
def test_carousel_yields_arrow_keys_to_a_scrollable_box(page, live_server):
    """Guard 2 walks ancestors from e.target and tests MEASURED scrollability, so the
    outcome depends entirely on what holds focus.

    Slide 1 is an over-wide table, slide 2 a narrow one: inside the wide table the key
    scrolls the wrapper and does NOT advance; inside the narrow one (nothing to
    scroll) it still advances.

    Both wrappers are given an explicit tabindex first. The plan's fixture -- a link
    in a cell -- is UNBUILDABLE: sanitize_cell's CELL_TAGS is
    {strong,b,em,i,u,br,span} with attributes={}, so an anchor in a cell is stripped
    at save(). And Chromium makes a SCROLLABLE box keyboard-focusable on its own but
    not a non-scrollable one, so relying on that would make the two halves differ for
    the wrong reason. With both boxes explicitly focusable, guard 2's measured
    overflow is the ONLY difference left between them."""
    car = _seed_carousel(
        page,
        live_server,
        "car_scroll",
        [
            ("Wide", [_table(3, 14, "wide")]),
            ("Narrow", [_table(3, 2, "n")]),
            ("Last", [_text("<p>last</p>")]),
        ],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
    page.evaluate(
        """(sel) => document.querySelectorAll(sel)
             .forEach((b) => b.setAttribute("tabindex", "0"))""",
        f"{CAROUSEL}{SECTIONS} .el--table__scroll",
    )

    box = """(sel) => {
      const b = document.querySelector(sel);
      return {
        scrollable: b.scrollWidth > b.clientWidth,
        left: b.scrollLeft,
        focused: document.activeElement === b,
      };
    }"""
    wide_sel = f"{CAROUSEL}{SECTIONS}:nth-child(1) .el--table__scroll"
    narrow_sel = f"{CAROUSEL}{SECTIONS}:nth-child(2) .el--table__scroll"

    page.locator(wide_sel).focus()
    before = page.evaluate(box, wide_sel)
    assert before["scrollable"], (
        f"the wide fixture does not actually overflow: {before}"
    )
    assert before["focused"], "could not put focus inside the wide scroll box"

    page.keyboard.press("ArrowRight")
    page.wait_for_function(
        "(sel) => document.querySelector(sel).scrollLeft > 0", arg=wide_sel
    )
    assert _slide_no(page) == 1, "a scrollable box did not keep its own arrow keys"

    page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
    _settled(page)
    page.locator(narrow_sel).focus()
    narrow = page.evaluate(box, narrow_sel)
    assert not narrow["scrollable"], f"the narrow fixture overflows too: {narrow}"
    assert narrow["focused"], "could not put focus inside the narrow scroll box"

    page.keyboard.press("ArrowRight")
    assert _slide_no(page) == 3, (
        "a class-only (unmeasured) guard would swallow the key here and the arrow "
        "would do nothing at all"
    )


@pytest.mark.django_db(transaction=True)
def test_carousel_survives_a_reversal_inside_the_fade_window(page, live_server):
    """Going BACK inside the 320 ms fade window leaves a permanently broken state on
    a build with finalizePending() neutered: the orphaned timer fires settleHidden on
    the slide now on screen, so ZERO slides end .is-active.

    Deliberately not the next-then-next case: there the orphaned timer settles slide 0
    and the second timer later settles slide 1, so the END state is still exactly one
    opaque slide and only a mid-window sample fails -- a race-window assertion. Both
    activations are issued from a SINGLE page.evaluate so the second lands inside the
    window deterministically; a correct build passes at any timing, but if the second
    click landed after the timer both mutants would also end clean and the
    falsification would silently report green. (Mutants: `return;` at the top of
    finalizePending(), or drop its clearTimeout.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_midfade",
        [
            ("One", [_text("<p>one</p>")]),
            ("Two", [_text("<p>two</p>")]),
            ("Three", [_text("<p>three</p>")]),
        ],
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
    _settled(page)

    page.evaluate(
        """(sel) => {
          const nav = document.querySelector(sel);
          nav.querySelector(".tabs__cnext").click();
          nav.querySelector(".tabs__cprev").click();
        }""",
        f"{CAROUSEL}{NAV}",
    )
    # Both builds converge to "no inline opacity left" once every timer has run, so
    # this waits out the window without asserting anything about it.
    page.wait_for_function(
        """(sel) => [...document.querySelectorAll(sel)]
             .every((s) => s.style.opacity === "")""",
        arg=f"{CAROUSEL}{SECTIONS}",
    )

    state = page.evaluate(SLIDE_STATE, f"{CAROUSEL}{SECTIONS}")
    live = [i for i, s in enumerate(state) if s["active"] and s["visible"]]
    assert live == [0], f"expected exactly slide 1 left active and opaque: {state}"
    assert not any(s["inert"] and s["visible"] for s in state), state
    assert _slide_no(page) == 1


def _top(join):
    """The student-side scope for ONE top-level element, so a nested [data-tabs]
    can never be mistaken for its host."""
    return f"section[data-element-id='{join.pk}'] > .lesson-block__body > .el--tabs"


@pytest.mark.django_db(transaction=True)
def test_carousel_nests_in_all_three_directions(page, live_server):
    """tabs-in-carousel, carousel-in-carousel and carousel-in-tabs each render
    visible and operable.

    The third is the regression test for the label rules (failure mode: the inner
    carousel silently loses every caption, because the tabs-mode sr-only rule reached
    it through a descendant selector); the first two for the child combinators
    (failure mode: a completely blank inner element)."""
    student, _course, unit = _enrolled_lesson(page, live_server, "car_nest3")

    _a, a_join = _seed_tabs_element(
        unit,
        [("t000101", "A one"), ("t000102", "A two")],
        {"t000102": [_text("<p>a slide two</p>")]},
        display="carousel",
    )
    _seed_tabs_element(
        unit,
        [("t000111", "Inner tab one"), ("t000112", "Inner tab two")],
        {
            "t000111": [_text("<p>inner tab one body</p>")],
            "t000112": [_text("<p>inner tab two body</p>")],
        },
        parent=a_join,
        tab_id="t000101",
    )

    _b, b_join = _seed_tabs_element(
        unit,
        [("t000201", "B one"), ("t000202", "B two")],
        {"t000202": [_text("<p>b slide two</p>")]},
        display="carousel",
    )
    _seed_tabs_element(
        unit,
        [("t000211", "Inner slide one"), ("t000212", "Inner slide two")],
        {
            "t000211": [_text("<p>inner slide one body</p>")],
            "t000212": [_text("<p>inner slide two body</p>")],
        },
        display="carousel",
        parent=b_join,
        tab_id="t000201",
    )

    _c, c_join = _seed_tabs_element(
        unit,
        [("t000301", "C one"), ("t000302", "C two")],
        {"t000302": [_text("<p>c tab two</p>")]},
    )
    _seed_tabs_element(
        unit,
        [("t000311", "Caption one"), ("t000312", "Caption two")],
        {
            "t000311": [_text("<p>c inner one body</p>")],
            "t000312": [_text("<p>c inner two body</p>")],
        },
        display="carousel",
        parent=c_join,
        tab_id="t000301",
    )
    del student
    _login(page, live_server, "car_nest3")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(f"{_top(a_join)}.tabs--carousel")
    page.wait_for_selector(f"{_top(b_join)}.tabs--carousel")
    page.wait_for_selector(f"{_top(c_join)}.tabs--js")
    for root in (
        _top(a_join),
        _top(b_join),
        f"{_top(b_join)} .el--tabs[data-display='carousel']",
        f"{_top(c_join)} .el--tabs[data-display='carousel']",
    ):
        _settled(page, root)

    # --- 1. tabs inside a carousel -----------------------------------------
    a = _top(a_join)
    assert page.locator(f"{a} > .tabs__stage > .tabs__section.is-active"
                        " > .tabs__panel-label").evaluate(VISIBLE) is True
    inner_tabs = f"{a} .el--tabs[data-display='tabs']"
    assert page.locator(f"{inner_tabs} [role='tablist']").count() == 1
    panels = page.locator(f"{inner_tabs} [data-tab-panel]")
    assert panels.nth(0).evaluate(VISIBLE) is True
    page.get_by_role("tab", name="Inner tab two").click()
    assert panels.nth(1).evaluate(VISIBLE) is True
    assert panels.nth(0).evaluate(VISIBLE) is False

    # --- 2. carousel inside a carousel --------------------------------------
    b = _top(b_join)
    inner_car = f"{b} .el--tabs[data-display='carousel']"
    inner_secs = f"{inner_car} > .tabs__stage > .tabs__section"
    assert page.locator(inner_secs).nth(0).evaluate(VISIBLE) is True
    assert page.locator(inner_secs).nth(1).evaluate(VISIBLE) is False
    page.locator(f"{inner_car} > .tabs__cbar > .tabs__cnext").click()
    _settled(page, inner_car)
    assert page.locator(inner_secs).nth(1).evaluate(VISIBLE) is True
    assert _slide_no(page, inner_car) == 2
    assert _slide_no(page, b) == 1, "the inner carousel moved its host"

    # --- 3. carousel inside TABS (the caption regression) --------------------
    c = _top(c_join)
    c_inner = f"{c} .el--tabs[data-display='carousel']"
    caption = page.locator(
        f"{c_inner} > .tabs__stage > .tabs__section.is-active > .tabs__panel-label"
    )
    assert caption.evaluate(VISIBLE) is True, (
        "the tabs-mode sr-only label rule reached the INNER carousel's caption"
    )
    assert caption.inner_text().strip() == "Caption one"
    c_secs = f"{c_inner} > .tabs__stage > .tabs__section"
    assert page.locator(c_secs).nth(0).evaluate(VISIBLE) is True
    page.locator(f"{c_inner} > .tabs__cbar > .tabs__cnext").click()
    _settled(page, c_inner)
    assert page.locator(c_secs).nth(1).evaluate(VISIBLE) is True
    assert page.locator(c_secs).nth(0).evaluate(VISIBLE) is False


@pytest.mark.django_db(transaction=True)
def test_below_label_keeps_a_wide_table_in_its_own_scroller(page, live_server):
    """label_pos="below" turns the section into a flex column; a wide table inside it
    must still scroll in its own box rather than widen the stage (or the page)."""
    car = _seed_carousel(
        page,
        live_server,
        "car_below",
        [("Wide", [_table(3, 14, "wide")]), ("Plain", [_text("<p>plain</p>")])],
        label_pos="below",
    )
    page.goto(car.lesson_url)
    page.wait_for_selector(f"{CAROUSEL}[data-label-pos='below'].tabs--carousel")

    geom = page.evaluate(
        """(sel) => {
          const c = document.querySelector(sel);
          const stage = c.querySelector(":scope > .tabs__stage");
          const sec = stage.children[0];
          const label = sec.querySelector(":scope > .tabs__panel-label");
          const panel = sec.querySelector(":scope > .tabs__panel");
          const box = sec.querySelector(".el--table__scroll");
          const doc = document.documentElement;
          return {
            labelTop: Math.round(label.getBoundingClientRect().top),
            panelTop: Math.round(panel.getBoundingClientRect().top),
            boxScroll: box.scrollWidth,
            boxClient: box.clientWidth,
            stageWidth: stage.clientWidth,
            hostWidth: c.clientWidth,
            docScroll: doc.scrollWidth,
            docClient: doc.clientWidth,
          };
        }""",
        CAROUSEL,
    )
    assert geom["labelTop"] > geom["panelTop"], f"caption not below the slide: {geom}"
    assert geom["boxScroll"] > geom["boxClient"], (
        f"the wide fixture does not actually overflow: {geom}"
    )
    assert geom["stageWidth"] <= geom["hostWidth"], f"the stage widened: {geom}"
    assert geom["docScroll"] <= geom["docClient"], f"the page scrolls sideways: {geom}"


@pytest.mark.django_db(transaction=True)
def test_editor_no_op_resave_keeps_the_carousel(page, live_server):
    """Reopen a saved carousel in the REAL editor, Save without touching a control,
    reload -- still a carousel.

    A Django form test cannot catch this: it builds the POST body by hand and always
    includes `display`, so it passes on a build where the browser drops it. The defect
    lives in tabs_editor.js::serialize(), which is the sole writer of the
    authoritative hidden input[name=data]."""
    from courses.models import TabsElement

    pa = _make_pa_user("car_resave")
    course, unit = _seed_unit(pa, "car-resave")
    obj, join = _seed_tabs_element(
        unit,
        [("t000001", "One"), ("t000002", "Two")],
        display="carousel",
        label_pos="below",
    )
    _login(page, live_server, "car_resave")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs')

    page.locator(
        f'[data-scope="editor"] [data-element="{join.pk}"] .el-act-edit'
    ).first.click()
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor]")
    display_sel = page.locator("[data-edit-slot] [data-tab-display]")
    label_pos_sel = page.locator("[data-edit-slot] [data-tab-label-pos]")
    assert display_sel.input_value() == "carousel"
    assert label_pos_sel.input_value() == "below"

    # Save with NOTHING touched -- no change event ever fires on either select.
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor]", state="detached")

    obj.refresh_from_db()
    assert obj.data["display"] == "carousel", (
        "a no-op Save reverted the element to tab mode"
    )
    assert obj.data["label_pos"] == "below"
    assert TabsElement.objects.get(pk=obj.pk).data["display"] == "carousel"

    page.reload()
    page.wait_for_selector('[data-scope="preview"] .el--tabs.tabs--carousel')


@pytest.mark.django_db(transaction=True)
def test_authoring_a_carousel_through_the_add_menu(page, live_server):
    """The authoring path end to end: add-menu -> Tabs -> Display: Carousel ->
    Save -> reload. Proves the two selects, the serializer and the form agree."""
    from courses.models import Element
    from courses.models import TabsElement

    pa = _make_pa_user("car_author")
    course, unit = _seed_unit(pa, "car-author")
    _login(page, live_server, "car_author")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    top_menu = page.locator("[data-add-menu]:not(.addwrap--nested)")
    top_menu.locator("[data-add-toggle]").click()
    top_menu.locator("[data-add-type='tabs']").click()
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor]")

    # The label-position row is hidden until the mode is carousel.
    assert not page.locator("[data-edit-slot] [data-tab-label-pos-row]").is_visible()
    page.locator("[data-edit-slot] [data-tab-display]").select_option("carousel")
    assert page.locator("[data-edit-slot] [data-tab-label-pos-row]").is_visible()
    page.locator("[data-edit-slot] [data-tab-label-pos]").select_option("below")

    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()
    page.wait_for_selector('[data-scope="preview"] .el--tabs.tabs--carousel')

    join = Element.objects.get(unit=unit)
    obj = TabsElement.objects.get(pk=join.object_id)
    assert obj.data["display"] == "carousel"
    assert obj.data["label_pos"] == "below"

    page.reload()
    page.wait_for_selector(
        '[data-scope="preview"] .el--tabs[data-label-pos="below"].tabs--carousel'
    )


@pytest.mark.django_db(transaction=True)
def test_carousel_bails_to_the_stacked_fallback_on_a_throw(page, live_server):
    """Any throw inside the carousel branch must undo everything and leave the
    server's stacked fallback usable -- and must NOT keep swallowing arrow keys.

    The throw is injected with an ACCESSOR, not a plain global write: all three
    templates assign window.TABS_I18N wholesale in an inline script before the
    deferred tabs.js, so a document-start `window.TABS_I18N = {...}` is simply
    overwritten, the carousel initialises normally and these assertions fail against a
    CORRECT implementation. (Mutants: empty the catch body -> the state assertions go
    RED; delete `if (dead) return;` from the container keydown handler -> only the
    defaultPrevented assertion can see it, because show() has its own dead guard and
    the DOM would be identical either way.)"""
    car = _seed_carousel(
        page,
        live_server,
        "car_bail",
        [("One", [_link("one")]), ("Two", [_link("two")])],
    )
    page.add_init_script(
        """
      Object.defineProperty(window, "TABS_I18N", {
        configurable: true,
        get() { return this.__t; },
        set(v) { this.__t = Object.assign({}, v, {slidePos: 42}); },
      });
    """
    )
    page.goto(car.lesson_url)
    page.wait_for_function(
        """(sel) => {
          const c = document.querySelector(sel);
          return !!c && c.dataset.tabsReady === "1"
                 && !c.classList.contains("tabs--js");
        }""",
        arg=CAROUSEL,
    )

    def assert_clean(when):
        state = page.evaluate(SLIDE_STATE, f"{CAROUSEL}{SECTIONS}")
        assert not any(s["inert"] for s in state), f"{when}: still inert {state}"
        assert not any(s["ariaHidden"] for s in state), f"{when}: aria-hidden {state}"
        assert all(s["visible"] for s in state), f"{when}: not all visible {state}"
        assert page.locator(f"{CAROUSEL} .tabs__cbar").count() == 0, when
        assert page.locator(f"{CAROUSEL}.tabs--carousel").count() == 0, when
        assert page.locator(f"{CAROUSEL}.tabs--js").count() == 0, when
        assert (
            page.evaluate(
                "(sel) => document.querySelector(sel).style.minHeight",
                f"{CAROUSEL} > .tabs__stage",
            )
            == ""
        ), f"{when}: the stage kept its height reservation"

    assert_clean("after the bail")

    # Content is reachable: focus() on a node inside an inert subtree is a silent
    # no-op, so this landing is itself the proof the sections were un-inerted.
    page.locator(f"{CAROUSEL}{SECTIONS}").nth(1).locator("a").focus()
    assert page.evaluate("() => (document.activeElement || {}).href || ''").endswith(
        "/two"
    )

    page.evaluate(
        """() => {
          window.__keys = [];
          document.addEventListener("keydown", (e) => {
            window.__keys.push([e.key, e.defaultPrevented]);
          });
        }"""
    )
    # FOCUS PRECONDITION, mandatory and easy to miss because the bail removed the nav
    # bar: with focus on <body>, body.closest("[data-tabs]") is null and guard 3
    # returns before preventDefault() on the mutant exactly as on correct code.
    page.locator(f"{CAROUSEL}{SECTIONS}").nth(0).locator("a").focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Home")
    assert page.evaluate("() => window.__keys") == [
        ["ArrowRight", False],
        ["Home", False],
    ], "a dead carousel is still swallowing arrow keys"
    assert_clean("after a key press")


@pytest.mark.django_db(transaction=True)
def test_carousel_screenshots_light_and_dark(page, live_server, tmp_path):
    """Both themes, captured separately. A dark screenshot is not verified by a light
    one passing; for dark set User.theme (an authed user's theme wins outright in
    _resolve_theme_pref), NOT the libli_theme cookie."""
    car = _seed_carousel(
        page,
        live_server,
        "car_shots",
        [
            ("Pierwszy slajd", [_table(4, 4, "one")]),
            ("Drugi slajd", [_table(4, 4, "two")]),
            ("Trzeci slajd", [_text("<p>third slide body</p>")]),
        ],
    )
    for theme in ("light", "dark"):
        car.user.theme = theme
        car.user.save(update_fields=["theme"])
        page.goto(car.lesson_url)
        page.wait_for_selector(f"{CAROUSEL}.tabs--carousel")
        assert page.locator("html").get_attribute("data-theme") == theme
        page.locator(f"{CAROUSEL}{NAV} > .tabs__cnext").click()
        _settled(page)
        shot = tmp_path / f"carousel-{theme}.png"
        page.locator(CAROUSEL).screenshot(path=str(shot))
        assert shot.exists()
    print(f"CAROUSEL_SHOTS_DIR={tmp_path}")
