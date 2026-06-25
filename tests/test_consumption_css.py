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
    # and NO `var(--token, #hex)` fallback literal should remain anywhere. The one
    # raw colour kept on purpose — `.html-el__frame { background: #fff }` — is `: #fff`,
    # not `, #`, so this guard does not trip on it.
    assert ", #" not in css, "a var(--token, #hex) fallback literal remains in courses.css"
    # standalone raw white on the primary-fill chips/badges must be tokenised too
    # (the retained `.html-el__frame { background: #fff }` is `background:`, so neither trips)
    assert "color: #fff" not in css, "raw `color: #fff` remains (use var(--text-inverse))"
    assert "solid #fff" not in css, "raw `solid #fff` border remains (use var(--surface-raised))"


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
