# Wielomiany long-division arrays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 71 long-division `TableElement`s across 10 Wielomiany units with `MathElement`s holding a KaTeX `array`, restoring the row rules and cell highlights the LAL import dropped.

**Architecture:** A pure converter turns a legacy `<table>` into a `\begin{array}{r...}` string. A scanner selects the qualifying tables from the legacy HTML directory. A matcher pairs each database table with its source by cell-text grid, resolving the six ambiguous ones. A dry-run-by-default management command repoints each existing `Element` join at a new `MathElement`, leaving the old `TableElement` row orphaned so the change is reversible. A scoped KaTeX `trust` predicate plus two CSS rules make the highlight theme-aware.

**Tech Stack:** Python 3.13, Django 5.2, BeautifulSoup 4, pytest + pytest-django, vanilla JS, KaTeX 0.16.11 (vendored).

**Spec:** `docs/superpowers/specs/2026-08-26-wielomiany-long-division-arrays-design.md`

## Global Constraints

- Course slug is `mat-pp`; the Wielomiany part is **ContentNode pk 408**.
- Legacy source directory: `C:\Users\krzys\Documents\teaching\LAL\html\045_wielomiany`. It lives **outside the repo**, so any test that reads it must `skipif` when absent.
- Selection rule: `my_table_noborder` **and** ≥1 `<tr>` with `border-bottom` in its inline style **and** first row is not the `wzór | nazwa` header pair. Selects exactly **73**.
- Expected outcome: **71 conversions**, **6** resolved by the ambiguity rules, **2** (`450#2`, `450#5`) reported absent.
- Column spec is `r` repeated to the widest row. No `\[...\]` wrapper.
- Highlight markup is exactly `\htmlClass{mk mk-amber}{...}`.
- Trust predicate is an **equality** check on `\htmlClass`, never a prefix.
- `scripts/lal_import/tables.py` must **not** be modified.
- Run tests with `uv run python -m pytest`; `uv` is not on PATH as a bare command.
- Never delete a `TableElement` row.

---

### Task 1: Theme-aware highlight rendering

Do this first: the converter emits `\htmlClass`, which KaTeX silently drops unless trust is enabled. Without this task the converted content renders unhighlighted.

**Files:**
- Modify: `courses/static/courses/js/math.js:6`
- Modify: `courses/static/courses/css/courses.css` (after line 1342, the `.tc-*` block)
- Test: `tests/test_long_division_render_static.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: the CSS classes `mk` and `mk-amber`, used by `MARK_CLASS` in Task 2.

- [ ] **Step 1: Write the failing tests**

```python
"""Source-level guards for the long-division highlight.

These assert on file CONTENT rather than behaviour because the units under
test are a KaTeX render option and two CSS rules -- neither is reachable from
Python, and both are silently droppable (KaTeX discards an untrusted command
without error; a missing CSS rule just renders unstyled).
"""

from pathlib import Path

from django.conf import settings

MATH_JS = Path(settings.BASE_DIR) / "courses/static/courses/js/math.js"
COURSES_CSS = Path(settings.BASE_DIR) / "courses/static/courses/css/courses.css"
TOKENS_CSS = Path(settings.BASE_DIR) / "core/static/core/css/tokens.css"


def _lum(hexstr):
    h = hexstr.lstrip("#")
    ch = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_math_js_trusts_htmlclass_by_equality():
    src = MATH_JS.read_text(encoding="utf-8")
    assert 'c.command === "\\\\htmlClass"' in src


def test_math_js_trust_is_not_a_prefix_match():
    # A prefix/startsWith test would also admit \htmlStyle and \htmlData, which
    # let authored LaTeX inject arbitrary CSS and data attributes.
    src = MATH_JS.read_text(encoding="utf-8")
    assert "startsWith" not in src
    assert "indexOf" not in src.split("trust")[-1][:200]


def test_inline_prose_path_does_not_get_trust():
    # renderInlineText covers .el--text and friends. Trust there would extend
    # \htmlClass to author prose in every element type.
    src = MATH_JS.read_text(encoding="utf-8")
    inline = src.split("function renderInlineText")[1]
    assert "trust" not in inline


def test_math_element_scrolls_instead_of_overflowing():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert ".el--math { overflow-x: auto; }" in css


def test_mark_classes_defined():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert ".el--math .mk-amber" in css
    assert "var(--warning-subtle)" in css.split(".el--math .mk-amber")[1][:120]
    assert "var(--tc-orange)" in css.split(".el--math .mk-amber")[1][:120]


