import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from courses import ordering
from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


def _unit(course, parent=None, title="u"):
    return ContentNodeFactory(
        course=course, parent=parent, kind="unit", unit_type="lesson", title=title
    )


@pytest.mark.django_db
def test_move_in_list_swaps():
    course = CourseFactory()
    a, b, c = (
        _unit(course, title="a"),
        _unit(course, title="b"),
        _unit(course, title="c"),
    )
    siblings = list(
        ContentNode.objects.filter(course=course, parent=None).order_by("order", "pk")
    )
    moved = ordering.move_in_list(siblings, b, "up")
    assert [n.pk for n in moved] == [b.pk, a.pk, c.pk]


@pytest.mark.django_db
def test_move_in_list_boundary_returns_none():
    course = CourseFactory()
    a = _unit(course, title="a")
    siblings = list(ContentNode.objects.filter(course=course, parent=None))
    assert ordering.move_in_list(siblings, a, "up") is None


@pytest.mark.django_db
def test_reorder_assigns_distinct_orders_even_when_tied():
    course = CourseFactory()
    a, b = _unit(course, title="a"), _unit(course, title="b")
    ContentNode.objects.filter(pk__in=[a.pk, b.pk]).update(order=0)  # force a tie
    siblings = list(
        ContentNode.objects.filter(course=course, parent=None).order_by("order", "pk")
    )
    ordering.assign_orders_nodes(ordering.move_in_list(siblings, b, "up"))
    orders = list(
        ContentNode.objects.filter(course=course, parent=None)
        .order_by("order")
        .values_list("pk", "order")
    )
    assert [pk for pk, _ in orders] == [b.pk, a.pk]
    assert [o for _, o in orders] == [0, 1]  # strictly distinct


@pytest.mark.django_db
def test_compact_closes_gap():
    course = CourseFactory()
    _a, b, _c = (
        _unit(course, title="a"),
        _unit(course, title="b"),
        _unit(course, title="c"),
    )
    b.delete()
    ordering.compact_nodes(course, None)
    orders = sorted(
        ContentNode.objects.filter(course=course, parent=None).values_list(
            "order", flat=True
        )
    )
    assert orders == [0, 1]


@pytest.mark.django_db
def test_place_node_inserts_at_position():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    _a = _unit(course, parent=part, title="a")
    _b = _unit(course, parent=part, title="b")
    moving = _unit(course, parent=None, title="m")
    moving.parent = part
    ordering.place_node(moving, part, course, position=1)
    kids = list(
        ContentNode.objects.filter(course=course, parent=part)
        .order_by("order")
        .values_list("title", flat=True)
    )
    assert kids == ["a", "m", "b"]


@pytest.mark.django_db
def test_assert_not_descendant_rejects_cycle():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None)
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=part)
    with pytest.raises(ValidationError):
        # chapter is a descendant of part
        ordering.assert_not_descendant(part, chapter)


@pytest.mark.django_db
def test_assert_not_descendant_allows_unrelated():
    course = CourseFactory()
    p1 = ContentNodeFactory(course=course, kind="part", parent=None)
    p2 = ContentNodeFactory(course=course, kind="part", parent=None)
    ordering.assert_not_descendant(p1, p2)  # no raise


# ---------------------------------------------------------------------------
# New edge-case tests added after code review
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_move_in_list_down_at_bottom_returns_none():
    """Symmetric boundary: moving the last sibling "down" is a no-op."""
    course = CourseFactory()
    _a = _unit(course, title="a")
    last = _unit(course, title="b")
    siblings = list(
        ContentNode.objects.filter(course=course, parent=None).order_by("order", "pk")
    )
    assert ordering.move_in_list(siblings, last, "down") is None


@pytest.mark.django_db
def test_assert_not_descendant_self_move_raises():
    """A node cannot be moved under itself (direct self-move)."""
    course = CourseFactory()
    node = ContentNodeFactory(course=course, kind="part", parent=None)
    with pytest.raises(ValidationError):
        ordering.assert_not_descendant(node, node)


@pytest.mark.django_db
def test_place_node_position_zero_prepends():
    """position=0 inserts the node before all existing siblings."""
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    _a = _unit(course, parent=part, title="a")
    _b = _unit(course, parent=part, title="b")
    moving = _unit(course, parent=None, title="m")
    moving.parent = part
    ordering.place_node(moving, part, course, position=0)
    kids = list(
        ContentNode.objects.filter(course=course, parent=part)
        .order_by("order")
        .values_list("title", flat=True)
    )
    assert kids == ["m", "a", "b"]


@pytest.mark.django_db
def test_place_node_position_none_appends():
    """position=None (and position > N) appends the node after all siblings."""
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="P")
    _a = _unit(course, parent=part, title="a")
    _b = _unit(course, parent=part, title="b")
    moving = _unit(course, parent=None, title="m")
    moving.parent = part
    ordering.place_node(moving, part, course, position=None)
    kids = list(
        ContentNode.objects.filter(course=course, parent=part)
        .order_by("order")
        .values_list("title", flat=True)
    )
    assert kids == ["a", "b", "m"]


@pytest.mark.django_db
def test_compact_elements_closes_gap():
    """Deleting a middle element's join-row and compacting produces contiguous
    orders."""
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    ct = ContentType.objects.get_for_model(TextElement)

    te1 = TextElement.objects.create(body="first")
    te2 = TextElement.objects.create(body="second")
    te3 = TextElement.objects.create(body="third")

    e1 = Element.objects.create(unit=unit, content_type=ct, object_id=te1.pk)
    e2 = Element.objects.create(unit=unit, content_type=ct, object_id=te2.pk)
    e3 = Element.objects.create(unit=unit, content_type=ct, object_id=te3.pk)

    # Delete the middle join-row to create a gap (e.g. orders 0, _, 2)
    e2.delete()

    ordering.compact_elements(unit)

    orders = list(
        Element.objects.filter(unit=unit)
        .order_by("order")
        .values_list("order", flat=True)
    )
    assert orders == [0, 1]  # contiguous after compaction
    pks_in_order = list(
        Element.objects.filter(unit=unit).order_by("order").values_list("pk", flat=True)
    )
    assert pks_in_order == [e1.pk, e3.pk]
