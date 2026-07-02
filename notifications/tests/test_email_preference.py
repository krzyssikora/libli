import pytest
from django.db import IntegrityError

from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_field_names_match_kind_values():
    field_names = {f.name for f in NotificationEmailPreference._meta.get_fields()}
    for kind in Notification.Kind.values:
        assert kind in field_names, f"missing boolean field for kind {kind!r}"


def test_defaults_all_on():
    pref = NotificationEmailPreference.objects.create(user=UserFactory())
    assert pref.quiz_needs_review is True
    assert pref.quiz_graded is True
    assert pref.enrolled is True


def test_one_row_per_user():
    user = UserFactory()
    NotificationEmailPreference.objects.create(user=user)
    with pytest.raises(IntegrityError):  # OneToOne uniqueness
        NotificationEmailPreference.objects.create(user=user)


def test_email_enabled_default_true_when_no_row():
    from notifications.emails import email_enabled

    assert email_enabled(UserFactory(), Notification.Kind.QUIZ_GRADED) is True


def test_email_enabled_reflects_row():
    from notifications.emails import email_enabled

    user = UserFactory()
    NotificationEmailPreference.objects.create(user=user, quiz_graded=False)
    assert email_enabled(user, Notification.Kind.QUIZ_GRADED) is False
    assert email_enabled(user, Notification.Kind.ENROLLED) is True


def test_absolute_url_builds_scheme_and_domain():
    from notifications.emails import _absolute_url

    url = _absolute_url("/notifications/")
    assert "://" in url
    assert url.endswith("/notifications/")
