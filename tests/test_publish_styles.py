"""Every class the publish-state UI declares must have a rule in a stylesheet
the page that renders it actually loads.

Final-review I3. The whole family shipped with zero CSS: the in-row confirm
strip rendered as loose text fallen into the builder tree, the student-facing
draft banner as ordinary body copy, and the six-row legend as a default-UA
<dl>. Nothing caught it because no test asserts CSS existence and no screenshot
pass was run.

The load-order table is the point of this module, not an incidental detail --
the four surfaces load DISJOINT stylesheets:

  builder.html            -> builder.css (+ base reset/tokens/app)
  editor/editor.html      -> courses.css, editor.css  (NOT builder.css)
  lesson_unit / quiz_unit -> courses.css (NOT builder.css, NOT editor.css)
  node_confirm_flag.html  -> base only: reset.css, tokens.css, app.css

So a rule for a shared partial's class placed in builder.css styles the strip
and leaves the no-JS interstitial bare. Same shape as the dark-theme
"invisible buttons" bug tests/test_editor_styles.py exists for.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses" / "static" / "courses" / "css"
APP_CSS = ROOT / "core" / "static" / "core" / "css" / "app.css"
BUILDER_CSS = CSS / "builder.css"
COURSES_CSS = CSS / "courses.css"
EDITOR_CSS = CSS / "editor.css"


def _code_only(path):
    """Rule text with block comments stripped.

    Same idiom as tests/test_editor_styles.py: several of these class names are
    NAMED in prose comments explaining the load-order split above, so a bare
    substring test against the whole file would stay green after the rule block
    itself was deleted -- the guard satisfied by its own documentation.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


# (selector, stylesheet, why that sheet and not another)
CASES = [
    # Builder-only: the wrapper card, the headline <p> (the interstitial renders
    # an <h1> instead) and the dismiss button builder.js injects.
    (".flag-strip", BUILDER_CSS, "in-row strip; builder page only"),
    (".flag-strip__headline", BUILDER_CSS, "strip only; interstitial uses <h1>"),
    (".flag-strip__dismiss", BUILDER_CSS, "injected by builder.js"),
    (".flag-legend", BUILDER_CSS, "builder page only"),
    (".flag-legend__row", BUILDER_CSS, "builder page only"),
    # Shared partials: rendered by _flag_strip.html AND node_confirm_flag.html.
    # The interstitial declares no extra_css, so these MUST be in app.css.
    (".flag-strip__counts", APP_CSS, "_flag_strip_counts.html: both callers"),
    (".flag-strip__actions", APP_CSS, "both callers wrap the buttons in it"),
    (".flag-strip__hide-action", APP_CSS, "_flag_strip_actions.html: both callers"),
    (".flag-strip__quiz-warning", APP_CSS, "_flag_strip_actions.html: both callers"),
    (".flag-strip__quiz-warning--quiet", APP_CSS, "same partial, quiet variant"),
    # The draft banner renders on the editor page AND the student-facing
    # lesson/quiz pages. courses.css is the only sheet both of those load.
    (".draft-banner", COURSES_CSS, "editor + student unit pages"),
    (".draft-banner__text", COURSES_CSS, "editor + student unit pages"),
    (".draft-banner__form", COURSES_CSS, "editor + student unit pages"),
    # Editor page only.
    (".quiz-submission-banner", EDITOR_CSS, "editor.html only"),
    (".quiz-submission-banner--quiet", EDITOR_CSS, "editor.html only"),
]


@pytest.mark.parametrize(
    "selector,stylesheet,why", CASES, ids=[c[0].lstrip(".") for c in CASES]
)
def test_every_flag_and_banner_class_has_a_rule_in_a_loaded_stylesheet(
    selector, stylesheet, why
):
    css = _code_only(stylesheet)
    # The selector must TERMINATE a selector in the rule's list -- only
    # whitespace may follow it before the `,` or `{`.
    #
    # Two weaker patterns were tried and are wrong:
    #  - a bare substring test: `.flag-strip` occurs inside
    #    `.flag-strip__headline`, so it passes for a class with no rule at all.
    #  - `re.escape(selector) + r"(?![\w-])[^{}]*\{"`: this accepts the class
    #    appearing ANYWHERE in a selector, so a descendant/state rule keeps the
    #    guard green after the rule that matters is deleted. Measured: deleting
    #    the `.flag-strip` card block still passed, because
    #    `.flag-strip > form > * + *` and `.flag-strip:focus-visible` both
    #    matched. Same hole for .flag-legend__row, .flag-strip__quiz-warning
    #    and .quiz-submission-banner -- 4 of the 15 cases could not fail.
    #
    # This form still allows a comma list (`.a, .draft-banner {`), which is how
    # several of these are actually written.
    pattern = re.escape(selector) + r"\s*[,{]"
    assert re.search(pattern, css), (
        f"{selector} has no rule in {stylesheet.name} ({why}). "
        "The page that renders it does not load any other stylesheet that could."
    )


def test_inert_flag_control_paints_no_glyph():
    """Final-review I4. `.icm::before` is a mask over a solid `currentColor`
    fill. An element with `.icm` but no `icm--*` variant leaves `--icm`
    undefined, so `mask: var(--icm)` is invalid at computed-value time and
    falls back to `mask-image: none` -- nothing is cut out and the box paints
    as a SOLID 15x15 square. That is the one thing the three deliberately
    glyph-less inert controls in _tree_node.html must not look like: a filled
    glyph means "published" everywhere else in this tree.

    Source-level rather than computed-style because the rule must hold for all
    three cases, only one of which (the quiz obligatory control) an e2e page
    conveniently renders. The e2e screenshot pass is the other half.
    """
    css = _code_only(BUILDER_CSS)
    rule = r'\.icm:not\(\[class\*="icm--"\]\)::before\s*\{[^}]*display:\s*none'
    assert re.search(rule, css), (
        "builder.css must suppress the ::before of an .icm carrying no icm--* "
        "variant, or every quiz row paints a solid dark square beside its "
        "publish dot"
    )


def test_quiet_variants_do_not_use_text_tertiary():
    """--text-tertiary fails AA at body size (see the design-language notes and
    tests/test_text_colour_css.py). "Lower visual weight" for the quiet banner
    must be spent on the background and the rail, never on dropping the body
    text below the contrast floor. Checks the two quiet rule BLOCKS, not the
    whole file -- both sheets legitimately use --text-tertiary elsewhere.
    """
    for path, selector in (
        (APP_CSS, ".flag-strip__quiz-warning--quiet"),
        (EDITOR_CSS, ".quiz-submission-banner--quiet"),
    ):
        block = re.search(
            re.escape(selector) + r"(?![\w-])[^{}]*\{([^}]*)\}", _code_only(path)
        )
        assert block, f"{selector} not found in {path.name}"
        assert "--text-tertiary" not in block.group(1), (
            f"{selector} must use --text-secondary; --text-tertiary fails AA"
        )
