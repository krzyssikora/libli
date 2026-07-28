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
def filtered_map(cmap, q) -> tuple[dict, set[int], int, int, bool]: ...
```

`filtered_map` returns `(restricted_cmap, chain_ids, shown, total, q_active)` and owns **all**
filter derivation: the fold, the match selection, the ancestor walk, the 100-cap and the
`(order, pk)` sort. `views_manage` imports it as `_filtered_map`, exactly as slice 1 aliased
`open_ids` → `_open_ids`.

**`q_active` is the fifth element, and nothing outside this module may re-derive it.** Four
consumers need to know whether the filter is on: §3b's `q_chain` decision, §3h's `filtered`
flag, §3i's `filter` entry (emitted even when `shown == total == 0`) and §4's Clear link. The
first four elements cannot express it — `chains=set(), shown=0, total=0` is returned both for
"below the floor, unfiltered" and for "active, matched nothing". The only alternative is to
re-test `len(q.strip()) >= MIN_QUERY` in the view, which is precisely the second copy of the
rule this module exists to prevent, and which would drift the moment the floor changes.

**`q_active` is not `bool(q)`.** A below-floor query (`?q=a`) is a *present* `q` that is
**inactive**: the tree renders unfiltered, no `filter` entry is emitted, and no `filter;…`
code appears in the header. The raw `q` still round-trips through the input's value, the hidden
form inputs and the URL, so the author sees what they typed — presentation and behaviour are
deliberately decoupled here.

**The returned map is always a fresh structure — a new outer dict whose values are new
lists — even on the blank path.** Returning `cmap` itself would make "restricted" and "full"
the *same object* on the most common path, at which point §3e's effect-2 insertion mutates the
map `_open_ids` and `_open_descendants` are reading from in the same request. §2 exists to keep
those two roles apart; aliasing them on the unfiltered path leaves a single line of code
between correct behaviour and a silent corruption that no filtered test would ever see. The
copy is ~944 appends on the largest course in the corpus.

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
stripping is **treated as blank**, and `filtered_map` returns
`(copy_of_cmap, set(), 0, 0, False)` — the unrestricted map, no chains, inactive.

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
`Łąka` folds to `łaka`, which `laka` does not match. Verified on this repo's Python 3.13 —
**the `folded` column is post-`casefold()`**, which is why `Ł` shows as `ł` rather than `Ł`
(NFKD alone leaves the case as it found it):

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
each match drags in up to 3 ancestors, so 100 × 4 = 400 sits under parent §2's 500-pk ceiling.

**The cap's own ordering drives the ancestor count toward the worst case, not away from it.**
It is tempting to argue that matched units *share* ancestors — `mat-pp`'s 807 units hang off
111 chapters, 21 parts and 5 sections — so 100 matches would drag in far fewer than 100
chapters. **That is backwards.** `order` is *sibling-local*, so a course-wide sort by
`("order", "pk")` takes every parent's first child before any parent's second child: it
systematically spreads the first 100 matches across as many distinct parents as possible. The
sort is kept anyway, because determinism is what the cap needs and clustering by chain would
make the cap depend on tree shape — but the fan-out it produces must be planned for, not
explained away.

**Expected case ≈ 226 rows** (100 matches + up to 100 chapters + 5 sections + 21 parts), and
that is the *expected* case, not a pessimistic one.

**The render-cost prediction is a LOWER BOUND, and the acceptance gate is the measurement, not
the prediction.** A naive extrapolation gives 226 rows × ~2.6 ms/row (slice 1's 2,477 ms /
944 rows) + 89 ms cmap + ~24 ms fold ≈ **700 ms**. That model is row-linear and this shape is
not: the 2.6 ms/row constant comes from an `open=all` render of 944 rows across 138 scopes
(0.15 scopes/row), whereas the filtered worst case is ~226 rows across up to ~126 scopes
(~0.56 scopes/row) — nearly the same *absolute* scope count as the full render. Per-scope work
is not free: `_scope.html` does four `{% url %}` reversals per scope plus an
`_add_affordance.html` include (which runs `legal_child_kinds`, `primary_child_kind` and
another reversal), and the filtered shape is far more container-heavy than the `open=all`
basis, so it pays proportionally more `{% blocktrans count %}` calls too. Treat 700 ms as the
floor, 1 s as the gate, and measure before believing either.

### 1d. What the filter does *not* do

**A matched container shows without its children.** Filtering for a chapter title returns that
chapter's row, whose count reads 0 and which expands to an empty scope. This is deliberate and
self-consistent: counts under a filter show the **filtered** count (see §3d), so a toggle never
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
| `_tree_context` → `_open_descendants` | **full** | It builds the descendant sets a *collapse* href subtracts. Over the restricted map, an open descendant the filter excluded would not be subtracted, so it would survive in the emitted `open` and spring back the moment the filter is cleared — breaking parent §4's "collapse forgets descendants, identically in both paths". |

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
def _filter_context(request, course, cmap, *, mode, extra_open=()) -> tuple[dict, OpenSet, int, int, bool]:
    """restricted cmap (effect 2 applied), the resolved OpenSet, shown, total, q_active."""
```

