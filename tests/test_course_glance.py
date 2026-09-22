"""Course glance bars (spec 2026-09-22-course-glance-bars-design.md)."""

from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rollups import _course_required_totals
from courses.rollups import _pct
from courses.rollups import _progress_width
from courses.rollups import _results_width
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [
        (0, 0, None),  # no required lessons: track only (D4)
        (0, 5, None),  # nothing done: track only, NO dot (D4)
        (1, 250, 1),  # rounds to 0 but must still draw a sliver
        (199, 200, 99),  # rounds to 100 but the course is not finished
        (1, 2, 50),
        (5, 5, 100),
        (6, 5, 100),  # defensive: done > total is still full, never 99
    ],
)
def test_progress_width(done, total, expected):
    assert _progress_width(done, total) == expected


@pytest.mark.parametrize(
    ("score", "max_score", "percent", "expected"),
    [
        (None, None, None, None),  # nothing submitted
        (Decimal("0"), Decimal("0"), None, None),  # pending-only / max 0: NOT the dot
        (Decimal("0"), Decimal("10"), 0, 0),  # scored zero: the dot (D3)
        (Decimal("1"), Decimal("300"), 0, 1),  # branches on score, not rounded pct
        (Decimal("299"), Decimal("300"), 100, 99),  # not full while short of max
        (Decimal("16"), Decimal("20"), 80, 80),  # D1 example
        (Decimal("10"), Decimal("10"), 100, 100),
        (Decimal("11"), Decimal("10"), 110, 100),  # score > max stays full
    ],
)
def test_results_width(score, max_score, percent, expected):
    assert _results_width(score, max_score, percent) == expected


def test_results_width_half_boundary_matches_pct():
    # 1/8 = 12.5 -> ROUND_HALF_EVEN -> 12, the same rounding as the spoken percent
    assert _results_width(Decimal("1"), Decimal("8"), _pct(1, 8)) == 12 == _pct(1, 8)


def test_course_required_totals_sums_top_level_items():
    tree = [
        {"required_done": 1, "required_total": 3},
        {"required_done": 2, "required_total": 2},
    ]
    assert _course_required_totals(tree) == (3, 5)
    assert _course_required_totals([]) == (0, 0)


def _lesson(course, *, obligatory=True, published=True):
    return ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        obligatory=obligatory,
        published=published,
    )


def _auto_quiz(course, student, *, score, max_score, max_marks=None):
    """A root quiz with one auto-marked short-text question and a SUBMITTED
    submission scored score/max_score."""
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=max_marks or max_score
    )
    Element.objects.create(unit=unit, content_object=q)
    QuizSubmissionFactory(
        student=student,
        unit=unit,
        status="submitted",
        score=Decimal(score),
        max_score=Decimal(max_score),
    )
    return unit


def _review_quiz(course, student, *, reviewed):
    """A root quiz with one [R] extended-response question and a SUBMITTED
    submission; reviewed=True adds a reviewed response and scores it 4/5."""
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    el = Element.objects.create(unit=unit, content_object=q)
    sub = QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0.00"),
        max_score=Decimal("0.00"),
    )
    if reviewed:
        QuestionResponse.objects.create(
            submission=sub,
            element=el,
            earned_marks=Decimal("4.00"),
            fraction=Decimal("0.8000"),
            reviewed_at=timezone.now(),
            locked=True,
        )
        sub.score = Decimal("4.00")
        sub.max_score = Decimal("5.00")
        sub.save()
    return unit


GLANCE_KEYS = {
    "progress_done",
    "progress_total",
    "results_pct",
    "progress_width",
    "results_width",
}


@pytest.mark.django_db
def test_d1_cumulative_not_mean_of_percentages():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="9", max_score="10")
    _auto_quiz(course, student, score="3", max_score="5")
    _auto_quiz(course, student, score="4", max_score="5")
    g = course_glance(course, student, drafts="hide")
    assert set(g) == GLANCE_KEYS
    assert g["results_pct"] == 80  # 16/20, NOT mean(90, 60, 80) = 77
    assert g["results_width"] == 80


@pytest.mark.django_db
def test_no_submission_is_track_only():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] is None and g["results_width"] is None


