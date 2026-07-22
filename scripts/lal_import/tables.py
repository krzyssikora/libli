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


def _segment_cell(seg, halign):
    """Classify one static segment (from the token split) into a cell dict, or
    None to drop it. Image is checked BEFORE emptiness: a lone <img> has empty
    get_text and would otherwise be dropped. `halign` positions the segment so an
    opening bracket hugs the input to its right and a closing bracket the input to
    its left (a segment cell inherits the column's width, which the header can make
    wide, so left-aligned brackets would drift far from their input)."""
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
        return {"kind": "static", "html": seg.strip(), "halign": halign}
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
    last = len(segments) - 1
    out = []
    for i, seg in enumerate(segments):
        # opening segment hugs the input to its right (right-align); closing hugs
        # the input to its left (left-align); a separator between inputs is centred.
        halign = "right" if i == 0 else "left" if i == last else "center"
        cell = _segment_cell(seg, halign)
        if cell is not None:
            out.append(cell)
        if i < len(answers):
            out.append({"kind": "answer", "answer": answers[i]})
    return out


def _image_with_details(c):
    """A cell that is a diagram PLUS an explanatory <details> (250_pole_trojkata:
    `<img><br><details><summary>wyjaśnienie</summary>…</details>`). A fill cell
    holds exactly one thing, so the caller makes the diagram an `image` cell and
    re-emits the explanation as its own full-width row. Returns (img, [details, …])
    only when the cell's sole non-<details> content is one <img> — a cell with
    other text, or whose image lives INSIDE the explanation, is left alone."""
    details = c.find_all("details")
    if not details:
        return None, []
    imgs = c.find_all("img")
    if len(imgs) != 1 or imgs[0].find_parent("details") is not None:
        return None, []
    for s in c.find_all(string=True):
        if s.strip() and s.find_parent("details") is None:
            return None, []  # stray text beside the diagram -> not a clean split
    return imgs[0], details


def _explanation_html(details):
    """The <details> content as cell HTML, its <summary> kept as a leading bold
    label. The cell sanitizer drops <details>/<summary>, so the collapse cannot
    survive in-cell; the label preserves what the disclosure was called."""
    summary = details.find("summary")
    label = summary.get_text(strip=True) if summary is not None else ""
    if summary is not None:
        summary.extract()
    body = details.decode_contents().strip()  # already math-escaped; never re-escape
    return (f"<strong>{label}</strong> " if label else "") + body


