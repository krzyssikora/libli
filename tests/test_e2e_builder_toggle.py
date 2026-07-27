import os

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    """Every e2e module in this repo defines this (74 of them). Fixtures
    declared in a test module are module-LOCAL, so a new file inherits
    nothing -- and running this file alone, which Steps 2/5 and Task 9 all
    do, would raise SynchronousOnlyOperation the moment the ORM is touched
    under the sync Playwright greenlet."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _make_pa_user(username):
    """Copied from tests/test_e2e_builder.py -- do NOT hand-roll this.

    UserFactory sets the password to "password123", not TEST_PASSWORD, and
    creates no verified email, so allauth's AccountMiddleware bounces the
    session to verify-email and the login silently never takes.
    """
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
    """allauth's field is name="login", not "username", and there is no
    `accounts:login` URL name -- the path is literal. The submit button is
    form-scoped because a bare button[type=submit] hits the shell header's
    language/logout buttons first."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _simulate_drag(page, src_selector, dst_selector, moves=1):
    """Dispatch native HTML5 DnD events.

    Playwright's pointer input (mouse.down/hover/up) and drag_to do NOT fire
    dragstart/dragover/drop in Chromium -- this repo measured that and ships
    this helper in tests/test_e2e_builder_ws2.py for exactly that reason.
    `moves` controls how many dragover events precede the drop: 1 exercises
    the drop-flushes-the-pending-frame path.
    """
    page.evaluate(
        """([srcSel, dstSel, moves]) => {
            const src = document.querySelector(srcSel);
            const dst = document.querySelector(dstSel);
            if (!src || !dst)
                throw new Error('selector not found: ' + srcSel + ' | ' + dstSel);
            const dt = new DataTransfer();
            const s = src.getBoundingClientRect(), d = dst.getBoundingClientRect();
            src.dispatchEvent(new DragEvent('dragstart', {bubbles: true,
                cancelable: true, dataTransfer: dt,
                clientX: s.x + s.width / 2, clientY: s.y + s.height / 2}));
            for (let i = 0; i < moves; i++) {
                dst.dispatchEvent(new DragEvent('dragover', {bubbles: true,
                    cancelable: true, dataTransfer: dt,
                    clientX: d.x + d.width / 2, clientY: d.y + d.height / 2}));
            }
            dst.dispatchEvent(new DragEvent('drop', {bubbles: true,
                cancelable: true, dataTransfer: dt,
                clientX: d.x + d.width / 2, clientY: d.y + d.height / 2}));
            src.dispatchEvent(new DragEvent('dragend', {bubbles: true,
                cancelable: true, dataTransfer: dt}));
        }""",
        [src_selector, dst_selector, moves],
    )


def _seed(owner, slug="e2e"):
    """part > [chap A, chap B] ; chap A > unit + 160 filler units.

    TWO chapters on purpose: with a single child, _scope.html passes
    is_first=is_last=True and _move_buttons.html renders BOTH reorder buttons
    `disabled` -- Playwright then waits for an enabled element and times out,
    and the tab order shifts by two stops.
    """
    course = CourseFactory(slug=slug, owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="Part A")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=part, title="Chap A")
    ch_b = ContentNodeFactory(
        course=course, kind="chapter", parent=part, title="Chap B"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="Unit A"
    )
    # push the course over SIZE_THRESHOLD so it does NOT auto-expand -- under
    # the threshold every assertion below would pass vacuously
    for i in range(160):
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=ch, title=f"U{i}"
        )
    return course, part, ch, unit, ch_b


def stamp(page):
    """Mark the current document so a navigation can be detected."""
    page.evaluate("() => { window.__samedoc = 1; }")


def assert_no_navigation(page):
    """Pin a test to the JS path.

    Task 4 gives every toggle a REAL href (`?open=…#node-N`), so before any JS
    exists a click performs a full page load that expands the scope, sets
    aria-expanded, and survives a reload. Without this guard the whole toggle
    suite passes with zero JS -- Step 2's red gate is green and none of the
    tests distinguishes the fetch path from a navigation.

    Detected with a window sentinel, NOT with performance navigation entries:
    a cross-document navigation creates a fresh Window with a fresh timeline
    that again holds exactly ONE navigation entry, so counting them is always
    1 and can never fail. A new document destroys `window.__samedoc`.
    """
    assert page.evaluate("() => window.__samedoc === 1"), (
        "the page navigated; this test must exercise the JS fetch path"
    )


