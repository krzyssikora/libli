# Text Colour (Slice 1 — Feature) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authors apply a fixed four-colour palette to rich text and table cells, with KaTeX maths resolving to the same palette in both themes.

**Architecture:** Colour is a `tc-*` class on an inline element — never inline style — mirroring the shipped `ta-*` alignment mechanism. One canonical colour map (`(r,g,b)` triple → slot) is defined in Python and mirrored in JS, consumed by the editor, by a KaTeX post-render pass, and (in slice 2) by the backfill. The sanitiser stays purely subtractive; all HTML rewriting happens in the browser where a real parser exists.

**Tech Stack:** Django templates, vanilla ES5-style JS (no build step), nh3 sanitiser, KaTeX, Playwright/pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-text-colour-design.md` — read it before starting. This plan implements **slice 1 only**. Slice 2 (the `recolour_imported_content` backfill) gets its own plan.

## Global Constraints

- **Tooling:** `ruff`/`pytest`/`python` are NOT on PATH. Always `uv run ruff …`, `uv run pytest …`. `uv run ruff format --check .` must pass before every commit.
- **e2e tests:** `-m e2e` is **mandatory** or e2e tests are silently deselected (pytest exits 5). Always `uv run pytest tests/test_e2e_*.py -m e2e`.
- **Never run two pytest invocations at once** — concurrent runs collide on the Postgres `test_libli` database.
- **Falsify every test.** After a test passes, delete or invert the thing it guards, re-run, and confirm it goes RED. A passing test proves nothing on its own. Restore afterwards.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **Django multi-line comments** must use `{% comment %}…{% endcomment %}`; `{# #}` is single-line only.
- **Prose in source is load-bearing:** `tests/test_element_state_write_routes.py` regexes raw source including comments. Do not write the words `element_state` in a comment in `courses/views.py`.
- **i18n:** run `uv run python manage.py makemessages -l pl -l en --no-obsolete`. Both catalogues, always. Never leave a `#, fuzzy` entry — clearing one means deleting **two** lines (`#, fuzzy` and `#| msgid`).
- **Palette values are normative and coupled.** `--tc-red` light and `--danger-subtle` sit at a 4.51:1 margin. Neither may be changed without re-running the ten-surface measurement in Task 1.
- **Colour slots:** exactly `tc-red`, `tc-blue`, `tc-green`, `tc-orange`. No others.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/static/core/css/tokens.css` | *modify* — add the four `--tc-*` tokens to `:root` and `[data-theme="dark"]` |
| `courses/static/courses/css/courses.css` | *modify* — add `.tc-*` utilities beside `.ta-*` |
| `courses/static/courses/css/editor.css` | *modify* — `.rte-swatch` styling and its `.is-on` ring |
| `courses/colour.py` | **new** — the single Python home for the palette contract: slot table, `normalise_colour()`, `parse_style_colour()`. Imported by `sanitize.py` and (slice 2) the backfill |
| `courses/sanitize.py` | *modify* — allow `span` + `tc-*` classes; add frozen `LEGACY_*` snapshots for slice 2 |
| `courses/static/courses/js/text_colour.js` | **new** — `window.libliColour`: MAP, `normaliseColour`, `apply`, `mapColours`, `tidyPastedSpans`, `activeSlot`, region test, KaTeX wrappers |
| `templates/courses/manage/editor/_rte_swatches.html` | **new** — the five swatch controls, included by all four RTE toolbars |
| 4 RTE toolbar templates + 2 table toolbar templates | *modify* — include the swatch partial |
| `courses/static/courses/js/text_toolbar.js` | *modify* — wire the RTE surface |
| `courses/static/courses/js/table_editor.js`, `filltable_editor.js` | *modify* — wire the two cell editors |
| 5 KaTeX-loading templates | *modify* — load `text_colour.js` after `auto-render.min.js`, before any caller |

---

### Task 0: Branch off an up-to-date master

**Files:** none.

**Interfaces:**
- Consumes: nothing.
- Produces: a clean `text-colour-palette` branch — the branch Task 12 pushes. Without
  this, all twelve commits land on whatever was checked out (an unrelated shipped
  feature) and the push in Task 12 either fails or pushes the wrong history.

- [ ] **Step 1: Fetch and branch**

```bash
git fetch origin
git checkout -b text-colour-palette origin/master
git branch --show-current
```

Expected: `text-colour-palette`.

If the branch already exists (this plan was written on it), verify instead:

```bash
git branch --show-current          # must print text-colour-palette
git log --oneline -1 origin/master # note the base; master moves often in this repo
```

- [ ] **Step 2: Confirm the worktree is clean**

```bash
git status --porcelain
```

Expected: empty, or only this plan/spec. A dirty tree here means another session is
using this worktree — resolve that before starting.

---

### Task 1: Palette tokens, `.tc-*` utilities, and the ten-surface contrast guard

**Files:**
- Modify: `core/static/core/css/tokens.css`
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_text_colour_css.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: CSS custom properties `--tc-red`, `--tc-blue`, `--tc-green`, `--tc-orange` (both themes); utility classes `.tc-red`, `.tc-blue`, `.tc-green`, `.tc-orange`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_text_colour_css.py`:

```python
"""The palette must clear WCAG AA body text (4.5:1) on EVERY surface rich text can
appear on — which is ten surfaces, not two. An earlier draft of this feature measured
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
# from tokens.css and recomputes the four callout grounds from courses.css. So
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
        for kind in ("example", "note", "tip", "warning"):
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
```

- [ ] **Step 2: Run the test to verify it fails**

```
uv run pytest tests/test_text_colour_css.py -v
```

Expected: **3 failed** — `test_tokens_define_every_slot_in_both_themes` with
`:root is missing --tc-* tokens: [...]`, `test_courses_css_defines_every_utility` on the
missing `.tc-*` classes, and `test_every_slot_clears_aa_on_every_surface` on its
`assert match`. All three are expected; nothing else is wrong.

- [ ] **Step 3: Add the tokens**

In `core/static/core/css/tokens.css`, inside the `:root` block, immediately after the
`--danger:  #A8392E; --danger-subtle:  #F2D9D5;` line:

```css
  /* Author-selectable text colour. Independent of --danger/--success/--warning
     despite some dark values coinciding: those are UI accents and may move for
     UI reasons; these are body-text colours measured against ten surfaces
     (see tests/test_text_colour_css.py). Light red and --danger-subtle sit at a
     4.51:1 margin — neither moves without re-running that test. */
  --tc-red: #B2372A; --tc-blue: #1F61AD; --tc-green: #3F6B24; --tc-orange: #8A5514;
```

In the `[data-theme="dark"]` block, immediately after the
`--danger:  #E57373; --danger-subtle:  #3A1E1A;` line:

```css
  --tc-red: #EA8A82; --tc-blue: #8FBCE8; --tc-green: #9FBF7B; --tc-orange: #E8B761;
```

- [ ] **Step 4: Add the utilities**

In `courses/static/courses/css/courses.css`, immediately after the `.va-bottom` line
(currently 934):

```css
.tc-red { color: var(--tc-red); }
.tc-blue { color: var(--tc-blue); }
.tc-green { color: var(--tc-green); }
.tc-orange { color: var(--tc-orange); }
```

- [ ] **Step 5: Run the tests to verify they pass**

```
uv run pytest tests/test_text_colour_css.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Falsify**

Temporarily change `--tc-red` in the `:root` block to `#E57373` (the dark-theme value)
and re-run. Expected: `test_every_slot_clears_aa_on_every_surface` FAILS listing several
surfaces. Restore `#B2372A` and confirm green again.

- [ ] **Step 7: Commit**

```bash
uv run ruff format .
git add core/static/core/css/tokens.css courses/static/courses/css/courses.css tests/test_text_colour_css.py
git commit -m "feat(text-colour): four-slot palette tokens, AA-measured on ten surfaces"
```

---

### Task 2: `courses/colour.py` — the canonical colour map

**Files:**
- Create: `courses/colour.py`
- Test: `courses/tests/test_colour_map.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TC_CLASS_VALUES: set[str]` — `{"tc-red", "tc-blue", "tc-green", "tc-orange"}`
  - `TC_CLASS_TAGS: set[str]` — `{"span", "b", "i", "em", "strong", "u", "a"}`
  - `SLOTS: dict[tuple[int, int, int], str]` — canonical triple → slot name
  - `normalise_colour(value: str) -> tuple[int, int, int] | None`
  - `parse_style_colour(style: str) -> tuple[int, int, int] | None`
  - `SENTINEL_RGB: tuple[int, int, int]` — `(1, 2, 3)`

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_colour_map.py`:

```python
from courses.colour import SENTINEL_RGB
from courses.colour import SLOTS
from courses.colour import normalise_colour
from courses.colour import parse_style_colour


def test_accepts_all_four_input_forms():
    assert normalise_colour("#B2372A") == (178, 55, 42)
    assert normalise_colour("#f00") == (255, 0, 0)
    assert normalise_colour("rgb(178, 55, 42)") == (178, 55, 42)
    assert normalise_colour("rgba(178, 55, 42, 0.5)") == (178, 55, 42)
    assert normalise_colour("red") == (255, 0, 0)


def test_slot_lookup_covers_light_dark_and_keyword_for_every_slot():
    for slot, values in {
        "red": ("#B2372A", "#EA8A82", "red"),
        "blue": ("#1F61AD", "#8FBCE8", "blue"),
        "green": ("#3F6B24", "#9FBF7B", "green"),
        "orange": ("#8A5514", "#E8B761", "orange"),
    }.items():
        for value in values:
            assert SLOTS[normalise_colour(value)] == slot, f"{value} -> {slot}"


def test_unmapped_colour_has_no_slot():
    assert normalise_colour("purple") not in SLOTS
    assert normalise_colour("#123456") not in SLOTS


def test_sentinel_is_unmapped():
    """Clearing colour applies the sentinel, then drops it. If it ever gained a slot,
    Clear would silently recolour instead of clearing."""
    assert SENTINEL_RGB not in SLOTS
    assert normalise_colour("rgb(1, 2, 3)") == SENTINEL_RGB


def test_garbage_returns_none():
    for value in ("", "   ", "not-a-colour", "rgb(1,2)", None):
        assert normalise_colour(value) is None


def test_parse_style_requires_the_exact_color_property():
    """background-color is the trap: an unanchored `color:` search matches it and
    invents a text colour that does not exist. Measured on the LAL corpus."""
    assert parse_style_colour("color: red") == (255, 0, 0)
    assert parse_style_colour("color:red") == (255, 0, 0)  # no space
    assert parse_style_colour("COLOR : red ;") == (255, 0, 0)  # case + spaces
    assert parse_style_colour("background-color: red") is None
    assert parse_style_colour("border-color: red") is None
    assert parse_style_colour("height: 1em; color: blue;") == (0, 0, 255)
    assert parse_style_colour("height: 1em") is None
    assert parse_style_colour("") is None
```

- [ ] **Step 2: Run the test to verify it fails**

```
uv run pytest courses/tests/test_colour_map.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'courses.colour'`.

- [ ] **Step 3: Write the implementation**

Create `courses/colour.py`:

```python
"""The one canonical definition of the author-selectable text palette.

Colour reaches this module in three vocabularies — a hex literal from the token
file, an `rgb(...)` serialisation read back out of the DOM, and a CSS keyword from
imported markup — so everything is keyed on a canonical (r, g, b) triple. A map
keyed on source-form literals would match nothing on the JS paths, because browsers
always serialise `el.style.color` as `rgb(...)`.

Mirrored in courses/static/courses/js/text_colour.js; tests/test_colour_map_drift.py
holds the two copies together.
"""

import re

TC_CLASS_VALUES = {"tc-red", "tc-blue", "tc-green", "tc-orange"}

# Tags allowed to carry a tc-* class. span is the normal carrier; the inline
# emphasis tags are here because execCommand("foreColor") may colour an existing
# wrapper instead of creating a span, and `a` because a selection covering a link's
# text commonly styles the <a> itself -- without it the colour would be stripped on
# save with no feedback.
TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}

# Applied by the Clear control, then dropped. Must be a colour the browser accepts
# (inherit/unset are rejected or inconsistent across engines), must not collide with
# any mapped triple, and must be one no author would plausibly type.
SENTINEL_RGB = (1, 2, 3)

_PALETTE = {
    "red": ("#B2372A", "#EA8A82", "red"),
    "blue": ("#1F61AD", "#8FBCE8", "blue"),
    "green": ("#3F6B24", "#9FBF7B", "green"),
    "orange": ("#8A5514", "#E8B761", "orange"),
}

_KEYWORDS = {
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
    "green": (0, 128, 0),
    "orange": (255, 165, 0),
}

_HEX = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6})$")
_RGB = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,[^)]*)?\)$")


def normalise_colour(value):
    """Any accepted colour form -> an (r, g, b) triple, or None."""
    if not value:
        return None
    text = str(value).strip().lower()
    if text in _KEYWORDS:
        return _KEYWORDS[text]
    if _HEX.match(text):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
    match = _RGB.match(text)
    if match:
        channels = tuple(int(g) for g in match.groups())
        return channels if all(c <= 255 for c in channels) else None
    return None


