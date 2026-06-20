"""View-agnostic helpers for the quiz path (Phase 2c)."""

from courses.models import ChoiceQuestionElement
from courses.models import QuestionElement


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
