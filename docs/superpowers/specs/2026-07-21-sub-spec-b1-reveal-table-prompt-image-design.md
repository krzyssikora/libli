# Sub-spec B1: reveal-table prompt-image extraction

## Purpose

Sub-spec B of the matematyka image-loss recovery is the parser-only tail (47
images / 22 files remaining after the fill-table image-cell + nestable-spoiler
work). It is split into independent slices; **B1 is the largest coherent one:
reveal-table prompt images — 18 images across 5 files.**

A LAL "reveal table" (`_is_reveal_table`: a `my_table*`-classed table or one with
a `.question_solution` cell) is mapped by `scripts/lal_import/lesson.py:
_reveal_table_spoilers` to **one `SpoilerElement` per row**: the row's first `<td>`
text becomes the spoiler label ("zobacz" / "pokaż" button text) and the row's
`.question_solution` (hidden) div is walked into the spoiler body. But each row's
cell ALSO contains a `.question_answer` div — the **always-visible prompt** shown
before the student clicks "zobacz" — and that div is **never walked, so its
`<img>` is silently dropped**. Verified on `100_geometria_2/240_pole_trojkata`
(the largest, 7 lost): each of the 7 rows has
`<td><div class="question_answer"><img …></div><div class="question_solution
hidden">…<img …></div></td>`; the `question_solution` image is emitted inside the
spoiler (7 recovered), the `question_answer` prompt image is lost (7 lost).

Affected files (measured via `measure_lost_imgs_recursive.py` / the per-image
classifier, `reveal_table_cell` bucket): `100_geometria_2/240_pole_trojkata` (7),
`050_ulamki_algebraiczne/330_funkcja_homograficzna` (6),
`030_kwadratowa/kwadratowa_140_wlasnosci` (2),
`090_trygonometria_1/011_zwiazki_tryg` (2),
`104_geometria_3_czworokaty/040_wstep` (1) — total 18.

## Scope

- **In scope:** emit each reveal row's `.question_answer` (visible prompt) content
  as visible sibling elements — images preserved as `ImageElement`, text as
  `TextElement`, in reading order — BEFORE the row's spoiler. Parser-only
  (`_reveal_table_spoilers` in `scripts/lal_import/lesson.py`).
- **Out of scope:** B2 (question-stem images), B3 (figure/switch-in-`<details>`),
  B4 (inline + leftover fill-table cells) — separate slices. No model, loader,
  transfer, or editor change (the recovered images are ordinary `ImageElement`s /
  `TextElement`s the existing pipeline already renders and edits).

## Background: the current reveal-table path

- **`_is_reveal_table(table)`** (`lesson.py` ~226): true if the table is
  `my_table`-classed OR contains a `.question_solution`.
- **`_reveal_table_spoilers(table, consumed, state)`** (`lesson.py` ~235): iterates
  `table.find_all("tr")`; for each `<tr>` with a `.question_solution`:
  - `sol = tr.find(class_="question_solution")`
  - `first_td = tr.find("td")`; `label = first_td.get_text(strip=True)` (the first
    cell's text — depending on the file this is a "zobacz"/"pokaż" show-solution
    button OR a concept name, e.g. `test_r3_…` uses a concept like "Suma zbiorów").
    The fix below is unaffected by which; it only touches the `question_answer` cell.
  - `_flag_relative_hrefs(sol, flags)`
  - `_emit_solution_region(label, list(sol.children), elements, flags, consumed,
    state)` → appends a `{type:"spoiler", label, elements:[…]}` (top level) whose
    children are the walked `question_solution` content (so the solution image
    survives as an `ImageElement` child — this is the nestable-spoiler win).
  - Returns `(elements, flags)`.
- The **`.question_answer`** div (sibling of `.question_solution` inside the same
  data `<td>`) is never referenced → dropped. It holds the visible prompt (often a
  figure/diagram image) the student sees before revealing the solution.
