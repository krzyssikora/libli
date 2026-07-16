import glob
from pathlib import Path


def _css():
    # The guessnumber rules live alongside .reveal-gate/.fillgate/.switchgate,
    # which are defined in core/static/core/css/app.css (NOT
    # courses/static/courses/css/ -- that tree holds the quiz/question styles
    # instead; see courses/tests/test_fillgate_css.py / test_switchgate_css.py).
    # Scan both static CSS trees so this test finds the rules wherever they land.
    return "".join(
        Path(p).read_text(encoding="utf-8")
        for pattern in (
            "courses/static/courses/css/*.css",
            "core/static/core/css/*.css",
        )
        for p in glob.glob(pattern)
    )


def test_guessnumber_css_present():
    # Every selector here is element-qualified (`.guessnumber ...`). A bare
    # ".is-correct" / ".is-wrong" already appears in courses.css today (e.g.
    # .question__verdict.is-correct), so an unscoped assertion would pass
    # without pinning anything this element actually introduces.
    css = _css()
    for sel in [
        ".guessnumber",
        ".guessnumber input[data-guess-input]",
        ".guessnumber button[data-guess-check]",
        ".guessnumber button[data-guess-check][hidden]",
        ".guessnumber input[data-guess-input].is-wrong",
        ".guessnumber input[data-guess-input].is-correct",
        ".guessnumber [data-guess-hint]",
        ".guessnumber [data-guess-hint][hidden]",
        ".guessnumber [data-guess-success]",
        ".guessnumber [data-guess-success][hidden]",
        ".guessnumber.guessnumber--done",
    ]:
        assert sel in css, sel


def test_guessnumber_css_deliberate_baseline_alignment():
    # Task 12's one genuinely new design problem: the input/Check button sit
    # inline against a KaTeX-rendered baseline. Pin that a real decision was
    # made (a vertical-align rule scoped to the two inline controls), not
    # left to the browser default.
    css = _css()
    assert "guessnumber input[data-guess-input]" in css
    assert "vertical-align" in css
    # The rule that sets it must be scoped to the guessnumber controls, not a
    # stray unrelated vertical-align elsewhere in the stylesheet.
    idx = css.find(".guessnumber input[data-guess-input],")
    assert idx != -1
    block = css[idx : idx + 400]
    assert "vertical-align" in block


def test_guessnumber_css_does_not_style_live_wrapper():
    # [data-guess-live] is a plain grouping node with no styling of its own
    # (spec §5); only its two children carry rules.
    css = _css()
    assert "[data-guess-live]" not in css
