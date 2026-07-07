"""Resolves notification recipients (teachers for a group/course, reviewers)."""

from django.contrib.auth import get_user_model

User = get_user_model()


def teachers_for(student, course):
    """Distinct union of Group.teachers across the student's non-archived groups
    for `course`. Front-line group teachers only (not the inverse of
    reviewable_students — owner/PA reach is deliberately not fanned out)."""
    return list(
        User.objects.filter(
            taught_groups__course=course,
            taught_groups__archived=False,
            taught_groups__memberships__student=student,
        ).distinct()
    )


def review_recipients(submission):
    """teachers_for(...) if non-empty, else [course.owner] (empty if owner None).
    The fallback triggers on an EMPTY resolved-teacher set — covers both a
    no-group student and a member of a teacher-less non-archived group."""
    course = submission.unit.course
    teachers = teachers_for(submission.student, course)
    if teachers:
        return teachers
    owner = course.owner
    return [owner] if owner is not None else []
