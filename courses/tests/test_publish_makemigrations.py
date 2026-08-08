import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_pending_migrations():
    """MIG2. A local, pre-push copy of the CI gate at ci.yml:53.

    Mutant: drop the AlterField from 0057 -> migration state says
    default=True while models.py says False -> --check detects a pending
    migration and raises SystemExit(1) -> this fails.

    Do NOT replace this with "a new node defaults to draft" (MIG3): that
    assertion is GREEN on the dropped-AlterField mutant, because the
    default comes from models.py either way.

    django_db is required, NOT optional: makemigrations --check calls
    MigrationLoader.check_consistent_history(connection), which queries
    django_migrations. Without the marker, pytest-django's blocker raises
    RuntimeError("Database access not allowed") — the test then fails on a
    CORRECT implementation as well as on the mutant, so it distinguishes
    nothing.
    """
    call_command("makemigrations", "courses", "--check", "--dry-run", verbosity=0)
