"""Two rationale comments make claims this change falsifies.

This repo treats such prose as load-bearing (a wrong comment sends the next
reader down a dead path), so each gets an assertion rather than a promise.
"""

from pathlib import Path

# Anchored on __file__, matching tests/test_consumption_css.py:3 -- a cwd-relative
# path would silently depend on pytest being invoked from the repo root.
ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses" / "static" / "courses" / "css" / "courses.css"
CALLOUT = ROOT / "templates" / "courses" / "elements" / "calloutelement.html"


def test_text_input_comment_no_longer_claims_the_textarea_fills_the_card():
    """`textarea.question__text-input` is now capped at 46rem in the collapsed
    shell, so 'fills the card column, resizable up to it' is false on the surface
    it describes. (It was already misleading: app.css declares
    `textarea { resize: vertical }`, so it has never been draggable sideways.)

    THE ANCHOR IS THE WHOLE DECLARATION, and the two rejected alternatives are
    both instructive:

    * a bare `resize: vertical` is VACUOUS -- courses.css already contains that
      string in an unrelated textarea rule, so the assertion would pass on the
      unmodified file and pin nothing.
    * the app.css line-150 citation this test used to assert on is worse than
      vacuous. It pinned a LINE NUMBER, so it required courses.css to keep citing
      a line the rule had long since moved off (`textarea { resize: vertical }`
      now sits 46 lines further down) -- the guard against stale prose was itself
      mandating stale prose. Anchor on text that moves with the rule, never on an
      ordinal. See tests/test_css_citations_are_durable.py, which now forbids the
      whole class -- and which is why that citation is spelled out in words here.
    """
    css = CSS.read_text(encoding="utf-8")
    assert "resizable up to it" not in css
    assert "`textarea { resize: vertical }`" in css, (
        "the amended comment must cite the rule that actually constrains the "
        "textarea, so the next reader does not re-derive it"
    )


def test_callout_children_comment_no_longer_cites_the_prose_cap_predicate():
    """The wrapper's third stated reason was being the subject of a :has()
    prose-cap predicate. This change deletes the only such predicate in the
    codebase, so a reader finding three reasons and only two mechanisms could
    wrongly conclude the wrapper is removable.
    """
    html = CALLOUT.read_text(encoding="utf-8")
    assert ":has(> .callout__children)" not in html
    assert "scopeOf" in html, "the two surviving reasons must remain documented"
    assert ".callout__body + .callout__children" in html
