from decimal import Decimal

import pytest
from django.utils import timezone

from courses import quiz as quiz_svc
from courses import review as review_svc
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuestionResponseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_review_feedback_defaults_to_empty_string():
    r = QuestionResponseFactory()
    r.refresh_from_db()
    assert r.review_feedback == ""
    # field is editable plain text
    r.review_feedback = "Nice working."
    r.save()
    r.refresh_from_db()
    assert r.review_feedback == "Nice working."


def _auto_q(unit, *, max_marks="2"):
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?",
        accepted="4",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _review_q(unit, *, max_marks="5"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def test_compute_scores_auto_only_at_submit():
    sub = QuizSubmissionFactory()
    unit = sub.unit
    auto = _auto_q(unit, max_marks="2")
    _review_q(unit, max_marks="5")  # unreviewed -> excluded from both
    QuestionResponse.objects.create(
        submission=sub,
        element=auto,
        fraction=Decimal("1.0000"),
        earned_marks=Decimal("2.00"),
        locked=True,
    )
    score, max_score = quiz_svc.compute_scores(unit, sub)
    assert score == Decimal("2.00")
    assert max_score == Decimal("2.00")  # the [R] max is NOT counted until reviewed


def test_compute_scores_includes_reviewed_review_in_both():
    sub = QuizSubmissionFactory()
    unit = sub.unit
    rev = _review_q(unit, max_marks="5")
    QuestionResponse.objects.create(
        submission=sub,
        element=rev,
        earned_marks=Decimal("3.00"),
        fraction=Decimal("0.6000"),
        reviewed_at=timezone.now(),
        locked=True,
    )
    score, max_score = quiz_svc.compute_scores(unit, sub)
    assert score == Decimal("3.00")
    assert max_score == Decimal("5.00")


def test_finalize_submission_freezes_auto_only(client):
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.IN_PROGRESS)
    unit = sub.unit
    auto = _auto_q(unit, max_marks="2")
    QuestionResponse.objects.create(
        submission=sub,
        element=auto,
        fraction=Decimal("0.5000"),
        earned_marks=Decimal("1.00"),
        locked=False,
    )
    quiz_svc.finalize_submission(unit, sub)
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.submitted_at is not None
    assert sub.score == Decimal("1.00")
    assert sub.max_score == Decimal("2.00")
    assert sub.responses.filter(locked=False).count() == 0


def test_review_response_creates_row_for_unanswered_review():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    el = _review_q(sub.unit, max_marks="5")  # no QuestionResponse exists yet
    teacher = QuizSubmissionFactory().student  # any user
    r = review_svc.review_response(
        submission=sub,
        element=el,
        earned_marks=Decimal("4.00"),
        feedback="good",
        reviewer=teacher,
    )
    assert r.earned_marks == Decimal("4.00")
    assert r.fraction == Decimal("0.8000")
    assert r.review_feedback == "good"
    assert r.reviewed_at is not None
    assert r.reviewed_by_id == teacher.pk
    sub.refresh_from_db()
    assert sub.score == Decimal("4.00")
    assert sub.max_score == Decimal("5.00")  # [R] now counted in max


def test_review_response_rejects_over_max_is_caller_guard():
    # bounds are the form's job; the service asserts as a programming guard
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    el = _review_q(sub.unit, max_marks="5")
    with pytest.raises(AssertionError):
        review_svc.review_response(
            submission=sub,
            element=el,
            earned_marks=Decimal("6.00"),
            feedback="",
            reviewer=sub.student,
        )


def test_review_response_rejects_non_review_element():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    auto = _auto_q(sub.unit, max_marks="2")
    with pytest.raises(ValueError):
        review_svc.review_response(
            submission=sub,
            element=auto,
            earned_marks=Decimal("1.00"),
            feedback="",
            reviewer=sub.student,
        )


def test_review_response_remark_overwrites():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    el = _review_q(sub.unit, max_marks="5")
    review_svc.review_response(
        submission=sub,
        element=el,
        earned_marks=Decimal("2.00"),
        feedback="",
        reviewer=sub.student,
    )
    r = review_svc.review_response(
        submission=sub,
        element=el,
        earned_marks=Decimal("5.00"),
        feedback="better",
        reviewer=sub.student,
    )
    assert r.earned_marks == Decimal("5.00")
    assert r.review_feedback == "better"
    sub.refresh_from_db()
    assert sub.score == Decimal("5.00")


