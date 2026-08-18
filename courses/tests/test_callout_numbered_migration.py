import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("courses", "0059_mediaasset_derivatives")   # <-- the new migration's dependency
AFTER = ("courses", "0060_calloutelement_numbered")   # <-- the new migration


@pytest.mark.django_db(transaction=True)
def test_backfill_unnumbers_note_and_tip_only():
    """Mutant: drop the RunPython (or make it set every row True) -> the note and tip
    rows arrive numbered.

    transaction=True is MANDATORY: this unapplies and re-applies a migration, which
    cannot happen inside pytest-django's per-test atomic block. The `finally` restore
    targets graph HEAD, not AFTER -- a restore pinned to a node that a later migration
    supersedes runs BACKWARDS and poisons every later test on the worker.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([BEFORE])
        executor.loader.build_graph()

        old_apps = executor.loader.project_state([BEFORE]).apps
        Callout = old_apps.get_model("courses", "CalloutElement")
        for kind in ("example", "task", "warning", "note", "tip"):
            Callout.objects.create(kind=kind, heading="", body="")

        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])

        new_apps = MigrationExecutor(connection).loader.project_state([AFTER]).apps
        Callout = new_apps.get_model("courses", "CalloutElement")
        by_kind = {c.kind: c.numbered for c in Callout.objects.all()}
        assert by_kind == {
            "example": True,
            "task": True,
            "warning": True,
            "note": False,
            "tip": False,
        }
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
