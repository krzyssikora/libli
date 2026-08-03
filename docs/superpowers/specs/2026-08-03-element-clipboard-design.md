# Element clipboard: duplicate an element, and move one into a container

Give the unit editor two operations it has never had: **duplicate an element in place**, and
**move an element across scopes** — out of a container, into a container, or between two
slots of the same container.

**Date:** 2026-08-03
**Base:** master `e3232416`
**Slices:** 2 PRs. PR1 is duplicate-in-place; PR2 is the clipboard (select / move here /
copy here). PR1 stands alone and is the smaller half.

---

## Purpose

Two author needs, both from redesigning the maths course:

1. **"An element above mine is a container, and I cannot move my element inside it."** The
   ↑ ↓ arrows reorder within one scope and stop dead at its boundary. The only way to get
   an existing element into a tab today is to delete it and author it again from scratch
   inside the tab.
2. **"I want three tabs whose content differs only in small details."** Each one must be
   built from nothing; there is no way to copy an element, let alone a populated container.

Both gaps have the same root: element operations are deliberately scope-preserving.
`reorder_element` reads the scope off the row and takes no parent, and says so —
*"That is also what makes a cross-scope move impossible by construction"*
(`courses/builder.py:391-394`). That guarantee is worth keeping. This spec does not weaken
it; it adds a separate, explicitly-validated placement path beside it.

## What already exists (and is reused, not rebuilt)

| Machinery | Where | Reused for |
|---|---|---|
| Recursive container rendering with a per-slot add-menu | `templates/courses/manage/editor/_element_row.html:44-197` | The paste buttons hang off the same slots |
| Nesting validation, clauses 1–4 | `builder.resolve_scope`, `courses/builder.py:117-172` | The placement rule generalises it |
| Absolute-position insert within a group | `ordering.place_element`, `courses/ordering.py:96-117` | Both paste and duplicate |
| Group compaction after a removal | `ordering.compact_elements`, `courses/ordering.py:58-60` | The source slot after a move |
| Whole-unit deep copy via the transfer layer | `builder.duplicate_unit`, `courses/builder.py:326-375` | The template for element-level copy |
| Container child walk (Tabs / TwoColumn / Spoiler) | `courses/transfer/export.py:507-526` | Scoping an export to one element subtree |
| Two-pass element materialisation | `importer._create_elements`, `courses/transfer/importer.py:872-911` | Grafting a copied subtree into an existing unit |
| Generic `form[data-op]` interception + fragment swap | `courses/static/courses/js/editor.js:283` | **No new JavaScript is required** |

That last row is load-bearing for the whole design: because every editor operation already
answers with a re-rendered editor+preview fragment pair (`_render_editor_fragments`,
`courses/views_manage.py:1244-1282`), and because the JS intercepts *any* form carrying
`data-op`, a new operation is a template form plus a view. Without JS the same form posts
normally and the no-JS path redirects, exactly as ↑ ↓ 🗑 do today.

## Decisions

**Move-vs-copy is decided at the destination, not at the source.** A row carries two new
controls only: ⧉ *duplicate below* and ⊹ *select*. Selecting marks the element; each legal
slot then offers **📋 Move here** and **⧉ Copy here**. The alternative — three source-side
buttons (duplicate / cut / copy) — puts eight controls on a row bar that already holds
✎ ✕ ↑ ↓ 🗑, and makes "copy into three tabs" a duplicate-cut-paste cycle per tab instead of
select-once-paste-three-times.

**The mark lives in the session, not in the browser.** A JS-held mark would need a client
re-implementation of the placement rule to decide which slots show a paste button, and the
two would drift. In the session, the paste buttons are just part of the server render that
every operation already returns — and the feature works without JavaScript.

**A paste appends at the end of the destination slot**, which is where a newly added
element lands today. Position within the slot is then adjusted with the existing ↑ ↓.

**Scope is one unit.** The mark is qualified by unit pk and is ignored when rendering any
other unit. Cross-unit and cross-course movement are out of scope (see below).

**Editor only.** These controls live in
`templates/courses/manage/editor/_element_row_controls.html`, which the builder's unit panel
(`_unit_panel.html`) does not include. The builder's inline element list keeps ↑ ↓ 🗑 alone.

## The placement rule

Definitions, all against existing code:

