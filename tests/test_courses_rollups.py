import pytest

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
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
