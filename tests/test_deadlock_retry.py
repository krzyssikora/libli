"""The teardown deadlock retry. See tests/deadlock_retry.py for why it exists."""

import psycopg
import pytest
from django.core.management.base import CommandError
from django.db.utils import OperationalError

from tests.deadlock_retry import call_with_deadlock_retry
from tests.deadlock_retry import is_deadlock


def _real_shaped_deadlock():
    """The exact three-layer shape the suite actually raises.

    Built by RAISING rather than by constructing, so `__cause__` is wired the way
    Python wires it -- a hand-assembled chain could pass while the real one fails.
    """
    try:
        try:
            try:
                raise psycopg.errors.DeadlockDetected("wykryto zakleszczenie")
            except psycopg.errors.DeadlockDetected as inner:
                raise OperationalError("wykryto zakleszczenie") from inner
        except OperationalError as mid:
            raise CommandError("Database test_x couldn't be flushed.") from mid
    except CommandError as outer:
        return outer


def test_the_real_three_layer_deadlock_is_recognised():
    assert is_deadlock(_real_shaped_deadlock()) is True


def test_a_bare_deadlock_is_recognised():
    assert is_deadlock(psycopg.errors.DeadlockDetected("boom")) is True


def test_an_unrelated_database_error_is_not_a_deadlock():
    """A lock TIMEOUT is not a deadlock: retrying it would just wait again."""
    assert is_deadlock(psycopg.errors.QueryCanceled("statement timeout")) is False
    assert is_deadlock(OperationalError("connection lost")) is False
    assert is_deadlock(ValueError("nothing to do with the database")) is False


def test_is_deadlock_terminates_on_a_self_referential_chain():
    """A cause cycle must not hang the suite it is meant to protect."""
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert is_deadlock(a) is False


def test_a_deadlocked_teardown_is_retried_and_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise _real_shaped_deadlock()
        return "flushed"

    assert call_with_deadlock_retry(flaky, backoff=0.01) == "flushed"
    assert len(calls) == 2, "it did not retry"


def test_a_non_deadlock_failure_is_raised_immediately_and_never_retried():
    """The retry must not become a way to hide real teardown breakage."""
    calls = []

    def broken():
        calls.append(1)
        raise CommandError("some other teardown failure")

    with pytest.raises(CommandError, match="some other"):
        call_with_deadlock_retry(broken, backoff=0.01)
    assert len(calls) == 1, "a non-deadlock error was retried"


def test_it_gives_up_after_the_last_attempt_rather_than_looping_forever():
    calls = []

    def always():
        calls.append(1)
        raise _real_shaped_deadlock()

    with pytest.raises(CommandError):
        call_with_deadlock_retry(always, attempts=3, backoff=0.01)
    assert len(calls) == 3, f"expected 3 attempts, made {len(calls)}"


def test_the_retry_hook_runs_between_attempts_so_connections_can_be_reset():
    """The wiring closes the broken connection here; prove the hook is reached."""
    seen = []
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise _real_shaped_deadlock()
        return "ok"

    call_with_deadlock_retry(
        flaky, backoff=0.01, before_retry=lambda attempt, exc: seen.append(attempt)
    )
    assert seen == [0]
