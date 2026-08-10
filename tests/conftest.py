import pytest

from tests.helpers_editor_rows import open_element_form
from tests.helpers_editor_rows import reopen

# ---------------------------------------------------------------------------
# Editor row-mechanics fixtures (the roster in the instant-row-add/remove plan).
#
# Every e2e opener has ONE contract: opener(page, live_server, **kwargs) ->
# Element. It logs in, seeds the element, navigates, opens its edit form and
# returns the **Element join row** — never the page, and never the content
# object (the payload lives on `element.content_object`).
# ---------------------------------------------------------------------------


def _pa_user(username):
    """A verified Platform Admin, created directly (not through a test client) so
    an e2e opener can log in through the real allauth form."""
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _editor_login(page, live_server, username):
    """Log in via the allauth HTML form (mirrors tests/test_e2e_questions.py)."""
    from tests.factories import TEST_PASSWORD

    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _editor_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:manage_editor", kwargs={"slug": unit.course.slug, "pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _lettered_pairs(n):
    """n pairs ("a", "1"), ("b", "2"), … — distinct on both sides so an assertion
    can tell which pair survived a remove."""
    return [(chr(ord("a") + i), str(i + 1)) for i in range(n)]


@pytest.fixture
def pa_client(client):
    """A Django test client logged in as a Platform Admin.

    A PA holds `courses.change_course`, so can_manage_course() lets it author any
    course — the seeded course needs no explicit owner.
    """
    from tests.factories import make_pa

    make_pa(client, "pa")
    return client


@pytest.fixture
def matchpair_element():
    """Factory -> (course, unit, element) with `pairs` persisted.

    `element` is the Element JOIN ROW (what the POST's `element` key and
    `form_url` take); the pairs live on `element.content_object.pairs`.
    """

    def _make(pairs=(("France", "Paris"), ("Spain", "Madrid"))):
        from courses.models import MatchPair
        from courses.models import MatchPairQuestionElement
        from tests.factories import ContentNodeFactory
        from tests.factories import CourseFactory
        from tests.factories import add_element

        course = CourseFactory()
        unit = ContentNodeFactory(
            course=course, parent=None, kind="unit", unit_type="lesson"
        )
        question = MatchPairQuestionElement.objects.create(stem="")
        for left, right in pairs:
            MatchPair.objects.create(question=question, left=left, right=right)
        return course, unit, add_element(unit, question)

    return _make


@pytest.fixture
def open_matchpair_editor(pa_client, matchpair_element):
    """Server-render opener: seeds a match-pairs element with `saved_pairs` pairs,
    GETs its edit fragment and returns the HTML."""

    def _open(saved_pairs=2):
        course, _unit, element = matchpair_element(pairs=_lettered_pairs(saved_pairs))
        return open_element_form(pa_client, course, element)

    return _open


@pytest.fixture
def open_matchpair_editor_e2e(matchpair_element):
    """e2e opener: log in a PA, seed the element, open the unit editor and swap its
    edit form into the slot. Returns the Element join row."""

    def _open(page, live_server, saved_pairs=2, username="mp_rows"):
        _pa_user(username)
        _course, unit, element = matchpair_element(pairs=_lettered_pairs(saved_pairs))
        _editor_login(page, live_server, username)
        page.goto(_editor_url(live_server, unit))
        page.wait_for_selector('[data-scope="editor"]')
        reopen(page, element.pk)
        return element

    return _open


def _seed_rows_element(kind, rows):
    """(course, unit, element) for the two retrofitted row editors.

    `kind` is "stepper" or "markdone"; the child rows are created directly through
    the ORM so the element is PRE-SEEDED (the e2e openers rely on that — a
    pre-seeded element already has a preview node, which is why the post-save wait
    targets the edit slot clearing rather than the preview).
    """
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import StepperElement
    from courses.models import StepperStep
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    if kind == "stepper":
        obj = StepperElement.objects.create(prompt="")
        for content in rows:
            StepperStep.objects.create(stepper=obj, content=content)
    elif kind == "markdone":
        obj = MarkDoneElement.objects.create(prompt="")
        for content in rows:
            MarkDoneItem.objects.create(element=obj, content=content)
    else:  # pragma: no cover - a typo'd kind must not silently seed nothing
        raise ValueError(f"unknown row-editor kind {kind!r}")
    return course, unit, add_element(unit, obj)


