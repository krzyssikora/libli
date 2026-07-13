import pytest
from django.urls import reverse

from courses.access import accessible_courses
from courses.access import can_access_course
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_login
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_accessible_includes_taught_nonarchived_course():
    # Pure-queryset test: no request is issued, so build the user WITHOUT a client
    # (make_login would call client.force_login and crash on a None client).
    teacher = make_verified_user(
        username="t_access_incl", email="t_access_incl@x.example.com"
    )
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    # the fix must grant via the taught branch, not is_staff
    assert not teacher.is_staff
    assert course in accessible_courses(teacher)


def test_accessible_excludes_archived_group_taught_course():
    teacher = make_verified_user(
        username="t_access_arch", email="t_access_arch@x.example.com"
    )
    course = CourseFactory()
    group = GroupFactory(course=course, archived=True)
    group.teachers.add(teacher)
    assert not teacher.is_staff
    assert course not in accessible_courses(teacher)


def test_accessible_excludes_unrelated_course():
    user = make_verified_user(
        username="t_access_unrel", email="t_access_unrel@x.example.com"
    )
    CourseFactory()  # not owned, not enrolled, not taught
    assert list(accessible_courses(user)) == []


def test_course_outline_admits_nonstaff_group_teacher(client):
    teacher = make_login(client, "t_outline_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert not teacher.is_staff
    assert can_access_course(teacher, course)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 200


def test_course_outline_403_for_untaught_teacher(client):
    teacher = make_login(client, "t_outline_403")
    course = CourseFactory()  # teacher has no relation to this course
    assert not can_access_course(teacher, course)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 403
