"""Source-level guards for the long-division highlight.

These assert on file CONTENT rather than behaviour because the units under
test are a KaTeX render option and two CSS rules -- neither is reachable from
Python, and both are silently droppable (KaTeX discards an untrusted command
without error; a missing CSS rule just renders unstyled).
"""

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


def test_math_js_trusts_htmlclass_by_equality():
    src = MATH_JS.read_text(encoding="utf-8")
    assert 'c.command === "\\\\htmlClass"' in src


def test_math_js_trust_is_not_a_prefix_match():
    # A prefix/startsWith test would also admit \htmlStyle and \htmlData, which
    # let authored LaTeX inject arbitrary CSS and data attributes.
    src = MATH_JS.read_text(encoding="utf-8")
    assert "startsWith" not in src
    assert "indexOf" not in src.split("trust")[-1][:200]


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
    pairs = {"light": ("#8A5514", "#F4E8CD"), "dark": ("#E8B761", "#3A2F18")}
    for theme, (fg, bg) in pairs.items():
        assert _ratio(fg, bg) >= 4.5, f"{theme} highlight below AA"
