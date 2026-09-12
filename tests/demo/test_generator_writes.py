import random

import pytest


def _run(course, pupil_count=5, seed=11):
    from courses.models import Enrollment
    from demo.content import build_course_plan
    from demo.generator import generate
    from tests.factories import make_verified_user

    pupils = []
    for i in range(pupil_count):
        u = make_verified_user(username=f"p{i}", email=f"p{i}@demo.invalid")
        Enrollment.objects.create(student=u, course=course)
        pupils.append(u)
    plan = build_course_plan(course)
    warnings, _bands, _depths = generate(
        random.Random(seed), plan, pupils, course=course
    )
    return pupils, plan, warnings


@pytest.mark.django_db
def test_every_stored_fraction_is_the_mark_of_the_stored_answer():
    """T1 — the derived-score rule. Without to_stored_fraction the comparison is
    Decimal vs float and fails on every partial."""
    from courses.models import QuestionElement
    from courses.models import QuestionResponse
    from courses.quiz import answer_from_json
    from courses.scoring import to_stored_fraction
    from tests.demo.fixtures import small_course

    course = small_course()
    _run(course)

    responses = QuestionResponse.objects.select_related("element").all()
    assert responses.exists()
    unmarked = 0
    for r in responses:
        question = r.element.content_object
        if question.marking_mode == QuestionElement.MarkingMode.NOT_MARKED:
            # Matches courses/views.py: a NOT_MARKED response carries an answer
            # but NO fraction. Pinned here so the generator cannot drift into
            # stamping 1.0 on questions nothing grades.
            assert r.fraction is None and r.earned_marks is None
            assert r.latest_answer is not None
            unmarked += 1
            continue
        # ⚠️ QUESTION FIRST. The real signature is
        # `answer_from_json(question, latest_answer)` (courses/quiz.py:192) —
        # note that answer_to_json takes only the payload, so the pair is NOT
        # symmetrical. Reversed, every `isinstance(question, ...)` branch inside
        # is False, the function hands back the model object, and this headline
        # derived-score test marks a model instance instead of an answer.
        answer = answer_from_json(question, r.latest_answer)
        assert r.fraction == to_stored_fraction(question.mark(answer).fraction)

    assert unmarked, "the fixture must carry a NOT_MARKED question (see 'Notes quiz')"


@pytest.mark.django_db
def test_progress_mode_and_results_mode_both_populate():
    """T2a and T2b — two independent readers of the matrix.

    ⚠️ THE LESSON ASSERTION MUST BE SCOPED AND COUNT-SENSITIVE. A bare
    `UnitProgress.objects.filter(completed=True).exists()` is green on a build
    with NO lesson writes at all, because two other paths still populate it:
    `_answer_quiz(finalize=True)` calls `_complete` for every answered quiz, and
    `generate`'s reach-forward forces `first_lesson` for any pupil whose
    `did_lesson` is False — which, with the depth-loop writes gone, is ALL of
    them. Counting lesson rows is what separates "the loop wrote them" (~50 for
    5 pupils) from "only the reach-forward did" (exactly 5).
    """
    from courses.models import QuizSubmission
    from courses.models import UnitProgress
    from tests.demo.fixtures import small_course

    course = small_course()
    pupils, _plan, _w = _run(course)

    lesson_rows = UnitProgress.objects.filter(
        completed=True, unit__unit_type="lesson"
    ).count()
    assert lesson_rows > len(pupils), (
        f"{lesson_rows} completed lessons for {len(pupils)} pupils — that is the "
        "reach-forward alone; the depth loop wrote nothing"
    )
    # Vacuous against the generator, kept as a REGRESSION GUARD: UnitProgress.save()
    # stamps completed_at on every write path, so this can only fail if someone
    # reintroduces a queryset `.update(completed=True)`, which bypasses save().
    assert UnitProgress.objects.filter(completed=True, completed_at=None).count() == 0
    submitted = QuizSubmission.objects.filter(status=QuizSubmission.Status.SUBMITTED)
    assert submitted.exists()
    assert submitted.filter(score=None).count() == 0


@pytest.mark.django_db
def test_some_pupil_lands_a_partial_answer():
    """The partial half of _pick_answer has NO other end-to-end coverage: the
    builders test exercises it in isolation, and every other fixture question
    returns partial=None. Without this, P_PARTIAL_GIVEN_WRONG, the
    fractions["partial"] key and the partial_fallback branch are dead code that
    every test leaves green.

    ⚠️ 20 pupils and a pinned seed, not 5: with p_partial 0.4 applied only to
    wrong answers, a 5-pupil class can legitimately produce none.

    ⚠️ This test depends on "Blanks quiz" sitting inside EVERY band's depth
    (Part A, index 7). The guard below asserts that precondition directly, so a
    fixture move reports as "nobody reached it" rather than as a mysterious
    dice failure.

    ⚠️ TWO FAILURE MODES, and they need different responses. If `reached` is
    EMPTY, the fixture moved — fix the fixture. If `reached` is non-empty but
    `partials` is empty, it is the DICE, not the code: P(no partial anywhere) is
    about 4% for an arbitrary seed at 20 pupils. Try the next seed and pin it.
    Re-verify the pinned seed whenever BANDS, P_PARTIAL_GIVEN_WRONG or the pupil
    count changes.
    """
    from courses.models import QuestionResponse
    from tests.demo.fixtures import small_course

    course = small_course()
    _pupils, plan, _w = _run(course, pupil_count=20, seed=99)

    blanks = [u for u in plan.units if u.title == "Blanks quiz"][0]
    blank_elements = {q.element_id for q in plan.questions[blanks.pk]}
    reached = QuestionResponse.objects.filter(element_id__in=blank_elements)
    assert reached.exists(), (
        "no pupil reached 'Blanks quiz' — it has moved out of the bands' depth"
    )

    partials = [r for r in reached if 0 < float(r.fraction) < 1]
    assert partials, "no pupil scored a strict partial on the two-blank question"


@pytest.mark.django_db
def test_a_non_kit_student_gains_nothing():
    """T3 / R7 — the generator writes only for the pupils it is handed."""
    from courses.models import Enrollment
    from courses.models import QuizSubmission
    from courses.models import UnitProgress
    from tests.demo.fixtures import small_course
    from tests.factories import make_verified_user

    course = small_course()
    outsider = make_verified_user(username="real", email="real@example.com")
    Enrollment.objects.create(student=outsider, course=course)

    _run(course)

    assert not UnitProgress.objects.filter(student=outsider).exists()
    assert not QuizSubmission.objects.filter(student=outsider).exists()


@pytest.mark.django_db
def test_a_skipped_quiz_receives_no_submission():
    """T5 — the WRITE half of the whole-unit skip.

    ⚠️ Uses `quiz_with_review_question`, not `quiz_without_questions`: a
    prose-only quiz exits via the `no_gradeable_question` branch and never sets
    `skip_reason`, so the earlier version of this test drove a different path
    than its docstring claimed. Task 6's
    `test_a_quiz_holding_a_review_question_is_skipped_WHOLE` covers the plan
    half; this covers the fact that no row is written for it.
    """
    from courses.models import QuizSubmission
    from tests.demo.fixtures import small_course

    course = small_course(quiz_with_review_question=True)
    _pupils, plan, _w = _run(course)

    for unit in plan.units:
        if unit.unit_type == "quiz" and unit.pk not in {
            u.pk for u in plan.answerable_quizzes
        }:
            assert not QuizSubmission.objects.filter(unit=unit).exists()
