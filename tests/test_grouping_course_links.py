"""The course title on the grouping pages links to the course outline.

Without these links a teacher assigned to a Group has no click-path to the
course they teach: `my_courses` is enrollment-only, and the grouping pages
rendered the course title as plain text. See test_teacher_can_follow_* for the
end-to-end proof that the link actually resolves for a teacher.
"""

import pytest
from django.urls import reverse

from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _outline_url(course):
    return reverse("courses:course_outline", args=[course.slug])


def test_my_groups_group_row_links_to_course_outline(client):
    teacher = make_teacher(client, "t_link_mygroups_grp")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    resp = client.get(reverse("grouping:my_groups"))
    assert resp.status_code == 200
    assert f'href="{_outline_url(course)}"' in resp.content.decode()


def test_my_groups_collection_row_links_to_course_outline(client):
    teacher = make_teacher(client, "t_link_mygroups_coll")
    course = CourseFactory()
    CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:my_groups"))
    assert resp.status_code == 200
    assert f'href="{_outline_url(course)}"' in resp.content.decode()


def test_group_detail_links_to_course_outline(client):
    teacher = make_teacher(client, "t_link_gd")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    assert f'href="{_outline_url(course)}"' in resp.content.decode()


def test_collection_detail_links_to_course_outline(client):
    teacher = make_teacher(client, "t_link_cd")
    course = CourseFactory()
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    assert f'href="{_outline_url(course)}"' in resp.content.decode()


def test_teacher_can_follow_my_groups_link_to_the_outline(client):
    """The click-path end to end: the href on my_groups resolves to a 200 for a
    non-staff teacher tied to the course only via Group.teachers. Since
    courses.access.accessible_courses now consults Group.teachers (non-archived),
    a bare factory teacher — no is_staff, not owner, not enrolled — is admitted.
    """
    teacher = make_teacher(client, "t_link_followthrough")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert not teacher.is_staff
    assert course.owner != teacher

    listing = client.get(reverse("grouping:my_groups"))
    href = _outline_url(course)
    assert f'href="{href}"' in listing.content.decode()

    outline = client.get(href)
    assert outline.status_code == 200
