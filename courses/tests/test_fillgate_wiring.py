import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element
from courses.models import FillGateElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


@pytest.fixture
def enrolled_unit():
    course = CourseFactory()
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )


@pytest.fixture
def enrolled_client(client, enrolled_unit):
    user = make_login(client, "fillgate-wiring-student")
    EnrollmentFactory(student=user, course=enrolled_unit.course)
    return client


def test_editor_loads_fillgate_js(client):
    pa = make_pa(client, "fillgate-wiring-pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"courses/js/fillgate.js" in resp.content


def test_lesson_loads_fillgate_js_only_with_gate(enrolled_client, enrolled_unit):
    unit = enrolled_unit
    url = reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk])
    # No fill-gate yet -> not loaded
    assert b"courses/js/fillgate.js" not in enrolled_client.get(url).content
    # Add a fill-gate -> loaded
    el = FillGateElement.objects.create(stem="q ￿0￿", answers=[["a"]])
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    assert b"courses/js/fillgate.js" in enrolled_client.get(url).content