```
depth(join)      1 for a top-level element, +1 per parent hop   (builder.element_depth)
MAX_NEST_DEPTH   4                                              (courses/builder.py:25)
is_container(n)  type(n.content_object) ∈ _CONTAINER_REGISTRY   (courses/builder.py:145)
cap(n)           MAX_NEST_DEPTH - 1 if is_container(n) else MAX_NEST_DEPTH   → 3 or 4
rel(n)           depth of n within the moved subtree; 0 for the root
dest_depth       1 for a top-level destination, else depth(parent_join) + 1
```

`cap` restates the existing clause 4 as a property of the element rather than of the
request: a container may live at depth 1–3 and never at 4, because a container at depth 4
would render slots that can never be filled. A leaf may live at depth 1–4.

`is_container` reads the **model-keyed** `_CONTAINER_REGISTRY`, not the transfer-key set
`CONTAINER_TRANSFER_KEYS`, because the subject here is an existing row rather than an
incoming request — no model→key hop is needed. The two must agree; the drift test in
`test_nesting_rule.py` already guards that they do.

Placing the subtree `S` rooted at `R` into (`P`, slot `t`) is admissible iff:

```
0. every element of S, and P, belong to the posted unit
1. if P is not None:  P is a container and t ∈ slots(P)      [resolve_scope clause 2]
2. if P is not None:  type(R) ∈ NESTABLE_TYPE_KEYS           [resolve_scope clause 1]
3. for every n ∈ S:   dest_depth + rel(n) ≤ cap(n)
4. P ∉ {R} ∪ descendants(R)
```

**Clause 2 checks the root only, deliberately.** Every descendant is already nested, so it
already passed clause 1 when it was created. The root is the only node whose nestability is
unproven — it may have been sitting at top level, where non-nestable types (slidebreak,
most question types) legally live.

Clause 2 needs the root's **transfer key**, since `NESTABLE_TYPE_KEYS` is keyed that way.
The model→key map exists as `courses/transfer/export._MODEL_TO_KEY` (`:402`) but is private.
Promote it to a named public helper rather than reaching into the private name from
`builder.py`; the import stays lazy, as builder's existing transfer imports are, to avoid
the documented import cycle (`courses/builder.py:339-341`).

**Clause 3 is the one genuinely new rule.** An *add* always places a single element, so it
never needed a height check; a paste can place a populated container. Note that clause 3
subsumes `resolve_scope`'s clauses 3 and 4 exactly: for a childless `R`, `S = {R}` and
`rel = 0`, so it reduces to `depth(P) + 1 ≤ cap(R)` — which is clause 3 for a leaf and
clause 4 for a container. **This equivalence is a test, not a comment** (see below): for
every (parent depth, type) pair, `paste_allowed` on a childless element must agree with
`resolve_scope`. That is what stops the two rules drifting when the cap next moves.

**Clause 4 hides paste buttons inside the marked element's own subtree in both modes.** For
a move it prevents a cycle. For a copy it is stricter than strictly necessary — copying a
container into its own descendant creates no cycle — but one rule is easier to reason about
and to test than two, and the case has no author value.

**Slots are computed with the non-destructive normaliser**, as `resolve_scope` already does
and for the reason its comment gives (`courses/builder.py:153-157`): `normalize_data` mints
fresh random slot ids on every call, so validating against it can admit a phantom slot that
never matches again at render time, silently orphaning the pasted element.

### One authority, three callers

```
paste_allowed(marked_join, dest_parent_join_or_None, tab) -> bool
```

Called by the view to build the set of legal slots for the render, called again by the paste
endpoint to enforce, and exercised directly by the unit tests. The UI cannot offer what the
server would reject, and a hand-crafted POST cannot beat the UI.

## Clipboard state

```python
request.session["element_clip"] = {"unit": <unit pk>, "element": <element pk>}
```

No mode is stored — move-vs-copy arrives with the paste. Lifecycle:

| Event | Effect |
|---|---|
| ⊹ select | Sets the mark. **No DB write, so no token check** — the paste re-validates everything. |
| ✕ cancel | Clears it. |
| 📋 Move here | Clears it (the element is now where you put it). |
| ⧉ Copy here | **Keeps** it, so one original can seed several slots. |
| Rendering another unit | Ignored; not cleared (you may navigate back). |
| Marked element gone or not in this unit | Treated as absent and cleared lazily at render. |

## Operations

All four are POST, all take `ctx=editor`, and all answer through `_render_editor_fragments`
so the editor pane and the live preview refresh together.