def test_highlight_clears_aa_in_both_themes():
    # The pair was chosen on this number: --warning on --warning-subtle looks
    # fine but measures 2.79:1 in light.
    pairs = {"light": ("#8A5514", "#F4E8CD"), "dark": ("#E8B761", "#3A2F18")}
    for theme, (fg, bg) in pairs.items():
        assert _ratio(fg, bg) >= 4.5, f"{theme} highlight below AA"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_long_division_render_static.py -v`
Expected: FAIL — `test_math_js_trusts_htmlclass_by_equality`, `test_math_element_scrolls_instead_of_overflowing` and `test_mark_classes_defined` all assert on text that does not exist yet. The two contrast/prefix tests should already PASS (they encode facts about tokens.css and the current absence of `startsWith`).

- [ ] **Step 3: Add the trust predicate**

In `courses/static/courses/js/math.js`, replace line 6:

```js
      katex.render(el.textContent, el, { displayMode: true, throwOnError: false });
```

with:

```js
      katex.render(el.textContent, el, {
        displayMode: true,
        throwOnError: false,
        // \htmlClass is the ONLY trusted command, matched by EQUALITY. It adds a
        // class attribute and nothing else. \htmlStyle and \htmlData would let
        // authored LaTeX inject arbitrary CSS and data attributes; \href and \url
        // arbitrary URLs. A prefix test would admit all of them.
        // Deliberately NOT added to renderInlineText below: that path covers
        // author prose in .el--text and every other element, and does not need it.
        trust: function (c) { return c.command === "\\htmlClass"; },
      });
```

- [ ] **Step 4: Add the CSS**

In `courses/static/courses/css/courses.css`, after the `.tc-orange` rule (line 1342), add:

```css
/* --- Long-division arrays (MathElement). `.el--math` had no rules at all; an
   array is intrinsically sized, so on a narrow viewport every one of them
   exceeds the content column. MEASURED against the 648px column: 72 of the 73
   converted arrays fit, the widest (160#34) overflows by 5px. --- */
.el--math { overflow-x: auto; }

/* The step highlight, carried by \htmlClass{mk mk-amber} inside the array.
   NOT \colorbox: that compiles to an inline background-color, so it can never
   follow the theme, and it inflates the marked row -- MEASURED at 6px taller
   overall with one \hline gap pushed to 50px against 46/47px elsewhere.
   Ink is --tc-orange, not --warning: --warning on --warning-subtle measures
   2.79:1 in light. This pair is 5.09:1 light / 7.11:1 dark. */
.el--math .mk { border-radius: 3px; padding: .02em .2em; margin: 0 -.05em; }
.el--math .mk-amber { background: var(--warning-subtle); color: var(--tc-orange); }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_long_division_render_static.py -v`
Expected: 6 passed.

- [ ] **Step 6: Falsify each new test**

For each of the three tests that were red in Step 2, break the thing it guards and confirm it goes red again — a test that cannot fail is not evidence.

1. Change `c.command === "\\htmlClass"` to `c.command.startsWith("\\html")`. Expect `test_math_js_trust_is_not_a_prefix_match` to FAIL. Revert **by hand** (never `git checkout`).
2. Delete the `.el--math { overflow-x: auto; }` line. Expect `test_math_element_scrolls_instead_of_overflowing` to FAIL. Restore by hand.
3. Change `var(--tc-orange)` to `var(--warning)`. Expect `test_mark_classes_defined` to FAIL. Restore by hand.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/math.js courses/static/courses/css/courses.css tests/test_long_division_render_static.py
git commit -m "feat(math): theme-aware highlight and scroll containment for math elements"
```

---

### Task 2: The pure converter

**Files:**
- Create: `courses/longdivision/__init__.py`
- Create: `courses/longdivision/convert.py`
- Test: `tests/test_long_division_convert.py`

Package placement mirrors `courses/recolour/`, the existing home for LAL content-repair helpers.

**Interfaces:**
- Consumes: the CSS classes from Task 1.
- Produces:
  - `MARK_CLASS: str` — `"mk mk-amber"`
  - `MARK_TOKEN: str` — `"\\htmlClass"`, used by Task 4 to detect the plain variant
  - `is_long_division(table: Tag) -> bool`
  - `cell_latex(td: Tag) -> str`
  - `table_to_array(table: Tag) -> str`
  - `text_key(table: Tag) -> str`
  - `db_text_key(cells: list[list[dict]]) -> str`

- [ ] **Step 1: Write the failing tests**

```python
"""The converter's contract. Pure functions over BeautifulSoup nodes: no
database, no filesystem, no fixture directory."""

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


# --- cells ----------------------------------------------------------------

def test_math_run_is_unwrapped():
    assert cell_latex(_td(r"<td>\(7\)</td>")) == "7"


def test_empty_math_run_is_an_empty_slot():
    assert cell_latex(_td(r"<td>\(\)</td>")) == ""


def test_empty_cell_is_an_empty_slot():
    assert cell_latex(_td("<td></td>")) == ""


def test_prose_cell_is_wrapped_in_text():
    assert cell_latex(_td("<td>nazwa</td>")) == r"\text{nazwa}"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_long_division_convert.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'courses.longdivision'`.

- [ ] **Step 3: Create the package**

```bash
mkdir courses/longdivision
```

Create `courses/longdivision/__init__.py` as an empty file.

