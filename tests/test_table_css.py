from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "courses/static/courses/css/courses.css"


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
