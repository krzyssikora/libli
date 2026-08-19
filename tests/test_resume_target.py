from datetime import timedelta

import pytest
from django.template.loader import render_to_string
from django.utils import timezone
from freezegun import freeze_time

from courses.models import Element
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.rollups import _stamp_current_chain
from courses.rollups import build_outline
from courses.rollups import build_resume
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


def _tree(course, user):
    return build_outline(course, user, drafts="hide")


def _resume(course, user):
    return build_resume(course, user, _tree(course, user))


def _course_with_units(n, **kw):
    """A course with n published lesson units at root level, in order."""
    course = CourseFactory(**kw)
    units = [
        ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=i)
        for i in range(n)
    ]
    return course, units


@pytest.mark.django_db
def test_no_visible_units_returns_none():
    course = CourseFactory()
    user = make_verified_user(username="s1", email="s1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_no_rows_at_all_starts_the_course():
    course, units = _course_with_units(3)
    user = make_verified_user(username="s2", email="s2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert r["state"] == "start"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_history_only_on_an_unpublished_unit_is_next_not_start():
    """Step 5. The student HAS history, so `start` would be a lie -- but every row
    sits on a unit that is no longer visible, so sources A-D see nothing.

    Unpublishing is the ONLY mechanism that reaches step 5: the unit FKs are
    CASCADE, so DELETING a unit destroys its rows and correctly lands on step 6.
    """
    course, units = _course_with_units(3)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="s3", email="s3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=ghost)
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_history_only_on_an_unpublished_quiz_also_reaches_step_5():
    """Source E's SECOND probe. A student whose only artefact is a QuizSubmission
    must not be told to start the course."""
    course, units = _course_with_units(3)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", order=9, published=False
    )
    user = make_verified_user(username="s4", email="s4@test.example.com")
    EnrollmentFactory(student=user, course=course)
    QuizSubmissionFactory(
        student=user, unit=ghost, status=QuizSubmission.Status.IN_PROGRESS
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_returned_node_is_a_contentnode_not_a_leaf_dict():
    """A leaf dict would blow up at {% url %} with NoReverseMatch (<int:node_pk>),
    after quietly rendering no kind chip and sending every link to lesson_unit."""
    from courses.models import ContentNode

    course, units = _course_with_units(2)
    user = make_verified_user(username="s5", email="s5@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert isinstance(r["node"], ContentNode)


def _backdate_progress(unit, user, when):
    """updated_at is auto_now, so save() cannot backdate it -- only .update() can."""
    UnitProgress.objects.filter(student=user, unit=unit).update(updated_at=when)


def _answered_question(unit, submission, when):
    """A QuestionResponse with last_attempt_at set -- source C's only input."""
    q = ShortTextQuestionElement.objects.create(stem="q", accepted="a")
    el = Element.objects.create(unit=unit, content_object=q)
    return QuestionResponse.objects.create(
        submission=submission, element=el, last_attempt_at=when
    )


@pytest.mark.django_db
def test_in_flight_lesson_is_the_resume_target():
    course, units = _course_with_units(3)
    user = make_verified_user(username="a1", email="a1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=units[1])
    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[1].pk


@pytest.mark.django_db
def test_answered_quiz_beats_a_later_opened_lesson():
    """SOURCE C EXISTS FOR THIS TEST. QuizSubmission.updated is auto_now and the
    answer path (views.py::quiz_answer) never saves the submission -- so B measures
    "opened", not "worked". Drop C and this student is resumed to the lesson they
    glanced at afterwards instead of the quiz they spent an hour on.
    """
    course = CourseFactory()
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=0)
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=1)
    user = make_verified_user(username="a2", email="a2@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
    )
    QuizSubmission.objects.filter(pk=sub.pk).update(updated=now - timedelta(hours=3))
    # The lesson was OPENED after the quiz was opened...
    UnitProgressFactory(student=user, unit=lesson)
    _backdate_progress(lesson, user, now - timedelta(hours=2))
    # ...but the quiz was ANSWERED most recently.
    _answered_question(quiz, sub, now - timedelta(minutes=5))

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_opened_but_unanswered_quiz_is_the_target():
    """Source B's own reason to exist: a quiz opened and not yet answered has no
    QuestionResponse, so source C cannot see it. Needs an OLDER rival, else the
    mutant falls through to step 5 and may return the same node anyway."""
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="a3", email="a3@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    UnitProgressFactory(student=user, unit=lesson)
    _backdate_progress(lesson, user, now - timedelta(hours=2))
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
    )
    QuizSubmission.objects.filter(pk=sub.pk).update(updated=now - timedelta(minutes=1))

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_submitted_quiz_with_no_progress_row_is_not_the_target():
    """THE seed_demo_course.py SHAPE. That command calls finalize_submission at
    lines 346 and 414 and has ZERO UnitProgress references, so a SUBMITTED
    submission whose unit is still in open_pks is a state this repo really ships.

    The competing OLDER lesson is load-bearing: without it the correct build
    reaches step 5 and returns open[0] -- possibly the quiz itself -- so the
    assertion would fail on a CORRECT build.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="a4", email="a4@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    UnitProgressFactory(student=user, unit=lesson)
    _backdate_progress(lesson, user, now - timedelta(hours=2))
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )
    QuizSubmission.objects.filter(pk=sub.pk).update(updated=now - timedelta(minutes=2))
    # Also give it an answered question, so source C's filter is exercised too.
    _answered_question(quiz, sub, now - timedelta(minutes=1))

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == lesson.pk


@pytest.mark.django_db
def test_invisible_newer_row_does_not_discard_the_visible_candidate():
    """Membership must be a FILTER INSIDE the query, not a post-check on LIMIT 1.
    Unit 30's row is strictly NEWER -- that is what makes the mutant fire. With a
    post-check, source A returns unit 30, fails the membership test, yields
    nothing, and the student is thrown back to unit 1.
    """
    course, units = _course_with_units(5)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="a5", email="a5@test.example.com")
    EnrollmentFactory(student=user, course=course)

    now = timezone.now()
    UnitProgressFactory(student=user, unit=units[2])
    _backdate_progress(units[2], user, now - timedelta(hours=1))
    UnitProgressFactory(student=user, unit=ghost)
    _backdate_progress(ghost, user, now)

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[2].pk


@pytest.mark.django_db
def test_exact_cross_source_tie_prefers_the_answered_quiz():
    """The source_rank tie-break (C=2 > B=1 > A=0). With rank dropped, max() over an
    untied key returns the FIRST maximal element, and the assembly order is A,B,C --
    so the mutant answers the LESSON. Assembling [C, B, A] would make the mutant
    coincidentally right, which is why the order is normative.

    The tie must be FORCED: all four timestamps are stamped Python-side, so two
    writes in one transaction differ by microseconds and produce no tie at all.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="t1", email="t1@test.example.com")
    EnrollmentFactory(student=user, course=course)

    moment = timezone.now() - timedelta(days=5)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=lesson)
        sub = QuizSubmissionFactory(
            student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
        )
        _answered_question(quiz, sub, timezone.now())

    a_ts = UnitProgress.objects.get(student=user, unit=lesson).updated_at
    c_ts = QuestionResponse.objects.get(submission=sub).last_attempt_at
    assert a_ts == c_ts  # the tie is real, not assumed

    r = _resume(course, user)
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_within_source_tie_prefers_the_higher_unit_id():
    """Source A's -unit_id secondary key. INSERTION ORDER IS LOAD-BEARING: create the
    LOWER-pk unit's row FIRST. Postgres's order among equal sort keys is unspecified
    but follows scan order in practice, so the mutant (no -unit_id) returns the
    first-inserted row. Insert the higher pk first and the mutant is coincidentally
    right and the test is GREEN on a broken build.
    """
    course, units = _course_with_units(3)
    user = make_verified_user(username="t2", email="t2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    lo, hi = sorted((units[0], units[1]), key=lambda u: u.pk)

    moment = timezone.now() - timedelta(days=5)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=lo)  # lower pk FIRST
        UnitProgressFactory(student=user, unit=hi)

    rows = UnitProgress.objects.filter(student=user, unit__in=(lo, hi))
    assert len({r.updated_at for r in rows}) == 1  # the tie is real

    assert _resume(course, user)["node"].pk == hi.pk


