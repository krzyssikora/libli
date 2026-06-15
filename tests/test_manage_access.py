import pytest
from django.contrib.auth.models import Group

from courses.access import can_manage_course
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from tests.factories import CourseFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_platform_admin_group_holds_course_perms():
    seed_roles()
    pa = Group.objects.get(name=PLATFORM_ADMIN)
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert {"add_course", "change_course", "delete_course", "view_course"} <= codenames


@pytest.mark.django_db
def test_can_manage_course_for_owner():
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    assert can_manage_course(owner, course) is True


@pytest.mark.django_db
def test_can_manage_course_for_platform_admin_non_owner():
    seed_roles()
    pa = UserFactory()
    pa.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    course = CourseFactory(owner=None)
    assert can_manage_course(pa, course) is True


@pytest.mark.django_db
def test_cannot_manage_course_for_unrelated_user():
    user = UserFactory()
    course = CourseFactory(owner=UserFactory())
    assert can_manage_course(user, course) is False


@pytest.mark.django_db
def test_null_owner_does_not_match_random_user():
    user = UserFactory()
    course = CourseFactory(owner=None)
    assert can_manage_course(user, course) is False
