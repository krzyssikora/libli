"""Playwright e2e reproducing the #9 reorder/move symptoms (spec WS1 #9a/#9b).

The backend is already correct + unit-tested, so DB state passes regardless; the #9
bugs are in the frontend swap / panel lifecycle, which only the rendered DOM reveals.
Each symptom is its own assertion so a failure pinpoints which one is real:

  (a) arrow-up does nothing  /  (d) arrow-down on a section does nothing
        -> reorder a unit (down then up) and a section (down); assert the DOM order.
  (c) can't move a lesson back / spurious 409
        -> reparent via the in-panel Move picker; assert the panel no longer holds a
           picker bearing the node's now-stale token (reusing it is what 409s today).

Marked e2e (excluded from the default run; run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


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


def _seed_tree(owner):
    """Chapter 1 -> [Intro lesson (unit), Section A (section) -> Core lesson, Section B
    (section)]. Two sibling sections so arrow-down on a section has somewhere to go."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug="reorder-test", owner=owner)
    ch1 = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter 1"
    )
    intro = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch1, title="Intro lesson"
    )
    sec_a = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch1, title="Section A"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=sec_a,
        title="Core lesson",
    )
    sec_b = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch1, title="Section B"
    )
    return course, ch1, intro, sec_a, sec_b


def _wait_order(page, scope_id, expected, timeout_ms=5000):
    """Poll the DOM order of direct <li> rows under [data-scope] until it equals
    `expected` (a list of pks). Raises on timeout -> swap didn't reflect the move."""
    page.wait_for_function(
        "([sel, want]) => {"
        "  const ol = document.querySelector(sel);"
        "  if (!ol) return false;"
        "  const got = Array.from(ol.children)"
        "    .filter(li => li.classList.contains('tree__row'))"
        "    .map(li => li.getAttribute('data-node'));"
        "  return got.length === want.length && got.every((v,i) => v === want[i]);"
        "}",
        arg=[f'[data-scope="{scope_id}"]', [str(x) for x in expected]],
        timeout=timeout_ms,
    )


