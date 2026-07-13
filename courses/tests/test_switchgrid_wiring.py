import pytest
from django.contrib.contenttypes.models import ContentType
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


def test_editor_loads_switchgrid_scripts(client):
    pa = make_pa(client, "switchgrid-wiring-pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"courses/js/switchgrid.js" in resp.content
    assert b"courses/js/switchgrid_editor.js" in resp.content


def test_lesson_page_loads_switchgrid_js_when_grid_present(client):
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    course = CourseFactory()
    unit = _lesson_unit(course)
    grid = SwitchGridElement.objects.create(
        prompt="Fix operators",
        lines=[{"stem": "intro static", "cyclers": []}],
    )
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(SwitchGridElement),
        object_id=grid.pk,
    )
    user = make_login(client, "switchgrid-wiring-student")
    EnrollmentFactory(student=user, course=course)
    resp = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert resp.status_code == 200
    assert b"courses/js/switchgrid.js" in resp.content