@pytest.fixture
def open_stepper_editor(pa_client):
    """Server-render opener: seeds a stepper element and returns its edit HTML."""

    def _open(rows=("one",)):
        course, _unit, element = _seed_rows_element("stepper", rows)
        return open_element_form(pa_client, course, element)

    return _open


@pytest.fixture
def open_markdone_editor(pa_client):
    """Server-render opener: seeds a checklist element and returns its edit HTML."""

    def _open(rows=("one",)):
        course, _unit, element = _seed_rows_element("markdone", rows)
        return open_element_form(pa_client, course, element)

    return _open


@pytest.fixture
def open_element_editor():
    """e2e opener for the two retrofitted row editors.

    `kind` is "stepper" or "markdone". Returns the Element JOIN ROW.

    `ready` is passed through to `reopen`: this opener is used by the
    no-regression test that must be GREEN on master too, where the new
    [data-fsrows-list] hook does not exist yet, so the wait keys on the row
    list's CLASS instead.
    """

    def _open(page, live_server, kind, rows=("one",), username="row_editor"):
        _pa_user(username)
        _course, unit, element = _seed_rows_element(kind, rows)
        _editor_login(page, live_server, username)
        page.goto(_editor_url(live_server, unit))
        page.wait_for_selector('[data-scope="editor"]')
        reopen(page, element.pk, ready=f".{kind}-rows li")
        return element

    return _open


@pytest.fixture
def course_with_image(db, tmp_path, settings):
    """A Course plus one real IMAGE MediaAsset with a readable file on disk.

    MEDIA_ROOT is redirected per test: make_image_asset writes a real file, and a
    render asserting on file.url needs it resolvable.
    """
    from tests.factories import make_course
    from tests.factories import make_image_asset

    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    return course, make_image_asset(course, filename="graph.png", size=(1586, 612))


@pytest.fixture(autouse=True)
def _enable_db_access(db):
    """Give every test DB access (small project; convenient default).

    Consequence: every test — including the /healthz smoke test — needs a
    running PostgreSQL. That coupling is intentional for this project."""


