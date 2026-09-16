"""The student results page (spec §4; T6-T13, T15, T16, T28b)."""

from decimal import Decimal

import pytest

from courses.models import QuizSubmission
from courses.rollups import build_student_breakdown
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _node(course, parent, kind, title, **kw):
    unit_type = kw.pop("unit_type", None)
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title, **kw
    )


def _titles(tree):
    out = []

    def walk(nodes):
        for d in nodes:
            out.append(d["node"].title)
            walk(d["children"])

    walk(tree)
    return out


def _find(tree, title):
    for d in tree:
        if d["node"].title == title:
            return d
        hit = _find(d["children"], title)
        if hit is not None:
            return hit
    return None


def test_t10_results_keeps_a_deep_quiz_with_every_ancestor():
    course = CourseFactory()
    part = _node(course, None, "part", "Part")
    chapter = _node(course, part, "chapter", "Chapter")
    section = _node(course, chapter, "section", "Section")
    quiz = _node(course, section, "unit", "Deep quiz", unit_type="quiz")
    _node(course, section, "unit", "Side lesson", unit_type="lesson", obligatory=True)
    student = UserFactory()
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )

    tree = build_student_breakdown(course, student, drafts="keep", mode="results")[
        "tree"
    ]
    assert _titles(tree) == ["Part", "Chapter", "Section", "Deep quiz"]
    assert _find(tree, "Deep quiz")["pill"]["kind"] in {"submitted", "scored"}


def test_t15_default_mode_is_progress_and_keeps_lessons():
    course = CourseFactory()
    chapter = _node(course, None, "chapter", "Chapter")
    _node(course, chapter, "unit", "Lesson", unit_type="lesson", obligatory=True)
    _node(course, chapter, "unit", "Quiz", unit_type="quiz")
    tree = build_student_breakdown(course, UserFactory(), drafts="keep")["tree"]
    assert _titles(tree) == ["Chapter", "Lesson", "Quiz"]


def test_units_are_stamped_additional_as_a_boolean():
    course = CourseFactory()
    chapter = _node(course, None, "chapter", "Chapter")
    _node(course, chapter, "unit", "Required", unit_type="lesson", obligatory=True)
    _node(course, chapter, "unit", "Extra", unit_type="lesson", obligatory=False)
    _node(course, chapter, "unit", "Quiz", unit_type="quiz")
    tree = build_student_breakdown(course, UserFactory(), drafts="keep")["tree"]
    assert _find(tree, "Required")["additional"] is False
    assert _find(tree, "Extra")["additional"] is True
    assert _find(tree, "Quiz")["additional"] is False  # never the raw "quiz" marker
