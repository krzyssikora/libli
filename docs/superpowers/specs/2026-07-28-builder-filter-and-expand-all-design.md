# Builder filter and expand-all (slice 2) — design

Supersedes §9 and §10 of
`docs/superpowers/specs/2026-07-27-builder-large-course-performance-design.md` (the parent
spec). Everything else in the parent still holds and is **not** re-litigated here: the
precedence table in §2, the no-JS rules in §4, the toggle mechanics in §5, the drag changes in
§6, the URL hoist in §7 and the notice/busy channel in §8 all shipped in slice 1 (PR #189) and
are load-bearing for this slice.

Where this document and the parent disagree, **this one wins**, and every such point is
called out explicitly under "Deltas from the parent spec" so a reviewer can check the
disagreement rather than discover it.

## What slice 1 left behind

Slice 1 rendered only the open tree scopes. On `mat-pp` (944 nodes, 137 containers, measured)
that took the builder from 8,367 ms `domInteractive` / 3.0 MB / 38,418 DOM elements to
991 ms / 83 KB / 968 elements. It deliberately left three hooks rather than stubs:

- `open_ids(request, course, cmap, *, mode, q_chain=None)` reserves precedence **step 3** for
  the filter's ancestor chains. Slice 1 always passes `None`.
- `_info_entries(opened)` already emits **keyed** entries (`data-info-key` in the markup).
  Slice 2 adds the `filter` key and the JS renderer for the `X-Builder-Info` header.
- `_extra_container_pks` implements `extra_open`'s **effect 1** (union into the open set).
  **Effect 2** — re-inserting a created or moved node into the *restricted* cmap while a
  filter is active — is this slice's.

`manage_tree` and `data-tree-url` are specified in the parent but not built.

## Goals

1. An author can find a node in a 944-node course by typing part of its title, and get there
   in under a second.
2. An author can expand the whole tree deliberately, and collapse it again, without a reload.
3. Neither capability re-introduces the cost slice 1 removed on any other path.

## 1. Filter derivation lives in its own module

New `courses/builder_filter.py`, mirroring `courses/builder_open.py`: **no view imports and
no database access**, so it is unit-testable standalone and the view layer cannot grow a
second copy of the matching rule.

```python
MIN_QUERY = 2      # chars, after stripping
MATCH_CAP = 100    # matches kept, in (order, pk) order

def fold(s: str) -> str: ...
def filtered_map(cmap, q) -> tuple[dict, set[int], int, int]: ...
```

`filtered_map` returns `(restricted_cmap, chain_ids, shown, total)` and owns **all** filter
derivation: the fold, the match selection, the ancestor walk, the 100-cap and the
`(order, pk)` sort. `views_manage` imports it as `_filtered_map`, exactly as slice 1 aliased
`open_ids` → `_open_ids`.

**It is still one query in total.** `filtered_map` receives the `cmap` the builder already
loads and never touches the ORM. The matches' ancestors are by definition absent from a
title match, and a match carries only `parent_id`, so ancestors cannot come from a second
filter without a full node load or one query per level. Selecting matches in memory and
walking `parent_id` upward avoids both.

**`course` is not a parameter**, unlike the parent spec's `_filtered_map(course, cmap, q)`.
Once matching is in-memory, `course` is unused, and dropping it is what keeps the module
DB-free. This is a deliberate deviation; see Deltas.

### 1a. Blank, and the 2-character floor

`q` is stripped of leading and trailing whitespace. A query shorter than `MIN_QUERY` after
stripping is **treated as blank**, and `filtered_map` returns `(cmap, set(), 0, 0)` — the
unrestricted map, no chains.

**The floor is enforced here, on the server**, not only in the JS. On `mat-pp` a single letter
matches hundreds of titles → 100 capped matches → up to ~220 rows, i.e. exactly the cost
profile the 300 ms debounce exists to avoid, reached by the one path (`?q=a` typed by hand, or
a no-JS form submit) that has no debounce.

**Unlike `open`, presence is meaningless for `q`.** Slice 1's central trap was that `open`
absent and `open=` mean different things, so `_raw_open` tests `"open" in request.GET` rather
than truthiness. `q` has no such distinction: absent, empty and whitespace-only all mean
"unfiltered", and there is no session carrier for it to fall back to. Stated explicitly
because the neighbouring code reads the opposite way and an implementer copying the pattern
would add a presence flag that nothing consumes.

### 1b. `fold` — diacritic-insensitive matching, measured

Titles are Polish. `str.casefold()` alone means `zolw` does not match `Żółw` and `katy` does
not match `Kąty` — i.e. the filter fails for an author typing without diacritics, which is how
people search. Both the needle and each title are folded before the containment test, so the
match is symmetric: `zolw` finds `Żółw` **and** `żółw` finds `Zolw`.

**`ł` is the trap, and it was measured, not assumed.** `unicodedata.normalize("NFKD", "ł")`
returns the character **unchanged** — U+0142 has no canonical decomposition, unlike
`ą ć ę ń ó ś ź ż`, which all decompose to base + combining mark. A generic
"NFKD then drop combining marks" fold therefore silently leaves every `ł` in place, and
`Łąka` folds to `łaka`, which `laka` does not match. Verified on this repo's Python 3.13:

```
0x105 (ą) len(NFKD)=2  folded='a'      0x142 (ł) len(NFKD)=1  folded='ł'   <-- unchanged
0x107 (ć) len(NFKD)=2  folded='c'      0x141 (Ł) len(NFKD)=1  folded='ł'   <-- unchanged
0x119 (ę) len(NFKD)=2  folded='e'
0x144 (ń) len(NFKD)=2  folded='n'      'Żółw'.casefold() + NFKD-strip -> 'zołw'
0x15b (ś) len(NFKD)=2  folded='s'      'Łąka'.casefold() + NFKD-strip -> 'łaka'
```

**Implementation: one `str.translate` table, built once at import**, rather than a per-call
NFKD pass — because the per-call cost is not negligible and this runs on every filtered
request:

| Variant | 944 titles (mat-pp scale), measured |
| --- | --- |
| `casefold()` + NFKD + drop combining marks (generator + join) | **39 ms** |
| `str.translate(TABLE)` + `casefold()` | **18–24 ms** |

The table is built at import by decomposing U+00C0–U+024F (Latin-1 Supplement through Latin
Extended-B) and keeping the entries whose stripped base is ASCII — **261 entries, 2.7 ms to
build, once per process**. The two characters NFKD cannot reach are added explicitly:
`ł → l`, `Ł → L`.

```python
def fold(s):
    return s.translate(_FOLD_TABLE).casefold()
```

`translate` runs **before** `casefold` so the table can carry both cases; folding first would
turn `Ł` into `ł` and need only one entry, but stating the order here removes the ambiguity.

**The fold is Polish-complete, not Unicode-complete**, and that is the intended scope. `ß`
folds to `ss` via `casefold` (a Python guarantee, not our table); `ø`, `đ` and `ħ` have no
decomposition and are not in the explicit pairs, so they do not fold. No course in the corpus
contains them. A future language adds a pair, not a mechanism.

### 1c. Matching, the cap and the walk

- **Matches** are the nodes — **every kind, units included** — whose folded title contains the
  folded query.
- **Capped at the first `MATCH_CAP` in `("order", "pk")` order.** That ordering is
  deterministic but is **not** tree order: `order` is a sibling-local index, so a course-wide
  sort interleaves nodes from unrelated parents. Determinism is what the cap needs; tree order
  is not claimed. The sort must be applied explicitly — `cmap` is grouped by parent, so
  iterating it yields (order, pk) *within* each parent only.
- **`total`** is the match count **before** the cap; **`shown`** is the count after it.
- **The walk** takes each kept match and follows `parent_id` upward, collecting ancestor pks.
  `chain_ids` is the union of those ancestors **plus each matched container itself** — the same
  rule `builder_open._chain` applies, and for the same reason: otherwise a matched chapter
  arrives collapsed, and its own row is the one the author searched for.
- **The restricted cmap** contains exactly the kept matches and their walked ancestors,
  regrouped by `parent_id` in the original order. `top_nodes` is `restricted.get(None, [])` —
  **derived, never returned separately**, which is also why `extra_open`'s effect 2 needs no
  separate `top_nodes` step: a top-level node is inserted under key `None`.

**100 rather than 200**, and the parent's arithmetic is worth restating with the real numbers:
each match drags in up to 3 ancestors, so 100 × 4 = 400 sits under parent §2's 500-pk ceiling. On
`mat-pp` the realistic figure is far lower, because matched units *share* ancestors — 807 units
hang off 111 chapters and 21 parts, so 100 matched units drag in at most 100 chapters + 21
parts and typically far fewer. **Predicted worst case ≈ 221 rows; predicted render ≈ 690 ms**
(221 rows × ~2.6 ms/row measured from slice 1's 2,477 ms / 944 rows, + 89 ms cmap + ~24 ms
fold). Under the 1 s target, but not by a wide margin on the DEBUG harness — this is a number
to check, not to trust.

### 1d. What the filter does *not* do

**A matched container shows without its children.** Filtering for a chapter title returns that
chapter's row, whose count reads 0 and which expands to an empty scope. This is deliberate and
self-consistent: counts under a filter show the **filtered** count (see §3c), so a toggle never
promises children the filtered view will not show, and the 100 × 4 = 400 arithmetic holds. The
author clears the filter to navigate into the hit. Including a match's own children would make
the filtered count mean two different things depending on whether the row itself matched, and
would break the pk arithmetic (a matched chapter can have 30 children).

## 2. Which map goes where

Two maps exist per filtered request, and mixing them up is the failure mode this section
exists to prevent:

| Consumer | Map | Why |
| --- | --- | --- |
| `_open_ids` (sanitisation) | **full** | Its rule is "is this a container of this course", not "is this in the filtered view". The restricted map would silently discard a legitimately-open pk the filter happens to exclude, and the author would lose that expansion on clearing the filter. |
| `_scope.html` / `top_nodes` | **restricted** | This is what filtering *is*. `_scope.html` renders whatever `cmap` it is given, so **no template change is needed for the filtering itself**. |
| `extra_open` effect 2 (node lookup) | **full** | The node being force-included is by definition absent from the restricted map. |

Both derive from the one queryset, so "one query in total" holds; the restricted map is a
derived structure, not a second query.

## 3. Server

### 3a. `q` is resolved inside `_render_scope`, not passed in

`_render_scope` reads `q` from the request itself and calls `_filtered_map`. Every fragment
path — the six mutation views, `_conflict_scope`, `manage_node_scope`, `manage_tree` —
inherits filtered behaviour without a new argument, which is what makes "`q` rides every
fragment request" true **by construction** rather than by six separate edits.

Resolution order is **POST first, then GET**: mutation forms carry a hidden `q` in the body
(parent §4), while toggles, `manage_node_scope` and `manage_tree` carry it in the query
string. A view that had both would be a mutation whose action URL also carried `q`; the body
is the authoritative one because the JS collector sets it there.

An earlier draft had the *view* compute `q_chain` and pass it to `_open_ids`. That works for
`builder()` and leaves every fragment path with no channel at all — and the filter's own
`manage_tree` request is *required* to omit `open` (§5b), so with `mode="fragment"` yielding
the empty set it would render a tree with **nothing open** and every match below the top level
invisible.

**`builder()` and `_builder_with_notice()` need the same derivation, and must not re-implement
it.** They render a page rather than a fragment, so they cannot call `_render_scope` — but they
need the identical restricted map, `top_nodes`, forced-in pks and `shown`/`total`. One shared
helper owns it and all three call it:

```python
def _filter_context(request, course, cmap, *, extra_open=()) -> tuple[dict, OpenSet, int, int]:
    """restricted cmap (with effect 2 applied), the resolved OpenSet, shown, total."""
```

Without a named owner, the `q` read, the `q_active` test, the `_open_ids` call, effect 2 and
the `top_nodes` restriction would exist in three places — the drift the parent's
three-call-sites rule exists to prevent, reintroduced by the page/fragment split.

### 3b. `q_chain` is passed when `q` is ACTIVE, not when the chain set is non-empty

`open_ids` tests `if q_chain is not None`. So:

```python
q_chain = chains if q_active else None
```

A filter that matches nothing yields an **empty** chain set. Passing `None` there would fall
through to precedence steps 4–6 — and step 4 opens a ≤150-node course **in full**. An author
who filters a small course for a typo would get the entire tree expanded under a notice saying
0 matches. Passing the empty set correctly resolves to "nothing open", which is what an empty
restricted map should render.

This is the one place where blank-vs-empty *does* matter for `q`, and it is resolved at the
call site (`q_active`), not by giving `q` a presence flag.

### 3c. Counts

Counts under a filter show the **filtered** count, matching the restricted `cmap` the rows are
rendered from. `_tree_toggle.html` already derives its count from `children_map|get_item:node.pk`,
so passing the restricted map is all this takes — no template change.

### 3d. `extra_open` effect 2

After the restricted map is built, `_render_scope` re-inserts each `extra_open` pk's node —
resolved from the **full** cmap — into `restricted[node.parent_id]`, re-sorted by `(order, pk)`,
and therefore into `top_nodes` when `parent_id is None`.

- **Effect 2 applies to every pk regardless of kind**, units included. Effect 1 (the open-set
  union) keeps its container-only filter. Splitting the kind test **across the two effects
  rather than at the call site** is what makes two otherwise-unsatisfiable requirements
  compatible: a unit added under an active filter needs effect 2 or the row the author just
  created does not come back, while that same pk must not enter the open set.
- **Force-included rows do not count toward `shown`/`total`**, or the `X-Builder-Info` notice
  would stop matching the cap it describes.
- Effect 2 is a **no-op when `q` is blank**, because the restricted map *is* the full map.
- Insertion must be **idempotent**: a pk already present (the author renamed a node so that it
  still matches) must not appear twice.

**Three views pass `extra_open`** — `node_add`, `node_move` (reparent) and `node_duplicate` —
all already wired in slice 1. Without effect 2, a mutation under an active filter returns a
scope *without* the row the author just created, indistinguishable from failure, on exactly the
path the reparent rule exists to protect.

### 3e. The no-JS force-include channel

`extra_open` exists only on **fragment** renders. A no-JS add, duplicate or reparent
**redirects**, and the following page GET re-derives the restricted map from `q` alone, knows
nothing of the created or moved pk, and that node's title will rarely match `q`. The author
lands on a filtered tree with their new node **absent** — on the path with the least feedback.

**Rule:** `node_add`, `node_duplicate` and `node_move` stash the created/moved pk in
`session["builder_force"][slug]` beside `builder_open`; `builder()` unions it into `extra_open`
for **exactly that next render**, then clears it. The stash reuses `remember_node`'s
per-slug bound (`SESSION_SLUG_LIMIT`), and holds a **chain**, not a bare pk — the same reason
`_persist_chain` exists on the `open` side.

A rename that moves a title out of the match set is the same case and is **not** covered: the
renamed row legitimately no longer matches. Recorded as a decision, not an oversight.

### 3f. `manage_tree` — a new GET endpoint

`…/build/tree/` → `_render_tree(request, course)`, behind `@login_required` + `_require_manage`.

Needed because `builder()` returns a full page and is the only builder view with no
`_wants_fragment` branch, and `manage_node_scope` is declared `<int:pk>` so it cannot serve the
top scope. Adding a fragment branch to `builder()` would silently change its contract for every
existing test that sends `X-Requested-With: fetch`.

It returns **the top scope `<ol data-scope="top">` and nothing else** — not `.builder__tree`
with its header, legend and helptext. `_render_tree` already does exactly this, and returning
more would break the single-`firstElementChild` contract `applyFragment` depends on.

Its URL reaches the JS as **`data-tree-url` on `.builder`**, emitted by `builder.html`,
matching every other JS-reachable endpoint in this design (`data-node-move-url`,
`data-node-scope-url`). It gets the same access-control row as `manage_node_scope`:
anonymous → login redirect, non-manager → 403, foreign slug → 404, manager → 200 with
`data-scope="top"`. Expand-all uses it too.

### 3g. The empty-scope message becomes filter-aware

`_scope.html`'s `{% empty %}` branch renders **"No children yet."** today. Under a filter that
matched nothing, the top scope hits that branch — so an author who mistypes a query is told
their **course** is empty. `_tree_context` gains a `filtered` flag and the branch reads:

```
{% if filtered %}No matching titles.{% else %}No children yet.{% endif %}
```

This applies to nested scopes too, where an empty scope under a filter has the same meaning.

### 3h. `X-Builder-Info` and the `info` slot

Two messages need a channel — slice 1's truncation notice and this slice's "showing 100 of
940" — and a scope fragment cannot carry either: it is a bare `<ol>` that `applyFragment`
consumes via `firstElementChild`.

**One function owns both renderings.** `_info_entries(opened, *, q_active, shown, total)`
returns a list of entries each carrying `key`, `text` and `code`; the template renders `text`,
and `_render_scope` joins the `code` values into the header. Two sources of truth here would
drift the moment a third notice is added.

| key | code | text |
| --- | --- | --- |
| `truncation` | `truncated;limit=500` | "Only the first 500 scopes were opened." |
| `filter` | `filtered;shown=100;total=940` | "Filtered: 100 / 940" |

Multiple codes join with `, `.

**The header must not carry the human string**, and this was measured on this repo's
Django 5.2.15 rather than assumed — Django encodes response header values as latin-1 with
`mime_encode=True`:

```
r['X-Builder-Info'] = 'Wyświetlono pierwsze 100 z 940 — widok jest niepełny'
r['X-Builder-Info'] → '=?utf-8?q?Wy=C5=9Bwietlono_pierwsze_100_z_940_=E2=80=94_widok_jest_niepe=C5=82ny?='
```

The JS would paste that literal token into a `role="status"` region. Every Polish message hits
this, and so does any English one containing an em dash. The human strings therefore live in
**`data-msg-truncated`** and **`data-msg-filtered`** on `.builder`, carrying `%(limit)s` /
`%(shown)s` / `%(total)s` placeholders the JS substitutes — matching the convention
`builder.js` already uses for `data-msg-conflict`, `data-msg-illegal` and `data-msg-network`.

**Both messages escape the "JS cannot pluralise Polish" constraint, and the wording must keep
it that way.** `limit` is the constant 500, so `data-msg-truncated` is pre-pluralised in the
catalog. `data-msg-filtered` is phrased so **no varying numeral governs a noun** —
"Filtered: 100 / 940", never "showing 100 results" — because the latter needs a plural form JS
cannot select.

**The `filter` entry is emitted whenever `q` is active**, including when `shown == total` and
when both are 0. "Filtered: 7 / 7" tells the author the view is filtered; "Filtered: 0 / 0"
over an empty tree is the only explanation they get. Emitting it only when capped would leave
the zero-match case unexplained.

**The same entry reaches the author by two routes, and both are required.** On a page render
(`builder()` / `_builder_with_notice()`, including any reload of a `?q=` URL) it goes into the
`info` slot as server-rendered markup carrying `data-info-key="filter"`. On a fragment it goes
into the header as `filtered;shown=…;total=…` and the JS renders it from `data-msg-filtered`.
One function produces both, so the two cannot disagree.

**`_render_scope` ALWAYS sets the header, emitting `none` when no codes apply.** This is a
deliberate change from the parent spec's "absent when none apply" plus "an absent header clears
all keys"; see Deltas for why the parent's pair is unimplementable. The JS rule becomes:

- header **absent** → the response is not a tree-pane response; **ignore entirely**
- header `none` → **clear all keys**
- header with codes → **replace by key** (an incoming entry replaces the entry with the same
  key rather than stacking)

Rename 200s (`_rename_result.html`), 422s (`_op_error.html`), unit-panel renames and both
panel fetches never reach `_render_scope`, so they carry no header and are inert **by
construction** — not by a call-site exclusion list that can drift. This matters concretely:
under a gesture-based rule, a rename would clear the filter notice on the single most common
authoring action, while the tree on screen is still filtered and capped.

**The slot is always in the DOM.** `builder.html` renders
`<ul class="builder__info" role="status" data-info hidden>` unconditionally, not behind
`{% if info %}` as slice 1 does — the JS needs somewhere to insert, and a slot that only exists
when the server put something in it means the first fragment-borne notice has no home. The JS
sets and clears the `hidden` attribute by child count.

**`[hidden]` needs an explicit `display: none`** in `builder.css` if `.builder__info` declares
any `display`, per this repo's recorded `.btn[hidden]` trap — the attribute loses to a class
rule of equal specificity.

The JS **reads the server-rendered `[data-info-key]` entries on init** so replace-and-clear
operate on them too. Without this the registry only knows entries it inserted itself, and the
path is routine: `history.replaceState` puts `q` in the address bar, so any reload while
filtered is a page GET rendering a server-side `filter` entry; the next toggle re-asserts
`filtered;…`, the JS finds nothing under key `filter` in its own registry, and appends a
**second** copy. The "two successive filter responses leave one entry" test must therefore
start from a `?q=` page load, or it passes vacuously against exactly this bug.

### 3i. `q` on the no-JS path

Per the parent's §4: every tree form carries a **hidden `q`** (a handful of bytes, unlike the
open enumeration), `{% toggle_href %}` preserves `q`, the six `open=session` redirect sites
append `q` when the mutation carried one, and `_builder_with_notice` re-renders under the
submitted `q`. Otherwise a no-JS author who filters and then renames a matched row lands on the
unfiltered tree — the "same gesture, two different trees" divergence the parent rejects.

