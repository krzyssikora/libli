""".prev-el` must never declare `display`.

The child wrappers .callout__child / .spoiler__child / .twocolumn__child are NOT in
app.css's [hidden] guard -- they honour `hidden` only through the UA rule, which
an author `display` on .prev-el would beat. reveal.js's gateWrap.hidden = true then
stops working in the editor preview.

Comments are stripped FIRST: they name the very selectors this test looks for, so a
raw scan is green under its own mutant (the test_beforeafter_css precedent).
"""

import re
from pathlib import Path

EDITOR_CSS = "courses/static/courses/css/editor.css"


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rule_body(css, selector):
    """The declarations of ONE rule, so the invariant is not asserted against a
    whole block that legitimately contains other rules (.prev-el--hl has a
    box-shadow, which is fine and must not be mistaken for a violation)."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_prev_el_declares_no_display():
    """Mutant: add `display: block` to .prev-el -> RED."""
    css = _strip_comments(Path(EDITOR_CSS).read_text(encoding="utf-8"))
    body = _rule_body(css, ".prev-el")
    assert "border-radius" in body, "extracted the wrong rule"
    assert "display" not in body


def test_prev_el_hl_declares_no_display():
    """The highlight state is applied to the same wrappers, so it carries the same
    constraint. Mutant: add `display: block` to .prev-el--hl -> RED."""
    css = _strip_comments(Path(EDITOR_CSS).read_text(encoding="utf-8"))
    body = _rule_body(css, ".prev-el--hl")
    assert "box-shadow" in body, "extracted the wrong rule"
    assert "display" not in body
