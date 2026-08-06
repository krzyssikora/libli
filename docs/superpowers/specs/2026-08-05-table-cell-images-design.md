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

| shape | `max-width: 50%` | `max-width: 160px` |
|---|---|---|
| 2-col img+text | 291.7px | 160.0px |
| 3-col all images | 99.3px | 160.0px |
| 5-col img+text | 213.1px | 160.0px |
| 5-col all images | 56.2px | 160.0px |
| 7-col img+text | 162.1px | 160.0px |

**5.2× spread** for the percentage versus **no spread** for the absolute cap (uniform 160.0px in
every shape measured). The absolute-cap column above is the corrected rule: `min(100%, Npx)` was
shipped first and Task 9's browser measurement found it collapses to a bare `max-width: 100%` for
column-sizing purposes (the unresolvable percentage makes `min()` degenerate), so it does **not**
in fact bind uniformly — see the Task 9 spike report. Dropping the percentage term to a bare
`max-width: Npx` fixes the 5-col all-images case too; the trade is that an all-image row now
widens the table (scrolling `.el--table__scroll`) rather than shrinking the images. Reusing
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

**The tokens live in one ordered place, with fully-qualified names given once.** Define a
`TextChoices` (mirroring `ImageElement.Size`) **nested on `TableElement`** — so the three names are
**`TableElement.CellImageSize`**, **`TableElement.DEFAULT_CELL_IMAGE_SIZE = "full"`** and
**`TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE = "medium"`**, not module-level names in
`courses/models.py`. The distinction is not cosmetic: it is a different import surface for the three
consumers that depend on it — `payloads.py`'s value-repair (`TableElement.CellImageSize.values`), the
form properties (`form.cell_image_sizes` returning `TableElement.CellImageSize.choices`), and the
source-level test that imports both constants to compare them against the JS literals. Nesting on the
model mirrors `ImageElement.Size` and keeps `MAX_ROWS`-style company. Where this spec later writes
`CellImageSize.choices` / `.values` unqualified, it means the nested attribute. A `TextChoices` gives an **ordered** sequence for the
select (Small → Medium → Large → Full) and a membership test for validation; a bare `set` would
render the select in arbitrary order. Shared by `FillTableElement`, both forms, both editor
**templates** and the transfer validators — one definition for the **ordered choices and the membership
test**.

**Scope of "no duplicated literals", stated precisely:** only the **JS** copies are pinned (by the
source-level test below), because JS cannot import the constant. The bare `"full"` literal is accepted at
Python and template *sinks* where it reads more clearly than the dotted path — `_val_table`'s repair
(`cell["size"] = "full"`), `_ser_table`'s `c.get("size") or "full"`, and `|default:'full'` in all four
partials. Both Python sites already import `TableElement` (`payloads.py` uses `TableElement.BORDERS` and
`MAX_ROWS`), so spelling them `TableElement.DEFAULT_CELL_IMAGE_SIZE` is equally correct and equally
acceptable. What is **not** acceptable is a *different* default appearing anywhere.

**The JS layer cannot read a `TextChoices`, so it needs its own named carrier.** Both editor
scripts need the two defaults — `serialize()` reads `td.dataset.size || CELL_IMAGE_DEFAULT` and
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

**The duplication of `ImageElement.Size` is deliberate, and the shared msgids are the point.**
`ImageElement.Size` already has exactly `small`/`medium`/`large`/`full` with exactly the labels this
slice mandates, so `CellImageSize` is a second identical enum. It is **not** aliased
(`CellImageSize = ImageElement.Size`) or subclassed, because the two scales are independent: the
*tokens* coincide today but the *rules* behind them do not (percentages of a containing block versus
absolute square caps), and this spec's own reason for not reusing `ImageElement.size` is that `full`
would drag `max-height: 100dvh` into a cell. A shared enum would couple future edits to one scale to
the other. The four **labels intentionally share `ImageElement.Size`'s msgids** — that is a feature,
not drift: it is what keeps the translations in one catalog entry each and is exactly why the i18n
split below must be copied rather than re-invented. No enum↔enum drift pin is added; the i18n test
below covers the only part that can silently go wrong.

**i18n — the existing entries are asymmetric.** `ImageElement.Size` has exactly **one**
context-forked label: `FULL = "full", pgettext_lazy("image size", "Full")`. `SMALL`/`MEDIUM`/
`LARGE` are bare `_("Small")`/`_("Medium")`/`_("Large")`. Reuse that **same split** — bare `_()`
for the first three, `pgettext_lazy("image size", "Full")` for Full. Wrapping all four in
`pgettext_lazy` would mint three brand-new msgids that ship untranslated and invite a wrong
`makemessages` fuzzy pre-fill. **Wherever this spec writes the bare literal `"full"` as a JS default,
it means `CELL_IMAGE_DEFAULT`** (the same aliasing note already given for `EDITOR_INSERT`), and the
mandated source-level pin must assert not only that each constant's **declaration** matches the Python
value but that it is actually **used** — symmetrically for both: `serialize()` uses
`CELL_IMAGE_DEFAULT`, **and `setImageCell` uses `CELL_IMAGE_INSERT`**, in both editor files. Otherwise
an implementer who writes the literal (`|| "full"`, or `|| "medium"` in `setImageCell`, whose only
consumer it is) leaves the constant declared-but-unused and the pin silently guards nothing.
The bare msgid `"Full"` is already taken by `courses/forms.py`'s
structure preset (feminine `"Pełna"`), which is why Full alone needs the context (masculine
`"Pełny"`). A source-level test pins that Full carries the `"image size"` context.

### Rendering

**`TableElement` gains its OWN delegating `@staticmethod resolve_image_cells(cells, course=None)`**,
exactly mirroring `FillTableElement`'s and supplying the plain table's `empty_cell` internally.
Without it the plain table would need an `empty_cell` callable at **two** call sites —
`TableElement.resolved_cells` and `TableElementForm.resolved_grid_cells` — and the
"single-definition-by-construction is the whole defence" claim below would be **false for the plain
table**: two hand-written lambdas, no Python-side twin-drift guard to catch their divergence, and an
obvious way to get them subtly different (the model side would naturally be spelled `c["halign"]`,
mirroring today's `FillTableElement.resolve_image_cells`, while the form side is written out here with
`.get`). One delegator per model, one `empty_cell` per model. Both `resolved_cells` and
`resolved_grid_cells` call the delegator, never the shared helper directly.

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

