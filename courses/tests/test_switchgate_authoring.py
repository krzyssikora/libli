import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SwitchGateElement
from courses.switchgate import SENTINEL_TOKEN
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
        {"type": "switchgate", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="stem"' in html  # the RTE textarea rendered
    assert 'name="option"' in html
    assert 'name="answer"' in html
    assert Element.objects.filter(unit=unit).count() == 0  # render-only, nothing saved


def test_save_creates_switchgate_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "switchgate",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "stem": "pick {{choice}}",
            "option": ["a", "b"],
            "answer": "0",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    obj = el.content_object
    assert isinstance(obj, SwitchGateElement)
    assert obj.stem == f"pick {SENTINEL_TOKEN}"
    assert obj.options == ["a", "b"]
    assert obj.answer == 0


def test_editor_type_label_present():
    from courses.views_manage import _EDITOR_TYPE_LABELS

    assert "switchgate" in _EDITOR_TYPE_LABELS


def test_element_label_present():
    from courses.templatetags.courses_manage_extras import _ELEMENT_LABELS

    assert "switchgateelement" in _ELEMENT_LABELS
