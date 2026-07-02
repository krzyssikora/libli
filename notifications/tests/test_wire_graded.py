from decimal import Decimal

import pytest

from courses import review as review_svc
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from notifications.models import Notification
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _review_q(unit, max_marks="5"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def test_completing_review_notifies_student_once():
    reviewer = UserFactory()
    sub = QuizSubmissionFactory()
    q1 = _review_q(sub.unit)
    q2 = _review_q(sub.unit)
    # Grade the first [R]: not fully reviewed yet -> no notification.
    review_svc.review_response(
        submission=sub,
        element=q1,
        earned_marks=Decimal("3"),
        feedback="",
        reviewer=reviewer,
    )
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_GRADED).count() == 0
    # Grade the second [R]: now fully reviewed -> exactly one notification.
    review_svc.review_response(
        submission=sub,
        element=q2,
        earned_marks=Decimal("4"),
        feedback="",
        reviewer=reviewer,
    )
    n = Notification.objects.get(kind=Notification.Kind.QUIZ_GRADED)
    assert n.recipient == sub.student


def test_re_editing_completed_review_does_not_renotify():
    reviewer = UserFactory()
    sub = QuizSubmissionFactory()
    q1 = _review_q(sub.unit)
    review_svc.review_response(
        submission=sub,
        element=q1,
        earned_marks=Decimal("3"),
        feedback="",
        reviewer=reviewer,
    )
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_GRADED).count() == 1
    # Edit marks after completion: fully_reviewed -> fully_reviewed, no re-notify.
    review_svc.review_response(
        submission=sub,
        element=q1,
        earned_marks=Decimal("5"),
        feedback="",
        reviewer=reviewer,
    )
    assert Notification.objects.filter(kind=Notification.Kind.QUIZ_GRADED).count() == 1
