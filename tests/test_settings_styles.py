"""Regression guard for settings styling (mirrors test_editor_styles.py).

The two settings templates render bespoke controls (.seg/.chip/.tile/.rcard) that
app.css does NOT define; a missing rule = an invisible/broken control. These tests
assert settings.css defines those classes and that both templates link it.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_CSS = ROOT / "core" / "static" / "core" / "css" / "settings.css"
USER_TPL = ROOT / "templates" / "core" / "user_settings.html"
INST_TPL = ROOT / "templates" / "core" / "institution_settings.html"


def test_settings_css_defines_control_classes():
    css = SETTINGS_CSS.read_text(encoding="utf-8")
    for cls in (
        ".settings-wrap",
        ".settings-section",
        ".settings-field",
        ".seg",
        ".chip",
        ".tile",
        ".rcard",
        ".settings-logo-row",
        ".settings-srow",
        ".settings-badge",
        ".settings-save-bar",
    ):
        assert cls in css, f"settings.css must style {cls}"


def test_settings_css_uses_checked_selection():
    # Selection must be :checked-driven (no JS), not a server-set .is-selected class.
    css = SETTINGS_CSS.read_text(encoding="utf-8")
    assert "input:checked" in css


def test_both_templates_link_settings_css():
    for tpl in (USER_TPL, INST_TPL):
        body = tpl.read_text(encoding="utf-8")
        assert "core/css/settings.css" in body, f"{tpl.name} must link settings.css"