**The double `normalize_data` per render is accepted, and named so it is not mistaken for an
oversight.** `resolved_cells` itself begins from `normalize_data(self.data)["cells"]` (that is what
the fill table's does), so `render()` normalizes twice over up to **7,246** cells. This is the
existing `FillTableElement.render` shape and is adopted unchanged for symmetry. **The editor render
pays the same double cost** (see `_edit_table.html` below — `grid_data` is uncached, so the
controls strip and `resolved_grid_cells` each run it), so this is a consistent, pre-existing
property of both paths rather than an asymmetry needing justification. Avoiding it here would mean
`render()` reaching past `resolved_cells` into the shared resolver and duplicating its call
signature; cheap consistency beats a micro-optimisation on a path already `in_bulk`-bound.

`tableelement.html` currently emits `{{ cell.html|safe }}` on all five of its branches (four of
which are `<th>`). Factor the cell body into **a new `_table_cell.html`**, included from all five
branches, so they cannot drift and an image in a header row is handled once. Path:
`templates/courses/elements/_table_cell.html`, beside `_filltable_cell.html`. The path is stated
rather than inferred because `APP_DIRS` is on, so a partial *could* be misfiled under an app's own
template directory and still resolve. (An earlier draft justified this by claiming "a second template
root at `courses/templates/courses/`" — that directory **does not exist**; settings set
`"DIRS": [BASE_DIR / "templates"]`, and the only app-level template roots are `notes/`,
`notifications/` and `tags/`.)

**The image branch's `<img>` carries exactly these four attributes**, stated because the byte rules
below pin the partial's *shape* while leaving its *content* unspecified — and an implementer
following only the testing row would ship an image with no `alt`, an a11y regression in a file
whose sibling already gets this right:

```
<img class="cell-img cell-img--{{ cell.size|default:'full' }}"
     src="{{ cell.media.file.url }}" alt="{{ cell.alt }}" data-zoomable>
```

(rendered on one line, per the byte rules; `_filltable_cell.html`'s existing image branch is the
same attribute set plus its `filltable__img` class.) `alt` joins the template testing row.

**The partial is a TWO-branch `{% if %}`, and the text branch's body is exact.** Stated because the
render-level byte assertion depends on it and because the nearest model has a *three*-way branch the
plain table must not copy (`_filltable_cell.html` also handles `cell.kind == "answer"`):

```
{% if cell.kind == "image" %}<img …>{% else %}{{ cell.html|safe }}{% endif %}
```

The `{% else %}` body is exactly `{{ cell.html|safe }}` — no wrapper element, no whitespace, no
`|default`. That is what makes the text-cell bytes identical to today's five inline
`{{ cell.html|safe }}` sites.

**The partial must be a single line with no leading whitespace and — stated at the byte level —
its last byte must be neither `\n` nor `\r`**, and the `{% include %}` must sit immediately between
`>` and the closing tag — **`</td>` *or* `</th>`**. Four of the five branches are `<th>`, so a rule
phrased only for `<td>` leaves a header-row table's bytes unpinned; the render-level guard below
must likewise assert **both** a plain cell and a `header_row` cell. `{% spaceless %}` strips whitespace only *between tags*, so an indented or
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
  asserts the exact `<td …>…</td>` bytes for a text cell, plus the `<th …>…</th>` bytes for a
  `header_row` cell. Plus a byte-level assertion that `_table_cell.html`'s last byte is not `\n`/`\r`.
  **The fixture cells MUST be non-empty, or the guard cannot fail.** `{% spaceless %}` is
  `re.sub(r">\s+<", "><", …)`, so with an **empty** cell (`html: ""`) the include emits only its
  trailing newline and the render is `<td …>\n</td>` — `>` + whitespace + `<` — which collapses to
  `<td …></td>`, byte-identical to today. Both the trailing-newline mutant *and* the leading-indent
  mutant survive. This is the dangerous default in **`test_table_editor_partial.py`**, which does
  `_render(TableElement())` — `data={}` normalizes to a 2×2 of `html: ""` cells.
  **`test_table_render.py` is NOT such a case** (an earlier draft said it was): every one of its tests
  goes through a `_grid(rows, cols)` helper whose cells are `{"html": f"r{r}c{c}", …}`, always
  non-empty — which makes it the **correct host** for this guard. The whole mechanism below turns on whitespace being **adjacent to text**, so the fixture
  must supply text.
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
**`class="cell-img cell-img--{{ cell.size|default:'full' }}"`**; `_filltable_cell.html` keeps
`filltable__img` alongside it for any fill-table-specific styling.

**The `|default:'full'` filter is not decorative.** A bare `{{ cell.size }}` on a cell without the
key renders **empty**, producing the class `cell-img--`, which matches no rule — and since the base
rule declares no `max-width` (below), *nothing* would then cap the image: a p50 1192px asset
renders at intrinsic width and blows the table out, strictly worse than today's
`.filltable__img { max-width: 100% }`. The render path does normalize (so `size` is guaranteed
present in practice, and this is defence-in-depth rather than a live bug), but the whole reason
`_ser_table` is required to use `.get` everywhere is that "normalization is guaranteed" is exactly
the assumption this spec refuses to make elsewhere. One filter buys the same posture here.
Pinned by a template test rendering a cell whose stored data has **no** `size` key.

**The base rule, written out so the deletion argument below is checkable:**

```
.cell-img { height: auto; display: block; }
```

— and nothing else. No `max-width` (see the specificity argument below), no `max-height`.

**The base rule must NOT declare `max-width`.** `.filltable__img` currently declares
`max-width: 100%`, which has **identical specificity** to a single-class `.cell-img--medium`, so a
preset block authored next to the `.el--table` rules (earlier in the file) would silently lose to
it and every preset would degrade to Full. Reduce `.filltable__img` to `height: auto; display:
block`, put all sizing on `.cell-img--*`, and place the preset block **after** the base rule. This
is the same equal-specificity trap already recorded from the callout slice; removing the competing
declaration resolves it by construction rather than by source order alone.
Once reduced, `.filltable__img` declares nothing `.cell-img` does not, so **delete the rule
outright** — keeping a no-op rule invites a future author to re-add `max-width` and re-open the
trap. The **class stays on the element**; only the CSS rule goes. Two dependents, not one:
`tests/test_filltable_render.py` asserts its presence (and its **absence** on the degraded path), and
`tests/test_e2e_imagezoom.py::test_filltable_image_cell_opens_the_overlay` drives
`page.locator(".filltable__img")`. Both are named so a future "tidy up the dead class" pass sees the
whole surface.

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
two **editor preview** classes, or the editor and the student view disagree — and **each pair lives in
its own stylesheet**, per the same per-file separation the class guard enforces:
`.ta-center > .table-editor__img` / `.ta-right > .table-editor__img` in **`editor.css`**, and the
`filltable-editor__img` pair in **`courses.css`**. (`.ta-center`/`.ta-right` themselves are defined in
`courses.css`; the descendant rules do not need to sit beside them.) Pinned by a measured
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
rule, and the `toolbar.hidden = false` line in each editor's `focusin` handler.
**The rule's deletion is accepted despite cutting against a repo convention, and that is deliberate:**
`.table-editor__toolbar` declares `display: flex`, so that one-liner is the same
author-`display`-beats-UA-`[hidden]` guard the repo keeps at `.btn[hidden]`, `.view-toggle[hidden]`,
`.outline-node[hidden]` and `.checkbox-list label[hidden]` — and the same guard this slice *adds* for
`[data-image-remove]`/`[data-image-size]`. Removing it means a future `hidden` on that toolbar would be
silently inert. Accepted because the toolbar is now permanently visible by design, so a future author
reaching for `hidden` there would be reversing this slice's central decision and should meet a dead
rule rather than a working one. Precisely:

**Every toolbar control gets an explicit predicate.** The premise of this section is that a
live-looking dead control is the defect; leaving any control unclassified reintroduces it. There is
no "and the rest" — this table is exhaustive over both toolbars:

| control | selector | with no focus | notes |
|---|---|---|---|
| B/I/U, math, the five colour swatches | `[data-cmd]` | `disabled = !focusCell \|\| isImage` (fill table: `\|\| isAnswer` too), using the locals derived once at the top of `refreshToolbarState` | swatches come from `_rte_swatches.html`, which is **not** edited |
| Image cell | `[data-image-toggle]` | `disabled = !focusCell` — **and nothing more** | see below |
| Answer cell (fill table only) | `[data-answer-toggle]` | `disabled = !focusCell` | see below |
| Align | `[data-halign]` / `[data-valign]` | `disabled = !focusCell`, **plus** `is-on` cleared | see below |
| Merge / Split / Header | — | already `disabled` in markup; existing logic unchanged | but see the Header **tooltip** note below |
| alt input, size select | `[data-image-alt]` / `[data-image-size]` | **hidden**, not disabled | both editors |
| Remove image | `[data-image-remove]` | **hidden**, not disabled | **`_edit_table.html` only** — the fill table reverts an image cell via its existing `[data-answer-toggle]`, which the plain table has no equivalent of |

Three of those rows are decisions, not transcriptions of today's code:

- **`[data-image-toggle]` must NOT be folded into the `[data-cmd]` loop.** It is a separate button
  with a *different* predicate: it stays **enabled on an image cell**, because that is the re-pick
  path this spec requires ("On an image cell → picker → replace the image, preserving `size` and
  `alt`"). The cheap implementation — widening the loop to
  `querySelectorAll("[data-cmd], [data-image-toggle]")` — disables it on image cells and makes
  re-pick **unreachable**. Give it its own line, guarded like every sibling handle in that
  function (`var imgBtn = toolbar.querySelector("[data-image-toggle]"); if (imgBtn) imgBtn.disabled = !focusCell;`
  — `refreshToolbarState` already guards `mergeBtn`/`splitBtn`/`headerBtn`/`answerBtn`/`imageAlt`) and pin it with a
  test: *focus an image cell, assert the image button is **enabled***.
  Relatedly, **BOTH picker callbacks must no-op when `focusCell` is null** — `libliTablePickImage`
  **and** `libliFillTablePickImage`. The diagnosis below is about the *fill table's* existing callback,
  and the trigger it names (the always-visible toolbar) applies to both toolbars equally, so requiring
  the guard in only the new one would leave the diagnosed file unfixed. Neither hook is visible to
  `test_editor_twin_drift.py` (both are function expressions) nor to `test_colour_glue_drift.py`, so
  nothing would catch the divergence.

  **Reachability, stated once so the spec does not argue both ways:** after the `disabled = !focusCell`
  predicate on `[data-image-toggle]` lands, this path is **not reachable through the UI** — the same
  reason given for tolerating the registry-miss modal. Both guards are therefore **defence-in-depth**,
  not fixes for a live defect, and neither is pinned by a UI test.
  For reference —
  the always-visible toolbar is exactly what newly exposes that path. **The early return must precede
  argument evaluation**, not merely the `setImageCell` body: in the fill-table precedent the callback
  throws while building its own arguments, at `target.dataset.alt || ""`, before `setImageCell` is
  entered at all.

  **And the guard tests `target`, not `focusCell`.** The outer hook captures
  `var target = focusCell;` when the picker opens, and it is that **captured** value the argument list
  dereferences — so `if (!focusCell) return;` would guard a different variable from the one that
  throws. Written out, as the first statement of the returned inner callback in both editors:

  ```
  return function (id, _name, url) {
    if (!target) return;
    …
  };
  ```

  (An earlier draft said the throw is at `td.setAttribute`; with the mandated stash guard first it would
  be `td.hasAttribute` — but the argument-list dereference comes earlier still, which is exactly why the
  guard's position *and* its subject both matter.)
- **`[data-answer-toggle]` was previously unclassified, and would ship live-and-dead.** It carries
  no `disabled` in `_edit_filltable.html` and `refreshToolbarState` only ever
  `classList.toggle("is-on", …)`s it. Once `hidden` is removed it renders enabled with no focus,
  and clicking it does nothing (`toggleAnswerCell(null)` → `if (!td) return;`). It gets
  `answerBtn.disabled = !focusCell`, and joins the e2e "cell-scoped buttons are disabled before any
  focus" assertion.
- **The align buttons need disabling too, not just `is-on` clearing.** Clearing `is-on` fixes the
  *stale paint*; it does not fix *inertness*. Both editors' click handlers gate on
  `if (halignBtn && focusCell)` / `if (valignBtn && focusCell)`, so with the toolbar permanently
  visible an author can click any of six alignment buttons with no cell focused and nothing
  happens. "They are class-toggled, never `disabled`" describes the current code; it is not a
  rationale, and merge/split/header are already disabled on the same reasoning. So: **both**
  `disabled = !focusCell` **and** `refreshAlignButtons` clearing `is-on` when `focusCell` is null
  (the latter still needed, or the toolbar shows an alignment painted from a previously-focused
  cell).
  **The two halves live in different functions, deliberately, because one is a `TWIN` and one is
  not.** `refreshAlignButtons` is a listed `TWIN` whose normalised body `test_twins_are_identical`
  compares, so anything written into it must land byte-identically in both files; `refreshToolbarState`
  is `DIVERGENT` and carries no such constraint. Therefore:
  - the **`disabled = !focusCell` pass** goes in **`refreshToolbarState`**, beside every other
    predicate in the exhaustive table above (no byte-identity burden, and the two editors' versions
    already differ);
  - the **`is-on` clearing** goes in **`refreshAlignButtons`**, byte-identically in both files,
    staying in `TWINS`.

  **`refreshAlignButtons`'s null-focus body must be written out, because the obvious edit kills the
  editor at load.** The current body opens `if (!toolbar || !focusCell) return;` and **both** loops
  dereference `focusCell.dataset.halign` / `.valign`. Simply deleting `|| !focusCell` makes the
  function throw on every null-focus call — and this slice *mandates* an init-time
  `refreshToolbarState()`, which ends in `refreshAlignButtons()`, with `focusCell === null`. The throw
  would fire inside `wire()`, aborting wiring: nothing serializes and every control stays exactly as
  rendered. That is far worse than the stale paint being fixed. Required shape:

  ```
  if (!toolbar) return;
  var h = focusCell ? (focusCell.dataset.halign || "left") : null;
  var v = focusCell ? (focusCell.dataset.valign || "top")  : null;
  // …toggle("is-on", btn.getAttribute("data-halign") === h)  — null matches nothing, so all clear
  ```

  Named mutant: call `refreshToolbarState()` at init with no focus; the guard-deleted variant must go
  RED.

  Left unlocated, two implementers write two different files and one of them reddens
  `test_twins_are_identical`.
- **The Header button's tooltip now lies before first focus.** `refreshHeaderButton` does
  `var locked = focusCell ? headerLocked(focusCell) : true;` then
  `btn.title = locked ? msg("header-locked") : msg("header")`. With the toolbar permanently visible,
  hovering Header with nothing focused shows "Unavailable while the row or column header option
  covers this cell." — a false explanation the author could never reach while the toolbar was hidden.
  **Require the `title` to fall back to `msg("header")` when `focusCell` is null**; the `disabled`
  state already communicates unavailability. `refreshHeaderButton` is a `TWIN`, so this lands
  byte-identically in both editors — and because byte-identity is enforced, the required lines are
  written out rather than left to prose (that one `locked` variable feeds **both** `btn.disabled` and
  `btn.title`, so there is more than one way to satisfy the instruction):

  ```
  var locked = focusCell ? headerLocked(focusCell) : false;   // was: : true
  btn.disabled = !focusCell || locked;                        // unchanged behaviour
  btn.title = locked ? msg("header-locked") : msg("header");  // now truthful with no focus
  ```

  Flipping the fallback to `false` is safe precisely because `btn.disabled` already ORs `!focusCell`.
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
  **The disable loop is not sufficient on its own — the plain table also needs the twin's runtime
  guard.** `filltable_editor.js`'s toolbar click handler carries a second line of defence,
  `if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable"))`, where
  `table_editor.js`'s is a bare `if (cmdBtn && focusCell)`. This spec cites that exact difference as
  the *rationale* for the disable loop and then never requires the guard itself.
  **`table_editor.js`'s click handler gains the `contenteditable` clause**, making it a genuine twin.

  **Justified as defence-in-depth and twin-parity — NOT by a reachable defect, and deliberately
  unpinned at the UI level.** An earlier draft argued the window was live ("right after converting a
  cell, `[data-cmd]` buttons are still enabled") and mandated a mutant test that *converts* a cell then
  clicks `[data-cmd="math"]`. Both are wrong once requirement **(b)** below lands: `setImageCell` ends
  with `refreshToolbarState()`, so on return from the picker `focusCell` is the image cell, `isImage`
  is true, and the `[data-cmd]` loop has already set `disabled = true` before the author can click.
  The proposed test is therefore **unfalsifiable**: Playwright's `.click()` on a disabled `<button>`
  waits for "enabled" and times out, and `force=True` dispatches no `click` event at all — so the
  assertion holds identically with and without the clause. Do not write it. The clause stands because
  the two handlers must be twins and because a future path that leaves the toolbar unpainted would
  otherwise reach a non-contenteditable cell; if it is ever pinned, it must be by directly dispatching
  the toolbar `click` handler with `disabled` cleared, not through the UI.
  **It must also ACQUIRE the three per-cell control handles and their two-way visibility+population
  lines from scratch.** `table_editor.js` contains **zero** occurrences of `imageAlt` and has no
  per-cell control handles at all, so the fill-table bullet's "move these above the early return"
  does not apply here — there is nothing to move. The asymmetry is the point of this list: **the
  fill table relocates and rewrites; the plain table creates.** Same final shape in both
  (`showCellCtl` block above), reached from opposite starting points.
  **All three handles must be acquired ABOVE the init-time `refreshToolbarState()` call**, beside
  `var toolbar = editor.querySelector("[data-table-toolbar]")` — the same hoisting rationale already
  given for `focusCell`. The natural site — beside the new alt-input listener at the *bottom* of
  `wire()`, mirroring the fill table's existing listener block — is **below** the init call, where the
  handles are hoisted-but-`undefined`. Every `if (imageAlt)` / `if (sizeSel)` / `if (removeBtn)` is then
  falsy and the init-time hide never runs, leaving cell-scoped controls visible with nothing focused.

  **The fill table is safe by accident for `imageAlt` ONLY — do NOT read that as "no work needed
  there."** It declares `var imageAlt` at the top of `wire()` (well above `var focusCell`), but it has
  **no `sizeSel`** (the size select is new to that editor too) and **no `removeBtn` at all**, since
  `[data-image-remove]` is rendered in `_edit_table.html` only. Precisely:

  | handle | `table_editor.js` | `filltable_editor.js` |
  |---|---|---|
  | `imageAlt` | acquire (new) | already at top of `wire()` — leave as is |
  | `sizeSel` | acquire (new) | **acquire (new)**, beside `var imageAlt` |
  | `removeBtn` | acquire (new) | **declare it anyway**, though the query returns `null` |

  That last row is load-bearing: the `showCellCtl` block is the same in both editors, so `removeBtn`
  must be a **declared** name in the fill table or the block throws `ReferenceError` inside `wire()`.
  `if (removeBtn)` then simply never fires there — the intended behaviour, not a bug. Left as "safe by
  accident", an implementer takes no action, writes `var sizeSel` beside the bottom-of-`wire()` listener
  block, and ships the fill table's size select **visible with nothing focused**.
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
  no longer connected**, in **both** editors.

  **The predicate must be `focusCell && !focusCell.isConnected` — a bare `!focusCell.isConnected`
  throws.** `focusCell` is `null` until the first `focusin`, and the row/column insert/delete handles
  are hover-revealed grid chrome reachable **from page load**, independent of focus. All four of those
  handlers call `afterStructuralEdit()`, so inserting or deleting a row before ever clicking a cell
  evaluates the predicate with `focusCell === null` and raises
  `TypeError: Cannot read properties of null` — aborting the handler and leaving the grid half-edited
  and **unserialized**. That is a worse failure than the stale-control bug being fixed. So:

  ```
  if (focusCell && !focusCell.isConnected) { focusCell = null; rangeAnchor = null; }
  ```

  `rangeAnchor` is cleared alongside rather than tested separately: `clearRange(false)` runs in the
  same function and `rangeAnchor` is only meaningful paired with a live `focusCell`, so a second
  `isConnected` test on it would be dead. Named mutant: **a row insert before any cell focus** — the
  unguarded form must go RED. Pinned additionally by a test that deletes the row holding the focused
  image cell and asserts the per-cell controls are hidden.

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
- **`window.libliFillTablePickImage` keeps its last-wins single global and is NOT converted.** The
  registry argument above applies verbatim to it — its own comment reads "Single global; assumes
  one fill-table editor per page" — so an implementer will otherwise either unify it (unscoped
  work) or wonder why the reasoning stops at one side. It is a **pre-existing** limitation, no
  worse after this slice, and out of scope; the plain table gets the registry because it is being
  written now, not because the fill table is being left broken.
- On a **hit** the hook returns `function (id, _name, url)` — mirroring
  `window.libliFillTablePickImage`'s shipped shape. **`id` is a STRING** (`media_picker.js` passes the
  raw `data-asset-id` attribute; its own comment says so), so the callback must
  **`parseInt(id, 10)`** before handing it to `setImageCell`. Stated because this spec devotes a whole
  paragraph to `parseInt(td.dataset.media, 10)` for exactly this failure — a string `media` reaches
  `_cell`, fails `isinstance(media, int)`, and the cell silently degrades to empty text — and the same
  string→int boundary exists one layer up, in the hook.
- On a lookup **miss** the hook returns `null`, and `media_picker.js` (which already tests the hook
  for truthiness before using it) does not throw. **Precisely** what happens then: `selectAsset`
  falls past the `fillTargetCb` branch to `if (!targetSelect) return;`, and a table editor page has
  no `select[name="media"]`, so it returns **without** calling `closeModal()` — the author's click
  does nothing and the modal stays open with no feedback. Accepted, not fixed: the miss is
  unreachable in practice because `[data-image-toggle]` is `disabled` with no focused cell, so the
  hook is only ever reached from a button inside a known editor root. Stated so "leaves the field
  untouched" is not mistaken for "closes cleanly".

**Table editor cell markup.** `_edit_table.html`'s grid loop has one
`<td contenteditable>`/`<th contenteditable>` pair and no image branch. It gains an image branch carrying **identical attributes to the existing text branch** —
`class="ta-{{ cell.halign }} va-{{ cell.valign }}"`, `data-halign`, `data-valign` and the
conditional `colspan`/`rowspan` — **plus** `data-image`, `data-media`, `data-alt`, `data-size`,
`tabindex="0"`, and **minus** `contenteditable`. **Written out literally, because one attribute
value is load-bearing:**

```
<td data-image data-media="{{ cell.media.pk }}" data-alt="{{ cell.alt }}"
    data-size="{{ cell.size|default:'full' }}" tabindex="0"
    class="ta-{{ cell.halign }} va-{{ cell.valign }}"
    data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"
    {% if cell.colspan %}colspan="{{ cell.colspan }}"{% endif %}
    {% if cell.rowspan %}rowspan="{{ cell.rowspan }}"{% endif %}>
```

**`data-media` must be `{{ cell.media.pk }}`, not `{{ cell.media }}`.** At this point `cell.media` is
a **resolved `MediaAsset`**, so `{{ cell.media }}` renders `MediaAsset object (5)`; `serialize()`'s
`parseInt` then yields `NaN`, `JSON.stringify` writes `media: null`, and `_cell` degrades the cell to
an empty text cell — **the image is lost on the author's next save with no error**.
`_edit_filltable.html`'s existing branches already use `.pk`. Pinned by a test that reloads the
editor and performs a **no-op save**, asserting the image cell's `media` survives. **It is a `<th>`/`<td>` pair, not one branch** —
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
`_edit_filltable.html` already does it.

**Do not justify that with "it avoids a second `normalize_data` pass" — it does not.** `grid_data`
is a plain uncached `@property` returning `_grid_data(self)` (on the bound-INVALID branch: parse +
`normalize_data` +
`_sanitized_data`), and `resolved_grid_cells` calls `self.grid_data["cells"]`. So
`{% with d=form.grid_data %}` **plus** `{% for row in form.resolved_grid_cells %}` runs `_grid_data`
**twice** per editor render regardless — a cost `_edit_filltable.html` already pays today. Keeping
`d` is about not disturbing the controls strip, nothing more. If the double parse is ever worth
removing, the fix is making `grid_data` a `cached_property` (per-instance, so a bound-invalid
re-render still re-reads the submitted data) — **out of scope here**, and noted only so the false
rationale is not re-derived.

**`serialize()`'s image branch must SKIP `mapColours` — by guarding the call, never by returning.**
The **first statement inside the `forEach` callback** is
`if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });`, which mutates
the cell's subtree on every serialize. On a non-contenteditable image cell that is both wasted work
and DOM mutation inside a node the author cannot edit, so it is skipped — stated as a decision
rather than left an accident.

**But `row.push(cell)` is the LAST statement of that same callback**, so "return before
`mapColours`" would skip the push and **silently delete the cell from the serialized row** — a
column vanishes on save. The only coherent shape is therefore:

- derive `isImage` first, then guard the call **on its own enclosing line** (see the drift-test
  constraint immediately below),
- build the cell object in a kind branch (below),
- and keep **one** `row.push(cell)` after the shared span/header suffix.

**No `return` may occur anywhere inside the `forEach` callback.**

**The guard's SHAPE is constrained by `tests/test_colour_glue_drift.py`, which the spec must name
because it goes red otherwise.** `test_serialize_colour_pass_is_identical` does:

```
needle = "window.libliColour.mapColours(td, { dropUnmapped: true })"
assert _line(table, needle) == _line(fill, needle)
```

— a whole-stripped-**line** equality between `table_editor.js` and `filltable_editor.js`, which
today carry that line identically. Writing the guard **inline**
(`if (!isImage && window.libliColour) …`) changes the plain table's line and **reddens the test**;
worse, the two files need *different* predicates (the fill table must also skip answer cells), so
no inline form can keep them equal. The natural "fix" — dropping the guard — silently reverts a
settled decision.

**Resolution: guard on a separate enclosing line, leaving the needle line byte-identical in both
files.**

**The derivations are part of the requirement — neither callback has them today.**
`filltable_editor.js`'s `serialize()` `forEach` branches **inline** on
`td.hasAttribute("data-image")` / `("data-answer")` and binds no `isAnswer`/`isImage` at all;
`table_editor.js`'s has no branch. Every other derivation instruction in this spec is scoped to
`refreshToolbarState`, a **different function**, so a block referencing those names here would throw
`ReferenceError` under `"use strict"` at `if (hidden.value === "") serialize();` inside `wire()` —
aborting wiring, nothing serialized, every control left as rendered. So the first statements of each
`forEach` callback are:

```
// table_editor.js
var isImage = td.hasAttribute("data-image");
if (!isImage) {
  if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });
}
```

```
// filltable_editor.js
var isAnswer = td.hasAttribute("data-answer");
var isImage  = td.hasAttribute("data-image");
if (!isAnswer && !isImage) {
  if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });
}
```

The fill table's **three existing branch conditions are rewritten to reuse these two locals**
(`if (isImage) { … } else if (isAnswer) { … } else { … }`), so the attribute is read once per cell and
the guard cannot drift from the branch it is meant to mirror.

The predicates differ, the needle line does not, and `test_colour_glue_drift.py` stays green
**untouched** — no assertion is relaxed and no needle is rewritten. The fill table gets the same
guard for the same reason (its answer and image cells are equally non-editable subtrees), which is
what makes the shared line honest rather than a coincidence. A Definition-of-Done item on the
editor tasks, alongside `test_editor_twin_drift.py` and `test_cell_selector_guard.py`.

**`serialize()` must gain a kind branch.** `table_editor.js`'s `serialize()` unconditionally emits
`{html: td.innerHTML, halign, valign}` for every cell. An image cell would serialize as
`html: "<img …>"`, which `sanitize_cell` then strips to `""` on save — **the image is lost with no
error**. The image branch replaces **only** the `{html, halign, valign}` literal: it emits
`{kind, media, alt, size, halign, valign}` and **no** `html` key, and the existing
`colspan`/`rowspan`/`header` suffix — appended *after* the cell object is built — still applies to
both branches. Writing the image branch as an early `row.push({...})` inside the `forEach` would
drop all three. **The image branch's field expressions, verbatim** — because `size` is the *least* dangerous of
them and pinning only it invites inference on the others:

```
{ kind: "image",
  media: parseInt(td.dataset.media, 10),
  alt: td.dataset.alt || "",
  size: td.dataset.size || CELL_IMAGE_DEFAULT,
  halign: td.dataset.halign || "left",
  valign: td.dataset.valign || "top" }
```

**`media` must be `parseInt(…, 10)`.** `td.dataset.media` is a **string**, and
`TableElement._cell`'s image branch requires `isinstance(media, int) and not isinstance(media, bool)`
— so a literal `media: td.dataset.media` passes every server-side test that constructs data directly,
while **every real editor save silently degrades the image cell to an empty text cell**. The fill
table's shipped line is already `media: parseInt(td.dataset.media, 10)`. Named JS-regression mutant:
replace the `parseInt` with the bare `td.dataset.media` and require the round-trip test to go **RED**.

It reads
the size as **`td.dataset.size || CELL_IMAGE_DEFAULT`** (never the bare `"full"` literal — see the
note below): a bare
`td.dataset.size` is `undefined` when the attribute is missing, `JSON.stringify` then drops the key
entirely, and the model coerces it back to `full` — silently demoting a `medium` cell if any path
forgets to write the attribute. Always emitting the key upholds the "every reader may use
`cell["size"]` directly" invariant.

**Focus must reach an image cell.** `table_editor.js`'s `focusin` handler matches
`e.target.closest("td[contenteditable], th[contenteditable]")` and returns early otherwise.
`filltable_editor.js` had to widen exactly this selector to include `td[data-image], th[data-image]`
because such cells are not contenteditable. Without the same widening, clicking a Table image cell
sets neither `focusCell` nor the range anchor: the alt input, the size select and Remove image
never appear, and the cell can never be a merge/split/align target. **Widen the `focusin` selector —
and that is the only selector that widens.**

**Correcting an earlier draft: there is no "post-merge/delete focus fallback" selector to widen.**
That phrase named a site that does not exist. `table_editor.js` carries the `[contenteditable]`
selector at exactly four places — `focusin`, an Enter `keydown`, an `input` handler, and a bare
`[contenteditable]` lookup inside the latter — and **none** of them is a post-structural-edit focus
fallback. The merge and split paths call `kept.focus()` / `anchor.focus()`, which take a **node** and
contain no selector at all; `afterStructuralEdit` never re-seats focus; `table_grid.js` contains no
`focus` or `contenteditable` reference whatsoever. (The fill table's analogous line,
`(kept.querySelector(".filltable-editor__answer") || kept).focus()`, is likewise node-based.) Since
those calls already receive the kept/anchor node directly, an image cell is focusable through them
without any change — the widening they appeared to need was imaginary.

**So the boundary is exactly one site.** `filltable_editor.js` widened **only** `focusin`,
deliberately: an image cell has no caret, so the Enter and `input` handlers must stay
`[contenteditable]`-only. This boundary must be exact because
`tests/test_cell_selector_guard.py`'s new inventory entry is anchored on it, and because the
paragraph below draws attention to these same sites for a different reason (the needle line-wrap
trap), which otherwise reads as an invitation to widen them all.

**`tests/test_cell_selector_guard.py` must be updated in the same change**, and it is a trap in its
own right. Its `INVENTORY` carries `("…/table_editor.js", 'closest("td[contenteditable]', "th")`,
and its own comment documents the hazard: IF the selector is line-wrapped — as it was for
`filltable_editor.js`, though the plain table's four-way widening
(`"td[contenteditable], th[contenteditable], td[data-image], th[data-image]"`) is shorter than the fill
table's six-way one and may well fit on one line — the needle no longer lands on the
`focusin` site and is instead satisfied by unrelated single-line `keydown`/`input` calls, leaving
the widened site **unguarded with the test still green**. The fill table needed a bespoke
full-literal inventory entry for precisely this; add the plain table's twin. A Definition-of-Done
item on the **editor** task, alongside its own siblings — `test_editor_twin_drift.py`'s
`EXPECTED_COUNTS`, `test_colour_glue_drift.py` and `NEVER_ARMED`. (The five `FORMAT_VERSION` sites are
Definition-of-Done items on the **transfer** task; pairing them here would send an implementer to the
wrong checklist.)

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
  3. the new `focusCell && !focusCell.isConnected` clearing block (required below) must be written
     **character-for-character the same** in both files, and sit as **statement two** — immediately
     after `cellStash.clear()` and **before** `clearRange(false)`. Position matters, not just
     bytes: placed after the body's `refreshToolbarState()`/`serialize()` calls, the toolbar is
     repainted from the still-detached `focusCell` and the per-cell controls stay visible — the
     very bug the requirement exists to close.

  Miss any one and `test_twins_are_identical` goes red, where the natural-looking "fix" is to
  reclassify the function back to `DIVERGENT` — silently undoing this decision. The fill table's
  trailing `// fill-table only` comment on that line also becomes false and must be deleted (the
  comparison strips comments, so nothing reddens to prompt it).
- **On an image cell** → picker → replace the image, preserving `size` and `alt`.
  **Both paths are one function.** `filltable_editor.js`'s `setImageCell(td, …)` has a single call
  site serving conversion *and* re-pick, so a literal `td.dataset.size = "medium"` would demote an
  author's `full` cell on every re-pick, while a literal "preserve" would leave a converted cell
  with no `data-size` at all. The rule is **`td.dataset.size = td.dataset.size || EDITOR_INSERT`**.
  **The stash write must be SKIPPED on the re-pick path, or Remove image destroys the author's
  original text.** This is the sharpest edge of "both paths are one function". The precedent stashes
  **unconditionally**:

  ```
  var s = stashFor(td);
  if (td.hasAttribute("data-answer")) { s.answer = …; } else { s.html = td.innerHTML; }
  ```

  On a **re-pick** the cell already carries `data-image`, so `s.html` is overwritten with the
  *preview `<img>` markup*. Remove image (and the fill table's answer-toggle) then restores that
  `<img>` into a contenteditable text cell, which `sanitize_cell` strips to `""` at save — the
  author's original text is **permanently and silently lost**, and the spec's reversibility promise
  is void. Requirement, in **both** editors: guard the stash write with
  **`if (!td.hasAttribute("data-image")) { … }`** so only a genuine text→image conversion records a
  stash. Pinned by a test that converts a text cell, **re-picks a different asset**, then removes the
  image, asserting the **original** HTML is restored — not the preview markup, and not `""`.

  **The plain table's `setImageCell` DOM contract, written out** — the server-rendered `<td>` above is
  pinned attribute-by-attribute, and the JS branch that must produce **the same node in-session**
  deserves the same treatment:

  ```
  td.setAttribute("data-image", "");
  td.dataset.media = String(mediaInt);
  td.dataset.alt   = alt || "";
  td.dataset.size  = td.dataset.size || CELL_IMAGE_INSERT;
  var size = td.dataset.size;              // read AFTER the assignment — see below
  td.setAttribute("tabindex", "0");
  td.removeAttribute("contenteditable");
  td.innerHTML = "";                       // then append the preview <img>
  ```

  **`var size = td.dataset.size;` is required, not incidental.** `setImageCell(td, mediaInt, url, alt)`
  has **no `size` parameter**, so the mandated `classList.add(CELL_IMG_CLASS[size])` would otherwise
  read an undeclared name — `ReferenceError` under `"use strict"`, the same class of defect this spec
  closes twice elsewhere. And it must be read **after** the `|| CELL_IMAGE_INSERT` assignment, from
  `td.dataset.size` rather than any caller-supplied value: reading it earlier or from an argument would
  paint a re-picked `full` cell as `medium`.

  **`removeAttribute("contenteditable")` is not cosmetic.** Omit it and the newly-mandated runtime
  guard `if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable"))` passes on an image
  cell, so `∑` again appends a text node that `serialize()`'s image branch discards — the exact defect
  that guard exists for — and the Enter/`input` handlers, deliberately left `[contenteditable]`-only,
  start firing on image cells. The conversion-path test asserts all of it: the converted cell has **no**
  `contenteditable`, has `tabindex="0"`, and carries all four `data-*`.
  **`setImageCell` must also emit the preview's modifier class.** It rebuilds the preview with
  `img.className = "filltable-editor__img"` — base only. Once `max-width` is stripped from that
  base rule, an in-session conversion or re-pick renders the asset at its intrinsic width (**DB**
  p50 1192px) and drags the editing grid — a regression to an already-shipped feature. Emit the
  base as a lone `className =` assignment plus `classList.add(CELL_IMG_CLASS[size])` against a
  literal-valued map, the same shape as the plain table's — **not** the concatenation
  `classList.add("filltable-editor__img--" + size)`, which leaves only a stem literal in the source
  and is exactly the vacuous-guard cause documented under the editor-preview class names below. **Nothing currently guards this**: `tests/test_table_css.py`
  reads only `TABLE_JS`, so the fill-table editor's class emissions are unguarded — extend that
  guard to `FILL_JS`/`courses.css`, or add a test asserting the class pair on a freshly converted
  fill-table cell.
  **Three durable contracts for that guard.** These are what must survive; the concrete patterns this
  spec gives alongside them are illustrations of the contracts, **verified against
  `test_table_css.py`'s current shape at authoring time** — if that file is restructured, the contracts
  bind and the patterns are re-derived, not copied.

  1. **Per-file, never concatenated.** `table-editor__*` is checked against **`editor.css` only** and
     `filltable-editor__*` against **`courses.css` only**. Today's guard is honest solely because
     `editor.css` contains **zero** occurrences of `filltable`; the moment `courses.css` joins the
     searched text, every plain-table assertion is satisfied by the fill table's rules — because
     `.table-editor__img--small` is a **substring** of `.filltable-editor__img--small` — and all four
     plain-table modifiers can ship unstyled.
  2. **"Named somewhere" and "a base rule exists" are two separate assertions.** A boundary-anchored
     name match must be anchored on **both** sides (a trailing `\b` matches between `g` and `-`, so a
     one-sided form is satisfied by `.table-editor__img--small`), and even a two-sided match is
     satisfied by the alignment rules this spec mandates (`.ta-center > .table-editor__img {`). So the
     name match proves **naming only**; each base rule — `.table-editor__img` in `editor.css`,
     `.cell-img` in `courses.css` — needs its own declaration-level assertion that the rule itself is
     present. Whatever form the plan picks must be **verified to fail when the base rule is deleted**
     (a line-anchored `^` regex needs `re.MULTILINE`, or it matches nothing and the guard destroys
     itself on a correct build).
  3. **Every class must appear as a whole quoted literal in the JS** — which is the entire reason for
     the `CELL_IMG_CLASS` map. A concatenation (`"…--" + size`) leaves only a stem literal, and any
     substring-style assertion then passes with three of four modifiers missing.

  A fourth, mechanical trap for the plan to carry: the emission guard's `cls` values come from
  `re.findall` and carry **no** leading dot, while `test_courses_css_defines_table_element`'s hardcoded
  entries **do** (`".el--table"`, …). Reusing one f-string across both yields `\..el--table`, which
  matches nothing.
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

**The plain table's alt input needs JS wiring, not just markup — the spec previously specified a
dead control.** `table_editor.js` contains **zero** occurrences of `imageAlt`: no handle, no
listener. `filltable_editor.js` carries a whole block the plain table must reproduce —
`imageAlt.addEventListener("input", …)`, guarded on
`focusCell && focusCell.hasAttribute("data-image")`, writing `focusCell.dataset.alt`, updating the
preview `<img>`'s `alt` attribute, then `serialize()`. Without it the new input is typeable and
writes nothing: a live-looking dead control, the exact defect class the Editor-UX section declares
its premise. Two notes:

- The preview lookup **diverges** — the fill table queries `.filltable-editor__img`, the plain
  table must query `.table-editor__img`.
  **But it CANNOT be classified in `test_editor_twin_drift.py`, and trying reddens a green test.**
  That guard's extractor is `_DEF = re.compile(r"^\s*function (\w+)\s*\(")` — **named function
  declarations only**. The alt-input listener is an anonymous `function () { … }` handed to
  `addEventListener`, so it has no name to key on; and `test_no_stale_classification` asserts every
  `TWINS`/`DIVERGENT` name **is** a function in both files, so inventing a key to satisfy a
  classification instruction turns that test RED. This is precisely why
  `tests/test_colour_glue_drift.py` exists — its own docstring says #169's extractor "never sees
  [inline anonymous callbacks] at all". **So: route the divergence risk to a
  `test_colour_glue_drift.py`-style textual guard** (read both sources, compare the listener bodies
  modulo the one intended difference), or accept it unguarded — but do **not** add a
  `test_editor_twin_drift.py` entry.
- Pinned by a test that types into the alt input on an image cell and asserts the serialized JSON
  carries the new `alt`.

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

**The same assertion must cover `[data-image-size]`.** Of the three hidden controls, only the alt
input is provably safe, and only incidentally: `.input` sets no `display` and
`.filltable-editor__alt` has no rule at all. The select cannot inherit that safety because its class
is unspecified — and any layout wrapper or toolbar class that sets `display` re-opens the trap for
both. So either extend the mandated rule to `[data-image-size][hidden] { display: none; }`
(the simplest resolution, and what this spec adopts), or name the select's class and assert it sets
no `display`. The CSS source assertion covers **both** `[data-image-remove][hidden]` and
`[data-image-size][hidden]`.

**Clicking Remove image with no image cell focused is a no-op** (guard on
`focusCell && focusCell.hasAttribute("data-image")`), so the control is inert rather than undefined
should it ever be reachable.

Remove image needs a sprite glyph: the sprite defines no trash/remove symbol today (`ed-minus` is
the nearest and means "delete row/column"), so **add a new monochrome `currentColor`
`ed-image-remove` symbol** rather than overloading an existing one, **defined in
`templates/courses/manage/editor/editor.html`** where the sprite lives. Covered by
`tests/test_table_editor_partial.py::test_toolbar_icons_resolve_to_sprite_symbols` and its
fill-table twin, which assert `refs <= _sprite_symbols()` — named here because this spec names every
other test it touches, and its own line-number policy says to cite by symbol.

**The conversion path paints NOTHING today, and three separate requirements silently depend on it.**
This is the slice's most load-bearing correction, because the Data-flow promise "per-cell controls
appear" has no mechanism behind it. Verified in `filltable_editor.js`:

- `setImageCell` ends by revealing the alt input **directly**
  (`if (imageAlt) { imageAlt.hidden = false; imageAlt.value = td.dataset.alt || ""; }`) and
  **never calls `refreshToolbarState()`** — its own comment says a later `focusin` is not relied
  upon, and indeed `td.removeAttribute("contenteditable")` **blurs** the cell rather than
  re-focusing it.
- `window.libliFillTablePickImage`'s callback does only `setImageCell(...)`, `focusCell = target`,
  `serialize()`.

So on the in-session text→image conversion path, neither `refreshToolbarState` nor `focusin` runs.
Since this spec assigns the size select's and Remove image's **visibility** to
`refreshToolbarState` and the select's **value** to `focusin`, both would stay hidden (and stale if
forced visible) after a conversion — the one moment the author most needs them.

**Requirement, in two parts — and the second is the load-bearing one.**

**(a) `refreshToolbarState` must become the sole owner of per-cell painting, which means making its
visibility lines TWO-WAY and adding population.** Relocating them above the early return is **not
sufficient**, and this is the trap: the existing line is

```
if (imageAlt && !isImage) imageAlt.hidden = true;      // ONE-WAY: only ever hides
```

It never assigns `hidden = false`. Reveal lives exclusively in `focusin` and in `setImageCell`'s
two-liner. So merely moving that line and calling `refreshToolbarState()` would leave all three
controls **hidden** after a conversion — the very state this section exists to fix — and would
**redden a currently-green test**: `tests/test_e2e_filltable.py`'s `make_image_cell` does
`editor.locator("[data-image-alt]").fill(alt)` immediately after the picker click, and Playwright's
`fill()` requires a visible element. Rewrite all three as two-way assignments **plus** value
population, driven by the focused cell:

```
var isImage = !!focusCell && focusCell.hasAttribute("data-image");
var showCellCtl = isImage;
if (imageAlt)   { imageAlt.hidden   = !showCellCtl; if (showCellCtl) imageAlt.value = focusCell.dataset.alt || ""; }
if (sizeSel)    { sizeSel.hidden    = !showCellCtl; if (showCellCtl) sizeSel.value  = focusCell.dataset.size || CELL_IMAGE_DEFAULT; }
if (removeBtn)  { removeBtn.hidden  = !showCellCtl; }
```

**`isImage` must be DERIVED in this function, in both editors — do not assume it is in scope.** In
`filltable_editor.js` it already exists but sits *below* the early return and must move up and become
null-safe (see that bullet). In `table_editor.js` the name **does not exist at all**: the file has zero
occurrences of `isImage`, and the only place this spec derives one for it is inside `serialize()`'s
`forEach` callback — a different function scope. Both files are `"use strict"`, so copying the block
without the derivation throws **`ReferenceError: isImage is not defined`** at the newly-mandated
**init-time** `refreshToolbarState()` call, inside `wire()` — aborting wiring, so nothing serializes
and every control stays exactly as rendered. That is the identical failure mode spelled out for
`refreshAlignButtons` below.

**Position: the `isImage` derivation is the first statement after `if (!toolbar) return;`** — above
**both** the `[data-cmd]` loop and the `showCellCtl` block, in both editors. The `showCellCtl` block
reads as belonging with the per-cell controls, i.e. later; if the derivation drifts down with it, `var`
hoisting makes the predicate `!focusCell || undefined` → falsy → `[data-cmd]` stays **enabled on a
focused image cell**, the exact regression documented for the fill table.

For the same reason the plain table's `[data-cmd]` predicate is written **`!focusCell || isImage`**
using that one derived name, rather than repeating the inline
`!focusCell || focusCell.hasAttribute("data-image")` — one name, one derivation, one place to get the
null-safety right.

**Population, not just visibility, must move here** — `setImageCell`'s deleted two-liner was the
only thing setting `imageAlt.value` on the conversion path, and the size select's value was
previously assigned in `focusin` alone (see the paragraph below, now corrected).

**(b) `setImageCell` must end with `refreshToolbarState()`, in both editors**, replacing its
bespoke two-line `imageAlt` reveal, so one function owns the painting. `refreshToolbarState` is
reached with `focusCell` pointing at the converted cell, so it paints correctly.

**The invariant to preserve is `focusCell === the converted cell` when `refreshToolbarState` runs** —
stated as an invariant rather than as a reordering, because the shipped callback already satisfies it.
`target` was captured **from** `focusCell` when the picker opened, and nothing between opening and
selecting re-seats it (the grid's `focusin` fires only for grid descendants, the modal is an overlay
outside the grid, and `removeAttribute("contenteditable")` blurs but never nulls `focusCell`). So
`focusCell === target` already holds at refresh time even though `focusCell = target` is assigned
*after* `setImageCell(...)`. Hoisting that assignment above the call is therefore **defence-in-depth**,
not a correction — an earlier draft asserted the paint is currently wrong without it, which overstated
the window in the same way the `contenteditable` clause's rationale did.

Pinned by a test that **converts a cell via the picker and never re-focuses it**, asserting all
three per-cell controls are visible **and populated** — the select reading `medium`, the alt input
reading the cell's alt. A test that drives `focusin` cannot see this defect, which is exactly why
the existing suite does not; and `test_e2e_filltable.py`'s conversion gesture is the existing
regression that proves part (a) was done as a two-way rewrite rather than a relocation.

**The select must be populated from the focused cell, not merely shown.** The alt input's
precedent is `imageAlt.value = td.dataset.alt || ""` inside `focusin`; a toolbar-level control
otherwise displays a stale value from the previously focused image cell, so an author focusing a
`full` cell would see "Medium".

**But `focusin` must NOT own the value assignment** — that is what left the conversion path
unpopulated (see the correction above). `focusin` sets `focusCell` and calls
`refreshToolbarState()`, which owns reveal **and** population for all three controls; `focusin`'s
own trailing `if (td.hasAttribute("data-image") && imageAlt) { imageAlt.hidden = false; imageAlt.value = … }`
block becomes redundant and is **deleted in the same change** (it sits immediately after that
function's existing `refreshToolbarState()` call, so leaving it would give per-cell painting two
owners — a drift hazard and a direct contradiction of the "one function owns" premise). It joins the
"delete the dead thing in the same change" list.

A `change` on the select writes `td.dataset.size`, swaps the preview's modifier class (see the
next paragraph — **swap**, not add) and calls `serialize()`. Pinned by a test that focuses two image
cells of different sizes in turn.

**The `change` handler has the same per-editor preview divergence as the alt listener, and the same
invisibility.** It must query `.table-editor__img` in the plain table and `.filltable-editor__img` in the
fill table. Both handlers are anonymous `addEventListener` callbacks, so neither is visible to
`test_editor_twin_drift.py`'s `_DEF` — route the `change` handler to the same
`test_colour_glue_drift.py`-style textual guard as the alt-input listener, or accept it unguarded on the
same terms. Silence here would reintroduce the "two implementers, two different files, nothing catches
it" risk for the control this slice is adding.

**The `change` handler must REMOVE the four modifier classes before adding one.** The only
class-emission mechanism this spec mandates is `classList.add(CELL_IMG_CLASS[size])`, which is safe
in `setImageCell` **only** because that function builds a fresh `<img>` and precedes it with a lone
`className =` reset. The `change` handler mutates an **existing** preview, so `add` alone
accumulates (`table-editor__img--large table-editor__img--small`). All four modifiers are
single-class selectors of **identical specificity**, so the winner is then decided by stylesheet
source order, not by the author's pick — the select silently shows the wrong size until reload. This
is the same equal-specificity trap this spec already documents twice for the base rules. So:
iterate `CELL_IMG_CLASS`'s values with `classList.remove` before the `add`, in **both** editors.
Pinned by a test that changes size **twice** on the same cell and asserts exactly one modifier class
remains.

**Two fill-table editor sites carry `size`, and missing either reverts every image cell to `full`
on every save** — the same defect class as the `_ser_fill_table` omission, but on the far more
frequent path:

- `filltable_editor.js`'s `serialize()` image branch currently emits exactly
  `{kind, media, alt, halign, valign}` (+span/header). It must emit `size`.
- `_edit_filltable.html`'s two image branches render `<td data-image data-media data-alt
  tabindex="0">` with **no `data-size`**. Both the `<td>` and `<th>` branches gain
  `data-size="{{ cell.size|default:'full' }}"`.
  **The `|default:'full'` filter belongs on BOTH editors' sites, not just the plain table's.** The
  argument made for the student partial transfers verbatim: a missing key renders
  `filltable-editor__img--`, matching no rule, and since this slice **strips** `max-width: 120px`
  from `.filltable-editor__img`, nothing then caps the preview — a p50 1192px asset renders at
  intrinsic width and drags the editing grid. Giving two sibling templates opposite defensive
  postures for the same key would contradict this spec's refusal to assume normalization is
  guaranteed. Extend the "a cell with no `size` key still renders bounded" template test to the
  fill-table editor partial as well.

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

**The cell-scoped BUTTONS carry `disabled` in markup too — the same argument, and it was missing.**
The section makes the markup-attribute case correctly for `hidden` and then never makes it for
`disabled`. Today `[data-cmd]` (B/I/U, math and the five swatches), `[data-image-toggle]`,
`[data-answer-toggle]` and the six align buttons carry **no** `disabled` in either partial — only
Merge/Split/Header do (verified: `_edit_table.html` has four `data-cmd=` occurrences and three
`disabled`, all on merge/split/header). Once `hidden` is removed from `[data-table-toolbar]`, those
buttons render **enabled with nothing focused** for the window between page load and `wire()`, and
**permanently** if JS fails to load or `wire()` takes its `if (!hidden || !grid) return;` early exit.
The mandated e2e assertion cannot see this, because by the time Playwright looks, `wire()` has run.

**But the five colour swatches are OFF LIMITS, and getting this wrong breaks four unrelated editors.**
Only the four `[data-cmd]` buttons (B/I/U/math) are authored *in* the two table partials. The swatches
come from `templates/courses/manage/editor/_rte_swatches.html`, which is included by **six** toolbars —
`_edit_callout.html`, `_edit_spoiler.html`, `_edit_text.html` and `_rte_toolbar.html` as well as the two
table editors. `text_toolbar.js` contains **zero** occurrences of `disabled`, and nothing anywhere sets
`disabled = false` on a `[data-cmd]`, so adding the attribute to that shared partial would
**permanently disable colour authoring** in the text, callout, spoiler and generic RTE editors and
redden `tests/test_e2e_text_colour.py`, which clicks `[data-cmd="colour-red"]` in four places.

So, precisely:

- **Add `disabled` in markup** to the **four** `[data-cmd]` buttons authored in each table partial,
  plus `[data-image-toggle]`, `[data-answer-toggle]` and the six `[data-halign]`/`[data-valign]`
  buttons — matching Merge/Split/Header. Pin it in the editor-partial source assertion.
- **Do NOT edit `_rte_swatches.html`.** The swatches keep their pre-`wire()` enabled window, accepted:
  they are shared with four editors that have no `disabled` mechanism at all, and a table-local
  override would mean forking the partial for no behavioural gain after `wire()` runs.
- The real counts are **twelve** in `_edit_filltable.html` (4 `[data-cmd]` + `[data-image-toggle]` +
  `[data-answer-toggle]` + 3 `[data-halign]` + 3 `[data-valign]`) and **eleven** in `_edit_table.html`
  (the same minus `[data-answer-toggle]`) — not "sixteen", and not one figure for both.

**All three new per-cell controls carry the `hidden` ATTRIBUTE in markup**, not merely a JS-painted
`hidden` property. The existing `[data-image-alt]` input is invisible before `wire()` runs because
`_edit_filltable.html` renders `<input … data-image-alt hidden …>` — the markup attribute is what
does that work. Without it, `[data-image-size]`, `[data-image-remove]` and the plain table's new
`[data-image-alt]` render **visible on every editor load** until JS paints them (and permanently if
the handle-hoisting trap above bites) — the exact live-looking dead control this section forbids.
Add `hidden` to the same editor-partial source assertion that pins `name`/`aria-label`.

**Accessible names, resolved per control type:**

- **size select** — `title` + `aria-label` (`{% trans 'Image size' %}`).
- **Remove image** — `title` + `aria-label` (`{% trans 'Remove image' %}`); an icon-only `.rte-btn`
  would otherwise ship nameless.
- **alt input (both editors)** — `placeholder` + **`aria-label`**, and **no `title`**. It follows the
  input precedent, not the icon-button one.

**Correcting an earlier draft: it is NOT true that "every other control in both toolbars carries
both."** The existing `[data-image-alt]` input is the exception — it carries only
`placeholder="{% trans 'Image description (alt)' %}"`, no `title` and no `aria-label`. That matters
beyond the false rationale: the plain table's alt input is **new**, so "copy the fill table" would
reproduce a placeholder-only control. **Decision: the new alt input gets an `aria-label` as well as
the placeholder** (a placeholder is not an accessible name — it disappears on input), and the
fill-table input gains one too, since the two are twins and a source assertion covering only one
would be arbitrary. Every icon-only button in these toolbars does carry both, which is why the select
and Remove image follow that precedent rather than the input's.

The source assertion is **per partial**, because `[data-image-remove]` exists in only one of them
(and because there are two test files, one per editor):

| partial | test file | controls checked |
|---|---|---|
| `_edit_table.html` | `tests/test_table_editor_partial.py` | `[data-image-alt]`, `[data-image-size]`, `[data-image-remove]` |
| `_edit_filltable.html` | `tests/test_filltable_editor_partial.py` | `[data-image-alt]`, `[data-image-size]` |

For each listed control: `hidden` present, `name` absent, `aria-label` present. A single assertion
naming all three controls would fail on `_edit_filltable.html`, which has no Remove-image button.

The choices reach the templates via a **property on each form**
(`form.cell_image_sizes`, returning `CellImageSize.choices`), since the forms otherwise expose only
`data`. The context test therefore asserts the **rendered select's Full option**, not just the
model constant. Per editor:

- **`_edit_filltable.html`** — the select goes beside the **existing** `data-image-alt` input.
- **`_edit_table.html`** — the image button, the alt input and the size select are **all new**;
  there is no existing anchor control there. **No new `data-msg-*` keys are needed:** nothing on
  the image path builds a translatable string in JS — the button titles, the alt placeholder and
  the select options are all server-rendered. (`_edit_filltable.html`'s fourteen existing keys are
  grid handles, answer strings and merge/header/range announcements; it has no image-related key
  either. An earlier draft asserted an artifact class that does not exist.)

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

- **Width:** **`max-width: min(100%, 200px)`** — an *absolute* cap, not a bare `100%`. A bare
  `max-width: 100%` is **not a bound here**, by this spec's own central thesis: the editor grid is
  an auto-layout `<table>` too, so a percentage resolves against a content-negotiated column. With
  the base `120px` stripped, `100%` + `max-height: 200px` + `height: auto` bounds the *width* only
  to `200 × aspect_ratio` — the spec's own **1586×612** case renders **~518px wide** and drags the
  editing grid to that column width. Calling that "bounded" would restate the exact false-bound
  claim this slice exists to retire, one paragraph after retiring it. The `min(100%, …)` form is
  the same construction the student presets use, and for the same measured reason.
- **Height:** it also carries **`max-height: 200px`**. "Mirroring the student rule" is incomplete
  without this — the student `--full` is `max-width: 100%` **plus** `max-height: 60dvh`, and
  dropping the height half reintroduces the exact defect this slice exists to fix, inside the
  editor: the spec's own 494×1492 case would render column-wide and unbounded vertically, dragging
  the editing grid down. A fixed px cap rather than `dvh` because `dvh` is meaningless in a split
  editor pane, which is not the viewport.

So the editor scale is **Small 40 · Medium 80 · Large 120 · Full `min(100%, 200px)` × 200px** —
every entry bounded **absolutely** in both axes, and strictly increasing.

**Consequence, accepted and stated: existing fill-table previews change size on first open.** All
**31** existing fill-table image cells read as `full` (the stored default), and today they render
as a uniform `max-width: 120px` thumbnail. After this ships they render at up to 200×200 — the
editing grid visibly reflows for content nobody edited. This is accepted rather than designed
around: the whole point of the editor scale is that the preview shows what the author picked, and a
`full` cell genuinely is the largest preset. The 120→200px jump is bounded and modest by
construction (which is why `--full` is capped at 200px rather than the 240px the student `large`
suggests). **The styling task's light+dark screenshot Definition of Done must include "an existing
fill-table with an image cell, reopened"** as one of its shots, so the reflow is seen rather than
discovered.

**Editor-preview class names and their file** (completing the "five artifacts" promise):

- Plain table: base `table-editor__img`, modifiers `table-editor__img--small|medium|large|full`.
  Because `tests/test_table_css.py` requires every `table-editor__*` class the JS emits to be
  styled in **`editor.css`**, these rules live in `editor.css`.
- Fill table: the existing `filltable-editor__img` plus the same four modifiers, kept in
  `courses.css` beside their twin.
- **The same equal-specificity trap applies here — but only one of the two base rules exists.**
  `.filltable-editor__img` currently declares `max-width: 120px`, which ties with any single-class
  modifier; strip `max-width` from it and put all four sizes on the modifiers. **`.table-editor__img`
  does not exist in `editor.css` at all** (zero occurrences) — it is **authored new**, not
  "stripped", and `test_table_css.py` requires it to be styled:

  ```
  .table-editor__img { height: auto; display: block; }
  ```

  (mirroring the student `.cell-img` base, and likewise declaring no `max-width`.)
- **The server-rendered previews emit the modifier too**, not just the JS. `_edit_filltable.html`'s
  two `<img class="filltable-editor__img">` tags gain
  `filltable-editor__img--{{ cell.size|default:'full' }}`, and
  the new `_edit_table.html` image branch emits its
  `table-editor__img--{{ cell.size|default:'full' }}` twin —
  otherwise a reloaded editor shows every preset at the same size until the author touches the
  select. **Written out literally**, given the same treatment the student partial gets and for the
  same reason:

  ```
  <img class="table-editor__img table-editor__img--{{ cell.size|default:'full' }}"
       src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
  ```

- **The editor preview carries NO `data-zoomable`, and a test must enforce that.**
  `tests/test_imagezoom_render.py` holds
  `NEVER_ARMED = ["courses/manage/editor/_edit_filltable.html", "courses/manage/editor/_edit_gallery.html", "courses/elements/dragtoimagequestionelement.html"]`
  and asserts the hook is absent from each — the deliberate negative half of the click-to-enlarge
  contract. `_edit_table.html` is about to gain its **first** `<img>`, and an implementer copying the
  student partial's four mandated attributes into the editor preview would arm editor thumbnails
  with **no test going red**, because that file is not in the list. **Append
  `courses/manage/editor/_edit_table.html` to `NEVER_ARMED`** — a Definition-of-Done item on the
  editor task, and the only place in this spec that names this test file.
- **The guard only sees a lone assignment.** `test_table_css.py` matches
  `className = "(table-editor__[\w-]+)"`, so the JS must assign the base as a single
  `className = "table-editor__img"` and add the modifier via `classList.add(...)`, or the
  assertion stops matching entirely and the class ships unstyled with no failure. (Note the
  substring hazard: `table-editor__` also occurs inside `filltable-editor__`.)
- **Widening that regex is NOT sufficient — done naively it produces a vacuous guard.** The
  assertion is `assert f".{cls}" in css`, a plain substring test. If the modifier is emitted as a
  **concatenation** (`classList.add("table-editor__img--" + size)`), the only string literal in the
  source is the **stem** `table-editor__img--`, so the widened regex captures the stem and
  `".table-editor__img--" in css` passes as a substring of **any one** modifier rule. Three of the
  four modifiers could be missing from `editor.css` and the guard would stay green — precisely the
  vacuous-guard failure `test_table_css.py` exists to prevent.
  **Resolution: emit the four modifiers as literals via a lookup map** —
  `var CELL_IMG_CLASS = {small: "table-editor__img--small", medium: …, large: …, full: …};` with
  `classList.add(CELL_IMG_CLASS[size])` — so every full class name appears verbatim in the source.
  The fill table's `classList.add("filltable-editor__img--" + size)` shape gets the same treatment.

  **The regex must match where those literals actually LIVE, which is the map, not the call.** A
  pattern anchored on `classList.add\("(table-editor__[\w-]+)"\)` finds **zero** matches against
  this design — the literals sit in the map declaration and the call site passes a variable. Pairing
  a zero-match pattern with a companion "assert non-empty" rule would make `test_table_css.py` fail
  on a *correct* implementation, whose natural "fix" is deleting the new assertion: a guard that
  destroys itself. So the pattern is anchored on **quoted class literals anywhere in the file**:

  ```
  emitted = set(re.findall(r'"(table-editor__[\w-]+)"', js))
  assert emitted, "expected table_editor.js to name table-editor__* classes"
  ```

  This is a strict **superset** of the existing `className = "(table-editor__[\w-]+)"` pattern (it
  matches those sites too), so it *replaces* rather than sits beside it — one pattern, one
  non-empty assertion, no set-union bookkeeping. It keeps the guard on every class the old pattern
  covered, including the row/column handles whose drift (`.table-row-handle` vs
  `.table-editor__rowctl`) is the documented reason this test exists. The "lone `className =`
  assignment" rule for the base class stays, but is now a style constraint rather than a
  guard-visibility requirement.

**Structural operations × image cells** (only merge was previously considered):

| operation | required behaviour |
|---|---|
| Merge | An absorbed image cell triggers the **existing merge-discard confirmation**, and on confirm the image cell **is discarded**. It does not block: `cellIsNonEmpty` feeds `absorbedNonEmpty`, whose only consumer is `if (rg && absorbedNonEmpty(rg)) { if (!window.confirm(msg("merge-confirm"))) return; }`. `cellIsNonEmpty` **already** reads `c.textContent.trim() !== "" \|\| c.querySelector("img") !== null`, so a rendered preview already triggers it. Add a `hasAttribute("data-image")` clause as **defence-in-depth / twin-parity**, not as a fix for a reachable state: every producer of `td[data-image]` also produces the child `<img>` in the same synchronous step (`setImageCell` appends it immediately; both server-rendered branches emit it inline; `toggleHeaderCell` *moves* the children onto the replacement; an unresolvable pk yields a `kind`-less text cell with no `data-image` at all), so `querySelector("img")` already covers every live case. The test must therefore **synthesise** the state by removing the `<img>` — say so, rather than implying a live window. (Two earlier claims were **false**: that this guard was missing, and that it blocks. The divergent function is `cellIsNonEmpty`; `absorbedNonEmpty` is a listed twin.) **Stale comment:** `table_editor.js`'s comment above `absorbedNonEmpty` reads "(table_editor.js has no kinds; the kind clauses live in filltable_editor.js's override.)" — false the moment the plain table gains image cells and a `data-image` clause. Delete or rewrite it in the same change. |
| Split | The image stays in the anchor cell; newly created cells come from the existing `makeCell()` helper as ordinary text cells. |
| Header toggle | `table_editor.js`'s `toggleHeaderCell` builds a **new** element and calls `td.replaceWith(next)`. Attributes are copied, but a **WeakMap stash key is not** — so header-toggling an image cell would orphan its stash and **Remove image would restore nothing**. It must re-point the new stash from the old node to the replacement, mirroring `filltable_editor.js`'s `cellStash` re-keying. Its in-file comment ("there is no such map in this file's scope (plain tables have no static/answer/image content to stash)") becomes **false** and must be deleted. Pinned by a test: toggle header on an image cell, then Remove image. |
| `header_row` / `header_col` toggles | An image cell may become a `<th>`; the shared `_table_cell.html` handles it, so no branch-specific work. |
| Row/column delete | No new warning — parity with text cells today. Stated so the omission is deliberate. |

**`tests/test_editor_twin_drift.py` will go red and must be updated.** It asserts a hard-coded
`EXPECTED_COUNTS = {TABLE_JS: 28, FILL_JS: 36}` and requires every function name common to both
files to be classified in exactly one of `TWINS` / `DIVERGENT`. This slice adds functions to both
editors — **every NAMED `function` declaration** it adds to both files must be classified. That
qualifier is load-bearing: `_DEF` matches only `^\s*function (\w+)\s*\(`, so **function expressions
are invisible to this guard** and listing them as classification obligations sends an implementer
hunting for entries that cannot exist. Concretely:

- **Real obligations** (named declarations newly common to both files): **`setImageCell`**, the
  `cellStash` accessor (`stashFor`), and remove-image **only if written as a named function**.
- **Not obligations** (function expressions — invisible to `_DEF`):
  `window.libliTablePickImage = function (pick) {…}`, and the `change`/`input` listeners handed to
  `addEventListener`. Anonymous callbacks are structurally outside this guard's contract; if they need
  protection it belongs in a `test_colour_glue_drift.py`-style textual guard.

**`setImageCell` lands in `DIVERGENT`, with a written reason.** Its two bodies **cannot** be
identical: the fill table's carries `td.removeAttribute("data-answer")`, the answer-branch stash write,
and `filltable-editor__img`; the plain table's carries `table-editor__img` and no answer handling. So
`DIVERGENT` is the only correct answer, and the reason is "preview class name differs; the fill table
also stashes and clears `data-answer`". Stated because an implementer who guesses `TWINS` reddens
`test_twins_are_identical`, whose natural "fix" is reclassification — the same trap this spec closes for
`afterStructuralEdit`.

**`stashFor` lands in `TWINS`, and the plain table keeps the unused `answer: null` slot verbatim.**
This is a hard, testable choice the spec must make rather than leave to the implementer:
`test_twins_are_identical` compares normalised bodies, and the plain table has **no answer cells**, so
the *natural* body (`{ html: null }`) diverges while the byte-identical body
(`{ html: null, answer: null }`) carries one dead key. Byte-identity wins — the same reasoning that
pins `cellStash`'s name and `afterStructuralEdit`'s statement order. A one-word dead key is a smaller
cost than a `DIVERGENT` entry whose reason would immediately need maintaining, and it keeps the stash
shape uniform if the plain table ever gains a second cell kind.

So the counts break immediately; and
`refreshToolbarState`'s `DIVERGENT` reason becomes stale the moment the plain table gains a
kind-specific refresh. Re-deriving `EXPECTED_COUNTS` and classifying every newly-common function
with a written reason is a **Definition-of-Done item on the editor tasks**, not incidental cleanup.

**Five `DIVERGENT` reasons go stale, not one.** No test compares these reason strings, so a false
rationale survives silently — the "false mechanism survives review" failure mode this project has
already recorded:

| entry | why its reason dies |
|---|---|
| `serialize` | reason says the fill table "emits three cell kinds (static/answer/image) where **the plain table emits one**"; the plain table now emits **two** (text/image). Replacement reason: three kinds vs two, plus the fill table's two extra document-level fields (`case_sensitive`, `prompt`) |
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
**two** statements still behind the gate are
`var answerBtn = toolbar.querySelector("[data-answer-toggle]");` and
`if (answerBtn) answerBtn.classList.toggle("is-on", isAnswer);`
— and with `isAnswer` now null-safe (`!!focusCell && …`), the toggle line is correct with no focus too.

**`answerBtn`'s handle is therefore a FIFTH hoist, or the gate's deletion must precede it.** The
declaration sits *after* the gate today, so an implementer who hoists only the four named items leaves
it behind — and then cannot write the newly-required `answerBtn.disabled = !focusCell` above it, since
the name is not yet in scope there. Deleting the gate makes the ordering moot, which is the cleanest
resolution; either way the handle must end up above **both** the `disabled` assignment and the `is-on`
toggle. Same hoisting trap already spelled out for `imageAlt`/`sizeSel`/`removeBtn` and for
`isAnswer`/`isImage`.

Leaving the gate in place would keep the Answer-cell button painted `is-on` from a **deleted** cell,
the very stale-state bug the align-button fix exists to close. The gate joins the
"delete the dead thing in the same change" list alongside `.table-editor__toolbar[hidden]`, the
`toolbar.hidden = false` lines, `setImageCell`'s bespoke two-line `imageAlt` reveal, `focusin`'s
trailing `imageAlt` reveal block, and **`toggleAnswerCell`'s `if (imageAlt) imageAlt.hidden = true;`**
in its image→static branch. (The unrelated `if (!toolbar) return;` on the function's first line is
**not** part of this and stays.)

**That site — the THIRD bespoke `imageAlt` painting site, and the fifth entry on this delete list —
is why the "sole owner" claim needs it deleted, not merely tolerated.** (The three are
`setImageCell`'s two-liner, `focusin`'s trailing block and this one; the one-way line inside
`refreshToolbarState` is *rewritten*, not deleted. The delete list also carries CSS and `hidden`
items that are not painting sites, which is where the "fifth" ordinal came from.)
`toggleAnswerCell`'s line paints **only** `imageAlt` — not the new size select, not Remove image — and
sits immediately before that branch's existing `refreshToolbarState()` call. Leave it in and the sole-
owner invariant is false specifically on the **revert** path, where two of the three controls would be
repainted by one function and the third by another. The trailing `refreshToolbarState()` already
repaints all three correctly once the visibility lines are two-way, so the line is pure redundancy.

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
  **no** `html` key, and **strips `alt` defensively**:
  **`cell["alt"] = alt.strip() if isinstance(alt, str) else ""`** — the fill table's actual line,
  quoted verbatim. A bare `cell["alt"] = alt.strip()` **raises `AttributeError` and 500s the save**
  on an image cell stored with a missing or non-string `alt`: `_sanitized_data` runs on **raw**
  `self.data` from `save()`, and its own docstring commits it to "reading defensively so a malformed
  legacy shape cannot raise". Named model-unit mutant: an image cell stored with **no** `alt` key
  still saves. This matches what `FillTableElement._sanitized_data` already does — otherwise the two tables store different bytes
  for the same authored alt text, and twin-drift discipline would not catch it (different files).
- **`FillTableElement._sanitized_data` already has that branch** and needs **no change**. Stated
  explicitly because this paragraph previously sat under the fill-table text and read as if it did.

**Shared image resolution.** `FillTableElement.resolve_image_cells` is already a `@staticmethod`
shared between the model and the form — deliberately, so the two cannot diverge on the
unresolved-asset fallback. The Table needs the same logic with a **different empty-cell shape**,
so it lifts to a shared helper parameterised by that shape.

**Named concretely**, since it has **two live callers today** — `FillTableElement.resolved_cells`
in `models.py` and `FillTableElementForm.resolved_grid_cells` in `element_forms.py` — plus the plain
table's two new ones: a module-level
`resolve_image_cells(cells, *, empty_cell, course=None)` in a new `courses/tablecells.py`
(mirroring how `courses/filltable.py` already hosts logic shared between a model, a form and a
view).

**The `courses/filltable.py` analogy breaks on imports, and that is the one point that matters.**
`courses/filltable.py` has **zero** imports — it is pure string/grid logic, which is precisely why
`courses/models.py` can import it freely. The new helper cannot be: it runs
`MediaAsset.objects.in_bulk(...)` / `.filter(course=…, kind="image")`, so a module-level
`from courses.models import MediaAsset` in `tablecells.py` **plus** a module-level
`from courses.tablecells import resolve_image_cells` in `models.py` is a **circular import at app
load**. Import discipline, stated so nobody discovers it by crashing:

- `courses/tablecells.py` imports `MediaAsset` **inside the function**, not at module level.
- This is the pattern the codebase already uses for exactly this reason, and the closest precedent is
  the **same symbol in the same role**: `_ser_fill_table` opens with a function-local
  `from courses.models import MediaAsset`. (A separate, weaker example is `models.py`'s
  `FillTableElement.canonical_cells` doing `from courses.filltable import split_alternatives`
  function-locally, as `views.py` also does — but `_ser_fill_table` does **not** import
  `split_alternatives`; an earlier draft claimed it did.)

`empty_cell` is a callable taking the original cell and returning the fallback's **model-specific
base shape only** — `{kind: "static", html, halign, valign}` for the fill table,
`{html, halign, valign}` for the plain table — which is what lets the two models differ while
sharing one definition of the unresolved-asset behaviour.

**Carrying `header`/`colspan`/`rowspan` is the HELPER's job, not the callable's, and this contract
must be pinned or the single-definition defence collapses.** If `empty_cell` returned the
*complete* fallback, each caller's callable would have to copy those keys itself — reintroducing
exactly the two-implementations divergence this helper exists to prevent, and making the
"single-definition-by-construction is the whole defence" claim below **false**. So: `empty_cell`
returns the base; the **shared helper** copies `header`/`colspan`/`rowspan` from the original cell
onto whatever it returns. Pinned by a test **per model** asserting a spanning unresolved cell keeps
its span.

**`FillTableElement.resolve_image_cells` survives as a thin delegating `@staticmethod`**, keeping its
signature **verbatim as `resolve_image_cells(cells, course=None)`** and supplying the fill table's own
`empty_cell` internally — it must **not** expose `empty_cell` to callers, because that exact
signature is what keeps both existing call sites working unchanged
(`FillTableElement.resolve_image_cells(cells, course=self.course)` in `element_forms.py` and
`self.resolve_image_cells(cells)` in `resolved_cells`).

**Why it must survive is those two live call sites — not a test.** An earlier draft claimed
`tests/test_filltable_editor_partial.py` "calls it by name"; it does not. The name appears there only
inside a **docstring**, so that test would not go red if the delegator were deleted. (Its docstring is on
the stale-artifact list for the span-preservation inversion, as is the span-drop test's.) Correcting this because
an unchallenged false mechanism is a first-class defect in this repo.

**Import it module-qualified** (`from courses import tablecells`, body
`return tablecells.resolve_image_cells(...)`), not as a bare name: a module-level
`from courses.tablecells import resolve_image_cells` plus a same-named delegating staticmethod
resolves correctly — class scope is not in a method's lookup chain — but *reads* like accidental
recursion, and invites an implementer to "fix" it by aliasing or by hoisting the `MediaAsset`
import back to module level.

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
  — **and its NAME must be renamed**, not just its assertions: `drops_spans` would lie about what the
  test checks, exactly the defect for which this spec mandates renaming `test_format_version_is_7`.
  Rename to `test_unresolvable_image_cell_keeps_spans_in_both_render_and_editor` and rewrite its
  docstring (which currently argues "a spanning gap left un-spanned would misshape the grid"). A
  Definition-of-Done item on the **model** task; that docstring is on the stale-artifact list too.
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
   **But not a literal mirror — the two `clean_data` bodies are structurally different, and the
   fill table's expression 500s on the plain table's data.** `FillTableElementForm.clean_data`
   computes `nd = normalize_data(...)` **first** and scopes over `nd["cells"]`, so `c["media"]` is
   guaranteed an `int`. `TableElementForm.clean_data` works on the **raw** submitted `rows`
   throughout and normalizes only in its `return`, so a copied
   `img_ids = {c["media"] for row in cells for c in row if c.get("kind") == "image"}` raises
   `KeyError` on a crafted `{"kind": "image"}` with no `media` — a 500 on the save path. Requirement:
   **bind `nd = TableElement.normalize_data(data)` before the scoping check, scope over
   `nd["cells"]`, and return `nd`** (one normalize, not two). The early
   `return TableElement.normalize_data({})` branch for the empty/no-cells case must **not** be routed
   through the guard. Named mutant: POST an image cell with **no** `media` — the form rejects or
   normalizes, never 500s.
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

**`TableElementForm.resolved_grid_cells`, written out** — the fill table's twin is quoted with its
exact call, and this section otherwise pins signatures verbatim:

```
@property
def resolved_grid_cells(self):
    return TableElement.resolve_image_cells(self.grid_data["cells"], course=self.course)
```

and its model-side twin:

```
@property
def resolved_cells(self):
    cells = self.normalize_data(self.data)["cells"]
    return self.resolve_image_cells(cells)
```

Both go through the **delegator**, which owns the single `empty_cell` for this model:

```
@staticmethod
def resolve_image_cells(cells, course=None):
    from courses import tablecells
    return tablecells.resolve_image_cells(
        cells,
        empty_cell=lambda c: {"html": "", "halign": c.get("halign", "left"),
                              "valign": c.get("valign", "top")},
        course=course,
    )
```

`course=self.course` is what makes the security guard meaningful (a submitted pk from another course,
or an in-course asset of the wrong kind, resolves to nothing and takes the fallback), and the
`empty_cell` shape carries **no** `kind` key — the plain table's fallback is a text cell. `.get` on
`halign`/`valign` rather than subscripting, for the same reason `_ser_table` uses it. These two
properties mirror `FillTableElement.resolved_cells` / `FillTableElementForm.resolved_grid_cells`
line-for-line, which is the point.

### Transfer (export / import)

**Five** sites, failing in three different ways — the earlier blanket "missing any one breaks export
silently" was wrong for three of them:

- **Silent** (the element round-trips, its image does not): **`_build_table`** and **`_ser_fill_table`**.
- **Loud, at import or duplicate:** **`_val_table`** (an un-widened allowlist rejects the archive with
  "a table cell has an unknown key" — the Error-handling table's own "unknown cell key → rejected"
  row, surfaced by `_copy_into`/`duplicate_element` as a raised `TransferError`) and **`_ser_table`**
  (without it the raw int pk reaches the archive, and `_require_media`'s
  `not isinstance(data_media, str)` branch rejects it just as loudly).
- **Diagnostics only:** **`_element_mids`** — see the correction under its row.

| site | change |
|---|---|
| `_val_table` | widen the per-cell `allowed` set with `kind`/`media`/`alt`/`size`; validate per the reject/tolerate table below; return media refs via `_require_media` |
| `_ser_table` | currently `return dict(el.data)`; must walk cells and register each image cell's asset |
| `_element_mids` | routes **by type key**; `table` currently falls through to the scalar `data.get("media")` and returns nothing, so it needs a `table` branch — the `fill_table` branch's exact twin, testing `isinstance(c.get("media"), str)` **not `int`** (it runs on the **already-serialized** data, after `_ser_table` has replaced pks with local ids). **But its consequence is NOT a broken zip — see the correction below.** Pinned by a direct unit assertion on `_element_mids("table", …)`, mirroring the existing `tests/test_transfer_export.py::test_element_mids_fill_table_yields_image_local_ids` |

**Correcting a false mechanism: a missing `_element_mids` branch does NOT omit the asset from the
zip.** An earlier draft claimed "the file is omitted from the zip and import then `KeyError`s", and
made the round-trip test the named mutant. Traced against `courses/transfer/export.py`, that is wrong:
`document["media"]` and the zip entries are both built by iterating **`media_ids.items()`** — the
registry `_ser_table` writes into via `ids.register(asset)` — and `importer._create_media` builds its
`assets` map from `document["media"]`. `_element_mids`'s return feeds only `mid_refs`, which is used
for **problem reporting** (`_units_for`) and Pass 4's *dropped*-mid filter. So with no `table` branch,
or with `int` swapped for `str`, the asset is still bundled and `_build_table`'s remap still resolves —
**the round-trip stays green**, and the named mutant could never have failed. (Images never reach
`status == "dropped"`; they become placeholders. `_copy_below` derives `media_map` from
`media_assets`, so duplicate-element and clipboard paste are unaffected too.)

**The real consequence, which is the one worth pinning:** a table whose cell-image file is **missing on
disk** would be silently absent from `problems` / `_units_for`, so the operator exporting a course gets
**no missing-image warning** for it. Pin that with a test modelled on
`test_missing_image_lists_all_referencing_units`, alongside the direct `_element_mids` unit assertion.
This row is therefore the **one exception** to the "Missing any one breaks export silently" header
above — it degrades diagnostics, not data.
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
Copying `_ser_fill_table`'s explicit **top-level six-key return literal**
(`header_row`/`header_col`/`case_sensitive`/`border`/`prompt`/`cells`) would inject
`header_row`/`header_col`/`border`
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
  the alignment pair, **and with the same defaults the render-side fallback uses**:
  `c.get("halign", "left")`, `c.get("valign", "top")`, `c.get("size") or "full"`,
  **`(c.get("alt") or "")[:255]`**.
  Bare `.get` would emit `"halign": null` into the archive; harmless (`_val_table` tolerates it, `_cell`
  coerces it) but it makes the export fallback a *different shape* from the delegator's `empty_cell`,
  which this spec writes out as `c.get("halign", "left")` / `c.get("valign", "top")` and calls the same
  fallback. The natural implementation copies `_ser_fill_table`'s opening line
  (`img_pks = [c["media"] for … if c.get("kind") == "image"]`), which is safe there only because it
  normalised first. By this spec's own argument, a stored `{"kind": "image"}` with no `media`, or an
  image cell written straight to the model without `size`, is reachable — and subscripting either
  500s export *and* duplicate-unit. **A `kind:"image"` cell whose `media` is missing or not an int
  takes the same empty-text-cell fallback as an unresolved pk.** The export test fixture therefore
  covers a ragged row, a non-dict cell, a cell missing `halign`, an image cell missing `media`, and
  one missing `size`.

  **The five fixtures split into two assertion classes — "does not alter bytes" is FALSE for two of
  them.** The two malformed-**image** fixtures are *required* to change bytes: an image cell whose
  `media` is missing or non-int takes the empty-text-cell fallback (rewriting it to
  `{html: "", halign, valign}`), and an image cell with no stored `size` must emit *something* for
  `size`. So:

  - **byte-identity asserted:** the ragged row, the non-dict cell, and the cell missing `halign` (plus
    the separate "legacy non-normalized table's export bytes are unchanged" all-text case);
  - **empty-text-cell fallback asserted:** the image cell missing `media`;
  - **byte-changing, exact output asserted:** the image cell missing `size` — it does **not** take the
    fallback (its `media` resolves fine); it exports as a valid image cell with `size: "full"`
    materialised.

  **What `_ser_table` emits for an image cell with no stored `size`:** `"full"` — it applies the same
  `DEFAULT_CELL_IMAGE_SIZE` the model would, via `c.get("size") or "full"`, rather than emitting `None`
  and pushing an out-of-enum value into the archive for `_val_table` to repair.

  **All five are EXPORT-ONLY — do not extend them into round-trips.** They assert that
  `_ser_table` does not raise, and either preserves bytes or produces the stated fallback — nothing
  more. The resulting archives are
  legitimately **not importable**: `_val_table` opens with
  `_exact_keys(data, ["header_row", "header_col", "border", "cells"], …)`, rejects any non-dict
  cell outright, and rejects non-uniform widths on a non-spanning table. That asymmetry is correct
  — export must survive whatever is on disk, import must not accept corruption — and is stated
  because an implementer who naturally extends these into round-trips will see them fail and "fix"
  the validator, widening the import surface this spec deliberately keeps narrow.

**Per-field import policy for `_val_table`** (resolving the reject-vs-tolerate ambiguity; the
precedent is that `_val_table` already **rejects** an out-of-enum `halign`/`valign` even though
the model coerces them):

| field | `_val_table` |
|---|---|
| `kind` | reject if present and not the literal `"image"` |
| `media` | reject via `_require_media` if absent or not a known ref on a `kind:"image"` cell |
| `alt` | **`alt = cell.get("alt"); if alt is not None: check_str(alt, "alt", max_length=255)`** — scoped like every other row, and bounded only because the model is bounded to match (see below) |
| `size` | **coerce** to `full`, matching `_val_image`'s intent — but see the exact form below; do **not** copy its `setdefault` |

**The `alt` bound must be enforced at BOTH ends, or a course cannot round-trip.** A naive "parity
with `_val_image`" argument does **not** hold: `ImageElement.alt` is a
`models.CharField(max_length=255)`, so `_val_image`'s import bound mirrors a bound the model
already enforces. A table cell's `alt` lives in a `JSONField` — `_cell` only coerces it to `str`,
and neither editor's alt input carries a `maxlength`. Left as-is, an author can save a 300-character
alt, export it **successfully**, and have the resulting archive **rejected on import**: a course
that cannot round-trip through its own export. So this slice bounds the model end too:

- **`_cell` truncates defensively: `alt = alt[:255] if isinstance(alt, str) else ""`** on both
  `TableElement` and `FillTableElement`. **Not `str(alt)[:255]`** — that coerces junk into *content*
  rather than dropping it, so a stored image cell with no `alt` key would get the literal alt text
  `"None"` and a dict would get `"{'a': 1}"`. That contradicts this spec's own error-handling row
  (`alt` non-string → coerced to `""`), silently changes shipped fill-table behaviour
  (`FillTableElement._cell` today is `alt if isinstance(alt, str) else ""`), and pushes garbage into
  both the a11y layer and the archive. Named model-unit mutant: an image cell stored with an absent
  and with a non-string `alt` coerces to `""`, never to `"None"`.
  **The 255 bound itself is a behavioural change to shipped fill-table data, and must be quantified
  like every other one in this spec** (**DB:** 31 cells, 7,246 cells, 15 of 312 spanning):
  `FillTableElement._cell` today is `alt if isinstance(alt, str) else ""` with **no** bound, so the
  next save of an existing image cell could truncate an already-authored alt. Record the **DB** count
  of existing fill-table cell `alt` values longer than 255 characters (expected: **zero**), so this
  lands as a measured no-op on real data rather than an unmeasured risk.
- **Both editors' alt inputs gain `maxlength="255"`** (`_edit_filltable.html`'s existing
  `[data-image-alt]` input and `_edit_table.html`'s new one).
- **The truncation must ALSO live in `_sanitized_data`, or "truncated at save" is false.** This spec
  establishes elsewhere that `save()` calls only `_sanitized_data`, **never** `normalize_data` — so a
  bound placed only in `_cell` fires on the form and import paths and **not at the save sink**. A test
  that constructs `TableElement(data={… 300-char alt …})` and calls `.save()` would find the alt
  untruncated. `_sanitized_data`'s image branch already touches `alt`
  (`alt.strip() if isinstance(alt, str) else ""`), so it becomes
  **`cell["alt"] = alt.strip()[:255] if isinstance(alt, str) else ""`** — symmetric with `_cell`, on
  both models. Two enforcement points, one bound.
- Pinned by a **round-trip test using a 300-character alt**: save → export → import, asserting it
  is truncated **by `save()` itself** (not merely via the form) and never rejected at import.

**The allowlist stays flat** (not partitioned by kind), so an archive text cell may legally carry
`media`/`alt`/`size`. That is harmless — `TableElement._cell`'s text branch drops them, and
`_element_mids`/`_build_table` key on `kind == "image"` — and is stated so nobody adds per-kind
key partitioning the model does not need.

**The `alt` check MUST carry an `is not None` guard, or every ordinary table archive is rejected.**
`courses/transfer/schema.py::check_str` opens with `if not isinstance(value, str): _err(…)`, so it
rejects `None`. Because **the allowlist stays flat**, `_val_table` iterates **text** cells too — and
a text cell carries no `alt`. An unconditional `check_str(cell.get("alt"), …)` therefore fails
every pre-feature table on import. This is not a new convention: `_val_table`'s own in-body comment
already states "Every field is read by value via `.get` with an explicit `is not None` guard, so a
missing key and an explicit null are treated identically (both tolerated)" — the `alt` row must
follow it. Named mutant for the transfer suite: **a plain all-text table archive still imports.**

**The exact form of the `size` repair, because `_val_image`'s cannot be copied.** `_val_image`
writes `data.setdefault("size", "full")` **because its `_exact_keys` check requires the key to be
present**. `_val_table` has no per-cell `_exact_keys` — its per-cell check is `set(cell) - allowed`,
which tolerates absence — so `setdefault` is both unnecessary and actively wrong: applied to every
cell it would write `size` onto **text** cells in the archive dict, which this spec insists never
carry it. Two things follow:

- **Scope:** the repair runs on `kind == "image"` cells **only**.
- **Form:** `if cell.get("size") not in CellImageSize.values: cell["size"] = "full"`.
- **What distinguishes this from `_val_image` is the SCOPING, not the shape.** Stated honestly:
  `cell.get("size")` returns `None` on an absent key, which is not in `values`, so this line **does**
  materialise `size` on image cells — it behaves as a *scoped* `setdefault`. That is fine and intended
  (the key is always present after normalization anyway). What must not happen is `_val_image`'s
  **unconditional** `setdefault`, which would write `size` onto **text** cells too. Do not write a test
  asserting the key stays absent on an image cell — it will not.

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

### Stale artifacts — the complete list

This spec treats a comment or docstring that becomes false as a first-class deliverable, because
this repo has source-scanning tests that read comments **and** because an unchallenged false
mechanism is its recorded review failure. A list that claims completeness and is not is worse than
no list, so this is the single consolidated enumeration; every entry is a Definition-of-Done item on
the named task.

| artifact | why it dies | task |
|---|---|---|
| `TableElement`'s class docstring — "a JSON grid of **{html, halign, valign} cells**" | image cells are a second shape | model |
| `TableElement._sanitized_data`'s docstring — "Sanitise **every** cell's html" | image cells are skipped | model |
| `FillTableElement.resolve_image_cells`'s docstring (span-dropping rationale) | the fallback now **preserves** spans | model |
| `resolved_grid_cells`'s docstring (same rationale, repeated) | same | model |
| `_element_mids`'s docstring — "a fill_table walks its `cells` grid …; **every other** media-bearing type reads the scalar `media`" | `table` now walks its grid too | transfer |
| `_val_table`'s in-body comment — "Unified per-cell shape check (**BOTH branches**) … tolerate whatever the model coerces" | the allowlist is now kind-aware in its *values* (`kind` rejected unless `"image"`, `media` required on image cells) | transfer |
| `tests/test_table_transfer.py`'s comment "…(4 <= FORMAT_VERSION=7)…" | a comment, not an assertion — nothing reddens | transfer |
| `dbscan.py`'s comment — "TableElement cells carry no `kind` at all, so the guard is a no-op there" | they now do; the guard becomes live | model |
| `table_editor.js`'s comment above `absorbedNonEmpty` — "(table_editor.js has no kinds …)" | it gains a `data-image` clause | editor |
| `toggleHeaderCell`'s in-file comment — "there is no such map in this file's scope" | the plain table now has `cellStash` | editor |
| **`filltable_editor.js`'s** `toggleHeaderCell` comment — "cellStash is LIVE here (**unlike table_editor.js's no-op guard**)" | the mirror image of the row above, and a false claim *about the other file*: the plain table's stash is live too once it re-keys. Its second sentence ("a stashed answer/html round-trip must follow the node") stays true. **No implementer is routed here by the diff** — the plain table's `toggleHeaderCell` is edited, the fill table's is not | editor |
| `filltable_editor.js`'s `// fill-table only` on `cellStash.clear()` | both files now clear | editor |
| `filltable_editor.js`'s header comment above `setImageCell` — "Stashes the prior kind's content … and **immediately reveals + populates the alt input** — a later focusin is **NOT** relied upon" | requirement (b) falsifies **both** clauses: the stash write becomes conditional (`if (!td.hasAttribute("data-image"))`) and the alt reveal is deleted in favour of `refreshToolbarState()`, which paints three controls. Nothing reddens — comments are stripped, and `setImageCell` is `DIVERGENT` anyway | editor |
| `templates/courses/manage/editor/editor.html`'s imagezoom comment — "renders the student **image/gallery/fill-table** templates, whose images carry `data-zoomable`" | the plain-table student template now carries it too, via `_table_cell.html`. Same file the slice already edits for the `ed-image-remove` sprite symbol | editor |
| `tests/test_filltable_editor_partial.py::test_unresolvable_image_cell_drops_spans_in_both_render_and_editor` — its **name** *and* its docstring ("a spanning gap left un-spanned would misshape the grid") both assert the dropped-span behaviour this slice inverts | rename to `…_keeps_spans_…` and rewrite the docstring | model |
| `test_editor_twin_drift.py`'s **module docstring counts** — "the **20 functions** duplicated", "**163 lines** … across 20 functions -- **11 at file scope, 9 nested inside `wire()`**", "a **21st** unguarded twin" — plus the `TWINS` inline comment "# Code-identical in both editors. 11 at file scope, 9 nested inside wire()." | this slice moves `afterStructuralEdit` into `TWINS` and adds `stashFor`, making it **22** twins (11 file-scope + 11 nested). No test compares these strings | editor (beside the `EXPECTED_COUNTS` re-derivation) |
| the **five** `DIVERGENT` reasons in `test_editor_twin_drift.py` (`serialize`, `refreshToolbarState`, `toggleHeaderCell`, `cellIsNonEmpty`, `afterStructuralEdit` — table below; `label` and `wire` survive) | see that table | editor |

Three of these live inside test files, and **none** of them reddens a test
(`test_table_transfer.py`'s is a comment, and
`test_twins_are_identical` strips comments) — which is exactly why they need enumerating rather
than trusting to a red suite.

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

**Export.** `_ser_table` / `_ser_fill_table` emit cells with local asset ids **including `size`** and
**`ids.register(asset)` each one — that registration is what bundles the asset** → `_element_mids` then
reads the *already-serialized* cells to collect those local ids into `mid_refs`, which feeds
missing-image reporting (`_units_for`/`problems`) only. Not the other way round: see the correction
under the `_element_mids` row. **Import.** `_val_table`
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
| Form | course-scoping **raises** with a foreign pk and with an in-course non-image asset; **the builder actually passes `course=` for `table`** (a separate test — without it the guard is a silent no-op); rejected-save re-render routed through `_sanitized_data`; **an image cell POSTed with no `media` never 500s** (the raw-vs-normalized `clean_data` mutant) |
| Transfer | all **five** sites; round-trip with a real asset asserting `size` survives **for both table types**; `_ser_table` leaves `el.data` unmutated; `_ser_table` survives a ragged row and a non-dict cell; `_ser_table` degrades an unresolvable pk to an empty text cell with spans carried; a legacy non-normalized table's export bytes are unchanged; a pre-feature archive still imports; out-of-enum `size` **coerced** by `_val_table` and **tolerated** by `_val_fill_table`; a **300-character `alt`** truncates at save and imports without rejection; **a plain all-text table archive still imports** (the `alt` `is not None` guard); **duplicate-element** and **clipboard paste** preserve `size`; `FORMAT_VERSION` bump |
| Template | both cell partials emit `<img>` + `data-zoomable` + `cell-img--<size>`; **`.cell-img` and all four `.cell-img--*` rules exist in `courses.css`** — added to `test_table_css.py::test_courses_css_defines_table_element`'s hardcoded list, boundary-anchored, since the JS-emission guard is blind to template-side classes; **the cell-scoped buttons carry `disabled` in markup**; **a render-level byte assertion on `TableElement.render()`'s `<td>` output for a text cell, before/after the factoring** (NOT `test_e2e_math_reflow_dom.py`, which renders no template); **`_table_cell.html`'s last byte is neither `\n` nor `\r`**; **both partials emit `alt="{{ cell.alt }}"`**; **a cell whose stored data has no `size` key still renders bounded** in **all four** partials — both student and both editor — (the `|default:'full'` filter); **a `header_row` cell's `<th>` bytes are pinned too**, not only `<td>`; the print block follows the preset block in `courses.css`; **`courses.css` contains no `.filltable__img` rule at all** — boundary-anchored
`(?<![\w-])\.filltable__img(?![\w-])` finds nothing — since the decision is deletion, not reduction; a
"no longer declares `max-width`" assertion would pass vacuously against a re-added
`.filltable__img { height: auto }` stub. The **class stays** in `_filltable_cell.html`; **`editor.css` carries `[data-image-remove][hidden]` and `[data-image-size][hidden]` `display: none` rules** |
| Editor / JS regression | both editors' `serialize()` emit the image branch with `size` and no `html` key; an untouched fill-table image cell round-trips `size` through an editor save; header-toggling an image cell then Remove image restores the stashed HTML; a not-yet-previewed image cell counts as non-empty for the merge confirmation; `test_editor_twin_drift.py` `EXPECTED_COUNTS` re-derived and every newly-common function classified; every `table-editor__*` class the JS emits is styled (`tests/test_table_css.py` exists because that drift was a real shipped bug); every `#ed-*` reference resolves to a defined sprite symbol; the Full label carries the `"image size"` gettext context; editor-preview widths strictly increase Small < Medium < Large; **the JS `CELL_IMAGE_DEFAULT`/`CELL_IMAGE_INSERT` literals equal the Python constants, in both editor files**; **focusing an image cell leaves `[data-image-toggle]` *enabled*** (re-pick must stay reachable); **`tests/test_colour_glue_drift.py` stays green untouched**; **the CONVERSION path (picker, never re-focused) leaves the per-cell controls visible AND populated — select reading `medium`, alt input reading the cell's alt**; **`tests/test_e2e_filltable.py`'s existing `make_image_cell` gesture stays green** (it `fill()`s the alt input right after the picker click, so it fails if the visibility rewrite is a mere relocation); **typing in the plain table's alt input writes `alt` into the serialized JSON**; **changing size twice on one cell leaves exactly one modifier class**; **`_edit_table.html` is in `test_imagezoom_render.py`'s `NEVER_ARMED`**; **convert → re-pick a different asset → Remove image restores the ORIGINAL html**, not the preview markup and not `""`; **a reloaded editor's image cell survives a no-op save** (the `data-media="{{ cell.media.pk }}"` and `parseInt` mutants); **the new per-cell controls carry `hidden` + `aria-label` and no `name` in markup, per the per-partial table**; **all cell-scoped buttons carry `disabled` in markup — twelve in `_edit_filltable.html`, eleven in `_edit_table.html` — while `_rte_swatches.html` is untouched**; **a 300-char alt is truncated by `save()` itself**; **`^\.cell-img\s*\{` and `^\.table-editor__img\s*\{` base rules exist**; **a row insert BEFORE any cell focus does not throw** (the bare `!focusCell.isConnected` mutant); **`refreshToolbarState()` at init with no focus does not throw** (the `refreshAlignButtons` guard-deletion mutant); **a converted cell has no `contenteditable`, has `tabindex="0"` and all four `data-*`** |
| e2e | sizing renders; clicking an image cell reveals the per-cell controls; **before any focus, every cell-scoped button is `disabled`** — `[data-cmd]`, `[data-image-toggle]`, `[data-answer-toggle]` and all six `[data-halign]`/`[data-valign]` (the exhaustive table above is the checklist) |

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
preset" — the measurement table above shows that the *original* `min(100%, Npx)` rule (Task 9
found and replaced it) could still be cell-bound below its cap even though it reads as a hard
ceiling: it rendered 112.4px in the 5-col all-images shape, still driven by the column. The
absolute-cap rule that replaced it (`max-width: Npx`, no percentage term) binds uniformly in
every shape measured, including all-images — see the Task 9 spike report. Use the **MEASURED**
5-col image-plus-four-text shape at **Medium**: 160.0px with short neighbour text and 160.0px
with long neighbour text. The same shape at `full` (426.2 → 285.7px) is the natural control,
asserting the defect is real.

**Light + dark screenshot verification belongs in the styling task's Definition of Done**, not
deferred — that deferral is how the fill-table shipped its dark-mode contrast bug. An editor page
must link **both** `courses.css` and `editor.css` to render faithfully.

## Release deliverables

Three per-slice deliverables that earlier drafts omitted entirely. Both immediate predecessors on this
roadmap shipped all of them — C1 (`356c956e`) touched `locale/{en,pl}/LC_MESSAGES/django.{po,mo}` **and**
`content-editors.md`/`.pl.md` in the same commit; the callout slice (`aa87f643`) did the same across both
manuals — so their absence here would be a regression in release discipline, not a scoping choice.

### i18n catalog — two brand-new msgids

The slice mints exactly **two** strings that do not exist in either catalog today (verified:
`grep msgid` finds neither in `locale/pl/LC_MESSAGES/django.po`):

- `Image size` — the size select's `title`/`aria-label`
- `Remove image` — the Remove-image button's `title`/`aria-label`

**Owning task: the LAST task — the same one that owns the docs and the screenshots**, not the editor
task. The two cannot both hold: "regenerate immediately before the PR, not early" and "Definition-of-Done
on the editor task" would force `makemessages`/`msgfmt` into a mid-sequence task, which is exactly the
"not early" this paragraph forbids, and whose named failure mode is an unmergeable binary `.mo`. The
cited precedent agrees — `356c956e` is **one** commit carrying `content-editors.{md,pl.md}` *and*
`locale/{en,pl}/LC_MESSAGES/django.{po,mo}` together. So all three release deliverables land in the same
last task.

**`aa87f643` is a counter-example, not a second precedent** (an earlier draft cited it as one): it
carries the four manuals and both `.po` files, adding a genuinely new translated pair
(`"This callout is empty."` / `"Ta ramka jest pusta."`) — but **no `.mo`**. The tracked `.mo` for that
slice was last touched by the earlier `91309851`, so the compiled catalog shipped without the new
string. That is exactly the miss this step exists to prevent, which is why "recompile the **tracked**
`.mo`" is stated explicitly rather than left implied by "run `makemessages`".

The step: run `makemessages`, supply natively-checked Polish for both strings, **clear any `#, fuzzy`
flag** (`makemessages` pre-fills a wrong translation from a near neighbour, and clearing it is *two*
deletions — the flag line and the bogus `msgstr`), then recompile the **tracked** `.mo` files.
Regenerate immediately before the PR: a stale branch produces a binary `.mo` conflict that cannot be
merged by hand.

(If the plan prefers to draft the Polish wording earlier, split it — "author the two strings" on the
editor task, "`makemessages` + `msgfmt` on the tracked catalogs" on the last task — but the catalog
files themselves are touched **once**, last.)

**Everything else deliberately reuses existing msgids, so no other catalog entry changes:** the four
`CellImageSize` labels share `ImageElement.Size`'s entries (`Small`/`Medium`/`Large` bare, plus the
`msgctxt "image size"` + `Full` pair), and the alt input's `aria-label` reuses
`Image description (alt)`, already present. That reuse is the point of the i18n subsection above — state
it here too so an implementer does not "helpfully" mint variants.

