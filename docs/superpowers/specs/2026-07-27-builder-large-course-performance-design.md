# Builder performance on large courses — design

**Date:** 2026-07-27
**Branch:** `worktree-builder-large-course-perf`
**Worktree directory:** `.claude/worktrees/builder-large-course-perf`
**Status:** design approved, spec awaiting review

## The complaint

On `/manage/courses/mat-pp/build/` (a 944-node course):

1. The page takes a long time before any action is possible; Chrome sometimes shows
   "Page unresponsive".
2. While dragging a unit to a new position, the drop marker lags well behind the pointer.
3. After dropping, the unit takes a long time to appear in its new place — and during
   the wait it still looks as though it is in its old position.

## Measured evidence

All numbers below were measured before any change, on the dev server against the real
`mat-pp` data, and are the acceptance baseline. `mat-pp` = 944 nodes (21 parts,
111 chapters, 5 sections, 807 units).

### Page load — 8.4 s to interactive (headless Chromium, `viewport 1400x900`)

| Stage | Measurement |
| --- | --- |
| Server render (TTFB) | 4.0–5.3 s across runs (`curl` 4.03 s, Playwright 5.28 s) |
| Response body | 3.0 MB, 247 ms on the wire |
| `domInteractive` | 8.37 s |

Server-side the render is **one SQL query** — there is no N+1 in the tree path. The cost is
pure template work. Rendering `_scope.html` for the whole tree in isolation:

- cold 5.19 s, **warm 3.14 s**
- 2.58 MB (2.70 MB without a request context; 3.0 MB in the real response, which adds
  2,833 CSRF inputs)

cProfile of the warm render (7.63 s under the profiler, ~2.4x overhead):

- `{% url %}` reversal — 5,803 calls, 2.33 s cumulative ≈ **30% of render time**
- gettext — 37,056 calls ≈ 10%

Of those 5,803 reversals, exactly **one** per row genuinely varies by node and cannot be
hoisted: `manage_node_export`, which is a real `<a href>` a no-JS author can follow.
`manage_node_move` (reversed **twice** per row — the `Move…` link in `_tree_node.html:30`
and the reorder form action in `_move_buttons.html:2`), `manage_node_delete` and
`manage_node_duplicate` are per-course constants reversed once per row. `manage_node_panel`
does vary by pk, but it is read only by JS (`builder.js:301`) and `builder.html:8` already
carries a `pk=0` template of the same URL on the `.builder` root — so it is hoistable by a
precedent already in the file. That leaves roughly **4,800** redundant reversals of 5,803.
`_scope.html` already hoists `manage_node_rename` this way and records the reason in a
comment.

### DOM weight

The total below is a browser count of the **real** response (`document.getElementsByTagName('*')`,
CSRF inputs included). The per-tag table is from an offline render of the same template
**without** a request context, so `{% csrf_token %}` emitted nothing and the table
**excludes the 2,833 CSRF hidden inputs**. Re-measure the same two ways after the change or
the numbers will not be comparable.

- Browser, real response: **38,418 elements**
- Offline render, no CSRF: **35,388 open tags**

| Tag (offline, no CSRF) | Count | Reconciles as |
| --- | --- | --- |
| `input` | 7,692 | 10,525 total inputs − 2,833 CSRF |
| `svg` / `use` | 6,471 each | 944 rows × 6 + 807 duplicate buttons |
| `button` | 5,037 | |
| `form` | 2,833 | 944 rename + 944 reorder + 807 duplicate + 138 add |
| `a` | 2,832 | 944 × 3 |
| `li` | 1,082 | 944 rows + 138 add rows |
| `ol` | 138 | one per scope |

Parse + forced layout of the tree fragment, measured in-page:

- with SVG: **3,295 ms** (38,415 elements)
- with every `<svg>…</svg>` stripped: **2,162 ms** (25,350 elements)

So the 6,471 `<use>` shadow-tree instantiations cost ~1.1 s, and the remaining
25k elements cost ~2.2 s.

### Drag — ~17 ms of forced work per `dragover`

`builder.js` `dragover` (currently `builder.js:432`) fires on every pointer move and, per
event:

