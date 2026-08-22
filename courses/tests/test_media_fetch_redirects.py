import urllib.error

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
URL = "https://upload.wikimedia.org/Foo.png"


@pytest.fixture(autouse=True)
def _isolated_media(tmp_path, settings):
    """Redirect MEDIA_ROOT per test: create_asset writes real files to storage, and
    without this every test in this module writes into the working tree's media/."""
    settings.MEDIA_ROOT = str(tmp_path)


def redirect(code, location):
    """A refused redirect arrives as a RAISED HTTPError -- never a returned response."""
    return urllib.error.HTTPError(URL, code, "redirect", {"Location": location}, None)


def sequence(*items):
    it = iter(items)

    def fake_open(req, timeout):
        nxt = next(it)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    return fake_open


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_exactly_three_redirects_succeed(monkeypatch):
    monkeypatch.setattr(
        media_fetch,
        "_open",
        sequence(
            redirect(302, "https://upload.wikimedia.org/a.png"),
            redirect(302, "https://upload.wikimedia.org/b.png"),
            redirect(302, "https://upload.wikimedia.org/c.png"),
            FakeResponse(png_bytes()),
        ),
    )
    asset = media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert asset.source_url == URL
    # NOTE: the other half of the spec's paired invariant -- that the filename stem
    # comes from the FINAL hop -- is asserted in
    # test_media_fetch_filename.py::test_stem_comes_from_the_final_hop, not here.
    # Keeping that assertion there (rather than adding original_filename here) keeps
    # each test's failure reason mapped to a single concern: this one to redirects,
    # that one to filename derivation.


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_a_fourth_redirect_is_too_many(monkeypatch):
    monkeypatch.setattr(
        media_fetch,
        "_open",
        sequence(
            *[redirect(302, f"https://upload.wikimedia.org/{i}.png") for i in range(4)]
        ),
    )
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "redirects too many times" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
@pytest.mark.parametrize(
    "location,fragment",
    [
        ("https://evil.com/x.png", "not on the allow-list"),
        ("http://upload.wikimedia.org/x.png", "not on the allow-list"),  # downgrade
        ("", "invalid redirect"),
        # A Location that makes urljoin/urlsplit raise ValueError -- without the guard
        # this escapes the HTTPError handler and becomes a 500, not a 422.
        ("//[bad", "invalid redirect"),
    ],
)
def test_bad_redirect_targets(monkeypatch, location, fragment):
    monkeypatch.setattr(media_fetch, "_open", sequence(redirect(302, location)))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert fragment in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_404_reports_status_not_transport(monkeypatch):
    """Proves the HTTPError clause precedes the URLError one.

    HTTPError SUBCLASSES URLError, so a URLError clause placed first swallows every
    redirect and status error and this reports "Could not reach the image host."
    """
    monkeypatch.setattr(
        media_fetch,
        "_open",
        sequence(urllib.error.HTTPError(URL, 404, "nope", {}, None)),
    )
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "returned an error" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_returned_206_is_rejected(monkeypatch):
    """206 never becomes an HTTPError -- HTTPErrorProcessor raises only outside
    200-299 -- so only the explicit resp.status != 200 check catches it."""
    monkeypatch.setattr(
        media_fetch, "_open", lambda req, t: FakeResponse(png_bytes(), status=206)
    )
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "returned an error" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_connection_failure_is_a_422_not_a_500(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("dns")

    monkeypatch.setattr(media_fetch, "_open", boom)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "Could not reach" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_mid_read_failure_is_also_a_422(monkeypatch):
    """The reason OSError is in the tuple and the try SPANS the read loop.

    A DNS failure raises from open(); a truncated body raises from inside the loop,
    AFTER the `with` has been entered. Narrowing the try to the open() call alone
    would keep test_connection_failure GREEN -- only this one goes RED.
    """

    class Truncating(FakeResponse):
        def __init__(self):
            super().__init__(png_bytes())
            self._calls = 0

        def read1(self, n=-1):
            self._calls += 1
            if self._calls > 1:
                raise OSError("connection reset mid-body")
            return super().read1(8)

    monkeypatch.setattr(media_fetch, "_open", lambda req, t: Truncating())
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "Could not reach" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_headers_are_sent_on_every_redirect_hop(monkeypatch):
    """Wikimedia 403s a generic UA, so a hop that drops the header silently breaks the
    feature against its own default allow-list. Capturing only the first call (as the
    Task-4 test does) would miss a refactor that reuses a bare url on the redirect path.
    """
    seen = []

    def fake_open(req, timeout):
        seen.append((req.get_header("User-agent"), req.get_header("Accept")))
        if len(seen) <= 3:
            raise redirect(302, f"https://upload.wikimedia.org/{len(seen)}.png")
        return FakeResponse(png_bytes())

    monkeypatch.setattr(media_fetch, "_open", fake_open)
    media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert len(seen) == 4
    assert all("libli" in ua and accept == "image/*" for ua, accept in seen)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_worker_message_renders_in_the_active_language(monkeypatch):
    """Proves the params= deferral. gettext is THREAD-LOCAL and the daemon thread has
    no activation, so a message %-formatted on the worker resolves to English there and
    this assertion goes RED. Every other test asserts English fragments, so this is the
    only guard on the rule.
    """
    from django.utils import translation

    monkeypatch.setattr(
        media_fetch,
        "_open",
        sequence(urllib.error.HTTPError(URL, 404, "nope", {}, None)),
    )
    with translation.override("pl"):
        with pytest.raises(ValidationError) as exc:
            media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
        rendered = "; ".join(exc.value.messages)
    assert "Serwer obrazów zwrócił błąd" in rendered
    assert "404" in rendered
