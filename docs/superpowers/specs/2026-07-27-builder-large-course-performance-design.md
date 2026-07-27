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
once per **unit** row only (807, not 944 — `_tree_node.html:32` guards it with
`{% if node.kind == "unit" %}`). `manage_node_panel`
does vary by pk, but it is read only by JS (`builder.js:301`) and `builder.html:8` already
carries a `pk=0` template of the same URL on the `.builder` root — so it is hoistable by a
precedent already in the file. That leaves **4,583** redundant reversals of 5,803 (79%) —
move ×2 (1,888) + delete (944) + panel (944) + duplicate (807).
`_scope.html` already hoists `manage_node_rename` this way and records the reason in a
comment.

### DOM weight

The total below is a browser count of the **real** response (`document.getElementsByTagName('*')`,
CSRF inputs included). The per-tag table is from an offline render of the same template
**without** a request context, so `{% csrf_token %}` emitted nothing and the table
**excludes the 2,833 CSRF hidden inputs**. Re-measure the same two ways after the change or
the numbers will not be comparable.

- Browser, real response: **38,418 elements** → **40.7 elements per row**
- Offline render, no CSRF: **35,388 open tags** → **37.5 per row**

**Scope widths** (needed to bound what the §3 seed can open): the widest scope is the top
level at **21**, then two chapters at **19**; the mean container holds **6.7** children. A
worst-case 4-deep seeded chain is therefore 21 + 19 + 19 + 19 = **78 rows**, and `mat-pp` has
only 5 sections so depth-4 chains are rare; the common case is 21 + 19 + 19 ≈ 59 rows.

**The 40.7/row basis is PRE-change and must not be used for the acceptance targets as-is.**
§1 adds a toggle (`<a>` + `<svg>` + `<use>` = 3) to every container row and a spacer (1) to
every leaf row, i.e. **+3 to +4 elements per row, ~+8%** → a post-change basis of **~44/row**.
Derived targets below use 44, not 40.7; using the pre-change figure would invite exactly the
"false failure at review time" this section warns about for the CSRF basis. The implementer
re-measures the real post-change per-row figure and records it in the PR.

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

> **Reading note.** The rules are what you implement; the *"an earlier draft…"* passages
> scattered through §2–§9 record designs that were tried and disproved, several of them
> empirically. They are kept because re-deriving them costs review rounds — but they are
> rationale, not requirements. If you are implementing, read the tables, the numbered
> precedence list, the helper contracts and the bolded rules; skip the rest on a first pass.
> Two stale sentences survived several rounds precisely because surrounding rationale buried
> them, so treat any conflict between a table and a paragraph as a bug worth reporting: the
> **table wins**.

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
explicitly defers (see Out of scope).

**The count is NOT visible text; it lives in the toggle's accessible name.** A visible count
would make the toggle's width vary with the number, defeating the fixed-width alignment column
described below, and a chevron plus a bare "3" gives a screen reader a link named "3" with no
subject. So the toggle renders the chevron only, in a fixed-width column, and carries
`aria-label` built with `{% blocktrans count %}` including the node title — "Expand Chapter 4,
3 items" / "Collapse Chapter 4, 3 items". `{% blocktrans count %}` rather than a `{% trans %}`
with an interpolated number because Polish has three plural forms and this is the single
most-repeated new string on the page.

**The server renders BOTH finished labels, as `data-label-expand` and `data-label-collapse`,
and the JS only swaps between them.** This is forced by the plural argument above: the JS
cannot build the opposite-state label from a `data-msg-*` template plus a count, because
selecting a Polish plural form is exactly what JS cannot do — so the `data-msg-*` convention
used everywhere else in this design does not work here. Both attributes are produced by
`{% blocktrans count %}` at render time. A Polish-locale test asserts both are present and
correctly pluralised for counts 1, 2 and 5 (the three forms).

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
| `builder()` | seed from session (§3) | empty set | that set | all containers |
| `_builder_with_notice()` | **reads `builder_open` directly** (see below) | empty set | that set | all containers |
| `_render_scope()` (all fragment paths) | **empty set — never seeds *from the session*.** Step 3's `q` chains still apply. | empty set | that set | all containers |

**`_builder_with_notice()` is the one exception, and it needs to be.** It answers a *POST* —
a no-JS conflict or validation error — where `open` is absent from both POST and GET (forms
carry nothing) and `open=session` cannot appear (that sentinel is a GET-redirect marker). Left
to the §3 seed, a failed mutation would collapse the tree to the ≤4-scope chain while the
*successful* version of the same gesture restored the full set: same page, same gesture, two
different trees depending on outcome. Reading `builder_open` directly is safe here precisely
because it cannot be a bookmark — it is the same author, same tab, mid-loop. It also renders
`builder.html`, so it must be given the `info` variable alongside `notice`.

The absent-vs-empty distinction on the page views is load-bearing: `open=` is how "I
collapsed the last open scope" is expressed, and without it the next navigation would
spring the tree back open from the session.

**The `all` sentinel.** `open=all` means "every container", so expand-all and the §3a
small-course default need not ship an enumeration. `_open_ids` resolves it to a concrete
`set[int]` before returning, so no template ever has to understand the sentinel and the
template condition stays a plain membership test.

`all` is primarily an accepted **input** sentinel. As an *output* it appears only where a
toggle href's **resulting** set is the full container set — which is why a fully expanded
course emits enumerations everywhere (every one of its toggles is a collapse; see the
Transport budget). There is deliberately **no `closed=` exclusion list**: an
earlier draft paired `all` with `closed` so the sentinel could survive a collapse, but that
required a client-side carrier for a flag `applyFragment` would destroy, and it contradicted
the JS collector, which can only ever produce an enumeration. Collapsing one scope under
`all` simply switches the encoding to an enumeration. On `mat-pp` that is 136 pks ≈ 680
bytes — see the transport budget below for why that is affordable.

**Helper contract.**

```python
@dataclass(frozen=True)
class OpenSet:
    ids: frozenset[int]    # resolved, sanitised, ceiling-applied
    truncated: bool        # the ceiling bit; drives the notice

def _open_ids(request, course, cmap, *, mode="fragment", q_chain=None) -> OpenSet: ...
```

**`mode` is three-valued, not a boolean**, because the caller table has three distinct
behaviours for an absent `open` and a two-valued flag cannot express them — `builder()` and
`_builder_with_notice()` would both be `seed=True` while needing *different* answers:

| `mode` | Caller | Steps it runs | `open` absent |
| --- | --- | --- | --- |
| `"page"` | `builder()` | 1, 2, 3, 4, 5, 6 | precedence steps 3–6 |
| `"notice"` | `_builder_with_notice()` | 2, 3, 4, 5, 6 + a direct `builder_open` read | read `builder_open`, then fall through to 3–6 |
| `"fragment"` | `_render_scope()` | **2, 3, 6 only** | step 3's `q` chains when `q` is present, otherwise the empty set — never reads the session |

