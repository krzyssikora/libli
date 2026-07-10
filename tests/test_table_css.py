import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"
TABLE_JS = ROOT / "courses/static/courses/js/table_editor.js"


def test_courses_css_defines_table_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".el--table",
        ".el--table--border-grid",
        ".el--table--border-rows",
        ".el--table--border-header",
        ".el--table--border-none",
        ".ta-center",
        ".va-middle",
    ]:
        assert cls in css, f"missing table element class: {cls}"


def test_editor_css_styles_every_control_class_the_js_emits():
    """table_editor.js injects the row/column handles client-side, so nothing but
    a name match ties its class names to editor.css. They once drifted apart
    (`.table-row-handle` in CSS vs `.table-editor__rowctl` in JS), which left the
    hover-reveal handles permanently unstyled. Pin the contract.
    """
    js = TABLE_JS.read_text(encoding="utf-8")
    css = EDITOR_CSS.read_text(encoding="utf-8")

    emitted = set(re.findall(r'className = "(table-editor__[\w-]+)"', js))
    assert emitted, "expected table_editor.js to assign table-editor__* classes"
    for cls in sorted(emitted):
        assert f".{cls}" in css, (
            f"editor.css never styles .{cls} (emitted by table_editor.js)"
        )
