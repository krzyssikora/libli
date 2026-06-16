import pytest

from tests.factories import ContentNodeFactory


@pytest.mark.django_db
def test_textelement_sanitised_on_save():
    from courses.models import TextElement

    el = TextElement.objects.create(body="<p>hi</p><script>alert(1)</script>")
    assert "<script>" not in el.body
    assert "<p>hi</p>" in el.body


@pytest.mark.django_db
def test_element_render_dispatches_to_template_and_join_row():
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    text = TextElement.objects.create(body="<p>lesson body</p>")
    el = Element.objects.create(unit=unit, content_object=text)
    html = el.content_object.render()
    assert "lesson body" in html


@pytest.mark.django_db
def test_deleting_concrete_element_cascades_join_row():
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    text = TextElement.objects.create(body="<p>x</p>")
    Element.objects.create(unit=unit, content_object=text)
    assert Element.objects.count() == 1
    text.delete()
    assert Element.objects.count() == 0  # GenericRelation cascade


@pytest.mark.django_db
def test_textelement_strips_disallowed_url_scheme():
    from courses.models import TextElement

    el = TextElement.objects.create(
        body='<a href="ftp://x/y">f</a><a href="https://ok.example/">ok</a>'
    )
    assert "ftp://" not in el.body
    assert "https://ok.example/" in el.body


@pytest.mark.django_db
def test_video_xor_rejects_neither_and_both():
    from django.core.exceptions import ValidationError

    from courses.models import MediaAsset
    from courses.models import VideoElement
    from tests.factories import CourseFactory

    asset = MediaAsset.objects.create(
        course=CourseFactory(),
        kind="video",
        file="courses/media/x/v.mp4",
        original_filename="v.mp4",
    )
    neither = VideoElement()
    with pytest.raises(ValidationError):
        neither.clean()
    both = VideoElement(url="https://www.youtube.com/watch?v=x", media=asset)
    with pytest.raises(ValidationError):
        both.clean()


@pytest.mark.django_db
def test_embed_url_requires_https_and_whitelist():
    from django.core.exceptions import ValidationError

    from courses.models import IframeElement

    ok = IframeElement(url="https://www.geogebra.org/m/abc")
    ok.full_clean()  # allowed host
    sub = IframeElement(url="https://sub.geogebra.org/m/abc")
    sub.full_clean()  # subdomain allowed
    bad_scheme = IframeElement(url="http://www.geogebra.org/m/abc")
    with pytest.raises(ValidationError):
        bad_scheme.full_clean()
    bad_host = IframeElement(url="https://evil.example.com/m/abc")
    with pytest.raises(ValidationError):
        bad_host.full_clean()


def test_validate_image_size_rejects_oversize():
    from django.core.exceptions import ValidationError

    from courses.validators import MAX_IMAGE_BYTES
    from courses.validators import validate_image_size

    class _Big:
        size = MAX_IMAGE_BYTES + 1

    class _Ok:
        size = 10

    with pytest.raises(ValidationError):
        validate_image_size(_Big())
    validate_image_size(_Ok())  # must not raise


def test_validate_video_size_rejects_oversize():
    from django.core.exceptions import ValidationError

    from courses.validators import MAX_VIDEO_BYTES
    from courses.validators import validate_video_size

    class _Big:
        size = MAX_VIDEO_BYTES + 1

    with pytest.raises(ValidationError):
        validate_video_size(_Big())


@pytest.mark.django_db
def test_video_file_extension_allowlist():
    from django.core.exceptions import ValidationError
    from django.core.files.uploadedfile import SimpleUploadedFile

    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    course = CourseFactory()
    bad = MediaAsset(
        course=course,
        kind="video",
        file=SimpleUploadedFile("malware.exe", b"x"),
        original_filename="malware.exe",
    )
    with pytest.raises(ValidationError):
        # disallowed extension for a video asset
        bad.clean()
    good = MediaAsset(
        course=course,
        kind="video",
        file=SimpleUploadedFile("clip.mp4", b"x"),
        original_filename="clip.mp4",
    )
    good.clean()  # allowed extension, small file -> passes


@pytest.mark.django_db
def test_image_file_extension_allowlist():
    from io import BytesIO

    from django.core.exceptions import ValidationError
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    # Real 1x1 PNG: valid content + wrong extension proves the extension allowlist.
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    png_1x1 = buf.getvalue()

    bad_ext = MediaAsset(
        course=CourseFactory(),
        kind="image",
        file=SimpleUploadedFile("pic.txt", png_1x1),
        original_filename="pic.txt",
    )
    with pytest.raises(ValidationError):
        bad_ext.clean()
