from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from grouping.models import Collection


@receiver(post_save, sender=User)
def ensure_cohort_membership(sender, instance, created, **kwargs):
    """Every newly-created student joins the current Default cohort. Staff users
    (is_staff/superuser/Teacher/Course Admin/Platform Admin) are skipped — cohorts
    are for students only.

    Deliberately NOT the allauth `user_signed_up` signal (which fires only for
    self-signups) — cohort membership must cover admin/fixture/SSO-JIT creation
    too. Idempotent via get_or_create; a no-op if no Default exists yet (e.g.
    mid-backfill, which seeds memberships directly against historical models)."""
    if not created:
        return
    from grouping import services

    services.sync_default_cohort_membership(instance)


@receiver(m2m_changed, sender=get_user_model().groups.through)
def sync_cohort_on_role_change(sender, instance, action, reverse, pk_set, **kwargs):
    """Re-sync cohort membership when a user's role groups change.

    A student promoted to a staff role must leave Default; a staff user demoted
    back to student must rejoin Default. Fires on post_add/post_remove/post_clear
    so the membership state always reflects the current role set."""
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    from grouping import services

    UserModel = get_user_model()
    if not reverse:
        # instance is the User whose groups changed (incl. post_clear)
        services.sync_default_cohort_membership(instance)
    elif pk_set:
        # instance is a Group; pk_set are the affected user ids
        for user in UserModel.objects.filter(pk__in=pk_set):
            services.sync_default_cohort_membership(user)


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
