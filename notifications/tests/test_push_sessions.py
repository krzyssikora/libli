"""D7 + D8: a subscription delivers only while its session is live, authenticated
as its user, with a current auth hash, an active user and a remembered login."""

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.sessions.models import Session
from django.utils import timezone

from notifications.models import PushSubscription
from notifications.push import live_subscriptions
from notifications.tests.push_helpers import live_session_for
from notifications.tests.push_helpers import make_sub
from tests.factories import TEST_PASSWORD
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_live_remembered_session_is_kept():
    user = UserFactory()
    sub = make_sub(user, live_session_for(user))
    assert live_subscriptions(user) == [sub]


def test_missing_session_is_dropped_and_deleted():
    # mutant "filter removed": return every row
    user = UserFactory()
    make_sub(user, "nosuchsession0000000000000000000")
    assert live_subscriptions(user) == []
    assert PushSubscription.objects.count() == 0


def test_expired_session_row_still_present_is_dropped():
    # mutant "existence only": Session.objects.filter(session_key__in=keys)
    # without expire_date
    user = UserFactory()
    key = live_session_for(user)
    Session.objects.filter(session_key=key).update(
        expire_date=timezone.now() - timedelta(seconds=1)
    )
    make_sub(user, key)
    assert live_subscriptions(user) == []
    assert PushSubscription.objects.count() == 0


def test_session_of_another_user_is_dropped():
    # mutant: drop the _auth_user_id check. ONLY the id is wrong -- the stored hash
    # is still user's own, so the hash check cannot drop the row on this test's
    # behalf.
    from django.contrib.auth import SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore

    user, other = UserFactory(), UserFactory()
    key = live_session_for(user)
    store = SessionStore(session_key=key)
    store[SESSION_KEY] = str(other.pk)
    store.save()
    make_sub(user, key)
    assert live_subscriptions(user) == []


def test_password_changed_elsewhere_is_dropped():
    # mutant: drop the auth-hash check
    user = UserFactory()
    make_sub(user, live_session_for(user))
    user.set_password(TEST_PASSWORD)  # differs from UserFactory's password
    user.save()
    assert live_subscriptions(user) == []


def test_fallback_secret_hash_is_still_live(settings):
    user = UserFactory()
    settings.SECRET_KEY_FALLBACKS = [settings.SECRET_KEY]
    key = live_session_for(user)  # hash made with the (now fallback) key
    settings.SECRET_KEY = settings.SECRET_KEY[::-1] + "x"  # derived: no secret literal
    make_sub(user, key)
    assert len(live_subscriptions(user)) == 1


def test_inactive_user_is_dropped():
    # mutant: drop the is_active check
    user = UserFactory()
    make_sub(user, live_session_for(user))
    user.is_active = False
    user.save()
    assert live_subscriptions(user) == []


def test_not_remembered_session_is_dropped():
    # mutant: drop the remembered_from_data check
    user = UserFactory()
    make_sub(user, live_session_for(user, remembered=False))
    assert live_subscriptions(user) == []
    assert PushSubscription.objects.count() == 0


def test_delete_spares_a_row_rekeyed_meanwhile():
    # mutant "delete by pk alone": PushSubscription.objects.filter(pk__in=...).delete()
    user = UserFactory()
    sub = make_sub(user, "deadsession00000000000000000000x")
    fresh = live_session_for(user)
    real_filter = Session.objects.filter

    def rekey_then_filter(*args, **kwargs):
        PushSubscription.objects.filter(pk=sub.pk).update(session_key=fresh)
        return real_filter(*args, **kwargs)

    with mock.patch.object(Session.objects, "filter", side_effect=rekey_then_filter):
        live_subscriptions(user)
    assert PushSubscription.objects.filter(pk=sub.pk, session_key=fresh).exists()


def test_other_users_rows_are_never_touched():
    user, other = UserFactory(), UserFactory()
    make_sub(other, "deadsession00000000000000000000y")
    live_subscriptions(user)
    assert PushSubscription.objects.filter(user=other).count() == 1
