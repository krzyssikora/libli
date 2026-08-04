import pytest

from courses.builder import ConflictError
from courses.builder import duplicate_element
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _tok(unit):
    return unit.updated.isoformat()


def _unit_with_populated_tabs():
    """Tabs with a child in tab 2, sitting between two loose Text elements."""
    course, unit = make_course_with_unit()
    first = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>first</p>")
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
    last = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>last</p>")
    )
    return course, unit, first, tabs_join, last, t2


def _top_level(unit):
    return list(unit.elements.filter(parent__isnull=True).order_by("order", "pk"))


def test_duplicate_lands_directly_below_the_source():
    course, unit, first, tabs_join, last, _t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, tabs_join.pk, _tok(unit))

    order = [e.pk for e in _top_level(unit)]
    assert order == [first.pk, tabs_join.pk, new_join.pk, last.pk]


def test_duplicate_of_the_first_element_lands_second():
    """Boundary: idx + 1 == 1, with nothing above the source."""
    course, unit, first, tabs_join, last, _t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, first.pk, _tok(unit))

    order = [e.pk for e in _top_level(unit)]
    assert order == [first.pk, new_join.pk, tabs_join.pk, last.pk]


def test_duplicate_of_the_last_element_lands_last():
    """Boundary: the copy lands at the tail of the group. Note place_element
    still renumbers -- with unit-wide orders the copy is born at max+1 and the
    top-level group is compacted to 0..3 -- so this is not a no-write case."""
    course, unit, first, tabs_join, last, _t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, last.pk, _tok(unit))

    order = [e.pk for e in _top_level(unit)]
    assert order == [first.pk, tabs_join.pk, last.pk, new_join.pk]


def test_duplicate_copies_the_whole_subtree_with_fresh_rows():
    course, unit, _first, tabs_join, _last, t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, tabs_join.pk, _tok(unit))

    assert new_join.pk != tabs_join.pk
    assert new_join.content_object.pk != tabs_join.content_object.pk
    child = new_join.children.get()
    assert child.pk != tabs_join.children.get().pk
    assert child.tab_id == t2
    assert child.content_object.body == "<p>tabbed</p>"


def test_duplicate_of_a_nested_child_stays_in_its_own_slot():
    """The graft returns a parentless root; without the scope-setting step the
    copy silently lands at TOP LEVEL instead of inside the tab."""
    course, unit, _first, tabs_join, _last, t2 = _unit_with_populated_tabs()
    source_child = tabs_join.children.get()

    _unit, new_join = duplicate_element(course, source_child.pk, _tok(unit))

    assert new_join.parent_id == tabs_join.pk
    assert new_join.tab_id == t2
    siblings = list(
        Element.objects.filter(unit=unit, parent=tabs_join, tab_id=t2)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    assert siblings == [source_child.pk, new_join.pk]


def test_duplicate_deep_copies_related_rows_and_reuses_the_media_row():
    """The image must live INSIDE the duplicated subtree. An asset created beside
    it is never serialised, so media_map is empty and both media assertions are
    true before duplicate_element is even called."""
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "pic.png")
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    question = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    Choice.objects.create(question=question, text="a", is_correct=True)
    Choice.objects.create(question=question, text="b")
    Element.objects.create(
        unit=unit, content_object=question, parent=tabs_join, tab_id=t1
    )
    src_image = ImageElement.objects.create(media=asset, alt="a", figcaption="")
    Element.objects.create(
        unit=unit, content_object=src_image, parent=tabs_join, tab_id=t2
    )
    choices_before = Choice.objects.count()

    _unit, new_join = duplicate_element(course, tabs_join.pk, _tok(unit))

    assert Choice.objects.count() == choices_before * 2  # related rows deep-copied
    assert MediaAsset.objects.filter(course=course).count() == 1  # ROW reused
    copied_image = next(
        child.content_object
        for child in new_join.children.all()
        if isinstance(child.content_object, ImageElement)
    )
    # Compare ImageElement to ImageElement. Comparing it to `asset.pk` would be
    # comparing pks from two unrelated sequences -- vacuous, and able to collide.
    assert copied_image.pk != src_image.pk  # a fresh ImageElement...
    assert copied_image.media_id == asset.pk  # ...pointing at the SAME asset row


def test_duplicate_bumps_the_unit_token():
    course, unit, _first, tabs_join, _last, _t2 = _unit_with_populated_tabs()
    before = unit.updated

    duplicate_element(course, tabs_join.pk, _tok(unit))

    unit.refresh_from_db()
    assert unit.updated > before


def test_duplicate_rejects_a_stale_token():
    course, unit, _first, tabs_join, _last, _t2 = _unit_with_populated_tabs()

    with pytest.raises(ConflictError):
        duplicate_element(course, tabs_join.pk, "2020-01-01T00:00:00+00:00")


def test_duplicate_refuses_a_damaged_subtree_rather_than_copying_it_partially():
    """build_export records a dangling GFK in `problems` and CONTINUES, so
    without an explicit check the copy silently loses the broken element and
    everything under it, and still returns 200."""
    course, unit, _first, tabs_join, _last, _t2 = _unit_with_populated_tabs()
    child = tabs_join.children.get()
    # Repoint object_id; do NOT delete the concrete row. Every concrete element
    # declares GenericRelation(Element), so deleting it CASCADES the join away --
    # leaving no join at all rather than a dangling one, an export with no
    # `problems`, and a test that fails for the wrong reason. This is the
    # `_make_broken_join` idiom from tests/test_transfer_export.py:342-351, whose
    # docstring documents the same trap.
    Element.objects.filter(pk=child.pk).update(object_id=9_999_999)

    with pytest.raises(TransferError):
        duplicate_element(course, tabs_join.pk, _tok(unit))


def test_element_export_scopes_link_nodes_to_the_unit_itself():
    """The reason graft_elements may skip _rewrite_links: link_nodes can only
    ever name nodes INSIDE the export, and an element-scoped export contains
    exactly one node -- the source unit. So the rewrite is provably an identity.
    If this ever stops holding, the skip stops being safe."""
    from courses.richtext import PERMALINK_PREFIX
    from courses.transfer.export import build_element_export

    course, unit = make_course_with_unit()
    other = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Target"
    )
    external = f"{PERMALINK_PREFIX}{other.pk}/"
    self_link = f"{PERMALINK_PREFIX}{unit.pk}/"
    join = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(
            body=f'<p><a href="{external}">out</a><a href="{self_link}">self</a></p>'
        ),
    )

    document, _media, _problems = build_element_export(unit, join)

    # The external target is filtered out; the self-link maps to the one node.
    assert document["link_nodes"] == {str(unit.pk): document["nodes"][0]["id"]}


def test_duplicate_keeps_an_internal_link_verbatim():
    """A plain regression check on the copy's body -- deliberately WITHOUT a
    mutant of its own, because no mutation CONFINED TO THE ELEMENT-SCOPED PATH
    can break it. (Mutating build_export's shared link_nodes filter does red it,
    along with much else -- see Step 8 mutation 3.)"""
    from courses.richtext import PERMALINK_PREFIX

    course, unit = make_course_with_unit()
    other = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Target"
    )
    href = f"{PERMALINK_PREFIX}{other.pk}/"
    join = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(
            body=f'<p><a href="{href}">see this</a></p>'
        ),
    )

    _unit, new_join = duplicate_element(course, join.pk, _tok(unit))

    assert href in new_join.content_object.body
