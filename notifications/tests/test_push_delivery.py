"""§3: deliver_notification_push decisions, payload, error handling, independence."""

import json
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import translation
from pywebpush import WebPushException

from notifications import services
from notifications.emails import email_content
from notifications.models import Notification
from notifications.models import NotificationEmailPreference
from notifications.models import NotificationPushPreference
from notifications.models import PushSubscription
from notifications.push import deliver_notification_push
from notifications.push import push_kind_enabled as real_push_kind_enabled
from notifications.tests.push_helpers import FCM
from notifications.tests.push_helpers import MOZ
from notifications.tests.push_helpers import live_session_for
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _graded(recipient, course=None):
    course = course or CourseFactory()
    return Notification.objects.create(
        recipient=recipient,
        kind=Notification.Kind.QUIZ_GRADED,
        target_type=Notification.TargetType.COURSE,
        target_id=course.pk,
        data={
            "course_title": course.title,
            "course_slug": course.slug,
            "unit_title": "Quiz 1",
            "node_pk": 999,
        },
    )


@pytest.fixture
def webpush():
    with mock.patch("pywebpush.webpush") as m:
        yield m


@pytest.fixture
def subscribed(settings):
    push_settings(settings)
    user = UserFactory(email="stu@example.com")
    sub = make_sub(user, live_session_for(user))
    return user, sub


def _payload(call):
    return json.loads(call.kwargs["data"])


def test_not_configured_sends_nothing(webpush):
    user = UserFactory()
    make_sub(user, live_session_for(user))
    deliver_notification_push(_graded(user))
    webpush.assert_not_called()


def test_kind_off_sends_nothing(webpush, subscribed):
    user, _ = subscribed
    NotificationPushPreference.objects.create(user=user, quiz_graded=False)
    deliver_notification_push(_graded(user))
    webpush.assert_not_called()


def test_no_subscriptions_sends_nothing(webpush, settings):
    push_settings(settings)
    deliver_notification_push(_graded(UserFactory()))
    webpush.assert_not_called()


def test_sends_with_the_documented_call_shape(webpush, subscribed, settings):
    user, sub = subscribed
    n = _graded(user)
    deliver_notification_push(n)
    call = webpush.call_args
    assert call.kwargs["subscription_info"] == {
        "endpoint": sub.endpoint,
        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
    }
    assert call.kwargs["vapid_private_key"] == settings.PUSH_VAPID_PRIVATE_KEY
    assert call.kwargs["vapid_claims"] == {"sub": "mailto:ops@example.com"}
    assert call.kwargs["ttl"] == 86400
    assert call.kwargs["timeout"] == 5
    payload = _payload(call)
    assert payload["url"] == reverse("notifications:open", args=[n.pk])
    assert payload["tag"] == f"libli-{n.pk}"
    sub.refresh_from_db()
    assert sub.last_success_at is not None


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_payload_text_is_the_email_wording_in_the_recipient_language(
    webpush, subscribed, lang
):
    user, _ = subscribed
    user.language = lang
    user.save()
    n = _graded(user)
    deliver_notification_push(n)
    with translation.override(lang):
        _s, headline, body_line = email_content(n)
    payload = _payload(webpush.call_args)
    assert (payload["title"], payload["body"]) == (headline, body_line)


