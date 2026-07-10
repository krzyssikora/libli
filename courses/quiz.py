"""View-agnostic helpers for the quiz path (Phase 2c)."""

from decimal import Decimal

from courses.models import ChoiceQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.scoring import earned_marks


def quiz_feedback_context(question, response, *, result=None, validation=False):
    """Reveal-gated feedback context. Reveal (reveal_template + mark_result) is
    included ONLY when the question is locked AND was marked — i.e. correct, or
    wrong-on-last-attempt. While attempts remain, only `attempts_left` passes.
    Handles all three modes: validation, [N]/[R] neutral, [A].

    `response` only needs `.locked` and `.attempt_count` — the live student path
    passes a QuestionResponse; the authoring 'try it' preview passes an ephemeral
    stand-in (nothing persisted)."""
    ctx = {
        "el": question,
        "validation": validation,
        "mode": "quiz",
        "neutral": None,
        "locked": response.locked,
        "attempts_left": None,
    }
    if validation:
        return ctx
    # [N]/[R]: recorded, never marked (result is None, locked on first submit).
    if result is None and response.locked:
        ctx["neutral"] = (
            "review"
            if question.marking_mode == QuestionElement.MarkingMode.REVIEW
            else "recorded"
        )
        ctx["mark_result"] = None
        ctx["reveal_template"] = None
        return ctx
    # [A]:
    revealing = response.locked and result is not None
    if revealing:
        # Reuse the per-type feedback_context (choices, reveal_template) for the reveal.
        ctx.update(question.feedback_context(result))
    else:
        # Withhold: no reveal_template, no mark_result payload beyond correct=False.
        ctx["mark_result"] = result
        ctx["reveal_template"] = None
    if question.max_attempts is not None and not response.locked:
        ctx["attempts_left"] = max(0, question.max_attempts - response.attempt_count)
    return ctx


def answer_is_empty(answer):
    """True iff a build_answer() payload carries nothing markable."""
    if isinstance(answer, (set, frozenset)):
        return not answer
    if isinstance(answer, str):
        return not answer.strip()
    if isinstance(answer, (list, tuple)):
        return not any(str(v).strip() for v in answer)
    return not answer


def answer_to_json(answer):
    """JSON-safe form of a build_answer() payload for QuestionResponse.latest_answer."""
    if isinstance(answer, (set, frozenset)):
        return sorted(answer)
    if isinstance(answer, tuple):
        return list(answer)
    return answer


def rehydrate(question, latest_answer):
    """Reconstruct (selected_ids, submitted_values) for the shared element templates
    from a stored latest_answer. Choice types use selected_ids; the rest use
    submitted_values — exactly the no-JS context vars check_answer already passes."""
    if isinstance(question, ChoiceQuestionElement):
        return set(latest_answer or []), None
    return set(), latest_answer


def answer_from_json(question, latest_answer):
    """Inverse of answer_to_json: reconstruct a mark() input from a stored
    latest_answer (choice -> set; text/numeric/fill-blank unchanged). Used by the
    resume render (Task 12) and the results per-blank reveal (Task 11)."""
    if isinstance(question, ChoiceQuestionElement):
        return set(latest_answer or [])
    return latest_answer


def compute_scores(node, submission):
    """Pure (no writes): return (score, max_score) for a submission.

    AUTO question: max_marks always counts toward max_score; earned counts toward
    score only when a response exists with a non-null fraction (matches the old
    _score_submission guard). REVIEW question: counts toward BOTH only once its
    response is reviewed (reviewed_at set), taking the stored earned_marks directly
    (never re-derived from fraction). NOT_MARKED: never counted.
    """
    responses = {r.element_id: r for r in submission.responses.all()}
    total = Decimal("0.00")
    possible = Decimal("0.00")
    for el in node.elements.filter(parent__isnull=True).prefetch_related(
        "content_object"
    ):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            possible += q.max_marks
            if r is not None and r.fraction is not None:
                total += earned_marks(r.fraction, q.max_marks)
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            if r is not None and r.reviewed_at is not None:
                possible += q.max_marks
                total += r.earned_marks or Decimal("0.00")
        # NOT_MARKED: excluded from both, always.
    return total, possible


def finalize_submission(node, submission):
    """Freeze a submission: lock all responses, cache score/max_score, mark
    SUBMITTED, save. The shared submit path for both the student finish and the
    teacher force-submit. Caller holds select_for_update on the submission.

    The final save() MUST remain a full save (no update_fields): force-submit
    (Task 7) pre-sets submission.submitted_by in memory and relies on this single
    save to persist it. Do not narrow the save to update_fields.
    """
    score, max_score = compute_scores(node, submission)
    submission.responses.update(locked=True)
    submission.score = score
    submission.max_score = max_score
    submission.status = QuizSubmission.Status.SUBMITTED
    submission.save()  # model save() stamps submitted_at
