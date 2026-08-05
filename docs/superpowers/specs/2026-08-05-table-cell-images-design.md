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
- **Bringing cell images into media usage tracking.** `courses/media.py`'s `_MEDIA_REF_MODELS` —
  documented as "the single source of truth for what can use an asset" — lists only
  `ImageElement`, `VideoElement` and `DragToImageQuestionElement`, and `usage_count` /
  `delete_asset` / the "where used" list all derive from **FK queries**. A JSON-referenced cell
  image therefore reports **0 uses**, so `delete_asset` will delete an asset a table is displaying,
  manufacturing exactly the dangling pk the render fallback absorbs. This is **pre-existing and
  identical for gallery and fill-table cell images**; it is stated here as a deliberate
  non-goal — with the fallback as the accepted mitigation — so an implementer who finds that
  docstring does not "fix" it inside this slice.
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
2. `_val_table`'s per-cell check is an **exact allowlist** (`set(cell) - allowed`), so every
   archive written in the new format would need that allowlist widened for a key carrying no
   information. (It rejects *unknown* keys, not missing ones — a pre-feature archive lacking
   `kind` validates fine. This is a cost, not a rejection.)
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
render the select in arbitrary order. Shared by `FillTableElement`, both forms, both editor
**templates** and the transfer validators — one definition, no duplicated literals **across the
Python and template layers**.

**The JS layer cannot read a `TextChoices`, so it needs its own named carrier.** Both editor
scripts need the two defaults — `serialize()` reads `td.dataset.size || "full"` and
`setImageCell` writes `td.dataset.size = td.dataset.size || EDITOR_INSERT` — and neither can call
into Django. **Decision: hard-code the two literals as module-level `var`s in each editor script**
(`var CELL_IMAGE_DEFAULT = "full";` and `var CELL_IMAGE_INSERT = "medium";`), adopting the existing
precedent in these same files — `table_editor.js` already carries `var MAX_ROWS = 50;` mirroring
`TableElement.MAX_ROWS`, and `HALIGNS`/`VALIGNS` mirroring the model enums. A `data-*` carrier was
considered and rejected as machinery these two tokens do not earn.

**The duplication is then pinned, not trusted:** a source-level test asserts the JS literals equal
the Python constants (`DEFAULT_CELL_IMAGE_SIZE` / `EDITOR_INSERT_CELL_IMAGE_SIZE`), in both editor
files. Note `MAX_ROWS` has **no** such pin today — this slice adds one for its own tokens rather
than inheriting the gap. Wherever this spec writes `EDITOR_INSERT`, it means `CELL_IMAGE_INSERT`.

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
`src=""`.

**The resolved cells go inside the existing `data` key, not in place of the context.**
`TableElement.render()` currently passes `{"el": self, "data": data}`, and `tableelement.html`
reads `data.border` / `data.header_row` / `data.cells`. So the change is
`ctx["data"] = {**self.normalize_data(self.data), "cells": self.resolved_cells}`, keeping `el` in
the context — the same shape `FillTableElement.render` already uses. Written as a bare
`{**normalize_data(self.data), "cells": self.resolved_cells}` *as the whole context*, `data.border`
resolves empty and the element ships as `el--table--border-` with the header attributes gone.

`normalized_data` (used elsewhere) stays **unresolved** — resolution is a render-time concern only.

`tableelement.html` currently emits `{{ cell.html|safe }}` on all five of its branches (four of
which are `<th>`). Factor the cell body into **a new `_table_cell.html`**, included from all five
branches, so they cannot drift and an image in a header row is handled once. Path:
`templates/courses/elements/_table_cell.html`, beside `_filltable_cell.html` (the repo has a second
template root at `courses/templates/courses/`, so the path is stated rather than inferred).

**The partial must be a single line with no leading whitespace and — stated at the byte level —
its last byte must be neither `\n` nor `\r`**, and the `{% include %}` must sit immediately between
`>` and `</td>`. `{% spaceless %}` strips whitespace only *between tags*, so an indented or
newline-terminated partial emits whitespace **adjacent to text**, which survives — changing
rendered bytes for all **7,246** existing cells.

**Do NOT copy `_filltable_cell.html`'s shape as if it already satisfied this.** It does not: it
ends `…{% endif %}\r\n`, carrying a trailing newline, and `filltableelement.html` includes it with
**no `{% spaceless %}`** at all, so that newline is emitted today and harms nothing there.
`tableelement.html` **does** use `{% spaceless %}`, which is precisely why the plain table's
partial has a requirement its sibling does not. An implementer told the sibling is already
whitespace-free will reproduce the trailing newline (and any editor will silently re-add it),
yielding `…text…\n</td>` — where `>\s+<` does not match because the whitespace follows a **text
node**, the exact failure this paragraph exists to prevent.

Two artifacts are required, and **the mechanism must not be mistaken for the guard**:

- **The guard (new).** A render-level test that exercises the real template —
  `TableElement.render()` (or `render_to_string("courses/elements/tableelement.html", …)`) — and
  asserts the exact `<td …>…</td>` bytes for a text cell, before and after the factoring. Plus a
  byte-level assertion that `_table_cell.html`'s last byte is not `\n`/`\r`.
- **The mechanism (explanatory only).** `math_reflow.js` compares **TEXT-NODE LEAVES**, so an
  injected whitespace node changes its decision — which is *why* the bytes matter.
  **`tests/test_e2e_math_reflow_dom.py` is NOT the guard**, despite asserting an exact innerHTML:
  its `_reflow_html(page, html)` helper assigns a **hand-authored literal string** to
  `#root.innerHTML` and never renders `tableelement.html`, so it stays green no matter what
  `_table_cell.html` emits. Naming a structurally-blind test as the proof of byte-safety is the
  failure mode; name the render-level test instead.
**`_filltable_cell.html` stays separate** — it branches on `cell.kind == "answer"`, reads
`mine.done`, and uses `forloop.parentloop.counter0` for the answer input's `data-r`/`data-c`, none
of which a plain table has.

**The CSS class names, named once so five artifacts agree** (both student partials, both editor
previews, `courses.css`): a shared base **`.cell-img`** with modifiers
**`.cell-img--small` / `--medium` / `--large` / `--full`**. Both partials emit
`class="cell-img cell-img--{{ cell.size }}"`; `_filltable_cell.html` keeps `filltable__img`
alongside it for any fill-table-specific styling.

**The base rule must NOT declare `max-width`.** `.filltable__img` currently declares
`max-width: 100%`, which has **identical specificity** to a single-class `.cell-img--medium`, so a
preset block authored next to the `.el--table` rules (earlier in the file) would silently lose to
it and every preset would degrade to Full. Reduce `.filltable__img` to `height: auto; display:
block`, put all sizing on `.cell-img--*`, and place the preset block **after** the base rule. This
is the same equal-specificity trap already recorded from the callout slice; removing the competing
declaration resolves it by construction rather than by source order alone.
Once reduced, `.filltable__img` declares nothing `.cell-img` does not, so **delete the rule
outright** — keeping a no-op rule invites a future author to re-add `max-width` and re-open the
trap. The **class stays on the element** (`tests/test_filltable_render.py` asserts on it); only the
CSS rule goes.

**Alignment needs its own mechanism, or the halign control ships inert.** `courses.css` implements
halign as `.ta-center { text-align: center }` on the `<td>`, which has **no effect on a
`display: block` child**. Today that is invisible because `max-width: 100%` makes the image fill
its cell; with absolute caps of 80/160/240px inside a 648px column the image is almost always
narrower than its cell, so it would sit flush left whatever the author picks — while the align
buttons stay enabled, `serialize()` faithfully writes `halign`, and the spec elsewhere insists that
attribute must survive. So `.cell-img` keeps `display: block` and gains margin-driven alignment
from the cell's existing class:

```
.ta-center > .cell-img { margin-inline: auto; }
.ta-right  > .cell-img { margin-inline: auto 0; }
```

(`ta-left` is the `margin-inline: 0` default and needs no rule.) The same pair is required for the
two **editor preview** classes, or the editor and the student view disagree. Pinned by a measured
assertion that a `ta-center` image cell centres its preset-bounded image — the C1 precedent, where
centring `fit-content` figures was exactly this class of bug.

CSS lives in `courses/static/courses/css/courses.css` alongside the existing `.el--table` and
`.filltable__img` rules (not `editor.css` — that is where the shared `.table-editor__grid` cell
styles live, a distinction that has already caused one misdiagnosis).

**A `@media print` block IS added**, bounding `full` at `max-height: 170mm` to match C1's print
scale, and placed **after** the preset block — `@media print` adds no specificity, so ordering is
what makes it win. Without it a `full` cell image prints at a viewport-relative `dvh` height.
Small/Medium/Large are already absolute and need no print counterpart.

### Editor UX

**Discoverability is a first-class requirement of this slice.** Both table editors render
`<div class="table-editor__toolbar" data-table-toolbar hidden>` and reveal it only on cell focus.
An author opening a table sees a bare grid and no controls, with nothing signalling that clicking
a cell reveals eighteen controls. This is not hypothetical: the person who commissioned this feature
could not find the fill-table's existing Image-cell button for exactly this reason.

**Fix:** the toolbar renders **always visible**, with cell-scoped controls **disabled** until a
cell is focused. The `hidden` attribute is removed from `[data-table-toolbar]` in **both**
`_edit_table.html` and `_edit_filltable.html`. Two things then become dead and must be removed in
the same change, not left to rot: `editor.css`'s `.table-editor__toolbar[hidden] { display: none }`
rule, and the `toolbar.hidden = false` line in each editor's `focusin` handler. Precisely:

- **Disabled with no focus:** every `[data-cmd]` (B/I/U, math, **and the five
  `data-cmd="colour-*"` swatches from `_rte_swatches.html`**), plus the image button.
  Merge/split/header are already `disabled` in markup and keep their existing logic.
- **The per-cell image controls are *hidden*, not disabled** — a different mechanism, assigned per
  control in "Per-cell controls" below. Do not conflate the two: the e2e assertion "cell-scoped
  buttons are `disabled` before any focus" applies to `[data-cmd]` and the image button only.
- **`[data-halign]`/`[data-valign]`** are class-toggled, never `disabled`; `refreshAlignButtons`
  must **clear their `is-on` state when `focusCell` is null**, or the toolbar shows a stale
  alignment painted from a previously-focused cell.
- **`refreshToolbarState()` must run once at init** in both editors, placed **after** the
  `focusCell`/`rangeAnchor` declarations. (The natural-looking site beside
  `refreshControlState(grid, desc)` sits *above* `var focusCell = null`, where it works only by
  `var` hoisting and would break the moment either becomes `let`/`const`.) Without the init call
  the always-visible toolbar paints with B/I/U/swatches *enabled* and no focus — clicking them
  does nothing, which is precisely the "controls that appear to work but don't" failure this
  section exists to prevent.

**This is not "one change in two editors" — both editors need work, differently.**

- `table_editor.js`'s `refreshToolbarState` touches merge/split/header only and then calls
  `refreshAlignButtons`, which itself returns early when `focusCell` is null. It must **gain** the
  `[data-cmd]` disable loop, with the predicate stated explicitly as
  **`!focusCell || focusCell.hasAttribute("data-image")`** (null-safe). Pinning only the no-focus
  case would leave B/I/U, math and the colour swatches **enabled on a focused image cell** — and
  the toolbar's click handler runs on `if (cmdBtn && focusCell)`, so `cmd === "math"` would append
  a text node into a non-contenteditable image `<td>` that `serialize()`'s image branch (no `html`
  key) then silently discards. Pinned by the same style of test as the fill table's: focus an image
  cell, assert a `[data-cmd]` button is `disabled`.
- `filltable_editor.js` **does** have the loop, but executes `if (!focusCell) return;` *before* it,
  so calling it at init with no focus leaves B/I/U, math and the five swatches **enabled** — the
  exact failure this section exists to prevent. Move the `[data-cmd]` loop **above** that early
  return and change its predicate to `!focusCell || isAnswer || isImage`.
  **The `isAnswer`/`isImage` derivations must move above the early return too, and become
  null-safe** (`!!focusCell && focusCell.hasAttribute(…)`). They are currently declared *after*
  the return; moving only the loop leaves both `var`s hoisted-but-`undefined`, so with a cell
  focused the predicate reads `false || undefined || undefined` → falsy → the buttons stay
  **enabled on answer and image cells**. That regression is invisible to every server-side test,
  so it is pinned by a test that focuses an image cell and asserts a `[data-cmd]` button is
  `disabled`.
- `imageAlt.hidden` sits behind the same early return, as will the new size-select and
  Remove-image visibility lines. All three must move above it with a `!focusCell` clause, so the
  newly-required **init-time refresh** hides them.
- **`focusCell` is never nulled after init — and that is a second, separate bug.** `focusCell =
  null` occurs exactly once per file, as the `var` initialiser; no delete or merge path re-nulls
  it. Delete the row holding the focused image cell and `focusCell` points at a **detached**
  `<td data-image>`: `!focusCell` is false and `hasAttribute("data-image")` is true, so the alt
  input, size select and Remove image stay visible **and populated**, and editing them writes to a
  node no longer in the grid — silently lost at the next `serialize()`. A `!focusCell` clause does
  not reach this. **`afterStructuralEdit()` must clear `focusCell`/`rangeAnchor` when the node is
  no longer connected** (`!focusCell.isConnected`), in **both** editors. Pinned by a test that
  deletes the row holding the focused image cell and asserts the per-cell controls are hidden.

**The image button needs BOTH pick attributes — `data-pick-mode` alone never opens the picker.**
`media_picker.js`'s open handler gates on `e.target.closest("[data-pick-media]")` and reads the
asset kind from **that** attribute's value; `data-pick-mode` is only consulted afterwards to choose
the destination. So the plain table's new image button carries
**`data-pick-media="image" data-pick-mode="cell"`**, exactly as `_edit_filltable.html`'s existing
one does. Naming only the mode attribute — as an earlier draft did throughout — yields a button
that does nothing at all, before any of the dispatch work below even matters.

**The media picker needs a per-editor dispatch.** `media_picker.js` currently hard-codes a single
hook: `if (pick.getAttribute("data-pick-mode") === "cell" && window.libliFillTablePickImage)`.
Rendering those attributes in `_edit_table.html` therefore still routes to the **fill table's**
callback until `media_picker.js` changes. `media_picker.js` gains a dispatch keyed off the button's owning editor
root (`[data-table-editor]` vs `[data-filltable-editor]`), and `table_editor.js` registers its own
hook, **`window.libliTablePickImage`**. **It must not assign
`window.libliFillTablePickImage`** — both editor scripts load on every editor page, so a shared
global means whichever runs last wins and one editor's picker silently drives the other's callback.

