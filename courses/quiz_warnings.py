"""Quiz submission predicates consumed by the publish-state warning banners.

Task 12's confirm strip (unit-scope quiz hide, and the aggregated subtree
hide) and Task 15's editor-page submission banner both key off `is_quiet`;
`submission_counts` supplies the figures either banner displays.
"""

from courses.models import QuizSubmission
from grouping.models import GroupMembership


def _unit_pks(unit_or_pks):
    """Accept a single ContentNode or an iterable of pks. Both public helpers
    take this contract so the subtree strip can aggregate over a chapter.
    """
    if hasattr(unit_or_pks, "pk"):
        return [unit_or_pks.pk]
    return list(unit_or_pks)


def submission_counts(unit_or_pks):
    """(submitted, in_progress) counts across the given unit(s).

    The "have submitted" count filters status=SUBMITTED; the in-progress
    figure counts everything else. A row exists as soon as a student *opens*
    the quiz, so counting every row would report e.g. "12 submissions" for a
    quiz twelve students merely glanced at -- which trains the CA to ignore
    the banner, the failure mode a warning cannot recover from.
    """
    pks = _unit_pks(unit_or_pks)
    submitted = QuizSubmission.objects.filter(
        unit_id__in=pks, status=QuizSubmission.Status.SUBMITTED
    ).count()
    in_progress = (
        QuizSubmission.objects.filter(unit_id__in=pks)
        .exclude(status=QuizSubmission.Status.SUBMITTED)
        .count()
    )
    return submitted, in_progress


def is_quiet(unit_or_pks, course):
    """The quiet note fires only when EVERY submitting student is provably in
    a finished class. Two lookups, not one.

    The obvious implementation -- one exists() joining
    QuizSubmission -> student -> GroupMembership -> Group(archived=False),
    quiet when False -- inverts the no-group rule: a self-enrolled student
    (joined via a Cohort) has NO GroupMembership at all, so that exists()
    returns False for them too and routes exactly the population the rule
    protects into the quiet branch.

    Cohort.archived does NOT participate: a cohort gates self-enrolment
    eligibility, not class membership, and says nothing about whether a given
    student's work is historical. Only Group.archived means "this class is
    finished".
    """
    submitters = set(
        QuizSubmission.objects.filter(
            unit_id__in=_unit_pks(unit_or_pks),
            status=QuizSubmission.Status.SUBMITTED,
        ).values_list("student_id", flat=True)
    )
    if not submitters:
        return False  # no submissions -> neither banner shows at all
    in_any_group = set(
        GroupMembership.objects.filter(
            group__course=course, student_id__in=submitters
        ).values_list("student_id", flat=True)
    )
    in_active_group = GroupMembership.objects.filter(
        group__course=course, group__archived=False, student_id__in=submitters
    ).exists()
    ungrouped = submitters - in_any_group  # self-enrolled -> treated as ACTIVE
    return not in_active_group and not ungrouped
