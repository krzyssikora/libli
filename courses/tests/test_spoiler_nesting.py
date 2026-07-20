import pytest

from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


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
