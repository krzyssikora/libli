"""The [hidden] attribute is inert against any class that sets `display` at equal
specificity, and this repo has shipped that bug at least five times (see the guards
at core/static/core/css/app.css:42, :185, :546, :1009, :1192). Every rule below is
load-bearing for the editor's instant add/remove; deleting one is a silent visual
regression, so each is asserted individually."""

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
EDITOR_CSS = BASE / "courses" / "static" / "courses" / "css" / "editor.css"
COURSES_CSS = BASE / "courses" / "static" / "courses" / "css" / "courses.css"
APP_CSS = BASE / "core" / "static" / "core" / "css" / "app.css"


def _has_rule(css: str, selector: str) -> bool:
    """True if `selector` heads a rule declaring display:none.

    The selector may appear anywhere in a comma-separated list, so we allow any
    run of further selector characters between it and the `{`. A naive
    `re.escape(selector) + r"\\s*\\{"` matches only the LAST selector in a group —
    `.pair-row[hidden], .choice-row[hidden] { ... }` would report the first as
    missing and the assertion would be red against correct CSS.
    """
    pattern = re.escape(selector) + r"[^{}]*\{[^}]*display:\s*none[^}]*\}"
    return re.search(pattern, css) is not None


def test_row_hidden_guards_in_editor_css():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for selector in (".pair-row[hidden]", ".choice-row[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from editor.css"


def test_del_label_hidden_guards_in_editor_css():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for selector in (".pair-row__del[hidden]", ".choice-row__del[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from editor.css"


def test_row_hidden_guards_in_courses_css():
    css = COURSES_CSS.read_text(encoding="utf-8")
    for selector in (".stepper-row[hidden]", ".markdone-row[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from courses.css"


def test_del_label_hidden_guards_in_courses_css():
    css = COURSES_CSS.read_text(encoding="utf-8")
    for selector in (".stepper-row__del[hidden]", ".markdone-row__del[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from courses.css"


def test_wrapper_is_display_contents():
    """Without this the wrapper becomes a single grid item and .el-editor's
    --space-3 gap between the list and the add button collapses in all five
    editors, with nothing else to catch it."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert re.search(
        r"\[data-fsrows\][^{]*\[data-sgate\]\s*\{[^}]*display:\s*contents", css
    ), "[data-fsrows], [data-sgate] { display: contents } missing from editor.css"


def test_switchgate_remove_style_twin():
    """.el-editor__remove is entirely switchgrid-scoped (app.css:1452-1478), so a
    bare class in a switchgate row inherits nothing and renders a raw UA button."""
    css = APP_CSS.read_text(encoding="utf-8")
    match = re.search(
        r"\.el-editor--switchgate\s+\.el-editor__remove\s*\{([^}]*)\}", css
    )
    assert match, "switchgate .el-editor__remove style twin missing from app.css"
    # Strip comments first: otherwise a stub body of `/* ...display: inline-grid... */`
    # satisfies every assertion below and the test cannot tell a placeholder from
    # the finished rule.
    block = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
    assert "inline-grid" in block, "style twin must set display: inline-grid"
    assert "flex:" in block, "style twin must set flex: 0 0 auto or the x shrinks"
    assert "width:" in block, "style twin must set an explicit size"


def test_switchgate_remove_hidden_guard():
    css = APP_CSS.read_text(encoding="utf-8")
    assert _has_rule(css, ".el-editor--switchgate .el-editor__remove[hidden]"), (
        "switchgate .el-editor__remove[hidden] guard missing from app.css"
    )
