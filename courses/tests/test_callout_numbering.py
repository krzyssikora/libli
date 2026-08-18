"""The callout numbering walk and its data layer."""

import pytest

from courses.models import KIND_DEFAULT_NUMBERED
from courses.models import SINGLE_SLOT_ID
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.numbering import callout_numbers
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def test_kind_default_numbered_covers_every_kind():
    """Mutant: delete one entry -> a sixth kind (or a renamed one) silently gets
    no per-kind decision at backfill and at legacy-archive import."""
    assert set(KIND_DEFAULT_NUMBERED) == {k.value for k in CalloutElement.Kind}


def test_kind_default_numbered_values():
    assert KIND_DEFAULT_NUMBERED["example"] is True
    assert KIND_DEFAULT_NUMBERED["task"] is True
    assert KIND_DEFAULT_NUMBERED["warning"] is True
    assert KIND_DEFAULT_NUMBERED["note"] is False
    assert KIND_DEFAULT_NUMBERED["tip"] is False


def test_model_default_is_a_flat_true_regardless_of_kind():
    """D2 is scoped to backfill and legacy import. An author-created Note is born
    numbered; the author unticks. Mutant: add a per-kind form/model initial -> this
    fails, which is the point (see spec section 1)."""
    assert CalloutElement(kind="note").numbered is True
    assert CalloutElement(kind="example").numbered is True


def test_kind_label_ignores_a_custom_heading():
    """kind_label is the KIND's label; display_heading is the author-facing one."""
    el = CalloutElement(kind="example", heading="Suma ciagu")
    assert el.kind_label == "Example"
    assert el.display_heading == "Suma ciagu"


def test_display_heading_falls_back_to_kind_label():
    el = CalloutElement(kind="warning", heading="")
    assert el.display_heading == "Important"
    assert el.display_heading == el.kind_label


def test_kind_label_survives_an_unknown_kind():
    """The string fallback key.
    Mutant: `KIND_DEFAULT_HEADING[self.kind]` -> KeyError."""
    el = CalloutElement(kind="bogus", heading="")
    assert el.kind_label == "Example"


def _callout(unit, kind="example", numbered=True, parent=None, tab_id="", order=0):
    """EVERY fixture sets `numbered` explicitly -- kind never implies it (see the
    Global Constraints). Returns the join row, because the map is keyed by join pk."""
    co = CalloutElement.objects.create(kind=kind, numbered=numbered, body="")
    return Element.objects.create(
        unit=unit, content_object=co, parent=parent, tab_id=tab_id, order=order
    )


def test_numbers_run_in_document_order_at_top_level():
    _course, unit = make_course_with_unit()
    a = _callout(unit, "example", numbered=True, order=0)
    b = _callout(unit, "task", numbered=True, order=1)
    assert callout_numbers(unit) == {a.pk: 1, b.pk: 2}


def test_an_unnumbered_callout_does_not_consume_a_number():
    """The acceptance criterion from the spec's Purpose:
    example, task, note, warning, task -> 1, 2, -, 3, 4.

    Mutant: increment the counter BEFORE the `numbered` check -> 1, 2, -, 4, 5.
    """
    _course, unit = make_course_with_unit()
    a = _callout(unit, "example", numbered=True, order=0)
    b = _callout(unit, "task", numbered=True, order=1)
    note = _callout(unit, "note", numbered=False, order=2)
    d = _callout(unit, "warning", numbered=True, order=3)
    e = _callout(unit, "task", numbered=True, order=4)

    numbers = callout_numbers(unit)
    assert numbers == {a.pk: 1, b.pk: 2, d.pk: 3, e.pk: 4}
    assert note.pk not in numbers


def test_tab_children_are_numbered_tab_by_tab_not_by_flat_order():
    """THE test the whole accessor-based design exists for.

    Real content interleaves tab children in `order` (spec section 3: unit 349 reads
    t000000, t000001, t000002, t000000, ...), so reading order is TAB INDEX then
    order-within-tab. Two callouts per tab is mandatory: with one per tab, tab-major
    and flat order coincide and the mutant survives.

    Creation order A, B, C, D is pinned, and A/B live in data["tabs"][0], because the
    flat walk's tiebreak inside an order-group is pk == creation order.

    Mutant: replace the accessor descent with a flat
    `join.children.order_by("order", "pk")` -> A, C, B, D.
    """
    _course, unit = make_course_with_unit()
    top = _callout(unit, "example", numbered=True, order=0)
    tabs = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000000", "label": "One"},
                {"id": "t000001", "label": "Two"},
            ]
        }
    )
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=1)
    a = _callout(
        unit, "task", numbered=True, parent=tabs_join, tab_id="t000000", order=0
    )
    b = _callout(
        unit, "task", numbered=True, parent=tabs_join, tab_id="t000000", order=1
    )
    c = _callout(
        unit, "task", numbered=True, parent=tabs_join, tab_id="t000001", order=0
    )
    d = _callout(
        unit, "task", numbered=True, parent=tabs_join, tab_id="t000001", order=1
    )

    numbers = callout_numbers(unit)
    assert numbers == {top.pk: 1, a.pk: 2, b.pk: 3, c.pk: 4, d.pk: 5}
    # Spelled out so a failure reads as an ORDER failure, not a count failure:
    assert [numbers[j.pk] for j in (a, b, c, d)] == [2, 3, 4, 5]


def test_a_container_takes_its_number_before_its_children():
    """Pre-order. A callout is itself a container, so this is reachable.
    Mutant: assign the container's number AFTER walking its children -> 2, 1."""
    _course, unit = make_course_with_unit()
    outer = _callout(unit, "example", numbered=True, order=0)
    inner = _callout(
        unit, "task", numbered=True, parent=outer, tab_id=SINGLE_SLOT_ID, order=0
    )
    assert callout_numbers(unit) == {outer.pk: 1, inner.pk: 2}


def test_spoiler_children_are_numbered_in_order():
    _course, unit = make_course_with_unit()
    top = _callout(unit, "example", numbered=True, order=0)
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, order=1)
    inner = _callout(
        unit,
        "task",
        numbered=True,
        parent=sp_join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    assert callout_numbers(unit) == {top.pk: 1, inner.pk: 2}


def test_non_callout_leaves_are_walked_past_without_consuming_numbers():
    _course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    a = _callout(unit, "example", numbered=True, order=1)
    assert callout_numbers(unit) == {a.pk: 1}
