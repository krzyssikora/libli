from decimal import Decimal

import pytest

from courses.review import review_response
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import make_review_submission

pytestmark = pytest.mark.django_db


def _enable():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = True, "https://r.example/h", "shh"
    ep.save()


def test_completion_enqueues_and_recorrection_re_pushes():
    _enable()
    ctx = make_review_submission(course_external_id="MATH-A")  # 1 [R] question
    reviewer = ctx["reviewer"]
    element = ctx["review_element"]
    submission = ctx["submission"]
    # Complete the review -> completion transition emits once.
    review_response(
        submission=submission,
        element=element,
        earned_marks=Decimal("3.00"),
        feedback="ok",
        reviewer=reviewer,
    )
    assert (
        WebhookDelivery.objects.filter(status=WebhookDelivery.Status.PENDING).count()
        == 1
    )
    # A correction that changes the score re-pushes (supersede + new).
    review_response(
        submission=submission,
        element=element,
        earned_marks=Decimal("2.00"),
        feedback="revised",
        reviewer=reviewer,
    )
    pending = WebhookDelivery.objects.filter(status=WebhookDelivery.Status.PENDING)
    assert pending.count() == 1
    assert pending.get().payload["score"]["earned"] != "3.00"


def test_feedback_only_correction_does_not_re_push():
    _enable()
    ctx = make_review_submission(course_external_id="MATH-A")
    reviewer, element, submission = (
        ctx["reviewer"],
        ctx["review_element"],
        ctx["submission"],
    )
    review_response(
        submission=submission,
        element=element,
        earned_marks=Decimal("3.00"),
        feedback="ok",
        reviewer=reviewer,
    )
    before = WebhookDelivery.objects.count()
    # Same marks, different feedback -> score unchanged -> no new delivery.
    review_response(
        submission=submission,
        element=element,
        earned_marks=Decimal("3.00"),
        feedback="typo fixed",
        reviewer=reviewer,
    )
    assert WebhookDelivery.objects.count() == before
