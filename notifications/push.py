"""Web push (PWA C2): every push decision lives here.

Spec: docs/superpowers/specs/2026-10-16-pwa-c2-web-push-design.md. This module
top-level-imports only django.conf and the standard library; the notifications
models, core and emails are imported function-locally (emails.py top-level-imports
services.py, which imports THIS module function-locally) -- keep it that way.
"""

import base64
import binascii
import logging
import re
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
    if not isinstance(value, str) or not _B64URL.match(value):
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
