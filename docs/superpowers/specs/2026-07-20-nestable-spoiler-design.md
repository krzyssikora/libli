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
- Add `join_row(self)` → `self.elements.order_by("pk").first()` (mirrors
  `TabsElement.join_row()`; the GFK is effectively 1:1).
- Add `resolved_children(self)` → the ordered list of child `Element` rows whose
  `parent` is this spoiler's join `Element`, **ordered `order_by("order", "pk")`**
  (exactly matching `resolved_tabs()`/`resolved_columns()` — the `pk` tie-break is
  required for determinism, not optional). Return `[]` when the join row is `None`
  (transient, mid-create). Children are read via
  `join.children.order_by("order", "pk").select_related("content_type").prefetch_related("content_object")`,
  mirroring the Tabs/two-column query. As with Tabs/two-column (the "ACCEPTED
  LIMITATION" at `views.py:296-298`), nested spoiler children are **not** in
  `build_lesson_context`'s top-level prefetch, so each rendered spoiler incurs one
  bounded child query — accepted and consistent with the existing containers, not
  a regression (M1).
- Add an explicit **`SpoilerElement.render(self, *, element=None, state=None,
  slug=None, node_pk=None)`** mirroring `TabsElement.render` (`models.py:1214`),
  rendering `templates/courses/elements/spoilerelement.html` with context
  `{el, children: resolved_children(), element_state: state, slug, node_pk}`. This
  is required, not "likely": the default `ElementBase.render` exposes only this
  element's own `mine`/`mine_json` and would strip `element_state`/`slug`/`node_pk`
  from the child render path, so any future stateful nested child would lose its
  restore context (see I2). The template renders **children recursively via
  `{% render_element %}` if `children` is non-empty, else the legacy `body`**.
- **`eid` / namespaced DOM ids are NOT needed** — unlike Tabs (whose per-tab DOM
  ids collide across elements), a `<details>`/`<summary>` spoiler emits no per-slot
  ids. Do not add `eid` to the context unless the template actually emits a
  namespaced id (it does not in this design).
- **`has_math` MUST recurse (C1).** `_element_has_math` (`courses/views.py:197`)
  currently returns `has_math_delimiters(obj.body)` for a `SpoilerElement`; a
  nested spoiler has an empty `body`, so math in `MathElement`/`TextElement`
  children would go undetected and KaTeX would not be enabled. Add a
  `_spoiler_has_math(el)` that recurses `el.resolved_children()` →
  `_element_has_math(child.content_object)` (mirroring `_tabs_has_math`,
  `views.py:222`), and route `SpoilerElement` through it (prefer children when
  present, fall back to `body`).
- **Why only `has_math` needs recursion (I5 — corrected reasoning).** It is NOT
  because container children are out of scope. The flags computed from the
  top-level `elements` list are `has_math`, `has_html` (`views.py:325`), and
  `has_questions` (`326`); the gate/stepper/markdone/switch/fill_table flags
  (`330-351`) are already recursion-safe because they use **flat**
  `node.elements.filter(...)` queries (a child keeps its own `unit` FK), not the
  top-level list. `has_questions` is safe because no question type is in
  `NESTABLE_TYPE_KEYS`. `has_math` MUST recurse (above). **`has_html` is the one
  known gap**: `html` IS a nestable leaf, so an `HtmlElement` inside a spoiler
  (or, already today, inside a tab) won't set `has_html` and `html_element.js`
  won't load (`lesson_unit.html:64`). This is a **pre-existing limitation shared
  with `TabsElement`**; the import targets zero `HtmlElement`, so it is
  **ACCEPTED as-is** (not fixed in this feature) — but stated so it isn't
  rediscovered as a regression. Fixing it (recursing `has_html`) is an optional
  follow-up.
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

**Sub-walk contract (I1).** `_walk` has signature
`_walk(nodes, elements, flags, consumed, state)` and mutates the shared
`consumed` (node-id) set and `state`. Today `_reveal_table_spoilers(table)`
(`lesson.py:235`) and `_emit_details(details, elements, flags)` (`lesson.py:1130`)
receive neither `consumed` nor `state`, and their callers (`lesson.py:488`, `516`)
don't pass them. The three spoiler emitters must therefore:
- build the spoiler's child list by calling `_walk` over the spoiler's content
  nodes into a **fresh, local `elements` list** (the nested dicts), **sharing the
  parent's `consumed` set** (so nodes consumed inside the spoiler are not
  re-emitted at the outer level) and **sharing the parent's `state`** (answer-key
  maps, qid context, etc. must remain visible to nested widgets/questions);