| Operation | Measured (20 iterations) | Per event |
| --- | --- | --- |
| `clearDropMarks()` — two full-document `querySelectorAll` | 51.4 ms | 2.6 ms |
| DOM mutation + `getBoundingClientRect()` → forced synchronous layout | 288.2 ms | 14.4 ms |
| `root.querySelector('[data-node=…]')` | 0.1 ms | negligible |

The forced layout dominates: `targetFor()` calls `getBoundingClientRect()` immediately
after the handler has mutated the DOM (removing the old drop line, adding
`.drop-target`), so the layout cache is dirty and the browser must re-lay-out a
38k-element document. At ~60 pointer events per second this saturates the main thread.

### Drop — a whole-tree round trip

`views_manage.py:412` — a reparent returns `_render_tree`, i.e. the entire tree:

- full-tree fetch: **4,472 ms**, 3,065,506 bytes
- `innerHTML` parse of the response: 390 ms
- `replaceWith` of the live scope: 153 ms

`replaceWith` is not the problem. The ~4.5 s server round trip is, and because the old
DOM stays on screen throughout it, the node appears not to have moved.

### Secondary findings (measured, deferred — see Out of scope)

`_descendant_ids`, `_descendant_count` and `_element_count` walk `node.children.all()` in
a loop, one query per node:

| Call | Result | Time | Queries |
| --- | --- | --- | --- |
| `_descendant_ids(part)` | 62 | 162.0 ms | 63 |
| `_descendant_count(part)` | 62 | 165.7 ms | 63 |
| `_element_count(part)` | 385 | 282.3 ms | 114 |

End-to-end GETs with a real session cookie:

| Endpoint | TTFB | Size |
| --- | --- | --- |
| builder page | 4.03 s | 3,071,409 |
| move picker (`?node=109`) | 0.65 s | 2,200 |
| delete confirm (`?node=109`) | 0.82 s | 6,483 |
| node panel | 0.21 s | 82 |

## Root cause

One cause, three symptoms: **the builder materialises the entire course tree, fully
expanded, with the full control cluster on every row — and a reparent re-materialises it
end to end.** Load cost, drag cost and drop cost are all linear in "rows currently in the
DOM", and that number is always the whole course.

## Approaches considered

**Client-side collapse** (render everything, hide it in closed `<details>`) — rejected on
measurement. The server still spends 3.14 s and the browser still parses 38k elements.
`content-visibility` removes layout cost, not parse cost. It fixes none of the three
symptoms.

**Virtualisation** (only rows near the viewport exist) — best raw numbers, rejected as
disproportionate. It breaks native HTML5 drag, the no-JS form fallbacks the builder
deliberately supports, and every e2e that queries rows by selector.

**Lazy scopes** (render a child `<ol>` only when its parent is open) — chosen. It is the
only option that attacks the root cause, and it makes the drop response cheap without any
change to the response's shape: once "the whole tree" means ~21 parts plus whatever chain
is open, `_render_tree` is inherently small.

## Design

### Slice 1 — the performance fix (PR 1)

#### 1. Render only open scopes

`_tree_node.html` currently always recurses into `_scope.html` for a non-unit node. It
becomes conditional on an `open_ids` set threaded through the context:

- node in `open_ids` → render the child scope exactly as today, plus an expanded toggle
- otherwise → render a collapsed toggle carrying the child count, and **no children**

`_children_map(course)` stays a single query (measured 89 ms for 944 nodes) and supplies
the counts, so no new queries are introduced.

**The count is of DIRECT children only** — what `cmap` already holds. A chapter with 3
sections and 100 units below them reads "3", because that is what expanding it will
reveal, and because a descendant count would need the `_descendant_count` walk this spec
explicitly defers (see Out of scope). The label must use `{% blocktrans count %}`, not a
`{% trans %}` with an interpolated number: Polish has three plural forms and this is the
single most-repeated new string on the page.

**Toggle markup, placement and styling.** The toggle is the first child of
`.tree__rowhead`, before the kind badge, so the disclosure column lines up down the tree at
every depth. It is an `<a>` (works without JS, see §4) carrying:

- `href` — the no-JS target, per §4
- `data-toggle="<pk>"` — the JS hook
- `aria-expanded="true|false"`
- `aria-controls="<id of the child ol>"`, with the child `<ol>` given a matching `id`.
  `aria-expanded` alone leaves a screen reader unable to associate the control with the
  region it governs.

It uses a new chevron symbol in `_icon_sprite.html`, following the monochrome
`currentColor` SVG convention (never emoji), rotated by CSS between states rather than
swapped for a second symbol. `builder.css` gains its sizing, focus ring and hover states;
a leaf (unit) row renders a same-width empty spacer so titles stay aligned with their
container siblings.

**Focus and panel behaviour on collapse.** Collapsing a subtree can remove the focused
element and can hide the node the detail panel is currently showing. On collapse: if
`document.activeElement` is inside the removed subtree, move focus to the toggle that was
just activated; leave the panel content alone (it stays valid — the node still exists, it
is merely not visible), which matches the existing rule that reordering and dragging leave
the panel unchanged.

**Row-geometry fallout.** `tests/test_e2e_builder_tree_layout.py` (381 lines) measures tree
geometry and will react to the new column. Its expectations must be re-measured, not
adjusted by guesswork.

#### 2. Open state travels with the request

A single `open` parameter carries the set of open container pks. It appears as a query
parameter on GETs and as a form field on fragment POSTs.

**Rules, pinned to the caller.** Session seeding is a property of the *page* views, not of
the parser — otherwise a fragment POST that happened to omit `open` would silently re-seed
from the session and hand back a tree with a different set of scopes open than the one on
screen:

| Caller | `open` absent | `open=` (empty) | `open=<pks>` | `open=all` |
| --- | --- | --- | --- | --- |
| `builder()`, `_builder_with_notice()` | seed from session (§3) | empty set | that set | all containers |
| `_render_scope()` (all fragment paths) | **empty set — never seeds** | empty set | that set | all containers |

The absent-vs-empty distinction on the page views is load-bearing: `open=` is how "I
collapsed the last open scope" is expressed, and without it the next navigation would
spring the tree back open from the session.

**The `all` sentinel and its algebra.** `open=all` exists so expand-all need not ship an
enumeration. It must survive a subsequent collapse, or it evaporates on the first click.
The state is therefore a *pair*: `open=all` plus an optional `closed=<pks>` exclusion list,
and `{% toggle_href %}` and the JS collector both follow the same rule:

- collapsing a scope while `all` is in force appends its pk to `closed`, keeping `open=all`
- expanding a scope removes its pk from `closed`
- `closed` is dropped entirely whenever `open` is an enumeration

`_open_ids` resolves this to a concrete `set[int]` before returning, so the template
condition stays a plain membership test and no template ever has to understand the
sentinel.

**Helper contract.** `_open_ids(request, cmap, *, seed=False) -> set[int]`. It takes `cmap`
rather than `course` — `cmap` already scopes to the course — and `seed` selects the row of
the table above. It:

- reads `request.POST["open"]` first, falling back to `request.GET["open"]`, so a JS
  request's live DOM state wins over whatever the markup was rendered with
- parses comma-separated ints, discarding anything non-numeric
- discards pks absent from `cmap` (foreign course, or a node deleted since the URL was
  built)
- discards unit pks (a unit owns no scope)
- resolves `all` (minus `closed`) into the concrete set
- applies **one ceiling of 500 pks after resolution**, so it also bounds the `all` case.
  Over the ceiling, the set is truncated and the response carries a notice saying so.

Two separate reasons fix the ceiling at 500 rather than something larger:

- 500 comma-separated pks is roughly 3 KB. The enumerated form travels in a **query
  string** (the toggle href and the no-JS form action are both GET-shaped), and common
  front-ends cap the request line well below the 12 KB that 2,000 pks would need — nginx's
  default `large_client_header_buffers` is 8 KB — which would surface as a 414, not a
  graceful degradation.
- It bounds the render regardless of how the request was forged. An earlier draft capped
  only the enumerated form, which left `?open=all` — the actually dangerous input — free to
  force a full-tree render.

**Genuine call sites.** `_open_ids` is called in exactly three places: `builder()` and
`_builder_with_notice()` (both `seed=True`), and `_render_scope()` (`seed=False`).
`_render_tree()` and `_conflict_scope()` both delegate to `_render_scope()` and inherit it —
computing it in them too would evaluate the set twice per request and give the rules two
places to drift apart.

