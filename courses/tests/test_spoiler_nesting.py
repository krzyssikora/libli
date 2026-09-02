import re

import pytest
from django.urls import reverse

from courses import builder
from courses.builder import NESTABLE_TYPE_KEYS
from courses.builder import NestingError
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

INTERACTIVE_SPOILER_FORM_KEYS = [
    "revealgate",
    "fillgate",
    "switchgate",
    "switchgrid",
    "fillblankquestion",
    "filltable",
]


def _nested_spoiler(unit, child_bodies=("<p>a</p>", "<p>b</p>")):
    """A top-level spoiler with N TextElement children, in order."""
    sp = SpoilerElement.objects.create(label="Hint")
    join = Element.objects.create(unit=unit, content_object=sp)
    for i, body in enumerate(child_bodies):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=body),
            parent=join,
            tab_id=SpoilerElement.SLOT_ID,
            order=i,
        )
    return sp, join


def test_slot_id_is_a_nonempty_class_attr():
    assert SpoilerElement.SLOT_ID == "only"


def test_resolved_children_returns_join_rows_in_order():
    _course, unit = make_course_with_unit()
    sp, join = _nested_spoiler(unit, ("<p>first</p>", "<p>second</p>"))
    children = sp.resolved_children()
    bodies = [c.content_object.body for c in children]
    assert bodies == ["<p>first</p>", "<p>second</p>"]
    assert all(c.parent_id == join.pk for c in children)


def test_resolved_children_empty_when_no_join_row():
    sp = SpoilerElement(label="x")  # unsaved, no join row
    assert sp.resolved_children() == []


def test_render_shows_body_ABOVE_children():
    """D1: content a CA enters must stay reachable. Both render; body first.

    Assert source ORDER -- a presence-only assertion is green under the wrong order,
    and the current template puts `{% if children %}` FIRST, so a bare elif->if
    conversion produces children-above-body.
    """
    _course, unit = make_course_with_unit()
    sp, join = _nested_spoiler(unit, ("<p>CHILD-BODY</p>",))
    sp.body = "<p>LEGACY-BODY</p>"
    sp.save()
    html = sp.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "CHILD-BODY" in html
    assert "LEGACY-BODY" in html
    assert html.index("LEGACY-BODY") < html.index("CHILD-BODY")


def test_render_falls_back_to_body_when_no_children():
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="x", body="<p>LEGACY-BODY</p>")
    el = add_element(unit, sp)
    html = sp.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert "LEGACY-BODY" in html


