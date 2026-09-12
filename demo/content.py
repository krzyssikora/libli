"""The kit-wide content pass (spec §4.4 step 5.5).

Runs ONCE per kit, before any pupil is touched: resolve the published-unit list,
validate every top-level question of every published QUIZ, and cache the answers
WITH THEIR FRACTIONS so the pupil loop never calls mark().
"""

from typing import NamedTuple

from courses.models import QuestionElement
from courses.rollups import units_in_order
from demo import builders
from demo.warnings import DemoWarning


class QuestionPlan(NamedTuple):
    element_id: int
    max_marks: object
    answers: object  # builders.Answers
    fractions: dict  # "correct" -> float, int index -> float, "partial" -> float
    gradeable: bool  # not NOT_MARKED
    sentinel: bool


class CoursePlan(NamedTuple):
    units: list
    skipped_quiz_ids: set
    answerable_quizzes: list  # answerable AND has a gradeable question
    in_progress_candidates: list  # answerable_quizzes minus units with < 2 answerable
    questions: dict  # unit_id -> [QuestionPlan]
    warnings: list


def _top_level_questions(unit):
    """R9: the set compute_scores and the review gate use.

    The explicit order_by RESTATES `Element.Meta.ordering = ["order", "pk"]`
    (courses/models.py:346). It is not what makes the queryset ordered — Meta
    already does — so removing it changes nothing today. It is here so that a
    future Meta change cannot silently move every ordinal in the golden file:
    determinism depends on this key, and the dependency should be visible at the
    only place that reads it.

    ⚠️ Do not "simplify" it away on the grounds that it is redundant. And note
    that the falsifying mutant is `.order_by()` (the no-arg form, which CLEARS
    Meta.ordering) or `.order_by("pk")` — dropping the call entirely is a no-op.
    """
    elements = (
        unit.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .prefetch_related("content_object")
    )
    return [e for e in elements if isinstance(e.content_object, QuestionElement)]


def build_course_plan(course):
    units = units_in_order(course, drafts="hide")
    units = [u for u in units if u.published]  # belt and braces over drafts="hide"

    skipped, answerable, candidates, questions, warns = set(), [], [], {}, []

    for unit in units:
        if unit.unit_type != "quiz":
            continue  # R3 is about QUIZZES; lesson self-checks are never touched
        plans, skip_reason, gradeable_n, answerable_n = [], None, 0, 0
        for element in _top_level_questions(unit):
            q = element.content_object
            mode = q.marking_mode
            not_marked = mode == QuestionElement.MarkingMode.NOT_MARKED
            if mode == QuestionElement.MarkingMode.REVIEW:
                skip_reason = "a REVIEW question cannot be answered"
                break
            if type(q) in builders.UNANSWERABLE_QUESTION_TYPES:
                if not_marked:
                    warns.append(
                        DemoWarning("question_dropped", unit.pk, type(q).__name__)
                    )
                    continue
                skip_reason = f"{type(q).__name__} has no builder"
                break
            answers = builders.build(q)
            if answers is None:
                if not_marked:
                    warns.append(
                        DemoWarning("question_dropped", unit.pk, "row unanswerable")
                    )
                    continue
                skip_reason = f"{type(q).__name__} row is unanswerable"
                break

            correct_fraction = q.mark(answers.correct).fraction
            # THE CORRECT ANSWER IS VALIDATED TOO, not just the variants and the
            # partial. Otherwise a real mat-pp row shaped unlike our seven
            # fixtures can hand back an answer that marks 0.4, and every pupil in
            # the kit stores it as their "correct" response at fraction 0.4 —
            # silently, with no warning and no skip. Task 5's honest-builder test
            # catches that for the FIXTURES; this catches it for the course.
            if correct_fraction != 1.0:
                if not_marked:
                    warns.append(
                        DemoWarning(
                            "question_dropped",
                            unit.pk,
                            f"correct answer marked {correct_fraction}",
                        )
                    )
                    continue
                warns.append(
                    DemoWarning(
                        "correct_answer_rejected",
                        unit.pk,
                        f"{type(q).__name__} marked {correct_fraction}",
                    )
                )
                skip_reason = (
                    f"{type(q).__name__}'s correct answer marked {correct_fraction}"
                )
                break

            fractions = {"correct": correct_fraction}
            sentinel = answers.wrong is builders.NO_WRONG_ANSWER
            surviving = []
            if not sentinel:
                for variant in answers.wrong:
                    f = q.mark(variant).fraction
                    if f == 0.0:
                        fractions[len(surviving)] = f
                        surviving.append(variant)
                    else:
                        warns.append(DemoWarning("variant_dropped", unit.pk, str(f)))
                if not surviving:
                    sentinel = True
            if sentinel:
                warns.append(
                    DemoWarning("sentinel_answered", unit.pk, type(q).__name__)
                )
                answers = builders.Answers(
                    answers.correct, builders.NO_WRONG_ANSWER, None
                )
            else:
                answers = builders.Answers(answers.correct, surviving, answers.partial)

            if answers.partial is not None:
                pf = q.mark(answers.partial).fraction
                if 0 < pf < 1:
                    fractions["partial"] = pf
                else:
                    warns.append(DemoWarning("partial_fallback", unit.pk, str(pf)))
                    answers = builders.Answers(answers.correct, answers.wrong, None)

            plans.append(
                QuestionPlan(
                    element_id=element.pk,
                    max_marks=q.max_marks,
                    answers=answers,
                    fractions=fractions,
                    gradeable=not not_marked,
                    sentinel=sentinel,
                )
            )
            answerable_n += 1
            gradeable_n += 0 if not_marked else 1

        if skip_reason is not None:
            skipped.add(unit.pk)
            warns.append(DemoWarning("quiz_skipped", unit.pk, skip_reason))
            continue
        questions[unit.pk] = plans
        if gradeable_n:
            answerable.append(unit)
            if answerable_n >= 2:
                candidates.append(unit)
        else:
            # A quiz that reached here with nothing gradeable — a prose-only quiz
            # never enters the loop at all, so skip_reason is None and this is the
            # ONLY place it can be reported. Without this branch the kit silently
            # contains a quiz no pupil will ever have a score for, and the
            # operator is never told.
            warns.append(
                DemoWarning(
                    "no_gradeable_question", unit.pk, f"{len(plans)} question(s)"
                )
            )

    return CoursePlan(units, skipped, answerable, candidates, questions, warns)
