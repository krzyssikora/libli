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
