"""Flush loop: select candidate ids first (no long lock), then process each in
its own short skip_locked transaction so a slow POST never holds locks across
unrelated rows."""

from django.db import transaction
from django.utils import timezone

from integrations.delivery import deliver_one
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint


def flush_pending(limit=100):
    endpoint = WebhookEndpoint.objects.filter(pk=1).first()
    if endpoint is None or not endpoint.enabled or not endpoint.url:
        return {"sent": 0, "skipped": 0}
    ids = list(
        WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.PENDING,
            next_attempt_at__lte=timezone.now(),
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    sent = skipped = 0
    for pk in ids:
        with transaction.atomic():
            row = (
                WebhookDelivery.objects.select_for_update(skip_locked=True)
                .filter(pk=pk, status=WebhookDelivery.Status.PENDING)
                .first()
            )
            if row is None:  # taken by a concurrent run, or superseded
                skipped += 1
                continue
            deliver_one(row, endpoint)
            sent += 1
    return {"sent": sent, "skipped": skipped}
