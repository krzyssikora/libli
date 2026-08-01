import pytest


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
