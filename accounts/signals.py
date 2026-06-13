from allauth.account.signals import user_signed_up
from django.contrib.auth.models import Group
from django.dispatch import receiver

from institution.roles import STUDENT


@receiver(user_signed_up)
def assign_default_student_group(sender, request, user, **kwargs):
    """New local self-signups default to the Student group (spec §2). Roles are
    Groups seeded in Plan 0a; we never branch on role *name* in app logic."""
    group, _ = Group.objects.get_or_create(name=STUDENT)
    user.groups.add(group)
