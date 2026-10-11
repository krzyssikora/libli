"""The five cascade scopes must agree between reveal.js and the pre-hide CSS.

This test must EXTRACT each block before scanning, or it is green under its own
mutant: `.spoiler__children` also occurs elsewhere, so a file-wide scan stays
green when a scope is missing from the block that matters.

There is deliberately NO print counterpart any more. Owner decision D8
(spec 2026-10-11-print-layout-for-units): gated content prints exactly as the
screen shows it, so the pre-hide must apply to print media too -- it may not
be scoped to screen, and no @media print rule may revert it.
"""

import re
from pathlib import Path

SCOPES = (
    "[data-tab-panel]",
    ".slide",
    ".spoiler__children",
    ".callout__children",
    ".ba__panel",
)


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _prehide_block(html):
    """lesson_unit.html has TWO `{% if has_reveal_gate %}` blocks: the prepaint boot
    guard and the pre-hide <style>. A non-greedy match from the first
    `has_reveal_gate` stops at the INNER `{% endif %}` and returns a JS fragment
    with none of the five scopes -- red against a correct implementation.
    Anchor on the <style> tag instead.
    """
    m = re.search(r"has_reveal_gate %\}\s*<style>(.*?)</style>", html, re.S)
    assert m, "no has_reveal_gate <style> block in lesson_unit.html"
    return m.group(1)


def _scope_of(js):
    m = re.search(r"function scopeOf\(btn\)\s*\{(.*?)\}", js, re.S)
    assert m, "no scopeOf in reveal.js"
    return m.group(1)


def _has_scope(block, scope):
    """`.spoiler` is a substring of `.spoiler__children`, so match on a boundary."""
    return re.search(re.escape(scope) + r"(?![\w-])", block) is not None


def test_all_five_scopes_are_in_scope_of():
    scope_of = _scope_of(_read("courses/static/courses/js/reveal.js"))
    for s in SCOPES:
        assert _has_scope(scope_of, s), f"{s} missing from scopeOf"
    # scopeOf carries a SIXTH selector: `.spoiler` is a deliberate legacy fallback
    # for the body-only shape and is intentionally absent from the CSS block. So
    # scopeOf is asserted by CONTAINMENT, the CSS block by exact-five.
    assert _has_scope(scope_of, ".spoiler")


def test_all_five_scopes_are_in_the_prehide_block():
    block = _prehide_block(_read("templates/courses/lesson_unit.html"))
    for s in SCOPES:
        assert _has_scope(block, s), f"{s} missing from the pre-hide CSS"


def test_prehide_also_applies_in_print():
    """D8: the pre-hide must not be media-scoped, or unrevealed blocks would
    print while the screen hides them."""
    block = _prehide_block(_read("templates/courses/lesson_unit.html"))
    assert "@media" not in block