def test_spoiler_with_math_child_reports_has_math():
    from courses.models import MathElement
    from courses.views import _element_has_math

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="x")
    join = Element.objects.create(unit=unit, content_object=sp)
    Element.objects.create(
        unit=unit,
        content_object=MathElement.objects.create(latex="x^2"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    assert _element_has_math(sp) is True


def test_legacy_body_spoiler_math_still_detected():
    from courses.views import _element_has_math

    sp = SpoilerElement.objects.create(label="x", body=r"<p>\(a\)</p>")
    assert _element_has_math(sp) is True


def test_empty_spoiler_reports_no_math():
    from courses.views import _element_has_math

    sp = SpoilerElement.objects.create(label="x", body="")
    assert _element_has_math(sp) is False


def test_empty_nested_spoiler_renders_no_body_wrapper():
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="x", body="")
    join = Element.objects.create(unit=unit, content_object=sp)  # join, zero children
    html = sp.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "spoiler__body" not in html  # no stray el--text wrapper
    assert "<details" in html


def _spoiler_join(unit, parent=None, tab_id=""):
    sp = SpoilerElement.objects.create(label="L")
    return sp, Element.objects.create(
        unit=unit, content_object=sp, parent=parent, tab_id=tab_id
    )


def test_resolve_scope_accepts_leaf_child_in_top_level_spoiler():
    from courses import builder

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    parent_join, tab = builder.resolve_scope(
        unit, str(join.pk), SpoilerElement.SLOT_ID, "text"
    )
    assert parent_join == join
    assert tab == SpoilerElement.SLOT_ID


def test_resolve_scope_child_types_in_a_top_level_spoiler():
    # Depth-3 slice: a top-level spoiler (depth 1) takes CONTAINER children too --
    # they land at depth 2. Only genuinely non-nestable types stay rejected.
    import pytest

    from courses import builder
    from courses.builder import NestingError

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    # `choicequestion` used to live in this tuple; it is now accepted in a LESSON
    # (see the `good` loop). The question types the widening deliberately left out
    # keep it honest.
    for bad in ("extendedresponsequestion", "dragfillblankquestion"):
        with pytest.raises(NestingError):
            builder.resolve_scope(unit, str(join.pk), SpoilerElement.SLOT_ID, bad)
    # The widened question FORM keys, exactly as element_add hands them over.
    for good in ("tabs", "spoiler", "choicequestion", "shorttextquestion"):
        parent_join, tab = builder.resolve_scope(
            unit, str(join.pk), SpoilerElement.SLOT_ID, good
        )
        assert parent_join == join and tab == SpoilerElement.SLOT_ID


def test_resolve_scope_child_types_in_a_top_level_spoiler_on_a_QUIZ():
    """The quiz-refusal companion of the `good` loop above. The widened question
    form keys move from the accepted list to the refused one purely because the
    unit is a quiz; the container keys stay accepted, which is what stops this
    passing under a "quiz refuses every nested child" implementation."""
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    _sp, join = _spoiler_join(quiz)
    for bad in ("choicequestion", "shorttextquestion", "shortnumericquestion"):
        with pytest.raises(NestingError):
            builder.resolve_scope(quiz, str(join.pk), SpoilerElement.SLOT_ID, bad)
    for good in ("tabs", "spoiler", "text"):
        parent_join, tab = builder.resolve_scope(
            quiz, str(join.pk), SpoilerElement.SLOT_ID, good
        )
        assert parent_join == join and tab == SpoilerElement.SLOT_ID


def test_nestable_type_keys_includes_interactive_leaves_and_containers():
    for k in (
        "reveal_gate",
        "fill_gate",
        "switch_gate",
        "switch_grid",
        "fill_blank",
        "fill_table",
    ):
        assert k in NESTABLE_TYPE_KEYS
    for k in ("tabs", "two_column", "spoiler"):  # containers are nestable now
        assert k in NESTABLE_TYPE_KEYS
    for k in ("choice", "short_text", "short_numeric"):  # the widened questions
        assert k in NESTABLE_TYPE_KEYS
    # `choicequestion` is a FORM key, and form keys never appear in this set --
    # resolve_scope translates them through _NESTABLE_FORM_KEY_ALIASES first. It used
    # to sit in the list below under the comment "genuinely non-nestable", which
    # became a lie the moment `choice` was widened while the assertion stayed green.
    assert "choicequestion" not in NESTABLE_TYPE_KEYS
    for k in ("extended_response", "slidebreak"):  # genuinely non-nestable
        assert k not in NESTABLE_TYPE_KEYS


def test_nestable_type_keys_includes_fill_blank():
    assert "fill_blank" in NESTABLE_TYPE_KEYS


@pytest.mark.django_db
@pytest.mark.parametrize("form_key", INTERACTIVE_SPOILER_FORM_KEYS)
def test_resolve_scope_accepts_interactive_form_key_in_spoiler(form_key):
    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    parent_join, tab = builder.resolve_scope(
        unit, str(join.pk), SpoilerElement.SLOT_ID, form_key
    )
    assert parent_join == join
    assert tab == SpoilerElement.SLOT_ID


@pytest.mark.django_db
def test_resolve_scope_accepts_leaf_child_of_a_nested_spoiler():
    # A spoiler-in-spoiler sits at depth 2 and takes both a leaf child (depth 3) and a
    # THIRD spoiler (depth 3). Clause 4 only bites one level further down: the
    # depth-3 spoiler takes leaves but no fourth container -- the user's
    # "spoiler with child tabs with child spoiler, but this is it" boundary, read
    # through the all-spoiler chain.
    _course, unit = make_course_with_unit()
    _outer_sp, outer_join = _spoiler_join(unit)
    _inner_sp, inner_join = _spoiler_join(
        unit, parent=outer_join, tab_id=SpoilerElement.SLOT_ID
    )
    parent_join, tab = builder.resolve_scope(
        unit, str(inner_join.pk), SpoilerElement.SLOT_ID, "switchgate"
    )
    assert parent_join == inner_join and tab == SpoilerElement.SLOT_ID
    # ...and a THIRD container level is still accepted here
    parent_join, tab = builder.resolve_scope(
        unit, str(inner_join.pk), SpoilerElement.SLOT_ID, "spoiler"
    )
    assert parent_join == inner_join and tab == SpoilerElement.SLOT_ID

    # ...but a FOURTH is not, while a leaf at depth 4 still is.
    _third_sp, third_join = _spoiler_join(
        unit, parent=inner_join, tab_id=SpoilerElement.SLOT_ID
    )
    parent_join, tab = builder.resolve_scope(
        unit, str(third_join.pk), SpoilerElement.SLOT_ID, "switchgate"
    )
    assert parent_join == third_join and tab == SpoilerElement.SLOT_ID
    with pytest.raises(NestingError):
        builder.resolve_scope(
            unit, str(third_join.pk), SpoilerElement.SLOT_ID, "spoiler"
        )


def test_resolve_scope_rejects_wrong_slot_for_spoiler():
    import pytest

    from courses import builder
    from courses.builder import NestingError

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(join.pk), "wrong", "text")


