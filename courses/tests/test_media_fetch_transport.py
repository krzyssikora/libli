import io
import threading

import pytest
from django.test import override_settings

from courses import media_fetch
from courses.models import DerivativesState
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

OK = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.png"


@pytest.fixture(autouse=True)
def _isolated_media(tmp_path, settings):
    """Redirect MEDIA_ROOT per test: create_asset writes real files to storage, and
    without this every test in this module writes into the working tree's media/."""
    settings.MEDIA_ROOT = str(tmp_path)


def png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
    return buf.getvalue()


def big_png_bytes():
    """A source WIDER than THUMB_WIDTH, for the derivatives assertion only.

    generate_derivatives skips a target when `img.width <= target`
    (THUMB_WIDTH = 512, WEB_WIDTH = 896, courses/derivatives.py:145-146), and
    derivatives_state is `OK if written else SKIPPED`. MEASURED: a 4x4 source writes
    nothing -> SKIPPED with thumb == "", so asserting OK on png_bytes() would be RED
    on a CORRECT build. 600x600 gives src=2336 B, thumb webp=52 B -> OK.

    Kept separate rather than widening png_bytes(): Task 6's cap test appends 6 MiB to
    that fixture and does not need a bigger base.
    """
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (600, 600), "blue").save(buf, format="PNG")
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    """Stands in for an http.client.HTTPResponse.

    NOTE read1 is inherited from BytesIO and returns partial data, which is what the
    production loop calls. Do NOT replace this with a generator-based double: a
    generator yields instantly and would pass on a build that uses read() instead of
    read1(), which is the exact defect the drip tests exist to catch.
    """

    def __init__(self, data=b"", status=200, headers=None):
        super().__init__(data)
        self.status = status
        # `is None`, NOT `or`: an explicit headers={} is FALSY, so `headers or {...}`
        # would substitute the default and silently give a header-less response an
        # image/png Content-Type -- making the absent-header test RED on a correct
        # build. MEASURED.
        self.headers = {"Content-Type": "image/png"} if headers is None else headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_happy_path_creates_a_normal_asset(monkeypatch):
    data = big_png_bytes()  # NOT png_bytes(): 4x4 would skip both derivative targets
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(data))
    asset = media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert asset.kind == "image"
    assert asset.source_url == URL
    assert asset.content_hash  # populated
    assert asset.file.size == len(data)
    # The spec's "a normal MediaAsset with derivatives generated" -- without this a
    # mutant passing generate=False to create_asset is invisible, and the whole
    # "the asset pipeline needs no change" premise rests on derivatives running.
    assert asset.derivatives_state == DerivativesState.OK
    assert asset.thumb and asset.width


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_create_asset_runs_on_the_request_thread(monkeypatch):
    """The worker does steps 4-8 only; create_asset must NOT run on it.

    Asserting via a "django_db-visible write" would be an assertion that CANNOT
    FAIL: a background thread opens its own connection and really commits, so this
    connection sees the row anyway -- and that row survives the rollback and leaks
    into the next test. Record the thread instead.
    """
    seen = {}
    real = media_fetch.create_asset

    def spy(*a, **kw):
        seen["thread"] = threading.current_thread()
        return real(*a, **kw)

    monkeypatch.setattr(media_fetch, "create_asset", spy)
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(png_bytes()))
    media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert seen["thread"] is threading.current_thread()


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_a_padded_url_is_stored_stripped(monkeypatch):
    """The spec's weakest-natural-coverage invariant, called out twice there.

    validate_fetch_url RETURNS the stripped url and step 1 must ASSIGN it. Every other
    test in this suite passes an already-clean url, so the bare-call mutant -- dropping
    the assignment -- stays GREEN across the whole suite except here. T1 does NOT cover
    this: it tests the validator's return value, not that fetch_image_asset uses it.
    """
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(png_bytes()))
    asset = media_fetch.fetch_image_asset(
        CourseFactory(), "  " + URL + "\n", UserFactory()
    )
    assert asset.source_url == URL  # no leading/trailing whitespace


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_user_agent_and_accept_are_sent(monkeypatch):
    captured = {}

    def fake_open(req, timeout):
        captured["ua"] = req.get_header("User-agent")
        captured["accept"] = req.get_header("Accept")
        return FakeResponse(png_bytes())

    monkeypatch.setattr(media_fetch, "_open", fake_open)
    media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "libli" in captured["ua"]
    assert captured["accept"] == "image/*"
