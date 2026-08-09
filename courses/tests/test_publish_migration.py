import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from courses.models import ContentNode

BEFORE = ("courses", "0056_alter_calloutelement_kind")
AFTER = ("courses", "0057_contentnode_published")


@pytest.mark.django_db(transaction=True)
def test_existing_nodes_land_published():
    """MIG1. Rows that existed before 0057 must arrive published=True.

    Mutant: collapse the two operations into AddField(default=False) ->
    every pre-existing row is a draft -> this fails.

    transaction=True is MANDATORY: this test unapplies a migration and
    re-applies it, which cannot happen inside pytest-django's per-test
    atomic block. The `finally` restore is equally mandatory — under
    `-n auto` with a reused database (this repo's CI), a half-restored
    migration state poisons every subsequent test on that worker, and the
    failures land nowhere near this file.

    If you see unrelated tests failing with "no such column" or
    "relation does not exist" after running this, the restore did not run.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([BEFORE])
        executor.loader.build_graph()

        old_apps = executor.loader.project_state([BEFORE]).apps
        Course = old_apps.get_model("courses", "Course")
        Node = old_apps.get_model("courses", "ContentNode")
        course = Course.objects.create(title="Legacy", slug="legacy")
        Node.objects.create(course=course, kind="part", title="Part", order=0)

        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])

        assert ContentNode.objects.filter(published=False).count() == 0
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db
def test_new_node_defaults_to_draft():
    """MIG3. models.py's declared default, not the AlterField."""
    node = ContentNode(kind="part", title="X")
    assert node.published is False
