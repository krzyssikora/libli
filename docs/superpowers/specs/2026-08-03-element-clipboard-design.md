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
| Absolute-position insert within a group | `ordering.place_element`, `courses/ordering.py:96-117` | Positioning, **after** the caller has persisted the scope — see below |
| Group compaction after a removal | `ordering.compact_elements`, `courses/ordering.py:58-60` | The source slot after a move |
| Whole-unit deep copy via the transfer layer | `builder.duplicate_unit`, `courses/builder.py:326-375` | The shape the element-level copy follows |
| Container child walk (Tabs / TwoColumn / Spoiler) | `walk_unit_joins`' `emit`, `courses/transfer/export.py:507-526` | The **export** side of a copy only — not the subtree of the placement rule |
| Two-pass element materialisation | `importer._create_elements`, `courses/transfer/importer.py:872-911` | Grafting a copied subtree into an existing unit |
| Generic `form[data-op]` interception + fragment swap | `courses/static/courses/js/editor.js:283` | **The operations need no new JavaScript** — PR2's force-open needs three lines, see UI surface |

**Two of these do less than their names suggest, and the design depends on the difference.**

- `place_element` saves every row with `save(update_fields=["order"])` and only when the
  order actually changed (`courses/ordering.py:112-116`). It therefore **cannot persist a
  re-parent**, and it will not save the moved row at all when its old order happens to equal
  its new index. It also *reads* `element.parent` / `element.tab_id` to pick the sibling
  group (`:101-102`). Both consequences are specified under Move semantics. Its sibling
  `place_node` handles the equivalent case with a deliberate full save and a documented
  precondition assert (`courses/ordering.py:63-93`); `place_element` has neither, and this
  spec does not change it — the caller carries the obligation.
- `materialize_duplicate` calls `_create_nodes` and returns a **ContentNode**
  (`courses/transfer/importer.py:1093-1119`). Grafting into an *existing* unit must not
  create a node, so it needs its own entry point (see Copy semantics).

The last table row is load-bearing for the whole design: because every editor operation
already answers with a re-rendered editor+preview fragment pair (`_render_editor_fragments`,
`courses/views_manage.py:1244-1282`), and because the JS intercepts *any* form carrying
`data-op`, a new operation is a template form plus a view.

**What "works without JavaScript" means here, precisely.** The form posts, the mutation
happens, and the response is the same fragment pair rendered as a bare page — because
`element_move` and `element_delete` both test `_editor_ctx` *before* the no-JS redirect
branch (`courses/views_manage.py:1163-1167`, `:1177-1182`), so a no-JS success in the editor
today does **not** redirect. Only the conflict path does (`_element_conflict:1206-1209`). The
new operations copy that existing behaviour exactly rather than fixing it; the bare-fragment
no-JS response is a pre-existing wart affecting ↑ ↓ 🗑 equally, and changing it would change
those ops too. Out of scope, recorded here so the claim is not read as stronger than it is.

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
incoming request — no model→key hop is needed.

The two must agree, and **the existing drift test is weaker than it looks**: it asserts
`CONTAINER_TRANSFER_KEYS == set(_CONTAINER_SLOT_KEY)` but only
`len(CONTAINER_TRANSFER_KEYS) == len(_CONTAINER_REGISTRY)`
(`courses/tests/test_nesting_rule.py:285-286`). A length equality passes green when a fourth
model is added to the registry under a *different* fourth key — which is exactly the seam
`cap(n)` and clause 2 now both sit on. Strengthening it is part of this work, using the
model→key helper promoted below.

### The subtree `S`

**`S` is the FK walk — `join.children`, every child row, matched slot or not.** The repo has
two subtree walkers that deliberately disagree, and picking the wrong one silently breaks the
rule:

- `builder._collect_subtree_pks` (`courses/builder.py:416-450`) descends `join.children`.
- `walk_unit_joins`' `emit` (`courses/transfer/export.py:507-526`) descends only
  `resolved_tabs()` / `resolved_columns()` / `resolved_children()`, which **omit** a child
  whose `tab_id` matches no slot. Its own docstring says so, and says the delete path must
  use the FK walk instead.

A move re-parents the root, so an orphaned child travels with it whether or not any slot
resolves — the FK walk is what actually happens, so it is what clause 3 must measure. Using
the export walk would let an over-deep orphaned branch through.

The two walks therefore disagree for a *copy*: the export omits an orphan-slot child, so the
copy silently drops it. That loss is **accepted and stated** (see Copy semantics) rather than
fixed here — the export's omission is deliberate and long-standing, and reproducing it keeps
the copy identical to what an export/import round-trip already produces.

Placing the subtree `S` rooted at `R` into (`P`, slot `t`), for `mode ∈ {move, copy}`, is
admissible iff:

```
0. R.unit == unit, and (P is None or P.unit == unit)
1. if P is not None:  P is a container and t ∈ slots(P)      [resolve_scope clause 2]
2. if P is not None:  type(R) ∈ NESTABLE_TYPE_KEYS           [resolve_scope clause 1]
3. for every n ∈ S:   dest_depth + rel(n) ≤ cap(n)
4. P ∉ {R} ∪ descendants(R)
5. if mode == move:   (P.pk if P else None, t) != (R.parent_id, R.tab_id)
```

Clause 5 compares **pks, not instances**. Model equality is pk-based so an instance
comparison happens to work, but `P is None` versus `R.parent_id is None` and the str/int
trap this spec spends a paragraph on elsewhere make the explicit form the safer one, and it
matches the `slot_key` discipline used for the template keys.

**Clause 5 suppresses the paste buttons on the slot the element already occupies**, for
moves only. Without it a move becomes "send myself to the end of my own group", where source
and destination are the same group and a compact-then-place ordering bug has somewhere to
hide. A *copy* into the element's own slot is meaningful (a sibling copy) and stays allowed —
which is why clause 5 is the one mode-dependent clause, and why `paste_allowed` takes the
mode.

**Clause 2 checks the root only, deliberately.** Every descendant is already nested, so it
already passed clause 1 when it was created. The root is the only node whose nestability is
unproven — it may have been sitting at top level, where non-nestable types (slidebreak,
most question types) legally live.

Clause 2 needs the root's **transfer key**, since `NESTABLE_TYPE_KEYS` is keyed that way.
The model→key map exists as `courses/transfer/export._MODEL_TO_KEY` (`:402`) but is private.
Promote it to a named public helper rather than reaching into the private name from
`builder.py`; the import stays lazy, as builder's existing transfer imports are, to avoid
the documented import cycle (`courses/builder.py:339-341`).

