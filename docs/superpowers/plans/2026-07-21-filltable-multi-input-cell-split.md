# FillTable multi-input cell split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split a fill-table `<td>` that holds ≥2 `table_input` inputs (vectors `[x,y]`, intervals) into a run of columns — static math cells around one answer cell per input — instead of collapsing to a single answer that drops the extra inputs and the `[ , ]` notation.

**Architecture:** Parser-only change to `scripts/lal_import/tables.py:fill_table_element`. A new `_split_multi_input_cell` helper uses the placeholder-token technique (replace each input with a U+FFFF sentinel, `decode_contents()` the whole `<td>` once so escaping is byte-identical, split on the tokens), classifying each static segment (image / static / drop). Rows are right-padded to a rectangle; an over-wide split falls back to a flagged HtmlElement. Loader/model/render/check/transfer/editor are unchanged — they already handle an arbitrary rectangular grid.

**Tech Stack:** Python, BeautifulSoup4, pytest. Run tooling with `uv run` (bash `pytest`/`python` NOT on PATH). Test DB not needed for these parser unit tests, but the harness sets `DJANGO_SETTINGS_MODULE`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-21-filltable-multi-input-cell-split-design.md` (4 spec-review rounds, clean). Read it first.
- **Scope:** ONLY `scripts/lal_import/tables.py` + `tests/lal_import/test_tables.py`. Do NOT touch the loader, model, render, transfer, or editor — they handle any rectangular static/answer/image grid unchanged.
- **Split trigger:** a `<td>` with `len(c.find_all(class_="table_input")) >= 2` (recursive, matching today's recursive `c.find(...)` detection). Exactly 1 input → single answer cell (today's behaviour, unchanged, even with a surrounding label — out of scope). 0 inputs → existing image/static branches, unchanged.
- **Escape invariant** (see the bs4 gotcha memory): build static html by splitting the output of ONE `c.decode_contents()` call — never `str(NavigableString)` a node (that DECODES math `<` and corrupts it). The tokens are inserted via `inp.replace_with(<sentinel>)`, which mutates the live tree.
- **`answer_by_input` is `id(inp)`-keyed** over the ORIGINAL nodes — record each input's answer from the original node; NEVER split on a `copy.copy`'d `<td>` (new node identities → every lookup misses → blank answers).
- **MAX_COLS raw-before-mutation:** capture `str(table)` BEFORE any `replace_with`; the MAX_COLS fallback must use that pristine raw (a post-mutation `str(table)` serialises U+FFFF garbage).
- **Falsify every test** — confirm RED for the right reason before implementing. Some guard tests (escape, wrapped, nbsp/br, image) MUST fail under a naive implementation.
- `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/lal_import/test_tables.py -v`. **Run `uv run ruff check`/`ruff format` on both touched files before committing** (CI gates on ruff; scope reformat to your changes).

## File map

- `scripts/lal_import/tables.py` — add `import re` + `_TOKEN_RE`; add `_segment_cell(seg)` and `_split_multi_input_cell(c, answer_by_input)` helpers; restructure the cell loop in `fill_table_element`; add post-split rectangular padding + MAX_COLS guard.
- `tests/lal_import/test_tables.py` — the guard test suite.

---

### Task 1: Split multi-input fill-table cells into columns

**Files:**
- Modify: `scripts/lal_import/tables.py` (`fill_table_element` ~34-84; new helpers + `import re`)
- Test: `tests/lal_import/test_tables.py`

**Interfaces:**
- Consumes: `fill_table_element(table, answer_by_input)` (existing); `_answer_alternatives` (existing).
- Produces: for a `<td>` with ≥2 inputs, a run of cells `[static?, answer, static?, answer, …]`; grid right-padded rectangular; over-`MAX_COLS` split → flagged HtmlElement with pristine raw.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lal_import/test_tables.py`. Uses the existing `_t` / `_fill_table` soup helper (single-`<table>`); build `answer_by_input` from the input nodes.

```python
from scripts.lal_import.tables import fill_table_element


def _ft(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").find("table")


def _answers(table, values):
    # map each table_input node (document order) to a raw answer
    inps = table.find_all(class_="table_input")
    return {id(i): v for i, v in zip(inps, values)}


def test_vector_cell_splits_into_bracket_answer_comma_answer_bracket():
    t = _ft(
        '<table><tr>'
        '<td>\\([\\) <input class="table_input"> \\(,\\) <input class="table_input"> \\(]\\)</td>'
        '</tr></table>'
    )
    result, _flags = fill_table_element(t, _answers(t, ["4", "2"]))
    row = result["data"]["cells"][0]
    kinds = [c["kind"] for c in row]
    assert kinds == ["static", "answer", "static", "answer", "static"]
    assert row[1]["answer"] == "4" and row[3]["answer"] == "2"
    assert "[" in row[0]["html"] and "," in row[2]["html"] and "]" in row[4]["html"]


def test_wrapped_inputs_still_split_two_answers():
    # inputs inside a <span> — recursive find_all + whole-td decode_contents must descend
    t = _ft(
        '<table><tr><td><span>\\([\\) <input class="table_input"> \\(,\\) '
        '<input class="table_input"> \\(]\\)</span></td></tr></table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["1", "2"]))
    row = result["data"]["cells"][0]
    answers = [c for c in row if c["kind"] == "answer"]
    assert len(answers) == 2 and answers[0]["answer"] == "1" and answers[1]["answer"] == "2"


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
    assert [c["kind"] for c in result["data"]["cells"][0]] == ["answer", "static", "answer"]


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
        '<table>'
        '<tr><th>wektor</th><th>wsp</th></tr>'
        '<tr><td>\\([\\) <input class="table_input"> \\(,\\) '
        '<input class="table_input"> \\(]\\)</td><td>x</td></tr>'
        '</table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["4", "2"]))
    cells = result["data"]["cells"]
    w = len(cells[0])
    assert all(len(r) == w for r in cells)  # rectangular
    assert result["data"]["header_row"] is True  # header still detected


def test_single_input_table_regression_unchanged():
    # a table with only single-input cells parses to the same shape as before
    t = _ft(
        '<table><tr><td>a</td><td><input class="table_input"></td></tr></table>'
    )
    result, _ = fill_table_element(t, _answers(t, ["9"]))
    assert result["data"]["cells"][0] == [
        {"kind": "static", "html": "a"},
        {"kind": "answer", "answer": "9"},
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/lal_import/test_tables.py -v -k "vector or wrapped or reescaped or adjacent or interleaved or padded"`
Expected: FAIL — today a ≥2-input `<td>` collapses to ONE answer cell (first input only), so the split/kinds assertions fail.

