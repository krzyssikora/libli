import pytest


@pytest.mark.django_db
def test_plan_caches_fractions_and_skips_only_quizzes():
    """R1 needs a fraction per written response and the generator may not call
    mark() in the pupil loop, so the cache holds (answer, fraction) pairs."""
    from demo import builders
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course()
    plan = build_course_plan(course)

    assert plan.units, "published units in pre-order"
    saw_sentinel = False
    for _unit_id, questions in plan.questions.items():
        for q in questions:
            assert q.fractions["correct"] == 1.0
            if q.sentinel:
                # NO_WRONG_ANSWER is a bare sentinel object with no __len__, so
                # len() below would raise TypeError — turning a content
                # regression into an unrelated crash the moment the fixture
                # grows an all-correct question.
                assert q.answers.wrong is builders.NO_WRONG_ANSWER
                saw_sentinel = True
                continue
            for i in range(len(q.answers.wrong)):
                assert q.fractions[i] == 0.0
    assert saw_sentinel, (
        "the fixture must carry a sentinel question (see 'All-correct quiz')"
    )
    # The NOT_MARKED branch must be REACHABLE, not merely present in the fixture.
    # A row whose builder returns None is dropped by build_course_plan and never
    # becomes a QuestionPlan, which silently kills every gradeable=False code
    # path downstream.
    assert any(not q.gradeable for qs in plan.questions.values() for q in qs), (
        "no QuestionPlan has gradeable=False — see 'Notes quiz' in the fixture"
    )

    # The (unit, ordinal) keys the golden file is built from. "Late quiz"'s two
    # questions were created in one order and given the OPPOSITE `order`, so this
    # is the one place the plan's ordering is observable.
    late = [u for u in plan.units if u.title == "Late quiz"][0]
    ids = [q.element_id for q in plan.questions[late.pk]]
    assert ids == sorted(ids, reverse=True), "element order must not be pk order"


@pytest.mark.django_db
def test_a_lesson_with_an_unanswerable_self_check_is_never_skipped():
    """R3 applies to QUIZ units only. A lesson holding an extendedresponse would
    otherwise drop out of the progress matrix's numerator while the denominator
    still counted it."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(lesson_with_unanswerable_selfcheck=True)
    plan = build_course_plan(course)

    lesson_ids = {u.pk for u in plan.units if u.unit_type == "lesson"}
    assert not (lesson_ids & plan.skipped_quiz_ids)


@pytest.mark.django_db
def test_a_quiz_with_no_gradeable_question_is_excluded_and_warned():
    """The PLAN half only — nothing here touches QuizSubmission (the name used to
    promise that and deliver it in a different task). The submission half is
    Task 8's `test_a_skipped_quiz_receives_no_submission`.

    ⚠️ ONE kind, not an `or` of two. A prose-only quiz never enters the
    question loop, so `skip_reason` stays None and the old `or` form asserted on
    two kinds that this fixture cannot produce — it failed on correct code. The
    `no_gradeable_question` branch added in Step 5 is what makes it pass."""
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(quiz_without_questions=True)
    plan = build_course_plan(course)

    assert plan.answerable_quizzes, "the good quizzes survive"
    empty = [u for u in plan.units if u.title == "Prose-only quiz"][0]
    assert empty.pk not in {u.pk for u in plan.answerable_quizzes}
    assert ("no_gradeable_question", empty.pk) in {
        (w.kind, w.unit_id) for w in plan.warnings
    }


@pytest.mark.django_db
def test_a_quiz_holding_a_review_question_is_skipped_WHOLE():
    """R3's headline rule, and the ONLY test that drives skip_reason.

    ⚠️ The skip is per-UNIT, never per-question: "Reviewed quiz" also holds a
    perfectly good choice question, and it must NOT survive on its own. This is
    also the path that makes the awaiting-review queue structurally empty (see
    this task's preamble) — so if this test ever starts failing because the skip
    was narrowed to the offending question, that consequence changed too.
    """
    from demo.content import build_course_plan
    from tests.demo.fixtures import small_course

    course = small_course(quiz_with_review_question=True)
    plan = build_course_plan(course)

    reviewed = [u for u in plan.units if u.title == "Reviewed quiz"][0]
    assert reviewed.pk in plan.skipped_quiz_ids
    assert reviewed.pk not in {u.pk for u in plan.answerable_quizzes}
    assert reviewed.pk not in plan.questions, "a skipped quiz gets NO question list"

    warning = [w for w in plan.warnings if w.unit_id == reviewed.pk]
    assert [w.kind for w in warning] == ["quiz_skipped"]
    assert "REVIEW" in warning[0].reason

    # The good quizzes are untouched — the skip is scoped to the one unit.
    assert plan.answerable_quizzes


def test_an_unknown_warning_kind_is_refused():
    """Without this, __post_init__ could be deleted and every other test stays
    green — Task 15's `set(DISPLAY) == KINDS` only compares the map with itself.
    No django_db mark: this touches no database."""
    from demo.warnings import DemoWarning

    with pytest.raises(ValueError):
        DemoWarning("quiz_skiped", None, "typo")

    DemoWarning("quiz_skipped", None, "the correctly spelled one")  # must not raise
