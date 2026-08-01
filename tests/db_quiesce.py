"""Wait for a test database to have no other session mid-transaction.

Used by the autouse fixture in tests/conftest.py to close the window in which a
`keepalive` request emitted by a closing Playwright page deadlocks the finishing
test's `TRUNCATE ... CASCADE`. See tests/test_db_quiesce.py for the mechanism.
"""

import time

from django.db import connections

# Postgres reports a session that is running a statement as 'active', and one that
# has begun a transaction and is between statements as 'idle in transaction'. BOTH
# hold locks, so both must clear -- waiting only for 'active' would let an open
# transaction that is momentarily between statements straight through, which is the
# exact state a request sitting inside `transaction.atomic()` is usually in.
BUSY_STATES = ("active", "idle in transaction", "idle in transaction (aborted)")

DEFAULT_TIMEOUT = 5.0
POLL_INTERVAL = 0.02

# How many consecutive quiet samples count as quiet. TWO, not one, because the request
# we are waiting for may still be in TCP flight when the first sample is taken -- it
# becomes a pg_stat_activity row only once the server thread reaches the database.
# MEASURED on a real e2e teardown: at t+0 there were 3 other sessions (one 'active'
# mid-SELECT, one committing), settling to a single harmless 'idle' connection by
# t+50ms. One sample taken a moment earlier would have seen an idle database and waved
# the TRUNCATE straight into the request it exists to wait for.
SETTLE_SAMPLES = 2

_SQL = """
    SELECT count(*) FROM pg_stat_activity
    WHERE datname = current_database()
      AND pid <> pg_backend_pid()
      AND state = ANY(%s)
"""


def busy_session_count(alias="default"):
    """How many OTHER sessions on THIS database currently hold locks."""
    with connections[alias].cursor() as cur:
        cur.execute(_SQL, [list(BUSY_STATES)])
        return cur.fetchone()[0]


def wait_for_db_quiescence(alias="default", timeout=DEFAULT_TIMEOUT):
    """Block until this database has no other busy session. True if it went quiet.

    Scoped to `current_database()` on purpose: under xdist each worker owns its own
    database, and a server-wide count would make every worker wait for every other
    worker's live_server and time out on every test.

    Returns False on timeout rather than raising. A barrier that raised would turn a
    slow request into a suite failure, which is a worse outcome than the deadlock it
    exists to prevent -- and the caller (a teardown fixture) has nothing useful to do
    with an exception anyway.
    """
    deadline = time.monotonic() + timeout
    quiet_in_a_row = 0
    while True:
        if busy_session_count(alias) == 0:
            quiet_in_a_row += 1
            if quiet_in_a_row >= SETTLE_SAMPLES:
                return True
        else:
            # Not "keep counting up": a session appearing between samples means the
            # window was never really quiet, so the count restarts.
            quiet_in_a_row = 0
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_INTERVAL)
