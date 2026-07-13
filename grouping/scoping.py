"""Role-scoped querysets and permission checks for groups and collections."""

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


def collections_visible_to(user, course):
    """Collections on `course` the user may report on: manageable ∪ those whose
    groups include a NON-archived group the user teaches. Excludes archived
    collections (parity with the group filter). See spec §2."""
    manageable = collections_manageable_by(user).filter(course=course, archived=False)
    taught = Collection.objects.filter(
        course=course,
        archived=False,
        groups__teachers=user,
        groups__archived=False,
    )
    # Combine by pk membership, NOT `manageable | taught`: collections_manageable_by
    # returns a `.distinct()` queryset (unlike groups_manageable_by), and OR-ing a
    # distinct queryset with a non-distinct one raises "Cannot combine a unique query
    # with a non-unique query." pk__in over each side's ids is distinct-agnostic and
    # inherently de-duplicated, so no trailing .distinct() is needed.
    return Collection.objects.filter(
        Q(pk__in=manageable.values("pk")) | Q(pk__in=taught.values("pk"))
    )


def analytics_scope_choices(user, course):
    """Picker options: "All my students" + each visible non-archived group +
    each visible collection on the course."""
    from django.utils.translation import gettext as _

    choices = [{"value": "all", "label": _("All my students")}]
    for g in (
        groups_visible_to(user).filter(course=course, archived=False).order_by("name")
    ):
        choices.append({"value": f"group:{g.pk}", "label": g.name})
    for c in collections_visible_to(user, course).order_by("name"):
        choices.append({"value": f"collection:{c.pk}", "label": c.name})
    return choices


def students_in_scope(user, course, scope):
    """Resolve a scope value to a student queryset, always re-deriving from the
    user's reach. Unreachable/malformed scope -> default ("all"). See spec §2."""
    User = get_user_model()
    if scope and scope != "all" and ":" in scope:
        prefix, _, raw_pk = scope.partition(":")
        try:
            pk = int(raw_pk)
        except (TypeError, ValueError):
            pk = None
        if pk is not None and prefix == "group":
            if (
                groups_visible_to(user)
                .filter(pk=pk, course=course, archived=False)
                .exists()
            ):
                student_ids = GroupMembership.objects.filter(group_id=pk).values(
                    "student_id"
                )
                return User.objects.filter(pk__in=student_ids).distinct()
        elif pk is not None and prefix == "collection":
            if collections_visible_to(user, course).filter(pk=pk).exists():
                student_ids = GroupMembership.objects.filter(
                    group__collections=pk, group__archived=False
                ).values("student_id")
                return User.objects.filter(pk__in=student_ids).distinct()
    # default / fallback
    return reviewable_students(user, course)
