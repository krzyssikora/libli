"""Playwright e2e for inline renaming of builder tree node titles.

Marked e2e (excluded from the default run; run with -m e2e).
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# A title long enough that the tree truncates it, so the tooltip is the only way to
# read it. Kept well under ContentNode.title's CharField(max_length=200).
LONG_TITLE = "A very long unit title that the tree must truncate on one line"

# courses/urls.py:155-183. The panel fragment URL contains no literal "panel", so
# filtering requests on `"panel" in r.url` would match nothing.
RENAME_URL = "/build/node/rename/"


def _is_rename_post(request):
    return request.method == "POST" and RENAME_URL in request.url


def _is_panel_get(r):
    # The trailing `$` excludes /node/<pk>/export/; `\d+` excludes /node/rename/.
    return r.method == "GET" and re.search(r"/build/node/\d+/$", r.url) is not None


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    u = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_course(username="owner", n_filler=0):
    """A course shaped for the token-refresh cases: a chapter that CONTAINS a nested
    section with its own add row, so a naive descendant query for parent_token finds
    the GRANDCHILD's and the test goes RED.

    Every non-unit node passes unit_type=None -- the factory defaults it to "lesson",
    which ContentNode.clean() rejects for non-units, so a chapter built without it
    422s on rename and the chapter-centric scenarios below fail looking like
    applyRename bugs. Keep this in mind if you extend the seed.

    `long` carries LONG_TITLE so the tooltip test has a row the tree truncates; the
    four short seeded titles would never truncate. `n_filler` appends extra sibling
    units so the tree overflows the viewport for the scroll-preservation test.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = _make_pa_user(username)
    course = CourseFactory(slug="c1", owner=owner)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter 1"
    )
    section = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=chapter, title="Section 1"
    )
    unit1 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title="Unit 1"
    )
    unit2 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title="Unit 2"
    )
    long_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title=LONG_TITLE
    )
    filler = [
        ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type="lesson",
            parent=section,
            title=f"Filler {i}",
        )
        for i in range(n_filler)
    ]
    return course, {
        "owner": owner,
        "chapter": chapter,
        "section": section,
        "unit1": unit1,
        "unit2": unit2,
        "long": long_unit,
        "filler": filler,
    }


def _open_builder(page, live_server, course, username):
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.wait_for_selector(".tree__title")


def _select_all_and_type(page, locator_or_handle, text):
    """Focus a title, replace its whole value, leaving focus in the field."""
    locator_or_handle.click()
    locator_or_handle.press("Control+a")
    page.keyboard.type(text)


def _commit_with_enter(page, expected):
    """Press Enter on the focused title and wait until applyRename has landed.

    Waiting on the response alone is not enough: applyRename runs in the fetch's
    `.then`, i.e. strictly after `expect_response` returns. `input.defaultValue`
    reflects to the `value` CONTENT attribute, so the attribute selector below is
    the observable proof that the patch ran.
    """
    with page.expect_response(lambda r: _is_rename_post(r.request)):
        page.keyboard.press("Enter")
    page.wait_for_selector(f'.tree__title[value="{expected}"]')


# --------------------------------------------------------------------------- core


@pytest.mark.django_db(transaction=True)
def test_enter_commits_a_unit_rename(page, live_server):
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]')
    title.click()
    title.press("Control+a")
    page.keyboard.type("Renamed unit")
    with page.expect_response(
        lambda r: "rename" in r.url and r.request.method == "POST"
    ):
        title.press("Enter")
    expect(page.locator('.tree__title[value="Renamed unit"]')).to_have_count(1)
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Renamed unit"


@pytest.mark.django_db(transaction=True)
def test_enter_commits_a_chapter_rename(page, live_server):
    """Kind-agnostic: the same gesture works on a container row, not just a unit."""
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    _select_all_and_type(
        page, page.locator('.tree__title[value="Chapter 1"]'), "Renamed chapter"
    )
    _commit_with_enter(page, "Renamed chapter")
    nodes["chapter"].refresh_from_db()
    assert nodes["chapter"].title == "Renamed chapter"