**`"fragment"` deliberately skips steps 1, 4 and 5.** Steps 1 and 5 are session reads, which a
fragment must never do. **Step 4 (≤150 nodes) is skipped too**, and that is easy to get wrong:
an implementer writing one precedence chain with mode guards only on the session steps would
apply step 4 in fragment mode, so on any small course every `open`-less fragment response
would render the whole tree open — contradicting the "empty set" cell and making the pinned
"a fragment POST with no `open` renders an empty open set" test unpassable on exactly the
small fixtures the Testing section says most fixtures are. The size default is a *landing*
rule for a page, not a rule about what a fragment re-render should contain.

**It must not return a bare `set`.** Truncation is detected *inside* this helper — it owns
the 500-pk ceiling — so a bare set gives no caller any way to learn it happened, and every
caller would have to re-parse the raw parameter to re-derive the flag, duplicating the parse
the helper exists to own. A pinned bare-set return would have made the truncation notice
silently unreachable.

`course` is required, not redundant: the seed path looks the session entry up by **slug**,
and a `parent_id -> [nodes]` map carries no slug — recovering it via `node.course.slug` costs
a query and is impossible on an empty course, which is exactly the first-visit case §3a
exists for. `q_chain` is the filter's ancestor-chain set (§9); **slice 1 always passes
`None`**, and it exists in the signature from the start so slice 2 does not have to retrofit
a precedence step across a function boundary. `mode` selects the row of the table above. It:

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
  slot above the tree**, distinct from the existing `notice`. **Each server-rendered entry
  carries its key in the markup (`data-info-key="filter"` / `"truncation"`), and the JS reads
  the existing slot on init** so replace-and-clear operate on server-rendered entries too.
  Without this the registry only knows about entries it inserted itself, and the path is
  routine rather than hypothetical: `history.replaceState` puts `q` in the address bar, so any
  reload while filtered is a page GET that renders a server-side "showing first 100 of M"
  entry; the next toggle re-asserts `filtered;…`, the JS finds nothing under key `filter` in
  its own registry, and appends a **second** copy. The pinned "two successive filter responses
  leave one entry" test must therefore start from a `?q=` page load, or it passes vacuously
  against exactly this bug. `notice` renders as
  `<div class="op-error" role="alert">` (`builder.html:6`) — wrong on both counts here, since
  "we opened only the first 500 scopes" is informational rather than an error, and
  `role="alert"` interrupts screen readers. The new slot uses a neutral style and
  `role="status"`, and holds a *list*, so a truncation notice and a filter notice can coexist
  rather than one silently replacing the other.
- **Fragment responses:** a **machine-readable** `X-Builder-Info` header — `truncated;limit=500`
  or `filtered;shown=100;total=940` — which the JS renders into the same slot using **two new**
  `data-msg-*` attributes added to the `.builder` root alongside the three that exist today
  (`data-msg-conflict`, `data-msg-illegal`, `data-msg-network`, `builder.html:10-12`):
  **`data-msg-truncated`** and **`data-msg-filtered`**, carrying `%(limit)s` / `%(shown)s` /
  `%(total)s` placeholders that the JS substitutes. This keeps the fragment body
  single-element.

  **These two escape §1's "JS cannot pluralise Polish" argument, and the wording must keep it
  that way.** `limit` is the constant 500, so `data-msg-truncated` is pre-pluralised in the
  catalog. `data-msg-filtered` must be phrased so **no varying numeral governs a noun** —
  "Filtrowane: 100 / 940" rather than "showing 100 results" — because the latter needs a plural
  form JS cannot select. Any future message with a varying count beside a noun uses §1's
  pre-render-both-forms trick instead of a placeholder.

  **The header must not carry the human string**, and this was measured rather than assumed.
  Django encodes response header values as latin-1 with `mime_encode=True`, so on this repo's
  Django 5.2.15:

  ```
  r['X-Builder-Info'] = 'Wyświetlono pierwsze 100 z 940 — widok jest niepełny'
  r['X-Builder-Info'] → '=?utf-8?q?Wy=C5=9Bwietlono_pierwsze_100_z_940_=E2=80=94_widok_jest_niepe=C5=82ny?='
  ```

  The JS would paste that literal token into a `role="status"` region. Every Polish message
  hits this, and so does any English one containing an em dash — i.e. it would fail exactly
  the users the notice exists for. Keeping the human strings in `data-msg-*` also matches the
  convention the file already uses for every other message.

**Slot lifecycle.** Each entry has a **key** (`truncation`, `filter`). **`_render_scope` sets
`X-Builder-Info` on every fragment response** — carrying the currently-applicable codes, or
absent when none apply — and an incoming header replaces the entry with the same key rather
than stacking. **A response with no header clears ALL keys — but only tree-pane responses
participate at all.**

The carve-out is the same one §8 makes for the busy counter, and for the same two fetches:
`loadPanel` (`builder.js:277`) and the `[data-move]` picker fetch (`builder.js:247`) never
touch `_render_scope`, so they never carry the header. Wiring header handling into a shared
response helper without this exclusion would clear the `filter` entry on the very next row
focus — within a second of filtering — silently removing the only signal that the view is
capped, which is the failure the clearing rule exists to prevent.

**Participation is defined by the response, not the gesture: only responses that return tree
markup through `_render_scope`/`_render_tree` participate** — the toggle, drop, `manage_tree`,
`manage_node_scope`, conflict scopes, and those mutations that re-render a scope (add,
reorder, duplicate, delete). Saying "submit" instead would be wrong, because three common
submit responses never reach `_render_scope`: a successful rename returns
`_rename_result.html` (`views_manage.py:349`), a 422 returns `_op_error.html` (`:283`, `:345`,
`:407`, `:490`), and a unit-settings rename returns `_render_unit_panel` (`:346`). Under a
gesture-based rule those would arrive header-less and **clear all keys** — deleting the filter
notice on the single most common authoring action. They neither set nor clear.

Consequently the "a filtered mutation re-asserts `filtered;…`" test must use a mutation that
actually re-renders a scope — add, reorder, duplicate or drop — **not** a rename, which has no
`_render_scope` call to re-assert it. ("Clears the keys it owns" would
be vacuous — a response with no header owns none — and under the opposite reading any
rename/add/reorder/drop issued while a filter is active would wipe the "showing first 100 of
M" entry while the tree on screen is still filtered and capped, silently removing the only
signal that the view is incomplete.) Because `_render_scope` re-asserts the codes, a filtered
mutation re-sends `filtered;…` and an unfiltered one legitimately clears it. The slot is
hidden when empty. Without this,
§9's filter would pile up a growing stack of contradictory counts as the author types, and
clearing the filter would leave the last one standing over an unfiltered tree.

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
`_builder_with_notice()` (`mode="page"` and `mode="notice"` respectively, both passing
`course`), and `_render_scope()` (`mode="fragment"`).
`_render_tree()` and `_conflict_scope()` both delegate to `_render_scope()` and inherit it —
computing it in them too would evaluate the set twice per request and give the rules two
places to drift apart.

**Views inject extra pks through a parameter, not by computing their own set.** Two rules
below require a view to force a scope open — a reparent must open its destination chain, and
`node_add` must open a newly created container. Neither view can do that through the request,
because the open set is computed inside `_render_scope`. So the fragment renderers grow one
keyword argument:

```python
def _render_scope(request, course, scope_ref, *, extra_open=()): ...
def _render_tree(request, course, status=200, *, extra_open=()): ...   # threads it through
```

**`q` is resolved inside `_render_scope`, not passed in.** An earlier draft had the view
compute `q_chain` and pass it to `_open_ids`, which works for `builder()` but leaves the
fragment paths with no channel at all — and `manage_tree`'s filter fetch is *required* to omit
`open` (§9), so with `mode="fragment"` yielding the empty set it would have rendered a tree
with **nothing open** and every match below the top level invisible. That would have made §9's
central promise, and its own test, unreachable.

So `_render_scope` reads `q` from the request and calls the single filter helper below,
passing the resulting chains to `_open_ids` as `q_chain`. Every fragment path — the six
mutation views, `_conflict_scope`, `manage_node_scope`, `manage_tree` — inherits filtered
behaviour without a new argument, which is also what makes "q rides on every fragment request"
true by construction rather than by six separate edits.

**One helper owns all filter derivation:**

```python
def _filtered_map(course, cmap, q) -> tuple[dict, set[int], int, int]:
    """restricted cmap, ancestor-chain ids, shown, total. Returns (cmap, set(), 0, 0) when q is blank."""
```

`_render_scope` calls it; `builder()` and `_builder_with_notice()` obtain their restricted map
from the same call. **`top_nodes` is derived, not returned** — it is
`restricted_cmap.get(None, [])`, exactly as `builder()` already derives it from the unrestricted
map today, which is also why `extra_open`'s effect 2 needs no separate `top_nodes` step: a
top-level node is inserted under key `None`. Without a named owner, the match selection, the
ancestor walk, the 100-cap and the `top_nodes` restriction would be re-implemented in two or
three places — the drift the three-call-sites rule exists to prevent.

**`extra_open` has TWO effects, not one.** Opening a scope does not make a row appear if the
restricted `cmap` that `_scope.html` renders from does not list that node among its parent's
children — so an implementer who wires only the first effect satisfies the reparent test and
silently fails the add-under-filter test in §9:

1. **Union into the open-id set**, after the ceiling is applied, so a forced-open destination
   can never be the thing truncated away — producing a **new local set**, never mutating the
   returned object. **This effect applies the same kind filter `_open_ids` applies: unit pks
   are dropped.** Effect 1 bypasses `_open_ids`'s pipeline (it runs after the ceiling), so
   without restating the rule here a unit pk would leak into the emitted open set.
2. **When `q` is active, re-insert those pks' node objects into the restricted `cmap`** —
   resolved from the full `cmap` that `_render_scope` already holds — and into `top_nodes`
   when the node is top-level, since §9 restricts that separately. **This effect applies to
   every pk regardless of kind**, units included. Force-included rows **do not** count toward
   the 100-match cap or the `shown`/`total` figures, or the `X-Builder-Info` notice would stop
   matching the cap it describes.

**Three views pass it**, not two: `node_add`, `node_move` (reparent) and **`node_duplicate`**
— §9's force-inclusion rule and its "an add **or duplicate** under an active filter returns its
own new row visible" test both reach the duplicate path, and an implementer wiring only the
first two leaves duplicate-under-filter broken.

**Callers pass `extra_open` for EVERY created or moved pk, whatever its kind** — the two
effects then diverge on kind by themselves. Coupling the *caller's* decision to kind (an
earlier draft's "when the created node is a container") made two pinned tests mutually
unsatisfiable: a unit added under an active filter needs effect 2 or the row the author just
created does not come back (a nested add returns `_render_scope(…, _scope_ref(node.parent_id))`,
`views_manage.py:286`, and the new unit is absent from the restricted map), while passing that
same pk must not put a unit into the open set. Splitting the kind test across the two effects,
rather than at the call site, satisfies both. (`ids` is a `frozenset` for exactly this reason:
`frozen=True` blocks attribute rebinding but not mutation of a mutable field, so a plain
`set` would let `open_set.ids |= extra_open` silently mutate a supposedly frozen result, and
would also make the generated `__hash__` raise on an unhashable field.) This is an addition
to the three-call-sites rule, not an exception to it: the set is still computed in exactly
one place.

**Which function owns which precedence step**, so the boundary is not left to be discovered:

| Step | Owner |
| --- | --- |
| 1 `open=session`, 2 `open` present, 5 session seed, 6 empty | `_open_ids` |
| 3 `q` chains | `_filtered_map`, called by `_render_scope` / the page views; result reaches `_open_ids` as `q_chain` |
| 4 ≤150-node rule | `_open_ids`, from `len` of the all-nodes index it already builds — **in `"page"` and `"notice"` modes only** |

**Transport — and why form actions carry nothing.** An earlier draft put the `open` query
string on every form action and href. Hoisting removes the *reversal* cost but not the
*byte* cost: the string is emitted into ~6 URLs per row, so on `mat-pp` under expand-all
that is 6 × 944 × ~685 bytes ≈ **3.9 MB of query strings added to a page this spec exists to
shrink**. On a 150-node course (~30 containers → a ~150-byte enumeration) it is 6 × 150 ×
~150 B ≈ **135 KB** — computed on that course's own container count, not by carrying
`mat-pp`'s 137-pk set onto it, which would inflate the figure ~5×. The transport is therefore:

| Path | Carrier |
| --- | --- |
| JS — any fragment request | `open` appended to the `FormData` / query by the collector in §5. Nothing in the markup is involved. |
| JS — surviving a reload | `history.replaceState` writes the recomputed `open` into the address bar on every toggle (§5). Without it, F5 discards the author's expansions. |
| No-JS — expanding | The toggle's own `href`, the **only** markup that carries an enumeration: one per container row, not one per URL per row. |
| No-JS — mutations | No `open` on the form (**except the delete confirm form** — see §4's delete chain). `builder()` persists the open set to `session["builder_open"][slug]` **only when it came from an explicit `open`** (precedence steps 1–2 — see the persistence rule below; a derived set must never be written back); the post-mutation redirect becomes `manage_builder?open=session`, and only that explicit sentinel reads it back. |

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

1. `open=session` → `session["builder_open"][slug]` (no-JS post-mutation only). **If that key
   is missing or empty — an expired or flushed session, a re-login between the page GET and
   the mutation, a forged `?open=session`, or a POST that is the first request of a new
   session — fall through to steps 3–6**, so a small course still arrives expanded rather
   than fully collapsed. `_builder_with_notice`'s direct read follows the same fall-through.
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

**Only sets that came from steps 1–2 are persisted.** A derived set must never be written
back: on a no-JS filter GET the effective set *is* the `q` chains, so persisting it would
overwrite the author's real expansion with the filter's, and clearing the filter (an
`open`-less GET → step 4/5) would then lose that expansion permanently. The same applies to
the §3a ≤150 default, the §3 seed, and any truncated resolution.

**Rule: `builder()` writes `builder_open` only when the set came from an explicit `open`
(steps 1–2) AND `q` is absent from the request.** The `q` clause is not redundant — without it
the invariant is broken by this design's own transport. A no-JS author filters (step 3 → the
`q` chains), then clicks any toggle; that href carries `open = q-chains ± pk`, which arrives
via **step 2** and would be persisted, overwriting their real pre-filter expansion with the
filter's chains. The JS path has §9's stash to recover from that; no-JS has nothing, so the
loss is permanent. Since any set computed while `q` is active is filter-derived by
construction, skipping the write whenever `q` is present closes it. The "does not persist a
derived set" test must therefore include a **toggle under an active filter**, not only an
un-toggled filter GET.

