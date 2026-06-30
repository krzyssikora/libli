"""Regression guard for settings styling (mirrors test_editor_styles.py).

The user-settings template renders bespoke controls (.seg/.chip/.tile/.rcard) that
app.css does NOT define; a missing rule = an invisible/broken control. These tests
assert core/css/settings.css defines those classes and that user_settings.html links
it. The 5c institution-settings surface lives at templates/institution/manage/
settings.html and carries its own institution/settings.css — guarded separately.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_CSS = ROOT / "core" / "static" / "core" / "css" / "settings.css"
USER_TPL = ROOT / "templates" / "core" / "user_settings.html"
INST_TPL = ROOT / "templates" / "institution" / "manage" / "settings.html"


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


def test_user_settings_links_core_settings_css():
    body = USER_TPL.read_text(encoding="utf-8")
    assert "core/css/settings.css" in body, "user_settings.html must link settings.css"


def test_institution_settings_links_its_css():
    # 5c surface ships its own stylesheet rather than the user-page settings.css.
    body = INST_TPL.read_text(encoding="utf-8")
    assert "institution/settings.css" in body, (
        "institution/manage/settings.html must link institution/settings.css"
    )