@pytest.mark.django_db(transaction=True)
def test_focus_and_caret_survive_an_enter_commit(page, live_server):
    """(F) falsified by reverting to the naive design: return _render_scope from
    node_rename and drop the applyRename branch so the 200 goes through
    applyFragment. The scope swap destroys the input, focus drops to <body>, and
    the first assertion goes RED. That is the regression this whole feature exists
    to prevent, and this is the only test that observes it.

    The order is load-bearing: the field must be DIRTY before the caret is placed.
    On a clean field commitRename bails on the dirty check, nothing posts, and
    focus/selectionStart are trivially unchanged in every build.

    NOTE, contrary to the plan: dropping either guarded value write (commitRename's
    `if (input.value !== trimmed)` or applyRename's `if (input.value !== title)`)
    does NOT make this go red, and no test can make it. Both guards only skip an
    assignment of an IDENTICAL string, and the HTML spec moves the text entry cursor
    "if the new API value is different from the old API value" -- Chromium obeys, so
    an identical assignment leaves selectionStart alone. Verified empirically: with
    each guard removed in turn this test still passes with selectionStart == 4. The
    guards are harmless defensive code, not load-bearing behaviour.
    """
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    _select_all_and_type(page, title, "Unit One Renamed")
    page.evaluate("el => el.setSelectionRange(4, 4)", title)
    assert page.evaluate("el => el.selectionStart", title) == 4

    _commit_with_enter(page, "Unit One Renamed")

    assert page.evaluate("el => el === document.activeElement", title), (
        "focus left the input across the commit -- a scope swap happened"
    )
    assert page.evaluate("el => el.selectionStart", title) == 4, (
        "the caret jumped: an unguarded value assignment ran"
    )
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Unit One Renamed"


@pytest.mark.django_db(transaction=True)
def test_blur_commits_the_rename(page, live_server):
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    _select_all_and_type(
        page, page.locator('.tree__title[value="Unit 1"]'), "Blurred name"
    )
    with page.expect_response(lambda r: _is_rename_post(r.request)):
        page.locator("h1").first.click()
    page.wait_for_selector('.tree__title[value="Blurred name"]')
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Blurred name"


@pytest.mark.django_db(transaction=True)
def test_escape_reverts_and_keeps_focus(page, live_server):
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    _select_all_and_type(page, title, "Abandoned")
    title.press("Escape")
    assert title.input_value() == "Unit 1"
    # Escape must NOT blur: dropping focus to <body> would force someone who
    # abandoned an edit 300 rows down to Tab from the top of the document again.
    assert page.evaluate("el => el === document.activeElement", title)
    page.wait_for_timeout(400)
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Unit 1"


@pytest.mark.django_db(transaction=True)
def test_tooltip_tracks_typing_then_reverts(page, live_server):
    """(F) two falsifications: delete the delegated `input` handler (the mid-typing
    assertion goes RED); drop revert()'s `input.title = input.value` (the post-Escape
    assertion goes RED).

    Uses the LONG_TITLE row on purpose -- that is exactly where the tooltip is the
    only way to read a truncated name, so a stale tooltip is a real defect.
    """
    course, _nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator(f'.tree__title[value="{LONG_TITLE}"]')
    _select_all_and_type(page, title, "Typed while editing")
    # BEFORE Escape: without this the Escape half passes even with no input handler.
    assert title.get_attribute("title") == "Typed while editing"
    title.press("Escape")
    assert title.input_value() == LONG_TITLE
    assert title.get_attribute("title") == LONG_TITLE


@pytest.mark.django_db(transaction=True)
def test_focus_and_blur_without_typing_does_not_post(page, live_server):
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    before = nodes["unit1"].updated
    posts = []
    page.on("request", lambda r: posts.append(r.url) if _is_rename_post(r) else None)
    page.locator('.tree__title[value="Unit 1"]').click()
    page.locator("h1").first.click()
    page.wait_for_timeout(500)
    assert posts == [], posts
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].updated == before


