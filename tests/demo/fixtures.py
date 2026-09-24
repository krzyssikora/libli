"""Fixture courses for the demo tests. `small` is the default.

It carries seven deliberate properties, each pinned by an assertion somewhere:
  * part B is CREATED FIRST, so pre-order != pk order;
  * "Late quiz"'s TWO questions sort against pk order, so the (unit, ordinal)
    keys move if `_top_level_questions` drops its explicit `order_by`. (quiz_b's
    prose/question swap also disagrees with pk, but quiz_b holds only ONE
    question, so no test can observe it — keep both, rely on this one.)
  * a 3-wrong-variant choice question, for T28;
  * a LATE multi-question quiz past every reachable depth, so
    `in_progress_candidates` is non-empty for Task 9;
  * an ALL-CORRECT choice question, so the NO_WRONG_ANSWER sentinel branch is
    exercised;
  * a NOT_MARKED question sharing "Notes quiz" with a graded one, so the
    no-fraction branch is exercised;
  * a TWO-BLANK fill-blank question IN PART A, the only partial-capable row —
    without it the whole partial half of _pick_answer is dead in every
    end-to-end test, and its POSITION matters as much as its existence (see the
    comment at its creation).
Change any of them and read the assertions that name them before you do."""

from decimal import Decimal

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement


def _unit(course, parent, title, unit_type, *, obligatory=True, published=True):
    return ContentNode.objects.create(
        course=course,
        parent=parent,
        kind="unit",
        title=title,
        unit_type=unit_type,
        obligatory=obligatory,
        published=published,
    )


def _choice_question(
    unit, *, correct="2", options=("2", "3", "4", "6"), all_correct=False
):
    q = ChoiceQuestionElement.objects.create(
        stem="pick",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
        multiple=all_correct,
    )
    for text in options:
        Choice.objects.create(
            question=q, text=text, is_correct=all_correct or (text == correct)
        )
    return Element.objects.create(unit=unit, content_object=q)


