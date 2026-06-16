"""Regression guards for editor styling gaps that aren't unit-testable via rendering.

Root cause of the dark-theme 'invisible buttons' bug: the editor templates reuse the
builder's `.tree__act` / `.tree__inline` classes (the ↑/↓/Delete element-row controls),
but the editor page does NOT load builder.css — so those buttons fell back to UA-default
rendering (light glyph on a light UA button face = invisible in dark mode). These tests
assert the editor's own stylesheet defines the action-button classes it depends on.
"""

from pathlib import Path

EDITOR_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "editor.css"
)


def test_editor_css_styles_action_buttons():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    # The classes the editor's _element_row.html relies on must be styled here, since
    # builder.css (their other home) is not loaded on the editor page. Otherwise the
    # buttons fall back to invisible UA defaults in dark mode.
    for cls in (".tree__act", ".tree__act--danger", ".tree__inline"):
        assert cls in css, f"editor.css must style {cls}"
