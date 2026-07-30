"""text_colour.js must load AFTER auto-render.min.js (which defines
renderMathInElement) and BEFORE any script that calls it. All scripts are `defer`, so
they execute in document order, and math.js calls renderMath(document) and
renderInlineText(document) at module evaluation — a wrapper installed after math.js
misses the entire initial page render, which is the dominant case.

Two templates load auto-render WITHOUT math.js; there the caller is question.js.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates/courses"

PAGES = [
    "lesson_unit.html",
    "quiz_unit.html",
    "quiz_results.html",
    "manage/editor/editor.html",
    "manage/review_submission.html",
]

CALLERS = ("math.js", "question.js", "quiz.js", "editor.js")


def _script_order(path):
    """Script basenames in document order.

    Parses the {% static '...' %} argument, NOT the raw src attribute: the real markup
    is src="{% static 'courses/vendor/katex/contrib/auto-render.min.js' %}", so a regex
    anchored on `.js"` matches nothing, and a `js/`-segment fallback misses everything
    under vendor/. Both mistakes make this test pass-proof rather than useful.
    """
    text = (TEMPLATES / path).read_text(encoding="utf-8")
    return [
        m.group(1).rsplit("/", 1)[-1]
        for m in re.finditer(r"{%\s*static\s*'([^']+\.js)'", text)
    ]


def test_the_parser_actually_sees_the_katex_scripts():
    """Self-check. Without it a broken parser returns [] and makes every assertion
    below vacuous — which is exactly how the first draft of this file failed."""
    order = _script_order("lesson_unit.html")
    assert "katex.min.js" in order, order
    assert "auto-render.min.js" in order, order


def test_every_katex_page_loads_text_colour_in_the_right_place():
    failures = []
    for page in PAGES:
        order = _script_order(page)
        if "auto-render.min.js" not in order:
            failures.append(f"{page}: no auto-render.min.js (template changed?)")
            continue
        if "text_colour.js" not in order:
            failures.append(f"{page}: text_colour.js is not loaded")
            continue
        colour_at = order.index("text_colour.js")
        if colour_at < order.index("auto-render.min.js"):
            failures.append(f"{page}: text_colour.js loads before auto-render.min.js")
        for caller in CALLERS:
            if caller in order and order.index(caller) < colour_at:
                failures.append(f"{page}: {caller} loads before text_colour.js")
    assert not failures, "\n".join(failures)
