import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db
OK = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.jpg"  # a .jpg PATH, deliberately


@pytest.fixture(autouse=True)
def _isolated_media(tmp_path, settings):
    """Redirect MEDIA_ROOT per test: create_asset writes real files to storage, and
    without this every test in this module writes into the working tree's media/."""
    settings.MEDIA_ROOT = str(tmp_path)


def run(monkeypatch, **kw):
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(**kw))
    return media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "ctype,fragment",
    [
        ("text/html", "did not return an image"),  # the commons.wikimedia.org case
        ("", "did not return an image"),  # header present but EMPTY
        ("image/svg+xml", "image type is not allowed"),  # honest message, not the above
    ],
)
def test_content_type_gate(monkeypatch, ctype, fragment):
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, data=b"<html>nope</html>", headers={"Content-Type": ctype})
    assert fragment in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_absent_content_type_header_is_rejected(monkeypatch):
    """The header MISSING ENTIRELY, distinct from the empty-string case above -- the
    spec requires both, and an implementer could plausibly treat absent as "unknown,
    let Pillow decide", which drops an enumerated message."""
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, data=b"<html>nope</html>", headers={})
    assert "did not return an image" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "ctype", ["image/png", "image/PNG", "image/png; charset=binary"]
)
def test_content_type_accepted_forms(monkeypatch, ctype):
    assert run(monkeypatch, data=png_bytes(), headers={"Content-Type": ctype})


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_nonstandard_image_jpg_media_type_is_accepted(monkeypatch):
    """image/jpg is non-standard but widely emitted. Both documents justify the map
    entry explicitly, and without this test it could be deleted with nothing going
    RED."""
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="JPEG")
    assert run(monkeypatch, data=buf.getvalue(), headers={"Content-Type": "image/jpg"})


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_cap_trips_mid_stream_when_content_length_lies(monkeypatch):
    """Assert the body was ABANDONED, not merely that the message appeared.

    A message-only assertion passes on the very mutant it is named for: with the cap
    check moved after the loop, the whole 11 MiB is still read and `total > max_bytes`
    raises the identical "too large". Counting read1 calls is what distinguishes
    "abandoned early" from "streamed it all, then complained".
    """
    cap = 5 * 1024 * 1024  # the effective ceiling
    big = png_bytes() + b"\0" * (6 * 1024 * 1024)  # comfortably over it

    class Counting(FakeResponse):
        def __init__(self):
            super().__init__(
                big,
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": "10",  # a lie, deliberately
                },
            )
            self.reads = 0

        def read1(self, n=-1):
            self.reads += 1
            return super().read1(n)

    resp = Counting()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: resp)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "too large" in "; ".join(exc.value.messages)
    # The loop reads ONE chunk past the cap, then stops. Reading the whole body would
    # take ~2x as many chunks.
    assert resp.reads <= (cap // media_fetch.CHUNK_BYTES) + 2


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_over_cap_content_length_rejects_before_reading_the_body(monkeypatch):
    """The early-exit half. Without this, deleting the whole Content-Length block from
    _read_capped breaks NO test -- the malformed and lying cases both pass without it.
    Assert zero read1 calls, which is the only thing that distinguishes "rejected early"
    from "rejected after streaming 6 MiB".
    """

    class NeverRead(FakeResponse):
        def __init__(self):
            super().__init__(
                b"",
                headers={
                    "Content-Type": "image/png",
                    "Content-Length": str(50 * 1024 * 1024),
                },
            )
            self.reads = 0

        def read1(self, n=-1):
            self.reads += 1
            raise AssertionError(
                "body must not be read when Content-Length is over cap"
            )

    resp = NeverRead()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: resp)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "too large" in "; ".join(exc.value.messages)
    assert resp.reads == 0


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize("cl", [None, "not-a-number", "-5"])
def test_malformed_content_length_is_ignored_not_rejected(monkeypatch, cl):
    headers = {"Content-Type": "image/png"}
    if cl is not None:
        headers["Content-Length"] = cl
    assert run(monkeypatch, data=png_bytes(), headers=headers)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_empty_body_is_rejected(monkeypatch):
    with pytest.raises(ValidationError) as exc:
        run(monkeypatch, data=b"", headers={"Content-Type": "image/png"})
    assert "empty" in "; ".join(exc.value.messages)
