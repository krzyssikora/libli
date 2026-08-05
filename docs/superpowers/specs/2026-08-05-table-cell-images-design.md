# Table cell images

Slice C2 of the math-and-nesting roadmap. Slice C1 (image size presets, `#216`) is merged;
this is the next and final piece of slice C.

## Purpose

A course author can put an image inside a **`TableElement`** cell, and can choose how large it
renders. Today they cannot: the Table editor's toolbar has no image control at all
(`_edit_table.html`), and `sanitize_cell` would strip an `<img>` anyway — `CELL_TAGS` in
`courses/sanitize.py` is `{strong, b, em, i, u, br, span}`.

The sibling `FillTableElement` **already has image cells** — `kind:"image"` with a `MediaAsset`
pk, an alt field, a media picker in `data-pick-mode="cell"`, and `resolve_image_cells` — shipped
via `docs/superpowers/specs/2026-07-20-filltable-image-cells-design.md`. C2 brings the same
capability to the plain Table, reusing that mechanism rather than inventing a second one, and adds
the **sizing story neither table has**.

### Populations behind every figure in this spec

Three distinct populations are cited; each figure below is labelled with its own.

- **PARSED** — the 835 JSON files under `scripts/lal_import/out/` (parser output, pre-save).
- **DB** — the local `libli` database: 312 `TableElement` rows / **7,246** cells, 80
  `FillTableElement` rows / 1,450 cells, 1,068 `ImageElement` rows (1,067 with a readable file).
- **MEASURED** — Chromium/Firefox/WebKit via Playwright against the real `.el--table` rules.

### This is a pure authoring capability

**PARSED:** zero images sit in a plain-table cell across all 835 files. All 31 image cells in the
corpus are `fill_table`, across 7 tables (**DB** agrees: 31). There is no import-recovery motive,
no lost-content backfill, and **no migration** — `TableElement.data` is already a `JSONField`.

The motive is direct: the author wants to place a figure in a grid cell, and cannot.

### Why sizing is not optional

**DB:** 31 of 31 existing cell images are wider than the cell they sit in, by **2.8×–8×**. Across
the 1,067-image corpus (p50 intrinsic width **1192px**), **99–100%** is wider than any realistic
cell. Downscaling is the universal case, not an edge case.

The current rule is `.filltable__img { max-width: 100%; height: auto; display: block }`
(`courses.css`). Because `.el--table table` is `width: 100%` with auto table layout, column widths
are *content-negotiated*, so `max-width: 100%` is not a size — it is whatever is left over.
**MEASURED**, the **same image** renders:

| shape (648px column) | rendered width |
|---|---|
| 2-col, image + text | 583px |
| 5-col, image + 4 short text cells | 426px |
| 5-col, image + 4 **longer** text cells | 286px |
| 5-col, all five cells images | 112px |

Lengthening text **in a neighbouring cell** shrinks the image 426→286px. The author has no
control and no repeatability.

Height is worse: a 494×1492 image renders **1287px tall** in a cell. That is exactly the defect C1
fixed for standalone images, and C1's fix does not reach here — `.el--image--*` rules never apply
to a cell image.

### Why C1's presets do not transfer

C1's four presets are percentages of the containing block. A cell's containing block is itself
content-negotiated, so a percentage compounds the instability. **MEASURED**, the same
"medium = 50%" preset across real table shapes:

| shape | `max-width: 50%` | `max-width: min(100%, 160px)` |
|---|---|---|
| 2-col img+text | 291.7px | 160.0px |
| 3-col all images | 99.3px | 160.0px |
| 5-col img+text | 213.1px | 160.0px |
| 5-col all images | 56.2px | 112.4px |
| 7-col img+text | 162.1px | 160.0px |

**5.2× spread** for the percentage versus **1.4×** for the absolute cap. Reusing
`ImageElement.size` would also drag `full = max-height: 100dvh` into a table cell, which is
meaningless there.

## Non-goals

