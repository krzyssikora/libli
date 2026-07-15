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
- **Palette group:** Content (top-level only, gated `{% if not nested %}`, alongside
  Tabs; mirrors Tabs' availability — present in **both** lesson and quiz palettes, as a
  layout-only container, with no extra quiz gate)
- **ELEMENT_MODELS:** 28 → 29
- **Migration:** next available — confirm the highest existing migration in the
  worktree at implementation time (0045 stepper / 0046 multi-select-grid are on
  still-open PRs, so the actual number depends on what is merged into the base branch)
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

- Column ids are `c` + 6 hex, matched by `COLUMN_ID_RE = re.compile(r"c[0-9a-f]{6}")`
  (mirroring Tabs' `TAB_ID_RE`), stable across re-saves (children reference them via
  `Element.tab_id`). A `new_column_id(taken)` helper mints a fresh non-colliding id.
  `normalize_ids` keeps an entry's id when it matches `COLUMN_ID_RE` and is unique, and
  mints a fresh one whenever the id is missing, malformed, or a duplicate. Columns have
  **no labels**.
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

**Initial state & form/save ownership (subtle — pin it exactly).** `normalize_ids` is
non-destructive and never *creates* columns, so a plain add+save with no column data
would persist `{"columns": []}`, and only the destructive read-side `normalize_data`
would then mint columns freshly on every render — the phantom-id orphan footgun. The
`TwoColumnForm` therefore carries **only** a `column_count` select (2–4); it does **not**
carry a `data` field, and `form.save()` must **never** write `columns` (so it can never
clobber persisted ids on edit). The `columns` list and its ids are owned entirely by the
model + `save_element`:

- **Create (`join is None`):** seed `columns` from `TwoColumnElement.default_data()` —
  **two** columns with freshly minted ids, built explicitly, **NEVER** via the
  destructive `normalize_data` — then run the **grow** step (see Data flow) to honor an
  initial `column_count > 2`.
- **Edit:** read the *existing persisted* `columns` from `instance.data` first, then run
  grow/shrink against it. **Never** re-seed from `default_data()` on edit.
- **Ordering, every case:** derive the new `columns` list → `normalize_ids` (validity /
  uniqueness) → set `obj.data` → `save()`.

This closes the footgun where a Tabs-style `clean_data`/`form.save()` returning
`default_data()` whenever "no column data is submitted" would, on edit (where a
count-only form *always* submits no column data), destroy existing column ids and orphan
every child before grow/shrink could read them. `default_data()` is a required
touch-point, but it is a **create-only** seed.

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
  **Registry contract:** each registered normalizer must return
  `{slot_list_key: [{slot_id_key: <id>}, …]}` — `slot_list_key` equals the key the
  normalizer actually emits (`"tabs"` for Tabs, `"columns"` for two-column), since
  `resolve_scope` indexes the normalizer output by `slot_list_key`; a mismatch would
  silently yield no valid ids. Pin this so a future third container cannot register a
  mismatched key.
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
- The model provides a no-arg **`render()`** (dispatched by `render_element` in
  `courses_extras.py`, like `TabsElement.render()`) and a **`resolved_columns()`**
  grouping helper (the columns-analogue of `resolved_tabs()`, plus `join_row()` if not
  inherited) that groups the join row's `children` by `tab_id`/column, ordered by
  `order`. The render template, the generalized export walk (`walk_unit_joins`), and
  `_twocolumn_has_math` should all consume this one grouping helper to avoid drift.
- CSS: `display: flex; flex-wrap: wrap; gap`; each column `flex: 1 1 <min>;
  min-width: ~260px`. On narrow screens columns wrap and stack naturally. Themed for
  light + dark via existing tokens.
- **Zero JS.** No enhancer, no `editor.html` `<script>`, no reveal handshake, no
  "invisible in the preview pane until JS loads" footgun.
