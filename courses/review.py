"""View-agnostic services for the teacher quiz-review path (Phase 3c-i)."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from courses import quiz as quiz_svc
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import UnitProgress
from courses.rollups import quiz_units_in_order
from grouping import scoping


def review_response(*, submission, element, earned_marks, feedback, reviewer):
    """Grade one [R] response and recompute the submission score.

    `element` must be an [R] QuestionElement in submission.unit (else ValueError —
    a programming error the view maps to 404). Bounds (0..max_marks) are the form's
    responsibility; here we assert them as a guard. Stores earned_marks directly and
    derives fraction (4dp) for display only.
    """
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise ValueError("element is not a question")
    if element.unit_id != submission.unit_id:
        raise ValueError("element is not on this submission's unit")
    if question.marking_mode != QuestionElement.MarkingMode.REVIEW:
        raise ValueError("element is not a [R] (requires-review) question")
    assert Decimal("0") <= earned_marks <= question.max_marks, "marks out of bounds"

    with transaction.atomic():
        # Lock the submission row: serializes concurrent reviews so each recompute
        # sees all prior reviewed rows.
        submission.__class__.objects.select_for_update().get(pk=submission.pk)
        # Creating the row for an unanswered [R] is safe: the columns not in
        # `defaults` (fraction, earned_marks, last_attempt_at, reviewed_at,
        # reviewed_by) are all nullable, and review_feedback defaults to "".
        response, _ = QuestionResponse.objects.get_or_create(
            submission=submission,
            element=element,
            defaults={"latest_answer": None, "attempt_count": 0, "locked": True},
        )
        response.earned_marks = earned_marks
        response.fraction = (earned_marks / question.max_marks).quantize(
            Decimal("0.0001")
        )
        response.review_feedback = feedback or ""
        response.reviewed_at = timezone.now()
        response.reviewed_by = reviewer
        response.save()  # persist BEFORE the recompute query below

        score, max_score = quiz_svc.compute_scores(submission.unit, submission)
        submission.score = score
        submission.max_score = max_score
        submission.save()
    return response


def force_submit_quiz(submission, *, by):
    """Teacher closes a student's IN_PROGRESS quiz so it can be graded/reviewed.

    Reuses the shared finalize path (AUTO-only freeze at submit time). Records the
    STUDENT's UnitProgress completion (never the acting teacher's). No-op if already
    submitted. Deliberately omits the student enrollment guard."""
    with transaction.atomic():
        locked = QuizSubmission.objects.select_for_update().get(pk=submission.pk)
        if locked.status != QuizSubmission.Status.IN_PROGRESS:
            return
        locked.submitted_by = by
        # single save persists submitted_by
        quiz_svc.finalize_submission(locked.unit, locked)
        progress, _ = UnitProgress.objects.get_or_create(
            student=locked.student, unit=locked.unit
        )
        if not progress.completed:
            progress.completed = True
            progress.save()


def _review_element_ids(unit):
    ids = []
    for el in unit.elements.all().prefetch_related("content_object"):
        q = el.content_object
        is_review = (
            isinstance(q, QuestionElement)
            and q.marking_mode == QuestionElement.MarkingMode.REVIEW
        )
        if is_review:
            ids.append(el.pk)
    return ids


def submission_review_state(submission):
    review_ids = _review_element_ids(submission.unit)
    total = len(review_ids)
    reviewed = QuestionResponse.objects.filter(
        submission=submission, element_id__in=review_ids, reviewed_at__isnull=False
    ).count()
    return {
        "total": total,
        "reviewed": reviewed,
        "remaining": total - reviewed,
        "fully_reviewed": total > 0 and reviewed >= total,
    }


def pending_reviews_for(user, course):
    student_ids = scoping.reviewable_students(user, course).values("pk")
    units = quiz_units_in_order(course)
    unit_pks = [u.pk for u in units]
    subs = list(
        QuizSubmission.objects.filter(unit_id__in=unit_pks, student_id__in=student_ids)
        .select_related("student", "unit")
        .order_by("unit__title", "student__username")
    )
    awaiting, in_progress = [], []
    for sub in subs:
        if sub.status == QuizSubmission.Status.IN_PROGRESS:
            in_progress.append(sub)
        elif sub.status == QuizSubmission.Status.SUBMITTED:
            st = submission_review_state(sub)
            if st["total"] > 0 and not st["fully_reviewed"]:
                sub.remaining_reviews = st["remaining"]  # attach for the template label
                awaiting.append(sub)
    return {"awaiting": awaiting, "in_progress": in_progress}
