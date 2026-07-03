from decimal import Decimal

import pytest

from courses.gradebook import build_matrix_table
from courses.gradebook import build_quiz_gradebook
from courses.models import Element
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rollups import quiz_gradeable_max
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


def _chapter(course, **kw):
    kw.setdefault("unit_type", None)
    return ContentNodeFactory(course=course, kind="chapter", parent=None, **kw)


def _quiz(course, parent, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=parent, **kw
    )


def _q(unit, mode, marks):
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode=mode, max_marks=Decimal(marks)
    )
    return Element.objects.create(unit=unit, content_object=q)


def _lesson(course, parent, obligatory=True, **kw):
    return ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=parent,
        obligatory=obligatory,
        **kw,
    )


@pytest.mark.django_db
def test_quiz_gradeable_max_sums_auto_and_review_excludes_not_marked():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _q(qz, QuestionElement.MarkingMode.AUTO, "3")
    _q(qz, QuestionElement.MarkingMode.REVIEW, "7")
    _q(qz, QuestionElement.MarkingMode.NOT_MARKED, "5")  # excluded
    result = quiz_gradeable_max([qz])
    assert result == {qz.pk: Decimal("10")}


@pytest.mark.django_db
def test_quiz_gradeable_max_zero_when_no_gradeable_questions():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _q(qz, QuestionElement.MarkingMode.NOT_MARKED, "5")
    empty = _quiz(course, ch)  # no questions at all
    result = quiz_gradeable_max([qz, empty])
    assert result == {qz.pk: Decimal("0"), empty.pk: Decimal("0")}


@pytest.mark.django_db
def test_quiz_gradeable_max_empty_units():
    assert quiz_gradeable_max([]) == {}


@pytest.mark.django_db
def test_build_matrix_table_mirrors_progress_matrix():
    course = CourseFactory()
    ch = _chapter(course)
    les = _lesson(course, ch)
    s1, s2 = UserFactory(username="aaa"), UserFactory(username="bbb")
    UnitProgressFactory(student=s1, unit=les, completed=True)  # s1 100%, s2 0%
    table = build_matrix_table(course, [s1, s2], mode="progress", expanded=frozenset())
    assert table["total_kind"] == "percent"
    assert table["meta_row"] is None
    assert [c["kind"] for c in table["columns"]] == ["percent"]
    # rows carry integer percents pulled out of the _cell dicts, not the dicts
    assert table["rows"][0]["cells"] == [100]
    assert table["rows"][0]["total"] == 100
    assert table["rows"][1]["cells"] == [0]
    # participants average of [100, 0] = 50
    assert table["footer"][0]["values"] == [50]
    assert table["title"] == "" and table["subtitle"] == ""


@pytest.mark.django_db
def test_build_matrix_table_neutral_cell_is_none():
    course = CourseFactory()
    ch = _chapter(course)
    _quiz(course, ch)  # results mode, no submissions -> neutral
    s1 = UserFactory()
    table = build_matrix_table(course, [s1], mode="results", expanded=frozenset())
    assert table["rows"][0]["cells"] == [None]  # neutral -> None, not "—", not 0


@pytest.mark.django_db
def test_build_matrix_table_honours_expand_set():
    course = CourseFactory()
    ch = _chapter(course)
    _lesson(course, ch)
    _lesson(course, ch)
    s1 = UserFactory(username="a")
    # un-expanded: one aggregated column (the chapter)
    collapsed = build_matrix_table(course, [s1], mode="progress", expanded=frozenset())
    assert len(collapsed["columns"]) == 1
    # expanded through the chapter: its two lesson columns
    expanded = build_matrix_table(
        course, [s1], mode="progress", expanded=frozenset({ch.pk})
    )
    assert len(expanded["columns"]) == 2


def _submit(student, unit, score, max_score, status="submitted"):
    return QuizSubmission.objects.create(
        student=student,
        unit=unit,
        status=status,
        score=Decimal(score),
        max_score=Decimal(max_score),
    )