The delete-confirm form already carries a hidden `open` (slice 1); it gains a hidden `q` the
same way, and its Cancel link preserves both.

## 4. The filter control

Sits in `.builder__tree`'s header row, after the title, beside the expand/collapse controls.

```html
<form class="builder__filter" method="get" action="{{ builder_url }}" data-filter>
  <input type="search" name="q" value="{{ q }}" ...>
  <button type="submit">Filter</button>
  {% if q %}<a href="{{ builder_url }}">Clear</a>{% endif %}
</form>
```

- **`method="get"`, no `data-op`.** `builder.js`'s submit handler gates on `form[data-op]`
  (`builder.js:216`, verified), so on the no-JS path this form falls straight through to the
  browser, and on the JS path it needs its own listener rather than an exclusion.
- **It carries no `open`.** Same rule as the JS filter fetch (§5b), and for the same reason:
  precedence step 2 would outrank step 3 and matches inside collapsed branches would never
  appear.
- `type="search"` gives Chromium a native clear affordance that fires `input`, so the JS path
  gets clearing for free; the explicit Clear link exists for the no-JS path and is rendered
  only when `q` is active.
- The no-JS **Clear** link is a plain GET with neither `q` nor `open`, so it lands on
  precedence steps 4–6. A no-JS author's pre-filter expansion is therefore **not** restored —
  there is no client to stash it and no session slot that means "what was open before the
  filter". Recorded as an accepted limitation of the no-JS path, not a defect.

