"""A neutral border token must stay VISIBLE, and the ramp must stay ORDERED, on every
surface a hairline is actually drawn on.

The dark ramp was cut against --surface-base and nothing else. --surface-raised is
LIGHTER than base, and --border-default (#322E29) landed almost exactly on it
(#2C2925) — 1.07:1, and 1.04:1 once a callout's 6% tint lifted the ground further.
So a table's grid lines disappeared inside a callout, and on every raised card the
ramp inverted: "subtle" read more strongly than "default". This test is that lesson.

The floors are deliberately per-theme, not symmetric. Light is faint (1.15:1 at worst)
but correctly ordered, and no one has reported it; holding light to the dark floors
would be a restyle, not a bugfix.
"""

import re

from tests.test_text_colour_css import CSS
from tests.test_text_colour_css import DARK_SURFACES
from tests.test_text_colour_css import LIGHT_SURFACES
from tests.test_text_colour_css import TOKENS
from tests.test_text_colour_css import _block
from tests.test_text_colour_css import _ratio

RUNGS = ("subtle", "default", "strong")

# The surfaces a NEUTRAL border token is actually painted on.
#
# The three semantic panels in the text-colour surface list (--danger-subtle,
# --success-subtle, --warning-subtle) are deliberately absent. Exactly two rules put a
# neutral token on one of them — .badge--done and .badge--review — and both color-mix
# it 40-45% toward the semantic colour first, so the bare token never renders there.
# Including them reports an inversion in light mode that nothing on screen can show.
BORDER_GROUNDS = (
    "--surface-raised",
    "--surface-base",
    "--surface-sunken",
    "callout-example",
    "callout-note",
    "callout-tip",
    "callout-warning",
    "callout-task",
)

# Chosen strength: restrained. --border-default clears ~1.7:1 on a raised card, which
# is the weight light mode already carries on white, rather than a wireframe look.
DARK_FLOORS = {"subtle": 1.15, "default": 1.50, "strong": 2.10}


def _ramp(selector):
    """The three neutral border tokens declared under one theme selector."""
    block = _block(TOKENS.read_text(encoding="utf-8"), selector)
    values = {}
    for rung in RUNGS:
        match = re.search(rf"--border-{rung}:\s*(#[0-9A-Fa-f]{{6}})", block)
        assert match, f"{selector} does not define --border-{rung}"
        values[rung] = match.group(1)
    return values


def _grounds(surfaces):
    return {name: surfaces[name] for name in BORDER_GROUNDS}


def test_border_grounds_all_exist_in_the_measured_surface_lists():
    """BORDER_GROUNDS names must resolve in both lists, or the sweep below is hollow —
    a typo'd key would otherwise silently measure nothing."""
    for label, surfaces in (("LIGHT", LIGHT_SURFACES), ("DARK", DARK_SURFACES)):
        missing = [name for name in BORDER_GROUNDS if name not in surfaces]
        assert not missing, f"{label}_SURFACES has no entry for: {missing}"


def test_both_themes_define_the_whole_ramp():
    for selector in (":root", '[data-theme="dark"]'):
        assert set(_ramp(selector)) == set(RUNGS)


def test_the_ramp_never_inverts_on_any_surface_it_is_drawn_on():
    """subtle <= default <= strong, measured — not assumed from the hex values.

    Ordering by luminance alone is what broke: against a ground BETWEEN two rungs the
    darker token wins, so the ladder has to be checked per surface.
    """
    failures = []
    for selector, surfaces in (
        (":root", LIGHT_SURFACES),
        ('[data-theme="dark"]', DARK_SURFACES),
    ):
        ramp = _ramp(selector)
        for name, ground in _grounds(surfaces).items():
            ratios = [_ratio(ramp[rung], ground) for rung in RUNGS]
            if not (ratios[0] <= ratios[1] <= ratios[2]):
                failures.append(
                    f"{selector} on {name} {ground}: "
                    + ", ".join(
                        f"{rung} {ramp[rung]} {r:.2f}:1"
                        for rung, r in zip(RUNGS, ratios, strict=True)
                    )
                )
    assert not failures, "border ramp inverts:\n" + "\n".join(failures)


def test_dark_ramp_clears_its_floor_on_every_surface():
    ramp = _ramp('[data-theme="dark"]')
    failures = []
    for name, ground in _grounds(DARK_SURFACES).items():
        for rung in RUNGS:
            ratio = _ratio(ramp[rung], ground)
            if ratio < DARK_FLOORS[rung]:
                failures.append(
                    f"--border-{rung} {ramp[rung]} on {name} {ground}: "
                    f"{ratio:.2f}:1 < {DARK_FLOORS[rung]}:1"
                )
    assert not failures, "dark border ramp below floor:\n" + "\n".join(failures)


def test_table_grid_still_resolves_to_a_neutral_border_token():
    """The reported symptom. If the grid stops using the ramp, the guard above stops
    protecting the thing that was actually broken."""
    css = CSS.read_text(encoding="utf-8")
    match = re.search(
        r"\.el--table--border-grid th,\s*\.el--table--border-grid td\s*\{([^}]*)\}", css
    )
    assert match, "no .el--table--border-grid cell rule in courses.css"
    assert re.search(
        r"border:\s*1px solid var\(--border-(subtle|default|strong)\)", match.group(1)
    ), f"table grid no longer draws with a neutral border token: {match.group(1)!r}"
