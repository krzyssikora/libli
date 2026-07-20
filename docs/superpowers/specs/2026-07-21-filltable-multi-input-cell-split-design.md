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

### Cell-kind cascade (explicit ordering)

Restructure the per-`<td>` decision to count inputs first (recursively —
`inputs = c.find_all(class_="table_input")`, matching today's recursive
`c.find(...)` detection so wrapped inputs are seen):

1. `len(inputs) >= 2` → **split** into a run of sub-cells (below).
2. `len(inputs) == 1` → a single `{kind:"answer", answer:
   _answer_alternatives(answer_by_input.get(id(inputs[0]), ""))}` cell — TODAY's
   behaviour, unchanged (a surrounding label is still dropped; out of scope).
3. `len(inputs) == 0` → the existing pure-`<img>` image branch (Task 4) else
   static branch, unchanged.

### Splitting one `<td>` into a run of sub-cells (placeholder-token technique)

Do **not** walk children and re-serialise a node list — there is no bs4 API that
serialises a sibling *list* with correct re-escaping, and `str(NavigableString)`
would DECODE math `&lt;` and reintroduce the corruption in
[[bs4-navigablestring-decodes-tag-reescapes]]. Instead, serialise the whole cell
**once** so escaping is byte-identical to the existing static path:

1. For each input in `c.find_all(class_="table_input")` (document order), record its
   answer `_answer_alternatives(answer_by_input.get(id(inp), ""))`, then
   `inp.replace_with(<unique sentinel token>)` — a token that cannot occur in the
   content and survives serialisation unchanged (e.g. the fillblank `SENTINEL`
   =U+FFFF wrapping an index, as `switch`/`fillblank` already use;
   `￿{i}￿`). Mutating the tree here is safe — this `<td>` is being
   consumed into the grid and not walked again.
2. `html = c.decode_contents()` — ONE call on the Tag → the same re-escaped output
   (math `<` → `&lt;`) the existing static branch produces.
3. Split `html` on the sentinel tokens in order. This yields alternating
   **static segments** and **input positions**: `seg0, in0, seg1, in1, …, segN`.
   Emit, in order: for each static segment, a `{kind:"static", html: seg.strip()}`
   cell **iff the segment is non-empty content** (see the emptiness rule below,
   dropped otherwise so adjacent inputs get no spurious empty column); for each
   input position, its recorded `{kind:"answer", answer}` cell. For the vector
   cell this yields `static "\([\)"`, `answer(x)`, `static "\(,\)"`, `answer(y)`,
   `static "\(]\)"` — 5 sub-cells.

**Per-segment classification (explicit precedence, mirroring the Task 4 cascade).**
Parse each static segment once (`seg_soup = BeautifulSoup(seg, "html.parser")`) and
classify in THIS order — image is checked BEFORE the emptiness drop, because a
lone `<img>` has empty `get_text` and would otherwise be dropped:

1. **Image** — `seg_soup.get_text(strip=True) == ""` AND exactly one `<img>`
   (`len(seg_soup.find_all("img")) == 1`) → emit `{kind:"image", media_src, alt}`
   (same test as the Task 4 pure-image branch; preserves an image between inputs
   that `sanitize_cell` would otherwise strip, CELL_TAGS has no `img`).
2. **Static** — else `seg_soup.get_text(strip=True) != ""` (real text/math, e.g.
   `\([\)`) → emit `{kind:"static", html: seg.strip()}`.
3. **Drop** — else (whitespace-only, treating `&nbsp;`/lone `<br>` as empty, with
   no single `<img>`) → emit nothing, so `&nbsp;`/`<br>`-only gaps between adjacent
   inputs create no spurious column.

(A segment mixing an image with other tags falls to case 2 = static, dropping the
image as elsewhere — no such shape is expected in the corpus.)

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