### Author-facing documentation

A discoverability-motivated feature that ships undocumented defeats its own purpose. Four files, each
with its Polish twin:

| file | what to add |
|---|---|
| `docs/help/course-admin/content-editors.md` + `.pl.md` | the Table's new image cells and the Size scale (C1 added its Size paragraph to exactly this file) **plus the toolbar rewording below** |
| `docs/help/course-admin/interactive-elements.md` + `.pl.md` | the fill-in table's new Size select — **and nothing else** |

**The toolbar rewording belongs to `content-editors.md`/`.pl.md` ONLY.** That entry carries the
now-false framing — "a WYSIWYG grid editor: **click a cell to edit** its rich text …" and its Polish
twin "kliknij komórkę, aby edytować jej" — and the toolbar is no longer focus-revealed but always
visible with cell-scoped controls disabled until a cell is focused. That change *is* the
discoverability fix, so leaving this entry describing the old behaviour would document the bug rather
than the feature.

**`interactive-elements.md` needs no toolbar rewording, and an earlier draft wrongly said it did.** Its
Fill-in table section opens by *delegating* the shared controls to the Table page — "the same grid,
header-row/column, border, and cell merge/split controls as [Table](content-editors)" — and contains no
"click a cell" wording in either language (its only `click` references are `Shift+click` range selection
and unrelated elements). Told to reword framing "in both files", an implementer either hunts for text
that does not exist or **invents a new paragraph in order to reword it** — fabricated manual content, in
a spec that treats stale prose as a first-class deliverable. Its change is the Size select, full stop.

