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
and the reorder form action in `_move_buttons.html:2`) and `manage_node_delete` are
per-course constants reversed once per row; `manage_node_duplicate` is the same but reversed
once per **unit** row only (807, not 944 — `_tree_node.html:33` guards it with
`{% if node.kind == "unit" %}`). `manage_node_panel`
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
- `aria-controls="<id of the child ol>"` — **emitted only in the expanded state**. When
  collapsed the child `<ol>` is not rendered at all, and `aria-controls` pointing at a
  missing id is invalid ARIA that screen readers treat as no relationship, i.e. worse than
  omitting it. The id lives on `_scope.html`'s root `<ol>` (format `tree-scope-<scope_id>`,
  so the top scope is `tree-scope-top`), which means the lazily fetched fragment carries it
  without any extra work.

It uses a new chevron symbol in `_icon_sprite.html`, following the monochrome
`currentColor` SVG convention (never emoji), rotated by CSS between states rather than
swapped for a second symbol. `builder.css` gains its sizing, focus ring and hover states;
a leaf (unit) row renders a same-width empty spacer so titles stay aligned with their
container siblings.

**It adds a focus stop, and a load-bearing comment describes the old sequence.**
`builder.js:298-301` reasons about the panel-fetch debounce from the exact tab order
("Tab goes title -> ~6 cluster controls -> next title"). The toggle makes that
"toggle -> title -> ~6 cluster controls", and it is a focus stop that is *not* a
`.tree__title`, so it consumes a `focusin` and clears the timer. Behaviour stays correct, but
the comment must be updated or it documents a sequence that no longer exists — and the test
list keeps its assertion that keyboard traversal across rows still issues exactly one panel
fetch.

**Focus and panel behaviour on collapse.** Collapsing a subtree can remove the focused
element and can hide the node the detail panel is currently showing. On collapse: if
`document.activeElement` is inside the removed subtree, move focus to the toggle that was
just activated; leave the panel content alone (it stays valid — the node still exists, it
is merely not visible), which matches the existing rule that reordering and dragging leave
the panel unchanged.

**Collapsing hides the add affordance — an accepted behaviour change.** `_add_affordance.html`
is rendered by `_scope.html:12`, so suppressing the child `<ol>` also removes that
container's "+ Chapter / + Unit" row. An author must expand a container before adding into
it. This is accepted (it mirrors the collapsed-drop-target change in §6, and adding into
something you cannot see is a dubious gesture anyway), and `test_manage_affordance.py` must
be updated to assert it — it encodes a real change, not merely a fixture that needs
expanding.

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

**The `all` sentinel.** `open=all` means "every container", so expand-all and the §3a
small-course default need not ship an enumeration. `_open_ids` resolves it to a concrete
`set[int]` before returning, so no template ever has to understand the sentinel and the
template condition stays a plain membership test.

The server **emits** `all` whenever the effective open set is exactly the full container
set, and an enumeration otherwise. There is deliberately **no `closed=` exclusion list**: an
earlier draft paired `all` with `closed` so the sentinel could survive a collapse, but that
required a client-side carrier for a flag `applyFragment` would destroy, and it contradicted
the JS collector, which can only ever produce an enumeration. Collapsing one scope under
`all` simply switches the encoding to an enumeration. On `mat-pp` that is 136 pks ≈ 680
bytes — see the transport budget below for why that is affordable.

**Helper contract.** `_open_ids(request, course, cmap, *, seed=False) -> set[int]`. `course`
is required, not redundant: the seed path looks the session entry up by **slug**, and a
`parent_id -> [nodes]` map carries no slug — recovering it via `node.course.slug` costs a
query and is impossible on an empty course, which is exactly the first-visit case §3a
exists for. `seed` selects the row of the table above. It:

- tests **presence** with `"open" in request.POST` / `in request.GET`, not `.get()`.
  `.get()` returns `""` for both absent and explicitly-empty and `""` is falsy, so the
  obvious implementation collapses the two cases and re-seeds from the session the moment
  the author collapses the last scope — the exact bug the absent-vs-empty rule exists to
  prevent. POST presence takes precedence over GET presence, so a JS request's live DOM
  state wins over whatever the markup was rendered with.