def test_resolve_scope_accepts_children_for_a_spoiler_inside_a_tab():
    from courses import builder
    from courses.models import TabsElement

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tjoin = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    # Purpose bullet 3: a spoiler nested inside a tab (depth 2) DOES take leaf
    # children -- they land at depth 3.
    _sp, sp_join = _spoiler_join(unit, parent=tjoin, tab_id=tab_id)
    parent_join, tab = builder.resolve_scope(
        unit, str(sp_join.pk), SpoilerElement.SLOT_ID, "text"
    )
    assert parent_join == sp_join and tab == SpoilerElement.SLOT_ID


def test_spoiler_form_keeps_body_for_legacy_spoiler():
    from courses.element_forms import SpoilerElementForm

    sp = SpoilerElement.objects.create(label="L", body="<p>x</p>")
    form = SpoilerElementForm(instance=sp)
    assert "body" in form.fields
    assert "label" in form.fields


def test_spoiler_form_keeps_body_when_instance_has_children():
    """The `fields.pop` protected data nobody could reach: not rendered (template
    elif) and not editable (this pop), with no signal anywhere."""
    from courses.element_forms import SpoilerElementForm

    _course, unit = make_course_with_unit()
    sp, _join = _nested_spoiler(unit, ("<p>c</p>",))
    form = SpoilerElementForm(instance=sp)
    assert "body" in form.fields
    assert "label" in form.fields


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _editor_html(client, course, unit):
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    return resp.content.decode()


def _spoiler_menu_block(html, join_pk):
    """The spoiler's OWN in_spoiler add-menu, bounded to its addwrap. The editor
    renders an unconditional top-level `_add_menu` after the element list, so a
    fixed-size window would overrun into it and defeat the assertions. Slice from
    this spoiler's `data-parent="<pk>"` marker to the START of the NEXT addwrap
    (the token `addwrap` appears only in an add-menu wrapper's class, and the two
    occurrences in THIS wrapper's `class="addwrap addwrap--nested"` are before the
    marker), so the window contains exactly this spoiler's menu."""
    marker = f'data-parent="{join_pk}"'
    start = html.index(marker)
    rest = html[start + len(marker) :]
    nxt = rest.find("addwrap")  # start of the next add-menu wrapper, if any
    return rest if nxt == -1 else rest[:nxt]


