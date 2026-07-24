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
`colspan`/`rowspan`/`header` on cells). These are provably spanning, not merely ragged:
`normalize_data` rectangularises a *non*-spanning table on save (padding, never truncating), so a
**stored** ragged table must carry `colspan`/`rowspan` — raggedness cannot survive save otherwise. Any
course export that contains a spanning table is currently un-importable. This feature makes spanning tables a first-class, round-trippable transfer payload so
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
- **Validator mirrors the model (lenient).** The validator accepts any layout and cell shape the
  model's `normalize_data` would preserve or coerce: it rejects only genuine structural corruption
  (non-dict cell, unknown cell key, present-but-wrong-type `html`, out-of-enum alignment) and enforces
  `MAX_ROWS`/`MAX_COLS` on the span-aware geometry. It does **not** reject bogus *optional* values
  (`header`/`colspan`/`rowspan` of the wrong type) — the model coerces those (`_span` treats a
  bool/non-int/≤1 span as absent; `_cell` normalizes any truthy `header` to `True`) — and does **not**
  enforce a perfect rectangular tiling (no gaps/overlaps). These tables already render in the source
  course; being stricter than the model would risk rejecting real content.

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

Restructured into a shared prefix, a **unified per-cell shape check applied to every cell in both
branches**, and a two-way branch that differs **only in geometry**. Separating cell-shape from geometry
is deliberate: the per-cell `header` key is orthogonal to spanning — `normalize_data`'s spanning
detector keys only on `colspan`/`rowspan`, while `_cell` emits `header: True` for any header cell
whether or not it spans — so a rectangular, non-spanning table can legitimately carry `header` cells.
Gating optional-key acceptance on spanning (the naive design) would wrongly reject those.

- **Shared prefix (unchanged):** `_exact_keys(data, ["header_row","header_col","border","cells"])`,
  the two `check_bool`s, the border-enum check, `rows = check_list(data["cells"], ...)`, and the
  `len(rows) > MAX_ROWS` check. Per-row cell counts (`widths`) are still gathered here, because the
  emptiness guard depends on them.
- **Emptiness guard (unchanged):** reject when there are no rows or every row is empty
  (`widths == {0}`).
- **Spanning detection:** `spanning = any(TableElement._span(c, "colspan") is not None or
  TableElement._span(c, "rowspan") is not None for row in rows for c in row if isinstance(c, dict))`.
  The explicit `isinstance(c, dict)` filter is **mandatory** and mirrors the model exactly: `_span`
  calls `raw.get(key)` and would raise `AttributeError` (→ 500, violating the module's
  no-raw-exceptions-on-hostile-input contract) on a non-dict cell otherwise.
- **Unified per-cell check (both branches), mirroring the model's leniency.** For each cell:
  - reject if not a dict;
  - reject if it carries any key outside `{html, halign, valign, header, colspan, rowspan}` — an
    allowed-keys/no-extra-keys check, hand-rolled, **not** `_exact_keys` (which enforces *presence of
    all listed keys* and would wrongly require header/colspan/rowspan on every cell);
  - `html`: if present, must be a str (reject non-str); **absent is tolerated** — the model defaults
    it to `""`;
  - `halign` / `valign`: if present, must be in `HALIGN` / `VALIGN` (reject out-of-enum); absent is
    tolerated (model defaults to `left`/`top`);
  - `header`, `colspan`, `rowspan`: optional and **not value-checked** — the model coerces them, so
    rejecting a bogus optional value would be stricter than the model and contradict the
    mirror-the-model decision. Access every key via `.get` so an absent key never raises `KeyError`.

  This rejects only genuine structural corruption (non-dict cell, unknown key, present-but-wrong-type
  `html`, out-of-enum alignment) and never a value the model would silently normalize.
- **Geometry — the only branch difference:**
  - **Non-spanning** (no cell spans): keep the existing uniform-width rejection (`if len(widths) != 1`)
    and `n_cols > MAX_COLS` check. Ordinary rectangular tables validate exactly as before.
  - **Spanning:** accept ragged rows; compute the span-aware grid width with
    `TableElement.layout_dims(rows)` and reject when `width > MAX_COLS`. Row *count* is bounded by the
    shared `MAX_ROWS` check; a `rowspan` that extends the occupied grid past `len(rows)` is left
    unclamped, **matching the model** (which clamps each span per-axis via `_span` but does not bound
    total occupied height) — the implementer must not add a spurious height guard.

Returns `set()` (a table references no media), unchanged.

