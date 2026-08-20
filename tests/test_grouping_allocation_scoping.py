import pytest

from grouping import scoping
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _role_user(role_name, username):
    from django.contrib.auth.models import Group as AuthGroup

    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    # Same shape as tests/factories.py::_make_role — a freshly created user has
    # never had has_perm() called on it, so these attributes do not exist yet and
    # a bare `del` would AttributeError before any assertion runs.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_platform_admin_sees_every_allocation():
    pa = _role_user(PLATFORM_ADMIN, "pa_scope")
    a = AllocationFactory()
    assert list(scoping.allocations_manageable_by(pa)) == [a]


def test_course_admin_sees_only_allocations_on_owned_courses():
    ca = _role_user(COURSE_ADMIN, "ca_scope")
    mine = AllocationFactory(course=CourseFactory(owner=ca))
    AllocationFactory(course=CourseFactory())  # someone else's
    assert list(scoping.allocations_manageable_by(ca)) == [mine]


def test_course_admin_does_not_see_owner_less_courses():
    ca = _role_user(COURSE_ADMIN, "ca_ownerless")
    AllocationFactory(course=CourseFactory(owner=None))
    assert list(scoping.allocations_manageable_by(ca)) == []


def test_teacher_sees_none():
    teacher = _role_user(TEACHER, "t_scope")
    # The allocation must be on a course the TEACHER owns, or this test is blind
    # to the "Teacher accidentally granted change_allocation" mutant: that mutant
    # sends them down the CA branch (course__owner=user), which returns nothing
    # for a bare AllocationFactory() whose course has owner=None.
    AllocationFactory(course=CourseFactory(owner=teacher))
    assert list(scoping.allocations_manageable_by(teacher)) == []


def test_archived_allocations_are_included():
    """Parity with groups_manageable_by: list views filter on top."""
    pa = _role_user(PLATFORM_ADMIN, "pa_arch")
    a = AllocationFactory(archived=True)
    assert list(scoping.allocations_manageable_by(pa)) == [a]


def test_course_admin_role_holds_the_allocation_permissions():
    ca = _role_user(COURSE_ADMIN, "ca_perms")
    for codename in ("add", "change", "delete", "view"):
        assert ca.has_perm(f"grouping.{codename}_allocation")


def test_teacher_role_holds_no_allocation_permissions():
    teacher = _role_user(TEACHER, "t_perms")
    for codename in ("add", "change", "delete", "view"):
        assert not teacher.has_perm(f"grouping.{codename}_allocation")