def _build_slots():
    slots = {}
    for slot, values in _PALETTE.items():
        for value in values:
            triple = normalise_colour(value)
            assert triple is not None, f"unparseable palette value {value!r}"
            slots[triple] = slot
    return slots


SLOTS = _build_slots()


def parse_style_colour(style):
    """The `color` declaration's value from a style attribute, canonicalised.

    Property matching is EXACT, never a suffix: an unanchored `color:` search also
    matches `background-color:` and `border-color:`, which would invent a text
    colour the author never set. The LAL corpus contains both.
    """
    if not style:
        return None
    for declaration in str(style).split(";"):
        name, sep, value = declaration.partition(":")
        if not sep:
            continue
        if name.strip().lower() != "color":
            continue
        return normalise_colour(value)
    return None


# NOTE: slot_for_style() -- the obvious SLOTS.get(parse_style_colour(style)) helper --
# is deliberately NOT defined here. Nothing in slice 1 calls it; it belongs to slice 2's
# backfill and arrives with slice 2's tests.
```

- [ ] **Step 4: Run the test to verify it passes**

```
uv run pytest courses/tests/test_colour_map.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Falsify**

Change `parse_style_colour`'s `if name.strip().lower() != "color":` to
`if "color" not in name.strip().lower():` — keep the `.strip().lower()`, so the mutation
isolates the substring risk. (Dropping it too makes the test fail one assertion earlier on
case-handling, and the `background-color` assertion is then never reached — MEASURED.)
Re-run. Expected: `test_parse_style_requires_the_exact_color_property` FAILS on
`assert parse_style_colour("background-color: red") is None`, showing `(255, 0, 0)`.
Restore.

- [ ] **Step 6: Commit**

```bash
uv run ruff format .
uv run ruff check courses/colour.py courses/tests/test_colour_map.py
git add courses/colour.py courses/tests/test_colour_map.py
git commit -m "feat(text-colour): canonical (r,g,b) colour map with exact declaration parsing"
```

---

### Task 3: Sanitiser — allow `tc-*` classes, and freeze the legacy snapshot

**Files:**
- Modify: `courses/sanitize.py`
- Modify: `courses/tests/test_sanitize_align.py` (line 34 — must be updated, not preserved)
- Test: `courses/tests/test_sanitize_colour.py` (create)

