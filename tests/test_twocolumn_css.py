from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"


def test_twocolumn_css_present():
    # courses.css is the stylesheet that holds .el--tabs (mirror tests/test_tabs_css.py)
    css = CSS.read_text(encoding="utf-8")
    assert ".el--twocolumn" in css
    assert "flex-wrap" in css
