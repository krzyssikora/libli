import pytest

from grouping import scoping
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory
from tests.factories import make_pa


@pytest.mark.django_db
def test_students_in_scope_all_is_reviewable_set_for_owner():
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    g = GroupFactory(course=course)
    GroupMembershipFactory(group=g)
    # owner sees all enrolled; but with no Enrollment rows the "all" set is empty.
    # Use the group arm to prove resolution; "all" for owner == reviewable_students.
    assert scoping.students_in_scope(owner, course, "all").count() == 0


@pytest.mark.django_db
def test_students_in_scope_group_arm(client):
    pa = make_pa(client)
    course = CourseFactory()
    g = GroupFactory(course=course)
    m = GroupMembershipFactory(group=g)
    ids = set(
        scoping.students_in_scope(pa, course, f"group:{g.pk}").values_list(
            "pk", flat=True
        )
    )
    assert ids == {m.student_id}


@pytest.mark.django_db
def test_students_in_scope_collection_arm_and_distinct(client):
    pa = make_pa(client)
    course = CourseFactory()
    g1 = GroupFactory(course=course)
    g2 = GroupFactory(course=course)
    student = UserFactory()
    GroupMembershipFactory(group=g1, student=student)
    GroupMembershipFactory(group=g2, student=student)  # same student in both
    col = CollectionFactory(course=course)
    col.groups.add(g1, g2)
    ids = list(
        scoping.students_in_scope(pa, course, f"collection:{col.pk}").values_list(
            "pk", flat=True
        )
    )
    assert ids == [student.pk]  # distinct -> appears once


@pytest.mark.django_db
def test_students_in_scope_bad_values_fall_back_to_all(client):
    pa = make_pa(client)
    course = CourseFactory()
    for bad in ("group:999", "collection:0", "group:abc", "garbage", "group:", ""):
        # falls back to "all" (== reviewable_students == empty here), never raises
        assert scoping.students_in_scope(pa, course, bad).count() == 0


@pytest.mark.django_db
def test_scope_choices_include_all_groups_collections(client):
    pa = make_pa(client)
    course = CourseFactory()
    g = GroupFactory(course=course, name="Group A")
    col = CollectionFactory(course=course, name="Collection X")
    choices = scoping.analytics_scope_choices(pa, course)
    values = [c["value"] for c in choices]
    assert values[0] == "all"
    assert f"group:{g.pk}" in values
    assert f"collection:{col.pk}" in values


@pytest.mark.django_db
def test_collections_visible_to_excludes_archived_collection(client):
    pa = make_pa(client)
    course = CourseFactory()
    live = CollectionFactory(course=course)
    archived = CollectionFactory(course=course, archived=True)
    pks = set(scoping.collections_visible_to(pa, course).values_list("pk", flat=True))
    assert live.pk in pks and archived.pk not in pks
