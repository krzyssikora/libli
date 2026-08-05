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