| URL name | Payload | Service |
|---|---|---|
| `manage_element_duplicate` | `element`, `unit`, `unit_token` | `builder.duplicate_element` |
| `manage_element_clip` | `element`, `unit`, `action=select\|cancel` | session only |
| `manage_element_paste` | `parent` (blank = top level), `tab`, `mode=move\|copy`, `unit`, `unit_token` | `builder.paste_element` |

URL paths follow the existing shape, `manage/courses/<slug>/build/element/<op>/`
(`courses/urls.py:209-217`).

Error responses reuse the established conventions verbatim:

- stale `unit_token`, or the element vanished → **409** via `_element_conflict`
  (`courses/views_manage.py:1196-1212`), which already recovers the unit from the payload
  and re-renders rather than dumping the author back to the tree.
- inadmissible placement → **400** `"bad nesting"`, as `element_add`/`element_save` already
  do for `NestingError` (`courses/views_manage.py:1560`, `:1626`).
- a copy that fails mid-flight → **422** with `_op_error`, matching `node_duplicate`'s
  `TransferError` path (`courses/views_manage.py:992-998`).

### Move semantics

Re-parent **the root join row only**: `parent`, `tab_id`, `order`. Descendants keep their
`parent` FK and their `unit` FK untouched, so the whole subtree travels with the root for
free — only the root's group membership changes. Then `compact_elements` on the source
group (the same call `delete_element` already makes, `courses/builder.py:470`) and one
`unit.save(update_fields=["updated"])`.

### Copy semantics

Serialise the subtree through the transfer layer and re-materialise it, as
`duplicate_unit` does. The only new transfer code is an **element-scoped** entry point;
everything below it is the existing walk. Four properties are deliberate:

- **`MediaAsset` rows are reused, never re-created.** `duplicate_unit` already passes an
  existing-asset map for exactly this reason. Do not "improve" this into copying assets:
  two `MediaAsset` rows sharing a `file.name` share a file *lifetime*, and deleting either
  deletes the file out from under the other. Reusing the row itself carries no such hazard.
- **`tab_id` values are copied verbatim.** Slot ids need only be unique within their own
  container's data, and children are scoped by `(unit, parent, tab_id)`
  (`courses/ordering.py:46-55`), so two sibling Tabs elements sharing slot ids is harmless.
  `duplicate_unit` already depends on this.
- **`Element.title` is copied verbatim, with no "(copy)" suffix** — matching
  `duplicate_unit`, whose test asserts `copy.title == unit.title`
  (`tests/test_builder_duplicate_unit.py:75`).
- **No student state carries over.** Progress rows key on the element, and the copy has
  fresh pks, so a duplicated checklist or stepper starts empty for every student. This is
  the wanted behaviour; it is stated so it is not later read as a bug.

A duplicate lands at `source_index + 1` **within the source's own group** — so duplicating a
child of Tab A puts the copy directly below it, still in Tab A. Depth is unchanged, so a
duplicate needs no admissibility check at all: it is safe by construction.

## UI surface

```
Unit editor — "Pochodne"        ⧉ "Tabs: Case 1" is selected   [✕ cancel]

  • Text                          ✎ ↑ ↓ ⧉ ⊹ 🗑
  ┌ Spoiler "Rozwiązanie" ────────────────────────┐
  │   • Text                     ✎ ↑ ↓ ⧉ ⊹ 🗑     │
  │   [＋ Add element]  [📋 Move here] [⧉ Copy here]
  └───────────────────────────────────────────────┘
  • Tabs "Case 1"   ⧉ selected    ✎ ↑ ↓ ⧉ ⊹ 🗑

  [＋ Add element]  [📋 Move here] [⧉ Copy here]
```

- **`_element_row_controls.html`** gains the ⧉ and ⊹ forms. This one partial is included by
  every branch of `_element_row.html` at every depth, so both controls appear on every row
  in a single edit.
- **Paste buttons** render beside each slot's add-menu. `_add_menu.html` already carries
  `data-parent` / `data-tab` (`:24-25`) — precisely the scope a paste needs — and the
  top-level menu carries neither, which *is* the top-level scope. A small inclusion tag in
  the existing `courses_manage_extras` renders the pair, testing the slot against the
  precomputed legal-slot set; the template never re-derives the rule.
