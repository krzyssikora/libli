from decimal import Decimal

import pytest

from courses.gradebook import build_matrix_table
from courses.models import Element
from courses.models import QuestionElement
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