- [ ] **Step 3: Add the helpers**

At the top of `scripts/lal_import/tables.py`, add `import re` and after `_answer_alternatives`:

```python
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
        return {"kind": "image", "media_src": img.get("src", ""), "alt": img.get("alt", "")}
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
```

- [ ] **Step 4: Restructure the cell loop + add padding + MAX_COLS guard**

In `fill_table_element`, capture the pristine raw before the loop mutates, restructure the per-cell cascade to count inputs first, then pad. Replace the block from `header_row = ...` through `return {"type": "fill_table", ...}` with:

```python
    header_row = all(c.name == "th" for c in grid[0])
    header_col = all(r[0].name == "th" for r in grid)
    pristine_raw = str(table)  # BEFORE any replace_with (MAX_COLS fallback uses this)
    cells = []
    for r in grid:
        row = []
        for c in r:
            inputs = c.find_all(class_="table_input")
            if len(inputs) >= 2:
                row.extend(_split_multi_input_cell(c, answer_by_input))
            elif len(inputs) == 1:
                raw = answer_by_input.get(id(inputs[0]), "")
                row.append({"kind": "answer", "answer": _answer_alternatives(raw)})
            elif not c.get_text(strip=True) and len(c.find_all("img")) == 1:
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
            {"type": "html", "flagged": True, "raw": pristine_raw, "reason": "table_too_wide"},
            [{"kind": "table_too_wide", "reason": "split exceeds MAX_COLS",
              "raw_excerpt": pristine_raw[:300]}],
        )
    for r in cells:
        while len(r) < out_width:
            r.append({"kind": "static", "html": ""})
    data = {
        "header_row": header_row,
        "header_col": header_col,
        "border": "grid",
        "cells": cells,
    }
    return {"type": "fill_table", "data": data}, []
```

Note: `c.decode_contents()` for a single-input cell's static neighbours is NOT re-run — a lone input still becomes one answer cell; only ≥2-input cells are split. The image/static branches for 0-input cells are byte-identical to before (regression test guards this).

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/lal_import/test_tables.py -v`
Expected: PASS — all new guard tests + the existing table/fill-table/image-cell tests (no regression).

- [ ] **Step 6: Ruff-clean + commit**

```bash
uv run ruff check scripts/lal_import/tables.py tests/lal_import/test_tables.py
uv run ruff format scripts/lal_import/tables.py tests/lal_import/test_tables.py
git add scripts/lal_import/tables.py tests/lal_import/test_tables.py
git commit -m "feat(lal-parser): split multi-input fill-table cells into columns"
```

---

## End-to-end verification (after Task 1)

Not a task — the SDD driver runs this and reports to the user.

1. Reseed: `uv run python -m scripts.lal_import.parser 110_przeksztalcanie_wykresow_funkcji --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --force`.
2. Assert the count recovered: re-parsing `wykresy_20` now yields **10** answer cells (was 5) — one per source input — and the `[ , ]` brackets are static cells. (A quick shell/`parse_lesson` check, or add an integration test.)
3. Reload part 110 into `libli_mat` (`import_lal_content … --allow-html`).
4. Server-side render `u/286`: each vector row is `[img] [ [x] , [y] ]` — two input boxes + bracket notation. Hand the user `/courses/matematyka/u/286/` (DEBUG server) to confirm the vector answer format matches the original.
5. Confirm the image-loss measure is unchanged (this is answer fidelity, not image recovery).

## Self-review notes

- **Spec coverage:** cascade ordering (Step 4 counts inputs first) ✓; placeholder-token split + segment classification precedence (`_split_multi_input_cell`/`_segment_cell`) ✓; escape invariant (split of one `decode_contents()`) ✓; emptiness `&nbsp;`/`<br>` drop ✓; interleaved image ✓; single-input unchanged ✓; wrapped inputs ✓; rectangular padding ✓; MAX_COLS raw-before-mutation guard ✓; no-copy (id-keyed answers) ✓.
- **Type consistency:** `answer_by_input` keyed by `id(inp)`; `media_src`/`alt` from `img.get(...)` string reads (safe across the segment re-parse); the sentinel `￿{i}￿` split by `_TOKEN_RE`.
- **Downstream untouched:** loader/model/render/check/transfer/editor unchanged (verified in the spec); the emitted grid is a normal rectangular static/answer/image grid.