def _goto_builder(page, live_server):
    page.goto(f"{live_server.url}/manage/courses/reorder-test/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    page.wait_for_selector('.tree__title[value="Chapter 1"]')


@pytest.mark.django_db(transaction=True)
def test_reorder_unit_and_section(page, live_server):
    """Symptoms (a) arrow-up and (d) arrow-down-on-section: the rendered tree must
    reflect reorders of both a unit and a section."""
    pa = _make_pa_user("pa9a")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9a")
    _goto_builder(page, live_server)

    _wait_order(page, ch1.pk, [intro.pk, sec_a.pk, sec_b.pk])  # seed order
    intro_row = page.locator(f'li.tree__row[data-node="{intro.pk}"]')
    sec_a_row = page.locator(f'li.tree__row[data-node="{sec_a.pk}"]')

    # Unit down, then up.
    intro_row.locator('button[data-op="reorder"][value="down"]').first.click()
    _wait_order(page, ch1.pk, [sec_a.pk, intro.pk, sec_b.pk])
    intro_row.locator('button[data-op="reorder"][value="up"]').first.click()
    _wait_order(page, ch1.pk, [intro.pk, sec_a.pk, sec_b.pk])

    # Section A down (swaps with sibling Section B).
    sec_a_row.locator('button[data-op="reorder"][value="down"]').first.click()
    _wait_order(page, ch1.pk, [intro.pk, sec_b.pk, sec_a.pk])


@pytest.mark.django_db(transaction=True)
def test_move_picker_not_left_stale_after_reparent(page, live_server):
    """Symptom (c): after a successful reparent via the in-panel Move picker, the panel
    must NOT still hold a picker bearing the moved node's now-stale token. Reusing
    such a stale picker (e.g. to move the lesson back) is exactly what 409s today."""
    pa = _make_pa_user("pa9c")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    stale_token = intro.updated.isoformat()  # the token the picker is born with
    _login(page, live_server, "pa9c")
    _goto_builder(page, live_server)

    # Open the Move picker for Intro and move it under Section A (enhanced JS UI).
    page.locator(f'a[data-move="{intro.pk}"]').click()
    dest = page.locator(f'[data-panel] [data-move-tree] [data-dest="{sec_a.pk}"]')
    dest.wait_for(state="visible", timeout=5000)
    dest.click()
    page.locator('[data-panel] [data-move-slot="0"]').click()
    page.locator("[data-panel] .move-picker__submit").click()

    # The move landed (Intro is now under Section A's scope).
    page.wait_for_function(
        "([sel, pk]) => {const ol=document.querySelector(sel); return ol && "
        "Array.from(ol.children).some(li => li.classList.contains('tree__row') "
        "&& li.getAttribute('data-node')===pk);}",
        arg=[f'[data-scope="{sec_a.pk}"]', str(intro.pk)],
        timeout=5000,
    )

    # A Move resets the panel to its neutral (course) state — consistent with arrow/drag
    # reorders, which never touch the panel. Wait for the neutral panel to settle.
    page.wait_for_selector('[data-panel] [data-panel-for="course"]', timeout=5000)

    # The panel must not retain a reparent picker carrying Intro's now-stale token.
    stale_picker = page.locator(
        f'[data-panel] form[data-op="reparent"] '
        f'input[name="node_token"][value="{stale_token}"]'
    )
    assert stale_picker.count() == 0, (
        "stale Move picker left in the panel after reparent -> reusing it 409s "
        "('can't move the lesson back')"
    )

    # User-level outcome: move Intro back to the top via a fresh picker — no 409.
    page.locator(f'a[data-move="{intro.pk}"]').click()
    top = page.locator('[data-panel] [data-move-tree] [data-dest="top"]')
    top.wait_for(state="visible", timeout=5000)
    top.click()
    page.locator('[data-panel] [data-move-slot="0"]').click()
    page.locator("[data-panel] .move-picker__submit").click()
    page.wait_for_function(
        "([sel, pk]) => {const ol=document.querySelector(sel); return ol && "
        "Array.from(ol.children).some(li => li.classList.contains('tree__row') "
        "&& li.getAttribute('data-node')===pk);}",
        arg=['[data-scope="top"]', str(intro.pk)],
        timeout=5000,
    )
    from courses.models import ContentNode

    assert ContentNode.objects.get(pk=intro.pk).parent_id is None, "move-back rejected"
    notices = page.locator(".op-error")
    texts = [notices.nth(i).text_content() or "" for i in range(notices.count())]
    assert not any("changed" in t.lower() or "elsewhere" in t.lower() for t in texts), (
        f"spurious 409 notice on move-back: {texts!r}"
    )


def _open_picker(page, node_pk):
    """Click a row's Move... control and wait for the JS-enhanced picker."""
    page.locator(f'a[data-move="{node_pk}"]').click()
    page.locator("[data-panel] [data-move-tree]").wait_for(
        state="visible", timeout=5000
    )
    # initPicker has run once the row carries the highlight.
    page.wait_for_selector(f'li.tree__row.moving[data-node="{node_pk}"]', timeout=5000)


def _assert_picker_dismissed(page, node_pk):
    """The panel is back to its neutral (course) content, the row highlight is
    gone, and focus is on that row's own Move... control."""
    page.wait_for_selector('[data-panel] [data-panel-for="course"]', timeout=5000)
    assert page.locator("[data-panel] form.move-picker").count() == 0, (
        "the Move picker is still in the panel"
    )
    assert page.locator("li.tree__row.moving").count() == 0, (
        "the moving-row highlight was not cleared"
    )
    page.wait_for_function(
        "pk => document.activeElement && "
        "document.activeElement.getAttribute('data-move') === pk",
        arg=str(node_pk),
        timeout=5000,
    )


@pytest.mark.django_db(transaction=True)
def test_move_picker_cancel_restores_the_course_panel(page, live_server):
    pa = _make_pa_user("pa9cancel")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9cancel")
    _goto_builder(page, live_server)
    page.wait_for_selector('[data-panel] [data-panel-for="course"]', timeout=5000)

    _open_picker(page, intro.pk)
    assert page.locator('[data-panel] [data-panel-for="course"]').count() == 0
    # A page-lifetime marker: the no-JS navigation to the builder would ALSO
    # show the course panel, so prove JS handled Cancel in place.
    page.evaluate("() => { window.__samePage = 1; }")
    page.locator("[data-panel] [data-move-cancel]").click()
    _assert_picker_dismissed(page, intro.pk)
    assert page.evaluate("() => window.__samePage") == 1, (
        "Cancel navigated away instead of restoring the panel in place"
    )


@pytest.mark.django_db(transaction=True)
def test_move_picker_escape_restores_the_course_panel(page, live_server):
    pa = _make_pa_user("pa9esc")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9esc")
    _goto_builder(page, live_server)

    _open_picker(page, intro.pk)
    # Choose a destination, then a slot. A slot is a non-focusable <li>, so the
    # click leaves focus on <body> -- OUTSIDE .builder, where a listener bound
    # to the builder root would never hear the key.
    page.locator(f'[data-panel] [data-move-tree] [data-dest="{sec_a.pk}"]').click()
    page.locator('[data-panel] [data-move-slot="0"]').click()
    assert page.evaluate("() => document.activeElement === document.body"), (
        "precondition: the slot click should leave focus on <body>"
    )
    page.keyboard.press("Escape")
    _assert_picker_dismissed(page, intro.pk)


@pytest.mark.django_db(transaction=True)
def test_move_picker_reclick_collapses_and_move_here_needs_a_destination(
    page, live_server
):
    pa = _make_pa_user("pa9coll")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9coll")
    _goto_builder(page, live_server)

    _open_picker(page, intro.pk)
    submit = page.locator("[data-panel] .move-picker__submit")
    assert submit.is_disabled(), "Move here must be disabled before any destination"

    dest = page.locator(f'[data-panel] [data-move-tree] [data-dest="{sec_a.pk}"]')
    slots = dest.locator("xpath=..").locator(".move-dest-children")
    dest.click()
    slots.wait_for(state="visible", timeout=5000)
    assert "sel" in (dest.get_attribute("class") or "")
    assert submit.is_enabled(), "Move here must be enabled once a destination is chosen"
    page.locator('[data-panel] [data-move-slot="0"]').click()

    dest.click()  # re-click the SELECTED destination -> collapse
    slots.wait_for(state="hidden", timeout=5000)
    assert "sel" not in (dest.get_attribute("class") or ""), (
        "the re-clicked destination is still selected"
    )
    assert page.locator("[data-panel] [data-move-tree] .move-dest.sel").count() == 0
    assert submit.is_disabled(), "Move here must be disabled again after collapsing"
    assert page.locator('[data-panel] input[name="position"]').input_value() == "", (
        "the chosen position survived the collapse"
    )


@pytest.mark.django_db(transaction=True)
def test_escape_in_a_tree_text_field_leaves_the_picker_open(page, live_server):
    """Escape inside the inline-add title field belongs to THAT field (it cancels
    the add). It must not also dismiss the picker and yank focus to the Move...
    control -- the author was typing somewhere else entirely."""
    pa = _make_pa_user("pa9escf")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9escf")
    _goto_builder(page, live_server)

    _open_picker(page, intro.pk)
    scope = page.locator(f'[data-add-scope="{ch1.pk}"]')
    scope.locator('button[data-add-kind="lesson"]').click()
    field = scope.locator("input[data-add-title]")
    field.fill("Draft")
    field.press("Escape")
    assert page.locator("[data-panel] form.move-picker").count() == 1, (
        "Escape in the add-title field dismissed the Move picker"
    )
    assert page.locator(f'li.tree__row.moving[data-node="{intro.pk}"]').count() == 1


@pytest.mark.django_db(transaction=True)
def test_escape_closing_a_header_menu_leaves_the_picker_open(page, live_server):
    """core/js/ui.js closes the header's dropdowns on a DOCUMENT Escape too. That
    key belongs to the menu: the picker (also listening on document) must not be
    dismissed by it."""
    pa = _make_pa_user("pa9menu")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9menu")
    _goto_builder(page, live_server)

    _open_picker(page, intro.pk)
    menu = page.locator("[data-account-menu]")
    menu.locator("[data-menu-trigger]").click()
    expect(menu.locator("[data-menu-panel]")).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu.locator("[data-menu-panel]")).to_be_hidden()
    # Both listeners run inside the SAME keydown dispatch, so once the menu has
    # closed a dismissal would already have happened.
    assert page.locator("[data-panel] form.move-picker").count() == 1, (
        "Escape that closed the account menu also dismissed the Move picker"
    )
    assert page.locator(f'li.tree__row.moving[data-node="{intro.pk}"]').count() == 1