- **`has_math` is NOT automatically generic — this must be wired explicitly.**
  `courses/views.py:_element_has_math` ends its dispatch at `_tabs_has_math`, which
  self-guards `isinstance(el, TabsElement)` and returns `False` for any other container;
  a `TwoColumnElement` would fall through every clause and report no math, so nested
  math/table/gallery inside columns would never trigger KaTeX loading. Add a
  `_twocolumn_has_math(el)` helper (mirroring `_tabs_has_math`: recurse over the join
  row's `children` via `_element_has_math`) and wire it into the `_element_has_math`
  fallback. `courses/views.py` is therefore a required touch-point.
- An empty column renders as an empty flex cell (keeps alignment), same as Tabs
  renders an empty tab.

### Editor — `templates/courses/manage/editor/_edit_twocolumn.html`

- The two-column **form manages only the column count** — nested children are added
  through the nested add-menu (separate posts carrying `parent` + `tab` refs), never
  through this form. So a **no-JS `<select name="column_count">`** submitting a bare
  integer 2–4 is sufficient; no JS mirror of a column-id list is needed (mirroring the
  surviving-id list into a hidden field is the only thing Tabs' `tabs_editor.js` existed
  for). The element therefore ships **fully no-JS** — no `editor.js` re-init and no
  `editor.html` `<script>`, so the "enhancer missing in the preview pane" footgun does
  not apply here.
- The editor renders one nested-element list (`_element_row.html` include) per column.
  Its ordered column-id list is sourced from the **persisted instance** (`instance.data`),
  **not** from submitted form data — unlike Tabs (whose form submits the full surviving
  tab-id list), the two-column form submits only a bare `column_count` with no ids, so a
  submitted-data source would mint fresh random ids and desync from the children's stored
  `tab_id`s. On a brand-new (unsaved) element, fall back to `default_data()`. Cache the
  resolved list (id-minting is otherwise re-randomized per call).
- The edit partial `_edit_twocolumn.html` must exist and its field names must match the
  form's field names (a missing/mismatched partial 500s `TemplateDoesNotExist` on
  palette-card click).

### Transfer

- Add `two_column` to `SERIALIZERS` (export.py), `VALIDATORS` (payloads.py), and
  `BUILDERS` (importer.py). The snake_case transfer key differs from the `twocolumn`
  form key — keep them straight. The `two_column` VALIDATOR must **enforce**
  `2 ≤ len(columns) ≤ 4` and well-formed column ids on import (mirroring the Tabs
  validator), rejecting an out-of-range or malformed blob rather than relying on
  render-time clamping to paper over it.
- **Two Tabs-hardcoded transfer paths must be generalized** (they are NOT
  container-generic despite the shared parent/tab substrate):
  - **Export — `courses/transfer/export.py:walk_unit_joins`** expands a container's
    children only via `if isinstance(obj, TabsElement): obj.resolved_tabs()`. A
    `TwoColumnElement` fails that check, so its children are **silently omitted from the
    export archive** (a two-column exports as an empty shell). Generalize it to expand
    any container's children parents-before-children (dispatch on the container registry
    or the shared `resolved_columns()` grouping helper).
  - **Import — `courses/transfer/payloads.py:validate_nesting`** is a cross-element check
    (distinct from the per-type `VALIDATORS`) that hardcodes `parent["type"] != "tabs"`
    and reads `parent["data"]["tabs"]`. For a `two_column` parent it rejects every child
    (wrong type) and would `KeyError` on a `columns`-only blob. Generalize the accepted
    parent types and the valid-slot-id lookup to cover any container (accept
    `two_column`, read `parent["data"]["columns"]` ids), mirroring the `resolve_scope`
    registry.
  Once generalized, children ride the same two-pass parent/tab importer as Tabs (the
  column id travels in the `tab` ref).
- **No `FORMAT_VERSION` bump** — the on-disk shape (parent + tab_id) is unchanged; a
  new element *type* alone does not change the format (per the reveal-gate
  "don't bump for a new type" lesson).

## Data flow

**Authoring (add):** palette card `twocolumn` → `element_add` → `_host_form` includes
`_edit_twocolumn.html` → author picks `column_count` → `save_element` creates the
`TwoColumnElement` + its join row, seeding `columns` from `default_data()` (two minted
ids) and running the **grow** step to honor `column_count > 2`, then `normalize_ids` →
`save()`. (A new element cannot start below 2 columns; grow is what makes an initial
pick of 3 or 4 stick.)

**Authoring (add child):** the nested add-menu (rendered with `nested=True`, questions/
containers hidden) posts a child element with `parent` = the two-column join row pk and
`tab` = the target column id → `resolve_scope` validates the parent is a registered
container and the column id is valid → child `Element` row saved with `parent` +
`tab_id` set, `order` scoped to `(unit, parent, tab_id)`.

