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
