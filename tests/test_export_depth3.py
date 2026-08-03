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
def test_duplicate_unit_keeps_depth_3_content():
    """tabs > spoiler > table. Today the table VANISHES from the copy, silently:
    the pre-fix walk_unit_joins only descends one level into a container's
    children, so a table sitting inside a spoiler that is itself inside a tabs
    element is never reached by the export walk that duplicate_unit runs
    through."""
    course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "spoiler", parent=top, tab=t1)
    _mk(unit, "table", parent=mid, tab=SpoilerElement.SLOT_ID)

    new_node = builder.duplicate_unit(course, unit.pk, token=_tok(unit))

    tables = [
        e.content_object
        for e in new_node.elements.all()
        if isinstance(e.content_object, TableElement)
    ]
    assert len(tables) == 1
    assert tables[0].data["cells"][0][0]["html"] == "x"
    # the container chain must have survived too, not just the leaf
    assert new_node.elements.filter(parent__isnull=True).count() == 1
    spoilers = [
        e
        for e in new_node.elements.all()
        if isinstance(e.content_object, SpoilerElement)
    ]
    assert len(spoilers) == 1


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
    import_subtree. Task 1 leaves validate_nesting's one-level check in place
    until Task 5, so validate_document REJECTS a depth-3 archive at this
    commit; materialize_duplicate skips validation entirely, which is why
    duplicate_unit works here at all.
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
