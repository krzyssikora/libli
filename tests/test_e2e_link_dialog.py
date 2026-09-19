"""Playwright e2e for the rich-text link dialog on the REAL editor page: insert an
internal link, save it, follow it as a student, and re-open it to remove it. The
dialog's own internals are covered by tests/test_link_dialog_behaviour.py."""

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
    # Mirrors tests/test_e2e_builder.py::_login -- allauth's field is name="login",
    # and the form must be scoped because the shell header also carries submits.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(owner, *, with_link=False):
    """A course with part > chapter > lesson unit, optionally holding a text element
    whose body already contains an internal link (for the re-open/remove path)."""
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    course = Course.objects.create(title="Algebra", slug="algebra", owner=owner)
    part = ContentNode.objects.create(course=course, kind="part", title="Part A")
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", parent=part, title="Quadratics"
    )
    unit = ContentNode.objects.create(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="Lesson",
        published=True,
    )
    if with_link:
        el = TextElement(
            body=f'<p>see <a href="/courses/n/{chapter.pk}/">quadratics</a></p>'
        )
        el.save()
        Element.objects.create(unit=unit, content_object=el)
    return course, chapter, unit


def _open_editor(page, live_server, course, unit):
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )


def _add_text_element(page):
    # The type cards sit inside `<div class="typemenu" hidden>`; without the toggle
    # click Playwright waits for visibility and times out.
    page.click("[data-add-toggle]")
    page.click("[data-add-type='text']")
    page.locator(".rte-surface").wait_for()


def _open_link_dialog(page):
    page.click("[data-cmd='link']")
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")
    # The tree arrives over fetch AFTER showModal, and setTabStop only runs once it has
    # painted. Pressing keys before then lands them nowhere.
    dialog.locator(".link-picker__item").first.wait_for()
    return dialog


def _await_effect(page, predicate_js):
    """Wait for a JS boolean predicate instead of reading state right after
    `dialog.wait_for(state="hidden")`.

    `dialog.close()` clears the `open` attribute SYNCHRONOUSLY but only QUEUES the
    `close` event as a task (HTML spec: "queue an element task"), and
    link_dialog.js's own close listener -- which performs every real effect this file
    asserts on (restoring the caret, writing the .op-error banner, inserting or
    unwrapping the <a> via libliLinkApply.apply(), all done from the callback
    text_toolbar.js passed to open()) -- runs inside that queued task
    (link_dialog.js:408-417). So `dialog.wait_for(state="hidden")` proves only that
    the attribute is gone, not that the callback has run; a one-shot read right after
    it is a genuine race under load (this repo hit the identical class of bug in
    imagezoom.js: commit b1ec23f3, "wait for the close HANDLER, not just for the
    dialog to shut"). A retrying `wait_for_function` on the effect itself -- the
    selection text, or a DOM node the callback creates/removes -- waits out exactly
    that gap instead of sampling it.
    """
    page.wait_for_function(predicate_js)


@pytest.mark.django_db(transaction=True)
def test_insert_internal_link_then_follow_it(page, live_server):
    from courses.models import Enrollment
    from courses.models import TextElement

    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("See the chapter on quadratics")
    # Select the LAST word deterministically. `text=` matches ELEMENTS, and the whole
    # sentence is one text node, so `dblclick(".rte-surface >> text=quadratics")` would
    # double-click the container's centre and select whatever word sits there.
    page.keyboard.press("Control+Shift+ArrowLeft")
    assert page.evaluate("() => window.getSelection().toString()") == "quadratics"

    dialog = _open_link_dialog(page)
    assert dialog.locator("[data-tab='node']").get_attribute("aria-selected") == "true"
    dialog.locator(f"[data-node='{chapter.pk}'] > .link-picker__row").click()
    # Prefill precedence: a non-empty selection beats the node title.
    assert dialog.locator("[data-link-text]").input_value() == "quadratics"
    dialog.locator("[data-link-insert]").click()
    dialog.wait_for(state="hidden")
    # Lower risk than the other sites (the save click + wait_for below give the
    # queued close handler far more time), but make it explicit rather than
    # incidental: the insert only lands once the callback has actually run.
    _await_effect(page, "() => !!document.querySelector('.rte-surface a')")

    page.click('form[data-op="element-save"] button[type="submit"]')
    page.locator(".element-list [data-element]").first.wait_for()

    body = TextElement.objects.latest("pk").body
    assert f'href="/courses/n/{chapter.pk}/"' in body

    # Follow it as an enrolled reader.
    Enrollment.objects.create(student=owner, course=course)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.click(f".el a[href='/courses/n/{chapter.pk}/']")
    page.wait_for_url(f"**#node-{chapter.pk}")
    row = page.locator(
        f"#node-{chapter.pk} > .outline-node__group > .outline-node__head"
    )
    bg = row.evaluate("el => getComputedStyle(el).backgroundColor")
    # "Highlighted" is not otherwise assertable: a :target rule mis-scoped to the <li>,
    # or written into a stylesheet the outline page never loads, passes a weaker check.
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")


