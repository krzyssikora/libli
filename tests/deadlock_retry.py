"""Retry a database teardown that lost a deadlock to a stray live_server request.

WHY A RETRY AND NOT PREVENTION. tests/conftest.py takes the browser offline and waits
for the test database to go quiet before teardown truncates, and that is worth doing --
but it cannot be made airtight. A live_server thread that has ACCEPTED a request but
not yet issued its first query sits in pg_stat_activity as plain `idle`, which is
byte-for-byte indistinguishable from the harmless pooled connection present on every
worker. Treating `idle` as busy would time out on every test; treating it as free lets
that thread issue its query straight into the TRUNCATE's AccessExclusiveLock.

MEASURED across three attempts at prevention: 4 -> 1 teardown errors, then still 1,
then still failing with the barrier reporting a quiet database and no timeout warning.
The truncation is idempotent and the loser of a deadlock is simply told to try again,
so recovery is reachable where prevention is not.
"""

import time

DEADLOCK_SQLSTATE = "40P01"

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = 0.25


def is_deadlock(exc):
    """True if `exc`, or anything it was raised from, is a Postgres deadlock.

    Walks the cause/context chain because the deadlock arrives wrapped twice over:
    psycopg raises DeadlockDetected, Django re-raises it as OperationalError, and the
    `flush` management command re-raises THAT as CommandError("Database ... couldn't
    be flushed"). Only the innermost link carries the SQLSTATE.

    Keys on SQLSTATE rather than the message on purpose: this server answers in
    Polish ("wykryto zakleszczenie"), so any message match would be a locale bug
    waiting to happen.
    """
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "sqlstate", None) == DEADLOCK_SQLSTATE:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def call_with_deadlock_retry(
    fn, attempts=DEFAULT_ATTEMPTS, backoff=DEFAULT_BACKOFF, before_retry=None
):
    """Call `fn`, retrying only a deadlock, at most `attempts` times.

    Anything that is not a deadlock propagates on the first raise: a retry loop that
    swallowed real teardown failures would hide exactly the breakage the suite exists
    to report.
    """
    last = attempts - 1
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- re-raised unless it is a deadlock
            if not is_deadlock(exc) or attempt == last:
                raise
            if before_retry is not None:
                before_retry(attempt, exc)
            # Linear, not exponential: the competing request is a single short HTTP
            # call, so the thing being waited out is milliseconds long. Backing off
            # exponentially would just idle the suite.
            time.sleep(backoff * (attempt + 1))
    raise AssertionError("unreachable")  # pragma: no cover
