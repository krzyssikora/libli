import pytest

from courses.models import ELEMENT_MODELS
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import UnitProgress

pytestmark = pytest.mark.django_db


def test_markdone_element_and_items_order_and_strip():
    el = MarkDoneElement.objects.create(prompt="  do these  ")
    assert el.prompt == "do these"  # stripped in save()
    a = MarkDoneItem.objects.create(element=el, content="  first ")
    b = MarkDoneItem.objects.create(element=el, content="second")
    assert a.content == "first"  # stripped
    assert [i.pk for i in el.items.all()] == [a.pk, b.pk]  # order 0,1
    assert a.order == 0 and b.order == 1


def test_markdone_class_constants():
    constants = (
        MarkDoneElement.MIN_ITEMS,
        MarkDoneElement.MAX_ITEMS,
        MarkDoneElement.MAX_LEN,
    )
    assert constants == (1, 20, 500)


def test_element_models_includes_markdone():
    assert "markdoneelement" in ELEMENT_MODELS


def test_unit_progress_checklist_state_defaults_to_dict():
    # minimal: checklist_state default is an empty dict
    up = UnitProgress()
    assert up.checklist_state == {}