- thread `consumed`/`state` through the changed emitter signatures and update
  every caller accordingly.

**No spoiler-inside-a-spoiler (C1 — enforce the depth-1 scope at parse time).**
`_walk` itself is what turns `<details>` / reveal-tables / `show_solution` into
spoilers, so a spoiler-source nested inside another spoiler-source (e.g. a `<details>`
hint inside a `question_solution`) would otherwise make the sub-walk emit a
`spoiler` dict inside the parent spoiler's `elements` — a depth-2 tree the loader
would build but `walk_unit_joins` can only export one level of, breaking the
round-trip (§6) and re-import (`validate_nesting` depth check). Prevent it at the
source: the sub-walk runs in a **"no-nest-spoiler" mode** (thread an
`in_spoiler=True` flag, or pass a walk-context that suppresses the spoiler
emitters) so that an inner `<details>`/reveal/`show_solution` **inlines its
content in place** — summary/label → a `text` heading child, its body walked into
sibling children (the same "drop the wrapper" precedent used for
`<details>`-containing-tabs) — and never emits a nested `spoiler` dict. Result:
all spoiler content stays at depth 1, with no content loss. Pin this explicitly in
the plan and test it (a `<details>` inside a solution → the outer spoiler's
children include the inner content inlined, and there is **no** nested `spoiler`
dict).

Edge cases: a spoiler whose content is purely inline text still yields a single
`text` child (fine). An empty solution → a spoiler with no children (`elements:
[]`) and no `body`, which the loader builds as an empty disclosure (see C5 / M4).

### 3. Loader (`courses/lal_loader/builders.py`)

**Single-slot id constant (C4).** Every layer must key spoiler children on ONE
representation, or editor-added and import-added children get different `tab_id`s
and export/validation break. Pin a fixed non-empty synthetic slot id — define
`SpoilerElement.SLOT_ID` (e.g. `"only"`) as the single source of truth — and use
it consistently in the loader (`tab_id=SLOT_ID`), `resolve_scope`, the editor's
slot resolution, `walk_unit_joins`, and transfer `validate_nesting`. A non-empty
id keeps `resolve_scope`'s "parent and tab must be supplied together" invariant
intact (an empty `tab_id=""` would trip that guard — do NOT use `""`).
`resolved_children()` groups by `parent` alone and does not depend on the slot id,
but the child rows still carry `tab_id=SLOT_ID` so the editor/transfer paths agree.

The `spoiler` branch of `build_element` becomes dual-path:

- **Nested path** — when `el` has an `elements` list: create
  `SpoilerElement.objects.create(label=el.get("label","")[:120])` (the `[:120]`
  truncation from commit `2d4ca95` is **required here too** — parser labels from
  reveal-table cells / `<details>` summaries are not length-capped, and
  `objects.create` skips `full_clean`, so a >120-char label raises Postgres
  `DataError` and aborts the unit; see I2), then create the join row **exactly as
  the `tabs` branch does** — `join = Element.objects.create(unit=unit,
  parent=parent, tab_id=tab_id, content_object=obj)` (`builders.py:116-118`) — and
  recurse `build_element(child, …, parent=join, tab_id=SpoilerElement.SLOT_ID)` for
  each child. Do **not** describe this as the `_attach` mechanism: `_attach`/
  `_attach_row` returns the concrete `obj` and discards the `Element` row, so it
  cannot hand back the `join` the children need. **Returns the concrete
  `SpoilerElement`** (mirroring the `tabs` branch, `builders.py:131`).