- parses comma-separated ints, discarding anything non-numeric
- discards pks that are not containers of **this** course. The membership test is against an
  index of every node by pk, built from the same single query as `cmap` — **not** `pk in
  cmap`. `_children_map` (`views_manage.py:129-134`) only creates a key for a parent that
  *has* children, so `pk in cmap` would discard every childless container and make the
  spec's own "collapsed container with zero children" case unreachable. The same index
  supplies each node's kind for the next rule.
- discards unit pks (a unit owns no scope)
- resolves `all` into the concrete container set
- applies **one ceiling of 500 pks after resolution**, so it also bounds the `all` case.
  Over the ceiling it keeps the **500 lowest pks** — a set has no truncation order, so this
  is pinned to make the outcome reproducible across runs — and the page render carries a
  notice saying so.

**Where informational notices go.** Two messages need a channel — this truncation notice and
§9's "showing first 100 of M" — and a scope fragment cannot carry either: it is a bare `<ol>`
that `applyFragment` consumes via `firstElementChild`, and a multi-element response is
deliberately avoided (see Known traps).

- **Page render:** `builder()` gains an `info` context variable rendered into a **dedicated
  slot above the tree**, distinct from the existing `notice`. `notice` renders as
  `<div class="op-error" role="alert">` (`builder.html:6`) — wrong on both counts here, since
  "we opened only the first 500 scopes" is informational rather than an error, and
  `role="alert"` interrupts screen readers. The new slot uses a neutral style and
  `role="status"`, and holds a *list*, so a truncation notice and a filter notice can coexist
  rather than one silently replacing the other.
- **Fragment responses:** the message rides in an `X-Builder-Info` response header, which the
  JS turns into an entry in the same slot. This keeps the fragment body single-element.

Truncation on a fragment is therefore reported, not silent — which matters because §9's filter
swaps the tree pane via a fragment, and the cap notice is the only signal that the view is
incomplete.

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
`_builder_with_notice()` (both `seed=True`, both passing `course`), and `_render_scope()`
(`seed=False`).
`_render_tree()` and `_conflict_scope()` both delegate to `_render_scope()` and inherit it —
computing it in them too would evaluate the set twice per request and give the rules two
places to drift apart.

**Transport — and why form actions carry nothing.** An earlier draft put the `open` query
string on every form action and href. Hoisting removes the *reversal* cost but not the
*byte* cost: the string is emitted into ~6 URLs per row, so on `mat-pp` under expand-all
that is 6 × 944 × ~685 bytes ≈ **3.9 MB of query strings added to a page this spec exists to
shrink**, and ~675 KB on a 150-node course. The transport is therefore:

| Path | Carrier |
| --- | --- |
| JS — any fragment request | `open` appended to the `FormData` / query by the collector in §5. Nothing in the markup is involved. |
| JS — surviving a reload | `history.replaceState` writes the recomputed `open` into the address bar on every toggle (§5). Without it, F5 discards the author's expansions. |
| No-JS — expanding | The toggle's own `href`, the **only** markup that carries an enumeration: one per container row, not one per URL per row. |
| No-JS — mutations | Nothing on the form. `builder()` persists the effective open set to `session["builder_open"][slug]` on each page GET; the post-mutation redirect becomes `manage_builder?open=session`, and only that explicit sentinel reads it back. |

**Form actions — rename, add, reorder, duplicate, delete, move — carry no `open` at all.**
This matters beyond bytes: `rename_url` (`_scope.html:5`) and the add form's action
(`_add_affordance.html:7`) are not in §7's hoist list, so a draft that relied on form
actions would have silently broken no-JS rename and add — the two most common authoring
actions.

