"""Grouping services: cohort membership, user resolution, default-cohort mgmt."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from courses.models import ContentNode
from courses.models import Course
from courses.models import Enrollment
from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.models import GroupMembership
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER


def student_users():
    """Users eligible to be cohort/group members: learners, i.e. anyone who is
    NOT staff. 'Staff' = holds a Teacher/Course Admin/Platform Admin role, or
    Django is_staff/is_superuser. Defined by EXCLUSION so users created via admin
    (who never received the Student role) still count as students."""
    return (
        User.objects.exclude(groups__name__in=[TEACHER, COURSE_ADMIN, PLATFORM_ADMIN])
        .exclude(is_staff=True)
        .exclude(is_superuser=True)
        .distinct()
    )


def teacher_users():
    """Staff eligible to be assigned as a group's teachers: holds a staff role
    (Teacher/Course Admin/Platform Admin) or Django is_staff/is_superuser."""
    return User.objects.filter(
        Q(groups__name__in=[TEACHER, COURSE_ADMIN, PLATFORM_ADMIN])
        | Q(is_staff=True)
        | Q(is_superuser=True)
    ).distinct()


def is_staff_user(user):
    """True if the user holds any staff role (Teacher/Course Admin/Platform Admin)
    or Django is_staff/is_superuser. Cohorts are for students (non-staff)."""
    return (
        user.is_staff
        or user.is_superuser
        or user.groups.filter(name__in=[TEACHER, COURSE_ADMIN, PLATFORM_ADMIN]).exists()
    )


def sync_default_cohort_membership(user):
    """Align a user's cohort membership with student status: staff hold NO cohort
    membership; a student has one (the Default, unless already assigned elsewhere)."""
    if is_staff_user(user):
        CohortMembership.objects.filter(user=user).delete()
    else:
        default = get_default_cohort()
        if default is not None:
            CohortMembership.objects.get_or_create(
                user=user, defaults={"cohort": default}
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


def catalog_courses_for(student):
    """Open courses this student may self-enroll in. Eligibility joins through the
    student's single cohort (CohortMembership.user); a student with NO membership
    matches only empty-set ("open to all") courses. The course must have >=1 unit
    (kind="unit", any unit_type). NOT ordered — the caller applies .order_by.
    .distinct() is required: the M2M OR-filter would otherwise emit one row per
    matching cohort. When cohort_id is None (no membership), the second Q arm
    degenerates to the empty-set arm, so the student matches only open-to-all
    courses (nothing extra)."""
    cohort_id = (
        CohortMembership.objects.filter(user=student)
        .values_list("cohort_id", flat=True)
        .first()
    )
    has_unit = ContentNode.objects.filter(
        course=OuterRef("pk"), kind="unit", published=True
    )
    return (
        Course.objects.filter(visibility="open")
        .filter(Q(self_enroll_cohorts__isnull=True) | Q(self_enroll_cohorts=cohort_id))
        .filter(Exists(has_unit))
        .distinct()
    )


def can_self_enroll(student, course):
    """Authoritative gate for the detail view and the enroll POST. Non-staff only,
    AND the course is in the student's catalog. Already-enrolled passes (the
    downstream enroll_self is an idempotent no-op)."""
    if is_staff_user(student):
        return False
    return catalog_courses_for(student).filter(pk=course.pk).exists()


def enroll_self(student, course):
    """Idempotent self-enroll. Performs NO eligibility check — the view is the sole
    gate. Never downgrades an existing group/manual row. Per-call savepoint so a
    concurrent create can't poison a surrounding transaction."""
    with transaction.atomic():
        enrollment, created = Enrollment.objects.get_or_create(
            student=student, course=course, defaults={"source": "self"}
        )
        if created:
            from notifications.services import notify_enrolled

            notify_enrolled(student, course, actor=student)
    return enrollment


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
                _, created = Enrollment.objects.get_or_create(
                    student=student, course=course, defaults={"source": "group"}
                )
                if created:
                    from notifications.services import notify_enrolled

                    notify_enrolled(student, course)
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


def allocation_columns(allocation):
    """The grid's columns: the allocation's non-archived groups, resolved ONCE
    per request and threaded through the token check, the value validation, and
    set_allocation_assignments.

    The redundant-looking `course=` filter is defence, not a fourth enforcement
    point: course scoping is deliberately not enforced against bulk-write paths,
    and the membership query below IS course-filtered — so a foreign-course
    column would render every affected row as unassigned and re-add on save."""
    return allocation.groups.filter(course=allocation.course, archived=False).order_by(
        "name"
    )


