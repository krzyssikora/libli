import pytest

from courses.models import (
    Course,
    ContentNode,
    Element,
    HtmlElement,
    ELEMENT_MODELS,
)


def test_htmlelement_in_element_models():
    assert "htmlelement" in ELEMENT_MODELS


@pytest.mark.django_db
def test_htmlelement_stores_raw_html_unsanitized():
    el = HtmlElement.objects.create(html='<script>alert(1)</script><b>x</b>')
    el.refresh_from_db()
    # Containment is the iframe, not sanitization — markup is stored verbatim.
    assert el.html == '<script>alert(1)</script><b>x</b>'


@pytest.mark.django_db
def test_course_and_unit_html_fields_default_empty():
    course = Course.objects.create(title="C", slug="c")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    assert course.html_css == "" and course.html_js == ""
    assert unit.html_seed_js == ""


@pytest.mark.django_db
def test_htmlelement_cascades_join_row_on_delete():
    course = Course.objects.create(title="C", slug="c2")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    el = HtmlElement.objects.create(html="<p>hi</p>")
    Element.objects.create(unit=unit, content_object=el)
    assert Element.objects.count() == 1
    el.delete()  # concrete-first delete cascades the join row via GenericRelation
    assert Element.objects.count() == 0


@pytest.mark.django_db
def test_htmlelement_editor_delete_removes_concrete_and_join():
    # Spec §8.1: exercise the REAL editor delete path (builder.delete_element,
    # which deletes concrete-first + compacts ordering), not just bare .delete().
    from courses import builder
    course = Course.objects.create(title="C", slug="c-del")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT, title="U",
        unit_type=ContentNode.UnitType.LESSON,
    )
    join = Element.objects.create(
        unit=unit, content_object=HtmlElement.objects.create(html="<p>x</p>")
    )
    unit.refresh_from_db()
    builder.delete_element(course, join.pk, unit.updated.isoformat())
    assert HtmlElement.objects.count() == 0
    assert Element.objects.count() == 0
