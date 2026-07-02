import pytest

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_notify_graded_targets_student():
    reviewer = UserFactory()
    sub = QuizSubmissionFactory()
    services.notify_graded(sub, reviewer)
    n = Notification.objects.get(kind=Notification.Kind.QUIZ_GRADED)
    assert n.recipient == sub.student
    assert n.actor == reviewer
    assert n.target_id == sub.pk
    assert n.data["course_slug"] == sub.unit.course.slug
    assert n.data["node_pk"] == sub.unit_id


def test_notify_enrolled_targets_student_with_null_actor():
    student = UserFactory()
    course = CourseFactory()
    services.notify_enrolled(student, course)
    n = Notification.objects.get(kind=Notification.Kind.ENROLLED)
    assert n.recipient == student
    assert n.actor is None
    assert n.target_id == course.pk
    assert n.data == {"course_title": course.title, "course_slug": course.slug}
