"""Source-level guards for the long-division highlight.

These assert on file CONTENT rather than behaviour because the units under
test are a KaTeX render option and two CSS rules -- neither is reachable from
Python, and both are droppable without an error being raised.

Losing the trust option is NOT a silent no-op: KaTeX routes an untrusted command
to `formatUnsupportedCmd`, which drops the argument and renders the command NAME
character by character in `errorColor` (verified in the vendored 0.16.11
bundle). The highlighted digit would vanish and a red `\\htmlClass` would appear
in its place. A missing CSS rule renders unstyled, which is the quiet failure.

`tests/test_e2e_math_reflow.py::test_a_marked_array_cell_renders_highlighted`
covers the same ground on the real render path, in a browser. These guards are
the cheap ones: they name WHICH line is load-bearing and why, and they run
without `-m e2e`.
"""

import re
from pathlib import Path

from django.conf import settings

MATH_JS = Path(settings.BASE_DIR) / "courses/static/courses/js/math.js"
COURSES_CSS = Path(settings.BASE_DIR) / "courses/static/courses/css/courses.css"
TOKENS_CSS = Path(settings.BASE_DIR) / "core/static/core/css/tokens.css"


def _lum(hexstr):
    h = hexstr.lstrip("#")
    ch = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _block(css, selector):
    """The declaration block for a top-level selector, e.g. ':root'."""
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.DOTALL)
    assert match, f"no {selector} block in tokens.css"
    return match.group(1)


def _token(block, name):
    """A single `--name: #hex;` value out of a declaration block."""
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})", block)
    assert match, f"no {name} in block"
    return match.group(1)


def _trust_predicate():
    """The `trust:` option's own source line.

    Scoped deliberately: `"startsWith" not in src` is a whole-file assertion that
    any unrelated future use of it anywhere in math.js would break, and it would
    not notice a prefix match written on a line of its own.
    """
    for line in MATH_JS.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("trust:"):
            return line
    raise AssertionError("no trust: option in math.js")


def test_math_js_trusts_htmlclass_by_equality():
    assert 'c.command === "\\\\htmlClass"' in _trust_predicate()


def test_math_js_trust_is_not_a_prefix_match():
    # A prefix/startsWith test would also admit \htmlStyle and \htmlData, which
    # let authored LaTeX inject arbitrary CSS and data attributes.
    trust = _trust_predicate()
    assert "startsWith" not in trust
    assert "indexOf" not in trust


def test_math_js_trust_bounds_the_class_value():
    # Trust has TWO axes and the command check closes only one. KaTeX passes the
    # class in the same context object ({command: "\\htmlClass", class: ...}), so
    # without a value check authored LaTeX may apply any class the stylesheet
    # defines -- a full-viewport `position: fixed; inset: 0` overlay over a
    # student's lesson, or a .visually-hidden-shaped class that hides content --
    # in the top-level lesson DOM, a primitive this project otherwise sandboxes
    # (HtmlElement goes through htmlsandbox.build_srcdoc into a cross-origin
    # iframe). The mk-* highlight vocabulary is the whole requirement.
    trust = _trust_predicate()
    assert "/^mk mk-[a-z]+$/" in trust
    assert ".test(c.class)" in trust


def test_inline_prose_path_does_not_get_trust():
    # renderInlineText covers .el--text and friends. Trust there would extend
    # \htmlClass to author prose in every element type.
    src = MATH_JS.read_text(encoding="utf-8")
    inline = src.split("function renderInlineText")[1]
    assert "trust" not in inline


def test_math_element_scrolls_instead_of_overflowing():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert ".el--math { overflow-x: auto; }" in css


def test_mark_classes_defined():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert ".el--math .mk-amber" in css
    assert "var(--warning-subtle)" in css.split(".el--math .mk-amber")[1][:120]
    assert "var(--tc-orange)" in css.split(".el--math .mk-amber")[1][:120]


def test_highlight_clears_aa_in_both_themes():
    # The pair was chosen on this number: --warning on --warning-subtle looks
    # fine but measures 2.79:1 in light.
    #
    # The hex literals below are a CROSS-CHECK, not the source of truth
    # (house style: tests/test_text_colour_css.py). The ratio is computed from
    # the PARSED tokens.css values, so editing --tc-orange or --warning-subtle
    # reddens this test instead of leaving it measuring numbers that no
    # longer exist.
    literals = {"light": ("#8A5514", "#F4E8CD"), "dark": ("#E8B761", "#3A2F18")}
    css = TOKENS_CSS.read_text(encoding="utf-8")
    for theme, selector in (("light", ":root"), ("dark", '[data-theme="dark"]')):
        block = _block(css, selector)
        fg = _token(block, "--tc-orange")
        bg = _token(block, "--warning-subtle")
        expected_fg, expected_bg = literals[theme]
        assert fg.upper() == expected_fg.upper(), (
            f"{selector} --tc-orange moved to {fg}; update the literal and "
            f"re-run the AA measurement"
        )
        assert bg.upper() == expected_bg.upper(), (
            f"{selector} --warning-subtle moved to {bg}; update the literal "
            f"and re-run the AA measurement"
        )
        assert _ratio(fg, bg) >= 4.5, f"{theme} highlight below AA"
