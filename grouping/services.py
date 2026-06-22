from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from courses.models import Enrollment
from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.models import GroupMembership
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER


def student_users():
    """Users eligible to be cohort/group members: the Student role, excluding
    anyone who also holds a staff role. Cohorts/group-rosters are for learners,
    not teachers/admins (teachers attach to a group via the separate teachers M2M)."""
    return (
        User.objects.filter(groups__name=STUDENT)
        .exclude(groups__name__in=[TEACHER, COURSE_ADMIN, PLATFORM_ADMIN])
        .distinct()
    )


def get_default_cohort():
    return Cohort.objects.filter(is_default=True).first()


@transaction.atomic
def promote_default(cohort):
    """Make `cohort` the sole default. Demote the current default FIRST, then
    promote, so the partial unique index never sees two True rows. Promoting a
    cohort also un-archives it: a default cohort must never be archived (it would
    vanish from pickers yet still auto-receive new members)."""
    Cohort.objects.filter(is_default=True).exclude(pk=cohort.pk).update(
        is_default=False
    )
    fields = []
    if not cohort.is_default:
        cohort.is_default = True
        fields.append("is_default")
    if cohort.archived:
        cohort.archived = False
        fields.append("archived")
    if fields:
        cohort.save(update_fields=fields)


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


def _is_reachable(student, course):
    return GroupMembership.objects.filter(
        student=student, group__course=course, group__archived=False
    ).exists()


def recompute_enrollment(student, course):
    """Sync Enrollment for (student, course) to group reachability. Idempotent;
    safe under concurrency. Self/manual sources are never downgraded; a
    group-reachable student is never stranded."""
    reachable = _is_reachable(student, course)
    enrollment = Enrollment.objects.filter(student=student, course=course).first()
    if reachable and enrollment is None:
        try:
            with (
                transaction.atomic()
            ):  # savepoint: a racing create won't poison the batch
                Enrollment.objects.get_or_create(
                    student=student, course=course, defaults={"source": "group"}
                )
        except IntegrityError:
            pass  # concurrent create won; leave its row untouched
    elif not reachable and enrollment is not None and enrollment.source == "group":
        enrollment.delete()
    # else: self/manual immune, or reachable+group steady state -> no-op


@transaction.atomic
def add_students_to_group(group, students, *, added_by=None):
    for student in students:
        # Per-student savepoint: a unique-violation on one row (concurrent add)
        # rolls back only that student, never the whole batch.
        with transaction.atomic():
            GroupMembership.objects.get_or_create(
                group=group, student=student, defaults={"added_by": added_by}
            )
            recompute_enrollment(student, group.course)


@transaction.atomic
def remove_students_from_group(group, students):
    students = list(students)
    GroupMembership.objects.filter(group=group, student__in=students).delete()
    for student in students:
        with transaction.atomic():  # per-student savepoint (batch resilience)
            recompute_enrollment(student, group.course)


@transaction.atomic
def set_group_members(group, student_ids, *, added_by=None):
    """Diff the target student set against current members; add/remove the delta."""
    target = set(student_ids)
    current = set(group.memberships.values_list("student_id", flat=True))
    to_add = User.objects.filter(pk__in=(target - current))
    to_remove = User.objects.filter(pk__in=(current - target))
    add_students_to_group(group, to_add, added_by=added_by)
    remove_students_from_group(group, to_remove)


@transaction.atomic
def set_group_archived(group, archived):
    group.archived = archived
    group.save(update_fields=["archived"])
    student_ids = list(group.memberships.values_list("student_id", flat=True))
    for student in User.objects.filter(pk__in=student_ids):
        recompute_enrollment(student, group.course)


@transaction.atomic
def delete_group(group):
    course = group.course
    student_ids = list(group.memberships.values_list("student_id", flat=True))
    group.delete()
    for student in User.objects.filter(pk__in=student_ids):
        recompute_enrollment(student, course)


@transaction.atomic
def set_collection_groups(collection, group_ids):
    """Replace the collection's group set. The m2m_changed receiver enforces the
    single-course rule; wrapping in atomic() lets its ValidationError roll back."""
    collection.groups.set(group_ids)
