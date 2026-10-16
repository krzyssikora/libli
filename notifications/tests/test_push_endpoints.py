"""§4: the three JSON endpoints."""

import base64
import json
from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from notifications.models import PushSubscription
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

P256DH = base64.urlsafe_b64encode(b"\x04" + b"\x01" * 64).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(b"\x02" * 16).decode().rstrip("=")


def body(endpoint=FCM + "dev1"):
    return {"endpoint": endpoint, "keys": {"p256dh": P256DH, "auth": AUTH}}


def post(client, name, payload):
    return client.post(
        reverse(f"notifications:{name}"),
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.fixture
def on(settings):
    push_settings(settings)


@pytest.fixture
def user_client(client):
    user = logged_in_user(client)  # force_login sets no _session_expiry: remembered
    return user, client


def forget_me(client):
    session = client.session
    session.set_expiry(0)
    session.save()


# --- gates and order --------------------------------------------------------------


@pytest.mark.parametrize("name", ["push_subscribe", "push_unsubscribe", "push_claim"])
def test_404_when_not_configured_even_for_anonymous(client, name):
    assert post(client, name, body()).status_code == 404


@pytest.mark.parametrize("name", ["push_subscribe", "push_unsubscribe", "push_claim"])
def test_anonymous_gets_403_json_not_a_redirect(client, on, name):
    r = post(client, name, body())
    assert r.status_code == 403
    assert r.json() == {"ok": False}


def test_csrf_is_required(on):
    strict = Client(enforce_csrf_checks=True)
    logged_in_user(strict)
    assert post(strict, "push_subscribe", body()).status_code == 403
    assert PushSubscription.objects.count() == 0


def test_get_is_refused(user_client, on):
    _, client = user_client
    assert client.get(reverse("notifications:push_subscribe")).status_code == 405


def test_not_remembered_subscribe_is_403_even_with_a_bad_body(user_client, on):
    # mutant: remembered check moved after body validation
    _, client = user_client
    forget_me(client)
    assert post(client, "push_subscribe", {"nope": 1}).status_code == 403
    assert post(client, "push_subscribe", body()).status_code == 403
    assert PushSubscription.objects.count() == 0


def test_bad_json_is_400(user_client, on):
    _, client = user_client
    r = client.post(
        reverse("notifications:push_subscribe"),
        data="{not json",
        content_type="application/json",
    )
    assert r.status_code == 400


def test_wrong_types_are_400(user_client, on):
    _, client = user_client
    for payload in (
        {"endpoint": 5, "keys": {}},
        {"endpoint": FCM + "x", "keys": "k"},
        [1],
    ):
        assert post(client, "push_subscribe", payload).status_code == 400


def test_disallowed_host_is_400(user_client, on):
    _, client = user_client
    r = post(client, "push_subscribe", body("https://evil.example/x"))
    assert r.status_code == 400


# --- subscribe --------------------------------------------------------------------


def test_subscribe_creates_a_keyed_row_and_remembers_the_endpoint(user_client, on):
    user, client = user_client
    r = post(client, "push_subscribe", body())
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = PushSubscription.objects.get()
    assert row.user == user
    assert row.session_key == client.session.session_key
    assert client.session["push_endpoint"] == FCM + "dev1"


def test_subscribe_moves_an_endpoint_from_another_user(user_client, on):
    user, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "dev1")
    post(client, "push_subscribe", body())
    assert PushSubscription.objects.get().user == user


def test_sixth_subscribe_evicts_only_this_users_oldest(user_client, on):
    user, client = user_client
    other = UserFactory()
    other_row = make_sub(
        other,
        "o" * 32,
        endpoint=FCM + "other",
        subscribed_at=timezone.now() - timedelta(days=30),
    )
    base = timezone.now() - timedelta(days=10)
    rows = [
        make_sub(
            user,
            "k" * 32,
            endpoint=f"{FCM}old{i}",
            subscribed_at=base + timedelta(days=i),
        )
        for i in range(5)
    ]
    post(client, "push_subscribe", body(FCM + "new"))
    remaining = set(
        PushSubscription.objects.filter(user=user).values_list("endpoint", flat=True)
    )
    assert rows[0].endpoint not in remaining
    assert len(remaining) == 5 and FCM + "new" in remaining
    assert PushSubscription.objects.filter(pk=other_row.pk).exists()


def test_resubscribing_an_old_endpoint_keeps_it(user_client, on):
    # mutant: not excluding the current endpoint from the cap
    user, client = user_client
    long_ago = timezone.now() - timedelta(days=100)
    old = make_sub(user, "k" * 32, endpoint=FCM + "dev1", subscribed_at=long_ago)
    PushSubscription.objects.filter(pk=old.pk).update(created_at=long_ago)
    for i in range(5):
        make_sub(user, "k" * 32, endpoint=f"{FCM}new{i}")
    post(client, "push_subscribe", body(FCM + "dev1"))
    assert PushSubscription.objects.filter(endpoint=FCM + "dev1").exists()
    assert PushSubscription.objects.filter(user=user).count() == 5