**Interfaces:**
- Consumes: `courses.colour.TC_CLASS_VALUES`, `TC_CLASS_TAGS`.
- Produces: `sanitize_html` and `sanitize_cell` preserve `class="tc-*"` on `TC_CLASS_TAGS`;
  `LEGACY_ALLOWED_CLASSES` and `LEGACY_CELL_ALLOWED_CLASSES` (frozen pre-change snapshots,
  consumed by slice 2's key generator).

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_sanitize_colour.py`:

```python
from courses.colour import TC_CLASS_TAGS
from courses.sanitize import ALIGN_CLASS_VALUES
from courses.sanitize import LEGACY_ALLOWED_CLASSES
from courses.sanitize import LEGACY_CELL_ALLOWED_CLASSES
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html


def test_body_keeps_tc_class_on_every_allowed_carrier():
    for tag in sorted(TC_CLASS_TAGS):
        attrs = ' href="/x/"' if tag == "a" else ""
        out = sanitize_html(f'<{tag}{attrs} class="tc-red">x</{tag}>')
        assert "tc-red" in out, f"{tag} lost its colour class: {out}"


def test_body_strips_tc_class_on_a_tag_outside_the_carrier_set():
    assert "tc-red" not in sanitize_html('<p class="tc-red">x</p>')


def test_body_strips_a_foreign_class_and_all_inline_style():
    out = sanitize_html('<span class="evil" style="color: red">x</span>')
    assert "evil" not in out
    assert "style" not in out


def test_cell_keeps_tc_class():
    assert "tc-blue" in sanitize_cell('<b class="tc-blue">x</b>')
    assert "tc-blue" in sanitize_cell('<span class="tc-blue">x</span>')


def test_cell_does_not_allow_tc_on_br():
    """br is in CELL_TAGS but not TC_CLASS_TAGS, so it must not gain a class key."""
    assert "tc-red" not in sanitize_cell('<br class="tc-red">')


def test_both_paths_are_idempotent():
    for sanitise in (sanitize_html, sanitize_cell):
        once = sanitise('<span class="tc-green">x</span>')
        assert sanitise(once) == once


def test_cell_still_protects_maths_spans():
    assert sanitize_cell(r"\(a<b\)") == r"\(a&lt;b\)"


def test_align_values_are_not_mutated_by_the_colour_merge():
    """ALLOWED_CLASSES was built by a comprehension binding ONE set object to seven
    keys. Any in-place merge would widen the align family for every tag at once."""
    assert ALIGN_CLASS_VALUES == {"ta-left", "ta-center", "ta-right"}


def test_allowlist_entries_are_not_shared_objects():
    """Same aliasing trap, one level down: two keys must not be the same set."""
    from courses.sanitize import ALLOWED_CLASSES
    from courses.sanitize import CELL_ALLOWED_CLASSES

    for mapping in (ALLOWED_CLASSES, CELL_ALLOWED_CLASSES):
        sets = list(mapping.values())
        for i, first in enumerate(sets):
            for second in sets[i + 1 :]:
                assert first is not second, "allowlist entries share one set object"


def test_legacy_snapshot_excludes_the_colour_family():
    """Slice 2's key generator replays the PRE-colour sanitiser: the DB holds
    <strong>x</strong>, but post-change nh3 emits <strong class=""> for a tag that is
    an allowed_classes key. Freezing the old allowlist is what keeps keys matching."""
    # Pin the exact key set: an emptiness-only check passes vacuously for {} and would
    # absorb a drift instead of catching it.
    assert set(LEGACY_ALLOWED_CLASSES) == {
        "p",
        "div",
        "h2",
        "h3",
        "h4",
        "blockquote",
        "li",
    }
    assert LEGACY_CELL_ALLOWED_CLASSES == {}
    for values in LEGACY_ALLOWED_CLASSES.values():
        assert values == {"ta-left", "ta-center", "ta-right"}
        assert not any(v.startswith("tc-") for v in values)
```

- [ ] **Step 2: Run the test to verify it fails**

```
uv run pytest courses/tests/test_sanitize_colour.py -v
```

Expected: collection error — `ImportError: cannot import name 'LEGACY_ALLOWED_CLASSES'`.

- [ ] **Step 3: Modify the sanitiser**

In `courses/sanitize.py`, add the import at the top (after `import nh3`):

```python
from courses.colour import TC_CLASS_TAGS
from courses.colour import TC_CLASS_VALUES
```

Add `"span"` to `ALLOWED_TAGS` — insert after the `"div",` entry:

```python
    # Colour carrier. Purely a class hook: no attribute beyond a token-allowlisted
    # class is permitted, so this widens the subset by nothing else.
    "span",
```

Replace the `ALLOWED_CLASSES` assignment (currently line 45) with:

```python
# The pre-colour allowlist, frozen. Slice 2's backfill builds its lookup keys by
# replaying the sanitiser AS IT BEHAVED AT IMPORT TIME: nh3 deletes the class
# attribute for a tag that is not an allowed_classes key, but emits an empty
# class="" for one that is. Adding strong/b/i/u/a/span below therefore moves every
# such key off the value the loader actually stored. MEASURED:
#   <strong class="x">y</strong>  ->  <strong>y</strong>          (before)
#                                 ->  <strong class="">y</strong> (after)
# Frozen as a literal, not derived from the live constants, so a later edit to the
# live allowlist cannot silently move the keys.
LEGACY_ALLOWED_CLASSES = {
    "p": {"ta-left", "ta-center", "ta-right"},
    "div": {"ta-left", "ta-center", "ta-right"},
    "h2": {"ta-left", "ta-center", "ta-right"},
    "h3": {"ta-left", "ta-center", "ta-right"},
    "h4": {"ta-left", "ta-center", "ta-right"},
    "blockquote": {"ta-left", "ta-center", "ta-right"},
    "li": {"ta-left", "ta-center", "ta-right"},
}
# sanitize_cell passed NO allowed_classes before this change, so the legacy cell
# behaviour is "no tag is an allowed_classes key" -- deliberately empty, not an
# oversight.
LEGACY_CELL_ALLOWED_CLASSES = {}

# Two independent families merged into one mapping. ALIGN_CLASS_TAGS and
# TC_CLASS_TAGS are currently DISJOINT, so no tag needs a union -- but every entry
# is a fresh set() regardless, because the previous comprehension bound one shared
# set object to all seven keys and any in-place merge would have widened the align
# family for every tag at once.
ALLOWED_CLASSES = {tag: set(ALIGN_CLASS_VALUES) for tag in ALIGN_CLASS_TAGS}
ALLOWED_CLASSES.update({tag: set(TC_CLASS_VALUES) for tag in TC_CLASS_TAGS})
```

Add `"span"` to `CELL_TAGS` and define the cell allowlist — replace the `CELL_TAGS`
assignment with:

```python
# Cells allow only inline emphasis + line break + the colour carrier. Includes b/i
# (not just strong/em) because document.execCommand("bold"/"italic") emits <b>/<i>.
CELL_TAGS = {"strong", "b", "em", "i", "u", "br", "span"}

# Only cell tags that may carry colour -- br is in CELL_TAGS but not TC_CLASS_TAGS,
# and the block-tag alignment family has no business in a cell.
CELL_ALLOWED_CLASSES = {tag: set(TC_CLASS_VALUES) for tag in CELL_TAGS & TC_CLASS_TAGS}
```

In `sanitize_cell`, pass the new allowlist to `nh3.clean` — change:

```python
    cleaned = nh3.clean(
        protected,
        tags=CELL_TAGS,
        attributes={},
```

to:

```python
    cleaned = nh3.clean(
        protected,
        tags=CELL_TAGS,
        attributes={},
        allowed_classes=CELL_ALLOWED_CLASSES,
```

- [ ] **Step 3b: Record the newly-widened marker hole**

Allowing `span` widens what survives inside a `{{...}}` marker on the **server** path.
MEASURED against the real `sanitize_html`:

```
before:  {{<span>a</span>|b}}  ->  {{a|b}}               (span stripped; answer clean)
after:   {{<span>a</span>|b}}  ->  {{<span>a</span>|b}}  (markup becomes the answer)
```

D10's `apply()` refusal is a **client-side** guard, so the HTML source view, a no-JS
save, and an import all bypass it. Slice 1 does not close this: closing it means
stripping tags inside markers in the parser, which changes fill-blank parsing and needs
its own change. Add a test that records the behaviour as knowingly accepted, so the next
reader finds a decision rather than a surprise — append to
`courses/tests/test_sanitize_colour.py`:

```python
def test_marker_interior_markup_is_knowingly_accepted():
    """Allowing span widened what survives inside {{...}}. The editor refuses to
    produce this (D10), but the server path does not reject it. Recorded, not fixed.
    If this ever fails, someone closed the hole — update the spec's D10 section.
    """
    assert "<span>" in sanitize_html("<p>{{<span>a</span>|b}}</p>")
```

- [ ] **Step 4: Update the align test that can no longer pass**

`courses/tests/test_sanitize_align.py:34` currently asserts
`assert "class" not in sanitize_cell('<b class="ta-center">x</b>')`.

Once `b` is an `allowed_classes` key, nh3 emits `<b class="">x</b>` — the attribute
survives with an empty value. It lives in `test_cell_and_label_stay_class_free`, whose name the new assertion
contradicts — cells no longer stay class-free. **Rename the function to
`test_cell_drops_align_token_and_label_stays_class_free`** and replace that line with:

```python
    # nh3 filters class TOKENS; it cannot unwrap or delete the attribute once the tag
    # is an allowed_classes key, so a disallowed class leaves class="" behind. What
    # matters is that the align token is gone from a tag that may not carry it.
    assert "ta-center" not in sanitize_cell('<b class="ta-center">x</b>')
```

- [ ] **Step 5: Run the tests to verify they pass**

```
uv run pytest courses/tests/test_sanitize_colour.py courses/tests/test_sanitize_align.py   tests/test_richtext.py tests/test_table_sanitize.py tests/lal_import/   tests/test_filltable_model.py tests/test_spanning_roundtrip.py   tests/test_table_transfer.py -v
```

Expected: all pass. Two things to expect rather than be surprised by:

- **Adding `span` to `CELL_TAGS` changes stored cell HTML.** MEASURED:
  `<span class="myequation">a</span>` used to store as `a` and now stores as
  `<span class="">a</span>`; a bare `<span>x</span>` used to vanish and now survives.
  That is why `tests/lal_import/`, `test_filltable_model.py`,
  `test_spanning_roundtrip.py` and `test_table_transfer.py` are in the run list — they
  assert exact cell `html`.
- **Two comments elsewhere carry justifications this change falsifies.**
  `tests/test_e2e_imagezoom.py:544` spells out "CELL_TAGS = {strong, b, em, i, u, br}"
  — both the set and its line reference are wrong after this task, and that file is
  not in the run list so nothing surfaces it. (`tests/test_richtext.py:335`'s
  "CELL_TAGS has no `<a>`" stays true — `a` is not added to `CELL_TAGS`.) And
  **`tests/lal_import/test_tables.py:169` carries a comment this change falsifies** — it
  justifies an accepted behaviour with "`span` is not in sanitize_cell's CELL_TAGS".
  Update that comment here; a stale justification is how the next reader concludes the
  wrong thing.

If `tests/test_richtext.py` fails, read the failure before changing anything —
`test_sanitiser_passes_internal_links_through_untouched` is load-bearing for the
internal-link feature and must stay green.

- [ ] **Step 6: Falsify**

Remove `"span"` from `ALLOWED_TAGS` and re-run `courses/tests/test_sanitize_colour.py`.
Expected: `test_body_keeps_tc_class_on_every_allowed_carrier` FAILS for `span`. Restore.

Then change `ALLOWED_CLASSES.update(...)` to use `TC_CLASS_VALUES` directly instead of
`set(TC_CLASS_VALUES)` and re-run. Expected:
`test_allowlist_entries_are_not_shared_objects` FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
uv run ruff format .
git add courses/sanitize.py courses/tests/test_sanitize_colour.py courses/tests/test_sanitize_align.py
git commit -m "feat(text-colour): allow tc-* classes through both sanitisers; freeze legacy allowlist"
```

---

### Task 4: Measure what the browser actually emits

This task writes no production code. It resolves the spec's Unknowns #1 and #2, whose
answers determine the next three tasks. Do not skip it — two earlier drafts of the spec
were wrong about exactly these behaviours.

**Files:**
- Create: `tests/test_e2e_colour_probe.py` (temporary — deleted at the end of this task)

**Interfaces:**
- Consumes: nothing.
- Produces: a recorded measurement, pasted into the plan's Task 5/6 notes and into the
  spec's Unknowns section.

- [ ] **Step 1: Write the probe**

Create `tests/test_e2e_colour_probe.py`:

```python
"""Throwaway probe. Records what execCommand and KaTeX actually emit, so Tasks 5-7
are written against measurement rather than assumption. Deleted at the end of Task 4.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent
KATEX = str(ROOT / "courses/static/courses/vendor/katex/katex.min.js")

PAGE = """
<div id="s" contenteditable="true">alpha <b>beta</b> gamma \\(x + y\\) delta</div>
<div id="t" contenteditable="true"><span class="tc-red">abc</span>def</div>
"""


def test_probe(page):
    page.set_content(PAGE)
    result = page.evaluate(
        """() => {
        const out = {};
        const sel = window.getSelection();
        const s = document.getElementById('s');
        // 1. foreColor over a plain word, styleWithCSS true
        const r1 = document.createRange();
        r1.setStart(s.firstChild, 0); r1.setEnd(s.firstChild, 5);
        sel.removeAllRanges(); sel.addRange(r1);
        document.execCommand('styleWithCSS', false, true);
        document.execCommand('foreColor', false, '#B2372A');
        out.plainWord = s.innerHTML;

        // 2. clear (sentinel) over a range ENCLOSING a stored tc-* span
        const t = document.getElementById('t');
        const r2 = document.createRange();
        r2.selectNodeContents(t);
        sel.removeAllRanges(); sel.addRange(r2);
        document.execCommand('foreColor', false, 'rgb(1, 2, 3)');
        out.clearEnclosing = t.innerHTML;
        return out;
    }"""
    )
    print("\n=== MEASURED ===")
    for key, value in result.items():
        print(f"{key}: {value}")
    assert result
```

- [ ] **Step 2: Run the probe and record the output**

```
uv run pytest tests/test_e2e_colour_probe.py -m e2e -s -v
```

**Each measurement has a defined expected answer and a defined consequence.** Tasks 5-7
are written out in full against the expected column; if a measurement differs, make the
stated edit before continuing — do not adapt a test to a shape the spec denies.

| # | measurement | expected | if it differs |
|---|---|---|---|
| 1 | which element `foreColor` styles | a fresh `<span>`, sometimes an existing inline wrapper | if it styles the **block**, Task 5's `mapColours` block branch is load-bearing rather than defensive — keep it and add the block case to Task 5's tests |
| 2 | the serialisation of `el.style.color` | `rgb(r, g, b)` | if a hex or a keyword, no change: `normaliseColour` accepts all three. Only a **fourth** form requires editing `MAP` |
| 3 | clearing over an enclosing range | sentinel span wraps the stored `tc-*`, i.e. the survivor is a **descendant** | if the survivor is an ancestor instead, Task 6's `eachTc` walk is wrong — **stop and revise the spec's clearing table**, then re-derive Task 6 |
| 4 | KaTeX's colour carrier and `style` contents | colour on a descendant; the same attribute also carries `height` | if colour lands only on the `.katex` root, Task 7's assertions need re-anchoring to that element |

Record each answer inline in this task, and update the spec's Unknowns section:

1. **Which element `foreColor` styles** — a fresh `<span>`, an existing inline wrapper,
   or the block. This decides whether `TC_CLASS_TAGS`'s `b/i/em/strong/u/a` entries and
   the move-off-block rule are load-bearing or belt-and-braces.
2. **The serialisation** — `rgb(178, 55, 42)` vs `#B2372A`. `courses/colour.py` already
   accepts both, but the JS mirror must too.
3. **Whether clearing over an enclosing range nests the sentinel span OUTSIDE the stored
   `tc-red`** — the spec says it does, which is why the clear rewrite strips descendants
   as well as ancestors. If this measurement disagrees, STOP and revise the spec before
   writing Task 6.

- [ ] **Step 3: Probe the KaTeX serialisation**

Record measurements 1-3 from Step 2 **before** editing the file. Then add the
following as a **second test function** (`test_katex_probe`) rather than replacing
`test_probe` — replacing it orphans the module-level `PAGE` constant and discards
the first probe:

```python
def test_katex_probe(page):
    page.goto("data:text/html,<!DOCTYPE html><div id='m'></div>")
    page.add_script_tag(path=KATEX)
    result = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{red}{x^2}', m, {throwOnError: false});
        const coloured = [...m.querySelectorAll('[style]')]
            .filter(el => el.style.color)
            .map(el => ({tag: el.tagName, color: el.style.color,
                         style: el.getAttribute('style')}));
        return {html: m.innerHTML.slice(0, 300), coloured};
    }"""
    )
    print("\n=== KATEX ===")
    print(result)
    assert result
```

Run it again. Record: whether `el.style.color` reads back as `"red"` or
`rgb(255, 0, 0)`, whether the colour lands on a wrapper or on descendants, and whether
the same `style` attribute also carries `height`/`vertical-align` (it decides whether
Task 7 clears the longhand or the attribute).

- [ ] **Step 4: Delete the probe and commit the recorded findings**

```bash
rm tests/test_e2e_colour_probe.py
```

Plain `rm`, not `git rm`: the probe was never staged, so `git rm` exits
`fatal: pathspec ... did not match any files` and the task stalls on a red command.

Append the three measurements to the spec's "Unknowns to measure during implementation"
section, converting each from a question into a recorded fact.

```bash
git add docs/superpowers/specs/2026-07-30-text-colour-design.md
git commit -m "docs(text-colour): record measured execCommand and KaTeX emission shapes"
```

---

### Task 5: `text_colour.js` — map, `normaliseColour`, `mapColours`, `tidyPastedSpans`

**Files:**
- Create: `courses/static/courses/js/text_colour.js`
- Test: `tests/test_colour_map_drift.py` (create)
- Test: `tests/test_e2e_text_colour.py` (create — grows through Tasks 5-10)

**Interfaces:**
- Consumes: the Task 4 measurements; `courses.colour.SLOTS` (mirrored, not imported).
- Produces: `window.libliColour` with
  `MAP` (array of `{rgb: [r,g,b], slot: string}`), `normaliseColour(value)`,
  `mapColours(root, opts)`, `tidyPastedSpans(root)`, `activeSlot(root)`.
  `apply(root, slot)` is added in Task 6.

- [ ] **Step 1: Write the failing drift test**

Create `tests/test_colour_map_drift.py`:

```python
"""The palette is defined twice — Python for the backfill, JS for the editor — because
the JS has no build step and cannot import Python. This holds the two copies together.

It compares the canonical slot tables (triple -> slot), NOT the raw literals: the two
languages legitimately accept different input forms (bs4 hands Python `color: red;`
from a style attribute; the DOM hands JS `rgb(255, 0, 0)`) over the same slots.
"""

import json
import re
from pathlib import Path

from courses.colour import SLOTS

JS = Path(__file__).resolve().parent.parent / "courses/static/courses/js/text_colour.js"


def test_js_and_python_slot_tables_agree():
    source = JS.read_text(encoding="utf-8")
    match = re.search(r"var MAP = (\[[^;]*?\]);", source, re.DOTALL)
    assert match, (
        "text_colour.js must expose the slot table as a single JS array literal "
        "assigned to `var MAP` — the test extracts it verbatim, so refactoring it "
        "into computed form is a deliberate break, not an accident"
    )
    raw = match.group(1)
    raw = re.sub(r"//[^\n]*", "", raw)  # strip line comments
    raw = re.sub(r",(\s*[\]}])", r"\1", raw)  # tolerate trailing commas
    raw = raw.replace("rgb:", '"rgb":').replace("slot:", '"slot":')
    entries = json.loads(raw)

    js_table = {tuple(entry["rgb"]): entry["slot"] for entry in entries}
    assert js_table == SLOTS, (
        "JS and Python slot tables disagree\n"
        f"  only in JS:     {sorted(set(js_table) - set(SLOTS))}\n"
        f"  only in Python: {sorted(set(SLOTS) - set(js_table))}"
    )


def test_css_tokens_are_in_the_python_slot_table():
    """There are THREE copies of every hex: tokens.css, colour.py and
    text_colour.js. The test above binds the last two. Without this one, changing a
    --tc-* token to satisfy a future surface leaves the other two stale with a green
    suite, and slotFor() silently stops recognising the colour the page renders."""
    from courses.colour import normalise_colour

    tokens = (
        Path(__file__).resolve().parent.parent / "core/static/core/css/tokens.css"
    ).read_text(encoding="utf-8")
    seen = 0
    for slot in ("red", "blue", "green", "orange"):
        for value in re.findall(rf"--tc-{slot}:\s*(#[0-9A-Fa-f]{{6}})", tokens):
            assert SLOTS.get(normalise_colour(value)) == slot, (
                f"tokens.css --tc-{slot} is {value}, which colour.py does not map "
                f"to {slot!r} — update _PALETTE and text_colour.js MAP together"
            )
            seen += 1
    assert seen == 8, f"expected 4 slots x 2 themes in tokens.css, found {seen}"
```

- [ ] **Step 2: Run it to verify it fails**

```
uv run pytest tests/test_colour_map_drift.py -v
```

Expected: FAIL — `FileNotFoundError` for `text_colour.js`.

- [ ] **Step 3: Write the module**

Create `courses/static/courses/js/text_colour.js`:

```javascript
(function () {
  "use strict";

  // Canonical slot table, mirroring courses/colour.py. tests/test_colour_map_drift.py
  // extracts this literal verbatim and compares it to the Python one, so it must stay
  // a single plain array assigned to `var MAP`.
  var MAP = [
    { rgb: [178, 55, 42], slot: "red" },
    { rgb: [234, 138, 130], slot: "red" },
    { rgb: [255, 0, 0], slot: "red" },
    { rgb: [31, 97, 173], slot: "blue" },
    { rgb: [143, 188, 232], slot: "blue" },
    { rgb: [0, 0, 255], slot: "blue" },
    { rgb: [63, 107, 36], slot: "green" },
    { rgb: [159, 191, 123], slot: "green" },
    { rgb: [0, 128, 0], slot: "green" },
    { rgb: [138, 85, 20], slot: "orange" },
    { rgb: [232, 183, 97], slot: "orange" },
    { rgb: [255, 165, 0], slot: "orange" }
  ];

  var SLOTS = ["red", "blue", "green", "orange"];
  var TC_TAGS = { SPAN: 1, B: 1, I: 1, EM: 1, STRONG: 1, U: 1, A: 1 };
  // Applied by Clear, then dropped. Never in MAP -- asserted by the drift test.
  var SENTINEL = "rgb(1, 2, 3)";

  var KEYWORDS = {
    red: [255, 0, 0], blue: [0, 0, 255],
    green: [0, 128, 0], orange: [255, 165, 0]
  };

  function normaliseColour(value) {
    if (!value) return null;
    var text = String(value).trim().toLowerCase();
    if (KEYWORDS[text]) return KEYWORDS[text].slice();
    var hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(text);
    if (hex) {
      var digits = hex[1];
      if (digits.length === 3) {
        digits = digits[0] + digits[0] + digits[1] + digits[1] + digits[2] + digits[2];
      }
      return [
        parseInt(digits.slice(0, 2), 16),
        parseInt(digits.slice(2, 4), 16),
        parseInt(digits.slice(4, 6), 16)
      ];
    }
    var rgb = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,[^)]*)?\)$/.exec(text);
    if (rgb) {
      var out = [+rgb[1], +rgb[2], +rgb[3]];
      return (out[0] > 255 || out[1] > 255 || out[2] > 255) ? null : out;
    }
    return null;
  }

  function slotFor(value) {
    var triple = normaliseColour(value);
    if (!triple) return null;
    for (var i = 0; i < MAP.length; i++) {
      var m = MAP[i].rgb;
      if (m[0] === triple[0] && m[1] === triple[1] && m[2] === triple[2]) {
        return MAP[i].slot;
      }
    }
    return null;
  }

  function tcClassOf(el) {
    if (!el.classList) return null;
    for (var i = 0; i < SLOTS.length; i++) {
      if (el.classList.contains("tc-" + SLOTS[i])) return SLOTS[i];
    }
    return null;
  }

  function clearTc(el) {
    for (var i = 0; i < SLOTS.length; i++) el.classList.remove("tc-" + SLOTS[i]);
    if (el.getAttribute("class") === "") el.removeAttribute("class");
  }

  // Clear the COLOR LONGHAND, never the style attribute: KaTeX packs height,
  // vertical-align and margin-right into the same attribute, and removing it whole
  // destroys the rendered layout.
  function clearInlineColour(el) {
    el.style.color = "";
    if (el.getAttribute("style") === "") el.removeAttribute("style");
  }

  function wrapChildren(el, slot) {
    var span = document.createElement("span");
    span.className = "tc-" + slot;
    while (el.firstChild) span.appendChild(el.firstChild);
    el.appendChild(span);
    return span;
  }

  // Touches ONLY elements carrying an inline colour. Never touches an element without
  // one -- which is what makes it safe to run over freshly rendered KaTeX, whose output
  // is overwhelmingly colourless spans that a broader pass would flatten.
  //
  // opts.dropUnmapped: author path (true) drops an unmapped colour; render path (false)
  // leaves it exactly as-is, so existing \color{purple} content keeps rendering.
  function mapColours(root, opts) {
    if (!root || !root.querySelectorAll) return false;
    var dropUnmapped = !!(opts && opts.dropUnmapped);
    var changed = false;
    var styled = root.querySelectorAll("[style]");
    var all = [];
    for (var i = 0; i < styled.length; i++) all.push(styled[i]);
    if (root.getAttribute && root.getAttribute("style")) all.push(root);

    for (var j = 0; j < all.length; j++) {
      var el = all[j];
      if (!el.style || !el.style.color) continue;
      var slot = slotFor(el.style.color);
      if (!slot) {
        if (dropUnmapped) { clearInlineColour(el); changed = true; }
        continue;
      }
      changed = true;
      if (el === root) {
        // The root's own classes are never serialised (sync reads innerHTML), so a
        // class here would vanish on save with no sanitiser involved.
        clearInlineColour(el);
        wrapChildren(el, slot);
      } else if (TC_TAGS[el.tagName]) {
        clearTc(el);
        el.classList.add("tc-" + slot);
        clearInlineColour(el);
      } else {
        clearInlineColour(el);
        wrapChildren(el, slot);
      }
    }
    // Unconditional: the collapse also has to fire for CLASS-ONLY markup (a reloaded
    // surface carries tc-* with no inline colour at all), where nothing above sets
    // `changed`. It is idempotent, so running it always is free.
    collapseNested(root);
    return changed;
  }

  // <span class="tc-red"><span class="tc-blue">x</span></span> -> the inner one.
  // "Only rendered content" ignores whitespace-only text nodes, which execCommand
  // emits routinely and which an "only child" predicate would trip over.
  function collapseNested(root) {
    var outers = root.querySelectorAll(
      ".tc-red, .tc-blue, .tc-green, .tc-orange"
    );
    for (var i = 0; i < outers.length; i++) {
      var outer = outers[i];
      var inner = null, extra = false;
      for (var n = outer.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3 && !n.nodeValue.trim()) continue;
        if (n.nodeType === 1 && tcClassOf(n) && !inner) { inner = n; continue; }
        extra = true;
      }
      if (inner && !extra) clearTc(outer);           // innermost wins
      // One element may carry two slots via the HTML source view; keep one.
      var slot = tcClassOf(outer);
      if (slot) { clearTc(outer); outer.classList.add("tc-" + slot); }
    }
  }

  // Paste hygiene ONLY. Rule (a) runs before rule (b) and (b) never fires inside a
  // .katex subtree: a .katex wrapper matches (b)'s predicate exactly, so a (b)-first
  // or bottom-up pass would destroy the subtree before (a) could read its annotation.
  function tidyPastedSpans(root) {
    if (!root || !root.querySelectorAll) return;
    // (a) a pasted .katex subtree -> its LaTeX source, re-delimited.
    var katex = root.querySelectorAll(".katex");
    for (var i = katex.length - 1; i >= 0; i--) {
      var node = katex[i];
      if (!node.parentNode) continue;
      var ann = node.querySelector('annotation[encoding="application/x-tex"]');
      var display = node.classList.contains("katex-display") ||
        (node.parentNode.classList &&
         node.parentNode.classList.contains("katex-display"));
      var latex = ann ? ann.textContent : "";
      var text = latex
        ? (display ? "\\[" + latex + "\\]" : "\\(" + latex + "\\)")
        : node.textContent;
      var target = display && node.parentNode.classList &&
        node.parentNode.classList.contains("katex-display")
        ? node.parentNode : node;
      target.parentNode.replaceChild(document.createTextNode(text), target);
    }
    // (b) any other span with no meaningful class and no attribute but class/style.
    var spans = root.querySelectorAll("span");
    for (var j = spans.length - 1; j >= 0; j--) {
      var span = spans[j];
      if (!span.parentNode) continue;
      if (tcClassOf(span)) continue;
      if (span.className && /\bta-(left|center|right)\b/.test(span.className)) continue;
      var onlyClassOrStyle = true;
      for (var k = 0; k < span.attributes.length; k++) {
        var name = span.attributes[k].name;
        if (name !== "class" && name !== "style") onlyClassOrStyle = false;
      }
      if (!onlyClassOrStyle) continue;
      if (span.style && span.style.color) continue;   // mapColours' business
      while (span.firstChild) span.parentNode.insertBefore(span.firstChild, span);
      span.parentNode.removeChild(span);
    }
  }

  function activeSlot(root) {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return null;
    var range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return null;
    function slotAt(node) {
      if (node && node.nodeType === 3) node = node.parentNode;
      while (node && node !== root) {
        var slot = tcClassOf(node);
        if (slot) return slot;
        node = node.parentNode;
      }
      return null;
    }
    var start = slotAt(range.startContainer);
    var end = slotAt(range.endContainer);
    return start && start === end ? start : null;
  }

  window.libliColour = {
    MAP: MAP,
    SENTINEL: SENTINEL,
    normaliseColour: normaliseColour,
    slotFor: slotFor,
    mapColours: mapColours,
    tidyPastedSpans: tidyPastedSpans,
    activeSlot: activeSlot
  };
})();
```

- [ ] **Step 4: Run the drift test to verify it passes**

```
uv run pytest tests/test_colour_map_drift.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Write the e2e test for the two passes**

Create `tests/test_e2e_text_colour.py`:

```python
"""Browser-level behaviour of window.libliColour.

EVERY set_content string here starts with <!DOCTYPE html>. Playwright's set_content
emits no doctype, which leaves the document in quirks mode, and katex.render then
throws "KaTeX doesn't work in quirks mode" — the assertion never runs and the test
errors instead of failing. Do not "tidy" the doctype away.

The pure helpers (normaliseColour, and the two DOM passes over fixed markup) are
exercised via page.evaluate — they are functions, not gestures. Everything involving
a selection or a toolbar click is driven through the real UI in later tasks, because
an e2e that bypasses the real gesture ships broken UX green.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "courses/static/courses/js/text_colour.js")
KATEX = str(ROOT / "courses/static/courses/vendor/katex/katex.min.js")
TOKENS_CSS = str(ROOT / "core/static/core/css/tokens.css")
COURSES_CSS = str(ROOT / "courses/static/courses/css/courses.css")


def _page_with_module(page):
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.add_script_tag(path=SCRIPT)
    return page


def test_normalise_colour_accepts_every_input_form(page):
    _page_with_module(page)
    assert page.evaluate("() => libliColour.normaliseColour('#B2372A')") == [
        178,
        55,
        42,
    ]
    assert page.evaluate("() => libliColour.normaliseColour('rgb(178, 55, 42)')") == [
        178,
        55,
        42,
    ]
    assert page.evaluate("() => libliColour.slotFor('red')") == "red"
    assert page.evaluate("() => libliColour.slotFor('purple')") is None
    assert page.evaluate("() => libliColour.slotFor(libliColour.SENTINEL)") is None


def test_map_colours_moves_a_class_off_a_block_tag(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<p style="color: rgb(178, 55, 42)">x</p>';
        libliColour.mapColours(r, {dropUnmapped: true});
        return r.innerHTML;
    }"""
    )
    assert 'class="tc-red"' in html
    assert "<span" in html, "a block tag may not carry tc-*; wrap its children instead"
    assert "style" not in html


def test_map_colours_leaves_unmapped_colour_on_the_render_path(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span style="color: purple">x</span>';
        libliColour.mapColours(r, {dropUnmapped: false});
        return r.innerHTML;
    }"""
    )
    assert "purple" in html, "render path must not destroy existing \\color{purple}"


def test_map_colours_is_a_noop_on_second_call(page):
    _page_with_module(page)
    first, second = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span style="color: rgb(31, 97, 173)">x</span>';
        libliColour.mapColours(r, {dropUnmapped: true});
        const a = r.innerHTML;
        libliColour.mapColours(r, {dropUnmapped: true});
        return [a, r.innerHTML];
    }"""
    )
    assert first == second


def test_nested_colour_spans_collapse_innermost_wins(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span class="tc-red"> <span class="tc-blue">x</span> </span>';
        libliColour.mapColours(r, {dropUnmapped: true});
        return r.innerHTML;
    }"""
    )
    assert "tc-blue" in html
    assert "tc-red" not in html, "whitespace text nodes must not defeat the collapse"


def test_tidy_unwraps_a_bare_span_but_keeps_semantic_ones(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span>a</span><span class="tc-red">b</span>'
                    + '<b>c</b><span data-x="1">d</span>';
        libliColour.tidyPastedSpans(r);
        return r.innerHTML;
    }"""
    )
    assert html.startswith("a"), "a bare span must be unwrapped"
    assert 'class="tc-red"' in html
    assert "<b>c</b>" in html
    assert "data-x" in html, "a span with another attribute is not paste litter"