**`mode` is required and has no default.** The three callers need three *different* values —
`builder()` is `mode="page"`, `_builder_with_notice()` is `mode="notice"`, `_render_scope()` is
`mode="fragment"` — and the parent's §2 table makes those mutually exclusive. `open_ids`'s own
default is `"fragment"`, so a `mode`-less helper would silently put `builder()` on the fragment
row and destroy both the session seed and the ≤150-node rule, on the one path where they
matter. Keyword-only and defaultless, so the mistake is a `TypeError` rather than a wrong tree.

Without a named owner, the `q` read, the `q_active` test, the `_open_ids` call, effect 2 and
the `top_nodes` restriction would exist in three places — the drift the parent's
three-call-sites rule exists to prevent, reintroduced by the page/fragment split.

### 3b. `q_chain` is passed when `q` is ACTIVE, not when the chain set is non-empty

`open_ids` tests `if q_chain is not None`. So:

```python
q_chain = chains if q_active else None
```

**This is an invariant, not a bug fix, and the difference is currently unobservable in the
rendered HTML.** An earlier draft of this spec claimed that passing `None` with zero matches
would fall through to step 4 and expand a ≤150-node course "in full". That is **false**, and
tracing it is what makes the rule honest:

- `chains` is empty exactly when no container is rendered. `chains` contains every matched
  container plus every ancestor of every match, and the restricted map contains exactly the
  matches and those ancestors — so *the restricted map contains a container if and only if
  `chains` is non-empty*.
- With `chains` empty the restricted map holds at most top-level units, `open_ids`'s result is
  consumed only by `_tree_node.html`'s `{% if node.pk in open_ids %}` and by `toggle_href`, and
  neither runs without a container row. The two branches render byte-identical markup.
- Nor is there a side channel: both resolve `explicit=False`, so `_remember_open` is unaffected
  either way, and neither can trip `truncated` (step 4 fires only at ≤150 nodes, and a chain set
  is bounded at 400 — both far under `CEILING`).

The rule stays, for two reasons that are worth more than the false one: it keeps "an active
filter fully determines the open set" true at the function boundary rather than by luck of what
the template happens to render, and it is the invariant every later change would otherwise
break silently.

**Consequently the guard is a unit test on `open_ids`, not a render assertion.** Asserting on
the rendered tree would pass whatever the view passed — the vacuous-test shape this repo has
already shipped twice. See §8.

### 3c. `q` outranks the notice-mode session carrier — a slice-1 change this spec authorizes

`open_ids` currently reads the no-JS carrier **before** step 3 (`builder_open.py:151-157`,
then step 3 at `:159-161`). So whenever `session["builder_open"][slug]` exists — the normal
state for any author who has toggled anything on an earlier visit — a no-JS 409/422 re-render
under an active filter would resolve its open set from the stored **pre-filter** enumeration
and never see `q_chain`. The restricted map would be filtered while the chains stayed shut:
every match below the top level invisible, under a notice reading "Filtered: 12 / 12".

That is the "same gesture, two different trees" divergence the notice-mode carrier exists to
*prevent*, reintroduced by the filter.

