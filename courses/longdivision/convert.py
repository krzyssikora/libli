"""A legacy LAL long-division table -> a KaTeX `array`.

Pure functions over BeautifulSoup nodes: no database, no filesystem. The
selection rule and the LaTeX it emits are the whole contract, so both are
testable without either.

The DB copy of these tables has neither the per-row rules nor the cell
highlights (the LAL import dropped both), which is why the legacy HTML is the
source of truth and why `text_key` / `db_text_key` key on cell TEXT alone.
"""

import json
import re

# A cell that is exactly one inline math run, e.g. `\(7\)`.
_MATH_RUN = re.compile(r"^\\\((.*)\\\)$", re.S)

# Applied to a cell the legacy markup marked `red_on_yellow`. Rendered by
# `.el--math .mk-amber` in courses.css; KaTeX only emits the class because
# math.js trusts `\htmlClass`.
MARK_CLASS = "mk mk-amber"
MARK_TOKEN = "\\htmlClass"  # noqa: S105 - a LaTeX command name, not a credential


def _is_ruled(tr):
    return "border-bottom" in (tr.get("style") or "")


def is_long_division(table):
    """True for the borderless ruled grids that are worked long division.

    Three conditions, all required. The third excludes the four `wzór | nazwa`
    formula reference tables, which share the class and the header rule but are
    ordinary two-column data tables.
    """
    if "my_table_noborder" not in (table.get("class") or []):
        return False
    rows = table.find_all("tr")
    if not rows or not any(_is_ruled(tr) for tr in rows):
        return False
    head = " ".join(c.get_text(" ", strip=True) for c in rows[0].find_all(["td", "th"]))
    return "nazwa" not in head


def cell_latex(td):
    """One `<td>` as an array slot."""
    raw = td.get_text(" ", strip=True)
    if not raw:
        return ""
    m = _MATH_RUN.match(raw)
    body = m.group(1).strip() if m else "\\text{%s}" % raw  # noqa: UP031 - clearer than nested braces here
    if not body:
        return ""  # `\(\)` is a spacer cell, not a mark target
    if "red_on_yellow" in (td.get("class") or []):
        body = "\\htmlClass{%s}{%s}" % (MARK_CLASS, body)  # noqa: UP031 - clearer than nested braces here
    return body


def table_to_array(table):
    """The whole table as `\\begin{array}{r...} ... \\end{array}`.

    No `\\[...\\]` wrapper: MathElement renders in displayMode already.
    """
    rows = table.find_all("tr")
    grid = [[cell_latex(td) for td in tr.find_all(["td", "th"])] for tr in rows]
    ruled = [_is_ruled(tr) for tr in rows]
    width = max(len(r) for r in grid)
    lines = []
    for i, row in enumerate(grid):
        line = " & ".join(row + [""] * (width - len(row)))
        # A trailing \hline STILL needs its row terminator. `... \hline` after
        # the final row raises "\hline valid only within array environment".
        if i < len(grid) - 1 or ruled[i]:
            line += " \\\\"
        if ruled[i]:
            line += " \\hline"
        lines.append(line)
    return "\\begin{array}{%s}\n%s\n\\end{array}" % (  # noqa: UP031 - clearer than nested braces here
        "r" * width,
        "\n".join(lines),
    )


def text_key(table):
    """A source table's grid of plain cell text."""
    return json.dumps(
        [
            [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            for tr in table.find_all("tr")
        ],
        ensure_ascii=False,
    )


def db_text_key(cells):
    """The same key computed from a stored `TableElement.data["cells"]`."""
    return json.dumps(
        [[(c.get("html") or "").strip() for c in row] for row in cells],
        ensure_ascii=False,
    )
