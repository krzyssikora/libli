import pytest

from courses.access import accessible_courses
from courses.access import can_access_course
from courses.models import Enrollment
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_accessible_courses_matches_can_access_for_every_role():
    owner = UserFactory()
    enrolled = UserFactory()
    outsider = UserFactory()
    staff = UserFactory(is_staff=True)

    owned = CourseFactory(owner=owner)
    joined = CourseFactory()
    other = CourseFactory()
    Enrollment.objects.create(student=enrolled, course=joined)

    for user in (owner, enrolled, outsider, staff):
        accessible_pks = set(accessible_courses(user).values_list("pk", flat=True))
        for course in (owned, joined, other):
            assert (course.pk in accessible_pks) == can_access_course(user, course), (
                user,
                course.pk,
            )


def test_accessible_courses_anonymous_is_empty():
    from django.contrib.auth.models import AnonymousUser

    CourseFactory()
    assert accessible_courses(AnonymousUser()).count() == 0