**It is stored as a sorted `list[int]`, not a `set`.** No `SESSION_SERIALIZER` is configured,
so Django 5.2 uses `JSONSerializer`, and a `set` is not JSON-serializable — measured:
`TypeError: Object of type set is not JSON serializable`. Storing the resolved set directly
would raise on **every** builder page load. The unchanged-check compares the stored list to
`sorted(open_set.ids)`, so it is neither accidentally always-true nor always-false.

The session write for no-JS is a **fallback, not the model**: the JS path never emits
`open=session`, so two JS tabs still cannot fight. Two *no-JS* tabs on one course share
`builder_open` and will; that is accepted for the fallback path and stated here rather than
discovered later.

**Transport budget.** The enumeration appears only in toggle hrefs, so its cost is bounded
by |containers| × |open set| × ~5 bytes. On `mat-pp` after expand-all that is 137 × 680 ≈
94 KB against an already-multi-megabyte page. On a **fully expanded** course (the §3a
small-course default, or expand-all) every container row's toggle is a *collapse* href, and a
collapse href is `open_joined` minus a set — always an enumeration. The bare `all` is emitted
only when the *resulting* set is the full container set, which a collapse never produces. So
the small-course default costs |containers|² × ~5 bytes, not 3 bytes: for a 150-node course
with ~30 containers that is ~4.5 KB, which is why the conclusion holds anyway. The 500-pk
ceiling below bounds the worst case.

**A newly added container opens itself.** `node_add` passes the new node's pk (and its
ancestor chain) as `extra_open` **whatever its kind** — the kind test belongs to effect 1, not
to the call site (see the two-effects rule below), so only a container ends up in the emitted
open set while a unit still gets effect 2's force-inclusion. Writing the condition here as
"when the created node is a container" is the rejected earlier draft: it reads as a call-site
guard, and `extra_open=(pk,) if node.kind != "unit" else ()` silently breaks the
add-under-filter case, because `views_manage.py:286` then returns the restricted parent scope
without the new row. Without effect 1, an author who adds a chapter would have to expand it
before they could add anything into it. **On the no-JS path there is
nothing to render** — `node_add` ends in a redirect (`views_manage.py:282`) — so it must write
into `session["builder_open"][slug]` before redirecting, or the rule would fail for exactly
the users who cannot expand cheaply. It writes the new pk **and the node's ancestor chain**,
unioned into whatever is already stored — not the bare pk. If the key happens to be missing at
that moment (the flushed-session / re-login case step 1 enumerates), a bare `[new_pk]` would be
non-empty, so step 1 would *not* fall through, and the tree would render with only the new
container's own scope open and every ancestor collapsed — making the node the author just
created invisible.

**A reparent opens its destination.** Same reasoning, different trigger, and it is the more
dangerous case. The Move… picker offers *every* legal destination including collapsed ones,
and a reparent returns `_render_tree` rendered with the caller's open set — so moving a node
into a collapsed chapter makes the row **disappear with no marker, no notice and no way to
tell success from failure**. §6's acceptance argument for the drag case ("open both branches
and drag") does not apply here: the picker exists precisely so the author need not see both
ends. Therefore a reparent adds the destination scope's pk **and its ancestor chain** to the
open set it renders with, on both the picker and drag paths, and a test asserts the moved
node is visible in the response.

**On the no-JS picker path it renders nothing either**, so the same session write applies:
`node_move`'s reparent branch unions the destination pk and its ancestor chain into
`session["builder_open"][slug]` before the `:411` redirect. Without it the no-JS picker — the
affordance that exists *precisely* for moves the author cannot see both ends of — would still
vanish the node, on the exact path this rule was written to protect. Tested as a no-JS picker
case, not only a drag case.

**The picker must carry `q` too, by the delete-style chain.** It is a separate page rendered
by `_move_picker`, not one of the in-tree forms, so §4's "every tree form carries a hidden `q`"
does not reach it — and the session write above propagates only `open`. Left as is, a no-JS
author who filters and then moves a matched row via the picker lands on the unfiltered tree:
the same "same gesture, two different trees" divergence closed for rename and for delete.

**The chain needs a first hop, and neither existing path supplies one.** The Move affordance is
a *link* (`_tree_node.html:30`), so §4's "every tree **form** carries a hidden `q`" does not
reach it; and §2/§8 both deliberately carve the `[data-move]` fetch (`builder.js:247`) out of
`_render_scope` handling, so the collector does not touch it either. Written without this, an
implementer's `request.GET.get("q")` is always `""` and the whole rule is a silent no-op. So,
explicitly:

1. **no-JS:** the Move link's `href` carries `&q=` in markup — permitted, like the hidden `q`
   on forms, because it is a handful of bytes rather than the open enumeration
2. **JS:** the `[data-move]` fetch appends the live `q`

Then `node_move`'s GET puts it into the picker context, the picker's reparent form carries it
as a hidden input, and the `:411` redirect emits `open=session` **plus `q`**. The no-JS picker
test asserts `q` survives the round trip.

`_move_picker.html` today is a bare `<form>` with no chrome — no back or cancel control — so
there is no existing link to thread `q` through. Adding one is **out of scope**; if a Cancel
affordance is ever added it points at `manage_builder` with `q` and `open=session`.

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

**A no-JS author never writes this key — stated, and accepted.** `node_panel`'s URL exists
only in `data-panel-url` and is fetched only by `builder.js:301`; §7 hoists it to the root,
making it *exclusively* a JS endpoint. So for a no-JS author on a >150-node course the §3 seed
never has a value, and every non-mutation return to the builder (step 6 of the precedence
list) lands on a fully collapsed tree. This is accepted rather than fixed: the no-JS path
already has the toggle hrefs and `open=session` for the mutation loop, and seeding
`builder_last_node` from the `#node-<pk>` fragment is impossible server-side — a URL fragment
is never sent to the server.

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

**Rule: if the course has at most 150 nodes, the effective open set is every container;
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
3.14 s of template time, so 150 rows is ~500 ms of server render and **~6,600 elements**
(150 × 44, the post-change browser basis — the pre-change 40.7 would say ~6,100 and the
offline, CSRF-less basis ~5,600; mixing bases invites a false failure at review time). Note
that this **exceeds even the "< 3,800 elements" row below** (the `mat-pp` §3-seed worst
case), which is why the element criteria are scoped to `mat-pp` and the threshold course gets
its own row: a 150-node
course is ~16% of `mat-pp`'s weight, an improvement on nothing but a large improvement on
where `mat-pp` is today, and it is the price of not regressing courses that are fine as
they are.

