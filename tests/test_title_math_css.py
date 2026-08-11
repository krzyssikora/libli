"""The [data-math-title] CSS normalisation (spec §3).

Source assertions, not rendering: this file pins that the rules exist, live in
the right stylesheet, and keep their specificity edge over the vendor rules they
override. The rendered confirmation is a browser A/B, not a source check.

It also pins one ABSENCE. Every `line-height`/`vertical-align` clamp this change
originally shipped was measured inert and removed (2026-08-11); the numbers and
the mechanism live in `test_no_title_surface_carries_a_line_height_clamp` and in
app.css's own block. That test is what keeps a plausible-sounding clamp from
returning without a measurement.
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
    """Deliberately left alone: the vendor's 1.2 is measured harmless on every
    title surface (see test_no_title_surface_carries_a_line_height_clamp), so
    there is nothing for this rule to override. `line-height: inherit` here would
    be a change with no measurement behind it -- and on an <h1>, whose 1.15 sits
    below 1.2, it would silently alter heights the change decided to accept."""
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


ANALYTICS_SURFACES = (
    ".analytics__matrix thead th .katex",
    ".breakdown-unit__title .katex",
    ".breakdown-node__title .katex",
)
UNIT_CHROME_SURFACES = (
    ".unit-foot__navtitle .katex",
    ".unit-tree__label .katex",
    ".unit-tree__grouptitle .katex",
    ".unit-crumbs__label .katex",
)


def test_no_title_surface_carries_a_line_height_clamp():
    """MEASURED ABSENCE, not an oversight -- this is the pin that stops the clamp
    coming back on a plausible-sounding argument.

    Both files once carried `line-height: 1; vertical-align: baseline` for these
    seven selectors. An A/B on the real pages (2026-08-11), forcing the vendor's
    line-height:1.2 back onto the same .katex boxes, moved every surface by at
    most 0.19px -- .breakdown-unit__title +0.19, .unit-crumbs__label +0.15,
    .unit-tree__label +0.06, the other four 0.00, and 0.00 on ALL seven for a
    fraction (the strut dominates, and line-height cannot touch a strut).

    The mechanism: all seven inherit line-height 1.5, which already exceeds the
    vendor's 1.2, so there was never a taller value to clamp; and
    `vertical-align` computes `baseline` either way, since the vendored
    stylesheet sets it on no .katex selector and baseline is the initial value.

    0.19px is the same delta this change rejects as noise for .result-row__title
    (49.2 vs 49.0) and .outline-unit__title. One standard, applied consistently.

    If a surface ever genuinely needs a clamp, A/B it against the rule's ABSENCE
    before adding it -- measuring only with the rule present proves nothing, which
    is exactly how the .outline-unit__title clamp was once justified and had to be
    withdrawn. Delete this test in the same commit, with the numbers."""
    for css, name, sels in (
        (_app(), "app.css", ANALYTICS_SURFACES),
        (_courses(), "courses.css", UNIT_CHROME_SURFACES),
    ):
        for sel in sels:
            assert not _has_rule(css, sel), (
                f"{name} has re-gained a rule for `{sel}`. If this is deliberate, "
                f"it needs an A/B measurement against the rule's absence."
            )


def test_the_one_surface_where_line_height_would_bite_is_documented():
    """reset.css gives h1-h4 line-height:1.15 -- BELOW the vendor's 1.2 -- so an
    <h1> title (.lesson-unit__title) is the single place a clamp would actually
    do something. It is deliberately unclamped (a tall construct keeps its own
    height), and app.css records why. This pins the heading value the reasoning
    rests on, so a future edit to reset.css cannot silently invalidate it."""
    reset = (ROOT / "core/static/core/css/reset.css").read_text(encoding="utf-8")
    m = re.search(r"h1,\s*h2,\s*h3,\s*h4\s*\{([^}]*)\}", reset)
    assert m, "the h1-h4 rule moved; re-check the clamp reasoning in app.css"
    assert "line-height: 1.15" in m.group(1)
    assert not _has_rule(_app(), ".lesson-unit__title .katex")
    assert not _has_rule(_courses(), ".lesson-unit__title .katex")


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
