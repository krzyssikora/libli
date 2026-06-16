# Phase 1b — WS2: Course-builder UX overhaul (design)

Date: 2026-06-16 · Status: design accepted (brainstorming), pending spec review → plan.
Accepted mockup: `docs/mockups/builder_accepted.html` (light + dark, all five items).

## 1. Scope

Redesign the **course-builder tree pane** and the **Move picker** (which lives in the
detail panel). Covers the five WS2 triage items:

- **#5** connector lines (tree hierarchy is too subtle)
- **#6** a tidy, consistent per-row control cluster
- **#8** a Move UI that shows *which* node is moving and allows precise placement
- **#11** contextual "+" add affordances (only legal kinds; no persistent kind dropdown)
- **#9c** drag-and-drop reorder/re-parent (pointer devices)

The full design is captured now so the markup/CSS/JS are built once; **implementation may
still sequence #9c last** (see §9).

**Out of scope:** the detail-panel editors, element/media work (other slices); the
delete-confirm flow (unchanged — see §4.6); touch drag-and-drop (deferred, §4.5); a
keyboard "drag mode" (the ↑/↓ buttons + Move picker already give keyboard users full
reorder/re-parent). No model or migration changes. No new server endpoints.

## 2. Current state (what we're changing)

Two-pane layout (`builder.html`): left `.builder__tree`, right `.builder__panel[data-panel]`.
The tree is a recursive `<ol>`/`<li>` structure:

- `_scope.html` — `<ol class="tree__scope" data-scope data-updated>` wrapping a parent's children.
- `_tree_node.html` — a `<li class="tree__row" data-node data-updated data-kind data-parent>` with
  a kind badge, a `data-select` title button, an action span (`_move_buttons.html` ↑/↓ form +
  `Move…` link + `Delete` link), and — for non-units — a nested `_scope.html` + `_add_form.html`.
- `_add_form.html` — a persistent per-scope form: title input + **kind `<select>` listing ALL
  kinds** + (hidden) unit_type select + Add.
- `_move_picker.html` — panel form: node_token + a `<select name="new_parent">` of candidates +
  a numeric `position`.

Backend (unchanged, already fully tested in `tests/test_manage_node_ops.py`):

- `courses/views_manage.py`: `node_add`, `node_move` (`mode=reorder` ±1 / `mode=reparent` with
  `position`), `_move_picker`, `_render_scope`/`_render_tree`, `_children_map`.
- `courses/builder.py`: `add_node`, `reorder_node`, `reparent_node` (+ `place_node` at a 0-based
  position), optimistic `_check_token`.
- `courses/ordering.py` + `ContentNode.RANK = {part:0, chapter:1, section:2, unit:3}`; a child's
  kind must be **strictly deeper** than its parent's.