**Rule: step 3 moves above the `mode == "notice"` carrier read.** `q` is an explicit signal in
the request being served; the carrier is a fallback for a request that carries no signal at
all. Filtered, the author gets the filtered tree with its chains open, whether the render came
from a success or from a conflict.

This edits `courses/builder_open.py`, which slice 1 shipped — named here so it is an
authorized change rather than an implementer's improvisation, and pinned by a test in §8.

### 3d. Counts

Counts under a filter show the **filtered** count, matching the restricted `cmap` the rows are
rendered from. `_tree_toggle.html` already derives its count from `children_map|get_item:node.pk`,
so passing the restricted map is all this takes — no template change.

### 3e. `extra_open` effect 2

After the restricted map is built, `_render_scope` re-inserts each `extra_open` pk's node —
resolved from the **full** cmap — into `restricted[node.parent_id]`, re-sorted by `(order, pk)`,
and therefore into `top_nodes` when `parent_id is None`.

- **Effect 2 applies to every pk regardless of kind**, units included. Effect 1 (the open-set
  union) keeps its container-only filter. Splitting the kind test **across the two effects
  rather than at the call site** is what makes two otherwise-unsatisfiable requirements
  compatible: a unit added under an active filter needs effect 2 or the row the author just
  created does not come back, while that same pk must not enter the open set.
- **Force-included rows do not count toward `shown`/`total`**, or the `X-Builder-Info` notice
  would stop matching the cap it describes. Pinned by a test — the rule is invisible in the
  markup and would otherwise rot.
- **Insertion must be idempotent.** A pk already present (the author renamed a node so it still
  matches, then added under it) must not appear twice. A duplicate is silent and nasty:
  `applyFragment` renders two `<li data-node="X">`, after which the DOM collector double-counts
  and `dragover`'s `:scope >` queries pick an arbitrary one. Pinned by a test.
- **Effect 2 changes nothing when `q` is inactive**, since the restricted map has the same
  contents as the full one — but it is **not** the same object (§1), so an insertion on the
  unfiltered path cannot corrupt the map `_open_ids` and `_open_descendants` read from. The
  no-op is a property of the contents, never a licence to alias the structures.

**Three views pass `extra_open`** — `node_add`, `node_move` (reparent) and `node_duplicate` —
all already wired in slice 1. Without effect 2, a mutation under an active filter returns a
scope *without* the row the author just created, indistinguishable from failure, on exactly the
path the reparent rule exists to protect.

### 3f. The no-JS force-include channel

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

**Consumed exactly once, and pinned as such.** The clear is the half that has no visible
symptom when it is missing: a stash that is never cleared passes the "the new row is present"
test *and* every other test in §8, while permanently pinning a stale pk into every filtered
render for that slug. §8 therefore asserts that a **second** builder GET no longer
force-includes it.

### 3g. `manage_tree` — a new GET endpoint

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

### 3h. The empty-scope message becomes filter-aware

`_scope.html`'s `{% empty %}` branch renders **"No children yet."** today. Under a filter that
matched nothing, the top scope hits that branch — so an author who mistypes a query is told
their **course** is empty. `_tree_context` gains a `filtered` flag and the branch reads:

```
{% if filtered %}No matching titles.{% else %}No children yet.{% endif %}
```

This applies to nested scopes too, where an empty scope under a filter has the same meaning.

### 3i. `X-Builder-Info` and the `info` slot

Two messages need a channel — slice 1's truncation notice and this slice's "showing 100 of
940" — and a scope fragment cannot carry either: it is a bare `<ol>` that `applyFragment`
consumes via `firstElementChild`.

**One function owns both renderings.** `_info_entries(opened, *, q_active, shown, total)`
returns a list of entries each carrying `key`, `text` and `code`; the template renders `text`,
and `_render_scope` joins the `code` values into the header. Two sources of truth here would
drift the moment a third notice is added.

**One word per concept, across all three vocabularies.** The key, the code prefix and the
`data-msg-*` suffix are the **same token** — `truncation` and `filter`:

