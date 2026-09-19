"""The placement rule. Every case here names the mutant it catches; a row that
cannot go RED under any mutation is decoration, not a test."""

import re

import pytest
from django.template.loader import render_to_string

from courses import builder
from courses.models import CalloutElement
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import MarkDoneElement
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import StepperElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _text(unit, parent=None, tab="", body="x"):
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


def _spoiler(unit, parent=None, tab=""):
    obj = SpoilerElement.objects.create(body="<p>s</p>")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def test_top_level_destination_is_always_admissible():
    _course, unit = make_course_with_unit()
    tabs_join, _slots = _tabs(unit)

    ok, reason = builder.paste_allowed(unit, tabs_join, None, "", "copy")

    assert (ok, reason) == (True, None)


def test_a_non_nestable_root_is_refused_by_a_nested_slot():
    """Mutant: drop clause 2 -> this goes RED. A slidebreak lives legally at top
    level, which is why the root is the only node whose nestability is unproven."""
    _course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    sb = Element.objects.create(
        unit=unit, content_object=SlideBreakElement.objects.create()
    )

    ok, reason = builder.paste_allowed(unit, sb, dest, slots[0], "move")

    assert (ok, reason) == (False, "type_not_nestable")


def test_an_unknown_slot_is_refused():
    _course, unit = make_course_with_unit()
    dest, _slots = _tabs(unit)
    leaf = _text(unit)

    ok, reason = builder.paste_allowed(unit, leaf, dest, "no-such-slot", "move")

    assert (ok, reason) == (False, "unknown_slot")


def test_a_leaf_destination_is_not_a_container():
    _course, unit = make_course_with_unit()
    dest = _text(unit)
    leaf = _text(unit)

    ok, reason = builder.paste_allowed(unit, leaf, dest, "anything", "move")

    assert (ok, reason) == (False, "not_a_container")


def test_a_leaf_may_land_at_depth_four_but_a_container_may_not():
    """Mutant: replace cap(n) with a constant 4 -> the container row goes RED.
    A container at depth 4 would render slots that can never be filled."""
    _course, unit = make_course_with_unit()
    d1, s1 = _tabs(unit)
    d2, s2 = _tabs(unit, parent=d1, tab=s1[0])
    d3, s3 = _tabs(unit, parent=d2, tab=s2[0])  # depth 3; its slots are depth 4

    leaf = _text(unit)
    container, _cslots = _tabs(unit)

    assert builder.paste_allowed(unit, leaf, d3, s3[0], "move") == (True, None)
    assert builder.paste_allowed(unit, container, d3, s3[0], "move") == (
        False,
        "too_deep",
    )


def test_depth_within_the_subtree_counts_not_just_the_roots():
    """`rel` must be subtracted per node. Subtree: Spoiler(cap 3, rel 0) ->
    Spoiler(cap 3, rel 1) -> Text(cap 4, rel 2), so the headroom is
    min(3, 2, 2) = 2 and a destination at dest_depth 3 is one too far -- while an
    EMPTY tabs (headroom 3) fits there exactly.

    Mutant: ignore `rel` -> min(3, 3, 4) = 3, the destination is admitted, RED.
    This subtree is deliberately NOT the one the height mutant catches: a
    height-based bound computes 4 - 2 = 2 here, the same answer, so this case stays
    GREEN under that mutation. That contrast is what separates the two mutations.
    """
    _course, unit = make_course_with_unit()
    d1, s1 = _tabs(unit)
    d2, s2 = _tabs(unit, parent=d1, tab=s1[0])  # its slots are at dest_depth 3

    root = _spoiler(unit)
    mid = _spoiler(unit, parent=root, tab=SpoilerElement.SLOT_ID)
    _text(unit, parent=mid, tab=SpoilerElement.SLOT_ID)

    empty, _eslots = _tabs(unit)
    assert builder.paste_allowed(unit, empty, d2, s2[0], "move") == (True, None)
    assert builder.paste_allowed(unit, root, d2, s2[0], "move") == (False, "too_deep")


