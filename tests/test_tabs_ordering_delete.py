import pytest

from courses import builder as builder_svc
from courses import ordering
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit  # use the existing helper

pytestmark = pytest.mark.django_db


def _tabs(unit):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    return obj, join


def _child(unit, join, tab_id, body="x"):
    txt = TextElement.objects.create(body=body)
    return Element.objects.create(
        unit=unit, content_object=txt, parent=join, tab_id=tab_id
    )


def test_siblings_are_scoped_to_parent_and_tab():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1, t2 = [t["id"] for t in obj.data["tabs"]]
    a = _child(unit, join, t1, "a")
    b = _child(unit, join, t1, "b")
    c = _child(unit, join, t2, "c")
    sibs = list(ordering.element_siblings(unit, join, t1))
    assert {e.pk for e in sibs} == {a.pk, b.pk}
    assert c.pk not in {e.pk for e in sibs}
    assert list(ordering.element_siblings(unit, None, "")) == [join]


def test_compact_elements_renumbers_only_its_own_group():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1 = obj.data["tabs"][0]["id"]
    a = _child(unit, join, t1, "a")
    b = _child(unit, join, t1, "b")
    Element.objects.filter(pk=a.pk).update(order=7)
    Element.objects.filter(pk=b.pk).update(order=9)
    ordering.compact_elements(unit, parent=join, tab_id=t1)
    a.refresh_from_db()
    b.refresh_from_db()
    join.refresh_from_db()
    assert (a.order, b.order) == (0, 1)
    assert join.order == 0  # top-level group untouched


def test_reorder_within_a_tab_succeeds():
    """The regression the spec's scope-immutability rule exists to protect: a
    within-tab reorder sends no parent/tab and must still work."""
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1 = obj.data["tabs"][0]["id"]
    a = _child(unit, join, t1, "a")
    b = _child(unit, join, t1, "b")
    unit.refresh_from_db()
    builder_svc.reorder_element(
        course, str(b.pk), unit.updated.isoformat(), direction="up"
    )
    a.refresh_from_db()
    b.refresh_from_db()
    assert b.order < a.order


def test_deleting_tabs_element_leaves_zero_orphaned_concretes():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1, t2 = [t["id"] for t in obj.data["tabs"]]
    _child(unit, join, t1, "a")
    _child(unit, join, t2, "b")
    assert TextElement.objects.count() == 2
    unit.refresh_from_db()
    builder_svc.delete_element(course, str(join.pk), unit.updated.isoformat())
    assert TextElement.objects.count() == 0  # concretes gone, not orphaned
    assert TabsElement.objects.count() == 0
    assert Element.objects.filter(unit=unit).count() == 0


def test_deleting_a_nested_child_leaves_the_tabs_element():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1 = obj.data["tabs"][0]["id"]
    child = _child(unit, join, t1, "a")
    unit.refresh_from_db()
    builder_svc.delete_element(course, str(child.pk), unit.updated.isoformat())
    assert TextElement.objects.count() == 0
    assert TabsElement.objects.filter(pk=obj.pk).exists()