def test_force_submit_closes_in_progress_and_stamps_by():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.IN_PROGRESS)
    _auto_q(sub.unit, max_marks="2")
    teacher = UserFactory()
    review_svc.force_submit_quiz(sub, by=teacher)
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.submitted_by_id == teacher.pk
    assert sub.submitted_at is not None
    # progress recorded for the STUDENT, not the teacher
    assert UnitProgress.objects.filter(
        student=sub.student, unit=sub.unit, completed=True
    ).exists()
    assert not UnitProgress.objects.filter(student=teacher).exists()


def test_force_submit_already_submitted_is_noop():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    teacher = UserFactory()
    review_svc.force_submit_quiz(sub, by=teacher)
    sub.refresh_from_db()
    assert sub.submitted_by_id is None  # untouched


def test_force_submit_review_quiz_becomes_awaiting():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.IN_PROGRESS)
    # Add an AUTO question (max 2) alongside the [R] (max 5). max_score must reflect
    # the AUTO 2.00 and EXCLUDE the unreviewed [R] — pinning a NON-default 2.00 so the
    # test fails if finalize_submission didn't actually write max_score (a bare 0.00
    # default would pass a weaker assertion).
    _auto_q(sub.unit, max_marks="2")
    _review_q(sub.unit, max_marks="5")
    review_svc.force_submit_quiz(sub, by=UserFactory())
    sub.refresh_from_db()
    assert sub.status == QuizSubmission.Status.SUBMITTED
    assert sub.max_score == Decimal("2.00")  # AUTO counted; [R] excluded until reviewed


def _two_quiz_units(course):
    return [
        ContentNodeFactory(course=course, kind="unit", unit_type="quiz"),
        ContentNodeFactory(course=course, kind="unit", unit_type="quiz"),
    ]


def test_submission_review_state_counts_unanswered_review():
    sub = QuizSubmissionFactory(status=QuizSubmission.Status.SUBMITTED)
    _review_q(sub.unit, max_marks="5")  # one [R], unanswered (no response)
    _review_q(sub.unit, max_marks="5")  # second [R]
    st = review_svc.submission_review_state(sub)
    assert st == {"total": 2, "reviewed": 0, "remaining": 2, "fully_reviewed": False}


def test_pending_reviews_for_lists_awaiting_and_in_progress():
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    u1, u2 = _two_quiz_units(course)
    # u1: submitted with an unanswered [R] -> awaiting
    _review_q(u1, max_marks="5")
    QuizSubmission.objects.create(
        student=student,
        unit=u1,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    # u2: in progress
    QuizSubmission.objects.create(
        student=student,
        unit=u2,
        status=QuizSubmission.Status.IN_PROGRESS,
    )
    data = review_svc.pending_reviews_for(owner, course)
    assert [s.unit_id for s in data["awaiting"]] == [u1.pk]
    assert [s.unit_id for s in data["in_progress"]] == [u2.pk]


def test_pending_reviews_excludes_fully_reviewed_and_out_of_scope():
    from django.utils import timezone

    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    # A SUBMITTED quiz whose only [R] is reviewed -> NOT awaiting.
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    rev = _review_q(unit, max_marks="5")
    done = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("5"),
        max_score=Decimal("5"),
    )
    QuestionResponse.objects.create(
        submission=done,
        element=rev,
        earned_marks=Decimal("5.00"),
        fraction=Decimal("1.0000"),
        reviewed_at=timezone.now(),
        locked=True,
    )
    # A submission for a student the owner cannot reach is invisible — here, the
    # owner CAN reach all enrolled, so use a different course's submission as the
    # out-of-scope case (its student is not enrolled in `course`).
    other_course = CourseFactory(owner=UserFactory())
    other_unit = ContentNodeFactory(course=other_course, kind="unit", unit_type="quiz")
    _review_q(other_unit, max_marks="5")
    QuizSubmission.objects.create(
        student=UserFactory(),
        unit=other_unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    data = review_svc.pending_reviews_for(owner, course)
    assert data["awaiting"] == []  # fully-reviewed dropped; other-course excluded
    assert data["in_progress"] == []
