# Transfer spanning tables

## Purpose

Native colspan/rowspan **spanning tables** cannot round-trip through the course transfer engine
(export → archive → import). The `TableElement` / `FillTableElement` models, the render templates, and
the LAL loader all support spanning cells, but the transfer engine's payload **validator**
(`courses/transfer/payloads.py::_val_table`) predates that work and rejects spanning tables. This
blocks the matematyka → `mat-pp` course migration: a dry-run of the migration (`migrate_course_content
import --dry-run`) fails on the very first part with

```
Element 'e89': all table rows must have the same number of cells.
```

Concretely, the source course holds **16 spanning `TableElement`s** (ragged rows carrying
`colspan`/`rowspan`/`header` on cells). Any course export that contains a spanning table is currently
un-importable. This feature makes spanning tables a first-class, round-trippable transfer payload so
the migration — and any future export/import of spanning-table content — succeeds without data loss.

### Why the validator is the whole problem

The rest of the pipeline is already spanning-correct:

- **Export** `_ser_table` returns `dict(el.data)` **verbatim**, so colspan/rowspan/header keys and
  ragged rows are already serialized faithfully.
- **Import** `_build_table` calls `TableElement.normalize_data(data)`, whose spanning branch keeps
  ragged rows verbatim (rectangularising would inject phantom cells and break the browser layout), then
  `save()` sanitises each cell's HTML. These tables were *created* through this same model path, so it
  demonstrably accepts them.

Only `_val_table`, which runs between deserialization and `_build_table`, rejects them — two ways:

1. `_exact_keys(cell, ["html", "halign", "valign"])` — spanning cells legitimately carry the extra
   optional keys `colspan`, `rowspan`, `header`.
2. A uniform-width check (`if len(widths) != 1`) — spanning tables are deliberately **ragged**.

There is one secondary, latent gap: `_ser_fill_table` rebuilds **image** cells with only
`{kind, media, alt, halign, valign}`, silently dropping any `colspan`/`rowspan`/`header` on an image
cell. (Static and answer cells are copied via `dict(c)` and already survive.) `_val_fill_table` is
already lenient — it does no exact-keys or width checks — so fill-table *validation* is not a blocker,
but the serializer gap is a correctness fix that belongs with this work.

## Scope and decisions

**In scope**

- Make `_val_table` accept spanning tables (the core fix).
- Carry `header`/`colspan`/`rowspan` through image cells in `_ser_fill_table`.
- Bump the transfer `FORMAT_VERSION` 4 → 5 and update version-assertion tests.

**Two settled design decisions**

- **FORMAT_VERSION bump 4 → 5.** Matches the codebase convention (iframe width/height, GeoGebra, tabs
  all bumped for schema additions). A bundle that predates this fix cannot import span-carrying content
  anyway; bumping makes a not-yet-upgraded instance reject a v5 bundle cleanly via the version gate
  (`if version > FORMAT_VERSION: reject`) rather than emit a confusing per-element validation error.
- **Validator mirrors the model (lenient).** The spanning branch accepts any layout the model's
  `normalize_data` preserves — it type-checks cells and enforces `MAX_ROWS`/`MAX_COLS` on the
  span-aware geometry, but does **not** enforce a perfect rectangular tiling (no gaps/overlaps). These
  tables already render in the source course; enforcing tiling the model itself does not enforce would
  risk rejecting real content.

**Out of scope**

- The WYSIWYG editor cell-merge/split UI (a separate roadmap item).
- Any change to the model's spanning semantics (`_span`, `_cell`, `layout_dims`, `normalize_data`).
- The production migration cutover itself (user-reserved).

## Architecture and components

All changes live under `courses/transfer/`. The model is the single source of truth for spanning
geometry and cell shape; the validator is realigned to defer to it rather than re-deriving stricter
rules.

**Cell schema (authoritative, from `TableElement._cell`).** A normalized table cell has exactly:

- `html` (str), `halign` (∈ `HALIGN`), `valign` (∈ `VALIGN`) — always present;
- `header` (`True`) — optional, present only for a `<th>` cell;
- `colspan`, `rowspan` (int > 1, ≤ axis cap) — optional, present only when the cell spans.