Styling follows the repo's practice: token-driven CSS, no new component vocabulary, and the UI
is verified with Playwright screenshots in **both** light and dark before the PR, judged
separately rather than inferred from one another.

## 5. Client

### 5a. The collector carries `q`

`withOpen(body)` becomes the one helper that sets **both** `open` and `q` on every fragment
request. **Set, never append**: mutation forms already carry a hidden `q`, so appending would
put two values in the `FormData` and `QueryDict.get` returns the last — the collector would win
only by accident of ordering. The two genuinely differ during the 300 ms debounce, where the
hidden input holds the last *rendered* `q` and the input holds what is currently typed. **The
input's value is authoritative.**

`syncUrl` sets `q` when active and **deletes** it when not, so a cleared filter does not leave
`?q=` in the address bar. `open` keeps its existing rule: present-but-empty, never omitted.

### 5b. The filter fetch

- **300 ms debounce** after the last keystroke. Undebounced it would issue a full-tree render
  per keystroke — the exact cost profile this work exists to remove.
- **Plus a last-wins request id**, in the shape `loadPanel` already uses. The debounce does not
  prevent overlap: a slow request for `tr` can land after a fast one for `tryg`, leaving the
  pane showing results for a query the author has moved past. Debounce alone is a common and
  wrong answer here.
