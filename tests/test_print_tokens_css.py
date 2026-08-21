"""The @media print override must restate the dark palette with :root's values.

A dark-theme student printing any page gets near-white text on white paper: the
dark block sets --text-primary: #F2EFE9 and browsers strip backgrounds. The fix
duplicates :root's values inside @media print, and duplication is exactly what
drifts, so this test pins it.

The two [data-theme="dark"] blocks are located STRUCTURALLY, never by line
number: the file is partitioned at "@media print", so the screen block and the
print block are in disjoint strings and cannot resolve to the same text. That is
the failure mode tests/test_text_colour_css.py:68's first-match _block() helper
would have here.
"""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parent.parent / "core/static/core/css/tokens.css"
).read_text(encoding="utf-8")

SCREEN, _sep, PRINT = CSS.partition("@media print")


def _decls(body):
    """{token-name: value} for one declaration block body.

    The newline exclusion in the value class is the whole mechanism, and it is
    deliberately the ONLY one. tokens.css:44-48 is prose containing
    "--surface-overlay:", and a naive [^;]+ (which matches newlines) swallows from
    there to the next semicolon: --surface-overlay comes back as "nothing of the
    page may\n show through. */\n --scrim-solid: ..." and --scrim-solid never gets
    a key at all, making this test RED on a CORRECT build.

    An earlier draft ALSO stripped comments first. Measured, each guard alone
    fixes the file and each is therefore individually unfalsifiable -- two
    redundant defences mean no mutant can redden either. One mechanism, one
    mutant (battery row 13). Do not re-add the strip without retiring that row.
    """
    return {
        name: " ".join(value.split())
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;{}\n]+);", body)
    }


def _block(source, pattern):
    match = re.search(pattern + r"\s*\{(.*?)\n\s*\}", source, re.DOTALL | re.MULTILINE)
    assert match, f"tokens.css: no block matching {pattern!r}"
    return _decls(match.group(1))


def test_print_block_exists_and_is_after_the_dark_block():
    assert _sep, "tokens.css must have an @media print block"
    # Structural, not a substring check: the print block's own header COMMENT
    # mentions [data-theme="dark"] and travels with it, so `in SCREEN` stays true
    # even when the block is moved above line 79 -- the exact mutant this guards.
    assert re.search(r'^\[data-theme="dark"\]\s*\{', SCREEN, re.M), (
        "the screen dark block must precede @media print"
    )
    assert '[data-theme="dark"]' in PRINT, (
        "@media print must scope its override to [data-theme=dark]"
    )


def test_print_override_restates_every_dark_token_with_the_root_value():
    root = _block(SCREEN, r"^:root")
    dark = _block(SCREEN, r'^\[data-theme="dark"\]')
    printed = _block(PRINT, r'\[data-theme="dark"\]')

    missing = sorted(set(dark) - set(printed))
    assert not missing, (
        f"@media print omits {len(missing)} token(s) the dark block "
        f"declares: {missing}. "
        "Every one must be restated or a dark-theme printout keeps that dark value."
    )
    for name in sorted(dark):
        assert printed[name] == root[name], (
            f"{name} prints as {printed[name]!r} but :root declares {root[name]!r}; "
            "the print block must copy :root verbatim (color-mix formulas included)"
        )


def test_scrim_solid_is_not_in_the_print_override():
    # Declared only in :root, never in the dark block, so it has nothing to undo.
    assert "--scrim-solid" not in _block(PRINT, r'\[data-theme="dark"\]')
