"""The three-level attempts resolver (spec 2026-10-20 §4)."""

import pytest

from courses.models import ShortTextQuestionElement
from courses.quiz import effective_course_attempts
from courses.quiz import effective_max_attempts
from courses.quiz import effective_unit_attempts
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _q(mode="inherit", limit=None):
    # Unsaved is enough: the resolver only reads attributes.
    return ShortTextQuestionElement(
        stem="x", accepted="a", attempts_mode=mode, attempts_limit=limit
    )


# ((course mode, limit), (unit mode, limit), (question mode, limit), expected)
CASES = [
    (("limited", 1), ("inherit", None), ("inherit", None), 1),
    (("limited", 4), ("inherit", None), ("inherit", None), 4),
    (("unlimited", None), ("inherit", None), ("inherit", None), None),
    (("limited", 4), ("limited", 2), ("inherit", None), 2),
    (("limited", 4), ("unlimited", None), ("inherit", None), None),
    (("unlimited", None), ("limited", 2), ("inherit", None), 2),
    (("limited", 4), ("limited", 2), ("limited", 7), 7),
    (("limited", 4), ("limited", 2), ("unlimited", None), None),
    (("unlimited", None), ("unlimited", None), ("limited", 3), 3),
]


@pytest.mark.parametrize("course_kw,unit_kw,q_kw,expected", CASES)
def test_resolution_matrix(course_kw, unit_kw, q_kw, expected):
    course = CourseFactory(attempts_mode=course_kw[0], attempts_limit=course_kw[1])
    unit = make_quiz_unit(
        course=course, attempts_mode=unit_kw[0], attempts_limit=unit_kw[1]
    )
    assert effective_max_attempts(_q(*q_kw), unit) == expected


def test_nothing_set_anywhere_resolves_to_one():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    add_element(unit, q)
    assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    assert effective_max_attempts(q, unit) == 1


def test_lesson_unit_override_is_skipped():
    course = CourseFactory(attempts_mode="limited", attempts_limit=4)
    lesson = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        attempts_mode="limited",
        attempts_limit=2,
    )
    assert effective_unit_attempts(lesson) == (4, "course")
    assert effective_max_attempts(_q(), lesson) == 4


def test_unit_source_word():
    course = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    assert effective_unit_attempts(make_quiz_unit(course=course)) == (None, "course")
    overriding = make_quiz_unit(
        course=course, attempts_mode="limited", attempts_limit=3
    )
    assert effective_unit_attempts(overriding) == (3, "quiz")
    assert effective_course_attempts(course) is None
