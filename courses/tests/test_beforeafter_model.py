import pytest

from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit

# NOTE the path: `tests.factories`, NOT `courses.tests.factories` (which does not
# exist). Every file under courses/tests/ imports it this way.


def _ba(unit, label=""):
    obj = BeforeAfterElement.objects.create(button_label=label)
    return Element.objects.create(unit=unit, content_object=obj), obj


def _child(unit, parent, tab, body="x"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


@pytest.mark.django_db
def test_resolved_slots_returns_pairs_in_slot_ids_order():
    """Pairs, not a bare tuple: the editor row template needs the slot id to pass
    as tab= to the add-menu include and to {% paste_buttons %}.

    Mutant: return a 2-tuple of lists -> unpacking `for slot_id, children` fails.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    _child(unit, join, BeforeAfterElement.AFTER_SLOT_ID, "A")
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID, "B")

    slots = obj.resolved_slots()
    assert [sid for sid, _ in slots] == list(BeforeAfterElement.SLOT_IDS)
    assert [c.content_object.body for c in slots[0][1]] == ["B"]
    assert [c.content_object.body for c in slots[1][1]] == ["A"]


@pytest.mark.django_db
def test_unknown_tab_id_is_rehomed_into_before_not_dropped():
    """TwoColumnElement.resolved_columns ends `by_col.get(col["id"], [])`, which
    DROPS a child whose tab_id matches no slot. Copying it verbatim here would
    make authored content invisible.

    Mutant: `by_slot.get(sid, [])` with no fallback -> the stray child vanishes.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID, "keep")
    _child(unit, join, "bogus-slot", "stray")

    before = obj.resolved_slots()[0][1]
    assert [c.content_object.body for c in before] == ["keep", "stray"]


@pytest.mark.django_db
def test_both_slots_come_from_one_children_queryset():
    """One queryset filtered on parent_id with NO tab_id predicate, partitioned in
    Python. (Total query count is >1 -- join_row() is its own query and
    prefetch_related issues one per distinct child content type -- so the
    invariant is the SHAPE of the children query, not a count.)

    Mutant: call the queryset once per slot -> two parent_id queries.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID)
    _child(unit, join, BeforeAfterElement.AFTER_SLOT_ID)

    with CaptureQueriesContext(connection) as ctx:
        obj.resolved_slots()
    # Match on the WHERE clause, NOT the whole SQL string: every SELECT over
    # courses_element names "parent_id" and "tab_id" in its COLUMN LIST, so a
    # substring scan would count join_row()'s own query too and would find
    # "tab_id" in a query that does not filter on it.
    wheres = [q["sql"].split("WHERE", 1)[-1] for q in ctx.captured_queries if "WHERE" in q["sql"]]
    parent_filters = [w for w in wheres if '"parent_id" =' in w]
    assert len(parent_filters) == 1
    assert '"tab_id" =' not in parent_filters[0]


@pytest.mark.django_db
def test_transient_join_row_returns_empty_pairs():
    """The pairs are always present; only their child lists are empty."""
    obj = BeforeAfterElement.objects.create()
    assert obj.resolved_slots() == [
        (BeforeAfterElement.BEFORE_SLOT_ID, []),
        (BeforeAfterElement.AFTER_SLOT_ID, []),
    ]


def test_element_models_includes_before_after():
    """limit_choices_to on Element.content_type is fed by this list."""
    from courses.models import ELEMENT_MODELS

    assert "beforeafterelement" in ELEMENT_MODELS
