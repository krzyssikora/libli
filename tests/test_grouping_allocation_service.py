import pytest

from courses.models import Enrollment
from grouping import services
from grouping.models import GroupMembership
from notifications.models import Notification
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CohortMembershipFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _alloc_with_columns(n=2):
    a = AllocationFactory()
    cols = [
        GroupFactory(course=a.course, allocation=a, name=f"col{i}") for i in range(n)
    ]
    return a, cols


def test_columns_token_sorts_numerically_not_lexically():
    """Asserting against a re-computation of the implementation would be blind to
    the lexical-sort mutant, and two consecutive pks never straddle a decade —
    so pin it with a stub whose pks do."""

    class _Stub:
        def __init__(self, pk):
            self.pk = pk

    assert services.allocation_columns_token([_Stub(10), _Stub(9)]) == "9,10"


def test_state_token_shapes():
    a, cols = _alloc_with_columns(2)
    s_none = UserFactory()
    s_one = UserFactory()
    s_conflict = UserFactory()
    services.add_students_to_group(cols[0], [s_one])
    services.add_students_to_group(cols[0], [s_conflict])
    services.add_students_to_group(cols[1], [s_conflict])
    tokens = services.allocation_state_tokens(
        cols, [s_none.pk, s_one.pk, s_conflict.pk]
    )
    assert tokens[s_none.pk] == ""
    assert tokens[s_one.pk] == str(cols[0].pk)
    assert tokens[s_conflict.pk] == ",".join(
        str(pk) for pk in sorted([cols[0].pk, cols[1].pk])
    )


def test_row_students_union_includes_out_of_cohort_and_archived_column_members():
    a, cols = _alloc_with_columns(1)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    in_cohort = UserFactory()
    CohortMembershipFactory(user=in_cohort, cohort=cohort)
    outsider = UserFactory()
    services.add_students_to_group(cols[0], [outsider])
    archived_col = GroupFactory(course=a.course, allocation=a, archived=True)
    archived_only = UserFactory()
    services.add_students_to_group(archived_col, [archived_only])
    ids = set(services.allocation_row_students(a).values_list("pk", flat=True))
    assert {in_cohort.pk, outsider.pk, archived_only.pk} <= ids


def test_row_students_excludes_staff():
    a, cols = _alloc_with_columns(1)
    staff = UserFactory(is_staff=True)
    GroupMembership.objects.create(group=cols[0], student=staff)
    ids = set(services.allocation_row_students(a).values_list("pk", flat=True))
    assert staff.pk not in ids


def test_writes_only_inside_the_rectangle_and_the_write_lands():
    """Load-bearing: was_token must match, or the row is skipped and the purely
    negative assertion holds under the mutant too."""
    a, cols = _alloc_with_columns(2)
    outside = GroupFactory(course=a.course)  # same course, NOT a column
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(outside, [student])
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[1].pk, str(cols[0].pk))}
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=outside, student=student).exists()
    assert GroupMembership.objects.filter(group=cols[1], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_none_target_removes_membership_and_drops_group_sourced_enrollment():
    """Load-bearing: the membership must come from add_students_to_group, or no
    group-sourced Enrollment exists and the assertion is vacuous."""
    a, cols = _alloc_with_columns(1)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    assert Enrollment.objects.filter(
        student=student, course=a.course, source="group"
    ).exists()
    services.set_allocation_assignments(cols, {student.pk: (None, str(cols[0].pk))})
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert not Enrollment.objects.filter(
        student=student, course=a.course, source="group"
    ).exists()


def test_a_row_absent_from_assignments_is_untouched():
    """The conflict case: no radio checked, so the browser posts nothing."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    services.set_allocation_assignments(cols, {})
    assert GroupMembership.objects.filter(student=student).count() == 2


def test_conflict_row_resolves_when_a_column_is_picked():
    """Whole-token comparison: 'already in the target group' must NOT read as a
    no-op, or conflicts are unresolvable through the screen built to resolve them."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    token = ",".join(str(pk) for pk in sorted([cols[0].pk, cols[1].pk]))
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, token)}
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[1], student=student).exists()


def test_guard_skips_a_moved_row_and_reports_it():
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    skipped = services.set_allocation_assignments(
        cols,
        {student.pk: (cols[1].pk, "")},  # stale: claims "no membership"
    )
    assert skipped == [student.pk]
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[1], student=student).exists()


def test_a_no_op_row_is_neither_written_nor_reported_even_when_the_token_moved():
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    skipped = services.set_allocation_assignments(
        cols,
        {student.pk: (cols[0].pk, "")},  # stale -was, but posted == current
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_a_none_was_token_is_a_mismatch_not_an_unguarded_write():
    """Load-bearing: the student must currently be in NO column (token ""), or
    the mutant's "" coincidentally mismatches and skips too."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, None)}
    )
    assert skipped == [student.pk]
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_moving_between_columns_keeps_the_enrollment_and_fires_no_new_notification():
    """Add-before-remove. Load-bearing: the membership must be group-sourced, or
    recompute_enrollment never deletes and the swap is invisible."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    enrollment = Enrollment.objects.get(
        student=student, course=a.course, source="group"
    )
    before = Notification.objects.filter(recipient=student).count()
    services.set_allocation_assignments(
        cols, {student.pk: (cols[1].pk, str(cols[0].pk))}
    )
    assert GroupMembership.objects.filter(group=cols[1], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert Enrollment.objects.get(student=student, course=a.course).pk == enrollment.pk
    assert Notification.objects.filter(recipient=student).count() == before


def test_an_out_of_range_target_keeps_the_membership():
    """Spec row 17c. Load-bearing: the -was must MATCH the current token, or the
    guard skips the row and the mutant survives."""
    a, cols = _alloc_with_columns(1)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (9999, str(cols[0].pk))}
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_added_by_is_recorded():
    a, cols = _alloc_with_columns(1)
    actor = UserFactory(is_staff=True)
    student = UserFactory()
    services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, "")}, added_by=actor
    )
    membership = GroupMembership.objects.get(group=cols[0], student=student)
    assert membership.added_by_id == actor.pk


def test_state_token_intersects_a_passed_membership_map():
    """Mutant 13 (drop `& column_ids`): only live for a caller-supplied,
    course-wide map — the `memberships is None` branch already filters on
    `group__in=columns`, so a DB-fixture change cannot reach this line."""
    a, cols = _alloc_with_columns(1)
    outside = GroupFactory(course=a.course)  # same course, not a column
    s = UserFactory()
    tokens = services.allocation_state_tokens(
        cols, [s.pk], memberships={s.pk: {cols[0].pk, outside.pk}}
    )
    assert tokens[s.pk] == str(cols[0].pk)
