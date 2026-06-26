import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "courses"
BEFORE = "0023_course_structure_flags"
AFTER = "0024_subject_localize_title"


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


def test_title_is_copied_into_title_en():
    old_apps = _migrate(BEFORE)
    Subject = old_apps.get_model(APP, "Subject")
    s = Subject.objects.create(title="Mathematics", slug="math-mig")

    new_apps = _migrate(AFTER)
    NewSubject = new_apps.get_model(APP, "Subject")
    assert NewSubject.objects.get(pk=s.pk).title_en == "Mathematics"

    # leave the DB migrated forward for the rest of the suite
    _migrate(AFTER)