A marked row whose own GFK is dangling falls out consistently and by accident, so it is
worth stating: `type(None)` is in neither the model→key map nor `_CONTAINER_REGISTRY`, so
clause 2 rejects it for any nested destination and `is_container` reports False. A top-level
paste passes the rule and then fails at export as a 422, per the `problems` check below. The
two paths disagree in status code but never in outcome — the broken element is not copied.

**Clause 3 is the one genuinely new rule.** An *add* always places a single element, so it
never needed a height check; a paste can place a populated container. Note that clause 3
subsumes `resolve_scope`'s clauses 3 and 4 exactly: for a childless `R`, `S = {R}` and
`rel = 0`, so it reduces to `depth(P) + 1 ≤ cap(R)` — which is clause 3 for a leaf and
clause 4 for a container. **This equivalence is a test, not a comment** (see below): for
every (parent depth, type) pair, `paste_allowed` on a childless element must agree with
`resolve_scope`. That is what stops the two rules drifting when the cap next moves.

**The equivalence is over clauses 1–3 only**, and the test must be built accordingly.
Clauses 4 and 5 have no `resolve_scope` counterpart: an empty Tabs pasted into its own slot
is rejected by clause 4 while `resolve_scope` accepts it (that is what an *add* into that tab
does today), and a move into the element's own current slot is rejected by clause 5 while
`resolve_scope` accepts it. A matrix that happens to use the element's own container as the
destination therefore produces a false RED, which an implementer would "fix" by weakening a
clause. Construct the destination parent as a row distinct from the element under test and
neither its ancestor nor its descendant.

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
subtree_facts(marked_join)                                    -> SubtreeFacts
paste_allowed(unit, marked_join, dest_parent, tab, mode, facts=None)
                                                              -> (bool, reason_key | None)
