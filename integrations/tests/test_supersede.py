from decimal import Decimal

import pytest
from django.db import transaction

from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from integrations.services import emit_result_finalized
from tests.factories import QuizSubmissionFactory

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def _sub(score="8.00"):
    sub = QuizSubmissionFactory(
        status="submitted", score=Decimal(score), max_score=Decimal("10.00")
    )
    c = sub.unit.course
    c.external_id = "MATH-A"
    c.save(update_fields=["external_id"])
    return sub


def test_correction_supersedes_prior_pending():
    _enable()
    sub = _sub("8.00")
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    sub.score = Decimal("9.00")
    sub.save(update_fields=["score"])
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.order_by("id"))
    assert len(rows) == 2
    assert rows[0].status == WebhookDelivery.Status.SUPERSEDED
    assert rows[1].status == WebhookDelivery.Status.PENDING
    assert rows[1].payload["score"]["earned"] == "9.00"


def test_delivered_row_is_not_superseded():
    _enable()
    sub = _sub("8.00")
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    first = WebhookDelivery.objects.get()
    first.status = WebhookDelivery.Status.DELIVERED
    first.save(update_fields=["status"])
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    first.refresh_from_db()
    assert first.status == WebhookDelivery.Status.DELIVERED  # untouched
    assert (
        WebhookDelivery.objects.filter(status=WebhookDelivery.Status.PENDING).count()
        == 1
    )