- **Loader depth guard (C2).** When building nested (`parent is not None`), the
  loader must refuse a child that is itself a container — a `spoiler` dict carrying
  `elements`, or a `tabs`/`two_column` dict — by raising `LoaderError`. The parser
  fix (C1) guarantees this never fires on real import content, but the guard turns
  a malformed/hand-edited JSON depth-2 tree into a clear error instead of a
  silently un-exportable structure.
- **Legacy path** — when `el` has `body` (authored content / older JSON): the
  current flat `SpoilerElement.objects.create(label=el.get("label","")[:120],
  body=…)` path, unchanged.

### 4. Builder editor (`courses/builder.py` + editor templates)

- Register `SpoilerElement` in `_CONTAINER_REGISTRY` as a **single-slot**
  container keyed on `SpoilerElement.SLOT_ID` (C4). The registry contract is
  slot-based (`normalizer`, `slot_list_key`, `slot_id_key`) and `resolve_scope`
  calls `normalizer(parent_obj.data)[list_key]` (`builder.py:110`) — but
  `SpoilerElement` has **no `data` field** (and we add none), so `parent_obj.data`
  is evaluated as the call argument and would raise `AttributeError` regardless of
  whether the normalizer uses it (I3). The `resolve_scope` change is therefore
  **mandatory, not optional**: add a single-slot branch **before** the
  `normalizer(parent_obj.data)` call that, for a `SpoilerElement` parent,
  validates `tab == SpoilerElement.SLOT_ID` without touching `.data` (equivalently
  `getattr(parent_obj, "data", {})`). The contract: a nested add/save resolves to
  "this spoiler's one child list," with the sole valid slot id being `SLOT_ID`.
- **Editor depth guard (C2).** `resolve_scope` (`builder.py:78-116`) does **no**
  depth check — it validates only parent-is-container, valid tab, and child in
  `NESTABLE_TYPE_KEYS`. Because `spoiler` stays in `NESTABLE_TYPE_KEYS` and is now
  itself a container, an author could add a `spoiler` child to a tab (allowed —
  leaf, body-only), then add children to that inner spoiler, producing a depth-2
  tree the editor/loader accept but transfer rejects. Add an explicit guard: a
  container may receive children **only when its own join row is top-level**
  (`join.parent_id is None`). So `resolve_scope`, when the resolved parent is a
  spoiler that is itself nested, raises `NestingError`. This preserves
  "legacy body-only spoiler nestable as a leaf inside Tabs" while making it
  impossible to give a *nested* spoiler children.
- Recursive editor modeled on the Tabs editor: render each child with the
  existing recursive editor partial, and support **add child / edit child /
  reorder children / delete child** inside a spoiler, plus the container's own
  label field. **Template (I6):** `templates/courses/manage/_element_row.html`
  routes `tabselement`/`twocolumnelement` to nested branches and drops everything
  else (spoiler included) into the generic leaf `{% else %}`. Add a
  `{% elif el.content_type.model == "spoilerelement" %}` branch that iterates
  `obj.resolved_children` as the single slot and includes `_add_menu.html with
  nested=True parent=el.pk tab=obj.SLOT_ID`. Expose `SLOT_ID` as a
  `SpoilerElement` **class attribute** so `{{ obj.SLOT_ID }}` resolves in the
  template (the add-menu needs the slot id, but `resolved_children()` is a flat
  list with no slot dict to read it from — unlike `resolved_tabs`). Mirror the
  tabs/two-column recursion-termination comment; termination is guaranteed by the
  C1/C2 depth-1 enforcement.
