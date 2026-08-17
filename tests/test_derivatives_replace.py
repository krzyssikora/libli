"""Service-level tests for `replace_asset` regenerating image derivatives.

These use `@pytest.mark.django_db(transaction=True)` rather than
`django_capture_on_commit_callbacks`: several assertions need the deferred
`_retire`/`_delete_file_if_unshared` on_commit callbacks to have actually run,
and with `transaction=True` the test itself runs outside the wrapping
transaction django_db normally provides, so `replace_asset`'s own
`@transaction.atomic` really commits and its on_commit callbacks fire
immediately when that atomic block exits.
"""

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.media import replace_asset
from tests.factories import CourseFactory
from tests.factories import make_image_asset


def _upload(size=(2400, 1800), name="new.png"):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "green").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.mark.django_db(transaction=True)
def test_replace_regenerates_and_deletes_the_superseded_files(
    course_with_image_media_root,
):
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_thumb, old_web = asset.thumb.name, asset.web.name

    replace_asset(asset, _upload())

    assert asset.thumb.name != old_thumb
    assert not default_storage.exists(old_thumb)
    assert not default_storage.exists(old_web)
    asset.refresh_from_db()
    assert asset.width == 2400, "the five new fields must survive update_fields"


@pytest.mark.django_db(transaction=True)
def test_replace_does_not_delete_when_the_name_is_reused(course_with_image_media_root):
    """Storage hands back the SAME name when the old file was already missing,
    in which case the 'old' file is the one just written. Mirrors the guard the
    module already applies to the original at courses/media.py:180-183.

    A genuine derivative-name collision needs the ORIGINAL's name to be reused
    too: `generate_derivatives` derives the stem from `asset.file.name`, so if
    only the old thumb bytes are missing while the old original is still on
    disk, the replacement original gets a storage-suffixed name (e.g.
    "old_XYZ.png") and its regenerated thumb never collides with the old one
    at all -- that would make this test pass on a broken build for a reason
    that has nothing to do with the guard (a storage-naming symptom, not the
    invariant). Deleting the original bytes too forces the SAME stem, and
    hence the SAME candidate thumb name, to be reused.

    MUTANT: drop the `if asset.thumb.name != old_thumb_name:` comparison in
    `_retire`. Must go red.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    default_storage.delete(asset.thumb.name)  # make the old derivative absent
    default_storage.delete(asset.file.name)  # force the ORIGINAL name to be reused

    replace_asset(asset, _upload(name="old.png"))

    assert asset.thumb.name
    assert default_storage.exists(asset.thumb.name), (
        "the file written by this call must not be deleted as if it were the old one"
    )


@pytest.mark.django_db(transaction=True)
def test_a_raise_at_the_persist_step_leaves_no_new_bytes(
    course_with_image_media_root, monkeypatch
):
    """The only real raiser inside the try is step 5's save -- a DB write this
    change INTRODUCES; today's replace_asset has no DB write after step 3. When
    it raises, atomic() rolls the row back to the old file, but the NEW
    original's bytes were written at step 3 and nothing references them.

    The new original's delete goes through _delete_file_if_unshared's logic with
    .exclude(pk=asset.pk) -- NOT delete_derivative_files, and not the plain
    helper, which would be a guaranteed no-op: it defers via on_commit (never
    runs on a rolling-back transaction) and early-returns because
    filter(file=name).exists() sees the row's own uncommitted write.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_file = asset.file.name

    from django.db.models import Model

    real_save = Model.save

    def flaky(self, *a, **k):
        if (
            isinstance(self, type(asset))
            and k.get("update_fields")
            and "derivatives_state" in k["update_fields"]
        ):
            raise RuntimeError("boom")
        return real_save(self, *a, **k)

    monkeypatch.setattr(Model, "save", flaky)

    with pytest.raises(RuntimeError):
        replace_asset(asset, _upload())

    asset.refresh_from_db()
    assert asset.file.name == old_file
    orphans = [n for n in default_storage.listdir("courses/media")[1] if "new" in n]
    assert orphans == [], f"new original orphaned: {orphans}"


@pytest.mark.django_db(transaction=True)
def test_a_raise_before_generation_leaves_the_old_derivatives_intact(
    course_with_image_media_root,
):
    """replace_asset raises before step 4 on the empty-file path. At that point
    asset.thumb.name still holds the OLD, LIVE name -- a handler wrapping the
    whole body would destroy the surviving row's derivatives. The try must begin
    at step 4."""
    from django.core.exceptions import ValidationError

    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_thumb = asset.thumb.name

    with pytest.raises(ValidationError):
        replace_asset(asset, SimpleUploadedFile("empty.png", b""))

    assert default_storage.exists(old_thumb)


@pytest.mark.django_db(transaction=True)
def test_replace_preserves_the_primary_key(course_with_image_media_root):
    """The entire point of replace_asset over delete-and-recreate: the pk must
    survive so every element referencing it follows the swap.

    MUTANT: replace_asset creating a new MediaAsset instead of mutating in
    place. Must go red.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_pk = asset.pk

    replace_asset(asset, _upload())

    assert asset.pk == old_pk
    from courses.models import MediaAsset

    assert MediaAsset.objects.filter(pk=old_pk).count() == 1
