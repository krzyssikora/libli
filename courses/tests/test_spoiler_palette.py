import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_palette_card_present_with_data_add_type(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'data-add-type="spoiler"' in html
    assert 'href="#el-spoiler"' in html
    assert 'id="el-spoiler"' in html


def test_spoiler_card_in_nested_add_menu(client):
    from courses.models import Element
    from courses.models import TabsElement
    from courses.models import TextElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="child"),
        parent=join,
        tab_id=tab_id,
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    html = resp.content.decode()
    assert html.count('data-add-type="revealgate"') >= 2  # nestable: top + nested
    assert html.count('data-add-type="spoiler"') >= 2  # nestable: top + nested


def test_spoiler_is_nestable_via_resolve_scope():
    # Prove nesting is actually allowed through the real resolve_scope() path
    # (form key "spoiler"), mirroring test_callout_is_nestable_via_resolve_scope.
    from courses import builder
    from courses.models import Element
    from courses.models import TabsElement
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    parent_join, resolved_tab = builder.resolve_scope(
        unit, str(join.pk), tab_id, "spoiler"
    )
    assert parent_join == join
    assert resolved_tab == tab_id
