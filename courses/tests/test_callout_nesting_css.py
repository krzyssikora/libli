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


def test_prose_cap_no_longer_applies_to_a_callout_with_children():
    """A table nested in a callout must not inherit the 46rem prose cap.

    Adding a `.callout__body` selector would be a NO-OP (it already carries el--text,
    which is already in the allowlist); the load-bearing edit is narrowing `.callout`.
    """
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    assert ".callout:not(:has(> .callout__children))" in css
    assert re.search(r"unit-tree-collapsed[^{]*\]\s+\.callout\s*,", css) is None


def test_callout_heading_katex_resets_the_eyebrow_treatment():
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    block = css.split(".callout__heading .katex")[1].split("}")[0]
    assert "text-transform" in block
    assert "letter-spacing" in block