**`open=session` is a sentinel, not a general restore — and that resolves the clash between
the two session keys.** There are two: `builder_open` (a set, this transport) and
`builder_last_node` (a pk, §3's seed). `builder()` cannot tell a post-mutation redirect from
a bookmark, an F5 or the editor back-link — all are `open`-less GETs — so without an explicit
marker the two keys would give two different answers to the same input, and `builder_open`
would silently override §3's ≤4-scope ceiling, reviving exactly the "author opened fifty
chapters, now every load is slow again" case the ceiling exists to prevent. The sentinel
makes it explicit: **only a no-JS mutation redirect carries `open=session`**, so only it
reads `builder_open`. Every other `open`-less GET falls through to §3/§3a.

**Full precedence for a page GET**, stated once so it cannot drift:

1. `open=session` → `session["builder_open"][slug]` (no-JS post-mutation only)
2. `open` present otherwise (including empty) → parse it per the rules above
3. `q` present → the filter's ancestor chains (§9)
4. course has ≤ 150 nodes → all containers (§3a)
5. `session["builder_last_node"][slug]` → that node's chain, ceiling 4 (§3)
6. otherwise → empty

`builder_open` carries the same 500-pk ceiling as any other open set, is bounded to the same
20 slugs as `builder_last_node`, and `builder()` **skips the write when the set is
unchanged** — without that it would be an unconditional DB-session save on every builder page
load, carrying a payload up to two orders of magnitude larger than the pk dict §3 bothered to
bound.

The session write for no-JS is a **fallback, not the model**: the JS path never emits
`open=session`, so two JS tabs still cannot fight. Two *no-JS* tabs on one course share
`builder_open` and will; that is accepted for the fallback path and stated here rather than
discovered later.

**Transport budget.** The enumeration appears only in toggle hrefs, so its cost is bounded
by |containers| × |open set| × ~5 bytes. On `mat-pp` after expand-all that is 137 × 680 ≈
94 KB against an already-multi-megabyte page. On the §3a small-course default the server
emits `all` (3 bytes), not an enumeration. The 500-pk ceiling below bounds the worst case.

**A newly added container opens itself.** `node_add` adds the new node's pk to the open set
it renders with when the created node is a container. Otherwise an author who adds a chapter
would have to expand it before they could add anything into it. **On the no-JS path there is
nothing to render** — `node_add` ends in a redirect (`views_manage.py:281`) — so it must
write the new pk into `session["builder_open"][slug]` before redirecting, or the rule would
fail for exactly the users who cannot expand cheaply.

**A reparent opens its destination.** Same reasoning, different trigger, and it is the more
dangerous case. The Move… picker offers *every* legal destination including collapsed ones,
and a reparent returns `_render_tree` rendered with the caller's open set — so moving a node
into a collapsed chapter makes the row **disappear with no marker, no notice and no way to
tell success from failure**. §6's acceptance argument for the drag case ("open both branches
and drag") does not apply here: the picker exists precisely so the author need not see both
ends. Therefore a reparent adds the destination scope's pk **and its ancestor chain** to the
open set it renders with, on both the picker and drag paths, and a test asserts the moved
node is visible in the response.

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
courses cannot grow the session payload without limit. The same bound applies to
`builder_open` (§2).

**A write must pop the slug before re-inserting it.** A dict preserves *insertion* order, and
re-assigning an existing key does **not** move it to the end — so without the pop, re-focusing
a row in a long-used course leaves that slug at its original position and it is evicted before
courses the author has not touched in weeks, which is the opposite of "most recent".

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

**Rule: if the course has at most 150 nodes, open everything (the server emits `open=all`);
otherwise fall back to the §3 session seed, and to nothing if that yields nothing.**
`cmap` is already loaded, so the node count is free.

**The size rule is checked BEFORE the session seed, not after.** Ordering it the other way
round — which an earlier draft did — defeats the whole section: `node_panel` stores a pk on
the very first row focus, so from the author's *second* visit onward a small course would
arrive with only the ≤4-scope chain open. The regression this section exists to prevent
would simply have been deferred by one visit. On a small course the seed is irrelevant:
everything is open, so the remembered node is visible anyway.

Neither rule applies when `open` is present — an explicit `open=` means the author collapsed
things deliberately. **`q` outranks the size rule**: on a small filtered course the filter's
chains decide what is open, so a filtered view shows the same thing whatever the course's
size. The single authority for all of this is the precedence list in §2; this section states
only the rule, not the ordering.

150 is chosen from the measured baseline: render cost is linear in rows, and 944 rows cost
3.14 s of template time, so 150 rows is ~500 ms of server render and ~5,600 elements. Note
that this **exceeds the "< 3,000 elements" success criterion below**, which is why that
criterion is scoped to `mat-pp` and a separate threshold-course row is stated: a 150-node
course is ~16% of `mat-pp`'s weight, an improvement on nothing but a large improvement on
where `mat-pp` is today, and it is the price of not regressing courses that are fine as
they are.

#### 4. No-JS parity

The builder's existing no-JS discipline is preserved:

- the toggle is a real link to the builder page with the recomputed `open` value, built by a
  `{% toggle_href %}` template tag
- the href ends with `#node-<pk>`, and rows gain a matching `id`. Without it, expanding a
  scope 300 rows down is a full page load that returns to the top of the document.
- the no-JS mutation paths keep their existing `redirect("courses:manage_builder", …)` and
  are **not** modified. The session carrier from §2 restores the tree on arrival.

**Every other route back to the builder is covered by the same carrier — deliberately.**
There are more of them than the obvious two, and requiring each to propagate an `open`
parameter would have been an unstated dependency on several unrelated subsystems:

| Return route | Template |
| --- | --- |
| editor back-link (the core authoring loop: open a unit, edit, return) | `editor/editor.html:60` |
| delete confirmation Cancel | `node_confirm_delete.html:12` |
| Move… picker | `_tree_node.html:30` → `_move_picker` |
| export preview, import, media manager | `export_preview.html:25`, `import_course.html:31`, `media/manager.html:12` |
| builder header `Import content` / `Export` | `builder.html:17-18` |

None of these templates or views changes. For a JS author the editor back-link is better
than covered: `builder()` receives no `open`, falls to the §3 seed, and the seed is the pk
`node_panel` stored when the author selected that very unit — so they land with its chain
open.

**`q` and toggles must not contradict each other.** An earlier draft had `{% toggle_href %}`
preserve `q` while §9 declared `open` ignored under a filter, which would have made every
toggle a no-op while filtering. The rule is: **`q` seeds the initial open set; an `open`
supplied alongside it wins.** So a toggle href under a filter carries both `q` and the
recomputed `open`, and expanding or collapsing works normally inside filtered results.

**Collapse forgets descendants — in both paths.** Choose the DOM's own semantics: collapsing
a part discards the open state of everything beneath it, so re-expanding it yields collapsed
children. With JS that is automatic (the subtree is removed, so the collector no longer sees
those scopes). `{% toggle_href %}` must match it explicitly by removing the toggled pk **and
every descendant pk**, rather than just the toggled pk — otherwise the same gesture produces
two different outcomes depending on whether JS is running.

**`{% toggle_href %}` must not become the new bottleneck, and the two cases differ.** Naively
it rebuilds the whole comma-joined open set per row — at the 500-pk ceiling that is 500 rows
× a ~3 KB string.

- **Expand href** (row currently collapsed): the open set plus one pk. Precompute the joined
  string once per render and splice the single pk in.
- **Collapse href** (row currently expanded): the open set minus this pk **and every open
  descendant pk** (per the rule above). This is *not* a single-pk splice, and under expand-all
  every one of `mat-pp`'s 137 container rows is in this case — so "splice one pk" alone would
  be wrong and a naive per-row subtree walk would reintroduce the per-row cost. Compute each
  container's open-descendant pk set **once per render, in a single bottom-up pass over
  `cmap`** (each node's set is the union of its children's sets plus its open children), then
  emit `open_joined` minus that set.

Emit the bare `all` when the resulting set is the full container set.

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

**The full-`cmap` rebuild per toggle is accepted, with its cost stated.** `_render_scope`
calls `_children_map(course)` — the whole-course query, measured at **89 ms on `mat-pp`** —
plus one `ContentNode` lookup, on *every* expand. Walking a 4-deep chain therefore costs
four full-course reads. It is accepted rather than optimised because it is one indexed query
against an already-loaded-per-request table, it keeps a single code path shared with every
mutation (a narrower query for the single-scope case would fork the fragment contract), and
89 ms sits well inside the < 300 ms toggle budget in the success criteria. If the budget is
missed in measurement, narrowing this query is the first thing to try.

**The endpoint URL is not hardcoded in JS.** `builder.js` never hardcodes a URL; the move
endpoint arrives as `data-node-move-url` on the `.builder` root (`builder.html:9`). Add
`data-node-scope-url` the same way. A literal path in the JS would break under any
URL-prefix or i18n-prefix change.

Client-side pk substitution has **no existing precedent to copy** — `builder.html:8`'s
`data-panel-url` is currently unused (`builder.js:301` reads the per-input attribute), and
`data-node-move-url` has no pk in it. So the rule must be stated rather than inferred, and
the naive form is unsafe: the reversed URL is `/manage/courses/<slug>/build/node/0/scope/`,
and a slug containing `0` makes a plain `replace("0", pk)` wrong.

A string placeholder is **not** an option, and this was measured rather than assumed: the
routes are declared `<int:pk>` (`courses/urls.py:163`), whose converter regex is `[0-9]+`,
and `reverse()` validates the generated path against it. Reversing with `pk='__PK__'` raises

```
NoReverseMatch: Reverse for 'manage_node_panel' with keyword arguments
{'slug': 'mat-pp', 'pk': '__PK__'} not found. 1 pattern(s) tried:
['manage/courses/(?P<slug>[-a-zA-Z0-9_]+)/build/node/(?P<pk>[0-9]+)/\\Z']
```

**Rule: reverse with `pk=0`, and substitute with an `$`-anchored replacement of the final
path segment** — `url.replace(/\/0\/$/, '/' + pk + '/')` for the panel URL, and
`url.replace(/\/0\/scope\/$/, '/' + pk + '/scope/')` for the scope URL. Anchoring at the end
makes a `0` inside the slug unmatchable, and an i18n or script prefix only prepends, so it
cannot affect the match. The same rule applies to the `manage_node_panel` hoist in §7, and
a unit test asserts the substitution against a slug containing a `0`.

`builder.js` gains a delegated click handler on `[data-toggle]`. It calls
`e.preventDefault()` first — the toggle is an `<a href>`, and without it the fetch races a
full page navigation (every other delegated link handler in the file does this; see
`builder.js:245` for `[data-move]`). Then:

- collapsed → mark the toggle in-flight, show its pending state, fetch the scope with
  `open` = current set + this pk, insert the returned `<ol>`, set `aria-expanded="true"`
  **and add `aria-controls="tree-scope-<pk>"`**, clear the in-flight mark
- expanded → remove the child `<ol>` from the DOM, set `aria-expanded="false"` **and remove
  `aria-controls`** (no request; the client owns collapse)

The `aria-controls` add/remove is not optional bookkeeping: §1 makes "emitted only when
expanded" load-bearing, so a handler that touches only `aria-expanded` violates the invariant
after every toggle, in one direction or the other. The toggle test asserts both attributes.

**The in-flight mark is required, and the insert must replace.** Unlike `applyFragment` —
which is idempotent because it *swaps* the element matching `data-scope` — this handler
inserts. Two clicks before the first response lands would produce two sibling
`<ol data-scope="pk">` elements, after which `:scope > ol.tree__scope` (`builder.js:155`,
`:442`) picks an arbitrary one and the DOM collector reports the pk twice. So: ignore repeat
activations while in flight (reuse the `dataset.submitting` convention already in the file),
and have the insert replace any existing `:scope > ol.tree__scope` rather than append
blindly.

**Every toggle calls `history.replaceState`** with the recomputed `open` (and `q`, if
active), so a reload or a Back navigation re-enters `builder()` with the author's expansions
intact instead of falling back to the seed. It also means the JS path keeps `open` in the
URL, which is what makes the "two tabs do not fight" claim in §2 true for JS authors.

**The empty set is written as `open=`, present-but-empty — never omitted.** This applies to
both `replaceState` and the collector. Dropping the parameter when the author collapses the
last scope would make the next page GET see `open` as *absent*, springing the tree back open
from the seed — §2's absent-vs-empty distinction defeated on the JS path, by the very
mechanism added to preserve state.

**A collapse must not commit a half-typed rename.** The rename `focusout` handler
(`builder.js:365-393`) bails only on `swapping || !form.isConnected`, and `swapping` is set
exclusively inside `applyFragment`. A collapse removes the subtree by a different route, and
per this repo's recorded trap Chromium delivers `focusout` from inside the removal with
`isConnected` still **true** — so collapsing over a dirty title would fire a real rename POST
whose `applyRename` then no-ops on a detached form, leaving the tree showing the old title
and the database holding the new one. Moving focus to the toggle (§1) fires the same event.
**Decision: a collapse abandons a pending rename**, consistent with what a scope swap already
does. The collapse must therefore set the `swapping` flag (or an equivalent guard) around the
`<ol>` removal *and* around the focus move.

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
`"top"`). One helper, called from the submit handler and the drop handler. **The collector
always emits an enumeration** — it can only observe what is in the DOM, and `all` originates
solely from the server (the §3a default) and the expand-all control (§10).

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

  **`drop` FLUSHES the pending frame; `dragend` cancels it.** This distinction is
  load-bearing and a cancel-in-both-handlers rule would be a silent bug. `drag.targetScope`,
  `scope.dataset.dropIndex/dropParent/dropToken` and the `.drop-target` class are all set in
  the *deferred* part (`builder.js:457-466`), and the `drop` handler bails when
  `!scope || !scope.classList.contains("drop-target")` (`builder.js:471`). So if the author
  releases within the same frame as the first `dragover` over a scope, cancelling the pending
  frame leaves `targetScope` null or pointing at the *previous* scope — and the gesture is
  dropped with no marker, no error and no request, after `preventDefault()` has already told
  the browser the drop was legal. Therefore:

  - `drop` runs the pending callback synchronously first, then cancels the scheduled frame,
    and only then reads `targetScope`
  - `dragend` cancels outright (the gesture was abandoned; there is nothing to commit)
  - the callback returns early if `drag` is null, covering a frame that outlives either path

  An e2e must drag and release **within a single pointer move**, or this case is untested.

  **Cancellation is still required in both.** A frame scheduled by the last `dragover` that
  ran after `drag = null` would dereference a null `drag` inside `targetFor` and re-insert a
  `.drop-line` into a tree `applyFragment` has just swapped — a stray marker with no drag in
  progress. Store the pending frame id module-scoped.

  **The rejecting branches must cancel too.** `builder.js:454` handles an illegal target
  synchronously with `clearDropMarks(); drag.targetScope = null; return;`, and there is an
  earlier `if (!scope) return;`. Under throttling a frame scheduled by the *previous, legal*
  `dragover` still runs after that return — re-adding `.drop-target` and a `.drop-line` on a
  target just rejected, and re-setting `drag.targetScope`, so a drop there would post an
  illegal move the browser had been told was legal. Both rejecting branches cancel any
  pending frame before returning.

  **The callback reads the LATEST event, not the one that scheduled it.** `targetFor` needs a
  `clientY` and a resolved scope, and closing over the scheduling event would leave the marker
  up to a frame stale — which is symptom 2, reintroduced by its own fix. The handler stores
  the latest `clientY` and resolved `scope` in module-scoped variables on **every** event, and
  the single scheduled callback reads those.

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
every row that carries them (`manage_node_duplicate` on unit rows only — 807 of 944).
Reverse them once per scope and pass them down, exactly as `_scope.html`
already does for `rename_url` (and keep the same explanatory comment style). ~30% of
render time for a mechanical change, and it benefits every scope render including
expand-all.