**How `open` reaches a POST.** The no-JS path carries it in the *form action's query
string* (`action="…/node/move/?open=1,2,3"`), built once per scope alongside the other
hoisted URLs in §7 — the open set is page-global, so hoisting is still correct and no
per-form hidden input is added. JS appends `open` to the `FormData`, which the
POST-before-GET precedence above lets win.

**A newly added container opens itself.** `node_add` adds the new node's pk to the open
set it renders with when the created node is a container. Otherwise an author who adds a
chapter would have to expand it before they could add anything into it.

Because the parameter round-trips through mutations, a reparent's `_render_tree` response
re-renders only the rows that were actually visible. Estimated ~60 rows / ~200 ms in place
of 3.0 MB / 4.5 s. **No narrowing of the reparent response to two scopes is needed** — the
existing structure simply becomes cheap. The same applies to add, delete and reorder.

#### 3. The session seeds the first load only

**New work** (there is no `session[` write anywhere in `views_manage.py` today): `node_panel`,
which already fires whenever a row is focused, gains a write of
`request.session["builder_last_node"][slug] = pk`, setting `request.session.modified`
explicitly since it mutates a nested dict.

**Skip the write when the pk is unchanged.** With a DB-backed session store an
unconditional write means a session save on every row focus, on an endpoint measured at
0.21 s. Comparing first makes the common case (re-focusing the same row, or a debounced
keyboard traversal settling back) free.

**Bound the dict.** One entry accumulates per course slug the author ever focuses a row in.
Keep the most recent 20 slugs, evicting oldest-first, so a platform admin browsing many
courses cannot grow the session payload without limit.

A builder GET with **no** `open` parameter derives `open_ids` from that node's ancestor
chain **plus the node itself when it is a container** — otherwise an author returns to the
course with the very chapter they were working in closed. Including the node raises the
ceiling by one: part → chapter → section → the node itself, so **at most 4 scopes open, as
a hard ceiling**. The "author opened fifty chapters, now every load is slow again" failure
mode cannot occur. Once `open` is present it wins, so two tabs on the same course do not
fight over shared state.

**A stale pk is discarded.** The stored pk outlives its node's deletion, a course
re-import, or a subtree move. A pk absent from `cmap` yields no chain and falls through to
the empty-session default below.

The session holds a pk only. It is a convenience, and losing it on logout is acceptable.

#### 3a. The empty-session default — small courses must not regress

The seed above says nothing about the case that is actually the most common: **no stored pk
at all** — a first-ever visit, and the state after every logout. Left implicit, `open_ids`
would be empty, and a 6-node course with two chapters would arrive collapsed to its parts.
That is a regression for the overwhelming majority of courses, which are nothing like
`mat-pp`.

**Rule: if the course has at most 150 nodes, open everything; otherwise open nothing.**
`cmap` is already loaded, so the node count is free. 150 is chosen from the measured
baseline: render cost is linear in rows, and 944 rows cost 3.14 s of template time, so 150
rows is ~500 ms of server render and ~5,600 elements — comfortably inside the success
criteria below, while `mat-pp` at 944 is decisively outside it.

The same threshold applies whenever the seed produces nothing (no stored pk, or a stale
one). It does **not** apply when `open` is present — an explicit `open=` means the author
collapsed things deliberately.

#### 4. No-JS parity

The builder's existing no-JS discipline is preserved:

- the toggle is a real link to the builder page with the recomputed `open` (and `closed`)
  value, built by a `{% toggle_href %}` template tag
- the href ends with `#node-<pk>`, and rows gain a matching `id`. Without it, expanding a
  scope 300 rows down is a full page load that returns to the top of the document.
- the no-JS mutation paths currently `redirect("courses:manage_builder", …)`; the redirect
  must carry the submitted `open` value, or every no-JS mutation would collapse the tree
- **the `Move…` and `Delete` links** (`_tree_node.html:30` and `:40`) are plain navigations
  to full pages that return to the builder. Their hrefs must carry the current `open`, and
  `_move_picker` / `node_delete` must propagate it into their own redirect and Cancel
  targets — otherwise the round trip collapses the tree. The same applies to the
  `Import content` and `Export` links in the builder header.

