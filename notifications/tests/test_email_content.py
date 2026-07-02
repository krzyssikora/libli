import pytest

from notifications.emails import email_content
from notifications.models import Notification

pytestmark = pytest.mark.django_db


def _notif(kind, data):
    # Unsaved instance is enough — email_content reads only kind + data.
    return Notification(kind=kind, data=data)


def test_quiz_needs_review_copy():
    subject, headline, body = email_content(
        _notif(
            Notification.Kind.QUIZ_NEEDS_REVIEW,
            {"student_name": "Ann", "unit_title": "Q1", "course_title": "Algebra"},
        )
    )
    assert subject == "A quiz needs your review"
    assert headline == subject
    assert "Ann" in body and "Q1" in body and "Algebra" in body


def test_quiz_graded_copy():
    subject, _h, body = email_content(
        _notif(
            Notification.Kind.QUIZ_GRADED,
            {"unit_title": "Q1", "course_title": "Algebra"},
        )
    )
    assert subject == "Your quiz was graded"
    assert "Q1" in body and "Algebra" in body


def test_enrolled_copy():
    subject, _h, body = email_content(
        _notif(Notification.Kind.ENROLLED, {"course_title": "Algebra"})
    )
    assert subject == "You've been enrolled in Algebra"
    assert "Algebra" in body


def test_enrolled_subject_collapses_newlines():
    subject, _h, _b = email_content(
        _notif(Notification.Kind.ENROLLED, {"course_title": "Line1\nLine2"})
    )
    assert "\n" not in subject
    assert "Line1 Line2" in subject


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        email_content(_notif("bogus_kind", {}))