@pytest.mark.django_db(transaction=True)
def test_collapsed_caret_defaults_link_text_to_the_node_title(page, live_server):
    """The other half of the precedence rule, and what the Purpose section promises."""
    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    dialog = _open_link_dialog(page)
    dialog.locator(f"[data-node='{chapter.pk}'] > .link-picker__row").click()
    assert dialog.locator("[data-link-text]").input_value() == chapter.title


@pytest.mark.django_db(transaction=True)
def test_keyboard_only_insert(page, live_server):
    """Tab into the tree, move with arrows, press with Enter -- no mouse.

    This is what makes the roving-tabindex model real: with ~925 rows a Tab-only path
    to a deep row is not a realistic gesture, so a Tab-only test would prove nothing.
    """
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("text")
    dialog = _open_link_dialog(page)

    # Focus starts in the filter (Task 6 pins that); one Tab reaches the tree.
    assert page.evaluate(
        "() => document.activeElement.hasAttribute('data-link-filter')"
    )
    page.keyboard.press("Tab")
    assert page.evaluate(
        "() => document.activeElement.classList.contains('link-picker__item')"
    )
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert dialog.locator("[aria-selected='true'][data-node]").count() == 1

    # Finish without the mouse too. A test that advertises itself as keyboard-only must
    # not click Insert. Tab UNTIL the text field has focus rather than hard-coding a
    # count: the intervening focusables depend on state (Remove link is disabled when
    # touchedAnchors is 0; the retry button and URL input sit in hidden panels), so a
    # fixed number silently breaks when that state changes.
    for _ in range(6):
        if page.evaluate("() => document.activeElement.hasAttribute('data-link-text')"):
            break
        page.keyboard.press("Tab")
    else:
        raise AssertionError("never reached the link-text field by tabbing")
    page.keyboard.type("Chapter")
    page.keyboard.press("Enter")
    dialog.wait_for(state="hidden")


@pytest.mark.django_db(transaction=True)
def test_dismissing_restores_the_caret(page, live_server):
    """The case the spec says would silently regress if the range were not cloned.

    A source grep for "cloneRange()" passes for code that clones the wrong object,
    clones after showModal(), or drops the restore entirely.
    """
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("See the chapter on quadratics")
    page.keyboard.press("Control+Shift+ArrowLeft")
    assert page.evaluate("() => window.getSelection().toString()") == "quadratics"

    _open_link_dialog(page)
    page.keyboard.press("Escape")
    page.locator(".link-dialog").wait_for(state="hidden")
    # The restore itself is the queued callback's effect (see _await_effect); wait
    # for the selection to actually settle rather than sampling it once.
    _await_effect(page, "() => window.getSelection().toString() === 'quadratics'")
    assert page.evaluate("() => window.getSelection().toString()") == "quadratics"


@pytest.mark.django_db(transaction=True)
def test_detached_surface_discards_and_explains(page, live_server):
    """A data-loss path: without this the author sees a successful insert and then
    loses the link on save. Two source greps cannot tell dead code from live code."""
    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("text")
    dialog = _open_link_dialog(page)
    # Simulate editor.js swapping the pane out from under the open dialog.
    page.evaluate("() => document.querySelector('.rte-surface').remove()")
    dialog.locator(f"[data-node='{chapter.pk}'] > .link-picker__row").click()
    dialog.locator("[data-link-text]").fill("Chapter")
    dialog.locator("[data-link-insert]").click()
    dialog.wait_for(state="hidden")
    # The .op-error banner is created BY the queued close-handler callback; wait for
    # it to actually exist rather than sampling right after the dialog hides.
    _await_effect(page, "() => !!document.querySelector('.op-error')")

    assert page.locator(".op-error").count() == 1
    conflict = page.locator(".editor").get_attribute("data-msg-conflict")
    assert page.locator(".op-error").inner_text().strip() == conflict.strip()