- **Nesting depth — DECIDED (C5): keep the existing one-level depth invariant
  unchanged.** `validate_nesting` (`payloads.py:722`) hard-rejects any element
  whose parent itself has a parent, and that bound is load-bearing for the
  editor's recursive-row template termination. Do NOT raise it. Consequences,
  which the plan states as firm scope:
  - A **top-level spoiler with leaf children** (text/math/image/video/table/…) is
    the supported shape and is exactly what the import produces (depth 1). ✓
  - **Container children inside a spoiler are OUT OF SCOPE**: `tabs`/`two_column`
    are already absent from `NESTABLE_TYPE_KEYS`, so they can never be a spoiler
    child. A nested `spoiler`-with-children (spoiler-inside-spoiler) is barred by
    the parser (C1 inlines inner disclosures) and the loader depth guard (C2).
    Acceptable because the import needs container-in-spoiler nowhere (the one real
    `<details>`-containing-tabs case was already resolved by dropping the
    `<details>` wrapper — the "native tabs, no wrapper" decision).
  - `spoiler` **stays in `NESTABLE_TYPE_KEYS`**, so a **legacy body-only** spoiler
    may still be nested as a leaf child inside Tabs (unchanged from today). But
    because `spoiler` is now BOTH a container AND nestable — the first such type —
    and neither the parser/loader nor `resolve_scope` runs `validate_nesting`,
    the depth-1 invariant is **not** self-enforcing here. It is upheld by three
    explicit guards: the parser no-nest-spoiler mode (C1), the loader container-
    child refusal (C2), and the `resolve_scope` "container must be top-level to
    receive children" guard (C2). Only a spoiler that *has its own children* is
    barred from being nested.

### 5. Backward-compat & safety

- **No migration**; existing spoilers keep rendering `body`.
- The nested path is **opt-in by presence of children** — a spoiler with zero
  children falls back to `body`.
- **`body` fate when children exist (M2).** Render, `has_math`, and export all key
  off children-presence, so a spoiler with both children and a non-empty `body`
  would silently orphan the `body` (still serialized, never rendered). The nested
  loader path creates with `body=""` so this cannot arise from the import. Pin the
  rule for the editor's add-first-child flow too: a spoiler that gains children
  keeps `body` **unused-but-harmless** (do NOT add cleanup logic that blanks it),
  and tests assert children win over any residual `body`. (The optional legacy-body
  → child-`TextElement` conversion nicety below, if built, is the one path that
  would consume `body`.)
- **Template branch (M4).** `spoilerelement.html` today always renders
  `<div class="el el--text spoiler__body">{{ el.body|sanitize }}</div>`. Change it
  to a branch: if `children` is non-empty, loop them via `{% render_element %}`
  (and **drop** the `el--text spoiler__body` text wrapper — children bring their
  own element markup); else render the legacy `body` div. The empty case (no
  children, empty `body`) must yield a truly empty `<details>` body — no stray
  `el--text` wrapper.
- **Guard**: the flat `body` editor must never run on a spoiler that has
  children (which would let a save blank the `body` while orphaning/ignoring the
  children, or worse). When a spoiler has children, the editor uses the nested
  editor; when it has only `body`, the flat body editor. The guard is explicit,
  not incidental.
- **Optional nicety (may be dropped for YAGNI):** on first nested-edit of a
  legacy `body` spoiler, offer to convert `body` → a single child `TextElement`.
  Not required for the import; the plan may include or defer it.

### 6. Transfer / export

Nested spoiler children **must** survive export, import, and duplicate-unit (which
uses the transfer engine) — otherwise the feature silently re-loses the very
content it exists to fix. These transfer changes are **required**, not "check
whether":

- **Export walk (C2).** `walk_unit_joins` (`export.py:416`) expands children ONLY
  for `TabsElement` and `TwoColumnElement`; its docstring forbids iterating
  `join.children.all()` directly. Add an
  `elif isinstance(obj, SpoilerElement):` branch that yields
  `(child, join, SpoilerElement.SLOT_ID)` for each `child` in
  `obj.resolved_children()` (mirroring the Tabs branch). Without this, a nested
  spoiler's children are omitted from every archive and every duplicate.