**`q` and toggles must not contradict each other.** An earlier draft had `{% toggle_href %}`
preserve `q` while §9 declared `open` ignored under a filter, which would have made every
toggle a no-op while filtering. The rule is: **`q` seeds the initial open set; an `open`
supplied alongside it wins.** So a toggle href under a filter carries both `q` and the
recomputed `open`, and expanding or collapsing works normally inside filtered results.

**`{% toggle_href %}` must not become the new bottleneck.** Naively it rebuilds the whole
comma-joined open set per row — at the 500-pk ceiling that is 500 rows × a ~3 KB string.
Precompute the joined string once per render (it is the same for every row) and splice the
single differing pk in, or emit the `all` + `closed` form, which stays short by
construction.

#### 5. Expanding a scope

A new GET endpoint `manage_node_scope` (`…/build/node/<pk>/scope/`) returns
`_render_scope(request, course, pk)` for the JS path. `_render_scope` already exists and is
already the fragment contract used by every mutation; this exposes it for reads.

**`_require_manage` alone is not enough** — it validates the *course*, not the node.
`_render_scope` (`views_manage.py:196-199`) resolves a missing or foreign pk to
`parent = None` and returns **200 with an empty scope**; for a unit pk it returns 200 with
`parent_kind="unit"`, rendering an add affordance under a unit; and a non-numeric pk raises
`ValueError` in `cmap.get(int(scope_ref))` → 500. So the endpoint must:

- carry `@login_required`
- resolve the node with `get_node_or_404(pk, slug)` **before** the access check, matching
  the deliberate ordering in `node_panel` (`views_manage.py:156`)
- 404 on a unit kind (a unit owns no scope)
- then `_require_manage` for the 403

**The endpoint URL is not hardcoded in JS.** `builder.js` never hardcodes a URL; the move
endpoint arrives as `data-node-move-url` on the `.builder` root (`builder.html:9`). Follow
that precedent: add `data-node-scope-url` reversed with `pk=0` and substitute the pk
client-side, as `builder.html:8` already does for the panel URL. A literal path in the JS
would break under any URL-prefix or i18n-prefix change.

`builder.js` gains a delegated click handler on `[data-toggle]`. It calls
`e.preventDefault()` first — the toggle is an `<a href>`, and without it the fetch races a
full page navigation (every other delegated link handler in the file does this; see
`builder.js:245` for `[data-move]`). Then:

- collapsed → show an inline pending state on the toggle, fetch the scope with
  `open` = current set + this pk, insert the returned `<ol>`, set `aria-expanded="true"`
- expanded → remove the child `<ol>` from the DOM and set `aria-expanded="false"`
  (no request; the client owns collapse)

**Where the `<ol>` goes is load-bearing.** It must be appended as a **direct child of
`li.tree__row`, after `.tree__rowhead`** — the position the server already renders it in.
Three existing code paths depend on exactly that and break silently otherwise:

- `applyRename`'s `row.querySelector(":scope > ol.tree__scope")` (`builder.js:155`), which
  refreshes the child scope's `data-updated` — the drop target's `parent_token`
- `dragover`'s `targetRow.querySelector(":scope > .tree__scope")` (`builder.js:442`), which
  is how hovering a container row targets its own scope rather than its parent's
- `targetFor`'s reliance on `scope.children` being the rows (`builder.js:415`)

Every existing fragment request gains `open` collected from the live DOM
(`root.querySelectorAll('ol.tree__scope[data-scope]')` → `data-scope` values, excluding
`"top"`), in the `all` + `closed` form when that is in force. One helper, called from the
submit handler and the drop handler.

#### 6. Drag handler

Two changes, both small, both independent of the above:

- `clearDropMarks()` stops scanning the whole document. Track the currently marked scope
  and the injected line in module-scoped variables — the file already does exactly this
  for `movingPk`/`clearMoving()`.