def test_toggle_expands_and_collapses(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, _unit, _chb = _seed(owner)
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}"
    )
    assert page.locator(f'[data-node="{ch.pk}"]').count() == 0
    stamp(page)  # detect a navigation
    page.click(f'[data-toggle="{part.pk}"]')  # the REAL gesture
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    assert_no_navigation(page)  # must be the fetch path, not the href
    toggle = page.locator(f'[data-toggle="{part.pk}"]')
    assert toggle.get_attribute("aria-expanded") == "true"
    assert toggle.get_attribute("aria-controls") == f"tree-scope-{part.pk}"
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]', state="detached")
    assert toggle.get_attribute("aria-expanded") == "false"
    assert toggle.get_attribute("aria-controls") is None


def test_double_click_yields_exactly_one_scope(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner)
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}"
    )
    stamp(page)
    page.dblclick(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    assert_no_navigation(page)
    assert page.locator(f'ol[data-scope="{part.pk}"]').count() == 1


def test_expansion_survives_a_reload(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner)
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'e2e'})}"
    )
    stamp(page)  # detect a navigation
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    assert_no_navigation(page)  # must be the fetch path, not the href
    page.reload()
    page.wait_for_selector(f'[data-node="{ch.pk}"]')  # replaceState carried it


def test_collapsing_the_last_scope_survives_a_reload(page, live_server):
    """The empty set must be written as `open=` (present, empty), not omitted,
    or the reload re-seeds from the session and springs the tree back open."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner)
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "e2e"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    stamp(page)  # detect a navigation
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]', state="detached")
    assert_no_navigation(page)  # must be the fetch path, not the href
    page.reload()
    assert page.locator(f'[data-node="{ch.pk}"]').count() == 0


def test_deleting_a_node_preserves_the_expanded_tree(page, live_server):
    owner = _make_pa_user("pa")
    course, part, ch, unit, _chb = _seed(owner, slug="del")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "del"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    page.click(f'[data-toggle="{ch.pk}"]')  # expand a second level
    page.wait_for_selector(f'ol[data-scope="{ch.pk}"]')
    page.click(f'[data-node="{unit.pk}"] a[data-delete]')
    page.wait_for_selector("form[action*='delete']")
    page.click("form[action*='delete'] button[type='submit']")
    page.wait_for_selector(f'ol[data-scope="{ch.pk}"]')  # BOTH scopes still open


def test_a_failed_scope_fetch_leaves_the_row_usable(page, live_server):
    """The in-flight guard clears on BOTH paths, or the row wedges forever."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="fail")
    _login(page, live_server, "pa")
    page.route(
        "**/scope/**", lambda route: route.fulfill(status=500, body="")
    )  # deterministic
    page.goto(
        f"{live_server.url}{reverse('courses:manage_builder', kwargs={'slug': 'fail'})}"
    )
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(".op-error")
    assert page.locator(".builder[data-busy]").count() == 0  # counter unwound
    page.unroute("**/scope/**")
    page.click(f'[data-toggle="{part.pk}"]')  # still works
    page.wait_for_selector(f'[data-node="{ch.pk}"]')


