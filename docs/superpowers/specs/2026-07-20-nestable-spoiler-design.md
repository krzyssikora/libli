# Nestable SpoilerElement (single-slot container)

## Purpose

Today `SpoilerElement` holds a single flat HTML `body`. The libli sanitizer
(`courses/sanitize.py`) strips `<img>` from every sanitized field, so any image
that lives inside a spoiler disappears. In the matematyka LAL import this is a
large, corpus-wide content loss: after the pure-image-table and prose-image fixes
(commits `a4e76ef`, `0998588`), ~640 images are still dropped, and the dominant
remaining bucket is **spoiler-type disclosures** — `<details>` blocks, reveal
tables (`my_table` + `show_solution`), and `show_solution`/`question_solution`
answer reveals — all of which the parser maps to `SpoilerElement.body`.

This feature makes `SpoilerElement` a **nesting container**: a spoiler can hold
ordered native child elements (text, math, image, table, …) instead of only a
flat body. Content behind a spoiler — including images and tables — then renders
correctly, and the change is general (not import-specific): it fixes the whole
"X inside a spoiler" class of problems, and gives authors the same nested-editing
UX that `TabsElement` already has.

Chosen approach (user-approved): **Approach A — mirror the Tabs join-row
substrate as a single-slot container.** Reuse the existing `Element.parent`
join-row machinery rather than adding a new nesting mechanism, and do **not**
refactor the working `TabsElement` / `TwoColumnElement` code.

User-approved scope decisions:
- **Full recursive builder editor now** (add / edit / reorder / delete child
  elements inside a spoiler), like the Tabs editor — not a deferred guard-only.
- **All spoiler sources** (`<details>`, reveal tables, `show_solution`) switch to
  the nested form in the importer.
- **Additive backward-compat**: keep `body`; existing authored spoilers are
  unchanged; the nested path is opt-in by the presence of children.

## Background: the existing nesting substrate

- **`Element`** (`courses/models.py`) is the generic join row: it has a
  `content_object` GFK, a self-referential `parent` FK, an `order`, and a
  `tab_id`. A container's own `Element` row is the "join row"; its children are
  `Element` rows whose `parent` points at that join row.
- **`TabsElement`** (`courses/models.py` ~1094) stores only tab metadata (labels
  + stable ids) in `data`; its children live in `Element` rows with
  `parent = join row` and `tab_id = <which tab>`. `resolved_tabs()` is "the one
  handle every children-consumer uses"; the template
  (`templates/courses/elements/tabselement.html`) iterates it and renders each
  child via the `{% render_element %}` tag (`courses/templatetags/courses_extras.py`).
- **`TwoColumnElement`** (~1230) is the simpler precedent: `resolved_columns()`,
  a fixed set of slots (columns), children keyed by a slot id.
- **Loader** (`courses/lal_loader/builders.py`): the `tabs` branch creates the
  container object, makes an `Element` join row, then recurses
  `build_element(child, …, parent=join, tab_id=t.id)` for each child.
- **Builder editor** (`courses/builder.py`): `NESTABLE_TYPE_KEYS` lists element
  types that may be nested as a *child* (`spoiler` is already in it — a spoiler
  can be nested *inside* a container today). `_CONTAINER_REGISTRY` lists element
  types that may act as a *container*, each with a normalizer + `slot_list_key` +
  `slot_id_key` (`TabsElement → ("tabs","id")`, `TwoColumnElement → ("columns","id")`).
  `resolve_scope()` validates and resolves a nested add/save against a container's
  slots.

`SpoilerElement` is a single-slot container: exactly one implicit child list, no
tab/column ids. This is a genuinely simpler shape than Tabs (no slot metadata,
one ordered list), which the design leans on throughout.

## Architecture / components

### 1. Model & rendering (`courses/models.py`)

- `SpoilerElement` keeps `label` (max 120) and `body` (legacy). **No schema
  change / no migration** — nesting is expressed purely through `Element.parent`
  rows that already exist.
- Add `resolved_children(self)` → the ordered list of child `Element` rows whose
  `parent` is this spoiler's join `Element` (mirrors `resolved_tabs()`; order by
  `Element.order`). Because a `SpoilerElement` is the `content_object` of exactly
  one `Element` (its `elements` GenericRelation), the join row is that element;
  children are `Element.objects.filter(parent=<join row>)`.
