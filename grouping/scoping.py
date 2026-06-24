from django.contrib.auth import get_user_model
from django.db.models import Q

from courses.models import Enrollment
from grouping.models import Collection
from grouping.models import Group
from grouping.models import GroupMembership


def _is_platform_admin(user):
    # Convention (mirrors courses/views_manage.py): the PA group alone holds
    # courses.change_course. Never branch on the role *name*.
    return user.has_perm("courses.change_course")


def _owner_or_course_q(user):
    return Q(owner=user) | Q(course__owner=user)


def groups_manageable_by(user):
    """Groups a user may create/edit/delete. Includes archived rows; list views
    apply the active/archived filter on top.

    NOTE on owner-less courses: `courses.Course.owner` is nullable
    (`on_delete=SET_NULL`). A course with `owner=None` matches no CA via
    `course__owner=user` and is therefore PA-manageable only, by design — a CA
    only manages groups on courses they explicitly own."""
    if _is_platform_admin(user):
        return Group.objects.all()
    if user.has_perm("grouping.change_group"):  # Course Admin
        return Group.objects.filter(course__owner=user)
    return Group.objects.none()


def groups_visible_to(user):
    """Manageable groups plus groups the user teaches (read access)."""
    manageable = groups_manageable_by(user)
    taught = Group.objects.filter(teachers=user)
    return (manageable | taught).distinct()


def collections_manageable_by(user):
    if _is_platform_admin(user):
        return Collection.objects.all()
    if user.has_perm("grouping.change_collection"):  # Teacher or Course Admin
        # Teacher: collections they own. Course Admin: + collections on courses
        # they own (owner-less courses are PA-only, as in groups_manageable_by).
        return Collection.objects.filter(_owner_or_course_q(user)).distinct()
    return Collection.objects.none()


def can_add_collection_group(user, group):
    if _is_platform_admin(user):
        return True
    if group.course.owner_id == user.id:  # Course Admin owns the course
        return True
    return group.teachers.filter(pk=user.pk).exists()  # Teacher teaches it


def reviewable_students(user, course):
    """Students whose quiz submissions `user` may review/force-submit in `course`.

    PA or course owner -> all enrolled students (Enrollment is the superset of
    anyone who could have a QuizSubmission). Group teacher -> students in the
    non-archived groups they teach/manage on this course. Else -> none.
    """
    User = get_user_model()
    if _is_platform_admin(user) or course.owner_id == user.id:
        student_ids = Enrollment.objects.filter(course=course).values("student_id")
        return User.objects.filter(pk__in=student_ids)
    group_ids = (
        groups_visible_to(user).filter(course=course, archived=False).values("pk")
    )
    student_ids = GroupMembership.objects.filter(group_id__in=group_ids).values(
        "student_id"
    )
    return User.objects.filter(pk__in=student_ids)


def can_review_course(user, course):
    """Whether `user` has any review reach on `course` (the page-level gate)."""
    if _is_platform_admin(user) or (
        course.owner_id is not None and course.owner_id == user.id
    ):
        return True
    return groups_visible_to(user).filter(course=course, archived=False).exists()
