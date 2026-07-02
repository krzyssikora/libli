from django.db import transaction

from courses.models import Course
from courses.models import QuizSubmission
from notifications.models import Notification


def _resolve_target(target):
    """Map a domain object to (target_type, target_id). No None case."""
    if isinstance(target, QuizSubmission):
        return (Notification.TargetType.SUBMISSION, target.pk)
    if isinstance(target, Course):
        return (Notification.TargetType.COURSE, target.pk)
    raise TypeError(f"Unsupported notification target: {type(target)!r}")


def notify(*, recipient, kind, target, actor=None, data=None):
    """Record a notification. No-op (returns None) when recipient == actor.
    Call inside the emit site's transaction.atomic() block."""
    if actor is not None and recipient == actor:
        return None
    target_type, target_id = _resolve_target(target)
    n = Notification.objects.create(
        recipient=recipient,
        kind=kind,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        data=data or {},
    )
    # Function-local import: emails.py top-level-imports this module, so a top-level
    # import here would cycle at load. Deferring to call time breaks the cycle.
    from notifications.emails import deliver_notification_email

    transaction.on_commit(lambda: deliver_notification_email(n))
    return n


def unread_count(user):
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def recent_for(user, limit):
    return Notification.objects.filter(recipient=user)[:limit]


def notify_needs_review(submission, actor):
    """Fan a quiz-needs-review notification out to the front-line teachers of the
    submitting student's group(s), or the course owner fallback. No-op when the
    unit has no [R] questions. Call inside the caller's atomic block, only on the
    not-SUBMITTED -> SUBMITTED transition branch (the guard lives at the call site)."""
    from courses.review import submission_review_state
    from notifications.recipients import review_recipients

    if submission_review_state(submission)["total"] == 0:
        return
    course = submission.unit.course
    data = {
        "course_title": course.title,
        "course_slug": course.slug,
        "unit_title": submission.unit.title,
        # carried for parity with quiz_graded; this kind's link uses target_id,
        # not node_pk
        "node_pk": submission.unit_id,
        "student_name": str(submission.student),
    }
    for teacher in review_recipients(submission):
        notify(
            recipient=teacher,
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW,
            target=submission,
            actor=actor,
            data=data,
        )


def notify_graded(submission, reviewer):
    course = submission.unit.course
    notify(
        recipient=submission.student,
        kind=Notification.Kind.QUIZ_GRADED,
        target=submission,
        actor=reviewer,
        data={
            "course_title": course.title,
            "course_slug": course.slug,
            "unit_title": submission.unit.title,
            "node_pk": submission.unit_id,
        },
    )


def notify_enrolled(student, course, actor=None):
    notify(
        recipient=student,
        kind=Notification.Kind.ENROLLED,
        target=course,
        actor=actor,
        data={"course_title": course.title, "course_slug": course.slug},
    )


def notification_url(notification):
    """Reverse the target URL from denormalized `data` (no DB load). None when
    the identifiers are missing or the route can't be reversed.

    Note: guard falsy ids explicitly — `reverse(..., kwargs={"slug": None})` does
    NOT raise; Django coerces None -> "None" and it matches the slug regex
    (yielding a bogus "/courses/None/"). So NoReverseMatch alone is insufficient.
    """
    from django.urls import NoReverseMatch
    from django.urls import reverse

    data = notification.data or {}
    slug = data.get("course_slug")
    if not slug:
        return None
    try:
        if notification.kind == Notification.Kind.QUIZ_NEEDS_REVIEW:
            return reverse(
                "courses:manage_review_submission",
                kwargs={"slug": slug, "submission_pk": notification.target_id},
            )
        if notification.kind == Notification.Kind.QUIZ_GRADED:
            node_pk = data.get("node_pk")
            if not node_pk:
                return None
            return reverse(
                "courses:quiz_results",
                kwargs={"slug": slug, "node_pk": node_pk},
            )
        if notification.kind == Notification.Kind.ENROLLED:
            return reverse("courses:course_outline", kwargs={"slug": slug})
    except NoReverseMatch:
        return None
    return None
