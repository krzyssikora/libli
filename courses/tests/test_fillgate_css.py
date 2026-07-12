import glob
from pathlib import Path


def test_fillgate_css_present():
    # The fill-gate rules live alongside .reveal-gate, which is defined in
    # core/static/core/css/app.css (NOT courses/static/courses/css/ — that tree
    # holds the quiz/question styles like .question__blank-input instead). Scan
    # both static CSS trees so this test finds the rules wherever they land.
    css = "".join(
        Path(p).read_text(encoding="utf-8")
        for pattern in (
            "courses/static/courses/css/*.css",
            "core/static/core/css/*.css",
        )
        for p in glob.glob(pattern)
    )
    for sel in [".fillgate", ".fillgate__confirm", ".is-wrong", ".fillgate--done"]:
        assert sel in css, sel
