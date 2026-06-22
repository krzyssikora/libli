from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from grouping.models import Collection


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


@receiver(m2m_changed, sender=Collection.groups.through)
def validate_collection_group_course(sender, instance, action, pk_set, **kwargs):
    """Defense-in-depth (non-form code paths): every group must share the
    collection's course. Raises to abort the surrounding transaction."""
    if action != "pre_add" or not pk_set:
        return
    from grouping.models import Group

    mismatched = (
        Group.objects.filter(pk__in=pk_set)
        .exclude(course_id=instance.course_id)
        .exists()
    )
    if mismatched:
        raise ValidationError(
            _("All groups in a collection must belong to the collection's course.")
        )
