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


def test_job_only_touches_the_given_never_attempted_images(
    course_with_image_media_root, owner
):
    course = Course.objects.create(title="C", slug="c", owner=owner)
    pending = create_asset(course, "image", _png(), owner, generate=False)
    failed = create_asset(course, "image", _png(), owner, generate=False)
    failed.derivatives_state = DerivativesState.FAILED
    failed.save(update_fields=["derivatives_state"])
    not_listed = create_asset(course, "image", _png(), owner, generate=False)

    derivatives_background.run_for_assets([pending.pk, failed.pk])

    for a in (pending, failed, not_listed):
        a.refresh_from_db()
    assert pending.derivatives_state == DerivativesState.OK
    assert failed.derivatives_state == DerivativesState.FAILED  # not retried here
    assert not_listed.derivatives_state == ""


def test_subtree_import_leaves_older_blank_images_of_the_target_alone(
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
    legacy = create_asset(target, "image", _png(), owner, generate=False)
    client.force_login(owner)
    upload = SimpleUploadedFile("x.zip", buf.getvalue(), content_type="application/zip")
    preview = client.post(
        reverse("courses:manage_import_content", args=[target.slug]),
        {"archive": upload},
    )
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            reverse("courses:manage_import_content_confirm", args=[target.slug]),
            {"token": preview.context["token"], "insertion": ""},
        )
    legacy.refresh_from_db()
    assert legacy.derivatives_state == ""
    assert MediaAsset.objects.get(course=target, derivatives_state="ok")


def _stored(name):
    from django.core.files.storage import default_storage

    return bool(name) and default_storage.exists(name)


def test_a_concurrent_replace_is_not_overwritten_and_nothing_leaks(
    course_with_image_media_root, owner, monkeypatch
):
    """The job reads the row, then spends a while decoding. If replace_asset
    commits a new original meanwhile, the job's derivatives (of the OLD
    picture) must not land on the row, and its files must not be orphaned."""
    course = Course.objects.create(title="C", slug="c", owner=owner)
    asset = create_asset(course, "image", _png(), owner, generate=False)
    real = derivatives_background.generate_derivatives
    written = []

    def generate_then_replace(a):
        state = real(a)
        written.extend([a.thumb.name, a.web.name])
        MediaAsset.objects.filter(pk=a.pk).update(file="courses/media/new.png")
        return state

    monkeypatch.setattr(
        derivatives_background, "generate_derivatives", generate_then_replace
    )
    derivatives_background.run_for_assets([asset.pk])

    asset.refresh_from_db()
    assert asset.derivatives_state == ""
    assert asset.thumb.name in ("", None)
    assert all(written) and not any(_stored(n) for n in written)


def test_a_deleted_asset_is_skipped_cleanly_and_the_rest_still_run(
    course_with_image_media_root, owner, monkeypatch
):
    course = Course.objects.create(title="C", slug="c", owner=owner)
    doomed = create_asset(course, "image", _png(), owner, generate=False)
    survivor = create_asset(course, "image", _png(), owner, generate=False)
    real = derivatives_background.generate_derivatives
    written = []

    def generate_then_delete(a):
        state = real(a)
        if a.pk == doomed.pk:
            written.extend([a.thumb.name, a.web.name])
            MediaAsset.objects.filter(pk=a.pk).delete()
        return state

    monkeypatch.setattr(
        derivatives_background, "generate_derivatives", generate_then_delete
    )
    derivatives_background.run_for_assets([doomed.pk, survivor.pk])

    survivor.refresh_from_db()
    assert survivor.derivatives_state == DerivativesState.OK
    assert all(written) and not any(_stored(n) for n in written)


def test_one_failing_asset_does_not_stop_the_rest(
    course_with_image_media_root, owner, monkeypatch, caplog
):
    course = Course.objects.create(title="C", slug="c", owner=owner)
    first = create_asset(course, "image", _png(), owner, generate=False)
    second = create_asset(course, "image", _png(), owner, generate=False)
    real = derivatives_background._process

    def flaky(pk):
        if pk == first.pk:
            raise RuntimeError("disk full")
        real(pk)

    monkeypatch.setattr(derivatives_background, "_process", flaky)
    with caplog.at_level(logging.ERROR, logger="courses.derivatives_background"):
        derivatives_background.run_for_assets([first.pk, second.pk])
    second.refresh_from_db()
    assert second.derivatives_state == DerivativesState.OK
    assert str(first.pk) in caplog.text


def test_worker_closes_its_connection_even_on_error(monkeypatch):
    closed = []
    monkeypatch.setattr(
        derivatives_background, "_close_connection", lambda: closed.append(1)
    )

    def boom(pks):
        raise RuntimeError("boom")

    monkeypatch.setattr(derivatives_background, "run_for_assets", boom)
    with pytest.raises(RuntimeError):
        derivatives_background._worker([1])
    assert closed == [1]


@pytest.mark.django_db(transaction=True)
def test_real_thread_generates_on_its_own_connection(
    course_with_image_media_root, django_user_model
):
    """No monkeypatching: the job runs on a real thread with its own DB
    connection, which sees the committed row and is closed afterwards."""
    import threading

    user = django_user_model.objects.create_user("t", password=TEST_PASSWORD)
    course = Course.objects.create(title="C", slug="c", owner=user)
    asset = create_asset(course, "image", _png(), user, generate=False)
    before = set(threading.enumerate())
    derivatives_background.schedule_for_import({"media_pks": [asset.pk]})
    (thread,) = [
        t for t in threading.enumerate() if t not in before
    ]  # autocommit: on_commit ran immediately
    thread.join(60)
    assert not thread.is_alive()
    asset.refresh_from_db()
    assert asset.derivatives_state == DerivativesState.OK
