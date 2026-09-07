"""`.public-page` rules that restore paragraph/heading vertical rhythm.

reset.css sets `* { margin: 0 }`. app.css already restores margins for
`.public-page h1`, `.public-page table` and `.public-page th/td`, but had no
`.public-page p` rule and gave `.public-page h2` a margin-top with no
margin-bottom -- so consecutive paragraphs ran together and a heading butted
straight against its first paragraph.

These are SOURCE assertions on app.css text only. They prove the declarations
exist and are well-formed (in particular, that no token in them is undefined --
tokens.css defines --space-1..6, 8, 10 only; --space-7 does not exist, and an
undefined custom property makes the WHOLE declaration invalid, silently
dropping the margin, as app.css already warns for h2's margin-top). They
cannot prove the spacing actually renders -- that a future edit leaves the
right amount of visual gap between paragraphs, or between a heading and the
text below it, is not something a text-search test can see. That is what
tests/capture_public_page_paragraph_spacing_screenshots.py's A/B screenshots
are for.
"""

import re
from pathlib import Path

from django.conf import settings

CSS = Path(settings.BASE_DIR, "core", "static", "core", "css", "app.css").read_text(
    encoding="utf-8"
)
# Comments stripped for the token scan below: app.css deliberately NAMES
# --space-7 inside a comment (warning that it is undefined), which would
# otherwise read as a real usage.
CSS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)

# Tokens actually defined in tokens.css (--space-1..6, 8, 10). Any other
# --space-N used below would be a silent no-op, exactly like the h2
# margin-top bug this file's docstring warns about.
DEFINED_SPACE_TOKENS = {
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
    "--space-5",
    "--space-6",
    "--space-8",
    "--space-10",
}


def _rule_body(selector):
    """The declaration block text for `selector .public-page ...` in app.css."""
    start = CSS.index(selector)
    open_brace = CSS.index("{", start)
    close_brace = CSS.index("}", open_brace)
    return CSS[open_brace + 1 : close_brace]


def test_public_page_paragraph_has_a_bottom_margin():
    assert ".public-page p " in CSS
    body = _rule_body(".public-page p ")
    assert "margin-bottom" in body


def test_public_page_h2_has_both_a_top_and_a_bottom_margin():
    body = _rule_body(".public-page h2 ")
    assert "margin-top" in body
    assert "margin-bottom" in body


def test_no_declaration_in_this_block_uses_an_undefined_space_token():
    # Scan the whole public-page block (h1 through the list rules) rather than
    # just p/h2: the same silent-drop trap applies to any --space-N reference.
    start = CSS_NO_COMMENTS.index(".public-page {")
    end = CSS_NO_COMMENTS.index(".public-page table")
    block = CSS_NO_COMMENTS[start:end]
    used = set()
    i = 0
    while True:
        i = block.find("--space-", i)
        if i == -1:
            break
        j = i
        while block[j] not in ");, \n":
            j += 1
        used.add(block[i:j])
        i = j
    assert used, "expected at least one --space-N token in this block"
    assert used <= DEFINED_SPACE_TOKENS, used - DEFINED_SPACE_TOKENS
