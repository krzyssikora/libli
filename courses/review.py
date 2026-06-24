"""View-agnostic services for the teacher quiz-review path (Phase 3c-i)."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from courses import quiz as quiz_svc
from courses.models import QuestionElement
from courses.models import QuestionResponse


def review_response(*, submission, element, earned_marks, feedback, reviewer):
    """Grade one [R] response and recompute the submission score.

    `element` must be an [R] QuestionElement in submission.unit (else ValueError —
    a programming error the view maps to 404). Bounds (0..max_marks) are the form's
    responsibility; here we assert them as a guard. Stores earned_marks directly and
    derives fraction (4dp) for display only.
    """
    question = element.content_object
    not_a_question = not isinstance(question, QuestionElement)
    wrong_unit = element.unit_id != submission.unit_id
    if not_a_question or wrong_unit:
        raise ValueError("element is not a question on this submission's unit")
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
