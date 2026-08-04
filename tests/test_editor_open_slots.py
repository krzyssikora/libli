import pytest
from django.urls import reverse

from courses.builder import ancestor_slots
from courses.builder import slot_key
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_slot_key_uses_an_explicit_none_test():
    """`parent_pk or ''` would collapse a pk of 0 onto the top-level key."""
    assert slot_key(None, "") == ":"
    assert slot_key(0, "t1") == "0:t1"
    assert slot_key(12, "t1") == "12:t1"


def test_ancestor_slots_names_every_container_above_a_join():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=tabs_join,
        tab_id=t2,
    )

    assert ancestor_slots(child) == {slot_key(tabs_join.pk, t2)}
    assert ancestor_slots(tabs_join) == set()


def test_duplicating_inside_tab_two_renders_that_tab_open(client):
    """Without the open-set the response shows only tab 1, so the author's new
    copy is born invisible."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=tabs_join,
        tab_id=t2,
    )

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    marker = f'data-tab-id="{t2}"'
    at = body.index(marker)
    tag = body[at : at + 200]
    assert " open" in tag
    assert "data-force-open" in tag


def test_a_column_nested_in_a_tab_opens_its_whole_ancestor_chain(client):
    """The `:132` edit uses `column.id`, not `tab.id`. Copying the tabs line
    verbatim there fails SILENTLY -- nested inside a tabs element, `tab` is still
    in scope (the recursive include at :86 passes no `only`), so the key names
    the enclosing TAB and matches nothing. Without this test that ships green,
    and it also gives ancestor_slots its only two-hop exercise."""
    from courses.models import TwoColumnElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    cols = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols_join = Element.objects.create(
        unit=unit, content_object=cols, parent=tabs_join, tab_id=t2
    )
    _c1, c2 = [c["id"] for c in cols.data["columns"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>deep</p>"),
        parent=cols_join,
        tab_id=c2,
    )

    # Two hops: the column slot AND the tab slot above it.
    assert ancestor_slots(child) == {
        slot_key(cols_join.pk, c2),
        slot_key(tabs_join.pk, t2),
    }

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    for marker in (f'data-column-id="{c2}"', f'data-tab-id="{t2}"'):
        tag = body[body.index(marker) : body.index(marker) + 200]
        assert "data-force-open" in tag, marker
        assert " open" in tag, marker
