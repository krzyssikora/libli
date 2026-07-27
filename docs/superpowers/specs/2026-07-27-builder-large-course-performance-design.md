# Builder performance on large courses — design

**Date:** 2026-07-27
**Branch/worktree:** `worktree-builder-large-course-perf`
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

Of those 5,803 reversals only two per row genuinely vary by node (`manage_node_panel`,
`manage_node_export`). `manage_node_move`, `manage_node_delete` and
`manage_node_duplicate` are per-course constants reversed once per row —
roughly 3,900 redundant reversals. `_scope.html` already hoists `manage_node_rename`
this way and records the reason in a comment.

### DOM weight — 38,418 elements

| Tag | Count |
| --- | --- |
| `input` | 7,692 |
| `svg` / `use` | 6,471 each |
| `button` | 5,037 |
| `form` | 2,833 |
| `a` | 2,832 |
| `li` | 1,082 |
| `ol` | 138 |

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

The toggle is an `<a>` with an `href` that works without JS (see §4), `aria-expanded`,
and a `data-toggle="<pk>"` hook for JS.

#### 2. Open state travels with the request

A single `open` parameter carries the set of open container pks. It appears as a query
parameter on GETs and as a form field on fragment POSTs.

Rules:

- **Absent** → seed from the session (§3). This is what a fresh visit does.
- **Present, including empty (`open=`)** → use it verbatim. The empty case matters: it is
  how "I collapsed the last open scope" is expressed, and without the
  absent-vs-empty distinction the next request would silently re-seed from the session.
- `open=all` → every container open. A sentinel rather than an enumeration, so expand-all
  does not build a multi-kilobyte query string.

Sanitisation in one helper, `_open_ids(request, course, cmap)`:

- read `request.POST["open"]` first, falling back to `request.GET["open"]`, so a JS
  request's live DOM state wins over whatever the markup was rendered with
- parse comma-separated ints, discarding anything non-numeric
- discard pks not present in `cmap` (not in this course)
- discard unit pks (a unit owns no scope)
- cap at 2,000 pks so a forged request cannot force an unbounded render

Every renderer of tree markup calls it and puts the result in the context:
`builder()`, `_render_scope()`, `_render_tree()`, `_builder_with_notice()`,
`_conflict_scope()`.

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

`node_panel` already fires whenever a row is focused. It records
`request.session["builder_last_node"][slug] = pk` (setting `request.session.modified`
explicitly, since it mutates a nested dict).

A builder GET with **no** `open` parameter derives `open_ids` from that node's ancestor
chain. A chain is at most part → chapter → section, so **at most 3 scopes open, as a hard
ceiling** — the "author opened fifty chapters, now every load is slow again" failure mode
cannot occur. Once `open` is present it wins, so two tabs on the same course do not fight
over shared state.

The session holds a pk only. It is a convenience, and losing it on logout is acceptable.

#### 4. No-JS parity

The builder's existing no-JS discipline is preserved:

- the toggle is a real link to the builder page with the recomputed `open` set — a
  template tag (`{% toggle_href %}`) builds the href, preserving `q` when present
- the no-JS mutation paths currently `redirect("courses:manage_builder", …)`; the redirect
  must carry the submitted `open` value, or every no-JS mutation would collapse the tree

#### 5. Expanding a scope

A new GET endpoint `manage_node_scope` (`…/build/node/<pk>/scope/`) returns
`_render_scope(request, course, pk)` for the JS path, behind `_require_manage` like every
other node endpoint. `_render_scope` already exists and is already the fragment contract
used by every mutation; this exposes it for reads.

`builder.js` gains a delegated click handler on `[data-toggle]`:

- collapsed → show an inline pending state on the toggle, fetch the scope with
  `open` = current set + this pk, insert the returned `<ol>` into the row, set
  `aria-expanded="true"`
- expanded → remove the child `<ol>` from the DOM and set `aria-expanded="false"`
  (no request; the client owns collapse)

Every existing fragment request gains `open` collected from the live DOM
(`root.querySelectorAll('ol.tree__scope[data-scope]')` → `data-scope` values, excluding
`"top"`). One helper, called from the submit handler and the drop handler.

#### 6. Drag handler

Two changes, both small, both independent of the above:

- `clearDropMarks()` stops scanning the whole document. Track the currently marked scope
  and the injected line in module-scoped variables — the file already does exactly this
  for `movingPk`/`clearMoving()`.
- `dragover` is throttled to one `requestAnimationFrame`, so at most one forced layout
  happens per frame instead of one per pointer event. The handler still calls
  `e.preventDefault()` synchronously on every event (dropping that would disable the drop
  target); only the marker work is deferred.

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

#### 8. Busy affordance

One mechanism, reused everywhere: while a tree-pane fragment request is in flight, set a
busy state on the tree pane, styled in `builder.css`. Toggles additionally get an inline
pending state so it is obvious *which* row is loading. This is the "course loading"
feedback asked for, and it is what makes expand-all honest.

### Slice 2 — filter and expand-all (PR 2)

#### 9. Filter box

A `q` parameter on the builder view:

- one query: `ContentNode.objects.filter(course=course, title__icontains=q)`
- compute the union of the matches' ancestor chains from `cmap`
- render with those chains open

The filtering itself needs **no template change**: the view builds a `children_map`
restricted to matches plus their ancestors, and `_scope.html` renders what it is given.
Results are capped (200) with a "showing first N of M" notice, so a one-letter query
cannot rebuild the whole tree.

When `q` is present it dictates what is open and `open` is ignored. One rule, stated in
the code.

Without JS it is a plain GET form. With JS it swaps the tree pane.

#### 10. Expand-all

A control that requests `open=all`, behind the busy affordance from §8. On `mat-pp` it
will still take seconds — that is inherent, and it is now an explicit, clearly-signalled
choice rather than the default on every visit.

## Testing

Per the repo's practice, tests are written to fail first, and a test that cannot go red is
treated as not written. See `falsify-tests-not-run-them`.

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
- sanitisation: foreign pks, unit pks and junk are discarded
- POST-before-GET precedence: an `open` in the body wins over one in the action's query
  string
- adding a container returns it already open; adding a unit does not change the open set
- a collapsed container with zero children still renders a toggle, and expanding it
  yields the empty scope plus its add affordance

**e2e (`-m e2e`, mandatory marker or the tests are silently deselected).**

- expand and collapse a scope
- drag across two separately-opened branches — driving the real gesture, never
  `page.evaluate`
- no-JS toggle link preserves the open set through a mutation redirect

**Manual, before the PR.** Re-run the exact probes used to produce the baseline above
(page timing + DOM count, dragover micro-benchmark, full-tree fetch) and record the
after-numbers in the PR against the before-numbers in this spec.

## Success criteria

| Metric | Before (measured) | Target |
| --- | --- | --- |
| builder `domInteractive` on `mat-pp` | 8.37 s | < 1.5 s |
| builder response size | 3.0 MB | < 300 KB |
| DOM elements on load | 38,418 | < 3,000 |
| reparent round trip | 4.47 s | < 500 ms |
| forced layout per `dragover` | 14.4 ms | ≤ 1 per frame |

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
