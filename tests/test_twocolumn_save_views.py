import pytest
from django.urls import reverse

from courses import builder as builder_svc
from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import TwoColumnElementForm
from courses.models import Element
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["twocolumn"] is TwoColumnElementForm


def test_form_has_no_data_field():
    f = TwoColumnElementForm()
    assert "data" not in f.fields
    assert "column_count" in f.fields


def test_form_column_count_coerces_int_and_bounds():
    f = TwoColumnElementForm(data={"column_count": "3"})
    assert f.is_valid()
    assert f.cleaned_data["column_count"] == 3
    bad = TwoColumnElementForm(data={"column_count": "5"})
    assert not bad.is_valid()


def test_form_initializes_count_to_persisted_on_edit():
    inst = TwoColumnElement(
        data={
            "columns": [
                {"id": "c000001"},
                {"id": "c000002"},
                {"id": "c000003"},
            ]
        }
    )
    f = TwoColumnElementForm(instance=inst)
    assert f.fields["column_count"].initial == 3


def test_form_initializes_count_to_two_on_create():
    f = TwoColumnElementForm()
    assert f.fields["column_count"].initial == 2


def _add_two_column(course, unit, count):
    post = {"unit_token": unit.updated.isoformat(), "column_count": str(count)}
    # save_element(course, unit_pk, type_key, element_ref, post_data, files)
    builder_svc.save_element(course, unit.pk, "twocolumn", "new", post, {})
    return Element.objects.filter(unit=unit, parent__isnull=True).latest("pk")


@pytest.mark.django_db
def test_create_honors_initial_count():
    course, unit = make_course_with_unit()
    join = _add_two_column(course, unit, 4)
    assert len(join.content_object.data["columns"]) == 4


@pytest.mark.django_db
def test_shrink_moves_children_to_last_column():
    course, unit = make_course_with_unit()
    join = _add_two_column(course, unit, 4)
    col = join.content_object
    ids = [c["id"] for c in col.data["columns"]]
    # put a text child in column 3 and one in column 4
    c3 = Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=ids[2],
        content_object=TextElement.objects.create(body="C3"),
    )
    c4 = Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=ids[3],
        content_object=TextElement.objects.create(body="C4"),
    )
    # shrink 4 -> 2 (refresh: the earlier save_element call already bumped
    # unit.updated, and our local `unit` handle wasn't re-fetched since)
    unit.refresh_from_db()
    post = {"unit_token": unit.updated.isoformat(), "column_count": "2"}
    builder_svc.save_element(course, unit.pk, "twocolumn", str(join.pk), post, {})
    col.refresh_from_db()
    c3.refresh_from_db()
    c4.refresh_from_db()
    new_ids = [c["id"] for c in col.data["columns"]]
    assert len(new_ids) == 2
    last = new_ids[-1]
    assert c3.tab_id == last and c4.tab_id == last  # moved, not deleted
    assert TextElement.objects.filter(body="C3").exists()
    assert TextElement.objects.filter(body="C4").exists()
    # deterministic drain order: column 3's child before column 4's
    merged = list(
        Element.objects.filter(parent=join, tab_id=last).order_by("order", "pk")
    )
    assert [m.pk for m in merged] == [c3.pk, c4.pk]


@pytest.mark.django_db
def test_grow_keeps_existing_children():
    course, unit = make_course_with_unit()
    join = _add_two_column(course, unit, 2)
    col = join.content_object
    first_id = col.data["columns"][0]["id"]
    child = Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=first_id,
        content_object=TextElement.objects.create(body="X"),
    )
    # refresh: the earlier save_element call already bumped unit.updated, and
    # our local `unit` handle wasn't re-fetched since
    unit.refresh_from_db()
    post = {"unit_token": unit.updated.isoformat(), "column_count": "4"}
    builder_svc.save_element(course, unit.pk, "twocolumn", str(join.pk), post, {})
    col.refresh_from_db()
    child.refresh_from_db()
    assert len(col.data["columns"]) == 4
    assert col.data["columns"][0]["id"] == first_id  # existing id stable
    assert child.tab_id == first_id  # child untouched


@pytest.mark.django_db
def test_element_add_twocolumn_renders_edit_partial(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "twocolumn", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200  # guards missing _edit_twocolumn.html
    assert 'name="column_count"' in resp.content.decode()
    assert Element.objects.filter(unit=unit).count() == 0  # add is render-only


@pytest.mark.django_db
def test_save_twocolumn_creates_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "twocolumn",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "column_count": "3",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit, parent__isnull=True)
    assert isinstance(el.content_object, TwoColumnElement)
    assert len(el.content_object.data["columns"]) == 3