**MAX_COLS guard:** `FillTableElement.MAX_COLS == 20`; a `normalize_data` grid over
this passes silently but `FillTableElementForm.clean_data` would later reject it.
If the post-split `width > MAX_COLS`, fall back to the flagged HtmlElement path for
that table rather than emitting a grid the editor can't save. **CAUTION — the raw
must be captured BEFORE mutation:** the split calls `inp.replace_with(<sentinel>)`
on the live tree, so by the time width is known `str(table)` would serialise the
U+FFFF tokens (garbage, inputs lost). Capture `raw = str(table)` (or the
`_flag_html(table, …)` result) ONCE at the top of `fill_table_element` before any
`replace_with`, and use that pristine raw for the MAX_COLS fallback. Do NOT
re-serialise the mutated table. **Do NOT "split on a copy of the `<td>`" instead:**
`answer_by_input` is keyed by `id(inp)` of the ORIGINAL input nodes (built once in
`lesson.py:_table_answer_map` over the live tree), so a `copy.copy`'d `<td>` has
new node objects with new `id()` — every `answer_by_input.get(id(inp))` would miss
and every split answer cell would resolve to `""` (silently blank answers, worse
than the original bug). The split must run on the original nodes; capturing `raw`
first is the only correct protection. Unreachable for the current corpus (widest
split = 6-col vector vs MAX_COLS 20), but bounded and non-corrupting.

**Correctness is per-cell, not per-column:** each answer cell is checked
independently against its own stored accepted answer by grid position
(`courses/filltable.py:answer_cells` + the per-cell check), so even a
hypothetical non-uniform split (data rows of differing widths, right-padded) only
affects visual column alignment, never answer correctness. Uniform corpus rows
align exactly.

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
- **Wrapped inputs** (C1 guard): a multi-input cell whose inputs are inside a
  `<span>`/`<div>` (e.g. `<td><span>\([\) <in> \(,\) <in> \(]\)</span></td>`)
  still splits into two answer cells — proving the recursive `find_all` +
  whole-`<td>` `decode_contents()` path descends, not a direct-children walk that
  would emit one static run and lose both inputs. **Known limitation (documented,
  not fixed):** the recursive-descent guarantee is for the ANSWER cells; splitting
  the decoded html on tokens cuts through the wrapper, so the static segments are
  fragments like `<span>\([\)` … `\(]\)</span>`. This is fine for wrappers NOT in
  `sanitize_cell`'s CELL_TAGS (`span`/`div` are stripped at load → clean `\([\)`),
  but an allowed inline wrapper (`<b>…</b>`) straddling both statics would style
  only the opening fragment. Acceptable — no such shape in the corpus; the answer
  cells (the correctness-bearing part) are always correct.
- **Escape invariant** (I1 guard): a split static segment whose math contains a
  comparison, e.g. `<in> \(a<b\) <in>`, reaches the middle static cell as the
  re-escaped `\(a&lt;b\)` (NOT a decoded `\(a<b\)`), matching the existing
  static-cell path. This test must FAIL under a naive `str(node)`-join
  implementation.
- **`&nbsp;`/`<br>` gaps** (I2 guard): `<in>&nbsp;<in>` and `<in><br><in>` each
  yield exactly two adjacent answer cells with NO empty static column between
  them; a real-content gap `<in> \(,\) <in>` yields the middle static cell.
- **Interleaved image** (I3 guard): a segment that is a lone `<img>` between
  inputs emits an `image` sub-cell (media_src preserved), not an empty static.
- **Rectangular padding**: a table whose header row is shorter than the split
  data rows yields a rectangular grid (all rows equal width); header row padded
  with empty statics; `header_row` still correct.
- **Image row + split answer** (the real `wykresy_20` shape): `[img] | [ x , y ]`
  → row `[image, static "[", answer, static ",", answer, static "]"]`; 6 columns;
  the image cell (Task 4) intact.
- **Regression**: an existing single-input-per-cell fill-table file parses to the
  identical `data` structure (same cells grid) — "byte-identical" here means the
  emitted parse is unchanged when no cell has ≥2 inputs (the split path never runs).
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
