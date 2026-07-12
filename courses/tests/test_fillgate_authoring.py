import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import FillGateElement
from courses.templatetags.courses_manage_extras import element_summary
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
        {"type": "fillgate", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'name="stem"' in resp.content  # the RTE textarea rendered
    assert Element.objects.filter(unit=unit).count() == 0  # render-only, nothing saved


def test_element_summary_fillgate():
    stem = "Cap of France is ￿0￿"
    el = FillGateElement.objects.create(stem=stem, answers=[["Paris"]])
    # summary falls through to the stem branch, rendering ￿0￿ as ___
    assert "Cap of France is ___" in element_summary(el)
