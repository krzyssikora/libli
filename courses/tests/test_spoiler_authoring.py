import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SpoilerElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_form_renders_spoiler_edit_partial(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "spoiler", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="label"' in html
    assert 'name="body"' in html
    assert Element.objects.filter(unit=unit).count() == 0


def test_save_round_trips_label_and_body(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "spoiler",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "label": "Show solution",
            "body": "<p>the answer</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, SpoilerElement)
    assert el.content_object.label == "Show solution"
    assert "<p>the answer</p>" in el.content_object.body


def test_save_allows_blank_label(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "spoiler",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "label": "",
            "body": "",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert el.content_object.label == ""
