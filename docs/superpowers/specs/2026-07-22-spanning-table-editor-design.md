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
{ rows: [<tr>, ...],        // data rows only (control row excluded)
  cells: (tr) => [...],     // the row's data cells only (control cell excluded)
  makeCell: () => <td> }    // the caller's default empty cell factory
```

`rows` and `cells` are exactly the editors' existing `dataRows()` / `dataCells()`
helpers, so there is one definition of "what is a data cell" per editor and the module
inherits it. Structural ops insert relative to the row's data cells and **before** the
trailing control cell; `insertRow` inserts before `tr[data-control-row]` by inserting
relative to a sibling data row, never by appending to the table.

**Degenerate-input policy.** `normalize_data` permits grids that are not layout-
consistent (two cells claiming one slot; a row that does not reach the layout width).
`slotMap` is **last-writer-wins** on a collision, leaves unreached slots `null`, and
treats `null` as unoccupied. Structural ops are a no-op on a row that does not reach the
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
| `insertColumn(grid, layoutCol)` | Insert a layout column at `layoutCol`; straddling colspans grow by 1. |
| `deleteColumn(grid, layoutCol)` | Delete a layout column; straddling colspans shrink by 1; an anchor in that column moves right; a cell whose last covered column goes is removed. |
| `insertRow(grid, afterIdx)` | Insert a row; straddling rowspans grow by 1; only uncovered slots get real new cells (via `grid.makeCell`). |
| `deleteRow(grid, idx)` | Transpose of `deleteColumn`. |
| `rangeCells(grid, a, b)` | The rectangle between two cells, **normalised**: expanded until it contains every partially-clipped merged cell whole, so a range is always a legal rectangle. Returns `{ cells, anchor, r0, c0, r1, c1 }`. |
| `canMerge(grid, a, b)` | True when the normalised range covers ≥ 2 cells. |
| `merge(grid, a, b)` | Top-left gains the covering colspan/rowspan; every other cell in the range is removed from its row. |
| `split(grid, cell)` | Remove the cell's spans; re-insert empty cells (via `grid.makeCell`) into the correct position in each freed row. |

`grid.makeCell` keeps the module kind-agnostic: `table_editor.js` passes its `newCell()`,
`filltable_editor.js` passes its own (which produces a static cell).

**Bounds invariant.** After *every* op, each cell satisfies `c + colspan <= width` and
`r + rowspan <= height`. This is separate from the `MAX_COLS`/`MAX_ROWS` caps: clamping a
rowspan to 50 does not stop it overflowing a 6-row grid. It matters concretely because
the data rows and the injected `tr[data-control-row]` share one `<table>` — an
overflowing rowspan shoves the control strip sideways and misaligns every handle.
`deleteRow` on the last row is the op that most easily produces this, so it clamps to the
new height rather than only shrinking straddling spans.

### Round-trip fidelity (must land before any UI)

- `_edit_table.html` / `_edit_filltable.html` emit `colspan` / `rowspan` on editor cells
  and render a cell carrying `header: true` as `<th contenteditable="true">` with the
  same `data-halign` / `data-valign` / `class` / kind attributes a `<td>` would get. The
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

  A source-level test asserts no `td`-only cell selector remains in either file, so a
  future edit cannot silently reintroduce one.

### Render templates: the `<th>` gap (in scope, slice 1)

`tableelement.html` and `filltableelement.html` emit `colspan`/`rowspan` on the
`cell.header` branch and on the plain `<td>` branch — but **not** on the `<th>` branches
driven by the `header_row` / `header_col` toggles. So a merge in row 0 of a header-row
table stores a span that the student render silently drops.

This is not hypothetical: `250_pole_trojkata` — the fill-table this work exists to
unblock — has `header_row: True`, and merging in its first row is an obvious author
action. Both templates must emit `colspan`/`rowspan` on **every** `<th>` branch, with a
partial-render test for a `header_row` table whose row-0 cell spans.

### Server-side (one line, in scope)

`TableElement._span` clamps **both** keys to `MAX_COLS` (20). Now that the editor can
author a rowspan, `rowspan` clamps to `MAX_ROWS` (50) instead. Own test.

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

**Accepted, deliberately:** structural enforcement lives only in JS. `normalize_data`'s
spanning branch caps neither row count nor layout width, so a crafted or stale POST could
store an over-wide grid. This is the same trust boundary as today's cell counts (the
rectangular editor's `MAX_ROWS`/`MAX_COLS` are equally client-side), the data is
author-only behind a course-scoped permission check, and the failure mode is a table that
renders badly for one course — not a security or integrity issue. Adding server-side
clamps would mean changing `normalize_data`, which is a non-goal.

## Editor UX

### Selection

- Per-editor state: `focusCell`, `rangeAnchor` and `rangeEnd`.
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
- **Alt+Shift+ArrowRight / ArrowDown / ArrowLeft / ArrowUp**, `preventDefault`ed, is the
  keyboard equivalent. `Alt+Shift` is chosen because plain and `Ctrl` arrows are taken by
  caret and word movement inside `contenteditable`. Semantics, precisely: **move
  `rangeEnd` one layout slot in that direction, clamped to the grid, then re-normalise**
  (`rangeCells`) — so pressing ArrowLeft after ArrowRight *shrinks* the range back toward
  the anchor rather than extending past it, an arrow at the grid edge is a no-op, and a
  range that comes to clip a merged cell re-expands on every keystroke. With no range
  yet, the first press seeds `rangeEnd` from `focusCell`.
  ⚠️ On Windows, `Alt+Shift` is the OS keyboard-layout-switch chord — directly relevant
  for a PL/EN author — and `Alt+Arrow` is browser history navigation. Live verification
  must confirm the chord neither switches layout nor navigates; if it does, fall back to
  `Ctrl+Alt+Arrow` and update the help text to match.
- `Escape` clears the range. So does any structural edit (row/column insert or delete,
  merge, split) — the same discipline as the fill-table editor's existing
  `cellStash.clear()` on structural edits (`table_editor.js` has no stash).
- Highlight is an outline + tint in `editor.css`, styled for light **and** dark.

### Toolbar (both editors)

After a `.rte-sep`, three buttons using new monochrome `currentColor` sprite symbols in
`editor.html` (`ed-merge`, `ed-split`, `ed-header`), matching the existing
`ed-answer` / `ed-image` line style:

- **Merge** — enabled only when `canMerge` is true.
- **Split** — enabled only when `focusCell` has a colspan or rowspan > 1. No range
  needed.
- **Header cell** — a toggle mirroring the existing "Answer cell" `is-on` pattern,
  flipping `focusCell` between `<td>` and `<th>`. See below: it is *not* a plain
  attribute flip, and it is disabled for cells already covered by the header toggles.

All strings ride on `data-msg-*` attributes on the editor root (the established
convention for client-built markup that cannot call `{% trans %}`), including the
merge-confirm text.

**Accessibility:** Merge and Split get `aria-label` plus a real `disabled` attribute (not
just a class); Header cell gets `aria-pressed` reflecting its state; cells in the range
get `aria-selected` alongside `is-range`. These are stated here because the
frontend-design pass at the end reviews appearance, not semantics.

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
5. Re-point every reference: the `cellStash` entry (a `Map` keyed by the live node —
   otherwise the stashed other-kind content is silently orphaned), `focusCell`,
   `rangeAnchor`, `rangeEnd`.
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
any cell in row 0 of a `header_row` table or column 0 of a `header_col` table. Elsewhere
it is enabled and its `is-on` state is simply "this cell's tag is `TH`".

This is also why the *editor* grid does not render `header_row` / `header_col` cells as
`<th>`: if it did, `serialize()` would start writing `header: true` for cells that never
had it, breaking the byte-identity constraint for every existing header-row table.

### Grid handles

The column control strip is rebuilt from `slotMap().width` — one button pair per
**layout** column, so it lines up with a ragged grid. Row handles are unchanged.
`refreshControlState` gates on layout width/height against `MAX_COLS` / `MAX_ROWS`.

### Merge

The top-left cell of the normalised range gains the covering colspan/rowspan; every
other cell in the range is removed from its row. Top-left keeps its content, its kind
(static / answer / image), its alignment and its header flag.

A single `confirm()` fires when any absorbed cell is non-empty, where **non-empty**
means: static HTML that is not blank, **or any answer cell, or any image cell**. Cancel
leaves the grid untouched. This is what satisfies the constraint that a merge never
silently loses an accepted answer or an image `media` pk.

The message is deliberately **count-free** — "Merging will discard the content of the
other selected cells." A count-bearing string would need `ngettext`, and Polish has three
plural forms, which a single `data-msg-*` attribute filled by `{% trans %}` cannot
express. Not worth `{% blocktrans count %}` plus JS plural selection for a confirm
dialog.

### Split

The anchor's spans are removed and the freed slots return as **each editor's default
empty cell** (`grid.makeCell`) — a plain contenteditable cell for `TableElement`, which
has no cell kinds, and a static cell for the fill-table — inserted at the correct
position in each affected row (for a rowspan, into rows the anchor no longer covers).
Discarded content is not resurrected.

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
the keyboard equivalent, the Merge / Split / Header cell buttons, and the fact that
merging keeps only the top-left cell's content.

No new screenshots: the existing help images are page-level editor overviews
(`content-editor.en.png`), not element-toolbar close-ups, so they do not go stale.
Per project convention, any msgid removed from a `.po` must be deleted, not left
obsolete — these are additions only, but the i18n catalog tests still run.

## Testing

0. **The headline data-loss test, first.** The stated motivation is that saving a
   spanning table *untouched* strips its spans, so that is the falsifying RED test for
   slice 1: load a spanning fixture, open the editor, save with **zero** edits, assert
   `normalize_data(before) == normalize_data(after)`. Run for both a spanning `table` and
   a spanning `fill_table`, each fixture carrying a `header: true` cell **and** a rowspan
   (48 `header: true` cells exist across the corpus, so this is not a corner case).
1. **Python partial-render + model tests** (default run, no browser):
   editor templates emit `colspan` / `rowspan` and `<th contenteditable>` for a spanning
   instance; **render** templates emit spans on the `header_row` / `header_col` `<th>`
   branches; a plain table's editor markup is unchanged; `_span` clamps `rowspan` to
   `MAX_ROWS`; the source-level check that no `td`-only cell selector remains.
2. **Grid-algebra tests for `table_grid.js`.** Its functions are pure, so they run in a
   headless page via `add_script_tag` + `evaluate` — grid in, grid out — marked `e2e`
   (there is no Node in CI; the e2e job has browsers). Explicitly: these are
   pure-function tests, **not** a stand-in for gesture tests. The real-UI convention
   governs everything in (3). Because these are `e2e`-marked, the default
   `-m "not e2e"` command never runs them — so slice 2's TDD loop uses
   `DATABASE_URL=… uv run pytest -m e2e -k table_grid` as its RED/GREEN command. Coverage
   includes the bounds invariant (`deleteRow` of the final row under an overflowing
   rowspan) and the degenerate-input policy.
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
   its `cellStash` entry; the toggle is disabled on a `header_row` table's row 0.

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

1. **Round-trip fidelity** — editor templates emit spans + `header`/`<th>`; both
   `serialize()`s read them back; every `td`-scoped selector accepts `th`; the **render**
   templates emit spans on their `header_row`/`header_col` `<th>` branches; `_span`
   rowspan clamp. *This alone stops the silent span-stripping data loss.*
2. **`table_grid.js`** — slot map + span-aware insert/delete/merge/split; both editors'
   column strips switch to layout columns.
3. **`table_editor.js`** — selection, Merge / Split / Header cell toolbar.
4. **`filltable_editor.js`** — the same, plus kind preservation and the confirm rules.
5. **Help pages x4**, then live verification on u/432, then the **frontend-design**
   pass over the new buttons, icons and range highlight (screenshot light + dark and
   self-critique before shipping).
