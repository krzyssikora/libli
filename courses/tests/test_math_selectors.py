"""renderInlineText's selector list must include every typeset region.

EXTRACT the function first: `.callout__heading` also appears in courses.css, and a
file-wide scan of the wrong file would be vacuous.
"""

import re
from pathlib import Path


def _render_inline_text_selectors():
    js = Path("courses/static/courses/js/math.js").read_text(encoding="utf-8")
    fn = re.search(r"function renderInlineText\(root\)\s*\{(.*?)\n  \}", js, re.S)
    assert fn, "renderInlineText not found in math.js"
    # Single-quoted pattern: the regex itself contains double quotes.
    sel = re.search(r'querySelectorAll\(\s*"([^"]+)"', fn.group(1))
    assert sel, "no querySelectorAll selector string in renderInlineText"
    return sel.group(1)


def test_every_typeset_region_is_in_the_selector_list():
    sel = _render_inline_text_selectors()
    for region in (".el--text", ".spoiler__toggle", ".callout__heading"):
        assert region in sel, f"{region} missing from renderInlineText"