Two sites are easy to miss:

- **`_move_buttons.html:2`** reverses `manage_node_move` as the reorder form's action —
  `manage_node_move` is reversed *twice* per row, here and at `_tree_node.html:30`. This
  template must stop calling `{% url %}` itself. Note that `_tree_node.html:29` includes it
  **without `only`**, so a `{% url … as move_url %}` set in `_scope.html` is already visible
  inside it; passing it explicitly in the `with` arguments is a consistency choice matching
  `rename_url`, not a correctness requirement.
- **`manage_node_panel`** (`_tree_node.html:24`) is read only by JS (`builder.js:301`), so
  hoist it to the root and have the JS substitute via the `pk=0` + `$`-anchored replacement
  rule in §5 — another ~944 reversals. (`builder.html:8` carries a `pk=0` form of this URL
  today, but it is **unused**, so it is a starting point, not a working precedent.) Only
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
while the counter is above zero.

`builder.js` issues two GETs into the detail panel, and **neither counts** toward the tree
pane's busy state: `loadPanel` (`builder.js:277`, the debounced focus fetch — it fires on
mere keyboard traversal, so counting it would flicker the tree during ordinary navigation)
and the `[data-move]` picker fetch (`builder.js:247`, which also ends in `setPanel`). Every
fetch that mutates or fetches *tree* markup — toggle, submit, drop, filter, expand-all —
does count.

