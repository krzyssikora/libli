import io
import zipfile
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Course
from courses.transfer.export import write_archive
from tests.factories import TEST_PASSWORD  # reuse existing user factory if present

pytestmark = pytest.mark.django_db


# Task 12 view tests write real staged zips through courses.transfer.staging
# unless redirected — without this, they'd land in BASE_DIR/transfer_staging/.
@pytest.fixture(autouse=True)
def _staging_tmp(settings, tmp_path):
    settings.TRANSFER_STAGING_DIR = tmp_path / "staging"


def _add_course_perm(user):
    user.user_permissions.add(
        Permission.objects.get(codename="add_course", content_type__app_label="courses")
    )


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user("owner", password=TEST_PASSWORD)
    _add_course_perm(user)  # Task 12: full-import flow needs courses.add_course
    return user


@pytest.fixture
def outsider(django_user_model):
    return django_user_model.objects.create_user("outsider", password=TEST_PASSWORD)


@pytest.fixture
def course(owner):
    c = Course.objects.create(title="Src", slug="src", owner=owner)
    ContentNode.objects.create(course=c, kind="unit", title="U", unit_type="lesson")
    return c


# --- Task 12: import views (upload/preview/confirm/cancel) -------------------


def _zip_bytes(course, node=None):
    buf = io.BytesIO()
    write_archive(course, node, buf)
    return buf.getvalue()


def _upload(content, name="x.zip"):
    return SimpleUploadedFile(name, content, content_type="application/zip")


def _staged_files():
    d = Path(settings.TRANSFER_STAGING_DIR)
    if not d.exists():
        return []
    return list(d.iterdir())


def _make_other_owner():
    user = get_user_model().objects.create_user("other_owner", password=TEST_PASSWORD)
    _add_course_perm(user)
    return user


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


# --- Task 12: full-course import (upload -> preview -> confirm/cancel) -------


def test_full_import_happy_path(client, owner, course):
    client.force_login(owner)
    resp = client.post(
        reverse("courses:manage_course_import"),
        {"archive": _upload(_zip_bytes(course))},
    )
    assert resp.status_code == 200
    assert resp.context["preview"]["title"] == course.title
    assert resp.context["preview"]["node_count"] == 1
    token = resp.context["token"]

    confirm = client.post(
        reverse("courses:manage_course_import_confirm"), {"token": token}
    )
    assert confirm.status_code == 302
    new_course = Course.objects.exclude(pk=course.pk).get(title=course.title)
    assert new_course.owner == owner
    assert _staged_files() == []


def test_wrong_kind_full_import_shows_pointer_message(client, owner, course):
    node = course.nodes.first()
    client.force_login(owner)
    resp = client.post(
        reverse("courses:manage_course_import"),
        {"archive": _upload(_zip_bytes(course, node))},  # a subtree, not a course
    )
    assert resp.status_code == 422
    assert "Import content" in resp.content.decode()
    assert _staged_files() == []


def test_full_import_requires_add_course_permission(client, outsider):
    client.force_login(outsider)
    resp = client.get(reverse("courses:manage_course_import"))
    assert resp.status_code == 403


def test_confirm_with_garbage_token_shows_expired(client, owner):
    client.force_login(owner)
    resp = client.post(
        reverse("courses:manage_course_import_confirm"), {"token": "garbage-token"}
    )
    assert resp.status_code == 422
    assert "expired" in resp.content.decode().lower()


def test_confirm_replay_same_token_second_expired_exactly_one_course(
    client, owner, course
):
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_course_import"),
        {"archive": _upload(_zip_bytes(course))},
    )
    token = preview.context["token"]

    first = client.post(
        reverse("courses:manage_course_import_confirm"), {"token": token}
    )
    assert first.status_code == 302

    second = client.post(
        reverse("courses:manage_course_import_confirm"), {"token": token}
    )
    assert second.status_code == 422
    assert "expired" in second.content.decode().lower()
    assert Course.objects.filter(title=course.title).exclude(pk=course.pk).count() == 1


def test_confirm_with_another_users_token_expired(client, owner, course):
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_course_import"),
        {"archive": _upload(_zip_bytes(course))},
    )
    token = preview.context["token"]

    other_owner = _make_other_owner()
    other_client = Client()
    other_client.force_login(other_owner)
    intruding = other_client.post(
        reverse("courses:manage_course_import_confirm"), {"token": token}
    )
    assert intruding.status_code == 422
    assert "expired" in intruding.content.decode().lower()

    # the real owner's staged upload is untouched by the failed attempt
    real = client.post(
        reverse("courses:manage_course_import_confirm"), {"token": token}
    )
    assert real.status_code == 302
    assert Course.objects.filter(title=course.title).exclude(pk=course.pk).count() == 1


def test_cancel_deletes_staged_file(client, owner, course):
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_course_import"),
        {"archive": _upload(_zip_bytes(course))},
    )
    token = preview.context["token"]
    assert _staged_files() != []

    resp = client.post(reverse("courses:manage_course_import_cancel"), {"token": token})
    assert resp.status_code == 302
    assert _staged_files() == []


# --- Task 12: subtree import (upload -> preview -> confirm/cancel) ----------


