from decimal import Decimal

import pytest

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _review_q(unit, *, max_marks="5"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _student_in_group(course, teachers):
    student = UserFactory()
    group = GroupFactory(course=course)
    for t in teachers:
        group.teachers.add(t)
    GroupMembershipFactory(group=group, student=student)
    return student


def test_notify_needs_review_fans_out_to_group_teachers():
    course = CourseFactory()
    t1, t2 = UserFactory(), UserFactory()
    student = _student_in_group(course, [t1, t2])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    _review_q(sub.unit)

    services.notify_needs_review(sub, actor=student)

    recipients = set(
        Notification.objects.filter(
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW
        ).values_list("recipient", flat=True)
    )
    assert recipients == {t1.pk, t2.pk}
    row = Notification.objects.filter(recipient=t1).get()
    assert row.data["student_name"] == str(student)
    assert row.data["course_slug"] == course.slug
    assert row.target_id == sub.pk


def test_notify_needs_review_noop_without_review_question():
    course = CourseFactory()
    t1 = UserFactory()
    student = _student_in_group(course, [t1])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    # No [R] question on the unit.
    services.notify_needs_review(sub, actor=student)
    assert Notification.objects.count() == 0


def test_notify_needs_review_suppresses_acting_teacher():
    course = CourseFactory()
    t1, t2 = UserFactory(), UserFactory()
    student = _student_in_group(course, [t1, t2])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    _review_q(sub.unit)
    # t1 force-submits: they should NOT notify themselves, but t2 should be notified.
    services.notify_needs_review(sub, actor=t1)
    recipients = set(Notification.objects.values_list("recipient", flat=True))
    assert recipients == {t2.pk}
