import pytest

from courses.models import Element
from courses.models import MathElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from courses.views import _element_has_math
from tests.factories import make_course_with_unit


@pytest.mark.django_db
def test_two_column_reports_math_from_nested_child():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    assert _element_has_math(col) is False
    Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=cid,
        content_object=MathElement.objects.create(latex="x^2"),
    )
    assert _element_has_math(col) is True


@pytest.mark.django_db
def test_two_column_no_math_when_children_plain():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=cid,
        content_object=TextElement.objects.create(body="plain"),
    )
    assert _element_has_math(col) is False
