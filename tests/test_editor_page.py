import pytest
from django.urls import reverse

from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.mark.django_db
def test_editor_renders_unit_with_elements(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, TextElement.objects.create(body="<p>Hello world</p>"))
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
    assert b'data-scope="preview"' in resp.content
    assert b"Hello world" in resp.content  # preview reuses 1a renderer


@pytest.mark.django_db
def test_editor_404_on_non_unit(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    part = ContentNodeFactory(course=course, parent=None, kind="part", unit_type=None)
    resp = client.get(_editor_url(course, part))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_editor_404_on_foreign_course_slug(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    other = CourseFactory()
    unit = ContentNodeFactory(
        course=other, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(
        reverse(
            "courses:manage_editor",
            kwargs={"slug": course.slug, "pk": unit.pk},
        )
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_editor_empty_unit_shows_empty_state(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