def test_a_container_inside_the_subtree_tightens_the_bound_more_than_height_does():
    """THE row that distinguishes min(cap(n) - rel(n)) from a plain subtree height.

    Subtree: Tabs(root, cap 3, rel 0) -> Spoiler(cap 3, rel 1). The correct bound is
    min(3-0, 3-1) = 2; a height-based bound computes MAX - max_rel = 4 - 1 = 3. At
    dest_depth 3 the two therefore disagree: the correct rule REFUSES (the spoiler
    would land at depth 4, which a container may never occupy) and the height-based
    one admits.

    Mutant: use subtree HEIGHT -> RED. The destination must be at dest_depth 3, not
    2: at 2 both bounds admit and the mutation is unobservable.
    """
    _course, unit = make_course_with_unit()
    d1, s1 = _tabs(unit)
    d2, s2 = _tabs(unit, parent=d1, tab=s1[0])  # its slots are at dest_depth 3

    root, rslots = _tabs(unit)
    _spoiler(unit, parent=root, tab=rslots[0])

    ok, reason = builder.paste_allowed(unit, root, d2, s2[0], "move")

    assert (ok, reason) == (False, "too_deep")


def test_a_destination_inside_the_marked_subtree_is_refused():
    _course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=root, tab=rslots[0])

    for mode in ("move", "copy"):
        ok, reason = builder.paste_allowed(unit, root, inner, islots[0], mode)
        assert (ok, reason) == (False, "into_own_subtree"), mode


def test_the_marked_element_itself_is_refused_as_its_own_destination():
    """Clause 4 covers {R} as well as descendants(R)."""
    _course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)

    ok, reason = builder.paste_allowed(unit, root, root, rslots[0], "copy")

    assert (ok, reason) == (False, "into_own_subtree")


def test_the_elements_own_slot_refuses_a_move_and_allows_a_copy():
    """Mutant: drop clause 5 -> the move case goes RED while the copy case stays
    green. A copy into your own slot is a meaningful sibling copy."""
    _course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    child = _text(unit, parent=dest, tab=slots[0])

    assert builder.paste_allowed(unit, child, dest, slots[0], "move") == (
        False,
        "own_slot",
    )
    assert builder.paste_allowed(unit, child, dest, slots[0], "copy") == (True, None)


def test_the_top_level_slot_is_the_own_slot_of_a_top_level_element():
    """The same clause on the synthetic (None, "") pair, where `P is None` and
    `R.parent_id is None` must compare equal with no instance on either side."""
    _course, unit = make_course_with_unit()
    top = _text(unit)

    assert builder.paste_allowed(unit, top, None, "", "move") == (False, "own_slot")
    assert builder.paste_allowed(unit, top, None, "", "copy") == (True, None)


def test_another_units_element_is_refused():
    _course, unit = make_course_with_unit()
    _course2, other_unit = make_course_with_unit()
    foreign = _text(other_unit)

    ok, reason = builder.paste_allowed(unit, foreign, None, "", "copy")

    assert (ok, reason) == (False, "wrong_unit")


def test_a_destination_parent_from_another_unit_is_refused():
    _course, unit = make_course_with_unit()
    _course2, other_unit = make_course_with_unit()
    dest, slots = _tabs(other_unit)
    leaf = _text(unit)

    ok, reason = builder.paste_allowed(unit, leaf, dest, slots[0], "move")

    assert (ok, reason) == (False, "wrong_unit")


def test_a_slot_the_renderer_would_truncate_away_is_refused():
    """Clause 1's position check, and the ONE case no template test can reach:
    the non-destructive normalizer KEEPS slots the renderer's destructive
    normalize_data drops, so no button renders (the UI is safe) but a hand-crafted
    POST would otherwise be admitted -- landing a populated subtree where neither
    resolved_tabs() nor the export walk will ever find it.

    Mutant: drop the `[:max_slots]` slice -> this goes RED and nothing else does.
    """
    _course, unit = make_course_with_unit()
    # Ids MUST match TabsElement.TAB_ID_RE (`t[0-9a-f]{6}`, fullmatch) or
    # TabsElement.save() -> normalize_labels_and_ids mints a fresh one for each
    # (TabsElement.TAB_ID_RE / normalize_labels_and_ids). With "t0"-style ids
    # every id here would be replaced at create time, the "kept" assertion
    # would fail as unknown_slot and the "dropped" one would pass vacuously.
    over = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": f"t{i:06x}", "label": f"L{i}"}
                for i in range(TabsElement.MAX_TABS + 2)
            ]
        }
    )
    dest = Element.objects.create(unit=unit, content_object=over)
    leaf = _text(unit)

    kept = f"t{TabsElement.MAX_TABS - 1:06x}"  # last slot surviving truncation
    dropped = f"t{TabsElement.MAX_TABS:06x}"  # first one normalize_data throws away

    assert builder.paste_allowed(unit, leaf, dest, kept, "move") == (True, None)
    assert builder.paste_allowed(unit, leaf, dest, dropped, "move") == (
        False,
        "unknown_slot",
    )


