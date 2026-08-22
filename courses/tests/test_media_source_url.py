import hashlib

import pytest
from django.core.files.base import ContentFile

from courses import media as media_svc
from courses.models import MediaAsset
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://upload.wikimedia.org/a/b.png", "upload.wikimedia.org"),
        ("", ""),
        ("https://[bad-ipv6/x.png", ""),  # malformed authority -> "" not a raise
    ],
)
def test_source_host(url, expected):
    assert MediaAsset(source_url=url).source_host == expected


def _png_bytes():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


def test_create_asset_persists_provenance_and_hash():
    data = _png_bytes()
    digest = hashlib.sha256(data).hexdigest()
    asset = media_svc.create_asset(
        CourseFactory(),
        "image",
        ContentFile(data, name="x.png"),
        UserFactory(),
        source_url="https://upload.wikimedia.org/x.png",
        content_hash=digest,
    )
    asset.refresh_from_db()
    assert asset.source_url == "https://upload.wikimedia.org/x.png"
    assert asset.content_hash == digest


def test_create_asset_defaults_leave_both_blank():
    asset = media_svc.create_asset(
        CourseFactory(), "image", ContentFile(_png_bytes(), name="x.png"), UserFactory()
    )
    assert asset.source_url == ""
    assert asset.content_hash == ""


def test_replace_asset_clears_source_url():
    asset = media_svc.create_asset(
        CourseFactory(),
        "image",
        ContentFile(_png_bytes(), name="x.png"),
        UserFactory(),
        source_url="https://upload.wikimedia.org/x.png",
        content_hash="deadbeef",
    )
    media_svc.replace_asset(asset, ContentFile(_png_bytes(), name="y.png"))
    asset.refresh_from_db()
    assert asset.source_url == ""
    assert asset.content_hash == ""
