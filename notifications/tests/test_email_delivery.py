import pytest
from django.core import mail

from notifications.emails import deliver_notification_email
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _graded(recipient, course, **data):
    base = {
        "course_title": course.title,
        "course_slug": course.slug,
        "unit_title": "Quiz 1",
        "node_pk": 999,
    }
    base.update(data)
    return Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.QUIZ_GRADED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data=base,
    )


def test_sends_multipart_with_html_alternative():
    recipient = UserFactory(email="stu@example.com")
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["stu@example.com"]
    assert msg.subject == "Your quiz was graded"
    assert any(ctype == "text/html" for _content, ctype in msg.alternatives)


def test_blank_email_is_noop():
    recipient = UserFactory(email="")
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    assert mail.outbox == []


def test_opted_out_kind_is_noop():
    recipient = UserFactory(email="stu@example.com")
    NotificationEmailPreference.objects.create(user=recipient, quiz_graded=False)
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    assert mail.outbox == []


def test_unknown_kind_swallowed_no_email_no_raise():
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    n = Notification.objects.create(
        recipient=recipient,
        kind="bogus_kind",  # not in Kind.choices; DB has no constraint
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data={},
    )
    deliver_notification_email(n)  # must not raise
    assert mail.outbox == []


def test_cta_is_absolute_and_uses_notification_url():
    recipient = UserFactory(email="stu@example.com")
    n = _graded(recipient, CourseFactory(slug="algebra"))
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "://" in html
    assert "/courses/algebra/" in html  # notification_url target, absolute


def test_cta_falls_back_to_list_when_no_target_url():
    # enrolled with no course_slug → notification_url returns None → /notifications/
    recipient = UserFactory(email="stu@example.com")
    n = Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.ENROLLED,
        target_type=Notification.TargetType.COURSE,
        target_id=1,
        data={"course_title": "Algebra"},  # no course_slug
    )
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "/notifications/" in html


def test_html_escapes_user_data():
    recipient = UserFactory(email="stu@example.com")
    course = CourseFactory()
    n = _graded(recipient, course, course_title="<b>x</b>")
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html


def test_header_uses_fallback_color_when_primary_none(monkeypatch):
    # An Institution with no valid primary color yields site.primary == None; the
    # template MUST fall back to #147E78 (an email has no external stylesheet).
    import notifications.emails as emails_mod

    monkeypatch.setattr(
        emails_mod, "get_site_config", lambda: {"name": "libli", "primary": None}
    )
    recipient = UserFactory(email="stu@example.com")
    n = _graded(recipient, CourseFactory())
    deliver_notification_email(n)
    html = mail.outbox[0].alternatives[0][0]
    assert "#147E78" in html
    assert "background-color: ;" not in html  # None must not render as empty
