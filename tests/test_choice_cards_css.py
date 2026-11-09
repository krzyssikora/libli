"""Source guards for the choice option cards (spec 2026-11-09 §3.1, §3.2)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RAW_CSS = (ROOT / "courses/static/courses/css/courses.css").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", RAW_CSS, flags=re.S)

HOVER_AT = "@media (hover: hover)"
HAS_AT = "@supports selector(:has(input:checked))"
PICKED = ".question__choices .question__choice:has(input:checked)"
HOVER_SELECTOR = re.compile(r"\.question__choice\b[^{}]*:hover")


def _at_blocks(css, header):
    """(start, end) of the body of every at-rule opened by `header`."""
    spans = []
    at = css.find(header)
    while at >= 0:
        depth = 0
        i = css.index("{", at)
        start = i + 1
        while True:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        spans.append((start, i))
        at = css.find(header, i)
    assert spans, f"no block opened by {header}"
    return spans


def _inside(css, header):
    return "\n".join(css[a:b] for a, b in _at_blocks(css, header))


def _outside(css, header):
    kept, last = [], 0
    for a, b in _at_blocks(css, header):
        kept.append(css[last:a])
        last = b
    kept.append(css[last:])
    return "\n".join(kept)


def _rule_body(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"no rule for {selector}"
    return match.group(1)


def test_hover_selectors_only_inside_hover_media():
    assert HOVER_SELECTOR.search(_inside(CSS, HOVER_AT))
    stray = HOVER_SELECTOR.findall(_outside(CSS, HOVER_AT))
    assert not stray, f"a tap could leave a sticky outline: {stray}"


def test_input_hiding_is_inside_supports_has():
    inside = _inside(CSS, HAS_AT)
    assert re.search(
        r"\.question__choices \.question__choice input\s*\{[^}]*clip: rect\(0 0 0 0\)",
        inside,
    )
    outside = _outside(CSS, HAS_AT)
    assert not re.search(
        r"\.question__choice\b[^{}]*input[^{}]*\{[^}]*clip:", outside
    ), "a browser without :has() would lose the selection indicator"


def test_picked_thickness_is_an_inset_shadow_not_a_border_width():
    body = _rule_body(CSS, PICKED)
    assert re.search(r"box-shadow:\s*inset", body)
    assert "border-width" not in body


def _print_tint_selector_lists():
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", _inside(CSS, "@media print"))
    return [
        selectors.strip()
        for selectors, body in rules
        if ".question__choice" in selectors and "print-color-adjust" in body
    ]


@pytest.mark.parametrize("verdict", ["--correct", "--wrong", "--missed"])
def test_print_verdict_tint_survives_a_browser_without_has(verdict):
    """One unsupported selector voids its whole list, so :has() stays out of it."""
    lists = [
        s for s in _print_tint_selector_lists() if f".question__choice{verdict}" in s
    ]
    assert lists, f"no print tint for {verdict}"
    assert not [s for s in lists if ":has(" in s], lists


def test_print_picked_tint_has_its_own_rule():
    assert PICKED in _print_tint_selector_lists()


def test_removed_row_and_list_modifiers_are_gone():
    assert ".question__choice--picked" not in RAW_CSS
    assert ".question__choices--marked" not in RAW_CSS
