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


def test_tree_title_input_neutralises_the_global_form_control_rule():
    # app.css styles input[type=text] with a sunken background, a strong border and
    # padding. It ties input.tree__title on specificity (0,1,1) and is only beaten by
    # builder.css loading later, so the rule must explicitly reset each property --
    # assert the DECLARATIONS, not specificity.
    css = _css()
    rule = re.search(r"input\.tree__title\s*\{[^}]*\}", css)
    assert rule, "the rule must be written literally as `input.tree__title { ... }`"
    body = rule.group(0)
    assert re.search(r"font:\s*inherit", body), (
        "an <input> does not inherit font-family/font-size; without font:inherit every "
        "tree label falls back to the UA default (~13.33px Arial)"
    )
    assert re.search(r"background:\s*none", body), "must reset the sunken background"
    assert re.search(r"padding:\s*0", body), "must reset the global padding"
    assert re.search(r"border:\s*1px\s+solid\s+transparent", body), (
        "a transparent rest border keeps :hover layout-neutral -- adding a border on "
        "hover to a border-less element shifts text and grows the row"
    )


def test_tree_title_is_a_shrinkable_flex_item():
    """The title input is the row's flex item now that .tree__rename is gone.

    `flex: 1 1 auto` is the trap this guards, not a style preference: with an
    `auto` basis the base size is max-content and the row's wrap decision is made
    on that BEFORE shrinking, so one long title drops the whole control cluster
    onto a second line. min-width:0 does not fix it.
    """
    css = _css()
    rule = re.search(r"input\.tree__title\s*\{[^}]*\}", css)
    assert rule, "input.tree__title must be styled"
    body = rule.group(0)
    assert re.search(r"flex:\s*1\s+1\s+0", body), (
        "must be `flex: 1 1 0` -- `1 1 auto` or a width sizes the row on max-content"
    )
    assert re.search(r"min-width:\s*0", body), (
        "without it the input's min-content width keeps the row from shrinking"
    )


def test_busy_state_does_not_block_pointer_events():
    """If it did, the per-toggle in-flight guard would be dead code and
    test_double_click_yields_exactly_one_scope would pass vacuously."""
    css = _css()
    block = re.search(r"\.builder\[data-busy\][^{]*\{([^}]*)\}", css)
    assert block, "no [data-busy] rule found"
    assert "pointer-events" not in block.group(1)


def test_the_info_slot_hides_when_empty_via_empty_not_hidden():
    css = _css()  # the file's existing helper (line 14)
    assert ".builder__info:empty" in css
    assert "display: none" in css.split(".builder__info:empty")[1].split("}")[0]


def test_the_filter_control_is_styled():
    css = _css()
    assert ".builder__filter" in css
