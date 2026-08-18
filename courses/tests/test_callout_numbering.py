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


EXPECTED_QUERIES = 21  # observed; see test_query_count_on_a_real_shaped_unit
# Breakdown against the shape (existence check + roots + per container (join_row +
# children + one prefetch per distinct child content type)), for the fixture built
# there: 1 top callout, 1 tabs container (3 callout children), 1 spoiler container
# (1 callout child) -- and every CalloutElement, including leaf ones, is ITSELF a
# container in ACCESSORS, so it pays join_row + children even with no children of
# its own (no children -> no prefetch query, since prefetch on an empty result set
# is skipped):
#   1 existence check
# + 4 roots (1 list query + 1 prefetch per distinct root type: callout/tabs/spoiler)
# + 2 top callout            (join_row + children, no children -> no prefetch)
# + 3 tabs container         (join_row + children + 1 prefetch: callout)
# + 2 * 3 tab-child callouts (join_row + children each, no children -> no prefetch)
# + 3 spoiler container      (join_row + children + 1 prefetch: callout)
# + 2 spoiler-child callout  (join_row + children, no children -> no prefetch)
# = 1 + 4 + 2 + 3 + 6 + 3 + 2 = 21


def _warm_content_type_cache():
    """Populate ContentTypeManager's per-process cache for every type the fixtures
    use, so an assertNumQueries below measures the walk and not cache warmth."""
    from django.contrib.contenttypes.models import ContentType

    for model in (CalloutElement, TabsElement, SpoilerElement, TextElement, Element):
        ContentType.objects.get_for_model(model)


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


def test_a_unit_with_no_callouts_short_circuits(django_assert_num_queries):
    """The early-out. Most units have no callout at all, and without this a
    callout-free unit with containers pays the full descent on every student and
    editor render.

    Mutant: delete the early-out -> the container is descended and the count exceeds 1.
    """
    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000000", "label": "One"}]}
    )
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=0)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>x</p>"),
        parent=tabs_join,
        tab_id="t000000",
        order=0,
    )
    _warm_content_type_cache()
    with django_assert_num_queries(1):
        assert callout_numbers(unit) == {}


def test_a_nested_only_callout_is_not_short_circuited():
    """The existence check is unit-wide, NOT parent__isnull=True.
    Mutant: add `parent__isnull=True` to the early-out filter -> {} is returned."""
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, order=0)
    inner = _callout(
        unit, "task", numbered=True, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    assert callout_numbers(unit) == {inner.pk: 1}


def test_a_dangling_content_object_is_skipped_not_raised_on():
    """A row whose concrete is gone must not 500 the student page.
    Mutant: drop the `obj is None` guard -> AttributeError.

    DO NOT build this by deleting the concrete. `TextElement.elements` is a
    GenericRelation whose own comment reads "cascade: deleting this removes its
    join-row" (courses/models.py:404), so `.delete()` takes the join row with it and
    there is never a dangling row -- the assertions below would both pass trivially
    and the mutant would stay GREEN. Repoint `object_id` at a nonexistent row
    instead; idiom copied from tests/test_builder_duplicate_unit.py:174-177.
    """
    _course, unit = make_course_with_unit()
    orphan = add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    Element.objects.filter(pk=orphan.pk).update(object_id=orphan.object_id + 10_000_000)
    a = _callout(unit, "example", numbered=True, order=1)

    numbers = callout_numbers(unit)
    assert numbers == {a.pk: 1}
    assert orphan.pk not in numbers


def test_the_walk_terminates_on_a_join_row_cycle():
    """`join_row()` returns the LOWEST-PK join row for a concrete, not the row the
    walk arrived on. Two join rows on one concrete therefore make a cycle in the
    walk's graph even though the `parent` tree is perfectly acyclic:

        R1 (root)      -> C_a
        R2 (parent=R1) -> C_b
        R3 (parent=R2) -> C_a      # join_row(C_a) is R1 -> back to the start

    C_a must be a CALLOUT: its accessor groups by parent alone (so the cycle forms
    at all), and its presence defeats the early-out. A spoiler satisfies only the
    first; a tabs container satisfies neither, because an unmatched tab_id makes
    resolved_tabs drop the child and dissolve the cycle.

    Mutant: drop the `seen` set -> RecursionError.
    """
    _course, unit = make_course_with_unit()
    c_a = CalloutElement.objects.create(kind="example", numbered=True, body="")
    c_b = CalloutElement.objects.create(kind="task", numbered=True, body="")
    r1 = Element.objects.create(unit=unit, content_object=c_a, order=0)
    r2 = Element.objects.create(
        unit=unit, content_object=c_b, parent=r1, tab_id=SINGLE_SLOT_ID, order=0
    )
    Element.objects.create(
        unit=unit, content_object=c_a, parent=r2, tab_id=SINGLE_SLOT_ID, order=0
    )

    numbers = callout_numbers(unit)  # must terminate
    assert numbers[r1.pk] == 1
    assert numbers[r2.pk] == 2


def test_accessors_cover_every_container():
    """Mutant: delete one ACCESSORS entry -> a real container's children are silently
    never numbered."""
    from courses import builder
    from courses.numbering import ACCESSORS

    assert set(ACCESSORS) == builder.CONTAINER_MODELS


def test_an_unmapped_container_raises_with_a_named_type(monkeypatch):
    """CONTAINER_MODELS is read as a MODULE ATTRIBUTE so this patch reaches the walk;
    a module-level from-import would freeze it and this test would fail against a
    CORRECT implementation (the MAX_NEST_DEPTH precedent, views_manage.py:1858-1861).

    TextElement, not an invented class: no Element.content_object is ever an instance
    of an invented class, so the walk would never dispatch and the test would pass
    vacuously on both builds. The fixture also needs a CALLOUT, or the early-out
    returns {} before any descent -- vacuous a second way.
    """
    from courses import builder

    _course, unit = make_course_with_unit()
    _callout(unit, "example", numbered=True, order=0)
    add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    monkeypatch.setattr(
        builder, "CONTAINER_MODELS", builder.CONTAINER_MODELS | {TextElement}
    )

    with pytest.raises(RuntimeError, match="TextElement"):
        callout_numbers(unit)


def test_query_count_on_a_real_shaped_unit(django_assert_num_queries):
    """Shape (spec section 3):
        existence check + roots + per container (join_row + children + one prefetch
        per distinct child content type)

    The ContentType cache is warmed FIRST and deliberately: ContentTypeManager caches
    per process and survives --reuse-db, so an unwarmed count depends on test ordering
    and on which xdist worker ran what -- an intermittent failure with nothing in the
    test explaining it.

    EXPECTED_QUERIES is transcribed from an observed run, not derived from prose
    arithmetic. If it changes, reconcile the delta against the shape above before
    editing the number.
    """
    _course, unit = make_course_with_unit()
    _callout(unit, "example", numbered=True, order=0)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": f"t00000{i}", "label": str(i)} for i in range(3)]}
    )
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=1)
    for i in range(3):
        _callout(
            unit, "task", numbered=True, parent=tabs_join, tab_id=f"t00000{i}", order=0
        )
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, order=2)
    _callout(
        unit, "example", numbered=True, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )

    _warm_content_type_cache()
    with django_assert_num_queries(EXPECTED_QUERIES):
        callout_numbers(unit)
