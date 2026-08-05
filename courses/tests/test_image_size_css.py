import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COURSES_CSS = REPO / "courses" / "static" / "courses" / "css" / "courses.css"


def _css():
    """Comments STRIPPED. Non-negotiable: the comment blocks this plan mandates
    contain the very tokens being asserted — the Task 5 comment names
    `.el--image--small` and `.el { margin: 1rem 0 }`, the Task 6 one contains
    "30/45/60%" — so a bare-substring scan of the raw file passes on prose alone.
    This repo has the recorded lesson (test_element_state_write_routes.py regexes
    raw source including comments AND docstrings)."""
    return re.sub(r"/\*.*?\*/", "", COURSES_CSS.read_text(encoding="utf-8"), flags=re.S)


WIDTH_DECL = {
    "small": re.compile(r"\.el--image--small\s*\{[^}]*max-width:\s*25%"),
    "medium": re.compile(r"\.el--image--medium\s*\{[^}]*max-width:\s*50%"),
    "large": re.compile(r"\.el--image--large\s*\{[^}]*max-width:\s*75%"),
}

HEIGHT_DECL = {
    "small": re.compile(r"\.el--image--small\s+img\s*\{[^}]*max-height:\s*30dvh"),
    "medium": re.compile(r"\.el--image--medium\s+img\s*\{[^}]*max-height:\s*45dvh"),
    "large": re.compile(r"\.el--image--large\s+img\s*\{[^}]*max-height:\s*60dvh"),
    "full": re.compile(r"\.el--image--full\s+img\s*\{[^}]*max-height:\s*100dvh"),
}

FIG_GROUP = re.compile(
    r"((?:\.el--image--\w+\s*,\s*)+\.el--image--\w+)\s*\{[^}]*width:\s*fit-content[^}]*\}",
    re.S,
)
IMG_GROUP = re.compile(
    r"((?:\.el--image--\w+\s+img\s*,\s*)+\.el--image--\w+\s+img)\s*\{[^}]*margin-inline:\s*auto[^}]*\}",
    re.S,
)

RETAINED_DECL = re.compile(
    r"\.el--image\s+img\s*\{[^}]*max-width:\s*100%;\s*height:\s*auto;?[^}]*\}"
)

PRINT_MM_DECL = {
    "small": re.compile(r"\.el--image--small\s+img\s*\{[^}]*max-height:\s*45mm"),
    "medium": re.compile(r"\.el--image--medium\s+img\s*\{[^}]*max-height:\s*75mm"),
    "large": re.compile(r"\.el--image--large\s+img\s*\{[^}]*max-height:\s*110mm"),
    "full": re.compile(r"\.el--image--full\s+img\s*\{[^}]*max-height:\s*170mm"),
}


def _print_block(css):
    """Extract the `@media print { ... }` block whose BODY mentions
    `.el--image--`, along with its start index in `css`.

    Two traps make the obvious one-liner wrong:

    1. `courses.css` holds several `@media print` blocks (breadcrumbs, the TOC
       pin, ...), so "the" block is ambiguous. A first-match regex would grab
       an unrelated one. Selecting by CONTENT (does the body mention
       `.el--image--`) is what makes this unambiguous.
    2. `@media` bodies contain nested rule braces, so a naive
       `@media print\\s*\\{[^}]*\\}` truncates at the FIRST inner `}` -- it
       would extract only the `small` declaration and silently pass a test
       that only ever checked one of the four values. Counting braces forward
       from the `@media print` match to its true matching close is what
       avoids that.
    """
    matches = []
    for m in re.finditer(r"@media\s+print\s*\{", css):
        depth = 1
        pos = m.end()
        while depth and pos < len(css):
            ch = css[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            pos += 1
        block = css[m.start() : pos]
        if ".el--image--" in block:
            matches.append((block, m.start()))
    assert len(matches) == 1, (
        f"expected exactly one @media print block mentioning .el--image--, "
        f"got {len(matches)}"
    )
    return matches[0]


def test_print_block_bounds_all_four_presets_in_mm():
    css = _css()
    block, _ = _print_block(css)
    for name, rx in PRINT_MM_DECL.items():
        assert rx.search(block), f"missing print max-height (mm) for {name}"


def test_print_block_comes_after_screen_presets():
    css = _css()
    _, print_start = _print_block(css)
    full_dvh_match = re.search(r"\.el--image--full\s+img\s*\{[^}]*100dvh", css)
    assert full_dvh_match, "could not locate the screen `full` max-height rule"
    assert print_start > full_dvh_match.start(), (
        "the @media print block must come AFTER the screen presets -- a media "
        "query adds no specificity, so an earlier print block loses the "
        "source-order tie and every image prints at its dvh height"
    )


def test_width_declarations():
    css = _css()
    for name, rx in WIDTH_DECL.items():
        assert rx.search(css), f"missing max-width declaration for {name}"


def test_height_declarations():
    css = _css()
    for name, rx in HEIGHT_DECL.items():
        assert rx.search(css), f"missing max-height declaration for {name}"


def test_figure_group_is_fit_content_and_excludes_full():
    css = _css()
    matches = FIG_GROUP.findall(css)
    assert len(matches) == 1, f"expected exactly one FIG_GROUP match, got {matches}"
    selectors = matches[0]
    for name in ("small", "medium", "large"):
        assert f"el--image--{name}" in selectors, selectors
    assert "el--image--full" not in selectors, selectors


def test_img_group_carries_margin_inline_auto_and_excludes_full():
    css = _css()
    matches = IMG_GROUP.findall(css)
    assert len(matches) == 1, f"expected exactly one IMG_GROUP match, got {matches}"
    selectors = matches[0]
    for name in ("small", "medium", "large"):
        assert re.search(rf"el--image--{name}\s+img", selectors), selectors
    assert not re.search(r"el--image--full\s+img", selectors), selectors


def test_retained_rule_is_unchanged():
    css = _css()
    assert RETAINED_DECL.search(css), "the retained .el--image img rule is missing"
