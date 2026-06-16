import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import MathElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


@pytest.mark.django_db
def test_editor_reorder_returns_editor_fragments(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    a = add_element(unit, MathElement.objects.create(latex="a"))
    add_element(unit, MathElement.objects.create(latex="b"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_move", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": a.pk,
            "unit": unit.pk,
            "direction": "down",
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
    assert b'data-scope="preview"' in resp.content


@pytest.mark.django_db
def test_editor_delete_returns_editor_fragments(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    a = add_element(unit, MathElement.objects.create(latex="a"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": a.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'data-scope="preview"' in resp.content
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_editor_vanished_element_is_409_editor_fragment(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": 999999,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 409
    assert b'data-scope="editor"' in resp.content


@pytest.mark.django_db
def test_panel_path_still_works_unchanged(client):
    """The unit-panel (non-ctx) path is retained; it now returns the read-only
    summary."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    a = add_element(unit, MathElement.objects.create(latex="a"))
    add_element(unit, MathElement.objects.create(latex="b"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_move", kwargs={"slug": course.slug}),
        {
            "element": a.pk,
            "unit": unit.pk,
            "direction": "down",
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200  # _render_unit_panel path