`TableElement._span(raw, key)` is the canonical span reader (positive int > 1, else absent);
`TableElement.layout_dims(cells)` is the canonical span-aware `(width, height)` (identical to
`table_grid.js`'s `slotMap()`). The validator will **reuse both** — `TableElement` is already imported
in `payloads.py` for `MAX_ROWS`/`BORDERS`/etc. — so validator and model can never disagree.

### Component 1 — `payloads.py::_val_table` (core change)

Restructured into a shared prefix plus a two-way branch on whether the table spans:

- **Shared prefix (unchanged):** `_exact_keys(data, ["header_row","header_col","border","cells"])`,
  the two `check_bool`s, the border-enum check, `rows = check_list(data["cells"], ...)`, the
  `len(rows) > MAX_ROWS` check, and the "at least one cell" emptiness check.
- **Spanning detection:** `spanning = any(TableElement._span(cell, "colspan") is not None or
  TableElement._span(cell, "rowspan") is not None ...)` over dict cells — the exact predicate
  `normalize_data` uses.
- **Non-spanning branch (unchanged behavior):** keep the existing `if len(widths) != 1` uniform-width
  rejection, the `n_cols > MAX_COLS` check, and the per-cell `_exact_keys(cell,
  ["html","halign","valign"])` + halign/valign enum checks. Ordinary tables validate exactly as today —
  zero regression.
- **Spanning branch (new):** accept ragged rows; validate the grid's span-aware size with
  `TableElement.layout_dims(rows)` → reject if `width > MAX_COLS` (height already bounded by the
  shared `MAX_ROWS` check). For each cell: it must be a dict; `html` must be a str; `halign`/`valign`
  must be in their enums; `header` (if present) must be boolean; `colspan`/`rowspan` (if present) must
  each be a positive int (mirroring `_span`'s type contract — reject a bool or non-int, matching the
  model treating it as absent rather than honoring a bogus span); and **no key outside**
  `{html, halign, valign, header, colspan, rowspan}` is allowed. This whitelist mirrors `_cell`'s
  output exactly, so the validator accepts precisely what a normalized spanning cell can contain.

Returns `set()` (a table references no media), unchanged.

### Component 2 — `export.py::_ser_fill_table` (latent-gap fix)

When emitting an **image** cell, carry `header`/`colspan`/`rowspan` through when present (alongside the
existing `kind`/`media`/`alt`/`halign`/`valign`), so a spanning image cell is not silently flattened on
export. Static/answer cells (via `dict(c)`) are unaffected. No change to `_val_fill_table` (already
lenient) or `_build_fill_table` (already remaps media then `normalize_data`-preserves spans).

### Component 3 — `schema.py::FORMAT_VERSION`

Bump `4 → 5`. Any test asserting the concrete version or the emitted bundle's `format_version` is
updated to 5. The importer's version gate and the export writer both read this constant, so no other
code change is needed for the bump.

## Data flow

```
TableElement.data (spanning: ragged rows, colspan/rowspan/header cells)
  → export: _ser_table  → dict(el.data)  [verbatim, already correct]
  → bundle document (format_version = 5)
  → import: deserialize
  → _val_table  [NEW: spanning branch accepts it; caps via layout_dims]
  → _build_table → TableElement.normalize_data → save()  [preserves ragged + spans]
  → TableElement.data  ≡  normalize_data(source data)   [byte-identical round-trip]

FillTableElement image cell with a span
  → export: _ser_fill_table  [NEW: carries header/colspan/rowspan]
  → _val_fill_table (lenient, unchanged) → _build_fill_table → normalize_data  [preserved]
```

The invariant the tests assert: for a spanning table, the imported element's `data` equals
`TableElement.normalize_data(source.data)` — spans, header flags, and ragged shape all preserved.

## Error handling

- **Over-cap spanning layout** (e.g. colspans summing beyond `MAX_COLS`): rejected by the
  `layout_dims` width check with the existing "at most N columns" error. Height beyond `MAX_ROWS` is
  caught by the shared prefix.
- **Corrupt spanning cell** (non-dict cell, non-str `html`, bad halign/valign enum, non-boolean
  `header`, non-positive-int span, or an unknown extra key): rejected with a clear per-element error,
  same `_err` machinery as the rest of the validator.
- **Non-spanning tables:** take the unchanged branch and fail/pass exactly as before (ragged
  non-spanning tables are still rejected — no behavior change).
- **Cross-version import:** a pre-fix (`FORMAT_VERSION = 4`) instance importing a new v5 bundle is
  rejected wholesale by the version gate with the "found N, max M" message — a clean failure, not a
  confusing table error. New code reading old (≤4) bundles is unaffected (no span keys present → the
  non-spanning branch).
- The migration command's own guards (manifest presence, media caps, `--start-at` baseline) are
  unchanged and orthogonal to this fix.

## Testing

Test-driven; each new guard is falsified (broken → confirm its test goes RED for the stated reason →
restored). Tests live alongside the existing transfer tests (e.g. `tests/` transfer payload/round-trip
suites).

1. **Round-trip byte-identity (core):** construct a spanning `TableElement` (a cell with `colspan`, a
   cell with `rowspan`, a `header` cell, genuinely ragged rows) → export → validate → import; assert
   the imported `data` equals `TableElement.normalize_data(source.data)` (spans, header, ragged shape
   all intact).
2. **Fill-table image-span round-trip:** a `FillTableElement` with a spanning **image** cell survives
   export with its span keys (falsifies the `_ser_fill_table` fix — RED before, GREEN after).
3. **Validator falsification (spanning branch):** an over-`MAX_COLS` span layout is rejected; a
   corrupt spanning cell (bad type / unknown key) is rejected; each with the expected error.
4. **Non-spanning regression:** a non-spanning ragged table is still rejected, and a normal
   rectangular table still validates — proving the non-spanning branch is unchanged. Existing table
   transfer tests remain green.
5. **Version bump:** the export bundle now declares `format_version = 5`; the version-assertion
   test(s) are updated and pass.
6. **Real-content fixture:** a fixture mirroring the shape of the failing matematyka `e89` table
   validates and round-trips.

**Real end-to-end proof (out-of-band, not part of this plan's automated tests):** after merge, re-run
the local migration dry-run (`migrate_course_content export` against `libli_mat` → `import --dry-run`
against `mat-pp`) and confirm all 21 parts validate. This requires the two local databases and the
worktree media, so it is performed manually rather than in the CI/test suite.