- **Elements nested inside a table cell.** Dropped by agreement; a cell is not an element slot.
- **Image *and* text in the same cell.** A cell is a slot: mixed content reintroduces exactly the
  content-negotiated width instability the presets exist to remove, since the text would once
  again drive the column. (The fill-table importer's refusal to build such a cell is a fact about
  the importer, not evidence of author demand — and since zero plain-table image cells exist,
  no corpus evidence about them can exist either way.)
- **Widening `CELL_TAGS` to allow a raw `<img>`.** Rejected: it stores a bare URL, losing the
  `MediaAsset` reference and with it course-scoped export/import bundling. (Note: a cell's `media`
  is a plain `int` in a `JSONField`, **not** a ForeignKey — `on_delete=PROTECT` does **not** apply
  to cell images. That is precisely why the unresolved-pk fallback below is mandatory. Only
  `ImageElement.media` is a real FK.)
- **Any data migration or parser change.** Neither is needed.
- **Making the presets meaningful on a phone.** **MEASURED:** at 296px a 5-column table renders
  ~42px images whatever preset is chosen, because the cell always binds. That is geometry, not a
  bug; tap-to-enlarge already covers it (`data-zoomable` + `imagezoom.js`).

## Architecture / components

### Data model

`TableElement` cell shapes after this change:

```
text  (unchanged): {html, halign, valign}                            + optional header/colspan/rowspan
image (new):       {kind: "image", media, alt, size, halign, valign} + optional header/colspan/rowspan
```

**A text cell must not gain a `kind` key.** Three independent reasons:

1. The spanning-table work established that a non-spanning table serializes **byte-identically**;
   a new key on every cell breaks that invariant.
2. `_val_table`'s per-cell check is an **exact allowlist** (`allowed = {...}` in `_val_table`), so
   every pre-feature archive would be rejected.
3. **DB:** the first save of any existing table would rewrite all **7,246** cells.

So `kind` appears **only** on image cells — the same "present only when set" pattern that
`header`, `colspan` and `rowspan` already use in `TableElement._cell`.

This deliberately **differs** from `FillTableElement`, where every cell carries a `kind`. That is
its own established convention and does not change; the fill-table only gains the new `size` key
on its image cells. The divergence is intentional and must not be "unified".

`size` is stored **per cell**, not per table: a row of five graphs beside one large diagram is a
real shape a per-table setting could not express.

### The size scale

Four presets named **Small / Medium / Large / Full**, the same author-facing vocabulary as C1's
image element. The *units* differ because the containing block does. Each preset is an **absolute
square bounding box**:

| preset | rule |
|---|---|
| Small | `max-width: min(100%, 80px)` · `max-height: 80px` |
| Medium | `max-width: min(100%, 160px)` · `max-height: 160px` |
| Large | `max-width: min(100%, 240px)` · `max-height: 240px` |
| Full | `max-width: 100%` · `max-height: 60dvh` |

**Two different defaults, deliberately** (this resolves the tension between back-compat and
authoring quality):

- **Stored default = `full`.** A cell with no `size` key reads as `full`, which preserves today's
  width exactly, so the 31 existing fill-table cell images render unchanged horizontally. The only
  behavioural change for them is the `60dvh` height bound — which is the point, since that is the
  1287px defect.
- **Editor-insert default = `medium`.** When the editor converts a cell to an image cell it writes
  `size="medium"` into `data-size`. A newly authored cell must not land in the unstable
  content-negotiated state the whole slice exists to fix. Full remains reachable from the select.

Properties, each **MEASURED** rather than assumed:

- **The `min(100%, …)` arm keeps the cell a hard ceiling.** Across **32** shape×treatment
  combinations, including phone at 296px, **none** produced horizontal scroll.
- **A square box, not a width.** C1's proven decision, and it holds here: at Medium, a 1586×612
  image lands at 160×62 and a 494×1492 one at 53×160. One preset, comparable visual weight, any
  aspect ratio.