**Owning task: the same one that owns the screenshots** (the styling task, or whichever task the plan
sequences **last**). Every other obligation in this spec is routed to a named task; an unowned
deliverable is the one most likely to land in no task at all. Last is the right slot for both docs and
screenshots, so the manuals describe the **shipped** behaviour rather than an intermediate state.

### Screenshots

Already stated in the styling task's Definition of Done — the same last task that owns the catalog and
the manuals (light + dark, judged separately, including "an
existing fill-table with an image cell, reopened") — repeated here only so the three release
deliverables sit in one place.

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
- `serialize()` **guards** the `mapColours` call on a **separate enclosing line**, keeping the
  needle line byte-identical so `test_colour_glue_drift.py` stays green; no `return` inside the
  `forEach` callback.
- **Every** toolbar control has an explicit `disabled` predicate — including
  `[data-image-toggle]` (`!focusCell` only, so re-pick stays reachable), `[data-answer-toggle]` and
  the six align buttons. No control is left live-and-inert.
- `courses/tablecells.py` imports `MediaAsset` **function-locally**; a module-level import is a
  circular import at app load.
- The editor `--full` preview is `min(100%, 200px)` × 200px — an absolute cap, because `100%` in
  an auto-layout editor grid is not a bound.
- Editor-preview modifier classes are emitted as **literals** via a `CELL_IMG_CLASS` lookup map, in
  **both** editors — never `classList.add("…--" + size)`, which leaves only a stem literal and makes
  `test_table_css.py`'s substring assertion vacuous.
- `refreshToolbarState` is the **sole** owner of per-cell control painting, with **two-way**
  visibility **and** value population; `setImageCell` ends with it in both editors, and both its own
  and `focusin`'s bespoke reveal blocks are deleted. Relocating the one-way `hidden = true` line is
  **not** the fix — it would leave the controls hidden and redden a green e2e test.
- The size-select `change` handler **removes all four modifier classes before adding one**; `add`
  alone accumulates and equal specificity then lets source order pick the winner.
- `[data-image-remove]` is rendered in **`_edit_table.html` only**.
- `empty_cell` returns the model-specific **base** shape; the shared helper carries
  `header`/`colspan`/`rowspan`. The delegator imports module-qualified.
- The editor preview `<img>` carries **no** `data-zoomable`, enforced by adding `_edit_table.html`
  to `test_imagezoom_render.py`'s `NEVER_ARMED`.
- The stash write is **skipped when the cell already carries `data-image`**, or a re-pick then
  Remove image destroys the author's original text.
- `serialize()`'s image branch reads `media: parseInt(td.dataset.media, 10)`, and the editor template
  emits `data-media="{{ cell.media.pk }}"`. Either mistake loses the image on the next save, silently.
- `alt` coercion is **always** `isinstance`-guarded (`alt[:255] if isinstance(alt, str) else ""`);
  never `str(alt)`, which would store the literal `"None"`.
- `test_table_css.py`'s pattern matches **quoted class literals anywhere** in the JS (a superset of
  the old `className = "…"` pattern); the two CSS files are checked **separately** with
  boundary-anchored matches, never concatenated.
