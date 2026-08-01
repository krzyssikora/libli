"""End-to-end rows for the builder's title filter (slice 2).

A new e2e module inherits NOTHING: fixtures and helpers declared in a test
module are module-LOCAL, so every helper below is copied from
tests/test_e2e_builder_toggle.py on purpose.
"""

import os

import pytest
from django.urls import reverse

from courses.models import ContentNode
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


def _builder(course):
    return reverse("courses:manage_builder", kwargs={"slug": course.slug})


def _center(locator):
    box = locator.bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _seed_flat(owner):
    """chapter > one matching unit. The chapter title must NOT contain
    "tryg", or it joins the match chain and renders already-expanded -- at
    which point clicking its toggle COLLAPSES it, no request is issued, and
    the toggle rows below wait forever on a removed element.
    """
    course = CourseFactory(slug="e2ef", owner=owner)
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria"
    )
    return course, chap, hit


def _seed_two(owner):
    """_seed_flat plus a NON-matching sibling, for the rows that assert the
    filter hides something."""
    course, chap, hit = _seed_flat(owner)
    miss = ContentNodeFactory(course=course, kind="unit", parent=chap, title="Logika")
    return course, chap, hit, miss


def _seed_deep(owner):
    """part > chapter > matching unit, for the stash and expand-all rows,
    which need two nested scopes to tell apart."""
    course = CourseFactory(slug="e2ed", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Czesc"
    )
    chap = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial"
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", parent=chap, title="Trygonometria"
    )
    return course, part, chap, hit


