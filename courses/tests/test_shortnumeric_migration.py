"""Migration 0058 conversion tests.

transaction=True is MANDATORY twice over: these tests unapply and re-apply a
migration, which cannot run inside the test's atomic block, AND it leaves the table
EMPTY at test start — which is the only reason the unapply succeeds at all. (The
RemoveField reverse re-adds a non-null DecimalField with no default; that is fine
on an empty table and fails on a populated one.)

The `finally` restore is equally mandatory — a half-restored migration state
poisons every later test on the same xdist worker with failures that land nowhere
near this file.
"""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("courses", "0057_contentnode_published")]
AFTER = [("courses", "0058_shortnumeric_text_value")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor


@pytest.mark.django_db(transaction=True)
def test_0058_strips_trailing_zeros_and_empties_zero_tolerance():
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        Element = old_apps.get_model("courses", "ShortNumericQuestionElement")
        plain = Element.objects.create(
            stem="a", value=Decimal("1.50000000"), tolerance=Decimal("0.10000000")
        )
        zero_tol = Element.objects.create(
            stem="b", value=Decimal("40401.00000000"), tolerance=Decimal("0")
        )
        # The row that catches the str() trap: str(Decimal("0.00000001")) is '1E-8'.
        tiny = Element.objects.create(
            stem="c", value=Decimal("2.00000000"), tolerance=Decimal("0.00000001")
        )

        new_apps = _migrate(AFTER).loader.project_state(AFTER).apps
        New = new_apps.get_model("courses", "ShortNumericQuestionElement")
        got = New.objects.get(pk=plain.pk)
        assert (got.value, got.tolerance) == ("1.5", "0.1")
        got = New.objects.get(pk=zero_tol.pk)
        assert (got.value, got.tolerance) == ("40401", "")
        assert New.objects.get(pk=tiny.pk).tolerance == "0.00000001"
    finally:
        _migrate(AFTER)


@pytest.mark.django_db(transaction=True)
def test_0058_aborts_with_a_named_error_on_a_negative_tolerance():
    # Deliberately NOT named "...before_writing_anything": 0058 is atomic on
    # PostgreSQL, so a partial write would roll back regardless and this test
    # cannot observe the difference. What it does pin is that the operator gets a
    # named RuntimeError naming the rows, not an opaque IntegrityError.
    try:
        old_apps = _migrate(BEFORE).loader.project_state(BEFORE).apps
        Element = old_apps.get_model("courses", "ShortNumericQuestionElement")
        Element.objects.create(
            stem="neg", value=Decimal("1.00000000"), tolerance=Decimal("-0.5")
        )
        # match= on a substring ONLY the counting pass emits. "negative" alone
        # would also match the write-site backstop, making the "delete the
        # counting pass" mutant undetectable.
        with pytest.raises(RuntimeError, match="Repair them before running 0058"):
            _migrate(AFTER)
    finally:
        Element = (
            _migrate(BEFORE)
            .loader.project_state(BEFORE)
            .apps.get_model("courses", "ShortNumericQuestionElement")
        )
        Element.objects.all().delete()
        _migrate(AFTER)


@pytest.mark.django_db(transaction=True)
def test_0058_reverse_fails_when_rows_are_present():
    # NOT an IrreversibleError test — see the migration's docstring for why the
    # reverse is a noop. What is pinned here is the operational protection: with
    # data present, reversing re-adds a non-null DecimalField with no default and
    # the database refuses. django.db.utils.Error deliberately, not a subclass:
    # the exact class is backend-specific and pinning it would test Postgres.
    from django.db.utils import Error

    try:
        _migrate(AFTER)
        New = (
            _migrate(AFTER)
            .loader.project_state(AFTER)
            .apps.get_model("courses", "ShortNumericQuestionElement")
        )
        New.objects.create(stem="x", value="1.5", tolerance="")
        with pytest.raises(Error):
            _migrate(BEFORE)
    finally:
        New = (
            _migrate(AFTER)
            .loader.project_state(AFTER)
            .apps.get_model("courses", "ShortNumericQuestionElement")
        )
        New.objects.all().delete()
        _migrate(AFTER)