- [ ] **Step 4: Write the converter**

Create `courses/longdivision/convert.py`:

```python
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
MARK_TOKEN = "\\htmlClass"


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
    body = m.group(1).strip() if m else "\\text{%s}" % raw
    if not body:
        return ""  # `\(\)` is a spacer cell, not a mark target
    if "red_on_yellow" in (td.get("class") or []):
        body = "\\htmlClass{%s}{%s}" % (MARK_CLASS, body)
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
    return "\\begin{array}{%s}\n%s\n\\end{array}" % ("r" * width, "\n".join(lines))


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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_long_division_convert.py -v`
Expected: 16 passed.

- [ ] **Step 6: Falsify the two load-bearing tests**

1. In `table_to_array`, change `if i < len(grid) - 1 or ruled[i]:` to `if i < len(grid) - 1:`. Expect `test_rule_on_the_final_row_still_gets_its_terminator` to FAIL. Revert by hand.
2. In `is_long_division`, delete the final `return "nazwa" not in head` and return `True`. Expect `test_wzor_nazwa_header_is_rejected` to FAIL. Revert by hand.

- [ ] **Step 7: Commit**

```bash
git add courses/longdivision/__init__.py courses/longdivision/convert.py tests/test_long_division_convert.py
git commit -m "feat(longdivision): convert a legacy long-division table to a KaTeX array"
```

---

### Task 3: Scan the legacy source directory

**Files:**
- Create: `courses/longdivision/source.py`
- Test: `tests/test_long_division_source.py`

**Interfaces:**
- Consumes: `is_long_division`, `table_to_array`, `text_key` from Task 2.
- Produces:
  - `SourceTable` — frozen dataclass with `file: str`, `index: int`, `key: str`, `latex: str`, and a read-only `ident` property returning `f"{file}#{index}"` (Task 5 reports on `src.ident`)
  - `scan(source_dir: str | Path) -> list[SourceTable]`

- [ ] **Step 1: Write the failing tests**

```python
"""Scanning a directory of legacy lesson HTML for convertible tables."""

import os
from pathlib import Path

import pytest

from courses.longdivision.source import scan

RULED = ' style="border-bottom: 1px solid black;"'

REAL_SOURCE = Path(r"C:\Users\krzys\Documents\teaching\LAL\html\045_wielomiany")


def _write(tmp_path, name, body):
    (tmp_path / name).write_text(body, encoding="utf-8")


def test_scan_selects_only_qualifying_tables(tmp_path):
    _write(
        tmp_path,
        "010_lesson.html",
        f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>'
        '<table class="my_table_border"><tr><td>x</td></tr></table>'
        '<table class="my_table_noborder"><tr><td>y</td></tr></table>',
    )
    found = scan(tmp_path)
    assert len(found) == 1
    assert found[0].file == "010_lesson"


def test_index_is_the_position_among_all_tables(tmp_path):
    # The index must count EVERY <table>, not just selected ones, so an id like
    # "130_wielomiany_dzielenie#9" refers to the same table a human counting
    # tables in the file would land on.
    _write(
        tmp_path,
        "020_lesson.html",
        '<table class="my_table_border"><tr><td>x</td></tr></table>'
        f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>',
    )
    assert scan(tmp_path)[0].index == 1


def test_files_are_scanned_in_sorted_order(tmp_path):
    for name in ("030_b.html", "010_a.html"):
        _write(
            tmp_path,
            name,
            f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>',
        )
    assert [s.file for s in scan(tmp_path)] == ["010_a", "030_b"]


@pytest.mark.skipif(not REAL_SOURCE.is_dir(), reason="legacy LAL source not present")
def test_real_directory_selects_exactly_73():
    found = scan(REAL_SOURCE)
    assert len(found) == 73
    excluded = {"330_wielomiany_wzory", "340_wielomiany_wzory",
                "350_wielomiany_wzory", "480_wielomiany_podsumowanie"}
    per_file = {}
    for s in found:
        per_file[s.file] = per_file.get(s.file, 0) + 1
    assert per_file["130_wielomiany_dzielenie"] == 10
    assert per_file["160_wielomiany_dzielenie"] == 40
    # The four wzór|nazwa tables are the ONLY table in their file that would
    # otherwise qualify, so those files must contribute nothing.
    for name in excluded:
        assert name not in per_file
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_long_division_source.py -v`
Expected: collection error — `No module named 'courses.longdivision.source'`.

- [ ] **Step 3: Write the scanner**

Create `courses/longdivision/source.py`:

```python
"""Selecting convertible tables out of the legacy LAL lesson HTML."""

from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from courses.longdivision.convert import is_long_division
from courses.longdivision.convert import table_to_array
from courses.longdivision.convert import text_key


@dataclass(frozen=True)
class SourceTable:
    """One convertible table in the legacy course.

    `index` counts EVERY <table> in the file, not just the selected ones, so
    `f"{file}#{index}"` names the same table a human counting tables in that
    file would land on.
    """

    file: str
    index: int
    key: str
    latex: str

    @property
    def ident(self):
        return "%s#%d" % (self.file, self.index)


def scan(source_dir):
    """Every convertible table under `source_dir`, in file then document order."""
    out = []
    for path in sorted(Path(source_dir).glob("*.html")):
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for index, table in enumerate(soup.find_all("table")):
            if not is_long_division(table):
                continue
            out.append(
                SourceTable(path.stem, index, text_key(table), table_to_array(table))
            )
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_long_division_source.py -v`
Expected: 4 passed (or 3 passed + 1 skipped if the legacy directory is absent).

If `test_real_directory_selects_exactly_73` runs and reports any number other than 73, **stop and report** — the selection rule has drifted from the spec's measured baseline.

- [ ] **Step 5: Falsify the index test**

Change `for index, table in enumerate(soup.find_all("table")):` to enumerate only the selected tables (move the `is_long_division` check into the loop header via a comprehension). Expect `test_index_is_the_position_among_all_tables` to FAIL. Revert by hand.

- [ ] **Step 6: Commit**

```bash
git add courses/longdivision/source.py tests/test_long_division_source.py
git commit -m "feat(longdivision): scan legacy lesson HTML for convertible tables"
```

---

### Task 4: Match database tables to source, resolving ambiguity

**Files:**
- Create: `courses/longdivision/match.py`
- Test: `tests/test_long_division_match.py`

**Interfaces:**
- Consumes: `SourceTable` from Task 3; `MARK_TOKEN` from Task 2.
- Produces:
  - `index_by_key(sources: list[SourceTable]) -> dict[str, list[SourceTable]]`
  - `resolve(candidates: list[SourceTable], sibling_files: Counter) -> SourceTable | None`
  - `plan_unit(db_rows: list[tuple[int, str]], index: dict) -> tuple[list, list, list]` returning `(matched, ambiguous, unmatched)` where `matched` is `[(db_id, SourceTable)]` and the other two are lists of `db_id`. `db_rows` is `[(db_id, text_key)]`.

- [ ] **Step 1: Write the failing tests**

```python
"""Pairing a unit's stored tables with their legacy source, including the six
tables that cell text alone cannot tell apart."""

from collections import Counter

from courses.longdivision.match import index_by_key
from courses.longdivision.match import plan_unit
from courses.longdivision.match import resolve
from courses.longdivision.source import SourceTable

PLAIN = "\\begin{array}{r}\n1\n\\end{array}"
MARKED = "\\begin{array}{r}\n\\htmlClass{mk mk-amber}{1}\n\\end{array}"


def _s(file, index, key, latex):
    return SourceTable(file, index, key, latex)


def test_single_candidate_resolves_to_itself():
    c = [_s("130_x", 0, "K", PLAIN)]
    assert resolve(c, Counter()) is c[0]


def test_identical_latex_from_several_files_is_not_ambiguous():
    # 150#0 and 155#0 are byte-identical; either is a correct answer.
    c = [_s("150_x", 0, "K", PLAIN), _s("155_x", 0, "K", PLAIN)]
    assert resolve(c, Counter()).latex == PLAIN


def test_sibling_majority_picks_the_marked_variant():
    # Unit 423: nine unambiguous siblings all came from 130, so its ambiguous
    # table is 130#9 -- the HIGHLIGHTED one.
    c = [_s("130_x", 9, "K", MARKED), _s("150_x", 0, "K", PLAIN)]
    got = resolve(c, Counter({"130_x": 9}))
    assert got.file == "130_x"
    assert got.latex == MARKED


def test_sibling_majority_is_ignored_when_it_has_no_candidate():
    c = [_s("150_x", 0, "K", PLAIN), _s("155_x", 0, "K", PLAIN)]
    got = resolve(c, Counter({"999_other": 4}))
    assert got.latex == PLAIN


def test_no_unambiguous_sibling_falls_back_to_the_plain_variant():
    # Units 425/426: both their tables are ambiguous, so there is no sibling to
    # vote. The conservative answer is the variant with no highlight markup --
    # never invent emphasis.
    c = [_s("130_x", 9, "K", MARKED), _s("150_x", 0, "K", PLAIN)]
    got = resolve(c, Counter())
    assert got.latex == PLAIN


def test_refuses_when_the_plain_variant_is_not_unique():
    c = [
        _s("a", 0, "K", "\\begin{array}{r}\n1\n\\end{array}"),
        _s("b", 0, "K", "\\begin{array}{r}\n2\n\\end{array}"),
    ]
    assert resolve(c, Counter()) is None


def test_plan_unit_splits_matched_ambiguous_and_unmatched():
    index = index_by_key([
        _s("130_x", 0, "K1", PLAIN),
        _s("130_x", 9, "K2", MARKED),
        _s("150_x", 0, "K2", PLAIN),
    ])
    matched, ambiguous, unmatched = plan_unit(
        [(1, "K1"), (2, "K2"), (3, "K_absent")], index
    )
    assert [d for d, _ in matched] == [1, 2]
    assert ambiguous == []
    assert unmatched == [3]
    # db 2 was ambiguous but resolved via db 1's file
    assert dict(matched)[2].file == "130_x"


def test_plan_unit_reports_a_table_it_cannot_resolve():
    index = index_by_key([
        _s("a", 0, "K", "\\begin{array}{r}\n1\n\\end{array}"),
        _s("b", 0, "K", "\\begin{array}{r}\n2\n\\end{array}"),
    ])
    matched, ambiguous, unmatched = plan_unit([(1, "K")], index)
    assert matched == []
    assert ambiguous == [1]
    assert unmatched == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_long_division_match.py -v`