- The align-button `disabled` pass lives in `refreshToolbarState` (`DIVERGENT`); the `is-on` clearing
  lives in `refreshAlignButtons` (`TWIN`, byte-identical in both files).
- `CellImageSize` deliberately duplicates `ImageElement.Size` and intentionally **shares its msgids**;
  it is not aliased, because the two scales must evolve independently.
- The delegator keeps the signature `resolve_image_cells(cells, course=None)` and never exposes
  `empty_cell`.
- `table_editor.js`'s toolbar click handler gains the fill table's
  `focusCell.hasAttribute("contenteditable")` clause; the disable pass alone is not sufficient.
- The plain table's alt input gets a real `input` listener (a **`DIVERGENT`** twin — it queries
  `.table-editor__img`); markup alone would ship a dead control.
- Both partials emit `cell-img--{{ cell.size|default:'full' }}`; `.cell-img` declares only
  `height: auto; display: block`.
- `refreshToolbarState` **derives its own null-safe `isImage`** in both editors; the mandated
  `showCellCtl` block references it, and `table_editor.js` has no such name today — copying the block
  without the derivation is a `ReferenceError` under `"use strict"` at the init-time call.
- **Five** `DIVERGENT` reasons go stale, including `serialize`'s "the plain table emits one" kind.
- Anonymous callbacks (the picker hook, the `change`/`input` listeners) are **outside**
  `test_editor_twin_drift.py`'s contract — `_DEF` matches named declarations only, and inventing a key
  reddens `test_no_stale_classification`. Only `setImageCell` and `stashFor` are real obligations.
