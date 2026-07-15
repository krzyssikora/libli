# Two-column layout element

## Purpose

Add a new **container** content element that arranges its nested child elements
into **2–4 equal-width columns** side by side. It is the last active-tier item in
the interactive-elements roadmap, ported from the legacy Demo Course `.two_columns`
widget (`left_column` / `right_column`, 50/50, `min-width` so it stacks on mobile).

In libli the modern equivalent is a container element holding real nested `Element`
join rows — exactly like the existing **Tabs** element, but simpler: it shows all
content at once, so there are **no hidden panels, no enhancer JS, and no reveal
handshake**. This is a genuine simplification over Tabs/Gallery.

- **Model:** `TwoColumnElement`
- **Form key:** `twocolumn`
- **Transfer key:** `two_column`
- **Palette group:** Content (top-level only, gated `{% if not nested %}`, alongside Tabs)
- **ELEMENT_MODELS:** 28 → 29
- **Migration:** next available (~0047)
- **FORMAT_VERSION:** unchanged (reuses the existing parent/tab_id on-disk shape)

## Scope decisions

1. **Column count:** configurable **2–4** (mirrors Tabs' 2–10 count model), equal width.
2. **Child allowlist:** the **same as Tabs** — `NESTABLE_TYPE_KEYS`
   (text, math, image, video, iframe, html, table, gallery, callout, spoiler,
   reveal_gate, fill_gate, switch_gate, switch_grid, fill_table, stepper).
   **No questions, no nested containers** (no tabs or two-column inside a column).
3. **Two-column is NOT itself nestable** — top-level only, like Tabs. Do **not**
   add `two_column` to `NESTABLE_TYPE_KEYS`.
4. **Reducing column count with content in the dropped column:** the dropped
   column's children are **moved (appended, in order) to the new last column**.
   Author content is never silently deleted.

Non-goals (YAGNI): configurable column ratios / per-column widths (equal only);
column labels or headings; questions or nested containers inside columns; more than
4 columns; any JavaScript-driven layout behavior.

## Architecture / components

### Model & data — `TwoColumnElement`

A thin container model (like `TabsElement`) whose `data` JSON holds only the ordered
list of column **stable ids**:

```json
{ "columns": [ { "id": "c1a2b3" }, { "id": "cf9e0d" } ] }
```

- Column ids are `c` + 6 hex, stable across re-saves (children reference them via
  `Element.tab_id`). Columns have **no labels**.
- Count is `len(columns)`, clamped to **2–4**.

**Two normalizers, mirroring Tabs (a rule that bit the Tabs build twice):**

- `normalize_ids(data)` — **non-destructive**, save-side, persisted: keeps existing
  ids, mints ids for new columns, never invents phantom ids. Used by `save()` and by
  write-path validation (`resolve_scope`).
- `normalize_data(data)` — **destructive**, read-side only: pads/truncates to the
  2–4 range and may mint fresh ids. **`save()` must NEVER call this** — doing so would
  mint phantom column ids and orphan children.

Name the two methods to make the contract obvious and add a docstring on each stating
the destructive/non-destructive split and the "save() must not call the destructive
one" rule, so the Tabs footgun is not re-introduced.

### Children — reuse the existing join-row substrate unchanged

No new fields on `Element`. A child of a two-column element is an `Element` join row
with:

- `parent` = the two-column element's own join row,
- `tab_id` = the **column id** it lives in,
- `order` scoped to `(unit, parent, tab_id)` (columns may reuse integers),
- `unit` FK kept (so `Course.delete` / `ContentNode.delete` sweep children up).

This is byte-for-byte the same shape Tabs uses; `tab_id` is simply reinterpreted as
"column id" for two-column parents. Every element walker that already filters
`parent__isnull=True` (render contexts, node/unit panels, editor rows, and the quiz/
review/rollup COLLECT paths) continues to work unchanged, because a two-column's
children are excluded from top-level iteration by the same `parent__isnull=True`
filter that excludes tab children today.

### The one real refactor — generalize `resolve_scope`

`courses/builder.py:resolve_scope` currently hardcodes the container type:

```python
if not isinstance(parent_obj, TabsElement):
    raise NestingError("parent is not a tabs element")
valid_tab_ids = {t["id"] for t in TabsElement.normalize_labels_and_ids(...)["tabs"]}
```

Generalize it to accept **any container parent**, dispatching to the correct
valid-slot-id set:

- Introduce a small **container registry** — a mapping from container model to
  `(non_destructive_normalizer, slot_list_key, slot_id_key)`, e.g.
  `TabsElement → (normalize_labels_and_ids, "tabs", "id")`,
  `TwoColumnElement → (normalize_ids, "columns", "id")`.
- `resolve_scope` looks the parent's model up in the registry; a parent not in the
  registry raises `NestingError("parent is not a container")` (preserving today's
  reject-non-container behavior, just generically).
- It validates the incoming slot id (the `tab` param — reused verbatim as the column
  id) against that container's valid ids, computed with the **non-destructive**
  normalizer (same reasoning as Tabs: a destructive normalizer could validate against
  an ephemeral phantom id and silently orphan the child).

The child-nestability check (`nestable_key not in NESTABLE_TYPE_KEYS`) is unchanged
and still applies. A future 3rd container becomes a one-line registry entry.

### Render — `templates/courses/elements/twocolumnelement.html`

- A flex row of N column `<div>`s. Each column renders its children through the same
  recursive element-render include the Tabs panels use (children grouped by their
  `tab_id` == column id, ordered by `order`).
- CSS: `display: flex; flex-wrap: wrap; gap`; each column `flex: 1 1 <min>;
  min-width: ~260px`. On narrow screens columns wrap and stack naturally. Themed for
  light + dark via existing tokens.
- **Zero JS.** No enhancer, no `editor.html` `<script>`, no reveal handshake, no
  "invisible in the preview pane until JS loads" footgun.
- `has_math` recurses through children via the already-generic `_element_has_math`,
  so nested math/table/gallery still load KaTeX.
- An empty column renders as an empty flex cell (keeps alignment), same as Tabs
  renders an empty tab.

### Editor — `templates/courses/manage/editor/_edit_twocolumn.html`

- A **column-count control (2–4)** plus the recursive nested-element list
  (`_element_row.html` include) per column — reusing the Tabs editor pattern, minus
  label editing. Field names in the partial must match the form's field names (a
  missing/mismatched partial 500s `TemplateDoesNotExist` on palette-card click).
