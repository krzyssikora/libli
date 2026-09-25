"""View-agnostic helpers for the quiz path (Phase 2c)."""

from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone

from courses.models import ChoiceQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.scoring import earned_marks
from courses.scoring import outcome
from courses.scoring import to_stored_fraction


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
        "revealed": bool(getattr(response, "revealed_at", None)),
        "outcome": None,
        "earned": None,
        "possible": question.max_marks,
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
    # The result line (spec §2.5): classified by EARNED marks via the shared helper.
    # Guarded: an AUTO answer whose question was since switched to N/R reaches here
    # with result=None and an UNLOCKED response (the early return needs locked);
    # today's code survives that, so the new line must too (outcome stays None).
    if result is not None:
        earned = earned_marks(to_stored_fraction(result.fraction), question.max_marks)
        ctx["earned"] = earned
        ctx["outcome"] = outcome(earned, question.max_marks)
        if ctx["outcome"] == "correct" and not result.correct and not response.locked:
            # An unlocked question never reads "Correct" (§1): rounding (e.g. 0.5 of
            # 0.01 marks -> 0.01) can reach full marks while result.correct is False.
            # LOCKED, the same rounding reads "Correct" while the switch still shows
            # (fully_correct follows result.correct): accepted by spec §2.6 ("the line
            # follows the helper, the switch follows the predicate") -- do not "fix".
            ctx["outcome"] = "partial"
    # [A]:
    revealing = response.locked and result is not None
    if revealing:
        # Reuse the per-type feedback_context (choices, reveal_template) for the reveal.
        ctx.update(question.feedback_context(result))
        if question.INLINE_QUIZ_REVEAL or question.SUPPORTS_REVEAL:
            # This type marks its own options list once locked (choice: ✓/✗/＋ per
            # option), so the bottom list would print the same answer key a second
            # time — and print it detached from the options, which is what made a
            # student unable to line up "what I picked" against "what was right".
            # Converted types (SUPPORTS_REVEAL) show the key as a second copy of
            # their own controls behind the Your/Correct switch (spec §2.2), so the
            # list goes for them too.
            ctx["reveal_template"] = None
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
        # Recurse so a list-of-lists (multigrid: [[], [], []]) reads as empty,
        # while the flat cases (matrix ["", 3]) are unchanged.
        return all(answer_is_empty(v) for v in answer)
    return not answer


def parse_attempt(post):
    """1-based attempt number from a client-supplied `attempt` field, floored at 1.

    The ephemeral grading paths (student previewer, authoring 'try it') are
    STATELESS, so the client owns the attempt counter. Junk, absent, and
    out-of-range values all floor to 1; this never raises.

    `attempt`, `reveal` and `answer_view_<pk>` are RESERVED answer-POST field names
    (spec 2026-09-25 §2.3): NO QuestionElement.build_answer implementation may read
    them -- all ten read only choice / answer / blank / slot / row_<pk>.
    """
    try:
        return max(1, int(post.get("attempt", "1")))
    except (TypeError, ValueError):
        return 1


def locked_after(question, result, attempt_count):
    """Does `question` lock after an attempt that produced `result`?

    THE single source of the lock rule. Both quiz answer paths call this: the
    persisted one in views.quiz_answer (passing the post-increment
    QuestionResponse.attempt_count) and the ephemeral one in
    ephemeral_quiz_feedback (passing the client-supplied attempt number). They
    were previously independent implementations of the same rule, which is the
    twin-drift failure mode issue #169 exists for -- each side's tests pinned only
    its own side, so a one-sided change went green.
    tests/test_quiz_lock_rule_parity.py is the behavioural guard.

    `max_attempts is not None` is mandatory: null means UNLIMITED attempts, and
    without the guard this raises
    TypeError: '>=' not supported between 'int' and 'NoneType'.

    `result` is only consulted for AUTO questions and may be None otherwise.
    """
    if question.marking_mode != QuestionElement.MarkingMode.AUTO:
        return True  # [N]/[R]: single submission
    return bool(result.correct) or (
        question.max_attempts is not None and attempt_count >= question.max_attempts
    )


def can_reveal(question, *, attempts_made, locked):
    """May Show answer be offered / accepted (spec §3.5)? THE single home of the
    SUPPORTS_REVEAL check: the button's render condition, the enrolled branch and
    both ephemeral paths all call this. SUBMITTED is checked by quiz_answer's gate."""
    return bool(
        type(question).SUPPORTS_REVEAL
        and question.marking_mode == QuestionElement.MarkingMode.AUTO
        and attempts_made >= 1
        and not locked
    )


def key_view(question, *, mode, locked, fully_correct):
    """The key-copy values, or None (spec §2.2). One decision, made here, passed to
    render() as `key_values`; the template draws the copy + switch iff non-None.
    The AUTO conjunct is load-bearing: N/R questions lock on first submission and
    are never fully correct, so without it they would show the key."""
    if mode not in ("quiz", "results"):
        return None
    if question.marking_mode != QuestionElement.MarkingMode.AUTO:
        return None
    if not locked or fully_correct:
        return None
    return question.key_answer()