@pytest.mark.django_db(transaction=True)
def test_reopening_prefills_and_remove_unwraps(page, live_server):
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner, with_link=True)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)

    # The row's edit affordance is the button carrying data-form-url; clicking the
    # <li data-element> itself does nothing.
    page.click(".element-list [data-form-url]")
    page.locator(".rte-surface").wait_for()
    page.click(".rte-surface a")  # caret inside the link

    dialog = _open_link_dialog(page)
    assert dialog.locator("[data-tab='node']").get_attribute("aria-selected") == "true"
    selected = dialog.locator("[aria-selected='true'][data-node]")
    assert selected.count() == 1
    # The preselected row must be scrolled into view, not merely marked.
    assert selected.is_visible()

    dialog.locator("[data-link-remove]").click()
    dialog.wait_for(state="hidden")
    # The unwrap is performed BY the queued close-handler callback; wait for the
    # anchor to actually be gone rather than sampling right after the dialog hides.
    _await_effect(page, "() => !document.querySelector('.rte-surface a')")
    assert page.locator(".rte-surface a").count() == 0
    assert "quadratics" in page.locator(".rte-surface").inner_text()


@pytest.mark.django_db(transaction=True)
def test_dialog_text_follows_the_dark_theme(page, live_server):
    """The UA styles <dialog> as `color: CanvasText; background-color: Canvas`, and this
    app themes off a data-theme ATTRIBUTE rather than color-scheme, so Canvas stays
    LIGHT under the dark theme. Anything in the dialog that does not state its own
    colour therefore inherits near-black -- which is what the picker tree titles and the
    "Insert link" heading do. Measured, not read: the assertion is on the computed
    colour against the dark palette's --text-primary, so deleting the rule that fixes it
    turns this red."""
    owner = _make_pa_user("pa")
    owner.theme = "dark"
    owner.save(update_fields=["theme"])
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    assert page.get_attribute("html", "data-theme") == "dark"

    _add_text_element(page)
    dialog = _open_link_dialog(page)

    dark_text = page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--text-primary').trim()"
    )
    assert dark_text == "#F2EFE9"  # the [data-theme=dark] token, not the light one

    def colour_of(selector):
        return dialog.locator(selector).first.evaluate(
            "el => getComputedStyle(el).color"
        )

    expected = "rgb(242, 239, 233)"
    assert colour_of(".link-picker__title") == expected
    assert colour_of(".link-dialog__title") == expected


@pytest.mark.django_db(transaction=True)
def test_modal_is_centred_in_the_viewport(page, live_server):
    """The UA centres a showModal() dialog with `dialog { margin: auto }` against its
    all-round `inset: 0`. core/static/core/css/reset.css's `* { margin: 0 }` matches the
    same element at higher specificity than a UA rule, so without an explicit `margin`
    the box collapses to the viewport's TOP-LEFT corner. (dialog.imgzoom in courses.css
    hand-writes its own insets around the same trap.) Measured against the real box, so
    dropping the declaration turns this red."""
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)
    dialog = _open_link_dialog(page)

    box = dialog.bounding_box()
    view = page.viewport_size
    # Not a tautology: the dialog is 34rem wide in a 1280px-wide viewport, so a
    # left-pinned box misses these by ~370px horizontally and ~100px vertically.
    assert box["width"] < view["width"] - 100
    assert box["height"] < view["height"] - 50
    slack_x = (view["width"] - box["width"]) / 2
    slack_y = (view["height"] - box["height"]) / 2
    assert abs(box["x"] - slack_x) <= 2, (box, view)
    assert abs(box["y"] - slack_y) <= 2, (box, view)


# ---- the collapsible tree --------------------------------------------------------


def _seed_two_parts(owner, *, link_to_far_unit=False):
    """Part A > Quadratics > Lesson (the unit being edited, two levels down) and a
    sibling Part B > Circles > Arcs that holds nothing on the edited unit's path.

    With link_to_far_unit the edited unit holds a text element linking to Arcs -- a
    target inside a branch the picker renders COLLAPSED."""
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    course = Course.objects.create(title="Algebra", slug="algebra", owner=owner)
    part_a = ContentNode.objects.create(course=course, kind="part", title="Part A")
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", parent=part_a, title="Quadratics"
    )
    unit = ContentNode.objects.create(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=chapter,
        title="Lesson",
        published=True,
    )
    part_b = ContentNode.objects.create(course=course, kind="part", title="Part B")
    circles = ContentNode.objects.create(
        course=course, kind="chapter", parent=part_b, title="Circles"
    )
    arcs = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=circles, title="Arcs"
    )
    if link_to_far_unit:
        el = TextElement(body=f'<p>see <a href="/courses/n/{arcs.pk}/">arcs</a></p>')
        el.save()
        Element.objects.create(unit=unit, content_object=el)
    return course, {
        "part_a": part_a,
        "chapter": chapter,
        "unit": unit,
        "part_b": part_b,
        "circles": circles,
        "arcs": arcs,
    }