### Slice 2 — filter and expand-all (PR 2)

#### 9. Filter box

A `q` parameter on the builder view. There is **one** mechanism, not two: `q` restricts
`children_map`, and everything else is a consequence of that.

- **still one query in total.** The matches' ancestors are by definition not in a
  `title__icontains` queryset, and a match carries only `parent_id`, not the parent object —
  so the ancestors cannot come from a second filter without either a full node load or one
  query per level. The mechanism is: load the full `cmap` (the single query the builder
  already issues), select the matches from it in memory, then walk `parent_id` upward. No
  extra query, and the earlier draft's "one query: `ContentNode.objects.filter(...)`" was
  incompatible with the restricted-map requirement in the same paragraph.
- matches are capped at the **first 100 in `("order", "pk")` order**, with a "showing first
  100 of M" notice. That ordering is deterministic but is **not** tree order — `order` is a
  sibling-local index, so a course-wide sort interleaves nodes from unrelated parents.
  Determinism is what the cap needs; tree order is not claimed. 100 rather than 200 because
  each match drags in up to 3 ancestors, and 100 × 4 = 400 sits under §2's 500-pk ceiling.
- the view derives a restricted `children_map` from the match set plus the walked ancestors;
  `_scope.html` renders whatever `cmap` it is given, so **no template change is needed for
  the filtering itself**. `top_nodes` (which `builder.html:22` renders from) must be
  restricted the same way, or the top level renders unfiltered under a filter.