BLANK_QUIZ_STATE = {
    "locked": False,
    "selected_ids": frozenset(),
    "submitted_values": None,
    "mark_result": None,
    "verdicts": None,
    "key_values": None,
    "can_reveal": False,
    "reveal_earned": None,
    "revealed": False,
}


def quiz_render_state(question, response, result):
    """Every quiz-mode render key for one answered question (spec §2.4): the fetch
    response, resume, the no-JS re-render and the editor try-it all build the
    element from this, so they cannot drift. `response` is a QuestionResponse or
    the ephemeral stand-in (needs .locked, .attempt_count, .latest_answer,
    .revealed_at). `result` is None for N/R."""
    locked = bool(response.locked)
    selected, submitted = rehydrate(question, response.latest_answer)
    verdicts = None
    if result is not None:
        verdicts = question.part_verdicts(
            result, answer_from_json(question, response.latest_answer)
        )
        if verdicts is not None and result.correct:
            # §2.6 reverse case: a stored fully-correct answer paints all correct
            # even if a later key edit makes the fresh mark disagree.
            verdicts = [None if v is None else True for v in verdicts]
    return {
        "locked": locked,
        "selected_ids": selected,
        "submitted_values": submitted,
        # Key material: only once locked (the withhold window is over).
        "mark_result": result if locked else None,
        "verdicts": verdicts,
        "key_values": key_view(
            question,
            mode="quiz",
            locked=locked,
            fully_correct=bool(result is not None and result.correct),
        ),
        "can_reveal": can_reveal(
            question, attempts_made=response.attempt_count, locked=locked
        ),
        "reveal_earned": (
            earned_marks(to_stored_fraction(result.fraction), question.max_marks)
            if result is not None
            else None
        ),
        "revealed": bool(getattr(response, "revealed_at", None)),
    }


def ephemeral_quiz_feedback(question, answer, attempt, *, reveal=False):
    """Grade `answer` without persisting anything.

    Returns the triple (stand_in, result, validation) -- NOT a finished context --
    so callers can feed it to whichever renderer they need. The student previewer
    path passes stand_in straight to _quiz_render_feedback in place of a
    QuestionResponse; views_manage.element_try builds its own context from it.

    Persists NOTHING: no QuizSubmission, no QuestionResponse, no Attempt.

    Mirrors quiz_answer's state machine, now with THREE branches:
      - empty answer        -> (stand_in, None, True); mark() is NOT called
      - reveal=True          -> skips the empty-answer validation entirely, marks
                               whatever the form holds, locks, and consumes no
                               attempt (spec §3.3). The caller has already checked
                               can_reveal().
      - anything else       -> mark() for AUTO only, then defer the lock decision
                               to locked_after(), which views.quiz_answer also
                               calls. Do not restate the rule here: a copy in prose
                               drifts exactly the way the code copy did.

    ONE four-attribute stand-in (`locked`, `attempt_count`, `latest_answer`,
    `revealed_at`) is built on every branch. `.latest_answer` is always present
    because _quiz_render_feedback's no-JS branch calls
    rehydrate(question, response.latest_answer); a stand-in missing it raises
    AttributeError there. It must be answer_to_json(answer), not the raw
    build_answer payload, because rehydrate is specified against a STORED value.
    """
    latest = answer_to_json(answer)
    if reveal:
        # Show answer on the stateless path (spec §3.3): bypasses the empty-answer
        # validation, marks whatever the form holds, locks, consumes no attempt.
        # The caller has already checked can_reveal().
        return (
            SimpleNamespace(
                locked=True,
                attempt_count=attempt,
                latest_answer=latest,
                revealed_at=timezone.now(),
            ),
            question.mark(answer),
            False,
        )
    if answer_is_empty(answer):
        # locked=False is load-bearing, not a default: quiz_feedback_context copies
        # .locked into the context before its `if validation: return ctx` exit, so a
        # locked stand-in would emit data-quiz-locked inside the VALIDATION panel and
        # freeze the question on an empty submit.
        return (
            SimpleNamespace(
                locked=False,
                attempt_count=attempt - 1,
                latest_answer=latest,
                revealed_at=None,
            ),
            None,
            True,
        )
    is_auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
    result = question.mark(answer) if is_auto else None
    locked = locked_after(question, result, attempt)
    return (
        SimpleNamespace(
            locked=locked,
            attempt_count=attempt,
            latest_answer=latest,
            revealed_at=None,
        ),
        result,
        False,
    )


def selected_ids(answer):
    """The choice-pk set from a build_answer() payload; empty for non-choice answers.

    Only choice questions produce a set/frozenset; text/fill-blank/etc. payloads
    (str, list, None) carry no selection, so they collapse to an empty frozenset.
    """
    return answer if isinstance(answer, (set, frozenset)) else frozenset()


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