@pytest.mark.django_db(transaction=True)
def test_enter_posts_exactly_once_and_not_at_all_when_unchanged(page, live_server):
    """Enter on a clean field posts nothing; Enter then blur posts exactly once.

    The unchanged case is what the unconditional `e.preventDefault()` on Enter
    buys: a text input in a form with a submit button natively submits on Enter.
    """
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if _is_rename_post(r) else None)

    title = page.locator('.tree__title[value="Unit 1"]')
    title.click()
    title.press("Enter")
    page.wait_for_timeout(500)
    assert posts == [], f"an unchanged title posted: {posts}"

    _select_all_and_type(page, title, "Once only")
    _commit_with_enter(page, "Once only")
    # Enter, then blur: the focusout handler must bail on dataset.submitting, and
    # after the response the field is clean again, so neither can post a second time.
    page.locator("h1").first.click()
    page.wait_for_timeout(600)
    assert len(posts) == 1, posts
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Once only"


# ---------------------------------------------------------------------- in-flight


@pytest.mark.django_db(transaction=True)
def test_field_is_readonly_during_the_round_trip(page, live_server):
    # (F) falsify: remove `input.readOnly = true` from commitRename.
    course, _nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")

    # Hold the response open so the in-flight window is observable.
    gate = {"release": None}

    def _handler(route):
        gate["release"] = route

    page.route("**/build/node/rename/", _handler)

    # Capture a HANDLE, not a value-attribute locator: applyRename sets defaultValue,
    # which reflects to the `value` ATTRIBUTE, so '[value="Unit 1"]' would resolve to
    # zero elements the moment the response lands.
    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    _select_all_and_type(page, title, "Renamed")
    with page.expect_request("**/build/node/rename/"):
        title.press("Enter")
    # readOnly is set BEFORE requestSubmit(), so waiting only on it can win the race
    # before the route handler has fired -- gate["release"] would still be None and the
    # test would die with AttributeError instead of a meaningful failure.
    page.wait_for_function("el => el.readOnly === true", arg=title)
    assert gate["release"] is not None
    # page.keyboard.type performs NO editability check and silently no-ops on a
    # readonly field. locator.fill()/type()/pressSequentially() run an *editable*
    # actionability check: they would hang and throw a timeout here, and would SUCCEED
    # once readOnly is removed -- inverting the test's RED and GREEN.
    page.keyboard.type("XYZ")
    assert title.input_value() == "Renamed"
    gate["release"].continue_()
    page.wait_for_function("el => el.readOnly === false", arg=title)
    assert title.input_value() == "Renamed"


@pytest.mark.django_db(transaction=True)
def test_window_blur_does_not_commit(page, live_server):
    """(F) falsify: remove the `relatedTarget === null && !document.hasFocus()`
    bail-out from the title focusout handler.

    Chromium fires focusout when the tab or window is deactivated; committing there
    would persist half-typed text. Playwright has no gesture that blurs the browser
    window, so this uses a second page in the same context plus bring_to_front().
    """
    course, _nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if _is_rename_post(r) else None)

    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    _select_all_and_type(page, title, "Half typed")

    other = page.context.new_page()
    other.goto(f"{live_server.url}/")
    other.bring_to_front()
    try:
        if page.evaluate("() => document.hasFocus()"):
            pytest.skip(
                "this run mode keeps document.hasFocus() true on a backgrounded "
                "page, so the window-blur bail-out is not observable here"
            )
        page.wait_for_timeout(600)
        assert posts == [], f"a window blur committed the edit: {posts}"
        assert title.input_value() == "Half typed", "the field must stay dirty"
    finally:
        other.close()