def _chapter_subtree_zip():
    src = Course.objects.create(
        title="Chapter Src",
        slug="chapter-src-view",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    chapter = ContentNode.objects.create(
        course=src, kind="chapter", title="Root Chapter"
    )
    return _zip_bytes(src, chapter)


def test_subtree_confirm_top_level(client, owner):
    target = Course.objects.create(
        title="Target B",
        slug="target-b-view",
        owner=owner,
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": _upload(_chapter_subtree_zip())},
    )
    assert preview.status_code == 200
    token = preview.context["token"]

    confirm = client.post(
        reverse("courses:manage_import_content_confirm", args=[target.slug]),
        {"token": token, "insertion": ""},
    )
    assert confirm.status_code == 302
    assert ContentNode.objects.filter(
        course=target, parent=None, kind="chapter", title="Root Chapter"
    ).exists()
    assert _staged_files() == []


def test_subtree_confirm_under_chosen_parent(client, owner):
    # Default flags: full depth part > chapter > section > unit.
    target = Course.objects.create(title="Target C", slug="target-c-view", owner=owner)
    part = ContentNode.objects.create(course=target, kind="part", title="Existing Part")
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": _upload(_chapter_subtree_zip())},
    )
    assert preview.status_code == 200
    token = preview.context["token"]

    confirm = client.post(
        reverse("courses:manage_import_content_confirm", args=[target.slug]),
        {"token": token, "insertion": str(part.pk)},
    )
    assert confirm.status_code == 302
    assert ContentNode.objects.filter(
        course=target, parent=part, kind="chapter", title="Root Chapter"
    ).exists()
    assert _staged_files() == []


def test_wrong_kind_subtree_import_shows_pointer_message(client, owner, course):
    client.force_login(owner)
    resp = client.post(
        reverse("courses:manage_import_content", args=[course.slug]),
        {"archive": _upload(_zip_bytes(course))},  # a whole course, not a subtree
    )
    assert resp.status_code == 422
    assert "Import course" in resp.content.decode()
    assert _staged_files() == []


def test_subtree_import_requires_manage_rights(client, outsider, course):
    client.force_login(outsider)
    resp = client.get(reverse("courses:manage_import_content", args=[course.slug]))
    assert resp.status_code == 403


def test_subtree_structure_rejection_shows_preview_error_nothing_staged(client, owner):
    src = Course.objects.create(
        title="Part Src",
        slug="part-src-view",
        uses_parts=True,
        uses_chapters=True,
        uses_sections=True,
    )
    part = ContentNode.objects.create(course=src, kind="part", title="Lone Part")
    target = Course.objects.create(
        title="Chapters Only Target",
        slug="chapters-only-target-view",
        owner=owner,
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    client.force_login(owner)
    resp = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": _upload(_zip_bytes(src, part))},
    )
    assert resp.status_code == 422
    assert "part" in resp.content.decode().lower()
    assert _staged_files() == []


# --- Task 12: confirm-time re-validation guards ------------------------------


def test_confirm_after_insertion_node_deleted_returns_404(client, owner):
    target = Course.objects.create(title="Target D", slug="target-d-view", owner=owner)
    part = ContentNode.objects.create(course=target, kind="part", title="Doomed Part")
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": _upload(_chapter_subtree_zip())},
    )
    token = preview.context["token"]
    part_pk = part.pk
    part.delete()

    resp = client.post(
        reverse("courses:manage_import_content_confirm", args=[target.slug]),
        {"token": token, "insertion": str(part_pk)},
    )
    assert resp.status_code == 404
    assert not ContentNode.objects.filter(course=target, kind="chapter").exists()
    assert _staged_files() == []


def test_confirm_after_rights_revoked_returns_403(client, owner):
    target = Course.objects.create(title="Target E", slug="target-e-view", owner=owner)
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": _upload(_chapter_subtree_zip())},
    )
    token = preview.context["token"]

    target.owner = None
    target.save()

    resp = client.post(
        reverse("courses:manage_import_content_confirm", args=[target.slug]),
        {"token": token, "insertion": ""},
    )
    assert resp.status_code == 403
    assert not ContentNode.objects.filter(course=target, kind="chapter").exists()


def test_confirm_forged_cross_course_insertion_pk_returns_404(client, owner):
    target = Course.objects.create(title="Target F", slug="target-f-view", owner=owner)
    other_course = Course.objects.create(
        title="Other G", slug="other-g-view", owner=owner
    )
    foreign_node = ContentNode.objects.create(
        course=other_course, kind="part", title="Foreign Part"
    )
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": _upload(_chapter_subtree_zip())},
    )
    token = preview.context["token"]

    resp = client.post(
        reverse("courses:manage_import_content_confirm", args=[target.slug]),
        {"token": token, "insertion": str(foreign_node.pk)},
    )
    assert resp.status_code == 404
    assert not ContentNode.objects.filter(course=target, kind="chapter").exists()
    assert _staged_files() == []


def test_confirm_token_staged_for_course_a_at_course_b_confirm_url_expired(
    client, owner
):
    course_a = Course.objects.create(
        title="Course A", slug="course-a-view", owner=owner
    )
    course_b = Course.objects.create(
        title="Course B", slug="course-b-view", owner=owner
    )
    client.force_login(owner)
    preview = client.post(
        reverse("courses:manage_import_content", args=[course_a.slug]),
        {"archive": _upload(_chapter_subtree_zip())},
    )
    token = preview.context["token"]

    cross = client.post(
        reverse("courses:manage_import_content_confirm", args=[course_b.slug]),
        {"token": token, "insertion": ""},
    )
    assert cross.status_code == 422
    assert "expired" in cross.content.decode().lower()
    assert not ContentNode.objects.filter(course=course_b, kind="chapter").exists()

    # course A's staged upload is untouched by the mismatched attempt
    real = client.post(
        reverse("courses:manage_import_content_confirm", args=[course_a.slug]),
        {"token": token, "insertion": ""},
    )
    assert real.status_code == 302
    assert ContentNode.objects.filter(course=course_a, kind="chapter").exists()
