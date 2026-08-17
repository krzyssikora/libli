import pytest
from django.core.files.storage import default_storage

from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_video_asset


@pytest.mark.django_db(transaction=True)
def test_deleting_an_asset_removes_both_derivative_files(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500), derivatives=True)
    thumb, web = asset.thumb.name, asset.web.name
    assert default_storage.exists(thumb) and default_storage.exists(web)

    asset.delete()

    assert not default_storage.exists(thumb)
    assert not default_storage.exists(web)


@pytest.mark.django_db(transaction=True)
def test_deleting_a_video_does_not_raise(course_with_image_media_root):
    """Both derivative fields are blank for every video (232 in mat-pp).
    FileSystemStorage.delete("") raises ValueError, and storage.exists("") is
    truthy because it stats MEDIA_ROOT -- so an unguarded implementation breaks
    ordinary video deletion."""
    course = CourseFactory()
    asset = make_video_asset(course, "v.mp4")
    asset.delete()  # must not raise


@pytest.mark.django_db(transaction=True)
def test_two_rows_sharing_one_file_name_keep_their_own_derivatives(
    course_with_image_media_root,
):
    """Migration 0008 copied storage references verbatim, so two MediaAsset rows
    can share one file.name -- the hazard _delete_file_if_unshared guards.
    Derivatives are generated per row and never shared, so deleting one must
    leave the other's intact. Requires REAL BYTES in storage."""
    course = CourseFactory()
    a = make_image_asset(course, "shared.png", size=(2000, 1500), derivatives=True)
    b = make_image_asset(course, "other.png", size=(2000, 1500))
    b.file.name = a.file.name  # the 0008 shape
    b.save(update_fields=["file"])
    from courses.derivatives import generate_derivatives

    generate_derivatives(b)
    b.save(update_fields=["width", "height", "thumb", "web", "derivatives_state"])

    assert a.thumb.name != b.thumb.name
    a.delete()

    assert default_storage.exists(b.thumb.name)
    assert default_storage.exists(b.web.name)