- **Containers force open while a mark is pending.** The `<details>` wrappers are
  `{% if forloop.first %}open{% endif %}` today (`_element_row.html:82`, `:132`), so a legal
  target could otherwise hide inside a collapsed tab.
- **The marked row** gets a modifier class, and the pane header shows which element is
  marked plus a cancel control — a mark that is invisible after scrolling is a trap.
- **Both context builders get the new keys.** `_render_editor_fragments`
  (`courses/views_manage.py:1244`) and `_editor_page` (`:1285`) build the editor context
  independently; the comment at `:1270-1278` records what happens when a key lands in only
  one — the first page load looks perfect and every later fragment swap silently drops the
  feature.
- New buttons carry translatable `aria-label` + `title` like their neighbours, and use the
  same icon idiom as the rest of the bar.

## Out of scope

- Cross-unit and cross-course clipboard. Both are reachable later on this machinery: the
  transfer layer already re-homes media and rewrites internal links. Neither is needed for
  the two stated author needs.
- Dragging a row into a container. The existing drag path is explicitly top-level-only
  (`courses/static/courses/js/editor_dnd.js:68-79`) and nested drop targets are a much
  larger job with no no-JS story.
- Multi-select, and undo of a move.
- Any change to `reorder_element`. Its scope-preserving guarantee stays exactly as written.

## Test plan

Following the repo's practice: every test is falsified by naming the mutant it must catch,
not merely run green.

**`paste_allowed` (unit).** A matrix over (root type, subtree shape, destination depth, slot
validity): non-nestable root into a slot; unknown slot; over-depth leaf; **over-height
populated container**; container landing at depth 4; destination inside the marked subtree;
top-level destination always admissible. Mutants: drop clause 2 → the slidebreak case must
go RED; replace `cap(n)` with a constant 4 → the container-at-depth-4 case must go RED; use
only the root's depth instead of the subtree max → the populated-container case must go RED.

**The agreement invariant.** For every (parent depth 1..4) × (leaf, container), a childless
element's `paste_allowed` verdict must equal `resolve_scope`'s. This is the drift guard
between the two rules; it must fail if either cap is changed in one place only.

**Copy fidelity (unit).** Duplicate a Tabs with two populated tabs, one of them holding a
Spoiler that itself has a child; plus a question with choices; plus an image element.
Assert: every join and concrete row has a fresh pk; rendered content matches; the
`MediaAsset` pk is *identical*, not merely equal; the subtree shape (parent/tab grouping) is
preserved at every depth.

**Move (unit).** The root is re-parented and its descendants' `parent`/`unit` rows are
byte-identical afterwards; the source group is compacted to `0..n-1`; the destination group
keeps distinct orders; `unit.updated` is bumped once.

**Views.** Each endpoint returns both fragments; 409 on a stale `unit_token`; 400 on an
inadmissible paste; 422 on a copy failure; and the session lifecycle table above, including
that a *copy* leaves the mark set and a *move* clears it.

**Templates.** A slot that fails `paste_allowed` renders no paste button; containers render
open while a mark is pending. These are meaningful here precisely because the markup is
server-rendered — the "green under the defect" trap applies to JS-built markup, not this.

**e2e.** Drive the real buttons, not the endpoints: select a **populated** container, paste
it into a spoiler, and confirm the student page renders the moved subtree. Per the depth-3
lesson, the fixture must move a populated container — that is the state an *add* can never
produce, and therefore the state no existing test covers.

## Slicing

**PR1 — duplicate in place.** `builder.duplicate_element`, the element-scoped transfer entry
point, one view, one URL, one ⧉ button. No clipboard, no session state, no new placement
rule. Delivers need #2 on its own.

**PR2 — the clipboard.** `paste_allowed`, the select/cancel/paste endpoints, the session
state, the paste buttons and the force-open behaviour. Delivers need #1.

## Risks

- **The element-scoped export is the only genuinely new transfer code.** Mitigation: scope
  the *existing* `emit` walk (`courses/transfer/export.py:507-526`) rather than writing a
  second walk that can disagree with it about which children a container has.
- **Newly-legal combinations.** A populated container landing in a slot is a shape adds
  cannot produce, which is exactly how the depth-3 slice shipped two client-side defects
  that thirteen per-task reviews missed. Mitigation: the e2e fixture above, and an explicit
  pass over the combinations a move newly permits.
- **Two context builders.** Called out in the UI section; a checklist item, not a design
  problem.
