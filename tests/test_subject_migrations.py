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


def test_fk_subject_lands_in_m2m():
    old_apps = _migrate("0024_subject_localize_title")
    Subject = old_apps.get_model(APP, "Subject")
    Course = old_apps.get_model(APP, "Course")
    s = Subject.objects.create(title_en="Physics", slug="phys-mig")
    c = Course.objects.create(title="Mechanics", slug="mech-mig", subject=s)

    new_apps = _migrate("0025_course_subjects_m2m")
    NewCourse = new_apps.get_model(APP, "Course")
    pks = list(NewCourse.objects.get(pk=c.pk).subjects.values_list("pk", flat=True))
    assert pks == [s.pk]

    _migrate("0025_course_subjects_m2m")