- Rendering: the spoiler template renders **children recursively if
  `resolved_children()` is non-empty, else the legacy `body`**. Provide whatever
  render-context handle the render pipeline needs (mirror how `TabsElement`
  exposes `resolved_tabs()` and `eid` to its template — likely a `render()` /
  render-context method plus the join row's pk as `eid` for DOM id namespacing).
- `save()` still sanitizes `body` (unchanged). Children are independent Elements;
  they are not affected by the spoiler's `body` sanitize.

### 2. Parser (`scripts/lal_import/lesson.py`)

All three spoiler emitters change from emitting `{type:"spoiler", label, body}`
to emitting `{type:"spoiler", label, elements:[<nested dicts>]}`, where the
nested dicts are produced by walking the spoiler's content through the existing
`_walk` (so images become `image` dicts, tables become `table`/image-table,
math becomes `math`, etc.):

- **`_emit_details`** — `<details>` → nested spoiler (summary → label).
- **`_reveal_table_spoilers`** — each reveal-table row → a nested spoiler
  (row label → spoiler label, the answer/solution cell content → nested children).
- **`show_solution` handler** (`_find_solution`) — the `question_solution`
  content → nested children.

Because `_walk` already runs the image-table unpack and the prose-image
extraction shipped earlier, images inside spoiler content now become
`ImageElement` children automatically.

Edge cases: a spoiler whose content is purely inline text still yields a single
`text` child (fine). An empty solution → a spoiler with no children (renders an
empty disclosure — acceptable, matches source).

### 3. Loader (`courses/lal_loader/builders.py`)

The `spoiler` branch of `build_element` becomes dual-path:

- **Nested path** — when `el` has an `elements` list: create the
  `SpoilerElement`, create its `Element` join row (via the same
  `parent`/`_attach` mechanism the `tabs` branch uses), then recurse
  `build_element(child, …, parent=join)` for each child (no `tab_id` needed —
  single slot, so `tab_id=""`).
- **Legacy path** — when `el` has `body` (authored content / older JSON): the
  current flat `SpoilerElement.objects.create(label[:120], body=…)` path,
  unchanged. (`label[:120]` truncation from commit `2d4ca95` stays.)

### 4. Builder editor (`courses/builder.py` + editor templates)

- Register `SpoilerElement` in `_CONTAINER_REGISTRY` as a **single-slot**
  container. Since the registry contract is slot-based (`slot_list_key`,
  `slot_id_key`), model the spoiler as one fixed, implicit slot — provide a
  normalizer that yields a single slot with a stable id (or adapt
  `resolve_scope()` to accept a slotless/single-slot container). The exact
  representation (a synthetic single slot vs. a slotless code path) is an
  implementation choice for the plan; the contract is: a nested add/save resolves
  to "this spoiler's one child list."
- Recursive editor modeled on the Tabs editor: render each child with the
  existing recursive editor partial, and support **add child / edit child /
  reorder children / delete child** inside a spoiler, plus the container's own
  label field.
- Keep `spoiler` in `NESTABLE_TYPE_KEYS` (a spoiler may still be nested inside
  another container — now nesting is possible in both directions; the plan must
  confirm the depth-invariant in `ContentNode`/`Element` still holds and that
  spoiler-inside-tabs and tabs-inside-spoiler behave).

### 5. Backward-compat & safety

- **No migration**; existing spoilers keep rendering `body`.
- The nested path is **opt-in by presence of children** — a spoiler with zero
  children falls back to `body`.
- **Guard**: the flat `body` editor must never run on a spoiler that has
  children (which would let a save blank the `body` while orphaning/ignoring the
  children, or worse). When a spoiler has children, the editor uses the nested
  editor; when it has only `body`, the flat body editor. The guard is explicit,
  not incidental.
- **Optional nicety (may be dropped for YAGNI):** on first nested-edit of a
  legacy `body` spoiler, offer to convert `body` → a single child `TextElement`.
  Not required for the import; the plan may include or defer it.

### 6. Transfer / export

`TabsElement` nesting participates in the course export/import (transfer) engine
and bumped `FORMAT_VERSION`. The plan must check whether making `SpoilerElement`
nestable requires transfer-serializer changes (a nested spoiler's children must
survive export/duplicate-unit). Mirror whatever `TabsElement` does for its
children in the transfer layer; if a `FORMAT_VERSION` bump or serializer entry is
needed, include it. (This is called out explicitly so it is not missed — nested
Tabs required it.)

## Data flow

Import: `HTML → parser` emits `{type:"spoiler", label, elements:[…]}` → JSON →
`import_lal_content` → loader `build_element` creates `SpoilerElement` + join
`Element` + child `Element`s under it → render pipeline calls
`resolved_children()` → template renders each child via `{% render_element %}`
inside `<details>`.

Authoring: builder editor → nested add/save resolves via `resolve_scope()` to the
spoiler's single child slot → child `Element` created/updated/reordered/deleted
under the join row → same render path.

## Error handling

- A spoiler with no children and no `body` renders an empty disclosure (no error).
- Loader: a nested child that fails to build (e.g. missing media) raises the
  existing `LoaderError` from `build_element`, same as any element — no new error
  surface.
- Editor guard: attempting the flat body edit on a spoiler with children is
  refused (raises the builder's `NestingError`, or routes to the nested editor) —
  never silently blanks children.
- Depth invariant: nesting a container inside a spoiler (or a spoiler inside a
  container) must respect the existing `ContentNode`/`Element` depth rules; the
  plan verifies and, if needed, bounds nesting depth.

## Testing

- **Model**: `resolved_children()` returns children in `order`; the render
  handle prefers children over `body` when children exist, and falls back to
  `body` when none.
- **Parser** (`tests/lal_import/test_lesson.py`): `<details>` with an image →
  nested spoiler dict whose `elements` include an `image`; reveal-table rows →
  one nested spoiler per row with the answer content as children; `show_solution`
  with an image → nested spoiler with an image child. Existing spoiler tests that
  assert `body` are updated to the nested shape (or kept for the legacy path
  where still valid).
- **Loader** (`tests/test_lal_loader_units.py`): a `{type:"spoiler",
  elements:[text, image]}` dict builds a `SpoilerElement` with two child
  `Element`s under its join row, in order; a legacy `{…, body}` dict still builds
  the flat form.
- **Editor** (builder tests): add / edit / reorder / delete a child inside a
  spoiler; a legacy body spoiler still edits via the body path; the guard blocks
  a body-save on a spoiler that has children.
- **Transfer** (if changes are needed): a nested spoiler round-trips through
  export/import and duplicate-unit with its children intact.
- **e2e / render**: an imported nested spoiler renders its image(s) behind the
  toggle (real browser or Django render), and the toggle still works (native
  `<details>`).

## Out of scope

- Refactoring `TabsElement` / `TwoColumnElement` onto a shared base (that was
  Approach B, rejected).
- Fill-table cell images (a separate remaining image bucket; not spoiler-related).
- Practice-state restore for interactive elements nested in spoilers — LAL
  spoiler content is static (solutions/answers: text, math, images, tables), so
  no restore integration is required for the import. If a future spoiler nests an
  interactive/question child, restore integration would be a follow-up.
