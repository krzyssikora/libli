import re
from pathlib import Path

BUILDER_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "builder.css"
)


def _css():
    return BUILDER_CSS.read_text(encoding="utf-8")


def test_builder_columns_are_two_to_one():
    m = re.search(r"\.builder\s*\{[^}]*grid-template-columns:\s*2fr\s+1fr", _css())
    assert m, ".builder must use a 2fr 1fr column ratio"


def test_course_panel_is_flex_column():
    m = re.search(
        r'\.builder__panel\s+\.panel\[data-panel-for="course"\]\s*\{[^}]*'
        r"flex-direction:\s*column",
        _css(),
    )
    assert m, 'course panel must be a flex column (scoped to [data-panel-for="course"])'


def test_tree_title_truncates_with_ellipsis():
    css = _css()
    assert re.search(r"\.tree__title\s*\{[^}]*text-overflow:\s*ellipsis", css), (
        ".tree__title must truncate with an ellipsis"
    )
    assert re.search(r"\.tree__title\s*\{[^}]*min-width:\s*0", css), (
        ".tree__title needs min-width:0 to shrink below content width"
    )
    assert re.search(r"\.tree__title\s*\{[^}]*white-space:\s*nowrap", css), (
        ".tree__title needs white-space:nowrap for single-line truncation"
    )
