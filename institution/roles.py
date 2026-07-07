"""RBAC role definitions and seed_roles (role groups and permissions)."""

from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.utils.translation import gettext_lazy as _

STUDENT = "Student"
TEACHER = "Teacher"
COURSE_ADMIN = "Course Admin"
PLATFORM_ADMIN = "Platform Admin"

ROLE_NAMES = [STUDENT, TEACHER, COURSE_ADMIN, PLATFORM_ADMIN]

# Translatable display labels for the 4 roles. gettext_lazy (NOT gettext): this
# dict is built at module import, and eager gettext would freeze the labels to the
# import-time language. This is the single display source — the role column,
# filters, and selects all render through it; the Group name stays the storage key.
ROLE_LABELS = {
    STUDENT: _("Student"),
    TEACHER: _("Teacher"),
    COURSE_ADMIN: _("Course Admin"),
    PLATFORM_ADMIN: _("Platform Admin"),
}

# (group_name, label) pairs for model `choices` and form selects. Labels are the
# SAME ROLE_LABELS — never a parallel set.
ROLE_CHOICES = [(name, ROLE_LABELS[name]) for name in ROLE_NAMES]


def role_is_staff(role):
    """True for every role except Student. Used by set_user_role to derive is_staff."""
    return role != STUDENT


# Phase 0 ships only account/institution-management permissions, assigned to
# Platform Admin (spec §2). Later phases attach their own permissions to the
# relevant roles. Codenames are Django's auto-generated add/change/delete/view.
COURSE_PERMS = [
    "courses.add_course",
    "courses.change_course",
    "courses.delete_course",
    "courses.view_course",
]

# Subjects are PA-only taxonomy (Phase 5a). view_subject is intentionally
# omitted — the only audience is the PA, who holds change_subject.
SUBJECT_PERMS = [
    "courses.add_subject",
    "courses.change_subject",
    "courses.delete_subject",
]

PLATFORM_ADMIN_PERMS = [
    "accounts.add_user",
    "accounts.change_user",
    "accounts.view_user",
    "accounts.delete_user",
    "institution.change_institution",
    "institution.view_institution",
    "institution.add_brandcolor",
    "institution.change_brandcolor",
    "institution.delete_brandcolor",
    "institution.view_brandcolor",
    *COURSE_PERMS,
    *SUBJECT_PERMS,
]

GROUPING_TEACHER_PERMS = [
    "grouping.view_group",
    "grouping.add_collection",
    "grouping.change_collection",
    "grouping.delete_collection",
    "grouping.view_collection",
]

GROUPING_COURSE_ADMIN_PERMS = [
    "grouping.add_group",
    "grouping.change_group",
    "grouping.delete_group",
    "grouping.view_group",
    "grouping.view_cohort",
    "grouping.add_collection",
    "grouping.change_collection",
    "grouping.delete_collection",
    "grouping.view_collection",
]

GROUPING_PLATFORM_ADMIN_PERMS = [
    "grouping.add_cohort",
    "grouping.change_cohort",
    "grouping.delete_cohort",
    "grouping.view_cohort",
    "grouping.add_group",
    "grouping.change_group",
    "grouping.delete_group",
    "grouping.view_group",
    "grouping.add_collection",
    "grouping.change_collection",
    "grouping.delete_collection",
    "grouping.view_collection",
]


def _permission(label):
    app_label, codename = label.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def seed_roles():
    """Create the four role Groups (idempotent) and assign their permissions.
    Permissions must already exist, so run this AFTER `migrate` (the setup_roles
    command and the DoD do exactly that)."""
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLE_NAMES}
    groups[PLATFORM_ADMIN].permissions.set(
        [
            _permission(label)
            for label in PLATFORM_ADMIN_PERMS + GROUPING_PLATFORM_ADMIN_PERMS
        ]
    )
    groups[TEACHER].permissions.set(
        [_permission(label) for label in GROUPING_TEACHER_PERMS]
    )
    groups[COURSE_ADMIN].permissions.set(
        [_permission(label) for label in GROUPING_COURSE_ADMIN_PERMS]
    )