- the open set is the consequence: the union of the matches' ancestor chains, so every
  match is actually visible. Toggles still work on top of it (§4) — `q` seeds, a supplied
  `open` wins.
- **`q` travels with EVERY fragment request, not just the toggle.** `manage_node_scope` is
  only one caller of `_render_scope`: under an active filter, a rename 409 (`_conflict_scope`),
  an add, a duplicate, a reorder and a drop (`_render_tree`) all return the same markup, and
  none of them would receive `q` — so the failure diagnosed for the toggle (unfiltered
  children arriving inside a filtered tree; a drop replacing the whole filtered pane with the
  unfiltered tree) would still happen on every mutation. Therefore: the §5 collector appends
  **`q` alongside `open`** on every fragment request; `_render_scope` and `_render_tree`
  honour `q` on **all** paths; and `history.replaceState` preserves `q` as well as `open`.
- **Which `cmap` `_open_ids` receives under a filter:** always the **full** map. Its
  sanitisation rule is "is this a container of this course", not "is this in the filtered
  view" — passing the restricted map would silently discard a legitimately-open pk that the
  filter happens to exclude, and the author would lose that expansion on clearing the filter.
  Both maps derive from the one queryset, so the "one query in total" claim holds; the
  restricted map is a derived structure, not a second query.

