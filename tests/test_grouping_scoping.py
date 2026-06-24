import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping import scoping
from institution.roles import seed_roles
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
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


def test_pa_reviews_all_enrolled_students():
    pa = _with_role(UserFactory(), "Platform Admin")
    course = CourseFactory(owner=UserFactory())
    s1 = UserFactory()
    s2 = UserFactory()
    EnrollmentFactory(student=s1, course=course)
    EnrollmentFactory(student=s2, course=course)
    ids = set(scoping.reviewable_students(pa, course).values_list("pk", flat=True))
    assert ids == {s1.pk, s2.pk}
    assert scoping.can_review_course(pa, course) is True


def test_owner_reviews_all_enrolled_students():
    owner = _with_role(UserFactory(), "Course Admin")
    course = CourseFactory(owner=owner)
    s1 = UserFactory()
    EnrollmentFactory(student=s1, course=course)
    assert list(scoping.reviewable_students(owner, course)) == [s1]
    assert scoping.can_review_course(owner, course) is True


def test_group_teacher_reviews_only_their_group_students():
    teacher = _with_role(UserFactory(), "Teacher")
    course = CourseFactory(owner=UserFactory())  # not owned by the teacher
    g = GroupFactory(course=course)
    g.teachers.add(teacher)
    mine = UserFactory()
    GroupMembershipFactory(group=g, student=mine)
    other = UserFactory()
    EnrollmentFactory(student=other, course=course)  # enrolled, not in group
    ids = set(scoping.reviewable_students(teacher, course).values_list("pk", flat=True))
    assert ids == {mine.pk}  # other-enrolled student is invisible to the teacher
    assert scoping.can_review_course(teacher, course) is True


def test_archived_group_gives_no_review_reach():
    teacher = _with_role(UserFactory(), "Teacher")
    course = CourseFactory(owner=UserFactory())
    g = GroupFactory(course=course, archived=True)
    g.teachers.add(teacher)
    GroupMembershipFactory(group=g, student=UserFactory())
    assert list(scoping.reviewable_students(teacher, course)) == []
    assert scoping.can_review_course(teacher, course) is False


def test_unrelated_teacher_cannot_review():
    teacher = _with_role(UserFactory(), "Teacher")
    course = CourseFactory(owner=UserFactory())
    assert scoping.can_review_course(teacher, course) is False
    assert list(scoping.reviewable_students(teacher, course)) == []
