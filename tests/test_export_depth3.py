import pytest

from courses import builder
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TableElement
from courses.models import TextElement
from courses.tests.test_nesting_rule import _mk
from courses.transfer.export import build_export
from tests.factories import make_course_with_unit


def _tok(node):
    return node.updated.isoformat()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "container_type,slot_list_key",
    [("tabs", "tabs"), ("two_column", "columns")],
    ids=["tabs", "two_column"],
)
def test_duplicate_unit_keeps_depth_3_content(container_type, slot_list_key):
    """<container> > spoiler > table. Today the table VANISHES from the copy,
    silently: the pre-fix walk_unit_joins only descends one level into a
    container's children, so a table sitting inside a spoiler that is itself
    inside a tabs/two-column element is never reached by the export walk that
    duplicate_unit runs through.

    Parametrized over BOTH container types that recurse in walk_unit_joins
    (tabs and two_column) so each arm's `yield from emit(...)` has its own
    killing test -- reverting either one loses the table under its own
    parametrization. The spoiler arm is exercised by both (it sits at depth 2
    in either fixture).
    """
    course, unit = make_course_with_unit()
    top = _mk(unit, container_type)
    slot_id = top.content_object.data[slot_list_key][0]["id"]
    mid = _mk(unit, "spoiler", parent=top, tab=slot_id)
    _mk(unit, "table", parent=mid, tab=SpoilerElement.SLOT_ID)

    new_node = builder.duplicate_unit(course, unit.pk, token=_tok(unit))

    # Pin the whole copied CHAIN, not just presence: an implementation that
    # re-parented the table onto the container root instead of the spoiler
    # would still pass a bare "does a table exist somewhere" assertion.
    top_copy = new_node.elements.get(parent__isnull=True)
    spoiler_copies = list(top_copy.children.all())
    assert len(spoiler_copies) == 1
    spoiler_copy = spoiler_copies[0]
    assert isinstance(spoiler_copy.content_object, SpoilerElement)
    table_copies = list(spoiler_copy.children.all())
    assert len(table_copies) == 1
    table_copy = table_copies[0]
    assert isinstance(table_copy.content_object, TableElement)
    assert table_copy.content_object.data["cells"][0][0]["html"] == "x"


@pytest.mark.django_db
def test_round_trip_preserves_within_slot_sibling_order():
    """The fixture places two siblings in the TABS slot, so the named
    `reversed(children)` mutant actually bites.

    `children` exists only in the resolved_tabs()/resolved_columns() arms of
    walk_unit_joins; the spoiler arm is `for child in obj.resolved_children():`.
    A fixture of tabs > spoiler > [text_a, text_b] would put the two siblings in
    the SPOILER's slot, leaving the tabs slot holding exactly one child -- so
    reversed(children) would be a no-op there and the test would pass under its
    own mutant. Instead this fixture is tabs > [spoiler_a, spoiler_b], BOTH
    children of the SAME tab id -- one `children` list of length 2 in the
    resolved_tabs() arm. (A default TabsElement has two tabs, so splitting the
    two spoiler siblings one-per-tab was tried and rejected: each `children`
    list would then have length 1 and the mutant would be vacuous again.)

    ENTRY POINT: builder.duplicate_unit (-> materialize_duplicate), NOT
    import_subtree. Before Task 5 landed, validate_nesting's one-level check
    meant validate_document REJECTED a depth-3 archive, and
    materialize_duplicate's skipping validation entirely was the ONLY reason
    duplicate_unit worked here. Task 5 has since made validate_document accept a
    depth-3 archive too, but the entry point stays duplicate_unit (not
    import_subtree) regardless -- this test is about the duplicate path, not
    about which validator would tolerate the shape.
    """
    course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    spoiler_a = _mk(unit, "spoiler", parent=top, tab=t1)
    spoiler_b = _mk(unit, "spoiler", parent=top, tab=t1)
    text_a = TextElement.objects.create(body="A")
    Element.objects.create(
        unit=unit,
        content_object=text_a,
        parent=spoiler_a,
        tab_id=SpoilerElement.SLOT_ID,
    )
    text_b = TextElement.objects.create(body="B")
    Element.objects.create(
        unit=unit,
        content_object=text_b,
        parent=spoiler_b,
        tab_id=SpoilerElement.SLOT_ID,
    )
    text_a.refresh_from_db()
    text_b.refresh_from_db()

    new_node = builder.duplicate_unit(course, unit.pk, token=_tok(unit))

    top_copy = new_node.elements.get(parent__isnull=True)
    tab_children = list(top_copy.children.order_by("order", "pk"))
    assert len(tab_children) == 2
    bodies = [c.children.get().content_object.body for c in tab_children]
    assert bodies == [text_a.body, text_b.body]


@pytest.mark.django_db
def test_export_does_not_keyerror_on_forward_reference():
    """export.py's walk_index_by_join_pk[parent_join.pk] is an UNGUARDED dict
    lookup. Parents-before-children is required by the EXPORT side (the
    importer is explicitly order-robust): a depth-3 tree exports without
    raising, and each child's serialized `parent` resolves to its actual
    parent's e-id."""
    course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "spoiler", parent=top, tab=t1)
    _mk(unit, "table", parent=mid, tab=SpoilerElement.SLOT_ID)

    _manifest, document, _media_assets, _problems = build_export(
        course, node=unit, drop_missing_media=False
    )

    assert [e["type"] for e in document["elements"]] == ["tabs", "spoiler", "table"]
    tabs_el, spoiler_el, table_el = document["elements"]
    assert tabs_el["parent"] is None
    assert spoiler_el["parent"] == tabs_el["id"]
    assert table_el["parent"] == spoiler_el["id"]