- The request goes to **`data-tree-url` with `q` and NO `open`.** Precedence step 2 outranks
  step 3, so a filter fetch carrying `open` would return only the scopes that happened to be
  open already, and a match three levels down inside a collapsed branch would never appear. The
  no-JS form (which carries no `open`) would work correctly, so the two paths would silently
  diverge on this slice's central promise.
- Wrapped in the parent §8 busy counter; `applyFragment` on the response; then the header handling of
  §3h and `syncUrl`.
- **Failure clears busy and surfaces `msg("network", …)`**, like every other fetch in the file.

### 5c. Below the floor takes the CLEAR path

The JS treats a below-`MIN_QUERY` query **exactly like an empty one** — stashed `open`, no `q`,
stash consumed. The floor therefore only ever saves a round trip on the way *into* a filter,
never on the way out.

Reading it as "just don't fetch below 2 characters" would leave filtered markup on screen while
the collector then sets `q=a` on the next toggle or mutation; the server treats that as blank
and returns **unfiltered** children into a **filtered** pane — precisely the defect the
"`q` rides every fragment request" rule exists to prevent.

### 5d. Clearing needs a request and a stash

"Restore the unfiltered tree" cannot be done client-side: the pane holds *filtered* markup with
the non-matching rows absent, and the author's pre-filter expansion no longer exists anywhere on
the client — the DOM collector now sees the filter's chains, and `replaceState` has already
overwritten the address bar with them.