def test_pasted_katex_becomes_its_latex_source(page):
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    text = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        const host = document.createElement('div');
        katex.render('x^2', host, {throwOnError: false});
        r.innerHTML = host.innerHTML;
        libliColour.tidyPastedSpans(r);
        return r.textContent;
    }"""
    )
    assert text.strip() == "\\(x^2\\)", (
        "rule (a) must run before rule (b); a .katex wrapper matches (b)'s predicate, "
        "so a (b)-first pass destroys the subtree before its annotation is read"
    )
    assert "<span" not in text
```

- [ ] **Step 6: Run the e2e tests**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -v
```

Expected: 7 passed. `-m e2e` is mandatory — without it pytest deselects everything and
exits 5, which looks like success.

- [ ] **Step 7: Falsify**

In `tidyPastedSpans`, move the rule-(b) loop above the rule-(a) loop. Re-run. Expected:
`test_pasted_katex_becomes_its_latex_source` FAILS. Restore.

In `collapseNested`, change the whitespace skip `if (n.nodeType === 3 && !n.nodeValue.trim()) continue;`
to `if (false) continue;`. Re-run. Expected:
`test_nested_colour_spans_collapse_innermost_wins` FAILS. Restore.

- [ ] **Step 8: Commit**

```bash
uv run ruff format .
git add courses/static/courses/js/text_colour.js tests/test_colour_map_drift.py tests/test_e2e_text_colour.py
git commit -m "feat(text-colour): colour map, mapColours and tidyPastedSpans with drift guard"
```

---

### Task 6: `apply()` — protected regions (D8/D10) and the range-aware clear

**Files:**
- Modify: `courses/static/courses/js/text_colour.js`
- Modify: `tests/test_e2e_text_colour.py`

**Interfaces:**
- Consumes: `mapColours`, `slotFor`, `SENTINEL` from Task 5.
- Produces: `window.libliColour.apply(root, slot)` — applies a slot, or clears when
  `slot` is `null`; returns `"ok"` or `"refused"`.
  `window.libliColour.regions(root)` — the protected `[start, end)` text offsets.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_e2e_text_colour.py`:

```python
def _select_text(page, root_id, needle):
    """Select `needle` inside `root_id` by walking text nodes — the same offset
    mapping apply() uses, so the test exercises the real path."""
    return page.evaluate(
        """([rootId, needle]) => {
        const root = document.getElementById(rootId);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let acc = '', nodes = [];
        while (walker.nextNode()) { nodes.push([walker.currentNode, acc.length]);
                                    acc += walker.currentNode.nodeValue; }
        const at = acc.indexOf(needle);
        if (at < 0) return false;
        const end = at + needle.length;
        let sN, sO, eN, eO;
        for (const [node, base] of nodes) {
            const len = node.nodeValue.length;
            if (sN === undefined && at >= base && at <= base + len) {
                sN = node; sO = at - base;
            }
            if (end >= base && end <= base + len) { eN = node; eO = end - base; }
        }
        const range = document.createRange();
        range.setStart(sN, sO); range.setEnd(eN, eO);
        const sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(range);
        return true;
    }""",
        [root_id, needle],
    )


def test_refuses_a_selection_wholly_inside_a_maths_region(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + y\\\\) b</div>'; }"""
    )
    assert _select_text(page, "root", "x")
    outcome = page.evaluate(
        "() => libliColour.apply(document.getElementById('root'), 'red')"
    )
    assert outcome == "refused"
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert "tc-red" not in html, "a refusal must not mutate the DOM"