def test_real_pywebpush_encrypts_and_signs_with_our_keys(settings):
    """The ONE test that runs the real library (every other test mocks webpush): our
    key format, the stored p256dh/auth and our kwargs must produce a real request.
    Only the HTTP call is patched. pywebpush 2.x posts via requests.post when no
    session is passed -- confirm in .venv/Lib/site-packages/pywebpush/__init__.py
    (WebPusher.send) and patch whatever it calls if that differs."""
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from notifications.push import _b64url

    push_settings(settings)
    receiver = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    user = UserFactory()
    sub = make_sub(
        user,
        live_session_for(user),
        endpoint=FCM + "real",
        p256dh=_b64url(receiver),
        auth=_b64url(os.urandom(16)),
    )
    response = mock.Mock(status_code=201, text="", headers={})
    with mock.patch("requests.post", return_value=response) as http:
        deliver_notification_push(_graded(user))
    http.assert_called_once()
    args, kwargs = http.call_args
    assert (args[0] if args else kwargs["url"]) == FCM + "real"
    headers = {k.lower(): v for k, v in kwargs["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["ttl"] == "86400"
    assert headers["authorization"].startswith("vapid t=")
    assert f"k={settings.PUSH_VAPID_PUBLIC_KEY}" in headers["authorization"]
    assert kwargs["timeout"] == 5
    sub.refresh_from_db()
    assert sub.last_success_at is not None


def test_icon_is_the_static_default_without_an_override(webpush, subscribed):
    user, _ = subscribed
    deliver_notification_push(_graded(user))
    assert _payload(webpush.call_args)["icon"].endswith("core/img/favicon/icon-192.png")


def test_icon_is_the_favicon_override_when_set(webpush, subscribed):
    user, _ = subscribed
    with mock.patch(
        "core.services.get_site_config",
        return_value={"favicon_url": "/media/branding/fav.png"},
    ):
        deliver_notification_push(_graded(user))
    assert _payload(webpush.call_args)["icon"] == "/media/branding/fav.png"


def test_push_ignores_the_email_gates(webpush, settings):
    push_settings(settings)
    user = UserFactory(email="")  # blank email still pushes
    NotificationEmailPreference.objects.create(user=user, quiz_graded=False)
    make_sub(user, live_session_for(user))
    deliver_notification_push(_graded(user))
    webpush.assert_called_once()


def test_each_call_gets_its_own_claims_dict(webpush, settings):
    # mutant: one vapid_claims dict hoisted out of the loop
    push_settings(settings)
    user = UserFactory()
    key = live_session_for(user)
    make_sub(user, key, endpoint=FCM + "a")
    make_sub(user, key, endpoint=MOZ + "b")
    deliver_notification_push(_graded(user))
    first, second = webpush.call_args_list
    assert first.kwargs["vapid_claims"] is not second.kwargs["vapid_claims"]


@pytest.mark.parametrize("status", [404, 410])
def test_gone_subscription_is_deleted(webpush, subscribed, status):
    user, sub = subscribed
    webpush.side_effect = WebPushException(
        "gone", response=mock.Mock(status_code=status)
    )
    deliver_notification_push(_graded(user))
    assert not PushSubscription.objects.filter(pk=sub.pk).exists()


def test_other_error_logs_and_the_next_subscription_still_goes(
    webpush, settings, caplog
):
    push_settings(settings)
    user = UserFactory()
    key = live_session_for(user)
    first = make_sub(user, key, endpoint=FCM + "a")
    make_sub(user, key, endpoint=FCM + "b")
    webpush.side_effect = [
        WebPushException("boom", response=mock.Mock(status_code=500)),
        None,
    ]
    deliver_notification_push(_graded(user))
    assert webpush.call_count == 2
    assert PushSubscription.objects.filter(pk=first.pk).exists()
    assert "push" in caplog.text.lower()


def test_unknown_kind_is_swallowed(webpush, subscribed):
    user, _ = subscribed
    n = Notification.objects.create(
        recipient=user, kind="bogus_kind", target_type="course", target_id=1, data={}
    )
    deliver_notification_push(n)  # must not raise
    webpush.assert_not_called()


def test_muted_notify_creates_nothing(webpush, subscribed):
    user, _ = subscribed
    with services.muted():
        services.notify_enrolled(user, CourseFactory())
    assert Notification.objects.count() == 0
    webpush.assert_not_called()


# --- independence (spec §10) -------------------------------------------------------


def test_email_failure_still_pushes(
    webpush, subscribed, django_capture_on_commit_callbacks
):
    # mutant: email's log-and-swallow removed (deliver_notification_email lets
    # send() raise)
    user, _ = subscribed
    with mock.patch(
        "django.core.mail.EmailMultiAlternatives.send", side_effect=RuntimeError("smtp")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            services.notify_enrolled(user, CourseFactory())
    webpush.assert_called_once()


def test_first_teachers_push_failure_does_not_stop_the_second_teacher(
    settings, django_capture_on_commit_callbacks
):
    # mutant: the try in deliver_notification_push narrowed so push_kind_enabled
    # sits outside it
    push_settings(settings)
    first = UserFactory(email="t1@example.com")
    second = UserFactory(email="t2@example.com")
    make_sub(first, live_session_for(first), endpoint=FCM + "t1")
    make_sub(second, live_session_for(second), endpoint=FCM + "t2")

    def boom_for_first(user, kind):
        if user.pk == first.pk:
            raise RuntimeError("pref lookup failed")
        return real_push_kind_enabled(user, kind)

    course = CourseFactory()
    with (
        mock.patch("notifications.push.push_kind_enabled", side_effect=boom_for_first),
        mock.patch("pywebpush.webpush") as webpush,
        django_capture_on_commit_callbacks(execute=True),
    ):
        services.notify_enrolled(first, course)
        services.notify_enrolled(second, course)
    endpoints = [
        c.kwargs["subscription_info"]["endpoint"] for c in webpush.call_args_list
    ]
    assert endpoints == [FCM + "t2"]
    assert {m.to[0] for m in mail.outbox} == {"t1@example.com", "t2@example.com"}