@pytest.mark.django_db
def test_scored_zero_is_the_dot():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="0", max_score="10")
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] == 0 and g["results_width"] == 0


@pytest.mark.django_db
def test_pending_only_is_track_only_not_the_dot():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _review_quiz(course, student, reviewed=False)
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] is None
    assert g["results_width"] is None  # score is Decimal("0") here: order matters


@pytest.mark.django_db
def test_pending_quiz_is_excluded_from_the_sum():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="3", max_score="4")
    _review_quiz(course, student, reviewed=False)
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] == 75 and g["results_width"] == 75


@pytest.mark.django_db
def test_max_score_zero_quiz_is_track_only():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _auto_quiz(course, student, score="0", max_score="0", max_marks=Decimal("0"))
    g = course_glance(course, student, drafts="hide")
    assert g["results_pct"] is None and g["results_width"] is None


@pytest.mark.django_db
def test_progress_counts_only_required_lessons():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    done = _lesson(course)
    _lesson(course)
    extra = _lesson(course, obligatory=False)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, obligatory=True
    )
    UnitProgressFactory(student=student, unit=done, completed=True)
    UnitProgressFactory(student=student, unit=extra, completed=True)
    UnitProgressFactory(student=student, unit=quiz, completed=True)
    g = course_glance(course, student, drafts="hide")
    assert (g["progress_done"], g["progress_total"]) == (1, 2)
    assert g["progress_width"] == 50


@pytest.mark.django_db
def test_zero_of_n_and_no_required_lessons_are_track_only():
    from courses.rollups import course_glance

    student = UserFactory()
    untouched = CourseFactory()
    _lesson(untouched)
    g = course_glance(untouched, student, drafts="hide")
    assert (g["progress_done"], g["progress_total"]) == (0, 1)
    assert g["progress_width"] is None

    empty = CourseFactory()
    g = course_glance(empty, student, drafts="hide")
    assert g["progress_total"] == 0 and g["progress_width"] is None


@pytest.mark.django_db
def test_drafts_hide_excludes_draft_lessons():
    from courses.rollups import course_glance

    course, student = CourseFactory(), UserFactory()
    _lesson(course)
    _lesson(course, published=False)
    assert course_glance(course, student, drafts="hide")["progress_total"] == 1
    assert course_glance(course, student, drafts="keep")["progress_total"] == 2


@pytest.mark.django_db
def test_containment_logs_and_returns_unknown(monkeypatch, caplog):
    import courses.rollups as rollups

    course, student = CourseFactory(), UserFactory()

    def boom(*args, **kwargs):
        raise RuntimeError("inconsistent tree")

    monkeypatch.setattr(rollups, "course_glance", boom)
    with caplog.at_level("ERROR", logger="courses.rollups"):
        g = rollups.course_glance_or_unknown(course, student, drafts="hide")
    assert g == rollups.UNKNOWN_GLANCE
    assert g is not rollups.UNKNOWN_GLANCE  # a copy: callers cannot mutate the constant
    assert f"pk={course.pk}" in caplog.text
    assert "inconsistent tree" in caplog.text


def _shaped_course(student, n):
    """The query-count fixture shape (spec Testing): every query branch non-empty,
    ONE question type. n of each: required lessons (all completed), additional
    lessons, reviewed [R] quizzes with submissions."""
    course = CourseFactory()
    for _ in range(n):
        req = _lesson(course)
        UnitProgressFactory(student=student, unit=req, completed=True)
        _lesson(course, obligatory=False)
        _review_quiz(course, student, reviewed=True)
    return course


@pytest.mark.django_db
def test_course_glance_query_count_is_size_independent():
    from courses.rollups import course_glance

    student = UserFactory()
    small = _shaped_course(student, 1)
    large = _shaped_course(student, 5)
    course_glance(small, student, drafts="hide")  # warm the ContentType cache
    with CaptureQueriesContext(connection) as c_small:
        course_glance(small, student, drafts="hide")
    with CaptureQueriesContext(connection) as c_large:
        course_glance(large, student, drafts="hide")
    assert len(c_small) == len(c_large)