def test_refuses_a_selection_straddling_a_maths_boundary(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + y\\\\) b</div>'; }"""
    )
    assert _select_text(page, "root", "a \\(x")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_allows_a_selection_enclosing_a_whole_maths_region(page):
    """The one ALLOWED branch. Without this case an implementation that refuses every
    intersection passes the whole suite and the falsification rule catches nothing."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x+y\\\\) b</div>'; }"""
    )
    assert _select_text(page, "root", "a \\(x+y\\) b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "ok"
    )
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert "tc-red" in html
    assert "\\(x+y\\)" in html, "the delimiters must survive intact"


def test_refuses_enclosing_a_region_that_contains_an_element_boundary(page):
    """The carve-out on the ALLOWED branch. Such a region already round-trips lossily
    through sanitize_cell with or without colour, so a span there is not a gesture the
    storage layer can support. Without this case, an implementation that ignores
    element boundaries entirely passes every other D8 test."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + <b>y</b>\\\\) b</div>'; }"""
    )
    # Pin the delimiters BEFORE selecting. With single backslashes Python emits a
    # SyntaxWarning, the JS literal collapses \( to (, and the DOM text becomes
    # "a (x + y) b" with no delimiters at all -- _select_text then returns False and
    # the test dies on the wrong assertion while the carve-out goes unexercised.
    assert "\\(" in page.evaluate("() => document.getElementById('root').textContent")
    assert _select_text(page, "root", "a \\(x + y\\) b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_refuses_inside_a_marker(page):
    """D10: markers are parsed AFTER sanitisation, so a coloured marker becomes the
    stored answer. The test runs on every surface, so no opt-in attribute is needed."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">pick {{a|b}} now</div>'; }"""
    )
    assert _select_text(page, "root", "a")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_fails_closed_on_an_unclosed_delimiter(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + y b</div>'; }"""
    )
    assert _select_text(page, "root", "y b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_clear_over_an_enclosing_selection_removes_stored_colour(page):
    """The primary clear path. Stored colour is class-carried with NO inline colour,
    and an enclosing selection nests the sentinel span OUTSIDE it — so the surviving
    tc-* is a DESCENDANT. An ancestors-only rule leaves Clear a silent no-op here."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">'
        + '<span class="tc-red">abc</span>def</div>'; }"""
    )
    assert _select_text(page, "root", "abcdef")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), null)")
        == "ok"
    )
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert "tc-red" not in html
    assert "abcdef" in page.evaluate(
        "() => document.getElementById('root').textContent"
    )


def test_clear_over_a_partial_selection_leaves_the_remainder_coloured(page):
    """execCommand does NOT split class-carried colour (there is no inline colour to
    split), so apply() must split explicitly or Clear wipes the whole run."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">'
        + '<span class="tc-red">abc</span></div>'; }"""
    )
    assert _select_text(page, "root", "b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), null)")
        == "ok"
    )
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert html.count("tc-red") == 2, f"a and c must stay coloured, b cleared: {html}"


def test_clearing_a_link_keeps_the_link(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">'
        + '<a href="/courses/n/12/" class="tc-red">link</a></div>'; }"""
    )
    assert _select_text(page, "root", "link")
    page.evaluate("() => libliColour.apply(document.getElementById('root'), null)")
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert 'href="/courses/n/12/"' in html, "clearing must never unwrap a link"
    assert "tc-red" not in html
```

- [ ] **Step 2: Run to verify they fail**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -k "refuses or allows or clear or fails_closed" -v
```

Expected: all FAIL with `libliColour.apply is not a function`.

- [ ] **Step 3: Implement regions and `apply`**

Insert into `text_colour.js`, before the `window.libliColour = {…}` assignment:

```javascript
  // ---- Protected regions: maths spans and {{...}} markers -------------------
  //
  // Colouring inside either is a permanent corruption, not a cosmetic slip:
  //   - maths: sanitize_cell stashes a balanced \(...\) region INCLUDING any injected
  //     markup, then escapes it. Both sanitisers are idempotent, so re-saving never
  //     heals it -- the damage outlives the undo window.
  //   - markers: fillblank.parse runs AFTER sanitize_html, so {{<span>a</span>|b}}
  //     still matches the marker regex and the markup becomes the accepted answer.
  //
  // The marker test runs on EVERY surface, not just marker-bearing fields: apply()
  // receives only `root` and has no signal for which field it is editing, and "{{"
  // occurs zero times in the imported corpus, so the false-refusal cost is nil.
  var MATH_RE = /\\\(|\\\)|\\\[|\\\]/g;
  var MARKER_RE = /\{\{(.*?)\}\}/g;

  // A DOM Range yields (node, offset) pairs, not indices into textContent. This is
  // the mapping step; getting it wrong is how a region test silently passes.
  function textOffsets(root, range) {
    // Handles BOTH container kinds. A selection's Range has TEXT containers, but
    // selectNodeContents(el) yields an ELEMENT container -- and a text-node-only walk
    // returns null for those, which made splitOrClear dead code and let Clear wipe a
    // whole coloured run instead of splitting it.
    var texts = [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var acc = 0, node;
    while ((node = walker.nextNode())) {
      texts.push({ node: node, start: acc });
      acc += node.nodeValue.length;
    }
    function offsetOf(container, offset) {
      var i;
      if (container.nodeType === 3) {
        for (i = 0; i < texts.length; i++) {
          if (texts[i].node === container) return texts[i].start + offset;
        }
        return null;
      }
      // Element container: `offset` counts CHILD NODES, so the text offset is the
      // start of the first text node at or after that child.
      var limit = container.childNodes[offset] || null;
      if (!limit) {
        var last = null;
        for (i = 0; i < texts.length; i++) {
          if (container.contains(texts[i].node)) last = texts[i];
        }
        return last ? last.start + last.node.nodeValue.length : null;
      }
      for (i = 0; i < texts.length; i++) {
        if (texts[i].node === limit || limit.contains(texts[i].node)) {
          return texts[i].start;
        }
      }
      return null;
    }
    var start = offsetOf(range.startContainer, range.startOffset);
    var end = offsetOf(range.endContainer, range.endOffset);
    if (start === null || end === null) return null;
    return [Math.min(start, end), Math.max(start, end)];
  }

  // Returns {regions: [[start, end], ...], ok: bool}. ok=false means a delimiter is
  // unbalanced or unclosed anywhere in the scan root -- apply() then FAILS CLOSED.
  function regions(root) {
    var text = root.textContent || "";
    var out = [], ok = true, open = null, m;
    MATH_RE.lastIndex = 0;
    while ((m = MATH_RE.exec(text))) {
      var isOpen = m[0] === "\\(" || m[0] === "\\[";
      if (isOpen) {
        if (open !== null) { ok = false; break; }
        open = m.index;
      } else {
        if (open === null) { ok = false; break; }
        out.push([open, m.index + m[0].length]);
        open = null;
      }
    }
    if (open !== null) ok = false;
    MARKER_RE.lastIndex = 0;
    while ((m = MARKER_RE.exec(text))) out.push([m.index, m.index + m[0].length]);
    return { regions: out, ok: ok };
  }

  // Four cases, per the spec's table. The enclosing case is ALLOWED only when the
  // region carries no element boundary: foreColor's behaviour across a boundary is
  // recorded as an unknown, and sanitize_cell already round-trips such a region
  // lossily, so a span there is not a gesture the storage layer can support.
  function regionVerdict(root, span) {
    var found = regions(root);
    if (!found.ok) return "refused";
    for (var i = 0; i < found.regions.length; i++) {
      var r = found.regions[i];
      var enclosing = span[0] <= r[0] && span[1] >= r[1];
      var disjoint = span[1] <= r[0] || span[0] >= r[1];
      if (disjoint) continue;
      if (!enclosing) return "refused";
      if (regionCrossesElement(root, r)) return "refused";
    }
    return "ok";
  }

  function regionCrossesElement(root, region) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var acc = 0, owner = null, node;
    while ((node = walker.nextNode())) {
      var start = acc, end = acc + node.nodeValue.length;
      acc = end;
      if (end <= region[0] || start >= region[1]) continue;
      if (owner === null) owner = node.parentNode;
      else if (owner !== node.parentNode) return true;
    }
    return false;
  }

  function styleWithCss(on) {
    try { document.execCommand("styleWithCSS", false, on); } catch (e) { /* ignore */ }
  }

  function announce(root) {
    var editor = root.closest ? root.closest(".editor") : null;
    var text = editor && editor.getAttribute("data-msg-colour-region");
    if (!text) return;                       // degrade silently, as the conflict path does
    var bar = document.createElement("div");
    bar.className = "op-error";
    bar.setAttribute("data-colour-refusal", "");
    bar.textContent = text;
    editor.prepend(bar);
    setTimeout(function () { bar.remove(); }, 6000);
  }

  function eachTc(el, fn) {
    if (tcClassOf(el)) fn(el);
    var inner = el.querySelectorAll(".tc-red, .tc-blue, .tc-green, .tc-orange");
    for (var i = 0; i < inner.length; i++) fn(inner[i]);
  }

  function apply(root, slot) {
    var sel = window.getSelection();
    if (!sel || !sel.rangeCount) return "refused";
    var range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return "refused";
    var span = textOffsets(root, range);
    if (!span) return "refused";
    if (regionVerdict(root, span) === "refused") { announce(root); return "refused"; }

    var value = SENTINEL;
    if (slot) {
      value = null;
      for (var i = 0; i < MAP.length; i++) {
        if (MAP[i].slot === slot) {
          value = "rgb(" + MAP[i].rgb.join(", ") + ")";
          break;
        }
      }
      if (!value) return "refused";   // unknown slot: refuse, never guess a colour
    }
    styleWithCss(true);
    try { document.execCommand("foreColor", false, value); } catch (e) { /* ignore */ }
    styleWithCss(false);   // MUST reset: document-global, and a leaked true breaks bold

    if (slot) {
      mapColours(root, { dropUnmapped: true });
      return "ok";
    }

    // Clear. Stored colour is class-carried, so execCommand cannot split it and the
    // surviving tc-* may be an ANCESTOR (partial selection) or a DESCENDANT (the
    // selection enclosed it). Walk both directions, and split explicitly when the
    // range covers only part of a coloured element.
    var sentinels = root.querySelectorAll('[style*="rgb(1, 2, 3)"]');
    for (var s = 0; s < sentinels.length; s++) {
      var el = sentinels[s];
      eachTc(el, clearTc);                                   // el + descendants
      var up = el.parentNode;
      while (up && up !== root) {
        if (tcClassOf(up)) splitOrClear(root, up, span);
        up = up.parentNode;
      }
      clearInlineColour(el);
    }
    dropAttributelessSpans(root);
    return "ok";
  }

  // If the cleared range covers the whole element, drop its class. Otherwise split it
  // into cleared and still-coloured parts -- execCommand does not do this for
  // class-carried colour, and stripping wholesale would clear text outside the range.
  function splitOrClear(root, el, span) {
    var elRange = document.createRange();
    elRange.selectNodeContents(el);
    var bounds = textOffsets(root, elRange);
    if (!bounds) { clearTc(el); return; }
    if (span[0] <= bounds[0] && span[1] >= bounds[1]) { clearTc(el); return; }
    var slot = tcClassOf(el);
    clearTc(el);
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    var acc = bounds[0], node, pending = [];
    while ((node = walker.nextNode())) {
      pending.push([node, acc, acc + node.nodeValue.length]);
      acc += node.nodeValue.length;
    }
    for (var i = 0; i < pending.length; i++) {
      var entry = pending[i], text = entry[0], from = entry[1], to = entry[2];
      if (to <= span[0] || from >= span[1]) {
        var keep = document.createElement("span");
        keep.className = "tc-" + slot;
        text.parentNode.insertBefore(keep, text);
        keep.appendChild(text);
      }
    }
  }

  // Narrower than tidyPastedSpans' rule (b): this one unwraps ONLY spans with zero
  // attributes -- the shells left behind after clearing removes a class and a colour.
  // Rule (b) additionally unwraps class/style-only spans and is paste-gated.
  function dropAttributelessSpans(root) {
    var spans = root.querySelectorAll("span");
    for (var i = spans.length - 1; i >= 0; i--) {
      var span = spans[i];
      if (span.attributes.length) continue;
      while (span.firstChild) span.parentNode.insertBefore(span.firstChild, span);
      span.parentNode.removeChild(span);
    }
  }
```

Add to the exported object:

```javascript
    apply: apply,
    regions: regions,
```

- [ ] **Step 4: Run the tests**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -v
```

Expected: 16 passed.

- [ ] **Step 5: Falsify**

In `apply`, change `eachTc(el, clearTc)` to `clearTc(el)` (ancestors/self only, no
descendants). Re-run. Expected:
`test_clear_over_an_enclosing_selection_removes_stored_colour` FAILS. Restore.

In `regionVerdict`, change `if (!enclosing) return "refused";` to `continue;`. Re-run.
Expected: `test_refuses_a_selection_wholly_inside_a_maths_region` FAILS. Restore.

- [ ] **Step 6: Commit**

```bash
uv run ruff format .
git add courses/static/courses/js/text_colour.js tests/test_e2e_text_colour.py
git commit -m "feat(text-colour): protected-region refusal and range-aware clear"
```

---

### Task 7: KaTeX normalisation and script loading

**Files:**
- Modify: `courses/static/courses/js/text_colour.js`
- Modify: `templates/courses/lesson_unit.html`, `quiz_unit.html`, `quiz_results.html`,
  `manage/editor/editor.html`, `manage/review_submission.html`
- Test: `tests/test_text_colour_script_order.py` (create)
- Modify: `tests/test_e2e_text_colour.py`

**Interfaces:**
- Consumes: `mapColours` from Task 5.
- Produces: `window.renderMathInElement` and `window.katex.render` wrapped at load; every
  KaTeX-rendered colour resolves to a `tc-*` class.

- [ ] **Step 1: Write the failing script-order test**

Create `tests/test_text_colour_script_order.py`:

```python
"""text_colour.js must load AFTER auto-render.min.js (which defines
renderMathInElement) and BEFORE any script that calls it. All scripts are `defer`, so
they execute in document order, and math.js calls renderMath(document) and
renderInlineText(document) at module evaluation — a wrapper installed after math.js
misses the entire initial page render, which is the dominant case.

