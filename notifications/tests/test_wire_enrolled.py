import pytest

from grouping import services as grouping_svc
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_self_enroll_does_not_notify():
    student = UserFactory()
    course = CourseFactory()
    grouping_svc.enroll_self(student, course)
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.ENROLLED, recipient=student
        ).count()
        == 0
    )
    grouping_svc.enroll_self(student, course)  # idempotent, still no row
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.ENROLLED, recipient=student
        ).count()
        == 0
    )


def test_group_enrollment_notifies_and_resync_does_not():
    student = UserFactory()
    course = CourseFactory()
    group = GroupFactory(course=course)
    grouping_svc.add_students_to_group(group, [student])
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.ENROLLED, recipient=student
        ).count()
        == 1
    )
    # Re-sync an already-enrolled student: no new notification.
    grouping_svc.recompute_enrollment(student, course)
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.ENROLLED, recipient=student
        ).count()
        == 1
    )