Expected: collection error — `No module named 'courses.longdivision.match'`.

- [ ] **Step 3: Write the matcher**

Create `courses/longdivision/match.py`:

```python
"""Pairing stored tables with their legacy source.

Matching is on cell TEXT, because that is the only signal the two sides still
share -- and it is content-based rather than driven by the import manifest on
purpose: units 425 and 426 are a hand split of one imported unit and share a
title, and unit 1144 postdates the import entirely. A file->unit map misses
both.

Two text keys in the real data each name three source tables whose LaTeX
differs, and in both groups the difference is ONLY the highlighting (the row
rules are identical and the two unhighlighted members are byte-identical). So
the choice is binary, and `resolve` settles it without ever inventing emphasis.
"""

from collections import Counter
from collections import defaultdict

from courses.longdivision.convert import MARK_TOKEN


def index_by_key(sources):
    """text key -> the source tables carrying it."""
    idx = defaultdict(list)
    for s in sources:
        idx[s.key].append(s)
    return dict(idx)


def resolve(candidates, sibling_files):
    """One source table for a stored table, or None if it cannot be settled.

    `sibling_files` counts the source files that the SAME unit's unambiguous
    matches came from.
    """
    if len({c.latex for c in candidates}) == 1:
        return candidates[0]
    if sibling_files:
        modal = sibling_files.most_common(1)[0][0]
        hit = [c for c in candidates if c.file == modal]
        if hit:
            return hit[0]
    plain = [c for c in candidates if MARK_TOKEN not in c.latex]
    if len({c.latex for c in plain}) == 1:
        return plain[0]
    return None


def plan_unit(db_rows, index):
    """Split one unit's stored tables into (matched, ambiguous, unmatched).

    Two passes: the first settles every table with exactly one possible LaTeX
    and builds the file vote, the second uses that vote on the rest. Done in one
    pass the outcome would depend on row order.
    """
    known = [(db_id, index[key]) for db_id, key in db_rows if key in index]
    unmatched = [db_id for db_id, key in db_rows if key not in index]

    sibling_files = Counter(
        cands[0].file for _, cands in known if len({c.latex for c in cands}) == 1
    )

    matched, ambiguous = [], []
    for db_id, cands in known:
        picked = resolve(cands, sibling_files)
        if picked is None:
            ambiguous.append(db_id)
        else:
            matched.append((db_id, picked))
    return matched, ambiguous, unmatched
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_long_division_match.py -v`
Expected: 8 passed.

- [ ] **Step 5: Falsify the fallback**

In `resolve`, change the fallback to `return candidates[0]` instead of preferring the plain variant. Expect `test_no_unambiguous_sibling_falls_back_to_the_plain_variant` and `test_refuses_when_the_plain_variant_is_not_unique` to FAIL. Revert by hand.

- [ ] **Step 6: Commit**

```bash
git add courses/longdivision/match.py tests/test_long_division_match.py
git commit -m "feat(longdivision): match stored tables to source and resolve the highlight variant"
```

---

### Task 5: The management command

**Files:**
- Create: `courses/management/commands/convert_long_division.py`
- Test: `tests/test_long_division_command.py`

**Interfaces:**
- Consumes: `scan` (Task 3), `index_by_key` / `plan_unit` (Task 4), `db_text_key` (Task 2).
- Produces: the command `convert_long_division`.

- [ ] **Step 1: Write the failing tests**