```

`unit` is a parameter, not an ambient fact, so **clause 0 lives inside the authority** and is
exercised by the same unit tests as the rest of the rule. `resolve_scope` takes `unit` for
the same reason and uses it to filter the parent (`courses/builder.py:117-138`), which is
what makes same-unit — and transitively same-course — hold. `mode` is present only for
clause 5.

**`facts` is the whole per-render precomputation, and it is a parameter so that the
enumerator and the endpoint provably run the same code.** `SubtreeFacts` carries the two
values that depend on the marked element and not on the destination: `min over n∈S of
(cap(n) − rel(n))`, and the descendant pk set clause 4 tests. The render computes it once
and passes it to every per-slot call; the endpoint omits it and the authority computes it
itself. The alternative — the view applying `dest_depth ≤ scalar` on its own — would put a
second copy of clause 3 outside the authority, which is exactly the drift "one authority"
exists to prevent.

**It returns a reason, not a bare bool**, because the 422 has to say what was wrong.
`reason_key` is one of a small enumerated set (`not_a_container`, `unknown_slot`,
`type_not_nestable`, `too_deep`, `into_own_subtree`, `own_slot`, `wrong_unit`), each mapped
to a translatable string at the view. A bare bool would force the endpoint to invent a
generic message, and "the author sees why nothing moved" would not be delivered.

Called by the view to build the set of legal slots for the render, called again by the paste
endpoint inside the transaction to enforce, and exercised directly by the unit tests. The UI
cannot offer what the server would reject, and a hand-crafted POST cannot beat the UI.

### Enumerating the slots to render

Nothing in the repo enumerates a unit's slots, and the editor never needed one: `_editor_rows`
fetches **top-level** joins only (`unit.elements.filter(parent__isnull=True)`,
`courses/views_manage.py:1235-1239`) and the template reaches nested containers lazily through
`resolved_tabs()` as it renders. So the "precomputed legal-slot set" is new code, not a
lookup, and it is specified here rather than left as a magic step:

```
enumerate_slots(unit) -> [(parent_join_or_None, tab_id)]
```

- Starts with the synthetic top-level pair `(None, "")`.
- Walks the FK tree (`join.children`, the same walk `S` uses, so the two cannot disagree
  about what exists), and for every join whose model is in `_CONTAINER_REGISTRY` emits one
  pair per slot.
- Reads slots as `normalizer(getattr(obj, "data", None))[list_key]` — **spelled out because
  the `getattr` is load-bearing**: `SpoilerElement` has no `data` field at all, and the
  argument is evaluated before the normalizer runs. `resolve_scope` carries the same call
  with the same comment (`courses/builder.py:154-161`). Writing `obj.data` instead is an
  `AttributeError` — a 500 — on every unit containing a spoiler, which is the container the
  e2e fixture targets.
- Uses the registry's **non-destructive** normalizer, as clause 1 validation does. Note this
  is a different id source from the one the *render* uses: the template goes through
  `resolved_tabs()` / `resolved_columns()`, which call the **destructive** `normalize_data`
  (`courses/models.py:1427-1443`). For well-formed data the two agree. They diverge for a
  wider class than padding alone: `normalize_labels_and_ids` (`:1369-1394`) and
  `TwoColumnElement.normalize_ids` (`:1494-1513`) mint a fresh id for **any** entry whose id
  is missing, malformed or duplicated, and `normalize_data` then pads *or truncates* on top
  (`:1396-1409`) — with a different id minted on every call. So the divergence covers
  `< MIN_TABS` padding, `> MAX_TABS` truncation, and malformed or duplicate ids alike.

  **In the padding and malformed-id directions this fails closed**: the template renders a
  slot whose id is not in the enumerated set, that slot shows no paste button, and this is
  exactly what `resolve_scope` already does to an *add* aimed at a phantom slot. **In the
  truncation direction it does not.** The non-destructive normalizer keeps slots the
  destructive one drops, so no button renders (the UI is safe) but `paste_allowed` would
  *admit* a hand-crafted POST into a truncated slot and orphan the pasted element.
  `resolve_scope` has the identical exposure for adds today, so this is a documentation gap
  rather than new breakage — but the write path is not closed in both directions, and saying
  "fails closed" without that qualification would be false. The template tests pin one
  padding case and one malformed/duplicate-id case.
- The view builds `SubtreeFacts` once, then calls `paste_allowed` per pair per mode and
  passes the two resulting sets to the template. The scalar is `min over n∈S of
  (cap(n) − rel(n))`, **not** a plain subtree height, because `cap` differs per node: a Tabs
  holding a Spoiler has height 2 but a limit of `min(3−0, 3−1) = 2`, and a height-based
  check would admit `dest_depth = 3`, landing the Spoiler at depth 4.
- **Emits each slot's depth alongside its key**, and `paste_allowed` takes it rather than
  recomputing `dest_depth`. The FK walk knows the depth for free; without this, every
  per-slot call re-walks `join.parent` hop by hop through `builder.element_depth`.
- When nothing is marked, this is skipped entirely: no walk, no cost on the common render.

**The marked-render cost is bounded explicitly**, because it is paid on *every* response for
as long as a mark is pending, and every editor operation returns a full re-render.
`_editor_rows` prefetches only top-level joins (`courses/views_manage.py:1235-1239`), so a
naive enumerator issues a GFK fetch per join plus a depth walk per slot — hundreds of queries
on a unit with a few hundred elements. The walk therefore carries
`prefetch_related("content_object")`, reuses the depth it already knows (above), and a
query-count assertion pins the result so a regression is caught rather than merely felt.

**The FK walk is a superset of the rendered tree, and that is the agreement that matters.**
The enumerator descends `join.children`; the *renderer* descends
`resolved_tabs()` / `resolved_columns()` / `resolved_children()`. A container that is itself
an orphan-slot child is reached by the FK walk but never rendered, so the enumerator can emit
pairs no template will ever ask about. Harmless in that direction — enumerator ⊇ renderer
means extra pairs are unreachable rather than wrong — and it is the same fail-closed argument
as the normalizer split above. The direction that would hurt is the reverse, and it cannot
happen.

**Key shape is pinned as a single flattened string**, `slot_key(parent_pk, tab_id) ->
f"{parent_pk or ''}:{tab_id}"`, with the top-level slot as `":"`. One helper, used by the
view when building both sets and by the template tags when testing them.

The reason is that Django's template language cannot construct a tuple, so a
`(parent_pk, tab_id)` key would be untestable from the template that needs it — and the
existing `in_set` filter (`courses_manage_extras`) takes a single scalar. A string key also
disposes of the int-vs-str trap: `_add_menu.html:24-25` renders
`data-parent="{{ parent }}" data-tab="{{ tab }}"`, where `parent` is the `el.pk` **int**
supplied at the include sites (`_element_row.html:91`, `:141`, `:195`) and becomes a string
only once serialised into an attribute — so a tuple key would arrive as `(int, str)` from
context and `(str, str)` from the DOM. Building the key through one helper makes that
impossible. A mismatched key still fails **closed**: every paste button disappears, which
reads as "the feature is broken" rather than as a bug in a key, so a template test must
assert the top-level slot renders its buttons.

## Clipboard state

```python
request.session["element_clip"] = {"unit": <unit pk>, "element": <element pk>}
```

No mode is stored — move-vs-copy arrives with the paste. Lifecycle:

| Event | Effect |
|---|---|
| ⊹ select | Sets the mark. **No DB write, so no token check** — the paste re-validates everything. It does re-render, and **that discards an open element form along with any unsaved edits**, exactly as ↑ ↓ 🗑 already do. See the note below; this is accepted, not solved. |
| ⊹ select while another element is marked | **Replaces** the mark. There is exactly one slot; no stack, no multi-select. |
| ⊹ select on the element that is already marked | Clears it, so the row's own control toggles. |
| ✕ cancel | Clears it. |
| 📋 Move here | Clears it (the element is now where you put it). |
| ⧉ Copy here | **Keeps** it, so one original can seed several slots. |
| Rendering another unit | Ignored; not cleared (you may navigate back). |
| Marked element gone or not in this unit | Treated as absent and cleared lazily at render. |

**On losing an open form to ⊹.** An open element form is *server*-rendered into
`.el-edit-slot` — `_render_open_form` returns the whole fragment pair with the form embedded
via the `open_form` context key (`courses/views_manage.py:1487-1493`; `_element_row.html:42`
and the matching lines in each branch). It is not client-side state, so **no server-side
re-render can preserve unsaved edits**: regenerating the form reads the element back from
the DB and yields a pristine one. Passing `open_form_pk` alone would be worse than nothing —
it renders an editing-styled row with an empty slot, since `open_form` would be blank. And
nothing on the page even transports which element is open: `_element_row_controls.html`
carries `element`, `unit` and `unit_token` only. So ⊹ discards the open form exactly as
↑ ↓ 🗑 do today. Accepted, and stated because "select is only advisory" invites the
assumption that it is non-destructive.

## Operations

Three endpoints carry the four author-visible operations (select and cancel share one).
All are POST, all take `ctx=editor`, and all answer through `_render_editor_fragments` so
the editor pane and the live preview refresh together.

**All three views are `@login_required` and open with
`course = _require_manage(request, slug)`**, like every neighbouring view (`element_move`,
`element_delete`, `element_add`, `node_duplicate`).

**The clip endpoint must resolve its `unit` against the course, despite writing no data.**
It is tempting to reason that it "only writes session state" and needs no validation beyond
the course gate — but it answers through `_render_editor_fragments`, which renders that
unit's element list *and* its live preview. A POST carrying a `unit` pk from course B, by a
user who manages only course A, would render course B's content. So it resolves the unit as
`ContentNode.objects.filter(pk=…, course=course, kind=UNIT).first()` — the same filter
`_element_conflict` already uses (`courses/views_manage.py:1201-1203`) — and returns 409
when that misses, which also covers a missing, non-numeric or non-unit pk rather than
letting `_render_editor_fragments` raise.

The *marked element* is deliberately **not** validated at clip time beyond belonging to that
unit: the paste re-resolves it through `_locked_element(course, …)`, which filters on
`unit__course`, and a mark is only a session note until then.

| URL name | Payload | Service |
|---|---|---|
| `manage_element_duplicate` | `element`, `unit`, `unit_token` | `builder.duplicate_element` |
| `manage_element_clip` | `element`, `unit`, `action=select\|cancel` | session only |
| `manage_element_paste` | `parent` (blank = top level), `tab`, `mode=move\|copy`, `unit`, `unit_token` | `builder.paste_element` |

**Service signatures and returns**, following the neighbours' convention (`reorder_element`
→ `(unit, changed)`, `delete_element` → `unit`, `duplicate_unit` → the new node):

```
duplicate_element(course, element_pk, unit_token)                  -> (unit, new_join)
paste_element(course, element_pk, parent_ref, tab, mode, unit_token) -> (unit, placed_join)
```

Both return the join, not just the unit, because the view needs it: `unit` feeds
`_render_editor_fragments`, and the open-set for the post-operation render is derived by
walking `placed_join.parent` upward. Without the join returned, the ancestor chain the UI
section relies on has no source.

URL paths follow the existing shape, `manage/courses/<slug>/build/element/<op>/`
(`courses/urls.py:209-217`).

**Payload parsing follows `resolve_scope`'s rules exactly.** `parent` and `tab` come
together or not at all; either alone is a `NestingError` → 400, not a silent fall-through to
top level (`courses/builder.py:127-132`). Reusing that parse — rather than writing a second
one — is what stops `parent=""&tab=t3` from being read as an always-admissible top-level
paste. A `mode` that is neither `move` nor `copy` is likewise a 400; there is no default.

**Both mutating services are `@transaction.atomic`** and take the existing locks before the
token check, as every element mutation already does (`reorder_element`,
`delete_element`, `save_element`): `_locked_element` for the subject row, which also yields
the unit, then `_check_token`. **`paste_allowed` is re-evaluated inside that lock**, after
it, so a concurrent add into the destination slot cannot interleave between the check and
the placement. The render-time call is advisory only; the in-transaction call is the
enforcement.

**All three mutating operations end with one `unit.save(update_fields=["updated"])`.**
Neither `_create_elements` nor `place_element` touches `unit.updated`, so without an
explicit bump a duplicate or a paste-copy would leave the optimistic-concurrency token
unchanged — a later stale-token 409 would fail to fire and a concurrent author's edit would
silently win.

**Error rendering in the editor context is not the builder's, and `_op_error` cannot be used
here.** Two independent facts make this so:

- `editor.js` acts only on 200, 409 and 422 (`:292-294`). A 400 produces no swap, no
  message, no flash whatsoever.
- A 422 carrying `_op_error` is **equally invisible**: `applyFragments` replaces only
  elements matching `[data-scope="editor"]` / `[data-scope="preview"]` (`editor.js:84-90`),
  and `_op_error.html` is a bare `<div class="op-error">` with no such wrapper, so nothing is
  swapped; `flash()` fires only on 409 (`:294`). `element_save`'s 422 is visible only because
  it returns `_render_editor_fragments(..., status=422)` instead.

So **every editor-context error response renders through `_render_editor_fragments(request,
unit, status=…)` with a new `error` context key, and that key must be rendered inside
`_editor_scope.html`** — in the editor pane, above `.pane-body`.

**Do not copy `_editor_page`'s existing `error` shape.** It renders at `editor.html:59`,
and `_editor_scope.html` — the only source of `[data-scope]` — is included at
`editor.html:93`. So the existing block sits *outside both panes*: reusing its position
would ship a 422 exactly as invisible as the `_op_error` div this section rejects. Moving
the block into `_editor_scope.html` also keeps `_editor_page`'s own error path working
(it renders `editor.html`, which includes the scope), and the `editor.html:59` block must
then be removed rather than left in place, or the settings-save 422 renders its message
twice. `_op_error` stays for builder-context callers only. (`element_move` already returns
`_op_error` for its "exactly one of direction or position" 422 and is therefore silent in the
editor today; that is pre-existing, out of scope, and not a licence to copy the pattern.)

That matters because this design deliberately creates a **reachable** rejection — the render
said a slot was legal, a concurrent edit changed the destination, and the in-transaction
re-check refuses. An author clicking a button that does literally nothing is not an
acceptable outcome, and it is exactly what both the naive 400 and the naive `_op_error` 422
produce.

- stale `unit_token`, the element vanished, or **no mark in the session** (absent, naming a
  different unit, or pointing at a deleted row) → **409** via `_element_conflict`
  (`courses/views_manage.py:1196-1212`), which already recovers the unit from the `unit`
  payload field and re-renders rather than dumping the author back to the tree. The no-mark
  case is reachable in ordinary use: a move clears the mark, so a back-button resubmit, a
  double POST, or a second tab holding a stale render all post a paste against an empty
  clipboard.
- **an inadmissible placement that the UI had offered → 422** as an editor fragment carrying
  the reason, so the author sees why nothing moved.
- a **malformed payload** the UI can never produce — half-supplied scope (`parent` without
  `tab` or vice versa), unknown `mode` → **400** `"bad nesting"`, matching
  `element_add`/`element_save`'s handling of `NestingError`
  (`courses/views_manage.py:1560`, `:1626`). Invisible in the editor, and correctly so: it is
  unreachable from the UI and only a hand-crafted POST produces it.
- a copy that fails mid-flight → **422**, likewise as an editor fragment. `node_duplicate`
  uses `_op_error` for its `TransferError` (`courses/views_manage.py:992-998`), but that is a
  builder-context view; the editor path cannot borrow it.

**Which parse raises which status.** "Follow `resolve_scope`'s rules" above means its
*parsing* rules only. `resolve_scope` is parse **plus** admissibility — clauses 1–4 all raise
`NestingError` (`courses/builder.py:145-172`) — so reusing it wholesale would send an
over-deep or vanished-slot paste back as a 400, contradicting the line above; it also demands
a fourth argument, `type_key`, in the *form* namespace, which a paste (holding only a join)
has no natural value for. Split it explicitly:

- a **parse-only helper** — `parent`/`tab` together-or-neither, the `int()` guard, and the
  `filter(pk=…, unit=unit)` lookup (`courses/builder.py:127-142`). `resolve_scope` is
  refactored to call it, so the two parses cannot drift.
- **admissibility is `paste_allowed`'s alone**, and always reports 422.

The helper's two failure kinds get **different statuses**, because they differ in
reachability:

- **Shape errors** — `parent` without `tab`, a non-integer pk, an unknown `mode` — stay
  **400**. No UI can produce them.
- **A well-formed but unresolvable parent pk** is **422** with reason `parent_gone`. Today
  that line raises `NestingError("unknown parent")` (`courses/builder.py:141-142`) and would
  land on the invisible 400 — yet "the destination container was deleted by another author
  between the render and the click" is precisely the concurrent-edit case this design
  deliberately creates. A silent no-op there is the outcome this section exists to rule out.

### Move semantics

Re-parent **the root join row only**. Descendants keep their `parent` FK and their `unit` FK
untouched, so the whole subtree travels with the root for free — only the root's group
membership changes.

The step order is load-bearing, because `place_element` neither writes the scope nor is
guaranteed to save the moved row at all:

1. **Capture `(old_parent, old_tab_id)` before mutating anything.** `delete_element` does
   exactly this, with the comment *"capture before the row disappears"*
   (`courses/builder.py:462`). A move mutates those same fields in place, so reading them
   afterwards would compact the *destination* twice and leave a hole in the source.
2. Set `element.parent` / `element.tab_id` to the destination **and persist them**:
   `save(update_fields=["parent", "tab_id"])`. `place_element` saves only `order`
   (`courses/ordering.py:112-116`), so a scope left unsaved here is a scope never written.
3. Call `ordering.place_element(el, unit, None)` — `None` is what `place_element:106-107`
   clamps to the end of the group, which is the "a paste appends at the end" decision.
   It reads the in-memory `parent`/`tab_id` to pick the sibling group
   (`courses/ordering.py:101-102`), so step 2 is also its precondition — the same
   precondition `place_node` states explicitly for nodes (`courses/ordering.py:63-76`).
   Because it saves only rows whose order changed, the moved row may legitimately not be
   saved by this call; step 2 is what guarantees the move is persisted regardless.
4. `compact_elements` on the **captured** source group (the same call `delete_element`
   makes, `courses/builder.py:470`).
5. One `unit.save(update_fields=["updated"])`.

### Copy semantics

Serialise the subtree through the transfer layer and re-materialise it, following
`duplicate_unit`'s shape. **This needs two new transfer entry points, one per side** — the
export side alone is not enough:

```
export.build_element_export(unit, root_join)      -> (document, media_assets, problems)
importer.graft_elements(document, media_map, unit) -> the created root Element join row
```

**`build_element_export` is one substitution, not a new export.** It calls the existing
`build_export(unit.course, node=unit, drop_missing_media=False)` and changes exactly one
thing: the roots query. `build_export` hard-codes "roots are top-level" as
`Element.objects.filter(unit_id__in=unit_pks, parent__isnull=True)`
(`courses/transfer/export.py:565-570`); the element-scoped export needs that replaced by the
single `root_join`. So the new parameter belongs on **`build_export`** — a `roots_by_unit=`
override — and **not** on `walk_unit_joins`, which already takes its roots as an argument
(`walk_unit_joins(unit_pk, joins_by_unit)`, `:473`) and needs no signature change at all;
calling it with `{unit.pk: [root_join]}` yields the desired `(root_join, None, "")` first
emission as-is. Everything else — `_ordered_nodes`, the manifest, `link_nodes`, passes 3–5 —
is reused untouched. Scoping with `node=unit` is what makes `document["nodes"]` a
single-entry list, which the graft below relies on; assert that rather than assume it.

`graft_elements` mirrors `materialize_duplicate`'s `work()` with three differences, each
forced by grafting into an existing unit rather than creating one:

- **It does not call `_create_nodes`.** It fabricates `node_map = {<the document's single
  unit id>: unit}`, because `_create_elements` looks the unit up as `node_map[el["unit"]]`
  (`courses/transfer/importer.py:887`).
- **It returns the created root join**, not a `ContentNode` — `materialize_duplicate` returns
  `node_map[document["nodes"][0]["id"]]` (`:1117`), which has no meaning here.
  `_create_elements` returns a bare `list(joins.values())` and discards its `{export_id:
  join}` map (`:911`), so the root is re-derived as **the single join in `created` whose
  `parent_id` is `None`** — its second pass has already set `parent` in memory for every
  child (`:902-909`), and an element-scoped document has exactly one parentless element.
  Assert that exactly one matches. Do **not** use `created[0]`, and do not zip the return
  against `document["elements"]` either: both re-introduce the same unstated assumption,
  that payload order survives into the returned list.
- **It does not call `_rewrite_links`.** That function remaps internal content links onto
  newly created nodes; in an element-scoped copy no node is created and `node_map` is a
  fabrication over the existing unit, so running it would rewrite every internal link in the
  copied elements onto that one unit — silently corrupting targets that are in fact
  unchanged. A copy stays in its own unit, so its links already point where they should.
  This is the one place where imitating `materialize_duplicate` verbatim produces a bug, so
  it is called out rather than left to be inferred.

It keeps `_run_import`'s wrapper, so any failure rolls back and is normalised to
`TransferError` → 422, which is what the error table promises.

**Setting the destination scope is the caller's job, and is easy to miss.**
`_create_elements`' second pass skips any element with no `parent` in the payload
(`courses/transfer/importer.py:902-905`), and the root of an element-scoped document is
exactly that — so the graft returns a root sitting at `parent=None, tab_id=""`, i.e. **top
level**, regardless of where it is destined. `place_element` will not fix this (see Move
semantics). The builder service therefore performs the same steps 2–3 as a move on the
returned root, then bumps `unit.updated`. Without this, duplicating a child of Tab A drops
the copy at the unit's top level.

**Export flags and a broken subtree.** `build_element_export` runs with
`drop_missing_media=False`, as `duplicate_unit` does (`courses/builder.py:348`), so a
missing media file cannot silently thin the copy.

A dangling GFK needs an explicit decision, because **nothing raises on its own**.
`build_export` records the broken join in its `problems` list and `continue`s
(`courses/transfer/export.py:588-590`), returning normally; `duplicate_unit` then discards
that list outright (`_manifest, document, media_assets, _problems = …`,
`courses/builder.py:347-348`). Copy that shape and a broken subtree yields a **silent
partial copy with a 200**.

Nor does anything downstream complain. `walk_unit_joins` reaches children only through the
`isinstance(obj, TabsElement | TwoColumnElement | SpoilerElement)` branches
(`courses/transfer/export.py:512-523`); when the GFK is dangling `obj` is `None`, no branch
matches, and the broken join's **entire subtree is never yielded**. So no orphaned
`parent_ref` is ever emitted and no importer `KeyError` occurs — the failure mode is quiet
data loss, not a crash. (An earlier draft of this spec claimed the opposite; it was wrong,
and the corrected mechanism is why the check below has to be explicit rather than assumed.)

**Therefore: the service inspects `problems` and raises `TransferError` when it is
non-empty**, failing the whole paste as a 422. With `drop_missing_media=False` no
missing-media problem can be produced, so a non-empty `problems` means exactly "a dangling
GFK" — which makes "raise if problems" a clean and testable rule rather than a heuristic.

Four further properties are deliberate:

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
- **No student state carries over to a copy.** Progress rows key on the element, and the
  copy has fresh pks, so a duplicated checklist or stepper starts empty for every student.
  This is the wanted behaviour; it is stated so it is not later read as a bug. **A move is
  the converse**: the pks are unchanged, so every progress row follows the element into its
  new scope — which is the whole reason a move is worth having rather than
  delete-and-re-author. Asserted in the move tests.
- **A child whose `tab_id` matches no slot is NOT copied.** The export walk omits it by
  design (see The subtree `S`), so the copy reproduces exactly what an export/import
  round-trip already produces. A *move* keeps such a child, because the FK travels. The two
  modes therefore differ on this one degenerate case, deliberately: making the copy carry
  orphans would mean a second walk that disagrees with the export, which is precisely the
  drift the Risks section warns against.

A duplicate lands at `source_index + 1` **within the source's own group** — so duplicating a
child of Tab A puts the copy directly below it, still in Tab A. It runs the same
graft-then-set-scope-then-position sequence as a paste-copy, with the destination being the
source's own scope. Depth is unchanged, so a duplicate needs no admissibility check at all:
it is safe by construction.

That index arithmetic rests on a precondition worth carrying over from `duplicate_unit`,
which spends four lines on the same point for nodes (`courses/builder.py:353-356`):
`Element.order` is `OrderField(for_fields=["unit"])` (`courses/models.py:319`), so the
grafted copy is born with a **unit-wide** `max+1` and therefore sorts last in its group. The
source's index is consequently unaffected by the copy's presence, and the sibling list may
be read *after* the graft. Do not "fix" this by excluding the copy from the sibling list or
by re-reading the group before grafting — both silently change which index means "below the
source".

## UI surface

```
Unit editor — "Pochodne"                        ← page chrome, NOT swapped
┌───────────────────────────────────────────────────────────────────┐
│ Editor · 4 elements     ⊹ Selected: "Tabs: Case 1"   [✕ cancel]   │  ← .pane-head
├───────────────────────────────────────────────────────────────────┤
  • Text                          ✎ ↑ ↓ ⧉ ⊹ 🗑
  ┌ Spoiler "Rozwiązanie" ────────────────────────┐
  │   • Text                     ✎ ↑ ↓ ⧉ ⊹ 🗑     │
  │   [＋ Add element]  [📋 Move here] [⧉ Copy here]
  └───────────────────────────────────────────────┘
  • Tabs "Case 1"   ⊹ selected    ✎ ↑ ↓ ⧉ ⊹ 🗑

  [＋ Add element]  [📋 Move here] [⧉ Copy here]
