"""The slot enumerator. Template tests cannot cover this: they assert a MISSING
button, which stays green if the enumerator returns nothing at all."""

import pytest

from courses import builder
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def test_the_synthetic_top_level_pair_is_always_first():
    _course, unit = make_course_with_unit()

    pairs, _map = builder.enumerate_slots(unit)

    assert pairs[0] == (None, "", 1)


def test_every_slot_of_a_two_level_container_tree_is_emitted_with_its_depth():
    _course, unit = make_course_with_unit()
    outer, oslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=outer, tab=oslots[1])

    pairs, _map = builder.enumerate_slots(unit)

    assert (None, "", 1) in pairs
    for sid in oslots:
        assert (outer, sid, 2) in pairs
    for sid in islots:
        assert (inner, sid, 3) in pairs
    # Nothing else: 1 synthetic + 2 outer slots + 2 inner slots.
    assert len(pairs) == 5


def test_a_spoiler_nested_in_a_tab_contributes_its_single_slot():
    """Mutant: write `obj.data` instead of `getattr(obj, "data", None)` ->
    AttributeError, RED. SpoilerElement has no `data` field at all, and the
    argument is evaluated before the normalizer runs."""
    _course, unit = make_course_with_unit()
    tabs_join, slots = _tabs(unit)
    sp = Element.objects.create(
        unit=unit,
        content_object=SpoilerElement.objects.create(body="<p>s</p>"),
        parent=tabs_join,
        tab_id=slots[0],
    )

    pairs, _map = builder.enumerate_slots(unit)

    assert (sp, SpoilerElement.SLOT_ID, 3) in pairs


def test_a_callout_contributes_its_fixed_slot():
    """Callout became a container in PR #214. The enumerator walks the registry, so
    it needs no callout-specific code -- but nothing else in this file would notice
    if the registry entry were dropped while rewriting the block for the slot cap."""
    _course, unit = make_course_with_unit()
    from courses.models import CalloutElement

    join = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )

    pairs, _map = builder.enumerate_slots(unit)

    assert (join, CalloutElement.SLOT_ID, 2) in pairs


def test_a_two_column_element_contributes_both_columns():
    _course, unit = make_course_with_unit()
    obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    cols = [c["id"] for c in obj.data["columns"]]

    pairs, _map = builder.enumerate_slots(unit)

    for cid in cols:
        assert (join, cid, 2) in pairs


def test_a_join_with_a_dangling_gfk_is_skipped_without_raising():
    """Repoint object_id rather than deleting the concrete -- GenericRelation
    cascades, so a delete would remove the join and prove nothing."""
    _course, unit = make_course_with_unit()
    tabs_join, _slots = _tabs(unit)
    Element.objects.filter(pk=tabs_join.pk).update(object_id=9_999_999)

    pairs, _map = builder.enumerate_slots(unit)

    assert pairs == [(None, "", 1)]


def test_a_slot_the_renderer_would_truncate_away_is_not_emitted():
    """The same position check clause 1 applies, here so the UI never offers a
    button the rule would then refuse. Mutant: drop the [:max_slots] slice -> RED."""
    _course, unit = make_course_with_unit()
    # Ids MUST match TabsElement.TAB_ID_RE (`t[0-9a-f]{6}`, fullmatch) or
    # TabsElement.save() -> normalize_labels_and_ids mints a fresh one for each
    # (see TabsElement.TAB_ID_RE). With "t0"-style ids every id here would be
    # replaced at create time, the "kept" assertion would fail as unknown_slot and
    # the "dropped" one would pass vacuously.
    over = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": f"t{i:06x}", "label": f"L{i}"}
                for i in range(TabsElement.MAX_TABS + 2)
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=over)

    pairs, _map = builder.enumerate_slots(unit)

    emitted = {t for p, t, _d in pairs if p is not None}
    assert f"t{TabsElement.MAX_TABS - 1:06x}" in emitted
    assert f"t{TabsElement.MAX_TABS:06x}" not in emitted
    assert join.pk  # the fixture row, referenced so the name is not unused


def test_the_children_map_is_returned_for_reuse():
    """subtree_facts takes this map so the marked render walks the tree once, not
    once per node. Mutant: return only `pairs` -> RED at the unpack."""
    _course, unit = make_course_with_unit()
    outer, oslots = _tabs(unit)
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=outer,
        tab_id=oslots[0],
    )

    _pairs, children_map = builder.enumerate_slots(unit)

    assert [j.pk for j in children_map[outer.pk]] == [child.pk]
    assert [j.pk for j in children_map[None]] == [outer.pk]


def test_rows_in_a_parent_cycle_are_simply_unreachable():
    """Named for what it actually pins. `Element.parent` is single-valued, so a
    node inside a cycle always has a non-null parent and is therefore never a root
    -- the walk starts from `children_map[None]` and never enters the cycle at all.
    (`_element_row.html:176-181` makes the same argument for the template
    recursion.)

    So `seen` CANNOT be falsified from this entry point: deleting the guard leaves
    this test green. It is defence-in-depth for a future caller that walks from an
    arbitrary node, and `subtree_facts` -- which does exactly that -- is where the
    guard IS exercised (see test_subtree_facts_terminates_on_a_parent_cycle).
    """
    _course, unit = make_course_with_unit()
    a, aslots = _tabs(unit)
    b, _bslots = _tabs(unit, parent=a, tab=aslots[0])
    Element.objects.filter(pk=a.pk).update(parent=b)

    pairs, _map = builder.enumerate_slots(unit)

    assert pairs == [(None, "", 1)]


def test_the_walk_costs_a_bounded_number_of_queries(django_assert_num_queries):
    """The cost is paid on EVERY response while a mark is pending, and every editor
    operation returns a full re-render. One query for the elements plus one per
    distinct content type (the GFK prefetch groups by type) -- and crucially NOT
    one per join.

    Mutant: drop the prefetch and read `join.content_object` per node -> the count
    scales with the number of elements and this goes RED.
    """
    _course, unit = make_course_with_unit()
    outer, oslots = _tabs(unit)
    for i in range(6):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>{i}</p>"),
            parent=outer,
            tab_id=oslots[0],
        )

    # 2 distinct content types (TabsElement, TextElement) -> 1 + 2 = 3.
    with django_assert_num_queries(3):
        builder.enumerate_slots(unit)
