"""Web push (PWA C2): every push decision lives here.

Spec: docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md. This module
top-level-imports only django.conf and the standard library; the notifications
models, core and emails are imported function-locally (emails.py top-level-imports
services.py, which imports THIS module function-locally) -- keep it that way.
"""

import base64
import binascii
import contextvars
import json
import logging
import re
from time import monotonic
from urllib.parse import urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

# Real push services only (spec §4). Matched exactly or as a dot-suffix, so
# "evilfcm.googleapis.com" and "fcm.googleapis.com.evil.example" are refused.
PUSH_ENDPOINT_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, Samsung Internet
    "push.services.mozilla.com",  # Firefox
    "push.apple.com",  # Safari, iOS home-screen apps
    "notify.windows.com",  # Edge on Windows
)
MAX_ENDPOINT_LENGTH = 1024
MAX_SUBSCRIPTIONS_PER_USER = 5
PUSH_TIMEOUT = 5
PUSH_TTL = 86400
PUSH_BUDGET_SECONDS = 10.0

_B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def push_configured():
    """True only when this box can actually deliver a push (spec §1)."""
    from core.pwa import serve_normal

    subject = settings.PUSH_VAPID_SUBJECT or ""
    return bool(
        settings.PUSH_VAPID_PUBLIC_KEY
        and settings.PUSH_VAPID_PRIVATE_KEY
        and subject.startswith(("mailto:", "https:"))
        and serve_normal()
    )


def remembered_from_data(data):
    """D8: is this login meant to outlive the browser? `data` is any mapping with
    .get(): request.session itself, or Session.get_decoded(). Same fallback as
    SessionBase.get_expire_at_browser_close()."""
    expiry = data.get("_session_expiry")
    if expiry is None:
        return not settings.SESSION_EXPIRE_AT_BROWSER_CLOSE
    return expiry != 0


def endpoint_host_allowed(endpoint):
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in PUSH_ENDPOINT_HOSTS)


def decode_b64url(value):
    if not isinstance(value, str) or not _B64URL.fullmatch(value):
        return None
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return None


def clean_subscription(body):
    """(endpoint, p256dh, auth) from a PushSubscription.toJSON() body, or None."""
    if not isinstance(body, dict):
        return None
    endpoint = body.get("endpoint")
    keys = body.get("keys")
    if not isinstance(endpoint, str) or not isinstance(keys, dict):
        return None
    if len(endpoint) > MAX_ENDPOINT_LENGTH or not endpoint_host_allowed(endpoint):
        return None
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    raw_p, raw_a = decode_b64url(p256dh), decode_b64url(auth)
    if raw_p is None or raw_a is None:
        return None
    if len(raw_p) != 65 or raw_p[0] != 4 or len(raw_a) != 16:
        return None
    if len(p256dh) > 128 or len(auth) > 64:
        return None
    return endpoint, p256dh, auth


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate_vapid_pair():
    """(public, private): the uncompressed P-256 point PushManager.subscribe takes,
    and the raw 32-byte scalar pywebpush accepts, both base64url without padding."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)


def push_kind_enabled(user, kind):
    """True when the user has no push preference row (default-on), else the per-kind
    boolean. An unknown kind raises later -- AttributeError here when a row exists, else
    ValueError in email_content -- and delivery swallows both."""
    from notifications.models import NotificationPushPreference

    pref = NotificationPushPreference.objects.filter(user=user).first()
    if pref is None:
        return True
    return getattr(pref, kind)


# --- per-request budget (spec §3, latency bound 3) ---------------------------------

_BUDGET = contextvars.ContextVar("libli_push_budget", default=None)


def reset_push_budget():
    _BUDGET.set(None)


def _budget_allows():
    state = _BUDGET.get()
    now = monotonic()
    if state is None:
        _BUDGET.set({"deadline": now + PUSH_BUDGET_SECONDS, "warned": False})
        return True
    if now < state["deadline"]:
        return True
    if not state["warned"]:
        logger.warning(
            "push budget exhausted; skipping remaining pushes in this request"
        )
        state["warned"] = True
    return False


# --- live sessions (D7, D8) ------------------------------------------------------


def _session_is_live_for(data, user):
    from django.contrib.auth import HASH_SESSION_KEY
    from django.contrib.auth import SESSION_KEY
    from django.utils.crypto import constant_time_compare

    if not user.is_active or data.get(SESSION_KEY) != str(user.pk):
        return False
    stored = data.get(HASH_SESSION_KEY) or ""
    hashes = [user.get_session_auth_hash(), *user.get_session_auth_fallback_hash()]
    if not any(constant_time_compare(stored, h) for h in hashes):
        return False
    return remembered_from_data(data)


def live_subscriptions(user):
    """The user's subscriptions whose session is live, authenticated as this user with
    a current auth hash, active and remembered. The rest are deleted -- conditionally
    on the stale key, so a row a concurrent claim re-keyed survives."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    from notifications.models import PushSubscription

    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        return []
    keys = {s.session_key for s in subs}
    sessions = Session.objects.filter(
        session_key__in=keys, expire_date__gt=timezone.now()
    )
    live = {
        s.session_key for s in sessions if _session_is_live_for(s.get_decoded(), user)
    }
    dead = keys - live
    if dead:
        PushSubscription.objects.filter(
            pk__in=[s.pk for s in subs if s.session_key in dead],
            session_key__in=dead,
        ).delete()
    return [s for s in subs if s.session_key in live]