@pytest.mark.django_db(transaction=True)
def test_422_does_not_wedge_the_row(page, live_server):
    # (F) falsify: stop clearing readOnly on the non-200 branch.
    # A 422 is UNREACHABLE by typing (required blocks empty, maxlength truncates
    # over-length, ContentNode.clean validates nothing else), so it is forced here.
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")

    state = {"n": 0}

    def _handler(route):
        state["n"] += 1
        if state["n"] == 1:
            route.fulfill(
                status=422,
                content_type="text/html; charset=utf-8",
                body='<div class="op-error" role="alert">Nope.</div>',
            )
        else:
            route.continue_()

    page.route("**/build/node/rename/", _handler)

    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    _select_all_and_type(page, title, "Rejected")
    title.press("Enter")
    expect(page.locator(".op-error").first).to_be_visible()
    assert title.input_value() == "Rejected"  # typed text survives
    page.wait_for_function("el => el.readOnly === false", arg=title)  # not wedged
    assert page.evaluate("el => el === document.activeElement", title)
    # The counter (not page.unroute) is the mechanism: the second request falls through
    # to route.continue_() and reaches the real server. No unroute call is needed, and
    # the route stays registered for the rest of the test.
    title.press("Control+a")
    page.keyboard.type("Corrected")
    with page.expect_response(lambda r: _is_rename_post(r.request)):
        title.press("Enter")
    page.wait_for_selector('.tree__title[value="Corrected"]')
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Corrected"


# ------------------------------------------------------------------ token refresh