```python
"""The command's contract: dry-run, repointing, idempotency, reporting."""

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from courses.models import ContentNode
from courses.models import Element
from courses.models import MathElement
from courses.models import TableElement
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db

RULED = ' style="border-bottom: 1px solid black;"'


def _source(tmp_path, name="130_x.html", body=None):
    body = body or (
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(7\)</td><td>\(4\)</td></tr>"
        r"<tr><td>\(6\)</td><td>\(\)</td></tr></table>"
    )
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def _course_with_table(cells, slug="mat-pp"):
    course = CourseFactory(slug=slug)
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title="Wielomiany"
    )
    unit = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="unit", title="U", unit_type="lesson"
    )
    table = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": cells})
    )
    join = Element.objects.create(unit=unit, content_object=table, order=3, title="T")
    return course, part, unit, table, join


def _cells():
    return [
        [{"html": r"\(7\)"}, {"html": r"\(4\)"}],
        [{"html": r"\(6\)"}, {"html": r"\(\)"}],
    ]


def _run(part, src, **kw):
    call_command(
        "convert_long_division",
        course="mat-pp",
        part_id=part.pk,
        source_dir=str(src),
        **kw,
    )


def test_dry_run_changes_nothing(tmp_path):
    _, part, _, table, join = _course_with_table(_cells())
    _run(part, _source(tmp_path))
    join.refresh_from_db()
    assert join.content_type == ContentType.objects.get_for_model(TableElement)
    assert join.object_id == table.pk
    assert MathElement.objects.count() == 0


def test_apply_repoints_the_join_and_keeps_the_table_row(tmp_path):
    _, part, _, table, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    assert join.content_type == ContentType.objects.get_for_model(MathElement)
    assert join.content_object.latex.startswith("\\begin{array}{rr}")
    # NEVER deleted: the orphan row is the revert path.
    assert TableElement.objects.filter(pk=table.pk).exists()


def test_apply_preserves_position_and_title(tmp_path):
    _, part, unit, _, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    assert join.unit_id == unit.pk
    assert join.order == 3
    assert join.title == "T"
    assert join.parent_id is None


def test_second_run_converts_nothing(tmp_path):
    _, part, _, _, _ = _course_with_table(_cells())
    src = _source(tmp_path)
    _run(part, src, apply=True)
    assert MathElement.objects.count() == 1
    _run(part, src, apply=True)
    assert MathElement.objects.count() == 1


def test_a_table_outside_the_part_is_untouched(tmp_path):
    course, part, _, _, _ = _course_with_table(_cells())
    other = ContentNode.objects.create(
        course=course, parent=None, order=1, kind="part", title="Other"
    )
    other_unit = ContentNode.objects.create(
        course=course, parent=other, order=0, kind="unit", title="O", unit_type="lesson"
    )
    t2 = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": _cells()})
    )
    j2 = Element.objects.create(unit=other_unit, content_object=t2)
    _run(part, _source(tmp_path), apply=True)
    j2.refresh_from_db()
    assert j2.content_type == ContentType.objects.get_for_model(TableElement)


def test_a_source_table_with_no_stored_counterpart_is_reported(tmp_path, capsys):
    # The real run hits this twice: 450#2 and 450#5, whose lesson was rewritten
    # by hand. It must be reported, never invented.
    _course_with_table(_cells())
    part = ContentNode.objects.get(title="Wielomiany")
    src = _source(tmp_path)
    (src / "450_x.html").write_text(
        f'<table class="my_table_noborder"><tr{RULED}>'
        r"<td>\(x^2\)</td></tr><tr><td>\(y\)</td></tr></table>",
        encoding="utf-8",
    )
    _run(part, src)
    out = capsys.readouterr().out
    assert "450_x#0" in out
    assert "no stored counterpart" in out


def test_a_byte_identical_twin_is_not_reported_absent(tmp_path, capsys):
    # `resolve` returns the FIRST of several byte-identical plain candidates, so
    # the twins stay unclaimed by ident while their content is fully converted.
    # Keying absence on ident would report them as lost content. MEASURED on the
    # real corpus: 150#0 and 155#0 are the same 204 characters, 150#1 and 155#1
    # the same 307 -- ident-keyed reports 4 absent, latex-keyed reports the 2 that
    # genuinely have none.
    _course_with_table(_cells())
    part = ContentNode.objects.get(title="Wielomiany")
    src = _source(tmp_path)
    twin = (src / "130_x.html").read_text(encoding="utf-8")
    (src / "155_x.html").write_text(twin, encoding="utf-8")  # same table, other file
    _run(part, src)
    out = capsys.readouterr().out
    assert "155_x#0" not in out
    assert "no stored counterpart" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_long_division_command.py -v`
Expected: FAIL — `Unknown command: 'convert_long_division'`.

- [ ] **Step 3: Write the command**

Create `courses/management/commands/convert_long_division.py`:

```python
"""Convert legacy long-division tables to KaTeX math elements.

Dry-run by default. Run this LOCALLY against the mat-pp database; there is no
prod-side counterpart.

The stored TableElement rows are NEVER deleted -- the Element join is repointed
and the old row is left orphaned, which is the whole revert path (repoint back).
Element deletion in libli is a hard delete with no backups.
"""

from collections import Counter

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from courses.longdivision.convert import db_text_key
from courses.longdivision.match import index_by_key
from courses.longdivision.match import plan_unit
from courses.longdivision.source import scan
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import MathElement
from courses.models import TableElement


def _subtree_ids(root):
    ids, frontier = {root.pk}, [root.pk]
    while frontier:
        kids = [
            pk
            for pk in ContentNode.objects.filter(parent_id__in=frontier).values_list(
                "pk", flat=True
            )
            if pk not in ids
        ]
        ids.update(kids)
        frontier = kids
    return ids


class Command(BaseCommand):
    help = "Convert long-division tables to math elements (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--course", required=True)
        parser.add_argument("--part-id", type=int, required=True)
        parser.add_argument("--source-dir", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--list-matches", action="store_true")

    def handle(self, *args, **opts):
        try:
            course = Course.objects.get(slug=opts["course"])
        except Course.DoesNotExist as exc:
            raise CommandError("no course with slug %r" % opts["course"]) from exc
        try:
            part = ContentNode.objects.get(pk=opts["part_id"], course=course)
        except ContentNode.DoesNotExist as exc:
            raise CommandError(
                "node %s is not in course %s" % (opts["part_id"], opts["course"])
            ) from exc

        sources = scan(opts["source_dir"])
        if not sources:
            raise CommandError("no convertible tables under %s" % opts["source_dir"])
        index = index_by_key(sources)
        self.stdout.write("source tables selected: %d" % len(sources))

        table_ct = ContentType.objects.get_for_model(TableElement)
        joins = list(
            Element.objects.filter(
                unit_id__in=_subtree_ids(part), content_type=table_ct
            ).select_related("unit")
        )

        by_unit = {}
        for join in joins:
            by_unit.setdefault(join.unit_id, []).append(join)

        matched, ambiguous, unmatched = [], [], []
        for unit_id, unit_joins in sorted(by_unit.items()):
            rows = [
                (j.pk, db_text_key(j.content_object.data.get("cells") or []))
                for j in unit_joins
            ]
            m, a, u = plan_unit(rows, index)
            by_pk = {j.pk: j for j in unit_joins}
            matched.extend((by_pk[pk], src) for pk, src in m)
            ambiguous.extend(by_pk[pk] for pk in a)
            unmatched.extend(by_pk[pk] for pk in u)

        self.stdout.write(
            "stored tables in the subtree: %d  (convertible %d, unresolved %d, "
            "not a long division %d)"
            % (len(joins), len(matched), len(ambiguous), len(unmatched))
        )

        if opts["list_matches"]:
            for join, src in matched:
                self.stdout.write(
                    "  el=%-6s unit=%-6s <- %s" % (join.pk, join.unit_id, src.ident)
                )

        for join in ambiguous:
            self.stderr.write(
                "UNRESOLVED el=%s unit=%s: several source tables, none preferred"
                % (join.pk, join.unit_id)
            )

        # Absence is judged on LATEX, not on ident. `resolve` legitimately returns
        # the first of several byte-identical plain candidates, so the others stay
        # unclaimed by ident while their content is fully converted -- 150#0 and
        # 155#0 are the same 204 characters, and 150#1/155#1 the same 307. Keying
        # this on ident would report two tables as lost content that are not lost
        # at all. MEASURED against the real corpus: ident-keyed reports 4 absent,
        # latex-keyed reports the 2 that genuinely have no stored counterpart.
        converted = {src.latex for _, src in matched}
        for src in sources:
            if src.latex not in converted:
                self.stdout.write(
                    "  %s: no stored counterpart (skipped)" % src.ident
                )

        if ambiguous:
            raise CommandError(
                "%d table(s) could not be resolved; nothing written" % len(ambiguous)
            )
        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("dry run -- pass --apply to write"))
            return

        math_ct = ContentType.objects.get_for_model(MathElement)
        with transaction.atomic():
            for join, src in matched:
                math = MathElement.objects.create(latex=src.latex)
                join.content_type = math_ct
                join.object_id = math.pk
                join.save(update_fields=["content_type", "object_id"])
        self.stdout.write(self.style.SUCCESS("converted %d" % len(matched)))
```

- [ ] **Step 4: Add the render test**

Append to `tests/test_long_division_command.py`:

```python
def test_converted_element_renders_as_a_katex_math_block(tmp_path):
    # The join is repointed, so the element template that runs for it changes
    # from tableelement.html to mathelement.html. Without this, a repoint that
    # produced an unrenderable element would still pass every test above.
    from django.template.loader import render_to_string

    _, part, _, _, join = _course_with_table(_cells())
    _run(part, _source(tmp_path), apply=True)
    join.refresh_from_db()
    html = render_to_string(
        "courses/elements/mathelement.html", {"el": join.content_object}
    )
    assert 'class="el el--math"' in html
    assert "data-katex" in html
    assert "\\begin{array}{rr}" in html
    assert "el--table" not in html
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_long_division_command.py -v`
Expected: 8 passed.

- [ ] **Step 6: Falsify the two safety tests**

1. In the `--apply` block, add `join.content_object.delete()` before the repoint. Expect `test_apply_repoints_the_join_and_keeps_the_table_row` to FAIL. Remove by hand.
2. Change `join.save(update_fields=["content_type", "object_id"])` to also reset `order` (`join.order = 0`). Expect `test_apply_preserves_position_and_title` to FAIL. Revert by hand.

- [ ] **Step 7: Run the whole new suite and lint**

