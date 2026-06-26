import pytest

from courses.models import ContentNode
from courses.models import Course
from courses.structure_backfill import backfill_structure_flags

pytestmark = pytest.mark.django_db


def _add(course, kind, parent=None):
    extra = {"unit_type": "lesson"} if kind == "unit" else {}
    return ContentNode.objects.create(
        course=course, kind=kind, title=kind, parent=parent, **extra
    )


def test_allowed_kinds_full_default():
    c = Course.objects.create(title="C", slug="c-full")
    assert c.allowed_kinds == ["part", "chapter", "section", "unit"]


def test_allowed_kinds_flat():
    c = Course.objects.create(
        title="C",
        slug="c-flat",
        uses_parts=False,
        uses_chapters=False,
        uses_sections=False,
    )
    assert c.allowed_kinds == ["unit"]


def test_allowed_kinds_chapters():
    c = Course.objects.create(
        title="C",
        slug="c-ch",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    assert c.allowed_kinds == ["chapter", "unit"]


def test_backfill_units_only_to_flat():
    c = Course.objects.create(title="C", slug="c1")
    _add(c, "unit")
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (False, False, False)


def test_backfill_chapters_only():
    c = Course.objects.create(title="C", slug="c2")
    ch = _add(c, "chapter")
    _add(c, "unit", parent=ch)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (False, True, False)


def test_backfill_parts_chapters():
    c = Course.objects.create(title="C", slug="c3")
    p = _add(c, "part")
    ch = _add(c, "chapter", parent=p)
    _add(c, "unit", parent=ch)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, False)


def test_backfill_mixed_custom():
    c = Course.objects.create(title="C", slug="c5")
    p = _add(c, "part")
    s = _add(c, "section", parent=p)
    _add(c, "unit", parent=s)
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, False, True)


def test_backfill_empty_course_keeps_full():
    c = Course.objects.create(title="C", slug="c4")
    backfill_structure_flags(Course, ContentNode)
    c.refresh_from_db()
    assert (c.uses_parts, c.uses_chapters, c.uses_sections) == (True, True, True)