#### 4. No-JS parity

The builder's existing no-JS discipline is preserved:

- the toggle is a real link to the builder page with the recomputed `open` value, built by a
  `{% toggle_href %}` template tag
- the href ends with `#node-<pk>`, and rows gain a matching `id`. Without it, expanding a
  scope 300 rows down is a full page load that returns to the top of the document.
- the no-JS mutation **forms** carry no hidden **`open`** and no query string on the action.
  Two deliberate exceptions, both named so the rule is not read as absolute: every tree form
  carries a hidden **`q`** (a handful of bytes, unlike the open enumeration), and the delete
  confirm form carries a hidden **`open`** (see the delete rule below). Their **redirect
  targets** do change: each becomes
  `manage_builder?open=session`, **plus `q` when the mutation carried one** — otherwise a
  no-JS author who filters and then renames a matched row lands on the unfiltered tree, the
  same "same gesture, two different trees" divergence rejected for `_builder_with_notice`
  below. `_builder_with_notice` likewise re-renders under the submitted `q`. To make that
  possible the **filter form's `q` is the one value tree forms do carry** — a single hidden
  input per form, which is a handful of bytes rather than the open enumeration's hundreds.
  Per §2's sentinel rule these six sites are the *only* places allowed to emit `open=session`:

  | Site | `views_manage.py` (the `redirect(...)` line) |
  | --- | --- |
  | `node_add` | `:282` |
  | `node_rename` | `:344` |
  | `node_move` (reorder) | `:376` |
  | `node_move` (reparent) | `:411` |
  | `node_delete` | `:455` |
  | `node_duplicate` | `:494` |

  **Three further `redirect("courses:manage_builder", …)` sites are deliberately excluded**
  and named here so the "only six" claim is checked rather than assumed: `element_move`
  (`:636`) and `element_delete` (`:652`) — which *are* mutation redirects, but are near-dead
  today because the builder's unit panel is read-only and the editor's element forms post
  `ctx=editor` — and `course_create` (`:79`), where a brand-new course has nothing to open.
  All three stay on the seed path.

  **Delete needs more than a redirect, because it is a full-page navigation for everyone.**
  `node_confirm_delete.html`'s form carries **no `data-op`** and `builder.js` has **no
  `[data-delete]` handler** (only `[data-move]`, `builder.js:245`) — verified — so the confirm
  POST is never a fragment request and `node_delete`'s fragment branch is unreachable from the
  UI. For a JS author `builder_open` then holds whatever was persisted at the *last page GET*,
  not the toggles made since (which live only in the DOM and the address bar), so deleting
  would snap the tree back to load-time state. Therefore: `builder.js` rewrites the
  `[data-delete]` href with the live `open` **and `q`** at click time (no `preventDefault` — it
  is still a navigation), `node_delete`'s GET puts both values in the confirm page, the confirm
  form carries them as **hidden inputs** (one form on the page, so the §2 byte argument does
  not apply), and the POST's redirect emits them instead of `open=session`. `q` must ride the
  whole chain, and so must the **Cancel** link: otherwise an author who filters and then
  deletes a matched row lands on the unfiltered tree — the same divergence rejected for rename
  one paragraph above.

  **Without JS there is no rewrite, so the chain must degrade rather than blank the tree.**
  `_tree_node.html:40` emits the delete href with no `open`, and §4 forbids adding one to the
  markup — so for a no-JS author every step of the chain sees nothing, and a naive "emit the
  hidden value instead of `open=session`" would send `open=` and collapse the tree to nothing,
  destroying the expansions of exactly the users the session carrier exists to protect. Rule:
  `node_delete`'s GET tests **presence** of `open` (the same presence-not-`.get()` rule as §2).
  Absent → the confirm template omits the hidden input and the POST redirects with
  `open=session`, which is accurate for a no-JS author because `builder_open` was populated
  from their toggle hrefs via step 2. Present (including empty) → round-trip the value. So
  `node_delete` is on the six-site table **for its no-JS branch only**; with JS it emits the
  round-tripped value.

  **`q` does not degrade — it is emitted in the markup.** `_tree_node.html:40`'s delete href
  carries `&q=`, symmetric with the Move link and with the hidden `q` on every tree form. `q`
  is not subject to the byte argument that bars `open` from markup, so there is no reason to
  let a filtered no-JS delete land on an unfiltered tree when the fix costs a few bytes. A
  no-JS delete gets its own test row — there is none today — covering both `open` and `q`.

**Every other route back to the builder falls through to the §3/§3a seed — deliberately.**
None of these is a mutation redirect, so none emits `open=session` and none reads
`builder_open`. Requiring each to propagate an `open` parameter would have been an unstated
dependency on several unrelated subsystems, so the trade is accepted explicitly:

| Return route | Template | What the author gets |
| --- | --- | --- |
| editor back-link (the core authoring loop: open a unit, edit, return) | `editor/editor.html:60` | **Better than the carrier**: the §3 seed is the pk `node_panel` stored when they selected that very unit, so they land with its chain open |
| delete confirmation Cancel | `node_confirm_delete.html:12` | **the live `open`** — the delete rule above already puts it in this template's context, so Cancel carries it for free; there is no remaining reason to degrade it |
| Move… picker | `_tree_node.html:30` → `_move_picker` | same as above (JS authors never leave the page) |
| export preview, import, media manager | `export_preview.html:25`, `import_course.html:31`, `media/manager.html:12` | seed chain; these are excursions, not part of the tree-editing loop |
| builder header `Import content` / `Export` | `builder.html:17-18` | seed chain |

Apart from `node_confirm_delete.html` and `node_delete`'s GET branch — which the delete rule
above already changes — none of these templates or views changes.

**Three `_render_tree` sites outside the builder flow are excluded, and named so the omission
is a decision rather than an oversight:** `_element_conflict` (`views_manage.py:675`) and
`element_save` (`:1076`, `:1087`) return a 409 tree fragment when the unit itself has vanished.
Those requests originate from the *editor* page, carry no `open` and no `q`, and will therefore
return a collapsed tree where they previously returned the whole one. Accepted: they are
unit-vanished conflict paths rendered into the editor, not the tree-editing loop.

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
  container's open-descendant pk set **once per render, in a single bottom-up pass over the
  FULL `cmap`** (each node's set is the union of its children's sets plus its open children),
  then emit `open_joined` minus that set. The full map, not §9's restricted one: over the
  restricted map a collapse href would fail to drop open descendants the filter excluded, so
  they would persist in the open set and reappear on clearing the filter — breaking the
  "collapse forgets descendants, identically in both paths" invariant this rule exists to
  hold. This matches the map `_open_ids` receives (§9).

Emit the bare `all` when the resulting set is the full container set.

