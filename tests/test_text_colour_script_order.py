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


GATED_PAGES = [
    "lesson_unit.html",
    "quiz_unit.html",
    "quiz_results.html",
    "manage/review_submission.html",
]


def test_math_reflow_present_on_every_katex_page():
    for page in PAGES:
        order = _script_order(page)
        assert "math_reflow.js" in order, page


def test_math_reflow_load_order():
    """katex < auto-render < math_reflow < text_colour, and math_reflow < math.js.

    math.js runs renderMath(document) and renderInlineText(document) at module
    evaluation, so a module loaded after it misses the entire first paint."""
    for page in PAGES:
        order = _script_order(page)
        i = order.index("math_reflow.js")
        assert order.index("katex.min.js") < i, page
        assert order.index("auto-render.min.js") < i, page
        assert i < order.index("text_colour.js"), page
        # Generalised to the CALLERS tuple already defined at the top of this module.
        # quiz_results.html and review_submission.html load question.js, NOT math.js,
        # so an `if "math.js" in order` branch silently skips both -- and question.js
        # is the module whose ordering actually matters on those two pages.
        for caller in CALLERS:
            if caller in order:
                assert i < order.index(caller), (page, caller)


def _has_math_block(path):
    """The `{% if has_math %}` block that holds the SCRIPTS.

    MEASURED TRAP, two layers deep. Every gated template's FIRST `{% if has_math %}`
    is the single-line stylesheet link (lesson_unit.html:36, quiz_unit.html:7,
    quiz_results.html:7, review_submission.html:6). Taking the first match slices the
    CSS conditional, which on three of the four contains no auto-render.min.js — the
    anti-vacuity assert fires and the test is RED wherever the tag sits.

    quiz_unit.html is worse: its `{% endif %}` sits on the SAME line as the `{% if %}`,
    and searching from `start + 1` skips it, so the "block" runs lines 7-20 and swallows
    unconditional markup including unit_done.js. That block DOES contain
    auto-render.min.js, so the anti-vacuity assert stays quiet and the guard passes with
    the tag placed fully outside any conditional — measured. Hence the single-line skip.
    """
    lines = (TEMPLATES / path).read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if "{% if has_math %}" in line]
    for start in starts:
        if "{% endif %}" in lines[start]:
            continue  # single-line conditional (the stylesheet link) -- not a block
        end = next(i for i in range(start + 1, len(lines)) if "{% endif %}" in lines[i])
        block = "\n".join(lines[start:end])
        if "auto-render.min.js" in block:
            return block
    raise AssertionError(f"no has_math block containing auto-render.min.js in {path}")


def test_math_reflow_sits_inside_the_has_math_block():
    """An index-based ordering check passes identically whether the tag is inside
    or outside the conditional, so containment needs its own assertion — otherwise
    the module ships on every math-free lesson page undetected."""
    for page in GATED_PAGES:
        block = _has_math_block(page)
        assert "auto-render.min.js" in block, page  # anti-vacuity: right block
        assert "math_reflow.js" in block, page


def _strip_js_comments(source):
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", source)


def test_math_reflow_registers_no_domcontentloaded_retry():
    """A retry would wrap an already-wrapped chain and reflow twice per call.

    Comments are stripped first because the module is REQUIRED to carry a comment
    explaining why it does not retry, and quote-agnostic because a single-quoted
    call would slip past a double-quoted literal."""
    src = _strip_js_comments(
        (ROOT / "courses/static/courses/js/math_reflow.js").read_text(encoding="utf-8")
    )
    # Anti-vacuity: prove comment-stripping left real code behind, not an empty
    # string that would make the negative assertion below pass trivially.
    # Anchor on something the Task 1 SKELETON already defines: IGNORE_SELECTOR is
    # not written until Task 3, so anchoring on it makes this test fail at Task 2
    # for a reason the plan never lists.
    assert "DEFAULT_DELIMITERS" in src
    assert len(src) > 200, "comment stripping ate the whole module"
    assert not re.search(r"""addEventListener\(\s*["']DOMContentLoaded""", src)
