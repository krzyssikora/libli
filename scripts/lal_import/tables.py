"""Convert a source <table> to a rectangular TableElement grid, or flag it.

The table tag comes from an already-math-escaped soup (parse_lesson escapes the
raw HTML before parsing), so cell content is emitted verbatim — never re-escaped.
"""


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
