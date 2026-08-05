# Table cell images

Slice C2 of the math-and-nesting roadmap. Slice C1 (image size presets, `#216`) is merged;
this is the next and final piece of slice C.

## Purpose

A course author can put an image inside a **`TableElement`** cell, and can choose how large it
renders. Today they cannot: the Table editor's toolbar has no image control at all
(`templates/courses/manage/editor/_edit_table.html:35` opens the toolbar; nothing in it picks
media), and `sanitize_cell` would strip an `<img>` anyway — `CELL_TAGS` in `courses/sanitize.py`
is `{strong, b, em, i, u, br, span}`.

The sibling `FillTableElement` **already has image cells** — `kind:"image"` with a `MediaAsset`
pk, an alt field, a media picker in `data-pick-mode="cell"`, and `resolve_image_cells` — shipped
via `docs/superpowers/specs/2026-07-20-filltable-image-cells-design.md`. C2 brings the same
capability to the plain Table, reusing that mechanism rather than inventing a second one, and adds
the **sizing story neither table has**.

### This is a pure authoring capability

Measured across all 835 parsed LAL files in `scripts/lal_import/out/`: **zero** images sit in a
plain-table cell. All 31 image cells in the corpus are `fill_table`, across 7 tables. There is no
import-recovery motive, no lost-content backfill, and **no migration** — `TableElement.data` is
already a `JSONField`.

The motive is direct: the author wants to place a figure in a grid cell, and cannot.

### Why sizing is not optional

A cell image without a size control is unusable, and the current fill-table behaviour proves it.

- **31 of 31** existing cell images are wider than the cell they sit in, by **2.8×–8×**.
- Across the whole 1067-image corpus (p50 intrinsic width **1192px**), **99–100%** is wider than
  any realistic cell. Downscaling is the universal case, not an edge case.

The current rule is `.filltable__img { max-width: 100%; height: auto; display: block }`
(`courses/static/courses/css/courses.css:1146`). Because `.el--table table` is `width: 100%` with
auto table layout, column widths are *content-negotiated*, so `max-width: 100%` is not a size —
it is whatever is left over. Measured in Chromium against the real rules, the **same image**
renders:

| shape (648px column) | rendered width |
|---|---|
| 2-col, image + text | 583px |
| 5-col, image + 4 short text cells | 426px |
| 5-col, image + 4 **longer** text cells | 286px |
| 5-col, all five cells images | 112px |

Lengthening text **in a neighbouring cell** shrinks the image 426→286px. The author has no
control and no repeatability.

