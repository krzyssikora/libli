import pytest

from courses import builder
from courses.builder import ConflictError
from courses.builder import PlacementRefused
from courses.builder import paste_element
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _tok(unit):
    return unit.updated.isoformat()


def _text(unit, parent=None, tab="", body="<p>x</p>"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _orders(unit, parent, tab):
    return list(
        Element.objects.filter(unit=unit, parent=parent, tab_id=tab)
        .order_by("order", "pk")
        .values_list("pk", "order")
    )


def test_a_move_reparents_the_root_and_persists_the_scope():
    """Re-read from the DB, not the in-memory instance: place_element writes only
    `order`, so an unsaved scope is a scope never written.

    Mutant: delete step 2's save(update_fields=["parent", "tab_id"]) -> RED here
    and ONLY here, which is the point of re-reading."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)

    _u, placed = paste_element(
        course, subject.pk, str(dest.pk), slots[1], "move", _tok(unit)
    )

    fresh = Element.objects.get(pk=subject.pk)
    assert placed.pk == subject.pk  # a move keeps the row
    assert fresh.parent_id == dest.pk
    assert fresh.tab_id == slots[1]


def test_a_move_carries_its_whole_subtree_without_touching_the_children():
    """Only the root's group membership changes; descendants keep their parent and
    unit FKs, so the subtree travels for free."""
    course, unit = make_course_with_unit()
    dest, dslots = _tabs(unit)
    root, rslots = _tabs(unit)
    child = _text(unit, parent=root, tab=rslots[0])
    before = (child.parent_id, child.tab_id, child.unit_id)

    paste_element(course, root.pk, str(dest.pk), dslots[0], "move", _tok(unit))

    child.refresh_from_db()
    assert (child.parent_id, child.tab_id, child.unit_id) == before


def test_a_move_compacts_the_source_group_and_appends_to_the_destination():
    """Mutant: read (parent, tab_id) AFTER mutating instead of before -> the source
    group is left with a hole and the source assertion reds. (Swapping steps 3 and 4
    is NOT a mutant here: the root's scope is already saved by step 2, so
    place_element and compact_elements operate on disjoint groups regardless of
    which runs first, and the destination result is identical either way.)"""
    course, unit = make_course_with_unit()
    a, b, c = (
        _text(unit, body="<p>a</p>"),
        _text(unit, body="<p>b</p>"),
        _text(unit, body="<p>c</p>"),
    )
    dest, slots = _tabs(unit)
    existing = _text(unit, parent=dest, tab=slots[0], body="<p>in</p>")

    paste_element(course, b.pk, str(dest.pk), slots[0], "move", _tok(unit))

    # Source group: the hole b left is compacted away, orders 0..n-1 and distinct.
    src = _orders(unit, None, "")
    assert [pk for pk, _o in src] == [a.pk, c.pk, dest.pk]
    assert [o for _pk, o in src] == [0, 1, 2]
    # Destination: appended last, distinct orders.
    dst = _orders(unit, dest, slots[0])
    assert [pk for pk, _o in dst] == [existing.pk, b.pk]
    assert len({o for _pk, o in dst}) == 2


def test_a_healthy_move_out_of_a_container_to_top_level():
    """The reverse direction, which nothing else covers: the damaged-row test that
    also lands at top level uses a dangling GFK and asserts only `parent_id is
    None`. Here the row is healthy and BOTH halves are checked -- the destination
    scope is fully cleared (`tab_id` back to ""), and the vacated slot is compacted
    rather than left with a hole.

    Mutant: compact the destination group instead of the captured source one ->
    the sibling-orders assertion goes RED.
    """
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    first = _text(unit, parent=dest, tab=slots[0], body="<p>1</p>")
    subject = _text(unit, parent=dest, tab=slots[0], body="<p>2</p>")
    last = _text(unit, parent=dest, tab=slots[0], body="<p>3</p>")

    _u, placed = paste_element(course, subject.pk, "", "", "move", _tok(unit))

    fresh = Element.objects.get(pk=placed.pk)
    assert fresh.parent_id is None
    assert fresh.tab_id == ""
    # The vacated slot is compacted to 0..n-1 with no hole where the row was.
    remaining = _orders(unit, dest, slots[0])
    assert [pk for pk, _o in remaining] == [first.pk, last.pk]
    assert [o for _pk, o in remaining] == [0, 1]


def test_a_move_between_two_slots_of_one_container():
    """Source and destination share a PARENT but differ in tab_id. That is a
    distinct compaction target -- ordering.element_siblings partitions on
    (unit, parent, tab_id) -- and no other test in this file exercises it: the
    mark-lifecycle test that looks similar leaves its subject at top level
    throughout.

    Mutant: compact the destination group instead of the captured source one ->
    the vacated-slot assertion goes RED.
    """
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    first = _text(unit, parent=dest, tab=slots[0], body="<p>1</p>")
    subject = _text(unit, parent=dest, tab=slots[0], body="<p>2</p>")
    sitting = _text(unit, parent=dest, tab=slots[1], body="<p>already there</p>")

    _u, placed = paste_element(
        course, subject.pk, str(dest.pk), slots[1], "move", _tok(unit)
    )

    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (dest.pk, slots[1])
    # The vacated slot is compacted; the destination appends after its sitting row.
    vacated = _orders(unit, dest, slots[0])
    assert [pk for pk, _o in vacated] == [first.pk]
    assert [o for _pk, o in vacated] == [0]
    arrived = _orders(unit, dest, slots[1])
    assert [pk for pk, _o in arrived] == [sitting.pk, subject.pk]


def test_a_move_whose_old_order_equals_its_new_index_is_still_persisted():
    """place_element saves only rows whose order CHANGED, so it may legitimately
    save the moved row not at all. Step 2 is what guarantees the move regardless --
    this is the case that proves it."""
    course, unit = make_course_with_unit()
    subject = _text(unit)  # order 0 at top level
    dest, slots = _tabs(unit)  # empty slot -> the moved row lands at index 0 again

    paste_element(course, subject.pk, str(dest.pk), slots[0], "move", _tok(unit))

    fresh = Element.objects.get(pk=subject.pk)
    assert (fresh.parent_id, fresh.tab_id, fresh.order) == (dest.pk, slots[0], 0)


def test_a_move_keeps_the_elements_pk_so_student_state_follows_it():
    """The converse of a copy, and the whole reason a move is worth having rather
    than delete-and-re-author: progress rows key on the element pk."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)
    pk_before = subject.pk

    _u, placed = paste_element(
        course, subject.pk, str(dest.pk), slots[0], "move", _tok(unit)
    )

    assert placed.pk == pk_before


def test_a_copy_creates_fresh_rows_in_the_destination_slot():
    course, unit = make_course_with_unit()
    dest, dslots = _tabs(unit)
    root, rslots = _tabs(unit)
    _text(unit, parent=root, tab=rslots[0], body="<p>inner</p>")

    _u, placed = paste_element(
        course, root.pk, str(dest.pk), dslots[0], "copy", _tok(unit)
    )

    assert placed.pk != root.pk
    assert placed.parent_id == dest.pk
    assert placed.tab_id == dslots[0]
    assert placed.content_object.pk != root.content_object.pk
    copied_child = placed.children.get()
    assert copied_child.content_object.body == "<p>inner</p>"
    # The source is untouched.
    root.refresh_from_db()
    assert root.parent_id is None


def test_a_copy_leaves_the_grafted_root_in_the_destination_not_at_top_level():
    """The graft returns a PARENTLESS root -- _create_elements' second pass skips
    exactly those rows -- and place_element saves only `order`. Mutant: skip the
    scope-setting step -> RED."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)

    _u, placed = paste_element(
        course, subject.pk, str(dest.pk), slots[0], "copy", _tok(unit)
    )

    # Re-read: _copy_into sets parent/tab_id on the instance BEFORE saving and
    # returns that same object, so asserting on `placed` would stay green with the
    # save deleted -- while the DB row kept parent=NULL and the copy silently
    # landed at top level. That is exactly the mutant this test must catch.
    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (dest.pk, slots[0])


def test_a_copy_preserves_the_subtree_shape_at_every_depth():
    """Copy fidelity for a THREE-level subtree, which the single-level test above
    cannot show: Tabs -> (tab 1) Spoiler -> Text. Every join and every concrete row
    must be fresh, and the parent/slot grouping must survive at each hop.

    Mutant: share concrete rows instead of copying them -> the fresh-pk assertions
    go RED while the content-equality ones stay green.
    """
    course, unit = make_course_with_unit()
    dest, dslots = _tabs(unit)

    root, rslots = _tabs(unit)
    sp = Element.objects.create(
        unit=unit,
        content_object=SpoilerElement.objects.create(body="<p>sp</p>"),
        parent=root,
        tab_id=rslots[0],
    )
    leaf = _text(unit, parent=sp, tab=SpoilerElement.SLOT_ID, body="<p>deep</p>")

    _u, placed = paste_element(
        course, root.pk, str(dest.pk), dslots[0], "copy", _tok(unit)
    )

    assert placed.pk != root.pk
    copied_sp = placed.children.get()
    assert copied_sp.pk != sp.pk
    assert copied_sp.tab_id == rslots[0]
    assert copied_sp.content_object.pk != sp.content_object.pk
    copied_leaf = copied_sp.children.get()
    assert copied_leaf.pk != leaf.pk
    assert copied_leaf.tab_id == SpoilerElement.SLOT_ID
    assert copied_leaf.content_object.pk != leaf.content_object.pk
    assert copied_leaf.content_object.body == "<p>deep</p>"


def test_a_copy_reuses_the_media_row_rather_than_re_creating_it():
    """Two MediaAsset rows sharing a file.name share a LIFETIME -- deleting either
    deletes the file out from under the other."""
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "pic.png")
    src_image = ImageElement.objects.create(media=asset, alt="a", figcaption="")
    subject = Element.objects.create(unit=unit, content_object=src_image)
    dest, slots = _tabs(unit)

    _u, placed = paste_element(
        course, subject.pk, str(dest.pk), slots[0], "copy", _tok(unit)
    )

    assert MediaAsset.objects.filter(course=course).count() == 1
    assert placed.content_object.pk != src_image.pk
    assert placed.content_object.media_id == asset.pk


def test_a_copy_into_the_elements_own_slot_lands_last_in_that_group():
    course, unit = make_course_with_unit()
    first = _text(unit, body="<p>1</p>")
    second = _text(unit, body="<p>2</p>")

    _u, placed = paste_element(course, first.pk, "", "", "copy", _tok(unit))

    order = [pk for pk, _o in _orders(unit, None, "")]
    assert order == [first.pk, second.pk, placed.pk]


def test_a_copy_of_a_damaged_subtree_refuses_rather_than_thinning_it():
    """build_export RECORDS a dangling GFK and continues, dropping the broken join
    and its whole subtree; discarding `problems` would yield a silent partial copy
    with a 200. Repoint object_id -- deleting the concrete cascades the join away."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    root, rslots = _tabs(unit)
    child = _text(unit, parent=root, tab=rslots[0])
    Element.objects.filter(pk=child.pk).update(object_id=9_999_999)

    with pytest.raises(TransferError):
        paste_element(course, root.pk, str(dest.pk), slots[0], "copy", _tok(unit))


def test_a_move_of_a_damaged_row_to_top_level_succeeds():
    """A move serialises nothing, so no export runs and no `problems` list exists.
    Stated in the spec because "paste" names both modes: a test written from the
    copy sentence alone would assert 422 here and be wrong."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit, parent=dest, tab=slots[0])
    Element.objects.filter(pk=subject.pk).update(object_id=9_999_999)

    _u, placed = paste_element(course, subject.pk, "", "", "move", _tok(unit))

    assert placed.parent_id is None


def test_an_inadmissible_placement_raises_placement_refused_with_its_reason():
    course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=root, tab=rslots[0])

    with pytest.raises(PlacementRefused) as exc:
        paste_element(course, root.pk, str(inner.pk), islots[0], "move", _tok(unit))

    assert exc.value.reason_key == "into_own_subtree"


def test_placement_refused_is_not_a_nesting_error():
    """A NestingError subclass would make element_add/element_save answer 400 to a
    condition they never raise, and the ParentGoneError handler would swallow it."""
    assert not issubclass(PlacementRefused, builder.NestingError)


def test_an_unknown_mode_is_rejected():
    course, unit = make_course_with_unit()
    subject = _text(unit)

    with pytest.raises(builder.NestingError):
        paste_element(course, subject.pk, "", "", "teleport", _tok(unit))


def test_a_half_supplied_scope_is_a_shape_error():
    course, unit = make_course_with_unit()
    subject = _text(unit)

    with pytest.raises(builder.NestingError):
        paste_element(course, subject.pk, "", "t1", "move", _tok(unit))


def test_a_stale_token_conflicts():
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)

    with pytest.raises(ConflictError):
        paste_element(
            course,
            subject.pk,
            str(dest.pk),
            slots[0],
            "move",
            "2020-01-01T00:00:00+00:00",
        )


@pytest.mark.parametrize("mode", ["move", "copy"])
def test_every_paste_bumps_the_unit_token_exactly_once(mode):
    """Mutant: drop the bump from the copy path -> the copy row goes RED, and
    without it a stale-token 409 would never fire after a copy."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)
    before = unit.updated

    paste_element(course, subject.pk, str(dest.pk), slots[0], mode, _tok(unit))

    unit.refresh_from_db()
    assert unit.updated > before


def test_a_move_into_a_third_column_lands_there():
    """Columns are the one container whose slot id key is `column.id` rather than
    `tab.id`, and the one whose cap is MAX_COLUMNS (4), not the default count (2).
    A third column is ordinary authored data -- element_forms lets an author pick
    2..4 -- so a cap of 2 would refuse this with `unknown_slot` while the renderer
    happily shows the column. Nothing else in the service tests reaches a column."""
    from courses.models import TwoColumnElement

    course, unit = make_course_with_unit()
    cols_obj = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]}
    )
    cols = Element.objects.create(unit=unit, content_object=cols_obj)
    cols_obj.refresh_from_db()
    third = cols_obj.data["columns"][2]["id"]
    subject = _text(unit)

    _u, placed = paste_element(
        course, subject.pk, str(cols.pk), third, "move", _tok(unit)
    )

    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (cols.pk, third)


def test_a_move_into_a_callout_uses_its_fixed_slot():
    """Callout became a container in #214. Its slot id is the SAME constant as a
    spoiler's, so this test and its spoiler twin must each build their own
    container rather than sharing a fixture.
    """
    from courses.models import CalloutElement

    course, unit = make_course_with_unit()
    callout = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    subject = _text(unit)

    _u, placed = paste_element(
        course, subject.pk, str(callout.pk), CalloutElement.SLOT_ID, "move", _tok(unit)
    )

    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (callout.pk, CalloutElement.SLOT_ID)


def test_a_move_into_a_spoiler_uses_its_fixed_slot():
    course, unit = make_course_with_unit()
    sp = Element.objects.create(
        unit=unit, content_object=SpoilerElement.objects.create(body="<p>s</p>")
    )
    subject = _text(unit)

    _u, placed = paste_element(
        course, subject.pk, str(sp.pk), SpoilerElement.SLOT_ID, "move", _tok(unit)
    )

    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (sp.pk, SpoilerElement.SLOT_ID)