def test_a_fixed_slot_container_skips_the_position_check():
    """A spoiler's cap is None. This assertion alone does NOT pin that -- a cap of
    1 would also pass -- which is why Task 2's registry test asserts `is None`
    directly."""
    _course, unit = make_course_with_unit()
    dest = _spoiler(unit)
    leaf = _text(unit)

    assert builder.paste_allowed(unit, leaf, dest, SpoilerElement.SLOT_ID, "move") == (
        True,
        None,
    )


def test_a_dangling_gfk_root_is_refused_below_but_allowed_at_top_level():
    """type(None) is in neither the model->key map nor the registry, so clause 2
    rejects it for any nested destination. A top-level MOVE of the same row is
    admissible and correctly so -- a move serialises nothing. (A COPY of one fails
    later, at export, as a 422; that is the service's test, not this one.)

    Repoint object_id rather than deleting the concrete: every concrete declares
    GenericRelation(Element), so deleting it CASCADES the join away and leaves no
    dangling row to test.
    """
    _course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    # NESTED, not top level: a top-level row's own slot IS the top-level slot, so
    # clause 5 would answer own_slot and the second assertion below would be
    # testing the wrong rule. This is a genuine relocation.
    broken = _text(unit, parent=dest, tab=slots[0])
    Element.objects.filter(pk=broken.pk).update(object_id=9_999_999)
    broken.refresh_from_db()

    assert builder.paste_allowed(unit, broken, dest, slots[1], "move") == (
        False,
        "type_not_nestable",
    )
    assert builder.paste_allowed(unit, broken, None, "", "move") == (True, None)


def test_a_callout_is_a_fixed_slot_container():
    """PR #214 made Callout the FOURTH container, with one fixed slot like a
    spoiler. So it is both a legal destination (via its SLOT_ID) and a legal
    subject, and -- being a container -- its cap is 3, not 4.

    This test is what catches a registry edit that drops the Callout entry while
    rewriting the block for the slot cap.
    """
    _course, unit = make_course_with_unit()
    dest = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    leaf = _text(unit)

    # A legal destination through its fixed slot, and only through that slot.
    assert builder.paste_allowed(unit, leaf, dest, CalloutElement.SLOT_ID, "move") == (
        True,
        None,
    )
    assert builder.paste_allowed(unit, leaf, dest, "x", "move") == (
        False,
        "unknown_slot",
    )

    # And a legal subject: `callout` is in NESTABLE_TYPE_KEYS.
    tabs_join, slots = _tabs(unit)
    callout_join = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    assert builder.paste_allowed(unit, callout_join, tabs_join, slots[0], "move") == (
        True,
        None,
    )
    # Its cap is a container's: at dest_depth 3 an empty callout still fits (3 <= 3),
    # but one holding a container does not.
    assert builder._slot_cap(callout_join) == builder.MAX_NEST_DEPTH - 1


def test_subtree_facts_reports_the_pks_and_the_headroom():
    _course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)
    child = _spoiler(unit, parent=root, tab=rslots[0])
    grandchild = _text(unit, parent=child, tab=SpoilerElement.SLOT_ID)

    facts = builder.subtree_facts(root)

    assert facts.subtree_pks == frozenset({root.pk, child.pk, grandchild.pk})
    # Tabs cap 3 at rel 0; Spoiler cap 3 at rel 1; Text cap 4 at rel 2.
    assert facts.min_headroom == min(3 - 0, 3 - 1, 4 - 2)


def test_subtree_facts_terminates_on_a_parent_cycle():
    """A corrupt cycle must terminate rather than spin -- the same guard
    _collect_subtree_pks carries, for the same reason."""
    _course, unit = make_course_with_unit()
    a, aslots = _tabs(unit)
    b, _bslots = _tabs(unit, parent=a, tab=aslots[0])
    Element.objects.filter(pk=a.pk).update(parent=b)
    a.refresh_from_db()

    facts = builder.subtree_facts(a)

    assert facts.subtree_pks == frozenset({a.pk, b.pk})


def _callout(unit, parent=None, tab=""):
    obj = CalloutElement.objects.create(kind="example")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _choice(unit, parent=None, tab=""):
    obj = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _markdone(unit, parent=None, tab=""):
    obj = MarkDoneElement.objects.create(prompt="Tick")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _stepper(unit, parent=None, tab=""):
    obj = StepperElement.objects.create(prompt="Steps")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def test_nested_question_is_false_for_a_lone_question_root():
    """Mutant: make nested_question include the root (drop `rel >= 1`) -> RED."""
    _course, unit = make_course_with_unit()
    q = _choice(unit)

    assert builder.subtree_facts(q).nested_question is False


