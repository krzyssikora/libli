import hashlib
import hmac
from unittest import mock

import pytest
from django.utils import timezone

from integrations import delivery
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.django_db


def _endpoint():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/hook", TEST_PASSWORD
    ep.save()
    return ep


def _row():
    return WebhookDelivery.objects.create(dedupe_key="1:", payload={"event": "x"})


def test_sign_prefixes_and_matches():
    sig = delivery.sign(TEST_PASSWORD, b'{"a":1}')
    expected = hmac.new(TEST_PASSWORD.encode(), b'{"a":1}', hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


def test_deliver_success_marks_delivered():
    ep = _endpoint()
    row = _row()
    resp = mock.MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: resp
    resp.__exit__ = lambda *a: False
    opener = mock.MagicMock()
    opener.open.return_value = resp
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        delivery.deliver_one(row, ep)
    row.refresh_from_db()
    assert row.status == WebhookDelivery.Status.DELIVERED
    assert row.delivered_at is not None
    # signature header computed over the exact bytes sent
    sent_req = opener.open.call_args.args[0]
    body = sent_req.data
    assert sent_req.headers["X-libli-signature"] == delivery.sign(ep.secret, body)


def test_deliver_failure_reschedules_by_backoff():
    import urllib.error

    ep = _endpoint()
    row = _row()
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.URLError("down")
    before = timezone.now()
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        delivery.deliver_one(row, ep)
    row.refresh_from_db()
    assert row.status == WebhookDelivery.Status.PENDING
    assert row.attempts == 1
    assert row.last_error
    # first failure → BACKOFF[0] == 1 minute out
    assert (row.next_attempt_at - before).total_seconds() >= 55


def test_deliver_dead_after_max_attempts():
    import urllib.error

    ep = _endpoint()
    row = _row()
    row.attempts = delivery.MAX_ATTEMPTS - 1  # this failure is the 8th
    row.save(update_fields=["attempts"])
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.URLError("down")
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        delivery.deliver_one(row, ep)
    row.refresh_from_db()
    assert row.status == WebhookDelivery.Status.DEAD
