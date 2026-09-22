"""The class: who is in which band, how far each pupil got, and what they did.

DETERMINISM (spec R5). All content randomness comes from one
random.Random(kit.seed), consumed in this fixed order:

  1. per pupil in creation order: gender, given name, surname (+1 per rejected
     duplicate)                                        -- demo.names.draw_names
  2. the band partition and its single shuffle         -- assign_bands
  3. per pupil in order: jitter, then per unit in PRE-ORDER: the lesson
     completion draw, or per question in element order (one draw, or two for a
     partial-capable type, plus one variant pick when the answer came out wrong
     and more than one variant survives); then, as item 3a, that pupil's
     reach-forward rows
  4. the IN_PROGRESS pass

A NOT_MARKED question, a sentinel question, an R3-skipped quiz, an
all-NOT_MARKED quiz and a non-lesson non-quiz unit consume NO draws.
"""

import math

from django.utils import timezone

from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import UnitProgress
from courses.quiz import answer_to_json
from courses.quiz import finalize_submission
from courses.rollups import is_obligatory_lesson
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from demo.builders import NO_WRONG_ANSWER
from demo.constants import AVERAGE
from demo.constants import BANDS
from demo.constants import FRONTIER_FRACTION
from demo.constants import IN_PROGRESS_PUPILS
from demo.constants import JITTER
from demo.constants import P_PARTIAL_GIVEN_WRONG
from demo.constants import STRONG
from demo.constants import STRONG_PCT
from demo.constants import STRUGGLING
from demo.constants import STRUGGLING_PCT
from demo.errors import InvalidFrontierPart
from demo.warnings import DemoWarning  # no alias: it is named DemoWarning at source


def assign_bands(rng, pupil_count):
    """A fixed partition, shuffled once, zipped with the pupils in creation order."""
    strong = pupil_count * STRONG_PCT // 100
    struggling = pupil_count * STRUGGLING_PCT // 100
    bands = (
        [STRONG] * strong
        + [STRUGGLING] * struggling
        + [AVERAGE] * (pupil_count - strong - struggling)
    )
    rng.shuffle(bands)
    return bands


def frontier_index(plan, frontier_part, course):
    """The published-unit index the class is working around.

    `course` is REQUIRED (no default): the frontier_part branch dereferences it,
    and a default of None turns a wiring mistake into an AttributeError deep in
    the body instead of a TypeError at the call.

    `frontier_part` is tested with `is not None`: part 0 is a legal AND falsy
    value, and `if frontier_part:` would silently turn --frontier-part 0 into
    the fraction.
    """
    total = len(plan.units)
    if frontier_part is not None:
        parts = list(course.nodes.filter(parent__isnull=True).order_by("order", "pk"))
        # BOTH ends. `>= len(parts)` alone lets -1 through: it passes the
        # `is not None` branch, passes this check, and `parts[-1]` then silently
        # selects the LAST part — the opposite of what the operator typed. The
        # run reaches DemoKit.objects.create(frontier_part=-1), where
        # PositiveSmallIntegerField raises a DB error that the command's
        # `except (DemoKitError, ImproperlyConfigured)` deliberately does not
        # catch, so the operator gets a raw traceback.
        if not 0 <= frontier_part < len(parts):
            raise InvalidFrontierPart(
                f"part {frontier_part} does not exist (0..{len(parts) - 1})"
            )
        wanted = parts[frontier_part]
        ids = set(wanted._subtree_node_ids())
        positions = [i for i, u in enumerate(plan.units) if u.pk in ids]
        if not positions:
            raise InvalidFrontierPart(
                f"part {frontier_part} contains no published unit"
            )
        return positions[-1]
    return math.floor(FRONTIER_FRACTION * total)


def pupil_depth(rng, band, frontier, unit_count=None):
    """Consumes exactly one draw (the jitter). `round` is Python's banker's
    rounding, NOT int(x + 0.5) — the two disagree at exact halves.

    `unit_count is not None`, NOT truthiness: this is the same falsy-zero trap
    the frontier_part docstring spends a paragraph on, and writing it the other
    way here would let `unit_count=0` silently fall through to the UNCLAMPED
    branch. provision_kit raises EmptyCourse before that can happen today, but
    this is a public interface Task 15's boundary test calls directly.
    """
    if unit_count is not None and unit_count < 1:
        raise ValueError("unit_count must be >= 1 when given")
    jitter = rng.uniform(-JITTER, JITTER)
    depth = round(frontier * BANDS[band]["depth"] * (1 + jitter))
    top = (unit_count - 1) if unit_count is not None else max(depth, 0)
    return max(0, min(depth, top))


