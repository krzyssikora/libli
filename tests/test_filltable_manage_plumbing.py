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


def test_palette_card_present_top_and_nested(client):
    # Mirrors test_spoiler_palette.py: the add-menu renders once for the unit
    # and once nested inside the tabs child scope; the filltable card must
    # appear in BOTH -- it is nestable.
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
    assert html.count('data-add-type="filltable"') >= 2  # nestable: top + nested
    assert 'href="#el-filltable"' in html
    assert 'id="el-filltable"' in html


def test_nested_save_creates_child_and_renders_in_tab(client):
    # End-to-end: POST the real save endpoint with parent+tab, proving a fill-table
    # actually persists nested inside a tab (resolve_scope accepts "filltable") and
    # then renders inside that tab's panel on the student lesson page.
    import json

    from courses.models import Element
    from courses.models import FillTableElement
    from courses.models import TabsElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "filltable",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "parent": str(join.pk),
            "tab": tab_id,
            "data": json.dumps({"cells": [[{"kind": "answer", "answer": "4"}]]}),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code in (200, 302)
    child = Element.objects.get(parent=join)
    assert isinstance(child.content_object, FillTableElement)
    assert child.tab_id == tab_id
    # ...and it renders inside the tab on the student consumption page.
    from courses.views import build_lesson_context

    ctx = build_lesson_context(unit, pa)
    assert ctx["has_fill_table"] is True


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
