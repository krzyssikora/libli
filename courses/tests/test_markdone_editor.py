import pytest
from django.urls import reverse

from courses.models import Element
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_element_add_markdone_renders_200(client):
    course, unit = make_course_with_unit(owner=make_login(client, "owner"))
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "markdone", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "data-markdone-editor" in html
    assert Element.objects.filter(unit=unit).count() == 0  # render-only, nothing saved


def test_editor_html_includes_markdone_scripts(client):
    course, unit = make_course_with_unit(owner=make_login(client, "owner"))
    body = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    assert "courses/js/markdone.js" in body
    assert "courses/js/markdone_editor.js" in body
