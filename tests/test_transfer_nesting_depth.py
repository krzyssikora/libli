import pytest

from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import TransferError
from tests.test_tabs_transfer import _child
from tests.test_tabs_transfer import _els  # reuse; do NOT redefine

_SLOTS = [{"id": "taaaaaa"}, {"id": "tbbbbbb"}]  # must match _child's default tab


def _tabs(eid, parent=None, tab=_SLOTS[0]["id"]):
    """A tabs element that can itself be nested. `_tabs_el` cannot: it pins
    parent=None/tab="".

    `tab` defaults to a REAL slot id, not "". A nested element carries its own
    `tab`, and validate_nesting checks the slot BEFORE the depth clauses -- so
    `_tabs("b", parent="a")` with tab="" raises "references a slot its parent does
    not have" on element b, and element c/d never reach clause 3 or 4 at all. That
    made both depth tests assert the wrong message. Verified by executing the
    validator against these documents.
    """
    return {
        "id": eid,
        "type": "tabs",
        "parent": parent,
        "tab": tab if parent else "",
        "data": {"tabs": [dict(s, label=f"T{i}") for i, s in enumerate(_SLOTS)]},
    }


def test_depth_4_parents_first_reports_the_container_clause():
    """Parents-first ordering examines the depth-3 container before its child, so
    CLAUSE 4 fires."""
    doc = _els(
        _tabs("a"),
        _tabs("b", parent="a"),
        _tabs("c", parent="b"),
        _child("d", parent="c"),
    )
    with pytest.raises(TransferError) as exc:
        validate_nesting(doc)
    assert "container" in str(exc.value)


def test_depth_4_child_before_parent_reports_the_depth_clause():
    """Child-before-parent ordering reaches D first, whose parent C is already at
    depth 3, so CLAUSE 3 fires and clause 4 never runs. Both clauses are reachable;
    which one fires is payload-order dependent."""
    doc = _els(
        _tabs("a"),
        _tabs("b", parent="a"),
        _child("d", parent="c"),
        _tabs("c", parent="b"),
    )
    with pytest.raises(TransferError) as exc:
        validate_nesting(doc)
    assert "too deeply" in str(exc.value)


def test_parent_cycle_raises_rather_than_hanging():
    """Asserts the exception TYPE only, deliberately: a hop-bounded walk reports a
    cycle as a too-deep parent, emitting the same clause-3 message an ordinary
    depth-4 archive does. Distinguishing them would need the unbounded traversal the
    bound exists to avoid."""
    doc = _els(_tabs("a", parent="b"), _tabs("b", parent="a"))
    with pytest.raises(TransferError):
        validate_nesting(doc)


def test_missing_ancestor_mid_walk_names_the_element_under_validation():
    """Asserting the interpolated id is the ONLY thing that makes this lethal: a
    .get()-based walk still rejects the archive with the same message when the loop
    reaches B, so a test asserting merely 'TransferError mentioning unknown parent'
    stays green under that mutant."""
    doc = _els(_child("c", parent="b"), _tabs("b", parent="ghost"))
    with pytest.raises(TransferError) as exc:
        validate_nesting(doc)
    assert "'c'" in str(exc.value)  # the element under validation, not 'b'