So the filter handler **stashes the pre-filter open enumeration in a module-scoped variable
before its FIRST filter fetch**, and clearing issues a `manage_tree` request carrying that
stashed `open` and no `q`.

- **The stash is initialised to `null`, and the fallback tests `stash === null`, not
  falsiness.** A legitimately empty pre-filter set stashes as `""`, and `if (!stash)` would
  misread it as absent — so an author who had everything collapsed, filtered, then cleared
  would get the filter's chains open instead of the empty tree they started from. Same
  empty-vs-absent trap as `open` itself.
- **Refining a filter does not re-stash.** Only the transition unfiltered → filtered does.
- **The stash is discarded once consumed, and whenever a mutation happens while filtered** —
  the tree has changed underneath it.
- **If the stash really is absent, the clear request carries the collector's current
  enumeration — it never omits `open`.** Filter → mutate → clear is a normal authoring
  sequence and reaches the clear with no stash. Omitting `open` there would put the request on
  the fragment-absent path, i.e. the **empty set**, collapsing a large course to its 21 top rows
  and destroying every expansion the author had. Falling back to the collector is merely lossy
  (it returns the filter's chains rather than the pre-filter set), which is the right trade.

## 6. Expand-all and collapse-all

Two controls in `.builder__tree`'s header, beside the filter.

### 6a. Expand-all

An `<a>` whose `href` is the builder URL with `open=all` (plus `q` when filtered), so it works
without JS as a plain navigation. With JS: `preventDefault`, fetch `data-tree-url` with
`open=all` and `q`, behind the parent §8 busy affordance, `applyFragment`, then `syncUrl` — which
writes the resulting **enumeration** into the URL, since the collector can only ever emit one.

On `mat-pp` this still takes seconds (slice 1 measured `open=all` at 2,477 ms server-side).
That is inherent, and it is now an explicit, clearly-signalled choice rather than the default on
every visit.

**Above the 500-pk ceiling the control is disabled**, rather than silently expanding 500
arbitrary scopes behind a truncation notice. No course in the corpus is close — `mat-pp`, the
largest, has **137 containers** (measured) — so this is a guard, not a limitation anyone will
meet.

- **The server-side omission of `href` is the authoritative guard**: over the ceiling the
  control renders without `href`, with `aria-disabled="true"` and a `title` saying the course
  is too large to expand at once.
- The JS **also** bails on `data-container-count` (on `.builder`, as the parent spec names), so
  the guard does not depend on markup archaeology. Two mechanisms for one rule, deliberately:
  the attribute is what the JS reads, the missing `href` is what the browser obeys.

### 6b. Collapse-all — no request at all

`replaceState` writes the full enumeration after an expand-all, so without an inverse every
subsequent reload re-renders the whole tree and the only escape is hand-editing the address bar.
Collapse is already client-owned (parent §5), so this costs nothing:

- **JS:** remove every `ol.tree__scope[data-scope]:not([data-scope="top"])`; for each
  `[data-toggle]`, set `aria-expanded="false"`, remove `aria-controls`, and set `aria-label`
  from the server-rendered **`data-label-expand`** attribute; then `syncUrl`.
- **No-JS:** `href` is the builder URL with `open=` — **present-but-empty**, per parent §2's rule.
  Omitting the parameter would re-seed from the session and collapse nothing.

The `data-label-expand` / `data-label-collapse` pair already exists on every toggle
(`_tree_toggle.html`, verified), rendered server-side precisely because JS cannot select a
Polish plural form. Collapse-all reuses it rather than composing a string.

## 7. Deltas from the parent spec

Every point where this document overrides `2026-07-27-…-design.md`:

1. **`filtered_map(cmap, q)`, not `_filtered_map(course, cmap, q)`.** `course` is unused once
   matching is in-memory, and dropping it keeps `courses/builder_filter.py` free of DB access
   and view imports.
2. **`_render_scope` always sets `X-Builder-Info`, emitting `none` when no codes apply.** The
   parent pairs "absent when none apply" with "an absent header clears all keys", scoped to
   "responses that came through `_render_scope`". **The client cannot implement that pair.**
   The submit handler serves both a rename (`_rename_result.html`, no header, must **not**
   clear) and an add (a scope, no codes, **must** clear); those two responses are
   indistinguishable from the client's side. The `none` sentinel moves the distinction into the
   response, where it is observable. Same guarantee, checkable at the right boundary. The
   parent's "a response without the header clears it" test becomes "a `_render_scope` response
   with no applicable codes clears it".
3. **Diacritic-insensitive matching** — the parent says `title__icontains`, which is
   case-insensitive only. See §1b.
4. **Collapse-all** — the parent specifies expand-all with no inverse. See §6b.
5. **The filter-aware empty-scope message** — the parent leaves `{% empty %}` alone, which
   tells an author with a mistyped query that their course is empty. See §3g.
6. **The `info` slot is always in the DOM**, not behind `{% if info %}`. See §3h.
7. **`q_chain` is passed when `q` is active, not when the chain set is non-empty.** The parent
   does not distinguish them; on a ≤150-node course they diverge badly. See §3b.

## 8. Testing

Per this repo's practice, tests are written to fail first, and **a test that cannot go red is
treated as not written**. Every guard below is falsified by deleting what it protects,
requiring RED, and restoring. Slice 1 shipped two tests that passed while guarding nothing
until this was done.

**`courses/builder_filter.py` — unit, no DB:**

- `fold` maps `ą ć ę ł ń ó ś ź ż` and their capitals to ASCII; **the `ł` case is the one that
  a generic NFKD fold silently fails**, so it is asserted explicitly in both directions
  (`laka` finds `Łąka`; `Łąka` finds `laka`)
- the 2-char floor returns the map unchanged and empty chains, for `"a"`, `" a "` and `""`
- the cap keeps exactly `MATCH_CAP` in `(order, pk)` order, and `total` reports the pre-cap
  count — asserted with **scattered, non-sequential pks**, since CPython iterates small
  sequential ints in ascending order and a `sorted` → `list` mutation would stay green
  otherwise (slice 1 hit exactly this)
- the walk includes a matched **container itself**, and every ancestor level
- the restricted map preserves sibling order and groups top-level nodes under `None`

**View / integration:**

- **`manage_tree` access control**, the same five rows as `manage_node_scope`: anonymous →
  login redirect, non-manager → 403, foreign slug → 404, manager → 200 with `data-scope="top"`.
  **Not** "non-numeric pk → 404" — that route has no pk.
- **a filter request omits `open`**: with every scope collapsed, filtering for a title three
  levels down returns the match row
- **`q` rides every fragment request**: with a filter active, a rename 409, an add, a reorder,
  a duplicate and a drop each return **filtered** markup
- **an add or duplicate under an active filter returns its own new row visible** (effect 2),
  for a **unit** as well as a container — the unit case is the one that fails when the kind
  test is put at the call site
- **a no-JS add under a filter** shows the new row after the redirect (the `builder_force`
  session channel), with the session cleared between the page GET and the POST to prove the
  write carried a chain
- **`q_chain` on a ≤150-node course with zero matches** renders an **empty** tree, not a fully
  expanded one (§3b). Falsified by passing `None` instead of the empty set.
- **counts under a filter are the filtered counts**
- **an empty filtered scope says "No matching titles.", an empty unfiltered one says "No
  children yet."**
- **the `X-Builder-Info` header is machine-readable** — never a non-ASCII byte, never an
  RFC-2047 `=?utf-8?` prefix — asserted **under the Polish locale**
- **`none` is emitted when no codes apply**, and codes join with `, ` when both apply
- **a rename, a 422 and a panel fetch under an active filter carry no header at all**
- **a filtered mutation re-asserts `filtered;…`** — driven by an **add, reorder, duplicate or
  drop**, never a rename, whose success response never reaches `_render_scope`
- **the info slot replaces by key**: two successive filter responses leave one entry — the test
  **starts from a `?q=` page load**, or it passes vacuously against the registry bug in §3h
- **toggle hrefs preserve `q`**, and a no-JS mutation under a filter returns to the filtered
  tree
- **the builder view still issues one query** with a filter active
- **expand-all renders disabled above the ceiling** (`CEILING` monkeypatched down) and enabled
  below it, asserted on the **absence of `href`**, not on a CSS class

**e2e (`-m e2e` — mandatory, or the tests are silently deselected and pytest exits 5, which is
not a pass):**

- type a query, assert only matching and ancestor rows are present
- **expand a scope while `q` is active** and assert only matching/ancestor rows return
- **filter → clear restores the pre-filter expansion** (the stash), and **filter → mutate →
  clear leaves the tree non-empty** (the collector fallback)
- **collapse everything, filter, clear** — the tree comes back **empty**, not filled with the
  filter's chains (the `stash === null` rule; falsified by changing it to `if (!stash)`)
- **a below-floor query takes the clear path** — type `tryg`, then delete down to `t`, and
  assert the unfiltered tree is back rather than stale filtered markup
- **two rapid queries leave the later one's results** (the last-wins id; falsified by removing
  it)
