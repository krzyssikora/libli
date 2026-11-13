"""Imported images get their derivatives generated automatically, after the
import commits, off the request thread -- so the author never sees an operator
instruction (`backfill_media_derivatives ...`) they cannot act on."""

import io
import logging

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from courses import derivatives_background
from courses.media import create_asset
from courses.models import ContentNode
from courses.models import Course
from courses.models import DerivativesState
from courses.models import Element as JoinElement
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.transfer.export import write_archive
from tests.factories import TEST_PASSWORD


@pytest.fixture(autouse=True)
def _staging_tmp(settings, tmp_path):
    settings.TRANSFER_STAGING_DIR = tmp_path / "staging"


@pytest.fixture
def inline_spawn(monkeypatch):
    """Run the background job on the test thread: a real thread would open its
    own DB connection, which cannot see this test's uncommitted rows."""
    calls = []

    def _spawn(target, args):
        calls.append(args)
        target(*args)

    monkeypatch.setattr(derivatives_background, "_spawn", _spawn)
    monkeypatch.setattr(derivatives_background, "_close_connection", lambda: None)
    return calls


def _png(size=(2000, 1500)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return SimpleUploadedFile("pic.png", buf.getvalue(), content_type="image/png")


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user("owner", password=TEST_PASSWORD)
    user.user_permissions.add(
        Permission.objects.get(codename="add_course", content_type__app_label="courses")
    )
    return user


def _archive_with_image(owner):
    src = Course.objects.create(title="Src", slug="src", owner=owner)
    unit = ContentNode.objects.create(
        course=src, kind="unit", title="U", unit_type="lesson"
    )
    asset = create_asset(src, "image", _png(), owner)
    JoinElement.objects.create(
        unit=unit, title="", content_object=ImageElement.objects.create(media=asset)
    )
    buf = io.BytesIO()
    write_archive(src, None, buf)
    return src, buf.getvalue()


def _import(client, content):
    upload = SimpleUploadedFile("x.zip", content, content_type="application/zip")
    preview = client.post(reverse("courses:manage_course_import"), {"archive": upload})
    assert preview.status_code == 200
    return client.post(
        reverse("courses:manage_course_import_confirm"),
        {"token": preview.context["token"]},
        follow=True,
    )


def test_course_import_generates_derivatives_after_commit(
    client,
    owner,
    course_with_image_media_root,
    inline_spawn,
    django_capture_on_commit_callbacks,
):
    src, content = _archive_with_image(owner)
    client.force_login(owner)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        resp = _import(client, content)
    assert callbacks, "generation must be deferred to on_commit"
    imported = MediaAsset.objects.exclude(course=src).get()
    assert imported.derivatives_state == DerivativesState.OK
    assert imported.thumb.name and imported.web.name
    text = " ".join(str(m) for m in resp.context["messages"])
    assert "backfill" not in text


def test_nothing_is_generated_before_the_import_commits(
    client, owner, course_with_image_media_root, inline_spawn
):
    """Without on_commit firing (the transaction never commits in a plain
    django_db test), no job may start: a thread started inside the request
    would race the import's own transaction."""
    src, content = _archive_with_image(owner)
    client.force_login(owner)
    _import(client, content)
    assert inline_spawn == []
    imported = MediaAsset.objects.exclude(course=src).get()
    assert imported.derivatives_state == ""


def test_subtree_import_generates_derivatives(
    client,
    owner,
    course_with_image_media_root,
    inline_spawn,
    django_capture_on_commit_callbacks,
):
    src = Course.objects.create(title="Src", slug="src", owner=owner)
    chapter = ContentNode.objects.create(course=src, kind="chapter", title="Ch")
    unit = ContentNode.objects.create(
        course=src, parent=chapter, kind="unit", title="U", unit_type="lesson"
    )
    asset = create_asset(src, "image", _png(), owner)
    JoinElement.objects.create(
        unit=unit, title="", content_object=ImageElement.objects.create(media=asset)
    )
    buf = io.BytesIO()
    write_archive(src, chapter, buf)
    target = Course.objects.create(title="T", slug="t", owner=owner)
    client.force_login(owner)
    upload = SimpleUploadedFile("x.zip", buf.getvalue(), content_type="application/zip")
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": upload},
    )
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("courses:manage_import_content_confirm", args=[target.slug]),
            {"token": preview.context["token"], "insertion": ""},
            follow=True,
        )
    imported = MediaAsset.objects.get(course=target)
    assert imported.derivatives_state == DerivativesState.OK
    text = " ".join(str(m) for m in resp.context["messages"])
    assert "backfill" not in text


def test_text_only_import_starts_no_job(
    client, owner, inline_spawn, django_capture_on_commit_callbacks
):
    src = Course.objects.create(title="Src", slug="src", owner=owner)
    ContentNode.objects.create(course=src, kind="unit", title="U", unit_type="lesson")
    buf = io.BytesIO()
    write_archive(src, None, buf)
    client.force_login(owner)
    with django_capture_on_commit_callbacks(execute=True):
        _import(client, buf.getvalue())
    assert inline_spawn == []


def test_job_only_touches_never_attempted_images_of_the_course(
    course_with_image_media_root, owner, inline_spawn
):
    course = Course.objects.create(title="C", slug="c", owner=owner)
    other = Course.objects.create(title="O", slug="o", owner=owner)
    pending = create_asset(course, "image", _png(), owner, generate=False)
    failed = create_asset(course, "image", _png(), owner, generate=False)
    failed.derivatives_state = DerivativesState.FAILED
    failed.save(update_fields=["derivatives_state"])
    elsewhere = create_asset(other, "image", _png(), owner, generate=False)

    derivatives_background.run_for_course(course.pk)

    for a in (pending, failed, elsewhere):
        a.refresh_from_db()
    assert pending.derivatives_state == DerivativesState.OK
    assert failed.derivatives_state == DerivativesState.FAILED  # not retried here
    assert elsewhere.derivatives_state == ""


def test_worker_logs_and_closes_connection_on_error(monkeypatch, caplog):
    closed = []
    monkeypatch.setattr(
        derivatives_background, "_close_connection", lambda: closed.append(1)
    )

    def boom(course_pk):
        raise RuntimeError("disk full")

    monkeypatch.setattr(derivatives_background, "run_for_course", boom)
    with caplog.at_level(logging.ERROR, logger="courses.derivatives_background"):
        derivatives_background._worker(42)  # must not raise
    assert closed == [1]
    assert "42" in caplog.text
