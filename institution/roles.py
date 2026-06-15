from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission

STUDENT = "Student"
TEACHER = "Teacher"
COURSE_ADMIN = "Course Admin"
PLATFORM_ADMIN = "Platform Admin"

ROLE_NAMES = [STUDENT, TEACHER, COURSE_ADMIN, PLATFORM_ADMIN]

# Phase 0 ships only account/institution-management permissions, assigned to
# Platform Admin (spec §2). Later phases attach their own permissions to the
# relevant roles. Codenames are Django's auto-generated add/change/delete/view.
COURSE_PERMS = [
    "courses.add_course",
    "courses.change_course",
    "courses.delete_course",
    "courses.view_course",
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
]


def _permission(label):
    app_label, codename = label.split(".")
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def seed_roles():
    """Create the four role Groups (idempotent) and assign Phase-0 permissions to
    Platform Admin. Permissions must already exist, so run this after `migrate`
    (the setup_roles command and the DoD do exactly that)."""
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLE_NAMES}
    groups[PLATFORM_ADMIN].permissions.set(
        [_permission(label) for label in PLATFORM_ADMIN_PERMS]
    )