def _token(group_ids):
    return ",".join(str(pk) for pk in sorted(int(pk) for pk in group_ids))


def allocation_columns_token(columns):
    return _token(c.pk for c in columns)


def allocation_state_tokens(columns, student_ids, memberships=None):
    """{student_id: token} over `columns`. `memberships` is {student_id: set[int]}
    of the student's group ids across the whole course, as the render path already
    bucketed them; a student ABSENT from it means the empty set (never a KeyError,
    never a re-query). Omitting it costs exactly ONE bulk query, never one per
    student."""
    column_ids = {c.pk for c in columns}
    if memberships is None:
        memberships = {}
        rows = GroupMembership.objects.filter(
            student_id__in=student_ids, group__in=columns
        ).values_list("student_id", "group_id")
        for student_id, group_id in rows:
            memberships.setdefault(student_id, set()).add(group_id)
    return {
        sid: _token(memberships.get(sid, set()) & column_ids) for sid in student_ids
    }


def allocation_row_students(allocation):
    """The grid's row set — called by BOTH the render path and the save path, so
    the two cannot drift. Arm 2 deliberately ignores `archived`: restricting it
    would make a student who is on the grid only through an archived column
    invisible while their membership survives."""
    by_cohort = student_users().filter(
        cohort_membership__cohort__in=allocation.cohorts.all()
    )
    assigned = student_users().filter(
        group_memberships__group__in=allocation.groups.filter(course=allocation.course)
    )
    # pk-membership OR, never `qs_a | qs_b`: student_users() ends in .distinct()
    # and OR-ing a distinct queryset with a non-distinct one raises "Cannot
    # combine a unique query with a non-unique query" (see
    # scoping.collections_visible_to's comment).
    return User.objects.filter(
        Q(pk__in=by_cohort.values("pk")) | Q(pk__in=assigned.values("pk"))
    )


@transaction.atomic
def set_allocation_assignments(columns, assignments, *, added_by=None):
    """assignments: {student_id: (target_group_id_or_None, was_token_or_None)},
    where the target is an **int pk** or None — NEVER the raw posted string. The
    caller coerces; `column_by_id`'s keys are ints, so a str "12" would miss the
    dict and the row would be silently omitted.

    A row absent from the POST is OMITTED FROM THIS DICT ENTIRELY; within it, a
    target of None means "— none —". Returns the skipped student ids.

    Three rules, first match wins:
      1. no-op   — current_token == token_of(target); never written, never
                   reported, EVEN IF the current token differs from `-was`.
      2. mismatch — current_token != was_token (was_token None counts) → skip
                   and report.
      3. write   — add to the target FIRST, then remove from the other columns.
    """
    column_by_id = {c.pk: c for c in columns}
    student_ids = list(assignments)
    students = {u.pk: u for u in User.objects.filter(pk__in=student_ids)}
    current = allocation_state_tokens(columns, student_ids)
    skipped = []
    for student_id, (target_id, was_token) in assignments.items():
        student = students.get(student_id)
        if student is None:
            continue
        target = column_by_id.get(target_id) if target_id is not None else None
        if target_id is not None and target is None:
            continue  # out-of-range: omitted, NOT unassigned
        now = current.get(student_id, "")
        # Rule 1 — whole-token comparison. "already in the target group" must not
        # read as a no-op, or a conflict row ("12,15" posted with 12) never resolves.
        wanted = str(target.pk) if target is not None else ""
        if now == wanted:
            continue
        # Rule 2
        if was_token is None or now != was_token:
            skipped.append(student_id)
            continue
        # Rule 3 — ADD BEFORE REMOVE. Removing first makes recompute_enrollment
        # see the student as unreachable and DELETE their group-sourced
        # Enrollment; the following add re-creates it and re-fires
        # notify_enrolled, so every ordinary move would emit a spurious
        # "you were enrolled" notification.
        if target is not None:
            add_students_to_group(target, [student], added_by=added_by)
        for column in columns:
            if target is not None and column.pk == target.pk:
                continue
            if str(column.pk) in now.split(","):
                remove_students_from_group(column, [student])
    return skipped
