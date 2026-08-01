"""The barrier that keeps a late live_server request from deadlocking teardown.

WHY THIS EXISTS. `progress.js` sends its `/seen/` POST with `keepalive: true` and
also on `pagehide` -- it is deliberately engineered to outlive the page (see the
comments in courses/static/courses/js/progress.js). `live_server` is SESSION-scoped,
so its WSGI thread keeps serving after any one test's body ends. So when Playwright
closes the page, that POST lands on the server thread, `seen()` opens a
`transaction.atomic()` and takes row locks -- concurrently with the finishing test's
`transactional_db` finalizer running `TRUNCATE ... CASCADE`, which needs
AccessExclusiveLock on the same tables. Two connections, opposite lock order:
`psycopg.errors.DeadlockDetected`, reported as `ERROR at teardown` and never as a
test failure, on a different set of tests each run.

MEASURED on this repo before the fix: two full e2e runs, 4 teardown errors each,
DISJOINT test sets, every test body passing in both.
"""

import threading
import time

import pytest
from django.db import connections
from django.db import transaction

from tests.db_quiesce import wait_for_db_quiescence

HOLD_TIMEOUT = 10.0


def _hold_transaction(started, release, alias="default"):
    """Occupy a SECOND session with an open transaction that has touched the table.

    Runs in its own thread, so Django hands it its own connection -- which is the
    whole point: one session cannot deadlock with itself.
    """
    conn = connections[alias]
    try:
        with transaction.atomic():
            with conn.cursor() as cur:
                # Touch the table so the transaction actually holds a lock on it,
                # rather than merely being open. A transaction that has read nothing
                # blocks no TRUNCATE.
                cur.execute("SELECT count(*) FROM courses_unitprogress")
            started.set()
            release.wait(timeout=HOLD_TIMEOUT)
    finally:
        conn.close()


@pytest.fixture
def other_session():
    """Start a second session holding a transaction; release it on teardown."""
    started, release = threading.Event(), threading.Event()
    t = threading.Thread(target=_hold_transaction, args=(started, release), daemon=True)
    t.start()
    assert started.wait(timeout=5), "the holder thread never opened its transaction"
    yield release
    release.set()
    t.join(timeout=HOLD_TIMEOUT)


@pytest.mark.django_db(transaction=True)
def test_a_concurrent_transaction_blocks_the_truncate_teardown_runs(other_session):
    """The hazard itself: this is what deadlocks teardown in the real suite.

    Proven by BLOCKING rather than by racing to a genuine deadlock cycle: a lock
    wait is deterministic, a deadlock is not. `statement_timeout` turns the wait
    into an assertable outcome instead of a hang.
    """
    conn = connections["default"]
    with conn.cursor() as cur:
        # `SET`, not `SET LOCAL`. MEASURED: Django runs these tests in autocommit, so
        # there is no surrounding transaction block for LOCAL to be local to -- it is
        # silently a no-op, the TRUNCATE then blocks for the holder's full lifetime and
        # the test passes for the wrong reason. Reset in `finally` because the
        # connection outlives this test.
        cur.execute("SET statement_timeout = '400ms'")
        try:
            with pytest.raises(Exception) as exc:
                cur.execute("TRUNCATE courses_unitprogress CASCADE")
        finally:
            conn.close()  # the cancelled statement leaves the session unusable

    # psycopg raises QueryCanceled; assert on the message so the test does not depend
    # on which driver-level class surfaces, nor on the server's locale.
    msg = str(exc.value).lower()
    assert "timeout" in msg or "anulowano" in msg or "cancel" in msg, msg


@pytest.mark.django_db(transaction=True)
def test_the_barrier_waits_until_the_other_session_finishes(other_session):
    """The fix: block until the late request's transaction is actually gone."""

    def _release_soon():
        time.sleep(0.6)
        other_session.set()

    threading.Thread(target=_release_soon, daemon=True).start()

    t0 = time.monotonic()
    quiet = wait_for_db_quiescence(timeout=5.0)
    elapsed = time.monotonic() - t0

    assert quiet is True
    # The point of the barrier is that it WAITED. A no-op that returns immediately
    # satisfies `quiet is True` and would leave the deadlock in place, so this
    # assertion -- not the one above -- is what makes the test falsifiable.
    assert elapsed >= 0.5, f"returned in {elapsed:.3f}s; it did not wait"


@pytest.mark.django_db(transaction=True)
def test_the_barrier_gives_up_rather_than_hanging_forever(other_session):
    """A stuck session must not wedge the whole suite: bounded wait, honest answer."""
    t0 = time.monotonic()
    quiet = wait_for_db_quiescence(timeout=0.5)
    elapsed = time.monotonic() - t0

    assert quiet is False
    assert elapsed < 3.0, f"took {elapsed:.3f}s for a 0.5s timeout"


@pytest.mark.django_db(transaction=True)
def test_an_idle_database_is_quiescent_immediately():
    """No other session -> no wait. Guards against a barrier that always sleeps."""
    t0 = time.monotonic()
    quiet = wait_for_db_quiescence(timeout=5.0)
    elapsed = time.monotonic() - t0

    assert quiet is True
    assert elapsed < 0.5, f"idle DB still took {elapsed:.3f}s"


@pytest.mark.django_db(transaction=True)
def test_the_barrier_ignores_sessions_on_OTHER_databases():
    """Scoping matters: xdist gives each worker its own database.

    A barrier that counted every session on the server would wait for the other
    workers' live_servers and time out on every test.
    """
    conn = connections["default"]
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        here = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname IS NOT NULL "
            "AND datname <> %s",
            [here],
        )
        elsewhere = cur.fetchone()[0]

    # Only meaningful when something else IS connected; otherwise it proves nothing.
    if elsewhere == 0:
        pytest.skip("no sessions on other databases to be confused by")
    assert wait_for_db_quiescence(timeout=0.5) is True