```bash
uv run python -m pytest tests/test_long_division_convert.py tests/test_long_division_source.py tests/test_long_division_match.py tests/test_long_division_command.py tests/test_long_division_render_static.py -v
uv run ruff check --no-cache courses/longdivision courses/management/commands/convert_long_division.py tests/test_long_division_*.py
uv run ruff format --check courses/longdivision courses/management/commands/convert_long_division.py tests/test_long_division_*.py
```

Expected: all pass. Grep the pytest summary line for `failed` — the exit code alone is not reliable in this repo.

- [ ] **Step 8: Commit**

```bash
git add courses/management/commands/convert_long_division.py tests/test_long_division_command.py
git commit -m "feat(longdivision): add the convert_long_division management command"
```

---

### Task 6: Run the conversion against the real database

This task writes to the user's local `mat-pp` database. It is the deliverable; do not skip the dry run.

**Files:**
- Modify: none (data only)

**Interfaces:**
- Consumes: everything above.
- Produces: 71 converted elements.

- [ ] **Step 1: Dry run**

```bash
uv run python manage.py convert_long_division \
  --course mat-pp --part-id 408 \
  --source-dir "C:/Users/krzys/Documents/teaching/LAL/html/045_wielomiany" \
  --list-matches
```

Expected, and **stop and report if any line differs**:
- `source tables selected: 73`
- `stored tables in the subtree: 98  (convertible 71, unresolved 0, not a long division 27)`
- exactly two `no stored counterpart` lines: `450_wielomiany_rownania#2` and `450_wielomiany_rownania#5`
- the per-unit spread in `--list-matches`: 423→10, 424→10, 425→2, 426→2, 427→40, 436→1, 438→1, 441→1, 442→3, 1144→1

- [ ] **Step 2: Check the six ambiguous resolutions in the listing**

In the `--list-matches` output confirm:
- the unit-423 table resolves to `130_wielomiany_dzielenie#9` (**highlighted** — 9 of its
  10 matched tables carry the mark)
- the unit-424 table resolves to `140_wielomiany_dzielenie#9` (**highlighted**, likewise 9
  of 10)
- units 425 and 426 each resolve both of their tables to the **plain** variant, with zero
  highlighted

**On attribution for 425/426.** The user confirmed 425 came from `150_wielomiany_dzielenie`
and 426 from `155`. The listing will attribute **both** to `150`, and that is expected, not
a fault: `150#0` and `155#0` are byte-identical (204 chars), as are `150#1` and `155#1`
(307 chars), so `resolve` returns whichever it sees first and the stored latex is the same
either way. Unit 426 receives exactly the correct array. Do NOT add a global 1:1 assignment
to correct a log line that has no effect on content.

What WOULD be a fault, and must stop the run: either unit showing a highlighted variant, or
the highlighted/plain split for 423/424 coming out other than 9 of 10.

- [ ] **Step 3: Apply**

```bash
uv run python manage.py convert_long_division \
  --course mat-pp --part-id 408 \
  --source-dir "C:/Users/krzys/Documents/teaching/LAL/html/045_wielomiany" \
  --apply
```

Expected: `converted 71`.

- [ ] **Step 4: Verify idempotency**

Re-run Step 3 verbatim. Expected: `converted 0` and no new `MathElement` rows.

- [ ] **Step 5: Verify in the browser**

Start the dev server and open `http://127.0.0.1:8000/courses/mat-pp/u/423/`. Screenshot in **both** light and dark, judging dark on its own terms rather than as a tinted copy of light. Confirm:
- the arrays are shrink-to-fit and centred, not full-width tables
- a horizontal rule sits under each step, and none is missing at the bottom of a table
- the highlighted digits in `423` show the amber treatment, legible in both themes
- unit `427` (40 arrays) renders with no leftover `.el--table`

- [ ] **Step 6: Commit**

No code changes; record the run.

```bash
git commit --allow-empty -m "chore(content): convert 71 Wielomiany long-division tables to KaTeX arrays"
```

---

## Rollback

The `TableElement` rows are intact and unreferenced. To revert one element, repoint its
`Element` join back:

```python
from django.contrib.contenttypes.models import ContentType
from courses.models import Element, TableElement
join = Element.objects.get(pk=<id>)
join.content_type = ContentType.objects.get_for_model(TableElement)
join.object_id = <original table pk>
join.save(update_fields=["content_type", "object_id"])
```

`--list-matches` does NOT carry the original pk — it prints the join pk, the unit pk and
the source ident, and the apply loop used to overwrite `object_id` without reading it.
The applying run now prints the mapping itself, one `REVERT el=… unit=… table=<old> ->
math=<new>` line per converted element; capture that output.

The mat-pp run predates that line, so its mapping was reconstructed afterwards from the
orphaned rows and is committed as
[`…-revert-map.md`](2026-08-26-wielomiany-long-division-arrays-revert-map.md). Take
`<original table pk>` from that file's `orphan_table_pk` column.