# --- payload + delivery (spec §3) --------------------------------------------------


def _icon_url():
    from django.templatetags.static import static

    from core.services import get_site_config

    return get_site_config().get("favicon_url") or static(
        "core/img/favicon/icon-192.png"
    )


def build_payload(notification):
    from django.urls import reverse
    from django.utils import translation

    from notifications.emails import email_content

    lang = notification.recipient.language or settings.LANGUAGE_CODE
    with translation.override(lang):
        _subject, headline, body_line = email_content(notification)
    return json.dumps(
        {
            "title": headline,
            "body": body_line,
            "url": reverse("notifications:open", args=[notification.pk]),
            "tag": f"libli-{notification.pk}",
            "icon": _icon_url(),
        }
    )


def _send_one(sub, data, notification):
    from django.utils import timezone
    from pywebpush import WebPushException
    from pywebpush import webpush

    from notifications.models import PushSubscription

    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=data,
            vapid_private_key=settings.PUSH_VAPID_PRIVATE_KEY,
            # FRESH per call: webpush writes aud/exp into the dict it is given.
            vapid_claims={"sub": settings.PUSH_VAPID_SUBJECT},
            ttl=PUSH_TTL,
            timeout=PUSH_TIMEOUT,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            PushSubscription.objects.filter(pk=sub.pk).delete()
            return
        logger.warning(
            "push delivery failed (subscription %s, notification %s, status %s)",
            sub.pk,
            notification.pk,
            status,
        )
        return
    except Exception:  # noqa: BLE001 -- one device never stops the next
        logger.exception(
            "push delivery failed (subscription %s, notification %s)",
            sub.pk,
            notification.pk,
        )
        return
    PushSubscription.objects.filter(pk=sub.pk).update(last_success_at=timezone.now())


def deliver_notification_push(notification):
    """Push one notification to the recipient's live devices. Runs in a post-commit
    callback; the WHOLE body is log-and-swallow (Django stops the on_commit chain at
    the first callback that raises -- see deliver_notification_email)."""
    try:
        if not push_configured():
            return
        user = notification.recipient
        if not push_kind_enabled(user, notification.kind):
            return
        subs = live_subscriptions(user)
        if not subs:
            return
        data = build_payload(notification)
        for sub in subs:
            if not _budget_allows():
                return
            _send_one(sub, data, notification)
    except Exception:  # noqa: BLE001 -- never break the request / fan-out
        logger.exception("push delivery failed (notification %s)", notification.pk)
