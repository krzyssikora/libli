import pytest

from core.public_pages import PAGES
from core.public_pages import normalize_lang


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en", "en"),
        ("pl", "pl"),
        ("pl-PL", "pl"),
        ("PL-pl", "PL"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalize_lang(raw, expected):
    assert normalize_lang(raw) == expected


def test_pages_registry_shape():
    assert set(PAGES) == {"privacy", "getting-started"}
    assert PAGES["privacy"].path == "public/privacy.md"
    assert PAGES["getting-started"].path == "public/getting-started.md"
    for page in PAGES.values():
        assert str(page.title)
        assert str(page.description)