@pytest.mark.django_db
def test_quiz_gradebook_scores_markers_max_and_total():
    course = CourseFactory()
    ch = _chapter(course)
    qz1 = _quiz(course, ch, title="Quiz")
    qz2 = _quiz(course, ch, title="Quiz")  # duplicate title
    _q1 = _q(qz1, QuestionElement.MarkingMode.AUTO, "10")
    _q2 = _q(qz2, QuestionElement.MarkingMode.AUTO, "10")
    s_done = UserFactory(username="done")
    s_prog = UserFactory(username="prog")
    s_none = UserFactory(username="none")
    _submit(s_done, qz1, "7", "10")  # counted -> 7
    _submit(s_prog, qz1, "0", "0", status="in_progress")  # -> "…"
    # s_none: nothing -> "—"
    table = build_quiz_gradebook(course, [s_done, s_prog, s_none], numbers_only=False)
    assert [c["label"] for c in table["columns"]] == ["1. Quiz", "2. Quiz"]
    assert [c["max"] for c in table["columns"]] == [Decimal("10"), Decimal("10")]
    assert table["meta_row"]["label"] == "Max"
    assert table["meta_row"]["total"] == Decimal("20")
    assert table["total_kind"] == "score"
    r0, r1, r2 = table["rows"]
    assert r0["cells"][0] == Decimal("7") and r0["cells"][1] == "—"
    assert r0["total"] == Decimal("7")
    assert r1["cells"][0] == "…" and r1["total"] is None
    assert r2["cells"][0] == "—" and r2["total"] is None


@pytest.mark.django_db
def test_quiz_gradebook_numbers_only_blanks_markers_not_scores():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="Q")
    _q(qz, QuestionElement.MarkingMode.AUTO, "10")
    s1, s2 = UserFactory(username="a"), UserFactory(username="b")
    _submit(s1, qz, "5", "10")  # counted
    # s2 not started
    table = build_quiz_gradebook(course, [s1, s2], numbers_only=True)
    assert table["rows"][0]["cells"][0] == Decimal("5")  # real score untouched
    assert table["rows"][1]["cells"][0] is None  # marker blanked


@pytest.mark.django_db
def test_quiz_gradebook_awaiting_review_marker_R():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="Q")
    _q(qz, QuestionElement.MarkingMode.REVIEW, "10")  # one [R], never reviewed
    s1 = UserFactory()
    _submit(s1, qz, "0", "10")  # SUBMITTED but the [R] is unreviewed -> pending
    table = build_quiz_gradebook(course, [s1], numbers_only=False)
    assert table["rows"][0]["cells"][0] == "R"
    assert table["rows"][0]["total"] is None


@pytest.mark.django_db
def test_quiz_gradebook_participants_only_average_quantized():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="Q")
    _q(qz, QuestionElement.MarkingMode.AUTO, "10")
    s1, s2, s3 = (UserFactory(username=u) for u in ("a", "b", "c"))
    _submit(s1, qz, "10", "10")
    _submit(s2, qz, "5", "10")
    # s3 not taken -> excluded from denominator
    table = build_quiz_gradebook(course, [s1, s2, s3], numbers_only=False)
    # mean(10, 5) over 2 participants = 7.50, quantized to 2dp
    assert table["footer"][0]["values"][0] == Decimal("7.50")
    assert table["footer"][0]["total"] == Decimal("7.50")


@pytest.mark.django_db
def test_quiz_gradebook_non_gradeable_column_blank_and_excluded():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch, title="NM")
    _q(qz, QuestionElement.MarkingMode.NOT_MARKED, "5")  # max 0 -> non-gradeable
    s1 = UserFactory()
    _submit(s1, qz, "0", "0")  # a counted submission exists
    table = build_quiz_gradebook(course, [s1], numbers_only=False)
    assert table["columns"][0]["max"] == Decimal("0")
    assert table["rows"][0]["cells"][0] is None  # blanked
    assert table["rows"][0]["total"] is None  # excluded from total
    assert table["footer"][0]["values"][0] is None  # excluded from average


@pytest.mark.django_db
def test_quiz_gradebook_no_quizzes_and_empty_students():
    course = CourseFactory()
    _chapter(course)
    assert build_quiz_gradebook(course, [], numbers_only=False)["rows"] == []
    empty = build_quiz_gradebook(course, [UserFactory()], numbers_only=False)
    assert empty["columns"] == [] and empty["rows"][0]["cells"] == []
