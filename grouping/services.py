from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from grouping.models import Cohort
from grouping.models import CohortMembership


def get_default_cohort():
    return Cohort.objects.filter(is_default=True).first()


@transaction.atomic
def promote_default(cohort):
    """Make `cohort` the sole default. Demote the current default FIRST, then
    promote, so the partial unique index never sees two True rows."""
    Cohort.objects.filter(is_default=True).exclude(pk=cohort.pk).update(
        is_default=False
    )
    if not cohort.is_default:
        cohort.is_default = True
        cohort.save(update_fields=["is_default"])


def assign_student_to_cohort(user, cohort, *, assigned_by=None):
    """In-place reassignment: update the OneToOne row, never delete+recreate."""
    CohortMembership.objects.update_or_create(
        user=user, defaults={"cohort": cohort, "assigned_by": assigned_by}
    )


def _guard_not_default(cohort):
    if cohort.is_default:
        raise ValidationError(
            _("The default cohort cannot be removed; designate another default first.")
        )


def _reassign_members_to_default(cohort):
    default = get_default_cohort()
    CohortMembership.objects.filter(cohort=cohort).update(cohort=default)


@transaction.atomic
def archive_cohort(cohort):
    _guard_not_default(cohort)
    _reassign_members_to_default(cohort)
    cohort.archived = True
    cohort.save(update_fields=["archived"])


@transaction.atomic
def delete_cohort(cohort):
    _guard_not_default(cohort)
    _reassign_members_to_default(cohort)
    cohort.delete()
