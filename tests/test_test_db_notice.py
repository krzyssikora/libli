"""The notice that nudges developers onto the tuned test database."""

import pytest

from conftest import TEST_DB_NOTICE
from conftest import _markexpr_selects_e2e
from conftest import _should_emit_test_db_notice

BASE = {"has_e2e_items": True, "env": {}}
TUNED = "postgres://libli@127.0.0.1:55433/libli"


def _emit(**overrides):
    return _should_emit_test_db_notice(**{**BASE, **overrides})


def test_emits_for_an_e2e_run_with_no_test_database_configured():
    assert _emit() is True


def test_silent_on_a_unit_only_run():
    assert _emit(has_e2e_items=False) is False


def test_silent_when_the_test_database_is_already_configured():
    # Bound to a constant deliberately: inline, this line is 94 chars against
    # ruff's default line-length of 88, so `ruff check` (E501) and
    # `ruff format --check` both fail -- as would CI's `ruff check .`.
    assert _emit(env={"TEST_DATABASE_URL": TUNED}) is False


def test_silent_under_ci():
    # CI sets DATABASE_URL but not TEST_DATABASE_URL, so it would otherwise
    # print on every run, advising a container CI neither has nor needs.
    assert _emit(env={"CI": "true"}) is False


def test_silent_under_github_actions():
    assert _emit(env={"GITHUB_ACTIONS": "true"}) is False


def test_silent_when_opted_out():
    assert _emit(env={"LIBLI_NO_TEST_DB_NOTICE": "1"}) is False


def test_the_notice_names_the_command_and_the_opt_out():
    assert "docker compose -p libli-test" in TEST_DB_NOTICE
    assert "LIBLI_NO_TEST_DB_NOTICE" in TEST_DB_NOTICE


@pytest.mark.parametrize(
    "markexpr,selects",
    [
        ("e2e", True),
        (" e2e ", True),
        # The default addopts value. `"e2e" in "not e2e"` is True, so a
        # substring test would fire the pre-run notice on every unit run.
        ("not e2e", False),
        ("", False),
        (None, False),
    ],
)
def test_markexpr_selection(markexpr, selects):
    assert _markexpr_selects_e2e(markexpr) is selects
