"""The converter's contract. Pure functions over BeautifulSoup nodes: no
database, no filesystem, no fixture directory."""

import pytest
from bs4 import BeautifulSoup

from courses.longdivision.convert import cell_latex
from courses.longdivision.convert import db_text_key
from courses.longdivision.convert import is_long_division
from courses.longdivision.convert import table_to_array
from courses.longdivision.convert import text_key

RULED = ' style="border-bottom: 1px solid black;"'


def _t(html):
    return BeautifulSoup(html, "html.parser").find("table")


def _td(html):
    return BeautifulSoup(html, "html.parser").find("td")


# --- selection rule -------------------------------------------------------


def test_borderless_ruled_table_is_selected():
    t = _t(f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>')
    assert is_long_division(t) is True


def test_bordered_table_is_rejected():
    t = _t(f'<table class="my_table_border"><tr{RULED}><td>\\(1\\)</td></tr></table>')
    assert is_long_division(t) is False


def test_borderless_table_without_a_rule_is_rejected():
    t = _t('<table class="my_table_noborder"><tr><td>\\(1\\)</td></tr></table>')
    assert is_long_division(t) is False


def test_wzor_nazwa_header_is_rejected():
    # The four formula reference tables. Same class, same rule, different job.
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}>'
        "<td>wzór</td><td></td><td>nazwa</td></tr>"
        "<tr><td>\\((a+b)^2\\)</td><td></td><td>kwadrat sumy</td></tr></table>"
    )
    assert is_long_division(t) is False


def test_a_table_with_a_two_run_cell_is_rejected():
    # `\(a\) + \(b\)` has no correct array slot: unwrapping splices the runs and
    # eats the ` + `, and \text{} renders the delimiters literally. So neither
    # the cell nor its table converts -- the table keeps its stored TableElement
    # and the command counts it "not a long division", which is visible.
    # math_reflow.js names this exact shape as the one case that must be refused.
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(a\) + \(b\)</td></tr></table>"
    )
    assert is_long_division(t) is False


def test_a_table_whose_cells_each_hold_one_run_is_still_selected():
    # The refusal is per CELL, not "any \( anywhere in the table".
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(a\)</td><td>\(b\)</td></tr></table>"
    )
    assert is_long_division(t) is True


# --- cells ----------------------------------------------------------------


def test_math_run_is_unwrapped():
    assert cell_latex(_td(r"<td>\(7\)</td>")) == "7"


def test_empty_math_run_is_an_empty_slot():
    assert cell_latex(_td(r"<td>\(\)</td>")) == ""


def test_empty_cell_is_an_empty_slot():
    assert cell_latex(_td("<td></td>")) == ""


def test_prose_cell_is_wrapped_in_text():
    assert cell_latex(_td("<td>nazwa</td>")) == r"\text{nazwa}"


def test_a_two_run_cell_refuses_rather_than_unwrapping_greedily():
    # `^\\\((.*)\\\)$` with re.S matched the WHOLE cell and captured
    # `a\) + \(b` -- two runs spliced into one, the ` + ` gone, no error.
    # Nothing in the corpus hits it; the module outlives the corpus.
    with pytest.raises(ValueError, match="more than one math run"):
        cell_latex(_td(r"<td>\(a\) + \(b\)</td>"))


def test_highlighted_cell_carries_the_mark_class():
    got = cell_latex(_td(r'<td class="red_on_yellow">\(2\)</td>'))
    assert got == r"\htmlClass{mk mk-amber}{2}"


def test_highlight_on_an_empty_cell_does_not_mark_nothing():
    assert cell_latex(_td(r'<td class="red_on_yellow">\(\)</td>')) == ""


# --- whole table ----------------------------------------------------------


def test_rule_becomes_hline_after_the_row_terminator():
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr>'
        "<tr><td>\\(2\\)</td></tr></table>"
    )
    assert table_to_array(t) == "\\begin{array}{r}\n1 \\\\ \\hline\n2\n\\end{array}"


def test_rule_on_the_final_row_still_gets_its_terminator():
    # A bare \hline after the last row is a KaTeX parse error:
    # "\hline valid only within array environment". Hits 130#5, 130#8,
    # 140#5, 140#8 in the real data.
    t = _t(
        '<table class="my_table_noborder"><tr><td>\\(1\\)</td></tr>'
        f"<tr{RULED}><td>\\(2\\)</td></tr></table>"
    )
    assert table_to_array(t).endswith("2 \\\\ \\hline\n\\end{array}")


def test_ragged_rows_pad_to_the_widest():
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr>'
        "<tr><td>\\(2\\)</td><td>\\(3\\)</td></tr></table>"
    )
    out = table_to_array(t)
    assert "\\begin{array}{rr}" in out
    assert "1 &  \\\\ \\hline" in out


def test_columns_are_right_aligned():
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}>'
        "<td>\\(1\\)</td><td>\\(2\\)</td><td>\\(3\\)</td></tr></table>"
    )
    assert "\\begin{array}{rrr}" in table_to_array(t)


def test_no_display_math_wrapper():
    # MathElement renders with displayMode already; a \[...\] wrapper would be
    # typeset as literal text inside the formula.
    t = _t(f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>')
    out = table_to_array(t)
    assert not out.startswith("\\[")
    assert not out.endswith("\\]")


# --- matching keys --------------------------------------------------------


def test_source_and_db_keys_agree_for_the_same_grid():
    # The DB copy lost the rules and the highlights, so cell TEXT is the only
    # signal the two sides still share. The keys must agree despite that.
    t = _t(
        f'<table class="my_table_noborder"><tr{RULED}>'
        r'<td class="red_on_yellow">\(2\)</td><td>\(5\)</td></tr></table>'
    )
    db_cells = [[{"html": r"\(2\)"}, {"html": r"\(5\)"}]]
    assert text_key(t) == db_text_key(db_cells)
