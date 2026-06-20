# tests/test_dnd_render.py
from courses import dnd


def test_render_select_has_empty_placeholder_and_escapes():
    html = str(dnd._render_select(["a", "<b>"], chosen=None))
    assert '<select name="slot"' in html
    assert '<option value="">' in html  # mandatory empty placeholder
    assert "&lt;b&gt;" in html          # token HTML-escaped in option
    assert "<b>" not in html


def test_render_select_preselects_member_else_placeholder():
    member = str(dnd._render_select(["Paris", "Rome"], chosen="Paris"))
    assert '<option value="Paris" selected>' in member
    # deleted/non-member token → placeholder selected, no real option selected
    gone = str(dnd._render_select(["Paris", "Rome"], chosen="Berlin"))
    assert '<option value="" selected>' in gone
    assert "selected>Paris" not in gone.replace('value="Paris" ', 'value="Paris"')


def test_render_select_preselects_normalize_variant_member():
    # A stored value differing from the pool's raw survivor only by case/space must
    # still pre-select that option (render/mark agree on normalized membership, C2).
    variant = str(dnd._render_select(["Paris", "Rome"], chosen="  paris "))
    assert '<option value="Paris" selected>' in variant
    assert '<option value="" selected>' not in variant


def test_render_selects_splices_one_select_per_gap():
    html = str(dnd.render_selects("A ￿0￿ B ￿1￿", ["x", "y"], chosen=["x", ""]))
    assert html.count('<select name="slot"') == 2
    assert "A " in html and " B " in html       # text segments preserved
    assert '<option value="x" selected>' in html  # gap 0 pre-selected


def test_render_match_rows_one_select_per_pair_with_left_label():
    class P:
        def __init__(self, left):
            self.left = left

    html = str(dnd.render_match_rows([P("France"), P("Spain")], ["Paris"], chosen=["Paris", ""]))
    assert html.count('<select name="slot"') == 2
    assert "France" in html and "Spain" in html
