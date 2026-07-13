import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGridElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_element_add_renders_edit_partial(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "switchgrid", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "data-switchgrid-editor" in html
    assert Element.objects.filter(unit=unit).count() == 0  # render-only, nothing saved


def test_save_creates_switchgrid_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    before = SwitchGridElement.objects.count()
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "switchgrid",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "prompt": "Fix",
            "line-0-stem": "3 {{choice}} 3 = 9",
            "line-0-c0-opt": ["+", "-", "x"],
            "line-0-c0-ans": "2",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code in (200, 302)
    assert SwitchGridElement.objects.count() == before + 1
    el = Element.objects.get(unit=unit)
    obj = el.content_object
    assert isinstance(obj, SwitchGridElement)


def test_editor_type_label_present():
    from courses.views_manage import _EDITOR_TYPE_LABELS

    assert "switchgrid" in _EDITOR_TYPE_LABELS


def test_element_label_present():
    from courses.templatetags.courses_manage_extras import _ELEMENT_LABELS

    assert "switchgridelement" in _ELEMENT_LABELS