**Authoring (change count):** the form submits a bare `column_count` integer (2–4).
`save_element` derives the new `columns` list from the *existing persisted* list — a
dedicated grow/shrink step, **distinct from `normalize_ids`**, because `normalize_ids`
(non-destructive) cannot itself add or drop columns from a count alone:

- **Grow (count > current):** append `count − current` new column dicts with freshly
  minted ids; existing columns and their children are untouched.
- **Shrink (count < current):** drop the **trailing** `current − count` columns (a count
  control cannot target a specific middle column). Reassign every child whose `tab_id`
  is a dropped column to the **new last column id**, appended after that column's
  existing children with recomputed `order` within the `(unit, parent, tab_id)` group.
  When multiple columns are dropped (e.g. 4→2, dropping 3 and 4), drain them in
  **original column order** (column 3's children, then column 4's), preserving each
  column's internal order, so the merge is deterministic.
  **Children are moved, never deleted** — this is the deliberate inverse of the Tabs
  `save_element` branch, which computes `removed = old_ids − new_ids` and *deletes* the
  doomed columns' children (`_delete_element_content_objects` then `.delete()`). That
  Tabs branch must **NOT** be copied here; copying it would silently destroy author
  content, violating scope decision 4.

`normalize_ids` then runs over the resulting list to guarantee id validity/uniqueness,
and `save()` persists it. All server-side, so it holds regardless of the client.

**Rendering:** top-level walkers filter `parent__isnull=True`, so the two-column join
row is iterated but its children are not; the `twocolumnelement.html` template pulls
its children (`parent=<join>`), groups them by `tab_id`/column, orders within column,
and renders each through the recursive element include. `has_math` recurses via
`_element_has_math`.

**Transfer:** export serializes the `columns` list and, via the **generalized**
`walk_unit_joins`, emits children with `parent` / `tab` refs (column id in `tab`); import
is two-pass (parents first, then children resolve their `parent` / `tab` refs) and passes
the **generalized** `validate_nesting` cross-check. Both walkers are Tabs-hardcoded today
and must be generalized (see the Transfer architecture section) — without that, export
silently drops children and import rejects them.

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

- `ELEMENT_MODELS` (models.py) 28 → 29 + concrete `TwoColumnElement` model (incl.
  `COLUMN_ID_RE`, `new_column_id`, `normalize_ids`, `normalize_data`, `default_data`,
  a no-arg `render()`, and a `resolved_columns()` grouping helper + `join_row()` if not
  inherited) + migration (confirm the next number in-worktree at implementation time)
- `FORM_FOR_TYPE` (element_forms.py) + `TwoColumnForm` (with `clean_data` returning
  `default_data()` on empty submission, and an `editor_rows`-equivalent for the editor)
- `save_element` (builder.py) — the `column_count` **grow/shrink** step (append minted
  columns on grow; drop trailing + **move** their children to the new last column on
  shrink, never delete)
- `resolve_scope` (builder.py) — **generalized container-parent check** via the
  container registry (the real refactor)
- `courses/views.py:_element_has_math` — add `_twocolumn_has_math` and wire it into the
  fallback (not automatically generic)
- `_add_menu.html` palette card (Content group, `{% if not nested %}`)
- `element_add` / `element_save` tuples (views_manage.py)
- `_EDITOR_TYPE_LABELS` (views_manage.py)
- `_ELEMENT_LABELS` + `element_summary` (courses_manage_extras.py)
- `templates/courses/elements/twocolumnelement.html` (student render)
- `templates/courses/manage/editor/_edit_twocolumn.html` (edit-form partial)
- transfer trio `SERIALIZERS` / `VALIDATORS` (enforce 2–4 + id shape) / `BUILDERS`
- `courses/transfer/export.py:walk_unit_joins` — generalize container-child expansion
  beyond `TabsElement` (else two-column children are silently dropped from export)
- `courses/transfer/payloads.py:validate_nesting` — generalize the parent-type +
  valid-slot-id cross-check beyond `"tabs"` (else two-column import rejects children)
- `NESTABLE_TYPE_KEYS` — **not** added (containers don't nest)
- i18n EN/PL
- **fully no-JS element** — no enhancer to wire into `editor.js` / `editor.html`
