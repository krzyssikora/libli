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

Modeled on tests/test_e2e_editor_ws3.py (editor half) and tests/test_e2e_gallery.py
(student half). Marked e2e (excluded from the default run)."""

import os
import types

import pytest

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


def _seed_tabs_element(unit, tabs, children=None):
    """Attach one TabsElement to `unit`.

    `tabs` is [(tab_id, label)]; `children` maps tab_id -> [concrete element obj].
    Returns (obj, join). Fixed 't' + 6-hex ids let two elements deliberately SHARE
    ids (the isolation scenario), which the namespaced DOM ids must survive.
    """
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={"tabs": [{"id": tid, "label": label} for tid, label in tabs]}
    )
    join = Element.objects.create(unit=unit, content_object=obj)
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
    page.locator("[data-add-toggle]").first.click()
    page.locator("[data-add-type='tabs']").click()
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
    target_a = page.locator(f'{editor} .element-list > [data-element="{a.pk}"]')
    nested_list.wait_for(state="visible")  # first tab open, so children are on-screen

    nbox = nested_list.bounding_box()
    abox = target_a.bounding_box()
    a_y = abox["y"] + abox["height"] / 2  # a real top-level drop target

    # Real dragstart on the grip, then a SWEEP of dragover clientY values spanning the
    # nested child zone. The buggy descendant query resolves `before` to a nested row
    # somewhere in this band, and list.insertBefore(line, nestedRow) throws
    # NotFoundError (the nested row is a descendant, not a child of the list). The
    # single-point version was flaky because whether one y lands on a nested row vs the
    # tabs row depends on exact box geometry; sweeping the whole zone is deterministic.
    dt = page.evaluate_handle("() => new DataTransfer()")
    grip.dispatch_event("dragstart", {"dataTransfer": dt})
    list_sel = page.locator(f"{editor} .element-list").first
    top = int(nbox["y"] - 4)
    bottom = int(nbox["y"] + nbox["height"] + 4)
    for y in range(top, bottom, 3):
        list_sel.dispatch_event("dragover", {"dataTransfer": dt, "clientY": y})
    # Final hover over the top-level target A, then drop there.
    list_sel.dispatch_event("dragover", {"dataTransfer": dt, "clientY": a_y})
    list_sel.dispatch_event("drop", {"dataTransfer": dt, "clientY": a_y})
    grip.dispatch_event("dragend", {"dataTransfer": dt})

    # The reorder posts and swaps the pane; B must end up before A at top level.
    page.wait_for_function(
        """(pks) => {
            const rows = document.querySelectorAll(
                '[data-scope=\"editor\"] .element-list > .el-row');
            const order = Array.from(rows).map(r => r.getAttribute('data-element'));
            const ia = order.indexOf(String(pks.a)), ib = order.indexOf(String(pks.b));
            return ia !== -1 && ib !== -1 && ib < ia;
        }""",
        arg={"a": a.pk, "b": b.pk},
    )
    assert errors == [], f"drag threw a page error: {errors}"


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