Two templates load auto-render WITHOUT math.js; there the caller is question.js.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates/courses"

PAGES = [
    "lesson_unit.html",
    "quiz_unit.html",
    "quiz_results.html",
    "manage/editor/editor.html",
    "manage/review_submission.html",
]

CALLERS = ("math.js", "question.js", "quiz.js", "editor.js")


def _script_order(path):
    """Script basenames in document order.

    Parses the {% static '...' %} argument, NOT the raw src attribute: the real markup
    is src="{% static 'courses/vendor/katex/contrib/auto-render.min.js' %}", so a regex
    anchored on `.js"` matches nothing, and a `js/`-segment fallback misses everything
    under vendor/. Both mistakes make this test pass-proof rather than useful.
    """
    text = (TEMPLATES / path).read_text(encoding="utf-8")
    return [
        m.group(1).rsplit("/", 1)[-1]
        for m in re.finditer(r"{%\s*static\s*'([^']+\.js)'", text)
    ]


def test_the_parser_actually_sees_the_katex_scripts():
    """Self-check. Without it a broken parser returns [] and makes every assertion
    below vacuous — which is exactly how the first draft of this file failed."""
    order = _script_order("lesson_unit.html")
    assert "katex.min.js" in order, order
    assert "auto-render.min.js" in order, order


def test_every_katex_page_loads_text_colour_in_the_right_place():
    failures = []
    for page in PAGES:
        order = _script_order(page)
        if "auto-render.min.js" not in order:
            failures.append(f"{page}: no auto-render.min.js (template changed?)")
            continue
        if "text_colour.js" not in order:
            failures.append(f"{page}: text_colour.js is not loaded")
            continue
        colour_at = order.index("text_colour.js")
        if colour_at < order.index("auto-render.min.js"):
            failures.append(f"{page}: text_colour.js loads before auto-render.min.js")
        for caller in CALLERS:
            if caller in order and order.index(caller) < colour_at:
                failures.append(f"{page}: {caller} loads before text_colour.js")
    assert not failures, "\n".join(failures)
```

- [ ] **Step 2: Run to verify it fails**

```
uv run pytest tests/test_text_colour_script_order.py -v
```

Expected: **1 failed, 1 passed** — the load-order test fails listing all five
templates with "text_colour.js is not loaded", while
`test_the_parser_actually_sees_the_katex_scripts` already passes (it guards the
parser, not the change).

- [ ] **Step 3: Add the wrappers**

Append to `text_colour.js`, immediately before the closing `})();`:

```javascript
  // ---- KaTeX normalisation -------------------------------------------------
  //
  // Two hooks, because one does not cover the other:
  //
  //  * INLINE prose maths goes through window.renderMathInElement. Wrapping it works
  //    only because math.js resolves that global at CALL time.
  //
  //  * DISPLAY maths ([data-katex]) cannot be reached via window.libliRenderMath:
  //    math.js assigns that symbol during its own evaluation (so it does not exist at
  //    our insertion point, and the assignment would clobber a wrapper installed
  //    earlier), and its initial pass calls the LOCAL renderMath. renderOne calls a
  //    bare `katex.render(...)`, resolved at call time on window.katex -- so that is
  //    the hook that actually covers the initial render.
  //
  // The render path never drops an unmapped colour, so existing \color{purple}
  // content keeps rendering exactly as it does today.
  function wrapRenderMathInElement() {
    var original = window.renderMathInElement;
    if (typeof original !== "function") return false;
    if (original.__libliColourWrapped) return true;
    var wrapped = function (element, options) {
      var result = original.apply(this, arguments);
      try { mapColours(element, { dropUnmapped: false }); } catch (e) { /* ignore */ }
      return result;
    };
    wrapped.__libliColourWrapped = true;
    window.renderMathInElement = wrapped;
    return true;
  }

  function wrapKatexRender() {
    if (!window.katex || typeof window.katex.render !== "function") return false;
    if (window.katex.render.__libliColourWrapped) return true;
    var original = window.katex.render;
    var wrapped = function (expression, element, options) {
      var result = original.apply(this, arguments);
      try { mapColours(element, { dropUnmapped: false }); } catch (e) { /* ignore */ }
      return result;
    };
    wrapped.__libliColourWrapped = true;
    window.katex.render = wrapped;
    return true;
  }

  // Defensive: if either global is not defined yet, retry once the document is ready
  // rather than silently no-opping for the whole page.
  // Evaluate BOTH before testing: `!a() || !b()` short-circuits and never calls b()
  // when a() fails -- which is exactly the case on a page that loads katex.min.js but
  // not auto-render.min.js, leaving katex.render unwrapped. The bug is invisible on
  // real pages (which load both) and only bites in isolation.
  var inlineWrapped = wrapRenderMathInElement();
  var renderWrapped = wrapKatexRender();
  if (!inlineWrapped || !renderWrapped) {
    // Note: this retry is dead for a script added AFTER load; it exists for the
    // ordinary defer-in-document-order case.
    document.addEventListener("DOMContentLoaded", function () {
      wrapRenderMathInElement();
      wrapKatexRender();
    });
  }
```

- [ ] **Step 4: Add the script tags**

In `templates/courses/lesson_unit.html`, between the `auto-render.min.js` line (62) and
the `math.js` line (63):

```html
    <script src="{% static 'courses/js/text_colour.js' %}" defer></script>
```

Do the same in `templates/courses/quiz_unit.html` — inside the same `{% if has_math %}`
gate, after `auto-render.min.js`, before `math.js`.

In `templates/courses/quiz_results.html` and
`templates/courses/manage/review_submission.html`, insert the same line after
`auto-render.min.js` and **before `question.js`** — those two templates never load
`math.js`, so `question.js` is the caller the wrapper must precede.

In `templates/courses/manage/editor/editor.html`, insert it after `auto-render.min.js`
(line 136) and before `math.js` (137). **Ungated**: that template loads KaTeX
unconditionally, and `window.libliColour` must exist for the toolbars even in a unit
with no maths.

- [ ] **Step 5: Run the script-order test**

```
uv run pytest tests/test_text_colour_script_order.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Add the e2e assertions**

Append to `tests/test_e2e_text_colour.py`:

```python
def test_katex_colour_resolves_to_the_palette_token(page):
    """D4: prose tc-red and \\color{red} must be the SAME colour. Asserting 'a colour
    is present' would pass even if the class were added while the inline colour stayed,
    which is the failure mode — inline style always beats a class."""
    # Load the REAL stylesheets. An inline `.tc-red{color:#B2372A}` stub makes the
    # computed value a foregone conclusion and proves nothing about palette identity
    # — it is a fourth unguarded copy of the literal. (katex.min.css sets no color.)
    page.set_content("<!DOCTYPE html><div id='m'></div>")
    page.add_style_tag(path=TOKENS_CSS)
    page.add_style_tag(path=COURSES_CSS)
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    computed = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{red}{x}', m, {throwOnError: false});
        const el = m.querySelector('.tc-red');
        return el ? getComputedStyle(el).color : null;
    }"""
    )
    # Compare against the token itself, never a repeated literal.
    import re

    tokens = Path(TOKENS_CSS).read_text(encoding="utf-8")
    light = re.search(r":root\s*\{(.*?)\n\}", tokens, re.DOTALL).group(1)
    digits = re.search(r"--tc-red:\s*#([0-9A-Fa-f]{6})", light).group(1)
    expected = "rgb(%d, %d, %d)" % tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
    assert computed == expected, (
        f"maths resolved to {computed}, prose token is {expected} — the mapped "
        "element must carry the class AND have its inline colour cleared"
    )


def test_katex_layout_style_survives_the_wrapper(page):
    """Clear the color LONGHAND, not the style attribute: KaTeX packs height and
    vertical-align into the same attribute and removing it destroys the layout."""
    page.set_content("<!DOCTYPE html><div id='m'></div>")
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    heights = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{red}{\\\\frac{1}{2}}', m, {throwOnError: false});
        return [...m.querySelectorAll('[style]')].map(e => e.getAttribute('style'))
            .filter(s => /height|vertical-align/.test(s)).length;
    }"""
    )
    assert heights > 0, "layout declarations must survive"