def test_top_level_spoiler_renders_child_list_and_add_menu(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    sp, join = _nested_spoiler(unit, ("<p>c</p>",))
    html = _editor_html(client, course, unit)
    assert f'data-parent="{join.pk}"' in html  # add-menu scope present
    assert f'data-tab="{SpoilerElement.SLOT_ID}"' in html


def test_spoiler_add_menu_hides_disallowed_cards(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _sp, join = _nested_spoiler(unit, ("<p>c</p>",))
    block = _spoiler_menu_block(_editor_html(client, course, unit), join.pk)
    # INVERTED by the depth-3 slice: the `in_spoiler` flag is gone, so html/stepper/
    # markdone/guessnumber are no longer special-cased away, and `spoiler` is now
    # governed purely by depth -- this spoiler is TOP-LEVEL (depth 1), so a spoiler
    # child would land at depth 2, which builder clause 4 accepts.
    for allowed in (
        "text",
        "image",
        "table",
        "math",
        "video",
        "iframe",
        "gallery",
        "callout",
        "html",
        "spoiler",
        "stepper",
        "markdone",
        "guessnumber",
    ):
        assert f'data-add-type="{allowed}"' in block, allowed
    # INVERTED by the question widening, then again by the grid widening, which moved
    # choicegridquestion/multigridquestion out of the banned tuple below. Reads
    # NESTED_QUESTION_CARDS (defined further down) rather than a second hand-written
    # copy: the two lists drifting apart is exactly how this test broke last time --
    # the module-level tuple grew and this literal did not.
    for allowed_question in NESTED_QUESTION_CARDS:
        assert f'data-add-type="{allowed_question}"' in block, allowed_question
    # The drag types and extended_response stay hidden in every nested menu -- they
    # are not in NESTABLE_TYPE_KEYS and a click would 400. Asserted as the COMPLEMENT
    # of the tuple above, so a card can never appear in both.
    for banned_question in (
        "dragfillblankquestion",
        "matchpairquestion",
        "dragtoimagequestion",
        "extendedresponsequestion",
    ):
        assert banned_question not in NESTED_QUESTION_CARDS, banned_question
        assert f'data-add-type="{banned_question}"' not in block, banned_question


def test_spoiler_add_menu_shows_allowed_interactive_cards(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _sp, join = _nested_spoiler(unit, ("<p>c</p>",))
    block = _spoiler_menu_block(_editor_html(client, course, unit), join.pk)
    present = {m.group(1) for m in re.finditer(r'data-add-type="([^"]+)"', block)}
    assert {
        "revealgate",
        "fillgate",
        "switchgate",
        "switchgrid",
        "fillblankquestion",
        "filltable",
        # INVERTED by the depth-3 slice: these four were hidden by `in_spoiler`, a flag
        # that no longer exists. `spoiler` is now depth-governed and this spoiler is
        # top-level (depth 1), so a spoiler child lands at the legal depth 2.
        "spoiler",
        "stepper",
        "markdone",
        "guessnumber",
        # INVERTED by the question widening: the nested Questions group.
        "choice-single",
        "shorttextquestion",
    } <= present
    # no NON-widened question card leaks into a nested menu
    assert present.isdisjoint({"dragfillblankquestion", "extendedresponsequestion"})


def test_author_switchgate_into_spoiler_succeeds(client):
    from courses.models import SwitchGateElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _sp, join = _spoiler_join(unit)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "switchgate",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "parent": str(join.pk),
            "tab": SpoilerElement.SLOT_ID,
            "stem": "pick {{choice}}",
            "option": ["a", "b"],
            "answer": "0",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    child = Element.objects.get(parent=join)
    assert isinstance(child.content_object, SwitchGateElement)
    assert child.tab_id == SpoilerElement.SLOT_ID


def test_tabs_add_menu_offers_the_widened_questions_and_hides_the_rest(client):
    # PR#126 no-regression, updated twice: by the depth-3 slice (fill-blank is offered
    # in EVERY nested menu now, not only in-spoiler -- the `in_spoiler` flag is gone)
    # and by the question widening (the nested Questions group). The tabs nested
    # add-menu still shows the 4 gates and the Spoiler card, and still hides the
    # question types left out of NESTABLE_TYPE_KEYS.
    from courses.models import TabsElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tjoin = Element.objects.create(unit=unit, content_object=tabs)
    block = _spoiler_menu_block(_editor_html(client, course, unit), tjoin.pk)
    for allowed in (
        "revealgate",
        "fillgate",
        "switchgate",
        "switchgrid",
        "spoiler",
        "fillblankquestion",  # INVERTED by the depth-3 slice
        "choice-single",  # INVERTED by the question widening
        "choice-multi",
        "shorttextquestion",
        "shortnumericquestion",
        "choicegridquestion",  # INVERTED by the grid widening
        "multigridquestion",
    ):
        assert f'data-add-type="{allowed}"' in block, allowed
    for banned_question in (
        "extendedresponsequestion",
        "dragfillblankquestion",
    ):
        assert f'data-add-type="{banned_question}"' not in block, banned_question


def test_tabs_nested_menu_still_offers_spoiler(client):
    # PR #126 no-regression: the Tabs nested add-menu (nested=True, NOT in_spoiler)
    # must still offer the spoiler + interactive cards.
    from courses.models import TabsElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=unit, content_object=tabs)
    html = _editor_html(client, course, unit)
    assert 'data-add-type="spoiler"' in html  # still present via the tabs nested menu


# The nested `Questions` group, card by card. Assert the STRINGS, never a count of
# the group: a count is blind to the choice-single/choice-multi mix-up, and emitting
# data-add-type="choicequestion" on both cards would 200 on every click while
# silently producing two identical single-choice elements. (The per-card `count == 2`
# below is a different check -- it locates each card in BOTH menus.)
NESTED_QUESTION_CARDS = (
    "choice-single",
    "choice-multi",
    "shorttextquestion",
    "shortnumericquestion",
    "fillblankquestion",
    "choicegridquestion",
    "multigridquestion",
)


def _quiz_unit(course):
    return ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")


def test_nested_add_menu_offers_every_question_card_in_a_lesson(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _sp, join = _spoiler_join(unit)
    block = _spoiler_menu_block(_editor_html(client, course, unit), join.pk)
    for card in NESTED_QUESTION_CARDS:
        assert f'data-add-type="{card}"' in block, card


def test_nested_add_menu_offers_no_question_card_in_a_quiz(client):
    """The `not unit_is_quiz` half of the group's guard. Hiding is courtesy -- the
    server refusal is a separate authority -- but a quiz author must not be invited
    to click something that cannot work."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _sp, join = _spoiler_join(unit)
    block = _spoiler_menu_block(_editor_html(client, course, unit), join.pk)
    for card in NESTED_QUESTION_CARDS:
        assert f'data-add-type="{card}"' not in block, card
    # Not vacuous: this really is a rendered nested menu, it just has no questions.
    assert 'data-add-type="text"' in block


def test_the_nested_questions_group_is_a_sibling_of_the_top_level_block(client):
    """Placement, which is load-bearing and fails SILENTLY: a `{% if nested %}` group
    written INSIDE the existing `{% if not nested %}` block is unreachable, every
    server gate test still passes, and the author simply never sees the cards.

    Counting per CARD is what catches it -- the top-level menu emits each of these
    strings once regardless, so a presence check on the whole page is green under the
    unreachable placement. With one spoiler on a lesson unit there are exactly two
    menus that may carry them: the top-level one and the spoiler's nested one.
    """
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _sp, _join = _spoiler_join(unit)
    html = _editor_html(client, course, unit)
    for card in NESTED_QUESTION_CARDS:
        assert html.count(f'data-add-type="{card}"') == 2, card
    # ...and the top-level group is untouched: its non-nestable cards stay exactly
    # once, so the new group did not accidentally duplicate the whole of it.
    for card in ("dragfillblankquestion", "extendedresponsequestion", "slidebreak"):
        assert html.count(f'data-add-type="{card}"') == 1, card


def test_reorder_and_delete_spoiler_child_via_generic_element_ops(client):
    # add/edit are covered by resolve_scope (Task 7) + the form (Task 8); reorder/
    # delete are generic Element ops (shared with Tabs). Prove they work for the
    # spoiler slot: reorder swaps child order; delete removes one child cleanly.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    sp, join = _nested_spoiler(unit, ("<p>A</p>", "<p>B</p>"))
    a, b = sp.resolved_children()
    a_pk, b_pk = a.pk, b.pk
    # reorder: push the first child's order past the second's -> it now sorts last.
    # (`order` is a PositiveIntegerField with a DB CHECK order >= 0, so bump `a`
    # upward rather than driving `b` negative.)
    a.order = 2
    a.save(update_fields=["order"])
    assert [c.pk for c in sp.resolved_children()] == [b_pk, a_pk]
    # delete the first child's concrete -> its Element join row cascades away
    # (TextElement.elements is a GenericRelation), leaving exactly one child.
    a.content_object.delete()
    remaining = sp.resolved_children()
    assert [c.pk for c in remaining] == [b_pk]
    assert remaining[0].content_object.body == "<p>B</p>"


def test_bodied_spoiler_nesting_a_spoiler_keeps_body_above_children_at_both_levels():
    """Same-type nesting with a bodied outer -- the fixture-monoculture gap PR #209
    root-caused. Both levels must render body first."""
    _course, unit = make_course_with_unit()
    outer = SpoilerElement.objects.create(label="outer", body="<p>OUTER-BODY</p>")
    outer_join = add_element(unit, outer)
    inner = SpoilerElement.objects.create(label="inner", body="<p>INNER-BODY</p>")
    inner_join = Element.objects.create(
        unit=unit,
        content_object=inner,
        parent=outer_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>INNER-CHILD</p>"),
        parent=inner_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    html = outer.render(element=outer_join, state={}, slug="x", node_pk=unit.pk)
    assert html.index("OUTER-BODY") < html.index("INNER-BODY")
    assert html.index("INNER-BODY") < html.index("INNER-CHILD")