**Context keys, supplied by all three page/fragment renderers.** `_scope.html` is included
recursively from `builder.html:22` *and* rendered directly by `_render_scope`, so the
precomputed structures must be added to **both** context dicts or the tag silently sees
nothing on fragment renders. `builder()`, `_builder_with_notice()` and `_render_scope()` each
supply: `open_joined` (the joined string), `open_descendants` (pk → set), `builder_url`,
`open_ids`, `data-container-count`'s value (§10 needs it on `.builder`, which both page
renderers emit), and **`q`** — omitting `q` from this list would make every toggle href drop the filter, which is
the same "toggles fight the filter" defect resolved above, in the opposite direction.

`open_joined` is **always the enumeration, never the literal `all`**; the `all` shorthand is
applied by the tag to the *resulting* set, after subtraction.

**Subtract on the id set, never by string replacement.** Comma-joined pks are
prefix-colliding: `"1,120,12".replace(",12", "")` corrupts the list. The tag already receives
the open-id set, so the collapse href subtracts there (or splits `open_joined` on commas and
filters token-wise) and re-joins. `open_joined` is a precomputed fast path for the **expand**
case only, where a single pk is appended.

Both `open_joined` and `open_descendants` are computed from the **post-`extra_open`** set, so
the hrefs a response emits describe the same open set as the markup they sit in. Building them
pre-union would make the toggle hrefs inside a reparent or add response contradict the tree
around them, breaking "collapse forgets descendants, identically in both paths" for anyone who
follows one.

**Tag signature**, so the context access is not left to be inferred:

```python
@register.simple_tag(takes_context=True)
def toggle_href(context, node, is_open): ...
```

It reads `open_joined`, `open_descendants`, `builder_url`, `q` and the open-id set from
context, and takes the node and its state as arguments. `open_descendants` is a pk-keyed dict,
which a Django template cannot index by a variable — so the lookup has to happen inside the
tag, which is why this is a `simple_tag` with `takes_context` rather than a filter.

**`builder_url` exists so `{% toggle_href %}` does not reintroduce the very defect §7
removes.** The tag needs `courses:manage_builder`, which is a per-course constant; reversing it
inside the tag would be one reversal per container row — 137 under expand-all, the same
mistake this spec is fixing. Reverse it once per render and pass it in, so the tag only
concatenates.

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
The `aria-label` is re-rendered too, since it says "Expand"/"Collapse".

**The count inside that label goes stale after an add, duplicate or delete in the row's own
scope, and that is accepted.** The count lives on the parent's row, in the parent's scope,
while those mutations return only the affected `<ol>` — so a chapter's toggle keeps announcing
the old number until the next full render. (Reparent is unaffected: `_render_tree` re-renders
everything visible.) Accepted because the count is not visible text, so the impact is confined
to assistive tech and is a stale number rather than a wrong action; fixing it would mean the JS
recomputing a pluralised string, which §1 establishes it cannot do. Recorded here so it is a
decision rather than an oversight, and deliberately **not** covered by a test.

**A foreign fragment swap can land mid-fetch, and the response must not resurrect a dead
row.** This file is written around exactly this hazard — `applyRename` guards
`!form.isConnected`, the rename `focusout` guards `swapping`, `loadPanel` uses a
last-request-wins id — because a rename commit, a reorder or a drop returning
`_render_scope`/`_render_tree` can `replaceWith` the ancestor scope while a toggle is in
flight. The fresh server markup renders the toggled node **collapsed** (the collector on
*that* request could not yet see the pending pk), and the toggle's late response would then
insert its `<ol>` into a detached `<li>`, so the author sees the row snap back to collapsed
with no error. **Rule: when the response lands, re-resolve the row by `[data-node]` from
`root` and bail if it is gone or no longer marked in-flight.** Tested by firing a
scope-returning mutation between the toggle request and its response.

**The in-flight mark is required, and the insert must replace.** Unlike `applyFragment` —
which is idempotent because it *swaps* the element matching `data-scope` — this handler
inserts. Two clicks before the first response lands would produce two sibling
`<ol data-scope="pk">` elements, after which `:scope > ol.tree__scope` (`builder.js:155`,
`:442`) picks an arbitrary one and the DOM collector reports the pk twice. So: ignore repeat
activations while in flight (reuse the `dataset.submitting` convention already in the file),
and have the insert replace any existing `:scope > ol.tree__scope` rather than append
blindly.

**The failure path must clear it, or the in-flight guard wedges the row for good.** Only the
success path is described above; a network failure or any non-200 (403 after a role change,
404 after another tab deleted the node, 500) would otherwise leave `dataset.submitting` set
and make that row's toggle permanently dead with no feedback. Every other fetch in
`builder.js` has a `.catch` that notices and calls `releaseForm`; this one needs the
equivalent: on `.catch` **and** on any non-200 — clear the in-flight mark, leave
`aria-expanded="false"` with `aria-controls` absent, decrement the §8 busy counter, and
surface `msg("network", …)`.

**`history.replaceState` fires after ANY successful tree-fragment application AND after every
client-side collapse** — recomputing `open` (and `q`, if active) from the DOM collector, which
already exists. Both halves are needed: a collapse is a toggle that applies *no* fragment (it
just removes the `<ol>`), so a fragment-only rule would never update the address bar on
collapse — a reload would re-open what the author just closed, and the "empty set is written
as `open=`" rule below would be unreachable, since collapsing the last scope is exactly the
case it names. Toggle-only would break the rules in §2 that open a scope *server*-side: an author who
drags a unit into a chapter and then reloads would re-enter `builder()` with the *pre-drop*
`open`, the destination collapsed and the moved node invisible again — the exact failure §2
calls "the more dangerous case". With it, a reload or Back navigation re-enters with the
author's expansions intact instead of falling back to the seed, and it is what makes the "two
tabs do not fight" claim in §2 true for JS authors.

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
does.

**The guard must be armed at `pointerdown` on `[data-toggle]`, not around the `<ol>`
removal.** A mouse click moves focus at *mousedown*, so `focusout` on the dirty title fires
**before** the delegated click handler ever runs — at which point `swapping` is false and
`form.isConnected` is true, so `commitRename` fires a real POST. A guard set around the
removal and the focus move runs strictly too late, so keyboard-collapse would abandon the
rename while mouse-collapse committed it: divergent behaviour, and the "collapse over a dirty
rename posts nothing" test could never pass on the mouse path. So: arm at
`pointerdown`/`mousedown` on the toggle, disarm if the click never materialises (e.g. the
pointer is released elsewhere). **The test must drive a real mouse click**, not just keyboard
activation, or it verifies only the path that was already correct.

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
`"top"`). One helper, called from the submit handler and the drop handler.

**The collector SETS `open` and `q`, it does not append them.** Mutation forms already carry a
hidden `q` (§4), so appending would put two `q` values in the `FormData`; Django's
`QueryDict.get` returns the last, so the collector would win only by accident of ordering —
and the two genuinely differ during the 300 ms filter debounce, where the hidden input holds
the last *rendered* `q` and the collector holds what is currently typed. The collector's value
is authoritative.

