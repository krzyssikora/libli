import re
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
        ".callout--task",
    ]:
        assert cls in css, f"missing callout class: {cls}"


def test_callout_task_light_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    # ^-anchored: without it this pattern also matches inside the dark selector,
    # so deleting the light rule would leave the test green.
    assert re.search(
        r"^\.callout--task\s*\{\s*--callout-accent:\s*#a8318f", css, re.M
    ), "light .callout--task accent missing or changed"


def test_callout_task_dark_accent_is_pinned():
    css = CSS.read_text(encoding="utf-8")
    assert re.search(
        r'^\[data-theme="dark"\]\s+\.callout--task\s*\{\s*--callout-accent:\s*#ee9fd8',
        css,
        re.M,
    ), "dark .callout--task accent missing or changed"