- **expand-all then collapse-all** returns to the top rows, and the address bar holds `open=`
- collapse-all sets `aria-expanded="false"` and removes `aria-controls` on every toggle

**Manual, before the PR** — re-run `scripts/perf/`:

| Metric | Target | Prediction to check |
| --- | --- | --- |
| filter round trip on `mat-pp` | < 1 s | ~690 ms (≈221 rows) — the number most at risk |
| expand-all on `mat-pp` | busy visible throughout; no "Page unresponsive" | ~2.5 s server-side |
| toggle round trip | < 300 ms | **re-measure** — `_render_scope` now does the filter walk on every fragment |
| unfiltered page load | no regression on slice 1's 991 ms / 83 KB / 968 elements | — |

**The full-cmap rebuild in `_render_scope` is deliberately NOT optimised in this slice.** Slice
1 measured the toggle at 425 ms against a < 300 ms target and judged it a dev-server artifact
(page TTFB on the same DEBUG single-threaded harness is 438 ms; real server work is bounded at
~150 ms). Narrowing it would help only the *unfiltered* toggle — under a filter the full map is
required by both `_open_ids`'s sanitisation and the ancestor walk — and would fork the fragment
contract. Re-measure; if it misses in production, that narrowing is still the sanctioned first
remedy.

## 9. i18n

