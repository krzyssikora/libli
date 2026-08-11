"""Structural CSS pins. Computed-style behaviour is covered by e2e (Task 13)."""

import glob
import re
from pathlib import Path


def _courses_css():
    return "".join(
        Path(p).read_text(encoding="utf-8")
        for p in glob.glob("courses/static/courses/css/courses.css")
    )


def test_callout_children_have_edge_margin_resets_and_a_sibling_gap():
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    assert ".callout__children" in css
    assert ".callout__child + .callout__child" in css, "no gap between two children"
    assert ".callout__body + .callout__children" in css, "no body/children separation"


def test_prose_cap_no_longer_applies_to_any_callout():
    """Every callout fills the column now, not just one with children.

    Was: `.callout:not(:has(> .callout__children))` must EXIST. That predicate is
    gone -- a callout with children and a callout with only text were rendering at
    two different widths, which is what this change fixes.

    Token boundary is mandatory. A bare `".callout" in block` also matches
    `.callout__body` / `__children` / `__heading`, and adding `.callout__body` to the
    cap would be a legitimate no-op (it already carries .el--text) -- so the naive
    form would redden on correct code.

    Replaces the old second assertion rather than keeping it: that one was
    `\\.callout\\s*,`, which REQUIRED a trailing comma, so a `.callout` re-added as
    the LAST prelude selector (followed by `{`, not `,`) escaped it. This regex has
    no such hole.

    Slices between the sentinels because the file has many @media blocks and many
    html.unit-tree-collapsed rules, and line numbers move the moment the block is
    edited.
    """
    css = _courses_css()
    start = css.index("/* prose-cap:begin */") + len("/* prose-cap:begin */")
    end = css.index("/* prose-cap:end */")
    block = re.sub(r"/\*.*?\*/", "", css[start:end], flags=re.S)
    assert re.search(r"\.callout(?![\w-])", block) is None, (
        f"a .callout selector is back in the prose-cap block: {block!r}"
    )


def test_callout_heading_katex_resets_the_eyebrow_treatment():
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    block = css.split(".callout__heading .katex")[1].split("}")[0]
    assert "text-transform" in block
    assert "letter-spacing" in block
