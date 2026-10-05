import re
from pathlib import Path

from tests.test_text_colour_css import DARK_SURFACES
from tests.test_text_colour_css import LIGHT_SURFACES
from tests.test_text_colour_css import _ratio

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"

# The same print marker tests/test_print_tokens_css.py uses. Everything BEFORE it
# is the screen CSS -- deliberately NOT that test's light/dark split, whose light
# half would exclude the summary surface block that sits after the dark group.
PRINT_MARKER = '@media print {\n  [data-theme="dark"] .callout--'

# ^-anchored so the light pattern can never match inside the dark selector, and
# the dark one never matches the INDENTED print-block line.
SUMMARY_LIGHT_ACCENT = (
    r"^\.callout--summary\s*\{\s*--callout-accent:\s*"
    r"(#[0-9a-fA-F]{6})"
)
SUMMARY_DARK_ACCENT = (
    r'^\[data-theme="dark"\]\s+\.callout--summary\s*\{\s*--callout-accent:\s*'
    r"(#[0-9a-fA-F]{6})"
)


def _screen_css():
    css = CSS.read_text(encoding="utf-8")
    screen, sep, _printed = css.partition(PRINT_MARKER)
    assert sep, "courses.css has no callout @media print block"
    return re.sub(r"/\*.*?\*/", "", screen, flags=re.S)


def _summary_accent(pattern):
    match = re.search(pattern, CSS.read_text(encoding="utf-8"), re.M)
    assert match, f"no summary accent matching {pattern!r}"
    return match.group(1).lower()


def _summary_blocks():
    """Every non-print `.callout--summary { ... }` body. UNANCHORED, so the
    [data-theme="dark"]-prefixed one-liner is caught too."""
    return [
        " ".join(body.split())
        for body in re.findall(r"\.callout--summary\s*\{([^}]*)\}", _screen_css())
    ]


def _anchored_block(pattern):
    match = re.search(pattern, _screen_css(), re.M)
    assert match, f"no block matching {pattern!r}"
    return " ".join(match.group(1).split())


def test_courses_css_defines_callout_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".callout",
        ".callout__header",
        ".callout__icon",
        ".callout__heading",
        ".callout__body",
        ".callout--example",
        ".callout--note",
        ".callout--tip",
        ".callout--warning",
        ".callout--task",
        ".callout--summary",
        ".callout__title",
    ]:
        assert cls in css, f"missing callout class: {cls}"


def test_callout_task_light_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    # ^-anchored: without it this pattern also matches inside the dark selector,
    # so deleting the light rule would leave the test green.
    assert re.search(
        r"^\.callout--task\s*\{\s*--callout-accent:\s*#a8318f", css, re.M
    ), "light .callout--task accent missing or changed"


def test_callout_task_dark_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(
        r'^\[data-theme="dark"\]\s+\.callout--task\s*\{\s*--callout-accent:\s*#ee9fd8',
        css,
        re.M,
    ), "dark .callout--task accent missing or changed"


def test_callout_summary_accents_are_pinned():
    """T9. The dark literal is the implementer's pick (spec 3.4); if it changes,
    change it here and in courses.css together, and re-run T9b."""
    assert _summary_accent(SUMMARY_LIGHT_ACCENT) == "#4b6b8a"
    assert _summary_accent(SUMMARY_DARK_ACCENT) == "#9db4cb"


def test_callout_summary_is_a_flat_card():
    """T9, D4: no tint, a hairline instead of the spine, a 3px accent top bar and
    no shadow in ANY summary block."""
    blocks = _summary_blocks()
    assert len(blocks) >= 3, f"expected light, dark and surface blocks: {blocks!r}"
    joined = " ".join(blocks)
    assert "border-top: 3px solid var(--callout-accent);" in joined
    assert "border-left: 1px solid var(--border-subtle);" in joined
    assert "background: var(--surface-raised);" in joined
    for block in blocks:
        assert "box-shadow" not in block, f"a summary block has a shadow: {block!r}"


def test_callout_title_overrides_the_heading_reset():
    """T9. reset.css gives headings line-height 1.15 and the house letter-spacing,
    and zeroes margins; the title must override all three explicitly."""
    block = _anchored_block(r"^\.callout__title\s*\{([^}]*)\}")
    assert "letter-spacing: normal;" in block
    assert "line-height: 1.3;" in block
    assert "margin: 0 0 var(--space-3);" in block


def test_callout_title_last_child_drops_its_bottom_margin():
    """T9. A heading-only card: .callout's padding blocks margin collapsing."""
    block = _anchored_block(r"^\.callout__title:last-child\s*\{([^}]*)\}")
    assert "margin-bottom: 0" in block


def test_callout_summary_accents_clear_3_to_1_on_both_grounds():
    """T9b, WCAG 1.4.11: the top bar is the kind's only visual identity. Its
    neighbours are the card inside and the page ground outside. Read from
    courses.css, never restated as literals here."""
    for pattern, surfaces in (
        (SUMMARY_LIGHT_ACCENT, LIGHT_SURFACES),
        (SUMMARY_DARK_ACCENT, DARK_SURFACES),
    ):
        accent = _summary_accent(pattern)
        for ground in ("--surface-raised", "--surface-base"):
            ratio = _ratio(accent, surfaces[ground])
            assert ratio >= 3.0, (
                f"summary accent {accent} on {ground} {surfaces[ground]}: "
                f"{ratio:.2f}:1 < 3:1"
            )


def test_callout_title_is_set_apart_from_body_bold():
    """Bold body text is ~1rem / 700 / --text-primary; at 1.05rem in the same colour
    the title read as one more bold phrase. The accent colour (the top bar's) and a
    larger size set it apart."""
    block = _anchored_block(r"^\.callout__title\s*\{([^}]*)\}")
    assert "font-size: 1.15rem;" in block
    assert "color: var(--callout-accent);" in block
    assert "--text-primary" not in block


def test_callout_title_accent_clears_4_5_to_1_on_the_card():
    """WCAG 1.4.3: at 1.15rem bold (18.4px) the title is just under "large text"
    (18.67px bold), so the accent needs 4.5:1 as TEXT on the card's own ground."""
    for pattern, surfaces in (
        (SUMMARY_LIGHT_ACCENT, LIGHT_SURFACES),
        (SUMMARY_DARK_ACCENT, DARK_SURFACES),
    ):
        accent = _summary_accent(pattern)
        ratio = _ratio(accent, surfaces["--surface-raised"])
        assert ratio >= 4.5, f"title {accent} on the card: {ratio:.2f}:1 < 4.5:1"