- `toggleAnswerCell`'s `if (imageAlt) imageAlt.hidden = true;` is the **third** bespoke `imageAlt`
  painting site and is deleted too.
- The cell-scoped **buttons** carry `disabled` in markup, exactly as the new controls carry `hidden` —
  otherwise **twelve** buttons in `_edit_filltable.html` and **eleven** in `_edit_table.html` ship
  live-and-dead until `wire()` runs, and permanently if it never does. **`_rte_swatches.html` is NOT touched** — it is shared by six toolbars whose editors have no
  `disabled` mechanism, so editing it would permanently disable colour authoring in four of them.
- The `contenteditable` clause on `table_editor.js`'s click handler is **defence-in-depth/twin-parity**,
  deliberately **unpinned** — after `setImageCell` calls `refreshToolbarState()`, the button is already
  `disabled`, so a UI-level "convert then click math" test is unfalsifiable.
- The CSS class guard has **three durable contracts** — per-file (never concatenated), "named
  somewhere" and "a base rule exists" as **separate** assertions, and every class present as a whole
  quoted literal in the JS. The patterns given are illustrations of those contracts; whatever form is
  written must be **verified to fail when the base rule is deleted**.
- The 255 `alt` bound lives in **`_sanitized_data` as well as `_cell`** — `save()` never normalizes, so
  `_cell` alone does not make "truncated at save" true.
