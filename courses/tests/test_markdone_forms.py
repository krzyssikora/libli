import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import MarkDoneElementForm
from courses.element_forms import build_markdone_formset
from courses.models import MarkDoneElement

pytestmark = pytest.mark.django_db


def _post(prompt="Prep", items=("a", "b"), total=None):
    total = len(items) if total is None else total
    data = {
        "prompt": prompt,
        "items-TOTAL_FORMS": str(total),
        "items-INITIAL_FORMS": "0",
        "items-MIN_NUM_FORMS": "0",
        "items-MAX_NUM_FORMS": "1000",
    }
    for i, c in enumerate(items):
        data[f"items-{i}-content"] = c
    return data


def test_registered():
    assert FORM_FOR_TYPE["markdone"] is MarkDoneElementForm


def test_formset_requires_at_least_one_item():
    data = _post(items=(), total=0)
    form = MarkDoneElementForm(data=data)
    fs = build_markdone_formset(data=data, instance=MarkDoneElement())
    assert form.is_valid()
    assert not fs.is_valid()  # MIN_ITEMS violated


def test_valid_form_and_formset():
    data = _post()
    form = MarkDoneElementForm(data=data)
    fs = build_markdone_formset(data=data, instance=MarkDoneElement())
    assert form.is_valid() and fs.is_valid()


def test_formset_rejects_over_max_items():
    items = tuple(f"item {i}" for i in range(MarkDoneElement.MAX_ITEMS + 1))
    data = _post(items=items)
    fs = build_markdone_formset(data=data, instance=MarkDoneElement())
    assert not fs.is_valid()


def test_save_element_persists_ordered_items():
    from courses.builder import save_element
    from courses.models import Element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    data = _post(items=("one", "", "three"), total=3)  # blank middle row dropped
    data["unit_token"] = unit.updated.isoformat()
    save_element(course, unit.pk, "markdone", "new", data, {})
    el = MarkDoneElement.objects.latest("pk")
    assert [i.content for i in el.items.all()] == ["one", "three"]
    assert [i.order for i in el.items.all()] == [0, 1]
    assert Element.objects.filter(object_id=el.pk).exists()


def test_save_element_edit_reorders_and_deletes():
    from courses.builder import save_element
    from courses.models import Element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    data = _post(items=("a", "b"), total=2)
    data["unit_token"] = unit.updated.isoformat()
    save_element(course, unit.pk, "markdone", "new", data, {})
    el = MarkDoneElement.objects.get()
    a, b = list(el.items.all())
    join = Element.objects.get(object_id=el.pk)
    unit.refresh_from_db()

    data2 = {
        "prompt": "",
        "items-TOTAL_FORMS": "3",
        "items-INITIAL_FORMS": "2",
        "items-MIN_NUM_FORMS": "0",
        "items-MAX_NUM_FORMS": "1000",
        "items-0-id": str(a.pk),
        "items-0-content": "a",
        "items-0-DELETE": "on",
        "items-1-id": str(b.pk),
        "items-1-content": "b",
        "items-2-content": "c",
        "unit_token": unit.updated.isoformat(),
    }
    save_element(course, unit.pk, "markdone", str(join.pk), data2, {})
    el.refresh_from_db()
    assert [i.content for i in el.items.all()] == ["b", "c"]
    assert [i.order for i in el.items.all()] == [0, 1]
