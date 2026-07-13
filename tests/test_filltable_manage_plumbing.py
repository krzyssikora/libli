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


def test_element_add_renders_filltable_editor_200(client):
    # element_add fully renders the open-form host, which auto-includes
    # templates/courses/manage/editor/_edit_filltable.html (Task 6). POST is
    # required -- the view reads request.POST["type"] / request.POST["unit"]
    # (a GET 404s at the unit lookup), mirroring test_table_manage_plumbing.py.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "filltable", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"data-filltable-editor" in resp.content


def test_palette_card_present_non_nested_absent_nested(client):
    # Mirrors test_spoiler_palette.py: the top-level add-menu (rendered once
    # for the unit + once nested inside the tabs child scope) must offer the
    # filltable card only at the top level -- it is non-nestable.
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
    assert resp.status_code == 200
    html = resp.content.decode()
    assert html.count('data-add-type="filltable"') == 1  # not nestable: top only
    assert 'href="#el-filltable"' in html
    assert 'id="el-filltable"' in html


def test_editor_html_loads_both_filltable_scripts(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"courses/js/filltable.js" in resp.content
    assert b"courses/js/filltable_editor.js" in resp.content