def test_an_unrelated_toggle_click_still_commits_a_pending_rename(page, live_server):
    """The converse of the dirty-rename guard: arming `swapping` for ANY
    toggle would silently discard this edit."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="ren")
    # unit_type=None: every non-unit node must pass it explicitly, or the
    # factory's "lesson" default trips full_clean()'s "Only units may have a
    # unit_type" the moment this node is renamed (see test_e2e_inline_rename.py:68).
    other = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Other part"
    )
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "ren"})
    page.goto(f"{live_server.url}{url}?open=")
    field = page.locator(f'[data-node="{other.pk}"] input.tree__title')
    field.click()
    field.fill("Renamed elsewhere")
    # Wait on the RENAME response, not on the scope fetch. They are different
    # requests, and asserting on the DB after the wrong one samples a race
    # window rather than an outcome -- it would flake on a slow runner and,
    # worse, could pass merely because the rename was slow rather than
    # suppressed.
    with page.expect_response(lambda r: "/node/rename/" in r.url and r.status == 200):
        page.click(f'[data-toggle="{part.pk}"]')  # a DIFFERENT row's toggle
    page.wait_for_selector(f'[data-node="{ch.pk}"]')
    other.refresh_from_db()
    assert other.title == "Renamed elsewhere"


def test_collapsing_over_a_dirty_rename_posts_nothing(page, live_server):
    """Driven by a real MOUSE click: focusout fires at mousedown, so a
    keyboard-only test would exercise the path that was already correct."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="dirty")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "dirty"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    field = page.locator(f'[data-node="{ch.pk}"] input.tree__title')
    field.click()
    field.fill("Half typed")
    stamp(page)  # detect a navigation
    page.click(f'[data-toggle="{part.pk}"]')  # collapses ch's own subtree
    page.wait_for_selector(f'[data-node="{ch.pk}"]', state="detached")
    assert_no_navigation(page)  # must be the fetch path, not the href
    ch.refresh_from_db()
    assert ch.title == "Chap A"  # abandoned, not committed


def test_keyboard_traversal_still_issues_one_panel_fetch(page, live_server):
    """The toggle adds a focus stop before every container title."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="kbd")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "kbd"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    # Start FROM a title, or Tab may never reach the tree (the base shell has a
    # skip link, header nav and the builder's own header links first) and the
    # assertion would hold with zero fetches, guarding nothing.
    # `> .tree__rowhead`, not a bare descendant combinator: part is open (that is
    # the point of this test), so its own <li> also CONTAINS its two children's
    # rows -- a plain `[data-node=X] input.tree__title` matches all three titles
    # and is a Playwright strict-mode violation.
    page.locator(
        f'li.tree__row[data-node="{part.pk}"] > .tree__rowhead input.tree__title'
    ).focus()
    assert page.evaluate("() => !!document.activeElement.closest('.tree__title')"), (
        "traversal must start inside the tree"
    )
    # Press the FIRST Tab before attaching the listener: .focus() arms the
    # 150ms panel debounce for this title, and on a loaded runner the gap
    # before the first press could exceed it, landing an extra fetch and
    # making len(calls) == 2.
    page.keyboard.press("Tab")
    calls = []
    page.on(
        "request",
        lambda r: (
            calls.append(r.url)
            if "/build/node/" in r.url and r.url.rstrip("/").split("/")[-1].isdigit()
            else None
        ),
    )
    # Tab until the NEXT title, bounded. Do not hard-code a stop count: the
    # reorder buttons are disabled (and so unfocusable) from is_first/is_last,
    # which _scope.html derives from forloop position among SIBLINGS -- not
    # from the node's child count -- so the count shifts with the fixture and
    # any hard-coded number silently lands on a non-title, where focusin
    # clears the timer and ZERO fetches fire.
    for _ in range(15):
        page.keyboard.press("Tab")
        if page.evaluate("() => !!document.activeElement.closest('.tree__title')"):
            break
    else:
        raise AssertionError("never reached a second title within 15 tab stops")
    page.wait_for_timeout(400)  # longer than the 150ms debounce
    assert len(calls) == 1  # exactly one, not "at most"


def test_two_overlapping_tree_fetches_stay_busy_until_both_settle(page, live_server):
    """The whole reason §8 specifies a COUNTER rather than a boolean."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="busy")
    other = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Second part"
    )
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "busy"})
    page.goto(f"{live_server.url}{url}?open=")
    # Capture-and-release, the pattern this suite already uses
    # (tests/test_e2e_inline_rename.py:326). Sleeping inside a sync route
    # handler serialises the driver and makes the overlap a wall-clock guess.
    held = []
    page.route("**/scope/**", lambda route: held.append(route))
    page.click(f'[data-toggle="{part.pk}"]')
    page.click(f'[data-toggle="{other.pk}"]')
    page.wait_for_function(
        "() => document.querySelectorAll('[data-submitting]').length === 2"
    )
    assert page.locator(".builder[data-busy]").count() == 1
    held[0].continue_()
    page.wait_for_selector(f'ol[data-scope="{part.pk}"]')
    assert page.locator(".builder[data-busy]").count() == 1  # still one in flight
    held[1].continue_()
    page.wait_for_selector(f'ol[data-scope="{other.pk}"]')
    assert page.locator(".builder[data-busy]").count() == 0  # counter unwound


