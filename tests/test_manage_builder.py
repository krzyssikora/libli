import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_builder_requires_manage_access(client):
    make_login(client, "stranger")
    CourseFactory(slug="c1")
    assert (
        client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"})).status_code
        == 403
    )


@pytest.mark.django_db
def test_builder_renders_tree_with_scope_and_token(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, title="Foundations"
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        title="Integers",
    )
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="top"' in body
    assert "Foundations" in body and "Integers" in body
    assert "data-updated=" in body


@pytest.mark.django_db
def test_empty_course_shows_empty_state(client):
    owner = make_login(client, "owner")
    CourseFactory(slug="c1", owner=owner)
    resp = client.get(reverse("courses:manage_builder", kwargs={"slug": "c1"}))
    assert (
        b"add your first" in resp.content.lower()
        or b"first node" in resp.content.lower()
    )


@pytest.mark.django_db
def test_node_panel_for_unit_shows_settings(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="Integers"
    )
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "c1", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"Integers" in resp.content
    assert b"obligatory" in resp.content.lower()


@pytest.mark.django_db
def test_node_panel_idor_404_before_403(client):
    owner = make_login(client, "owner")
    CourseFactory(slug="a", owner=owner)  # course A exists; its slug is used below
    course_b = CourseFactory(slug="b", owner=owner)
    unit_b = ContentNodeFactory(course=course_b, kind="unit", unit_type="lesson")
    # pair course A's slug with course B's node pk -> 404 (not 403)
    resp = client.get(
        reverse("courses:manage_node_panel", kwargs={"slug": "a", "pk": unit_b.pk})
    )
    assert resp.status_code == 404
