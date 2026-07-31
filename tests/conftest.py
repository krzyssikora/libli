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

    ORDERING IS THE WHOLE TRICK, and it is why this reaches for `transactional_db`
    the same way pytest-django's own `_live_server_helper` does:
      - requesting `transactional_db` here makes it set up BEFORE this fixture, so
        this finalizer runs BEFORE the flush -- which is the entire point;
      - `page` is NOT autouse, so it is set up after this fixture and torn down
        before it, meaning the browser is already closed (and the `pagehide` POST
        already emitted) by the time the barrier starts polling.
    Depend on neither and the barrier runs at the wrong moment and protects nothing.
    """
    if "live_server" not in request.fixturenames:
        yield
        return
    request.getfixturevalue("transactional_db")
    yield
    from tests.db_quiesce import wait_for_db_quiescence

    # Deliberately not asserted. A timeout means a request outlived the window, which
    # is worth neither failing a passing test over nor hiding: the deadlock it guards
    # against is itself only an intermittent teardown error, and turning that into a
    # hard failure would be a worse trade than the one we are fixing.
    wait_for_db_quiescence()