- Prefer a no-JS `<select>` that re-renders on save if that suffices; only add a JS
  editor helper if genuinely needed. If a helper is added, it must be wired into
  **BOTH** `editor.js` (re-run the re-init after each fragment swap, next to the
  gallery/tabs re-inits) **AND** `editor.html` (add the `<script src=... defer>`) —
  the step missed twice historically (gallery, reveal-gate). Guard with a test that
  GETs `manage_editor` and asserts the script is present. (If the element ships
  fully no-JS, this guard is unnecessary — state which path was taken.)

### Transfer

- Add `two_column` to `SERIALIZERS` (export.py), `VALIDATORS` (payloads.py), and
  `BUILDERS` (importer.py). The snake_case transfer key differs from the `twocolumn`
  form key — keep them straight.
- Children ride the **existing two-pass parent/tab importer** unchanged (`parent` /
  `tab` refs already round-trip for Tabs; the column id travels in the `tab` ref).
- **No `FORMAT_VERSION` bump** — the on-disk shape (parent + tab_id) is unchanged; a
  new element *type* alone does not change the format (per the reveal-gate
  "don't bump for a new type" lesson).

## Data flow

**Authoring (add):** palette card `twocolumn` → `element_add` → `_host_form` includes
`_edit_twocolumn.html` → author picks column count → `save_element` creates the
`TwoColumnElement` + its join row, `save()` runs `normalize_ids` to persist stable
column ids.

**Authoring (add child):** the nested add-menu (rendered with `nested=True`, questions/
containers hidden) posts a child element with `parent` = the two-column join row pk and
`tab` = the target column id → `resolve_scope` validates the parent is a registered
container and the column id is valid → child `Element` row saved with `parent` +
`tab_id` set, `order` scoped to `(unit, parent, tab_id)`.

