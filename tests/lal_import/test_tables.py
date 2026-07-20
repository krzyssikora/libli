from bs4 import BeautifulSoup

from scripts.lal_import.tables import fill_table_element
from scripts.lal_import.tables import table_element


def _t(html):
    return BeautifulSoup(html, "html.parser").find("table")


def _fill_table(html):
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


def test_pure_image_cell_becomes_image_kind():
    # one input cell (so it routes to fill_table) + one pure-<img> cell
    t = _fill_table(
        "<table>"
        '<tr><td><img src="static/g.png" alt="graph"></td>'
        '<td><input class="table_input"></td></tr>'
        "</table>"
    )
    inp = t.find("input", class_="table_input")
    result, _flags = fill_table_element(t, {id(inp): "5"})
    cells = result["data"]["cells"]
    assert cells[0][0] == {"kind": "image", "media_src": "static/g.png", "alt": "graph"}
    assert cells[0][1]["kind"] == "answer"


def test_image_cell_with_only_stray_br_still_image():
    t = _fill_table(
        "<table><tr>"
        '<td><img src="static/v.png"><br></td>'
        '<td><input class="table_input"></td>'
        "</tr></table>"
    )
    inp = t.find("input", class_="table_input")
    result, _ = fill_table_element(t, {id(inp): "1"})
    assert result["data"]["cells"][0][0]["kind"] == "image"


def test_mixed_text_and_image_cell_stays_static():
    # meaningful text alongside the image -> falls through to static (image dropped,
    # documenting the deliberate non-split; no such cell exists in the corpus)
    t = _fill_table(
        "<table><tr>"
        '<td>Look: <img src="static/g.png"></td>'
        '<td><input class="table_input"></td>'
        "</tr></table>"
    )
    inp = t.find("input", class_="table_input")
    result, _ = fill_table_element(t, {id(inp): "1"})
    assert result["data"]["cells"][0][0]["kind"] == "static"
