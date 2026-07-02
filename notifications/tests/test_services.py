import pytest

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_notify_creates_row():
    recipient = UserFactory()
    course = CourseFactory()
    n = services.notify(
        recipient=recipient,
        kind=Notification.Kind.ENROLLED,
        target=course,
        data={"course_title": course.title},
    )
    assert n is not None
    assert n.recipient == recipient
    assert n.target_type == "course"
    assert n.target_id == course.pk
    assert n.data == {"course_title": course.title}


def test_notify_self_is_noop():
    user = UserFactory()
    course = CourseFactory()
    result = services.notify(
        recipient=user, kind=Notification.Kind.ENROLLED, target=course, actor=user
    )
    assert result is None
    assert Notification.objects.count() == 0


def test_resolve_target_course_and_submission():
    course = CourseFactory()
    sub = QuizSubmissionFactory()
    assert services._resolve_target(course) == ("course", course.pk)
    assert services._resolve_target(sub) == ("submission", sub.pk)


def test_resolve_target_rejects_unknown():
    with pytest.raises(TypeError):
        services._resolve_target(object())


def test_unread_count_and_recent_for():
    user = UserFactory()
    course = CourseFactory()
    a = services.notify(recipient=user, kind=Notification.Kind.ENROLLED, target=course)
    b = services.notify(recipient=user, kind=Notification.Kind.ENROLLED, target=course)
    assert services.unread_count(user) == 2
    a.read_at = b.created_at
    a.save(update_fields=["read_at"])
    assert services.unread_count(user) == 1
    assert list(services.recent_for(user, 1)) == [b]