**Authoring (reduce count):** author lowers the count → `save_element` (or the form's
save path) runs `normalize_ids` to compute the surviving column ids, then reassigns
any child whose `tab_id` is a dropped column to the **new last column id**, appended
after that column's existing children (recompute `order` within the target group).
Implemented server-side so it holds regardless of the client.

**Rendering:** top-level walkers filter `parent__isnull=True`, so the two-column join
row is iterated but its children are not; the `twocolumnelement.html` template pulls
its children (`parent=<join>`), groups them by `tab_id`/column, orders within column,
and renders each through the recursive element include. `has_math` recurses via
`_element_has_math`.

**Transfer:** export serializes the `columns` list and emits children with `parent` /
`tab` refs; import is two-pass (parents first, then children resolve their `parent` /
`tab` refs), reusing the existing Tabs machinery.

## Error handling

- **Orphan prevention:** `save()` never calls the destructive `normalize_data`; the
  non-destructive `normalize_ids` is the only save-side normalizer, so column ids are
  stable and children are never orphaned by a re-save. This is the single most
  important invariant (Tabs learned it twice).
- **Reduce-count safety:** children in a dropped column are reassigned, never deleted;
  a test asserts none are lost.
- **Bad nesting refs:** `resolve_scope` raises `NestingError` (→ 400) for an unknown
  parent, a non-container parent, an unknown column id, or a disallowed child type —
  same failure surface Tabs already has, now generic.
- **Missing edit partial:** covered by an authoring-path test (GET **and** POST
  `manage_element_add` for `twocolumn` → 200), guarding the `TemplateDoesNotExist`
  500 footgun.
- **Count clamp:** the destructive read-side `normalize_data` clamps out-of-range
  counts to 2–4 so a malformed payload never renders 0/1/5+ columns.

## Testing

- **Model:** `normalize_ids` stability (existing ids kept, new minted, none invented);
  `normalize_data` clamps to 2–4; `save()` never destroys/re-mints ids.
- **`resolve_scope`:** accepts a `TwoColumnElement` parent + valid column id; rejects
  unknown column id, a question (non-container) parent, and a container-in-container
  attempt.
- **Reduce-count orphan move:** 3→2 with children in column 3 → children reassigned to
  column 2, appended in order, none deleted.
- **Authoring path:** `manage_element_add` GET **and** POST for `twocolumn` → 200
  (guards the `_edit_twocolumn.html` partial-missing 500 footgun).
- **Render:** N columns present; children render in the correct column in order; empty
  column renders; `has_math` recurses (KaTeX loads for nested math).
- **Transfer:** export → import round-trip with nested children preserves column
  assignment and order; ELEMENT_MODELS count assertion updated 28 → 29; no
  `FORMAT_VERSION` change.
- **Drag-reorder regression guard:** the Tabs `:scope > .el-row` fix still holds with a
  two-column element expanded (nested rows not matched by the top-level reorder query).
- **Frontend-design pass** on the student render + editor UI before completion
  (explicit user requirement): verify light + dark with screenshots and self-critique.
- Full non-e2e suite + focused e2e; ruff / format / migration / i18n (EN + PL) clean.

## Touch-points checklist (keep in lockstep)

- `ELEMENT_MODELS` (models.py) 28 → 29 + concrete `TwoColumnElement` model + migration (~0047)
- `FORM_FOR_TYPE` (element_forms.py) + `TwoColumnForm`
- `save_element` (builder.py) — incl. reduce-count orphan-move logic
- `resolve_scope` (builder.py) — **generalized container-parent check** (the real refactor)
- `_add_menu.html` palette card (Content group, `{% if not nested %}`)
- `element_add` / `element_save` tuples (views_manage.py)
- `_EDITOR_TYPE_LABELS` (views_manage.py)
- `_ELEMENT_LABELS` + `element_summary` (courses_manage_extras.py)
- `templates/courses/elements/twocolumnelement.html` (student render)
- `templates/courses/manage/editor/_edit_twocolumn.html` (edit-form partial)
- transfer trio `SERIALIZERS` / `VALIDATORS` / `BUILDERS`
- `NESTABLE_TYPE_KEYS` — **not** added (containers don't nest)
- i18n EN/PL
- no enhancer JS to wire (zero-JS element) unless the count control needs a helper
