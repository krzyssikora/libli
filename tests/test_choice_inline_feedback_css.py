from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"


def test_inline_feedback_classes_are_styled():
    css = CSS.read_text(encoding="utf-8")
    assert ".question__choice-feedback" in css
    assert ".question__choice-marker" in css
    assert "--wrong" in css and "--missed" in css