**The collector always emits an enumeration** — it can only observe what is in the DOM, and `all` originates
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
  no layout (only `closest()` and attribute reads), so it does not need throttling.

  **The split, by line:** the rAF callback takes **all of `builder.js:457-466`** —
  `clearDropMarks()`, `classList.add("drop-target")`, `targetFor()`, the line insertion, the
  three `dataset.drop*` writes and `drag.targetScope = scope`. The synchronous part is limited
  to scope resolution, the legality test and `e.preventDefault()`. Naming only
  "clearDropMarks, targetFor and the line insertion" would omit four statements, and the
  omission is not harmless: the `dataset.drop*` writes depend on `targetFor`'s result so they
  *must* defer, and it is precisely `.drop-target` and `targetScope` deferring that makes the
  "`drop` flushes the pending frame" rule below necessary. An implementer following a shorter
  list would produce a `drop` that reads an undefined `dropIndex`.

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

  **The rejecting branches must cancel too.** `builder.js:455` handles an illegal target
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
already does for `rename_url` (and keep the same explanatory comment style). Reversals are
~30% of render time and this removes **4,583 of 5,803 (79%)** — move ×2 (1,888) + delete
(944) + panel (944) + duplicate (807) — so the expected saving is **~24% of render time** for
a mechanical change, and it benefits every scope render including expand-all.

**§7 needs a structural guard, or it can be silently dropped.** It is the one section whose
entire justification is wall-clock render time, which the Testing section deliberately refuses
to assert on CI. Without a guard, reintroducing `{% url %}` in `_move_buttons.html` or
`_tree_node.html` would be invisible to the suite. The guard: render a fixed-size scope with
`django.urls.reverse` patched and **count the calls**, asserting exactly one per row
(`manage_node_export`) plus the per-scope constants — a test that goes red the moment a
per-row reversal returns.

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

**The busy state is visual only — it must not block pointer events.** §5 relies on a
per-toggle in-flight mark to prevent double-activation, and that guard is dead code if the
pane sets `pointer-events: none`; the "two rapid clicks" test would then pass vacuously.
Gesture-level guarding is per-control; the pane-level state only communicates.

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
- **The no-JS path needs its own force-include channel**, because `extra_open` exists only on
  fragment renders. A no-JS add, duplicate or reparent redirects; the following page GET
  re-derives the restricted map from `q` alone, knows nothing of the created or moved pk, and
  that node's title will rarely match `q` — so the author lands on a filtered tree with their
  new node **absent**, indistinguishable from failure, on the path with the least feedback. (A
  rename that moves a title out of the match set is the same case.) Rule: `node_add`,
  `node_duplicate` and `node_move` stash the created/moved pk in
  `session["builder_force"][slug]` beside `builder_open`, and `builder()` unions it into the
  restricted map for **exactly that next render**, then clears it. Tested: filter, add a
  non-matching title without JS, assert the new row is present.
- **`q` travels with EVERY fragment request, not just the toggle** — **set**, not appended,
  per §5's rule (a mutation form already carries a hidden `q`, so appending would put two
  values in the `FormData` and the collector would win only by accident of ordering). `manage_node_scope` is
  only one caller of `_render_scope`: under an active filter, a rename 409 (`_conflict_scope`),
  an add, a duplicate, a reorder and a drop (`_render_tree`) all return the same markup, and
  none of them would receive `q` — so the failure diagnosed for the toggle (unfiltered
  children arriving inside a filtered tree; a drop replacing the whole filtered pane with the
  unfiltered tree) would still happen on every mutation. Therefore: the §5 collector sets
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

Without JS it is a plain GET form posting to `manage_builder`.

**A filter-initiated request must OMIT `open`, or the filter cannot work on the JS path.**
§5's collector sets `open=<current DOM enumeration>` on every fragment request, and
precedence step 2 (`open` present) outranks step 3 (`q`) — so a filter fetch carrying `open`
would return only the scopes that happened to already be open, and a match three levels down
inside a collapsed branch would never appear. The no-JS path (a plain GET form with no
`open`) would work correctly, so the two paths would silently diverge on §9's central promise.
**Rule: the filter's own `manage_tree` request omits `open` entirely**, letting step 3 seed
from the match chains; *subsequent* toggles under that filter do send `open`, so step 2 then
correctly wins. This is the same carve-out §10 gets by sending `open=all`.

**With JS it needs an endpoint that returns the top scope, and none exists today.**
`builder()` returns a full page and is the only builder view with no `_wants_fragment`
branch; `manage_node_scope` is declared `<int:pk>` so it cannot serve the top scope. Adding a
fragment branch to `builder()` would silently change its contract for every existing test that
sends `X-Requested-With: fetch`. So: **a new `manage_tree` GET** (`…/build/tree/`) returning
`_render_tree(request, course)`, carrying `q`, `open` and the `X-Builder-Info` header, behind
`@login_required` + `_require_manage`. **Its URL reaches the JS as `data-tree-url` on
`.builder`**, emitted by `builder.html` — named here because slice 2 may be implemented from
§9/§10 alone, and every other JS-reachable endpoint and constant in this design has an
explicitly named attribute (`data-node-move-url`, `data-node-scope-url`, `data-msg-truncated`,
`data-msg-filtered`, `data-container-count`). It gets the same access-control test row as
`manage_node_scope`: anonymous → login redirect, non-manager → 403, foreign slug → 404,
manager → 200 with `data-scope="top"`. Expand-all (§10) uses it too.

It returns **the top scope `<ol data-scope="top">` and nothing else** — not `.builder__tree`
with its header, legend and helptext. `_render_tree` already does exactly this, and returning
more would break the single-`firstElementChild` contract `applyFragment` depends on (see Known
traps).

**Filter UI, pinned.** The control sits in `.builder__tree`'s header row, after the title.
The JS path debounces at **300 ms** after the last keystroke — undebounced it would issue a
full-tree render per keystroke, the exact cost profile this spec exists to remove. `q` is
stripped of leading/trailing whitespace, and a query shorter than **2 characters** after
stripping is treated as blank — **by `_filtered_map`, on the server**, so a no-JS `?q=a` or a
hand-typed URL cannot filter either. On `mat-pp` one letter matches hundreds of titles → 100
capped matches → up to 400 open pks → a several-hundred-row render, i.e. exactly the cost
profile the debounce exists to avoid, reached by the one path that has no debounce.

**The JS treats a below-floor query exactly like an empty one — it takes the clear path**
(stashed `open`, no `q`, stash consumed). The floor therefore only ever saves a round trip on
the way *into* a filter, never on the way out. Reading it as "just don't fetch below 2
characters" would leave filtered markup on screen while the collector then sets `q=a` on the
next toggle or mutation; the server treats that as blank and returns **unfiltered** children
into a **filtered** pane — the precise defect the "`q` rides every fragment request" rule
exists to prevent.

**Clearing the filter needs a request and a stash.** "Restores the unfiltered tree" cannot be
done client-side: the pane holds *filtered* markup with the non-matching rows absent, and the
author's pre-filter expansion no longer exists anywhere on the client — the DOM collector now
sees the filter's chains, and `history.replaceState` has already overwritten the address bar
with them. So the filter handler **stashes the pre-filter open enumeration in a module-scoped
variable before its first filter fetch**, and clearing the filter issues a `manage_tree`
request carrying that stashed `open` and no `q`. The stash is discarded once consumed, and
also whenever a mutation happens while filtered (the tree has changed underneath it).

