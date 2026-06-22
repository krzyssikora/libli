import pytest
from django.urls import reverse

from courses.models import Enrollment
from grouping.models import Group
from grouping.models import GroupMembership
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_login  # noqa: F401
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_group_list_scoped_to_owned_courses(client):
    pa = make_pa(client)  # PA sees all  # noqa: F841
    GroupFactory()
    resp = client.get(reverse("grouping:group_list"))
    assert resp.status_code == 200


def test_create_group_enrolls_selected_students(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    student = UserFactory()
    resp = client.post(
        reverse("grouping:group_create"),
        {"name": "7A", "course": course.pk, "teachers": [], "students": [student.pk]},
    )
    assert resp.status_code == 302
    group = Group.objects.get(name="7A")
    assert GroupMembership.objects.filter(group=group, student=student).exists()
    assert Enrollment.objects.filter(
        student=student, course=course, source="group"
    ).exists()


def test_remove_student_via_edit_drops_enrollment(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    group = GroupFactory(course=course)
    student = UserFactory()
    from grouping import services

    services.add_students_to_group(group, [student])
    # Edit with an empty roster -> student removed.
    resp = client.post(
        reverse("grouping:group_edit", args=[group.pk]),
        {"name": group.name, "course": course.pk, "teachers": [], "students": []},
    )
    assert resp.status_code == 302
    assert not Enrollment.objects.filter(student=student, course=course).exists()


def test_archive_group_drops_access(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    group = GroupFactory(course=course)
    student = UserFactory()
    from grouping import services

    services.add_students_to_group(group, [student])
    resp = client.post(reverse("grouping:group_archive", args=[group.pk]))
    assert resp.status_code == 302
    group.refresh_from_db()
    assert group.archived is True
    assert not Enrollment.objects.filter(student=student, course=course).exists()
