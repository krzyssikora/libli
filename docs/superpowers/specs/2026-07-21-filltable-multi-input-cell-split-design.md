# FillTable multi-input cell split

## Purpose

The LAL importer maps a `<table>` with `<input class="table_input">` cells to a
`FillTableElement` (ungraded self-check grid). A common LAL shape packs **several
inputs into one `<td>`**, interleaved with static math — e.g. a vector answer cell:

```html
<td> \([\) <input class="table_input"> \(,\) <input class="table_input"> \(]\) </td>
```

i.e. `[ ⟨x⟩ , ⟨y⟩ ]` — the brackets/comma are static math, and there are **two**
inputs (the vector's components). Intervals `( ⟨a⟩ , ⟨b⟩ )` / `[ ⟨a⟩ ; ⟨b⟩ ]` and
coordinate pairs have the same shape.

The parser (`scripts/lal_import/tables.py:fill_table_element`) builds one cell per
`<td>` and detects an answer cell with `c.find(class_="table_input")` — which
returns only the **first** input. So a `[4,2]` cell collapses to a single answer
cell holding `4`, **silently dropping the second input, its answer, and the
`[ , ]` notation**. Measured on `110.../wykresy_20`: the source grid has **10
inputs / 10 answers** (`[4,2] [0,3] [-3,0] [2,-3] [-4,-1]`) but the import keeps
**5** (the x-components `4,0,-3,2,-4`); half the answers and all the bracket
notation are lost. This is a pre-existing fidelity bug (since Group B #4), not
related to the image-cell feature; it became visible once fill-table image cells
made these exercises worth rendering.

This spec makes the parser **split a multi-input `<td>` into a run of columns**,
preserving the interleaved static math and emitting one answer cell per input.
User-approved design (the "faithful split"): `image | [ | ⟨x⟩ | , | ⟨y⟩ | ]`.

## Scope

- **In scope**: a `<td>` in a `table_input` table that contains **≥2**
  `table_input` inputs → split into an ordered run of cells (static runs +
  one answer cell per input). Rows are padded so the grid stays rectangular.
- **Out of scope (unchanged)**: a `<td>` with exactly **one** input stays a
  single answer cell (today's behaviour — even if it has a surrounding label; a
  broader "preserve label around a lone input" change is deliberately deferred to
  limit blast radius across the ~114 existing `table_input` files). Image cells
  (the pure-`<img>` branch) and plain static cells are unchanged. Span/nested/
  ragged tables still fall back to a flagged HtmlElement.

## Background: the pieces this touches

- **`scripts/lal_import/tables.py:fill_table_element(table, answer_by_input)`** —
  builds `data["cells"]` row-major. Current cell loop: input cell →
  `{kind:"answer", answer: _answer_alternatives(answer_by_input[id(inp)])}`;
  a pure-`<img>` cell (Task 4 of the image feature) → `{kind:"image", …}`; else →
  `{kind:"static", html: c.decode_contents().strip()}`. `answer_by_input` maps
  `id(input_node) -> raw accepted-answer string`, positional over ALL question
  inputs — it already keys per input, so multiple answer cells from one `<td>`
  each resolve their own answer with no key change.
- **`_answer_alternatives(raw)`** — turns a raw answer into the pipe-delimited
  accepted-answer string (decimals accept dot+Polish-comma). Reused per input.
- **The math-escape invariant** (see [[bs4-navigablestring-decodes-tag-reescapes]]):
  the parser runs on an `escape_math_delimited`-escaped soup; a static cell body
  built from a node uses `decode_contents()` (re-escapes to `&lt;`). Static cells
  are sanitised (`sanitize_cell`) at load and rendered `|safe` with client-side
  KaTeX, so a static math segment like `\([\)` must reach the cell as the same
  form the existing static-cell path produces.
- **`FillTableElement`** (`courses/models.py`) — a cell is exactly one of
  static / answer / image. It has NO colspan/rowspan; the grid must be
  rectangular (`normalize_data` pads ragged rows with empty static cells, but the
  parser should emit a clean rectangle, not rely on that).
- **`header_row`/`header_col`** — `fill_table_element` sets `header_row = all(cell
  is <th>)` for row 0, `header_col = all(row[0] is <th>)`. After splitting, row 0
  (often a plain header like `wektor | współrzędne`, no inputs) is shorter than a
  split data row; padding must not break these predicates.

## Design

### Splitting one `<td>` into a run of sub-cells

Add a helper that, given a `<td>` with ≥2 inputs, walks its **direct rendered
content in document order** and produces a list of cell dicts:

- Accumulate consecutive non-input content (NavigableStrings + non-input child
  tags, e.g. the `\([\)`, `\(,\)`, `\(]\)` math spans) into a **static run**.
  When an input is reached, first flush any pending non-empty static run as a
  `{kind:"static", html: <decoded, escaped, stripped>}` cell (empty/whitespace-
  only runs are dropped — no empty static columns between adjacent inputs unless
  there is real content), then emit `{kind:"answer", answer:
  _answer_alternatives(answer_by_input.get(id(inp), ""))}` for the input.
- After the last input, flush the trailing static run (the closing `]`).
- Static html is produced the SAME way as the existing static branch — from the
  node stream via the cell's `decode_contents()`-style serialisation so math `<`
  stays `&lt;` (do NOT `str(NavigableString)` a decoded run and lose the escape;
  build the run's html by joining the ESCAPED serialisation of each member, i.e.
  the same output `decode_contents()` gives for those children). The result for
  the vector cell is: `static "\([\)"`, `answer(x)`, `static "\(,\)"`,
  `answer(y)`, `static "\(]\)"` — 5 sub-cells.

A `<td>` with exactly one input is NOT sent to the splitter (keeps today's single
answer cell); a `<td>` with zero inputs is a normal static/image/th cell.

### Reshaping the grid (padding)

Because splitting makes some rows wider, after building all rows as
lists-of-cells, compute `width = max(len(row) for row in rows)` and **right-pad**
every shorter row with empty static cells `{kind:"static", html:""}` to `width`.
This keeps the grid rectangular without colspan. (Right-pad, not centre/align:
the corpus multi-input tables are uniform — every data row splits identically —
so the image/label column stays col 0 and the split answer group occupies the
same columns across data rows; the shorter **header** row pads on the right, so
`wektor | współrzędne` becomes `wektor | współrzędne | "" | "" | "" | ""`, with
`współrzędne` sitting above the opening `[`. Acceptable and faithful enough.)

### Header detection after padding

Compute `header_row`/`header_col` on the ORIGINAL `<tr>`/`<td>` node types BEFORE
padding (as today: row 0 all-`<th>`; col 0 all-`<th>`), so appended empty static
pad cells (which are neither) don't flip the predicate. The pad cells are plain
`<td>`-equivalent statics regardless.

### Span/nested/ragged fallback

Unchanged and evaluated BEFORE splitting: a table with rowspan/colspan, a nested
`<table>`, or (source-)ragged rows still returns the flagged HtmlElement. Splitting
operates only on an otherwise-regular grid; the split itself never produces a
ragged grid (it pads).

## Answer mapping & downstream

- `answer_by_input` already maps each input node to its answer, so each emitted
  answer cell resolves its own component — the x/y answers land in their own
  cells. No change to the answer-key extraction (`table_answers` positional over
  question inputs) or the loader.
- The loader `fill_table` builder, `normalize_data`, `_cell`, render template,
  `answer_cells`/checking, transfer, and editor are all **unchanged** — they
  already handle an arbitrary rectangular grid of static/answer/image cells. The
  split only changes how many/which cells the parser emits.
- A split cell's answer cells participate in the normal per-cell server check
  (each is checked independently). The student now fills two boxes per vector,
  matching the original.

## Testing

Follow TDD; every test falsifiable (RED before GREEN).

- **Split, happy path** (`tests/lal_import/test_tables.py`): a `table_input`
  table with a vector cell `\([\) <in> \(,\) <in> \(]\)` (+ answers via
  `answer_by_input`) produces a row `[…, static "\([\)", answer(x), static
  "\(,\)", answer(y), static "\(]\)"]`; both answers present and correct; the
  `[`, `,`, `]` are static cells with the escaped math.
- **Two inputs, no surrounding brackets**: `<in><in>` (adjacent) → two answer
  cells, no empty static between them.
- **Single input unchanged**: a lone `<input>` cell (with or without a label)
  still yields exactly one answer cell (documents the deliberate out-of-scope
  boundary; guards against over-splitting).
- **Rectangular padding**: a table whose header row is shorter than the split
  data rows yields a rectangular grid (all rows equal width); header row padded
  with empty statics; `header_row` still correct.
- **Image row + split answer** (the real `wykresy_20` shape): `[img] | [ x , y ]`
  → row `[image, static "[", answer, static ",", answer, static "]"]`; 6 columns;
  the image cell (Task 4) intact.
- **Regression**: an existing single-input-per-cell fill-table file parses
  byte-identically (no reshape).
- **End-to-end count** (integration, not unit): re-parsing `wykresy_20` yields
  **10** answer cells (was 5), matching the 10 source answers.

## Verification

- Reseed `110_przeksztalcanie_wykresow_funkcji` (`parser --force`), reload into
  `libli_mat`. Re-render `u/286`: each vector row shows `[img] [ [x] , [y] ]`
  with two input boxes and the bracket notation; server check accepts the
  component answers.
- Confirm the image-loss measure is unchanged (this is answer-cell fidelity, not
  image recovery — image count per file is unaffected).
- Hand the user `/courses/matematyka/u/286/` (DEBUG server) to confirm the vector
  answer format now matches the original.

## Out of scope

- Preserving a label around a **single** input (deferred; limits blast radius).
- Any colspan/alignment beyond right-pad (FillTable has no colspan).
- Non-`table_input` widgets; span/nested/ragged tables (unchanged fallback).