def test_nested_question_is_true_for_a_container_holding_a_question():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    _choice(unit, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.subtree_facts(box).nested_question is True


def test_nested_question_is_true_for_a_question_two_levels_down():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    tabs, slots = _tabs(unit, parent=box, tab=CalloutElement.SLOT_ID)
    _choice(unit, parent=tabs, tab=slots[0])

    assert builder.subtree_facts(box).nested_question is True


def test_has_interactive_sees_an_interactive_root():
    _course, unit = make_course_with_unit()

    assert builder.subtree_facts(_stepper(unit)).has_interactive is True


def test_has_interactive_sees_an_interactive_two_levels_down():
    """callout > tabs > checklist, inside the depth cap.

    Mutant: stop the walk at depth 1 (e.g. `if rel >= 1: return` after the
    headroom line) -> RED."""
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    tabs, slots = _tabs(unit, parent=box, tab=CalloutElement.SLOT_ID)
    _markdone(unit, parent=tabs, tab=slots[0])

    assert builder.subtree_facts(box).has_interactive is True


def test_has_interactive_is_false_for_a_subtree_with_none():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    _text(unit, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.subtree_facts(box).has_interactive is False


def test_has_interactive_never_counts_a_dangling_gfk():
    """model_to_key(type(None)) is None, never an interactive key.

    Mutant: treat a None key as interactive
    (`key is None or key in QUIZ_EXCLUDED_TYPE_KEYS`) -> RED.

    Repoint object_id rather than deleting the concrete: every concrete declares
    GenericRelation(Element), so deleting it CASCADES the join away."""
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    broken = _text(unit, parent=box, tab=CalloutElement.SLOT_ID)
    Element.objects.filter(pk=broken.pk).update(object_id=9_999_999)

    facts = builder.subtree_facts(box)

    assert facts.has_interactive is False
    assert facts.nested_question is False


def test_the_map_walk_and_the_orm_walk_agree():
    """The render passes unit_children_map(); the endpoint omits it. Both must
    produce identical facts, or the advisory buttons and the enforcing check
    disagree."""
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    tabs, slots = _tabs(unit, parent=box, tab=CalloutElement.SLOT_ID)
    _markdone(unit, parent=tabs, tab=slots[0])
    _choice(unit, parent=tabs, tab=slots[1])

    mapped = builder.subtree_facts(box, children_map=builder.unit_children_map(unit))

    assert mapped == builder.subtree_facts(box)


def test_unit_children_map_groups_every_join_by_parent():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    child = _text(unit, parent=box, tab=CalloutElement.SLOT_ID)
    top = _text(unit)

    cmap = builder.unit_children_map(unit)

    assert cmap[None] == [box, top]
    assert cmap[box.pk] == [child]


_CARD = re.compile(r'data-add-type="([^"]+)"')


def _top_level_cards(unit_is_quiz):
    html = render_to_string(
        "courses/manage/editor/_add_menu.html",
        {
            "depth": 0,
            "nested": False,
            "max_nest_depth": builder.MAX_NEST_DEPTH,
            "unit_is_quiz": unit_is_quiz,
            "parent": "",
            "tab": "",
        },
    )
    return set(_CARD.findall(html))


def test_quiz_excluded_type_keys_match_the_add_menus_interactive_group():
    """DERIVED, never a hard-coded count: the add menu hides exactly these types
    in a quiz, so the paste rule must refuse exactly these types into one.

    Depth 0 and nested=False on purpose: a deeper menu drops the depth-gated
    spoiler card from BOTH menus and would fake a drift.

    Mutant: remove one key from QUIZ_EXCLUDED_TYPE_KEYS -> RED. Mutant: spell the
    set with card names ("revealgate", "markdone", ...) -> RED."""
    lesson = _top_level_cards(unit_is_quiz=False)
    quiz = _top_level_cards(unit_is_quiz=True)

    # A future quiz-only card must be noticed deliberately, not absorbed.
    assert quiz - lesson == set()
    hidden = {
        builder._NESTABLE_FORM_KEY_ALIASES.get(name, name) for name in lesson - quiz
    }
    assert hidden  # not vacuous: the menus really differ
    assert hidden == builder.QUIZ_EXCLUDED_TYPE_KEYS