@pytest.mark.django_db(transaction=True)
def test_sibling_tokens_are_refreshed_so_duplicate_still_works(page, live_server):
    # (F) falsify: skip the rowhead token refresh in applyRename.
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    # MUST await the response: the token patch happens when it lands, so firing the
    # follow-up op immediately would race the round trip (which the design accepts as
    # a 409) and the test would be flaky by construction.
    _select_all_and_type(page, page.locator('.tree__title[value="Unit 1"]'), "Renamed")
    _commit_with_enter(page, "Renamed")
    # Anchor by pk and scope to the row's OWN head. `li.tree__row:has(...)` would match
    # the chapter and section ancestors too, and a bare descendant selector under those
    # also finds Unit 2's duplicate button -- two elements, so .click() raises a
    # strict-mode violation before the feature is exercised at all.
    row = page.locator(f'li.tree__row[data-node="{nodes["unit1"].pk}"]')
    row.locator(
        ':scope > .tree__rowhead form[data-op="duplicate"] button[type="submit"]'
    ).click()
    expect(page.locator('.tree__title[value="Renamed"]')).to_have_count(2)
    expect(page.locator(".op-error")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_reorder_arrows_still_work_after_a_rename(page, live_server):
    # (F) falsify: skip the rowhead token refresh in applyRename.
    from courses.models import ContentNode

    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    _select_all_and_type(page, page.locator('.tree__title[value="Unit 1"]'), "Moved")
    _commit_with_enter(page, "Moved")
    row = page.locator(f'li.tree__row[data-node="{nodes["unit1"].pk}"]')
    # Unit 1 is the FIRST sibling, so its "up" arrow renders disabled -- click "down".
    row.locator(
        ':scope > .tree__rowhead form[data-op="reorder"] button[value="down"]'
    ).click()
    page.wait_for_function(
        "([sel, pk]) => {const ol = document.querySelector(sel); if (!ol) return false;"
        " const rows = Array.from(ol.children)"
        ".filter(li => li.classList.contains('tree__row'));"
        " return rows.length && rows[0].getAttribute('data-node') !== pk;}",
        arg=[f'[data-scope="{nodes["section"].pk}"]', str(nodes["unit1"].pk)],
        timeout=5000,
    )
    expect(page.locator(".op-error")).to_have_count(0)
    assert ContentNode.objects.get(pk=nodes["unit1"].pk).order > 0


@pytest.mark.django_db(transaction=True)
def test_renaming_the_same_row_twice_needs_no_reload(page, live_server):
    """(F) falsify: skip the rowhead token refresh in applyRename.

    The only test exercising the rename form's OWN refreshed token together with
    the defaultValue reset -- without the reset the field would still read dirty
    against the old title.
    """
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    _select_all_and_type(page, title, "First")
    _commit_with_enter(page, "First")
    _select_all_and_type(page, title, "Second")
    _commit_with_enter(page, "Second")
    expect(page.locator(".op-error")).to_have_count(0)
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Second"


def _simulate_drag(page, src_selector, dst_selector):
    """Dispatch native HTML5 DnD events programmatically.

    Playwright's drag_to uses pointer events internally and does NOT fire
    dragstart/dragover/drop, so it would produce a silently-green "nothing
    happened" test. The `dragover` is required as well as the `drop`:
    scope.dataset.dropToken is populated only by the dragover handler, so a drop
    without one posts no parent_token and would not exercise the token refresh.
    Copied from tests/test_e2e_builder_ws2.py per the self-contained-e2e convention.
    """
    page.evaluate(
        """([srcSel, dstSel]) => {
            const src = document.querySelector(srcSel);
            const dst = document.querySelector(dstSel);
            if (!src || !dst)
                throw new Error('selector not found: ' + srcSel + ' | ' + dstSel);
            const dt = new DataTransfer();
            const srcRect = src.getBoundingClientRect();
            const dstRect = dst.getBoundingClientRect();
            src.dispatchEvent(new DragEvent('dragstart', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: srcRect.x + srcRect.width / 2,
                clientY: srcRect.y + srcRect.height / 2,
            }));
            dst.dispatchEvent(new DragEvent('dragover', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: dstRect.x + dstRect.width / 2,
                clientY: dstRect.y + dstRect.height / 2,
            }));
            dst.dispatchEvent(new DragEvent('drop', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: dstRect.x + dstRect.width / 2,
                clientY: dstRect.y + dstRect.height / 2,
            }));
            src.dispatchEvent(new DragEvent('dragend', {
                bubbles: true, cancelable: true, dataTransfer: dt,
            }));
        }""",
        [src_selector, dst_selector],
    )


@pytest.mark.django_db(transaction=True)
def test_dragging_a_just_renamed_row_does_not_conflict(page, live_server):
    """(F) falsify: drop `row.setAttribute("data-updated", token)` from applyRename.

    dragstart reads the <li>'s data-updated as node_token.
    """
    from courses.models import ContentNode

    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    _select_all_and_type(page, page.locator('.tree__title[value="Unit 1"]'), "Dragged")
    _commit_with_enter(page, "Dragged")

    _simulate_drag(
        page,
        f'li.tree__row[data-node="{nodes["unit1"].pk}"] .ica--grip',
        f'li.tree__row[data-node="{nodes["chapter"].pk}"]',
    )
    page.wait_for_function(
        "([sel, pk]) => {const ol = document.querySelector(sel); return ol &&"
        " Array.from(ol.children).some(li =>"
        " li.classList.contains('tree__row') && li.getAttribute('data-node') === pk);}",
        arg=[f'[data-scope="{nodes["chapter"].pk}"]', str(nodes["unit1"].pk)],
        timeout=5000,
    )
    expect(page.locator(".op-error")).to_have_count(0)
    moved = ContentNode.objects.get(pk=nodes["unit1"].pk)
    assert moved.parent_id == nodes["chapter"].pk


@pytest.mark.django_db(transaction=True)
def test_dragging_into_a_just_renamed_chapter_does_not_conflict(page, live_server):
    """(F) falsify: drop `scope.setAttribute("data-updated", token)` from applyRename.

    The child scope's data-updated is read by the dragover handler as dropToken and
    posted as parent_token.
    """
    from courses.models import ContentNode

    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    chapter_title = page.locator('.tree__title[value="Chapter 1"]')
    _select_all_and_type(page, chapter_title, "Ch One")
    _commit_with_enter(page, "Ch One")

    _simulate_drag(
        page,
        f'li.tree__row[data-node="{nodes["unit2"].pk}"] .ica--grip',
        f'li.tree__row[data-node="{nodes["chapter"].pk}"]',
    )
    page.wait_for_function(
        "([sel, pk]) => {const ol = document.querySelector(sel); return ol &&"
        " Array.from(ol.children).some(li =>"
        " li.classList.contains('tree__row') && li.getAttribute('data-node') === pk);}",
        arg=[f'[data-scope="{nodes["chapter"].pk}"]', str(nodes["unit2"].pk)],
        timeout=5000,
    )
    expect(page.locator(".op-error")).to_have_count(0)
    moved = ContentNode.objects.get(pk=nodes["unit2"].pk)
    assert moved.parent_id == nodes["chapter"].pk


@pytest.mark.django_db(transaction=True)
def test_adding_under_a_just_renamed_chapter_does_not_conflict(page, live_server):
    """Guards the child scope's add-form parent_token.

    The fixture chapter CONTAINS a nested section with its own add row, so a naive
    descendant query for parent_token would find the GRANDCHILD's; the final
    assertion (the section's own add still works) is what catches a mis-stamped one.
    """
    from courses.models import ContentNode

    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    chapter_title = page.locator('.tree__title[value="Chapter 1"]')
    _select_all_and_type(page, chapter_title, "Ch Two")
    _commit_with_enter(page, "Ch Two")

    ch_pk = nodes["chapter"].pk
    chapter_add = page.locator(f'form.tree__add[data-add-scope="{ch_pk}"]')
    chapter_add.locator('button[data-add-kind="section"]').click()
    chapter_add.locator("input[data-add-title]").fill("Fresh section")
    chapter_add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector('.tree__title[value="Fresh section"]')
    expect(page.locator(".op-error")).to_have_count(0)
    assert ContentNode.objects.filter(
        course=course, parent=nodes["chapter"], title="Fresh section"
    ).exists()

    # The nested section's own add row must still carry ITS token, not the chapter's.
    sec_pk = nodes["section"].pk
    section_add = page.locator(f'form.tree__add[data-add-scope="{sec_pk}"]')
    section_add.locator('button[data-add-kind="lesson"]').click()
    section_add.locator("input[data-add-title]").fill("Fresh lesson")
    section_add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector('.tree__title[value="Fresh lesson"]')
    expect(page.locator(".op-error")).to_have_count(0)
    assert ContentNode.objects.filter(
        course=course, parent=nodes["section"], title="Fresh lesson"
    ).exists()


# -------------------------------------------------------------------------- errors


@pytest.mark.django_db(transaction=True)
def test_409_reloads_the_row_and_discards_the_edit(page, live_server):
    """(F) falsify: route the 409 through applyRename instead of applyFragment --
    the row would keep the stale title and this goes RED.

    This is the ONE path that still swaps a scope, deliberately: the tree genuinely
    diverged and must be reloaded to server truth. The typed title is discarded and
    focus drops to <body>. That is an accepted cost; the test pins it so it cannot
    change unnoticed.
    """
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")

    # Force the page's token stale server-side, AFTER the render. Route-fulfilling a
    # hand-written body would not be the real _conflict_scope [data-scope] fragment
    # these assertions depend on.
    node = nodes["unit1"]
    node.title = "Changed elsewhere"
    node.save(update_fields=["title", "updated"])

    _select_all_and_type(page, page.locator('.tree__title[value="Unit 1"]'), "My edit")
    with page.expect_response(lambda r: _is_rename_post(r.request)):
        page.keyboard.press("Enter")

    expect(page.locator(".op-error")).to_be_visible()
    expect(page.locator('.tree__title[value="Changed elsewhere"]')).to_have_count(1)
    expect(page.locator('.tree__title[value="My edit"]')).to_have_count(0)
    page.wait_for_function("() => document.activeElement.tagName === 'BODY'")
    node.refresh_from_db()
    assert node.title == "Changed elsewhere"


@pytest.mark.django_db(transaction=True)
def test_open_add_rows_deferred_commit_clobbers_a_fresh_rename_edit(page, live_server):
    """(F) falsify: drop `swapping ||` from the focusout handler's bail-out 3 -- the
    rename posts "Doomed" and the zero-POST assertion goes RED (measured: 10 runs of
    10, so this is a real guard and not a flake). Falsify the other half by removing
    the deferred `commitOrCancel(form)` from the add row's focusout: no swap happens,
    the input survives, focus never drops to <body> and the wait times out.

    ACCEPTED behaviour, pinned rather than left to be discovered: 120ms after the add
    field blurs, commitOrCancel posts node_add, whose 200 is a [data-scope] fragment
    that applyFragment swaps -- destroying the rename input mid-edit. The typed text
    is lost. Cross-wiring the two flows to preserve it would reintroduce the
    coordination machinery this design removed.

    What must NOT happen is the edit committing anyway. Chromium delivers a focusout
    for the doomed input from inside replaceWith(), while it still reports
    isConnected === true, so only the `swapping` flag stops it; a commit from there
    posts a superseded token, applyRename then no-ops on the now-detached form, and
    the tree is left displaying "Unit 1" over a database holding "Doomed".

    The assertion is on REQUESTS, not on the row's title in the database. An earlier
    version read the database the instant focus reached <body> -- which is true at
    swap time, i.e. inside the window between the POST being issued and it landing.
    It sampled that gap and passed locally while the commit went through behind it;
    only a loaded CI runner closed the gap and turned it red.
    """
    from courses.models import ContentNode

    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if _is_rename_post(r) else None)

    sec_pk = nodes["section"].pk
    section_add = page.locator(f'form.tree__add[data-add-scope="{sec_pk}"]')
    section_add.locator('button[data-add-kind="lesson"]').click()
    section_add.locator("input[data-add-title]").fill("Deferred child")

    # Click a title in the SAME scope and start typing; the add row's blur timer is
    # now armed behind us.
    _select_all_and_type(page, page.locator('.tree__title[value="Unit 1"]'), "Doomed")
    page.wait_for_selector('.tree__title[value="Deferred child"]')
    page.wait_for_function("() => document.activeElement.tagName === 'BODY'")

    # The swap has landed and torn the input out. Let any commit it could have posted
    # reach the server before reading either the request log or the row.
    page.wait_for_timeout(500)
    assert posts == [], "the torn-out rename must not have posted"
    assert ContentNode.objects.filter(
        course=course, parent=nodes["section"], title="Deferred child"
    ).exists()

    # Exactly one row for the unit, still showing server truth, and no error surfaced.
    assert page.locator('.tree__title[value="Unit 1"]').count() == 1
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Unit 1"
    expect(page.locator(".op-error")).to_have_count(0)

    # Not wedged: the swapped-in row is editable and its token is current, so the
    # author simply retypes rather than being met with a phantom 409.
    _select_all_and_type(page, page.locator('.tree__title[value="Unit 1"]'), "Retyped")
    _commit_with_enter(page, "Retyped")
    expect(page.locator(".op-error")).to_have_count(0)
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Retyped"


