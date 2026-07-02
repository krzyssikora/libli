import pytest

from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_notification_defaults_and_fields():
    user = UserFactory()
    course = CourseFactory()
    n = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
    )
    assert n.read_at is None
    assert n.data == {}
    assert n.actor is None
    assert n.created_at is not None


def test_notification_ordering_newest_first():
    user = UserFactory()
    first = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=1,
    )
    second = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=2,
    )
    assert list(Notification.objects.filter(recipient=user)) == [second, first]
