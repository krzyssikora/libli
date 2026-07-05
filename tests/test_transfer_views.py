import io
import zipfile

import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Course
from tests.factories import TEST_PASSWORD  # reuse existing user factory if present

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user("owner", password=TEST_PASSWORD)


@pytest.fixture
def outsider(django_user_model):
    return django_user_model.objects.create_user("outsider", password=TEST_PASSWORD)


@pytest.fixture
def course(owner):
    c = Course.objects.create(title="Src", slug="src", owner=owner)
    ContentNode.objects.create(course=c, kind="unit", title="U", unit_type="lesson")
    return c


def test_export_course_streams_zip(client, owner, course):
    client.force_login(owner)
    resp = client.get(reverse("courses:manage_course_export", args=[course.slug]))
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment;")
    assert "src-export-" in resp["Content-Disposition"]
    body = b"".join(resp.streaming_content)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert {"manifest.json", "course.json"} <= set(zf.namelist())


def test_export_requires_edit_rights(client, outsider, course):
    client.force_login(outsider)
    resp = client.get(reverse("courses:manage_course_export", args=[course.slug]))
    assert resp.status_code == 403


def test_subtree_export_scoped_to_url_course(client, owner, course):
    other = Course.objects.create(title="Other", slug="other", owner=owner)
    foreign = ContentNode.objects.create(
        course=other, kind="unit", title="X", unit_type="lesson"
    )
    client.force_login(owner)
    resp = client.get(
        reverse("courses:manage_node_export", args=[course.slug, foreign.pk])
    )
    assert resp.status_code == 404  # forged cross-course node id → 404, no archive


def test_subtree_export_ok(client, owner, course):
    node = course.nodes.first()
    client.force_login(owner)
    resp = client.get(
        reverse("courses:manage_node_export", args=[course.slug, node.pk])
    )
    assert resp.status_code == 200