- `courses/static/courses/js/builder.js` — fetch-and-swap by `[data-scope]`; panel-refresh after a
  panel-form op (the #9 fix); `_move_picker` reads each option's `data-updated` as `parent_token`.
- `courses/static/courses/css/builder.css` — interim layout (to be largely replaced).

This is a **frontend redesign**: templates, `builder.css`, `builder.js`. The service layer and
endpoints are reused as-is; drag-and-drop and the new Move picker map onto the **existing**
`reorder`/`reparent` contracts.

## 3. Legal-kind logic (shared by #11 and #9c)

`legal_child_kinds(parent)` = kinds strictly deeper than the parent's, in RANK order; at the top
(no parent) all four are legal:

| parent | legal child kinds (RANK order) |
|---|---|
| top (none) | part, chapter, section, unit |
| part | chapter, section, unit |
| chapter | section, unit |
| section | unit |
| unit | — (units hold elements, not nodes) |

A new server helper (e.g. `courses/ordering.py:legal_child_kinds(parent_kind_or_None)`) returns
this list; it is the single source for both the contextual "+" affordances and the drag-drop
drop-legality check. It mirrors the depth rule already enforced in `ContentNode.clean()`.

## 4. Design decisions

### 4.1 #5 — Connector lines

Vertical guide lines per nesting level via `border-left` on each nested `.tree__scope`
(`--border-strong` at the top level, `--border-default` deeper). No new markup — the nested
`<ol data-scope>` already exists. Light/dark both use border tokens (verified in the mockup).
Row elbow ticks are an optional later refinement, not required.

### 4.2 #6 — Per-row control cluster

Replace the loose action span with one right-aligned **icon cluster** per row:
`grip · ↑ · ↓ · move · delete`. Requirements:

- **Icon buttons** with `title` + `aria-label` tooltips; consistent sizing; right-aligned so
  titles line up across rows. Icons = an inline **SVG sprite** (`<symbol>`/`<use>`) defined once
  in `builder.html` (grip, up, down, move, trash).
- **Always visible**, low-contrast by default (`opacity ~.5`), brightening to full on row
  hover/focus and on the selected row. **No hover-only controls** — touch has no hover.
- Behaviour wiring (progressive enhancement, all existing):
  - ↑/↓ = the existing `data-op="reorder"` two-button form (works no-JS; JS fragment-swaps).
  - move = the existing `data-move` link → opens the picker in the panel (§4.3).
  - delete = the existing `data-delete` link → existing confirm flow (§4.6).
  - **grip** = drag handle; JS-only (§4.5). Absent/inert with JS off.

### 4.3 #8 — Move UI

The Move picker is redesigned and continues to live in the detail panel (reusing the #9
panel-refresh fix). When opened:

- The **moving node is highlighted** in the tree (JS adds a `moving` state to its row).
- The panel shows: a **"Move" header**, the **moving node as a chip** (badge + title), then a
  **"Destination & position"** control built as an **indented mini-tree of legal destinations**
  (the existing `_move_picker` candidate set: structural nodes whose kind is strictly shallower
  than the moving node's, excluding itself/descendants, plus "Top level").
- Selecting a destination reveals **insertion slots** between that destination's **current
  children** (all of them, since a position is among all siblings) — "insert at top / between
  each pair / at end". The chosen slot = the 0-based `position` passed to `reparent_node`. This
  is how arbitrary placement (e.g. between lesson 2 and 3) is expressed.

**Progressive enhancement:** the **no-JS baseline** is the existing picker form — a
`<select name="new_parent">` of candidates (each `<option>` carrying `data-updated`) + a numeric
`<input name="position">` — which already submits `mode=reparent` correctly. JS **layers the nice
UI on top**: it renders the indented destination tree + insertion slots, hides the raw
select/number, and on each click **syncs** the chosen destination into the hidden `new_parent`
select (so `parent_token` is read from that option's `data-updated`, as today) and the chosen slot
index into the hidden `position` field. One form, one endpoint, no ambiguity; the raw controls are
the source of truth that the enhanced UI drives.

### 4.4 #11 — Contextual "+" add affordances

Replace the persistent `_add_form.html` (with its all-kinds `<select>`) with **contextual
"+" chips** rendered at the end of each scope's child list (a new `_add_affordance.html`).
Each scope offers only `legal_child_kinds(parent)` (§3), rendered by this rule:

- `len(legal) == 0` → no affordance (units).
- `len(legal) <= 2` → a `+ Kind` chip per kind (RANK order). → Section: `+ Unit`; Chapter:
  `+ Section  + Unit`.
- `len(legal) >= 3` → a **primary** `+ Kind` chip + a `+…` **overflow** menu listing the rest
  (RANK order). `PRIMARY = {top: chapter, part: chapter}` (the only parents with ≥3 legal kinds).
  → top: `+ Chapter` + `+…`(Part, Section, Unit); part: `+ Chapter` + `+…`(Section, Unit).

This removes illegal choices by construction (solving #11's "shows forbidden kinds").

**Add interaction — inline new row:** clicking `+ Kind` inserts a transient editable row at the
add-spot, indented to that level, showing the kind badge and a focused title field.

- **Enter** (or **blur with non-empty text**) → POST the existing `node_add` (`parent`, `kind`,
  `title`, `parent_token` = the scope's `data-updated`; `unit_type=lesson` when `kind==unit`,
  else none). On 200 the scope swaps in the saved node (existing fragment flow).
- **Esc** (or **blur while empty**) → discard the transient row, no request.
- **Empty title + Enter** → inline "required" hint; stay editing (do not submit).
- Units default to **`unit_type=lesson`**; switch to quiz later in unit settings (quiz stays the
  Phase-2-inert placeholder). Keeps the inline row to a single field.

No-JS fallback: `+ Kind` chips are real submit buttons in a tiny per-kind form that posts
`node_add` with a title field (degrades to the current per-scope add behaviour, minus the
illegal kinds).

### 4.5 #9c — Drag-and-drop (pointer devices)

Grab a row by its **grip** handle to reorder or re-parent in one gesture. Built in `builder.js`.

- **Drop feedback:** a teal **insertion line** at the landing spot (indented to the target
  parent's level) + a dashed **highlight on the destination container** during dragover.
- **Mapping to the backend:** every drop = `mode=reparent` with `new_parent` = the target
  container (its pk, or "top") and `position` = the insertion index. This single path covers both
  same-parent reordering (to an arbitrary index — which the ±1 reorder buttons can't express) and
  cross-parent re-parenting, because `reparent_node`/`place_node` already accept same-or-different
  parent + 0-based position. Tokens: `node_token` = dragged row's `data-updated`, `parent_token`
  = target container's `data-updated`. On success the whole tree swaps + the panel refreshes
  (existing reparent flow + #9 fix).
- **Illegal drops refused client-side:** no insertion line / "no-drop" cursor when the dragged
  node's kind is **not** strictly deeper than the target parent's (`legal_kinds`, §3) or the
  target is the node itself or a descendant. The server still enforces this (`assert_not_descendant`
  → 422; depth via `full_clean` → 422) as defense-in-depth.
- **Pointer only.** Touch does **not** initiate drag (deferred); touch users reorder/re-parent
  with the always-visible ↑/↓ buttons and the Move picker, which cover every case. The ↑/↓
  buttons and Move picker remain for **all** users (precision, keyboard, accessibility).

### 4.6 Unchanged by design

- **Delete** keeps its existing confirm flow (with the cascade descendant/element-count warning);
  WS2 only restyles the trigger into the cluster. Data-safety stays explicit.
- **Layout** stays the two-pane tree | detail panel. The optimistic-token contract (409/422 +
  fresh fragment) and the #9 panel-refresh are unchanged and relied upon.

## 5. Components & files

- **Templates:** `_tree_node.html` (cluster + `draggable`/drag hooks + connector nesting),
  `_scope.html` (unchanged data attrs), `_move_buttons.html` (folded into the cluster's ↑/↓),
  **new** `_add_affordance.html` (replaces `_add_form.html`), `_move_picker.html` (rewritten:
  indented destinations + slots), `builder.html` (inline SVG icon sprite).
- **CSS:** `builder.css` — largely rewritten: connectors, cluster (always-visible/hover-emphasis,
  icon buttons), `+` chips + overflow menu, inline new-row, redesigned picker, drag insertion
  line + drop-target highlight + ghost. Light + dark via existing tokens (no new tokens).
- **JS:** `builder.js` — add: inline new-row lifecycle (insert/focus/Enter/Esc/blur), `+…`
  overflow menu, picker destination-select → reveal slots + `moving` highlight, drag-and-drop
  (grip drag, dragover insertion line + drop-target, legality check, drop → reparent POST). Keep
  the existing fetch-and-swap + panel-refresh.
- **Views (`views_manage.py`):** render the new `_add_affordance` per scope (needs
  `legal_kinds`); render the redesigned `_move_picker` (destinations + each destination's
  children for slots — reuse `_children_map`). `node_add` and `node_move`(reparent) are unchanged.
- **New helper:** `legal_child_kinds(parent_kind)` in `courses/ordering.py` (or a templatetag) +
  the `PRIMARY`/overflow grouping for the affordance template.

## 6. Data flow (summary)

- **Add:** `+ Kind` → inline row → `node_add(parent, kind, title, parent_token)` → scope swap.
- **Reorder (±1):** unchanged `mode=reorder` form → scope/tree swap.
- **Move (picker):** select destination + slot → `mode=reparent(new_parent, position,
  node_token, parent_token)` → whole-tree swap + panel refresh.
- **Drag-drop:** drop → same `mode=reparent` call (new_parent = container, position = insertion
  index) → whole-tree swap + panel refresh.

## 7. Accessibility & responsive

- Cluster icons are real `<button>`s with `aria-label`/`title`; always visible (no hover-only).
- Full keyboard path: Tab to a row's cluster, ↑/↓ to reorder, move to open the picker (radio
  destinations + slots, operable without a pointer). Drag is a pointer-only enhancement.
- Mobile/narrow: the two-pane grid stacks (existing `@media`); the picker stacks below the tree
  (or opens as a sheet). All actions reachable without hover or drag.

## 8. Testing

- **Playwright e2e** (extend `tests/test_e2e_builder_reorder.py` style; `-m e2e`): each level shows
  exactly its legal `+` kinds (Section → only `+ Unit`; top → `+ Chapter` + overflow); inline add
  creates the right kind; the cluster is visible and ↑/↓ reorder; the Move picker is indented and an
  insertion slot places a node at the chosen position (incl. between two existing children);
  drag-drop reorders within a parent and re-parents across, landing at the dropped slot; an illegal
  drag target is refused. Light + dark visual sanity.
- **Unit/view tests:** `legal_child_kinds` per parent kind (incl. top); `_add_affordance`/picker
  context (legal kinds, primary/overflow grouping, destinations); `node_add` defaults
  `unit_type=lesson` for inline unit add. Arbitrary-position reparent is already covered by
  `tests/test_manage_node_ops.py`.
- Regression: the existing builder e2e and `test_e2e_builder_reorder.py` must still pass.

## 9. Implementation sequencing

1. **Static tree + add (#5, #6, #11):** connectors, the SVG icon sprite + cluster, the
   `legal_child_kinds` helper + `_add_affordance` (chips/overflow) + inline new-row; retire
   `_add_form.html`. Rewrite the relevant `builder.css`.
2. **Move UI (#8):** rewrite `_move_picker.html` (indented destinations + slots) + the JS to
   reveal slots and highlight the moving node.
3. **Drag-and-drop (#9c) last:** grip drag, insertion line + drop-target, legality check, drop →
   reparent. Independent of 1–2 and the riskiest, so it lands on top of a working tree.

Each step keeps the suite green and the no-JS fallback working before the next begins.