- `dragover` is throttled to one `requestAnimationFrame`, so at most one forced layout
  happens per frame instead of one per pointer event.

  **The legality decision stays synchronous, and `preventDefault()` stays conditional on
  it.** Today `builder.js:455-456` calls `preventDefault()` *only after* the legality check
  passes, so an illegal target correctly shows the browser's no-drop cursor. Making it
  unconditional would advertise every location — a unit's own row, the dragged node's own
  descendants — as a valid drop target, and the `drop` handler bails on those *without*
  calling `preventDefault()` (`builder.js:471`), so the browser would additionally run its
  default drop action on a gesture the author was told was legal. The legality check costs
  no layout (only `closest()` and attribute reads), so it does not need throttling. **Only**
  `clearDropMarks()`, `targetFor()` and the line insertion move into the rAF callback.

  **Cancellation semantics.** A frame scheduled by the last `dragover` can run *after*
  `drop` or `dragend` has already executed `clearDropMarks(); drag = null`
  (`builder.js:480`, `:494`). It would then dereference a null `drag` inside `targetFor` and
  re-insert a `.drop-line` into a tree `applyFragment` has just swapped — a stray marker
  with no drag in progress. So: store the pending frame id module-scoped,
  `cancelAnimationFrame` it in **both** the `drop` and `dragend` handlers, and have the
  callback return early if `drag` is null.

With lazy scopes these paths operate on tens of rows rather than 944, but the fix is what
keeps expand-all usable and is cheap to make.

**Dropping onto a collapsed container — an accepted behaviour change.** `dragover`
prefers a hovered row's own child scope (`:scope > .tree__scope`) and falls back to the
ancestor scope. A collapsed container has no child scope, so hovering it will drop the
node as its *sibling*, not into it. This is accepted for slice 1: to move a unit between
two chapters the author opens both and drags, which is the gesture the reporter already
described. Spring-loaded expansion (auto-expanding a collapsed container after a hover
dwell) is the natural follow-up and is deliberately not in this slice — it needs its own
dwell-timing and cancellation design, and it would be the only part of the drag path that
issues a network request mid-gesture.

#### 7. Hoist the per-course URL reversals

`manage_node_move`, `manage_node_delete` and `manage_node_duplicate` are identical for
every row. Reverse them once per scope and pass them down, exactly as `_scope.html`
already does for `rename_url` (and keep the same explanatory comment style). ~30% of
render time for a mechanical change, and it benefits every scope render including
expand-all.

Two sites are easy to miss:

- **`_move_buttons.html:2`** reverses `manage_node_move` as the reorder form's action, and
  it is a separate `{% include … with node=node is_first=… is_last=… %}` per row. The
  hoisted `move_url` must be threaded through that include's arguments too, or ~944
  reversals survive the change (`manage_node_move` is reversed *twice* per row — that link
  and `_tree_node.html:30`).
- **`manage_node_panel`** (`_tree_node.html:24`) is read only by JS (`builder.js:301`), and
  `builder.html:8` already carries a `pk=0` template of it on the root. Hoist it the same
  way and have the JS substitute the pk, removing another ~944 reversals. Only
  `manage_node_export` must stay per-node, because it is a link a no-JS author follows.

#### 8. Busy affordance

One mechanism, reused everywhere: while a tree-pane fragment request is in flight, set a
busy state on the tree pane, styled in `builder.css`. Toggles additionally get an inline
pending state so it is obvious *which* row is loading. This is the "course loading"
feedback asked for, and it is what makes expand-all honest.

**Concurrency.** Requests here overlap routinely — a debounced panel fetch, a rename
commit and a drop can all be in flight at once — so a naive set-on-start / clear-on-finish
would clear the busy state while a second request is still running, or leave it stuck if
one rejects. Use a **counter**: increment when a request is issued, decrement in a
`finally`-equivalent on both the success and the failure path, and treat the pane as busy
while the counter is above zero. **The panel fetch does not count** — it targets the detail
panel, not the tree pane, and it fires on mere keyboard traversal, so including it would
flicker the tree's busy state during ordinary navigation.

### Slice 2 — filter and expand-all (PR 2)

#### 9. Filter box

A `q` parameter on the builder view. There is **one** mechanism, not two: `q` restricts
`children_map`, and everything else is a consequence of that.

