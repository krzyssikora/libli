from decimal import Decimal

import pytest

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import (
    EnrollmentFactory,  # noqa: F401  (used by later tasks' tests)
)
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_rollup_required_additional_and_quiz_excluded():
    from courses.rollups import build_outline

    course = CourseFactory()
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None
    )
    u1 = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=True
    )
    ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=True
    )
    extra = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=False
    )
    ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="quiz", obligatory=True
    )
    user = UserFactory()
    UnitProgressFactory(student=user, unit=u1, completed=True)
    UnitProgressFactory(student=user, unit=extra, completed=True)

    roots = build_outline(course, user)
    ch = roots[0]
    assert ch["required_total"] == 2  # two obligatory lessons; quiz excluded
    assert ch["required_done"] == 1
    assert ch["additional_done"] == 1


@pytest.mark.django_db
def test_rollup_container_less_course():
    from courses.rollups import build_outline

    course = CourseFactory()
    ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson", obligatory=True
    )
    user = UserFactory()
    roots = build_outline(course, user)
    assert len(roots) == 1
    assert roots[0]["required_total"] == 1


@pytest.mark.django_db
def test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes():
    from courses.rollups import quiz_units_in_order

    course = CourseFactory()
    # Two chapters; ch1 (order 0) contains a quiz at LOCAL order 9 and a lesson at 0;
    # ch2 (order 1) contains a quiz at order 0. A naive flat scan of course.nodes.all()
    # (sorted globally by order,pk) would yield [q_b, q_a] — pre-order yields [q_a,
    # q_b].
    ch1 = ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None, order=0
    )
    ch2 = ContentNodeFactory(
        course=course, kind="chapter", parent=None, unit_type=None, order=1
    )
    q_a = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch1, order=9
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch1, order=0
    )
    q_b = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=ch2, order=0
    )

    units = quiz_units_in_order(course)
    # pre-order; lesson + chapters excluded
    assert [u.pk for u in units] == [q_a.pk, q_b.pk]


def _quiz_with_questions(course, modes):
    """A quiz unit (root-level) whose questions have the given marking modes.
    modes: list of (mode, max_marks_decimal). Returns the unit."""
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    for i, (mode, mm) in enumerate(modes):
        q = ShortTextQuestionElement.objects.create(
            stem=f"q{i}", accepted="a", marking_mode=mode, max_marks=mm
        )
        Element.objects.create(unit=unit, content_object=q)
    return unit


@pytest.mark.django_db
def test_build_course_results_combined_headline_and_statuses():
    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()
    # A: submitted [A] 6/10
    a = _quiz_with_questions(course, [("A", Decimal("10"))])
    QuizSubmissionFactory(
        student=student,
        unit=a,
        status="submitted",
        score=Decimal("6.00"),
        max_score=Decimal("10.00"),
    )
    # B: awaiting_review [A+R], frozen [A] portion 3/5
    b = _quiz_with_questions(course, [("A", Decimal("5")), ("R", Decimal("4"))])
    QuizSubmissionFactory(
        student=student,
        unit=b,
        status="submitted",
        score=Decimal("3.00"),
        max_score=Decimal("5.00"),
    )
    # C: fully-[N] 0/0
    c = _quiz_with_questions(course, [("N", Decimal("1"))])
    QuizSubmissionFactory(
        student=student,
        unit=c,
        status="submitted",
        score=Decimal("0.00"),
        max_score=Decimal("0.00"),
    )
    # D: in_progress
    d = _quiz_with_questions(course, [("A", Decimal("1"))])
    QuizSubmissionFactory(student=student, unit=d, status="in_progress")
    # E: not_started (no submission)
    _quiz_with_questions(course, [("A", Decimal("1"))])

    s = build_course_results(course, student)
    assert s["done_count"] == 3
    assert s["total_count"] == 5
    assert s["score"] == Decimal("9.00")
    assert s["max_score"] == Decimal("15.00")
    assert s["percent"] == 60
    assert isinstance(s["percent"], int)
    assert isinstance(s["done_count"], int)
    by_pk = {r["unit"].pk: r for r in s["rows"]}
    assert by_pk[a.pk]["status"] == "submitted" and by_pk[a.pk]["graded"] is True
    assert by_pk[b.pk]["status"] == "awaiting_review" and by_pk[b.pk]["pending"] is True
    assert by_pk[b.pk]["graded"] is True
    assert by_pk[c.pk]["status"] == "submitted" and by_pk[c.pk]["graded"] is False
    assert by_pk[d.pk]["status"] == "in_progress"


@pytest.mark.django_db
def test_awaiting_review_is_element_driven_even_for_unanswered_review_question():
    # C1 regression: QuestionResponse rows are lazy; an unanswered [R] has no row.
    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()
    # all-[R], nothing answered
    unit = _quiz_with_questions(course, [("R", Decimal("4"))])
    QuizSubmissionFactory(
        student=student,
        unit=unit,
        status="submitted",
        score=Decimal("0.00"),
        max_score=Decimal("0.00"),
    )

    row = build_course_results(course, student)["rows"][0]
    assert row["status"] == "awaiting_review"
    assert row["pending"] is True
    assert row["graded"] is False  # no [A] question


@pytest.mark.django_db
def test_build_course_results_empty_and_zero_guards():
    from courses.rollups import build_course_results

    # No quizzes at all → empty rows, percent None.
    empty_course = CourseFactory()
    s0 = build_course_results(empty_course, UserFactory())
    assert s0["rows"] == [] and s0["total_count"] == 0 and s0["percent"] is None

    # One quiz, none submitted → not_started, percent None.
    course = CourseFactory()
    student = UserFactory()
    _quiz_with_questions(course, [("A", Decimal("1"))])
    s1 = build_course_results(course, student)
    assert s1["done_count"] == 0 and s1["total_count"] == 1
    assert s1["rows"][0]["status"] == "not_started"
    assert s1["percent"] is None and s1["score"] is None


@pytest.mark.django_db
def test_build_course_results_row_url_names():
    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()
    sub_unit = _quiz_with_questions(course, [("A", Decimal("1"))])
    QuizSubmissionFactory(
        student=student,
        unit=sub_unit,
        status="submitted",
        score=Decimal("1.00"),
        max_score=Decimal("1.00"),
    )
    _quiz_with_questions(course, [("A", Decimal("1"))])  # not started

    by_status = {r["status"]: r for r in build_course_results(course, student)["rows"]}
    assert by_status["submitted"]["url_name"] == "courses:quiz_results"
    assert by_status["not_started"]["url_name"] == "courses:quiz_unit"


@pytest.mark.django_db
def test_build_course_results_query_count_is_size_independent():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from courses.rollups import build_course_results

    course = CourseFactory()
    student = UserFactory()

    def add(n):
        for _ in range(n):
            u = _quiz_with_questions(course, [("A", Decimal("1"))])
            QuizSubmissionFactory(
                student=student,
                unit=u,
                status="submitted",
                score=Decimal("1.00"),
                max_score=Decimal("1.00"),
            )

    add(3)
    build_course_results(course, student)  # warm the ContentType cache
    with CaptureQueriesContext(connection) as c1:
        build_course_results(course, student)
    add(20)
    with CaptureQueriesContext(connection) as c2:
        build_course_results(course, student)
    assert len(c1) == len(c2)  # N-independent: no per-unit / per-submission N+1
