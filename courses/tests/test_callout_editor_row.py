"""The editor row for a callout.

Every other test in this slice passes without this branch existing at all: the
depth tests use tabs fixtures, and "a callout accepts a table child" is satisfiable
through resolve_scope/POST without ever rendering the editor. So the branch needs
its own pins.
"""

import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _editor_html(client, course, unit):
    from django.urls import reverse

    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    resp = client.get(url)
    # Assert 200 first, mirroring tests/test_editor_depth.py::_page -- otherwise a
    # 403/302 surfaces as "el-row--callout not in html" and misdirects the debugging.
    assert resp.status_code == 200
    return resp.content.decode()


def test_callout_row_renders_children_and_its_own_add_menu(client):
    from tests.factories import add_element

    pa = make_pa(client, "pa")
    course, unit = make_course_with_unit(owner=pa)
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>NESTED-CHILD</p>"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    html = _editor_html(client, course, unit)
    assert "el-row--callout" in html
    assert "el-row__callout" in html
    assert "NESTED-CHILD" in html
    # `_add_menu.html:25` emits data-parent/data-tab -- there is no `data-add-parent`.
    # And no `or`: `value="{pk}"` is emitted by _element_row_controls.html on EVERY
    # row, so it holds whether or not the nested menu rendered.
    assert f'data-parent="{join.pk}" data-tab="{CalloutElement.SLOT_ID}"' in html


def test_callout_row_keeps_the_base_class_and_data_element(client):
    """editor.js selects `.el-row[data-element]` at :147/:289/:391 for selection,
    alignment and the edit-slot lifecycle. A modifier-only row silently drops out."""
    from tests.factories import add_element

    pa = make_pa(client, "pa")
    course, unit = make_course_with_unit(owner=pa)
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    html = _editor_html(client, course, unit)
    assert 'class="el-row el-row--callout' in html
    assert f'data-element="{join.pk}"' in html
