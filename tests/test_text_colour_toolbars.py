"""There are FOUR rte-toolbar markup sites, not one: the shared partial plus fully
duplicated inline toolbars in _edit_text/_edit_callout/_edit_spoiler. TextElement.body
alone holds 390 of the 588 palette-coloured elements in the imported corpus, so a
change that touched only the shared partial would ship the feature with no swatches on
the surface that needs it most. Plus the two table toolbars.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITOR = ROOT / "templates/courses/manage/editor"

TOOLBARS = [
    "_rte_toolbar.html",
    "_edit_text.html",
    "_edit_callout.html",
    "_edit_spoiler.html",
    "_edit_table.html",
    "_edit_filltable.html",
]
CMDS = [
    "colour-red",
    "colour-blue",
    "colour-green",
    "colour-orange",
    "colour-none",
]


def test_every_toolbar_includes_the_swatch_partial():
    missing = [
        name
        for name in TOOLBARS
        if "_rte_swatches.html" not in (EDITOR / name).read_text(encoding="utf-8")
    ]
    assert not missing, f"toolbars without the swatch group: {missing}"


def test_the_partial_defines_every_command_exactly_once():
    text = (EDITOR / "_rte_swatches.html").read_text(encoding="utf-8")
    for cmd in CMDS:
        assert text.count(f'data-cmd="{cmd}"') == 1, f"{cmd} not defined exactly once"


def test_every_swatch_has_an_accessible_name():
    """Colour alone cannot name a control."""
    text = (EDITOR / "_rte_swatches.html").read_text(encoding="utf-8")
    assert text.count("aria-label") >= len(CMDS)
    assert text.count("{% trans") >= len(CMDS)


def test_swatch_active_state_does_not_reuse_rte_btn_is_on():
    """editor.css:230 makes .rte-btn.is-on solid --primary, which would repaint the
    active swatch brand-teal and hide the very colour it represents. Specificity is a
    tie, so the swatch rule must come LATER in the file."""
    css = (ROOT / "courses/static/courses/css/editor.css").read_text(encoding="utf-8")
    assert ".rte-swatch" in css, "swatches need their own class"
    # Anchor on the selector PLUS its opening brace. Without the brace, str.index
    # finds the first textual occurrence anywhere -- including inside this block's own
    # explanatory comment, which names both selectors in prose in that order. MEASURED:
    # the bare form passes even when the real rules are reordered, i.e. it is vacuous.
    assert css.index(".rte-swatch.is-on {") > css.index(".rte-btn.is-on {"), (
        "declaration order decides this tie; .rte-swatch.is-on must be declared after "
        ".rte-btn.is-on"
    )
