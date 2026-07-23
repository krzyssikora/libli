import re

import pytest
from django.urls import reverse

from courses import builder
from courses.builder import NESTABLE_TYPE_KEYS
from courses.builder import SPOILER_CHILD_TYPES
from courses.builder import NestingError
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_pa

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


def test_render_prefers_children_over_body():
    _course, unit = make_course_with_unit()
    sp, join = _nested_spoiler(unit, ("<p>CHILD-BODY</p>",))
    sp.body = "<p>LEGACY-BODY</p>"
    sp.save()
    html = sp.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "CHILD-BODY" in html
    assert "LEGACY-BODY" not in html


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


def test_resolve_scope_rejects_disallowed_child_type_in_spoiler():
    import pytest

    from courses import builder
    from courses.builder import NestingError

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    for bad in ("tabs", "spoiler", "choicequestion"):
        with pytest.raises(NestingError):
            builder.resolve_scope(unit, str(join.pk), SpoilerElement.SLOT_ID, bad)


def test_spoiler_child_types_includes_interactive_leaves():
    for k in (
        "reveal_gate",
        "fill_gate",
        "switch_gate",
        "switch_grid",
        "fill_blank",
        "fill_table",
    ):
        assert k in SPOILER_CHILD_TYPES
    for k in ("tabs", "two_column", "spoiler"):  # containers still excluded
        assert k not in SPOILER_CHILD_TYPES


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
def test_resolve_scope_still_rejects_children_of_nested_spoiler():
    # a spoiler whose OWN join.parent_id is not None (depth-2) takes no children
    _course, unit = make_course_with_unit()
    _outer_sp, outer_join = _spoiler_join(unit)
    _inner_sp, inner_join = _spoiler_join(
        unit, parent=outer_join, tab_id=SpoilerElement.SLOT_ID
    )
    with pytest.raises(NestingError):
        builder.resolve_scope(
            unit, str(inner_join.pk), SpoilerElement.SLOT_ID, "switchgate"
        )


def test_resolve_scope_rejects_wrong_slot_for_spoiler():
    import pytest

    from courses import builder
    from courses.builder import NestingError

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(join.pk), "wrong", "text")


def test_resolve_scope_refuses_children_for_nested_spoiler():
    import pytest

    from courses import builder
    from courses.builder import NestingError
    from courses.models import TabsElement

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tjoin = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    # a spoiler nested inside a tab (depth 1) may NOT itself receive children
    _sp, sp_join = _spoiler_join(unit, parent=tjoin, tab_id=tab_id)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(sp_join.pk), SpoilerElement.SLOT_ID, "text")


def test_spoiler_form_keeps_body_for_legacy_spoiler():
    from courses.element_forms import SpoilerElementForm

    sp = SpoilerElement.objects.create(label="L", body="<p>x</p>")
    form = SpoilerElementForm(instance=sp)
    assert "body" in form.fields
    assert "label" in form.fields


def test_spoiler_form_drops_body_when_instance_has_children():
    from courses.element_forms import SpoilerElementForm

    _course, unit = make_course_with_unit()
    sp, _join = _nested_spoiler(unit, ("<p>c</p>",))
    form = SpoilerElementForm(instance=sp)
    assert "body" not in form.fields
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
    # allowlisted leaves ARE offered inside the spoiler menu
    for allowed in (
        "text",
        "image",
        "table",
        "math",
        "video",
        "iframe",
        "gallery",
        "callout",
    ):
        assert f'data-add-type="{allowed}"' in block, allowed
    # disallowed cards are NOT offered inside the spoiler menu (the non-allowed
    # Interactive cards -- gates/switchgrid/fillblank/filltable are now ALLOWED, see
    # test_spoiler_add_menu_shows_allowed_interactive_cards below)
    for banned in (
        "html",
        "spoiler",
        "stepper",
        "markdone",
        "guessnumber",
    ):
        assert f'data-add-type="{banned}"' not in block, banned
    # non-fillblank question cards stay hidden in-spoiler
    for banned_question in (
        "choice-single",
        "choice-multi",
        "shorttextquestion",
        "shortnumericquestion",
        "dragfillblankquestion",
        "matchpairquestion",
        "choicegridquestion",
        "multigridquestion",
        "dragtoimagequestion",
        "extendedresponsequestion",
    ):
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
    } <= present
    # the non-allowed interactive/structure cards are ABSENT in-spoiler
    assert present.isdisjoint({"spoiler", "stepper", "markdone", "guessnumber"})
    # no other question card leaks in-spoiler
    assert present.isdisjoint(
        {"choice-single", "shorttextquestion", "dragfillblankquestion"}
    )


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


def test_tabs_add_menu_unaffected(client):
    # PR#126 no-regression: the tabs nested add-menu (nested=True, NOT in_spoiler)
    # still shows the 4 gates and hides questions.
    from courses.models import TabsElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tjoin = Element.objects.create(unit=unit, content_object=tabs)
    block = _spoiler_menu_block(_editor_html(client, course, unit), tjoin.pk)
    for allowed in ("revealgate", "fillgate", "switchgate", "switchgrid", "spoiler"):
        assert f'data-add-type="{allowed}"' in block, allowed
    for banned_question in (
        "choice-single",
        "shorttextquestion",
        "fillblankquestion",
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
