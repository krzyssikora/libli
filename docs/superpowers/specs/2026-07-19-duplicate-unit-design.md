# Duplicate a unit in the course tree

## Purpose

Course authors working in the `/manage/` builder tree need a fast way to make a
copy of an existing unit — for example, to author a near-identical variant
without rebuilding all of its content elements by hand. Today the per-node action
cluster offers move up/down, move (reparent), download (export), and delete, but
no duplicate.

This feature adds a **Duplicate** action, rendered only on `kind == "unit"` nodes,
that creates a full deep copy of the unit as a sibling positioned immediately
below the original, then re-renders the tree scope so the copy appears in place.
The operation is non-destructive and instant (no confirmation page).

### Scope decisions (settled during brainstorming)

- **Units only.** Parts/chapters/sections do not get the button; their existing
  cluster is unchanged. Units are leaves (they cannot have child nodes), so no
  recursive subtree-of-nodes copy is required — only the unit's own content
  elements are deep-copied.
- **Identical title.** The copy keeps the source unit's exact title (no "Copy of"
  prefix). Two identically-named siblings until the author renames the copy is
  acceptable and expected.
- **Shared media.** The copy's elements point at the *same* `MediaAsset` rows as
  the source. No media files or rows are duplicated. Replacing an image in the
  copy later just repoints that element; it never mutates the original.
- **Reuse the transfer engine.** Duplication is built on the existing
  export/import machinery (`courses/transfer/`) rather than a second per-type copy
  registry, so it inherits the authoritative, in-lockstep per-type copy logic for
  all element types.

## Architecture / components

There is no `Unit` model. The course tree is a single self-referential
`ContentNode` model (`courses/models.py`) whose `kind` is one of
`part/chapter/section/unit`. A unit's content is an ordered list of `Element`
generic-FK join rows, each pointing at one concrete element model (the set
enumerated by `ELEMENT_MODELS` / the transfer `BUILDERS` registry), some
of which own child rows (Choices, Blanks, grid columns/rows, stepper steps, drag
zones, mark-done items, …) and/or nested `Element` children (tabs/two-column
containers) and/or ids embedded in a JSON `data` field.

The existing `courses/transfer/` package already serializes an arbitrary subtree
(`export.build_export`) and re-materializes it into a course
(`importer.import_subtree`), handling every one of those element shapes via
per-type registries kept deliberately in lockstep. Duplication reuses this path.

### New / changed components

1. **Service — `builder.duplicate_unit(course, node_pk, *, token)`**
   (new, `courses/builder.py`), wrapped in `transaction.atomic`.
   - Takes `node_pk` (not a pre-fetched node) and **re-fetches the source under a
     row lock inside the atomic** via `_locked_node(course, node_pk)`
     (`select_for_update`), then token-checks the locked row — matching
     `delete_node` / `reorder_node` exactly, so neither the token check nor the
     subsequent `build_export` serialization of the source can race a concurrent
     writer.
   - Guards: `node.kind == "unit"` (defense-in-depth — the view already rejects
     non-units with 404, so this guard is effectively an assertion; if reached it
     raises `ValueError`, which the whole-body wrapper then normalizes rather than
     500-ing); caller already access-checked in the view; and
     the optimistic-concurrency token (`node.updated.isoformat()`) matched via the
     existing `_check_token` helper (409 on stale) — consistent with the sibling
     node-ops (`reorder_node`, `reparent_node`, `delete_node`).
   - Serializes the unit in-memory: `transfer.export.build_export(course, node)`.
   - Materializes via a **duplicate-mode** path through the importer that (a)
     **shares** existing `MediaAsset` rows instead of creating new files/rows, and
     (b) otherwise reuses the importer's two-pass element rebuild (concrete
     objects, child rows, nested `parent`/`tab_id`, JSON `data`).
   - Placement: the materialize step appends the new node at the end of the
     parent's children; the service then moves it directly below the source. It
     sets `new_node.parent = source.parent` (a precondition of `place_node`) and
     calls `ordering.place_node(new_node, source.parent, course, position=idx + 1)`,
     where `idx` is the source's **0-based index in the freshly-read sibling list** —
     `list(ContentNode.objects.filter(course=course, parent=source.parent)
     .order_by("order", "pk"))`, read after the append so it reflects reality. Do
     **not** use `source.order` (an order value, not a position index). `place_node`
     takes that 0-based position index, clamps it, and reindexes all siblings, so
     the copy ends up immediately after the source.
   - Returns the newly created `ContentNode` (for the view to re-render / focus).
   - **Imports the transfer modules lazily** (`from courses.transfer import export,
     importer` *inside* `duplicate_unit`, not at module top), following
     `builder.py`'s existing lazy-import convention for cross-module deps — the
     importer pulls `courses.forms` / `courses.media`, so a new top-level edge risks
     an import cycle.