| key = code prefix = `data-msg-` suffix | code | text |
| --- | --- | --- |
| `truncation` | `truncation;limit=500` | "Only the first 500 scopes were opened." |
| `filter` | `filter;shown=100;total=940` | "Filtered: 100 / 940" |

An earlier draft had three parallel vocabularies — keys `truncation`/`filter`, codes
`truncated`/`filtered`, attributes `data-msg-truncated`/`data-msg-filtered` — which forces the
JS to carry a prefix→key map that was written down nowhere. A natural implementation keys the
registry off the code prefix, never matches the server-rendered `data-info-key="truncation"`
entry, and appends a duplicate: precisely the bug the "read the server-rendered entries on
init" rule below exists to close, reintroduced by naming. **The `data-msg-*` attributes are
therefore `data-msg-truncation` and `data-msg-filter`**, renamed from the parent spec's
`data-msg-truncated` / `data-msg-filtered`; see Deltas.

**Header grammar**, stated because the JS has to parse it:

```
X-Builder-Info := "none" | entry ( ", " entry )*
entry          := key ( ";" name "=" value )*
```

`key` matches the info key exactly. Values are ASCII digits in every code this slice defines.
Parsing is: split on `", "`; for each entry split on `";"`; the first token is the key; each
remaining token splits once on `"="` into a placeholder name and its value. `none` is a
reserved whole-header sentinel, never an entry, so it can never collide with a key.

**The header must not carry the human string**, and this was measured on this repo's
Django 5.2.15 rather than assumed — Django encodes response header values as latin-1 with
`mime_encode=True`:

```
r['X-Builder-Info'] = 'Wyświetlono pierwsze 100 z 940 — widok jest niepełny'
r['X-Builder-Info'] → '=?utf-8?q?Wy=C5=9Bwietlono_pierwsze_100_z_940_=E2=80=94_widok_jest_niepe=C5=82ny?='
```

The JS would paste that literal token into a `role="status"` region. Every Polish message hits
this, and so does any English one containing an em dash. The human strings therefore live in
**`data-msg-truncation`** and **`data-msg-filter`** on `.builder`, carrying `%(limit)s` /
`%(shown)s` / `%(total)s` placeholders the JS substitutes — matching the convention
`builder.js` already uses for `data-msg-conflict`, `data-msg-illegal` and `data-msg-network`.

**Both messages escape the "JS cannot pluralise Polish" constraint, and the wording must keep
it that way.** `limit` is the constant 500, so `data-msg-truncation` is pre-pluralised in the
catalog. `data-msg-filter` is phrased so **no varying numeral governs a noun** —
"Filtered: 100 / 940", never "showing 100 results" — because the latter needs a plural form JS
cannot select.

**The `filter` entry is emitted whenever `q` is active**, including when `shown == total` and
when both are 0. "Filtered: 7 / 7" tells the author the view is filtered; "Filtered: 0 / 0"
over an empty tree is the only explanation they get. Emitting it only when capped would leave
the zero-match case unexplained.

**The same entry reaches the author by two routes, and both are required.** On a page render
(`builder()` / `_builder_with_notice()`, including any reload of a `?q=` URL) it goes into the
`info` slot as server-rendered markup carrying `data-info-key="filter"`. On a fragment it goes
into the header as `filter;shown=…;total=…` and the JS renders it from `data-msg-filter`.
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
`filter;…`, the JS finds nothing under key `filter` in its own registry, and appends a
**second** copy. The "two successive filter responses leave one entry" test must therefore
start from a `?q=` page load, or it passes vacuously against exactly this bug.

### 3j. `q` on the no-JS path

Per the parent's §4: every tree form carries a **hidden `q`** (a handful of bytes, unlike the
open enumeration), `{% toggle_href %}` preserves `q`, the six `open=session` redirect sites
append `q` when the mutation carried one, and `_builder_with_notice` re-renders under the
submitted `q`. Otherwise a no-JS author who filters and then renames a matched row lands on the
unfiltered tree — the "same gesture, two different trees" divergence the parent rejects.

