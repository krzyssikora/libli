from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "courses/static/courses/css/courses.css"


def test_courses_css_has_no_legacy_fallback_tokens():
    """courses.css must use the real design tokens, not the pre-consolidation
    legacy fallback names (which have no dark-mode value)."""
    css = CSS.read_text(encoding="utf-8")
    legacy = [
        "--color-success",
        "--color-danger",
        "--color-warning",
        "--color-border",
        "--text-muted",
        "--primary-200",
        "var(--surface,",
        "var(--border,",
        "var(--muted,",
    ]
    present = [name for name in legacy if name in css]
    assert present == [], f"legacy token names still in courses.css: {present}"
    # No `var(--token, #hex)` fallback literals. The retained
    # `.html-el__frame { background: #fff }` is `: #fff`, not `, #`.
    assert ", #" not in css, "var(--token, #hex) fallback found"
    # Standalone raw white must use tokens, not raw #fff.
    # Retained `.html-el__frame { background: #fff }` is `background:`.
    assert "color: #fff" not in css, "raw color: #fff found (use var(--text-inverse))"
    assert "solid #fff" not in css, "raw solid #fff found (use var(--surface-raised))"


def test_uploaded_video_is_constrained_to_its_container():
    """An uploaded <video> (the else branch of videoelement.html) has no intrinsic
    width cap, so without this rule it renders at its native pixel size and overflows
    the panel / preview / a tab. The external-embed <iframe> already gets width:100%."""
    import re

    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"\.el--video\s+video\s*\{([^}]*)\}", css)
    assert m, ".el--video video rule missing (uploaded video overflows its container)"
    block = m.group(1)
    assert "max-width" in block or "width" in block, (
        f"video width not capped: {block!r}"
    )


def test_courses_css_defines_result_components():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".result-summary",
        ".result-summary__score",
        ".result-list",
        ".result-row",
        ".badge--review",
    ]:
        assert cls in css, f"missing result component class: {cls}"


def test_courses_css_defines_code_field():
    css = CSS.read_text(encoding="utf-8")
    for cls in [".code-field", ".code-field__gutter", ".code-field__area"]:
        assert cls in css, f"missing code-field class: {cls}"
    # font-family must use the centralised token (no inline literal), and the token
    # must be defined in tokens.css
    assert "font-family: var(--font-mono)" in css
    tokens = (CSS.parents[4] / "core/static/core/css/tokens.css").read_text(
        encoding="utf-8"
    )
    assert "--font-mono:" in tokens


def test_unit_strip_rules_are_present_and_load_bearing():
    """.unit-strip and .unit-strip .unit-tags carry SIX jointly load-bearing
    declarations. A screenshot a human looks at once does not stop them silently
    returning later. Exactly these six are asserted below, in this order:

    On .unit-strip:
    - display: flex — without it there is no row at all: the panel and the button
      stack vertically and `flex: 1 1 0` below becomes inert. Every other
      assertion here can pass while this one's absence undoes the feature.
    - flex-wrap: wrap — without it the narrow layout overflows horizontally
      instead of dropping the button onto its own line.
    - margin-block, and it must be NON-ZERO — deleting it *or zeroing it*
      reintroduces the 0px gap before .unit-shell in the wrapped layout (where
      .btn contributes no block-end margin). The exact value is left free so it
      can keep tracking tags.css's `.unit-tags { margin: .5rem 0 }`.

    On .unit-strip .unit-tags:
    - min-width: 0 — wrapping the panel in a flex container makes it a flex item
      for the first time (on master it is a plain block child of .app-main).
      Without this, the UA's `min-inline-size: min-content` on
      <fieldset class="unit-tags__picker"> floors the panel's border box at
      min-content and inflates its chrome. This RESTORES master's rendering.
      It only BINDS under a narrow combination — open panel + narrow viewport +
      a long unbreakable label (measured at 400px with a 50-char tag name:
      removing it grows the panel 250→396px and document.scrollWidth 400→412,
      i.e. real horizontal overflow). With an ordinary label, removing it changes
      nothing on screen, so a no-op mutation is NOT evidence the rule is dead.
    - margin-block: 0 — deleting it reintroduces the ~8px top-edge misalignment
      between the two flex items.
    - flex: 1 1 0 — the basis must be 0, not auto. See the inline comment on the
      assertion below; `auto` keeps the button on the row only while the panel is
      CLOSED.
    """
    import re

    css = CSS.read_text(encoding="utf-8")

    strip = re.search(r"\.unit-strip\s*\{([^}]*)\}", css)
    assert strip, ".unit-strip rule missing"
    outer = strip.group(1)
    # display: flex FIRST — it is the declaration every other one here presupposes.
    assert "display: flex" in outer, f"display: flex missing (no row at all): {outer!r}"
    assert "flex-wrap: wrap" in outer, f"flex-wrap: wrap missing: {outer!r}"
    # Value-checked, not substring-checked: `.unit-strip { margin-block: 0 }`
    # reintroduces the very 0px gap this assertion exists to guard, and a bare
    # `"margin-block" in outer` would stay green through it.
    rhythm = re.search(r"margin-block:\s*([^;}]+)", outer)
    assert rhythm, f"the strip must own the block rhythm: {outer!r}"
    assert rhythm.group(1).strip() not in {"0", "0px", "0rem", "0em"}, (
        f"margin-block must be NON-ZERO — zeroing it reintroduces the 0px gap "
        f"before .unit-shell in the wrapped layout: {rhythm.group(1)!r}"
    )

    inner = re.search(r"\.unit-strip\s+\.unit-tags\s*\{([^}]*)\}", css)
    assert inner, (
        ".unit-strip .unit-tags rule missing — note the TWO-class selector is "
        "required: courses.css loads before tags.css, so a bare .unit-tags here "
        "would lose the cascade to tags.css's margin: .5rem 0"
    )
    block = inner.group(1)
    assert "min-width: 0" in block, f"min-width: 0 missing (fieldset hazard): {block!r}"
    assert "margin-block: 0" in block, f"margin-block: 0 missing: {block!r}"
    # The panel must absorb the remaining width so the button is pinned to the row's
    # FAR RIGHT edge. Delete the declaration and the panel shrink-wraps, the button
    # lands beside "Tags (n)", and nothing else in CI notices.
    # The BASIS is load-bearing on its own, and `auto` is wrong: an auto basis makes
    # the flex base size the panel's MAX-CONTENT width, and flex line-breaking uses
    # the base size before shrinking — so with the panel OPEN, .unit-tags__picker
    # (a wrapping fieldset listing every tag the author owns that is not on this
    # unit) overflows the line and flex-wrap drops the button to a second row, at
    # 1280px and not only when narrow. Measured with 12 addable tags: `1 1 auto`
    # wrapped in all of {1280, 900, 600, 400}; `1 1 0` stayed same-row and
    # right-pinned in all of them. So do NOT weaken this to a bare "flex:" check.
    assert "flex: 1 1 0" in block, f"flex: 1 1 0 missing (right-pin): {block!r}"
