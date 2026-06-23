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
def test_embed_iframes_send_origin_referrer():
    """Embed providers (notably YouTube) refuse framed playback with "Error 153 /
    embedder.identity.missing.referrer" when no Referer reaches them. Django's
    SecurityMiddleware defaults Referrer-Policy to "same-origin", which strips the
    Referer on the cross-origin embed request. Each embed iframe overrides that with
    referrerpolicy="strict-origin-when-cross-origin" so the player receives the
    page's origin."""
    from courses.models import IframeElement
    from courses.models import VideoElement

    video = VideoElement(url="https://www.youtube.com/embed/abc123")
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in video.render()
    iframe = IframeElement(url="https://www.geogebra.org/m/abc", title="g")
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in iframe.render()


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


@pytest.mark.django_db
def test_video_form_normalizes_schemeless_youtu_be():
    from courses.element_forms import VideoElementForm

    form = VideoElementForm(data={"url": "youtu.be/lk5_OSsawz4"})
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.youtube.com/embed/lk5_OSsawz4"


@pytest.mark.django_db
def test_video_form_normalizes_watch_url():
    from courses.element_forms import VideoElementForm

    form = VideoElementForm(
        data={"url": "https://www.youtube.com/watch?v=lk5_OSsawz4&t=90"}
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.youtube.com/embed/lk5_OSsawz4?start=90"


@pytest.mark.django_db
def test_video_form_rejects_playlist_with_url_error_only():
    from courses.element_forms import VideoElementForm

    form = VideoElementForm(data={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert not form.is_valid()
    assert "url" in form.errors
    # _post_clean short-circuits on the url error, so the url/media XOR never adds a
    # spurious non-field message — the author sees only the precise url error.
    assert "__all__" not in form.errors


@pytest.mark.django_db
def test_video_form_rejected_paste_survives_rerender():
    from courses.element_forms import VideoElementForm

    raw = "https://www.youtube.com/playlist?list=PL1"
    form = VideoElementForm(data={"url": raw})
    assert not form.is_valid()
    assert form["url"].value() == raw


@pytest.mark.django_db
def test_video_form_empty_url_plus_media_is_valid():
    from courses.element_forms import VideoElementForm
    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="video",
        file="courses/media/x/v.mp4",
        original_filename="v.mp4",
    )
    form = VideoElementForm(data={"url": "", "media": str(asset.pk)}, course=course)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_video_form_valid_url_plus_media_trips_xor():
    from courses.element_forms import VideoElementForm
    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course,
        kind="video",
        file="courses/media/x/v.mp4",
        original_filename="v.mp4",
    )
    form = VideoElementForm(
        data={"url": "youtu.be/lk5_OSsawz4", "media": str(asset.pk)}, course=course
    )
    assert not form.is_valid()
    assert "__all__" in form.errors  # non-field XOR error


@pytest.mark.django_db
def test_video_form_rejects_non_allowlisted_passthrough():
    from courses.element_forms import VideoElementForm

    # A non-YouTube/Vimeo host passes through canonicalize_video_url unchanged
    # (no clean_url error), then validate_embed_url (run once, via _post_clean's
    # full_clean()) rejects it. That surfaces as a NON-FIELD (__all__) error, not a
    # url field error — the same behavior the model has always had off the allow-list.
    form = VideoElementForm(data={"url": "https://evil.example.com/x"})
    assert not form.is_valid()
    assert "__all__" in form.errors
    assert "url" not in form.errors


@pytest.mark.django_db
def test_video_form_normalizes_nocookie_end_to_end():
    from courses.element_forms import VideoElementForm

    # A recognized-but-not-allow-listed input host (youtube-nocookie.com) must
    # rewrite to www.youtube.com BEFORE the allow-list sees it, so the full form
    # path (canonicalize → _post_clean allow-list) accepts and saves the embed URL.
    form = VideoElementForm(
        data={"url": "https://www.youtube-nocookie.com/embed/lk5_OSsawz4"}
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.url == "https://www.youtube.com/embed/lk5_OSsawz4"


@pytest.mark.django_db
def test_edit_video_template_uses_text_input_and_help():
    from django.template.loader import render_to_string

    from courses.element_forms import VideoElementForm

    html = render_to_string(
        "courses/manage/editor/_edit_video.html",
        {"form": VideoElementForm()},
    )
    # the URL input must be free-text so the browser doesn't block scheme-less paste
    assert 'name="url"' in html
    assert 'type="text"' in html
    assert 'type="url"' not in html
    # author-facing guidance is present
    assert "Share button" in html