def _fill_span_table(grid, answer_by_input):
    """A colspan/rowspan fill table -> a native FillTableElement with RAGGED rows,
    each cell's span + <th>-ness preserved. An input cell -> answer, a pure <img>
    cell -> image, else static. The multi-input column-split (a rectangular-grid
    transform) doesn't apply here -- spans + multi-input cells don't co-occur."""
    cells = []
    for r in grid:
        row = []
        for c in r:
            inputs = c.find_all(class_="table_input")
            if inputs:
                raw = answer_by_input.get(id(inputs[0]), "")
                cell = {"kind": "answer", "answer": _answer_alternatives(raw)}
            elif not c.get_text(strip=True) and len(c.find_all("img")) == 1:
                img = c.find("img")
                cell = {
                    "kind": "image",
                    "media_src": img.get("src", ""),
                    "alt": img.get("alt", ""),
                }
            else:
                cell = {"kind": "static", "html": c.decode_contents().strip()}
            if c.name == "th":
                cell["header"] = True
            for key in ("colspan", "rowspan"):
                v = str(c.get(key) or "").strip()
                if v.isdigit() and int(v) > 1:
                    cell[key] = int(v)
            row.append(cell)
        cells.append(row)
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": cells,
    }
    return {"type": "fill_table", "data": data}, []


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
    if any(c.find("table") for tr in rows for c in tr.find_all(["td", "th"])):
        return _flag_html(table, "table_nested", "table nests another table")

    def _has_real_span(c):
        return any(
            str(c.get(k) or "").strip().isdigit() and int(c.get(k)) > 1
            for k in ("colspan", "rowspan")
        )

    if any(_has_real_span(c) for tr in rows for c in tr.find_all(["td", "th"])):
        return _fill_span_table(grid, answer_by_input)
    width = len(grid[0])
    if any(len(r) != width for r in grid):
        return _flag_html(table, "table_ragged", "rows have differing cell counts")

    header_row = all(c.name == "th" for c in grid[0])
    header_col = all(r[0].name == "th" for r in grid)
    pristine_raw = str(table)  # BEFORE any replace_with (MAX_COLS fallback uses this)
    did_split = False
    # Build per-ORIGINAL-column groups for each row: a normal cell -> a 1-element
    # group; a split (>=2-input) cell -> the run of sub-cells. Keeping the groups
    # (instead of a flat row) lets the header label align with the column's input.
    grid_groups = []
    explanations = {}  # row index -> [explanation html, ...] to insert BELOW that row
    for ri, r in enumerate(grid):
        row_groups = []
        for c in r:
            inputs = c.find_all(class_="table_input")
            img_d, det = _image_with_details(c)
            if len(inputs) >= 2:
                did_split = True
                row_groups.append(_split_multi_input_cell(c, answer_by_input))
            elif len(inputs) == 1:
                raw = answer_by_input.get(id(inputs[0]), "")
                row_groups.append(
                    [{"kind": "answer", "answer": _answer_alternatives(raw)}]
                )
            elif img_d is not None:
                # diagram + explanation: keep the diagram in the cell, and queue the
                # explanation as a full-width row directly below this one (250).
                row_groups.append(
                    [
                        {
                            "kind": "image",
                            "media_src": img_d.get("src", ""),
                            "alt": img_d.get("alt", ""),
                        }
                    ]
                )
                explanations.setdefault(ri, []).extend(
                    _explanation_html(d) for d in det
                )
            elif not c.get_text(strip=True) and len(c.find_all("img")) == 1:
                # a pure image cell (only an <img>, maybe a stray <br>): keep the
                # image as an image cell; the loader resolves media_src -> MediaAsset.
                img = c.find("img")
                row_groups.append(
                    [
                        {
                            "kind": "image",
                            "media_src": img.get("src", ""),
                            "alt": img.get("alt", ""),
                        }
                    ]
                )
            else:
                row_groups.append(
                    [{"kind": "static", "html": c.decode_contents().strip()}]
                )
        grid_groups.append(row_groups)

    ncols = len(grid[0])  # original column count (grid is rectangular, checked above)
    col_width = [max(len(gr[j]) for gr in grid_groups) for j in range(ncols)]
    out_width = sum(col_width)
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

    def _empty():
        return {"kind": "static", "html": ""}

    # For a header row, anchor each label over the FIRST answer cell of its column's
    # data group (so "współrzędne" sits above the first input, not the leading "["),
    # which also stops the label from widening the bracket column.
    data_groups = grid_groups[1:] if header_row else grid_groups

    def _anchor(j):
        for gr in data_groups:
            for k, cell in enumerate(gr[j]):
                if cell.get("kind") == "answer":
                    return k
        return 0

    anchor = [_anchor(j) for j in range(ncols)]
    cells = []
    for ri, row_groups in enumerate(grid_groups):
        is_header = header_row and ri == 0
        row = []
        for j, group in enumerate(row_groups):
            w = col_width[j]
            if len(group) == w:
                row.extend(group)
            elif is_header and len(group) == 1:
                padded = [_empty() for _ in range(w)]
                padded[min(anchor[j], w - 1)] = group[0]
                row.extend(padded)
            else:  # non-uniform data group (rare): right-pad
                row.extend(group)
                row.extend(_empty() for _ in range(w - len(group)))
        cells.append(row)
        # A diagram cell's explanation follows as its own full-width row. The
        # colspan makes normalize_data treat the grid as spanning, which keeps
        # these ragged 1-cell rows verbatim instead of padding them out.
        for html in explanations.get(ri, []):
            cells.append([{"kind": "static", "html": html, "colspan": out_width}])
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


def _span_cell(c):
    """A cell dict preserving the source's <th>-ness and any colspan/rowspan > 1
    (TableElement.normalize_data keeps a spanning table's rows ragged verbatim)."""
    cell = {
        "html": c.decode_contents().strip(),  # already escaped
        "halign": "left",
        "valign": "top",
    }
    if c.name == "th":
        cell["header"] = True
    for key in ("colspan", "rowspan"):
        v = str(c.get(key) or "").strip()
        if v.isdigit() and int(v) > 1:
            cell[key] = int(v)
    return cell


def table_element(table):
    rows = _rows(table)
    if not rows:
        return _flag_html(table, "table_empty", "table has no rows")

    grid = [_cells(tr) for tr in rows]

    # A nested table can't be flattened to a cell grid -> stays HtmlElement.
    if any(c.find("table") for tr in rows for c in tr.find_all(["td", "th"])):
        return _flag_html(table, "table_nested", "table nests another table")

    def _has_real_span(c):
        return any(
            str(c.get(k) or "").strip().isdigit() and int(c.get(k)) > 1
            for k in ("colspan", "rowspan")
        )

    spanning = any(_has_real_span(c) for tr in rows for c in tr.find_all(["td", "th"]))
    if spanning:
        # A colspan/rowspan table keeps RAGGED rows: each row's actual cells with
        # their span + <th>-ness preserved (the browser lays it out from the spans).
        # The header_row/header_col toggles are off; th cells carry `header` instead.
        cells = [[_span_cell(c) for c in r] for r in grid]
        data = {
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": cells,
        }
        return {"type": "table", "data": data}, []

    # A non-spanning ragged table is genuinely malformed -> HtmlElement.
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
