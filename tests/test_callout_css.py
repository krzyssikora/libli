from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"


def test_courses_css_defines_callout_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".callout",
        ".callout__header",
        ".callout__icon",
        ".callout__heading",
        ".callout__body",
        ".callout--example",
        ".callout--note",
        ".callout--tip",
        ".callout--warning",
    ]:
        assert cls in css, f"missing callout class: {cls}"
