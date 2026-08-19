from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from courses.models import Element
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
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
