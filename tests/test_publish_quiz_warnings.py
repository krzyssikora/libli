"""Task 10: quiz submission predicates.

QZ1-QZ4. QZ3 is the trap: a submitting student with NO group membership at
all (self-enrolled, e.g. via a Cohort) must be treated as ACTIVE, not quiet.
The obvious single-exists() implementation inverts this -- see quiz_warnings.py.
"""

import pytest

from courses.models import QuizSubmission
from courses.quiz_warnings import is_quiet
from courses.quiz_warnings import submission_counts
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_qz1_submission_from_non_archived_group_is_loud():
    """QZ1: a submission from a student in a non-archived group -> loud
    (is_quiet is False)."""
    unit = make_quiz_unit()
    course = unit.course
    student = UserFactory()
    group = GroupFactory(course=course, archived=False)
    GroupMembershipFactory(group=group, student=student)
    QuizSubmissionFactory(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )

    assert is_quiet(unit, course) is False
    assert is_quiet([unit.pk], course) is False


@pytest.mark.django_db
def test_qz2_all_submissions_from_archived_groups_only_is_quiet():
    """QZ2: every submitting student is in an archived group only -> quiet."""
    unit = make_quiz_unit()
    course = unit.course
    student = UserFactory()
    group = GroupFactory(course=course, archived=True)
    GroupMembershipFactory(group=group, student=student)
    QuizSubmissionFactory(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )

    assert is_quiet(unit, course) is True
    assert is_quiet([unit.pk], course) is True


@pytest.mark.django_db
def test_qz3_ungrouped_submitting_student_is_loud():
    """QZ3: a submitting student with NO group membership at all (self-enrolled)
    -> loud. This is the inversion the spec exists to prevent: the naive
    single-exists() form on non-archived groups sees no match for this student
    and reads the population as "all archived", going quiet.
    """
    unit = make_quiz_unit()
    course = unit.course
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    # Deliberately NO GroupFactory/GroupMembershipFactory for this student --
    # they belong to no Group at all on this course.
    QuizSubmissionFactory(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )

    assert is_quiet(unit, course) is False
    assert is_quiet([unit.pk], course) is False


@pytest.mark.django_db
def test_qz4_zero_submissions_shows_neither_banner():
    """QZ4: a quiz with zero submissions -> is_quiet False (no quiet banner)
    and submission_counts reports (0, 0) (no loud banner either)."""
    unit = make_quiz_unit()
    course = unit.course

    assert is_quiet(unit, course) is False
    assert submission_counts(unit) == (0, 0)
    assert submission_counts([unit.pk]) == (0, 0)


@pytest.mark.django_db
def test_submission_counts_splits_submitted_from_in_progress():
    """submission_counts splits status=SUBMITTED (the 'have submitted' figure)
    from everything else (the 'part-way through' figure) -- a row exists as
    soon as a student opens the quiz, so in-progress rows must not inflate the
    submitted count."""
    unit = make_quiz_unit()
    submitted_student = UserFactory()
    in_progress_student = UserFactory()
    QuizSubmissionFactory(
        student=submitted_student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    QuizSubmissionFactory(
        student=in_progress_student,
        unit=unit,
        status=QuizSubmission.Status.IN_PROGRESS,
    )

    assert submission_counts(unit) == (1, 1)
    assert submission_counts([unit.pk]) == (1, 1)
