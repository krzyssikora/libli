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

    Used for depth-4 parents: clause 4 forbids a container at depth 4, so such a
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
    inner = _mk(unit, "tabs", parent=mid, tab="t2")
    leaf = _mk(unit, "text", parent=inner, tab="t3")
    assert builder.element_depth(top) == 1
    assert builder.element_depth(mid) == 2
    assert builder.element_depth(inner) == 3
    assert builder.element_depth(leaf) == 4


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
def test_container_child_accepted_at_depth_2(child_form_key):
    """A container inside a depth-2 container lands at depth 3 -- the THIRD level of
    containers the cap lift exists for.

    This is also the only test that kills the clause-4 off-by-one tightening
    (`parent_depth >= MAX_NEST_DEPTH - 2`): under that mutant a depth-2 parent
    rejects every container, while `test_container_child_accepted_at_depth_1` (1 < 2)
    stays green."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=tab_id)
    mid_tab = mid.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(mid.pk), mid_tab, child_form_key)
    assert join == mid and slot == mid_tab


@pytest.mark.django_db
@pytest.mark.parametrize("child_form_key", ["tabs", "twocolumn", "spoiler"])
def test_container_child_rejected_at_depth_3(child_form_key):
    """Clause 4: a container child of a depth-3 parent would sit at depth 4 -- a
    FOURTH level of containers, which the cap does not allow."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=t1)
    t2 = mid.content_object.data["tabs"][0]["id"]
    deep = _mk(unit, "tabs", parent=mid, tab=t2)
    t3 = deep.content_object.data["tabs"][0]["id"]
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(deep.pk), t3, child_form_key)


@pytest.mark.django_db
def test_leaf_child_accepted_at_depth_2():
    """The same depth-2 parent accepts a LEAF -- it lands at depth 3."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=tab_id)
    mid_tab = mid.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(mid.pk), mid_tab, "text")
    assert join == mid and slot == mid_tab


@pytest.mark.django_db
def test_leaf_child_accepted_at_depth_3():
    """A LEAF inside the THIRD container level lands at depth 4 -- this is what makes
    three levels of containers with content inside them real.

    Also the only test that kills the clause-3 off-by-one tightening
    (`parent_depth >= MAX_NEST_DEPTH - 1`): under that mutant a depth-3 parent takes
    no children at all, while `test_leaf_child_accepted_at_depth_2` (2 < 3) stays
    green."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=t1)
    t2 = mid.content_object.data["tabs"][0]["id"]
    deep = _mk(unit, "tabs", parent=mid, tab=t2)
    t3 = deep.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(deep.pk), t3, "text")
    assert join == deep and slot == t3


