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
    return Notification.objects.create(
        recipient=recipient,
        kind=kind,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        data=data or {},
    )


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
