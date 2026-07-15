import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_editor_loads_choicegrid_js(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c1", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"courses/js/choicegrid.js" in resp.content


@pytest.mark.django_db
def test_editor_loads_multigrid_js(client):
    owner = make_login(client, "owner2")
    course = CourseFactory(slug="c2", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c2", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"courses/js/multigrid.js" in resp.content