@pytest.mark.django_db
def test_leaf_child_rejected_at_depth_4():
    """Clause 3. The depth-4 parent is ORM-built: clause 4 makes it unreachable
    through resolve_scope, so this is defence-in-depth. Do not delete as dead."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=t1)
    t2 = mid.content_object.data["tabs"][0]["id"]
    deep = _mk(unit, "tabs", parent=mid, tab=t2)
    t3 = deep.content_object.data["tabs"][0]["id"]
    deeper = _mk(unit, "tabs", parent=deep, tab=t3)
    t4 = deeper.content_object.data["tabs"][0]["id"]
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(deeper.pk), t4, "text")


@pytest.mark.django_db
def test_canonical_spoiler_tabs_spoiler_text_is_authorable():
    """THE acceptance criterion for the cap lift, in the user's own words:
    "a spoiler with child tabs with child spoiler, but this is it".

        spoiler (1) > tabs (2) > spoiler (3) > text (4)

    Every hop goes through resolve_scope, exactly as manage_element_add does -- no ORM
    shortcut -- so this fails if ANY of the four levels is refused. The closing
    assertions pin "but this is it": a FOURTH container level is rejected, while the
    depth-4 leaf really is at depth 4.
    """
    from courses.models import SpoilerElement

    _course, unit = make_course_with_unit()

    sp1 = _mk(unit, "spoiler")
    assert builder.element_depth(sp1) == 1

    join, slot = builder.resolve_scope(
        unit, str(sp1.pk), SpoilerElement.SLOT_ID, "tabs"
    )
    tabs = _mk(unit, "tabs", parent=join, tab=slot)
    assert builder.element_depth(tabs) == 2

    tab_id = tabs.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(tabs.pk), tab_id, "spoiler")
    sp2 = _mk(unit, "spoiler", parent=join, tab=slot)
    assert builder.element_depth(sp2) == 3

    join, slot = builder.resolve_scope(
        unit, str(sp2.pk), SpoilerElement.SLOT_ID, "text"
    )
    text = _mk(unit, "text", parent=join, tab=slot)
    assert builder.element_depth(text) == 4

    # "...but this is it": no fourth container level, whichever container is asked for.
    for container in ("spoiler", "tabs", "twocolumn"):
        with pytest.raises(NestingError):
            builder.resolve_scope(unit, str(sp2.pk), SpoilerElement.SLOT_ID, container)


@pytest.mark.django_db
def test_resolve_scope_walks_the_parent_chain_without_extra_queries():
    """`select_related` must cover MAX_NEST_DEPTH - 1 = 3 parent hops.

    MEASURED, not assumed: a LEGAL parent tops out at depth 3, and walking from there
    touches only two non-null parents, so `parent__parent` still covers every accepted
    resolve. The third hop is for the REJECTION path -- an over-deep parent (legacy
    rows, an import, a direct ORM write, a corrupt cycle) sits at depth 4, and that is
    the walk a two-hop prefetch pays an uncached fetch for. Using a depth-3 parent
    here instead would make this test pass under its own mutant.

    Comparing against a depth-1 parent in the SAME test keeps the ContentType cache
    warm, so the delta is the parent walk and nothing else. Both calls get past the
    slot check identically; only the depth clauses differ.

    Mutant: `select_related("parent__parent")` -> the depth-4 count exceeds the
    depth-1 count.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=t1)
    t2 = mid.content_object.data["tabs"][0]["id"]
    deep = _mk(unit, "tabs", parent=mid, tab=t2)
    t3 = deep.content_object.data["tabs"][0]["id"]
    deeper = _mk(unit, "tabs", parent=deep, tab=t3)
    t4 = deeper.content_object.data["tabs"][0]["id"]

    builder.resolve_scope(unit, str(top.pk), t1, "text")  # warm the ContentType cache
    with CaptureQueriesContext(connection) as shallow:
        builder.resolve_scope(unit, str(top.pk), t1, "text")
    with CaptureQueriesContext(connection) as deepest:
        with pytest.raises(NestingError):  # clause 3 -- this is the rejection path
            builder.resolve_scope(unit, str(deeper.pk), t4, "text")
    assert len(deepest) == len(shallow)


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


def test_container_registry_carries_a_slot_cap():
    """Clause 1's truncation check needs each container's MAX. A registry entry
    without one forces an ad-hoc getattr(type(obj), "MAX_TABS", ...) inside
    paste_allowed -- a second copy of container knowledge outside the registry."""
    from courses.models import CalloutElement
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TwoColumnElement

    reg = builder._CONTAINER_REGISTRY
    assert len(reg[TabsElement]) == 4
    assert reg[TabsElement][3] == TabsElement.MAX_TABS
    # MAX_COLUMNS, not the DEFAULT column count: normalize_data truncates at 4 and
    # the author may pick 2, 3 or 4. A cap of 2 would silently make columns 3 and 4
    # unpasteable while the renderer still shows them.
    assert reg[TwoColumnElement][3] == TwoColumnElement.MAX_COLUMNS
    # A fixed-slot container is never truncated, so its cap is None -- not 1.
    # `None` is what makes paste_allowed SKIP the position check rather than
    # apply it with a bound that happens to work.
    assert reg[SpoilerElement][3] is None
    # Callout became a container in PR #214 and is the second fixed-slot one.
    assert reg[CalloutElement][3] is None
    assert len(reg) == 4


def test_container_keys_agree_by_key_not_by_count():
    """The old assertion was `len(CONTAINER_TRANSFER_KEYS) == len(_CONTAINER_REGISTRY)`,
    which passes green when a fourth model is registered under a fourth key that is
    absent from CONTAINER_TRANSFER_KEYS -- exactly the seam cap(n) and clause 2 now
    both sit on."""
    from courses.transfer.export import model_to_key

    assert {model_to_key(m) for m in builder._CONTAINER_REGISTRY} == set(
        builder.CONTAINER_TRANSFER_KEYS
    )