@pytest.mark.django_db(transaction=True)
def test_enter_on_an_empty_field_does_not_wedge_or_post(page, live_server):
    """(F) falsify: set input.readOnly BEFORE form.reportValidity() in commitRename.

    A readonly input is barred from constraint validation, so `required` stops
    firing and the empty title is POSTed (and merely 422s). Without the zero-request
    assertion the test would pass in that build.
    """
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if _is_rename_post(r) else None)

    title = page.locator('.tree__title[value="Unit 1"]').element_handle()
    title.click()
    title.press("Control+a")
    page.keyboard.press("Backspace")
    assert title.input_value() == ""
    title.press("Enter")
    page.wait_for_timeout(600)
    assert posts == [], f"an empty title was POSTed: {posts}"

    page.keyboard.type("Recovered")
    _commit_with_enter(page, "Recovered")
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Recovered"


# ------------------------------------------------------------- navigation / a11y


@pytest.mark.django_db(transaction=True)
def test_tabbing_across_a_row_issues_one_panel_fetch(page, live_server):
    # (F) falsify: scope the panelTimer clear to .tree__title focusins only.
    course, _nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    gets = []
    page.on("request", lambda r: gets.append(r.url) if _is_panel_get(r) else None)

    # Start tabbing IMMEDIATELY -- do not settle, do not clear. Unit 1's debounced
    # fetch must still be PENDING when traversal begins: that pending timer is the
    # whole point. Draining it first (a 400ms wait + gets.clear()) makes the test
    # vacuous -- the falsified build would record the same single GET and pass, and so
    # would a build with no debounce at all. The only timing requirement is that the
    # first Tab lands within 150ms of this focus, which is not tight.
    page.locator('.tree__title[value="Unit 1"]').focus()

    # The REAL tab order is title -> cluster controls -> next row's title, and the
    # number of stops VARIES: _move_buttons renders the up arrow `disabled` on the
    # first sibling and the down arrow `disabled` on the last, and disabled buttons are
    # skipped. So tab until focus lands on a title again rather than hard-coding a
    # count -- a wrong count lands on a cluster control, whose focusin clears the timer,
    # and the test then asserts 0 == 1 for a reason unrelated to the debounce.
    for _ in range(15):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.classList.contains('tree__title')"):
            break
    else:
        raise AssertionError("never tabbed back onto a .tree__title")
    assert page.evaluate("document.activeElement.value") == "Unit 2"

    page.wait_for_timeout(400)  # let the 150ms debounce settle
    # Exactly one: Unit 2's. Unit 1's pending timer was cancelled by the first cluster
    # focusin. Falsified (clear scoped to .tree__title focusins), this records 2.
    assert len(gets) == 1, gets


