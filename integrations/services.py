"""Outbound grade-sync: the emit choke-point. Called INSIDE the caller's
transaction.atomic() block via a function-local import (the emit sites import
from courses/grouping, so a top-level import here would cycle)."""

from django.utils import timezone

from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint


def dedupe_key(submission_pk, group):
    """Delivery identity: submission (pins student+unit+course) + the stable
    Group.pk (NOT the blankable external_id — two unmapped groups must not
    collide). Empty group segment for the no-group delivery."""
    return f"{submission_pk}:{group.pk if group is not None else ''}"


def _percent(earned, maximum):
    if not maximum:
        return 0
    return round(float(earned) / float(maximum) * 100, 2)


def build_payload(submission, course, group):
    student = submission.student
    unit = submission.unit
    return {
        "event": WebhookDelivery.Event.RESULT_FINALIZED.value,
        "finalized_at": timezone.now().isoformat(),
        "student": {
            "external_id": student.external_id,
            "email": student.email or "",
            "name": student.display_name or student.username,
        },
        "course": {
            "external_id": course.external_id,
            "slug": course.slug,
            "title": course.title,
        },
        "group": (
            None
            if group is None
            else {"id": group.pk, "external_id": group.external_id, "name": group.name}
        ),
        "unit": {"id": unit.pk, "title": unit.title},
        "score": {
            "earned": str(submission.score),
            "max": str(submission.max_score),
            "percent": _percent(submission.score, submission.max_score),
        },
    }


def _student_groups(course, student):
    from grouping.models import Group

    return list(
        Group.objects.filter(
            course=course, archived=False, memberships__student=student
        ).distinct()
    )


def emit_result_finalized(submission, *, already_final=False):
    """Enqueue outbox deliveries for a finalized quiz result. No-op unless the
    endpoint is enabled AND the course has a subject code. Call inside the
    caller's atomic() block. `already_final=True` (review-completion path) skips
    the auto-final check; the submit paths pass False and this checks it."""
    endpoint = WebhookEndpoint.objects.filter(pk=1).first()
    if endpoint is None or not endpoint.enabled:
        return
    course = submission.unit.course
    if not course.external_id:
        return
    if not already_final:
        from courses.review import submission_review_state

        if submission_review_state(submission)["total"] != 0:
            return  # has [R] questions → not final at submit time
    assert submission.score is not None and submission.max_score is not None, (
        "emit_result_finalized called before score/max_score were populated"
    )
    groups = _student_groups(course, submission.student) or [None]
    for group in groups:
        _enqueue(submission, course, group)


def _enqueue(submission, course, group):
    WebhookDelivery.objects.create(
        dedupe_key=dedupe_key(submission.pk, group),
        payload=build_payload(submission, course, group),
    )