@pytest.mark.django_db(transaction=True)
def test_escape_closing_a_confirm_strip_leaves_the_picker_open(page, live_server):
    """The confirm strip dismisses itself on Escape (and removes itself, so the
    key's target is DETACHED by the time document hears it). The picker stays."""
    pa = _make_pa_user("pa9strip")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9strip")
    _goto_builder(page, live_server)

    _open_picker(page, intro.pk)
    page.click(
        f'li.tree__row[data-node="{ch1.pk}"] > .tree__rowhead '
        'a[data-flag-confirm][data-flag="published"]'
    )
    strip = page.locator(f'[data-flag-strip="{ch1.pk}"]')
    expect(strip).to_be_visible()
    page.wait_for_function(
        "() => document.activeElement"
        " && document.activeElement.hasAttribute('data-flag-strip')"
    )
    page.keyboard.press("Escape")
    expect(strip).to_have_count(0)
    assert page.locator("[data-panel] form.move-picker").count() == 1, (
        "Escape that closed the confirm strip also dismissed the Move picker"
    )
    assert page.locator(f'li.tree__row.moving[data-node="{intro.pk}"]').count() == 1


@pytest.mark.django_db(transaction=True)
def test_cancel_with_the_moving_row_collapsed_focuses_the_panel(page, live_server):
    """The row's Move... control is gone (its chapter was collapsed while the picker
    was open), so Cancel cannot return focus there. It must not strand focus on
    <body>: the panel, now showing the course, takes it."""
    pa = _make_pa_user("pa9fall")
    course, ch1, intro, sec_a, sec_b = _seed_tree(pa)
    _login(page, live_server, "pa9fall")
    _goto_builder(page, live_server)

    _open_picker(page, intro.pk)
    page.click(f'[data-toggle="{ch1.pk}"]')
    expect(page.locator(f'a[data-move="{intro.pk}"]')).to_have_count(0)
    page.locator("[data-panel] [data-move-cancel]").click()
    page.wait_for_selector('[data-panel] [data-panel-for="course"]', timeout=5000)
    page.wait_for_function(
        "() => document.activeElement"
        " && document.activeElement.hasAttribute('data-panel')",
        timeout=5000,
    )