**Counts under a filter show the filtered count**, matching the restricted `cmap` the rows
are rendered from, so a toggle never promises children the filtered view will not show. The
notice makes it clear the view is filtered.

Without JS it is a plain GET form. With JS it swaps the tree pane.

#### 10. Expand-all

A control that requests `open=all`, behind the busy affordance from §8. On `mat-pp` it
will still take seconds — that is inherent, and it is now an explicit, clearly-signalled
choice rather than the default on every visit.

**Above the 500-pk ceiling the control is disabled**, with a tooltip saying the course is
too large to expand at once, rather than silently expanding 500 arbitrary scopes behind a
truncation notice. No course in the corpus is close — `mat-pp`, the largest, has 137
containers — so this is a guard, not a limitation anyone will meet.

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
`test_e2e_builder_reorder.py`, `test_e2e_builder_tree_layout.py`,
`test_e2e_inline_rename.py`, `test_manage_duplicate_button.py`, `test_tree_badge.py:108`,
`test_e2e_transfer.py:175` (waits on `[data-scope="{part.pk}"]` after an import) and
`test_seed_demo_course.py:82`.

**That list is a starting point, not the enumeration.** Regenerate it by grepping `tests/`
for `manage_builder`, `/build/`, `data-scope` and `tree__row` — a file-name prefix is not a
reliable filter, and four of the files above were missed by one.

The migration must be **enumerated file by file before implementation starts**, and it must
use a shared helper rather than per-test edits, so the rule stays in one place:

- **Python/view tests:** a helper that appends `?open=<all container pks>` (or `open=all`)
  to the builder GET.