Height is worse: a 494×1492 image (the corpus's worst aspect ratio) renders **1287px tall** in a
cell. That is exactly the defect C1 fixed for standalone images, and C1's fix does not reach here
— `.el--image--*` rules never apply to a cell image.

### Why C1's presets do not transfer

C1's four presets are percentages of the containing block. A cell's containing block is itself
content-negotiated, so a percentage compounds the instability. Measured, the same "medium = 50%"
preset across real table shapes:

| shape | `max-width: 50%` | `max-width: min(100%, 160px)` |
|---|---|---|
| 2-col img+text | 291.7px | 160.0px |
| 3-col all images | 99.3px | 160.0px |
| 5-col img+text | 213.1px | 160.0px |
| 5-col all images | 56.2px | 112.4px |
| 7-col img+text | 162.1px | 160.0px |

**5.2× spread** for the percentage versus **1.4×** for the absolute cap. A percentage of an
unstable containing block is not a comparable scale. Reusing `ImageElement.size` would also drag
`full = max-height: 100dvh` into a table cell, which is meaningless there.

## Non-goals

- **Elements nested inside a table cell.** Dropped by agreement; a cell is not an element slot.
- **Image *and* text in the same cell.** No measured demand: the fill-table parser already
  refuses to build one (`scripts/lal_import/tables.py:56,138` require no text and exactly one
  `<img>`), and works around image-plus-explanation by re-emitting the explanation as its own
  row. A cell is image **or** text.
- **Widening `CELL_TAGS` to allow a raw `<img>`.** Rejected: it stores a bare URL, losing the
  `MediaAsset` FK, and with it course-scoped export/import bundling and `on_delete=PROTECT`.
- **Any data migration or parser change.** Neither is needed (see Purpose).
- **Making the presets meaningful on a phone.** At 296px a 5-column table renders ~42px images
  whatever preset is chosen, because the cell always binds. That is geometry, not a bug;
  tap-to-enlarge already covers it (`data-zoomable` + `imagezoom.js`, already wired to cell
  images).

## Architecture / components

### Data model

`TableElement` cell shapes after this change:

```
text  (unchanged): {html, halign, valign}                            + optional header/colspan/rowspan
image (new):       {kind: "image", media, alt, size, halign, valign} + optional header/colspan/rowspan
```

**A text cell must not gain a `kind` key.** Three independent reasons:

1. The spanning-table work established that a non-spanning table serializes **byte-identically**
   (`docs/superpowers/specs/2026-07-22-spanning-table-editor-design.md`); a new key on every cell
   breaks that invariant.
2. `_val_table`'s per-cell check is an **exact allowlist** (`courses/transfer/payloads.py:616`),
   so every pre-feature archive would be rejected.
3. The first save of any existing table would rewrite all **7,118** corpus cells.

So `kind` appears **only** on image cells — the same "present only when set" pattern that
`header`, `colspan` and `rowspan` already use in `TableElement._cell`.

This deliberately **differs** from `FillTableElement`, where every cell carries a `kind`
(`static`/`answer`/`image`). That is its own established convention and does not change; the
fill-table only gains the new `size` key on its image cells. The divergence is intentional and
must not be "unified".

`size` is stored **per cell**, not per table: a row of five graphs beside one large diagram is a
real shape a per-table setting could not express.

### The size scale

Four presets named **Small / Medium / Large / Full**, defaulting to **Full** — the same
author-facing vocabulary as C1's image element, so the author meets one concept, not two. The
*units* differ because the containing block does. Each preset is an **absolute square bounding
box**:

| preset | rule |
|---|---|
| Small | `max-width: min(100%, 80px)` · `max-height: 80px` |
| Medium | `max-width: min(100%, 160px)` · `max-height: 160px` |
| Large | `max-width: min(100%, 240px)` · `max-height: 240px` |
| **Full** (default) | `max-width: 100%` · `max-height: 60dvh` |

Three properties, each measured rather than assumed:

- **The `min(100%, …)` arm keeps the cell a hard ceiling.** Across **32** shape×treatment
  combinations, including phone at 296px, **none** produced horizontal scroll. The px arm can only
  shrink the image further than the cell already would.
- **A square box, not a width.** This is C1's proven decision and it holds here: at Medium, a
  1586×612 image lands at 160×62 and a 494×1492 one at 53×160. One preset, comparable visual
  weight, any aspect ratio.
- **Full preserves today's width**, so the 31 existing fill-table cell images render unchanged
  horizontally. The only behavioural change for them is the `60dvh` height bound — which is the
  point, since that is the 1287px defect.

`dvh` not `vh`, per C1's finding: `vh` resolves against the toolbar-collapsed viewport, so a
`vh` cap can still fall below the fold on a phone. `courses.css` already uses `100dvh` for
imagezoom.

The four size tokens live as a constant set on `TableElement` (e.g. `CELL_IMAGE_SIZES` +
`DEFAULT_CELL_IMAGE_SIZE = "full"`), shared by `FillTableElement`, both forms, both editors and
the transfer validators — one definition, no duplicated literals.

**i18n:** the msgid `"Full"` is already taken twice over. `courses/forms.py:166` uses a bare
`_("Full")` translated to the feminine `"Pełna"`, and C1 forked an image-size entry as
`pgettext_lazy("image size", "Full")` → masculine `"Pełny"`. The cell-size labels must **reuse
C1's existing `pgettext_lazy("image size", …)` entries** rather than introduce a bare `_("Full")`,
or one of the three ships ungrammatical and no test would see it.

### Rendering

Cell images render through the existing partials. The plain table's `tableelement.html` currently
emits `{{ cell.html|safe }}` on all five of its branches; it gains an image branch on each, or —
preferably — factors the cell body into a shared partial the way `filltableelement.html` already
does with `_filltable_cell.html`, so the five branches cannot drift.

The image markup mirrors the fill-table's: `<img class="…" src="{{ cell.media.file.url }}"
alt="{{ cell.alt }}" data-zoomable>` — `data-zoomable` so tap/click-to-enlarge works, which is
what makes the phone case tolerable.

CSS lives in `courses/static/courses/css/courses.css` alongside the existing `.el--table` and
`.filltable__img` rules (not `editor.css` — that is where the shared `.table-editor__grid` cell
styles live, a distinction that has already caused one misdiagnosis).

**Source order matters.** As in C1, `@media print` adds no specificity, so any print block must
follow the preset rules or every cell image prints at its `dvh` height.

### Editor UX

**Discoverability is a first-class requirement of this slice, not a nicety.** Both table editors
render `<div class="table-editor__toolbar" data-table-toolbar hidden>` and reveal it only on cell
focus (`courses/static/courses/js/table_editor.js:374`,
`courses/static/courses/js/filltable_editor.js:554`). An author opening a table sees a bare grid
and no controls, with nothing signalling that clicking a cell reveals ten buttons. This is not
hypothetical: the person who commissioned this feature could not find the fill-table's existing
Image-cell button for exactly this reason. Adding the same affordance to the Table editor in the
same place would reproduce that failure.

**Fix:** the toolbar renders **always visible**, with its buttons **disabled** until a cell is
focused. Both editors, one change. The refresh functions already do per-cell enable/disable for
`[data-cmd]`, so the mechanism exists.

**The Image-cell button** in the Table editor uses the existing delegated listener in
`media_picker.js` — `data-pick-media="image" data-pick-mode="cell"`, which calls back into the
editor via a `window.libli…PickImage` hook, exactly as `_edit_filltable.html:62-64` does. Placed
in its own group before Merge/Split/Header.

Behaviour:

- **On a text cell** → picker → convert the cell to an image cell, **stashing the prior HTML** so
  the conversion is reversible (the fill-table's per-node stash is the precedent).
- **On an image cell** → picker → replace the image.
- **Reverting to text** needs its own control: the fill-table gets this free from its Answer-cell
  toggle, which the plain Table has no equivalent of. So a **Remove image** action restores the
  stashed HTML.

**Per-cell controls**, shown only while an image cell is focused (the existing `data-image-alt`
pattern): the **alt** input, the new **size** select, and **Remove image**. The fill-table editor
gains the same size select — this is the "both tables" half of the decision.

**The editor preview must scale with the preset.** Today's `.filltable-editor__img { max-width:
120px }` (`courses.css:1147`) is a flat thumbnail that would render Small, Medium and Large
identically, leaving the author unable to see what they picked. It cannot be pixel-exact — the
editor grid is not the 648px student column — but the three bounded presets must be **visibly
different from each other**.

**Data-loss guard.** `table_grid.js`'s merge absorbs cells. The fill-table guards this with
`absorbedNonEmpty`, which counts an image cell as non-empty so a merge cannot silently discard a
`media` pk. The plain Table's equivalent check tests HTML-emptiness only and **would swallow an
image cell**. That guard must be extended as part of this work.

### Server side

**`TableElement._cell`** gains an image branch **before** the text fallback, mirroring
`FillTableElement._cell`:

- `media` must be an `int` and **not** a `bool` (the `GalleryElement._image` precedent).
- `alt` coerced to `str`.
- `size` validated against the four tokens and **coerced to the default on junk** — C1's
  precedent, where an unknown image `size` coerces (a lossless default exists) while an unknown
  callout `kind` raises (none does).
- **Invalid `media` degrades to an empty *text* cell** — `{html: "", halign, valign}` with **no**
  `kind` key, preserving the shape invariant above. Never raise, never render a broken image.

**`_sanitized_data`** (called from `save()`) currently runs `cell["html"] =
sanitize_cell(cell.get("html", ""))` unconditionally for every non-answer cell. It needs an
explicit `elif kind == "image"` branch **before** that `else`, or every saved image cell gains a
spurious `html` key.

**Shared image resolution.** `FillTableElement.resolve_image_cells` is already a `@staticmethod`
shared between the model (`resolved_cells`, student render) and the form
(`resolved_grid_cells`, editor re-render on a rejected save) — deliberately, so the two cannot
diverge on the unresolved-asset fallback. The Table needs the same logic with a **different
empty-cell shape**, so it lifts to a shared helper parameterised by that shape. It must **not** be
copied: 163 code-identical lines across these two editors are already guarded by
`tests/test_editor_twin_drift.py` precisely because duplication here has bitten before.

**Unresolved-asset fallback preserves spans.** When an image cell's asset cannot be resolved
(deleted media), the current fill-table fallback replaces it with an empty cell **and drops any
`header`/`colspan`/`rowspan` it carried**. In a spanning table that shifts every following cell in
the row and breaks the layout; **15 of the 312** tables span. The shared helper therefore
**preserves** those keys, leaving a blank spanning cell. This is a deliberate behaviour change for
the fill-table too, not an oversight — one helper, one behaviour.

**`TableElementForm.clean_data`** course-scopes the referenced media ids, mirroring the
fill-table's "A table image is not an image in this course." A `resolved_grid_cells` property
re-renders the **submitted** grid on a rejected save, and **must route through `_sanitized_data`**
— that exact path is where a self-XSS was caught during the spanning-table work (a grid that
failed validation echoed raw author HTML back through a `|safe` template).

### Transfer (export / import)

Four separate sites. **Missing any one breaks export silently** — the element round-trips but its
image does not.

| site | file | change |
|---|---|---|
| `_val_table` | `courses/transfer/payloads.py:585` | widen the per-cell `allowed` set with `kind`/`media`/`alt`/`size` (backward compatible — old archives simply lack them); validate the new fields; return media refs via `_require_media` |
| `_ser_table` | `courses/transfer/export.py` | currently `return dict(el.data)`; must register each image cell's asset so the bundle carries the file, following `_ser_fill_table:177` |
| `_element_mids` | `courses/transfer/export.py:433` | routes **by type key**; `table` currently falls through to the scalar `data.get("media")` and returns nothing — without a `table` branch the file is omitted from the zip and import then `KeyError`s |
| `_build_table` | `courses/transfer/importer.py:585` | remap each image cell's local string id → the real asset pk, as `_build_fill_table:593` does |

`FORMAT_VERSION` **7 → 8**.

## Data flow

**Authoring.** Author focuses a cell → toolbar buttons enable → clicks Image cell →
`media_picker.js` opens the modal in `cell` mode → author picks/uploads an asset → the picker
callback converts the focused cell (stashing prior HTML), writes `data-media`/`data-alt`/
`data-size` and renders a preview `<img>` → per-cell controls (alt, size, Remove image) appear →
the editor's `serialize()` writes the grid JSON into the hidden `data` input → submit.

**Save.** `TableElementForm.clean_data` → `normalize_data` (coercion, `_cell` per cell) →
course-scoping check on referenced ids → `save()` → `_sanitized_data` (image cells skipped, text
cells sanitised) → JSON stored.

**Rejected save.** The submitted grid re-renders via `resolved_grid_cells` → shared resolver with
`course=` scoping (so a foreign or wrong-kind pk resolves to nothing and takes the fallback) →
routed through `_sanitized_data` before any `|safe` output.

**Student render.** `resolved_cells` → shared resolver (one `in_bulk` pass) → pk replaced by
`MediaAsset`, unresolved → blank cell **retaining spans** → template emits `<img …
data-zoomable>` → CSS preset bounds it → `imagezoom.js` handles enlarge.

**Export.** `_element_mids` collects the cell media ids → assets bundled → `_ser_table` emits
cells with local asset ids. **Import.** `_val_table` validates and returns refs → `_build_table`
remaps local ids → pk → `normalize_data` + `save()`.

## Error handling

Every degradation is **silent and lossless-leaning**, never a 500 and never a broken image:

| condition | behaviour |
|---|---|
| `media` missing / non-int / `bool` | cell degrades to an empty **text** cell (no `kind` key) |
| `size` unknown or non-string | coerced to `full` (a lossless default exists) |
| `alt` non-string | coerced to `""` |
| asset pk does not resolve at render | blank cell, **spans preserved** |
| asset belongs to another course, or is not `kind="image"` | fails to resolve → same blank-cell path; the form rejects it at save with a field error |
| unknown cell key in an imported archive | `_val_table` rejects (exact allowlist, unchanged behaviour) |
| merge would absorb an image cell | blocked by the extended `absorbedNonEmpty` guard |

`_table_has_math` reads `cell.get("html", "")` (`courses/views.py:135`), so an image cell with no
`html` key cannot raise there — **verified, no change needed**.

## Testing

Each claim is owned by the **cheapest layer that can see it**. Every test names a specific mutant
and must be shown RED before it counts.

| layer | owns |
|---|---|
| Model unit | `_cell` image branch; junk-`size` coercion; invalid-media degradation to a `kind`-less text cell; span preservation in the shared resolver; `_sanitized_data` writing no `html` key on an image cell; text cells still normalising byte-identically |
| Form | course-scoping rejection (foreign course, wrong media kind); rejected-save re-render routed through `_sanitized_data` |
| Transfer | all four sites; round-trip with a real asset; a pre-feature archive still imports; `FORMAT_VERSION` bump |
| Template | image cell emits `<img>` + `data-zoomable`; text-cell output unchanged |
| CSS / partial regression | every `table-editor__*` class the JS emits is styled (`tests/test_table_css.py` exists because that drift was a real shipped bug — the +/− handles were unstyled and permanently visible); every `#ed-*` reference resolves to a defined sprite symbol (icon-only buttons fail blank) |
| e2e | the sizing actually renders |

**The sizing claims are only real if measured in a browser.** C1's harness traps transfer
verbatim and must be honoured:

- **Caps only shrink**, so a bounding-box assertion needs `min(hcap, wcap/ratio,
  naturalHeight)` — without the intrinsic clamp the *correct* build fails.
- **`getComputedStyle().width` is the border box** (`reset.css` sets `box-sizing: border-box`
  globally). Measure the wrapper, never a padded container.
- **`_isolated_media` is mandatory, not hygiene** — `live_server`'s `_MediaFilesHandler` reads
  `MEDIA_ROOT` per request, so it is what makes `/media/<path>` resolve at all. Pair it with an
  await-decoded step: an undecoded `<img>` legitimately reports `naturalWidth` 0.
- **A request recorder must filter on the URL path**, never the Django URL *name* — a
  name-filtered recorder matches nothing and the assertion is vacuous.
- **`_seed_unit` mints a fresh Course**, and `MediaAsset` is course-scoped, so a seeded element
  cannot reference another course's asset.
- The **editor and preview panes are siblings**, so mutating the preview pane is a no-op mutant
  that proves nothing; mutate the editor pane.

**The one genuinely new e2e assertion is stability**: lengthening text in a *neighbouring* cell
must no longer change the image's rendered width (426→286px today). Nothing below the browser
layer can observe this, and it is the defect the presets exist to fix.

**Light + dark screenshot verification belongs in the styling task's Definition of Done**, not
deferred — that deferral is exactly how the fill-table shipped its dark-mode contrast bug
(`--border-default` on a dark surface, nearly invisible). An editor page must link **both**
`courses.css` and `editor.css` to render faithfully.

## Settled decisions (do not re-litigate)

- Widen the cell subset + media picker; **not** element slots in cells.
- `kind:"image"` with a `MediaAsset` pk; **not** a raw `<img>` in the sanitised HTML.
- A cell is image **or** text, never both.
- Absolute px presets; **not** percentages, and **not** a reuse of `ImageElement.size`.
- Both tables get the scale; the unresolved-asset fallback **preserves** spans in both.
- Content column is **648px desktop / 296px phone**. The C1 spec's 880/328 is superseded; the C1
  plan carries the correct derivation. Chromium shrink-wraps `fit-content` to the constrained
  contribution — settled in C1, not to be re-derived.
