"""notes.css had ZERO print rules before this feature; these pin the ones that
would be silently inert if written at the wrong weight.

A deletion tripwire only. A substring assertion cannot detect a rule that is
present but loses on specificity -- that is what the e2e A/B is for.
"""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parent.parent / "notes/static/notes/css/notes.css"
).read_text(encoding="utf-8")

# Partition on the BRACE, not the bare words. The print block's own header
# comment contains the literal "@media print" (explaining that it adds no
# specificity) and quotes several of the selectors below verbatim -- so
# partitioning on "@media print" would put the comment inside PRINT, and every
# needle it happens to mention would be satisfied by prose even after the RULE
# was deleted. That is a tripwire that silently stops tripping.
SCREEN, _sep, PRINT = CSS.partition("@media print {")

REQUIRED = (
    # returns the pop to flow; must match the (0,4,0) screen rule verbatim
    ".notes-js .block-notes__panel[open] .block-notes__pop",
    "top: auto !important",
    # un-clamp: (0,1,0), wins on source order, deliberately UNSCOPED
    ".note-card__body--clamp",
    "-webkit-line-clamp: none",
    # the add-more hide must beat its (0,3,0) screen reveal
    ".lesson .block-notes__pop--has-notes .block-notes__add-more",
    # the three composer carve-outs
    ":not(.note-composer--edit)",
    ":not(.note-composer--has-draft)",
    ".note-composer__error",
    # empty-pop hide -- the full :has() list, not just its opening. The three
    # carve-out classes must appear INSIDE it: _block_notes.html renders a
    # composer for every block, so without them this rule hides the pop and the
    # draft/error carve-outs buy nothing.
    ":has(.note-card, .note-composer--edit, .note-composer--has-draft, "
    ".note-composer__error)",
    # focus-highlight reset, both (0,2,0)
    ".lesson-block.is-dimmed",
    ".lesson-block.is-highlighted",
    # the SAME gesture stamps a third class, on the card itself
    ".note-card.is-highlighted",
    # print-only card elements
    ".note-card__print-label",
    ".note-card__print-date",
    ".note-card__meta-rel",
)


def test_notes_css_has_a_print_block():
    assert _sep, "notes.css must have an @media print block"


def test_print_block_declares_every_load_bearing_rule():
    for needle in REQUIRED:
        assert needle in PRINT, f"notes.css print block is missing {needle!r}"


def test_un_clamp_is_not_lesson_scoped():
    """notes.js:576-578 runs setupClamp on the hub too. A .lesson-scoped un-clamp
    would leave course_notes.html printing every long note truncated at six lines.
    Scope a hide, globalise an un-hide."""
    m = re.search(r"\.note-card__body--clamp\s*\{", PRINT)
    assert m, "no un-clamp rule in the print block"
    line_start = PRINT.rfind("\n", 0, m.start()) + 1
    assert ".lesson" not in PRINT[line_start : m.start()], (
        "the un-clamp rule must NOT carry the .lesson scope"
    )


def test_print_only_card_elements_are_hidden_on_screen():
    for cls in (".note-card__print-label", ".note-card__print-date"):
        m = re.search(re.escape(cls) + r"\s*\{([^}]*)\}", SCREEN)
        assert m, f"{cls} needs a base-block rule hiding it on screen"
        assert "display: none" in m.group(1), (
            f"{cls} must be display:none on screen, or every card shows it"
        )
