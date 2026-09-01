"""Source-level guards for the dark-mode content-image plate.

The rendering itself is proved by tests/test_e2e_dark_image_plate.py, which samples
real pixels in both themes. This module guards the two things that test cannot see,
because both are invariants about where declarations SIT rather than about what a
browser paints:

1. --image-plate is theme-invariant. It is light-ground colour used only in a dark
   context, so it works by being absent from the [data-theme="dark"] block. Adding a
   dark restatement -- the obvious thing to do when routinely editing a file where
   every neighbouring surface token IS declared twice -- would make the plate resolve
   to the dark ground and silently restore the original defect. Nothing in the CSS
   reads as wrong afterwards.

2. The print reset must follow the screen rule. The two tie on specificity (0,2,1),
   so print wins on source order alone; moved above, a dark-theme student's printout
   silently keeps the plate padding. The e2e cannot catch this -- it measures a
   screen.

The same reasoning, and very nearly the same code, guards --scrim-solid in
tests/test_imagezoom_render.py.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO / "core" / "static" / "core" / "css" / "tokens.css"
COURSES_CSS = REPO / "courses" / "static" / "courses" / "css" / "courses.css"

# Match DECLARATIONS, not substring occurrences: both files carry comments that name
# this token in prose, and a comment naming its own subject must not break the count.
PLATE_DECL = re.compile(r"--image-plate\s*:")

SCREEN_RULE = re.compile(
    r'^\[data-theme="dark"\]\s+\.el--image\s+img\s*\{', re.MULTILINE
)
# `[ \t]+`, NOT `\s+`: \s matches newlines, so a blank line before the column-0 screen
# rule lets `^\s+` start on that blank line and match the screen rule as though it were
# indented. That made this pattern's match count depend on the blank lines around the
# rule rather than on the invariant, and it fired the count assertion below instead of
# the ordering one -- red for the wrong reason on the ordering mutant.
PRINT_RULE = re.compile(r'^[ \t]+\[data-theme="dark"\]\s+\.el--image\s+img\s*\{', re.M)


def test_plate_token_is_declared_once_and_never_in_the_dark_block():
    source = TOKENS_CSS.read_text(encoding="utf-8")
    decls = list(PLATE_DECL.finditer(source))
    assert len(decls) == 1, f"expected one --image-plate declaration, got {len(decls)}"
    # The absence from the dark block IS the mechanism; this catches a *relocated*
    # definition, which the count alone would not. Anchor on the SELECTOR, not on the
    # first occurrence of the string: the token ships with a comment that names
    # `[data-theme="dark"]` in prose ABOVE the declaration it documents, so a plain
    # str.index would find the comment and fail for an unrelated reason.
    dark_selector = re.search(r'^\[data-theme="dark"\]\s*\{', source, re.MULTILINE)
    assert dark_selector, "tokens.css must still have a dark-theme block"
    assert decls[0].start() < dark_selector.start()


def test_plate_token_equals_the_light_page_ground():
    """Pinned to :root's --surface-base, the colour a light-theme lesson paints.

    Not a style preference: the plate exists so a transparent PNG composites onto the
    ground it was authored against, so the two values matching IS the spec. Asserting
    equality rather than the literal means a deliberate retune of the page ground
    fails here (one line to follow) instead of silently desynchronising the themes.
    """
    source = TOKENS_CSS.read_text(encoding="utf-8")
    root = re.search(r"^:root\s*\{(.*?)\n\}", source, re.DOTALL | re.MULTILINE)
    assert root, "tokens.css must still have a :root block"
    decls = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;{}\n]+);", root.group(1)))
    assert decls["--image-plate"].strip().upper() == (
        decls["--surface-base"].strip().upper()
    ), (
        f"--image-plate {decls['--image-plate']!r} must equal :root's "
        f"--surface-base {decls['--surface-base']!r}"
    )


def test_print_reset_follows_the_screen_plate_rule():
    source = COURSES_CSS.read_text(encoding="utf-8")
    screen = SCREEN_RULE.search(source)
    assert screen, "courses.css must declare the dark-theme image plate"
    print_rules = [
        m for m in PRINT_RULE.finditer(source) if m.start() != screen.start()
    ]
    assert len(print_rules) == 1, (
        f"expected exactly one indented print reset, got {len(print_rules)}"
    )
    assert print_rules[0].start() > screen.start(), (
        "the @media print reset must come after the screen rule -- they tie on "
        "specificity, so an earlier print block loses and the plate padding prints"
    )
