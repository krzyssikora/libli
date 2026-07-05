import pytest
from django.utils import timezone

from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def test_endpoint_load_is_singleton():
    a = WebhookEndpoint.load()
    a.enabled = True
    a.url = "https://register.example/hook"
    a.save()
    b = WebhookEndpoint.load()
    assert a.pk == 1 and b.pk == 1
    assert b.enabled is True
    assert b.url == "https://register.example/hook"
    assert WebhookEndpoint.objects.count() == 1


def test_delivery_defaults():
    row = WebhookDelivery.objects.create(dedupe_key="7:3", payload={"x": 1})
    assert row.status == WebhookDelivery.Status.PENDING
    assert row.event == WebhookDelivery.Event.RESULT_FINALIZED
    assert row.attempts == 0
    assert row.last_error == ""
    assert row.delivered_at is None
    # default=timezone.now makes a fresh row immediately due
    assert row.next_attempt_at <= timezone.now()