**`q` is value-gated, never presence-gated — the opposite of `open`.** The delete-confirm form
carries a hidden `open` behind an `open_present` flag (`views_manage.py:654`, and
`node_confirm_delete.html`'s `{% if open_present %}`), because absent-vs-empty is meaningful
for `open`. It is **not** for `q` (§1a). So the delete form's `q` renders under a plain
`{% if q %}`, and adding a `q_present` twin would be a flag nothing consumes. The Cancel link
needs its own `q`: its existing `{% if open_present %}?open=…{% else %}?open=session{% endif %}`
structure has no slot for one.

**Four carrier sites are easy to miss because they are markup hrefs or a bespoke redirect, not
forms**, and each is named so the "every tree form carries a hidden `q`" rule is not read as
covering them:

1. **The delete href** in `_tree_node.html` (`{{ delete_url }}?node={{ node.pk }}`) must carry
   `&q=` **in the markup** — without JS there is no click-time rewrite.
2. **The Move link** in `_tree_node.html` (`{{ move_url }}?node={{ node.pk }}`), same reason.
3. **`node_delete`'s no-JS success branch builds its own redirect** — `views_manage.py:671-674`
   constructs `redirect(f"{url}?{urlencode({'open': …})}")` rather than going through
   `_redirect_to_builder`, so it is **not** one of the six sites and needs its own edit. Verified
   against the current source.
4. **The whole Move-picker chain**, which parent §2 (`:683-701`) pins separately precisely
   because the picker is a separate page and not an in-tree form: the Move link's href carries
   `&q=`, the `[data-move]` fetch appends the live `q`, `node_move`'s GET puts it in the picker
   context, `_move_picker.html`'s reparent form carries it as a hidden input, and the reparent
   redirect emits `open=session` **plus** `q`. The picker has no first hop from the "every tree
   form" rule, and parent §8 carves the `[data-move]` fetch out of the collector, so nothing
   else would supply it.

### 3k. `_tree_context` grows three keys — stated once, not patched three times

`toggle_href` reads everything from the template context, and the sole producer of those keys
is `_tree_context(course, cmap, ids)` — whose docstring says "Takes no `request`: everything it
needs is already resolved". This slice needs three more context values in every renderer:

| key | consumer | source |
| --- | --- | --- |
| `q` | `toggle_href`, the hidden inputs, the delete/Move hrefs, the filter input's value | the **raw** submitted `q`, not the normalized one |
| `filtered` | `_scope.html`'s `{% empty %}` branch (§3h) | `q_active` |
| `container_count` | `data-container-count` on `.builder`, and the expand-all disabled state (§6a) | `len(container_pks(full_cmap))` |

They go into `_tree_context`'s signature — which therefore gains the arguments to compute
them — **not** into three hand-patched render calls. Three renderers exist (`builder()`,
`_builder_with_notice()`, `_render_scope()`), and `_tree_context` exists specifically to stop
them drifting; adding keys at the call sites re-opens exactly that.

### 3l. `_remember_open` must not write while a filter is active

Parent §2 (`:616-617`) pins: **"`builder()` writes `builder_open` only when the set came from an
explicit `open` (steps 1–2) AND `q` is absent from the request."** Slice 1 could implement only
the first half — `_remember_open` (`views_manage.py:218-239`) gates on `opened.explicit` alone,
because `q` did not exist yet. **This slice is the only place the second half can be written**,
and it is easy to skip because nothing in slice 1 looks unfinished.

The failure it prevents is permanent and silent: a no-JS author filters, then clicks a toggle
whose href carries `open = <the filter's chains> ± pk`. That arrives via precedence step 2 as
`explicit=True`, and `_remember_open` writes the **derived filter chains** over the author's
real pre-filter expansion. The no-JS path has no stash, so nothing can restore it.

**Rule: `_remember_open` no-ops whenever `q` is active.** Gate on `q_active`, not on `"q" in
request.GET` — a below-floor `?q=a` renders unfiltered, so its `open` is a genuine
author-chosen set and suppressing the write would lose it.

The pinned test must go through **a toggle under an active filter**, not a bare filtered GET: a
bare GET resolves via step 3, which is not `explicit`, so the write is already suppressed and
the test would pass without the rule.

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

### 5a. `q` rides FOUR request paths, and `withOpen` reaches only two of them

**Set, never append**: mutation forms already carry a hidden `q`, so appending would put two
values in the `FormData` and `QueryDict.get` returns the last — the collector would win only by
accident of ordering. The two genuinely differ during the 300 ms debounce, where the hidden
input holds the last *rendered* `q` and the input holds what is currently typed. **The filter
input's value is authoritative.**

**`withOpen` (`builder.js:110`) is called from exactly two sites** — the submit handler
(`:240`) and the drop handler (`:638`). Saying "`withOpen` sets `q` on every fragment request"
is therefore **false**, and the gap is the worst possible one: **the toggle builds its own
query string** (`builder.js:487-490`, verified) —

```js
var body = new URLSearchParams();
var open = collectOpen();
body.set("open", open ? open + "," + pk : pk);        // needs open + pk, not the bare collector value
fetch(scopeUrlFor(pk) + "?" + body.toString(), …)
```

— so an implementer following the earlier wording ships a toggle that carries no `q` at all.
The toggle is the most common fragment request and the subject of this slice's own e2e, and
the result is exactly the defect §5c exists to prevent: unfiltered children arriving into a
filtered pane.

**Rule: all four paths set `q` from the filter input, and each is named.**

| path | site | how it carries `open` |
| --- | --- | --- |
| mutation submit | `builder.js:240` via `withOpen` | collector |
| drop | `builder.js:638` via `withOpen` | collector |
| **toggle expand** | `builder.js:487-490`, its own `URLSearchParams` | collector **+ this pk** |
| filter / expand-all / clear | new, §5b and §6 | omitted, `all`, or the stash |

The cleanest shape is one `setTreeParams(target, {openOverride})` helper used by all four, with
the toggle passing its `open + pk` as the override; whatever the shape, **`q` must not be
supplied by `withOpen` alone**. §8 pins a test that the toggle request carries `q`.

`syncUrl` sets `q` when active and **deletes** it when not, so a cleared filter does not leave
`?q=` in the address bar. `open` keeps its existing rule: present-but-empty, never omitted.

**The toggle's `.then` chain has to be reshaped to read a header at all.** It currently does
`.then(function (r) { if (r.status !== 200) throw …; return r.text(); })` (`builder.js:492-495`),
which discards the `Response` before the body is available — so §3i's header handling is
unreachable there without adopting the nested `r.text().then(…)` form the submit and drop
handlers already use. This is a real edit, it touches the same chains as **M15** in §10, and
the two are done together rather than twice.

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
  §3i and `syncUrl`.
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
  the tree has changed underneath it. **The two discard sites are the submit handler
  (`builder.js:215`) and the drop handler (`:618`)**, neither of which otherwise knows the
  stash exists; naming them is what stops the rule being implemented in whichever handler the
  implementer happened to be editing. The e2e must assert the **fallback was used** (the
  cleared tree still shows the row the mutation created), because a stale stash and a correct
  fallback both produce a merely non-empty tree.
- **If the stash really is absent, the clear request carries the collector's current
  enumeration — it never omits `open`.** Filter → mutate → clear is a normal authoring
  sequence and reaches the clear with no stash. Omitting `open` there would put the request on
  the fragment-absent path, i.e. the **empty set**, collapsing a large course to its 21 top rows
  and destroying every expansion the author had. Falling back to the collector is merely lossy
  (it returns the filter's chains rather than the pre-filter set), which is the right trade.

## 6. Expand-all and collapse-all

Two controls in `.builder__tree`'s header, beside the filter.

### 6z. Both are inert while a filter is active

Under a filter, **every visible container is already open** — the restricted map contains only
matches and their ancestors, and `chains` contains every one of those containers by
construction (§3b). So the two controls degrade into nonsense:

- **Expand-all** sets `open=all`, precedence step 2 wins, every container opens — but the
  response still renders from the restricted map, where nothing was closed. The author pays a
  multi-second round trip and a busy state for a **visually identical tree**.
- **Collapse-all** removes every scope below the top, i.e. hides **every match**, and then
  `syncUrl` writes `open=` while keeping `q`. The next toggle or mutation sends `open=` + `q`,
  step 2 wins again, and the matches stay invisible until the filter is cleared and re-applied
  — leaving the author staring at 21 top rows under a notice reading "Filtered: 100 / 940".

**Rule: while `q` is active, both controls are disabled** — `aria-disabled="true"`, no `href`,
and a `title` explaining that the filter already decides what is open. The server renders them
that way when it renders with an active `q`; the JS sets and clears the same state when the
filter is applied and cleared client-side, so the two paths agree without a page render.

This is the same disabled treatment §6a gives the over-ceiling case, so there is one disabled
state to style and one to test, not two.

### 6a. Expand-all

An `<a>` whose `href` is the builder URL with `open=all` (and `q`, though under an active
filter it is disabled per §6z — the parameter is carried so the markup rule is uniform), so it
works without JS as a plain navigation. With JS: `preventDefault`, fetch `data-tree-url` with
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
- **No-JS:** `href` is the builder URL with `open=` — **present-but-empty**, per parent §2's
  rule. Omitting the parameter would re-seed from the session and collapse nothing. **It
  carries `q` too**, symmetrically with §6a.

**Both hrefs carry `q` whenever they are emitted at all**, even though §6z disables the
controls under an *active* filter. The case that remains is a **present-but-inactive** `q` — a
below-floor `?q=a`, where the controls are live and the raw query must survive the navigation
so the author's half-typed text is still in the box when the page comes back. One rule ("tree
hrefs carry `q`") beats a carve-out, and it keeps these two hrefs consistent with the toggle,
delete and Move hrefs in §3j.

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
   tells an author with a mistyped query that their course is empty. See §3h.
6. **The `info` slot is always in the DOM**, not behind `{% if info %}`. See §3i.
7. **`q_chain` is passed when `q` is active, not when the chain set is non-empty.** The parent
   does not distinguish them. Kept as an invariant, but **not** on the grounds an earlier draft
   claimed — the two are currently indistinguishable in the rendered markup. See §3b.
8. **`data-msg-truncation` / `data-msg-filter`**, renamed from the parent's
   `data-msg-truncated` / `data-msg-filtered`, so the info key, the header code prefix and the
   message attribute are one token instead of three near-synonyms the JS must map between. See
   §3i.
9. **Step 3 moves above the `mode == "notice"` carrier read in `builder_open.open_ids`** — a
   change to code slice 1 shipped. Without it a no-JS conflict re-render under a filter shows a
   filtered map with unfiltered chains, i.e. matches invisible. See §3c.
10. **`_remember_open` no-ops while `q` is active.** The parent *pins* this rule (`:616-617`)
    but slice 1 could not implement it, and it is not a "still holds" item — it is unwritten
    code that only this slice can write. See §3l.
11. **Both bulk controls are disabled while a filter is active.** The parent specifies
    expand-all unconditionally; under a filter it is a no-op that costs seconds, and
    collapse-all hides every match. See §6z.

## 8. Testing

Per this repo's practice, tests are written to fail first, and **a test that cannot go red is
treated as not written**. Every guard below is falsified by deleting what it protects,
requiring RED, and restoring. Slice 1 shipped two tests that passed while guarding nothing
until this was done.

**`courses/builder_filter.py` — unit, no DB:**

- `fold` maps `ą ć ę ł ń ó ś ź ż` and their capitals to ASCII; **the `ł` case is the one that
  a generic NFKD fold silently fails**, so it is asserted explicitly in both directions
  (`laka` finds `Łąka`; `Łąka` finds `laka`)
- the 2-char floor returns the map unchanged, empty chains and **`q_active is False`**, for
  `"a"`, `" a "` and `""`; an at-floor `"ab"` returns `q_active is True` **even when it matches
  nothing** — the distinction the fifth return value exists for
- **the returned map is never the argument**: `assert restricted is not cmap` and
  `restricted[parent] is not cmap[parent]`, on the **blank** path — the alias §1 forbids, and
  the one that no filtered test can catch
- **`q_chain` matters at the function boundary**: `open_ids(..., q_chain=set())` on a
  ≤150-node fixture returns an **empty** set while `q_chain=None` returns every container.
  This is the §3b guard; it is a unit test on `open_ids`, **not** a render assertion, because
  the two are indistinguishable in markup (§3b) and a render test would pass vacuously
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
  write carried a chain — **and a second builder GET no longer force-includes it**, which is
  the half with no visible symptom when the clear is missing
- **force-inclusion is idempotent**: forcing a pk that the filter already matched yields
  exactly **one** `<li data-node=…>` for it
- **a force-included row does not move `shown`/`total`** in the emitted header
- **counts under a filter are the filtered counts**
- **`_builder_with_notice` under an active filter, with `builder_open` populated**, returns the
  filter's chains open — the §3c ordering. Falsified by moving step 3 back below the
  notice-mode carrier read; this test is the only thing standing between that reordering and a
  silent regression.
- **`_remember_open` does not write while `q` is active** (§3l) — driven through **a toggle
  under an active filter**, asserted **on the session**, never on the render. A bare filtered
  GET resolves via step 3, which is not `explicit`, so it would pass without the rule.
- **a below-floor `?q=a` renders unfiltered markup**, with **no** `data-info-key="filter"`
  entry and `X-Builder-Info: none` — the view-level twin of the unit floor test, and the one
  that catches a `q_active` derived from `bool(q.strip())`
- **an empty filtered scope says "No matching titles.", an empty unfiltered one says "No
  children yet."**
- **the `X-Builder-Info` header is machine-readable** — never a non-ASCII byte, never an
  RFC-2047 `=?utf-8?` prefix — asserted **under the Polish locale**
- **`none` is emitted when no codes apply**, and codes join with `, ` when both apply
- **a rename, a 422 and a panel fetch under an active filter carry no header at all**
- **a filtered mutation re-asserts `filter;…`** — driven by an **add, reorder, duplicate or
  drop**, never a rename, whose success response never reaches `_render_scope`
- **the info slot replaces by key**: two successive filter responses leave one entry — the test
  **starts from a `?q=` page load**, or it passes vacuously against the registry bug in §3i
- **toggle hrefs preserve `q`**, and a no-JS mutation under a filter returns to the filtered
  tree
- **the four no-form carriers of §3j**: the delete href and the Move href carry `&q=` **in the
  markup**; `node_delete`'s own no-JS redirect (`views_manage.py:671-674`, not one of the six
  `open=session` sites) carries `q`; and the no-JS Move-picker round trip lands back on the
  filtered tree
- **the builder view still issues one query** with a filter active
- **expand-all renders disabled above the ceiling** (`CEILING` monkeypatched down) and enabled
  below it, asserted on the **absence of `href`**, not on a CSS class
- **both bulk controls render disabled under an active filter** and live without one (§6z)
- **both bulk-control hrefs carry a present-but-inactive `q`** (`?q=a`), so a below-floor query
  survives the navigation

**e2e (`-m e2e` — mandatory, or the tests are silently deselected and pytest exits 5, which is
not a pass):**

- type a query, assert only matching and ancestor rows are present
- **expand a scope while `q` is active** and assert only matching/ancestor rows return —
  **and that the toggle's own request carried `q`** (§5a; falsified by reverting the toggle to
  `withOpen`-less parameter building, which is how the defect would actually reappear)
- **filter → clear restores the pre-filter expansion** (the stash), and **filter → mutate →
  clear** lands on the **collector fallback** — asserted by the *created row* still being
  present, not merely by the tree being non-empty, since a stale stash produces that too
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
| filter round trip on `mat-pp` | < 1 s | ≥ 700 ms (≈226 rows across ~126 scopes) — a **lower bound** from a row-linear model that under-counts per-scope work (§1c); the number most at risk |
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
- **no varying numeral may govern a noun** in `data-msg-filter` or `data-msg-truncation`
  (§3i) — the JS substitutes placeholders and cannot select a Polish plural form

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
  **Sequenced with §5a's toggle reshape**: making the toggle keep its `Response` in scope for
  §3i's header touches the same `.then` chain, so the two edits are done in one pass rather
  than rewriting the chain twice.
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
