import pytest
from django.db import IntegrityError
from django.utils import timezone

from notifications.models import NotificationPushPreference
from notifications.models import PushSubscription
from notifications.push import push_kind_enabled
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def make_sub(user, endpoint="https://fcm.googleapis.com/fcm/send/a", **kw):
    kw.setdefault("p256dh", "p")
    kw.setdefault("auth", "a")
    kw.setdefault("subscribed_at", timezone.now())
    kw.setdefault("session_key", "k" * 32)
    return PushSubscription.objects.create(user=user, endpoint=endpoint, **kw)


def test_endpoint_is_unique_across_users():
    make_sub(UserFactory())
    with pytest.raises(IntegrityError):
        make_sub(UserFactory())


def test_deleting_the_user_deletes_subscriptions():
    user = UserFactory()
    make_sub(user)
    user.delete()
    assert PushSubscription.objects.count() == 0


def test_no_preference_row_means_every_kind_on():
    user = UserFactory()
    for kind in ("quiz_needs_review", "quiz_graded", "enrolled"):
        assert push_kind_enabled(user, kind) is True


def test_preference_row_turns_one_kind_off():
    user = UserFactory()
    NotificationPushPreference.objects.create(user=user, quiz_graded=False)
    assert push_kind_enabled(user, "quiz_graded") is False
    assert push_kind_enabled(user, "enrolled") is True


def test_str_methods():
    user = UserFactory()
    assert str(user.pk) in str(make_sub(user))
    assert str(user.pk) in str(NotificationPushPreference.objects.create(user=user))
