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


def test_builder_tree_column_can_shrink():
    # The 2fr grid track must be allowed to shrink below its content width, else a
    # long nowrap title balloons the track and breaks the 2:1 ratio. This needs
    # min-width:0 on the grid item itself — .tree__title's own min-width:0 only
    # bounds truncation within the row.
    assert re.search(r"\.builder__tree\s*\{[^}]*min-width:\s*0", _css()), (
        ".builder__tree needs min-width:0 so the 2fr column can shrink"
    )


def test_builder_panel_column_can_shrink():
    # The 1fr panel track ALSO needs min-width:0, else the content-heavy unit detail
    # panel balloons its track when a unit is selected and steals width back from the
    # tree (measured collapse of the ratio from 2.0 to ~0.73). Bare .builder__panel
    # rule (not a descendant selector).
    assert re.search(r"\.builder__panel\s*\{[^}]*min-width:\s*0", _css()), (
        ".builder__panel needs min-width:0 so the 1fr panel track can't balloon"
    )


def test_element_list_item_can_shrink():
    # The element-list row is a flex item; without min-width:0 its auto minimum grows
    # to the nowrap __summary's content width and overflows the narrowed 1/3 panel
    # horizontally (the __summary's own min-width:0 only bounds it once the row is
    # itself bounded).
    assert re.search(r"\.element-list__item\s*\{[^}]*min-width:\s*0", _css()), (
        ".element-list__item needs min-width:0 so its summary can truncate in-panel"
    )