def _pick_answer(rng, qplan, p_correct):
    """One question's decision. Returns (answer, fraction).

    Draw accounting, pinned:
      * NOT_MARKED or sentinel  -> zero draws, always the correct answer
      * otherwise               -> one draw (correct?)
      * partial-capable         -> a second draw ALWAYS, even when the first said
                                   correct (then discarded)
      * answered wrong with >1 surviving variant -> one further pick draw
    """
    answers = qplan.answers
    if not qplan.gradeable or qplan.sentinel or answers.wrong is NO_WRONG_ANSWER:
        return answers.correct, qplan.fractions["correct"]

    correct_roll = rng.random() < p_correct
    partial_capable = answers.partial is not None
    partial_roll = rng.random() < P_PARTIAL_GIVEN_WRONG if partial_capable else False

    if correct_roll:
        return answers.correct, qplan.fractions["correct"]
    if partial_capable and partial_roll:
        return answers.partial, qplan.fractions["partial"]
    index = rng.randrange(len(answers.wrong)) if len(answers.wrong) > 1 else 0
    return answers.wrong[index], qplan.fractions[index]


def _complete(student, unit):
    """save()/get_or_create, NEVER bulk_create: UnitProgress.save() is what
    stamps completed_at, and the model declares that invariant for every write
    path."""
    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    if not progress.completed:
        progress.completed = True
        progress.save()


def _answer_quiz(rng, student, unit, qplans, p_correct, *, finalize=True, limit=None):
    # select_for_update is KEPT deliberately, and only for the contract:
    # finalize_submission's docstring says "Caller holds select_for_update on the
    # submission". It is a no-op on the create path (there is no row to lock) and
    # there is no concurrent writer here — every user was created inside this same
    # transaction — so do not read it as concurrency protection.
    submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
        student=student,
        unit=unit,
        defaults={"status": QuizSubmission.Status.IN_PROGRESS},
    )
    if submission.status == QuizSubmission.Status.SUBMITTED:
        return submission
    # ⚠️ SINGLE-SHOT per (pupil, unit). The guard above covers a re-finalized
    # quiz, NOT general re-entry: QuestionResponse carries
    # UniqueConstraint(["submission", "element"]), so a second call against a
    # still-IN_PROGRESS submission would raise IntegrityError at the bulk_create
    # below. All THREE callers guarantee it cannot happen:
    #   1. generate's depth loop — visits each unit at most once;
    #   2. generate's reach-forward — fires only when `did_quiz` is False, which
    #      means no submission exists for ANY answerable quiz, first_quiz included;
    #   3. leave_in_progress — skips every unit already in `submitted_unit_ids`.
    # Keep it that way. (2) is the one that is not obvious from its call site.
    now = timezone.now()
    rows = []
    for qplan in qplans[:limit]:  # qplans[:None] is already the whole list
        answer, fraction = _pick_answer(rng, qplan, p_correct)
        # ⚠️ NOT_MARKED ROWS STORE NO FRACTION. courses/views.py:1645-1655 sets
        # `response.fraction` / `earned_marks` ONLY when marking_mode is AUTO and
        # leaves them None otherwise. Writing 1.0 here would make every `[N]`
        # question in the kit render as fully correct on any surface that shows a
        # stored fraction — and compute_scores ignores NOT_MARKED, so no scoring
        # test could ever see it. It would surface first in the mat-pp eyeball,
        # and again in PR 5's per-question view.
        stored = to_stored_fraction(fraction) if qplan.gradeable else None
        rows.append(
            QuestionResponse(
                submission=submission,
                element_id=qplan.element_id,
                fraction=stored,
                earned_marks=(
                    earned_marks(stored, qplan.max_marks)
                    if stored is not None
                    else None
                ),
                latest_answer=answer_to_json(answer),
                attempt_count=1,
                last_attempt_at=now,
                locked=False,
            )
        )
    # QuestionResponse has no save() override (verified), so bulk_create is safe
    # here — and this is the highest-volume write by an order of magnitude.
    QuestionResponse.objects.bulk_create(rows)
    # ⚠️ NO `Attempt` ROWS, deliberately. The real answer path
    # (courses/views.py:1665) creates one Attempt per response; we write
    # attempt_count=1 with nothing behind it. What that costs: any surface that
    # JOINS Attempt shows a count with no history — PR 5's per-question view,
    # the stated consumer, reads attempt_count alone (views_analytics.py
    # _quiz_answer_rows), never joining Attempt. Writing them here would add
    # ~pupils x questions rows for a demo that never replays an attempt; it
    # consumes no draw either way, so the draw order is unaffected.
    if finalize:
        finalize_submission(unit, submission)
        _complete(student, unit)
    return submission


