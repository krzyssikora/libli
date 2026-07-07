import pytest
from django.urls import reverse

from grouping import services
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_ca
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _analytics_url(course):
    return reverse("courses:manage_analytics", args=[course.slug])


def test_my_groups_group_row_has_scoped_analytics_link(client):
    teacher = make_teacher(client, "t_mygroups_grp")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)  # teaches a live group -> can_review true
    resp = client.get(reverse("grouping:my_groups"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=group:{group.pk}" in body


def test_my_groups_reachable_collection_row_has_scoped_analytics_link(client):
    teacher = make_teacher(client, "t_mygroups_coll_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)  # live group on the course -> can_review true
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:my_groups"))
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=collection:{coll.pk}" in body


def test_my_groups_unreachable_collection_row_hides_analytics_link(client):
    # Teacher owns a collection on a course where they teach NO live group ->
    # can_review is false -> the collection's Analytics link must be absent,
    # otherwise the link would 404 at the analytics page gate.
    teacher = make_teacher(client, "t_mygroups_coll_no")
    course = CourseFactory()
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:my_groups"))
    body = resp.content.decode()
    assert f"?scope=collection:{coll.pk}" not in body


def test_group_detail_teacher_sees_scoped_analytics_link(client):
    teacher = make_teacher(client, "t_gd_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=group:{group.pk}" in body


def test_group_detail_archived_group_hides_link_even_when_can_review(client):
    # ISOLATES the `not group.archived` term: a Course Admin who owns the course
    # has can_review == True and can see their own archived group, yet the link
    # must be hidden because a group:<pk> scope on an archived group silently
    # falls back to "all" (students_in_scope requires archived=False).
    ca = make_ca(client, "ca_gd_arch")
    course = CourseFactory(owner=ca)
    group = GroupFactory(course=course)
    services.set_group_archived(group, True)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=group:{group.pk}" not in body


def test_group_detail_archived_only_reach_hides_link(client):
    # can_review == False path: a teacher whose ONLY group on the course is
    # archived. groups_visible_to still returns it (they teach it) so the page
    # loads, but can_review_course is false -> link absent.
    teacher = make_teacher(client, "t_gd_arch_only")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    services.set_group_archived(group, True)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=group:{group.pk}" not in body


def test_collection_detail_reachable_shows_scoped_link(client):
    teacher = make_teacher(client, "t_cd_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)  # live group -> can_review true
    coll = CollectionFactory(course=course, owner=teacher)  # teacher owns -> visible
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=collection:{coll.pk}" in body


def test_collection_detail_unreachable_hides_link(client):
    # Load-bearing can_review gate: teacher owns the collection (so the page is
    # reachable) but teaches no live group on the course -> can_review false.
    teacher = make_teacher(client, "t_cd_no")
    course = CourseFactory()
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=collection:{coll.pk}" not in body


def test_collection_detail_archived_hides_link_even_when_can_review(client):
    # ISOLATES `not collection.archived`: can_review true (teacher teaches a live
    # group on the course) but the collection is archived -> scope would fall back
    # to "all", so the link is hidden.
    teacher = make_teacher(client, "t_cd_arch")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    coll = CollectionFactory(course=course, owner=teacher, archived=True)
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=collection:{coll.pk}" not in body