def _complete(unit, user, days_ago):
    """A completed UnitProgress whose completed_at is `days_ago` days back.

    save() stamps completed_at itself, so freeze the clock rather than backdating.

    RELATIVE, never a hard-coded calendar date: mixing literal dates with
    `timezone.now() - timedelta(...)` in one fixture makes the ordering
    clock-dependent, and such a test silently INVERTS once the wall clock passes
    those dates. Larger days_ago == older.
    """
    with freeze_time(timezone.now() - timedelta(days=days_ago)):
        UnitProgressFactory(student=user, unit=unit, completed=True)


@pytest.mark.django_db
def test_most_recent_unit_completed_advances_to_the_next_open_unit():
    """FIXTURE IS LOAD-BEARING: units[0] stays OPEN so open_leaves[0] is units[0]
    while forward is units[3]. Complete 0 and 1 instead and both step 4 and step 5
    answer units[2] -- deleting step 4 entirely would leave the test green via
    step 5, which also returns state "next".
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d1", email="d1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[1], user, 30)
    _complete(units[2], user, 20)
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[3].pk


@pytest.mark.django_db
def test_stray_visit_does_not_pin_the_card_forever():
    """THE bug the ts_f >= ts_d comparison exists to stop. Opening unit 0 once
    leaves a permanent completed=False row -- views.py::build_lesson_context does a
    get_or_create on every enrolled lesson GET. Without the comparison it outranks
    every completion made since and the card says "Pick up where you left off -
    unit 0" forever.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d2", email="d2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=units[0])
    _backdate_progress(units[0], user, timezone.now() - timedelta(days=90))
    _complete(units[1], user, 20)
    _complete(units[2], user, 10)
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[3].pk


