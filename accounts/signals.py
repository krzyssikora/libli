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
    """New local self-signups default to the Student group (spec §2). Roles are
    Groups seeded in Plan 0a; we never branch on role *name* in app logic."""
    group, _ = Group.objects.get_or_create(name=STUDENT)
    user.groups.add(group)


@receiver(post_save, sender=Invitation)
def send_invitation_on_create(sender, instance, created, **kwargs):
    """Email the invite link once, after the row actually commits (so a rolled-back
    admin save sends nothing, and there is no ordering race in tests)."""
    if created:
        transaction.on_commit(lambda: send_invitation_email(instance))
