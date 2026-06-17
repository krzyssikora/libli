import pytest
from django.core.exceptions import ValidationError

from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import VideoElement
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_mediaasset_str_and_scope():
    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x/a.png",
        original_filename="a.png",
    )
    assert asset.course_id == course.id
    assert asset.kind == "image"
    assert course.media_assets.count() == 1


@pytest.mark.django_db
def test_imageelement_requires_media_via_protect():
    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x/a.png",
        original_filename="a.png",
    )
    # No Element join-row here — an orphan concrete element is a test artifact (it
    # exercises the FK PROTECT in isolation), not a supported runtime state (create-on-
    # first-save always pairs a concrete element with its join-row).
    ImageElement.objects.create(media=asset, alt="diagram")
    # PROTECT: an asset referenced by an element cannot be deleted.
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        asset.delete()


@pytest.mark.django_db
def test_videoelement_xor_url_or_media():
    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="video",
        file="courses/media/x/v.mp4",
        original_filename="v.mp4",
    )
    # both set -> invalid
    v = VideoElement(url="https://www.youtube.com/embed/x", media=asset)
    with pytest.raises(ValidationError):
        v.clean()
    # neither set -> invalid
    with pytest.raises(ValidationError):
        VideoElement().clean()
    # exactly one -> valid
    VideoElement(media=asset).clean()
    VideoElement(url="https://www.youtube.com/embed/x").clean()


@pytest.mark.django_db
def test_display_name_falls_back_to_filename():
    from tests.factories import CourseFactory
    from courses.models import MediaAsset

    course = CourseFactory()
    a = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png",
        original_filename="x.png", name="",
    )
    assert a.display_name == "x.png"
    assert str(a) == "Image: x.png"
    a.name = "Cover"
    assert a.display_name == "Cover"
    assert str(a) == "Image: Cover"
