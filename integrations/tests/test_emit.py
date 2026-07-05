from decimal import Decimal

import pytest
from django.db import transaction

from grouping.models import GroupMembership
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from integrations.services import emit_result_finalized
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory

pytestmark = pytest.mark.django_db


def _enable_endpoint():
    ep = WebhookEndpoint.load()
    ep.enabled = True
    ep.url = "https://register.example/hook"
    ep.secret = "shh"
    ep.save()


def _finalized_submission(course_external_id="MATH-A"):
    """A SUBMITTED, auto-marked (no [R]) submission with a scored result."""
    sub = QuizSubmissionFactory(
        status="submitted", score=Decimal("8.00"), max_score=Decimal("10.00")
    )
    course = sub.unit.course
    course.external_id = course_external_id
    course.save(update_fields=["external_id"])
    return sub


def test_no_endpoint_configured_is_noop():
    sub = _finalized_submission()  # endpoint row absent / disabled
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    assert WebhookDelivery.objects.count() == 0


def test_course_without_external_id_is_noop():
    _enable_endpoint()
    sub = _finalized_submission(course_external_id="")
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    assert WebhookDelivery.objects.count() == 0


def test_no_group_yields_one_null_group_delivery():
    _enable_endpoint()
    sub = _finalized_submission()
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.all())
    assert len(rows) == 1
    assert rows[0].payload["group"] is None
    assert rows[0].dedupe_key == f"{sub.pk}:"


def test_payload_shape_and_score():
    _enable_endpoint()
    sub = _finalized_submission()
    student = sub.student
    student.external_id = "S-123"
    student.save(update_fields=["external_id"])
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    p = WebhookDelivery.objects.get().payload
    assert p["event"] == "result_finalized"
    assert p["student"]["external_id"] == "S-123"
    assert p["course"]["external_id"] == "MATH-A"
    assert p["unit"]["id"] == sub.unit_id
    assert p["score"] == {"earned": "8.00", "max": "10.00", "percent": 80.0}
    assert "T" in p["finalized_at"]  # ISO-8601


def test_fanout_two_groups_blank_external_id_both_survive():
    _enable_endpoint()
    sub = _finalized_submission()
    course = sub.unit.course
    g1 = GroupFactory(course=course)  # external_id blank (default)
    g2 = GroupFactory(course=course)
    GroupMembership.objects.create(group=g1, student=sub.student)
    GroupMembership.objects.create(group=g2, student=sub.student)
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.all())
    assert len(rows) == 2  # keyed on group_id, not blank external_id
    keys = {r.dedupe_key for r in rows}
    assert keys == {f"{sub.pk}:{g1.pk}", f"{sub.pk}:{g2.pk}"}
    ids = {r.payload["group"]["id"] for r in rows}
    assert ids == {g1.pk, g2.pk}


def test_archived_group_excluded():
    _enable_endpoint()
    sub = _finalized_submission()
    course = sub.unit.course
    live = GroupFactory(course=course)
    archived = GroupFactory(course=course, archived=True)
    GroupMembership.objects.create(group=live, student=sub.student)
    GroupMembership.objects.create(group=archived, student=sub.student)
    with transaction.atomic():
        emit_result_finalized(sub, already_final=True)
    rows = list(WebhookDelivery.objects.all())
    assert len(rows) == 1
    assert rows[0].payload["group"]["id"] == live.pk
