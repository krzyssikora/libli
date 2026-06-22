import pytest
from django.contrib.auth.models import Group

from institution.roles import seed_roles

pytestmark = pytest.mark.django_db


def _codenames(role_name):
    seed_roles()
    g = Group.objects.get(name=role_name)
    return set(g.permissions.values_list("codename", flat=True))


def test_teacher_gets_group_view_and_collection_crud():
    cn = _codenames("Teacher")
    assert "view_group" in cn
    assert {
        "add_collection",
        "change_collection",
        "delete_collection",
        "view_collection",
    } <= cn
    assert "add_group" not in cn  # teachers don't author groups


def test_course_admin_gets_group_crud_and_cohort_view():
    cn = _codenames("Course Admin")
    assert {"add_group", "change_group", "delete_group", "view_group"} <= cn
    assert "view_cohort" in cn
    assert "add_cohort" not in cn  # cohorts are PA-managed


def test_platform_admin_gets_all_grouping_perms():
    cn = _codenames("Platform Admin")
    assert {"add_cohort", "change_cohort", "delete_cohort", "view_cohort"} <= cn
    assert {"add_group", "change_group", "delete_group", "view_group"} <= cn
    assert {
        "add_collection",
        "change_collection",
        "delete_collection",
        "view_collection",
    } <= cn


def test_seed_roles_idempotent_for_grouping():
    seed_roles()
    seed_roles()
    teacher = Group.objects.get(name="Teacher")
    assert teacher.permissions.filter(codename="view_group").count() == 1
