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
