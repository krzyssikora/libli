import pytest
from django.urls import reverse

from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
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
