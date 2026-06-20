"""View-agnostic helpers for the quiz path (Phase 2c)."""

from courses.models import ChoiceQuestionElement


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