This slice adds roughly nine user-facing strings — the two `data-msg-*` templates, the two
`info` texts, "Filter", "Clear", "Expand all", "Collapse all", the over-ceiling tooltip and
"No matching titles." — so the catalog work is a task, not an afterthought:

- msgids in **both** catalogs (`pl` and `en`); regenerate with
  `makemessages -l pl -l en --no-obsolete`
- **clear every fuzzy entry**, which is two deletions per entry (`#, fuzzy` and `#| msgid`) —
  a fuzzy entry arrives **pre-filled with an unrelated translation**, so leaving one ships a
  wrong Polish string that reads as deliberate
- `.mo` is tracked and binary and has **no 3-way merge** — rebase onto master and regenerate
  with `compilemessages` immediately before the PR, never resolve a `.mo` conflict by hand
- `test_i18n_po_health.py` owns the whole-catalog guards and must stay green
- **no varying numeral may govern a noun** in `data-msg-filtered` or `data-msg-truncated`
  (§3h) — the JS substitutes placeholders and cannot select a Polish plural form

## 10. Slice-1 minors folded in

Deferred from PR #189's final review, fixed as one commit **after** the feature tasks are
green, so a bisect separates them from the feature:

- **M20** — a regression test for the "unit vanished mid-edit" 409 path
  (`_element_conflict`, `element_save`). The *behaviour* was decided in the parent's §4 as an
  accepted trade; only the coverage is missing.
