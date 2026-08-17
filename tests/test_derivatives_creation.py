"""create_asset / get_or_create_asset wiring: generation happens at asset
creation (courses/media.py, courses/lal_loader/media.py), not the importer's
bulk path (which opts out -- covered separately in
tests/test_transfer_import.py::test_a_failed_import_leaves_no_orphaned_files)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.media import create_asset
from courses.models import DerivativesState
from tests.factories import CourseFactory


def _png(size=(2000, 1500)):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return SimpleUploadedFile("up.png", buf.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_create_asset_populates_all_five_fields(
    course_with_image_media_root, admin_user
):
    """Catches: dropping the generate_derivatives() call from create_asset, and
    swallowing its returned state without persisting it (asserted via
    refresh_from_db, which only sees what update_fields actually wrote)."""
    course = CourseFactory()
    asset = create_asset(course, "image", _png(), admin_user)
    assert asset.width == 2000 and asset.height == 1500
    assert asset.thumb.name and asset.web.name
    assert asset.derivatives_state == DerivativesState.OK
    asset.refresh_from_db()
    assert asset.thumb.name, "update_fields must include the derivative fields"
    assert asset.derivatives_state == DerivativesState.OK


@pytest.mark.django_db
def test_generate_false_leaves_the_pending_state(
    course_with_image_media_root, admin_user
):
    """Catches: flipping the `generate` default to False (this test alone
    would not catch it -- see test_create_asset_populates_all_five_fields for
    the default-True path).

    width/height are None, not "" -- they are PositiveIntegerField(null=True),
    so a test written as 'all five stay ""' asserts the wrong thing for two.
    """
    course = CourseFactory()
    asset = create_asset(course, "image", _png(), admin_user, generate=False)
    assert asset.derivatives_state == ""
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert asset.width is None and asset.height is None


@pytest.mark.django_db
def test_lal_loader_generates_on_create_and_not_on_dedup(
    course_with_image_media_root, tmp_path
):
    """Catches: moving generation onto get_or_create_asset's get-branch too
    (the dedup return would then regenerate and overwrite the derivative
    names, which the second assertion below would still equal by luck unless
    we captured the name string, not just truthiness, before the second call).

    get_or_create_asset does NOT call create_asset -- it constructs
    MediaAsset(...) directly, so the `generate` keyword never reaches it.
    Generation goes before its existing asset.save(), which is a full save with
    no update_fields and therefore persists the new fields unchanged.

    The content_hash dedup early-return must NOT regenerate.
    """
    import io

    from PIL import Image

    from courses.lal_loader.media import get_or_create_asset

    course = CourseFactory()
    src = tmp_path / "d.png"
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), "blue").save(buf, "PNG")
    src.write_bytes(buf.getvalue())

    first = get_or_create_asset(course, "image", src)
    assert first.thumb.name
    assert first.derivatives_state == DerivativesState.OK
    first_thumb = first.thumb.name

    second = get_or_create_asset(course, "image", src)
    assert second.pk == first.pk
    assert second.thumb.name == first_thumb  # not regenerated