@pytest.mark.django_db(transaction=True)
def test_the_hidden_rename_submit_is_not_a_tab_stop(page, live_server):
    """.visually-hidden uses the clip pattern, which keeps an element FOCUSABLE --
    without tabindex="-1" every row would gain a second tab stop right after the
    title."""
    course, _nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    page.locator('.tree__title[value="Unit 1"]').focus()
    page.keyboard.press("Tab")
    landed = page.evaluate(
        "() => {const a = document.activeElement;"
        " return {tag: a.tagName, cls: a.className, type: a.type || ''};}"
    )
    assert "visually-hidden" not in landed["cls"], (
        f"Tab landed on the hidden Rename submit: {landed}"
    )
    assert landed["cls"].startswith("ica"), landed


@pytest.mark.django_db(transaction=True)
def test_tab_then_click_another_row_ends_on_the_clicked_row(page, live_server):
    """Only the END STATE is asserted: Playwright cannot guarantee both actions
    complete inside the 150ms window, and a timing-based assertion flakes both ways.

    HONEST SCOPE, contrary to the plan: this does NOT pin the panelReq
    last-request-wins guard. Removing that guard leaves the test green, because the
    click's own focusin clears Unit 1's pending debounce timer before its fetch is
    ever issued -- so only one request exists and there is nothing to race. What the
    test does pin is that a pointer click into a title selects THAT row (falsified
    by making the pointer branch of the focusin handler a no-op: RED). The
    last-request-wins guard has no e2e-observable failure mode found here.
    """
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    page.locator('.tree__title[value="Unit 1"]').focus()
    page.locator('.tree__title[value="Unit 2"]').click()
    page.wait_for_timeout(800)
    expect(page.locator(f'.panel[data-panel-for="{nodes["unit2"].pk}"]')).to_have_count(
        1
    )
    expect(page.locator(f'.panel[data-panel-for="{nodes["unit1"].pk}"]')).to_have_count(
        0
    )


