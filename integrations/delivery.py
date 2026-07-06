"""Send one WebhookDelivery: sign, POST via stdlib urllib, record outcome with
exponential backoff. No new dependency; no redirects (SSRF); 4xx/5xx raise."""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from datetime import timedelta

from django.utils import timezone

from integrations.models import WebhookDelivery

logger = logging.getLogger(__name__)

BACKOFF = [1, 5, 15, 60, 180, 360, 720]  # minutes; index by (attempts-1), clamped
MAX_ATTEMPTS = 8
TIMEOUT_SECONDS = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect refused", headers, fp
        )


def _build_opener():
    # build_opener keeps HTTPErrorProcessor (so 4xx/5xx raise HTTPError); we only
    # swap the redirect handler for one that refuses redirects.
    return urllib.request.build_opener(_NoRedirect)


def sign(secret, body):
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _schedule(attempts):
    return BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]


def deliver_one(delivery, endpoint):
    body = json.dumps(delivery.payload).encode("utf-8")
    # endpoint.url scheme (http/https) is validated by the settings form (Task 3);
    # this is never user-supplied at request time, so the bandit URL-scheme audit
    # is a false positive here.
    req = urllib.request.Request(  # noqa: S310
        endpoint.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Libli-Event": delivery.event,
            "X-Libli-Delivery": str(delivery.pk),
            "X-Libli-Signature": sign(endpoint.secret, body),
        },
    )
    try:
        opener = _build_opener()
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
        if not (200 <= status < 300):
            raise urllib.error.HTTPError(endpoint.url, status, "non-2xx", None, None)
    except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        _record_failure(delivery, exc)
        return
    delivery.status = WebhookDelivery.Status.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["status", "delivered_at", "last_error"])


def _record_failure(delivery, exc):
    delivery.attempts += 1
    delivery.last_error = f"{type(exc).__name__}: {exc}"[:2000]
    if delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = WebhookDelivery.Status.DEAD
    else:
        delivery.next_attempt_at = timezone.now() + timedelta(
            minutes=_schedule(delivery.attempts)
        )
    delivery.save(update_fields=["attempts", "last_error", "status", "next_attempt_at"])
    logger.warning("webhook delivery %s failed: %s", delivery.pk, delivery.last_error)


# Sample body for the "Send test event" button. Shape-identical to a real
# delivery, but marked "test": true (and X-Libli-Delivery: test) and using
# obvious placeholder ids so a receiver can verify the signature without
# ingesting it. finalized_at is a fixed literal (matches the guide's sample).
SAMPLE_PAYLOAD = {
    "test": True,
    "event": "result_finalized",
    "finalized_at": "2026-07-06T10:15:30.123456+00:00",
    "student": {
        "external_id": "SAMPLE-STUDENT",
        "email": "sample.student@example.edu",
        "name": "Sample Student",
    },
    "course": {
        "external_id": "SAMPLE-COURSE",
        "slug": "sample-course",
        "title": "Sample Course",
    },
    "group": {"id": 0, "external_id": "SAMPLE-GROUP", "name": "Sample Group"},
    "unit": {"id": 0, "title": "Sample Unit"},
    "score": {"earned": "8.00", "max": "10.00", "percent": 80.0},
}


def send_test_event(endpoint):
    """Synchronously POST one signed SAMPLE_PAYLOAD to the endpoint. Reuses
    sign()/_build_opener(), persists nothing, and never raises: returns
    (ok, status, detail) so the view always gets a tuple and never 500s."""
    body = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        endpoint.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Libli-Event": "result_finalized",
            "X-Libli-Delivery": "test",
            "X-Libli-Signature": sign(endpoint.secret, body),
        },
    )
    try:
        opener = _build_opener()
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
        if 200 <= status < 300:
            return (True, status, "")
        # Defensive no-op: _build_opener() keeps HTTPErrorProcessor, so a non-2xx
        # normally raises HTTPError (caught below) before reaching here — mirrors
        # deliver_one's handling.
        return (False, status, f"HTTP {status}")
    except urllib.error.HTTPError as exc:
        return (False, exc.code, f"HTTP {exc.code}")
    except (TimeoutError, urllib.error.URLError) as exc:
        return (False, None, f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # e.g. a malformed URL urllib rejects pre-flight
        return (False, None, f"{type(exc).__name__}: {exc}")
