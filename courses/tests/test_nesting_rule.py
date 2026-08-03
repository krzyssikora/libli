import pytest

from courses import builder
from courses.builder import NestingError
from courses.models import Element
from tests.factories import make_course_with_unit

# NOTE the path: `tests.factories`, NOT `courses.tests.factories` (which does not
# exist). Every file under courses/tests/ imports it this way -- e.g.
# courses/tests/test_callout_authoring.py:10.


def _mk(unit, type_key, parent=None, tab=""):
    """Create an element join row directly through the ORM.

    Used for depth-3 parents: clause 4 forbids a container at depth 3, so such a
    fixture is UNREACHABLE through resolve_scope itself. This is deliberate
    defence-in-depth coverage, not dead code -- do not delete it.
    """
    from courses.models import MathElement
    from courses.models import SpoilerElement
    from courses.models import TableElement
    from courses.models import TabsElement
    from courses.models import TextElement
    from courses.models import TwoColumnElement

    obj = {
        "text": lambda: TextElement.objects.create(body="x"),
        "math": lambda: MathElement.objects.create(latex="x^2"),
        # NB: TableElement has NO default_data() -- only TabsElement (models.py:1355)
        # and TwoColumnElement (:1487) do. Build the dict literally; check
        # TableElement.save()'s sanitiser and the shape
        # tests/test_table_manage_plumbing.py already uses.
        "table": lambda: TableElement.objects.create(data={"cells": [[{"html": "x"}]]}),
        "tabs": lambda: TabsElement.objects.create(data=TabsElement.default_data()),
        "two_column": lambda: TwoColumnElement.objects.create(
            data=TwoColumnElement.default_data()
        ),
        "spoiler": lambda: SpoilerElement.objects.create(label="s"),
    }[type_key]()
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


@pytest.mark.django_db
def test_element_depth_counts_hops():
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab="t1")
    leaf = _mk(unit, "text", parent=mid, tab="t2")
    assert builder.element_depth(top) == 1
    assert builder.element_depth(mid) == 2
    assert builder.element_depth(leaf) == 3


@pytest.mark.django_db
def test_element_depth_terminates_on_a_cycle():
    """EXEMPT from the named-mutant requirement.

    Its only natural mutant -- unbounding element_depth's `while` -- HANGS, and
    pytest-timeout is not installed, so it can never be verified RED without
    wedging the run. The bound is exercised indirectly by the delete-cycle test in
    Task 3, whose collector mutant raises RecursionError rather than looping.
    """
    _course, unit = make_course_with_unit()
    a = _mk(unit, "tabs")
    b = _mk(unit, "tabs", parent=a, tab="t1")
    a.parent = b
    a.save(update_fields=["parent"])
    # Bounded walk: returns a too-deep value rather than looping forever.
    assert builder.element_depth(a) > builder.MAX_NEST_DEPTH - 1


@pytest.mark.django_db
@pytest.mark.parametrize("child_form_key", ["tabs", "twocolumn", "spoiler"])
def test_container_child_accepted_at_depth_1(child_form_key):
    """A container inside a top-level container lands at depth 2 -- legal."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(top.pk), tab_id, child_form_key)
    assert join == top and slot == tab_id


@pytest.mark.django_db
@pytest.mark.parametrize("child_form_key", ["tabs", "twocolumn", "spoiler"])
def test_container_child_rejected_at_depth_2(child_form_key):
    """Clause 4: a container child of a depth-2 parent would sit at depth 3."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=tab_id)
    mid_tab = mid.content_object.data["tabs"][0]["id"]
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(mid.pk), mid_tab, child_form_key)


@pytest.mark.django_db
def test_leaf_child_accepted_at_depth_2():
    """The same depth-2 parent accepts a LEAF -- this is what makes depth 3 real."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=tab_id)
    mid_tab = mid.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(mid.pk), mid_tab, "text")
    assert join == mid and slot == mid_tab


@pytest.mark.django_db
def test_leaf_child_rejected_at_depth_3():
    """Clause 3. The depth-3 parent is ORM-built: clause 4 makes it unreachable
    through resolve_scope, so this is defence-in-depth. Do not delete as dead."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=t1)
    t2 = mid.content_object.data["tabs"][0]["id"]
    deep = _mk(unit, "tabs", parent=mid, tab=t2)
    t3 = deep.content_object.data["tabs"][0]["id"]
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(deep.pk), t3, "text")


@pytest.mark.django_db
def test_spoiler_accepts_a_spoiler_child():
    """Purpose bullet 1: spoiler-in-spoiler."""
    _course, unit = make_course_with_unit()
    from courses.models import SpoilerElement

    outer = _mk(unit, "spoiler")
    join, slot = builder.resolve_scope(
        unit, str(outer.pk), SpoilerElement.SLOT_ID, "spoiler"
    )
    assert join == outer and slot == SpoilerElement.SLOT_ID


@pytest.mark.django_db
def test_nested_spoiler_may_have_children():
    """Purpose bullet 3: a spoiler inside a tab may hold children."""
    _course, unit = make_course_with_unit()
    from courses.models import SpoilerElement

    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    sp = _mk(unit, "spoiler", parent=top, tab=tab_id)
    join, slot = builder.resolve_scope(unit, str(sp.pk), SpoilerElement.SLOT_ID, "text")
    assert join == sp and slot == SpoilerElement.SLOT_ID


def test_container_key_spaces_do_not_drift():
    """PR2 adds Callout to THREE structures. Adding it to two silently leaves
    clause 4 permissive. No pre-existing test touches either structure."""
    from courses.transfer.payloads import _CONTAINER_SLOT_KEY

    assert builder.CONTAINER_TRANSFER_KEYS == set(_CONTAINER_SLOT_KEY)
    assert len(builder.CONTAINER_TRANSFER_KEYS) == len(builder._CONTAINER_REGISTRY)


def test_twocolumn_form_key_alias_exists():
    """Without the alias the Columns card is offered nested and every click 400s."""
    assert builder._NESTABLE_FORM_KEY_ALIASES["twocolumn"] == "two_column"
