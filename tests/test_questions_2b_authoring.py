import pytest
from django.urls import reverse

from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _base(unit, type_key, element="new"):
    return {
        "ctx": "editor",
        "type": type_key,
        "element": element,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "explanation": "",
    }


@pytest.mark.django_db
def test_add_card_is_render_only_for_each_type(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    for key in ("shorttextquestion", "shortnumericquestion", "fillblankquestion"):
        resp = client.post(
            reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
            {"type": key, "unit": unit.pk},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        assert resp.status_code == 200
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_save_shorttext(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "shorttextquestion")
    data.update(stem="<p>Capital?</p>", accepted="Paris\nParyż")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ShortTextQuestionElement.objects.get()
    assert q.accepted == "Paris\nParyż"
    assert Element.objects.filter(unit=unit, object_id=q.pk).count() == 1


@pytest.mark.django_db
def test_save_shortnumeric_comma_decimal(client):
    from decimal import Decimal

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "shortnumericquestion")
    data.update(stem="<p>Pi?</p>", value="3,14", tolerance="0,01")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ShortNumericQuestionElement.objects.get()
    assert q.value == Decimal("3.14") and q.tolerance == Decimal("0.01")


@pytest.mark.django_db
def test_save_fillblank_creates_blanks_and_rebuilds_on_edit(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "fillblankquestion")
    data["stem"] = "<p>{{Paris}} on the {{Seine|seine}}.</p>"
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = FillBlankQuestionElement.objects.get()
    assert [b.accepted for b in q.blanks.all()] == ["Paris", "Seine\nseine"]
    assert [b.order for b in q.blanks.all()] == [0, 1]
    el = Element.objects.get(unit=unit, object_id=q.pk)

    # Edit: a new single-blank stem fully replaces the old blanks.
    unit.refresh_from_db()
    edit = _base(unit, "fillblankquestion", element=str(el.pk))
    edit["stem"] = "<p>Just {{one}}.</p>"
    resp2 = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        edit,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp2.status_code == 200
    q.refresh_from_db()
    assert [b.accepted for b in q.blanks.all()] == ["one"]
    assert Blank.objects.filter(question=q).count() == 1  # old blanks gone


@pytest.mark.django_db
def test_save_fillblank_invalid_returns_422_and_persists_nothing(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    data = _base(unit, "fillblankquestion")
    data["stem"] = "<p>no markers</p>"
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert FillBlankQuestionElement.objects.count() == 0
    assert Blank.objects.count() == 0
