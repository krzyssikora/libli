"""The [data-math-title] CSS normalisation (spec §3).

Source assertions, not rendering: the MEASURED confirmation of these values is
Task 11's job (screenshots + devtools), and this file only pins that the rules
exist, live in the right stylesheet, and keep their specificity edge over the
vendor rules they override.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "core/static/core/css/app.css"
COURSES_CSS = ROOT / "courses/static/courses/css/courses.css"


def _app():
    return APP_CSS.read_text(encoding="utf-8")


def _courses():
    return COURSES_CSS.read_text(encoding="utf-8")


def test_the_global_normalisation_lives_in_app_css_not_courses_css():
    """Seven of the twelve gate-table templates link NO courses.css -- their rules
    live in app.css / notes.css / tags.css. A courses.css copy would leave all
    seven at an unnormalised 1.21em."""
    # Anchored to a RULE, not a mention: the courses.css block this task appends
    # is a long comment that cross-references the app.css block, and a bare
    # `not in` substring check would go red for a documentation edit with no
    # behavioural change.
    assert re.search(r"^\s*\[data-math-title\]\s+\.katex\s*\{", _app(), re.M)
    assert not re.search(r"^\s*\[data-math-title\]\s+\.katex", _courses(), re.M)


def test_font_size_weight_and_style_are_all_restored():
    """The vendored rule is `.katex{font:normal 1.21em KaTeX_Main,...}` -- a font
    SHORTHAND, which resets every unset font longhand, font-weight among them.
    Restoring only font-size leaves a maths run at `normal` weight inside a bold
    .lesson-unit__title / .result__title / .editor-head__title, visibly lighter
    than the prose beside it."""
    block = re.search(r"\[data-math-title\]\s+\.katex\s*\{([^}]*)\}", _app())
    assert block, "the [data-math-title] .katex rule is missing"
    body = block.group(1)
    assert "font-size: inherit" in body
    assert "font-weight: inherit" in body
    assert "font-style: inherit" in body


def test_line_height_is_not_inherited_by_the_global_rule():
    """Deliberately NOT inherited here -- the compact-chrome clamps own it."""
    block = re.search(r"\[data-math-title\]\s+\.katex\s*\{([^}]*)\}", _app())
    assert "line-height" not in block.group(1)


def test_the_display_wrapper_is_neutralised():
    """`.katex-display{display:block;margin:1em 0;text-align:center}` would turn a
    \\[...\\] title into a centred block with 1em margins inside a nav button, a
    breadcrumb <li> or a tree row. Since \\[...\\] in titles is supported, this is
    required, not optional."""
    block = re.search(r"\[data-math-title\]\s+\.katex-display\s*\{([^}]*)\}", _app())
    assert block, "the .katex-display wrapper override is missing"
    body = block.group(1)
    assert "display: inline-block" in body
    assert "margin: 0" in body
    assert "text-align: inherit" in body


def test_the_display_child_override_uses_the_child_combinator():
    """The vendor's `.katex-display>.katex` is (0,2,0) -- IDENTICAL to
    `[data-math-title] .katex`. Overriding it needs the child combinator to reach
    (0,3,0); at equal specificity KaTeX wins, because katex.min.css always loads
    AFTER app.css (base.html:46 vs the extra_css block at :49)."""
    assert re.search(
        r"\[data-math-title\]\s+\.katex-display\s*>\s*\.katex\s*\{", _app()
    ), "the child override is missing or lost its > combinator"


def test_both_display_rules_are_present_neither_alone_suffices():
    """Neutralising only the CHILD is wrong, and that is the half that matters: a
    display:block WRAPPER is still a block-level box -- inside
    `<h1>Rozwiaz \\[x^2\\] teraz</h1>` it splits the inline content into anonymous
    block boxes and renders on three lines. `margin: 0` removes the gaps but NOT
    the line break."""
    css = _app()
    assert re.search(r"\[data-math-title\]\s+\.katex-display\s*\{", css)
    assert re.search(r"\[data-math-title\]\s+\.katex-display\s*>\s*\.katex\s*\{", css)


def _rule_body(css, selector):
    """The declaration block of the (possibly grouped) rule `selector` heads.

    Returns None if `selector` never heads a rule. Matching up to the `{` --
    allowing a comma, i.e. the selector being one member of a grouped rule --
    means a documentation edit can never satisfy it: both stylesheets gain long
    comment blocks naming several of these class names, and they pass today only
    because those comments happen to omit the ` .katex` suffix, which is an
    incidental property rather than a designed one.

    THE COMMA BRANCH MUST BE OPTIONAL, NOT ALTERNATIVE. `[,{][^{}]*\{` looks
    right and is broken: when the selector is the LAST member of a group -- or a
    solo rule -- the `{` is consumed by the character class and the pattern then
    demands a second `{` that never comes. Verified: that form misses
    `.breakdown-node__title .katex`, `.unit-crumbs__label .katex` and
    `[data-math-title] .katex-display > .katex`, i.e. three of this file's own
    assertions, including the sole pin on the deliberate spec §3 deviation.
    """
    m = re.search(re.escape(selector) + r"\s*(?:,[^{}]*)?\{([^}]*)\}", css)
    return m.group(1) if m else None


def _has_rule(css, selector):
    """True iff `selector` heads a rule in `css`. Takes the stylesheet as its
    first argument so PLACEMENT is asserted, not merely existence -- a rule
    appended to a stylesheet the page does not link is a silent no-op."""
    return _rule_body(css, selector) is not None


def test_the_analytics_clamp_lives_in_app_css_and_actually_clamps():
    """The analytics pages have no courses.css.

    Asserts the DECLARATIONS, not just the selector: a rule with an empty body --
    or one carrying line-height:1.2 -- would satisfy a selector-only check while
    clamping nothing, and the clamp's whole purpose is those two properties. The
    analytics sticky header is the most fragile surface in the change (a cell
    taller than --ahead-h desynchronises every sticky row beneath it)."""
    css = _app()
    for sel in (
        ".analytics__matrix thead th .katex",
        ".breakdown-unit__title .katex",
        ".breakdown-node__title .katex",
    ):
        body = _rule_body(css, sel)
        assert body is not None, f"missing analytics clamp rule: {sel}"
        assert "line-height: 1;" in body, f"{sel} does not clamp line-height"
        assert "vertical-align: baseline" in body, f"{sel} lacks baseline align"


def test_the_unit_chrome_clamp_lives_in_courses_css_and_actually_clamps():
    css = _courses()
    for sel in (
        ".unit-foot__navtitle .katex",
        ".unit-tree__label .katex",
        ".unit-tree__grouptitle .katex",
        ".unit-crumbs__label .katex",
    ):
        body = _rule_body(css, sel)
        assert body is not None, f"missing unit-chrome clamp rule: {sel}"
        assert "line-height: 1;" in body, f"{sel} does not clamp line-height"
        assert "vertical-align: baseline" in body, f"{sel} lacks baseline align"


def test_the_display_child_override_does_not_touch_white_space():
    """The vendor's `.katex-display>.katex{white-space:nowrap}` must SURVIVE.

    A formula must not break mid-formula, and an <h1> is white-space:normal, so
    `white-space: inherit` here would hand the formula back exactly the wrapping
    the vendor rule prevents. Spec §3's code block says `inherit` while its own
    prose says nowrap is "which we in fact want to keep for a formula" -- the
    prose is right, and this test is what pins it."""
    body = _rule_body(_app(), "[data-math-title] .katex-display > .katex")
    assert body is not None
    assert "white-space" not in body