**A `closest()` call alone does not fix that**, and saying so would be decorative: the existing
hook is assigned *inside* `wire(editor)` and closes over that editor's `focusCell` and
`setImageCell`, so a per-editor closure re-assigned to one global is still last-wins regardless of
what the callback inspects. The registry must be explicit:

- `wire(editor)` publishes its per-editor handle into a **module-level `WeakMap` keyed by the
  editor root element** (`[data-table-editor]`).
- **One module-scope** `window.libliTablePickImage = function (pick) { … }` — assigned once, not
  per editor — looks the handle up via `pick.closest("[data-table-editor]")`.
- On a lookup **miss** the hook returns `null`, and `media_picker.js` (which already tests the hook
  for truthiness before using it) leaves the field untouched rather than throwing.

**Table editor cell markup.** `_edit_table.html`'s grid loop has one
`<td contenteditable>`/`<th contenteditable>` pair and no image branch. It gains an image branch carrying **identical attributes to the existing text branch** —
`class="ta-{{ cell.halign }} va-{{ cell.valign }}"`, `data-halign`, `data-valign` and the
conditional `colspan`/`rowspan` — **plus** `data-image`, `data-media`, `data-alt`, `data-size`,
`tabindex="0"`, and **minus** `contenteditable`. **It is a `<th>`/`<td>` pair, not one branch** —
the loop's outer structure is `{% if cell.header %}<th…>{% else %}<td…>{% endif %}`, and
`toggleHeaderCell` makes `<th data-image>` reachable while `serialize()` writes `header: true` for
it. A `<td>`-only image branch silently demotes every header image cell to a `<td>` on reload and
loses `header` on the next save. Round-trip test: header-toggle an image cell, save, reopen, assert
`<th data-image>`. Omitting the alignment/span attributes would
reset every image cell to left/top on the next save (`serialize()` reads `td.dataset.halign`/
`valign` and `td.colSpan`/`rowSpan`) and make a spanning image cell unrenderable. The loop must also read
`form.resolved_grid_cells`, not `form.grid_data`, or `cell.media` stays an int. **Only the grid
loop changes:** `{% with d=form.grid_data %}` still feeds the controls strip (`d.header_row`,
`d.header_col`, `d.border`), so `d` is kept and only the row iteration switches — matching how
`_edit_filltable.html` already does it, and avoiding a second `normalize_data` pass per render.

**`serialize()`'s image branch must SKIP `mapColours` — by guarding the call, never by returning.**
The **first statement inside the `forEach` callback** is
`if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });`, which mutates
the cell's subtree on every serialize. On a non-contenteditable image cell that is both wasted work
and DOM mutation inside a node the author cannot edit, so it is skipped — stated as a decision
rather than left an accident.

**But `row.push(cell)` is the LAST statement of that same callback**, so "return before
`mapColours`" would skip the push and **silently delete the cell from the serialized row** — a
column vanishes on save. The only coherent shape is therefore:

- derive `isImage` first, then guard the call:
  `if (!isImage && window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });`
- build the cell object in a kind branch (below),
- and keep **one** `row.push(cell)` after the shared span/header suffix.

**No `return` may occur anywhere inside the `forEach` callback.**

**`serialize()` must gain a kind branch.** `table_editor.js`'s `serialize()` unconditionally emits
`{html: td.innerHTML, halign, valign}` for every cell. An image cell would serialize as
`html: "<img …>"`, which `sanitize_cell` then strips to `""` on save — **the image is lost with no
error**. The image branch replaces **only** the `{html, halign, valign}` literal: it emits
`{kind, media, alt, size, halign, valign}` and **no** `html` key, and the existing
`colspan`/`rowspan`/`header` suffix — appended *after* the cell object is built — still applies to
both branches. Writing the image branch as an early `row.push({...})` inside the `forEach` would
drop all three. It reads
the size as **`td.dataset.size || "full"`** (the shared default constant): a bare
`td.dataset.size` is `undefined` when the attribute is missing, `JSON.stringify` then drops the key
entirely, and the model coerces it back to `full` — silently demoting a `medium` cell if any path
forgets to write the attribute. Always emitting the key upholds the "every reader may use
`cell["size"]` directly" invariant.

**Focus must reach an image cell.** `table_editor.js`'s `focusin` handler matches
`e.target.closest("td[contenteditable], th[contenteditable]")` and returns early otherwise.
`filltable_editor.js` had to widen exactly this selector to include `td[data-image], th[data-image]`
because such cells are not contenteditable. Without the same widening, clicking a Table image cell
sets neither `focusCell` nor the range anchor: the alt input, the size select and Remove image
never appear, and the cell can never be a merge/split/align target. Widen the selector **and** the
post-merge/delete focus fallback.

**`tests/test_cell_selector_guard.py` must be updated in the same change**, and it is a trap in its
own right. Its `INVENTORY` carries `("…/table_editor.js", 'closest("td[contenteditable]', "th")`,
and its own comment documents the hazard: once the selector is line-wrapped — which widening it
will force, exactly as it did for `filltable_editor.js` — the needle no longer lands on the
`focusin` site and is instead satisfied by unrelated single-line `keydown`/`input` calls, leaving
the widened site **unguarded with the test still green**. The fill table needed a bespoke
full-literal inventory entry for precisely this; add the plain table's twin. A Definition-of-Done
item on the editor task, alongside the five `FORMAT_VERSION` sites.

**Behaviour of the image button:**

