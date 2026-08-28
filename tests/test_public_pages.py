import pytest

from core.public_pages import PAGES
from core.public_pages import normalize_lang
from core.public_pages import render_markdown


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


def test_table_survives_sanitisation():
    html = render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_deep_heading_survives():
    assert "<h5>Deep</h5>" in render_markdown("##### Deep\n")


def test_two_space_line_break_survives():
    assert "<br" in render_markdown("a  \nb\n")


def test_script_is_stripped():
    html = render_markdown("<script>alert(1)</script>ok\n")
    assert "<script" not in html
    assert "alert(1)" not in html


def test_ftp_href_is_stripped_but_anchor_remains():
    # nh3 with a restricted url_schemes drops the href ATTRIBUTE and keeps the
    # element. Asserting `"<a" not in html` would be red on a correct build.
    html = render_markdown("[y](ftp://h/f)\n")
    assert "ftp:" not in html
    assert "<a" in html
    assert ">y</a>" in html


def test_javascript_href_does_not_survive():
    # Regression only: nh3 blocks javascript: by DEFAULT, so this passes with or
    # without PUBLIC_PAGE_URL_SCHEMES. Kept knowingly; the ftp test is the one
    # that actually kills the mutant.
    assert "javascript:" not in render_markdown("[j](javascript:alert(1))\n")


def test_image_is_excluded_on_purpose():
    assert "<img" not in render_markdown("![alt](https://example.com/a.png)\n")


def test_sanitiser_does_not_raise_on_a_link():
    # Guards the pinned attribute set: including "rel" raises ValueError on EVERY
    # call, because nh3 sets link_rel by default.
    html = render_markdown("[y](https://example.com)\n")
    assert 'rel="noopener noreferrer"' in html