- **Both** picker callbacks guard on a null `focusCell`; both are defence-in-depth, since
  `[data-image-toggle]` is `disabled` with no focus.
- `stashFor` is a **`TWIN`** (the plain table keeps the unused `answer: null` slot verbatim);
  `setImageCell` is **`DIVERGENT`** — its bodies cannot match (preview class name, `data-answer`).
- The `serialize()` `forEach` callbacks **derive their own** `isImage` (and `isAnswer` in the fill
  table) as their first statements; no such binding exists in either file today.
- The render-level byte guard uses **non-empty** cells; `{% spaceless %}` collapses `<td>\n</td>`, so
  an empty-cell fixture cannot falsify either whitespace mutant.
- `filltable_editor.js` must also acquire **`sizeSel`**, and **declare `removeBtn`** even though its
  query returns `null` — "safe by accident" applies to `imageAlt` alone.
- The picker hook returns `function (id, _name, url)` where **`id` is a string**; the callback
  `parseInt`s it.
- `_ser_table`'s `.get` reads carry the **same defaults** as the delegator's `empty_cell`.
- `courses.css` ends up with **no `.filltable__img` rule**; the class stays in the template.
- Django `default` filters are written single-quoted (`|default:'full'`), matching `_edit_table.html`.
- `TableElement` gets its **own** delegating `resolve_image_cells(cells, course=None)`, so there is one
  `empty_cell` per model rather than two lambdas per model.
