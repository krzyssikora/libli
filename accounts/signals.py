from allauth.account.signals import user_signed_up
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.invitations import send_invitation_email
from accounts.models import Invitation
from institution.roles import STUDENT


@receiver(user_signed_up)
def assign_default_student_group(sender, request, user, **kwargs):
    """New self-signups default to Student — UNLESS a role was already assigned
    (e.g. an SSO invite consumed via set_user_role in the adapter's save_user, which
    runs before this signal). Skipping then preserves the exactly-one-role invariant.
    Open local self-signup (no set_user_role) still lands Student here."""
    from institution.roles import ROLE_NAMES

    if user.groups.filter(name__in=ROLE_NAMES).exists():
        return
    group, _ = Group.objects.get_or_create(name=STUDENT)
    user.groups.add(group)


@receiver(post_save, sender=Invitation)
def send_invitation_on_create(sender, instance, created, **kwargs):
    """Email the invite link once, after the row actually commits.

    on_commit: a rolled-back admin save sends nothing and there is no ordering
    race in tests. if created: updates (e.g. setting accepted_at) never re-send."""
    if created:
        transaction.on_commit(lambda: send_invitation_email(instance))