- **Validator (C3).** `validate_nesting` (`payloads.py:700`) reads
  `slot_key = _CONTAINER_SLOT_KEY.get(parent["type"])` and then
  `el["tab"] in {s["id"] for s in parent["data"][slot_key]}`. `spoiler` is absent
  from `_CONTAINER_SLOT_KEY` (`payloads.py:697`) and a spoiler payload has no slot
  list in `data`. Special-case `spoiler` so it is accepted as a container whose
  sole valid slot id is `SpoilerElement.SLOT_ID`, WITHOUT requiring a `data`
  slot-list. The one-level depth check (`payloads.py:722`) stays and is what
  enforces the C5 leaf-only scope.
- **Per-element (de)serializers — NO CHANGE NEEDED (I4).** Children are serialized
  as **separate** `Element` payloads via the generic walk and linked by the
  importer's second pass (`importer.py:892-898`: it sets `join.parent`/`join.tab_id`
  from each child payload's `parent`/`tab` refs) — exactly like Tabs, whose
  `_build_tabs` (`importer.py:765`) never touches children and `_ser_tabs`
  (`export.py:176`) emits only metadata. So `_ser_spoiler` (`export.py:110`) keeps
  emitting `{label, body}` (a nested spoiler's `concrete.body` is just `""`),
  `_val_spoiler` (`payloads.py:187`) keeps `_exact_keys(["label","body"])`, and
  `_build_spoiler` (`importer.py:535`) keeps building from `{label, body}` — none
  needs a nested-vs-legacy discriminator, and `body` is never absent. Do NOT add a
  dual-shape serializer (an earlier draft did; it was unnecessary and left the
  discriminator unpinned).
- **FORMAT_VERSION — no bump (M5).** The `parent`/`tab` nesting refs already exist
  at `FORMAT_VERSION = 4` (`schema.py:14`); a nested spoiler reuses the existing
  format and introduces no new incompatible key, so **do not bump** it (consistent
  with "don't bump FORMAT_VERSION for a new element type"). Only bump if a new
  incompatible key is genuinely introduced.

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
- Depth invariant (C5): the existing one-level `validate_nesting` cap is kept
  unchanged. A spoiler-with-children nested inside another container (depth-2) is
  rejected by that existing check — no new error surface, and out of scope per the
  DECIDED C5 resolution above. Container children inside a spoiler cannot occur
  (`tabs`/`two_column` are not in `NESTABLE_TYPE_KEYS`).

## Testing

- **Model**: `resolved_children()` returns children in `order_by("order", "pk")`
  and `[]` when the join row is `None`; the render handle prefers children over
  `body` when children exist, and falls back to `body` when none.
- **has_math (C1)**: a spoiler with a `MathElement` child reports `has_math=True`
  via `_spoiler_has_math`; a legacy body-only spoiler with `\(..\)` still reports
  `True`; an empty spoiler reports `False`.
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
- **Transfer** (required, C2/C3): a nested spoiler (e.g. `[text, image]`
  children) round-trips through export→import and through duplicate-unit with its
  children intact and in order; `walk_unit_joins` yields the spoiler's children;
  `validate_nesting` accepts a child whose `tab == SLOT_ID`; a legacy `{label,
  body}` spoiler still validates/serializes/builds; a depth-2 spoiler-with-children
  is rejected by `validate_nesting`.
- **e2e / render**: an imported nested spoiler renders its image(s) behind the
  toggle (real browser or Django render), and the toggle still works (native
  `<details>`).

## Out of scope

- Refactoring `TabsElement` / `TwoColumnElement` onto a shared base (that was
  Approach B, rejected).
- **Container children inside a spoiler** and **a spoiler-with-children nested
  inside another container** (both depth-2). Decided C5: keep the one-level depth
  invariant; only top-level spoilers with leaf children are supported. A
  legacy body-only spoiler nested as a leaf child of Tabs is still supported.
- Fill-table cell images (a separate remaining image bucket; not spoiler-related).
- Practice-state restore for interactive elements nested in spoilers — LAL
  spoiler content is static (solutions/answers: text, math, images, tables), so
  no restore integration is required for the import. If a future spoiler nests an
  interactive/question child, restore integration would be a follow-up.