- **e2e tests:** a fixture helper `expand_to(page, node)` that clicks the toggles down the
  chain and waits for each scope — driving the real control, never `page.evaluate`, per
  `e2e-must-drive-real-ui`.

Two structural guards over the files this design edits most are **not** fixture problems and
need their own attention:

- `tests/test_builder_js_invariants.py` — regexes **raw `builder.js` source**, asserting
  `panel.innerHTML` is assigned in exactly one place and that `setPanel` resets `scrollTop`.
  New fetch/toggle code, and even prose in comments, can trip it (see this repo's
  `comments-can-fail-tests` lesson). The new toggle fetch must not introduce a second
  `panel.innerHTML` write, and any comment mentioning it will redden the suite.
- `tests/test_builder_styles.py` — CSS-shape assertions on `.tree__*`, which the new toggle
  column sits beside.

**Committed help screenshots go stale.** `tests/capture_help_screenshots.py` shoots
`manage_builder` on `demo-course` into `core/static/core/img/help/builder-tree.en.png` and
`builder-tree.pl.png`, which ship in the help system. This change adds a disclosure column to
every row and may collapse the tree, so both must be re-captured as a work item — otherwise
the PR ships help pages depicting a UI that no longer exists. Record `demo-course`'s node
count in the PR: it determines whether the new shot shows an expanded or a collapsed tree,
and therefore what the help text around it should say.

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
  scope is still open, and that the request switched to an enumeration
- **collapse forgets descendants identically in both paths**: expand a part and a chapter
  within it, collapse the part, re-expand it, and assert the chapter is collapsed — asserted
  once through the JS toggle and once through the no-JS `{% toggle_href %}` link
- the 500-pk ceiling keeps the 500 lowest pks (a pinned, reproducible outcome) and the page
  render carries a notice; a fragment response truncates silently
- **the toggle is idempotent under double-activation**: two rapid clicks yield exactly one
  `:scope > ol.tree__scope`
- **a collapse over a dirty rename input posts nothing** (the `swapping`-equivalent guard)
- **the full precedence list in §2**, one case per row of it, including that a plain
  `open`-less GET does NOT read `builder_open` and only `open=session` does
- **a reparent into a collapsed destination returns the moved node visible** — via the Move
  picker as well as via drag
- **the `pk=0` substitution** against a slug containing a `0`, asserting the `$`-anchored
  replacement targets the final segment
- **the empty set survives a round trip**: collapse the last scope, reload, and assert the
  tree is still empty rather than re-seeded (i.e. `open=` was emitted, not omitted)
- **`q` rides on every fragment request**: with a filter active, a rename 409, an add, a
  reorder, a duplicate and a drop each return filtered markup
- **keyboard traversal still issues exactly one panel fetch** despite the new focus stop
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
- **drag and release within a single pointer move**, covering the `drop`-flushes-the-frame
  case in §6 that a cancel-only rule would silently break
- no-JS mutation preserves the open set via the session carrier (§2)
- a reload after expanding several scopes preserves them (`history.replaceState`)
- slice 2: expand a scope while `q` is active and assert only matching/ancestor rows return

**Manual, before the PR.** Re-run the exact probes used to produce the baseline above
(page timing + DOM count, dragover micro-benchmark, full-tree fetch) and record the
after-numbers in the PR against the before-numbers in this spec.

## Success criteria

All slice-1 targets are **on `mat-pp`** unless stated otherwise. A course at the §3a
threshold arrives fully expanded by design and therefore has its own, looser row — the
alternative would be to collapse small courses, which §3a rejects.

| Slice | Metric | Before (measured) | Target |
| --- | --- | --- | --- |
| 1 | builder `domInteractive` on `mat-pp` | 8.37 s | < 1.5 s |
| 1 | builder response size on `mat-pp` | 3.0 MB | < 300 KB |
| 1 | DOM elements on load, `mat-pp` | 38,418 | < 3,000 |
| 1 | reparent round trip | 4.47 s | < 500 ms |
| 1 | forced layout per `dragover` | 14.4 ms | ≤ 1 per frame |
| 1 | toggle (expand one scope) round trip | n/a — new primary interaction | < 300 ms |
| 1 | a 150-node course (the §3a threshold) | unchanged today | still fully expanded; `domInteractive` < 1.5 s; ~5,600 elements accepted |
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
