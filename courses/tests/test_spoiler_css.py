import glob
import re
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


def test_children_region_carries_the_same_rule_as_the_body():
    """The element-based spoiler shipped with NO styling on its revealed region at
    all, so it lost both the left rule and the indent that the legacy body-only
    spoiler has. Both paths must read as the same bound-to-its-toggle aside."""
    # Comments are stripped FIRST: the rule is documented with a comment that names
    # `.spoiler__children`, and splitting on the raw text would land inside the prose
    # and read an empty declaration block (this repo's standing lesson — a comment
    # can fail, or falsely pass, a source-scanning test).
    css = re.sub(r"/\*.*?\*/", "", _all_css(), flags=re.S)
    assert ".spoiler__children" in css, "the children region is styled by nothing"
    # The declaration block the selector opens (it shares one with .spoiler__body).
    block = css.split(".spoiler__children")[1].split("}")[0]
    assert "border-left" in block, f"no rule on the children region: {block!r}"
    assert "padding-left" in block, f"no indent on the children region: {block!r}"


def test_spoiler_marker_suppressed_cross_browser():
    css = _all_css()
    assert "list-style: none" in css
    assert "::-webkit-details-marker" in css


def test_spoiler_chevron_rotates_on_open():
    css = _all_css()
    assert ".spoiler[open]" in css
