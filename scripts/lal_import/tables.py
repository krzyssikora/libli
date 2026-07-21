"""Convert a source <table> to a rectangular TableElement grid, or flag it.

The table tag comes from an already-math-escaped soup (parse_lesson escapes the
raw HTML before parsing), so cell content is emitted verbatim — never re-escaped.
"""

import re


def _rows(table):
    # Flatten thead/tbody: any <tr> anywhere under the table.
    return table.find_all("tr")


def _cells(tr):
    return [c for c in tr.find_all(["td", "th"], recursive=False)] or tr.find_all(
        ["td", "th"]
    )


def _flag_html(table, kind, reason):
    return (
        {"type": "html", "flagged": True, "raw": str(table), "reason": reason},
        [{"kind": kind, "reason": reason, "raw_excerpt": str(table)[:300]}],
    )


def _answer_alternatives(raw):
    """A decimal answer accepts both dot and Polish-comma forms (mirrors the LAL
    standardizeDP eval); a fraction/integer/string is kept verbatim."""
    if "." in raw and "/" not in raw:
        return raw + "|" + raw.replace(".", ",")
    return raw


# Mirror courses.models.FillTableElement.MAX_COLS (hardcoded to keep this pure
# parser module free of a Django-models import; the guard is unreachable for the
# current corpus, widest split = 6 cols).
_MAX_COLS = 20

_TOKEN_RE = re.compile("￿\\d+￿")


def _segment_cell(seg):
    """Classify one static segment (from the token split) into a cell dict, or
    None to drop it. Image is checked BEFORE emptiness: a lone <img> has empty
    get_text and would otherwise be dropped."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(seg, "html.parser")
    text = soup.get_text(strip=True)
    imgs = soup.find_all("img")
    if not text and len(imgs) == 1:
        img = imgs[0]
        return {
            "kind": "image",
            "media_src": img.get("src", ""),
            "alt": img.get("alt", ""),
        }
    if text:
        return {"kind": "static", "html": seg.strip()}
    return None  # whitespace/&nbsp;/<br>-only -> no spurious column


def _split_multi_input_cell(c, answer_by_input):
    """A <td> with >=2 table_input inputs -> a run of cells: static segments
    (interleaved math) around one answer cell per input. Placeholder-token
    technique: record each input's answer by id() from the ORIGINAL node, replace
    it with a U+FFFF sentinel, decode_contents() the whole <td> ONCE (byte-identical
    re-escaping to the static path), split on the tokens."""
    inputs = c.find_all(class_="table_input")
    answers = []
    for i, inp in enumerate(inputs):
        answers.append(_answer_alternatives(answer_by_input.get(id(inp), "")))
        inp.replace_with(f"￿{i}￿")
    segments = _TOKEN_RE.split(c.decode_contents())  # len == len(inputs) + 1
    out = []
    for i, seg in enumerate(segments):
        cell = _segment_cell(seg)
        if cell is not None:
            out.append(cell)
        if i < len(answers):
            out.append({"kind": "answer", "answer": answers[i]})
    return out


def fill_table_element(table, answer_by_input):
    """A <table> holding <input class="table_input"> cells -> FillTableElement
    grid: an input cell becomes an `answer` cell (its accepted answer looked up
    in `answer_by_input` by input node id), every other cell stays `static`.
    Falls back to a flagged html element on an irregular (span/nested/ragged)
    grid, exactly like table_element."""
    rows = _rows(table)
    if not rows:
        return _flag_html(table, "table_empty", "table has no rows")
    grid = [_cells(tr) for tr in rows]
    for tr in rows:
        for c in tr.find_all(["td", "th"]):
            if c.get("colspan") or c.get("rowspan"):
                return _flag_html(table, "table_span", "table uses rowspan/colspan")
    if any(c.find("table") for tr in rows for c in tr.find_all(["td", "th"])):
        return _flag_html(table, "table_nested", "table nests another table")
    width = len(grid[0])
    if any(len(r) != width for r in grid):
        return _flag_html(table, "table_ragged", "rows have differing cell counts")

    header_row = all(c.name == "th" for c in grid[0])
    header_col = all(r[0].name == "th" for r in grid)
    pristine_raw = str(table)  # BEFORE any replace_with (MAX_COLS fallback uses this)
    did_split = False
    cells = []
    for r in grid:
        row = []
        for c in r:
            inputs = c.find_all(class_="table_input")
            if len(inputs) >= 2:
                did_split = True
                row.extend(_split_multi_input_cell(c, answer_by_input))
            elif len(inputs) == 1:
                raw = answer_by_input.get(id(inputs[0]), "")
                row.append({"kind": "answer", "answer": _answer_alternatives(raw)})
            elif not c.get_text(strip=True) and len(c.find_all("img")) == 1:
                # a pure image cell (only an <img>, maybe a stray <br>): keep the
                # image as an image cell; the loader resolves media_src -> MediaAsset.
                img = c.find("img")
                row.append(
                    {
                        "kind": "image",
                        "media_src": img.get("src", ""),
                        "alt": img.get("alt", ""),
                    }
                )
            else:
                row.append({"kind": "static", "html": c.decode_contents().strip()})
        cells.append(row)
    out_width = max(len(r) for r in cells)
    if out_width > _MAX_COLS:
        return (
            {
                "type": "html",
                "flagged": True,
                "raw": pristine_raw,
                "reason": "table_too_wide",
            },
            [
                {
                    "kind": "table_too_wide",
                    "reason": "split exceeds MAX_COLS",
                    "raw_excerpt": pristine_raw[:300],
                }
            ],
        )
    for r in cells:
        while len(r) < out_width:
            r.append({"kind": "static", "html": ""})
    data = {
        "header_row": header_row,
        "header_col": header_col,
        # A split (multi-input) grid uses horizontal-only borders so a vector
        # cell reads as a continuous "[ x , y ]" instead of the "grid" border
        # fragmenting the brackets/comma into separate boxed columns.
        "border": "rows" if did_split else "grid",
        "cells": cells,
    }
    return {"type": "fill_table", "data": data}, []


def table_element(table):
    rows = _rows(table)
    if not rows:
        return _flag_html(table, "table_empty", "table has no rows")

    grid = [_cells(tr) for tr in rows]

    # Reject spans.
    for tr in rows:
        for c in tr.find_all(["td", "th"]):
            if c.get("colspan") or c.get("rowspan"):
                return _flag_html(table, "table_span", "table uses rowspan/colspan")
    # Nested table?
    if any(c.find("table") for tr in rows for c in tr.find_all(["td", "th"])):
        return _flag_html(table, "table_nested", "table nests another table")
    # Ragged?
    width = len(grid[0])
    if any(len(r) != width for r in grid):
        return _flag_html(table, "table_ragged", "rows have differing cell counts")

    header_row = all(c.name == "th" for c in grid[0])
    header_col = all(r[0].name == "th" for r in grid)

    cells = []
    for r in grid:
        cells.append(
            [
                {
                    "html": c.decode_contents().strip(),  # already escaped
                    "halign": "left",
                    "valign": "top",
                }
                for c in r
            ]
        )
    data = {
        "header_row": header_row,
        "header_col": header_col,
        "border": "grid",
        "cells": cells,
    }
    return {"type": "table", "data": data}, []
