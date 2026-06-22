import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping import scoping
from institution.roles import seed_roles
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _with_role(user, role_name):
    seed_roles()
    user.groups.add(AuthGroup.objects.get(name=role_name))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_pa_sees_all_groups():
    GroupFactory()
    GroupFactory()
    pa = _with_role(UserFactory(), "Platform Admin")
    assert scoping.groups_manageable_by(pa).count() == 2


def test_ca_sees_only_owned_course_groups():
    ca = _with_role(UserFactory(), "Course Admin")
    mine = GroupFactory(course=CourseFactory(owner=ca))
    GroupFactory(course=CourseFactory(owner=UserFactory()))  # someone else's
    result = list(scoping.groups_manageable_by(ca))
    assert result == [mine]


def test_visible_includes_taught_groups():
    teacher = _with_role(UserFactory(), "Teacher")
    g = GroupFactory()
    g.teachers.add(teacher)
    assert g in scoping.groups_visible_to(teacher)
    assert g not in scoping.groups_manageable_by(teacher)


def test_can_add_collection_group_rules():
    pa = _with_role(UserFactory(), "Platform Admin")
    ca = UserFactory()
    teacher = UserFactory()
    owned_course = CourseFactory(owner=ca)
    g = GroupFactory(course=owned_course)
    g.teachers.add(teacher)
    assert scoping.can_add_collection_group(pa, g) is True
    assert scoping.can_add_collection_group(ca, g) is True
    assert scoping.can_add_collection_group(teacher, g) is True
    assert scoping.can_add_collection_group(UserFactory(), g) is False


def test_collections_manageable_owner_and_course():
    ca = _with_role(UserFactory(), "Course Admin")
    own = CollectionFactory(owner=ca, course=CourseFactory(owner=UserFactory()))
    on_my_course = CollectionFactory(
        owner=UserFactory(), course=CourseFactory(owner=ca)
    )
    CollectionFactory(owner=UserFactory(), course=CourseFactory(owner=UserFactory()))
    result = set(scoping.collections_manageable_by(ca))
    assert result == {own, on_my_course}
