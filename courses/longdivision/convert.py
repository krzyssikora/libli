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

# A cell that is exactly one inline math run, e.g. `\(7\)`. NON-GREEDY, but the
# `$` anchor is what actually decides the match, so greed alone was never the
# defence: on `\(a\) + \(b\)` either form unwraps to `a\) + \(b`, splicing two
# runs into one and swallowing the ` + ` between them.
# `math_reflow.js:709-710` names this exact shape as the one that must be
# refused, so `_MATH_OPEN` refuses it -- see `is_single_run`.
_MATH_RUN = re.compile(r"^\\\((.*?)\\\)$", re.S)
_MATH_OPEN = re.compile(r"\\\(")

# Applied to a cell the legacy markup marked `red_on_yellow`. Rendered by
# `.el--math .mk-amber` in courses.css; KaTeX only emits the class because
# math.js trusts `\htmlClass`.
MARK_CLASS = "mk mk-amber"
MARK_TOKEN = "\\htmlClass"  # noqa: S105 - a LaTeX command name, not a credential


def _is_ruled(tr):
    return "border-bottom" in (tr.get("style") or "")


def is_single_run(raw):
    """False for cell text holding more than one `\\(...\\)` run.

    Such a cell has no correct array slot. Unwrapping it splices the runs
    together and eats the text between them; `\\text{}` renders the delimiters
    literally. There is no third rendering to fall back on, so the DECISION is
    to convert neither the cell nor its table -- see `is_long_division`. A table
    left unconverted keeps its stored TableElement and is counted by the command
    as "not a long division", which is visible; a mis-emitted cell would not be.

    MEASURED: zero such cells in the Wielomiany corpus, so this selects exactly
    the same 73 tables. It is here because the module outlives the corpus.
    """
    return len(_MATH_OPEN.findall(raw)) <= 1


def is_long_division(table):
    """True for the borderless ruled grids that are worked long division.

    Four conditions, all required. The third excludes the four `wzór | nazwa`
    formula reference tables, which share the class and the header rule but are
    ordinary two-column data tables. The fourth excludes tables the converter
    cannot express (see `is_single_run`).
    """
    if "my_table_noborder" not in (table.get("class") or []):
        return False
    rows = table.find_all("tr")
    if not rows or not any(_is_ruled(tr) for tr in rows):
        return False
    head = " ".join(c.get_text(" ", strip=True) for c in rows[0].find_all(["td", "th"]))
    if "nazwa" in head:
        return False
    return all(
        is_single_run(td.get_text(" ", strip=True))
        for tr in rows
        for td in tr.find_all(["td", "th"])
    )


def cell_latex(td):
    """One `<td>` as an array slot.

    Raises ValueError on a multi-run cell rather than emitting something wrong.
    `is_long_division` already excludes any table holding one, so reaching this
    means a caller bypassed the selection rule.
    """
    raw = td.get_text(" ", strip=True)
    if not raw:
        return ""
    if not is_single_run(raw):
        raise ValueError(f"cell holds more than one math run: {raw!r}")
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