2. **Importer duplicate-mode seam** (`courses/transfer/importer.py`).
   The importer's `import_subtree(zf, manifest, document, media_entries,
   target_course, insertion_node, user)` is **zip-coupled**: it requires a real
   `zf` zipfile and a `media_entries` filename→zip-info map, and `_create_media`
   extracts media bytes from that zip. The duplicate flow has no zip, so
   duplicate-mode does **not** call `import_subtree`. Instead the service reaches
   the importer's inner steps directly — `_create_nodes` then `_create_elements`,
   inside the importer's `_run_import` / `transaction.atomic` wrapper — bypassing
   `zf`, `media_entries`, and `_create_media` entirely.

   `_create_elements` resolves media by looking up `assets[mid]`, keyed on the
   **export-assigned `mid` string** (`"m1"`, `"m2"`, …). Duplicate-mode therefore
   passes a precomputed `{mid: MediaAsset}` map built from `build_export`'s
   `media_assets` return, where each `mid` maps to the **existing** source
   `MediaAsset` row — so no bytes are read, no files are written, and no new asset
   rows are created. Concretely this is a new internal materialize entry point
   (e.g. `materialize_duplicate(document, media_map, target_course,
   insertion_node)` — no `user` parameter, since duplicate-mode bypasses
   `_create_media` and neither `_create_nodes` nor `_create_elements` consumes it)
   added alongside `import_subtree`, so the normal cross-course import path is
   untouched. The two-pass ordering rebuild and all
   per-type `BUILDERS` are reused verbatim.

   Rationale for this seam over a standalone deep-copy: it keeps a single
   authoritative per-type copy path. As new element types are added, only the
   transfer registries must stay correct; duplication follows automatically.

3. **View — `views_manage.node_duplicate`** (new, POST only, `courses/views_manage.py`).
   Mirrors `node_move`'s structure: `_require_manage` access gate, resolve the node
   within the course, read the token, call `builder.duplicate_unit`, and re-render
   the affected scope.
   - **Scope selection mirrors `node_move` / `node_delete`:** when the source unit
     has a parent, return the `_scope.html` fragment for that parent scope; when the
     unit is **top-level** (`parent is None`, as in a Flat course where units are
     the deepest kind), use scope `"top"` and return `_render_tree` (the whole-tree
     render), exactly as the sibling ops do.
   - **No-JS fallback mirrors the sibling ops via `_wants_fragment(request)`:** with
     JS, a success returns the scope fragment (status 200) and a **stale-token 409
     returns the refreshed source-parent scope fragment with fresh tokens**
     (`_conflict_scope`, or `_render_tree(status=409)` for a top-level unit), which
     builder.js swaps and annotates — mirroring `node_move`'s reorder-conflict
     branch. Without JS, on success redirect to `manage_builder`, and on a 409 render
     `_builder_with_notice(..., status=409)`.
   - Rejects non-unit nodes (404/400) and stale tokens (409). A `TransferError` from
     the materialize step (see Error handling) is caught and pinned to **HTTP 422** —
     the JS branch renders `_op_error.html` (mirroring the ValidationError path of
     `node_add` / `node_move`, which builder.js surfaces as a notice), and the no-JS
     branch renders `_builder_with_notice(..., status=422)`. (200/409/422 are the
     only statuses builder.js acts on, so an unpinned 400/500 would leave the JS path
     showing the user nothing.) Guards match sibling ops.

4. **URL — `manage_node_duplicate`** (new, `courses/urls.py`), placed alongside the
   other `manage_node_*` node-ops.

5. **Template — Duplicate button** in
   `templates/courses/manage/_tree_node.html`, added to the action cluster,
   **gated on `node.kind == "unit"`**. Non-destructive, so positioned near
   export/move and before the danger `delete`. It renders as a small inline
   `<form>` like `_move_buttons.html`, carrying the `node` pk, the `token`,
   `{% csrf_token %}`, and — **critically** — a `data-op="duplicate"` attribute:
   builder.js only intercepts and fragment-swaps `form[data-op]` submits (any value
   except the special-cased `reparent`), so without it the button would silently
   fall back to a full-page POST every time and the fragment-swap data flow would
   never fire. The button follows the existing icon-**sprite** pattern the other
   cluster buttons use — `<button class="ica"><svg class="ic"><use
   href="#bi-duplicate"/></svg></button>` — **not** an inline `currentColor` SVG.
   Since the sprite (`templates/courses/manage/_icon_sprite.html`) currently defines
   only `bi-{down,download,grip,move,trash,up}` and has no copy/duplicate glyph, a
   new `<symbol id="bi-duplicate">` must be **added to the sprite** as a concrete
   deliverable — reusing the existing `bi-*` symbols' `viewBox` and monochrome
   `currentColor` line convention (they are Bootstrap Icons; source the glyph from
   Bootstrap Icons' `files` / `copy` icon) so it matches the cluster's size and
   style. The button carries a translated `title` / aria-label.

6. **i18n** — a "Duplicate" string added to the EN and PL message catalogs
   (`gettext`), following the lazy-vs-eager and catalog-test conventions already in
   the repo.

## Data flow

1. Author clicks **Duplicate** on a unit row → inline form POSTs to
   `manage_node_duplicate` with `node=<pk>` and `token=<source.updated.isoformat()>`.
2. `node_duplicate` view: access-gate → resolve `node_pk` (must be a unit in the
   course) → hand off to `builder.duplicate_unit(course, node_pk, token=token)`.
3. Service (atomic):
   a. Re-fetch the source under a row lock (`_locked_node`); validate kind + token
      on the locked row (409 on stale).
   b. `manifest, document, media_assets, problems = build_export(course, node,
      drop_missing_media=False)` — a 4-tuple (in-memory serialize of the unit
      subtree: one unit node plus its elements). `media_assets` is a list of
      `(mid, asset, is_placeholder)` tuples and is the only place the
      export-assigned `mid` → source `MediaAsset` mapping exists, so the
      share-media map (`{mid: MediaAsset}`) is derived from it.
   c. Materialize via the duplicate-mode entry point (§2) with that share-media
      map → new `ContentNode` + copied `Element` rows + concrete objects + child
      rows + nested children, all pointing at the **existing** `MediaAsset` rows.
   d. Set `new_node.parent = source.parent`, then `place_node` it at the 0-based
      index `(index of source among its siblings) + 1` within the same parent
      scope; siblings are reindexed. When `source.parent is None` (top-level unit),
      also `course.save(update_fields=["updated"])` after placement — the `"top"`
      scope's rendered token is `course.updated`, so this keeps token parity with
      the sibling top-scope ops (`reorder_node` / `delete_node` / `add_node`).
   e. Return the new node.
4. View re-renders `_scope.html` for the scope and returns the fragment; the
   builder JS swaps it in, showing the copy directly below the original. The new
   node is **not** specially focused, scrolled-to, or highlighted — it simply appears
   in the swapped fragment (mirroring how `node_add`'s freshly created node appears);
   the service returning the new `ContentNode` is for the view's scope selection, not
   for any highlight behavior.

### What is / isn't copied

- **Copied:** the `ContentNode` fields relevant to authoring content — `title`,
  `unit_type`, `obligatory`, `html_seed_js`; every `Element` join row; each
  concrete element and its child rows; nested container children (re-linked
  `parent`/`tab_id`); JSON `data`. Element `order` is preserved. Media is
  **referenced, not duplicated**.
- **Not copied:** any student-scoped or personal data attached to the unit —
  student practice state, personal notes, personal tags, analytics / quiz
  submissions. The duplicate is fresh authoring content with no progress history.
  (These are separate models keyed on the node; the copy simply does not create
  rows in them.)
- **Cannot be copied:** an `Element` join row whose concrete `content_object` is
  missing (a dangling generic-FK) carries no content to duplicate — `build_export`'s
  walk skips it, so such an element is silently absent from the copy. This is an
  unavoidable divergence from "full deep copy" and only affects already-broken
  source rows.

## Error handling

- **Non-unit node** → the view rejects it (the button is never rendered for
  non-units, but the endpoint guards server-side anyway): 404/400, no mutation.
- **Stale token** (source unit changed since the tree was rendered) → 409, no
  mutation, consistent with `reorder_node`/`delete_node`. The author reloads and
  retries.
- **Access** → `_require_manage` / `can_manage_course`; non-managers get the
  standard denial. The button is not rendered for users who cannot manage.
- **Atomicity** → the whole duplicate runs in `transaction.atomic`. `build_export`
  and the importer's `_run_import` each open their **own inner** `atomic`; these
  nest under the service's outer block as savepoints, so a failure in either inner
  block still rolls the entire duplicate back — leaving the tree untouched (no
  partial unit, no orphaned elements or child rows).
- **Missing-media elements must not be dropped.** `build_export`'s normal walk
  *degrades* missing media: an element whose file is absent on disk is either
  excluded from the serialized output (missing video → `status="dropped"`) or
  replaced with a synthetic placeholder (missing image). For a **shared-row** in-DB
  duplicate that is wrong — it would make the copy lose or alter elements the source
  still has. Because duplicate-mode references the existing `MediaAsset` rows and
  never reads files, on-disk presence is irrelevant, so the serialization used for
  duplication runs in a **non-dropping mode** — a flag on `build_export`
  (`drop_missing_media`, **defaulting to `True`** so every existing caller —
  `export_to` / `write_archive` — keeps today's drop/placeholder behavior unchanged;
  only the duplicate path passes `False`). Its contract when `False` is to
  **short-circuit the on-disk media probing across all three coupled passes** of the
  export walk: every registered
  asset is treated as present (`status="real"`, `is_placeholder=False`), so (a) no
  element is excluded (the element-emission pass), and — critically — (b) the
  returned `media_assets` contains an entry for **every** referenced `mid` (the
  media-emission pass). Both halves matter: the share map is built from
  `media_assets`, so if a missing video's `mid` were still dropped there, the map
  would lack it and the video builder's `assets[mid]` lookup would `KeyError` on the
  very "absent file" test below. Covered by a test (a unit whose media file is absent
  duplicates with the element intact — see Testing).
- **Genuine failures → rollback, uniformly wrapped.** The importer's `_run_import`
  wraps only the *materialize* half (`_create_nodes` / `_create_elements`) as a
  `TransferError`. But `build_export` runs *before* materialize and `place_node`
  *after*, both inside the service's outer atomic yet **outside** `_run_import`, so
  their exceptions would not be `TransferError` — and the view (which catches only
  `TransferError`) would surface a raw 500 that builder.js ignores. To close this,
  `duplicate_unit` wraps its **entire body** (build_export + materialize +
  place_node) so any unexpected exception is normalized to `TransferError`, which the
  view maps to 422; the whole duplicate rolls back atomically. Missing media does
  **not** raise (it is handled by the non-dropping mode), so it is never a rollback
  trigger.

## Testing

- **Service tests** (`courses/tests/…`):
  - Duplicating a rich unit — a question element with child rows (e.g. choices), a
    container element with nested children (tabs/two-column), and a media-bearing
    element, **with all media files present on disk** — yields a new `ContentNode`
    distinct from the source with **equal** element and child-row counts and
    equivalent structure. (The count-equality assertion assumes a clean source with
    no broken/dangling elements.)
  - Duplicating a unit whose media file is **absent** on disk: the copy still
    contains that element, referencing the same `MediaAsset` row (ties to the
    non-dropping-mode constraint in Error handling) — no element is lost or
    replaced with a placeholder.
  - The copy's media-bearing elements reference the **same** `MediaAsset` pks as
    the source (share-media assertion), and no new `MediaAsset` rows are created.
  - The copy is the **immediate next sibling** of the source within the same parent
    — assert by reading the ordered sibling list (source at index `i`, copy at
    `i+1`), not by comparing raw `order` values; siblings remain contiguously
    ordered.
  - Duplicating a source that contains a **dangling** `Element` (missing
    `content_object`) succeeds with no exception; the copy has exactly one fewer
    element (the broken row is silently skipped, per "Cannot be copied").
  - Independence: editing the copy (e.g. changing an element's text, repointing an
    image) does **not** mutate the original's rows.
  - Non-unit node → rejected. Stale token → 409, no mutation.
  - No student-scoped rows (practice state / notes / tags) are created for the
    copy.
- **View test:** POST to `manage_node_duplicate` re-renders the scope fragment with
  the new unit present; access-gated (non-manager denied); token honored.
- **i18n catalog test:** the new string is present in EN+PL and the catalog tests
  (no obsolete/fuzzy regressions) still pass.
- **Regression:** existing `courses/transfer` export/import tests continue to pass
  (the duplicate-mode seam must not change normal cross-course import behavior),
  and the `ELEMENT_MODELS` count assertion in `test_transfer_schema.py` is
  untouched.

### Test-DB note (worktree)

This work runs in an isolated worktree while a parallel session holds another
worktree; concurrent Postgres `test_libli` contention is a known hazard. Test runs
here must use a unique `DATABASE_URL` for the worktree to avoid colliding with the
parallel session's test DB.
