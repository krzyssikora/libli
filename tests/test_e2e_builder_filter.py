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
