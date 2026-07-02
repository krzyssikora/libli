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
        was_fully = submission_review_state(submission)["fully_reviewed"]
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

        if not was_fully and submission_review_state(submission)["fully_reviewed"]:
            from notifications.services import notify_graded

            notify_graded(submission, reviewer)
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
        from notifications.services import notify_needs_review

        notify_needs_review(locked, actor=by)


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


def _awaiting_review(state):
    """Shared grouping predicate: a SUBMITTED submission whose unit has at least
    one [R] element and is not yet fully reviewed. Both pending_reviews_for and
    roster_for_unit call this so the two groupings cannot drift (spec §4.2)."""
    return state["total"] > 0 and not state["fully_reviewed"]


def _review_marks_from_prefetch(submission, review_elements):
    """(earned, max, reviewed_count) over the unit's [R] elements, using the
    submission's PREFETCHED responses — no per-row query. `review_elements` is a
    list of (Element, QuestionElement) pairs gathered once per unit."""
    by_el = {r.element_id: r for r in submission.responses.all()}
    earned = Decimal("0")
    max_total = Decimal("0")
    reviewed = 0
    for el, q in review_elements:
        max_total += q.max_marks
        r = by_el.get(el.pk)
        if r is not None and r.reviewed_at is not None:
            reviewed += 1
            if r.earned_marks is not None:
                earned += r.earned_marks
    return earned, max_total, reviewed


def roster_for_unit(reviewer, submission):
    """Every in-scope sibling submission for submission.unit, grouped for the
    review roster (spec §4.2). One flat list sorted by (lower(name), pk); groups
    are a display concern. No N+1 (responses + content_object prefetched)."""
    unit = submission.unit
    course = unit.course
    student_ids = scoping.reviewable_students(reviewer, course).values("pk")
    subs = list(
        QuizSubmission.objects.filter(unit=unit, student_id__in=student_ids)
        .select_related("student")
        .prefetch_related("responses")
    )
    review_elements = [
        (el, el.content_object)
        for el in unit.elements.all().prefetch_related("content_object")
        if isinstance(el.content_object, QuestionElement)
        and el.content_object.marking_mode == QuestionElement.MarkingMode.REVIEW
    ]
    total = len(review_elements)

    rows = []
    for sub in subs:
        earned, max_total, reviewed = _review_marks_from_prefetch(sub, review_elements)
        state = {"total": total, "fully_reviewed": total > 0 and reviewed >= total}
        if sub.status == QuizSubmission.Status.IN_PROGRESS:
            group = "in_progress"
        elif _awaiting_review(state):
            group = "to_review"
        else:
            group = "reviewed"  # SUBMITTED & (fully reviewed OR zero-[R] auto-only)
        is_reviewed_with_marks = group == "reviewed" and total > 0
        name = sub.student.display_name or sub.student.username
        rows.append(
            {
                "submission": sub,
                "student": sub.student,
                "display_name": name,
                "group": group,
                "is_current": sub.pk == submission.pk,
                "earned": earned if is_reviewed_with_marks else None,
                "max": max_total if is_reviewed_with_marks else None,
                "auto_marked": group == "reviewed" and total == 0,
            }
        )
    rows.sort(key=lambda r: (r["display_name"].lower(), r["submission"].pk))
    groups = {"to_review": [], "in_progress": [], "reviewed": []}
    for r in rows:
        groups[r["group"]].append(r)
    return {
        "rows": rows,
        "groups": groups,
        "to_review_count": len(groups["to_review"]),
        "in_progress_count": len(groups["in_progress"]),
    }


def roster_neighbours(roster, current_submission):
    """Prev (any group) + Next-to-review for footer nav, over the flat roster
    order (spec §4.3). Both None at the ends."""
    rows = roster["rows"]
    idx = next(
        (i for i, r in enumerate(rows) if r["submission"].pk == current_submission.pk),
        None,
    )
    if idx is None:
        return {"prev": None, "next_to_review": None}
    prev = rows[idx - 1]["submission"] if idx > 0 else None
    next_to_review = None
    for r in rows[idx + 1 :]:
        if r["group"] == "to_review":
            next_to_review = r["submission"]
            break
    return {"prev": prev, "next_to_review": next_to_review}


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
            if _awaiting_review(st):
                sub.remaining_reviews = st["remaining"]  # attach for the template label
                awaiting.append(sub)
    return {"awaiting": awaiting, "in_progress": in_progress}
