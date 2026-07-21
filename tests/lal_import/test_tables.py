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


def _ft(html):
    # Mirror parse_lesson: escape math <,> on the RAW string BEFORE parsing, so a
    # cell like \(a<b\) reaches fill_table_element as \(a&lt;b\) exactly as in
    # production (html.parser would otherwise mis-read `<b\)` as a tag and swallow
    # the following <input>).
    from bs4 import BeautifulSoup

    from scripts.lal_import.mathsafe import escape_math_delimited

    return BeautifulSoup(escape_math_delimited(html), "html.parser").find("table")


def _answers(table, values):
    # map each table_input node (document order) to a raw answer
    inps = table.find_all(class_="table_input")
    return {id(i): v for i, v in zip(inps, values, strict=True)}


def test_vector_cell_splits_into_bracket_answer_comma_answer_bracket():
    t = _ft(
        "<table><tr>"
        '<td>\\([\\) <input class="table_input"> \\(,\\) '
        '<input class="table_input"> \\(]\\)</td>'
        "</tr></table>"
    )
    result, _flags = fill_table_element(t, _answers(t, ["4", "2"]))
    row = result["data"]["cells"][0]
    kinds = [c["kind"] for c in row]
    assert kinds == ["static", "answer", "static", "answer", "static"]
    assert row[1]["answer"] == "4" and row[3]["answer"] == "2"
    assert "[" in row[0]["html"] and "," in row[2]["html"] and "]" in row[4]["html"]


def test_wrapped_inputs_still_split_two_answers():
    # inputs inside a <span> — recursive find_all + whole-td decode_contents must
    # descend. NOTE (spec-documented limitation): the token split cuts the <span>
    # open, so the static segments are unbalanced fragments ("<span>\([\)" …
    # "\(]\)</span>"). This is accepted: `span` is not in sanitize_cell's CELL_TAGS,
    # so both fragments strip to clean math at load. This test only asserts the
    # ANSWER cells (the correctness-bearing part); static-fragment balancing is the
    # loader's sanitize_cell/nh3 job, not the parser's.
    t = _ft(
        '<table><tr><td><span>\\([\\) <input class="table_input"> \\(,\\) '
        '<input class="table_input"> \\(]\\)</span></td></tr></table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["1", "2"]))
    row = result["data"]["cells"][0]
    answers = [c for c in row if c["kind"] == "answer"]
    assert (
        len(answers) == 2
        and answers[0]["answer"] == "1"
        and answers[1]["answer"] == "2"
    )


def test_split_static_math_reescaped_not_decoded():
    # a comparison in a split static segment must arrive as &lt;, not <
    t = _ft(
        '<table><tr><td><input class="table_input"> \\(a<b\\) '
        '<input class="table_input"></td></tr></table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["1", "2"]))
    mid = [c for c in result["data"]["cells"][0] if c["kind"] == "static"]
    assert any("a&lt;b" in c["html"] for c in mid)
    assert not any("a<b" in c["html"] for c in mid)  # never the decoded form


def test_adjacent_inputs_no_spurious_static_column():
    for gap in ("&nbsp;", "<br>", " "):
        t = _ft(
            f'<table><tr><td><input class="table_input">{gap}'
            f'<input class="table_input"></td></tr></table>'
        )
        result, _ = fill_table_element(t, _answers(t, ["1", "2"]))
        row = result["data"]["cells"][0]
        assert [c["kind"] for c in row] == ["answer", "answer"], f"gap={gap!r} -> {row}"


def test_real_content_gap_keeps_static():
    t = _ft(
        '<table><tr><td><input class="table_input"> \\(,\\) '
        '<input class="table_input"></td></tr></table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["1", "2"]))
    assert [c["kind"] for c in result["data"]["cells"][0]] == [
        "answer",
        "static",
        "answer",
    ]


def test_interleaved_image_segment_becomes_image_cell():
    t = _ft(
        '<table><tr><td><input class="table_input">'
        '<img src="static/x.png"><input class="table_input"></td></tr></table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["1", "2"]))
    row = result["data"]["cells"][0]
    assert [c["kind"] for c in row] == ["answer", "image", "answer"]
    assert row[1]["media_src"] == "static/x.png"


def test_single_input_cell_unchanged():
    t = _ft('<table><tr><td><input class="table_input"></td></tr></table>')
    result, _ = fill_table_element(t, _answers(t, ["7"]))
    row = result["data"]["cells"][0]
    assert [c["kind"] for c in row] == ["answer"] and row[0]["answer"] == "7"


def test_rows_padded_rectangular_and_header_ok():
    # header row (2 cells) shorter than a 5-cell split data row -> padded to 5
    t = _ft(
        "<table>"
        "<tr><th>wektor</th><th>wsp</th></tr>"
        '<tr><td>\\([\\) <input class="table_input"> \\(,\\) '
        '<input class="table_input"> \\(]\\)</td><td>x</td></tr>'
        "</table>"
    )
    result, _ = fill_table_element(t, _answers(t, ["4", "2"]))
    cells = result["data"]["cells"]
    w = len(cells[0])
    assert all(len(r) == w for r in cells)  # rectangular
    assert result["data"]["header_row"] is True  # header still detected


def test_single_input_table_regression_unchanged():
    # a table with only single-input cells parses to the same shape as before
    t = _ft('<table><tr><td>a</td><td><input class="table_input"></td></tr></table>')
    result, _ = fill_table_element(t, _answers(t, ["9"]))
    assert result["data"]["cells"][0] == [
        {"kind": "static", "html": "a"},
        {"kind": "answer", "answer": "9"},
    ]