def small_course(
    *,
    slug="small",
    lesson_with_unanswerable_selfcheck=False,
    quiz_without_questions=False,
    quiz_with_review_question=False,
):
    """⚠️ `slug` is a PARAMETER because `Course.slug` is `unique=True`
    (courses/models.py:127). Any test that needs two courses in one transaction —
    Task 10 Step 6's scaling test is the one — must pass a distinct slug for the
    second, or the create raises IntegrityError.
    (Note the separate rule in Task 13: for comparing two KITS, build ONE course
    and provision twice. Two courses there would compare disjoint row sets.)"""
    course = Course.objects.create(slug=slug, title="Small", language="pl")
    # PART 2 IS CREATED FIRST: pre-order must not coincide with pk order, or the
    # "flat order_by('order')" mutant is invisible.
    part_b = ContentNode.objects.create(
        course=course, kind="part", title="Part B", order=1
    )
    part_a = ContentNode.objects.create(
        course=course, kind="part", title="Part A", order=0
    )
    for i in range(6):
        _unit(course, part_a, f"A lesson {i}", "lesson")
    quiz_a = _unit(course, part_a, "A quiz", "quiz")
    # Three wrong variants (four options, one correct) — T28's question.
    _choice_question(quiz_a)
    _choice_question(quiz_a, correct="3")

    # THE PARTIAL-CAPABLE QUESTION, and it must live IN PART A — inside every
    # band's reach. _fillblank returns a partial whenever there are >= 2 blanks,
    # and this is the only such row in the fixture: without it `_pick_answer`'s
    # partial branch, P_PARTIAL_GIVEN_WRONG, the content pass's partial
    # validation and the `partial_fallback` warning are dead in every end-to-end
    # test, and Task 13's draw-order mutant (which moves the partial draw) cannot
    # turn the golden test red.
    #
    # ⚠️ POSITION IS THE WHOLE POINT. Parked at the END of Part B it sat near the
    # tail of the outline, while the depth bands reach roughly 8-9 (struggling),
    # 11-13 (average) and 13-15 (strong) — so a 20-pupil class answered it at all
    # only ~55% of the time, and the partial assertion held maybe 1 run in 40.
    # Here it is in Part A, below the SHALLOWEST depth any band can produce:
    #     round(floor(0.75 * len(plan.units)) * 0.70 * 0.92)
    # The fixture currently builds 18 published units (9 under each part), giving
    # a floor of 8 against this quiz's index of 7. ⚠️ RE-DERIVE FROM THE
    # EXPRESSION, never from the numbers — they move whenever a unit is added.
    # Task 9's first test derives the same floor and asserts a candidate survives.
    fb_quiz = _unit(course, part_a, "Blanks quiz", "quiz")
    fb = FillBlankQuestionElement.objects.create(
        stem="2 + {{2}} = {{4}}",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("2"),
    )
    Blank.objects.create(question=fb, accepted="2")
    Blank.objects.create(question=fb, accepted="4")
    Element.objects.create(unit=fb_quiz, content_object=fb)
    _choice_question(fb_quiz, correct="4")  # a second question, so it is 2-deep
    for i in range(6):
        _unit(course, part_b, f"B lesson {i}", "lesson")
    quiz_b = _unit(course, part_b, "B quiz", "quiz")
    q = ShortNumericQuestionElement.objects.create(
        stem="2+2?",
        value="4",
        tolerance="0",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal("1"),
    )
    question_el = Element.objects.create(unit=quiz_b, content_object=q)
    prose = Element.objects.create(
        unit=quiz_b, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    # ELEMENT ORDER MUST DISAGREE WITH PK.
    # ⚠️ Element.order is an OrderField(for_fields=["unit"]) that AUTO-ASSIGNS on
    # create: the question gets 0 and the prose gets 1. Setting prose to 0 alone
    # makes BOTH 0, and `order_by("order", "pk")` then breaks the tie on pk —
    # yielding exactly pk order, so the mutant this is supposed to catch
    # (dropping the explicit order_by) stays green. Swap them properly: the prose
    # must sort FIRST while holding the HIGHER pk.
    prose.order = 0
    prose.save(update_fields=["order"])
    question_el.order = 1
    question_el.save(update_fields=["order"])
    assert prose.pk > question_el.pk, "the fixture's own property, pinned"

    # A LATE, MULTI-QUESTION QUIZ. Without it `in_progress_candidates` holds only
    # "A quiz", while _usable_target's `position <= depth` rejects anything at or
    # below the SHALLOWEST depth any band can produce —
    # round(floor(0.75 * len(units)) * 0.70 * 0.92). (Compute it from the fixture
    # rather than trusting a literal here: units get added and the number moves.
    # Task 9's first test derives it and asserts a candidate survives.) With no
    # surviving candidate, `chosen` is always empty and Task 9's review-queue
    # test fails on correct code.
    late_quiz = _unit(course, part_b, "Late quiz", "quiz")
    late_a = _choice_question(late_quiz)
    late_b = _choice_question(late_quiz, correct="3")
    # ELEMENT ORDER MUST DISAGREE WITH PK **IN A UNIT THAT HAS TWO QUESTIONS**.
    # ⚠️ quiz_b's prose/question swap below is NOT enough on its own:
    # _top_level_questions filters down to QuestionElements, and quiz_b holds
    # exactly one, so its ordinal is 0 whatever the queryset order — dropping
    # `.order_by("order", "pk")` would leave every test AND the golden file green.
    # Swapping these two makes the (unit, ordinal) keys in the golden projection
    # actually change under that mutant.
    late_a.order, late_b.order = 1, 0
    late_a.save(update_fields=["order"])
    late_b.save(update_fields=["order"])
    assert late_b.pk > late_a.pk, "the later-created question must sort FIRST"

    # A NOT_MARKED question, sharing a quiz with a graded one. The generator
    # writes it an ANSWER but NO fraction (courses/views.py does the same), and
    # compute_scores ignores it — so without this row that whole branch is
    # untested and nothing stops the generator stamping 1.0 on ungraded work.
    notes_quiz = _unit(course, part_a, "Notes quiz", "quiz")
    _choice_question(notes_quiz, correct="3")
    # ⚠️ `accepted` MUST BE NON-EMPTY. `_accepted_lines` (courses/models.py)
    # drops blank lines, so accepted="" yields [] and `_shorttext` returns None —
    # build_course_plan then takes the `question_dropped` branch and the row never
    # becomes a QuestionPlan at all. The effect is worse than a missing fixture:
    # `gradeable=False` becomes UNREACHABLE plan-wide, so _pick_answer's
    # `not qplan.gradeable` early-out and _answer_quiz's `if qplan.gradeable else
    # None` — the branch that stops the generator stamping 1.0 on [N] questions —
    # are dead code that every test leaves green.
    unmarked = ShortTextQuestionElement.objects.create(
        stem="Your own notes?",
        accepted="cokolwiek",
        marking_mode=QuestionElement.MarkingMode.NOT_MARKED,
        max_marks=Decimal("0"),
    )
    Element.objects.create(unit=notes_quiz, content_object=unmarked)

    # A SENTINEL question: every option correct, so _choice finds no wrong pick
    # and build() returns NO_WRONG_ANSWER. Exercises the sentinel branch in
    # build_course_plan and in _pick_answer, which no other fixture row reaches.
    sentinel_quiz = _unit(course, part_b, "All-correct quiz", "quiz")
    _choice_question(sentinel_quiz, correct=None, options=("2", "3"), all_correct=True)

    if lesson_with_unanswerable_selfcheck:
        from courses.models import ExtendedResponseQuestionElement

        lesson = ContentNode.objects.filter(course=course, unit_type="lesson").first()
        er = ExtendedResponseQuestionElement.objects.create(
            stem="explain",
            marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("5"),
        )
        Element.objects.create(unit=lesson, content_object=er)

    if quiz_without_questions:
        empty = _unit(course, part_b, "Prose-only quiz", "quiz")
        Element.objects.create(
            unit=empty, content_object=TextElement.objects.create(body="<p>x</p>")
        )

    if quiz_with_review_question:
        # R3's WHOLE-QUIZ SKIP — the one path nothing else drives.
        # ⚠️ The ExtendedResponse in `lesson_with_unanswerable_selfcheck` is in a
        # LESSON (deliberately: R3 is quiz-only), and `quiz_without_questions`
        # exits via `no_gradeable_question`, not via skip_reason. So without this
        # flag `plan.skipped_quiz_ids` is EMPTY in every test, no test ever sees a
        # `quiz_skipped` warning, and the rule that fires constantly on real
        # mat-pp — and that makes the awaiting-review queue structurally empty —
        # ships with zero positive coverage.
        from courses.models import ExtendedResponseQuestionElement

        reviewed = _unit(course, part_b, "Reviewed quiz", "quiz")
        _choice_question(reviewed)  # a GOOD question, so the skip is whole-unit
        er = ExtendedResponseQuestionElement.objects.create(
            stem="explain",
            marking_mode=QuestionElement.MarkingMode.REVIEW,
            max_marks=Decimal("5"),
        )
        Element.objects.create(unit=reviewed, content_object=er)

    return course