def test_cap_evicts_by_subscribed_at_not_created_at(user_client, on):
    # mutant: cap ordered by created_at. A was CREATED first but RE-SUBSCRIBED
    # last; B is the oldest by subscribed_at. Only B may go.
    user, client = user_client
    now = timezone.now()
    a = make_sub(
        user, "k" * 32, endpoint=FCM + "A", subscribed_at=now - timedelta(hours=1)
    )
    PushSubscription.objects.filter(pk=a.pk).update(created_at=now - timedelta(days=99))
    make_sub(user, "k" * 32, endpoint=FCM + "B", subscribed_at=now - timedelta(days=50))
    for i in range(3):
        make_sub(
            user,
            "k" * 32,
            endpoint=f"{FCM}mid{i}",
            subscribed_at=now - timedelta(days=10 - i),
        )
    post(client, "push_subscribe", body(FCM + "sixth"))
    left = set(
        PushSubscription.objects.filter(user=user).values_list("endpoint", flat=True)
    )
    assert FCM + "A" in left and FCM + "B" not in left and len(left) == 5


def test_concurrent_insert_integrity_error_retries_as_update(user_client, on):
    user, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "dev1")
    with mock.patch(
        "notifications.models.PushSubscription.objects.update_or_create",
        side_effect=IntegrityError("dup"),
    ):
        r = post(client, "push_subscribe", body())
    assert r.status_code == 200
    assert PushSubscription.objects.get(endpoint=FCM + "dev1").user == user


# --- unsubscribe ------------------------------------------------------------------


def test_unsubscribe_deletes_own_row_and_clears_the_entry(user_client, on):
    _, client = user_client
    post(client, "push_subscribe", body())
    r = post(client, "push_unsubscribe", {"endpoint": FCM + "dev1"})
    assert r.json() == {"ok": True}
    assert PushSubscription.objects.count() == 0
    assert "push_endpoint" not in client.session


def test_unsubscribe_of_another_users_endpoint_deletes_nothing(user_client, on):
    _, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "theirs")
    r = post(client, "push_unsubscribe", {"endpoint": FCM + "theirs"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert PushSubscription.objects.count() == 1


# --- claim ------------------------------------------------------------------------


def test_claim_own_row_rekeys_and_sets_the_entry(user_client, on):
    user, client = user_client
    row = make_sub(user, "stale" * 8, endpoint=FCM + "dev1")
    r = post(client, "push_claim", {"endpoint": FCM + "dev1"})
    assert r.json() == {"mine": True}
    row.refresh_from_db()
    assert row.session_key == client.session.session_key
    assert client.session["push_endpoint"] == FCM + "dev1"


def test_claim_other_users_row_deletes_it(user_client, on):
    _, client = user_client
    make_sub(UserFactory(), "x" * 32, endpoint=FCM + "dev1")
    r = post(client, "push_claim", {"endpoint": FCM + "dev1"})
    assert r.json() == {"mine": False}
    assert PushSubscription.objects.count() == 0


def test_claim_with_no_row_creates_nothing(user_client, on):
    _, client = user_client
    r = post(client, "push_claim", {"endpoint": FCM + "dev1"})
    assert r.json() == {"mine": False}
    assert PushSubscription.objects.count() == 0


def test_claim_in_a_not_remembered_session_deletes_own_row(user_client, on):
    user, client = user_client
    make_sub(user, "x" * 32, endpoint=FCM + "dev1")
    forget_me(client)
    r = post(client, "push_claim", {"endpoint": FCM + "dev1"})
    assert r.json() == {"mine": False}
    assert PushSubscription.objects.count() == 0


def test_claim_after_rotation_rekeys_and_delivers_again(user_client, on):
    from notifications.models import Notification
    from notifications.push import deliver_notification_push

    user, client = user_client
    post(client, "push_subscribe", body())
    session = client.session
    session.cycle_key()  # as login / password change do; the row's key goes stale
    session.save()
    client.cookies["sessionid"] = session.session_key
    r = post(client, "push_claim", {"endpoint": FCM + "dev1"})
    assert r.json() == {"mine": True}
    assert PushSubscription.objects.get().session_key == client.session.session_key
    n = Notification.objects.create(
        recipient=user,
        kind="enrolled",
        target_type="course",
        target_id=1,
        data={"course_title": "C", "course_slug": "c"},
    )
    with mock.patch("pywebpush.webpush") as webpush:
        deliver_notification_push(n)
    webpush.assert_called_once()


def test_claim_with_a_non_string_endpoint_is_400(user_client, on):
    _, client = user_client
    assert post(client, "push_claim", {"endpoint": 7}).status_code == 400