- **M10** — `_persist_chain` re-runs `_children_map` on the no-JS redirect path.
- **M15** — `builder.js`'s `.catch` blocks also swallow errors thrown inside the success
  `.then`, mislabelling them "Network error". A shape shared by **every** handler in the file,
  so they are fixed together or not at all; this slice adds two more fetches, which is why now.
- **M16** — `swapping` latches true if `pointerup` never fires (window blur mid-press). A blur
  disarm is one line; `pointerFocus` has the same shape.

## 11. Out of scope

- **Matching anything but the title** — kind, unit type, slug, element content. Title is what
  an author navigates by.
- **Diacritic folding beyond Latin Extended-B**, and locale-aware collation generally. §1b's
  fold is Polish-complete; a future language adds a table entry, not a mechanism.
- **Server-side match highlighting.** The matched substring is not marked in the row title.
  Rows are `<input type="text">`, so highlighting would need either a parallel display element
  or contenteditable — a UI change out of proportion to a filter.
- **Persisting `q` in the session.** It rides the URL, which `replaceState` maintains, so a
  reload keeps it and a fresh visit does not.
- **Narrowing `_render_scope`'s cmap rebuild** — see §8 (Testing).
- **The N+1 in `_descendant_ids` / `_descendant_count` / `_element_count`** (measured 63–114
  queries), which slows the Move picker and the delete confirmation. A separate, small PR.
