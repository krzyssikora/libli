import re
from pathlib import Path

from courses.models import BeforeAfterElement

COURSES_CSS = "courses/static/courses/css/courses.css"
APP_CSS = "core/static/core/css/app.css"


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _strip_comments(css):
    """Comments name the very selectors these tests look for, so a raw scan is
    green under its own mutant (the test_element_state_write_routes precedent).
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css):
    """Split the element's CSS into (base, state, print).

    Comments are stripped FIRST -- they name the very selectors these tests look
    for, so a raw scan is green under its own mutant, and a comment mentioning
    `html:not(.ba-js)` would truncate the base block. That means the delimiters
    must be REAL SELECTORS, never the delimiter comments (which stripping
    deletes): `.el--beforeafter` opens the base block, `html:not(.ba-js)` opens
    the state block, `@media print` opens the print block.

    Every index is asserted, and the print block is sanity-checked by content, so
    a mis-extraction is loud rather than vacuous.
    """
    s = _strip_comments(css)
    i_base = s.index(".el--beforeafter")
    i_state = s.index("html:not(.ba-js)", i_base)
    i_print = s.index("@media print", i_state)
    end = s.index("\n}", i_print)
    base, state, printed = s[i_base:i_state], s[i_state:i_print], s[i_print:end]
    # courses.css holds several @media print blocks; this asserts we took ours.
    assert ".ba__panel[hidden]" in printed, "extracted the wrong @media print block"
    return base, state, printed


def _rule_body(block, selector):
    """The declarations of one rule, so an invariant about `.ba__panel` is not
    asserted against a whole block that legitimately contains other rules."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", block)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_panel_and_child_declare_no_display():
    """The invariant is narrow: `.ba__panel` and `.ba__child` declare no display.
    It is NOT "the base block declares no display" -- the block also holds
    `.ba__toggle { display: inline-flex }`, which the spec requires.

    Mutant: add `display: block` to .ba__panel -> RED.
    """
    block, _state, _print = _blocks(_read(COURSES_CSS))
    panel = _rule_body(block, ".ba__panel")
    assert "border-left" in panel
    assert "display" not in panel
    # .ba__child deliberately has NO base rule: that is what keeps the `hidden`
    # attribute working through the UA default. If one is ever added it must not
    # declare `display`, and this assertion must be updated to check it rather
    # than silently skipping.
    assert ".ba__child" not in block, (
        "a .ba__child base rule appeared -- assert it declares no display"
    )


def test_ba_child_joins_the_hidden_guard():
    """.ba__child is a reveal-cascade wrapper exactly as .tabs__child is, so it
    needs the same protection against an author display beating [hidden].

    Anchor on the guard rule itself: app.css's first one is
    `.reveal-gate[hidden] { display: none !important; }`, which is the FIRST line
    matching a generic [hidden]+!important pattern and would never contain
    .ba__child -- making a first-match regex RED against correct code.
    """
    css = _strip_comments(_read(APP_CSS))
    guard = re.search(r"^.*\.lesson-block\[hidden\].*$", css, re.M)
    assert guard, "the shared [hidden] guard line moved"
    assert ".ba__child[hidden]" in guard.group(0)


# courses.css contains SIX @media print blocks (the first at :103). A first-match
# `@media print` regex -- the convention test_reveal_scope_agreement uses for
# app.css, where it holds -- extracts the WRONG one here, so all the print tests
# below would be RED against a correct implementation. _blocks() searches forward
# from the state block instead, and asserts the result is ours.


def _print_block(css):
    return _blocks(css)[2]


def test_print_unhides_with_block_not_revert():
    """`revert` rolls back to the UA origin, where [hidden] { display: none }
    lives -- so it CANNOT un-hide an element carrying the attribute.

    Bound to the `.ba__panel[hidden]` rule specifically via `_rule_body` --
    a bare substring check for "display: block !important" anywhere in the
    print block is satisfied by the neighbouring `[data-ba-side="after"]`
    rule even when THIS rule reads `revert`, so it would not go red.

    Mutant: change to `display: revert` -> the panel stays hidden in print.
    """
    block = _print_block(_read(COURSES_CSS))
    panel_rule = _rule_body(block, ".ba__panel[hidden]")
    assert "display: block !important" in panel_rule
    assert ".ba__toggle" in block


def test_print_reverts_clip_not_clip_path():
    """.visually-hidden (app.css) uses `clip`, not `clip-path`. A
    `clip-path: none` override is a no-op leaving a 1x1 overflow-hidden box --
    an unlabelled printed page that LOOKS handled.
    """
    block = _print_block(_read(COURSES_CSS))
    assert "clip: auto !important" in block
    assert "clip-path" not in block


def test_print_carries_the_eyebrow_and_separation_rules():
    """Print is the ONLY path that reaches these headings on a working JS page.

    Mutant: drop them -> two butted-together panels under unstyled bare <p>s.
    """
    block = _print_block(_read(COURSES_CSS))
    assert "text-transform: uppercase" in block
    assert ".ba__panel + .ba__panel" in block


def test_print_child_rule_follows_the_app_css_guard_in_document_order():
    """Both are `.ba__child[hidden]` at specificity 0-2-0 with !important, so
    NEITHER specificity nor @media print decides the winner -- only document
    order does. base.html loads app.css before courses.css, so the print
    declaration living in courses.css is what makes it win.

    Mutant: move the print block into app.css above :1010 -> the child stays
    hidden in print.
    """
    assert ".ba__child[hidden]" in _print_block(_read(COURSES_CSS))
    # NOTE: the "moved into app.css" mutant is killed by _blocks()'s
    # `assert ".ba__panel[hidden]" in printed`, not by a check here -- after Step 3
    # app.css contains .ba__child[hidden] exactly once, so any count-based branch
    # would be dead code.


def test_no_js_rules_revert_the_same_five_properties():
    """Bounded by the print delimiter -- a fixed character window would go red
    whenever the block grows, and would silently swallow the print block if it
    shrank."""
    _base, block, _print = _blocks(_read(COURSES_CSS))
    for decl in (
        "position: static",
        "width: auto",
        "height: auto",
        "overflow: visible",
        "clip: auto",
    ):
        assert decl in block
    assert ".ba--dead" in block  # the per-instance twin shares the declarations


def test_after_slot_id_matches_every_css_selector():
    """CSS cannot reference a Python constant, so `after` is hardcoded in three
    sites. Renaming AFTER_SLOT_ID would silently disarm the pre-hide -- and the
    failure mode is a FLASHED ANSWER, not a test error.

    Two of the three sites are TEMPLATES, not stylesheets: a guard that globs
    *.css would cover one of three and ship green.
    """
    assert BeforeAfterElement.AFTER_SLOT_ID == "after"
    selector = '[data-ba-side="after"]'
    for path in (
        "templates/courses/lesson_unit.html",
        "templates/courses/quiz_unit.html",
        COURSES_CSS,
    ):
        text = _read(path)
        assert selector in text, f"{selector} missing from {path}"
