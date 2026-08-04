import pytest

from courses.models import ContentNode
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.export import build_element_export
from courses.transfer.importer import graft_elements
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def test_export_refuses_a_root_from_a_different_unit():
    """build_element_export(unit, root_join) never checked that root_join
    actually belongs to `unit`. Left unchecked, the walk would emit the OTHER
    unit's subtree while every element dict is labelled with THIS unit's node
    id -- and graft_elements would then materialise it into `unit`, across
    units (or courses). Construct exactly that mismatched pair."""
    course, unit = make_course_with_unit()
    other_unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Other"
    )
    join_in_other_unit = Element.objects.create(
        unit=other_unit,
        content_object=TextElement.objects.create(body="<p>elsewhere</p>"),
    )

    with pytest.raises(AssertionError):
        build_element_export(unit, join_in_other_unit)


def _unit_with_tabs():
    """A unit holding: a loose Text, and a Tabs whose second tab has one Text child."""
    course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>loose</p>")
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>tabbed</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    return course, unit, tabs_join, t2


def test_element_export_covers_the_subtree_and_nothing_else():
    _course, unit, tabs_join, t2 = _unit_with_tabs()

    document, _media, problems = build_element_export(unit, tabs_join)

    assert problems == []
    # Exactly the container plus its one child -- the loose Text is NOT exported.
    assert len(document["elements"]) == 2
    types = sorted(e["type"] for e in document["elements"])
    assert types == ["tabs", "text"]
    # The subtree root is parentless in the payload; the child carries its slot.
    root = [e for e in document["elements"] if not e.get("parent")]
    child = [e for e in document["elements"] if e.get("parent")]
    assert len(root) == 1 and root[0]["type"] == "tabs"
    assert len(child) == 1 and child[0]["tab"] == t2


def test_every_exported_element_points_at_the_single_node_id():
    """The coupling graft_elements actually depends on: it fabricates
    node_map = {document["nodes"][0]["id"]: unit}, and _create_elements then
    looks each element's "unit" key up in that map. Asserting only
    len(nodes) == 1 would duplicate build_element_export's own assert, which
    fires first and would mask this test."""
    _course, unit, tabs_join, _t2 = _unit_with_tabs()

    document, _media, _problems = build_element_export(unit, tabs_join)

    node_id = document["nodes"][0]["id"]
    assert {e["unit"] for e in document["elements"]} == {node_id}


def test_graft_creates_the_subtree_in_the_same_unit_and_returns_its_root():
    _course, unit, tabs_join, t2 = _unit_with_tabs()
    document, media_assets, _problems = build_element_export(unit, tabs_join)
    media_map = {mid: asset for (mid, asset, _ph) in media_assets}
    before = unit.elements.count()

    new_root = graft_elements(document, media_map, unit)

    assert unit.elements.count() == before + 2  # container + its child
    assert new_root.unit_id == unit.pk
    assert new_root.pk != tabs_join.pk
    assert isinstance(new_root.content_object, TabsElement)
    # The graft does NOT place it: the payload root has no parent, and
    # _create_elements' second pass skips parentless rows. The builder service
    # is what sets the scope -- this assertion pins that contract.
    assert new_root.parent_id is None
    assert new_root.tab_id == ""
    # The child came across and kept its slot.
    child = new_root.children.get()
    assert child.tab_id == t2
    assert child.content_object.body == "<p>tabbed</p>"


def test_graft_does_not_create_a_content_node():
    _course, unit, tabs_join, _t2 = _unit_with_tabs()
    document, media_assets, _problems = build_element_export(unit, tabs_join)
    media_map = {mid: asset for (mid, asset, _ph) in media_assets}
    nodes_before = ContentNode.objects.count()

    graft_elements(document, media_map, unit)

    assert ContentNode.objects.count() == nodes_before
