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
    # Same argument for the clipboard's four classes: _element_row.html,
    # _editor_scope.html and _paste_buttons.html reference them and nothing else
    # styles them, so an unstyled .el-row--marked is indistinguishable from a
    # broken mark. A screenshot pass is a one-off; this is the standing guard.
    for cls in (".el-row--marked", ".clip-banner", ".pastewrap", ".pastebtn"):
        assert cls in css, f"editor.css must style {cls}"


BUILDER_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "builder.css"
)
EDITOR_HTML = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "courses"
    / "manage"
    / "editor"
    / "editor.html"
)


def test_editor_page_links_no_builder_css():
    # The badge rules are DUPLICATED into editor.css precisely because this page does
    # not load builder.css. That constraint was previously only prose in this module's
    # docstring -- adding builder.css to the editor page would have kept the suite
    # green. Now it cannot.
    assert "builder.css" not in EDITOR_HTML.read_text(encoding="utf-8")


def test_editor_css_defines_every_class_the_link_ui_uses():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for cls in (
        ".link-dialog",
        ".link-picker__scope",
        ".link-picker__item",
        ".link-picker__row",
        ".link-picker__title",
        ".tree__badge",
        # Exact substring: data-scope is NOT editor-only (the builder puts it on every
        # tree scope), so a "simplification" to [data-scope] .el a would break the
        # builder, and deleting the rule lets a preview click discard unsaved work --
        # both silently.
        '[data-scope="preview"] .el a',
    ):
        assert cls in css, f"editor.css must style {cls}"


def test_duplicated_badge_rules_match_their_twin():
    # A class-name substring check cannot catch what this duplication actually risks:
    # the two copies drifting. Compare declarations. All THREE duplicated rules, not
    # just the base one -- editor.css:920-921 duplicates the --part/--chapter/--section
    # and --unit modifiers too, and each can drift independently of the others.
    import re

    def decls(text, selector):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text)
        assert m, f"{selector} not found"
        return {d.strip() for d in m.group(1).split(";") if d.strip()}

    editor = EDITOR_CSS.read_text(encoding="utf-8")
    builder = BUILDER_CSS.read_text(encoding="utf-8")
    for selector in (
        ".tree__badge",
        ".tree__badge--part, .tree__badge--chapter, .tree__badge--section",
        ".tree__badge--unit",
    ):
        assert decls(editor, selector) == decls(builder, selector), selector
