import pytest

from courses.models import ContentNode
from courses.rollups import units_under
from tests.factories import make_course

pytestmark = pytest.mark.django_db


def _node(course, kind, parent=None, unit_type=None, title="n"):
    kw = {}
    if unit_type:
        kw["unit_type"] = unit_type
    return ContentNode.objects.create(
        course=course, kind=kind, parent=parent, title=title, **kw
    )


def test_units_under_a_chapter_returns_its_units_only():
    course = make_course()
    ch1 = _node(course, ContentNode.Kind.CHAPTER, title="c1")
    ch2 = _node(course, ContentNode.Kind.CHAPTER, title="c2")
    u1 = _node(course, ContentNode.Kind.UNIT, ch1, ContentNode.UnitType.LESSON, "u1")
    u2 = _node(course, ContentNode.Kind.UNIT, ch1, ContentNode.UnitType.LESSON, "u2")
    _u3 = _node(course, ContentNode.Kind.UNIT, ch2, ContentNode.UnitType.LESSON, "u3")
    assert units_under(ch1) == {u1, u2}


def test_units_under_a_unit_is_inclusive():
    course = make_course()
    u1 = _node(course, ContentNode.Kind.UNIT, None, ContentNode.UnitType.LESSON, "u1")
    assert units_under(u1) == {u1}


def test_units_under_descends_through_nested_levels():
    course = make_course()
    part = _node(course, ContentNode.Kind.PART, title="p")
    ch = _node(course, ContentNode.Kind.CHAPTER, part, title="c")
    sec = _node(course, ContentNode.Kind.SECTION, ch, title="s")
    u = _node(course, ContentNode.Kind.UNIT, sec, ContentNode.UnitType.LESSON, "u")
    assert units_under(part) == {u}


def test_units_under_includes_quiz_units():
    # Reset clears whatever is there; quiz units simply hold nothing.
    course = make_course()
    ch = _node(course, ContentNode.Kind.CHAPTER, title="c")
    q = _node(course, ContentNode.Kind.UNIT, ch, ContentNode.UnitType.QUIZ, "q")
    assert units_under(ch) == {q}


def test_units_under_an_empty_chapter_is_empty():
    course = make_course()
    ch = _node(course, ContentNode.Kind.CHAPTER, title="c")
    assert units_under(ch) == set()
