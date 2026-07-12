import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import RevealGateElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_form_renders_revealgate_edit_partial(client):
    # Regression: the gate keeps the standard edit control, so _host_form.html
    # includes _edit_revealgate.html. A missing partial 500s (TemplateDoesNotExist)
    # the moment the author clicks "Show more" in the palette.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "revealgate", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="label"' in html  # the button-text field is rendered
    assert Element.objects.filter(unit=unit).count() == 0  # render-only, nothing saved


def test_save_round_trips_the_label(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "revealgate",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "label": "Reveal the proof",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, RevealGateElement)
    assert el.content_object.label == "Reveal the proof"


def test_save_allows_blank_label(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "revealgate",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "label": "",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert el.content_object.label == ""