- **Cross-engine agreement is measured, not assumed.** `max-width: min(100%, Npx)` on a child of
  an auto-layout table cell is a circular-resolution case where engines historically diverge.
  Chromium, Firefox and WebKit were measured on five shapes (including the narrow 296px case and
  the tall-image case) and **agree to within 1px on every one**. No cross-engine caveat is needed;
  do not re-derive this.

**Aggregate height.** The `60dvh` bound is per image, so a five-row table of tall `full` images is
still ~300dvh of scrolling. Accepted: it is strictly better than today's unbounded 1287px per
cell, the editor-insert default of `medium` keeps new content well clear of it, and a per-table
aggregate cap would need a layout mechanism no other element has.

`dvh` not `vh`, per C1: `vh` resolves against the toolbar-collapsed viewport, so a `vh` cap can
still fall below the fold on a phone.

**The tokens live in one ordered place.** Define a `TextChoices` (mirroring `ImageElement.Size`)
on `TableElement`, e.g. `CellImageSize`, plus `DEFAULT_CELL_IMAGE_SIZE = "full"` and
`EDITOR_INSERT_CELL_IMAGE_SIZE = "medium"`. A `TextChoices` gives an **ordered** sequence for the
select (Small → Medium → Large → Full) and a membership test for validation; a bare `set` would
render the select in arbitrary order. Shared by `FillTableElement`, both forms, both editors and
the transfer validators — one definition, no duplicated literals.

**i18n — the existing entries are asymmetric.** `ImageElement.Size` has exactly **one**
context-forked label: `FULL = "full", pgettext_lazy("image size", "Full")`. `SMALL`/`MEDIUM`/
`LARGE` are bare `_("Small")`/`_("Medium")`/`_("Large")`. Reuse that **same split** — bare `_()`
for the first three, `pgettext_lazy("image size", "Full")` for Full. Wrapping all four in
`pgettext_lazy` would mint three brand-new msgids that ship untranslated and invite a wrong
`makemessages` fuzzy pre-fill. The bare msgid `"Full"` is already taken by `courses/forms.py`'s
structure preset (feminine `"Pełna"`), which is why Full alone needs the context (masculine
`"Pełny"`). A source-level test pins that Full carries the `"image size"` context.

### Rendering

