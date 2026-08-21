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


COURSES_CSS = (
    Path(__file__).resolve().parent.parent / "courses/static/courses/css/courses.css"
).read_text(encoding="utf-8")

CALLOUT_KINDS = ("example", "note", "tip", "warning", "task")


def _callout_accents(source):
    """{kind: value} for every .callout--KIND { --callout-accent: ... } in `source`."""
    return {
        kind: value.strip()
        for kind, value in re.findall(
            r"\.callout--([a-z]+)\s*\{\s*--callout-accent:\s*([^;]+);", source
        )
    }


def test_print_restates_every_dark_callout_accent_with_the_light_value():
    """--callout-accent is declared in courses.css, a LATER sheet at (0,2,0), so
    tokens.css's print block cannot reach it. Without its own print block a
    dark-theme lesson with callouts prints #7db0f7 headings on white (2.23:1)."""
    # Whitespace-exact by necessity, and unique in courses.css today (checked
    # against all 8 existing @media print blocks). If a reformat ever breaks it,
    # the failure reads "no @media print block" rather than "wrong value" -- so
    # check the marker before believing that message.
    marker = '@media print {\n  [data-theme="dark"]'
    screen, sep, printed = COURSES_CSS.partition(marker)
    assert sep, (
        "courses.css must have an @media print block scoped to [data-theme=dark]"
    )

    # Light values live on the bare modifier classes; dark ones on the
    # [data-theme="dark"] .callout--KIND rules. Split the screen half on the
    # dark selector so the two are never confused.
    light_half, _d, dark_half = screen.partition('[data-theme="dark"] .callout--')
    light = _callout_accents(light_half)
    print_side = _callout_accents(printed)

    for kind in CALLOUT_KINDS:
        assert kind in print_side, (
            f".callout--{kind} has a dark accent but no print override; a dark-theme "
            "printout keeps the light-on-white tint"
        )
        assert print_side[kind] == light[kind], (
            f"print .callout--{kind} is {print_side[kind]!r} but the light rule "
            f"declares {light[kind]!r}; the source is the light-theme declaration of "
            "the same selector, NOT :root (--callout-accent is never declared there)"
        )


def test_every_dark_rule_in_a_shipped_stylesheet_is_classified():
    """A new [data-theme="dark"] rule must not slip in unnoticed: it either needs a
    print counterpart or a recorded reason it does not.

    Deliberately limited to COLUMN-0 rules. error.css:50's dark rule is indented
    inside a media query and is not matched; that is accepted, because dropping the
    anchor would also match the prose mentions in notes.css:17 and tags.css:2.
    """
    root = Path(__file__).resolve().parent.parent
    covered = {  # has a print counterpart
        "core/static/core/css/tokens.css",
        "courses/static/courses/css/courses.css",
    }
    excluded = {  # deliberately no print counterpart, reason recorded
        # Editor chrome; never on a page this feature prints.
        "courses/static/courses/css/editor.css",
        # tags.css IS loaded by lesson_unit.html:36, but .tag-delete-confirm is
        # built only by wireDeleteConfirm() (tags.js:103,108) from
        # .tag-section__manage delete links, which exist only in
        # _tag_section.html -> my_tags.html. The element never reaches a lesson.
        "tags/static/tags/css/tags.css",
    }
    found = set()
    for css in root.glob("*/static/**/*.css"):
        if ".venv" in css.parts or "staticfiles" in css.parts:
            continue
        text = css.read_text(encoding="utf-8")
        if re.search(r'^\[data-theme="dark"\]', text, re.M):
            found.add(css.relative_to(root).as_posix())
    unclassified = found - covered - excluded
    assert not unclassified, (
        f'unclassified [data-theme="dark"] rule(s): {sorted(unclassified)}. '
        "Add a print counterpart, or record why one is not needed."
    )


SLIDESHOW_PRINT_REQUIRED = (
    ".slideshow-deck .slide[hidden]",
    "position: static !important",
    "opacity: 1 !important",
    "transition: none !important",
    ".slideshow-bar",
)


def test_slideshow_print_block_declares_the_load_bearing_rules():
    """Cheap tripwire, not a cascade proof: a rule can be present and still inert,
    which only the e2e A/B in Task 4 can catch. This exists so a typo or a dropped
    declaration fails in Task 3 rather than two tasks later."""
    marker = ".slideshow-deck {\n    overflow: visible"
    _screen, sep, printed = COURSES_CSS.partition(marker)
    assert sep, "courses.css must have a print block for the slideshow deck"
    block = sep + printed
    for needle in SLIDESHOW_PRINT_REQUIRED:
        assert needle in block, f"slideshow print block is missing {needle!r}"


def test_courses_css_braces_balance():
    """Green BEFORE the append too -- courses.css already balances (559/559). This
    is a regression tripwire for a malformed hand-edit, not part of the red phase,
    and battery row 14 is what proves it can go red at all."""
    text = re.sub(r"/\*.*?\*/", "", COURSES_CSS, flags=re.DOTALL)
    assert text.count("{") == text.count("}"), (
        "unbalanced braces in courses.css -- an appended block is malformed"
    )
