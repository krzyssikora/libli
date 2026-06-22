from django.db.models import Q

from grouping.models import Collection
from grouping.models import Group


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
