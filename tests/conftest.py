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

    ORDERING IS THE WHOLE TRICK, and it is why this reaches for its dependencies the
    same way pytest-django's own `_live_server_helper` does:
      - requesting `transactional_db` makes it set up BEFORE this fixture, so this
        finalizer runs BEFORE the flush -- which is the entire point. VERIFIED, not
        assumed: probing `ContentNode.objects.count()` here returns 1, so the tables
        are still populated when the barrier runs;
      - requesting `page` makes the browser set up before this fixture too, so the
        page is still OPEN in this finalizer and is torn down after it.

    WAITING ALONE IS NOT ENOUGH, and a first attempt that only waited proved it:
    the full e2e suite went from 4 teardown errors to 1, not 0. A barrier can only
    wait for a request that has ARRIVED, and the delay between `page.close()` and a
    `keepalive` request reaching the server is unbounded -- so a late enough one
    still slips in behind the barrier and deadlocks the flush.

    So do not wait for the POST to happen at some unknown moment; MAKE it happen at
    a known one. Navigating to `about:blank` fires `pagehide` synchronously, which
    flushes progress.js's queue right here, and the blank page that replaces it has
    no progress.js left to fire anything else. Only then is waiting meaningful.
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
            page.goto("about:blank")
        except Exception as exc:  # noqa: BLE001 -- teardown must not raise
            # A test may legitimately have closed or crashed the page itself. That is
            # not a failure of the test, and the barrier below is still worth running,
            # so report and carry on rather than turning a green test red.
            warnings.warn(
                f"could not blank the page at teardown: {exc!r}", stacklevel=1
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