def _row(dialog, node):
    return dialog.locator(f"[data-node='{node.pk}']")


def _title(dialog, node):
    return _row(dialog, node).locator("> .link-picker__row .link-picker__title")


def _twisty(dialog, node):
    return _row(dialog, node).locator("> .link-picker__row > .link-picker__twisty")


def _expect_expanded(dialog, node, value):
    # Retrying: UI state after a click/key/fill is awaited, never sampled once.
    expect(_row(dialog, node)).to_have_attribute("aria-expanded", value)


def _expect_selected(dialog, node, value):
    expect(_row(dialog, node)).to_have_attribute("aria-selected", value)


def _expect_focused(page, node):
    page.wait_for_function(
        "pk => document.activeElement"
        " && document.activeElement.getAttribute('data-node') === pk",
        arg=str(node.pk),
    )


def _open_tree_dialog(page, live_server):
    owner = _make_pa_user("pa")
    course, n = _seed_two_parts(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, n["unit"])
    _add_text_element(page)
    page.locator(".rte-surface").click()
    return _open_link_dialog(page), n


@pytest.mark.django_db(transaction=True)
def test_tree_opens_on_the_path_to_the_edited_unit(page, live_server):
    dialog, n = _open_tree_dialog(page, live_server)
    _expect_expanded(dialog, n["part_a"], "true")
    _expect_expanded(dialog, n["chapter"], "true")
    expect(_row(dialog, n["unit"])).to_be_visible()
    _expect_expanded(dialog, n["part_b"], "false")
    expect(_row(dialog, n["part_b"])).to_be_visible()
    expect(_row(dialog, n["circles"])).to_be_hidden()
    expect(_row(dialog, n["arcs"])).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_twisty_toggles_without_selecting_and_the_title_selects_without_toggling(
    page, live_server
):
    dialog, n = _open_tree_dialog(page, live_server)
    _title(dialog, n["unit"]).click()
    _expect_selected(dialog, n["unit"], "true")

    _twisty(dialog, n["part_b"]).click()
    _expect_expanded(dialog, n["part_b"], "true")
    expect(_row(dialog, n["circles"])).to_be_visible()
    # The twisty toggled and did NOT select: the selection is where it was.
    _expect_selected(dialog, n["part_b"], "false")
    _expect_selected(dialog, n["unit"], "true")

    _twisty(dialog, n["part_b"]).click()
    _expect_expanded(dialog, n["part_b"], "false")
    expect(_row(dialog, n["circles"])).to_be_hidden()

    # The title selects and does NOT toggle.
    _title(dialog, n["part_b"]).click()
    _expect_selected(dialog, n["part_b"], "true")
    _expect_expanded(dialog, n["part_b"], "false")


@pytest.mark.django_db(transaction=True)
def test_the_twisty_hit_target_is_at_least_24px(page, live_server):
    """WCAG 2.2 target size (2.5.8): a 24x24 CSS px target. The twisty lays out as
    1.25rem (20px), like a leaf's spacer; the hit box must still be 24x24, and
    enlarging it must not push a container's badge+title right of a leaf's."""
    dialog, n = _open_tree_dialog(page, live_server)
    box = _twisty(dialog, n["part_b"]).bounding_box()
    assert box["width"] >= 24 and box["height"] >= 24, box

    def badge_offset(node):
        row = _row(dialog, node).locator("> .link-picker__row")
        return (
            row.locator("> .tree__badge").bounding_box()["x"] - row.bounding_box()["x"]
        )

    # Quadratics (container: twisty) and Lesson (leaf: spacer) sit at different
    # depths, so compare the badge's offset WITHIN each row.
    assert abs(badge_offset(n["chapter"]) - badge_offset(n["unit"])) <= 1


