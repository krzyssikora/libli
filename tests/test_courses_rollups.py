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


@pytest.mark.django_db
def test_quiz_units_in_order_is_preorder_and_excludes_non_quizzes():
    from courses.rollups import quiz_units_in_order

    course = CourseFactory()
    # Two chapters; ch1 (order 0) contains a quiz at LOCAL order 9 and a lesson at 0;
    # ch2 (order 1) contains a quiz at order 0. A naive flat scan of course.nodes.all()
    # (sorted globally by order,pk) would yield [q_b, q_a] — pre-order yields [q_a, q_b].
    ch1 = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None, order=0)
    ch2 = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None, order=1)
    q_a = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch1, order=9)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch1, order=0)
    q_b = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=ch2, order=0)

    units = quiz_units_in_order(course)
    assert [u.pk for u in units] == [q_a.pk, q_b.pk]  # pre-order; lesson + chapters excluded
