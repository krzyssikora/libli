from bs4 import BeautifulSoup

from scripts.lal_import.tables import table_element


def _t(html):
    return BeautifulSoup(html, "html.parser").find("table")


def test_rectangular_table_maps_to_grid():
    el, flags = table_element(
        _t("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>")
    )
    assert el["type"] == "table"
    assert flags == []
    cells = el["data"]["cells"]
    assert cells[0][0]["html"] == "a"
    assert cells[1][1]["html"] == "d"
    assert el["data"]["header_row"] is False


def test_th_first_row_marks_header_row():
    el, _ = table_element(
        _t(
            "<table><tr><th>H1</th><th>H2</th></tr><tr><td>1</td><td>2</td></tr></table>"
        )
    )
    assert el["data"]["header_row"] is True


def test_math_in_cell_preserved_from_escaped_input():
    # Input is already math-escaped (parse_lesson escapes before building the soup),
    # so the cell html carries the entity verbatim — exact assert, not substring.
    el, _ = table_element(_t(r"<table><tr><td>\(a&lt;b\)</td></tr></table>"))
    assert el["data"]["cells"][0][0]["html"] == r"\(a&lt;b\)"


def test_colspan_is_flagged_not_dropped():
    html = (
        '<table><tr><td colspan="2">wide</td></tr><tr><td>a</td><td>b</td></tr></table>'
    )
    el, flags = table_element(_t(html))
    assert el["type"] == "html" and el["flagged"] is True
    assert any(f["kind"] == "table_span" for f in flags)


def test_ragged_rows_flagged():
    el, flags = table_element(
        _t("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>")
    )
    assert el["type"] == "html"
    assert any(f["kind"] == "table_ragged" for f in flags)
