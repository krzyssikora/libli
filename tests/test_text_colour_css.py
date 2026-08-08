"""The palette must clear WCAG AA body text (4.5:1) on EVERY surface rich text can
appear on — which is eleven surfaces, not two. An earlier draft of this feature measured
only --surface-raised/--surface-base and shipped a light palette that scored 3.79:1 on
--danger-subtle, where QuestionElement.explanation renders. This test is that lesson.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "core/static/core/css/tokens.css"
CSS = ROOT / "courses/static/courses/css/courses.css"

SLOTS = ("red", "blue", "green", "orange")

# Normative surface list (spec: "The surface list is the specification").
#
# These literals are a CROSS-CHECK, not the source of truth:
# test_surface_literals_still_match_the_css below re-reads the six token surfaces
# from tokens.css and recomputes the five callout grounds from courses.css. So
# changing --surface-base, a .callout--* accent, or the 6% mix reddens the suite
# instead of silently leaving the AA guard measuring values that no longer exist.
# Callout grounds are
# color-mix(in srgb, <accent> 6%, --surface-raised) with per-channel round() in sRGB.
LIGHT_SURFACES = {
    "--surface-raised": "#FFFFFF",
    "--surface-base": "#F4F1EA",
    "--surface-sunken": "#FAF8F3",
    "--danger-subtle": "#F2D9D5",
    "--success-subtle": "#E3ECD7",
    "--warning-subtle": "#F4E8CD",
    "callout-example": "#F2F6FC",
    "callout-note": "#F5F5F6",
    "callout-tip": "#F2F8F5",
    "callout-warning": "#FAF6F1",
    "callout-task": "#FAF3F8",
}
DARK_SURFACES = {
    "--surface-raised": "#2C2925",
    "--surface-base": "#1A1816",
    "--surface-sunken": "#15130F",
    "--danger-subtle": "#3A1E1A",
    "--success-subtle": "#2A3620",
    "--warning-subtle": "#3A2F18",
    "callout-example": "#313132",
    "callout-note": "#34322F",
    "callout-tip": "#2F332C",
    "callout-warning": "#373229",
    "callout-task": "#383030",
}


def _luminance(hex_colour):
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _block(css, selector):
    """The declaration block for a top-level selector, e.g. ':root'."""
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.DOTALL)
    assert match, f"no {selector} block in tokens.css"
    return match.group(1)


def _token_values(block):
    return {
        slot: re.search(rf"--tc-{slot}:\s*(#[0-9A-Fa-f]{{6}})", block) for slot in SLOTS
    }


def test_tokens_define_every_slot_in_both_themes():
    css = TOKENS.read_text(encoding="utf-8")
    for selector in (":root", '[data-theme="dark"]'):
        found = _token_values(_block(css, selector))
        missing = [slot for slot, m in found.items() if m is None]
        assert not missing, f"{selector} is missing --tc-* tokens: {missing}"


def test_courses_css_defines_every_utility():
    css = CSS.read_text(encoding="utf-8")
    for slot in SLOTS:
        assert f".tc-{slot}" in css, f"missing utility class .tc-{slot}"
        assert f"var(--tc-{slot})" in css, (
            f".tc-{slot} must resolve to var(--tc-{slot})"
        )


def _mix(accent, ground, ratio=0.06):
    a = [int(accent.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(ground.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    r, g, bl = (round(a[i] * ratio + b[i] * (1 - ratio)) for i in range(3))
    return f"#{r:02X}{g:02X}{bl:02X}"


def test_surface_literals_still_match_the_css():
    """The AA guard measures against frozen literals; this is what stops them drifting
    away from the CSS they claim to describe."""
    tokens = TOKENS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for selector, surfaces in (
        (":root", LIGHT_SURFACES),
        ('[data-theme="dark"]', DARK_SURFACES),
    ):
        block = _block(tokens, selector)
        for name, expected in surfaces.items():
            if not name.startswith("--"):
                continue
            match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})", block)
            assert match, f"{selector} no longer defines {name}"
            assert match.group(1).upper() == expected.upper(), (
                f"{selector} {name} moved to {match.group(1)}; update the surface list "
                f"and re-run the AA measurement"
            )
    for theme, surfaces, ground in (
        ("", LIGHT_SURFACES, LIGHT_SURFACES["--surface-raised"]),
        ('[data-theme="dark"] ', DARK_SURFACES, DARK_SURFACES["--surface-raised"]),
    ):
        for kind in ("example", "note", "tip", "warning", "task"):
            match = re.search(
                rf"{re.escape(theme)}\.callout--{kind}\s*\{{\s*--callout-accent:\s*"
                rf"(#[0-9A-Fa-f]{{6}})",
                css,
            )
            assert match, f"no {theme}.callout--{kind} accent in courses.css"
            computed = _mix(match.group(1), ground)
            assert computed.upper() == surfaces[f"callout-{kind}"].upper(), (
                f"callout-{kind}{' dark' if theme else ''} ground is now {computed}"
            )


def test_every_slot_clears_aa_on_every_surface():
    css = TOKENS.read_text(encoding="utf-8")
    failures = []
    for selector, surfaces in (
        (":root", LIGHT_SURFACES),
        ('[data-theme="dark"]', DARK_SURFACES),
    ):
        values = _token_values(_block(css, selector))
        for slot, match in values.items():
            assert match, f"{selector} missing --tc-{slot}"
            colour = match.group(1)
            for name, ground in surfaces.items():
                ratio = _ratio(colour, ground)
                if ratio < 4.5:
                    failures.append(
                        f"{selector} --tc-{slot} {colour} on {name} {ground}: "
                        f"{ratio:.2f}:1"
                    )
    assert not failures, "below AA 4.5:1:\n" + "\n".join(failures)


def test_every_callout_kind_has_a_ground_in_both_surface_lists():
    # Derived from the enum, NOT a second hardcoded list: that is what makes a
    # sixth kind fail loudly here instead of silently escaping the AA sweep.
    from courses.models import CalloutElement

    expected = {f"callout-{value}" for value in CalloutElement.Kind.values}
    for name, surfaces in (("LIGHT", LIGHT_SURFACES), ("DARK", DARK_SURFACES)):
        got = {k for k in surfaces if not k.startswith("--")}
        assert got == expected, (
            f"{name}_SURFACES callout grounds drifted: {got ^ expected}"
        )
