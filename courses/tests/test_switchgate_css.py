import glob
from pathlib import Path


def test_switchgate_css_present():
    # The switchgate rules live alongside .reveal-gate/.fillgate, which are
    # defined in core/static/core/css/app.css (NOT courses/static/courses/css/
    # -- that tree holds the quiz/question styles instead). Scan both static
    # CSS trees so this test finds the rules wherever they land.
    css = "".join(
        Path(p).read_text(encoding="utf-8")
        for pattern in (
            "courses/static/courses/css/*.css",
            "core/static/core/css/*.css",
        )
        for p in glob.glob(pattern)
    )
    for sel in [
        ".switchgate",
        ".switchgate__cycler",
        ".switchgate__confirm",
        ".switchgate--done",
    ]:
        assert sel in css, sel
