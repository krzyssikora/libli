import pytest
from django.urls import reverse

from grouping import services
from grouping.models import Collection
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_create_collection_sets_owner(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    g = GroupFactory(course=course)
    resp = client.post(
        reverse("grouping:collection_create"),
        {"name": "Both 7s", "course": course.pk, "groups": [g.pk]},
    )
    assert resp.status_code == 302
    coll = Collection.objects.get(name="Both 7s")
    assert coll.owner == pa


def test_collection_detail_union_excludes_archived_group(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    g1 = GroupFactory(course=course)
    g2 = GroupFactory(course=course)
    s1 = UserFactory(username="s1")
    s2 = UserFactory(username="s2")
    services.add_students_to_group(g1, [s1])
    services.add_students_to_group(g2, [s2])
    coll = Collection.objects.create(name="Union", course=course, owner=pa)
    services.set_collection_groups(coll, [g1.pk, g2.pk])
    services.set_group_archived(g2, True)  # g2 archived -> s2 excluded
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    body = resp.content.decode()
    assert "s1" in body
    assert "s2" not in body
    assert resp.context["student_count"] == 1
