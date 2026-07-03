from decimal import Decimal

import pytest

from courses.models import Element
from courses.models import QuestionElement
from courses.models import ShortTextQuestionElement
from courses.rollups import quiz_gradeable_max
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


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