**The stash is initialised to `null`, and the fallback tests `stash === null`, not
falsiness** — a legitimately empty pre-filter set stashes as `""`, and an `if (!stash)` would
misread it as absent, so an author who had everything collapsed, filtered, then cleared would
get the filter's chains open instead of the empty tree they started from. This is the same
empty-vs-absent trap §2 pins for the `open` parameter itself.

**If the stash really is absent, the clear request carries the collector's current enumeration
— it never omits `open`.** Filter → mutate → clear is a normal authoring sequence, and it reaches
the clear with no stash. Omitting `open` there would put the request on the `mode="fragment"`
absent path, i.e. the **empty set**, collapsing a large course to its 21 top rows and
destroying every expansion the author had. Falling back to the collector is merely lossy (it
returns the filter's chains rather than the pre-filter set), which is the right trade. Tested:
filter, mutate, clear, assert the tree is not empty. The §10
expand-all control reads the container count from a `data-container-count` attribute the
server puts on `.builder`, which is how it knows to render itself disabled above the 500
ceiling.

**A mutation under an active filter must not make its own result vanish.** The new node's
title will rarely match `q`, so an add or duplicate rendered through the restricted map would
return a scope *without* the row the author just created — indistinguishable from failure, and
the same shape of bug §2's reparent rule exists to prevent. **Rule: a mutation's own
created/moved pk, and its ancestor chain, are force-included in the restricted map for that
response**, via the same `extra_open` channel. Tested alongside the reparent-visibility test.

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
for `manage_builder`, `/build/`, `data-scope`, `tree__row`, **`data-panel-url`** and
**`data-node-move-url`** — a file-name prefix is not a reliable filter, and four of the files
above were missed by one. The last two matter because §7 moves `data-panel-url` off every
`input.tree__title` and onto `.builder`, so any test reading it from a row breaks and none of
the first four terms would find it.

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
- session seed opens exactly the ancestor chain **plus the node itself when it is a
  container** (§3 — this is why the ceiling is 4, not 3) and nothing else
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
- the 500-pk ceiling keeps the 500 lowest pks (a pinned, reproducible outcome); the page
  render carries the notice in the `info` slot **and a truncated fragment response carries
  `X-Builder-Info: truncated;limit=500`**, which the JS renders under the `truncation` key
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
- **`manage_tree` access control**, the same five rows as `manage_node_scope`
- **an add or duplicate under an active filter returns its own new row visible**, via
  `extra_open` — the filtered twin of the reparent-visibility test
- **a scope-returning mutation landing mid-toggle** leaves no detached `<ol>` and no row
  stuck marked in-flight
- **`builder_open` round-trips as a sorted list** and the unchanged-check actually suppresses
  the second write
- **`_builder_with_notice` renders the same tree as the success path** for the same gesture
- **the `X-Builder-Info` header is machine-readable** — assert it never contains a non-ASCII
  byte or an RFC-2047 `=?utf-8?` prefix, in a Polish-locale test
- **the `info` slot replaces by key**: two successive filter responses leave one entry, and a
  response without the header clears it
- **§7's reversal-count guard** (above): exactly one per-row reversal survives
- **§8's busy counter**: a *failing* tree fetch leaves the pane not-busy (else it wedges);
  two overlapping tree fetches keep it busy until both settle; a debounced panel fetch does
  not set it at all; and a `test_builder_styles.py`-style assertion that the busy selector
  does **not** declare `pointer-events: none` — without which §5's per-toggle in-flight guard
  is dead code and the double-click test passes vacuously
- **the toggle's failure path**: a non-200 clears the in-flight mark and the row stays usable
- **`open=session` with no stored value** falls through to steps 3–6 (a small course still
  arrives expanded)
- **a filter request omits `open`**: with scopes collapsed, filtering for a title three levels
  down returns the match row
- **toggle hrefs preserve `q`**, and a no-JS mutation under a filter returns to the filtered
  tree
- **collapse updates the address bar**: collapse the last scope, reload, tree stays empty
- Polish-locale: `data-label-expand` / `data-label-collapse` pluralise correctly for 1, 2, 5
- **a no-JS reparent via the Move picker into a collapsed destination** returns the moved node
  visible (the session-write half of the rule, not just the rendered half)
- **a no-JS add with the session cleared between the page GET and the POST** still shows the
  new container — i.e. the write carried the ancestor chain, not a bare pk
- **`builder()` does not persist a derived set** — asserted on the session, not the render,
  because clearing a filter is an `open`-less GET that reaches step 4/5/6 and never reads
  `builder_open`, so a render-level assertion would pass vacuously (and doubly so on a
  ≤150-node fixture where everything is open anyway). On a fixture **above** the 150 threshold:
  expand A and B via explicit `open` (persisted), filter, clear the filter, then perform a
  no-JS mutation so the redirect carries `open=session` — and assert A and B come back.
- **a filtered mutation re-asserts `X-Builder-Info: filtered;…`** so the cap notice survives —
  driven by an **add, reorder, duplicate or drop**, never a rename (whose success response is
  `_rename_result.html` and never reaches `_render_scope`)
- **a rename, a 422 and a panel fetch under an active filter leave the notice untouched** —
  they neither set nor clear
- filter then expand: with `q` active, a toggle still expands (the `q`-seeds/`open`-wins
  rule), and the filtered count is what the toggle shows
- adding a container returns it already open; adding a unit does not change the open set
- a collapsed container with zero children still renders a toggle, and expanding it
  yields the empty scope plus its add affordance
- **`manage_node_scope` access control**, per `access-widening-reachability-tests`:
  anonymous → login redirect; non-manager → 403; pk from another course → 404; unit pk →
  404; manager → 200 carrying the expected `data-scope`. **Not** "non-numeric pk → 404": the
  route is `<int:pk>`, so the resolver 404s before the view runs and such a test would pass
  without any view code, guarding nothing (`falsify-tests-not-run-them`). The real hazard —
  `int(scope_ref)` raising inside `_render_scope` — belongs to a direct unit test of
  `_render_scope` with a non-numeric `scope_ref`.

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
| 1 | DOM elements on load, `mat-pp`, empty open set | 38,418 | < 1,300 (21 rows × 44) |
| 1 | DOM elements on load, `mat-pp`, §3 seed worst case | 38,418 | < 3,800 (78 rows × 44 ≈ 3,432 — see Scope widths) |
| 1 | reparent round trip | 4.47 s | < 500 ms |
| 1 | forced layout per `dragover` | 14.4 ms | ≤ 1 per frame |
| 1 | toggle (expand one scope) round trip | n/a — new primary interaction | < 300 ms |
| 1 | a 150-node course (the §3a threshold) | unchanged today | still fully expanded; `domInteractive` < 1.5 s; ~6,600 elements accepted (150 × 44, post-change browser basis) |
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