- one query: `ContentNode.objects.filter(course=course, title__icontains=q)`, ordered by
  `("order", "pk")` — the same ordering the tree uses — and capped at the **first 100
  matches in that order**, with a "showing first 100 of M" notice. The cap's ordering is
  stated so results are deterministic, and 100 rather than 200 because each match drags in
  up to 3 ancestors, and 100 × 4 = 400 sits under the 500-pk ceiling from §2.
- the view builds a restricted `children_map` containing the matches plus their ancestors;
  `_scope.html` renders whatever `cmap` it is given, so **no template change is needed for
  the filtering itself**
- the open set is the consequence: the union of the matches' ancestor chains, so every
  match is actually visible. Toggles still work on top of it (§4) — `q` seeds, a supplied
  `open` wins.

**Counts under a filter show the filtered count**, matching the restricted `cmap` the rows
are rendered from, so a toggle never promises children the filtered view will not show. The
notice makes it clear the view is filtered.

Without JS it is a plain GET form. With JS it swaps the tree pane.

#### 10. Expand-all

A control that requests `open=all`, behind the busy affordance from §8. On `mat-pp` it
will still take seconds — that is inherent, and it is now an explicit, clearly-signalled
choice rather than the default on every visit.

## Testing

Per the repo's practice, tests are written to fail first, and a test that cannot go red is
treated as not written. See `falsify-tests-not-run-them`.

### Migrating the existing suite — a first-class work item, not cleanup

**The existing builder suite assumes the whole tree is in the DOM, and most of it will fail
on this change for reasons unrelated to a defect.** `tests/test_e2e_builder_ws2.py` alone
waits on `[data-scope="{ch.pk}"]` and drives `li.tree__row[data-node="{sec.pk}"]`
immediately after load, on courses seeded 2–3 levels deep (23 such references). The same
applies to `test_manage_builder.py`, `test_manage_node_ops.py`, `test_manage_affordance.py`,
`test_manage_node_duplicate.py`, `test_e2e_builder.py`, `test_e2e_builder_authoring.py`,
`test_e2e_builder_reorder.py`, `test_e2e_builder_tree_layout.py` and
`test_e2e_inline_rename.py`.

The migration must be **enumerated file by file before implementation starts**, and it must
use a shared helper rather than per-test edits, so the rule stays in one place:

- **Python/view tests:** a helper that appends `?open=<all container pks>` (or `open=all`)
  to the builder GET.
- **e2e tests:** a fixture helper `expand_to(page, node)` that clicks the toggles down the
  chain and waits for each scope — driving the real control, never `page.evaluate`, per
  `e2e-must-drive-real-ui`.

Most seeded fixtures are small, so §3a's ≤150-node rule will keep many of them fully
expanded and passing untouched. **That is a trap, not a relief:** a test that passes only
because its fixture is under the threshold is no longer exercising the lazy path. At least
one test per behaviour must seed above the threshold, or force `open=`, so the collapsed
path is genuinely covered.

**Structural guards (CI-safe).** Wall-clock assertions are flaky on CI runners and are
deliberately *not* used as the guard:

- a closed scope emits no descendant rows — delete the conditional in `_tree_node.html`
  and this must go red
- query-count invariant on the builder view (the tree path stays at one query)
- response-size / row-count invariant against a seeded large course, which is the test
  that actually guards this regression from coming back
- `open` round-trips through a mutation: expand a scope, perform a reparent, assert the
  returned fragment still has that scope open
- absent-vs-empty `open`: absent seeds from session, `open=` does not
- session seed opens exactly the ancestor chain and nothing else
- sanitisation: foreign pks, unit pks, junk and a stale (deleted) session pk are discarded
- POST-before-GET precedence: an `open` in the body wins over one in the action's query
  string