def test_a_panel_fetch_never_sets_the_busy_state(page, live_server):
    """It fires on mere keyboard traversal; counting it would flicker the tree."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="nobusy")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "nobusy"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    flagged = []
    page.locator(f'[data-node="{ch.pk}"] input.tree__title').click()
    page.wait_for_timeout(50)
    flagged.append(page.locator(".builder[data-busy]").count())
    page.wait_for_timeout(300)
    assert flagged == [0]


def test_collapse_forgets_descendants_through_the_JS_toggle(page, live_server):
    """The JS half of the invariant. The no-JS half is a template-tag test; the
    mechanism here is different (subtree removal + collectOpen re-derivation),
    which is where a bug would actually live."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="forget")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "forget"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    stamp(page)  # detect a navigation across the whole click sequence below
    page.click(f'[data-toggle="{ch.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{ch.pk}"]')
    page.click(f'[data-toggle="{part.pk}"]')  # collapse the parent
    page.wait_for_selector(f'ol[data-scope="{part.pk}"]', state="detached")
    page.click(f'[data-toggle="{part.pk}"]')  # re-expand it
    page.wait_for_selector(f'ol[data-scope="{part.pk}"]')
    assert_no_navigation(page)  # must be the fetch path throughout, not the href
    assert page.locator(f'ol[data-scope="{ch.pk}"]').count() == 0


def test_a_mutation_landing_mid_toggle_leaves_no_detached_scope(page, live_server):
    """Exercises the re-resolve-and-bail guard in the toggle's .then."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="midflight")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "midflight"})
    page.goto(f"{live_server.url}{url}?open={part.pk}")
    # `ch` has a sibling (Chap B), so its "down" button is ENABLED -- with a
    # lone child _move_buttons renders both disabled and page.click() would
    # block until timeout.
    down = page.locator(f'[data-node="{ch.pk}"] button[name="direction"][value="down"]')
    assert down.is_enabled(), "fixture must give ch a sibling"
    held = []
    page.route("**/scope/**", lambda route: held.append(route))
    page.click(f'[data-toggle="{ch.pk}"]')  # held scope fetch
    page.wait_for_function("() => !!document.querySelector('[data-submitting]')")
    handle = page.evaluate_handle(
        f"() => document.querySelector('li[data-node=\"{ch.pk}\"]')"
    )
    down.click()  # a reorder returns _render_scope, replacing the row
    page.wait_for_selector(f'li[data-node="{ch.pk}"]')  # the fresh row
    held[0].continue_()  # now let it land
    page.wait_for_timeout(300)
    assert page.locator(f'ol[data-scope="{ch.pk}"]').count() <= 1
    # The pre-mutation row must be detached AND must not have gained a scope.
    # (`querySelectorAll(...).every(o => o.isConnected)` is vacuous -- that API
    # only ever returns attached nodes.)
    assert page.evaluate(
        "(el) => !el.isConnected && !el.querySelector('ol.tree__scope')", handle
    )


def test_pk_substitution_survives_a_slug_containing_a_zero(page, live_server):
    """Guards the $-anchored replacement in scopeUrlFor and the panel URL."""
    owner = _make_pa_user("pa")
    course, part, ch, _u, _chb = _seed(owner, slug="mat-0-pp")
    _login(page, live_server, "pa")
    url = reverse("courses:manage_builder", kwargs={"slug": "mat-0-pp"})
    page.goto(f"{live_server.url}{url}")
    stamp(page)  # detect a navigation
    page.click(f'[data-toggle="{part.pk}"]')
    page.wait_for_selector(f'[data-node="{ch.pk}"]')  # a naive replace() 404s
    assert_no_navigation(page)  # must be the fetch path, not the href
