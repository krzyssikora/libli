"""Platform-admin people services: the single role-swap point + lockout guards."""

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from accounts.invitations import send_invitation_email
from accounts.models import INVITE_TTL
from accounts.models import Invitation
from accounts.models import User
from accounts.provisioning import resolve_user_for_email
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


class InvitationError(Exception):
    """An invite cannot be sent (e.g. the email already has an account)."""


def create_or_refresh_invitation(*, email, role, invited_by):
    """Send (or refresh + resend) an invite for `email` carrying `role`.

    The existing-account rejection (active OR inactive) is evaluated FIRST, before
    the pending-refresh path, so a registered email is never refreshed into a dead
    invite. resolve_user_for_email is case-insensitive.
    """
    existing = resolve_user_for_email(email)
    if existing is not None:
        if existing.is_active:
            raise InvitationError("An active account already uses this email.")
        raise InvitationError(
            "This email belongs to a deactivated user — reactivate them instead."
        )
    pending = Invitation.find_pending(email)
    if pending is not None:
        pending.role = role
        pending.invited_by = invited_by
        pending.expires_at = timezone.now() + INVITE_TTL
        pending.save(update_fields=["role", "invited_by", "expires_at"])
        # Refresh is NOT a create, so the post_save `send_invitation_on_create`
        # signal does not fire — send explicitly here.
        send_invitation_email(pending)
        return pending, False
    invitation = Invitation.objects.create(
        email=email, role=role, invited_by=invited_by
    )
    # Create: the EXISTING post_save `send_invitation_on_create` signal
    # (accounts/signals.py) emails the link via transaction.on_commit. Do NOT call
    # send_invitation_email here, or a new invite is emailed twice (the Django-admin
    # invite path also relies on that signal).
    return invitation, True


def invitation_feedback(email):
    """User-facing feedback for a just-sent invitation, as (level, text) pairs.

    Always carries the success line; appends a warning when the email's domain
    falls outside the institution allowlist. Centralised so the People admin and
    the first-run setup wizard surface identical feedback. The `create` itself
    stays at each call site, since they handle InvitationError differently.
    Levels map to django.contrib.messages methods (success/warning).
    """
    from accounts.provisioning import email_domain
    from accounts.provisioning import normalized_allowlist
    from institution.models import Institution

    msgs = [("success", gettext("Invitation sent."))]
    allowed = normalized_allowlist(Institution.load().allowed_email_domains)
    domain = email_domain(email)
    if allowed and domain not in allowed:
        msgs.append(
            (
                "warning",
                gettext("Note: %(domain)s is not in your allowed email domains.")
                % {"domain": domain},
            )
        )
    return msgs


def revoke_invitation(invitation):
    """Revoke a pending invite by deleting the row (it carries no user data)."""
    invitation.delete()


def resend_invitation(invitation):
    """Re-send a pending invite, refreshing expiry explicitly (save() won't)."""
    invitation.expires_at = timezone.now() + INVITE_TTL
    invitation.save(update_fields=["expires_at"])
    send_invitation_email(invitation)
