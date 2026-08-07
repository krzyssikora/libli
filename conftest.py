"""Project-wide pytest fixtures.

Kept minimal: this root conftest exists so an autouse fixture can cover EVERY
test directory (tests/, courses/tests/, notifications/tests/, ...). Directory
conftests (e.g. tests/conftest.py) only apply to their own subtree, which is
too narrow for cross-cutting test-isolation concerns like the one below.
"""

import os
from collections.abc import Mapping

import pytest
from django.conf import settings
from django.utils import translation


@pytest.fixture(autouse=True)
def _reset_active_language():
    """Pin the active translation to the default language around every test.

    Some tests issue ``client.get(..., HTTP_ACCEPT_LANGUAGE="pl")``. Django's
    LocaleMiddleware activates ``pl`` for that request but does NOT deactivate it
    afterwards, so ``pl`` stays active in the worker's thread and leaks into
    whatever test runs next on that worker. Victims are any test that asserts
    against gettext output in the default language (e.g. the transfer-validation
    tests, which check English error text). This was latent until CI moved to
    xdist (``-n auto`` / ``-n 2``), which makes "which test runs before which on a
    worker" nondeterministic — turning the leak into a flaky failure.

    Activating the default before each test guarantees a clean starting locale
    regardless of order or parallelism; deactivating after keeps a leaking test
    from polluting the next one. Tests that need another language still use
    ``translation.override(...)`` or ``HTTP_ACCEPT_LANGUAGE`` locally — those are
    unaffected because they set the language *within* the test.
    """
    translation.activate(settings.LANGUAGE_CODE)
    yield
    translation.deactivate_all()


TEST_DB_NOTICE = (
    "tip: e2e teardown TRUNCATEs 89 tables after each test. Running against the "
    "disposable tuned database makes that ~37x cheaper:\n"
    "       docker compose -p libli-test -f docker-compose.test.yml up -d --wait\n"
    "     then uncomment TEST_DATABASE_URL in your .env. "
    "Silence this with LIBLI_NO_TEST_DB_NOTICE=1."
)


def _should_emit_test_db_notice(*, has_e2e_items: bool, env: Mapping[str, str]) -> bool:
    """Whether to print TEST_DB_NOTICE. Pure, so every branch is unit-testable."""
    if not has_e2e_items:
        return False
    if env.get("TEST_DATABASE_URL"):
        return False
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        return False
    if env.get("LIBLI_NO_TEST_DB_NOTICE"):
        return False
    return True


def _markexpr_selects_e2e(markexpr: str) -> bool:
    """Whether `-m <markexpr>` selects e2e tests. Substring matching is WRONG here.

    MEASURED: the default `addopts` sets markexpr to "not e2e", and
    `"e2e" in "not e2e"` is True -- so a substring test fires the notice on every
    unit run. Deliberately conservative: only the exact `-m e2e` form counts.
    Anything subtler (`-k`, a nodeid, a compound expression) falls through to
    `pytest_terminal_summary`, which decides from the reports themselves.
    """
    return (markexpr or "").strip() == "e2e"


def pytest_sessionstart(session):
    """Pre-run nudge, so an e2e run can still be saved rather than merely mourned.

    `pytest_sessionstart`, NOT `pytest_configure`: MEASURED, the terminal reporter
    is not yet registered when a rootdir conftest's `pytest_configure` runs (that
    hook is dispatched LIFO and the builtin terminal plugin registers after the
    conftest), so `get_plugin("terminalreporter")` returns None there and the
    emission is dead code. At sessionstart it is present, on the controller, in
    both single-process and `-n 2`.
    """
    config = session.config
    if hasattr(config, "workerinput"):
        return
    if not _markexpr_selects_e2e(config.option.markexpr):
        return
    if not _should_emit_test_db_notice(has_e2e_items=True, env=os.environ):
        return
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:  # `-p no:terminal` -- degrade rather than crash
        reporter.write_line(TEST_DB_NOTICE, yellow=True)
        config._libli_test_db_notice_shown = True


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Nudge toward the tuned test database when an e2e run is not using it.

    `pytest_terminal_summary`, NOT `pytest_collection_finish`: under xdist the
    controller never calls `perform_collect` (dsession returns True from the
    firstresult `pytest_collection` hook), so a collection hook fires in workers
    only. This one fires exactly once, on the controller, in both modes.

    A terminal-reporter line, deliberately NOT a `warnings.warn`: node IDs in the
    warnings summary have previously made an unanchored `grep FAILED` report
    failures on a green run.
    """
    has_e2e = any(
        "e2e" in (getattr(report, "keywords", {}) or {})
        # "deselected" MUST be excluded. MEASURED: it holds collected-but-
        # deselected items, whose keywords still carry `e2e` -- and `addopts`
        # deselects all 845 e2e tests on every plain `uv run pytest`. Including
        # it makes the notice fire on every unit run.
        for key, reports in terminalreporter.stats.items()
        if key != "deselected"
        for report in reports
    )
    if getattr(config, "_libli_test_db_notice_shown", False):
        return  # already said it up front; don't say it twice
    if _should_emit_test_db_notice(has_e2e_items=has_e2e, env=os.environ):
        terminalreporter.write_line(TEST_DB_NOTICE, yellow=True)
