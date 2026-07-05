from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from integrations import flush
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def _pending(**kw):
    return WebhookDelivery.objects.create(dedupe_key="1:", payload={"e": "x"}, **kw)


def test_flush_noop_when_disabled():
    _pending()  # endpoint absent/disabled
    result = flush.flush_pending()
    assert result["sent"] == 0
    assert WebhookDelivery.objects.get().status == WebhookDelivery.Status.PENDING


def test_flush_sends_only_due_rows():
    _enable()
    due = _pending()
    _pending(next_attempt_at=timezone.now() + timedelta(hours=1))  # future

    def fake_deliver(row, endpoint):
        row.status = WebhookDelivery.Status.DELIVERED
        row.save(update_fields=["status"])

    with mock.patch.object(flush, "deliver_one", side_effect=fake_deliver) as m:
        flush.flush_pending()
    assert m.call_count == 1
    due.refresh_from_db()
    assert due.status == WebhookDelivery.Status.DELIVERED


def test_flush_respects_limit():
    _enable()
    for _ in range(3):
        _pending()
    with mock.patch.object(flush, "deliver_one") as m:
        flush.flush_pending(limit=2)
    assert m.call_count == 2
