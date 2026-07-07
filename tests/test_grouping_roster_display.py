"""Roster display on group/collection detail pages: full-name labels
(User.list_display_name), family-name ordering (User.sort_name), and the owner
shown once (not duplicated when the course owner also teaches the group).
"""

import pytest
from django.urls import reverse

from grouping import services
from grouping.models import Collection
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_group_detail_owner_not_duplicated_in_teachers(client):
    make_pa(client)
    owner = UserFactory(username="owner1", first_name="", last_name="", display_name="")
    course = CourseFactory(owner=owner)
    group = GroupFactory(course=course)
    group.teachers.add(owner)  # owner ALSO teaches the group
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert owner not in resp.context["teachers"]  # excluded from the teachers list
    assert resp.content.decode().count("owner1") == 1  # rendered exactly once


def test_group_detail_students_sorted_by_family_name_not_username(client):
    make_pa(client)
    group = GroupFactory()
    # usernames deliberately in the REVERSE order of family names, so a username
    # sort would fail this test — only a family-name sort passes.
    alpha = UserFactory(
        username="u3", first_name="Zoe", last_name="Alpha", display_name=""
    )
    mid = UserFactory(username="u2", first_name="Bob", last_name="Mid", display_name="")
    zeta = UserFactory(
        username="u1", first_name="Aaron", last_name="Zeta", display_name=""
    )
    services.add_students_to_group(group, [zeta, alpha, mid])
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    order = [m.student.last_name for m in resp.context["students"]]
    assert order == ["Alpha", "Mid", "Zeta"]


def test_group_detail_shows_first_last_name(client):
    make_pa(client)
    group = GroupFactory()
    s = UserFactory(
        username="jk", first_name="Jan", last_name="Kowalski", display_name=""
    )
    services.add_students_to_group(group, [s])
    assert (
        "Jan Kowalski"
        in client.get(
            reverse("grouping:group_detail", args=[group.pk])
        ).content.decode()
    )


def test_group_detail_falls_back_to_display_name_without_structured_name(client):
    make_pa(client)
    group = GroupFactory()
    s = UserFactory(username="jk", first_name="", last_name="", display_name="Janek K")
    services.add_students_to_group(group, [s])
    assert (
        "Janek K"
        in client.get(
            reverse("grouping:group_detail", args=[group.pk])
        ).content.decode()
    )


def test_collection_detail_students_sorted_by_family_name(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    g = GroupFactory(course=course)
    alpha = UserFactory(
        username="u3", first_name="Zoe", last_name="Alpha", display_name=""
    )
    zeta = UserFactory(
        username="u1", first_name="Aaron", last_name="Zeta", display_name=""
    )
    services.add_students_to_group(g, [zeta, alpha])
    coll = Collection.objects.create(name="Union", course=course, owner=pa)
    services.set_collection_groups(coll, [g.pk])
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert [u.last_name for u in resp.context["students"]] == ["Alpha", "Zeta"]
    assert "Zoe Alpha" in resp.content.decode()