@pytest.mark.django_db(transaction=True)
def test_rename_preserves_document_scroll_on_a_long_tree(page, live_server):
    """Renaming a row far down a long tree keeps both the scroll position and the
    author's place in it.

    (F) falsified by reverting to the naive design (node_rename returns
    _render_scope, applyFragment applies it): the FOCUS assertion goes RED.

    The scrollY assertion alone does NOT distinguish the two designs -- verified: a
    scope swap replaces the <ol> with identical-height markup, so the document never
    changes height and the browser keeps scrollY. It is kept as the cheap regression
    guard it is; the focus assertion is what carries this test.
    """
    course, nodes = _seed_course(n_filler=40)
    page.set_viewport_size({"width": 1280, "height": 700})
    _open_builder(page, live_server, course, "owner")

    target = page.locator('.tree__title[value="Filler 35"]').element_handle()
    _select_all_and_type(page, target, "Scrolled rename")
    scroll_before = page.evaluate("() => window.scrollY")
    assert scroll_before > 0, "the tree did not overflow the viewport; seed more rows"
    _commit_with_enter(page, "Scrolled rename")
    assert page.evaluate("() => window.scrollY") == scroll_before
    assert page.evaluate("el => el === document.activeElement", target), (
        "focus was lost 35 rows down the tree -- a scope swap happened"
    )
    nodes["filler"][35].refresh_from_db()
    assert nodes["filler"][35].title == "Scrolled rename"