```

**Glyph assignment is fixed, one meaning each:** ⧉ is the *copy family* and nothing else
(duplicate below, Copy here); ⊹ is *select*, and is therefore also what marks the selected
row and heads the banner; 📋 is *move here*. An earlier draft used ⧉ for all three, which
left an author unable to tell the row-bar control from the paste-mode one at a glance. The
one exception is **✕, which is context-scoped**: on a row it cancels the open editor
(`_element_row.html:57-58`), in the banner it cancels the mark. The two never appear within
the same control group, and both read as "dismiss this".

The mock shows the **resting** bar, six controls: ✎ ↑ ↓ ⧉ ⊹ 🗑. ✕ belongs to the open-editor
state and is the seventh; it is counted in the eight-control argument under Decisions
because that argument is about the worst case. If the resting bar would exceed six, the
third source-side button is exactly what gets dropped — which is the reasoning that produced
this design.

Two facts about where these controls actually live, both easy to get wrong:
`_element_row_controls.html` holds **only ↑ ↓ and 🗑** — ✎ and ✕ are written inline in each
branch of `_element_row.html`. So (a) the new forms go **between** the move form and the
delete form in the partial, to land the mock's ⧉ ⊹ ordering rather than appending after 🗑;
and (b) the **slidebreak** branch (`_element_row.html:2-17`) includes the partial but has no
✎/✕ of its own, so its bar becomes five controls, not six. Both are correct as they stand —
a slide break has nothing to edit, but duplicating and moving one are perfectly sensible.

- **`_element_row_controls.html`** gains the ⧉ and ⊹ forms. This one partial is included by
  every branch of `_element_row.html` at every depth, so both controls appear on every row
  in a single edit.
- **Paste buttons** render beside each slot's add-menu, via a small inclusion tag in the
  existing `courses_manage_extras` that tests the slot against the precomputed legal-slot
  set; the template never re-derives the rule. `_add_menu.html` already carries
  `data-parent` / `data-tab` (`:24-25`) — precisely the scope a paste needs — and the
  top-level menu carries neither, which *is* the top-level scope.
- **The tag is invoked at the four include sites, not inside `_add_menu.html`** — the three
  nested ones (`_element_row.html:91`, `:141`, `:195`) plus the top-level menu in
  `_editor_scope.html`. Four edits rather than one, bought deliberately: the nested includes
  sit behind `{% if depth < max_nest_depth %}`, so putting the buttons inside the add-menu
  would silently inherit that guard and make a slot unpasteable exactly where the menu is
  suppressed. **Paste legality is `paste_allowed`'s business alone.** The two agree for
  authored data; they diverge only for an over-deep container reachable through legacy or
  direct-ORM rows, where the row recursion is deliberately unbounded while the menu is not —
  and there, a paste that clause 3 permits should be offered even though a fresh *add* is
  not. Concretely: **the tag call goes outside the `{% if depth < max_nest_depth %}` guard**,
  which sits on the same line as the `_add_menu` include at each of the three nested sites.
  The consequence is that the buttons can render with no `.addwrap` beside them, so the CSS
  must define a standalone appearance as well as the grouped-against-the-add-menu one.
- **Containers force open while a mark is pending.** The `<details>` wrappers are
  `{% if forloop.first %}open{% endif %}` today (`_element_row.html:82`, `:132`), so a legal
  target could otherwise hide inside a collapsed tab.
- **Server-side `open` alone does not survive, and fixing that costs three lines of JS.**
  `applyFragments` calls `applyStoredTabs(root)` immediately after every swap
  (`editor.js:92`), which does `if (v !== null) d.open = v === "1";` over
  `details.tabs-rows` from a localStorage entry written on each author toggle (`:38-50`).
  Any tab the author has ever collapsed is therefore **re-collapsed client-side after** the
  server rendered it open — hiding the paste button in the destination the mark exists to
  reach. Resolution: the server stamps forced-open wrappers with `data-force-open` and
  `applyStoredTabs` skips those. This is the one place the feature adds JavaScript, and the
  "no new JavaScript" property in the reuse table is qualified accordingly: it holds for the
  three operations and their forms, not for force-open. **The stamp and the skip land in
  PR1**, together with the open-ancestor mechanism they make work: `applyStoredTabs` runs
  after a duplicate's swap just as it runs after a paste's, so splitting them across PRs
  would ship a PR1 mechanism that provably does nothing — and PR1's own template test would
  pass while the real UI stayed collapsed. (Columns are unaffected —
  `saveTab`/`applyStoredTabs` match `details.tabs-rows` only, an existing asymmetry this
  spec does not change.) **This one must be verified in a browser, not by a template test:**
  the defect lives in `applyStoredTabs`, which a template test never runs, so such a test
  passes whether or not the JS honours the stamp. Collapse a tab so `saveTab` writes its
  entry, select an element, then assert the tab is open and its paste buttons visible after
  the swap. Mutant: remove the skip → RED.
- **A forced-open container cannot be collapsed while a mark is pending**, and that is
  intended. With the stamp set, the skip ignores the stored value, so a tab the author
  collapses snaps open again on the next swap; `saveTab` still records the preference, which
  takes effect once the mark clears. Stated so it is not read as a bug.
- **And they stay open for the render that follows a paste.** A *move* clears the mark, so
  the very re-render that shows the result would otherwise have no mark pending and every
  `<details>` would snap back to first-tab-only — the author moves a row into tab 2 and
  watches it vanish, which is the exact trap force-open exists to prevent. The paste
  response therefore also opens the **ancestor chain of the pasted element**: the view
  passes that chain (a set of `(parent_pk, tab_id)` pairs, same key shape as the slot set)
  and the `<details>` condition ORs it in.
- **Scrolling after a paste is left as-is, and that is a choice.** `editor.js` computes its
  "keep this row in view" anchor from `form.closest(".el-row[data-element]")` *before* the
  POST (`:286-289`), so it can only ever name a row that already exists — never the pasted
  element, whose pk does not yet exist client-side. Making the new element the scroll target
  would need a response header or a marker attribute plus JS to read it, which would cost
  the design its "no new JavaScript" property for a scroll nicety. So: a nested paste
  anchors on the **destination container's** row (the form's nearest `.el-row` ancestor),
  and a top-level paste has no `.el-row` ancestor at all, so `keepId` is null and no scroll
  adjustment happens. Forcing the ancestor chain open is what actually keeps the result
  visible; this bullet exists so the weaker scroll behaviour is not mistaken for a defect.
- **The marked row** gets a modifier class. Note this is **six edits, not one**: the
  `<li class="el-row…">` opening tag is written out separately in every branch of
  `_element_row.html` (`:3`, `:19`, `:45`, `:97`, `:147`, `:199`). Only the *controls* come
  from the shared partial. The template test must assert the modifier on a nested row as
  well as a top-level one, or five branches can ship unstyled.
- **The mark banner goes in the editor pane's `.pane-head`** (`_editor_scope.html:8`), not in
  the page chrome the mock's top line suggests. `applyFragments` replaces only the two
  `[data-scope]` panes, and `editor.html`'s header region sits outside both — a banner there
  would render once on page load and then never reflect a select, a cancel or a paste. This
  is the same trap `refreshUnitTokens` exists to work around, and its comment says so
  (`editor.js:62-66`). **Any mark-dependent chrome must live inside
  `[data-scope="editor"]`.** A view test asserts the select response's editor fragment
  contains the banner.
- **The banner labels the element title-or-type**, falling back exactly as the row label
  already does (`{% if el.title %}…{% else %}{{ obj|element_summary }}`,
  `_element_row.html:62-63`); `Element.title` is routinely empty, so a naive label renders
  `"" is selected`.
- **Both context builders get the new keys.** `_render_editor_fragments`
  (`courses/views_manage.py:1244`) and `_editor_page` (`:1285`) build the editor context
  independently; the comment at `:1270-1278` records what happens when a key lands in only
  one — the first page load looks perfect and every later fragment swap silently drops the
  feature.
- **The inclusion tag is `takes_context=True`, and that is load-bearing.** Django renders an
  inclusion tag's template with a *fresh* context otherwise, so `{% csrf_token %}` emits
  nothing and the no-JS submit 403s. Under JS the failure hides — `post()` sends the token
  as an `X-CSRFToken` header from the cookie (`editor.js:209-217`) — and a 403 is outside
  editor.js's `{200, 409, 422}` set, so even the JS-adjacent failure is silent.
  `courses_manage_extras` has no form-rendering tag to copy, so this is stated rather than
  inferred. The tag reads `slug`, `unit`, the unit token and the two legal-slot sets from
  context, and takes the slot's `parent` and `tab` as arguments. A template test asserts the
  rendered paste form contains a `csrfmiddlewaretoken` input.
- New buttons carry translatable `aria-label` + `title` like their neighbours, and use the
  same icon idiom as the rest of the bar.
- **Styling ships with the feature**, in `courses/static/courses/css/editor.css` (the
  editor's only sheet, `editor.html:7`): the marked-row modifier, the `.pane-head` banner,
  and the grouping of the two paste buttons against the add-menu. A modifier class with no
  rule is invisible, which for the mark is indistinguishable from the feature being broken.
  Verified with light **and** dark screenshots of a marked row and of a slot showing both
  paste buttons, judged separately rather than assumed from the light pass.

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
populated container**; **a container-inside-a-container subtree** (a Tabs holding a Spoiler);
container landing at depth 4; destination inside the marked subtree; the marked element's own
slot, for each mode; top-level destination always admissible.

The container-inside-container row is not optional padding — it is the only row that
distinguishes `min(cap(n) − rel(n))` from a plain subtree height. With a leaf-only subtree
the two agree, so a height-based implementation stays green through every other row.

Mutants: drop clause 2 → the slidebreak case goes RED; replace `cap(n)` with a constant 4 →
the container-at-depth-4 case goes RED; use only the root's depth instead of the subtree
minimum → the populated-container case goes RED; use subtree *height* instead of
`min(cap(n) − rel(n))` → **only** the container-inside-container case goes RED; drop clause 5
→ the own-slot move case goes RED while the own-slot copy case stays green.

**`enumerate_slots` (unit).** New code carrying three of this spec's own named traps, and
template tests cannot cover it — they assert a *missing* button, which stays green if the
enumerator returns nothing at all. Direct tests, with mutants: a spoiler nested inside a tab
contributes its slot (mutant: `obj.data` instead of `getattr(obj, "data", None)` →
`AttributeError`, RED); a join with a dangling GFK is skipped without raising; a two-level
container tree emits every slot including the synthetic `(None, "")`; the returned keys are
built by `slot_key`, not by hand.

**The agreement invariant.** For a childless element, `paste_allowed`'s verdict must equal
`resolve_scope`'s. Two things make this test easy to write vacuously:

- **It spans two key namespaces.** `resolve_scope` takes a *form* key and translates it
  through `_NESTABLE_FORM_KEY_ALIASES` before testing `NESTABLE_TYPE_KEYS`
  (`courses/builder.py:149`); `paste_allowed` takes a join and reaches the *transfer* key
  through the promoted model→key helper. A matrix built only from types whose two keys
  coincide (text, image, tabs) never exercises the nine aliased types — `fill_blank`,
  `switch_grid`, `two_column` and the rest — which is exactly where a drift would hide.
  Parametrise over the aliased types, feeding `resolve_scope` the form key and
  `paste_allowed` the corresponding join. Mutant: break one alias entry → RED.
- **Parent depth 4 is unconstructible by any legal write.** A parent must be a container,
  and `cap` says a container never lives at depth 4. Build that row by direct ORM write
  anyway, precisely to prove both rules reject it identically, and say in the test why it
  bypasses the normal path.

Also assert the strengthened container-key drift test: `{model_to_key(m) for m in
_CONTAINER_REGISTRY} == CONTAINER_TRANSFER_KEYS`, replacing today's length equality
(`courses/tests/test_nesting_rule.py:286`). Mutant: register a fourth container model under
a key absent from `CONTAINER_TRANSFER_KEYS` → the old assertion stays green, the new one
goes RED.

**Copy fidelity (unit).** Duplicate a Tabs with two populated tabs, one of them holding a
Spoiler that itself has a child; plus a question with choices; plus an image element.
Assert: every join and concrete row has a fresh pk; rendered content matches; the
`MediaAsset` pk is *identical*, not merely equal; the subtree shape (parent/tab grouping) is
preserved at every depth; **the copied root's `parent`/`tab_id` are the destination's, not
`None`/`""`** — the graft leaves them unset, so this assertion is what catches the copy
landing at top level; and **an internal content link in a copied element still resolves to
its original target**, which is what `_rewrite_links` would have broken.

**Move (unit).** The root is re-parented **and that scope is persisted** — re-read from the
DB, not asserted on the in-memory instance, since `place_element` writes only `order`;
include the case where the moved row's old order equals its new index, where `place_element`
saves nothing at all. Descendants' `parent`/`unit` rows are byte-identical afterwards; the
source group is compacted to `0..n-1`; the destination group keeps distinct orders. A
copy-into-own-slot leaves that single group compacted with the copy last.

**`unit.updated` is bumped exactly once by each of duplicate, paste-move and paste-copy** —
asserted per operation, not only for move. Mutant: drop the bump from the copy path → the
copy test goes RED (and, without this, a stale-token 409 would never fire after a copy).

**Views.** Each endpoint returns both fragments; each is gated by `_require_manage` (drive
one as a user who cannot manage the course and assert the refusal). 409 on a stale
`unit_token` **and on a paste with no mark in the session** — absent, naming another unit, or
pointing at a deleted row, the case a back-button resubmit reaches. 400 on a half-supplied
scope (`parent` without `tab` and vice versa) and on an unknown `mode`; **422, not 400, when
the in-transaction re-check rejects a placement the render had offered** — and assert the
*body*, not only the status: it must carry a `[data-scope="editor"]` fragment with the
reason in it. A 422 whose body is a bare `_op_error` div passes a status-only assertion and
is still invisible to the author, which is precisely how this error path was got wrong once
already. Also assert a foreign-course `unit` pk on the clip endpoint renders no foreign
content. 422 on a copy
failure, including **a subtree containing a dangling GFK**: assert the whole paste fails
rather than silently copying a thinned subtree, which is what discarding `problems` would
produce. Plus the session lifecycle table in full: replace-on-reselect, toggle-off, a *copy*
leaves the mark set, a *move* clears it.

**Templates.** A slot that fails `paste_allowed` renders no paste button; the marked
element's own slot offers Copy here but not Move here; containers render open while a mark
is pending, on the render following a paste, **and on the render following a duplicate**
(PR1's case — otherwise the copy is born inside a collapsed tab); the top-level pair renders
its buttons (the key-shape failure is silent and closed, so this is the test that catches
it); a Tabs row with fewer stored tabs than `MIN_TABS` renders its padded slot with **no**
paste button, pinning the fail-closed divergence between the enumerator's non-destructive
normalizer and the renderer's destructive one. These are meaningful here precisely because
the markup is server-rendered — the "green under the defect" trap applies to JS-built
markup, not this.

**e2e.** Drive the real buttons, not the endpoints: select a **populated** container, paste
it into a spoiler, and confirm the student page renders the moved subtree. Per the depth-3
lesson, the fixture must move a populated container — that is the state an *add* can never
produce, and therefore the state no existing test covers.

## Slicing

**PR1 — duplicate in place.** `builder.duplicate_element`, **both** new transfer entry points
(`build_element_export` with `build_export`'s new roots override, and `graft_elements` — the
graft is not PR2-only; a duplicate needs it just as much), the `problems` → 422 check, the
scope-setting step on the grafted root, one view, one URL, one ⧉ button. No clipboard, no
session state, no new placement rule.

PR1 **also carries the open-ancestor mechanism**, not PR2. Duplicating an element inside tab
2 re-renders with only tab 1 open (`{% if forloop.first %}`), collapsing both the source and
its brand-new copy out of view — the identical trap the paste path spends a paragraph
preventing. The duplicate's ancestor chain is the source's and is already known, so the
open-set is a few lines here; PR2 then reuses it for the marked element and for the pasted
one.

So PR1's inventory also includes the pieces that mechanism and its error path depend on,
none of which are PR2's despite being introduced in sections about the clipboard:
**`slot_key`** (the open-set uses the same key shape), the **`error` context key on
`_render_editor_fragments`** and its render slot in `_editor_scope.html` (with the
`editor.html:59` block moved, not duplicated), and the **`data-force-open` stamp plus the
`applyStoredTabs` skip**. Delivers need #2 on its own.

**PR2 — the clipboard.** `paste_allowed` and `enumerate_slots`, the promotion of the
model→key helper and the strengthened container-key drift test in
`courses/tests/test_nesting_rule.py` (both belong here: clause 2 is the only consumer of the
helper), the select/cancel/paste endpoints, the session state, the paste buttons, and
reusing PR1's open-set for the mark and the paste. Delivers need #1.

## Risks

- **New transfer code exists on both sides, not one.** An earlier draft claimed the export
  was the only new piece; the import-side graft is equally new, because
  `materialize_duplicate` creates a node and returns one. Mitigation for the export half:
  override the **roots query in `build_export`** (`courses/transfer/export.py:565-570`) and
  leave `walk_unit_joins` alone — it already takes its roots as an argument and needs no
  change, and its `emit` closure must be neither extracted nor re-implemented. Its docstring
  already anticipates entry at a non-root join (the `seen` set is described as defence for
  exactly that). One walk, one behaviour; a second walk would be free to disagree about
  which children a container has.
- **Newly-legal combinations.** A populated container landing in a slot is a shape adds
  cannot produce, which is exactly how the depth-3 slice shipped two client-side defects
  that thirteen per-task reviews missed. Mitigation: the e2e fixture above, and an explicit
  pass over the combinations a move newly permits.
- **Two context builders.** Called out in the UI section; a checklist item, not a design
  problem.
