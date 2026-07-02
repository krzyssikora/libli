import pytest
from django.core import mail

from notifications.emails import deliver_notification_email
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_polish_recipient_gets_polish_subject():
    recipient = UserFactory(email="pl@example.com", language="pl")
    course = CourseFactory()
    n = Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.QUIZ_GRADED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data={
            "course_title": course.title,
            "course_slug": course.slug,
            "unit_title": "Quiz 1",
            "node_pk": 999,
        },
    )
    deliver_notification_email(n)
    assert mail.outbox[0].subject == "Twój quiz został oceniony"


def test_per_recipient_language_is_independent():
    """Two recipients of the same event get the email in their OWN language — proves
    the per-recipient translation.override (the fan-out localization guarantee)."""
    course = CourseFactory()
    data = {
        "course_title": course.title,
        "course_slug": course.slug,
        "unit_title": "Quiz 1",
        "node_pk": 999,
    }
    for lang, email in (("en", "en@example.com"), ("pl", "pl@example.com")):
        recipient = UserFactory(email=email, language=lang)
        n = Notification.objects.create(
            recipient=recipient,
            kind=Notification.Kind.QUIZ_GRADED,
            target_type=Notification.TargetType.COURSE,
            target_id=course.pk,
            data=data,
        )
        deliver_notification_email(n)
    subjects = {m.to[0]: m.subject for m in mail.outbox}
    assert subjects["en@example.com"] == "Your quiz was graded"
    assert subjects["pl@example.com"] == "Twój quiz został oceniony"
