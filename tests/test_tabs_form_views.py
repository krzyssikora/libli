import json

import pytest

from courses import builder as builder_svc
from courses.element_forms import FORM_FOR_TYPE
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

Form = FORM_FOR_TYPE["tabs"]


def _bound(payload):
    return Form(data={"data": json.dumps(payload)})


def test_blank_add_yields_two_default_tabs():
    form = Form(data={"data": ""})
    assert form.is_valid(), form.errors
    assert len(form.cleaned_data["data"]["tabs"]) == TabsElement.MIN_TABS


def test_rejects_below_min_tabs():
    assert not _bound({"tabs": [{"id": "taaaaaa", "label": "only"}]}).is_valid()


def test_rejects_above_max_tabs():
    assert not _bound({"tabs": [{"label": f"T{i}"} for i in range(11)]}).is_valid()


def test_preserves_submitted_ids():
    form = _bound(
        {"tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]}
    )
    assert form.is_valid(), form.errors
    assert [t["id"] for t in form.cleaned_data["data"]["tabs"]] == [
        "taaaaaa",
        "tbbbbbb",
    ]


def test_mints_id_for_a_new_idless_row():
    form = _bound({"tabs": [{"id": "taaaaaa", "label": "A"}, {"label": "New"}]})
    assert form.is_valid(), form.errors
    assert TabsElement.TAB_ID_RE.fullmatch(form.cleaned_data["data"]["tabs"][1]["id"])


def _make_tabs(unit):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    return obj, join


def _post(unit, **extra):
    d = {"unit_token": unit.updated.isoformat(), "unit": str(unit.pk)}
    d.update(extra)
    return d


def test_create_nested_child_sets_parent_and_tab():
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    tab = obj.data["tabs"][1]["id"]
    unit.refresh_from_db()
    builder_svc.save_element(
        course,
        unit.pk,
        "text",
        "new",
        _post(unit, body="hi", parent=str(join.pk), tab=tab),
        {},
    )
    child = Element.objects.get(parent=join)
    assert child.tab_id == tab
    assert child.unit_id == unit.pk  # children KEEP their unit FK


def test_update_of_a_nested_child_never_reparents_it():
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    tab = obj.data["tabs"][0]["id"]
    txt = TextElement.objects.create(body="a")
    child = Element.objects.create(
        unit=unit, content_object=txt, parent=join, tab_id=tab
    )
    unit.refresh_from_db()
    builder_svc.save_element(
        course, unit.pk, "text", str(child.pk), _post(unit, body="edited"), {}
    )
    child.refresh_from_db()
    assert child.parent_id == join.pk and child.tab_id == tab


@pytest.mark.parametrize(
    "kwargs",
    [
        {"parent": "PARENT"},  # parent without tab
        {"tab": "taaaaaa"},  # tab without parent
        {"parent": "PARENT", "tab": "tzzzzzz"},  # tab not in parent
        {"parent": "999999", "tab": "taaaaaa"},  # unknown parent
        {"parent": "abc", "tab": "taaaaaa"},  # non-numeric parent ref
    ],
)
def test_bad_scope_raises_nesting_error(kwargs):
    course, unit = make_course_with_unit()
    _obj, join = _make_tabs(unit)
    kwargs = {k: (str(join.pk) if v == "PARENT" else v) for k, v in kwargs.items()}
    unit.refresh_from_db()
    with pytest.raises(builder_svc.NestingError):
        builder_svc.save_element(
            course, unit.pk, "text", "new", _post(unit, body="x", **kwargs), {}
        )


def test_non_nestable_child_type_raises():
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    tab = obj.data["tabs"][0]["id"]
    unit.refresh_from_db()
    with pytest.raises(builder_svc.NestingError):  # tabs-in-tabs
        builder_svc.save_element(
            course,
            unit.pk,
            "tabs",
            "new",
            _post(unit, data="", parent=str(join.pk), tab=tab),
            {},
        )


def test_deleting_a_tab_deletes_exactly_that_tabs_children():
    """Also covers the add-and-delete-in-one-save KeyError trap: the submitted list
    carries a brand-new, id-less row alongside the survivor."""
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    keep, drop = [t["id"] for t in obj.data["tabs"]]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="keep"),
        parent=join,
        tab_id=keep,
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="drop"),
        parent=join,
        tab_id=drop,
    )
    unit.refresh_from_db()
    payload = json.dumps(
        {"tabs": [{"id": keep, "label": "Keep"}, {"label": "Brand new"}]}
    )
    builder_svc.save_element(
        course, unit.pk, "tabs", str(join.pk), _post(unit, data=payload), {}
    )
    assert set(TextElement.objects.values_list("body", flat=True)) == {"keep"}
    assert not Element.objects.filter(parent=join, tab_id=drop).exists()
    obj.refresh_from_db()
    assert len(obj.data["tabs"]) == 2  # survivor + the minted new tab
