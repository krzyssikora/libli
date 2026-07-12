import glob
from pathlib import Path


def _all_css():
    return "".join(
        Path(p).read_text(encoding="utf-8")
        for pattern in (
            "courses/static/courses/css/*.css",
            "core/static/core/css/*.css",
        )
        for p in glob.glob(pattern)
    )


def test_spoiler_css_present():
    css = _all_css()
    assert ".spoiler__toggle" in css
    assert ".spoiler__body" in css


def test_spoiler_marker_suppressed_cross_browser():
    css = _all_css()
    assert "list-style: none" in css
    assert "::-webkit-details-marker" in css


def test_spoiler_chevron_rotates_on_open():
    css = _all_css()
    assert ".spoiler[open]" in css