@pytest.mark.django_db(transaction=True)
def test_collapsing_over_the_selection_keeps_it_and_moves_the_tab_stop(
    page, live_server
):
    dialog, n = _open_tree_dialog(page, live_server)
    _title(dialog, n["unit"]).click()
    _twisty(dialog, n["part_a"]).click()
    expect(_row(dialog, n["unit"])).to_be_hidden()
    # The selection survives the collapse and Insert still targets it.
    _expect_selected(dialog, n["unit"], "true")
    expect(dialog.locator("[data-link-insert]")).to_be_enabled()
    # Exactly one tab stop, and never on a row the collapse hid.
    stops = dialog.locator(".link-picker__item[tabindex='0']")
    expect(stops).to_have_count(1)
    expect(stops.first).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_left_and_right_open_close_and_move_focus(page, live_server):
    dialog, n = _open_tree_dialog(page, live_server)
    page.keyboard.press("Tab")  # filter -> the tree's tab stop
    page.keyboard.press("End")  # the last VISIBLE row: Part B, not Arcs
    _expect_focused(page, n["part_b"])

    page.keyboard.press("ArrowRight")  # closed parent -> opens, focus stays
    _expect_expanded(dialog, n["part_b"], "true")
    _expect_focused(page, n["part_b"])
    page.keyboard.press("ArrowRight")  # open parent -> its first child
    _expect_focused(page, n["circles"])
    page.keyboard.press("ArrowLeft")  # closed parent -> its parent row
    _expect_focused(page, n["part_b"])
    page.keyboard.press("ArrowLeft")  # open parent -> closes, focus stays
    _expect_expanded(dialog, n["part_b"], "false")
    _expect_focused(page, n["part_b"])

    # Up/Down walk VISIBLE rows only: from Part B, Up lands on the open path's leaf.
    page.keyboard.press("ArrowUp")
    _expect_focused(page, n["unit"])
    page.keyboard.press("ArrowLeft")  # a leaf -> its parent row
    _expect_focused(page, n["chapter"])
    # Arrows never select.
    expect(dialog.locator("[aria-selected='true'][data-node]")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_filter_opens_matching_ancestors_and_clearing_restores(page, live_server):
    dialog, n = _open_tree_dialog(page, live_server)
    filter_el = dialog.locator("[data-link-filter]")
    filter_el.fill("arcs")
    _expect_expanded(dialog, n["part_b"], "true")
    _expect_expanded(dialog, n["circles"], "true")
    expect(_row(dialog, n["arcs"])).to_be_visible()

    filter_el.fill("")
    _expect_expanded(dialog, n["part_b"], "false")
    _expect_expanded(dialog, n["circles"], "false")
    expect(_row(dialog, n["arcs"])).to_be_hidden()
    # The author's own open path came back as it was.
    _expect_expanded(dialog, n["part_a"], "true")
    expect(_row(dialog, n["unit"])).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_clearing_the_filter_keeps_a_row_picked_during_it_visible(page, live_server):
    """Arcs sits in Part B, which was collapsed before the query. Picked while the
    filter held Part B open, it must not vanish when clearing restores that state."""
    dialog, n = _open_tree_dialog(page, live_server)
    _expect_expanded(dialog, n["part_b"], "false")
    filter_el = dialog.locator("[data-link-filter]")
    filter_el.fill("arcs")
    _title(dialog, n["arcs"]).click()
    _expect_selected(dialog, n["arcs"], "true")

    filter_el.fill("")
    _expect_selected(dialog, n["arcs"], "true")
    expect(_row(dialog, n["arcs"])).to_be_visible()
    _expect_expanded(dialog, n["part_b"], "true")
    _expect_expanded(dialog, n["circles"], "true")
    # The tab stop follows the (visible) selection.
    expect(_row(dialog, n["arcs"])).to_have_attribute("tabindex", "0")


@pytest.mark.django_db(transaction=True)
def test_editing_a_link_into_a_collapsed_branch_opens_it(page, live_server):
    owner = _make_pa_user("pa")
    course, n = _seed_two_parts(owner, link_to_far_unit=True)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, n["unit"])
    page.click(".element-list [data-form-url]")
    page.locator(".rte-surface").wait_for()
    page.click(".rte-surface a")

    dialog = _open_link_dialog(page)
    _expect_selected(dialog, n["arcs"], "true")
    expect(_row(dialog, n["arcs"])).to_be_visible()
    _expect_expanded(dialog, n["part_b"], "true")
    _expect_expanded(dialog, n["circles"], "true")
