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
generic-FK join rows, each pointing at one concrete element model (31 types), some
of which own child rows (Choices, Blanks, grid columns/rows, stepper steps, drag
zones, mark-done items, …) and/or nested `Element` children (tabs/two-column
containers) and/or ids embedded in a JSON `data` field.

The existing `courses/transfer/` package already serializes an arbitrary subtree
(`export.build_export`) and re-materializes it into a course
(`importer.import_subtree`), handling every one of those element shapes via
per-type registries kept deliberately in lockstep. Duplication reuses this path.

### New / changed components

1. **Service — `builder.duplicate_unit(course, node, *, token)`**
   (new, `courses/builder.py`), wrapped in `transaction.atomic`.
   - Guards: `node.kind == "unit"`; caller already access-checked in the view; and
     the optimistic-concurrency token (`node.updated.isoformat()`) matched via the
     existing `_check_token` helper (409 on stale) — consistent with the sibling
     node-ops (`reorder_node`, `reparent_node`, `delete_node`).
   - Serializes the unit in-memory: `transfer.export.build_export(course, node)`.
   - Materializes via a **duplicate-mode** path through the importer that (a)
     **shares** existing `MediaAsset` rows instead of creating new files/rows, and
     (b) otherwise reuses the importer's two-pass element rebuild (concrete
     objects, child rows, nested `parent`/`tab_id`, JSON `data`).
   - Placement: the importer appends the new node at the end of the parent's
     children; the service then moves it directly below the source using the
     existing `courses/ordering.py` helpers, so the copy lands at
     `source.order + 1` and siblings are compacted.
   - Returns the newly created `ContentNode` (for the view to re-render / focus).

2. **Importer duplicate-mode seam** (`courses/transfer/importer.py`).
   The importer's `import_subtree` currently calls `_create_media`, which creates
   new `MediaAsset` rows and builds an `old-ref → new-row` media map consumed by
   `_create_elements`. Duplicate-mode injects a media map that resolves every
   referenced asset to its **existing** row (identity mapping keyed on the source
   asset), skipping `_create_media` entirely. Implemented as a narrow parameter
   (e.g. `media_map=` / `share_media=True`) on the internal materialize path so the
   normal cross-course import behavior is untouched. The two-pass ordering rebuild
   and all per-type BUILDERS are reused verbatim.

   Rationale for this seam over a standalone deep-copy: it keeps a single
   authoritative per-type copy path. As new element types are added, only the
   transfer registries must stay correct; duplication follows automatically.

3. **View — `views_manage.node_duplicate`** (new, POST only, `courses/views_manage.py`).
   Mirrors `node_move`'s structure: `_require_manage` access gate, resolve the node
   within the course, read the token, call `builder.duplicate_unit`, and return the
   re-rendered `_scope.html` fragment for the affected scope (the same AJAX swap the
   reorder/reparent ops return). Rejects non-unit nodes (404/400) and stale tokens
   (409), matching sibling ops.

4. **URL — `manage_node_duplicate`** (new, `courses/urls.py`), placed alongside the
   other `manage_node_*` node-ops.

5. **Template — Duplicate button** in
   `templates/courses/manage/_tree_node.html`, added to the action cluster,
   **gated on `node.kind == "unit"`**. Non-destructive, so positioned near
   export/move and before the danger `delete`. It POSTs (a small inline form like
   `_move_buttons.html`, carrying `node` pk and the `token`) rather than being a GET
   link, since it mutates. Uses a monochrome `currentColor` "duplicate" SVG icon
   (per the icon convention — shared `.ica`/`.icon`), with a translated
   `title`/aria-label.

6. **i18n** — a "Duplicate" string added to the EN and PL message catalogs
   (`gettext`), following the lazy-vs-eager and catalog-test conventions already in
   the repo.

## Data flow

1. Author clicks **Duplicate** on a unit row → inline form POSTs to
   `manage_node_duplicate` with `node=<pk>` and `token=<source.updated.isoformat()>`.
2. `node_duplicate` view: access-gate → fetch node (unit, in course) → hand off to
   `builder.duplicate_unit(course, node, token=token)`.
3. Service (atomic):
   a. Validate kind + token (409 on stale).
   b. `document, media, problems = build_export(course, node)` (in-memory
      serialize of the unit subtree — one unit node plus its elements).
   c. Materialize via importer duplicate-mode with a share-media map → new
      `ContentNode` + copied `Element` rows + concrete objects + child rows +
      nested children, all pointing at the **existing** `MediaAsset` rows.
   d. Move the new node to `source.order + 1` within the same parent scope via
      `ordering` helpers; compact siblings.
   e. Return the new node.
4. View re-renders `_scope.html` for the scope and returns the fragment; the
   builder JS swaps it in, showing the copy directly below the original.

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

## Error handling

- **Non-unit node** → the view rejects it (the button is never rendered for
  non-units, but the endpoint guards server-side anyway): 404/400, no mutation.
- **Stale token** (source unit changed since the tree was rendered) → 409, no
  mutation, consistent with `reorder_node`/`delete_node`. The author reloads and
  retries.
- **Access** → `_require_manage` / `can_manage_course`; non-managers get the
  standard denial. The button is not rendered for users who cannot manage.
- **Atomicity** → the whole duplicate runs in `transaction.atomic`; any failure
  during serialize/materialize rolls back, leaving the tree untouched (no partial
  unit, no orphaned elements or child rows).
- **Export `problems`** → `build_export` can report per-element problems (e.g. a
  missing media reference). For an in-course duplicate these should be rare (the
  source lives in the same DB); the service treats a hard serialization failure as
  a rollback+error, and benign problems (already-missing media) degrade the same
  way the source already renders. This path is covered by a test.

## Testing

- **Service tests** (`courses/tests/…`):
  - Duplicating a rich unit — a question element with child rows (e.g. choices), a
    container element with nested children (tabs/two-column), and a media-bearing
    element — yields a new `ContentNode` distinct from the source with **equal**
    element and child-row counts and equivalent structure.
  - The copy's media-bearing elements reference the **same** `MediaAsset` pks as
    the source (share-media assertion), and no new `MediaAsset` rows are created.
  - The copy is placed at `source.order + 1` within the same parent; siblings
    remain contiguously ordered.
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
