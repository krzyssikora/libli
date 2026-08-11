"""Service-level tests for replacing a MediaAsset's file in place.

Every test that asserts on a file being deleted or kept builds the asset under
replacement with `make_image_asset` (real PNG bytes through storage). The bare
`MediaAssetFactory` writes a *name* with no bytes behind it, which would make
"the old file is gone" pass on a build where the deletion never ran at all.
Two tests deliberately use a byte-less row, and say so where they do.

`django_capture_on_commit_callbacks(execute=True)` wraps the `replace_asset`
CALL, not the assertion: the deletion is registered via `transaction.on_commit`
during the call, and those callbacks never fire under the plain `db` fixture.
"""

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from courses import media as media_svc
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_image_asset


def _png(name="new.png", size=(2, 2), color="red"):
    """An uncommitted upload with real PNG bytes.

    Uncommitted matters: `_validate_file` short-circuits on a committed
    FieldFile (courses/validators.py:91), so handing replace_asset an existing
    asset's `.file` would skip BOTH the extension and the size check.
    """
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_replace_preserves_identity_and_swaps_the_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="old.png", name="Cover art")
    asset.content_hash = "deadbeef"
    asset.save(update_fields=["content_hash"])
    element = ImageElement.objects.create(media=asset, alt="a")
    old_name = asset.file.name
    storage = asset.file.storage
    created_before = asset.created
    assert storage.exists(old_name)

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    fresh = MediaAsset.objects.get(pk=asset.pk)
    assert fresh.kind == "image"  # kind is never assigned
    assert fresh.name == "Cover art"  # a custom display name survives
    assert fresh.original_filename == "new.png"
    assert fresh.content_hash == ""  # stale hash cleared, never left wrong
    assert fresh.uploaded_by_id is None  # provenance untouched
    assert fresh.created == created_before
    assert fresh.file.name != old_name
    assert storage.exists(fresh.file.name)
    assert not storage.exists(old_name)  # superseded bytes reclaimed

    element.refresh_from_db()
    assert element.media_id == asset.pk  # the FK never moved


@pytest.mark.django_db
def test_replace_succeeds_when_uploaded_by_is_null(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """The LAL-import shape. A bare full_clean() would 422 the whole imported
    catalogue: uploaded_by is null=True WITHOUT blank=True, so clean_fields()
    raises "This field cannot be blank." on a NULL uploader."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="imported.png")
    assert asset.uploaded_by_id is None  # the condition under test

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    assert MediaAsset.objects.get(pk=asset.pk).original_filename == "new.png"


@pytest.mark.django_db
def test_a_row_sharing_the_old_filename_keeps_the_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """Shared names are reachable in real data: migration 0008 copied storage
    REFERENCES off ImageElement.image, so two elements pointing at one stored
    file produced two rows sharing a name. The decoy must be a literal file=
    row -- make_image_asset always saves through storage, which guarantees a
    UNIQUE name, so two rows sharing one are unconstructible that way."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="shared.png")
    old_name = asset.file.name
    storage = asset.file.storage
    decoy = MediaAssetFactory(course=course, kind="image", file=old_name)

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    assert storage.exists(old_name)  # the decoy still needs it
    assert MediaAsset.objects.get(pk=decoy.pk).file.name == old_name


@pytest.mark.django_db
def test_identical_storage_name_keeps_the_newly_written_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """When the old file is ALREADY missing, get_available_name hands back the
    same name -- so the "old" file IS the one just written. Deleting it would
    leave the row pointing at nothing. This is the second deliberate byte-less
    fixture: a row whose file is absent is the whole subject."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = MediaAssetFactory(
        course=course, kind="image", file="courses/media/same.png"
    )
    storage = asset.file.storage
    assert not storage.exists("courses/media/same.png")

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("same.png"))

    fresh = MediaAsset.objects.get(pk=asset.pk)
    assert fresh.file.name == "courses/media/same.png"
    assert storage.exists(fresh.file.name)  # NOT deleted by its own cleanup


@pytest.mark.django_db
def test_missing_old_file_does_not_raise(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="lost.png")
    old_name = asset.file.name
    asset.file.storage.delete(old_name)  # bytes lost after the row was made

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    assert MediaAsset.objects.get(pk=asset.pk).original_filename == "new.png"
