# Spanning-table editor: cell merge / split UI

Date: 2026-07-22
Status: approved (brainstorm)
Scope: `TableElement` (`table_editor.js`) **and** `FillTableElement` (`filltable_editor.js`)

## Problem

Native `colspan`/`rowspan` support for both table elements shipped as **render-only**
(memory: `matematyka-content-import-status`, commits `a326cdc` + `1bbc255`). The model
keeps per-cell `colspan`/`rowspan` (> 1 only) and a per-cell `header` flag,
`normalize_data` detects a spanning grid and preserves its **ragged rows verbatim**
(rectangularising injects phantom cells and breaks the browser's span layout), the
student-facing templates emit the spans, and the LAL parser + loader build and preserve
them. The WYSIWYG editors were never taught any of it.

Two consequences, one of them worse than "unsupported":

1. **No merge/split UI.** A spanning table cannot be restructured by an author.
2. **Silent destruction on save.** `_edit_table.html` / `_edit_filltable.html` do not
   emit `colspan`/`rowspan`/`header` on the editor `<td>`s, and neither `serialize()`
   reads them back. So opening a spanning table shows a *misaligned ragged grid*, and
   saving it — even saving it untouched, since both editors serialize the live DOM —
   **strips every span and every header flag**. The table is not merely un-editable; it
   is destructively editable.

This blocks real content. The 250_pole_trojkata fill-table (unit "Pola trójkątów
podobnych", `/courses/matematyka/u/432/`) gained full-width `colspan` explanation rows
when mixed image+explanation fill cells were recovered (commit `30745b4`); the user
accepted that approach **on condition** this work makes the table editable.

### Corpus reality

24 spanning tables in the imported course (`scripts/lal_import/out/**/*.json`):
16 `table`, 8 `fill_table`. `colspan` appears in 19, `rowspan` in 8. Extremes:
`060_ciagi/060_ciagi` 7x4 with 4 rowspans; `130_kombinatoryka/240_kombinatoryka`
14x26 with 113 colspans. So both span axes are real content, and any design that
handles only full-width row merges is insufficient.

## Goals

- Spans and per-cell header flags survive an editor round-trip, always.
- An author can **merge** a rectangular range of cells and **split** a merged cell, in
  both editors.
- Row/column insert and delete work correctly on a spanning grid.
- A teacher can author a *new* merged table, not only edit an imported one.
- 250_pole's fill-table is editable in the real `libli_mat` course.

## Non-goals

- Unifying `table_editor.js` and `filltable_editor.js`. They are near-twins today;
  merging them is a larger refactor than this work justifies. Only the grid algebra —
  the part that would otherwise be duplicated span-for-span — is extracted.
- Changing `normalize_data`, the parser, or the loader. They already handle spans.
  (The **render** templates do *not* — see "Render templates: the `<th>` gap" below.
  Fixing that is in scope.)
- Re-keying persisted student practice state. `filltable.js` restores by `(r, c)`, so a
  reshape can misalign saved work — exactly as true today for column insert/delete.
  Unchanged, and out of scope.
- Nested tables (table-in-cell). Still `HtmlElement`; none remain in the corpus.

## Hard constraints

- **Non-spanning tables are byte-identical.** A table with no merges must serialize
  exactly as it does today: no `colspan`, no `rowspan`, no `header` keys. Enforced at
  the single place it can be — `serialize()` emits a span key only when > 1 and a
  `header` key only when true.
- **Never rectangularise a spanning grid.** Merge removes absorbed cells from their
  rows; split re-inserts them. The editor DOM *is* the ragged grid and `serialize()`
  walks it verbatim.
- **Fill-table kinds are preserved.** `static | answer | image`. A merge must not lose
  an image cell's `media` pk or an answer cell's accepted answers without the author
  being told.
- **Answer checking stays aligned.** `filltable_check` recomputes `(r, c)` from the
  current `normalize_data(...)["cells"]` and `filltableelement.html` emits matching
  `data-r`/`data-c`, so template iteration and server checking remain consistent by
  construction after any reshape.

## Decisions (agreed with the user)

| # | Question | Decision |
|---|---|---|
| 1 | Capability level | **Full merge/split** with span-aware structural ops — not preserve-only, not full-width-row-only. `rowspan` is real content. |
| 2 | Range selection | **Anchor + Shift+click**, plus `Alt+Shift+Arrow` as the keyboard equivalent. Not drag-to-select (fights `contenteditable`), not step-wise merge-right/merge-down. |
| 3 | Absorbed content | **Keep top-left; discard the rest**, with one `confirm()` when any absorbed cell is non-empty. Split returns **empty static** cells. |
| 4 | Ops that cut a span | **Adjust the span** (Word/Docs behaviour): insert inside a span grows it, delete inside shrinks it, deleting a span's anchor moves the anchor to the next slot it covers, deleting the last slot it covers deletes the cell. |
| 5 | Header cells | Round-trip is mandatory; **also add a per-cell "Header cell" toggle**, so a merged header can be undone to a `<td>`. |
| 6 | Real-data verification | **Read-mostly against `libli_mat`.** Prove u/432 opens and edits correctly, leave its stored data unchanged, do destructive experiments on a throwaway element. No reseed / reload / rebuild. |
| 7 | Visual pass | Run the **frontend-design** skill at the end, over the new toolbar buttons, icons and range highlight. |

## Architecture

### New shared module: `courses/static/courses/js/table_grid.js`

Exposes `window.libliTableGrid`. Pure functions over a DOM `<table>`'s data rows, with
no knowledge of cell kinds, toolbars, serialization or the hidden field. Added as a
third **`defer`** script in `templates/courses/manage/editor/editor.html`, immediately
above `table_editor.js` (both editor scripts are already `defer`, so source order alone
would not guarantee execution order).

**Interface: the caller supplies the cell accessor.** Both editors inject chrome into
the same `<table>` — a trailing `td[data-control]` on every data row, and a whole
`tr[data-control-row]`. A slot map that walked raw children would count the control cell
as a layout slot, making `layoutWidth` off by one and every index-based op wrong. Since
the module is deliberately chrome-agnostic, it cannot know to skip them. Therefore every
entry point takes a `grid` descriptor supplied by the caller:

```
{ rows:  () => [<tr>, ...], // data rows only (control row excluded)
  cells: (tr) => [...],     // the row's data cells only (control cell excluded)
  makeCell: () => <td>,     // the caller's default empty cell factory
  makeRow:  () => <tr> }    // an empty <tr> WITH the caller's row chrome
```

`rows` is a **function**, symmetrical with `cells`, and every op re-reads it after
mutating. This is not cosmetic: `insertRow` adds a `<tr>` and `deleteRow` removes one, so
a materialized array would be stale exactly when it matters — `deleteRow`'s step-4 clamp
must run against the **new** height. And the module cannot recompute the row list itself,
because doing so would mean knowing about `tr[data-control-row]`, which the chrome-
agnostic contract forbids.

`makeRow` exists because today's `buildRow()` creates the `<tr>` *and* appends
`rowCtl(grid)` (the per-row insert/delete handles). Without it `insertRow` would either
emit a bare `<tr>` whose handles are silently missing, or reach into chrome the module is
defined not to know about. `makeRow` returns the `<tr>` with its control cell already
appended; `insertRow` then inserts data cells **before** that control cell.

`rows` and `cells` are exactly the editors' existing `dataRows()` / `dataCells()`
helpers, so there is one definition of "what is a data cell" per editor and the module
inherits it. Structural ops insert relative to the row's data cells and **before** the
trailing control cell; `insertRow` inserts before `tr[data-control-row]` by inserting
relative to a sibling data row, never by appending to the table.

The rowspan-covered rule for `insertColumn` is the mirror of `insertRow`'s, and it is the
one an obvious implementation gets wrong: "insert a cell into every data row" produces a
layout-inconsistent grid on any table with a rowspan — 8 of the 24 corpus tables,
including `060_ciagi` with 4. Named test: insert a column through the covered rows of a
`rowspan=3` cell.

⚠️ **The skip predicate is the strict straddle test, not "occupies the slot"** — the two
diverge at `layoutCol == c` and the difference corrupts the grid. Consider a cell anchored
at `(0, 2)` with `colspan=1, rowspan=3`, and `insertColumn(grid, 2)`. The numeric rule
says the span does not grow and row 0 gets a fresh cell before it. If rows 1–2 were
skipped merely because their slot 2 is *occupied* by that cell, they would gain nothing
while row 0 gained a cell — a layout-inconsistent grid, and precisely the state the
"editor only ever posts a layout-consistent grid" invariant (and the `normalize_data`
branch-flip safety argument resting on it) requires never to occur. When a covering cell
is anchored *at* `layoutCol`, every covered row gets a real new cell like any other.
`insertRow` mirrors this exactly: a cell anchored *at* `layoutRow` must not suppress new
cells in the inserted row. Named test: insert a column at the anchor column of a
`colspan=1 rowspan=3` cell → all three rows gain a cell and the layout stays consistent.

**`width` and `height`, defined for overflowing stored spans.** Slice 1 rebuilds the
column strip from `slotMap().width` and the caps compare against these numbers, so the
definitions are observable before any op runs.

- `width = max over cells of (c + colspan)`, and **`0` when the grid has no cells at all**
  (`max` over an empty sequence is otherwise undefined; unreachable through the UI thanks
  to the delete floor guard, but reachable from hand-edited JSON — and it is what feeds
  `normalize_data`'s width-0 → default-2x2 collapse).
- `height = grid.rows().length`. A rowspan reaching past the last row is clipped for
  mapping purposes, not counted as extra height.

`layout_dims` uses identical definitions.

**Consequence: the bounds invariant is a row-axis assertion.** Because `width` is
*defined* as `max(c + colspan)`, the column half (`c + colspan <= width`) is a tautology —
no grid can violate it, so there is nothing to assert or test there. Only
`r + rowspan <= height` is falsifiable, since `height` is defined independently. This is
the correct reading rather than a defect: an over-reaching colspan genuinely widens the
grid, exactly as a browser lays it out, and the caps then catch that widening as growth.
Degenerate test: a rowspan that reaches past the last row.

**Empty data rows are legal.** Merging a full-width range across two rows leaves the
second row with **no data cells at all** — a `<tr>` holding only its control cell,
serialized as `[]` — and imported content can already contain such rows. Pinned rather
than left undefined: the editor still renders that row's control cell (so it can be
deleted or have rows inserted around it), `slotMap` counts it as a full layout row of
`null` slots, and the relaxed form must **not** treat a zero-length row as malformed on
the *spanning* branch (the `widths == {0}` guard keeps applying on the non-spanning
branch, unchanged). Named test: full-width 2-row merge → save → reopen → the span is
intact and the empty row survives.

**Range normalisation runs to a fixpoint.** Expanding the rectangle to swallow one
clipped merged cell can newly clip a *different* merged cell on another edge, so a
single pass can return an illegal rectangle — and `merge` on an illegal rectangle would
remove cells that still project outside it, corrupting the grid. `rangeCells` therefore
repeats the expansion until a full pass changes nothing; it terminates because the
rectangle only ever grows and is bounded by the grid. Tested with two merged cells
clipped on opposite edges, forcing two expansion rounds.

**Degenerate-input policy.** `normalize_data` permits grids that are not layout-
consistent (two cells claiming one slot; a row that does not reach the layout width).
`slotMap` is **last-writer-wins** on a collision, leaves unreached slots `null`, and
treats `null` as unoccupied. Consequence that must be handled rather than crashed on: the
normalised rectangle's top-left slot can itself be `null`, making `rangeCells`' `anchor`
null and leaving `merge` with no cell to grow — which would either throw or, worse,
remove the absorbed cells with no survivor. **If `anchor` is `null`, `canMerge` is false
and `merge` is a no-op** (the Merge button stays disabled). Covered in the
degenerate-input test set. Structural ops are a no-op on a row that does not reach the
target layout column. All 24 corpus tables were verified layout-consistent at spec time,
so **no repair pass is built** — this policy exists only so a hand-edited JSON or a
future import degrades predictably instead of throwing.

| Function | Contract |
|---|---|
Every function takes the `grid` descriptor above as its first argument.

| Function | Contract |
|---|---|
| `slotMap(grid)` | Standard HTML table cell-mapping: `{ map, width, height }` where `map[r][c]` is the cell occupying that layout slot (or `null`), accounting for colspan and rowspan. The primitive everything else builds on. |
| `layoutWidth(grid)` | Layout column count. Replaces `colCount()`, which reads row 0's **cell** count and is wrong once a span exists. |
| `insertColumn(grid, layoutCol)` | Insert a layout column at `layoutCol`; straddling colspans grow by 1; **a row is skipped only when a cell anchored in an *earlier* row *straddles* the insertion point** (strict `c < layoutCol < c + colspan`), in which case that covering cell's colspan grows exactly once, at its anchor. |
| `deleteColumn(grid, layoutCol)` | Delete a layout column; straddling colspans shrink by 1; an anchor in that column moves right; a cell whose last covered column goes is removed. |
| `insertRow(grid, layoutRow)` | Insert a row **at** `layoutRow` (same *at*-convention as `insertColumn`, deliberately not an "after" index); straddling rowspans grow by 1; only uncovered slots get real new cells (via `grid.makeCell`). |
| `deleteRow(grid, layoutRow)` | Like `deleteColumn`, **plus anchor relocation** — see the rule below; it is not a pure transpose. |
| `rangeCells(grid, a, b)` | The rectangle between two cells, **normalised** to a fixpoint (below). Returns `{ cells, anchor, r0, c0, r1, c1 }`, where `anchor` is the cell occupying `(r0, c0)` **after** normalisation — which fixpoint expansion can make a different cell from the one the author first clicked. `merge` keeps *this* cell's content, not `rangeAnchor`. |
| `canMerge(grid, a, b)` | True when the normalised range covers ≥ 2 cells. |
| `merge(grid, a, b)` | Top-left gains the covering colspan/rowspan; every other cell in the range is removed from its row. |
| `split(grid, cell)` | Remove the cell's spans; re-insert empty cells (via `grid.makeCell`) into the correct position in each freed row. |

`grid.makeCell` keeps the module kind-agnostic: `table_editor.js` passes its `newCell()`,
`filltable_editor.js` passes its own (which produces a static cell).

**Insert position, precisely.** "Straddling" and "inside" are ambiguous at a span's edges,
and two implementers would choose differently on a corpus full of full-width spans. The
rule is numeric: a cell anchored at column `c` with colspan `s` **grows** iff
`c < layoutCol < c + s`. At `layoutCol == c` a fresh independent cell is inserted
*before* it (the span does not grow). At `layoutCol == c + s` the insert falls outside
the span entirely. `insertColumn(grid, width)` appends at the right edge and is legal.
`insertRow` mirrors the same inequality against `r` and `rowspan`.

**Handler → API mapping.** The existing buttons are labelled "Insert column right" and
carry `data-col-index`, while the new API inserts *at* a layout column. The translation
is `insertColumn(grid, i + 1)` and `deleteColumn(grid, i)`, where `i` is now the
**layout** column of the pressed handle; `insertColumn(grid, width)` appends. Consequence,
stated so it is not rediscovered: pressing "insert right" on a column that is a colspan's
*last* covered slot yields `layoutCol == c + s`, so the span does **not** grow — a new
cell appears after it.

Rows map **identically**, which is why `insertRow` takes an *at*-index rather than an
"after" one: "insert below" on row handle `i` is `insertRow(grid, i + 1)`, and
`insertRow(grid, height)` appends. Naming the row parameter `afterIdx` while columns use
an at-convention is exactly the off-by-one this spelling-out exists to prevent.

**`deleteRow` anchor relocation.** This is the one genuinely hard step, and it is *not*
a transpose of `deleteColumn`: deleting a column never moves a node between rows, whereas
deleting the anchor row of a `rowspan > 1` cell must physically relocate that cell's node
into the next row it covers. The rule:

1. For each cell anchored in the deleted row with `rowspan > 1`: take its node, decrement
   its rowspan by 1, and move it into row `idx + 1`. **Terminal case:** when the deleted
   row is the *last* row, there is no row `idx + 1` — this is reachable via an overflowing
   stored rowspan (hand-edited JSON), which the degenerate-input policy promises to
   degrade rather than throw on. Such a cell is simply removed with its row, no
   relocation attempted, since after clipping it covers no surviving row. Folded into the
   existing "delete the final row under an overflowing rowspan" test.
2. Its insertion position in that row is computed from the *target row's* slot map:
   before the first data cell whose layout column is greater than the moved cell's layout
   column, and always before the trailing control cell. If no such cell exists, it goes
   last among the data cells.
3. Cells merely *straddling* the deleted row (anchored above it) just decrement their
   rowspan; no node moves.
4. Then clamp to the bounds invariant below.

Named test: *delete the anchor row of a `rowspan=3` cell sitting mid-way along a wide
row*, asserting the node lands in the right row at the right sibling index.

**Bounds invariant.** After *every* op, each cell satisfies `r + rowspan <= height` (the
column half being definitionally satisfied — see above). This is separate from the
`MAX_COLS`/`MAX_ROWS` caps: clamping a rowspan to 50 does not stop it overflowing a
6-row grid. It matters concretely because
the data rows and the injected `tr[data-control-row]` share one `<table>` — an
overflowing rowspan shoves the control strip sideways and misaligns every handle.
`deleteRow` on the last row is the op that most easily produces this, so it clamps to the
new height rather than only shrinking straddling spans.

### Round-trip fidelity (must land before any UI)

- `_edit_table.html` / `_edit_filltable.html` emit `colspan` / `rowspan` on editor cells
  and render a cell carrying `header: true` as `<th contenteditable="true">` with the
  same `data-halign` / `data-valign` / `class` / kind attributes a `<td>` would get.
  **Precedence: the cell's own `header` flag wins, always** — mirroring the render
  templates, where `{% if cell.header %}` is deliberately the *first* branch, ahead of
  the `header_row` / `header_col` ones. Otherwise a cell that is both in row 0 of a
  `header_row` table and carries its own `header: true` would render `<td>`, and
  `serialize()` (which emits `header: true` only for `TH` tags) would silently drop a
  stored flag on every save — the exact data loss this work exists to stop. No corpus
  table currently combines the two (verified: zero of 24), but an author can create the
  combination by switching on **Header row** over imported per-cell headers, so it is
  pinned by a round-trip test rather than left to chance. The "do not promote to `<th>`"
  rule below applies *only* to cells promoted by the toggles. The
  editing grid thereby reproduces the student **span layout** — it is deliberately *not*
  a pixel-match of the student view: the editor adds a control column and control row,
  and it does **not** render `header_row` / `header_col` cells as `<th>` (see the header
  toggle section for why that would break byte-identity).
- Both `serialize()`s read `td.colSpan` / `td.rowSpan` back, emitting the key **only
  when > 1**, and emit `header: true` only for cells whose tag is `TH`.
- **Every `td`-scoped selector must accept `th`.** `dataCells()` is not the only one; a
  `<th>` that only half the selectors match is un-focusable, un-alignable, and invisible
  to the submit guard. The full inventory to change:

  | File | Site | Today |
  |---|---|---|
  | `table_editor.js` | `dataCells()` | `td[contenteditable]` |
  | `table_editor.js` | `focusin`, `keydown`, `input` handlers | `closest("td[contenteditable]")` ×3 |
  | `filltable_editor.js` | `dataCells()` | `td:not([data-control])` |
  | `filltable_editor.js` | `focusin` handler | `closest("td[contenteditable], td[data-answer], td[data-image]")` |
  | `filltable_editor.js` | `keydown`, `input` handlers | `closest("td[contenteditable]")` ×2 |
  | `filltable_editor.js` | submit guard | `querySelectorAll("td[data-answer] .filltable-editor__answer")` |
  | `editor.css:595,600,607` | `.table-editor__grid td`, `td:focus`, `td[data-control]` | border, padding, min-width, focus outline |
  | `courses.css:902,904` | `.el-editor--filltable … td`, `.filltable-editor__grid td[data-answer]` | border colour, answer-cell styling |

  The CSS sites matter as much as the JS ones: without them every `<th>` in the editing
  grid renders with no border, padding or focus outline, and a `<th>` answer cell loses
  its shading — on precisely the imported tables this work targets, since all 48
  `header: true` cells live in spanning tables. A source-level test asserts no `td`-only
  cell selector remains in either JS file **or** either CSS file, so a future edit cannot
  silently reintroduce one.

  The guard's rule is "**any selector that can match a _data_ cell must also match
  `th`**", with two named exemptions, or it becomes a whitelist-everything no-op: chrome
  selectors scoped by `[data-control]`, and element construction
  (`document.createElement("td")`, 8 sites). The guard must go RED when any single
  inventory row above is reverted — that is what makes it a real test rather than a
  grep in prose.

### Render templates: the `<th>` gap (in scope, slice 1)

`tableelement.html` and `filltableelement.html` emit `colspan`/`rowspan` on the
`cell.header` branch and on the plain `<td>` branch — but **not** on the `<th>` branches
driven by the `header_row` / `header_col` toggles. So a merge in row 0 of a header-row
table stores a span that the student render silently drops.

This is not hypothetical: `250_pole_trojkata` — the fill-table this work exists to
unblock — has `header_row: True`, and merging in its first row is an obvious author
action. Both templates must emit `colspan`/`rowspan` on **every** `<th>` branch, with a
partial-render test for a `header_row` table whose row-0 cell spans.

### Server-side (in scope)

**Form validation currently makes this whole design unsaveable.**
`TableElementForm.clean_data` (`courses/element_forms.py:1343`) computes
`widths = {len(r) for r in rows}` and raises *"All table rows must have the same number
of cells."* whenever `len(widths) != 1`. A spanning grid is ragged by construction, so
**every** `TableElement` save from the new editor — including slice 1's zero-edit
round-trip — is rejected before `normalize_data` is ever reached. This must be relaxed:

> If any cell carries `colspan`/`rowspan` > 1, skip the uniform-width check and validate
> the **layout** width/height (from a server-side slot walk) instead of per-row cell
> counts. Non-spanning grids keep today's check verbatim.

**Detection vs. range are two different checks, and they must not share a helper.**

*Detection* ("is this grid spanning?") uses `TableElement._span(c, key) is not None`, for
two reasons: a bare `c.get("colspan") > 1` raises `TypeError` on a string value → 500,
and `_span` is the very definition `normalize_data` uses to pick its branch, so detection
cannot diverge from the branch actually taken. Note what `_span` does **not** do: it does
not coerce (`isinstance(n, bool) or not isinstance(n, int) → None`), so a string
`"colspan": "3"` is *not* a span — such a grid is treated as non-spanning and its ragged
rows are still rejected, consistently with how `normalize_data` would have handled it.
The scan also **skips non-dict cells** (today's code only reads `len(r)`, so a crafted
POST with a non-dict cell survives to `normalize_data`; a naive `c.get(...)` would raise
`AttributeError` → 500). Named tests: a string span → treated as non-spanning → the
ragged rejection still fires and there is no 500; a non-dict cell → no 500.

*Range* ("is this span within the caps?") must read the **raw** `c.get(key)` int, guarded
for bool/non-int — **never** `_span`'s return value, which is already clamped to the cap
and would therefore always look in-range. Using `_span` here would silently reinstate the
truncation the decision below forbids.

**Guard ordering.** The existing `clean_data` has two guards ahead of the uniform-width
one, and they stay first and unchanged, stated verbatim so they are not accidentally
tightened: a non-list `cells` is rejected, then `-1 in widths or widths == {0}` — that
is, **a non-list row, or *every* row empty**. Note what this is *not*: a per-row
zero-width rejection. A single empty row is legal (see "Empty data rows are legal"), and
a per-row reading would reject every full-width multi-row merge. Only *after* those two
guards does the span scan choose between the uniform-width check and the layout check;
hoisting the span branch above them would lose a genuine malformed-input rejection.
Positive test: a spanning grid containing one empty row saves.

**Where each check runs differs per form**, because the two forms are structurally
different — this is not one uniform recipe:

- `TableElementForm.clean_data` validates **raw** `cleaned_data["data"]`, so both the
  detection scan and the range check live there as described.
- `FillTableElementForm.clean_data` calls `normalize_data` on its first line and
  validates the *normalised* cells — where every cell is already a dict and every span
  has already been through `_span`, so the range check there would be **impossible**
  (normalisation has already clamped). It must therefore do its span work on the raw
  `cleaned_data["data"]` *before* normalising, at which point the raw-JSON caveats apply
  in full, exactly as for the table form.

Both forms call **one shared helper** rather than each growing its own copy, with its
responsibilities pinned so the split cannot drift:

> `courses/element_forms.py: _scan_spans(cells) -> bool` — returns whether the grid is
> spanning (detection, via `_span`), raising `ValidationError` for a **raw** span value
> out of per-axis range (read as a raw int, guarded for bool/non-int). The range is
> `2 <= n <= cap`: a value below 2 is **not a span**, so it is ignored rather than
> rejected — matching `_span` (which returns `None`) and `layout_dims` (which counts it
> as 1), so a crafted `colspan: 0` or `-3` cannot be read two ways. Skips non-dict
> cells. Does **not** compute layout dims, apply the caps, or consult `self.instance` —
> grandfathering needs the instance and stays in each form's `clean_data`, which calls
> `layout_dims` itself.

`FillTableElementForm.clean_data` has no raggedness check, but derives
`n_cols = len(cells[0])` — meaningless once row 0 is a single full-width merged cell, so
the 20-column cap silently lapses. It gets the same layout-based computation.

**Caps are grandfathered, not absolute.** `130_kombinatoryka/240_kombinatoryka` has a
measured layout width of **26** against `MAX_COLS = 20`. Expressing the caps in layout
terms would make that existing element unsaveable. So the caps gate **growth**, with the
baseline pinned precisely: the stored dimensions are
`layout_dims(normalize_data(self.instance.data)["cells"])` — the pre-save DB value, never `cleaned_data`, which
would make the rule circular — and **`(0, 0)` when `self.instance.pk is None`**, as an
explicit special case rather than a property of the expression (`normalize_data({})`
returns the default **2x2**, not an empty grid). Either way a brand-new 21-column table
is rejected normally. **Each axis is compared independently**
(`new_axis > cap and new_axis > stored_axis`), so a 26x10 grid narrowed to 24 columns but
grown to 12 rows is judged per-axis rather than passed wholesale.
`refreshControlState` correspondingly disables insert when at or over the cap, which
leaves that table's column strip insert-disabled — correct, and it stays editable
otherwise.

**The client gate is deliberately stricter than the server rule.** The server accepts
`new_axis <= stored_axis` even above the cap; the client simply disables insert at or
above the cap, because it has no source for `stored_axis` (no data attribute carries it,
and inventing one to re-widen a grandfathered table is not worth the surface). The
practical consequence, stated so it is a decision rather than a surprise: **narrowing a
grandfathered over-cap table is one-way** — delete a column from the 26-wide table and
the UI will not let you add it back. The help wording must therefore say the limit
applies to *adding* rows/columns, not promise that an over-cap table can be restored.

**`_span` must stop clamping silently — both axes.** `TableElement._span`
(`courses/models.py:838`) currently does `min(n, MAX_COLS)` for *both* keys. Two defects
follow, and the second is one this work would newly create:

- `rowspan` is clamped against the *column* cap. It should use `MAX_ROWS` (50).
- A full-width merge on the grandfathered 26-column table posts `colspan: 26`; the
  relaxed form accepts it (26 is not larger than the stored width) and `_span` silently
  rewrites it to 20 — producing exactly the layout-**inconsistent** grid the
  "editor only ever posts a layout-consistent grid" invariant exists to prevent. The
  corpus maximum colspan today is 12, so this is reachable only once authors have a merge
  button.

**Decision: refuse, never silently clamp.** `canMerge` returns false for a range wider
than `MAX_COLS` or taller than `MAX_ROWS`, and the forms reject an out-of-range span
rather than truncating it — reading the **raw** posted int, per the range-check rule
above, since `_span`'s clamped return can never be out of range. `_span` keeps its clamp
only as defence-in-depth for non-form write paths, fixed to the correct per-axis cap
(`MAX_COLS` for colspan, `MAX_ROWS` for rowspan). Named tests: merge all 26 columns of
the 26-wide grid → the merge is refused; a hand-posted `colspan: 26` → `ValidationError`,
and nothing is stored as 20.

**The layout walk needs one home.** Both forms and the grandfathering baseline need
layout dimensions, and if the server's number ever disagreed with the editor's
`layoutWidth()` the caps could reject a grid the editor believes legal — an author-facing
dead end. So it is one named function: **`TableElement.layout_dims(cells) -> (width,
height)`** in `courses/models.py`, called by both forms and by the baseline computation.
Its degenerate-input behaviour matches `slotMap`'s verbatim (last-writer-wins on a
collision, unreached slots unoccupied), pinned by a shared-expectation test that runs the
same fixture grids through `layout_dims` and through `slotMap` and asserts equal
dimensions.

`layout_dims` also faces inputs `slotMap` never can: the table form calls it on **raw**
data, where a DOM-backed slot map would be impossible — so its handling of malformed
cells is specified rather than left to the shared test (whose fixtures are well-formed by
construction). A **non-dict cell counts as a 1x1 occupant**, and a span value that fails
`_span`'s type test **counts as 1**. Both go in the degenerate-input test set. Getting
this wrong changes the computed width and therefore the caps verdict.

`normalize_data` is otherwise untouched.

**The branch flip is the sharp edge.** `normalize_data` picks its branch dynamically from
"does any cell carry a span". Splitting the *last* merge flips a grid from the
keep-ragged-verbatim branch to the rectangularising branch (pad-to-max-width, plus the
degenerate 2x2 collapse guard); the first merge flips it back. If the posted grid were
ever not layout-consistent at that moment, the save would silently inject phantom cells —
empty static cells in a fill-table — or, at width 0, replace the grid with a default 2x2.

The invariant that makes this safe: **the editor only ever posts a layout-consistent
grid**, so a fully-split grid is exactly rectangular and the flip is a no-op. Guarded by
the bounds invariant above and pinned by a test: merge → save → split all → save →
dimensions and cell contents unchanged, and no `colspan` / `rowspan` / `header` keys
remain.

**Accepted, deliberately:** *shape* enforcement (layout consistency) lives only in JS.
The size caps are enforced server-side by the forms, per the layout-based rule above —
but nothing server-side checks that a posted spanning grid is layout-*consistent*. A
crafted or stale POST could store a grid whose spans overlap or leave holes. This is the
same trust boundary as today's ragged/aligned assumptions, the data is author-only behind
a course-scoped permission check, and the failure mode is one course's table rendering
badly — not a security or integrity issue. Enforcing consistency server-side would mean
reimplementing the slot map in `normalize_data`, which is a non-goal.

**The bound-invalid re-render must not diverge from the hidden field.** The editor
templates render the grid from `form.instance.normalized_data` — the *stored* value —
while on a rejected save the hidden field carries the *submitted* JSON, and `serialize()`
deliberately skips init when that field is non-empty. Today that divergence is nearly
unreachable; this work adds new server-side rejections (out-of-range span, over-cap
growth, the relaxed structural checks) that an author hits from an ordinary merge
gesture, and they would then see the *pre-merge* grid while the field still holds the
merged JSON — so the next Save silently re-posts the rejected shape. Fix: on a
bound-invalid re-render, render the grid from the **submitted** JSON. Named test: an
over-cap merge → rejected save → the visible grid and the hidden field agree.

**Browser undo.** The grid is `contenteditable`, so a Ctrl+Z after a merge can partially
resurrect DOM that `table_grid.js` removed, leaving spans that no longer match the cells
— which would post a non-layout-consistent grid and defeat the invariant above.
Accepted as a known risk rather than intercepted: `serialize()` re-reads the live DOM, so
the damage is bounded to a table the author is actively looking at and can fix by
splitting and re-merging. Live verification includes one Ctrl+Z-after-merge probe to
confirm the result is visibly wrong rather than silently corrupt.

## Editor UX

### Selection

- Per-editor state: `focusCell` (a cell node), `rangeAnchor` (a cell node) and
  **`rangeEnd` (a layout `(r, c)` coordinate, not a node)**. The two are different types
  deliberately: `Alt+Shift+Arrow` moves by one layout *slot*, which is undefined against a
  node — for a `colspan=3` cell, "one slot right" would either advance within the same
  cell (a keystroke with no visible effect) or jump a whole cell, and implementers would
  split on it. `rangeCells` accepts a cell **or** a coordinate for its second argument,
  resolving a coordinate through the slot map; seeding from `focusCell` uses that cell's
  **anchor** slot. A press that lands on a `null` slot in a degenerate grid moves on
  (the slot is skipped) rather than selecting nothing.
- **`focusCell` is the single authority** for which cell the toolbar acts on. It is set
  on plain click / `focusin` and is deliberately **not** moved by Shift+click. This
  matters because suppressing the Shift+`mousedown` (below) also suppresses focus
  movement, so `document.activeElement` is not a usable source. Split enablement, Header
  toggle enablement and the arrow-extension origin all read `focusCell`; only Merge reads
  the range. `focusCell` replaces the existing `focusedCell` variable in both editors.
- A plain click / focus in a cell sets `focusCell` and `rangeAnchor` and clears the
  range. Today's caret, B/I/U and math-insert behaviour is untouched.
- **Shift+click** sets the range end. `mousedown` with `shiftKey` inside the grid is
  `preventDefault`ed so `contenteditable` does not start a text selection; the `click`
  handler computes `rangeCells` and marks each covered cell `is-range`.
  The suppression is **scoped away from form controls** — skipped when
  `e.target.closest("input, textarea, select, button, [data-control]")` — because the
  fill-table's answer cells contain a real `<input>`, where Shift+click is a legitimate
  text-selection gesture a blanket suppression would kill. A Shift+click landing on
  chrome or inside an input leaves `rangeEnd` untouched.
  **A Shift+click while `rangeAnchor` is null** — the likely case when it is the author's
  *first* gesture in a freshly loaded editor, since the `mousedown` suppression means no
  `focusin` has fired — seeds `rangeAnchor` and `focusCell` from the clicked cell and
  forms no range, i.e. it behaves exactly like a plain click. It must not reach
  `rangeCells` with a null anchor. Covered in the named degenerate tests.
- **Alt+Shift+ArrowRight / ArrowDown / ArrowLeft / ArrowUp**, `preventDefault`ed, is the
  keyboard equivalent. `Alt+Shift` is chosen because plain and `Ctrl` arrows are taken by
  caret and word movement inside `contenteditable`. Semantics, precisely: **move
  `rangeEnd` one layout slot in that direction, clamped to the grid, then re-normalise**
  (`rangeCells`) — so pressing ArrowLeft after ArrowRight *shrinks* the range back toward
  the anchor rather than extending past it, an arrow at the grid edge is a no-op, and a
  range that comes to clip a merged cell re-expands on every keystroke. With no range
  yet, the first press seeds `rangeEnd` from `focusCell`.
  ⚠️ On Windows, `Alt+Shift` is the OS keyboard-layout-switch chord — directly relevant
  for a PL/EN author — and `Alt+Arrow` is browser history navigation. The chord must be
  probed in a real browser **at the end of slice 3**, as soon as the keyboard handler
  first exists — *not* in slice 5's live verification, which runs after four help files
  and their Polish translations are already committed. The confirmed chord is then an
  input to slices 4 and 5, so the help text and msgids are written once. If it fails,
  fall back to `Ctrl+Alt+Arrow`.
- `Escape` clears `rangeEnd` and the highlight but **leaves `rangeAnchor` at
  `focusCell`**, so the next Shift+click forms a range from where the author actually is
  rather than from a stale anchor. The handler acts — and stops propagation — **only when
  a range is active**, so a stray Escape still reaches the media-picker and math-input
  modals that share the editor page. So does any structural edit (row/column insert or
  delete, merge, split) — the same discipline as the fill-table editor's existing
  `cellStash.clear()` on structural edits (`table_editor.js` has no stash).
- **Node references must be re-pointed after every structural op**, or they dangle: after
  a merge `focusCell` may be an absorbed, now-detached cell; after a row/column delete it
  may be a removed one. A detached `focusCell` makes Split/Header enablement and the
  alignment buttons act on a node outside the document, and the Header toggle would
  `replaceWith` into nothing. Rule: merge → `focusCell` becomes the surviving top-left;
  split → the anchor; delete → `null`, with the toolbar hidden. Tested by merging while
  focus sits on an absorbed cell, then pressing Split.
- The `Alt+Shift+Arrow` listener is registered **on the grid**, not the document, so it is
  scoped to the editor that owns it (the page can hold more than one). With `focusCell`
  null — before any click, or after a delete cleared it — the keystroke is a **no-op**.
- Highlight is an outline + tint in `editor.css`, styled for light **and** dark.

### Toolbar (both editors)

After a `.rte-sep`, three buttons using new monochrome `currentColor` sprite symbols in
`editor.html` (`ed-merge`, `ed-split`, `ed-header`), matching the existing
`ed-answer` / `ed-image` line style:

- **Merge** — enabled only when `canMerge` is true. When a range is legal in shape but
  **too large** (wider than `MAX_COLS` or taller than `MAX_ROWS` — reachable by selecting
  all 26 columns of the grandfathered table), the button carries a `title` saying the
  selection exceeds the size limit, rather than greying out unexplained. That string is
  a `data-msg-*`, added to slice 3's msgids and mentioned in the help pages beside the
  reworded caps message.
- **Split** — enabled only when `focusCell` has a colspan or rowspan > 1. No range
  needed.

⚠️ `filltable_editor.js`'s existing `refreshToolbarState` opens with
`if (!toolbar || !focusedCell) return;`. The new Merge/Split/Header enablement must run
**before**, or independently of, that early return — otherwise a delete that sets
`focusCell` to `null` leaves the three buttons in whatever state they last had (e.g.
Merge still enabled). "Toolbar hidden" is a different mechanism and does not substitute.
Same requirement in the `refreshToolbarState` that slice 3 adds to `table_editor.js`.
- **Header cell** — a toggle mirroring the existing "Answer cell" `is-on` pattern,
  flipping `focusCell` between `<td>` and `<th>`. See below: it is *not* a plain
  attribute flip, and it is disabled for cells already covered by the header toggles.

All strings ride on `data-msg-*` attributes on the editor root (the established
convention for client-built markup that cannot call `{% trans %}`), including the
merge-confirm text.

**Accessibility:** Merge and Split get `aria-label` plus a real `disabled` attribute (not
just a class); Header cell gets `aria-pressed` reflecting its state. Range membership is
announced through a visually-hidden `aria-live="polite"` region whose text is
**count-free** — "Range selected" / "Range cleared", never "3 cells selected", for
precisely the reason the merge confirm is count-free (a count needs `ngettext`, and
Polish has three plural forms a single `data-msg-*` cannot carry) — and
**not** `aria-selected`, which is only meaningful on `gridcell`/`option`/`row` roles and
is ignored (and axe-flagged) on a bare `<td>`; giving the editing table `role="grid"`
would mean owning full grid keyboard semantics, which is out of scope. These are stated
here because the frontend-design pass at the end reviews appearance, not semantics.

#### Header cell: node replacement, not an attribute flip

Unlike the Answer-cell toggle, `td` ↔ `th` requires a **new element**, and several live
references point at the old node. The procedure:

1. Create the new element with the opposite tag.
2. Copy every attribute (`class`, `data-halign`, `data-valign`, `colspan`, `rowspan`,
   `contenteditable`, and the fill-table's `data-answer` / `data-image` / `data-media` /
   `data-alt` / `tabindex`).
3. **Move** `childNodes` across — moved, not re-serialized, so a live
   `.filltable-editor__answer` input keeps its typed value and its event bindings.
4. `replaceWith` the old node.
5. Re-point every reference: the `cellStash` entry (fill-table only — a `Map` keyed by
   the live node, so the stashed other-kind content is otherwise silently orphaned),
   `focusCell`, and `rangeAnchor`. (`rangeEnd` is a coordinate, so it needs no
   re-pointing.)
6. Re-focus, `refreshToolbarState()`, `serialize()`.

Tested: toggling header on an answer cell preserves its typed answer **and** its stash
entry (so a later answer→static toggle still restores the right HTML).

#### Header cell vs. the `header_row` / `header_col` toggles

The model cannot express "this cell is *not* a header": `_cell` writes `header: True`
only when truthy, and `header_row` / `header_col` promote row 0 / column 0 to `<th>` at
render time regardless. So for a cell covered by those toggles, "turn header off" is
unimplementable without a new `header: false` sentinel — a model change this spec does
not want.

**Decision:** the Header-cell toggle is **disabled** (with a `title` explaining why) for
any cell the toggles already promote. Elsewhere it is enabled and its `is-on` state is
simply "this cell's tag is `TH`".

"Already promoted" must be defined exactly as the render templates define it, or the
editor and the renderer disagree about which cells are covered:

- `header_row` → **row 0** (`forloop.parentloop.first`). Unambiguous.
- `header_col` → the **positionally first cell of each row** (`forloop.first`), i.e.
  `cells(tr)[0]` — *not* layout column 0. On a ragged spanning grid these genuinely
  diverge: a row whose layout column 0 is occupied by a rowspan anchored above starts its
  cell list at layout column 1 or later. Today's templates promote the positionally first
  cell, so **the editor matches that** — adopting a layout-column definition would
  silently change how existing content renders, which this work must not do. A
  partial-render test pins it: a `header_col` table where a row-0 rowspan occupies row
  1's layout column 0.

**Accepted simplification:** the blanket disable also blocks *removing* a genuine
per-cell `header: true` from a cell that `header_row`/`header_col` happens to cover —
which is technically implementable (just delete the key). It is disallowed anyway,
because allowing it would produce an editor/student divergence this spec otherwise works
hard to avoid: the editor would drop to `<td>` while the student render still shows `<th>`
via the toggle. So ticking "Header row" does freeze any per-cell header flags beneath it.
The button `title` and the help wording say the toggle is unavailable while the row/column
header option covers the cell, without promising the flag underneath is editable.

**Enablement is live.** `header_row` / `header_col` are checkboxes the author can flip
while the same cell stays focused — the very scenario noted above. The JS reads the
existing `[data-th-row]` / `[data-th-col]` inputs inside the editor root, and both get a
`change` listener that calls `refreshToolbarState()`, so the button's `disabled`,
`aria-pressed` and `title` never go stale. Tested: enable **Header row** while focus sits
in row 0 → the button becomes disabled without a re-click.

This is also why the *editor* grid does not render `header_row` / `header_col` cells as
`<th>`: if it did, `serialize()` would start writing `header: true` for cells that never
had it, breaking the byte-identity constraint for every existing header-row table.

### Grid handles

The column control strip is rebuilt from `slotMap().width` — one button pair per
**layout** column, so it lines up with a ragged grid. Row handles are unchanged.
`refreshControlState` gates on layout width/height: insert is disabled at or above
`MAX_COLS` / `MAX_ROWS` (per the grandfathering rule), and **delete stays disabled at
layout width 1 or height 1** — today's floor guard, which must be restated in layout
terms because "one layout column left" is not the same as "one cell left in row 0".

### Merge

The top-left cell of the normalised range gains the covering colspan/rowspan; every
other cell in the range is removed from its row. Top-left keeps its content, its kind
(static / answer / image), its alignment and its header flag.

A single `confirm()` fires when any absorbed cell is non-empty, where **non-empty**
means: static HTML that is not blank, **or any answer cell, or any image cell**. Cancel
leaves the grid untouched. This is what satisfies the constraint that a merge never
silently loses an accepted answer or an image `media` pk.

**Interaction with `header_col`, accepted:** because `header_col` promotes each row's
*positionally first* cell, a vertical or full-width merge that removes a row's first cell
silently promotes the **next** cell in that row to `<th>` at student-render time — and
the author sees nothing, since the editor deliberately does not render `header_col` cells
as `<th>`. This is accepted rather than engineered around (detecting and blocking it would
mean the editor tracking a render rule it otherwise ignores), and the help text mentions
it. Test: merge column 0 across two rows of a `header_col` table and assert what the
render template emits for the now-first cell of the affected row.

**Tail sequence** (the same discipline the Header toggle's step 6 spells out, required
here too): re-point `focusCell`, clear the range and `cellStash` (fill-table only),
`rebuildColControls`,
`refreshControlState`, `refreshToolbarState`, `serialize()`. Note that
`refreshToolbarState` exists **only in `filltable_editor.js`** today — `table_editor.js`
has `refreshAlignButtons` and no toolbar-state function, so slice 3 adds one there
(wrapping `refreshAlignButtons` plus the new Merge/Split/Header enablement). Skipping `serialize()` loses
the merge on save; skipping the control rebuild leaves the strip at the old layout width.
**Split runs the identical sequence.**

The message is deliberately **count-free** — "Merging will discard the content of the
other selected cells." A count-bearing string would need `ngettext`, and Polish has three
plural forms, which a single `data-msg-*` attribute filled by `{% trans %}` cannot
express. Not worth `{% blocktrans count %}` plus JS plural selection for a confirm
dialog.

### Split

The anchor's spans are removed and the freed slots return as **each editor's default
empty cell** (`grid.makeCell`) — a plain contenteditable cell for `TableElement`, which
has no cell kinds, and a static cell for the fill-table. Discarded content is not
resurrected.

**Insertion position uses the same rule as `deleteRow`'s relocation**, because "the
correct position" in a ragged row is exactly as non-obvious here — and worse, in both
axes at once: splitting a `colspan=3 rowspan=2` cell frees 2 slots to the anchor's right
in its own row and 3 slots in the row below. For **each** freed layout slot, insert
`makeCell()` before the first data cell in that row whose layout column exceeds the
freed slot's column, always before the trailing control cell; if there is no such cell,
append it last among the data cells. Named test: split a `colspan=3 rowspan=2` cell
anchored mid-row in a ragged grid, asserting the sibling index of every new cell.

### Fill-table specifics

- Merged cell keeps the top-left **kind**; no answer string or `media` pk is ever
  reinterpreted as another kind.
- The existing submit guard (≥ 1 answer cell, none blank) still fires if a merge
  absorbed the last answer cell — no change needed.
- `cellStash` is cleared on merge and split, as on any structural edit.
- A `<th>` may hold an answer or image cell: `filltableelement.html` already routes both
  its `<th>` and `<td>` branches through `_filltable_cell.html`, so this renders.

## Help pages

Four files, text only:

- `docs/help/course-admin/content-editors.md` + `.pl.md` — the `{el:table}` paragraph.
- `docs/help/course-admin/interactive-elements.md` + `.pl.md` — the `{el:filltable}`
  section.

Each gains a short passage covering: Shift+click to select a range, `Alt+Shift+Arrow` as
the keyboard equivalent (or whatever slice 3's chord probe confirms), the Merge / Split /
Header cell buttons, the fact that merging keeps only the top-left cell's content, and —
the one behaviour authors will otherwise file a bug about — **why Header cell is greyed
out** when "Header row" / "Header column" is ticked, worded to match the button's own
`title` so help and UI agree.

The existing caps message, *"Tables are limited to %(r)d rows by %(c)d columns."*, is now
misleading under grandfathering (a 26-wide table *is* saveable, and the cap really gates
growth). Reword it to say the limit applies to *making a table larger*, which makes it a
changed msgid — so it joins slice 5's Polish translation list.

No new screenshots: the existing help images are page-level editor overviews
(`content-editor.en.png`), not element-toolbar close-ups, so they do not go stale.
Per project convention, any msgid removed from a `.po` must be deleted, not left
obsolete — these are additions only, but the i18n catalog tests still run.

## Testing

0. **The headline data-loss test, first — and it must be browser-driven.** The stated
   motivation is that saving a spanning table *untouched* strips its spans, so that is
   the falsifying RED test for slice 1: load a spanning fixture, open the editor page in
   a real browser, click **Save** with **zero** other gestures, then assert the grid's
   **structure** survived: per-cell `colspan` / `rowspan` / `header` / `kind`, plus each
   row's length. Deliberately **not** a whole-grid `normalize_data` equality — every
   cell's `html` makes a round trip through `contenteditable`'s `innerHTML`
   re-serialization and the server sanitiser, and imported LAL markup (math, entities,
   attribute order, whitespace) can legitimately return non-identical while every span
   and header flag is perfectly preserved; a whole-grid equality would be a permanent,
   misleading RED that an implementer "fixes" by weakening the test. For the same reason
   the fixtures use plain-text cell content, leaving structure as the only signal.
   Run for both a spanning `table` and
   a spanning `fill_table`, each fixture carrying a `header: true` cell **and** a rowspan
   (48 `header: true` cells exist across the corpus, so this is not a corner case). The
   `fill_table` fixture must also carry **at least one non-blank answer cell** — and
   ideally one image cell, to exercise the `media` path — or
   `FillTableElementForm.clean_data`'s no-answer / blank-answer guards reject it and it
   goes RED for a third, misleading reason.

   It **must not** be a Python test that POSTs the stored JSON: on the edit path the
   hidden field renders empty (`value="{{ form.data.data|default:'' }}"`) and
   `serialize()` fills it from the live DOM on init, so a POST-based test never exercises
   the code under test and would pass today — a textbook vacuous test.

   **The assertion must be two-part, or the `table` half is vacuous by construction:** a
   rejected save writes nothing, so `after == before` is trivially satisfied and the test
   would be GREEN before a line of code is written — the precise failure mode the
   project's *falsify tests, don't run them* lesson warns about. So test 0 asserts
   **first that the save succeeded** (redirected, no form error rendered) and only then
   compares `normalize_data`.

   With that addition the two fixtures go RED for **different reasons**, and an
   implementer should expect that rather than suspect the harness: the `table` fixture
   fails the *success* assertion (the *"All table rows must have the same number of
   cells"* rejection above), while the `fill_table` fixture passes it and fails the
   *equality* assertion, having silently stripped its spans.
1. **Python partial-render + model tests** (default run, no browser):
   editor templates emit `colspan` / `rowspan` and `<th contenteditable>` for a spanning
   instance; **render** templates emit spans on the `header_row` / `header_col` `<th>`
   branches; a plain table's editor markup is unchanged; `_span` clamps `rowspan` to
   `MAX_ROWS`; the source-level check that no `td`-only cell selector remains.

   Two negative-space tests the relaxation's safety argument rests on, neither of which
   any other listed test would catch:
   - **A ragged grid with no spans is still rejected** — and so is one whose only span
     key is `colspan: 1`. A branch predicate written a shade too broadly ("any cell has a
     `colspan` key") would disable raggedness validation for *every* table while leaving
     the whole suite green.
   - **Grandfathering has positive cases, not only refusals.** The reason it exists is
     that the 26-wide table stays saveable, so: a stored 26-wide grid saves unchanged;
     narrowed to 24 it still saves; widened to 27 it is rejected; and growth past
     `MAX_ROWS` is rejected independently of the column axis (per-axis comparison). Get
     the comparison backwards and that element can never be saved again — with CI green.
2. **Grid-algebra tests for `table_grid.js`.** Its functions are pure, so they run in a
   headless page via `add_script_tag` + `evaluate` — grid in, grid out — marked `e2e`
   (there is no Node in CI; the e2e job has browsers). Explicitly: these are
   pure-function tests, **not** a stand-in for gesture tests. The real-UI convention
   governs everything in (3). Because these are `e2e`-marked, the default
   `-m "not e2e"` command never runs them — so slice 2's TDD loop uses
   `DATABASE_URL=… uv run pytest -m e2e -k table_grid` as its RED/GREEN command. Coverage
   includes the bounds invariant (`deleteRow` of the final row under an overflowing
   rowspan) and the degenerate-input policy. Decision 4 defines **four** distinct
   column-side behaviours, each of which silently destroys author content if implemented
   wrongly, so each gets its own named test asserting the resulting cell list *and* span
   values (not merely the layout width): insert-inside grows the span; delete-inside
   shrinks it; deleting a span's anchor column moves the anchor right; deleting the last
   column a span covers removes the cell.
3. **Real-gesture e2e in both editors** (clicks and keystrokes, no `page.evaluate`
   shortcuts): Shift+click a range → Merge → Save → reopen → the span survived; Split
   restores empty cells; `Alt+Shift+Arrow` builds a range; a column insert through a
   colspan widens it; a fill-table merge over an answer cell shows the confirm; an image
   cell round-trips.
4. **Regression:** a plain 2x2 saved through the editor still serializes with no
   `colspan` / `rowspan` / `header` keys.
5. **Branch-flip round trip:** merge → save → split all → save; dimensions and cell
   contents unchanged, no span or header keys remain (the `normalize_data` flip is a
   no-op, per the invariant above).
6. **Header toggle:** toggling header on an answer cell preserves its typed answer and
   its `cellStash` entry; the toggle is disabled on a `header_row` table's row 0; and —
   the subtle half of the "already promoted" definition — in a `header_col` table where a
   row-0 rowspan occupies row 1's layout column 0, the toggle is disabled on row 1's
   *positionally first* cell (layout column 1) and enabled elsewhere.

Every slice is TDD: a falsifying RED test first (memory: *falsify tests, don't run
them*). Run pytest **without** forcing `DJANGO_SETTINGS_MODULE`:
`DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e"`,
and never pipe it through `tail` (the harness reports the pipe's exit code).

## Verification on real data

With the worktree `.env` DEBUG server on `libli_mat`
(`uv run python manage.py runserver 127.0.0.1:8000`), signed in as the local pilot
account (credentials in the worktree `.env` / the project notes — not repeated here, per
the project's no-password-literals convention):

- **Pre-flight, before any code lands:** query all 24 spanning elements in `libli_mat`
  for surviving `colspan` / `rowspan` / `header` keys and diff against the import JSON.
  If any element was opened and saved through the editor before slice 1, its spans are
  *already* gone in the DB, and a read-mostly verification would never reveal it. Report
  any damage found; recovering it is a reload of that part, which needs the user's
  go-ahead.
- Open u/432's fill-table editor. Confirm the two `colspan=3` explanation rows render
  aligned and the column strip matches the layout width. Screenshot light + dark.
- Exercise merge, split, `Alt+Shift+Arrow` and a span-crossing column insert live.
  Confirm the `Alt+Shift` chord does not switch the Windows keyboard layout or trigger
  browser history navigation; fall back to `Ctrl+Alt+Arrow` if it does.
- Leave the stored element unchanged. Destructive experiments happen on a throwaway
  element that is created and deleted.
- No reseed, no reload, no course rebuild (the user is concurrently renaming nodes).

## Slices

Dependency order; each independently reviewable.

1. **Round-trip fidelity** — relax `TableElementForm`'s ragged-rows rejection and move
   both forms' caps to layout terms (grandfathered); editor templates emit spans +
   `header`/`<th>`; both `serialize()`s read them back; every `td`-scoped JS **and CSS**
   selector accepts `th`; the **render** templates emit spans on their
   `header_row`/`header_col` `<th>` branches; `_span` rowspan clamp.
   *This stops the silent span-stripping data loss for untouched saves.*
   **It also opens a window:** the structural handles still use `colCount()` (row-0 cell
   count) and cell-index insertion, so on a spanning grid they would now corrupt a table
   that previously could not be saved at all. Slice 1 therefore **disables row/column
   insert/delete whenever any cell carries a span** — a few lines, removed again in slice
   2 when the handles become span-aware.
   Slice 1 also carries the **bound-invalid re-render fix** and its test, because slice 1
   is what introduces the new server-side rejections that make the divergence reachable.
   Disabling the handles closes the *corruption* window but not the *layout* one:
   `rebuildColControls` would still emit `colCount()` button pairs, which for any table
   with a row-0 colspan is fewer than the layout width, leaving every handle under the
   wrong column — and slice 1's own live goal is that u/432's strip lines up. So the
   **read-only** half of `table_grid.js` (`slotMap` / `layoutWidth`) lands in slice 1 and
   drives the strip; only the mutating ops wait for slice 2.
2. **`table_grid.js`** — the mutating half: span-aware insert/delete/merge/split; **rewire
   the existing `data-col-index` / row handle handlers in BOTH editors** to the new API
   per the "Handler → API mapping" section; then, and only then, lift slice 1's blanket
   handle-disable. (`slotMap`/`layoutWidth` and the layout-column strips already landed in
   slice 1.) Lifting the disable before the rewiring lands would re-open the corruption
   window slice 1 closed.
3. **`table_editor.js`** — selection, Merge / Split / Header cell toolbar.
4. **`filltable_editor.js`** — the same, plus kind preservation and the confirm rules.
5. **Help pages x4** and the **i18n sweep**. Slices 3 and 4 each run `makemessages` for
   the msgids *they* introduce, so no slice lands with an out-of-date catalogue and the
   catalog tests stay meaningful per-slice; slice 5 then sweeps, supplies the Polish
   translations for all of them (the three button labels, the disabled-Header `title`,
   the live-region text, the merge confirm), checks for fuzzy flags and runs
   `compilemessages`. Then live verification on u/432, then the **frontend-design** pass
   over the new buttons, icons and range highlight (screenshot light + dark and
   self-critique before shipping).
