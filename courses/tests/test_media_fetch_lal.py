import pytest
from django.test import override_settings

from courses import media_fetch
from courses.lal_loader.media import get_or_create_asset
from courses.models import MediaAsset
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db
WIKI = ["upload.wikimedia.org"]


@pytest.fixture(autouse=True)
def _isolated_media(tmp_path, settings):
    """Redirect MEDIA_ROOT per test: create_asset writes real files to storage, and
    without this every test in this module writes into the working tree's media/."""
    settings.MEDIA_ROOT = str(tmp_path)


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_lal_import_reuses_a_byte_identical_fetched_asset(monkeypatch, tmp_path):
    """Populating content_hash is NOT behaviour-neutral: lal_loader/media.py:40 already
    dedups on (course, content_hash), so a later LAL import of identical bytes now
    reuses the fetched row, inheriting its name and source_url. Intended -- but a real
    behaviour change, so it is pinned here rather than discovered later.

    Exactly ONE fetched asset: .first() runs on an UNORDERED queryset, so with two
    identical-hash rows this would silently assert on DB order.

    The LAL side goes through the REAL loader, not a shared digest helper -- otherwise
    both sides compute the hash the same way by construction and the test would still
    pass if the digest form diverged from lal_loader/media.py:33.
    """
    course = CourseFactory()
    data = png_bytes()
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(data))

    fetched = media_fetch.fetch_image_asset(
        course, "https://upload.wikimedia.org/Foo.png", UserFactory(), name="My picture"
    )

    # get_or_create_asset reads bytes from a FILESYSTEM PATH, not a file object --
    # write the identical bytes out and drive the real loader.
    path = tmp_path / "Foo.png"
    path.write_bytes(data)
    reused = get_or_create_asset(course, "image", path)

    assert reused.pk == fetched.pk
    assert MediaAsset.objects.filter(course=course).count() == 1
    assert reused.name == "My picture"  # inherited, as documented
    assert reused.source_url == "https://upload.wikimedia.org/Foo.png"