def test_unmapped_katex_colour_is_left_untouched(page):
    page.set_content("<!DOCTYPE html><div id='m'></div>")
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    html = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{purple}{x}', m, {throwOnError: false});
        return m.innerHTML;
    }"""
    )
    assert "purple" in html
```

- [ ] **Step 7: Run and falsify**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -v
```

Expected: 19 passed.

Falsify: in `mapColours`, delete the `clearInlineColour(el)` call in the
`TC_TAGS[el.tagName]` branch. Re-run. Expected:
`test_katex_colour_resolves_to_the_palette_token` FAILS (computed colour is still raw
red). Restore.

- [ ] **Step 8: Commit**

```bash
uv run ruff format .
git add courses/static/courses/js/text_colour.js templates/courses tests/test_text_colour_script_order.py tests/test_e2e_text_colour.py
git commit -m "feat(text-colour): normalise KaTeX colour onto the palette in both themes"
```

---

### Task 8: The swatch partial, toolbars, and `.rte-swatch` styling

**Files:**
- Create: `templates/courses/manage/editor/_rte_swatches.html`
- Modify: `templates/courses/manage/editor/_rte_toolbar.html`, `_edit_text.html`,
  `_edit_callout.html`, `_edit_spoiler.html`, `_edit_table.html`, `_edit_filltable.html`
- Modify: `courses/static/courses/css/editor.css`
- Test: `tests/test_text_colour_toolbars.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: five controls with `data-cmd="colour-red|colour-blue|colour-green|colour-orange|colour-none"`
  in all six toolbars.

- [ ] **Step 1: Write the failing test**

Create `tests/test_text_colour_toolbars.py`:

```python
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
    assert css.index(".rte-swatch.is-on") > css.index(".rte-btn.is-on"), (
        "declaration order decides this tie; .rte-swatch.is-on must be declared after "
        ".rte-btn.is-on"
    )
```

- [ ] **Step 2: Run to verify it fails**

```
uv run pytest tests/test_text_colour_toolbars.py -v
```

Expected: 4 failures, starting with the missing `_rte_swatches.html`.

- [ ] **Step 3: Create the partial**

Create `templates/courses/manage/editor/_rte_swatches.html`:

```html
{% load i18n %}
{% comment %}
Five colour controls, included by all six toolbars. Extracted into a partial rather
than hand-copied, because there are four separate rte-toolbar markup sites and the two
table toolbars on top; four hand-copies would drift.

Swatch buttons carry .rte-swatch, NOT .rte-btn: .rte-btn.is-on paints a solid --primary
background, which would hide the colour the swatch represents.
{% endcomment %}
<span class="rte-swatches">
  <button type="button" class="rte-swatch rte-swatch--red" data-cmd="colour-red"
          title="{% trans 'Red text' %}" aria-label="{% trans 'Red text' %}"></button>
  <button type="button" class="rte-swatch rte-swatch--blue" data-cmd="colour-blue"
          title="{% trans 'Blue text' %}" aria-label="{% trans 'Blue text' %}"></button>
  <button type="button" class="rte-swatch rte-swatch--green" data-cmd="colour-green"
          title="{% trans 'Green text' %}" aria-label="{% trans 'Green text' %}"></button>
  <button type="button" class="rte-swatch rte-swatch--orange" data-cmd="colour-orange"
          title="{% trans 'Orange text' %}" aria-label="{% trans 'Orange text' %}"></button>
  <button type="button" class="rte-swatch rte-swatch--none" data-cmd="colour-none"
          title="{% trans 'No colour' %}" aria-label="{% trans 'No colour' %}"></button>
</span>
```

- [ ] **Step 4: Include it in all six toolbars**

In `_rte_toolbar.html`, `_edit_text.html`, `_edit_callout.html` and `_edit_spoiler.html`,
insert immediately after the underline button and before the first
`<span class="rte-sep"></span>`:

```html
  {% include "courses/manage/editor/_rte_swatches.html" %}
```

In `_edit_table.html` and `_edit_filltable.html` the RTE rule does not transfer — B/I/U
end at line 38/47 and `∑` follows immediately. Insert the same line **after the `∑`
button and before the opening `<span class="table-editor__aligns">`** in both files, so
the twins land identically.

- [ ] **Step 5: Style the swatches**

Insert into `courses/static/courses/css/editor.css` **immediately after line 231**
(`.rte-btn .ic`) — after `.rte-btn.is-on` at 230, keeping the toolbar rules together.
The ordering is load-bearing, not cosmetic; the Step 1 test pins it:

```css
/* Colour swatches. Deliberately NOT .rte-btn: that class's .is-on state is a solid
   --primary fill, which would repaint the active swatch and hide the colour it
   represents. Specificity between .rte-btn.is-on and .rte-swatch.is-on is a tie
   (0,2,0), so this block must stay AFTER it — tests/test_text_colour_toolbars.py
   pins the order. */
.rte-swatches { display: inline-flex; gap: 3px; align-items: center; }
.rte-swatch {
  width: 18px; height: 18px; padding: 0; cursor: pointer;
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
  background: transparent;
}
.rte-swatch:disabled { opacity: .38; cursor: default; }
.rte-swatch--red { background: var(--tc-red); }
.rte-swatch--blue { background: var(--tc-blue); }
.rte-swatch--green { background: var(--tc-green); }
.rte-swatch--orange { background: var(--tc-orange); }
/* "No colour": a bordered square with a diagonal, drawn in CSS so no sprite entry
   is needed. */
.rte-swatch--none {
  background: linear-gradient(
    to top right,
    transparent calc(50% - 1px), var(--text-secondary) calc(50% - 1px),
    var(--text-secondary) calc(50% + 1px), transparent calc(50% + 1px)
  );
}
.rte-swatch.is-on {
  box-shadow: 0 0 0 2px var(--surface-raised), 0 0 0 4px var(--text-primary);
}
```

- [ ] **Step 6: Run the tests**

```
uv run pytest tests/test_text_colour_toolbars.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Falsify**

Remove the include from `_edit_text.html`. Re-run. Expected:
`test_every_toolbar_includes_the_swatch_partial` FAILS naming that file. Restore.

- [ ] **Step 8: Commit**

```bash
uv run ruff format .
git add templates/courses/manage/editor courses/static/courses/css/editor.css tests/test_text_colour_toolbars.py
git commit -m "feat(text-colour): swatch partial across all six toolbars"
```

---

### Task 9: Wire the RTE surface

**Files:**
- Modify: `courses/static/courses/js/text_toolbar.js`
- Modify: `templates/courses/manage/editor/editor.html` (the refusal message attribute)
- Modify: `tests/test_e2e_text_colour.py`

**Interfaces:**
- Consumes: `window.libliColour.apply/mapColours/tidyPastedSpans/activeSlot`.
- Produces: working swatches on every RTE surface; `data-msg-colour-region` on `.editor`.

- [ ] **Step 1: Write the failing e2e test**

Append to `tests/test_e2e_text_colour.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_colour_survives_save_and_reload(page, live_server):
    """The whole point, driven through the real gesture: type into the editor, select,
    click the red swatch, save, reload, and find the class still stored."""
    from courses.models import TextElement

    _make_pa_user("tc_save")
    _login(page, live_server, "tc_save")
    unit = _seed_course_and_unit("tc_save", slug="tc-save")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("alpha beta")
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-red"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()
    # Wait on a CHILD, not the slot itself: _element_row.html renders
    # <div class="el-edit-slot" data-edit-slot> unconditionally on every row, so the
    # slot survives the save (empty but present) and state="detached" on the bare
    # selector times out. Every shipped e2e scopes to a child for this reason.
    page.wait_for_selector(
        "[data-edit-slot] form[data-op='element-save']", state="detached"
    )

    body = TextElement.objects.order_by("-id").first().body
    assert "tc-red" in body, body
    assert "style" not in body, "colour must be stored as a class, never inline"

    # Reload and reopen — the round-trip half of the claim. classToStyle runs on
    # mount, and this is what proves it leaves tc-* alone.
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator("[data-element] .el-act-edit").first.click()
    page.wait_for_selector("[data-edit-slot] .rte-surface")
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 1


@pytest.mark.django_db(transaction=True)
def test_paste_normalises_in_the_surface_and_the_textarea(page, live_server):
    """styleToClass is a pure STRING function and never touches the live surface, and
    sync is already registered on `input` — so the colour pass must run BEFORE it, or
    the textarea is written from un-normalised DOM and the sanitiser strips the colour
    on any save path that does not go through the form's submit handler."""
    _make_pa_user("tc_paste")
    _login(page, live_server, "tc_paste")
    unit = _seed_course_and_unit("tc_paste", slug="tc-paste")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")
    page.locator("[data-edit-slot] .rte-surface").wait_for(state="visible")

    page.evaluate(
        """() => {
        const s = document.querySelector('[data-edit-slot] .rte-surface');
        s.focus();
        s.innerHTML = '<span style="color: red">x</span>';
        s.dispatchEvent(new InputEvent('input', {inputType: 'insertFromPaste'}));
    }"""
    )
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 1
    value = page.evaluate(
        "() => document.querySelector('[data-edit-slot] [data-rte-source]').value"
    )
    assert "tc-red" in value, (
        "the textarea must carry the class immediately after paste"
    )
    assert "style" not in value


@pytest.mark.django_db(transaction=True)
def test_refusal_shows_the_translated_message(page, live_server):
    _make_pa_user("tc_refuse")
    _login(page, live_server, "tc_refuse")
    unit = _seed_course_and_unit("tc_refuse", slug="tc-refuse")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")
    page.locator("[data-edit-slot] .rte-surface").wait_for(state="visible")

    page.evaluate(
        """() => {
        const s = document.querySelector('[data-edit-slot] .rte-surface');
        s.innerHTML = 'a \\\\(x + y\\\\) b';
        const t = s.firstChild;
        const r = document.createRange();
        r.setStart(t, 3); r.setEnd(t, 4);          // inside the maths region
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    }"""
    )
    page.locator('[data-edit-slot] [data-cmd="colour-red"]').click()
    assert page.locator("[data-colour-refusal]").count() == 1
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 0
```

**Merge into the file's existing header** — Task 5 already created it with
`import pytest` and `pytestmark = pytest.mark.e2e`, so add only `import os`, the five
`tests.test_e2e_editor` imports and the session fixture (the `from pathlib import
Path` and the `ROOT`/`SCRIPT`/`KATEX`/`TOKENS_CSS`/`COURSES_CSS` constants are already
there from Task 5). Re-adding `import pytest`
duplicates it and reddens `ruff check .` with F811. **Reuse the repo's shipped editor
helpers; do not hand-roll them.** `tests/test_e2e_alignment.py` is the
closest shipped analogue of this gesture and is the model to copy:

```python
import os

import pytest

from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield
```

Four things this replaces, each of which was wrong when written by hand:

| hand-rolled | why it fails | use instead |
|---|---|---|
| `page.fill("[name=username]", …)` | allauth's field is `name="login"`, and the shell header has its own submit buttons, so the click must be scoped to the login form | `_login(page, live_server, username)` |
| `UserFactory(is_staff=True)` + `TEST_PASSWORD` | `UserFactory` sets `"password123"` via `PostGenerationMethodCall`, **not** `TEST_PASSWORD`; and mandatory email verification means a user cannot log in without a verified primary `EmailAddress` | `_make_pa_user(username)` |
| `/manage/units/<pk>/edit/` | that route does not exist — the editor is `manage/courses/<slug>/build/unit/<pk>/edit/` (`courses/urls.py:226`) | `_editor_url(live_server, unit)` |
| `Element.objects.create(unit=unit, order=1, content_type_for(body), …)` | positional-after-keyword is a **SyntaxError**, and `content_type_for` does not exist | `tests.factories.add_element(unit, obj)` |

Every test that drives the browser must also carry `@pytest.mark.django_db(transaction=True)`
and seed **inside the test body**. `live_server` runs the app on its own connection in a
separate thread, so rows written inside the plain `db` fixture's uncommitted transaction
are invisible to it and the page 404s.

- [ ] **Step 2: Run to verify it fails**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -k "survives_save or paste_normalises or refusal_shows" -v
```

Expected: FAIL — the swatch click does nothing (no handler wired).

- [ ] **Step 3: Wire the toolbar and the input listener**

In `courses/static/courses/js/text_toolbar.js`, inside `applyCmd`'s `switch`, before
`default:`:

```javascript
      case "colour-red": case "colour-blue":
      case "colour-green": case "colour-orange":
        if (window.libliColour) {
          window.libliColour.apply(surface, cmd.slice("colour-".length));
        }
        break;
      case "colour-none":
        if (window.libliColour) window.libliColour.apply(surface, null);
        break;
```

In `wireRte`, register the colour pass **before** the existing `sync` listener. Replace:

```javascript
    function sync() { textarea.value = styleToClass(surface.innerHTML); }
    surface.addEventListener("input", sync);
```

with:

```javascript
    function sync() { textarea.value = styleToClass(surface.innerHTML); }
    // Registered BEFORE sync: listener order is registration order, so a pass added
    // afterwards would let sync write the textarea from the un-normalised surface.
    // Any save path that does not go through the form's submit handler (the editor's
    // fragment saves) would then store inline colour, which the sanitiser strips --
    // silent colour loss on exactly the pasted content this exists for.
    surface.addEventListener("input", function (e) {
      if (!window.libliColour) return;
      // mapColours FIRST: a pasted <span style="color: red"> matches
      // tidyPastedSpans' predicate exactly, so tidying first would unwrap the carrier
      // and destroy the colour before it could be mapped.
      window.libliColour.mapColours(surface, { dropUnmapped: true });
      if (e.inputType === "insertFromPaste" || e.inputType === "insertFromDrop") {
        window.libliColour.tidyPastedSpans(surface);
      }
    });
    surface.addEventListener("input", sync);
```

In `classToStyle`, leave `tc-*` untouched — it already only rewrites `.ta-*`, so no
change is needed; confirm by reading it.

In `refreshActive`, add the swatch state at the end of the function:

```javascript
      // Swatches. Not part of the flat bold/italic map: the active slot comes from
      // the caret's ancestor class, not from queryCommandState.
      var slot = window.libliColour ? window.libliColour.activeSlot(surface) : null;
      ["red", "blue", "green", "orange"].forEach(function (name) {
        var button = toolbar.querySelector('[data-cmd="colour-' + name + '"]');
        if (button) button.classList.toggle("is-on", slot === name);
      });
```

- [ ] **Step 4: Add the refusal message attribute**

In `templates/courses/manage/editor/editor.html`, on the element that already carries
`data-msg-conflict` (the `.editor` root, line 13):

```html
data-msg-colour-region="{% trans 'Text colour cannot be applied inside a formula or a {{...}} blank.' %}"
```

- [ ] **Step 5: Run the tests**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -v
```

Expected: all pass.

- [ ] **Step 6: Falsify**

Swap the two `input` listeners so `sync` is registered first. Re-run. Expected:
`test_paste_normalises_in_the_surface_and_the_textarea` FAILS on the textarea
assertion. Restore.

- [ ] **Step 7: Commit**

```bash
uv run ruff format .
git add courses/static/courses/js/text_toolbar.js templates/courses/manage/editor/editor.html tests/test_e2e_text_colour.py
git commit -m "feat(text-colour): wire swatches into the rich-text editor"
```

---

### Task 10: Wire the two table editors

**Files:**
- Modify: `courses/static/courses/js/table_editor.js`
- Modify: `courses/static/courses/js/filltable_editor.js`
- Modify: `tests/test_e2e_text_colour.py`

**Interfaces:**
- Consumes: `window.libliColour`.
- Produces: working swatches in both cell editors; colour reaches the saved JSON.

- [ ] **Step 1: Write the failing e2e test**

Append to `tests/test_e2e_text_colour.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_cell_colour_reaches_the_saved_json(page, live_server):
    """Colour applied in a table cell must reach the stored JSON, not just the DOM.

    MEASURED: TableElement.save() calls _sanitized_data, NOT normalize_data, so the
    1x1 grid is stored with exactly the keys authored here.
    """
    from courses.models import Element
    from courses.models import TableElement

    _make_pa_user("tc_cell")
    _login(page, live_server, "tc_cell")
    unit = _seed_course_and_unit("tc_cell", slug="tc-cell")

    table = TableElement.objects.create(
        data={"cells": [[{"html": "abc", "halign": "left", "valign": "top"}]]}
    )
    add_element(unit, table)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    join = Element.objects.get(unit=unit, object_id=table.pk)
    page.locator(f"[data-element='{join.pk}'] .el-act-edit").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")
    cell = page.locator("[data-edit-slot] [data-table-grid] td[contenteditable]").first
    cell.wait_for(state="visible")
    cell.click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-blue"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()
    # Child-scoped, per the note in Task 9 — the slot div itself never detaches.
    page.wait_for_selector("[data-edit-slot] [data-table-editor]", state="detached")

    table.refresh_from_db()
    assert "tc-blue" in table.data["cells"][0][0]["html"], table.data
