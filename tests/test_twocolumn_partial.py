import pytest

from courses.models import Element
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def test_render_emits_columns_with_children():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    ids = [c["id"] for c in col.data["columns"]]
    Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=ids[0],
        content_object=TextElement.objects.create(body="LEFT"),
    )
    Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=ids[1],
        content_object=TextElement.objects.create(body="RIGHT"),
    )
    html = col.render()
    assert 'class="el el--twocolumn"' in html
    assert html.count("twocolumn__column") == 2
    assert "LEFT" in html and "RIGHT" in html


def test_render_empty_column_still_emitted():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(
        data={
            "columns": [
                {"id": "c000001"},
                {"id": "c000002"},
                {"id": "c000003"},
            ]
        }
    )
    col.save()
    Element.objects.create(unit=unit, content_object=col)
    html = col.render()
    assert html.count("twocolumn__column") == 3  # empty columns still render