def test_a_toggle_under_a_filter_carries_the_APPLIED_q(page, live_server):
    """Three values are in play during the 300ms debounce: the hidden input
    holds the last RENDERED q, the box holds what is currently typed, and the
    tracker holds what the pane actually shows. Sending the live value returns
    markup filtered by `trygo` into a pane rendered for `tryg`."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    # ?open= as well as ?q=: under an active filter every ancestor of every
    # match is in `chains`, so `chap` would render ALREADY EXPANDED and the
    # click below would collapse it -- no request, and the wait would time out
    # on a removed element. An explicit empty `open` wins by precedence step 2.
    page.goto(f"{live_server.url}{_builder(course)}?q=tryg&open=")

    # Kill every filter fetch for the whole row, so appliedQ CANNOT advance
    # past the rendered `tryg` no matter when the debounce fires. Without this
    # the assertions depend on page.fill and page.click both completing inside
    # the 300 ms window: if the timer wins, applyFilterState swaps the top
    # scope (removing the toggle mid-click) and writes appliedQ = "trygo", and
    # the last assertion fails intermittently on a loaded machine. Sleeping or
    # "do NOT wait for the debounce" is sampling a race, not pinning a rule.
    #
    # `**/build/tree/**` matches manage_tree ONLY -- the toggle's own request
    # is /build/node/<pk>/scope/ (courses/urls.py:169) and is untouched. The
    # aborted fetch raises a "Network error" notice this row does not assert
    # on, and [data-busy] deliberately does not block pointer events
    # (builder.css:196-198), so the toggle click still lands.
    page.route("**/build/tree/**", lambda route: route.abort())

    sent = []
    page.on("request", lambda r: sent.append(r.url) if "/build/" in r.url else None)

    page.fill("#builder-q", "trygo")
    page.click(f'[data-toggle="{chap.pk}"]')
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')

    scope_reqs = [u for u in sent if "/scope/" in u]
    assert scope_reqs, "the toggle issued no request"
    assert "q=tryg" in scope_reqs[-1]
    assert "q=trygo" not in scope_reqs[-1]


def test_drag_is_inert_while_a_filter_is_active(page, live_server):
    """The row that catches the targetFor-index-into-full-list defect, which
    produces no error and no visible symptom in the filtered pane. Uses the
    real gesture via _simulate_drag (tests/test_e2e_builder_toggle.py:56),
    never page.evaluate."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    # NOT `other = ContentNodeFactory(...)`: the name is never read, and ruff
    # selects `F`, so F841 would fail this task's own Step 8 lint gate. The
    # filtered_course fixture uses the same unbound-call idiom for "Pusty".
    ContentNodeFactory(course=course, kind="unit", parent=chap, title="Logika")
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    before = list(
        ContentNode.objects.filter(parent=chap)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    moved = []
    page.on("request", lambda r: moved.append(r.url) if "node/move" in r.url else None)
    _simulate_drag(
        page, f'li[data-node="{hit.pk}"] .ica--grip', f'ol[data-scope="{part.pk}"]'
    )
    page.wait_for_timeout(400)
    assert moved == []
    after = list(
        ContentNode.objects.filter(parent=chap)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    assert before == after


def test_typing_a_query_filters_without_navigating(page, live_server):
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    stamp(page)  # plants window.__samedoc; assert_no_navigation
    # only READS it, so the order is load-bearing
    page.fill("#builder-q", "trygo")
    # Wait on the non-matching row DISAPPEARING, never on the matching one
    # appearing: these fixtures are under SIZE_THRESHOLD, so a bare page GET
    # takes precedence step 4 and opens every container -- `hit` is already in
    # the DOM at load, the wait returns instantly, and the assertions below run
    # inside the 300 ms debounce, before any fetch exists.
    page.wait_for_selector(f'li[data-node="{miss.pk}"]', state="detached")
    assert_no_navigation(page)  # AFTER the gesture, or it cannot detect one
    assert "q=trygo" in page.url


def test_the_filter_fetch_omits_open(page, live_server):
    """Collapse the target's ancestor chain FIRST. Without that the row is
    vacuous: filtering is done by the restricted map, so sending
    open=<collector> and sending nothing produce identical rows on any tree
    whose match ancestors are already open."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    sent = []
    page.on(
        "request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None
    )
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'li[data-node="{hit.pk}"]')
    assert sent and "open=" not in sent[-1]


def test_typing_below_the_floor_into_an_UNFILTERED_tree_issues_no_request(
    page, live_server
):
    """Without the applied-state guard the first character takes the clear
    path, the stash is null, and the fallback sends the collector's full
    enumeration -- a complete re-render triggered by one keystroke."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    sent = []
    page.on(
        "request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None
    )
    page.fill("#builder-q", "t")
    page.wait_for_timeout(600)
    assert sent == []


def test_a_single_astral_character_issues_no_filter_fetch(page, live_server):
    """The ONE row that can go red against a `.length` client measure, which
    is worth ~1M characters of tree-collapsing exposure: .length counts UTF-16
    units and Python counts code points, so an astral character is 2 here and
    1 there. Every other floor row uses BMP input, where the two agree."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    sent = []
    page.on(
        "request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None
    )
    page.fill("#builder-q", "\U0001d400")
    page.wait_for_timeout(600)
    assert sent == []


def test_the_client_reads_data_q_min_rather_than_hardcoding_it(
    page, live_server, monkeypatch
):
    """The view-level row asserts the ATTRIBUTE; only this one can go red
    against a by-value `2` in builder.js."""
    monkeypatch.setattr("courses.builder_filter.MIN_QUERY", 3)
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    sent = []
    page.on(
        "request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None
    )
    page.fill("#builder-q", "tr")  # 2 chars, below a floor of 3
    page.wait_for_timeout(600)
    assert sent == []


def test_retrying_the_same_query_after_a_FAILED_fetch_issues_a_new_request(
    page, live_server
):
    """pendingQ advances at ISSUE time and only the success path advances
    appliedQ, so a failed fetch leaves pendingQ ahead of reality. Without the
    rollback, retrying the identical query takes the skip branch: no request,
    yet appliedQ, syncUrl and the bulk hrefs all move as if it had worked --
    the pane shows the pre-filter tree while ?q=trygo sits in the URL, and the
    next toggle sends q=trygo against unfiltered markup.

    One keystroke from the suite already: Task 10's headline row aborts every
    filter fetch for exactly this reason.
    """
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")

    fail = [True]
    sent = []

    def handler(route):
        sent.append(route.request.url)
        if fail[0]:
            fail[0] = False
            route.abort()
        else:
            route.continue_()

    page.route("**/build/tree/**", handler)

    page.fill("#builder-q", "trygo")
    page.wait_for_timeout(600)
    assert len(sent) == 1, "the first attempt did not reach the network"

    # The retry gesture: Enter on the form, same query, nothing retyped.
    page.press("#builder-q", "Enter")
    page.wait_for_selector(f'li[data-node="{miss.pk}"]', state="detached")
    assert len(sent) == 2, "the retry was skipped; pendingQ was never rolled back"


def test_clearing_a_BELOW_FLOOR_query_scrubs_it_from_the_url_and_the_hrefs(
    page, live_server
):
    """The skip path, which issues no request and therefore reaches no
    response handler. effectiveQ("a") and effectiveQ("") are BOTH "", so the
    guard returns early -- and without syncUrl/rewriteBulkHrefs on that path
    `?q=a` outlives the Clear it was cleared by. No other row exercises it:
    every other clear crosses the floor and takes the fetch path.

    The HREF half of this rule is asserted in Task 13, not here:
    rewriteBulkHrefs is still a no-op stub at the end of this task, so an
    href assertion would be red for a reason that is not the behaviour
    under test.
    """
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=a&open=all")
    sent = []
    page.on(
        "request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None
    )
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    assert sent == [], "the skip path must issue no request"
    assert "q=" not in page.url


def test_a_MUTATION_while_filtered_discards_the_stash(page, live_server):
    """Step 7's `if (appliedQ) preFilterOpen = null;`, which would otherwise
    ship with nothing able to redden it.

    The two behaviours are cleanly separable here. Load with only `part` open,
    filter (chains open `chap` too), then RENAME through the submit handler --
    a real mutation under an active filter -- and clear:
      * WITH the discard: preFilterOpen is null, so the clear falls back to
        collectOpen() over the current tree and `chap` stays open.
      * WITHOUT it: the clear replays the stashed pre-filter enumeration and
        `chap` collapses, silently undoing the expansion the filter produced
        around the row the author just edited.
    """
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open={part.pk}")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')  # the chain opened
    row = page.locator(f'li[data-node="{hit.pk}"] input.tree__title')
    row.fill("Trygonometria II")
    # The rename is a real network mutation, so wait for it to LAND. The 400 ms
    # sleep this replaces was a guess, and on a loaded machine the clear below
    # raced it -- the mutation had not happened yet, so there was no stash to
    # discard and the test failed for a reason it does not describe.
    with page.expect_response(lambda r: "/node/rename/" in r.url and r.status == 200):
        row.press("Enter")

    # The clear re-fetches the whole tree and re-paints it. `data-busy` goes on at
    # issue and comes off only AFTER the fragment has painted (builder.js busyEnd
    # via afterPaint), so its removal is the happens-after this assertion needs.
    #
    # Waiting on chap's scope instead would be VACUOUS: it is already on the page,
    # and the bug being guarded REMOVES it. There is no DOM condition that becomes
    # true on success here -- success is the absence of a change -- which is
    # precisely when you need a happens-after barrier rather than a state wait.
    with page.expect_response(
        lambda r: "/build/tree/" in r.url and "q=" not in r.url and r.status == 200
    ):
        page.click("[data-filter-clear]")
    page.wait_for_selector("[data-busy]", state="detached")

    assert page.locator(f'ol[data-scope="{chap.pk}"]').count() == 1, (
        "the clear replayed a stash the mutation should have discarded"
    )


def test_clear_restores_the_pre_filter_expansion(page, live_server):
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open={part.pk}")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')  # the chain opened
    page.click("[data-filter-clear]")
    # `part`'s scope is open in BOTH states, so waiting on it is satisfied by
    # the still-filtered markup and the assertion then races the response.
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]', state="detached")
    assert page.locator(f'ol[data-scope="{part.pk}"]').count() == 1


def test_collapse_everything_filter_clear_comes_back_EMPTY(page, live_server):
    """The stash === null rule: a legitimately empty pre-filter set stashes as
    "", and `if (!stash)` misreads it as absent."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'li[data-node="{hit.pk}"]')
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    assert (
        page.locator('ol.tree__scope[data-scope]:not([data-scope="top"])').count() == 0
    )


def test_clicking_the_clear_control_hides_it(page, live_server):
    """box.value = "" fires NO input event, so a visibility rule living only
    in that handler never runs on this path. Emptying by TYPING passes
    regardless, which is why this row clicks the control."""
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    assert page.locator("[data-filter-clear]").is_visible()
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    assert not page.locator("[data-filter-clear]").is_visible()


def test_a_clear_is_not_overwritten_by_an_in_flight_filter_response(page, live_server):
    """ONE generation counter across every data-tree-url request. With a
    counter per path the released filter response repaints filtered markup
    over an empty input."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")

    held = []

    def handler(route):
        if "q=trygo" in route.request.url and not held:
            held.append(route)  # hold the FILTER response
        else:
            route.continue_()

    page.route("**/build/tree/**", handler)

    page.fill("#builder-q", "trygo")
    page.wait_for_timeout(400)
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    held[0].continue_()  # release it late
    page.wait_for_timeout(400)

    assert page.locator(f'li[data-node="{miss.pk}"]').count() == 1
    assert page.locator('[data-info-key="filter"]').count() == 0
    assert "q=" not in page.url


def test_a_fragment_borne_notice_lands_on_a_page_that_had_none(page, live_server):
    """Without the always-present slot the JS has nowhere to insert, and the
    throw is swallowed by the .catch and mislabelled 'Network error' while the
    tree still updates -- so no other row notices."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector('[data-info-key="filter"]')


def test_the_info_slot_replaces_by_key(page, live_server):
    """From a ?q= PAGE LOAD, or the test passes vacuously: the registry bug is
    that the JS knows only about entries it inserted itself."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.fill("#builder-q", "trygono")
    page.wait_for_timeout(500)
    page.fill("#builder-q", "trygonom")
    page.wait_for_timeout(500)
    assert page.locator('[data-info-key="filter"]').count() == 1


def test_an_absent_header_does_NOT_clear_the_slot(page, live_server):
    """A rename 200 is _rename_result.html and carries no header. The
    server-side row proves only that it is absent; this proves the client
    IGNORES an absent header rather than clearing on it."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.wait_for_selector('[data-info-key="filter"]')
    row = page.locator(f'li[data-node="{hit.pk}"] input.tree__title')
    row.fill("Trygonometria II")
    row.press("Enter")
    page.wait_for_timeout(400)
    assert page.locator('[data-info-key="filter"]').count() == 1


def test_clearing_the_filter_removes_the_filter_entry(page, live_server):
    """The ONLY path on which `none` does any work."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.wait_for_selector('[data-info-key="filter"]')
    page.click("[data-filter-clear]")
    page.wait_for_timeout(500)
    assert page.locator('[data-info-key="filter"]').count() == 0


def test_a_REFINE_that_drops_below_the_ceiling_removes_the_truncation_entry(
    page, live_server, monkeypatch
):
    """The case `none` cannot express, in the ONLY direction that is reachable.

    NOT the clear path. A clear sends `open=<preFilterOpen or collectOpen()>`,
    both DOM-derived enumerations of scopes a previous _finalize already
    capped at <= CEILING -- so `len(kept) > CEILING` is False and a clear
    response can never be truncated. Its header is `none`, and
    replaceChildren() already covers that. Building this row on a clear makes
    it red against a CORRECT implementation.

    The reachable direction is a REFINE: the slot holds truncation + filter,
    and a narrower query resolves to a chain set that FITS under the ceiling,
    so the response carries `filter` with no `truncation`. Without the removal
    loop the stale truncation entry survives.

    CEILING=2 with three containers: "trygo" matches both units, so the chains
    are {part, c1, c2} = 3 > 2 and the load truncates. "trygonometria d"
    matches only the second, so the chains are {part, c2} = 2 and it does not.
    Both folds verified by substring, not by eye.
    """
    monkeypatch.setattr("courses.builder_open.CEILING", 2)
    owner = _make_pa_user("pa")
    course = CourseFactory(slug="e2etr", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=None, title="Czesc"
    )
    c1 = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial I"
    )
    c2 = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, title="Rozdzial II"
    )
    ContentNodeFactory(course=course, kind="unit", parent=c1, title="Trygonometria")
    ContentNodeFactory(
        course=course, kind="unit", parent=c2, title="Trygonometria dodatkowa"
    )
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=trygo")
    page.wait_for_selector('[data-info-key="truncation"]')
    assert page.locator('[data-info-key="filter"]').count() == 1
    page.fill("#builder-q", "trygonometria d")
    page.wait_for_selector('[data-info-key="truncation"]', state="detached")
    assert page.locator('[data-info-key="filter"]').count() == 1


def test_the_empty_info_slot_is_not_rendered(page, live_server):
    """Both at load AND after a filter -> clear cycle: the second catches the
    JS leaving a whitespace text node, which makes the sunken bar permanent."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    assert page.evaluate("document.querySelector('.builder__info').matches(':empty')")
    page.fill("#builder-q", "trygo")
    page.wait_for_selector('[data-info-key="filter"]')
    page.click("[data-filter-clear]")
    page.wait_for_timeout(500)
    assert page.evaluate("document.querySelector('.builder__info').matches(':empty')")


def test_expand_all_then_collapse_all(page, live_server):
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    page.click("[data-expand-all]")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')
    page.click("[data-collapse-all]")
    page.wait_for_timeout(300)
    assert (
        page.locator('ol.tree__scope[data-scope]:not([data-scope="top"])').count() == 0
    )
    assert "open=" in page.url


def test_collapse_all_does_not_navigate(page, live_server):
    """It is an <a href>. After a navigation the server renders the same
    collapsed toggles and the same open= in the address bar, so every other
    collapse-all assertion passes through the bug."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    stamp(page)
    page.click("[data-collapse-all]")
    page.wait_for_timeout(300)
    assert_no_navigation(page)


def test_collapse_all_resets_aria_on_every_toggle(page, live_server):
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    page.click("[data-collapse-all]")
    page.wait_for_timeout(300)
    for t in page.locator("[data-toggle]").all():
        assert t.get_attribute("aria-expanded") == "false"
        assert t.get_attribute("aria-controls") is None


def test_collapse_all_over_a_dirty_rename_posts_nothing(page, live_server):
    """A REAL MOUSE CLICK, not keyboard activation: a click moves focus at
    mousedown, so the dirty title's focusout fires BEFORE the click handler,
    when `swapping` is still false and isConnected is still true -- and
    commitRename fires a real POST whose applyRename then no-ops on a detached
    form. DB holds the new title, tree shows the old, nothing is reported.
    The keyboard path was already correct."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=all")
    posted = []
    page.on("request", lambda r: posted.append(r.url) if r.method == "POST" else None)
    page.locator(f'li[data-node="{hit.pk}"] input.tree__title').fill("Brudny tytul")
    stamp(page)
    page.mouse.click(*_center(page.locator("[data-collapse-all]")))
    page.wait_for_timeout(400)
    assert_no_navigation(page)  # renames are JS-driven; a dead JS path would
    # navigate here, post nothing (correctly, but for the wrong reason), and
    # pass the assertion below vacuously.
    assert not [u for u in posted if "rename" in u]


def test_expand_all_fires_a_request_UNDER_the_ceiling(page, live_server):
    """The under-ceiling half catches a data-expand-all-disabled emitted BY
    VALUE: "False" is truthy in JS, so the bail fires on every course and the
    control is silently dead everywhere."""
    owner = _make_pa_user("pa")
    course, part, chap, hit = _seed_deep(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?open=")
    sent = []
    page.on(
        "request", lambda r: sent.append(r.url) if "/build/tree/" in r.url else None
    )
    page.click("[data-expand-all]")
    page.wait_for_selector(f'ol[data-scope="{chap.pk}"]')
    assert sent


def test_the_bulk_hrefs_stay_current_after_a_js_filter_apply(page, live_server):
    """They sit in the header, OUTSIDE every fragment applyFragment swaps, so
    nothing else refreshes them -- and a middle-click on a stale one opens an
    unfiltered open=all render."""
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    page.fill("#builder-q", "trygo")
    # Same trap: `hit` is already rendered at load on an under-threshold
    # fixture, and rewriteBulkHrefs only runs in the RESPONSE handler ~300 ms
    # later -- so a no-op wait reads the server-rendered href.
    page.wait_for_selector(f'li[data-node="{miss.pk}"]', state="detached")
    href = page.locator("[data-expand-all]").get_attribute("href")
    assert "q=trygo" in href


def test_an_over_ceiling_expand_all_never_grows_an_href(page, live_server, monkeypatch):
    """The `if (!href) return;` guard, as a runnable row rather than a hand
    check. Over the ceiling the server omits the href on purpose; without the
    guard `new URL(null, origin)` yields "/null" and rewriteBulkHrefs turns a
    deliberately inert control into a live link to a 404.

    Collapse-all is the control group: it always has an href, so it proves the
    rewrite still ran and this row is not passing because nothing happened.

    BARRIER NOTE, measured rather than copied. Do NOT reuse the neighbouring
    row's `li[data-node=miss]` + state="detached" wait: under CEILING=0
    `_finalize` truncates the resolved set to EMPTY, so the page loads with the
    chapter COLLAPSED and that <li> is never in the DOM. `state="detached"`
    resolves instantly on a selector that never existed, and the assertions
    would then run inside the 300 ms debounce, before any fetch — reading the
    server-rendered href and failing. Wait on the `filter` info entry instead:
    at load the slot holds only a `truncation` entry (no `q` in the URL), so
    the `filter` entry is a true happens-after signal for the response.
    """
    monkeypatch.setattr("courses.builder_open.CEILING", 0)
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")
    expand = page.locator("[data-expand-all]")
    assert expand.get_attribute("href") is None, (
        "the server rendered an href over the ceiling; the row proves nothing"
    )
    assert page.locator('[data-info-key="filter"]').count() == 0
    page.fill("#builder-q", "trygo")
    page.wait_for_selector('[data-info-key="filter"]')  # the response landed
    assert expand.get_attribute("href") is None
    assert "q=trygo" in page.locator("[data-collapse-all]").get_attribute("href")


def test_the_bulk_hrefs_are_scrubbed_when_a_below_floor_q_is_cleared(page, live_server):
    """The href half Task 11 deferred to here, now that rewriteBulkHrefs has a
    real body. This is the SKIP path -- no request, no response handler -- so
    the rewrite happens only because applyFilterState calls it inline. The
    server rendered `q=a` into this href, so a no-op leaves it there and a
    middle-click reopens a filter the author cleared.
    """
    owner = _make_pa_user("pa")
    course, chap, hit = _seed_flat(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}?q=a&open=all")
    assert "q=a" in page.locator("[data-expand-all]").get_attribute("href"), (
        "the server did not render q into the href; the row proves nothing"
    )
    page.click("[data-filter-clear]")
    page.wait_for_timeout(400)
    for hook in ("[data-expand-all]", "[data-collapse-all]"):
        assert "q=" not in page.locator(hook).get_attribute("href"), hook


def test_an_in_flight_expand_all_does_not_repaint_over_a_later_filter(
    page, live_server
):
    """The forward obligation Task 11's review left open, made runnable.

    `treeGen` is ONE counter for EVERY data-tree-url request, and the comment
    that says so was written before expand-all existed -- so nothing until now
    could redden an expand-all that fetches without taking a generation. The
    interleaving: click Expand all, type a filter while it is in flight, and
    the expand-all response lands LAST and repaints the fully-expanded,
    unfiltered tree over the filtered one, clears the filter info entry and
    strips ?q= from the address bar.

    Held by `open=all`, which only the expand-all fetch carries: the filter
    fetch deliberately sends no `open` at all.
    """
    owner = _make_pa_user("pa")
    course, chap, hit, miss = _seed_two(owner)
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}{_builder(course)}")

    # BARRIER NOTE, measured rather than copied. The wait below for `miss` to
    # reach state="detached" is only a happens-after signal for the filter
    # response if `miss` was actually rendered at load. On a fixture where it
    # never renders, that wait resolves INSTANTLY, the held response is
    # released before the 300 ms debounce even fires, the two responses land
    # in the benign order, and this row would pass even with the guard
    # removed.
    assert page.locator(f'li[data-node="{miss.pk}"]').count() == 1

    held = []

    def handler(route):
        if "open=all" in route.request.url and not held:
            held.append(route)  # hold the EXPAND-ALL response
        else:
            route.continue_()

    page.route("**/build/tree/**", handler)

    page.click("[data-expand-all]")
    page.wait_for_timeout(400)
    assert held, "expand-all issued no request; the row proves nothing"
    page.fill("#builder-q", "trygo")
    page.wait_for_selector(f'li[data-node="{miss.pk}"]', state="detached")

    # A sleep after continue_() only samples whether the stale response has
    # landed; expect_response is a real happens-after signal that it has.
    with page.expect_response(lambda r: "open=all" in r.url):
        held[0].continue_()  # release it late

    assert page.locator(f'li[data-node="{miss.pk}"]').count() == 0
    assert page.locator('[data-info-key="filter"]').count() == 1
    assert "q=trygo" in page.url