- The CSS class match is anchored on **both** sides (`(?<![\w-])\.{cls}(?![\w-])`); a trailing `\b`
  lets a modifier rule satisfy the base-class assertion.
- **`focusin` is the ONLY selector that widens** to `[data-image]`; the Enter-`keydown` and `input`
  handlers stay `[contenteditable]`-only. (There is no "post-merge/delete focus fallback" selector —
  see the correction in the focus section.)
- The `afterStructuralEdit` disconnect predicate is **`focusCell && !focusCell.isConnected`** — the
  bare `!focusCell.isConnected` throws on a row insert before any cell is focused.
- `serialize()`'s `size` read is `td.dataset.size || CELL_IMAGE_DEFAULT`; the bare `"full"` literal
  leaves the mandated source pin guarding nothing.
- **Both** editor partials use `|default:'full'` on `data-size` and on the preview modifier class,
  not just the plain table's.
- `_element_mids`'s new `table` branch tests `isinstance(c.get("media"), str)` — it runs
  **post-serialization**, where `media` is a local string id.
- `TableElementForm.clean_data` binds `nd = normalize_data(data)` **before** the scoping check and
  scopes over `nd["cells"]`; the fill table's expression applied to raw rows 500s.
- `refreshAlignButtons` must not simply drop its `!focusCell` guard — the body dereferences
  `focusCell.dataset`, and this slice calls it at init with no focus.
- The names are `TableElement.CellImageSize`, `TableElement.DEFAULT_CELL_IMAGE_SIZE`,
  `TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE` — nested on the model, not module-level.
- `_ser_table`'s defensive-shape fixtures are **export-only**; those archives are legitimately not
  importable.
- `window.libliFillTablePickImage` keeps its pre-existing last-wins single global — out of scope.

## Line-number policy

This spec cites code **by symbol name**, not line number. An earlier draft's line citations had
already drifted by 1–3 lines against the current tree, which erodes the verification value they
were meant to add. Implementers should locate symbols by name.
