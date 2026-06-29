"""Platform-admin people services: the single role-swap point + lockout guards."""

from django.contrib.auth.models import Group
from django.db import transaction

from accounts.models import User
from institution.roles import PLATFORM_ADMIN
from institution.roles import role_is_staff


def set_user_role(user, role):
    """Make `user` hold exactly the one role Group named `role`, syncing is_staff.

    Order matters and is pinned: is_staff is set + saved BEFORE groups.set, because
    the Phase-3a cohort m2m_changed receiver reads `user.is_staff` during
    `groups.set` to decide Default-cohort membership. If groups changed first, a
    Teacher->Student demote would still look like staff at signal time and not be
    rejoined to the Default cohort. Superusers always keep is_staff=True (Django
    admin login requires it — the recovery path); is_superuser is never modified.
    Runs atomic so the staff write, group swap, and cohort sync commit together.
    """
    if not role:
        raise ValueError("set_user_role requires a non-empty role name")
    # get_or_create (NOT get): preserves the prior _consume_and_create behavior so
    # accept/SSO flows that have not called seed_roles still work; setup_roles
    # assigns the perms in prod. (Using .get would raise Group.DoesNotExist and
    # turn existing non-seeded accept/SSO tests red.)
    group, _ = Group.objects.get_or_create(name=role)
    with transaction.atomic():
        user.is_staff = role_is_staff(role) or user.is_superuser
        user.save(update_fields=["is_staff"])
        # Full replace is safe: auth Groups hold only the 4 roles in this app.
        user.groups.set([group])


def is_last_active_platform_admin(user, *, lock=False):
    """True iff `user` is the ONLY active member of the Platform Admin group.

    Counts by group membership; superusers outside the PA group are a separate
    recovery path and are not counted. Pass lock=True inside a transaction to take
    a row lock (authoritative check that closes the deactivate/demote TOCTOU window).
    """
    qs = User.objects.filter(is_active=True, groups__name=PLATFORM_ADMIN)
    if lock:
        qs = qs.select_for_update()
    ids = list(qs.values_list("id", flat=True))
    return ids == [user.id]