- **`_walk` is the chosen entry point** for `question_answer` (see Design). `_walk`
  dispatches each child individually: a bare `<img>` child → `ImageElement`
  directly; a `<figure><img>` → `_emit_figure` (figcaption preserved); a text-tag
  child that itself contains `<img>` → the shipped prose-image split
  (**`_emit_text_with_images` / `_emit_text_or_images`**: split into `TextElement`s +
  `ImageElement`s in reading order, NavigableStrings math-escaped, tags
  re-serialised, so the image is not stripped by the sanitized `TextElement.body`).
  We do NOT call `_emit_text_or_images(ans, …)` directly (that treats the whole div
  as one text block); walking the children routes each correctly.
- **`_walk(nodes, elements, flags, consumed, state)`** is the general dispatcher;
  it already routes an `<img>`/`<figure>`/text-with-images to the right emitter.

## Design

In `_reveal_table_spoilers`, for each row that has a `.question_solution`, **before
the `_emit_solution_region` call**, locate the row's visible prompt and emit it:

- `ans = tr.find(class_="question_answer")`.
- If `ans` is present, emit its content as visible siblings by walking its children
  into the same `elements` list: `_walk(list(ans.children), elements, flags,
  consumed, state)`. `_walk` routes an `<img>` (or a text-with-`<img>` block) through
  the image-aware path, so the prompt image becomes an `ImageElement` and any
  accompanying prompt text becomes a `TextElement`, in reading order. **No `consumed`
  bookkeeping is needed:** the caller (`_walk`'s `name == "table"` branch) does NOT
  add the table to `consumed`; double-walk is prevented simply because the reveal
  table is fully handled by the `_is_reveal_table` branch and its descendant cells
  are never enqueued into any other `_walk` call, so `ans` is reached exactly once
  (here). Do NOT add a spurious `consumed.add(id(table))`.
- Then emit the spoiler exactly as today (`_emit_solution_region(label,
  list(sol.children), …)`).

Result per row: `[prompt ImageElement/TextElement…]` then `[Spoiler("zobacz"){
solution children}]` — the prompt image is now visible, the solution (with its own
image) stays behind the reveal.

### Edge cases (pin in planning)

- **Row with no `.question_answer`** (some reveal tables have only a label cell +
  solution): emit nothing extra — unchanged behaviour.
- **`question_answer` with text but no image**: `_walk` emits a `TextElement` for
  the prompt text. This is NEW visible content (previously dropped). Confirm this
  is desirable — it is: the prompt text was being lost too; showing it is more
  faithful. (If any file's `question_answer` is purely decorative/duplicate, note
  it; none observed in the 5 affected files.)
- **`question_answer` inside a spoiler / nested reveal** (`state["in_spoiler"]`):
  `_reveal_table_spoilers` is already called in both top-level and in-spoiler
  contexts; walking `ans` in the in-spoiler context emits inline siblings (the
  nestable-spoiler INLINE mode) — consistent with how `_emit_solution_region`
  already branches on `state["in_spoiler"]`. Verify the prompt walk respects the
  same branch (it does, because `_walk` reads `state`).
- **`first_td` vs the answer cell**: the label still comes from the first `<td>`.
  The `question_answer` is in the data `<td>` (a later cell). Do not confuse them.
- **`question_answer` / `question_solution` are disjoint siblings** (verified: in the
  5 affected files both are separate `<div>`s inside the same data `<td>`). The fix
  relies on this — if a file ever NESTED `question_solution` inside `question_answer`,
  `_walk(list(ans.children))` would also walk the solution div (which, without a
  following `show_solution` button, falls to the `_unmapped` flagged-html catch-all),
  double-emitting/flagging. Add a test asserting the sibling structure; none of the 5
  files nest, so this is a guard, not a handled case.
- **Ordering across rows**: emit prompt-then-spoiler per row, preserving row order,
  so a multi-row reveal table reads prompt₁, spoiler₁, prompt₂, spoiler₂, …

### Why parser-only

The recovered prompt image is an ordinary top-level `ImageElement` (or a spoiler
child in the in-spoiler branch) — both already render, transfer, and edit. No new
model/loader/transfer/editor capability is needed; only the parser stops dropping
the `question_answer` content.

## Testing

TDD, falsifiable (RED first). Build fixtures by EXTENDING the existing reveal-table
tests in `tests/lal_import/test_lesson.py` (`test_r3_reveal_table_becomes_spoilers_
per_row` / `test_reveal_table_row_becomes_nested_spoiler`) so the table shell
(`my_table*` class or a `.question_solution`, a label `<td>`, `<tr>` scaffolding)
routes through `_reveal_table_spoilers` — a bare fixture without that shell won't.

- **Prompt image extracted**: a reveal table whose row has
  `<div class="question_answer"><img src="p.png"></div>` +
  `<div class="question_solution hidden"><img src="s.png"></div>` (in a proper
  `my_table`/`question_solution` shell with a label td) emits, in order, an `image`
  element for `p.png` (the prompt) THEN a `spoiler` whose children include an `image`
  for `s.png` (the solution). RED today (only `s.png` emitted).
- **Prompt text + image** split into `text` + `image` in reading order.
- **Prompt text only** (no img) → a `text` element before the spoiler.
- **No `question_answer`** → only the spoiler (unchanged); no spurious element.
- **In-spoiler context**: a reveal table nested inside a `<details>`/spoiler emits
  the prompt inline (no nested container), matching `_emit_solution_region`'s
  in-spoiler branch.
- **Regression**: the existing reveal-table tests (spoiler label, solution
  children) still pass; solution-image recovery is unchanged.
- **Integration / count**: re-parsing the 5 affected files, the `reveal_table_cell`
  lost count drops 18 → 0. **Measurement prerequisites:** the source LAL HTML tree
  must be present (external `source_root`, `C:/Users/krzys/Documents/teaching/LAL/
  html`), and the measure scripts live in the session scratchpad, not the repo —
  `measure_lost_imgs_recursive.py` + `classify_lost_imgs.py` (both already updated to
  count fill-table image cells). Reseed the parts (`parser <part> --force`) before
  measuring; the committed `out/*.json` is stale between parser changes.

## Verification

- Reseed the 5 affected parts (`100_geometria_2`, `050_ulamki_algebraiczne`,
  `030_kwadratowa`, `090_trygonometria_1`, `104_geometria_3_czworokaty`), reload
  into `libli_mat`, re-measure: total lost 47 → 29 (B2–B4 remain), reveal-table
  bucket → 0.
- Render a sample unit (e.g. 240_pole_trojkata's unit): each row now shows the
  prompt diagram, then a "zobacz" spoiler revealing the solution diagram. Hand the
  user the URL (DEBUG server per the `.env`).

## Out of scope / follow-up slices

- **B2 — question-stem images (15/6):** images inside `<div id="questionN">` stems
  (`020_uklady_rownan/uk_rown_30` ×3, `090_trygonometria_1/040`+`044` ×3 each,
  `100_geometria_2/180`+`280`, `080_geometria_analityczna/110_geo_an`). Extract
  stem `<img>` → sibling `ImageElement` (the shipped `_mcq_stem`/u/229 pattern,
  generalised to all question types). Its own spec.
- **B3 — figure/switch-in-`<details>` (10/8):** `<figure><img>` and `switch_steps`
  images nested in `<details>` that the nestable-spoiler path doesn't extract
  (`104_geometria_3_czworokaty/*`, `090_trygonometria_1/080`, `100_geometria_2/030`,
  `140_geometria_analityczna_2/300`). Its own spec.
- **B4 — inline (2) + leftover fill-table cells (2):** `030_kwadratowa/
  kwadratowa_161`+`162` (free-floating `<img>` the prose split missed) and
  `100_geometria_2/250_pole_trojkata` (2 fill-table cells not caught by the
  pure-image branch — likely mixed content; investigate). Small tail.