**`TableElement` gains a `resolved_cells` property** (the fill-table's `resolved_cells` analog),
and **`TableElement.render()` must use it** — today it passes `normalize_data(self.data)` straight
to the template, so without this change `cell.media` stays an `int` and the template emits
`src=""`. `render()` passes `{**normalize_data(self.data), "cells": self.resolved_cells}`.
`normalized_data` (used elsewhere) stays **unresolved** — resolution is a render-time concern only.

`tableelement.html` currently emits `{{ cell.html|safe }}` on all five of its branches (four of
which are `<th>`). Factor the cell body into a shared partial — the way `filltableelement.html`
already does with `_filltable_cell.html` — so the five branches cannot drift and an image in a
header row is handled once.

Image markup mirrors the fill-table's: `<img class="… <preset class>" src="{{ cell.media.file.url }}"
alt="{{ cell.alt }}" data-zoomable>`.

**`_filltable_cell.html` must also emit the preset class.** It currently emits a bare
`class="filltable__img"`. Without this change "both tables get the scale" is half-implemented and
the `60dvh` fix — the stated point of the slice for the 31 real cells — never reaches a student.

CSS lives in `courses/static/courses/css/courses.css` alongside the existing `.el--table` and
`.filltable__img` rules (not `editor.css` — that is where the shared `.table-editor__grid` cell
styles live, a distinction that has already caused one misdiagnosis).

**Source order matters.** As in C1, `@media print` adds no specificity, so any print block must
follow the preset rules or every cell image prints at its `dvh` height.

### Editor UX

**Discoverability is a first-class requirement of this slice.** Both table editors render
`<div class="table-editor__toolbar" data-table-toolbar hidden>` and reveal it only on cell focus.
An author opening a table sees a bare grid and no controls, with nothing signalling that clicking
a cell reveals ten buttons. This is not hypothetical: the person who commissioned this feature
could not find the fill-table's existing Image-cell button for exactly this reason.

**Fix:** the toolbar renders **always visible**, with cell-scoped controls **disabled** until a
cell is focused. Precisely:

- **Disabled with no focus:** every `[data-cmd]` (B/I/U, math, **and the five
  `data-cmd="colour-*"` swatches from `_rte_swatches.html`**), plus the image button and the
  per-cell image controls. Merge/split/header are already `disabled` in markup and keep their
  existing logic.
- **`[data-halign]`/`[data-valign]`** are class-toggled, never `disabled`; `refreshAlignButtons`
  must **clear their `is-on` state when `focusCell` is null**, or the toolbar shows a stale
  alignment painted from a previously-focused cell.
- **`refreshToolbarState()` must run once at init** in both editors. Without it the
  always-visible toolbar paints with B/I/U/swatches *enabled* and no focus — clicking them does
  nothing, which is precisely the "controls that appear to work but don't" failure this section
  exists to prevent.

**This is not "one change in two editors".** Only `filltable_editor.js` loops `[data-cmd]` and
sets `btn.disabled`; `table_editor.js`'s `refreshToolbarState` touches merge/split/header only and
then calls `refreshAlignButtons`, which itself returns early when `focusCell` is null. The Table
editor must **gain** the `[data-cmd]` disable loop, gated on `focusCell` being null rather than on
cell kind.

**The media picker needs a per-editor dispatch.** `media_picker.js` currently hard-codes a single
hook: `if (pick.getAttribute("data-pick-mode") === "cell" && window.libliFillTablePickImage)`.
Rendering `data-pick-mode="cell"` in `_edit_table.html` therefore does **nothing** until
`media_picker.js` changes. `media_picker.js` gains a dispatch keyed off the button's owning editor
root (`[data-table-editor]` vs `[data-filltable-editor]`), and `table_editor.js` registers its own
distinctly-named hook. **`table_editor.js` must not assign `window.libliFillTablePickImage`** —
both editor scripts load on every editor page, so a shared global means whichever runs last wins
and one editor's picker silently drives the other's callback.

**Table editor cell markup.** `_edit_table.html`'s grid loop has one
`<td contenteditable>`/`<th contenteditable>` pair and no image branch. It gains an image branch —
`<td data-image data-media data-alt data-size tabindex="0">` (and the `<th>` twin), **not**
`contenteditable` — mirroring `_edit_filltable.html`. The loop must also read
`form.resolved_grid_cells`, not `form.grid_data`, or `cell.media` stays an int.

**`serialize()` must gain a kind branch.** `table_editor.js`'s `serialize()` unconditionally emits
`{html: td.innerHTML, halign, valign}` for every cell. An image cell would serialize as
`html: "<img …>"`, which `sanitize_cell` then strips to `""` on save — **the image is lost with no
error**. The image branch emits `{kind, media, alt, size, halign, valign}` and **no** `html` key.

**Focus must reach an image cell.** `table_editor.js`'s `focusin` handler matches
`e.target.closest("td[contenteditable], th[contenteditable]")` and returns early otherwise.
`filltable_editor.js` had to widen exactly this selector to include `td[data-image], th[data-image]`
because such cells are not contenteditable. Without the same widening, clicking a Table image cell
sets neither `focusCell` nor the range anchor: the alt input, the size select and Remove image
never appear, and the cell can never be a merge/split/align target. Widen the selector **and** the
post-merge/delete focus fallback.

**Behaviour of the image button:**

- **On a text cell** → picker → convert, **stashing the prior HTML** so the conversion is
  reversible (the fill-table's per-node stash is the precedent), writing `size="medium"`.
- **On an image cell** → picker → replace the image, preserving `size` and `alt`.
- **Reverting to text** needs its own control: the fill-table gets this free from its Answer-cell
  toggle, which the plain Table has no equivalent of. A **Remove image** action restores the
  stashed HTML.

**Per-cell controls**, shown only while an image cell is focused: the **alt** input, the new
**size** select, and **Remove image**. The fill-table editor gains the same size select.

**The size select is server-rendered** in the toolbar alongside the existing `data-image-alt`
input, so its four option labels come from `{% trans %}`. JS-injected controls cannot call
`{% trans %}` — that is why `_edit_table.html` already carries ten `data-msg-*` attributes. A
hard-coded English option list in JS would ship untranslated and no test would catch it.

**The editor preview must scale with the preset.** Today's `.filltable-editor__img { max-width:
120px }` is a flat thumbnail that would render Small, Medium and Large identically, leaving the
author unable to see what they picked. It cannot be pixel-exact — the editor grid is not the 648px
student column — but the three bounded presets must be **visibly different from each other**.

**Structural operations × image cells** (only merge was previously considered):

| operation | required behaviour |
|---|---|
| Merge | An absorbed image cell blocks the merge. `cellIsNonEmpty` **already** reads `c.textContent.trim() !== "" \|\| c.querySelector("img") !== null`, so a rendered preview is already covered. Add a `hasAttribute("data-image")` clause so a cell whose preview has not yet rendered still counts, and pin it with a test. (The earlier claim that this guard was missing was **false**; the divergent function is `cellIsNonEmpty`, not `absorbedNonEmpty`, which is a listed twin.) |
| Split | The image stays in the anchor cell; newly created cells come from the existing `makeCell()` helper as ordinary text cells. |
| Header toggle / `header_row` / `header_col` | An image cell may become a `<th>`; the shared cell partial handles it, so no branch-specific work. |
| Row/column delete | No new warning — parity with text cells today. Stated so the omission is deliberate. |

**`tests/test_editor_twin_drift.py` will go red and must be updated.** It asserts a hard-coded
`EXPECTED_COUNTS = {TABLE_JS: 28, FILL_JS: 36}` and requires every function name common to both
files to be classified in exactly one of `TWINS` / `DIVERGENT`. This slice adds functions to both
editors (picker callback, remove-image, size-select wiring), so the counts break immediately; and
`refreshToolbarState`'s `DIVERGENT` reason becomes stale the moment the plain table gains a
kind-specific refresh. Re-deriving `EXPECTED_COUNTS` and classifying every newly-common function
with a written reason is a **Definition-of-Done item on the editor tasks**, not incidental cleanup.

### Server side

**`TableElement._cell`** gains an image branch **before** the text fallback, mirroring
`FillTableElement._cell`:

- `media` must be an `int` and **not** a `bool`.
- `alt` coerced to `str`.
- `size` validated against the four tokens and **coerced to the stored default (`full`) on junk** —
  C1's precedent, where an unknown image `size` coerces (a lossless default exists) while an
  unknown callout `kind` raises (none does).
- **Invalid `media` degrades to an empty *text* cell** — `{html: "", halign, valign}` with **no**
  `kind` key. Never raise, never render a broken image.

**`FillTableElement._cell`'s image branch gains the same validated/coerced `size`.**
`canonical_cells` passes non-answer cells through by reference, which is correct as-is.

**`_sanitized_data`** (called from `save()`) currently runs `cell["html"] =
sanitize_cell(cell.get("html", ""))` unconditionally for every non-answer cell. It needs an
explicit `elif kind == "image"` branch **before** that `else`, or every saved image cell gains a
spurious `html` key.

**Shared image resolution.** `FillTableElement.resolve_image_cells` is already a `@staticmethod`
shared between the model and the form — deliberately, so the two cannot diverge on the
unresolved-asset fallback. The Table needs the same logic with a **different empty-cell shape**,
so it lifts to a shared helper parameterised by that shape. It must **not** be copied: 163
code-identical lines across these two editors are already guarded by
`tests/test_editor_twin_drift.py`.

**Unresolved-asset fallback preserves spans.** When an image cell's asset cannot be resolved, the
current fill-table fallback replaces it with an empty cell **and drops any
`header`/`colspan`/`rowspan` it carried**. This slice **inverts** that: the shared helper preserves
those keys, leaving a blank spanning cell.

The decisive evidence is that **export and render already disagree today**: `_ser_fill_table`
explicitly carries span/header through *both* branches, with the comment "losing the image must
not silently un-span the cell and shift the grid" — the exact opposite of what the render-side
fallback does. One of the two is wrong; this slice makes render agree with export.

Three artifacts assert the current behaviour and **must be inverted**, not worked around:

- `tests/test_filltable_editor_partial.py::test_unresolvable_image_cell_drops_spans_in_both_render_and_editor`
- `FillTableElement.resolve_image_cells`'s docstring
- the same rationale repeated in `resolved_grid_cells`'s docstring

The competing rationale in those docstrings ("a spanning gap left un-spanned would misshape the
grid") is a **judgement call, not a measurement**, and so is this reversal — neither layout was
measured. It is decided on consistency with export plus the fact that **DB:** 15 of 312 tables
span, so the case is live.

**`TableElementForm` must become a `_CourseScopedMediaForm`.** It is currently a plain
`forms.ModelForm` with no `course` kwarg and no `self.course`. Two changes, and **omitting the
second makes the security check a silent no-op**:

1. Subclass `_CourseScopedMediaForm` with `media_kind = "image"`, and add a `clean_data` guard
   mirroring the fill-table's "A table image is not an image in this course."
2. `course=` is threaded by **hard-coded type-key tuples in three places** — one in
   `courses/builder.py` and two in `courses/views_manage.py`. `"table"` must be added to the
   builder's tuple (and to the others if the Table element is reachable through them). If it is
   not, `self.course` stays `None`, the fill-table's own guard pattern
   (`if img_ids and self.course is not None`) reproduces as a check that **never fires**, and a
   crafted POST can attach a foreign course's asset with every test still green.

A `resolved_grid_cells` property re-renders the **submitted** grid on a rejected save, and **must
route through `_sanitized_data`** — that exact path is where a self-XSS was caught during the
spanning-table work.

### Transfer (export / import)

**Five** sites. Missing any one breaks export silently — the element round-trips but its image
does not.

| site | change |
|---|---|
| `_val_table` | widen the per-cell `allowed` set with `kind`/`media`/`alt`/`size`; validate per the reject/tolerate table below; return media refs via `_require_media` |
| `_ser_table` | currently `return dict(el.data)`; must walk cells and register each image cell's asset |
| `_element_mids` | routes **by type key**; `table` currently falls through to the scalar `data.get("media")` and returns nothing — without a `table` branch the file is omitted from the zip and import then `KeyError`s |
| `_build_table` | remap each image cell's local string id → the real asset pk, as `_build_fill_table` does |
| **`_ser_fill_table`** | **does not copy the cell** — it builds an explicit `out_cell` literal of `{kind, media, alt, halign, valign}` and then carries `header`/`colspan`/`rowspan`. `size` is not in that literal, so without this change every fill-table export (and therefore **duplicate-unit**, which runs export in-process) silently reverts every image cell to `full` |

`FORMAT_VERSION` **7 → 8**.

**`_ser_table` must NOT call `normalize_data`, and must NOT mutate `el.data`.** Two traps, both
specific to this function:

- `_ser_fill_table` opens with `data = el.normalize_data(el.data)`. Copying that literally would
  change exported bytes for **pre-feature** tables: `TableElement.save()` calls only
  `_sanitized_data`, never `normalize_data`, so directly-created rows (the LAL importer) can hold
  ragged rows and cells missing `halign`/`valign`/`html`. Normalizing at export would
  rectangularise them and inject defaults — silently altering archive bytes and colliding with the
  byte-identity invariant. `_ser_table` therefore walks the stored cells as-is.
- `dict(el.data)` is a **shallow** copy: row lists and cell dicts are shared with the live
  instance. Assigning `cell["media"] = ids.register(asset)` in place would replace real pks with
  local string ids on the in-memory element, and duplicate-unit would then persist that. Build
  fresh rows, exactly as `_ser_fill_table`'s "never mutate `el.data`" comment demands.

**Per-field import policy for `_val_table`** (resolving the reject-vs-tolerate ambiguity; the
precedent is that `_val_table` already **rejects** an out-of-enum `halign`/`valign` even though
the model coerces them):

| field | `_val_table` |
|---|---|
| `kind` | reject if present and not the literal `"image"` |
| `media` | reject via `_require_media` if absent or not a known ref on a `kind:"image"` cell |
| `alt` | tolerate (coerced by the model) |
| `size` | **reject** if present and outside the four tokens — matches the `halign`/`valign` precedent; the model's coercion remains the defence for non-archive paths |

## Data flow

**Authoring.** Author focuses a cell → cell-scoped controls enable → clicks Image cell →
`media_picker.js` dispatches to the Table editor's own hook → modal opens in `cell` mode → author
picks/uploads → the callback converts the focused cell (stashing prior HTML), writes
`data-media`/`data-alt`/`data-size="medium"`, renders a preview `<img>` → per-cell controls appear
→ `serialize()` writes the grid JSON (image branch, no `html` key) into the hidden `data` input.

**Save.** `TableElementForm.clean_data` → `normalize_data` (`_cell` per cell) → course-scoping
check → `save()` → `_sanitized_data` (image cells skipped, text cells sanitised) → JSON stored.

**Rejected save.** The submitted grid re-renders via `resolved_grid_cells` → shared resolver with
`course=` scoping (a foreign or wrong-kind pk resolves to nothing and takes the fallback) → routed
through `_sanitized_data` before any `|safe` output.

**Student render.** `render()` → `resolved_cells` → shared resolver (one `in_bulk` pass) → pk
replaced by `MediaAsset`, unresolved → blank cell **retaining spans** → shared cell partial emits
`<img … data-zoomable>` with the preset class → CSS bounds it → `imagezoom.js` handles enlarge.

**Export.** `_element_mids` collects cell media ids → assets bundled → `_ser_table` /
`_ser_fill_table` emit cells with local asset ids **including `size`**. **Import.** `_val_table`
validates and returns refs → `_build_table` remaps local ids → pk → `normalize_data` + `save()`.

## Error handling

Every degradation is silent and lossless-leaning, never a 500 and never a broken image:

| condition | behaviour |
|---|---|
| `media` missing / non-int / `bool` (model path) | cell degrades to an empty **text** cell (no `kind` key) |
| `size` unknown or non-string (model path) | coerced to `full` |
| `alt` non-string | coerced to `""` |
| asset pk does not resolve at render | blank cell, **spans preserved** |
| asset belongs to another course, or is not `kind="image"` | fails to resolve → same blank-cell path; the form rejects it at save with a field error |
| archive carries `size` outside the four tokens | **rejected** by `_val_table` (see the per-field table above) |
| archive carries an unknown cell key | rejected (exact allowlist, unchanged) |
| merge would absorb an image cell | blocked by `cellIsNonEmpty` |

The model-path and archive-path rows differ **by design**: the model coerces because it defends
non-archive paths where no rejection channel exists; `_val_table` rejects because an archive is a
machine-generated artifact and silent repair hides corruption. This mirrors `halign`/`valign`.

`_table_has_math` reads `cell.get("html", "")`, so an image cell with no `html` key cannot raise
there — **verified, no change needed**.

## Testing

Each claim is owned by the **cheapest layer that can see it**. Every test names a specific mutant
and must be shown RED before it counts.

| layer | owns |
|---|---|
| Model unit | `_cell` image branch (both models); junk-`size` coercion; invalid-media degradation to a `kind`-less text cell; **span preservation** in the shared resolver; `_sanitized_data` writing no `html` key; text cells still normalising byte-identically; `TableElement.resolved_cells` resolves and `render()` uses it |
| Form | course-scoping **raises** with a foreign pk and with an in-course non-image asset; **the builder actually passes `course=` for `table`** (a separate test — without it the guard is a silent no-op); rejected-save re-render routed through `_sanitized_data` |
| Transfer | all **five** sites; round-trip with a real asset asserting `size` survives **for both table types**; `_ser_table` leaves `el.data` unmutated; a legacy non-normalized table's export bytes are unchanged; a pre-feature archive still imports; out-of-enum `size` rejected; `FORMAT_VERSION` bump |
| Template | both cell partials emit `<img>` + `data-zoomable` + the preset class; text-cell output unchanged |
| Editor / JS regression | `serialize()` emits the image branch and no `html` key; `test_editor_twin_drift.py` `EXPECTED_COUNTS` re-derived and every newly-common function classified; every `table-editor__*` class the JS emits is styled (`tests/test_table_css.py` exists because that drift was a real shipped bug); every `#ed-*` reference resolves to a defined sprite symbol; the Full label carries the `"image size"` gettext context |
| e2e | sizing renders; clicking an image cell reveals the per-cell controls; the toolbar's cell-scoped buttons are disabled before any focus |

**The sizing claims are only real if measured in a browser.** C1's harness traps transfer verbatim:

- **Caps only shrink**, so a bounding-box assertion needs `min(hcap, wcap/ratio, naturalHeight)` —
  without the intrinsic clamp the *correct* build fails.
- **`getComputedStyle().width` is the border box** (`reset.css` sets `box-sizing: border-box`
  globally). Measure the wrapper, never a padded container.
- **`_isolated_media` is mandatory, not hygiene** — `live_server`'s `_MediaFilesHandler` reads
  `MEDIA_ROOT` per request, so it is what makes `/media/<path>` resolve at all. Pair it with an
  await-decoded step: an undecoded `<img>` legitimately reports `naturalWidth` 0.
- **A request recorder must filter on the URL path**, never the Django URL *name*.
- **`_seed_unit` mints a fresh Course**, and `MediaAsset` is course-scoped.
- The **editor and preview panes are siblings**, so mutating the preview pane is a no-op mutant;
  mutate the editor pane.

**The one genuinely new e2e assertion is stability**: lengthening text in a *neighbouring* cell
must no longer change the image's rendered width (426→286px today). Nothing below the browser
layer can observe this. Note it must be written against a **bounded** preset — at `full` the
image is still content-negotiated by design, so a `full` cell would (correctly) fail it.

**Light + dark screenshot verification belongs in the styling task's Definition of Done**, not
deferred — that deferral is how the fill-table shipped its dark-mode contrast bug. An editor page
must link **both** `courses.css` and `editor.css` to render faithfully.

## Settled decisions (do not re-litigate)

- Widen the cell subset + media picker; **not** element slots in cells.
- `kind:"image"` with a `MediaAsset` pk; **not** a raw `<img>` in the sanitised HTML.
- A cell is image **or** text, never both.
- Absolute px presets; **not** percentages, and **not** a reuse of `ImageElement.size`.
- Stored default `full` (back-compat); editor-insert default `medium` (authoring quality).
- Both tables get the scale; the unresolved-asset fallback **preserves** spans in both.
- Content column is **648px desktop / 296px phone**. The C1 spec's 880/328 is superseded.
  Chromium shrink-wraps `fit-content` to the constrained contribution — settled in C1.
- Chromium/Firefox/WebKit agree to 1px on the preset rules — settled here, do not re-derive.

## Line-number policy

This spec cites code **by symbol name**, not line number. An earlier draft's line citations had
already drifted by 1–3 lines against the current tree, which erodes the verification value they
were meant to add. Implementers should locate symbols by name.
