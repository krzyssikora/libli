import io

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
from courses.tests.test_media_fetch_transport import FakeResponse
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db
OK = ["upload.wikimedia.org"]


@pytest.fixture(autouse=True)
def _isolated_media(tmp_path, settings):
    """Redirect MEDIA_ROOT per test: create_asset writes real files to storage, and
    without this every test in this module writes into the working tree's media/."""
    settings.MEDIA_ROOT = str(tmp_path)


def img_bytes(fmt="PNG", size=(4, 4)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "green").save(buf, format=fmt)
    return buf.getvalue()


def run(monkeypatch, url, data, ctype):
    monkeypatch.setattr(
        media_fetch,
        "_open",
        lambda req, t: FakeResponse(data, headers={"Content-Type": ctype}),
    )
    return media_fetch.fetch_image_asset(CourseFactory(), url, UserFactory())


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "url,data_fmt,ctype,expected",
    [
        # EXACT equality, not "endswith" -- an endswith check would also pass for the
        # Foo.png.gif double-extension bug this rule exists to prevent.
        ("https://upload.wikimedia.org/Foo.png", "PNG", "image/png", "Foo.png"),
        ("https://upload.wikimedia.org/Foo.JPG", "JPEG", "image/jpeg", "Foo.jpg"),
        ("https://upload.wikimedia.org/Foo", "PNG", "image/png", "Foo.png"),
        ("https://upload.wikimedia.org/", "PNG", "image/png", "image.png"),
        # The sniffed format WINS over a lying header:
        ("https://upload.wikimedia.org/Foo.png", "GIF", "image/png", "Foo.gif"),
    ],
)
def test_filename(monkeypatch, url, data_fmt, ctype, expected):
    asset = run(monkeypatch, url, img_bytes(data_fmt), ctype)
    assert asset.original_filename == expected


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_stem_comes_from_the_final_hop(monkeypatch):
    """The other half of the spec's paired invariant (Task 5 asserts source_url).

    commons.wikimedia.org/wiki/Special:FilePath/Foo.jpg redirects to an
    upload.wikimedia.org path whose basename is the useful one; the submitted path's
    basename is "Special:FilePath". Deferred to THIS task because _derive_filename
    does not exist until now.
    """
    import urllib.error

    calls = []

    def fake_open(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                req.full_url,
                302,
                "r",
                {"Location": "https://upload.wikimedia.org/Real.png"},
                None,
            )
        return FakeResponse(img_bytes("PNG"), headers={"Content-Type": "image/png"})

    monkeypatch.setattr(media_fetch, "_open", fake_open)
    submitted = "https://upload.wikimedia.org/Special:FilePath"
    asset = media_fetch.fetch_image_asset(CourseFactory(), submitted, UserFactory())
    assert asset.source_url == submitted  # submitted url is STORED
    assert asset.original_filename == "Real.png"  # stem comes from the FINAL hop


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_narrowed_extensions_do_not_double_up(monkeypatch):
    """With the allowed set narrowed to ["jpeg"], a .jpg URL must store Foo.jpeg --
    never Foo.jpg.jpeg. This is what pins the trailing-extension strip to
    SAFE_IMAGE_EXTENSIONS rather than effective_image_extensions()."""
    monkeypatch.setattr(media_fetch, "effective_image_extensions", lambda: ["jpeg"])
    asset = run(
        monkeypatch,
        "https://upload.wikimedia.org/Foo.jpg",
        img_bytes("JPEG"),
        "image/jpeg",
    )
    assert asset.original_filename == "Foo.jpeg"


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_traversal_in_path_cannot_escape(monkeypatch):
    asset = run(
        monkeypatch,
        "https://upload.wikimedia.org/a/..%2F..%2Fx.png",
        img_bytes("PNG"),
        "image/png",
    )
    assert "/" not in asset.original_filename
    assert ".." not in asset.original_filename


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_html_under_an_image_content_type_is_rejected(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        run(
            monkeypatch,
            "https://upload.wikimedia.org/Foo.png",
            b"<html>not an image</html>",
            "image/png",
        )
    assert "usable image" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_unknown_pillow_format_is_a_422_not_a_keyerror(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        run(
            monkeypatch,
            "https://upload.wikimedia.org/Foo.png",
            img_bytes("BMP"),
            "image/png",
        )
    assert "image type is not allowed" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_pixel_bound_rejects_between_max_pixels_and_pillows_limit(monkeypatch):
    """Target the band THIS code owns: MAX_PIXELS (50M) < declared < 2x Pillow's
    89,478,485. Above 2x, Pillow refuses unaided and the test would pass on a build
    with no pixel check at all.

    NOTE this does NOT pin the check's ORDER relative to verify() -- a genuine 50x50
    PNG passes verify(), so moving the size check after it produces the identical
    error. See test_pixel_check_runs_before_verify for the ordering.
    """
    monkeypatch.setattr(media_fetch, "MAX_PIXELS", 100)
    with pytest.raises(ValidationError) as exc:
        run(
            monkeypatch,
            "https://upload.wikimedia.org/Foo.png",
            img_bytes("PNG", size=(50, 50)),
            "image/png",
        )
    assert "dimensions are too large" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_pixel_check_runs_before_verify(monkeypatch):
    """The ordering the spec argues for, with the fixture that actually pins it.

    A PNG whose IHDR declares huge dimensions over a TRUNCATED body: Image.open reads
    the header and reports the size, but PngImageFile.verify() walks the remaining
    chunks and checks CRCs, so it would reject this as "not a usable image". Only when
    the pixel check runs FIRST does it report the dimensions message.
    """
    good = img_bytes("PNG", size=(8, 8))
    # Rewrite IHDR width/height to 9000x9000, RECOMPUTE THE CHUNK CRC, then truncate.
    # Without the CRC recompute the chunk is corrupt and Image.open raises
    # UnidentifiedImageError -- the broad clause fires, the message is "not a usable
    # image", and this test is RED on a CORRECT build. MEASURED on Pillow 12.2:
    #   no CRC fix  -> UnidentifiedImageError
    #   CRC fixed   -> Image.open reports (9000, 9000); verify() raises OSError
    import struct
    import zlib

    ihdr = good.index(b"IHDR")
    d = bytearray(good)
    d[ihdr + 4 : ihdr + 12] = struct.pack(">II", 9000, 9000)
    d[ihdr + 17 : ihdr + 21] = struct.pack(
        ">I", zlib.crc32(bytes(d[ihdr : ihdr + 17])) & 0xFFFFFFFF
    )
    truncated = bytes(d[: ihdr + 40])

    monkeypatch.setattr(media_fetch, "MAX_PIXELS", 1000)
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png", truncated, "image/png")
    assert "dimensions are too large" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_truncated_png_is_rejected_by_the_broad_clause(monkeypatch):
    """What actually falsifies `except UnidentifiedImageError` only.

    MEASURED: HTML bytes raise precisely UnidentifiedImageError, so the narrowed
    clause catches them and test_html_under_an_image_content_type_is_rejected passes
    on that mutant. A truncated-but-valid PNG is the discriminator: Image.open
    SUCCEEDS and verify() raises OSError("Truncated File Read"), which only the broad
    clause converts -- the narrow one lets it escape as a 500.
    """
    good = img_bytes("PNG", size=(64, 64))
    truncated = good[: len(good) // 2]
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, "https://upload.wikimedia.org/Foo.png", truncated, "image/png")
    assert "usable image" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_decompression_bomb_reports_the_same_dimensions_message(monkeypatch):
    """The FAR side of the boundary. Above 2x Image.MAX_IMAGE_PIXELS, Pillow raises
    DecompressionBombError from Image.open -- BEFORE the explicit size check can run --
    so without the dedicated except clause it falls into the broad one and the author
    is told the file is "not a usable image", disagreeing with the smaller case.
    """
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 16)  # 2x -> 32 px
    with pytest.raises(ValidationError) as exc:
        run(
            monkeypatch,
            "https://upload.wikimedia.org/Foo.png",
            img_bytes("PNG", size=(50, 50)),
            "image/png",
        )
    assert "dimensions are too large" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_mpo_format_is_accepted_as_jpg(monkeypatch):
    """MPO is the NORMAL Pillow format for multi-picture JPEGs -- what most phone
    cameras produce. Omitting it from the map rejects a large share of real photos.

    Pillow will not save(format="MPO") from a plain Image.new, so build a two-frame
    JPEG (which Pillow opens as MPO) via append_images.
    """
    from PIL import Image

    buf = io.BytesIO()
    a = Image.new("RGB", (4, 4), "red")
    b = Image.new("RGB", (4, 4), "blue")
    # format="MPO", NOT "JPEG": Image.SAVE_ALL has no "JPEG" entry, so save_all with
    # format="JPEG" raises KeyError('JPEG') before the guard below runs. MEASURED.
    a.save(buf, format="MPO", save_all=True, append_images=[b])
    data = buf.getvalue()
    assert Image.open(io.BytesIO(data)).format == "MPO"  # guard the fixture itself

    asset = run(monkeypatch, "https://upload.wikimedia.org/Foo.jpg", data, "image/jpeg")
    assert asset.original_filename == "Foo.jpg"