@pytest.mark.django_db
def test_exact_tie_between_in_flight_and_completion_resumes():
    """The >= arm. Without a FORCED tie this test is vacuous: ts_f > ts_d passes on
    BOTH builds and ts_f < ts_d fails on the correct one. All four timestamps are
    stamped Python-side, so only freeze_time (or .update) can make them equal."""
    course, units = _course_with_units(4)
    user = make_verified_user(username="d3", email="d3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    moment = timezone.now() - timedelta(days=5)
    with freeze_time(moment):
        UnitProgressFactory(student=user, unit=units[0], completed=True)
        UnitProgressFactory(student=user, unit=units[2])

    row_f = UnitProgress.objects.get(student=user, unit=units[2])
    row_d = UnitProgress.objects.get(student=user, unit=units[0])
    assert row_f.updated_at == row_d.completed_at  # the tie is real

    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[2].pk


@pytest.mark.django_db
def test_reseeing_a_finished_unit_does_not_rewind_the_anchor():
    """THE ONLY scenario that separates completed_at from updated_at. views.py::seen
    calls progress.save() UNCONDITIONALLY, including for an already
    completed unit -- so re-reading unit 0 re-dates its updated_at while
    completed_at stays put. Anchor on updated_at and the mutant answers units[1].

    Do NOT try to build this with force_submit_quiz: it is guarded by
    `if not progress.completed`, so it can never re-date a completed row, and on
    the path where it does save, save() stamps completed_at in the same instant.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d4", email="d4@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, 30)
    _complete(units[2], user, 20)
    # Re-read unit 0 today: seen's unconditional save bumps updated_at only.
    UnitProgress.objects.filter(student=user, unit=units[0]).update(
        updated_at=timezone.now()
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[3].pk


@pytest.mark.django_db
def test_finished_the_last_unit_wraps_back_to_the_earliest_gap():
    course, units = _course_with_units(4)
    user = make_verified_user(username="d5", email="d5@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, 30)
    _complete(units[2], user, 20)
    _complete(units[3], user, 10)
    r = _resume(course, user)
    assert r["state"] == "gap"
    assert r["node"].pk == units[1].pk


@pytest.mark.django_db
def test_all_units_completed_returns_none():
    """Step 1. Deleting it does NOT "return the last unit" -- flight is None, done
    is the last completed leaf, forward is None, and step 4 indexes an empty list,
    so the symptom is the same IndexError as the no-visible-units case."""
    course, units = _course_with_units(2)
    user = make_verified_user(username="d6", email="d6@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, 30)
    _complete(units[1], user, 20)
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_completed_quiz_that_is_the_last_open_unit_yields_none():
    """Mutant: treating unit_type == quiz as never-complete -> `gap` on the quiz.
    The fixture MUST make the quiz the last remaining unit. The obvious
    "quiz mid-course, assert we advance past it" fixture is VACUOUS: under that
    mutant the quiz re-enters `open`, but A still excludes it (completed=False) and
    B/C still exclude it (SUBMITTED), so flight stays None, done is the quiz, and
    forward is the same unit the correct build returns.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="d7", email="d7@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(lesson, user, 30)
    _complete(quiz, user, 20)
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_additional_lesson_still_counts_as_a_target():
    """`open` is every uncompleted VISIBLE unit -- the rule deliberately does not
    inherit build_outline's required/additional distinction."""
    course = CourseFactory()
    required = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=0, obligatory=True
    )
    extra = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=1, obligatory=False
    )
    user = make_verified_user(username="d8", email="d8@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(required, user, 30)
    r = _resume(course, user)
    assert r["node"].pk == extra.pk


@pytest.mark.django_db
def test_in_flight_strictly_newer_than_a_real_completion_resumes():
    """The plain `ts_f > ts_d` arm, which nothing else covers: the existing tests
    exercise `done is None` (no completion at all), `==` (the tie test) and `<`
    (stray_visit). Kills a mutant that reversed the comparison to `ts_d >= ts_f`,
    and one that made step 3 fire only when `done is None`.
    """
    course, units = _course_with_units(4)
    user = make_verified_user(username="d10", email="d10@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(units[0], user, 30)
    UnitProgressFactory(student=user, unit=units[2])
    _backdate_progress(units[2], user, timezone.now() - timedelta(days=10))
    r = _resume(course, user)
    assert r["state"] == "resume"
    assert r["node"].pk == units[2].pk


@pytest.mark.django_db
def test_submitted_quiz_without_progress_can_surface_as_next():
    """DOCUMENTS AN ACCEPTED LIMITATION, deliberately -- this is not a bug report.

    build_outline's `completed` flag derives solely from UnitProgress.completed
    (rollups.py:244-250, leaf key at :265) and knows nothing about
    QuizSubmission.status, so a SUBMITTED submission whose unit lacks a completed
    UnitProgress row -- the seed_demo_course.py shape -- stays in `open` and can be
    offered under "Up next".

    The violated invariant is "a SUBMITTED submission always has a completed
    UnitProgress", which every production path upholds and only the demo seeder
    breaks. The repair belongs in the seeder, NOT in this card: adding a fifth query
    to compensate for a fixture-only state was explicitly rejected. This test exists
    so that decision is recorded and cannot evaporate silently.

    EXEMPT FROM FALSIFICATION, like the query-budget guards: its only "mutant" is a
    design change this spec explicitly rejected (adding a fifth query to exclude
    submitted quizzes from `open`). Do not hunt for one.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="d9", email="d9@test.example.com")
    EnrollmentFactory(student=user, course=course)
    _complete(lesson, user, 30)
    QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == quiz.pk


@pytest.mark.django_db
def test_ancestors_are_the_root_to_parent_chain_excluding_the_unit():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, order=0)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, order=0
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, order=0
    )
    user = make_verified_user(username="n1", email="n1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert [a.pk for a in r["ancestors"]] == [part.pk, chapter.pk]
    assert unit.pk not in [a.pk for a in r["ancestors"]]


@pytest.mark.django_db
def test_root_level_unit_has_no_ancestors():
    """_current_ancestors legitimately returns [] for a depth-1 unit."""
    course, units = _course_with_units(2)
    user = make_verified_user(username="n2", email="n2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    assert _resume(course, user)["ancestors"] == []


@pytest.mark.django_db
def test_stamping_the_tree_does_not_change_the_outline_html():
    """build_resume mutates the tree the outline template then renders, adding
    contains_current to every dict. That key is read ONLY by _unit_tree_node.html
    (the unit-page rail); _outline_node.html never reads it.

    TREE SHAPE IS LOAD-BEARING: ` open` lives in the container arm, which renders
    only for a non-unit node WITH children. Stamp a root-level unit and no stamped
    dict reaches that branch, so the mutant produces identical output and the test
    is GREEN on a broken build. Hence the unit is nested under a surviving chapter.

    Mutant: add `{% if item.contains_current %} open{% endif %}` to the <details>
    in _outline_node.html.
    """
    course = CourseFactory()
    # THREE levels, not two. A depth-0 container already renders ` open` from the
    # existing {% if item.depth == 0 %}, so stamping a unit under a root chapter
    # makes the mutant emit `<details ... open open>` -- the strings still differ, so
    # the test is not vacuous, but it proves the point via a duplicated attribute
    # rather than the branch the guard is about. Nesting deeper makes the chapter's
    # ` open` appear ONLY under the mutant.
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, order=0)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part, order=0
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, order=0
    )
    user = make_verified_user(username="n3", email="n3@test.example.com")
    EnrollmentFactory(student=user, course=course)

    def _render(tree):
        return "".join(
            render_to_string(
                "courses/_outline_node.html",
                {
                    "item": item,
                    "course": course,
                    "note_counts": {},
                    "active_tag_ids": [],
                },
            )
            for item in tree
        )

    tree = _tree(course, user)
    before = _render(tree)
    _stamp_current_chain(tree, unit.pk)
    after = _render(tree)
    assert before == after


@pytest.mark.django_db
def test_warm_path_costs_exactly_four_queries(django_assert_num_queries):
    """FIXTURE IS LOAD-BEARING. The student needs a live UnitProgress AND an
    IN_PROGRESS QuizSubmission on an open quiz carrying a QuestionResponse with
    last_attempt_at set -- so source C actually returns a row. With a lone
    UnitProgress, C's .first() returns None, the `row.submission.unit_id`
    dereference mutant never fires, and the count stays 4 on a broken build.
    """
    course = CourseFactory()
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", order=1)
    user = make_verified_user(username="q1", email="q1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=lesson)
    sub = QuizSubmissionFactory(
        student=user, unit=quiz, status=QuizSubmission.Status.IN_PROGRESS
    )
    _answered_question(quiz, sub, timezone.now())

    tree = _tree(course, user)  # built OUTSIDE the assertion
    with django_assert_num_queries(4):
        build_resume(course, user, tree)


@pytest.mark.django_db
def test_cold_path_with_no_rows_costs_six_queries(django_assert_num_queries):
    """Both source-E probes run. (A `Q(...) | Q(...)` collapse is NOT a
    constructible mutant -- the probes hit two different models.)"""
    course, units = _course_with_units(2)
    user = make_verified_user(username="q2", email="q2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    tree = _tree(course, user)
    with django_assert_num_queries(6):
        build_resume(course, user, tree)


@pytest.mark.django_db
def test_cold_path_short_circuits_after_the_first_probe(django_assert_num_queries):
    """source E's `or` short-circuits: history on a UnitProgress costs ONE probe."""
    course, units = _course_with_units(2)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="q3", email="q3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=ghost)
    tree = _tree(course, user)
    with django_assert_num_queries(5):
        build_resume(course, user, tree)
