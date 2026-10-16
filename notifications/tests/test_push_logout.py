"""§4 Logout: driven through the real account_logout view (a receiver that is never
connected fails these)."""

import json

import pytest
from django.urls import reverse

from notifications.models import PushSubscription
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from notifications.tests.test_push_endpoints import body
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _subscribe(client):
    client.post(
        reverse("notifications:push_subscribe"),
        data=json.dumps(body()),
        content_type="application/json",
    )


def test_logout_deletes_the_sessions_row_only(client, settings):
    push_settings(settings)
    user = logged_in_user(client)
    _subscribe(client)
    other_device = make_sub(user, "y" * 32, endpoint=FCM + "phone")
    client.post(reverse("account_logout"))
    assert list(PushSubscription.objects.all()) == [other_device]


def test_logout_without_an_entry_is_a_noop(client, settings):
    push_settings(settings)
    user = logged_in_user(client)
    row = make_sub(user, "y" * 32)
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.filter(pk=row.pk).exists()


def test_logout_deletes_even_when_push_is_off_now(client, settings):
    push_settings(settings)
    logged_in_user(client)
    _subscribe(client)
    settings.PUSH_VAPID_PUBLIC_KEY = ""  # keys blanked after subscribing
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.count() == 0


def test_subscription_from_an_earlier_session_is_deleted_after_a_claim(
    client, settings
):
    push_settings(settings)
    user = logged_in_user(client)  # a new session that has never seen the endpoint
    make_sub(user, "earlier" * 5, endpoint=FCM + "dev1")
    client.post(
        reverse("notifications:push_claim"),
        data=json.dumps({"endpoint": FCM + "dev1"}),
        content_type="application/json",
    )
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.count() == 0


def test_logout_via_confirmation_page_still_deletes(client, settings):
    push_settings(settings)
    logged_in_user(client)
    _subscribe(client)
    assert client.get(reverse("account_logout")).status_code == 200  # confirm page
    client.post(reverse("account_logout"))
    assert PushSubscription.objects.count() == 0


def test_receiver_ignores_a_none_user_and_a_missing_request():
    # Through the signal, not a direct import, so this test cannot connect the
    # receivers for later tests and mask the "ready() import removed" mutant.
    # NOTE: every send also reaches core/signals.py:clear_theme_cookie_on_logout,
    # which sets an attribute on any non-None request -- so pass a real request
    # object (a bare object() would raise there), one with NO .session to
    # exercise our guard.
    from django.contrib.auth.signals import user_logged_out
    from django.test import RequestFactory

    user_logged_out.send(sender=None, request=None, user=UserFactory())
    user_logged_out.send(
        sender=None, request=RequestFactory().get("/"), user=UserFactory()
    )
    user_logged_out.send(sender=None, request=RequestFactory().get("/"), user=None)