```

Add `from tests.factories import add_element` to the module's imports.

**Verified:** `data-op="element-edit"` does **not** exist — the only `data-op` values on
an element row are `element-move` and `element-delete`. The real affordance is
`.el-act-edit` scoped by `[data-element='<join pk>']`, and the shipped analogue is
`tests/test_e2e_table_editor.py:100`, **not** `test_e2e_editor.py` (which never opens an
existing element's editor).

- [ ] **Step 2: Run to verify it fails**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -k cell_colour -v
```

Expected: FAIL — `tc-blue` not in the saved JSON.

- [ ] **Step 3: Wire `table_editor.js`**

In the toolbar `click` handler, insert **after `focusCell.focus();` and before
`if (cmd === "bold" …)`**. Not "immediately inside the branch": `var cmd = ...` and
`focusCell.focus();` sit between the `if (` on line 529 and the bold branch, so an
insertion above them reads an undefined `cmd` (var hoisting) and runs before the cell
has focus, leaving `apply()` no selection to act on.

```javascript
          if (cmd.indexOf("colour-") === 0 && window.libliColour) {
            var slot = cmd === "colour-none" ? null : cmd.slice("colour-".length);
            // styleWithCSS must be TRUE for colour (this file forces it false for
            // bold/italic/underline); apply() sets and resets it itself.
            window.libliColour.apply(focusCell, slot);
            serialize();
            return;
          }
```

In the grid `input` listener, before the existing `serialize()` call:

```javascript
      var cell = e.target.closest && e.target.closest("[contenteditable]");
      if (cell && window.libliColour) {
        window.libliColour.mapColours(cell, { dropUnmapped: true });
        if (e.inputType === "insertFromPaste" || e.inputType === "insertFromDrop") {
          window.libliColour.tidyPastedSpans(cell);
        }
      }
```

In `serialize()`, insert as the **first statement of the
`Array.prototype.forEach.call(dataCells(tr), function (td) {` callback — before
`var cell = {`** (line 172). There is no statement position "immediately before
`td.innerHTML`": that read happens at line 173, inside the object literal. The pass must
run over every cell because a paste can land in one that is never focused again:

```javascript
      if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });
```

- [ ] **Step 4: Wire `filltable_editor.js` identically**

The three call expressions are byte-identical to `table_editor.js`, but **the anchors
are not** — this file's shape differs and "the same three edits" is not executable
without them:

| edit | `filltable_editor.js` anchor |
|---|---|
| colour branch | after `focusCell.focus();` at **:731**, before the bold branch |
| `serialize()` pass | first statement of the `Array.prototype.forEach.call(dataCells(tr), function (td) {` callback, **before `if (td.hasAttribute("data-image"))` at :195** — `serialize()` here has **three** `var cell = {` sites (:196 image, :209 answer, :220 static), so "before `var cell = {`" is ambiguous |
| `input` listener | before the `contenteditable` branch's `serialize(); return;` at **:652** — that listener (:651-656) contains **two** `serialize()` calls |

The **inner colour-branch bodies and the `mapColours` / `tidyPastedSpans` call
expressions must be byte-identical** to `table_editor.js`; the
enclosing guards already differ between the twins (`table_editor.js:529` guards
`if (cmdBtn && focusCell)`, `filltable_editor.js:729` adds
`&& focusCell.hasAttribute("contenteditable")`) and stay different.

Note: `filltable_editor.js:379-381` disables every `[data-cmd]` on answer/image cells, so
the swatches inherit that disabled state there for free. `table_editor.js` has no
analogue and does not.

- [ ] **Step 5: Run the tests and the twin-drift guard**

```
uv run pytest tests/test_e2e_text_colour.py -m e2e -v
uv run pytest tests/ -k "twin or drift" -v
```

Expected: all pass. If the #169 twin-drift guard fails, read its message — it fails when
the two editors' shared functions stop matching, and the fix is to edit **both**.

- [ ] **Step 6: Commit**

```bash
uv run ruff format .
git add courses/static/courses/js/table_editor.js courses/static/courses/js/filltable_editor.js tests/test_e2e_text_colour.py
git commit -m "feat(text-colour): wire swatches into both table editors"
```

---

### Task 11: Transfer round-trip, i18n, and the full suite

**Files:**
- Test: `tests/test_text_colour_transfer.py` (create)
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ `.mo`)

**Interfaces:**
- Consumes: everything above.
- Produces: a green suite and translated swatch labels.

- [ ] **Step 1: Write the failing transfer test**

Create `tests/test_text_colour_transfer.py`:

```python
"""D5 says colour reaches production inside a #68 export bundle, with no prod-side
migration. That is the single load-bearing claim for how this work ships, and nothing
tested it. Colour rides inside strings that already round-trip, so this should pass on
the first run — which is exactly why it must exist: if it ever stops passing, the
delivery plan is broken.

Drives the REAL transfer engine through the same sequence tests/test_transfer_import.py
uses. The public API is write_archive(course, node, fileobj) into a file object, then
open_archive(...) as a context manager yielding (zf, mani, doc, media) — there is no
export_course()/import_course(path) pair.
"""

import io

import pytest

from courses.models import Element
from courses.models import TableElement
from courses.models import TextElement
from courses.transfer.export import write_archive
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

BODY = '<p>plain <span class="tc-red">red</span> tail</p>'
CELL = '<b class="tc-blue">cell</b>'


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    """The import path writes real files through default_storage. Copied from
    tests/test_transfer_import.py:48 — without it the import writes into the repo."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    yield


def test_colour_survives_export_and_import():
    course, unit = make_course_with_unit()
    user = course.owner
    body = TextElement.objects.create(body=BODY)
    table = TableElement.objects.create(
        data={"cells": [[{"html": CELL, "halign": "left", "valign": "top"}]]}
    )
    add_element(unit, body)
    add_element(unit, table)

    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course")
        imported = import_course(zf, mani, doc, media, user)

    bodies = [
        e.content_object.body
        for e in Element.objects.filter(unit__course=imported)
        if isinstance(e.content_object, TextElement)
    ]
    assert bodies == [BODY], "tc-* must survive export/import byte-identically"

    tables = [
        e.content_object.data
        for e in Element.objects.filter(unit__course=imported)
        if isinstance(e.content_object, TableElement)
    ]
    assert tables[0]["cells"][0][0]["html"] == CELL
```

**Verified:** `tests.factories.make_course_with_unit(owner=None, **kw)` returns a
**2-tuple** `(course, unit)` — not 3, and not a fixture. `tests/test_transfer_import.py`
has no course/unit fixture at all (it uses a module-level `_mk_full_source_course()`
helper), so do not go looking for one there. The four transfer symbols, the `_media_root`
fixture and `add_element` are all verified to exist with these signatures.

- [ ] **Step 2: Run it**

```
uv run pytest tests/test_text_colour_transfer.py -v
```

Expected: PASS. If it fails, the sanitiser is re-running on import and stripping the
class — read `courses/transfer/importer.py` before changing anything.

- [ ] **Step 3: Falsify**

Temporarily remove `"span"` from `ALLOWED_TAGS`. Re-run. Expected: FAIL. Restore.

- [ ] **Step 4: Extract and translate the six new strings**

```
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Translate in `locale/pl/LC_MESSAGES/django.po`:

| msgid | msgstr |
|---|---|
| `Red text` | `Czerwony tekst` |
| `Blue text` | `Niebieski tekst` |
| `Green text` | `Zielony tekst` |
| `Orange text` | `Pomarańczowy tekst` |
| `No colour` | `Bez koloru` |
| `Text colour cannot be applied inside a formula or a {{...}} blank.` | `Nie można pokolorować tekstu wewnątrz wzoru ani luki {{...}}.` |

Check every new entry for a `#, fuzzy` marker — `makemessages` pre-fills fuzzy
translations from unrelated msgids, and clearing one means deleting **two** lines
(`#, fuzzy` and the `#| msgid` line beneath it).

```
uv run python manage.py compilemessages
```

- [ ] **Step 5: Run the whole suite**

```
uv run ruff format --check .
uv run ruff check .
uv run pytest -x -q
uv run pytest tests/ -m e2e -q
```

Expected: all green. Do not run the two pytest invocations concurrently — they collide
on the `test_libli` database.

- [ ] **Step 6: Commit**

```bash
git add tests/ courses/ locale   # widened: earlier tasks may have been reformatted
git commit -m "test(text-colour): transfer round-trip guard; pl/en catalogues"
```

---

### Task 12: Frontend-design pass at mobile widths

**Files:**
- Possibly modify: `courses/static/courses/css/editor.css`

**Interfaces:**
- Consumes: the shipped toolbars.
- Produces: a judged-acceptable toolbar at 360px in both themes.

- [ ] **Step 1: Screenshot all six toolbars in both themes**

Use the `frontend-design` skill. Capture the RTE toolbar, the callout/spoiler/text inline
toolbars, and both table toolbars at **360px** and at desktop width, in light and dark.
Set the user's theme via `user.theme` — the cookie does not work in e2e.

- [ ] **Step 2: Judge the two risks explicitly**

1. **Wrapping.** The table toolbars already carry bold/italic/underline, `∑`, three
   h-align, three v-align, merge, split and header-toggle. Five more controls at 360px is
   the stated risk. If the group cannot wrap gracefully, the agreed fallback is
   collapsing the swatches into a single popover button **on narrow viewports only** —
   not a redesign of the toolbar.
2. **The active ring.** Confirm the `is-on` swatch shows a ring and is **not** repainted
   solid `--primary`. A test asserting the class is present would pass either way, which
   is why this is judged in a screenshot.

Judge dark mode on its own screenshots — never infer it from the light ones.

- [ ] **Step 3: Commit any CSS fixes — only if Step 2 produced changes**

If the screenshots were acceptable there is nothing to commit; skip to Step 4.
`git commit` on an empty diff exits non-zero and stalls the task — the same failure
mode the `rm` vs `git rm` note in Task 4 guards against.

```bash
git status --porcelain courses/static/courses/css/editor.css   # empty => skip
git add courses/static/courses/css/editor.css
git commit -m "style(text-colour): toolbar polish at mobile widths"
```

- [ ] **Step 4: Open the PR**

```bash
git push -u origin text-colour-palette
gh pr create --title "feat(text-colour): four-slot palette for rich text and table cells" --body "$(cat <<'EOF'
Implements slice 1 of docs/superpowers/specs/2026-07-30-text-colour-design.md.

Authors can colour text in rich text and table cells from a fixed four-slot palette
(red/blue/green/orange). KaTeX maths is normalised onto the same palette, so prose and
formulas agree in both themes.

- Palette measured to clear WCAG AA 4.5:1 on all ten surfaces rich text renders on —
  including the quiz feedback panels, where an earlier palette scored 3.79:1.
- Sanitiser allows `tc-*` classes on inline carriers only; stays purely subtractive.
- Colouring inside a formula or a `{{...}}` marker is refused with a translated message:
  both are permanent corruptions, because markers are parsed after sanitisation and
  `sanitize_cell` escapes markup inside a maths span idempotently.

Slice 2 (the `recolour_imported_content` backfill for the ~588 colour-bearing elements
the LAL import dropped) follows in its own PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PtKjq8ErcP6NQamAhSkFht
EOF
)"
```

---

## Self-review notes

**Spec coverage.** Every normative section maps to a task: palette + surface list → 1;
colour map + drift → 2, 5; storage contract + legacy snapshot → 3; unknowns → 4; D9 two
passes → 5; D8/D10 + clear → 6; KaTeX + load order → 7; four toolbar sites + swatch CSS →
8; RTE wiring + message → 9; both table editors → 10; transfer round-trip + i18n → 11;
frontend-design → 12.

**Deliberately deferred to slice 2's plan:** `recolour_imported_content`, the per-carrier
value rules, the acceptance gate, and the `<dirname>=<pk>` exclusions. Slice 1 defines
`LEGACY_ALLOWED_CLASSES` (Task 3) because the snapshot is only meaningful at the moment
the allowlist changes.

**What plan-review round 1 changed (all defects were in executable artefacts, none in
the design):** four of the plan's own tests went red against its own implementation
(`collapseNested` never ran for class-only markup; `splitOrClear` was dead code because
`textOffsets` could not handle an element container; `wrapKatexRender` was skipped by a
`||` short-circuit; the script-order parser could not see a single `{% static %}`
script). Every KaTeX assertion errored in quirks mode. The whole browser-driving layer
was hand-rolled and wrong four independent ways — a syntax error, allauth's field name,
`UserFactory`'s password, a non-existent editor URL — and the transfer test targeted an
API that does not exist. All are now fixed by reusing the repo's shipped helpers.

**Remaining soft spots, to verify while executing:**
- **Resolved in round 2:** Task 11 uses the verified 2-tuple
  `tests.factories.make_course_with_unit()`; `tests/test_transfer_import.py` has no
  course/unit fixture at all. Task 10 opens the editor with
  `[data-element='<pk>'] .el-act-edit`, per `tests/test_e2e_table_editor.py:100` —
  `data-op="element-edit"` exists nowhere in the repo.
- Task 4's measurements may contradict Task 6's clear implementation. If they do, the
  spec is wrong and must be revised before writing code — do not adapt the code to a
  measurement the spec denies. The table in Task 4 Step 2 states the branch for each.
