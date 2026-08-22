import pytest

from courses.models import MediaAsset

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
