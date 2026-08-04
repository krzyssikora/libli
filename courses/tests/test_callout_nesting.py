"""Callout as a nesting PARENT: the three registries plus the depth clauses."""

import pytest

from courses import builder
from courses.models import CalloutElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _top_callout(unit):
    co = CalloutElement.objects.create(kind="example")
    return co, add_element(unit, co)


def test_callout_is_in_the_container_key_space():
    """Only the MEMBERSHIP line is new. The generic drift pair
    (CONTAINER_TRANSFER_KEYS == set(_CONTAINER_SLOT_KEY), and the _CONTAINER_REGISTRY
    length equality) is already asserted by
    test_nesting_rule.py::test_container_key_spaces_do_not_drift, which Step 4 runs --
    duplicating it here would just be a second place to update.
    """
    assert "callout" in builder.CONTAINER_TRANSFER_KEYS


def test_resolve_scope_accepts_a_table_into_a_callout():
    _course, unit = make_course_with_unit()
    _co, join = _top_callout(unit)
    parent, tab = builder.resolve_scope(
        unit, str(join.pk), CalloutElement.SLOT_ID, "table"
    )
    assert (parent, tab) == (join, CalloutElement.SLOT_ID)


def test_resolve_scope_rejects_an_unknown_slot():
    _course, unit = make_course_with_unit()
    _co, join = _top_callout(unit)
    with pytest.raises(builder.NestingError):
        builder.resolve_scope(unit, str(join.pk), "nope", "table")


def test_callout_in_callout_is_authorable():
    """Same-type nesting -- the shape a fixture monoculture hides (PR #209)."""
    _course, unit = make_course_with_unit()
    _co, join = _top_callout(unit)
    parent, tab = builder.resolve_scope(
        unit, str(join.pk), CalloutElement.SLOT_ID, "callout"
    )
    assert parent == join


def test_canonical_spoiler_tabs_callout_table_is_authorable():
    """spoiler(1) > tabs(2) > callout(3) > table(4) -- the deepest legal shape."""
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)

    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    co = CalloutElement.objects.create(kind="example")
    co_join = Element.objects.create(
        unit=unit, content_object=co, parent=tabs_join, tab_id="t000001"
    )
    # depth(co_join) == 3, so a LEAF child at depth 4 is legal...
    parent, _tab = builder.resolve_scope(
        unit, str(co_join.pk), CalloutElement.SLOT_ID, "table"
    )
    assert parent == co_join


def test_a_container_may_not_be_nested_at_depth_4():
    """Clause 4: callout is now a container, so it is refused where a leaf is fine."""
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    sp2 = SpoilerElement.objects.create(label="s2")
    sp2_join = Element.objects.create(
        unit=unit, content_object=sp2, parent=tabs_join, tab_id="t000001"
    )
    with pytest.raises(builder.NestingError):
        builder.resolve_scope(unit, str(sp2_join.pk), SpoilerElement.SLOT_ID, "callout")