def generate(rng, plan, pupils, *, course, frontier_part=None):
    """Write every pupil's activity. Returns `(warnings, bands, depths)`.

    The triple, not a bare warnings list — Task 9 consumes bands and depths for
    the IN_PROGRESS selection, and narrowing this docstring is how a caller comes
    to unpack one value.

    NO `kit` PARAMETER. The body never read it and the plan's own test passed
    None for it — a positional argument that is legitimately None at half the
    call sites is an invitation to start using it and break the other half. R7
    scoping comes from `pupils`, which is the list the caller already filtered.
    """
    warnings = []
    bands = assign_bands(rng, len(pupils))
    frontier = frontier_index(plan, frontier_part, course)  # all three, always
    answerable_ids = {u.pk for u in plan.answerable_quizzes}
    first_lesson = next((u for u in plan.units if is_obligatory_lesson(u)), None)
    first_quiz = plan.answerable_quizzes[0] if plan.answerable_quizzes else None

    depths = []
    for pupil, band in zip(pupils, bands, strict=True):
        cfg = BANDS[band]
        depth = pupil_depth(rng, band, frontier, len(plan.units))
        depths.append(depth)
        did_lesson = did_quiz = False

        for unit in plan.units[: depth + 1]:
            if unit.unit_type == "lesson":
                obligatory = is_obligatory_lesson(unit)
                p = cfg["p_lesson"] if obligatory else cfg["p_optional"]
                if rng.random() < p:
                    _complete(pupil, unit)
                    did_lesson = did_lesson or obligatory
            elif unit.unit_type == "quiz" and unit.pk in answerable_ids:
                _answer_quiz(
                    rng, pupil, unit, plan.questions[unit.pk], cfg["p_correct"]
                )
                did_quiz = True
            # An R3-skipped quiz, or any other unit kind: NO draws at all.

        # Item 3a: the reach-forward. Guarantees the post-generation invariant by
        # CONSTRUCTION rather than by dice — a pupil whose slice holds no
        # obligatory lesson or no surviving quiz reaches the first one in
        # pre-order. The lesson is forced with NO draw.
        if not did_lesson and first_lesson is not None:
            _complete(pupil, first_lesson)
        if not did_quiz and first_quiz is not None:
            _answer_quiz(
                rng, pupil, first_quiz, plan.questions[first_quiz.pk], cfg["p_correct"]
            )

    warnings.extend(leave_in_progress(rng, plan, pupils, bands, depths))
    return warnings, bands, depths


def _usable_target(plan, depth, submitted_unit_ids):
    """The STATIC, draw-free predicate. Selection runs before the pass, so a
    predicate phrased as 'yields a conforming prefix' would force an implementer
    to simulate draws — perturbing a stream nothing pins.

    No `pupil` parameter: the caller already resolved it into
    `submitted_unit_ids`, and a parameter the body never reads sends a reader
    hunting for logic that is not here.
    """
    for unit in plan.in_progress_candidates:
        position = next(i for i, u in enumerate(plan.units) if u.pk == unit.pk)
        if position <= depth or unit.pk in submitted_unit_ids:
            continue
        qplans = plan.questions[unit.pk]
        n = len(qplans)
        first_gradeable = next((i for i, q in enumerate(qplans) if q.gradeable), None)
        # 0-based: a prefix of length L <= n-1 covers indices 0..L-1.
        if first_gradeable is not None and first_gradeable <= n - 2:
            return unit
    return None


def leave_in_progress(rng, plan, pupils, bands, depths):
    """The shallowest pupils WITH A USABLE TARGET get an unfinished quiz.

    Not 'the first two in creation order': the shallowest pupils are exactly the
    ones the reach-forward already gave a finalized submission after their
    depth, so the weaker rule selects pupils with nothing to write. Ties break
    on (depth, creation index) — bands share multipliers and jitter often rounds
    to the same integer.
    """
    # (No local `from courses.models import QuizSubmission` — Task 8 already put
    # it in the module header, and a function-local re-import tells the next
    # reader there is an import cycle here. There is not.)
    warnings = []
    ranked = sorted(range(len(pupils)), key=lambda i: (depths[i], i))
    chosen = []
    for i in ranked:
        submitted = set(
            QuizSubmission.objects.filter(student=pupils[i]).values_list(
                "unit_id", flat=True
            )
        )
        target = _usable_target(plan, depths[i], submitted)
        if target is not None:
            chosen.append((i, target))
        if len(chosen) == IN_PROGRESS_PUPILS:
            break

    for i, unit in chosen:
        qplans = plan.questions[unit.pk]
        n = len(qplans)
        length = rng.randint(1, n - 1)
        # If the drawn prefix holds no gradeable response, EXTEND forward to the
        # first gradeable question, consuming no further draw.
        if not any(q.gradeable for q in qplans[:length]):
            # `idx`, not `i` and not `n`: the genexp has its own scope so reusing
            # either is not a bug, but `i` is the PUPIL index this loop is keyed
            # on and `n` is len(qplans) on the line below — a reader should not
            # have to prove scoping rules to read a function about which pupil
            # gets which unit.
            first_gradeable = next(idx for idx, q in enumerate(qplans) if q.gradeable)
            length = min(first_gradeable + 1, n - 1)
        _answer_quiz(
            rng,
            pupils[i],
            unit,
            qplans,
            BANDS[bands[i]]["p_correct"],
            finalize=False,
            limit=length,
        )

    if not chosen:
        warnings.append(
            DemoWarning("no_qualifying_pupil", None, "no pupil had a usable target")
        )
    elif len(chosen) < IN_PROGRESS_PUPILS:
        warnings.append(
            DemoWarning(
                "fewer_in_progress_than_target",
                None,
                f"{len(chosen)} of {IN_PROGRESS_PUPILS}",
            )
        )
    return warnings
