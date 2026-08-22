import io
import time

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from courses import media_fetch
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


class DripBody(io.RawIOBase):
    """read1 returns PARTIAL data slowly.

    Deliberately NOT a generator: a generator-based double returns instantly and the
    test would pass GREEN on a build that reads with read() instead of read1() -- the
    exact "assertion that cannot fail" this repo has shipped before.
    """

    def __init__(self, delay):
        self.delay = delay
        self.headers = {"Content-Type": "image/png"}
        self.status = 200

    def read1(self, n=-1):
        time.sleep(self.delay)
        return b"\0" * 8

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_drip_body_hits_the_deadline(monkeypatch):
    # Patch the constants DOWN -- at 20s each of these would add ~20s to a suite that
    # otherwise runs affected tests in ~30s. The drip rate is expressed relative to
    # the patched value so the test stays meaningful if the constant changes.
    monkeypatch.setattr(media_fetch, "DEADLINE_SECONDS", 0.4)
    monkeypatch.setattr(media_fetch, "TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: DripBody(0.05))
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "took too long" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_drip_header_hits_the_deadline(monkeypatch):
    """A slow HEADER never reaches the chunk loop at all -- only the thread-join
    budget bounds it. A per-socket timeout would not fire."""
    monkeypatch.setattr(media_fetch, "DEADLINE_SECONDS", 0.3)

    def slow_open(req, timeout):
        time.sleep(5)

    monkeypatch.setattr(media_fetch, "_open", slow_open)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(CourseFactory(), URL, UserFactory())
    assert "took too long" in "; ".join(exc.value.messages)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=OK, ALLOW_HTTP_IMAGE_FETCH=False)
def test_budget_is_checked_between_redirect_hops(monkeypatch):
    """Assert on the WORKER, not on the user-facing message.

    The message is the wrong probe: the joiner emits "took too long" unconditionally
    whenever join() times out with an empty box, whether or not the worker ever checked
    its budget. So with the top-of-loop _remaining() removed the worker keeps issuing
    hops on the daemon thread while the joiner still reports the deadline -- and a
    message-only assertion stays GREEN on the mutant it claims to catch.

    This is the spec's headline safety property: (MAX_REDIRECT_HOPS + 1) x
    TIMEOUT_SECONDS = 32s exceeds DEADLINE_SECONDS = 20s, and the per-iteration check
    is the only thing holding the bound. Count the calls instead.
    """
    import urllib.error

    # Build the fixtures BEFORE the clock: CourseFactory + UserFactory + the two
    # effective_* reads cost 57.7ms on the first call and 25-26ms after (MEASURED
    # against the test DB), which would otherwise eat the margin below.
    course, user = CourseFactory(), UserFactory()

    monkeypatch.setattr(media_fetch, "DEADLINE_SECONDS", 0.5)
    started = []

    def slow_redirect(req, timeout):
        started.append(time.monotonic())
        time.sleep(0.4)
        raise urllib.error.HTTPError(
            URL, 302, "r", {"Location": "https://upload.wikimedia.org/next.png"}, None
        )

    monkeypatch.setattr(media_fetch, "_open", slow_redirect)
    with pytest.raises(ValidationError) as exc:
        media_fetch.fetch_image_asset(course, URL, user)
    assert "took too long" in "; ".join(exc.value.messages)

    # Give the daemon thread time to make any further (forbidden) calls.
    time.sleep(0.5)
    assert started, "the worker never issued a request"
    # COUNT, not a wall-clock bound. A second hop legitimately starts on a correct
    # build -- _remaining only raises at left <= 0, so with ~0.098s of budget left the
    # loop takes another turn -- which is why <= 2 is the correct bound and why an
    # earlier `max(started) < t0 + 0.5` assertion had only ~40ms of headroom and could
    # redden a CORRECT build under load. On the mutant the worker has started hops at
    # ~0, 0.4 and 0.8s by this point, so len(started) == 3 and this goes RED.
    msg = f"the worker kept issuing hops past the deadline: {started}"
    assert len(started) <= 2, msg
