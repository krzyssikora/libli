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
- Changing `normalize_data`, the render templates, the parser, or the loader. They
  already handle spans.
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
no knowledge of cell kinds, toolbars, serialization or the hidden field. Loaded in
`templates/courses/manage/editor/editor.html` **before** both editor scripts.

| Function | Contract |
|---|---|
| `slotMap(rows)` | Standard HTML table cell-mapping: `{ map, width, height }` where `map[r][c]` is the `<td>`/`<th>` occupying that layout slot (or `null`), accounting for colspan and rowspan. The primitive everything else builds on. |
| `layoutWidth(rows)` | Layout column count. Replaces `colCount()`, which reads row 0's **cell** count and is wrong once a span exists. |
| `insertColumn(rows, layoutCol)` | Insert a layout column at `layoutCol`; straddling colspans grow by 1. |
| `deleteColumn(rows, layoutCol)` | Delete a layout column; straddling colspans shrink by 1; an anchor in that column moves right; a cell whose last covered column goes is removed. |
| `insertRow(rows, afterIdx, makeCell)` | Insert a row; straddling rowspans grow by 1; only uncovered slots get real new cells (via the caller's `makeCell`, so each editor supplies its own default cell kind). |
| `deleteRow(rows, idx)` | Transpose of `deleteColumn`. |
| `rangeCells(rows, a, b)` | The rectangle between two cells, **normalised**: expanded until it contains every partially-clipped merged cell whole, so a range is always a legal rectangle. Returns `{ cells, anchor, r0, c0, r1, c1 }`. |
| `canMerge(rows, a, b)` | True when the normalised range covers ≥ 2 cells. |
| `merge(rows, a, b)` | Top-left gains the covering colspan/rowspan; every other cell in the range is removed from its row. |
| `split(rows, cell, makeCell)` | Remove the cell's spans; re-insert empty cells (via `makeCell`) into the correct position in each freed row. |

`makeCell` is a caller-supplied factory so `table_grid.js` stays kind-agnostic:
`table_editor.js` passes its `newCell()`, `filltable_editor.js` passes its own (which
produces a static cell).

### Round-trip fidelity (must land before any UI)

- `_edit_table.html` / `_edit_filltable.html` emit `colspan` / `rowspan` on editor cells
  and render a `header` cell as `<th>`, so the browser lays the *editing* grid out
  exactly as the student sees it.
- Both `serialize()`s read `td.colSpan` / `td.rowSpan` back, emitting the key **only
  when > 1**, and emit `header: true` only for `<th>` cells.
- **Kind-agnostic cell selectors.** `dataCells()` is `td[contenteditable]`
  (table) and `td:not([data-control])` (filltable). Once a cell can be a `<th>`, both
  become `td:not([data-control]), th` — otherwise a header cell vanishes from counting,
  insert, delete and serialization.

### Server-side (one line, in scope)

`TableElement._span` clamps **both** keys to `MAX_COLS` (20). Now that the editor can
author a rowspan, `rowspan` clamps to `MAX_ROWS` (50) instead. Own test.

`normalize_data` is otherwise untouched, and stays permissive about an inconsistent
ragged grid (renders oddly, never raises). The editor is what guarantees consistency.

## Editor UX

### Selection

- Per-editor state: `rangeAnchor` and `rangeEnd`.
- A plain click / focus in a cell sets the anchor and clears the range. Today's caret,
  B/I/U and math-insert behaviour is untouched.
- **Shift+click** sets the range end. `mousedown` with `shiftKey` inside the grid is
  `preventDefault`ed so `contenteditable` does not start a text selection; the `click`
  handler computes `rangeCells` and marks each covered cell `is-range`.
- **Alt+Shift+ArrowRight / ArrowDown / ArrowLeft / ArrowUp** extends the range by one
  layout column/row from the focused cell, `preventDefault`ed. `Alt+Shift` is chosen
  because plain and `Ctrl` arrows are taken by caret and word movement inside
  `contenteditable`.
- `Escape` clears the range. So does any structural edit (row/column insert or delete,
  merge, split) — the same discipline as the existing `cellStash.clear()`.
- Highlight is an outline + tint in `editor.css`, styled for light **and** dark.

### Toolbar (both editors)

After a `.rte-sep`, three buttons using new monochrome `currentColor` sprite symbols in
`editor.html` (`ed-merge`, `ed-split`, `ed-header`), matching the existing
`ed-answer` / `ed-image` line style:

- **Merge** — enabled only when `canMerge` is true.
- **Split** — enabled only when the focused cell has a colspan or rowspan > 1. No range
  needed.
- **Header cell** — a toggle mirroring the existing "Answer cell" `is-on` pattern,
  flipping the focused cell between `<td>` and `<th>`.

All strings ride on `data-msg-*` attributes on the editor root (the established
convention for client-built markup that cannot call `{% trans %}`), including the
merge-confirm text.

### Grid handles

The column control strip is rebuilt from `slotMap().width` — one button pair per
**layout** column, so it lines up with a ragged grid. Row handles are unchanged.
`refreshControlState` gates on layout width/height against `MAX_COLS` / `MAX_ROWS`.

### Merge

The top-left cell of the normalised range gains the covering colspan/rowspan; every
other cell in the range is removed from its row. Top-left keeps its content, its kind
(static / answer / image), its alignment and its header flag.

A single `confirm()` fires — naming the count — when any absorbed cell is non-empty,
where **non-empty** means: static HTML that is not blank, **or any answer cell, or any
image cell**. Cancel leaves the grid untouched. This is what satisfies the constraint
that a merge never silently loses an accepted answer or an image `media` pk.

### Split

The anchor's spans are removed and the freed slots return as **empty static** cells,
inserted at the correct position in each affected row (for a rowspan, into rows the
anchor no longer covers). Discarded content is not resurrected.

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

1. **Python partial-render + model tests** (default run, no browser):
   templates emit `colspan` / `rowspan` and `<th>` for a spanning instance; a plain
   table's editor markup is unchanged; `_span` clamps `rowspan` to `MAX_ROWS`.
2. **Grid-algebra tests for `table_grid.js`.** Its functions are pure, so they run in a
   headless page via `add_script_tag` + `evaluate` — grid in, grid out — marked `e2e`
   (there is no Node in CI; the e2e job has browsers). Explicitly: these are
   pure-function tests, **not** a stand-in for gesture tests. The real-UI convention
   governs everything in (3).
3. **Real-gesture e2e in both editors** (clicks and keystrokes, no `page.evaluate`
   shortcuts): Shift+click a range → Merge → Save → reopen → the span survived; Split
   restores empty cells; `Alt+Shift+Arrow` builds a range; a column insert through a
   colspan widens it; a fill-table merge over an answer cell shows the confirm; an image
   cell round-trips.
4. **Regression:** a plain 2x2 saved through the editor still serializes with no
   `colspan` / `rowspan` / `header` keys.

Every slice is TDD: a falsifying RED test first (memory: *falsify tests, don't run
them*). Run pytest **without** forcing `DJANGO_SETTINGS_MODULE`:
`DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e"`,
and never pipe it through `tail` (the harness reports the pipe's exit code).

## Verification on real data

With the worktree `.env` DEBUG server on `libli_mat`
(`uv run python manage.py runserver 127.0.0.1:8000`, pilot / pilot-pass-123):

- Open u/432's fill-table editor. Confirm the two `colspan=3` explanation rows render
  aligned and the column strip matches the layout width. Screenshot light + dark.
- Exercise merge, split, `Alt+Shift+Arrow` and a span-crossing column insert live.
- Leave the stored element unchanged. Destructive experiments happen on a throwaway
  element that is created and deleted.
- No reseed, no reload, no course rebuild (the user is concurrently renaming nodes).

## Slices

Dependency order; each independently reviewable.

1. **Round-trip fidelity** — templates emit spans + `header`/`<th>`; both `serialize()`s
   read them back; kind-agnostic `dataCells()`; `_span` rowspan clamp. *This alone stops
   the silent span-stripping data loss.*
2. **`table_grid.js`** — slot map + span-aware insert/delete/merge/split; both editors'
   column strips switch to layout columns.
3. **`table_editor.js`** — selection, Merge / Split / Header cell toolbar.
4. **`filltable_editor.js`** — the same, plus kind preservation and the confirm rules.
5. **Help pages x4**, then live verification on u/432, then the **frontend-design**
   pass over the new buttons, icons and range highlight (screenshot light + dark and
   self-critique before shipping).
