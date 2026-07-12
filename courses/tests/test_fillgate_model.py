import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import ELEMENT_MODELS
from courses.models import Element
from courses.models import FillGateElement


@pytest.mark.django_db
def test_fillgate_defaults_and_registration():
    el = FillGateElement.objects.create(stem="a ￿0￿ b", answers=[["x", "y"]])
    assert el.answers == [["x", "y"]]
    # answers defaults to an empty list, not null/dict
    el2 = FillGateElement.objects.create(stem="")
    assert el2.answers == []
    assert "fillgateelement" in ELEMENT_MODELS


@pytest.mark.django_db
def test_fillgate_generic_relation_and_render():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    el = FillGateElement.objects.create(stem="hi ￿0￿", answers=[["a"]])
    join = Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    # GenericRelation reverse accessor resolves the join row
    assert el.elements.first().pk == join.pk
    # NOTE: render() output (data-element-pk exposure) is asserted in Task 3, once
    # the fillgateelement.html template exists — render() cannot be tested here
    # in isolation.
