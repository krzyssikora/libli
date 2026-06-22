from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User


@receiver(post_save, sender=User)
def ensure_cohort_membership(sender, instance, created, **kwargs):
    """Every newly-created user joins the current Default cohort.

    Deliberately NOT the allauth `user_signed_up` signal (which fires only for
    self-signups) — cohort membership must cover admin/fixture/SSO-JIT creation
    too. Idempotent via get_or_create; a no-op if no Default exists yet (e.g.
    mid-backfill, which seeds memberships directly against historical models)."""
    if not created:
        return
    from grouping.models import Cohort
    from grouping.models import CohortMembership

    default = Cohort.objects.filter(is_default=True).first()
    if default is None:
        return
    CohortMembership.objects.get_or_create(user=instance, defaults={"cohort": default})