@pytest.fixture(autouse=True)
def _clear_site_cache():
    """LocMemCache is not transaction-scoped; clear it around every test so a
    cached site-config (palette / signup_policy / enabled_languages) from one test
    never leaks into the next."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True, scope="session")
def _retry_deadlocked_fixture_teardown():
    """Retry a TRUNCATE that lost a deadlock to a stray live_server request.

    The prevention below (offline browser + quiescence barrier) narrows the window
    but provably cannot close it: a server thread that has accepted a request but
    not yet issued its first query is `idle` in pg_stat_activity, indistinguishable
    from the harmless pooled connection every worker keeps open. So recover instead.

    Patched at the Django level rather than pytest-django's, because the flush is
    reached from `TransactionTestCase._fixture_teardown` however the test asked for
    a transactional database -- the `transactional_db` fixture, the
    `django_db(transaction=True)` marker, or `live_server` pulling it in implicitly.
    """
    import warnings

    from django.db import connections
    from django.test import TransactionTestCase

    from tests.deadlock_retry import call_with_deadlock_retry

    original = TransactionTestCase._fixture_teardown

    def _reset(attempt, exc):
        # The losing side of a deadlock has its transaction aborted, so its
        # connection cannot run the retry. Drop them and let Django reconnect.
        for conn in connections.all():
            conn.close()
        warnings.warn(
            f"teardown TRUNCATE deadlocked (attempt {attempt + 1}); retrying",
            stacklevel=1,
        )

    def patched(self):
        return call_with_deadlock_retry(lambda: original(self), before_retry=_reset)

    TransactionTestCase._fixture_teardown = patched
    yield
    TransactionTestCase._fixture_teardown = original


@pytest.fixture(autouse=True)
def _quiesce_live_server_before_db_teardown(request):
    """Let a late `keepalive` request finish before teardown TRUNCATEs under it.

    `progress.js` sends its `/seen/` POST with `keepalive: true` AND on `pagehide`,
    so the request is deliberately built to outlive the page; `live_server` is
    session-scoped, so its WSGI thread is still serving after the test body ends.
    When Playwright closes the page, that POST lands on the server, `seen()` opens a
    transaction and takes row locks -- while this test's `transactional_db` finalizer
    runs `TRUNCATE ... CASCADE`, which needs AccessExclusiveLock on the same tables.
    Opposite lock order on two connections is a deadlock, and it surfaces as
    `ERROR at teardown` on a different set of tests every run.

    MEASURED at a real e2e teardown: 3 other sessions at t+0, one `active` mid-SELECT
    and one committing, quiet by t+50ms. So the wait is real but short.

    ORDERING IS THE WHOLE TRICK, and it is why this reaches for its dependencies the
    same way pytest-django's own `_live_server_helper` does:
      - requesting `transactional_db` makes it set up BEFORE this fixture, so this
        finalizer runs BEFORE the flush -- which is the entire point. VERIFIED, not
        assumed: probing `ContentNode.objects.count()` here returns 1, so the tables
        are still populated when the barrier runs;
      - requesting `page` makes the browser set up before this fixture too, so the
        page is still OPEN in this finalizer and is torn down after it.

    THREE THINGS ARE NEEDED, and each was added only after the previous one was
    measured to be insufficient on the real suite:

    1. WAITING. A barrier can only wait for a request that has ARRIVED. Waiting
       alone took the suite from 4 teardown errors to 1, not 0.
    2. FIRING THE QUEUE AT A KNOWN MOMENT. The delay between the page closing and a
       `keepalive` request reaching the server is unbounded, so there is no settle
       window that is provably long enough. `page.goto("about:blank")` runs
       `pagehide` synchronously, so the queue is flushed HERE rather than at some
       unknown later point. Still not enough on its own: blanking guarantees the
       request is SENT, not that it has ARRIVED.
    3. TAKING THE BROWSER OFFLINE FIRST. This is what makes it deterministic
       instead of merely likely -- an offline context cannot put anything on the
       wire at all, so there is no in-flight request left to race.

    And it must be ALL requests, not just `/seen/`. MEASURED: five modules post with
    `keepalive: true` -- progress.js, markdone.js, reveal.js, slideshow.js and
    state.js's fire-and-forget `saveFlag` -- which is exactly why the teardown errors
    spanned practice-state, markdone, reveal-gate, slideshow, filltable and
    guessnumber rather than clustering on one feature.

    Going offline is safe here precisely because it happens in TEARDOWN: the test
    body has already finished and asserted. Nothing a test cares about is suppressed.
    """
    if "live_server" not in request.fixturenames:
        yield
        return
    request.getfixturevalue("transactional_db")
    page = request.getfixturevalue("page") if "page" in request.fixturenames else None
    yield
    import warnings

    from tests.db_quiesce import wait_for_db_quiescence

    if page is not None:
        try:
            # Offline BEFORE blanking, so the `pagehide` handlers that fire during the
            # navigation have no wire to put anything on.
            page.context.set_offline(True)
            page.goto("about:blank")
        except Exception as exc:  # noqa: BLE001 -- teardown must not raise
            # A test may legitimately have closed or crashed the page itself. That is
            # not a failure of the test, and the barrier below is still worth running,
            # so report and carry on rather than turning a green test red.
            warnings.warn(
                f"could not quiesce the browser at teardown: {exc!r}", stacklevel=1
            )

    if not wait_for_db_quiescence():
        # Surfaced rather than swallowed: a timeout is the one state in which this
        # fixture knowingly hands a still-busy database to TRUNCATE, so if the
        # deadlock ever comes back, the warnings summary says whether the barrier
        # gave up (this warning present) or was outrun (absent).
        warnings.warn(
            f"live_server still busy at teardown of {request.node.nodeid}; "
            "the flush may deadlock",
            stacklevel=1,
        )
