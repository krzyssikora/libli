import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.export import build_element_export
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


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