**Relationship to today's non-spanning behavior.** The unified cell check is slightly *more permissive*
than today's `_exact_keys(cell, ["html","halign","valign"])`: it additionally allows the optional
`header`/`colspan`/`rowspan` keys and tolerates an absent core key — both of which the model already
normalizes. It never *newly rejects* a cell that validates today, so no table that currently imports
stops importing; it only stops rejecting content the model would have accepted. Geometry validation for
non-spanning tables is unchanged.

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
  → _build_table → TableElement.normalize_data → save()→_sanitized_data  [preserves ragged + spans]
  → TableElement.data  ≡  saved source's data   [round-trip preserves spans/header/ragged shape]

FillTableElement image cell with a span
  → export: _ser_fill_table  [NEW: carries header/colspan/rowspan]
  → _val_fill_table (lenient, unchanged) → _build_fill_table → normalize_data  [preserved]
```

The invariant the tests assert: for a spanning table **that was saved through the model**, the imported
element's `data` equals the source's stored `data` — equivalently `_sanitized_data(normalize_data(
source))`, since import applies `normalize_data` then `save()`→`_sanitized_data`. Spans, header flags,
and ragged shape are all preserved. Asserting against a *saved* (already normalized + sanitized) source
keeps the test from accidentally depending on sanitize-stable fixtures.

## Error handling

- **Over-cap spanning layout** (e.g. colspans summing beyond `MAX_COLS`): rejected by the
  `layout_dims` width check with the existing "at most N columns" error. Height beyond `MAX_ROWS` is
  caught by the shared prefix.
- **Corrupt cell** (non-dict cell, an unknown extra key, a present-but-non-str `html`, or an
  out-of-enum `halign`/`valign`): rejected with a clear per-element error, same `_err` machinery as the
  rest of the validator. A bogus *optional* value (`header`/`colspan`/`rowspan` of the wrong type) is
  **not** rejected — the model coerces it — so the validator stays no stricter than the model on
  optional keys.
- **Non-spanning tables:** geometry validation is unchanged — ragged non-spanning tables are still
  rejected. The unified cell check is slightly more permissive (allows `header`, tolerates absent core
  keys — both matching the model) but never *newly rejects* a cell that validates today, so no
  currently-importable table stops importing.
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

1. **Round-trip byte-identity (core):** construct and **save** a spanning `TableElement` (a cell with
   `colspan`, a cell with `rowspan`, a `header` cell, genuinely ragged rows) → export → validate →
   import; assert the imported `data` equals the source's *stored* `data` (spans, header, ragged shape
   all intact). Asserting against the saved source avoids depending on sanitize-stable fixtures.
2. **Rectangular header, no spans (falsifies C1):** a non-spanning, uniform-width `TableElement` whose
   only optional key is a per-cell `header: True` round-trips through export → validate → import. This
   is the case the spanning-vs-non-spanning split must not regress — it exercises the unified cell check
   on the *non-spanning* branch, and fails before the fix (today's `_exact_keys` rejects the `header`
   key).
3. **Fill-table image-span round-trip:** a `FillTableElement` with a spanning **image** cell survives
   export with its `header`/`colspan`/`rowspan` keys intact (falsifies the `_ser_fill_table` fix — RED
   before, GREEN after).
4. **Validator falsification, per guard:** a distinct failing case for each new/kept guard —
   over-`MAX_COLS` span layout rejected; non-dict cell rejected (with no raw exception); unknown extra
   cell key rejected; present-but-non-str `html` rejected; out-of-enum `halign`/`valign` rejected. Plus
   two *acceptance* cases proving the mirror-the-model leniency: a cell with a bogus optional value
   (e.g. `colspan: 0`) is accepted, and a cell omitting a core key is accepted.
5. **Non-spanning regression:** a non-spanning ragged table is still rejected, and a normal rectangular
   table still validates. Existing table transfer tests remain green.
6. **Version bump:** the export bundle now declares `format_version = 5`; the version-assertion
   test(s) are updated and pass.
7. **Real-content fixture:** a fixture mirroring the shape of the failing matematyka `e89` table
   (confirmed to carry actual `colspan`/`rowspan`, not merely ragged) validates and round-trips.

**Real end-to-end proof (out-of-band, not part of this plan's automated tests):** after merge, re-run
the local migration dry-run (`migrate_course_content export` against `libli_mat` → `import --dry-run`
against `mat-pp`) and confirm all 21 parts validate. This requires the two local databases and the
worktree media, so it is performed manually rather than in the CI/test suite.
