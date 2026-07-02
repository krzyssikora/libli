import pytest
from django.core import mail

from notifications import services
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_notify_sends_email_on_commit(django_capture_on_commit_callbacks):
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            recipient=recipient,
            kind=Notification.Kind.ENROLLED,
            target=course,
            data={"course_title": course.title, "course_slug": course.slug},
        )
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["stu@example.com"]


def test_self_suppressed_sends_nothing(django_capture_on_commit_callbacks):
    user = UserFactory(email="stu@example.com")
    course = CourseFactory()
    with django_capture_on_commit_callbacks(execute=True):
        result = services.notify(
            recipient=user,
            kind=Notification.Kind.ENROLLED,
            target=course,
            actor=user,
        )
    assert result is None
    assert Notification.objects.count() == 0
    assert mail.outbox == []


def test_opt_out_keeps_in_app_row_but_no_email(django_capture_on_commit_callbacks):
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    NotificationEmailPreference.objects.create(user=recipient, enrolled=False)
    with django_capture_on_commit_callbacks(execute=True):
        services.notify(
            recipient=recipient,
            kind=Notification.Kind.ENROLLED,
            target=course,
            data={"course_title": course.title, "course_slug": course.slug},
        )
    assert Notification.objects.filter(recipient=recipient).count() == 1  # in-app kept
    assert mail.outbox == []  # email suppressed