- **a fragment POST with no `open` renders an empty open set and does NOT seed from the
  session** (the §2 table's second row — the case an earlier draft left undefined)
- **the ≤150-node default**: a small course arrives fully expanded with no session pk; a
  course above the threshold arrives collapsed; an explicit `open=` overrides both
- **`open=all` survives a collapse**: collapse one scope under `all` and assert every other
  scope is still open, and that the request carried `all` + `closed`, not an enumeration
- the 500-pk ceiling truncates and emits a notice, including via `open=all` on a course
  above the ceiling
- filter then expand: with `q` active, a toggle still expands (the `q`-seeds/`open`-wins
  rule), and the filtered count is what the toggle shows
- adding a container returns it already open; adding a unit does not change the open set
- a collapsed container with zero children still renders a toggle, and expanding it
  yields the empty scope plus its add affordance
- **`manage_node_scope` access control**, per `access-widening-reachability-tests`:
  anonymous → login redirect; non-manager → 403; pk from another course → 404; unit pk →
  404; non-numeric pk → 404 not 500; manager → 200 carrying the expected `data-scope`

**e2e (`-m e2e`, mandatory marker or the tests are silently deselected).**

- expand and collapse a scope
- drag across two separately-opened branches — driving the real gesture, never
  `page.evaluate`
- no-JS toggle link preserves the open set through a mutation redirect

**Manual, before the PR.** Re-run the exact probes used to produce the baseline above
(page timing + DOM count, dragover micro-benchmark, full-tree fetch) and record the
after-numbers in the PR against the before-numbers in this spec.

## Success criteria

| Slice | Metric | Before (measured) | Target |
| --- | --- | --- | --- |
| 1 | builder `domInteractive` on `mat-pp` | 8.37 s | < 1.5 s |
| 1 | builder response size | 3.0 MB | < 300 KB |
| 1 | DOM elements on load | 38,418 | < 3,000 |
| 1 | reparent round trip | 4.47 s | < 500 ms |
| 1 | forced layout per `dragover` | 14.4 ms | ≤ 1 per frame |
| 1 | a ≤150-node course still arrives fully expanded | n/a | no regression |
| 2 | filter round trip on `mat-pp` | n/a | < 1 s to first result |
| 2 | expand-all on `mat-pp` | n/a | busy state visible for its whole duration; no "Page unresponsive" |

## Known traps

Recorded so they do not each cost a review round:

- **Playwright's text engine never matches `input[type=text]`.** Tree row titles are
  inputs; e2e must not locate rows with `text=` / `get_by_text`.
- **`{# #}` must be single-line**; use `{% comment %}` for multi-line template comments.
- **New i18n strings** need msgids in both catalogs; module-level translatable dicts must
  use `gettext_lazy`. Regenerate with `-l pl -l en --no-obsolete` and clear fuzzy entries
  (two deletions: `#, fuzzy` and `#| msgid`) — a fuzzy entry arrives pre-filled with an
  unrelated translation.
- **`.mo` is tracked and binary** — it has no 3-way merge. Rebase and regenerate before
  opening the PR.
- **This worktree needs its own `DATABASE_URL`**; concurrent pytest runs collide on the
  Postgres `test_libli` database. Never run two pytest invocations at once.
- **`_add_affordance.html` renders LAST in every scope**, so a plain descendant query for
  an add form's `parent_token` returns a *grandchild's* token. Use the pk-anchored
  `form.tree__add[data-add-scope=…]` selector.
- **`applyFragment` takes `firstElementChild` only.** Any future multi-scope response
  would need it to loop — this design deliberately avoids needing that.
- **`swapping` vs `isConnected`** in the rename focusout guards is load-bearing; Chromium
  dispatches `focusout` from inside `replaceWith()` with `isConnected` still true. Do not
  "simplify" it while touching this file.
- Verify `git branch --show-current` immediately before commit/push — a parallel session
  has switched branches under this worktree before.

## Out of scope

Recorded, deliberately not fixed here:

- **The 6,471 `<svg><use>` instantiations** (~1.1 s of parse). With lazy scopes only tens
  of rows render, so this stops mattering outside expand-all, and changing it would fight
  the established icon convention.
- **The N+1 in `_descendant_ids` / `_descendant_count` / `_element_count`** (measured
  63–114 queries, 0.16–0.28 s), which slows the Move picker (0.65 s) and the delete
  confirmation (0.82 s). Each can be rewritten against the already-loaded `children_map`.
  A separate, small PR — it is a different code path from the tree render and is not what
  the reported symptoms describe.
- Per-row control-cluster deferral (rendering the action cluster only for the focused
  row). It would make even a fully expanded tree cheap, but it breaks the no-JS path and
  is unnecessary once scopes are lazy.
