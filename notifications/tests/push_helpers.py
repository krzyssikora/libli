"""Shared fixtures-as-functions for the push tests."""

import itertools

from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone

from notifications.models import PushSubscription
from notifications.push import generate_vapid_pair

FCM = "https://fcm.googleapis.com/fcm/send/"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/"

_PAIR = generate_vapid_pair()
_SEQ = itertools.count()


def push_settings(settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    settings.PUSH_VAPID_PUBLIC_KEY, settings.PUSH_VAPID_PRIVATE_KEY = _PAIR
    settings.PUSH_VAPID_SUBJECT = "mailto:ops@example.com"


def logged_in_user(client, **attrs):
    """A user the test client STAYS logged in as. Never UserFactory()+force_login:
    UserFactory skips the post-generation save, so the persisted password differs
    from the in-memory one, the session hash mismatches on the next request and the
    client is silently anonymous (see tests/test_notes_views.py:_stranger)."""
    from tests.factories import make_verified_user

    n = next(_SEQ)
    user = make_verified_user(username=f"pushuser{n}", email=f"pushuser{n}@example.com")
    for key, value in attrs.items():
        setattr(user, key, value)
    if attrs:
        user.save()
    client.force_login(user)
    return user


def live_session_for(user, *, remembered=True):
    """A real DB session authenticated as `user`, like a login would leave.

    Saves the user's password FIRST: UserFactory skips the post-generation save, so
    its in-memory password (which Notification.recipient and live_subscriptions see --
    nothing reloads it) differs from the persisted one. Persisting it makes both agree,
    so a later user.save() (is_active, language) no longer changes the hash on its own
    and each session test fails only through the check it targets."""
    user.save(update_fields=["password"])
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    if not remembered:
        store.set_expiry(0)
    store.create()
    return store.session_key


def make_sub(user, session_key, endpoint=None, **kw):
    kw.setdefault("p256dh", "BPp")
    kw.setdefault("auth", "aa")
    kw.setdefault("subscribed_at", timezone.now())
    return PushSubscription.objects.create(
        user=user,
        endpoint=endpoint or f"{FCM}{PushSubscription.objects.count()}-{user.pk}",
        session_key=session_key,
        **kw,
    )