- **On a text cell** → picker → convert, **stashing the prior HTML** so the conversion is
  reversible (the fill-table's per-node stash is the precedent), writing `size="medium"`.
  **The stash is cleared on every structural edit**, adopting the *other* half of that precedent:
  `filltable_editor.js`'s `afterStructuralEdit()` opens with `cellStash.clear()` because a stash
  could otherwise restore into the wrong node after the grid reshapes. This is not a free choice —
  `afterStructuralEdit` is currently a `DIVERGENT` entry whose entire stated reason is that the
  fill-table clears and the plain table does not; clearing makes the bodies identical, so the entry
  **moves to `TWINS`**.

  **"Identical" is mechanical, and the spec must pin it or the move silently reverts.**
  `test_twins_are_identical` compares comment-stripped, indent-stripped **token lines**, so moving
  the entry to `TWINS` imposes three hard naming/ordering constraints on the plain table:

  1. its stash Map must be named **exactly `cellStash`** — not `stash`, not `htmlStash`;
  2. **`cellStash.clear()` must be the first statement** of `afterStructuralEdit()`, matching the
     fill table's opening line;
  3. the new `!focusCell.isConnected` clearing block (required below) must be written
     **character-for-character the same** in both files.

  Miss any one and `test_twins_are_identical` goes red, where the natural-looking "fix" is to
  reclassify the function back to `DIVERGENT` — silently undoing this decision. The fill table's
  trailing `// fill-table only` comment on that line also becomes false and must be deleted (the
  comparison strips comments, so nothing reddens to prompt it).
- **On an image cell** → picker → replace the image, preserving `size` and `alt`.
  **Both paths are one function.** `filltable_editor.js`'s `setImageCell(td, …)` has a single call
  site serving conversion *and* re-pick, so a literal `td.dataset.size = "medium"` would demote an
  author's `full` cell on every re-pick, while a literal "preserve" would leave a converted cell
  with no `data-size` at all. The rule is **`td.dataset.size = td.dataset.size || EDITOR_INSERT`**.
  **`setImageCell` must also emit the preview's modifier class.** It rebuilds the preview with
  `img.className = "filltable-editor__img"` — base only. Once `max-width` is stripped from that
  base rule, an in-session conversion or re-pick renders the asset at its intrinsic width (**DB**
  p50 1192px) and drags the editing grid — a regression to an already-shipped feature. Emit the
  base as a lone `className =` assignment plus `classList.add("filltable-editor__img--" + size)`,
  the same shape as the plain table's. **Nothing currently guards this**: `tests/test_table_css.py`
  reads only `TABLE_JS`, so the fill-table editor's class emissions are unguarded — extend that
  guard to `FILL_JS`/`courses.css`, or add a test asserting the class pair on a freshly converted
  fill-table cell.
  Correspondingly, `data-size` must be added to the attributes removed by `toggleAnswerCell`'s
  image→static branch (which today drops `data-media`/`data-alt`/`tabindex`), or a stale `data-size`
  lingers on the static cell and is inherited by a later reconversion.
- **Reverting to text** needs its own control: the fill-table gets this free from its Answer-cell
  toggle, which the plain Table has no equivalent of. **Remove image** mirrors
  `filltable_editor.js`'s `toggleAnswerCell` image branch exactly: restore the stashed HTML **if a
  stash entry exists**, else leave the cell **empty** (`stashed.html != null ? stashed.html : ""`
  — a literal `td.innerHTML = stash.html` would write the string `"undefined"`); then remove
  `data-image`/`data-media`/`data-alt`/`data-size`/`tabindex`, restore `contenteditable="true"`,
  set `focusCell`, refresh the toolbar and `serialize()`.
  **The no-stash case is the dominant one**, not an edge case: the stash is populated only by an
  in-session text→image conversion, so any author who saves, reloads the editor and then removes a
  server-rendered image cell hits it. Pinned by a test that reloads the editor and removes an image
  without ever having converted one in-session.

**Per-cell controls**, shown only while an image cell is focused: the **alt** input, the new
**size** select (`[data-image-size]`), and **Remove image** (`[data-image-remove]`) — named here
once, mirroring the existing `[data-image-alt]`/`[data-answer-toggle]` spelling, because two
templates, two JS files and their tests must all agree on them. The fill-table editor gains the
same size select.

**Mechanism, stated per control so the two passages cannot disagree:**

| control | mechanism with no image cell focused |
|---|---|
| alt input (`[data-image-alt]`) | **hidden** (the existing precedent: `imageAlt.hidden = true`) |
| size select (`[data-image-size]`) | **hidden**, same as the alt input |
| Remove image (`[data-image-remove]`) | **hidden**, same as the alt input |
| `[data-cmd]` buttons, image button | **disabled** (they stay visible; see above) |

**A `hidden` Remove-image button styled `.rte-btn` will NOT hide, and this repo has already
shipped that bug.** `editor.css`'s `.rte-btn` declares `display: inline-flex`, and an author
`display` beats the UA `[hidden] { display: none }` rule **regardless of specificity**. The same
file documents the trap verbatim beside `.view-toggle[hidden] { display: none; }`. The alt input
escapes it only because `.input` sets no `display` — which is exactly why copying the alt input's
`hidden` mechanism onto a `.rte-btn` is not sufficient. So: **add an explicit
`[data-image-remove][hidden] { display: none; }` rule to `editor.css`** (a `.rte-btn[hidden]` rule
is the equally acceptable broader form), and **pin it with a CSS source assertion**. Without it the
button is permanently visible, on text cells too — precisely the "controls that appear to work but
don't" failure the discoverability section exists to prevent.

**Clicking Remove image with no image cell focused is a no-op** (guard on
`focusCell && focusCell.hasAttribute("data-image")`), so the control is inert rather than undefined
should it ever be reachable.

Remove image needs a sprite glyph: the sprite defines no trash/remove symbol today (`ed-minus` is
the nearest and means "delete row/column"), so **add a new monochrome `currentColor`
`ed-image-remove` symbol** rather than overloading an existing one; the "every `#ed-*` reference
resolves to a defined sprite symbol" test covers it.

**The select must be populated from the focused cell, not merely shown.** The alt input's
precedent is `imageAlt.value = td.dataset.alt || ""` inside `focusin`; a toolbar-level control
otherwise displays a stale value from the previously focused image cell, so an author focusing a
`full` cell would see "Medium". So: `focusin` on an image cell sets the select's value from
`td.dataset.size` (defaulting to `full`); a `change` on the select writes `td.dataset.size`, swaps
the preview's modifier class, and calls `serialize()`. Pinned by a test that focuses two image
cells of different sizes in turn.

**Two fill-table editor sites carry `size`, and missing either reverts every image cell to `full`
on every save** — the same defect class as the `_ser_fill_table` omission, but on the far more
frequent path:

- `filltable_editor.js`'s `serialize()` image branch currently emits exactly
  `{kind, media, alt, halign, valign}` (+span/header). It must emit `size`.
- `_edit_filltable.html`'s two image branches render `<td data-image data-media data-alt
  tabindex="0">` with **no `data-size`**. Both the `<td>` and `<th>` branches gain
  `data-size="{{ cell.size }}"`.

Pinned by a test that an **untouched** image cell round-trips its `size` through an editor save.

**The size select is server-rendered**, so its labels are translated server-side rather than
hard-coded in JS (which cannot call `{% trans %}` — that is why `_edit_table.html` already carries
eleven `data-msg-*` attributes).

**The templates iterate `CellImageSize.choices`; they must NOT write `{% trans %}` per option.**
Per-option literals would both duplicate the "one ordered place" constant and re-open the msgid
collision: a bare `{% trans "Full" %}` resolves to the msgid already owned by `courses/forms.py`
(feminine `"Pełna"`), so the model would carry the correct `pgettext_lazy("image size", …)` label
while the shipped select rendered the wrong gender — and a source-level test on the model constant
would still pass. **Neither the size select nor the alt input carries a `name` attribute.** `_edit_table.html`'s own
header comment establishes that the hidden `name="data"` field is the sole authoritative input and
the controls strip is name-less JS UI; a named control inside the element `<form>` would post an
extra field, and — per this project's recorded `form.action` shadowing incident — a badly chosen
name can shadow a form property and silently disable the form in a browser while every server test
stays green. Pinned by a source-level assertion in the editor-partial test.

The choices reach the templates via a **property on each form**
(`form.cell_image_sizes`, returning `CellImageSize.choices`), since the forms otherwise expose only
`data`. The context test therefore asserts the **rendered select's Full option**, not just the
model constant. Per editor:

- **`_edit_filltable.html`** — the select goes beside the **existing** `data-image-alt` input.
- **`_edit_table.html`** — the image button, the alt input, the size select and the image-related
  `data-msg-*` attributes are **all new**; there is no existing anchor control there.

**The editor preview must scale with the preset.** Today's `.filltable-editor__img { max-width:
120px }` is a flat thumbnail that would render Small, Medium and Large identically, leaving the
author unable to see what they picked. It cannot be pixel-exact — the editor grid is not the 648px
student column — so use a proportional editor-only scale, **square bounding boxes** like the
student rules: **Small 40px · Medium 80px · Large 120px · Full `max-width: 100%` +
`max-height: 200px`** (see the correction below — `full` is bounded in both axes, never uncapped).
All three numeric presets set **both** `max-width` and `max-height` to that value, matching the
student rules' square bounding box.
Assertion form: for one asset, rendered widths are **strictly increasing** across
Small < Medium < Large.

**`--full` must be bounded in BOTH axes, not uncapped.** A table cell in auto layout does not bound
its child — it *grows* to the child's intrinsic width, which is the very content-negotiation the
MEASURED table documents. With `max-width` stripped from the base rules and nothing on `--full`, a
p50 1192px asset would render at 1192px and drag the editing grid to that width.

- **Width:** the editor `--full` modifier carries `max-width: 100%`, mirroring the student rule.
- **Height:** it also carries **`max-height: 200px`**. "Mirroring the student rule" is incomplete
  without this — the student `--full` is `max-width: 100%` **plus** `max-height: 60dvh`, and
  dropping the height half reintroduces the exact defect this slice exists to fix, inside the
  editor: the spec's own 494×1492 case would render column-wide and unbounded vertically, dragging
  the editing grid down. A fixed px cap rather than `dvh` because `dvh` is meaningless in a split
  editor pane, which is not the viewport.

So the editor scale is **Small 40 · Medium 80 · Large 120 · Full `100%` × 200px**, every entry
bounded in both axes.

**Editor-preview class names and their file** (completing the "five artifacts" promise):

- Plain table: base `table-editor__img`, modifiers `table-editor__img--small|medium|large|full`.
  Because `tests/test_table_css.py` requires every `table-editor__*` class the JS emits to be
  styled in **`editor.css`**, these rules live in `editor.css`.
- Fill table: the existing `filltable-editor__img` plus the same four modifiers, kept in
  `courses.css` beside their twin.
- **The same equal-specificity trap applies here.** `.filltable-editor__img` currently declares
  `max-width: 120px`, which ties with any single-class modifier and would also make "Full
  uncapped" impossible. Strip `max-width` from both base rules and put all four sizes on the
  modifiers.
- **The server-rendered previews emit the modifier too**, not just the JS. `_edit_filltable.html`'s
  two `<img class="filltable-editor__img">` tags gain `filltable-editor__img--{{ cell.size }}`, and
  the new `_edit_table.html` image branch emits its `table-editor__img--{{ cell.size }}` twin —
  otherwise a reloaded editor shows every preset at the same size until the author touches the
  select.
- **The guard only sees a lone assignment.** `test_table_css.py` matches
  `className = "(table-editor__[\w-]+)"`, so the JS must assign the base as a single
  `className = "table-editor__img"` and add the modifier via `classList.add(...)`, or the
  assertion stops matching entirely and the class ships unstyled with no failure. **Widen that
  regex to also capture `classList.add("table-editor__…")`** so the modifiers are guarded too —
  a Definition-of-Done item on the editor task. (Note the substring hazard: `table-editor__` also
  occurs inside `filltable-editor__`.)

**Structural operations × image cells** (only merge was previously considered):

| operation | required behaviour |
|---|---|
| Merge | An absorbed image cell triggers the **existing merge-discard confirmation**, and on confirm the image cell **is discarded**. It does not block: `cellIsNonEmpty` feeds `absorbedNonEmpty`, whose only consumer is `if (rg && absorbedNonEmpty(rg)) { if (!window.confirm(msg("merge-confirm"))) return; }`. `cellIsNonEmpty` **already** reads `c.textContent.trim() !== "" \|\| c.querySelector("img") !== null`, so a rendered preview already triggers it; add a `hasAttribute("data-image")` clause so a cell whose preview has not yet rendered also counts, and pin it with a test. (Two earlier claims were **false**: that this guard was missing, and that it blocks. The divergent function is `cellIsNonEmpty`; `absorbedNonEmpty` is a listed twin.) **Stale comment:** `table_editor.js`'s comment above `absorbedNonEmpty` reads "(table_editor.js has no kinds; the kind clauses live in filltable_editor.js's override.)" — false the moment the plain table gains image cells and a `data-image` clause. Delete or rewrite it in the same change. |
| Split | The image stays in the anchor cell; newly created cells come from the existing `makeCell()` helper as ordinary text cells. |
| Header toggle | `table_editor.js`'s `toggleHeaderCell` builds a **new** element and calls `td.replaceWith(next)`. Attributes are copied, but a **WeakMap stash key is not** — so header-toggling an image cell would orphan its stash and **Remove image would restore nothing**. It must re-point the new stash from the old node to the replacement, mirroring `filltable_editor.js`'s `cellStash` re-keying. Its in-file comment ("there is no such map in this file's scope (plain tables have no static/answer/image content to stash)") becomes **false** and must be deleted. Pinned by a test: toggle header on an image cell, then Remove image. |
| `header_row` / `header_col` toggles | An image cell may become a `<th>`; the shared `_table_cell.html` handles it, so no branch-specific work. |
| Row/column delete | No new warning — parity with text cells today. Stated so the omission is deliberate. |

**`tests/test_editor_twin_drift.py` will go red and must be updated.** It asserts a hard-coded
`EXPECTED_COUNTS = {TABLE_JS: 28, FILL_JS: 36}` and requires every function name common to both
files to be classified in exactly one of `TWINS` / `DIVERGENT`. This slice adds functions to both
editors (picker callback, remove-image, size-select wiring), so the counts break immediately; and
`refreshToolbarState`'s `DIVERGENT` reason becomes stale the moment the plain table gains a
kind-specific refresh. Re-deriving `EXPECTED_COUNTS` and classifying every newly-common function
with a written reason is a **Definition-of-Done item on the editor tasks**, not incidental cleanup.

**Four `DIVERGENT` reasons go stale, not one.** No test compares these reason strings, so a false
rationale survives silently — the "false mechanism survives review" failure mode this project has
already recorded:

| entry | why its reason dies |
|---|---|
| `refreshToolbarState` | the plain table gains a kind-specific refresh |
| `toggleHeaderCell` | reason says "fill-table re-keys the live `cellStash` Map old->new"; the plain table must now do exactly that |
| `cellIsNonEmpty` | reason contrasts the two mechanisms; the plain table must now check **both** a nested `<img>` and `data-image` |
| `afterStructuralEdit` | reason says only the fill-table clears the stash; both now do, so it moves to `TWINS` |

**`refreshAlignButtons` is a listed `TWIN`**, and `test_twins_are_identical` normalises and
compares the two bodies. Its `focusCell`-null fix must land **byte-identically in both files** and
stay in `TWINS`. Patching only `table_editor.js` reddens the guard, and "fixing" that by
reclassifying it would leave the fill-table toolbar painting a stale alignment.

**Fixing the body is not enough for the fill table — its call site makes the fix unreachable.**
`filltable_editor.js` invokes `refreshAlignButtons()` from exactly three places: inside
`refreshToolbarState()` *after* the `if (!focusCell) return;` gate, and from the two
`[data-halign]`/`[data-valign]` click handlers, which only run with a cell focused. So in the
null-focus state — which this slice newly manufactures via the required disconnect-clearing, and
newly exposes because the toolbar no longer hides — the function is never called and the stale
`is-on` survives. **Hoist the `refreshAlignButtons()` call above that early return too**, alongside
the `[data-cmd]` loop and the `isAnswer`/`isImage` derivations. Pinned by a test that deletes the
row holding the focused cell and asserts no `[data-halign]` button carries `is-on`.

**After the four hoists, `if (!focusCell) return;` is DELETED from `filltable_editor.js`'s
`refreshToolbarState` — say so, or two implementers write two different files.** Once the
`[data-cmd]` loop, the `isAnswer`/`isImage` derivations, the `imageAlt`/size-select/Remove-image
visibility lines and the `refreshAlignButtons()` call have all moved above it, the **only**
statement still behind the gate is `if (answerBtn) answerBtn.classList.toggle("is-on", isAnswer);`
— and with `isAnswer` now null-safe (`!!focusCell && …`), that line is correct with no focus too.
Leaving the gate in place would keep the Answer-cell button painted `is-on` from a **deleted** cell,
the very stale-state bug the align-button fix exists to close. The gate joins the
"delete the dead thing in the same change" list alongside `.table-editor__toolbar[hidden]` and the
`toolbar.hidden = false` lines. (The unrelated `if (!toolbar) return;` on the function's first line
is **not** part of this and stays.)

### Server side

**`TableElement._cell`** gains an image branch **before** the text fallback, mirroring
`FillTableElement._cell`:

- `media` must be an `int` and **not** a `bool`.
- `alt` coerced to `str`.
- `size` validated against the four tokens and **coerced to the stored default (`full`) on junk** —
  C1's precedent, where an unknown image `size` coerces (a lossless default exists) while an
  unknown callout `kind` raises (none does).
- **`size` is ALWAYS written on an image cell** (absent → `"full"`), unlike `kind`/`header`/spans,
  which are present-only-when-set. Consequence, accepted: the first save of a pre-feature fill
  table adds the key to its image cells (**DB:** 31 cells). This does *not* touch the
  byte-identity invariant, which covers **text** cells of non-spanning plain tables only. Because
  the key is always present **after normalization**, both render partials, both editor templates
  and `_ser_fill_table` (which normalizes first) may read `cell["size"]` unconditionally.
  **`_ser_table` may not** — it is forbidden to normalize, so it sees raw stored cells where the
  key can be absent; it uses `.get` throughout (see the `_ser_table` guards below).
- **Invalid `media` degrades to an empty *text* cell** — `{html: "", halign, valign}` with **no**
  `kind` key. Never raise, never render a broken image.

**`FillTableElement._cell`'s image branch gains the same validated/coerced `size`.**
`canonical_cells` passes non-answer cells through by reference, which is correct as-is.

**`_sanitized_data` — the work is on `TableElement`, not the fill table.**

- **`TableElement._sanitized_data`** has no `kind` branching at all: it sanitises every dict cell
  unconditionally. It gains a `kind == "image"` skip that leaves `media`/`size` untouched, writes
  **no** `html` key, and **strips `alt`** (`cell["alt"] = alt.strip()`), matching what
  `FillTableElement._sanitized_data` already does — otherwise the two tables store different bytes
  for the same authored alt text, and twin-drift discipline would not catch it (different files).
- **`FillTableElement._sanitized_data` already has that branch** and needs **no change**. Stated
  explicitly because this paragraph previously sat under the fill-table text and read as if it did.

**Shared image resolution.** `FillTableElement.resolve_image_cells` is already a `@staticmethod`
shared between the model and the form — deliberately, so the two cannot diverge on the
unresolved-asset fallback. The Table needs the same logic with a **different empty-cell shape**,
so it lifts to a shared helper parameterised by that shape.

**Named concretely**, since it has four callers across two modules: a module-level
`resolve_image_cells(cells, *, empty_cell, course=None)` in a new `courses/tablecells.py`
(mirroring how `courses/filltable.py` already hosts logic shared between a model, a form and a
view). `empty_cell` is a callable taking the original cell and returning the fallback, which is
what lets the two models differ (`kind:"static"` for the fill table, no `kind` for the plain
table) while sharing one definition of the unresolved-asset behaviour.
**`FillTableElement.resolve_image_cells` survives as a thin delegating `@staticmethod`** — its
docstring is one of the artifacts this slice must invert, and `tests/test_filltable_editor_partial.py`
calls it by name.

It must **not** be copied. The analogy, not a guarantee: the same duplication between the two JS
editors eventually needed a dedicated guard (`tests/test_editor_twin_drift.py`, 163 code-identical
lines). That test reads only the two JS files and has **no visibility into Python**, so it will not
catch divergence here — single-definition-by-construction is the whole defence, which is why the
helper is one function rather than two methods.

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
   `courses/builder.py` (`("image", "video", "gallery", "filltable")`) and two in
   `courses/views_manage.py` (both `("image", "video", "dragtoimagequestion", "gallery")`). Add
   `"table"` to **the builder tuple only**, mirroring `filltable`, which is deliberately absent
   from the other two. Consequence, matching existing fill-table behaviour: on the
   `views_manage` GET render path `self.course` is `None`, so `resolved_grid_cells` resolves
   **unscoped** against already-validated stored data — acceptable, because scoping is a
   *save-time* guard. If `"table"` is omitted from the builder tuple, `self.course` stays `None`
   on the save path too, the guard pattern (`if img_ids and self.course is not None`) becomes a
   check that **never fires**, and a crafted POST can attach a foreign course's asset with every
   test still green.

A `resolved_grid_cells` property re-renders the **submitted** grid on a rejected save. It
**inherits sanitisation from `_grid_data`** and must **not** add a second pass: `_grid_data`
already returns `model._sanitized_data(model.normalize_data(parsed))` on the bound-invalid branch,
and `resolved_grid_cells` sources from `grid_data`. That existing path is where a self-XSS was
caught during the spanning-table work, so the test here is a **regression pin on behaviour that
already holds**, not new work. Adding a redundant sanitise would, for the plain table, re-run over
already-sanitised HTML on every editor render.

### Transfer (export / import)

**Five** sites. Missing any one breaks export silently — the element round-trips but its image
does not.

| site | change |
|---|---|
| `_val_table` | widen the per-cell `allowed` set with `kind`/`media`/`alt`/`size`; validate per the reject/tolerate table below; return media refs via `_require_media` |
| `_ser_table` | currently `return dict(el.data)`; must walk cells and register each image cell's asset |
| `_element_mids` | routes **by type key**; `table` currently falls through to the scalar `data.get("media")` and returns nothing — without a `table` branch the file is omitted from the zip and import then `KeyError`s |
| `_build_table` | remap each image cell's local string id → the real asset pk, as `_build_fill_table` does. **Ordering is load-bearing: remap the raw archive dict FIRST, then `normalize_data`.** Reversed, the string local id has already failed `_cell`'s `isinstance(media, int)` test and degraded the cell to an empty text cell — a silent, total loss of every imported cell image with no error. The round-trip test pins it. |
| **`_ser_fill_table`** | **does not copy the cell** — it builds an explicit `out_cell` literal of `{kind, media, alt, halign, valign}` and then carries `header`/`colspan`/`rowspan`. `size` is not in that literal, so without this change every fill-table export silently reverts every image cell to `full` |

**The serializers gate three in-process paths, not just export.** `duplicate-unit` is the obvious
one, but `courses/builder.py::duplicate_element` → `_copy_below` calls
`_export.build_element_export` + `_importer.graft_elements` in-process as well, and the **element
clipboard paste** path (`#213`/`#215`) rides the same machinery. So a missing `size` in
`_ser_table` / `_ser_fill_table` silently degrades **duplicate-unit, duplicate-element and
clipboard paste** alike. The transfer test row therefore also covers "duplicate an image-cell table
element and assert `size` survives".

`FORMAT_VERSION` **7 → 8**. **Five existing tests hard-assert the old value and go red**; they
are Definition-of-Done updates on the transfer task, listed here because the "scope test runs
narrowly" discipline means an implementer running only `test_table_transfer.py` would see none of
them: `tests/test_link_transfer.py`, `tests/test_tabs_transfer.py`, `tests/test_transfer_schema.py`
and `courses/tests/test_image_size_transfer.py` (all `assert FORMAT_VERSION == 7`), plus
`tests/test_transfer_export.py` (`manifest["format_version"] == 7`).

**Two of them carry the version in the function NAME** — `tests/test_link_transfer.py` and
`tests/test_tabs_transfer.py` both define `test_format_version_is_7`. Changing only the assertion
leaves a name that lies about what it checks. **Rename both to the version-agnostic
`test_format_version_is_current`** (the shape `courses/tests/test_image_size_transfer.py` already
uses with `test_format_version_is_bumped`), as part of the same Definition-of-Done item. A sixth site is a **comment**,
not an assertion, so nothing reddens: `tests/test_table_transfer.py` carries "table imports through
the full gate (4 <= FORMAT_VERSION=7) …" — in the one file the transfer task certainly opens.
Update it too; this spec treats stale comments as first-class artifacts.

**`_ser_table` must NOT call `normalize_data`, and must NOT mutate `el.data`.** Two traps, both
specific to this function:

- `_ser_fill_table` opens with `data = el.normalize_data(el.data)`. Copying that literally would
  change exported bytes: `TableElement.save()` calls only `_sanitized_data`, **never**
  `normalize_data`, so nothing at the model layer guarantees a stored row is rectangular or that
  its cells carry `halign`/`valign`/`html`. A row written by `objects.update()`, by a data
  migration, or by any future ad-hoc path can therefore hold ragged shapes. Normalizing at export
  would rectangularise them and inject defaults — silently altering archive bytes and colliding
  with the byte-identity invariant. `_ser_table` therefore walks the stored cells as-is.

  **Correcting an earlier draft's false attribution:** no *shipped* path produces such a row today.
  `courses/lal_loader/builders.py` calls `TableElement.objects.create(data=TableElement.
  normalize_data(el["data"]))` — it **does** normalize — as do `seed_demo_course`, `_build_table`
  and `TableElementForm.clean_data`, and `_cell` always writes `html`/`halign`/`valign`. The
  defensive rules below stand as **defence-in-depth against the missing model-layer guarantee**,
  not as a response to a live producer. Citing the LAL importer as that producer was wrong, and is
  recorded here because an unchallenged false mechanism is this project's recurring review failure.
- `dict(el.data)` is a **shallow** copy: row lists and cell dicts are shared with the live
  instance. Assigning `cell["media"] = ids.register(asset)` in place would replace real pks with
  local string ids on the in-memory element, and duplicate-unit would then persist that. Build
  fresh rows, exactly as `_ser_fill_table`'s "never mutate `el.data`" comment demands.

**`_ser_table` reassembles the top-level dict by shallow copy**, replacing `cells` only when the
stored value is already a list and leaving every other top-level key — and their order — untouched.
Copying `_ser_fill_table`'s explicit five-key literal would inject `header_row`/`header_col`/`border`
defaults into a legacy row that lacks them (the same byte-changing failure the no-normalize rule
exists to prevent), while an unconditional `{**dict(el.data), "cells": rows}` would append a `cells`
key to stored data that has none.

**`_ser_table` needs the two guards `normalize_data` would otherwise have provided.** Forbidding
that call means the walk sees raw stored shapes:

- **Defensive traversal.** Skip non-list rows and copy non-dict cells through untouched
  (`isinstance` guards mirroring `_sanitized_data`, which carries them for exactly this reason).
  Today `dict(el.data)` never touches cells so it cannot fail; after this change a bare
  `c.get("kind")` over a non-dict cell raises. Pinned by a transfer test exporting a table whose
  stored data has a ragged row and a non-dict cell.
- **Unresolved-pk fallback.** A cell's `media` is a bare int with no FK protection, so a dangling
  pk is reachable and `ids.register(assets[pk])` would `KeyError` — 500ing both export and
  duplicate-unit. An unresolved pk degrades to the table's empty-cell shape
  (`{html: "", halign, valign}`, **no `kind`**) with `header`/`colspan`/`rowspan` carried through,
  matching both `_ser_fill_table` and the new render-side fallback.
  **Read those keys with `.get`, not subscripting.** `_ser_fill_table` can safely write
  `"halign": c["halign"]` only because it normalised first; `_ser_table` must not, so it uses
  `.get` for **every key it reads** — `kind`, `media`, `size`, `alt`, `halign`, `valign` — not just
  the alignment pair. The natural implementation copies `_ser_fill_table`'s opening line
  (`img_pks = [c["media"] for … if c.get("kind") == "image"]`), which is safe there only because it
  normalised first. By this spec's own argument, a stored `{"kind": "image"}` with no `media`, or an
  image cell written straight to the model without `size`, is reachable — and subscripting either
  500s export *and* duplicate-unit. **A `kind:"image"` cell whose `media` is missing or not an int
  takes the same empty-text-cell fallback as an unresolved pk.** The export test fixture therefore
  covers a ragged row, a non-dict cell, a cell missing `halign`, an image cell missing `media`, and
  one missing `size`.

**Per-field import policy for `_val_table`** (resolving the reject-vs-tolerate ambiguity; the
precedent is that `_val_table` already **rejects** an out-of-enum `halign`/`valign` even though
the model coerces them):

| field | `_val_table` |
|---|---|
| `kind` | reject if present and not the literal `"image"` |
| `media` | reject via `_require_media` if absent or not a known ref on a `kind:"image"` cell |
| `alt` | tolerate as a type, bounded by `check_str(..., max_length=255)` — but **only because the model is bounded to match** (see below); an unmatched import bound makes an authorable table un-importable |
| `size` | **coerce** to `full`, matching `_val_image`'s intent — but see the exact form below; do **not** copy its `setdefault` |

**The `alt` bound must be enforced at BOTH ends, or a course cannot round-trip.** A naive "parity
with `_val_image`" argument does **not** hold: `ImageElement.alt` is a
`models.CharField(max_length=255)`, so `_val_image`'s import bound mirrors a bound the model
already enforces. A table cell's `alt` lives in a `JSONField` — `_cell` only coerces it to `str`,
and neither editor's alt input carries a `maxlength`. Left as-is, an author can save a 300-character
alt, export it **successfully**, and have the resulting archive **rejected on import**: a course
that cannot round-trip through its own export. So this slice bounds the model end too:

- **`_cell` truncates: `alt = str(alt)[:255]`** on both `TableElement` and `FillTableElement`.
- **Both editors' alt inputs gain `maxlength="255"`** (`_edit_filltable.html`'s existing
  `[data-image-alt]` input and `_edit_table.html`'s new one).
- Pinned by a **round-trip test using a 300-character alt**: save → export → import, asserting it
  is truncated at save and never rejected at import.

**The allowlist stays flat** (not partitioned by kind), so an archive text cell may legally carry
`media`/`alt`/`size`. That is harmless — `TableElement._cell`'s text branch drops them, and
`_element_mids`/`_build_table` key on `kind == "image"` — and is stated so nobody adds per-kind
key partitioning the model does not need.

**The exact form of the `size` repair, because `_val_image`'s cannot be copied.** `_val_image`
writes `data.setdefault("size", "full")` **because its `_exact_keys` check requires the key to be
present**. `_val_table` has no per-cell `_exact_keys` — its per-cell check is `set(cell) - allowed`,
which tolerates absence — so `setdefault` is both unnecessary and actively wrong: applied to every
cell it would write `size` onto **text** cells in the archive dict, which this spec insists never
carry it. Two things follow:

- **Scope:** the repair runs on `kind == "image"` cells **only**.
- **Form:** `if cell.get("size") not in CellImageSize.values: cell["size"] = "full"` — a
  value-repair, not a `setdefault`. Absence is legal on the wire; the model supplies the default.

**Why coerce rather than reject.** The nearest precedent is not `halign`/`valign` but `_val_image`,
added by C1 for a field of the **same name with the same lossless default**, which coerces and
carries the comment: "A cosmetic field with a lossless default must never fail an import: `full` IS
the pre-feature rendering. (Contrast `_val_callout`, which rejects an unknown `kind` — a kind has
no safe fallback.)" That reads as a general rule about cosmetic fields, so rejecting here would
leave it standing as a false statement about the codebase. Coercing also removes the model-vs-archive
asymmetry an earlier draft introduced: **both layers now coerce `size`**, and only genuinely
unrecoverable input (a bad `media` ref, an unknown cell key) is rejected.

**`_val_fill_table` stays lenient on `size`** and gains no symmetric rejection. Its docstring
commits it to being "intentionally more lenient than `_val_table`", leaving value-enum drift for
`normalize_data` to repair. The strictness asymmetry between the two validators is **intentional
and pre-existing**; do not "fix" it.

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
| archive carries `size` outside the four tokens | coerced to `full` by `_val_table`, matching `_val_image` |
| archive carries an unknown cell key | rejected (exact allowlist, unchanged) |
| merge would absorb an image cell | `absorbedNonEmpty` raises the existing confirmation; on confirm the image cell **is discarded**, on cancel nothing changes. It does **not** block. |

`size` behaves identically on both the model and archive paths — always coerced, never rejected —
matching `_val_image`'s stated rule for cosmetic fields with a lossless default. Rejection is
reserved for genuinely unrecoverable input: a bad `media` ref, an unknown cell key, an out-of-enum
`halign`/`valign`.

`_table_has_math` reads `cell.get("html", "")`, so an image cell with no `html` key cannot raise
there — **verified, no change needed**.

`courses/recolour/` needs **no behavioural change**: `source.py` emits `cell.get("html")` and
`dbscan.py` guards with `if cell.get("kind") not in (None, "static"): continue`, which correctly
skips an image cell (`kind == "image"`). But `dbscan.py`'s comment — "TableElement cells carry no
`kind` at all, so the guard is a no-op there" — becomes **false** and must be updated. This repo
has source-scanning tests that read comments, so a stale comment here is not cosmetic.

## Testing

Each claim is owned by the **cheapest layer that can see it**. Every test names a specific mutant
and must be shown RED before it counts.

| layer | owns |
|---|---|
| Model unit | `_cell` image branch (both models); `size` **always written** on an image cell; junk-`size` coercion; invalid-media degradation to a `kind`-less text cell; **span preservation** in the shared resolver; `TableElement._sanitized_data` writing no `html` key and **stripping `alt`**; text cells still normalising byte-identically; `TableElement.resolved_cells` resolves and `render()` uses it |
| Form | course-scoping **raises** with a foreign pk and with an in-course non-image asset; **the builder actually passes `course=` for `table`** (a separate test — without it the guard is a silent no-op); rejected-save re-render routed through `_sanitized_data` |
| Transfer | all **five** sites; round-trip with a real asset asserting `size` survives **for both table types**; `_ser_table` leaves `el.data` unmutated; `_ser_table` survives a ragged row and a non-dict cell; `_ser_table` degrades an unresolvable pk to an empty text cell with spans carried; a legacy non-normalized table's export bytes are unchanged; a pre-feature archive still imports; out-of-enum `size` **coerced** by `_val_table` and **tolerated** by `_val_fill_table`; a **300-character `alt`** truncates at save and imports without rejection; **duplicate-element** and **clipboard paste** preserve `size`; `FORMAT_VERSION` bump |
| Template | both cell partials emit `<img>` + `data-zoomable` + `cell-img--<size>`; **a render-level byte assertion on `TableElement.render()`'s `<td>` output for a text cell, before/after the factoring** (NOT `test_e2e_math_reflow_dom.py`, which renders no template); **`_table_cell.html`'s last byte is neither `\n` nor `\r`**; the print block follows the preset block in `courses.css`; `.filltable__img` no longer declares `max-width`; **`editor.css` carries `[data-image-remove][hidden] { display: none; }`** |
| Editor / JS regression | both editors' `serialize()` emit the image branch with `size` and no `html` key; an untouched fill-table image cell round-trips `size` through an editor save; header-toggling an image cell then Remove image restores the stashed HTML; a not-yet-previewed image cell counts as non-empty for the merge confirmation; `test_editor_twin_drift.py` `EXPECTED_COUNTS` re-derived and every newly-common function classified; every `table-editor__*` class the JS emits is styled (`tests/test_table_css.py` exists because that drift was a real shipped bug); every `#ed-*` reference resolves to a defined sprite symbol; the Full label carries the `"image size"` gettext context; editor-preview widths strictly increase Small < Medium < Large; **the JS `CELL_IMAGE_DEFAULT`/`CELL_IMAGE_INSERT` literals equal the Python constants, in both editor files** |
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
must no longer change the image's rendered width. Nothing below the browser layer can observe this.

The shape must be one where **the cap provably binds in both variants**, not merely "a bounded
preset" — the measurement table above shows a bounded preset can still be cell-bound
(`min(100%, 160px)` renders 112.4px in the 5-col all-images shape, still driven by the column), and
such a shape would fail on the *correct* build. Use the **MEASURED** 5-col image-plus-four-text
shape at **Medium**: 160.0px with short neighbour text and 160.0px with long neighbour text. The
same shape at `full` (426.2 → 285.7px) is the natural control, asserting the defect is real.

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
- CSS carrier is `.cell-img` + `.cell-img--<size>`, shared by both tables; the base rule declares
  no `max-width`, which removes the equal-specificity conflict rather than relying on source order.
- A `@media print` block bounds `full` at 170mm; Small/Medium/Large are already absolute.
- Merge **confirms and discards** an absorbed image cell; it does not block.
- `size` is always written on an image cell **by `normalize_data`**, so every reader of
  **normalized** cells may subscript `cell["size"]` directly. `_ser_table` is the one reader that
  is forbidden to normalize, so it must use `.get` for every key — the invariant does not reach it.
- The shared resolver is `courses/tablecells.py::resolve_image_cells`; `FillTableElement`'s
  staticmethod stays as a delegator.
- The plain table's stash is cleared on structural edits, moving `afterStructuralEdit` to `TWINS`.
- Remove image with no stash yields an **empty** text cell, which is the common path.
- The new picker hook is `window.libliTablePickImage`, resolving its editor from the button; the
  button carries **both** `data-pick-media="image"` and `data-pick-mode="cell"`.
- The JS defaults are **hard-coded literals** (`CELL_IMAGE_DEFAULT`/`CELL_IMAGE_INSERT`) pinned to
  the Python constants by a source-level test; JS cannot read a `TextChoices`.
- `alt` is bounded at **255 at both ends** — truncated in `_cell`, `maxlength` on both inputs — so
  an authorable table always re-imports.
- Per-cell image controls are **hidden**; `[data-cmd]` and the image button are **disabled**.
- The editor `--full` preview is bounded in **both** axes (`100%` × 200px), never uncapped.
- `serialize()` **guards** the `mapColours` call; no `return` inside the `forEach` callback.

## Line-number policy

This spec cites code **by symbol name**, not line number. An earlier draft's line citations had
already drifted by 1–3 lines against the current tree, which erodes the verification value they
were meant to add. Implementers should locate symbols by name.
