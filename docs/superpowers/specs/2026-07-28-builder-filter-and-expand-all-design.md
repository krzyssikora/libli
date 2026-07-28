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
MIN_QUERY = 2      # chars of the FOLDED query, after stripping -- see 1a
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
flag, §3i's `filter` entry (emitted even when `shown == total == 0`) and §3l's
`_remember_open` gate. **§4's Clear link is deliberately NOT one of them** — it reads the raw
`q`, so a below-floor `?q=a` still offers a way to empty the box. The first four elements
cannot express it — `chains=set(), shown=0, total=0` is returned both for
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

`q` is stripped of leading and trailing whitespace. A query whose **folded** length is shorter
than `MIN_QUERY` is **treated as blank**, and `filtered_map` returns
`(copy_of_cmap, set(), 0, 0, False)` — the unrestricted map, no chains, inactive.

**The floor counts `len(fold(q.strip()))`, not `len(q.strip())`.** Code points and folded
characters are not the same thing, and the gap is reachable from the same source §1b's NFD
handling exists for: a decomposed `ą` pasted out of imported HTML is **two** code points
(measured) that fold to the single character `a`. Counting raw length lets it clear the floor
and produce the hundreds-of-matches → 100-cap → ~226-row render the floor exists to block — on
the one path (`?q=` by hand, or a no-JS submit) that has no debounce to soften it. Folding
first also keeps the floor consistent with what is actually matched.

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

**Implementation: one `str.translate` table, built once at import.**

```python
def fold(s):
    return s.translate(_FOLD_TABLE).casefold()
```

The table is built at import from three sources:

1. **U+00C0–U+024F** (Latin-1 Supplement through Latin Extended-B) decomposed via NFKD, keeping
   the entries whose stripped base is ASCII — 259 entries.
2. **`ł → l`, `Ł → L`** — the two characters NFKD cannot reach.
3. **U+0300–U+036F → deleted** (Combining Diacritical Marks) — 112 entries. **Without this the
   table silently fails on decomposed input**, and that is a correctness bug, not a nicety:

```
fold(unicodedata.normalize("NFD", "Kąty"))   table without (3) -> 'kąty'   "katy" does NOT match
                                             table with (3)    -> 'katy'   matches
```

A precomposed `ą` (U+0105) is one table hit; a decomposed `a` + U+0328 is a base character the
table leaves alone plus a combining mark it deletes. Both land on `a`. This matters here
specifically: ~797 of this corpus's units were imported from external HTML, which is exactly
where NFD-normalized text arrives, and a title stored decomposed would be unfindable with no
symptom other than "the filter doesn't work for that one node".

**373 entries, ~1.5–2.7 ms to build, once per process.**

`translate` runs **before** `casefold` so the table can carry both cases; folding first would
turn `Ł` into `ł` and need only one entry, but stating the order here removes the ambiguity.

**Cost: the ratio is stable, the absolute numbers are not, and only the ratio is recorded.**
Three attempts to pin absolutes for 944 titles produced 8.7 / 11.8 / 24.1 ms for the same
variant, because the dominant variable was never held fixed: **diacritic density**. Re-measured
deliberately, 15 repetitions, CPython 3.13, 944 titles of mean length ~42:

| corpus | `str.translate` (sources 1–3) | NFKD + drop combining marks |
| --- | --- | --- |
| diacritic-heavy (every title) | 24.1 ms best | 32.4 ms best |
| ~5 % of titles carry a diacritic | 9.4 ms best | 21.8 ms best |

So: **the table is 1.3–2.3× faster than the NFKD pass**, and both are tens of milliseconds
against a ~700 ms render. Real Polish titles sit between these corpora.

**The table is not chosen for speed at all** — it is chosen because it handles NFD input in the
same single pass (§1b's third source), and because what folds is an explicit, inspectable table
rather than a property of whichever Unicode version ships with the interpreter. Any absolute
number quoted here should be treated as an order of magnitude; the ratio is the reproducible
part.

**The fold is Polish-complete, not Unicode-complete**, and that is the intended scope. `ß`
folds to `ss` via `casefold` (a Python guarantee, not our table); `ø`, `đ` and `ħ` have no
decomposition and are not in the explicit pairs, so they do not fold. No course in the corpus
contains them. A future language adds a pair, not a mechanism.

### 1c. Matching, the cap and the walk

- **Matches** are the nodes — **every kind, units included** — whose folded title contains
  **`needle = fold(q.strip())`**. One value, computed once, used for **both** the floor test
  (§1a) and the containment test. Folding without stripping first would let `"ab "` — a
  trailing space is routine on paste — clear the floor as a 3-character query and then match no
  title at all, so the author gets "Filtered: 0 / 0" on a query that should hit.
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
944 rows) + 89 ms cmap + 10–25 ms fold ≈ **700 ms**. That model is row-linear and this shape is
not: the 2.6 ms/row constant comes from an `open=all` render of 944 rows across 138 scopes
(0.15 scopes/row), whereas the filtered worst case is ~226 rows across up to ~126 scopes
(~0.56 scopes/row) — nearly the same *absolute* scope count as the full render. Per-scope work
is not free: `_scope.html` does four `{% url %}` reversals per scope plus an
`_add_affordance.html` include (which runs `legal_child_kinds`, `primary_child_kind` and
another reversal), and the filtered shape is far more container-heavy than the `open=all`
basis, so it pays proportionally more `{% blocktrans count %}` calls too. Treat 700 ms as the
floor, 1 s as the gate, and measure before believing either.

### 1d. What the filter does *not* do

**A matched container shows without its NON-matching children.** Filtering for a chapter title
returns that chapter's row **already expanded** — §1c puts every matched container into
`chains`, so it renders open — over a scope holding **only its matching descendants**. When
none match, that scope is empty: "No matching titles." (§3h) plus the scope's add affordance,
and the toggle's count reads 0.

The count is **not** invariably 0, and saying so would be wrong: §1c keeps *every* match, so a
chapter whose title matches and one of whose units also matches renders that unit inside it and
counts 1. The rule is that the filter never *pulls in* a non-matching child — not that a matched
container is always childless.

Getting this wrong in either direction is easy, so both halves are pinned: the row is **not**
collapsed-awaiting-expansion (an earlier draft of this spec said it was, contradicting §1c and
producing different markup, a different accessible name — `data-label-collapse` vs
`data-label-expand` — and a different scope count for the render estimate), and its children are
**not** pulled in.

Excluding the children is deliberate and self-consistent: counts under a filter show the
**filtered** count (see §3d), so a toggle never promises children the filtered view will not
show, and the 100 × 4 = 400 arithmetic holds. The author clears the filter to navigate into the
hit. Including a match's own children would make the filtered count mean two different things
depending on whether the row itself matched, and would break the pk arithmetic (a matched
chapter can have 30 children).

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
@dataclass(frozen=True)
class FilterContext:
    cmap: dict           # RESTRICTED, effect 2 already applied
    opened: OpenSet      # the resolved set, UNTOUCHED -- what _remember_open reads
    open_ids: frozenset  # opened.ids | effect 1 -- what _tree_context renders from
    shown: int
    total: int
    q_active: bool
    q_raw: str           # exactly what the author submitted, unnormalized

def _filter_context(request, course, cmap, *, mode, extra_open=()) -> FilterContext: ...
```

**A record, not a tuple, because it carries seven things and grew twice during review.** Two of
them are easy to leave out and expensive to leave out:

- **`q_raw`.** `_filter_context` owns the `q` read (POST then GET, above). If it does not hand
  the raw value back, all three renderers must re-do `request.POST.get("q") or
  request.GET.get("q")` to populate §3k's `q` context key — reinstating the resolution rule in
  three places, which is the drift this helper exists to prevent. **No tree renderer may
  re-read `q` from the request** — `builder()`, `_builder_with_notice()` and `_render_scope()`
  take it from here. It is `q_raw`, not the normalized form, because the author's half-typed
  `?q=a` must survive into the input's value and every href (§1).

  **Eight non-rendering sites do need their own read, so the resolution rule itself lives in a
  named helper**, `_raw_q(request)` (POST then GET), which `_filter_context` calls too. They
  are the six `_redirect_to_builder` mutation sites (§3j), plus `node_delete`'s GET (for the
  confirm form's hidden input and its Cancel link) and `node_move`'s GET (for the picker
  context) — none of which render tree markup, so none can be served by `FilterContext`.
  Without the named helper the POST-then-GET rule really would be re-expressed nine times.
- **Both the pre-union and the post-union set**, because two consumers need different ones.
  `_render_scope` today keeps the force-union in a plain local
  (`ids = set(opened.ids) | _extra_container_pks(...)`), deliberately *outside* the frozen
  `OpenSet` — and that separation is load-bearing: `_tree_context` must render from the union,
  while `_remember_open` must read `opened` untouched, or `builder()` would persist forced-open
  pks as though the author had chosen them. (Writing a created node's chain to the session is a
  real requirement, but slice 1 already discharges it through its own `_persist_chain`;
  folding it into `_remember_open` as well would double-write.) Returning only one of the two
  sets pushes the union back out to three call sites.

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

- **Absent effect 2**, `chains` is empty exactly when no container is rendered: `chains`
  contains every matched container plus every ancestor of every match, and the restricted map
  contains exactly the matches and those ancestors — so the restricted map contains a container
  if and only if `chains` is non-empty. (Effect 2 is the one exception, and it cuts the other
  way: a force-included container **is** in the restricted map without being in `chains`, so
  with `extra_open` in play the two branches genuinely differ. That strengthens the rule rather
  than weakening it — it is simply not the justification an earlier draft claimed.)
- With `chains` empty the restricted map holds at most top-level units, `open_ids`'s result is
  consumed only by `_tree_node.html`'s `{% if node.pk in open_ids %}` and by `toggle_href`, and
  neither runs without a container row. The two branches render byte-identical markup.
- Nor is there a side channel. The two branches do **not** both resolve `explicit=False` —
  under §3c's ordering a `q_chain=None` request carrying `open=session` reaches the sentinel and
  returns `explicit=True` (`builder_open.py:141`) — but it does not matter, because
  `_remember_open` no-ops whenever `q` is active (§3l), so nothing can be persisted either way.
  Neither branch can trip `truncated` either (step 4 fires only at ≤150 nodes, and a chain set is
  bounded at 400 — both far under `CEILING`).

The rule stays, for two reasons that are worth more than the false one: it keeps "an active
filter fully determines the open set" true at the function boundary rather than by luck of what
the template happens to render, and it is the invariant every later change would otherwise
break silently.

**Consequently the guard is a unit test on `open_ids`, not a render assertion.** Asserting on
the rendered tree would pass whatever the view passed — the vacuous-test shape this repo has
already shipped twice. See §8.

### 3c. `q` outranks BOTH session-derived sources — a slice-1 change this spec authorizes

There are **two** places `open_ids` resolves from the session, and both currently run before
step 3. Fixing only one leaves the no-JS filtered author broken on the more common path.

| # | source | where | reached by |
| --- | --- | --- | --- |
| 1 | the `open=session` **sentinel** | `builder_open.py:138-142`, step 1 | every no-JS mutation **success** — the six redirects emit `?open=session` |
| 2 | the **notice carrier** | `builder_open.py:151-157` | every no-JS 409 / 422 re-render |

Both return the author's stored **pre-filter** enumeration and never consult `q_chain`, so a
no-JS author who filters and then renames, adds, reorders, duplicates or deletes lands on a map
that *is* filtered over chains that are *not* open: every match below the top level invisible,
under a notice reading "Filtered: 12 / 12". §3l makes this worse rather than better — suppressing
the write is exactly what keeps the stale pre-filter set alive to win.

**Rule: when `q` is active, step 3 beats both. It never beats step 2.**

```
step 2 (an explicit enumeration or `all`)   >   step 3 (the filter's chains)   >   the session
```

**This is a restructuring, not a relocation, and the required shape is stated here because
three of the four natural placements are wrong.** Step 1 and step 2 share one predicate —
`present`, from `_raw_open` — and step 1 *mutates* it (`present = False` when the stored key is
missing, so the sentinel falls through). Simply hoisting the `if q_chain is not None:` block
above both reads makes `?open=3,4&q=…` resolve to the **chains**, breaking "an explicit `open`
wins". Leaving `if present:` intact while moving the sentinel is worse: `open=session` then
reaches `_parse("session")`, which matches no digits and yields the **empty** set with
`explicit=True` — a silently collapsed tree that `_remember_open` would then persist.

The sentinel must be lifted out of step 2's test:

```python
sentinel = present and raw == "session" and mode == "page"

if present and not sentinel:          # step 2 -- an explicit value, including ""
    return _finalize(_parse(raw, containers), containers, explicit=True)

if q_chain is not None:               # step 3 -- the filter's chains
    return _finalize(q_chain, containers)

if sentinel:                          # step 1 -- the no-JS post-mutation sentinel
    stored = _stored_open(request, course.slug)
    if stored is not _MISSING:
        return _finalize(stored, containers, explicit=True)
                                      # missing/flushed -> fall through to 4-6

if mode == "notice":                  # the conflict/validation carrier
    ...
```

**In page mode, `raw == "session"` must never reach `_parse`** — it matches no digits, so it
would yield the empty set with `explicit=True`. In the other two modes the sentinel is `False`
by construction and `"session"` *does* fall through to `_parse`; that is unreachable in
practice (the sentinel is a GET-redirect marker and a fragment or notice render never carries
it) and must be left alone. **Do not "fix" it by dropping `mode == "page"` from `sentinel`**:
that would make a fragment call `_stored_open`, which the parent's mode table forbids outright
— a fragment must never read the session.

The fragment-mode early return stays **below** step 3, or a filter fetch — which omits `open` by
design (§5b) — would resolve to the empty set and render every match below the top level
invisible.

- **Above the session**, because `q` is a signal in the request being served, while both session
  reads are fallbacks for a request that carries no signal. Concretely, `open=session` is a
  *sentinel* meaning "restore what I had"; under an active filter the right answer to that is
  the filter's chains, not a set from before the filter existed.
- **Below step 2**, because that is the parent's "`q` seeds, a supplied `open` wins" rule, and
  it is what makes "filter, then toggle" work — a no-JS toggle href under a filter carries a
  real enumeration (`chains ± pk`), which must beat re-seeding.

The result is `explicit=False`: the chains are derived, not author-chosen, so nothing
downstream may persist them (§3l).

This edits `courses/builder_open.py`, which slice 1 shipped — named here so it is an authorized
change rather than an implementer's improvisation. §8 pins **both** paths: the notice re-render
*and* the mutation success, each with `builder_open` populated, since a test of only the first
leaves the second silently broken.

### 3d. Counts

Counts under a filter show the **filtered** count, matching the restricted `cmap` the rows are
rendered from. `_tree_toggle.html` already derives its count from `children_map|get_item:node.pk`,
so passing the restricted map is all this takes — no template change.

### 3e. `extra_open` effect 2

**`_filter_context` performs the re-insertion**, not `_render_scope`. Both `_render_scope` (from
its `extra_open` argument) and `builder()` (from the `builder_force` session channel, §3f) need
it, so placing it in the fragment renderer alone would leave the no-JS path without it. Each
renderer merely passes its own `extra_open` through.

**`_builder_with_notice` does NOT read `builder_force`.** A notice render follows a *failed*
mutation, so there is nothing created to force-include — and letting it read would leave the
single clear site undefined, with a 409 able to consume a stash `builder()` was about to use.
`builder()` is the sole reader and the sole clearer.

After the restricted map is built, each `extra_open` pk's node — resolved from the **full**
cmap — is re-inserted into **`restricted.setdefault(node.parent_id, [])`**, re-sorted by
`(order, pk)`, and therefore into `top_nodes` when `parent_id is None`.

**`setdefault`, not `restricted[...]`, and this is a 500 rather than a nicety.**
`_children_map` only creates a key for a parent that **has** children
(`views_manage.py:139-141`), and the restricted map is built by regrouping the kept nodes — so
a matched container with no matching descendants has **no key of its own**, and a filter that
matched nothing has no `None` key either. §1d makes both routine, and `_add_affordance.html`
renders unconditionally after `_scope.html`'s `{% empty %}` branch, so the author is *offered*
an add form inside exactly those empty scopes. "Filter for a chapter title, add a unit inside
it" and "filter matches nothing, add a top-level node" therefore both reach a missing key →
`KeyError` → 500. Every read site in this spec is already careful (`restricted.get(None, [])`,
`restricted.get(<scope key>, [])`); this is the one write site, and it needs the same care.

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

**It stores the UNFILTERED `_ancestor_chain(node)` — do NOT copy `_persist_chain`'s
intersection.** `_persist_chain` computes `_ancestor_chain(node) & container_pks(cmap)`
(`views_manage.py:419`), deliberately dropping the node's own pk when it is a unit, because it
feeds the *open* set and a unit owns no scope. `builder_force` feeds `extra_open`, whose effect
2 "applies to every pk regardless of kind, units included" (§3e). An implementer told to follow
`_persist_chain` copies the `& container_pks(...)`, the new unit's pk never reaches effect 2,
and a no-JS unit add under a filter returns a tree **without the row the author just created** —
the precise failure this section exists to close. The two channels feed different consumers and
must not share a filter.

**It stores a sorted `list[int]`, not the `set` that `_ancestor_chain` returns.** No
`SESSION_SERIALIZER` is configured, so Django 5.2 uses `JSONSerializer` and a `set` raises
`TypeError: Object of type set is not JSON serializable` — the parent spec measured this exact
failure on the sibling channel, and `_persist_chain` avoids it by passing `sorted(...)`
(`views_manage.py:428`). The rule above says which half of `_persist_chain` **not** to copy;
this is the half that must be. Same payload cap as `builder_open`.

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

**And one msgid owns each string.** The entry has a single owner, but the *human text* still
reaches the author by two routes — `_info_entries`'s `_(…)` on the page, `data-msg-<key>` on a
fragment — and if those are two catalog entries the same notice can be translated two different
ways, so the page and the fragment disagree about what the tree is showing. **The Python literal
and the template literal must be the same msgid**, placeholders included
(`"Filtered: %(shown)s / %(total)s"` in both; the server interpolates, the JS substitutes). That
is one catalog entry per key, not two, and §8 pins the two renderings against each other under
the Polish locale.

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

**The slot is always in the DOM, and it is NEVER `hidden`.** `builder.html` renders
`<ul class="builder__info" role="status" data-info>` unconditionally, not behind
`{% if info %}` as slice 1 does — the JS needs somewhere to insert, and a slot that only exists
when the server put something in it means the first fragment-borne notice has no home.

**It is hidden by `.builder__info:empty { display: none; }`, not by the `hidden` attribute.**
The reason is singular and sufficient: **a `hidden` attribute set at render time makes every
server-rendered notice invisible without JS.** Only the JS would ever remove it, so a no-JS
author who filters gets `data-info-key="filter"` in the DOM and sees nothing — and slice 1's
*shipped* truncation notice, visible today (`builder.html:23` has no `hidden`), silently
regresses on the same path. §3i's own rule is that the page route and the fragment route are
both required. With `:empty` the JS never touches visibility at all: it inserts and removes
entries, and the CSS follows. That also sidesteps this repo's recorded `.btn[hidden]` trap.

**`:empty` does not match an element containing whitespace, and this markup is one newline away
from a permanent grey bar.** Measured in Chromium: `<ul id="b">\n</ul>` reports
`matches(":empty") === false` and renders at 16 px. `.builder__info` carries `padding` and
`background: var(--surface-sunken)` (`builder.css:184-185`), so a slot written the natural
multi-line Django way shows a sunken bar on **every** builder page — permanently, because the
server's whitespace text nodes survive the JS's `<li>` removals, so a `none` header can never
re-hide it. **Rule: the `<ul>` and its `{% for %}` emit no whitespace inside the element**, as
`builder.html:23` already does today on one line. §8 asserts the computed style, not mere
presence.

**The rule binds the JS equally, because the JS is the element's other writer.** Any insertion
that leaves a text node — a multi-line `insertAdjacentHTML` string, a `join("\n")` — survives
the later `<li>` removals, so a subsequent `none` header can never re-hide the slot and the
sunken bar becomes permanent from the author's first filter onward. **The JS inserts and
removes only element nodes and never leaves a text node inside `.builder__info`.** Every
server-side `:empty` assertion is taken at page load, before the JS has written anything, so
this half needs its own falsification: after a filter → clear cycle, the slot must still match
`:empty`.

**Accepted limitation: the first fragment-borne notice may not be announced.** `display: none`
keeps the region out of the accessibility tree just as `hidden` does, so inserting a child and
rendering the region in the same task is not a reliable live-region trigger. An earlier draft
claimed `:empty` avoided this; it does not, and the claim is withdrawn rather than left as an
invariant the mechanism cannot deliver. Server-rendered notices — the common case, and the one
a no-JS author depends on — are unaffected, since they are in the DOM and rendered from the
start.

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

**"The six redirect sites" is one function with EIGHT callers.** All six mutation redirects go
through `_redirect_to_builder(course)` (`views_manage.py:398-401`), whose signature has no
access to `q` — so the edit is that helper plus its signature, not six edit points. But the
helper is also called by **`element_move` (`:861`) and `element_delete` (`:877`)**, which parent
§4 explicitly *excludes* from the `q` rule ("Three further `redirect(…)` sites are deliberately
excluded … All three stay on the seed path").

**So `q` is passed IN, not read inside.** The helper takes an explicit `q` argument defaulting
to blank; the six mutation sites pass the request's `q`, and the two element sites pass nothing
and keep their current behaviour. Reading `request` inside the helper would silently extend the
rule to two editor-originated redirects the parent scoped out — a change nobody asked for,
arriving through a signature.

**Every `q` in an href is percent-encoded — `{{ q|urlencode }}`, never bare `{{ q }}`.**
Django autoescapes HTML but does **not** percent-encode, and these are hand-built hrefs
(`{{ delete_url }}?node={{ node.pk }}`) rather than `urlencode` dicts like `toggle_href`
(`courses_manage_extras.py:244`) or the delete Cancel link's `{{ open|urlencode }}`
(`node_confirm_delete.html:18`). A query containing `&` therefore splits into a second
parameter — filtering for `x&open=all` makes the delete-confirm GET arrive with `open=all`
attached — and a `#` truncates the href outright. `_redirect_to_builder` builds its query with
`urlencode` for the same reason. Hidden inputs are unaffected: they are form values, not URLs.

**Every `q` carrier — hidden inputs, `{% toggle_href %}`, the delete and Move hrefs, and the
two bulk-control hrefs — omits the parameter entirely when `q` is blank**, rather than emitting
`&q=`. On an unfiltered `open=all` render that is one saved parameter on every container toggle
href and every form on the page.

**The hidden `q` is emitted under `{% if q %}`, in every tree form.** Unconditional emission
would add an empty hidden input to every rename, reorder, duplicate and add form on the page —
944 + 944 + 807 + 138 of them on `mat-pp` under `open=all`, on a page this work exists to
shrink. Because `q` is value-gated (below), an absent input and an empty one are the same
thing, so the conditional costs nothing.

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

   **And the JS rewrite at `builder.js:524-530` deliberately does NOT touch `q`**, unlike
   parent §4 (`:838`), which has it set "the live `open` **and `q`**" at click time. See Deltas.
   The markup value is already correct: every filter transition re-renders the whole top scope
   through `manage_tree`, so these hrefs carry the applied `q` by construction. Setting it at
   click time would add a sixth `q`-writing client path for no gain — and it is the one
   gesture that is a full-page navigation, so an implementation that reached for the live input
   value there could not be corrected by a later fragment.
2. **The Move link** in `_tree_node.html` (`{{ move_url }}?node={{ node.pk }}`), same reason.
3. **`node_delete`'s `open`-present branch builds its own redirect**, and it is the **JS**
   author's path, not the no-JS one. The code is `if "open" in request.POST:` (`:672`) →
   bespoke `redirect(f"{url}?{urlencode({'open': …})}")` (`:673-674`), `else` →
   `_redirect_to_builder(course)` (`:675`). A **no-JS** confirm POST carries no `open` — the
   hidden input renders only `{% if open_present %}`, and the no-JS delete href has no `open`
   in it — so it takes `:675`, one of the six. The bespoke branch is reached only when
   `builder.js:524-530` rewrote the delete href at click time. **A test driven as a no-JS
   delete therefore goes green the moment the six-site edit lands, while `:674` keeps dropping
   `q` for every JS author who deletes under a filter.** The §8 row drives a delete whose
   confirm GET carried `?open=…`, so the assertion actually reaches `:674`.
4. **The whole Move-picker chain**, which parent §2 (`:683-701`) pins separately precisely
   because the picker is a separate page and not an in-tree form: the Move link's href carries
   `&q=`, the `[data-move]` fetch **sets** `q` on the parsed URL, `node_move`'s GET puts it in
   the picker context, `_move_picker.html`'s reparent form carries it as a hidden input, and the
   reparent redirect emits `open=session` **plus** `q`. The picker has no first hop from the
   "every tree form" rule, and parent §8 carves the `[data-move]` fetch out of the collector, so
   nothing else would supply it.

   **The fetch SETS the applied `q`, it does not append** (parent §2 says "appends", and this
   spec overrides it; see Deltas). `builder.js:276` fetches `mv.getAttribute("href")`, and item
   2 above already put `&q=` in that href — so appending yields `?node=5&q=X&q=X` and works only
   because `QueryDict.get` returns the last (verified). The duplicate is harmless today, since
   §5a makes the picker an **applied**-`q` sender and every filter transition re-renders the
   whole top scope, so the href's value and the tracker's are the same string. It is still
   forbidden: a request whose correctness depends on parameter ordering is one refactor away
   from breaking, and the picker's `q` flows on into `_move_picker.html`'s hidden input and the
   reparent redirect. It goes through §5a's `setTreeParams` like every other path — which is
   also what stops an implementer reaching for the live input value here.

### 3k. `_tree_context` grows five keys — stated once, not patched three times

`toggle_href` reads everything from the template context, and the sole producer of those keys
is `_tree_context(course, cmap, ids)` — whose docstring says "Takes no `request`: everything it
needs is already resolved". This slice needs five more context values in every renderer:

| key | consumer | source |
| --- | --- | --- |
| `q` | `toggle_href`, the hidden inputs, the delete/Move hrefs, the filter input's value | the **raw** submitted `q`, not the normalized one |
| `filtered` | `_scope.html`'s `{% empty %}` branch (§3h); the grip's `draggable` in `_tree_node.html` and both buttons' `disabled` in `_move_buttons.html` (§3m) | `q_active` |
| `expand_all_disabled` | whether `builder.html` emits expand-all's `href`, **and** `data-expand-all-disabled` on `.builder` for the JS bail (§6a) | `len(container_pks(full_cmap)) > builder_open.CEILING` |
| `applied_q` | `data-applied-q` on `.builder` — initialises §5z's tracker | **`fc.q_raw`**, emitted **unconditionally** (empty string when there is no `q`) — never the `q_active` bool |
| `q_min` | `data-q-min` on `.builder` — the client floor (§5c) | `builder_filter.MIN_QUERY`, read **through the module** so §8's monkeypatch bites |

**Two of the three DOM-carried values are RESOLVED server-side; `MIN_QUERY` deliberately
crosses as a number.** `expand_all_disabled` and `applied_q` become a boolean and a string
because the client has no business re-deriving them. `MIN_QUERY` is the exception and the
reason is different: the client must apply the floor **without a round trip**, so it needs the
number itself — carried, never hardcoded, for the same reason `CEILING` is never hardcoded.

**`q_min` belongs in `_tree_context` like the rest, not hand-patched into `builder()`.**
`.builder` is rendered by `builder()` *and* `_builder_with_notice()`; patching one leaves the
notice page without the attribute, where `parseInt(null)` is `NaN`, every floor comparison is
false, and filtering is silently dead on that page. That page is reachable with JS on — the
delete-confirm form carries no `data-op`, so its 409 returns `_builder_with_notice`.

- **`expand_all_disabled`** is a boolean, not a number the template or the JS compares. A Django
  template cannot evaluate `container_count > builder_open.CEILING` — module attributes are
  unreachable from template syntax — and §6a requires the comparison to read `CEILING` *through
  the module* so §8's monkeypatch takes effect. **The parent spec's `data-container-count` is
  therefore replaced by `data-expand-all-disabled`** (see Deltas): a raw count on `.builder`
  would leave the JS with nothing to compare it against except a hardcoded `500`, which is
  exactly the by-value duplication §6a's next bullet forbids — and §8's monkeypatch test asserts
  on the missing `href`, so a desynced JS constant would ship green.

  **Emitted by PRESENCE, read with `hasAttribute`** — `{% if expand_all_disabled %}data-expand-all-disabled{% endif %}`,
  never `data-expand-all-disabled="{{ expand_all_disabled }}"`. The value form renders the
  string `"False"` below the ceiling, which is **truthy** in JS, so the obvious
  `if (root.getAttribute("data-expand-all-disabled")) return;` bails on *every* course and
  expand-all never fires anywhere. It ships green, too: §8's ceiling test asserts on the
  server-omitted `href` and the bail test drives the `aria-disabled` branch, so neither sees it.
  This is the same presence-vs-truthiness trap this repo pins for `open`/`open_present` and for
  `.btn[hidden]`.
- **`applied_q`** must reach the client because §5c initialises its tracker from it, and the
  value it needs is **the last APPLIED query — a stable anchor that does not move as the author
  types**. The filter input cannot serve that: its `value` is the live text by the second
  keystroke, which is precisely what §5a forbids the five applied-`q` paths from sending. (At
  init the two happen to agree, since both come from `q_raw`; they diverge the moment anyone
  types, which is when the tracker matters.) Sniffing the `[data-info-key="filter"]` entry
  would work but couples the tracker to a notice that exists for a different reason, and
  `filtered` is a template key with no markup carrier.

  **It is a distinct key from `q_active`, and the distinction is load-bearing.** `q_active` is
  a `bool` on `FilterContext`; wiring it straight to the attribute renders
  `data-applied-q="True"`, §5c's tracker initialises to the *string* `"True"`, and §5a then
  makes every toggle, drop, submit and picker fetch send `q=True` — which the server folds,
  matches nothing against, and the author's pane empties on their next toggle. One name for a
  bool and a string is how that ships. §8 asserts the attribute's **value**, not just its
  presence.

  **The attribute is always emitted, even when empty**, exactly as `q_min` always is and for
  the same class of reason. §5z stores it verbatim at init, so a conditionally-emitted
  attribute puts `null` in the tracker without throwing — the failure surfaces **later**, the
  first time the skip-comparison folds it (`null.replace`), inside the `input`/submit handler.
  The builder keeps working; **filtering is permanently inert**, and the exception is one the
  author never sees. That is the same outcome `q_min`'s `parseInt(null) === NaN` produces, and
  it is why both attributes are unconditional rather than one of them.

  **It carries `q_raw` unconditionally — including a present-but-INACTIVE `q`.** An earlier
  draft emitted `""` below the floor, which made the two paths of the same gesture disagree:
  the no-JS expand-all href carried `q=a` (§6b) while the JS fetch sent `q=""`, and `syncUrl`
  then stripped `a` from the address bar and from every re-rendered hidden input — contradicting
  §1's promise that the raw `q` round-trips through the input's value, the hidden inputs and the
  URL. Sending `q_raw` costs nothing, because the server treats a below-floor value as blank
  either way (§1a); it just keeps the author's half-typed text alive on both paths.

  **The tracker's skip-comparison is on the EFFECTIVE values, not the raw ones** (§5c): both
  sides run through the client floor first, so typing `t` into an unfiltered tree compares
  `""` against `""` and sends nothing.

These go into `_tree_context`'s signature — which therefore gains the arguments to compute
them — **not** into four hand-patched render calls. Three renderers exist (`builder()`,
`_builder_with_notice()`, `_render_scope()`), and `_tree_context` exists specifically to stop
them drifting; adding keys at the call sites re-opens exactly that.

**Three context keys carry a map or a node list, and ALL THREE must become restricted.** §2
names the maps by role; this is the line where role meets code, and getting it partially right
is the failure mode:

| key | set at | consumed by |
| --- | --- | --- |
| `children_map` | `views_manage.py:252`, `:348`, `:737` | `_tree_node.html`'s recursive descent and `_tree_toggle.html`'s counts |
| `top_nodes` | `builder()` and `_builder_with_notice()` | `builder.html:24` |
| **`nodes`** | **`_render_scope`, `views_manage.py:333-341` — the only *Python* site** | **`_scope.html`'s `{% for node in nodes %}`** |

`nodes` is also bound in template syntax — `builder.html:24` passes `nodes=top_nodes` and
`_tree_node.html:49` passes `nodes=children_map|get_item:node.pk` — but both derive from keys
already in the table above, so restricting those two covers them.

**`nodes` is the one that is easy to miss and the most damaging to miss.** `_scope.html` does
**not** iterate `children_map` — it iterates `nodes`, which `_render_scope` builds from its own
separate read of the map (`cmap.get(None, [])` for `"top"`, `cmap.get(int(scope_ref), [])`
otherwise). An implementer who swaps only `children_map` ships a toggle that, under an active
filter, returns **every** child of the expanded scope into a filtered pane — exactly the defect
§5a and §5c exist to prevent — and `manage_tree`'s top scope renders unfiltered too. §1d's
"matched container over an empty scope" also becomes unreachable, because `nodes` would be the
full child list.

So: `nodes` is `restricted.get(<scope key>, [])` in **both** branches. The sibling lookups in
the same block — `parent`, `parent_kind`, `updated` — continue to resolve against the full
course, since a scope's own identity is not a filtering question.

**Two further `children_map` sites keep the FULL map, and must be named or they will be
"fixed".** `link_picker` (`views_manage.py:275`, which sets **`top_nodes` in the same dict literal**) and
`node_move`'s picker GET (`:804`, together with its own `nodes_top` key at `:805`) both set
`children_map` and neither renders the builder tree. The picker's lists are *destination candidates* and the slot positions the numeric
`position` field indexes into — restricting them would make the JS picker compute positions
against a filtered child list, and offering only matching destinations would make a filtered
author unable to move anything out of the match set. The risk is live rather than theoretical:
§3j item 4 already sends the implementer into `node_move`'s GET context to add `q`, one line
from `:804`. §8's reparent row POSTs, so it would stay green.

Meanwhile the **full** map continues to be what `_tree_context` hands `_open_descendants`
(§2, row 4). Restricted and full derive from the same local, and the difference between them is
one argument at one call site, which is exactly why it needs writing down.

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

### 3m. Ordering is suppressed while a filter is active

**A filtered scope shows a SUBSET of its siblings, and every position-based operation in this
builder computes against the full list.** §1d is what first makes a rendered scope partial —
slice 1 always rendered every child of an open scope — so this is a hazard the filter creates,
not one it inherits. Two operations break, both silently, both verified against the shipped
code:

- **Drag-and-drop.** `targetFor` (`builder.js:543-554`) counts only the rendered `.tree__row`
  children of the target `<ol>` and posts that ordinal as `position` (`:635`); `place_node`
  (`courses/ordering.py:77-86`) splices it into
  `ContentNode.objects.filter(course=…, parent=new_parent).order_by("order", "pk")` — **the
  full child list**. Dropping between the two visible children of a 30-child chapter posts
  `position=1`, and the node lands as that chapter's *second* node overall. No error, no
  feedback, wrong data.
- **The up/down arrows.** `reorder_node` (`courses/builder.py:260-264`) swaps against the full
  sibling queryset. With full order `u1(match), u2, u3, u4(match)` the filtered scope shows
  `u1, u4`; clicking u1's "Move down" yields `u2, u1, u3, u4` — and the re-rendered filtered
  scope is **visually identical**, so the author clicks again, and again. Three silent
  mutations for one apparent no-op. Worse, `is_first`/`is_last` come from `forloop.first` /
  `forloop.last` over the restricted `nodes` (`_scope.html:11` → `_move_buttons.html`), so the
  arrows are `disabled` at the edges of the *filtered* list: u4's "down" is greyed out although
  u4 can still move down. The affordance lies in both directions.

**Rule: while `q_active`, drag-and-drop is disabled and the up/down arrows render `disabled`.**

**Both are carried by the `filtered` context flag, server-side, in the markup** — `filtered`
adds `disabled` to both buttons in `_move_buttons.html`, and on the grip button
(`_tree_node.html:32`) it both drops `draggable` **and** adds `disabled`.

**Dropping `draggable` alone would reintroduce the lying affordance this section condemns.**
The arrows get a real disabled treatment for free (`builder.css:60`,
`.ica:disabled { opacity: .35; cursor: default; }`), but the grip keeps
`.ica--grip { cursor: grab; }` (`:62`) and `.ica--grip:active { cursor: grabbing; }` (`:155`)
— so an author would see a grab cursor, press, see a grabbing cursor, and get nothing, with no
visual difference from an unfiltered row. `disabled` fixes both: the grip is a `<button>`, so
it picks up the opacity and `cursor: default`, and `:active` never matches a disabled control.
It carries a `title` naming the reason, reusing the reorder refusal's string (§9). §3k's `filtered` row lists these two
templates alongside `_scope.html`'s `{% empty %}` branch.

**Not from `data-applied-q` in a `dragstart` bail.** That attribute is defined by §5z as the
*initial* value of a JS variable, and no fragment render updates it (§3g returns the top `<ol>`
only) — so a client-side check would leave drag live for the whole type-a-query path and
wrongly dead after a JS clear on a `?q=` page load. The server re-renders the whole top scope
on every filter transition, so markup is the carrier that is always current.

This is the honest reading of what a filtered view is *for*. "Move down" past siblings the
author cannot see is not a well-defined gesture, so there is no correct index to compute — the
choice is between suppressing the operation and inventing a semantics for it. The alternative
(carry the neighbouring sibling's pk instead of an ordinal, and have `place_node` resolve it
against the real list) changes the contract of two shipped service functions to support a
gesture that means nothing in the view that needs it.

**Moving things while filtered still works — through the Move picker**, whose destination and
slot lists §3k already keeps **full** for exactly this reason. That is the one surface where a
position under a filter is unambiguous, and it is now the documented route.

**The server guard is scoped to `mode=reorder`, and a positioned REPARENT is not refused.**
A drop posts `mode=reparent` with a `position` (`builder.js:630-636`) to the same endpoint the
Move picker's reparent form uses, and the two are indistinguishable server-side — so a guard
written symmetrically over "any positioned move" would break the one route this section
designates for moving under a filter. The picker's slot indices are computed against the
**full** child list (§3k), so they are correct by construction and need no guard. Stated here so
it is not "made consistent" later.

**The refusal's contract: HTTP 422, branching on `_wants_fragment` exactly as every other 422
in this file does** — `_op_error.html` on the fragment path, **`_builder_with_notice(...,
status=422)` on the no-JS path** (`node_add:480-486`, `node_rename:540-549`, `node_move`'s
reparent `:612-618`, `node_duplicate:706-712` all have this shape).

**`_op_error.html` is NOT a page**, and an earlier draft of this spec said it was: it is two
lines — `{% load i18n %}` plus one `<div class="op-error" role="alert">` — with no `base.html`,
no stylesheet, no navigation and no way back to the builder. Returning it unconditionally
would ship a no-JS author a bare unstyled string, which is what "every view ships styled"
forbids and what the branch above exists to prevent. `builder.js`'s submit handler already acts
on 422 (`:243-261`), so the fragment path needs no new plumbing.

It carries one translatable string — *"Clear the filter to reorder."* — counted in §9.

**Consequently the mutations available under a filter are: rename, add, duplicate, delete and
the Move picker.** Reorder and drop are not, so §8's "`q` rides every fragment request" row and
its "a filtered mutation re-asserts `filter;…`" row both narrow accordingly — a drop under a
filter is not a case that exists.

## 4. The filter control

Sits in `.builder__tree`'s header row, after the title, beside the expand/collapse controls.

```html
<form class="builder__filter" method="get" action="{{ builder_url }}" data-filter>
  <label class="visually-hidden" for="builder-q">{% trans "Filter by title" %}</label>
  <input id="builder-q" type="search" name="q" value="{{ q }}">
  <button type="submit">{% trans "Filter" %}</button>
  <a class="btn btn--ghost btn--small" href="{{ builder_url }}"
     data-filter-clear{% if not q %} hidden{% endif %}>{% trans "Clear" %}</a>
</form>
```

**The input's accessible name is written out, not elided.** "Filter" labels the *button*, not
the field, so without this the control ships unnamed — and the name is a translatable string,
counted in §9. A visually-hidden `<label>` rather than the `placeholder` the media manager uses
(`media/manager.html:34-35`), because a placeholder disappears the moment the author types and
is not a reliable accessible name.

- **`method="get"`, no `data-op`.** `builder.js`'s submit handler gates on `form[data-op]`
  (`builder.js:216`, verified), so on the no-JS path this form falls straight through to the
  browser, and on the JS path it needs its own listener rather than an exclusion.
- **It carries no `open`.** Same rule as the JS filter fetch (§5b), and for the same reason:
  precedence step 2 would outrank step 3 and matches inside collapsed branches would never
  appear.
- `type="search"` gives Chromium a native clear affordance that fires `input`, so the JS path
  gets clearing for free — **but Firefox renders none**, so the link below is the only one-click
  clear a Firefox author has, and it must work on both paths. The explicit Clear link is
  rendered **whenever the input has any text — `{% if q %}`, on the raw value, not on
  `q_active`**.
- **The anchor is rendered UNCONDITIONALLY and carries `hidden` when `q` is blank.** An
  earlier draft wrapped it in `{% if q %}`, which puts nothing in the DOM on an unfiltered page
  — so the JS rule below has no element to show, and the natural spelling
  (`clear.hidden = !box.value` on a `querySelector` that returned `null`) **throws inside the
  `input` handler** on the most common entry point there is, aborting it before the debounce is
  scheduled and leaving filtering permanently dead. That is the same "silently inert" shape
  §3k pins for `data-applied-q`. Rendering it always keeps the server correct for a no-JS
  author *and* gives the JS something that exists.
- **The hide mechanism is the `hidden` attribute on a `.btn`-classed anchor**, which is safe
  only because `app.css:42` already ships `.btn[hidden] { display: none; }` with a comment
  naming this exact trap. A new component class would re-open it — §3i makes the same call for
  `.builder__info` and reaches the opposite answer for its own reasons; both are stated rather
  than left to the implementer.
- **The JS owns the Clear control's visibility, because the server cannot.** `{% if q %}` would
  be evaluated only on a **page** render, and the filter control sits in `.builder__tree`'s header
  — outside every `[data-scope]` element `applyFragment` swaps, and outside what `manage_tree`
  returns at all (§3g: the top `<ol>` and nothing else). So on the overwhelmingly common
  gesture — load an unfiltered builder, type a query — a server-only rule renders **no Clear
  control at all**, for precisely the Firefox author the bullet above says it exists for; and
  after a JS clear on a `?q=` page load it would linger over an empty box. **Rule: the JS shows
  the Clear control whenever the box is non-empty and hides it when empty**, on the same
  `input` handler that drives the debounce.
- **The JS intercepts the Clear control**: `preventDefault`, **cancel any pending debounce
  timer** (the same rule §5b gives the form's submit listener, and for the same reason — the
  timer would otherwise fire afterwards and issue a *second* clear), empty the input, and run
  §5d's clear path. Left un-intercepted it is a full-page navigation to a bare builder URL — precedence
  steps 4–6, the module-scoped stash discarded, every expansion lost — which is exactly what
  §5d's stash exists to prevent, on the control *labelled* "Clear". The route is routine, not
  theoretical: the link is server-rendered, so it appears on any reload of a `?q=` URL, which
  §5c calls a first-class path. It is the eighth entry in §5a's request table, sending the same
  values as the clear fetch. A
  below-floor `?q=a` renders an unfiltered tree with `a` still in the box, and a no-JS author
  needs a way to empty it; gating on `q_active` would leave them retyping over stale text.
- **Without** JS the Clear link is a plain GET with neither `q` nor `open`, so it lands on
  precedence steps 4–6. A no-JS author's pre-filter expansion is therefore **not** restored —
  there is no client to stash it and no session slot that means "what was open before the
  filter". Recorded as an accepted limitation of the no-JS path, not a defect.
- **A no-JS author's expansions made *while* filtered do not survive a mutation either**, and
  this follows from two deliberate rules meeting: §3l never writes `builder_open` while
  filtered, and §3c resolves the post-mutation `open=session` to the bare chains. So filter,
  expand a matched chapter, rename a row inside it — and the chapter comes back collapsed. The
  JS path is unaffected (the collector carries the live enumeration). Recorded here as a
  decision rather than left to be discovered.

Styling follows the repo's practice: token-driven CSS, no new component vocabulary, and the UI
is verified with Playwright screenshots in **both** light and dark before the PR, judged
separately rather than inferred from one another.

**The header row already has a rule that will fight this.** The row is `.manage__head`
(`builder.html:16-20`) — an `<h1>` plus two `.btn` links — and `app.css:591` declares
`.manage__head .btn { margin-left: auto; }` (overridden to `0` at `:644` for narrow
viewports). Dropping a search form and two more controls into a flex row where *every* `.btn`
claims the free space is where this repo's recorded `flex: 1 1 auto` wrap trap bites. The
layout is designed around that existing rule rather than discovered by it, and the screenshot
pass checks the row at a narrow width, not just at 1400px.

## 5. Client

### 5z. The applied-`q` tracker — defined once, here

Three sections need this value and an earlier draft defined it in all three, against subtly
different mental models; the contradiction that produced is recorded below. It is defined here,
and §3k, §5a and §5c point at this definition rather than restating it.

| | |
| --- | --- |
| **type** | a **string** — the *raw* query, never a boolean and never the folded form |
| **initial value** | `data-applied-q` verbatim (§3k), which is `q_raw` — so a below-floor `?q=a` initialises it to `"a"`, not `""` |
| **written by** | the filter fetch, to the value it sent; the clear fetch, to the **live raw box value** (see below); a skipped request, to the live raw box value |
| **read by** | the five applied-`q` senders (§5a), `syncUrl` (§5a), and the skip-comparison (§5c) |

**The floor is applied in the COMPARISON, never in the tracker.** The skip test is

```
effective(candidate) === effective(tracker)      // both sides folded through the client floor
```

and what gets *sent* is the tracker's raw string. Storing the effective value instead breaks
three things at once, which is what an earlier draft did: on a `?q=a` page the tracker would
hold `""`, so the first toggle would send `q=""`, `syncUrl` would strip `a` from the address
bar — the exact regression §3k carries `q_raw` unconditionally to prevent — the two halves of
§6b's expand-all gesture would disagree again, and the toggled scope's re-rendered delete and
Move hrefs would drop `q` while every other row kept it.

Raw-in-tracker, effective-in-comparison satisfies every case the floor exists for: typing `t`
into an unfiltered tree compares `""` to `""` and sends nothing; clearing an applied `tryg`
compares `""` to `"tryg"` and fires; clearing a below-floor `a` compares `""` to `""` and
correctly does nothing.

**The clear fetch writes the live RAW box value, not blank.** "The value that request sent"
has no referent here — the clear request omits `q` entirely (§5a) — and reading it as blank
reproduces the regression this section exists to prevent: on a `?q=tryg` page where the author
cuts the box down to `t`, the clear fires, a blank tracker makes `syncUrl` drop `q` from the
URL, and the `t` is gone on reload. §1 and §3k both promise the raw `q` round-trips through the
box, the hidden inputs and the URL. So all three writers agree: **the tracker always holds the
raw text the box last settled on**, and only the comparison folds it.

**A skipped request still updates the tracker to the live raw value.** Otherwise the tracker —
and therefore the address bar, which follows it (§5a) — keeps a value the box no longer holds:
delete the `a` from a `?q=a` page, no request fires (correctly), but the next toggle would send
`q=a` and `syncUrl` would keep `?q=a`, so a reload repopulates the character the author just
deleted. Since the effective query did not change, no re-render is needed and the update is
free: the pane stays correct either way, and the URL now tracks the box on both below-floor
paths instead of only one of them.

### 5a. `q` rides EIGHT request paths — six with the applied value — and `withOpen` reaches two

**Set, never append**: mutation forms already carry a hidden `q`, so appending would put two
values in the `FormData` and `QueryDict.get` returns the last — the collector would win only by
accident of ordering.

**The value they set is the APPLIED `q` (§5c's tracker), not the filter input's live value.**
Three values are in play during the 300 ms debounce: the hidden input holds the last *rendered*
`q`, the box holds what is currently typed, and the tracker holds what the pane is actually
showing. An earlier draft of this spec sent the live value, which is the one choice that breaks
the pane: with `tryg` applied and `trygo` typed, a toggle or an add fired inside the debounce
returns markup filtered by `trygo` **into a pane rendered for `tryg`** — the mirror image of the
"unfiltered children arriving into a filtered pane" defect this rule exists to prevent — after
which `syncUrl` writes `q=trygo` and the `filter` entry re-asserts counts for a query the tree
does not show.

The filter fetch itself is the exception, and obviously so: its whole job is to *apply* the live
value, and it updates the tracker when it lands.

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

**Rule: eight request paths are named here, each with the value it sends. Six carry `q`; the
two clear paths omit it.**

| path | site | `open` | `q` |
| --- | --- | --- | --- |
| mutation submit | `builder.js:240` via `withOpen` | collector | **applied** |
| drop | `builder.js:638` via `withOpen` | collector | **applied** — but §3m makes a drop impossible while filtered, so in practice always blank |
| **toggle expand** | `builder.js:487-490`, its own `URLSearchParams` | collector **+ this pk** | **applied** |
| **Move picker fetch** | `builder.js:276`, an href GET (§3j item 4) | n/a — carved out of the collector | **applied** |
| **expand-all** | new, §6a | `all` | **applied** |
| **filter fetch** | new, §5b | **omitted** | **live** — its job is to apply it |
| **clear** (box emptied / below floor) | new, §5d | stash, or the collector | **omitted** |
| **clear** (the Clear link, intercepted) | new, §4 | stash, or the collector | **omitted** |

The last four rows are distinct requests with distinct `q` rules, so they get one row each:
collapsing them hides the fact that expand-all is an *applied*-`q` sender rather than an
exception like the filter fetch, and that the Clear link is a request path at all rather than
the plain navigation §4 originally took it for. Sending the live value there would drop a
~226-row bulk render, filtered by a query the author never applied, into the pane.

The cleanest shape is one `setTreeParams(target, {openOverride})` helper used by all of them,
with the toggle passing its `open + pk` as the override and the picker passing none; whatever
the shape, **`q` must not be supplied by `withOpen` alone**. §8 pins a test that the toggle
request carries `q`.

**`syncUrl` writes the TRACKER (§5z)** — never "whatever this request sent", which is
undefined for the two paths that send no `q` at all (the clear fetch) or issue no request at
all (§6b's collapse-all, which also calls `syncUrl`; under the other reading it would strip `q`
from the URL and silently drop the filter). It deletes the parameter only when the tracker is
**blank**. Not "when inactive": a below-floor `?q=a` is
present-but-inactive, so an activity-gated `syncUrl` would strip the `a` from the address bar on
the author's first toggle, undoing on the JS path exactly the round-trip §3k carries `q_raw`
unconditionally to preserve. A cleared filter sends a blank value and so still leaves no `?q=`
behind. `open` keeps its existing rule: present-but-empty, never omitted.

**The toggle's `.then` chain has to be reshaped to read a header at all.** It currently does
`.then(function (r) { if (r.status !== 200) throw …; return r.text(); })` (`builder.js:492-495`),
which discards the `Response` before the body is available — so §3i's header handling is
unreachable there without adopting the nested `r.text().then(…)` form the submit and drop
handlers already use. This is a real edit, it touches the same chains as **M15** in §10, and
the two are done together rather than twice.

### 5b. The filter fetch

- **The form's own submit is a first-class path, not just the debounce.** Pressing Enter in
  the search field or clicking the Filter button submits a `method="get"` form; §4 requires the
  JS to intercept it, and without that the single most obvious "apply the filter" gesture does a
  full-page navigation and discards §5d's module-scoped stash. **Rule: the `[data-filter]`
  submit listener `preventDefault`s, cancels any pending debounce timer, and runs the same
  filter/clear decision as the debounced path with the live value** — one code path, reached two
  ways.
- **300 ms debounce** after the last keystroke. Undebounced it would issue a full-tree render
  per keystroke — the exact cost profile this work exists to remove.
- **Plus a last-wins request id**, in the shape `loadPanel` already uses. The debounce does not
  prevent overlap: a slow request for `tr` can land after a fast one for `tryg`, leaving the
  pane showing results for a query the author has moved past. Debounce alone is a common and
  wrong answer here.
- **ONE generation counter covers every `data-tree-url` request — filter, clear and
  expand-all — not one per path.** They all `applyFragment` the same pane, and the ordinary
  sequence "type `tryg`, then immediately hit the native ✕ or the Clear control" issues a
  filter fetch followed by a clear fetch. With separate counters, a filter response landing
  last repaints **filtered** markup, re-asserts `filter;…`, writes the tracker back to `tryg`
  and restores `?q=tryg` — filtered capped markup over an empty input, the exact state §5c
  exists to prevent. **A stale response is dropped before `applyFragment`, before the header
  handling, before the tracker write and before `syncUrl`** — all four, or the discarded
  response still moves state.
- The request goes to **`data-tree-url` with `q` and NO `open`.** Precedence step 2 outranks
  step 3, so a filter fetch carrying `open` would return only the scopes that happened to be
  open already, and a match three levels down inside a collapsed branch would never appear. The
  no-JS form (which carries no `open`) would work correctly, so the two paths would silently
  diverge on this slice's central promise.
- Ordered steps on the response: the parent §8 busy counter → `applyFragment` → §3i's header
  handling → **the tracker write (§5z), to the value this fetch sent** → `syncUrl`. **The order
  is load-bearing, exactly as in §5d**, and for the mirror-image reason: `syncUrl` reads the
  tracker (§5a), which starts at `""` on an unfiltered page — so writing it *after* `syncUrl`
  puts `open=…` and **no `q`** into the address bar when a filter is applied. The reload path
  §3i and §5c both call routine then silently loses the filter, and because the tracker never
  advanced, the author's next clear compares `""` to `""`, skips, and leaves filtered capped
  markup over an empty box.
- **Failure clears busy and surfaces `msg("network", …)`**, like every other fetch in the file.

### 5c. Below the floor takes the CLEAR path — but only if a filter is actually applied

The JS treats a below-`MIN_QUERY` query **exactly like an empty one** — stashed `open`, no `q`,
stash consumed.

**The client's floor constant and its measurement are both specified, because a JS/server
disagreement here does not degrade — it collapses the tree.** If the JS thinks a query clears
the floor and the server does not, the client sends a *filter* fetch, which by §5b omits `open`;
the server treats `q` as blank, `open_ids` takes the fragment-absent path, and the response is
the **empty** set — every expansion the author had, gone. The clear path would have carried the
stash; the filter path deliberately does not.

So: **`MIN_QUERY` reaches the JS as `data-q-min` on `.builder`** (never a by-value `2`, for the
same reason `CEILING` never crosses the boundary), and **the client measures**

```js
[...q.replace(/^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/g, "")
     .normalize("NFC").replace(/[\u0300-\u036f]/g, "")].length
```

**The spread is not decoration: `.length` counts UTF-16 code units and Python's `len()` counts
code points.** Every astral character — an emoji, or a U+1D400-block mathematical letter, which
is not an exotic thing to paste into a maths course's filter box — is `.length === 2` on the
client and `len() == 1` after the server's fold. That is the dangerous direction, for
essentially the whole astral plane.

**Only one direction of disagreement is dangerous, and the measure is chosen to close it.**
If the client thinks a query is *above* the floor while the server thinks it is *below*, the
client sends a filter fetch, which omits `open` (§5b); the server treats `q` as blank,
`open_ids` takes the fragment-absent path, and the response is the **empty** set — every
expansion gone. The opposite disagreement is harmless: the client takes the clear path, which
carries `open`.

**Two things break that guarantee, and both were measured rather than reasoned about.**

1. **`NFD` was the wrong normalisation.** Measured across all of Unicode, comparing
   `len(fold(ch))` against the client's measure: an **NFD**-based client is longer than the
   server's fold for **11,371** characters — every Hangul syllable, plus Hebrew, Katakana,
   Hiragana, Arabic and the Indic scripts, whose decomposed marks and jamo fall *outside*
   U+0300–U+036F while the server leaves the precomposed character as one. An **NFC**-based
   client is longer for **83**. For Latin script — the corpus — the count is **0 either way**.
2. **`.length` was the wrong count**, and this one dwarfs the normalisation choice. Measured in
   **Node**, not emulated in Python: with `.length`, **1,048,216** single characters measure
   longer on the client than on the server (77 of them BMP; the rest are astral characters
   counted as two units purely by their encoding). With code-point counting the figure is the
   **83** above. An earlier draft of this spec quoted "83" beside a `.length` expression — the
   number was measured in Python, which counts code points, and does not describe the JS it was
   attached to. Both figures are now measured in the runtime that will execute them.
3. **`String.prototype.trim()` and Python's `str.strip()` strip different sets.** Measured:
   Python strips U+0085 and U+001C–U+001F (all report `isspace()`), JS `trim()` does not; JS
   strips U+FEFF, Python does not. So a bare `q.trim()` makes `"a\u0085"` client-length 2 and
   server-length 1 — the dangerous direction, from input that is not even exotic. The explicit
   character class above closes it; U+FEFF needs no handling, because JS stripping *more* than
   Python only ever puts the client below the floor.

**Residual, accepted:** the 83 non-Latin characters that survive NFC and code-point counting.
A single one of them typed alone into the box yields one collapsed tree, recoverable by
expanding again or reloading. Closing it completely would mean shipping the 373-entry fold
table to the client — a duplicated rule, for a corpus with zero exposure (0 Latin-script
counterexamples, measured).

Note what the ordering does *not* rely on: the fold table is not one-character-to-one, and
saying so would be false — it holds 14 multi-character entries (`Ĳ→IJ`, `ǆ→dz`, `ǉ→lj`,
`ǌ→nj`, `ǳ→dz` and their case variants) and `casefold` expands `ß→ss` and the `ﬁ`-class
ligatures (measured: `'ß'` is client-length 1, server-length 2). Those all lengthen the
*server* side, which is the safe direction.

**Guarded by whether a filter is currently APPLIED, not by what the input contains.** Without
that guard the first character an author types into an *unfiltered* tree takes the clear path;
no filter was ever applied, so the stash is `null`; §5d's fallback then sends the collector's
full enumeration to `manage_tree` — **a complete re-render of everything the author had open,
triggered by one keystroke**, and again on every pause below two characters. After an
expand-all on `mat-pp` that is the multi-second render §6a warns about, provoked by typing.

**Rule: the client tracks the `q` of the last *applied* render, and any request — filter or
clear — is skipped when the value it would send equals it.** Typing `t` into an unfiltered tree
computes an effective `q` of `""`, which equals the applied state, so nothing is sent. Deleting
a real filter down to `t` computes `""` against an applied `tryg`, so the clear fires exactly
once.

**The tracker is initialised from the SERVER-RENDERED active `q`, never unconditionally to
`""`.** A page GET of a `?q=tryg` URL is a routine path here, not an edge case: `syncUrl` puts
`q` in the address bar, so every reload while filtered is one, and §3i's registry rule and §8's
replace-by-key test are both built on it. Initialised to `""` on such a load, the tracker says
"nothing applied" over a tree that is visibly filtered — so the author's very next clear (the
`type="search"` native affordance §4 relies on, or deleting below the floor) computes `""`,
finds it equal, and **skips the request**, leaving filtered and capped markup on screen above an
empty input. The next toggle then sends `q=""` and drops unfiltered children into it: the exact
"stale filtered markup" outcome this section exists to prevent, reintroduced by its own guard.

So: **initialise the tracker from `data-applied-q`, verbatim** — see §5z, which defines the
tracker once and is the only place its type, initial value, writers and readers are stated. Not
from the `filtered` context key: that has no markup carrier (§3k), so the JS cannot read it.

With the guard in place, the floor only ever saves a round trip on the way *into* a filter,
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
- **The stash is consumed when a clear response is APPLIED, not when the request is issued.**
  Consuming at issue would let a superseded clear (§5b's shared generation counter drops it)
  take the stash with it, so the surviving clear falls back to the collector — which still
  reflects the *filtered* tree — and the author's pre-filter expansion is replaced by the
  filter's chains, defeating the point of the stash.
- **The stash is discarded once consumed, and whenever a mutation happens while filtered** —
  the tree has changed underneath it. **The two discard sites are the submit handler
  (`builder.js:215`) and the drop handler (`:618`)**, neither of which otherwise knows the
  stash exists; naming them is what stops the rule being implemented in whichever handler the
  implementer happened to be editing. The e2e must assert the **fallback was used** (the
  cleared tree still shows the row the mutation created), because a stale stash and a correct
  fallback both produce a merely non-empty tree.
**The clear response is handled exactly like the filter fetch's** — the parent §8 busy
counter, `applyFragment`, §3i's header handling, **the tracker write (§5z)**, then `syncUrl`.
**That order is load-bearing and is why the tracker write is listed as a step rather than left
to inference**: `syncUrl` reads the tracker, so writing it afterwards leaves `?q=tryg` in the
address bar over a freshly-unfiltered tree, and the next reload restores the filter the author
just dismissed. The header step is the one
worth naming: **the clear path is the ONLY consumer of `X-Builder-Info: none`.** Its response
carries no codes, so `none` is what removes the "Filtered: 100 / 940" entry; a clear handler
written without header handling leaves that notice standing over a freshly-unfiltered tree,
and every server-side assertion still passes because the header was emitted correctly.

- **If the stash really is absent, the clear request carries the collector's current
  enumeration — it never omits `open`.** Filter → mutate → clear is a normal authoring
  sequence and reaches the clear with no stash. Omitting `open` there would put the request on
  the fragment-absent path, i.e. the **empty set**, collapsing a large course to its 21 top rows
  and destroying every expansion the author had. Falling back to the collector is merely lossy
  (it returns the filter's chains rather than the pre-filter set), which is the right trade.

## 6. Expand-all and collapse-all

Two controls in `.builder__tree`'s header, beside the filter.

### 6z. Under a filter, both controls act on the FILTERED tree — and stay enabled

The tempting rule is to disable them while filtering, on the grounds that a filtered tree is
already fully open. **That reasoning is false, and an earlier draft of this spec shipped it.**
It holds only while the open set comes from step 3. Step 2 outranks step 3, so the moment the
author toggles anything under a filter — a no-JS toggle href carries `open = chains ± pk`, and
`syncUrl` writes the collector's enumeration on the JS path — the resolved set is *not* the
chains, and filtered containers genuinely are collapsed. Disabling expand-all in exactly that
state would strand a filtered author with collapsed chains and no bulk way back.

The cost argument was wrong too: under a filter, `open=all` renders from the **restricted**
map, so it is ~226 rows, not 944 — sub-second, not the multi-second render §6a warns about.

**Rule: both controls stay enabled under a filter and operate on the filtered tree.**
Expand-all opens every filtered container; collapse-all closes them. They remain each other's
inverse, so an author who collapses a filtered tree can restore it with one click, and neither
control needs a client-side enable/disable dance, an `href` to stash and rebuild, or a
`data-builder-url` that does not exist today.

Expand-all is a **no-op when nothing under the filter is collapsed** — one cheap request for an
identical tree. Accepted: it is bounded by the restricted render, and detecting the case
client-side would mean reasoning about which containers the server considers open.

The only disabled state is §6a's over-ceiling guard.

### 6a. Expand-all

An `<a data-expand-all>` whose `href` is the builder URL with `open=all` and `q`, so it works
without JS as a plain navigation. (Named, like every other JS-reachable hook in this design, so
the delegated handler has something to match on and §6a's bail order is unambiguous:
hook match → `aria-disabled="true"` early return → `data-expand-all-disabled` bail.) With JS: `preventDefault`, fetch `data-tree-url` with
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
- The JS **also** bails, on `data-expand-all-disabled` (on `.builder`) — **not** on the parent's
  `data-container-count`, which would give the client a number and no threshold to compare it
  against (§3k). Two mechanisms for one rule, deliberately: the attribute is what the JS reads,
  the missing `href` is what the browser obeys. **The handler additionally returns early on
  `aria-disabled="true"`** — a `preventDefault`-then-fetch handler never consults the markup
  otherwise, so without this the disabled control still fires its request when clicked.
- **The comparison reads `builder_open.CEILING` through the module**, never
  `from courses.builder_open import CEILING`. `_info_entries` carries a load-bearing comment
  about exactly this (`views_manage.py:362-365`): tests monkeypatch the module attribute, and a
  by-value import desyncs the guard from the patched number. §8's ceiling test monkeypatches
  `CEILING` down, so a by-value import fails it confusingly rather than clearly.

### 6b. Collapse-all — no request at all

`replaceState` writes the full enumeration after an expand-all, so without an inverse every
subsequent reload re-renders the whole tree and the only escape is hand-editing the address bar.
Collapse is already client-owned (parent §5), so this costs nothing:

The control is `<a data-collapse-all>`.

- **JS: `preventDefault` first**, exactly as §6a's expand-all does and for a sharper reason —
  this handler issues no request, so without it the browser follows the `href` and the "no
  request at all" title is false: a full-page navigation that also discards §5d's module-scoped
  stash, the same hazard §5b names for the filter form's Enter key. Every otherwise-pinned
  assertion survives the bug, because after the navigation the server renders exactly the same
  collapsed toggles and the address bar holds `open=` from the href itself — so §8 pins it with
  a no-navigation guard.
- **JS:** remove every `ol.tree__scope[data-scope]:not([data-scope="top"])`; for each
  `[data-toggle]`, set `aria-expanded="false"`, remove `aria-controls`, and set `aria-label`
  from the server-rendered **`data-label-expand`** attribute; then `syncUrl`.
- **JS, the half that is easy to omit:** the `swapping` guard, **both halves of it**.

**Collapse-all inherits neither half of slice 1's dirty-rename guard, because both are bound to
`[data-toggle]`.** Slice 1 wraps the single-scope removal in `swapping = true / finally false`
(`builder.js:475-478`) *and* arms `swapping` at **`pointerdown`** on a toggle
(`builder.js:445-463`), with a comment recording why the later position does not work: a mouse
click moves focus at mousedown, so a dirty title's `focusout` fires **before** the click handler
runs, at which point the rename guard (`:420`, `if (swapping || !form.isConnected) return;`)
sees `swapping === false` and `isConnected === true` and `commitRename` posts for real.

Collapse-all is a new control, so clicking it with a half-typed title anywhere in the tree fires
a rename POST whose `applyRename` then no-ops on the detached form: **the database holds the new
title, the tree shows the old one, and nothing is reported.**

The existing arming is also deliberately **narrowed** to the clicked toggle's own subtree — its
comment names the case it protects (edit row A, click row B's toggle, and A's edit would be
silently swallowed) — so it cannot simply be widened.

**Rule for collapse-all:** arm `swapping` at `pointerdown` when `document.activeElement` is
inside *any* scope about to be removed (which, for collapse-all, is any non-top scope), and
latch it around the bulk removal.

**The accepted cost: a half-typed rename in a nested row is discarded, not committed.** That is
the right trade here and it differs from slice 1's narrowed case — there, an unrelated row
survives the gesture and its pending edit deserves its commit opportunity, so arming broadly
would lose an edit for no reason. Under collapse-all the row is removed either way, so the
choice is between losing the uncommitted text and shipping a database/tree divergence the
author is never told about. Recorded so it reads as a decision. **The e2e must drive a real mouse click**, not keyboard
activation — parent §5 records that a keyboard-only test verifies the one path that was already
correct.
- **No-JS:** `href` is the builder URL with `open=` — **present-but-empty**, per parent §2's
  rule. Omitting the parameter would re-seed from the session and collapse nothing. **It
  carries `q` too**, symmetrically with §6a.

**Both hrefs carry `q`** — the active kind, so a no-JS bulk expand or collapse stays inside the
filter, and the present-but-inactive kind (a below-floor `?q=a`), so the author's half-typed
text is still in the box when the page comes back.

**And both handlers rewrite their own href's `q` from the tracker when a filter or clear
response is applied.** §3j item 1's reason for never rewriting an href at click time — "every
filter transition re-renders the whole top scope" — holds for the delete and Move hrefs, which
live *inside* the swapped `<ol data-scope="top">`. These two do not: they sit in
`.builder__tree`'s header beside the filter, outside every fragment `applyFragment` swaps and
outside what `manage_tree` returns (§3g). The same fact forced §4 to hand the Clear control's
visibility to the JS and §3m to reject `data-applied-q` as a drag carrier. Left stale, a
middle-click or ctrl-click on "Expand all" over a filtered tree opens an **unfiltered**
`open=all` — the 944-row, ~2.5 s render this work exists to avoid, with the filter silently
dropped. One rule ("tree hrefs carry `q`") beats a
carve-out, and it keeps these two consistent with the toggle, delete and Move hrefs in §3j.

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
9. **Step 3 moves above BOTH session reads in `builder_open.open_ids`** — the `open=session`
   sentinel (step 1) and the `mode == "notice"` carrier — while still losing to step 2. A
   change to code slice 1 shipped. Without it every no-JS mutation under a filter shows a
   filtered map with unfiltered chains, i.e. matches invisible. See §3c.
10. **`_remember_open` no-ops while `q` is ACTIVE — narrower than the parent's "`q` is
    absent"** (`:616-617`). They differ on a below-floor `?q=a`: the parent forbids the write,
    this spec permits it, because that render is unfiltered and its `open` really is
    author-chosen. Slice 1 could not implement either version — this is unwritten code only
    this slice can write, not a "still holds" item. See §3l.
11. **The Move-picker fetch SETS `q` rather than appending it.** Parent §2 says "appends"; the
    href already carries a rendered `q`, so appending sends two values and works only because
    `QueryDict.get` takes the last — the accident parent §5 forbids by name. See §3j item 4.
12. **`_filter_context` returns a `FilterContext` record** carrying `q_raw` and both the
    pre-union and post-union open sets, rather than the parent's loose tuple. See §3a.
13. **The fold table deletes combining marks (U+0300–U+036F)**, so decomposed titles match. Not
    in the parent, which specifies `title__icontains`. See §1b.
14. **`data-expand-all-disabled` replaces the parent's `data-container-count`**, and
    `data-applied-q` is added. The parent has the JS compare a raw count against the ceiling,
    which would put a by-value `500` in `builder.js` — the duplication §6a forbids one bullet
    later, and one §8's monkeypatch test cannot catch. Both attributes now carry a
    server-resolved value instead of a number the client must interpret. See §3k.
15. **Five client paths send the APPLIED `q`, not the live input value** — submit, drop,
    toggle, picker and expand-all. The parent's collector rule makes the input authoritative;
    during the debounce that returns markup filtered by a query the pane is not showing. Only
    the filter fetch sends the live value. See §5a.
16. **The `[data-delete]` click-time rewrite sets `open` only.** Parent §4 (`:838`) has it set
    "the live `open` **and `q`**"; here the href's `q` is server-rendered and always current
    (every filter transition replaces the whole top scope), so rewriting it would make delete a
    sixth live-value sender on the one gesture that is a full-page navigation. See §3j item 1.
17. **`MIN_QUERY` reaches the JS as `data-q-min`, and the client floor strips combining marks
    before counting.** Not in the parent, which has no client-side floor. See §5c.

## 8. Testing

Per this repo's practice, tests are written to fail first, and **a test that cannot go red is
treated as not written**. Every guard below is falsified by deleting what it protects,
requiring RED, and restoring. Slice 1 shipped two tests that passed while guarding nothing
until this was done.

**`courses/builder_filter.py` — unit, no DB:**

- `fold` maps `ą ć ę ł ń ó ś ź ż` and their capitals to ASCII; **the `ł` case is the one that
  a generic NFKD fold silently fails**, so it is asserted explicitly in both directions
  (`laka` finds `Łąka`; `Łąka` finds `laka`)
- **the client floor never exceeds the server floor on Latin input** — over the Polish
  alphabet, `ß`, and the multi-character table entries, asserting
  `client_measure(ch) <= len(fold(ch))`. This is the direction that collapses the tree (§5c),
  and the measured Latin-script count of counterexamples is 0, so any regression is real.
  **`client_measure` is a stated Python mirror of §5c's expression, and its UTF-16 half must be
  explicit** — `len(stripped.encode("utf-16-le")) // 2` for the `.length` behaviour versus
  `len(stripped)` for code points — or the pinned `"\u{1D400}"` falsification is unreachable,
  since Python has no `.length` and both spellings would agree. Include `"a\u0085"`, which
  fails under a bare `trim()`.
  **This row guards the mirror, not `builder.js`.** An implementation that ships `.length`
  passes it, so the real coverage is the astral e2e below.
- **an NFD-normalized title is found by an ASCII query** — `fold(unicodedata.normalize("NFD",
  "Kąty"))` must equal `"katy"`. Falsified by dropping U+0300–U+036F from the table, which
  leaves `'kąty'` and is invisible in every precomposed fixture (§1b)
- the 2-char floor returns the map unchanged, empty chains and **`q_active is False`**, for
  `"a"`, `" a "`, `""` **and a decomposed single grapheme** (`unicodedata.normalize("NFD", "ą")`
  — two code points, one folded character, so a raw-length floor would wrongly let it through); an at-floor `"ab"` returns `q_active is True` **even when it matches
  nothing** — the distinction the fifth return value exists for
- **the returned map is never the argument**: `assert restricted is not cmap` and
  `restricted[parent] is not cmap[parent]`, on the **blank** path — the alias §1 forbids, and
  the one that no filtered test can catch
- **`q_chain` matters at the function boundary**: `open_ids(..., mode="page", q_chain=set())`
  on a ≤150-node fixture returns an **empty** set while `q_chain=None` returns every container.
  **`mode="page"` is not optional** — the signature's default is `"fragment"`, which skips step
  4 and returns the empty set for *both*, making the assertion vacuous. Measured. This is the
  §3b guard; it is a unit test on `open_ids`, **not** a render assertion, because the two are
  indistinguishable in markup (§3b) and a render test would pass vacuously
- the cap keeps exactly `MATCH_CAP` in `(order, pk)` order, and `total` reports the pre-cap
  count — asserted with **scattered, non-sequential pks**, since CPython iterates small
  sequential ints in ascending order and a `sorted` → `list` mutation would stay green
  otherwise (slice 1 hit exactly this)
- the walk includes a matched **container itself**, and every ancestor level
- the restricted map preserves sibling order and groups top-level nodes under `None`

**View / integration:**

- **`manage_tree` access control**, the same rows as `manage_node_scope` minus the pk row —
  four in total: anonymous → login redirect, non-manager → 403, foreign slug → 404, manager →
  200 with `data-scope="top"`. **Not** "non-numeric pk → 404" — that route has no pk, so such a
  test would guard nothing.
- **a filter request omits `open`**: with every scope collapsed, filtering for a title three
  levels down returns the match row
- **`q` rides every fragment request**: with a filter active, a rename 409, an add and a
  duplicate each return **filtered** markup. **Not a reorder or a drop** — §3m suppresses both
  while filtered, so they are not cases that exist; driving them here would pin behaviour the
  spec forbids.
- **expanding a scope under a filter returns only the filtered children of that scope** — the
  `nodes` half of §3k. Falsified by pointing `_render_scope`'s `nodes` back at the full map,
  which leaves `children_map` restricted and every other filtered test green.
- **a mutation under an active filter returns its own new row visible** (effect 2), across the
  buildable matrix: an add of a **unit**, an add of a **container**, and a **duplicate** (units
  only — `node_duplicate` raises `Http404("Only units can be duplicated.")` for any other kind,
  so a duplicated container is not a case that exists). The unit cases are the ones that fail
  when the kind test is put at the call site.
- **an add into an EMPTY filtered scope** — filter for a container title whose descendants do
  not match, then add inside it via the add affordance §1d ships into that scope. The
  destination has **no key** in the restricted map, so a `restricted[parent_id]` write raises
  `KeyError` → **500** (§3e). Nothing in the matrix row above requires an empty destination, so
  this needs its own row. The mirror case — filter matches nothing, add a top-level node,
  missing `None` key — is the same defect and the same row.
- **a no-JS add of a UNIT under a filter** shows the new row after the redirect (the
  `builder_force` channel, §3f), **and a second builder GET no longer force-includes it** — the
  half with no visible symptom when the clear is missing. The unit kind is load-bearing: a
  container would survive a `& container_pks(...)` intersection and hide the §3f trap.
  **Clear only `session["builder_open"]` between the GET and the POST**, never the whole
  session — `flush()` drops `_auth_user_id`, so the POST would measure a login redirect rather
  than force-inclusion.
- **a no-JS REPARENT under a filter, into a destination the filter excludes**, returns the
  moved node visible. This is the row that actually proves the stash carried a *chain*: an add
  form can only be submitted from a scope that is already visible, so its parent is a match or
  a walked ancestor either way and a bare-pk stash would pass. The Move picker is the one no-JS
  surface that offers a destination outside the restricted map.
- **force-inclusion is idempotent**: forcing a pk that the filter already matched yields
  exactly **one** `<li data-node=…>` for it
- **a force-included row does not move `shown`/`total`** in the emitted header
- **counts under a filter are the filtered counts**
- **the up/down arrows AND the grip render `disabled` under an active filter, and enabled
  without one** (§3m) — asserted on the rendered markup. The grip half is separate from its
  `draggable` removal: dropping `draggable` alone leaves `cursor: grab` / `grabbing` intact
  (`builder.css:62`, `:155`), so the row would still look draggable. Falsified by restoring the `is_first`/`is_last`
  gating alone, which leaves the arrows live at non-edge positions and lets a click mutate the
  full sibling order invisibly.
- **a reorder POST submitted under an active filter is refused** — 422 on **both branches**
  (§3m): with `X-Requested-With: fetch` it renders `_op_error.html`; without it, a full builder
  page via `_builder_with_notice`. Assert the full sibling order is unchanged in both. The
  no-JS half is the one that catches an unconditional `_op_error.html`, which is a bare
  unstyled fragment. The server cannot rely
  on the markup alone, since the form is trivially replayable.
- **…but a positioned REPARENT under an active filter still succeeds** — the Move picker's
  route (§3m). Both post to `node_move` and are indistinguishable server-side, so this row is
  what stops the guard being widened to "any positioned move" and silently breaking the only
  sanctioned way to move something while filtered.
- **a matched container renders OPEN over an empty scope** (§1d) — `aria-expanded="true"`,
  `aria-controls` present, and "No matching titles." inside, not a collapsed row
- **BOTH §3c session paths, each with `builder_open` populated and holding a set that is not
  the filter's chains:** (a) `_builder_with_notice` under an active filter returns the chains
  open; (b) a no-JS mutation **success** under a filter — which redirects to
  `?open=session&q=…` — returns the chains open. Path (b) is the common one and would stay
  broken if only (a) were pinned. Each falsified by moving step 3 back below its session read.
- **step 2 still beats step 3**: a no-JS toggle href under an active filter (carrying a real
  enumeration) renders that enumeration, not the chains — the half of §3c that a
  move-step-3-to-the-top implementation would break
- **`_remember_open` does not write while `q` is active** (§3l) — driven through **a toggle
  under an active filter**, asserted **on the session**, never on the render. A bare filtered
  GET resolves via step 3, which is not `explicit`, so it would pass without the rule.
- **…but DOES write under a below-floor `?q=a`** — a toggle with `?q=a&open=…`, asserting
  `session["builder_open"]` was updated. This is the half where §3l deliberately narrows the
  parent's "`q` is absent" to "`q` is active" (Delta 10), and the row above cannot guard it: a
  presence gate (`"q" in request.GET`) is strictly stricter and passes it too. Without this
  row the deviation is untested and a no-JS author silently stops persisting expansions
  whenever a stray `?q=a` sits in the URL.
- **a below-floor query is inactive on both response types** — the view-level twin of the unit
  floor test, and the one that catches a `q_active` derived from `bool(q.strip())`. Two
  assertions, because the two response types carry the signal differently and neither carries
  both: the **page** `?q=a` renders unfiltered markup with no `data-info-key="filter"` entry and
  **no header at all** (`builder()` never reaches `_render_scope`, §3i), while the **fragment**
  `manage_tree?q=a` returns `X-Builder-Info: none` and has no info slot to inspect
- **an empty filtered scope says "No matching titles.", an empty unfiltered one says "No
  children yet."**
- **the `X-Builder-Info` header is machine-readable** — never a non-ASCII byte, never an
  RFC-2047 `=?utf-8?` prefix — asserted **under the Polish locale**
- **one msgid per notice**, asserted under the Polish locale for both keys (§3i). The two
  routes are **not** directly comparable — the server interpolates (`"Filtrowane: 100 / 940"`)
  while the attribute keeps its placeholders (`"Filtrowane: %(shown)s / %(total)s"`) — so a
  literal equality assertion fails on a *correct* implementation. Assert instead that
  `data-msg-<key> % <the same placeholder dict the server used>` equals the page-rendered entry
  text. Goes red the moment a second catalog entry appears for the same notice.
- **`none` is emitted when no codes apply**, and codes join with `, ` when both apply
- **a rename, a 422 and a panel fetch under an active filter carry no header at all**
- **a filtered mutation re-asserts `filter;…`** — driven by an **add or a duplicate** (§3m
  rules out reorder and drop under a filter), never a rename, whose success response never
  reaches `_render_scope`
- **a filtered response carries exactly one `filter` code** in `X-Builder-Info` (the
  server-side half; the client-side registry behaviour is an e2e row, below)
- **the info slot is in the DOM on an UNFILTERED, untruncated builder page** and carries **no
  `hidden` attribute** — plus, in the same row, that the rendered element has **no text content
  at all**: assert the markup contains `<ul class="builder__info" …></ul>` with nothing between
  the tags (or that the parsed node's `contents` is empty). Two falsifications, both required:
  restore slice 1's `{% if info %}` wrapper (presence), and insert **one newline** inside the
  element (whitespace). The second is the one that matters — `:empty` does not match an element
  containing whitespace, so a newline leaves a sunken grey bar on every builder page,
  permanently (§3i) — and a presence-only assertion stays green through it. The browser-side
  `matches(":empty")` check is the e2e row below. Falsified by restoring slice 1's
  `{% if info %}` wrapper. The existing registry e2e cannot cover this: it starts from a `?q=`
  load, where the server rendered an entry and `{% if info %}` would produce the slot anyway.
- **a server-rendered notice is VISIBLE without JS** — a filtered page GET, asserting the
  `data-info-key="filter"` entry is present and its container is not `hidden`. This is the row
  that stops the always-present slot regressing slice 1's truncation notice into an invisible
  one on the no-JS path (§3i).
- **toggle hrefs preserve `q`**, and a no-JS mutation under a filter returns to the filtered
  tree
- **the four no-form carriers of §3j**, driven with a query containing **a space and an `&`**
  so the encoding is exercised rather than assumed: the delete href and the Move href carry a
  **percent-encoded** `&q=` **in the markup** — a bare `{{ q }}` lets `x&open=all` arrive at the
  delete confirm as a second parameter; `node_delete`'s bespoke redirect (`views_manage.py:673-674`) carries `q` —
  **driven with an `open`-bearing confirm GET**, i.e. the JS-rewritten path, because a plain
  no-JS delete takes `:675` instead and would pass on the six-site edit alone; and the no-JS
  Move-picker round trip lands back on the filtered tree
- **the builder view still issues one query** with a filter active
- **expand-all renders disabled above the ceiling** (`CEILING` monkeypatched down) and enabled
  below it, asserted on the **absence of `href`**, not on a CSS class
- **both bulk controls stay enabled under an active filter** (§6z), and **expand-all under a
  filter returns only filtered rows** — `open=all` + `q` renders the restricted map, never the
  944-row tree
- **both bulk-control hrefs carry `q`**, both the active kind and a present-but-inactive
  `?q=a` — and, in an e2e, **still carry the right `q` after a JS filter apply** (§6b), since
  they sit outside every swapped fragment and would otherwise open an unfiltered `open=all` on
  a middle-click
- **`data-applied-q` holds the raw submitted `q`** — on a filtered render *and* on a
  below-floor `?q=a` (where it is `a`, not empty), and **present-and-empty** with no `q` at
  all. **The empty case is asserted as *present*** because a conditionally-emitted attribute
  puts `null` in §5z's tracker without any symptom at load: the `TypeError` comes later, inside
  the `input` handler, and leaves **filtering silently inert** while the rest of the builder
  works (§3k). There is nothing to notice at runtime, so the attribute has to be pinned here.
  Asserted on the attribute's **value**: one failure it guards is a bool rendering as the
  string `"True"` (§3k), the other is a below-floor `q` being dropped so the JS and no-JS
  paths of the same gesture disagree.
- **`data-expand-all-disabled` is present over the ceiling and ABSENT under it** — asserted on
  presence, never on a value, per §3k's emission rule
- **`data-q-min` equals `builder_filter.MIN_QUERY`**, with `MIN_QUERY` monkeypatched to a
  non-default value, **on `builder()` AND on `_builder_with_notice()`** — the notice page is
  where a hand-patched attribute goes missing and `parseInt(null)` silently kills filtering
  (§3k). This row guards the **attribute**, not the JS: a hardcoded `2` in `builder.js` passes
  it either way. The client half is the e2e row below. Without it a by-value `2` in
  `builder.js` ships green and the two constants desync the moment `MIN_QUERY` moves.

**e2e (`-m e2e` — mandatory, or the tests are silently deselected and pytest exits 5, which is
not a pass):**

- type a query, assert only matching and ancestor rows are present
- **drag is inert while a filter is active** (§3m) — attempt the real drag gesture under a
  filter and assert no `node_move` request and an unchanged full-course order. This is the row
  that catches the `targetFor`-index-into-full-list defect, which produces no error and no
  visible symptom in the filtered pane. Drive the real gesture, never `page.evaluate`.
- **the filter fetch omits `open`, asserted where it can go red** — **collapse the target row's
  ancestor chain first**, then type the query and assert the match appears. Without the collapse
  the test is vacuous: filtering is done by the restricted map, so sending `open=<collector>`
  and sending nothing produce byte-identical rows on any tree whose match ancestors are already
  open — which is every fixture small enough to land fully expanded under step 4. Belt and
  braces: also assert the outgoing request URL has no `open` parameter, as the toggle row
  already does for `q`.
- **expand a scope while `q` is active** and assert only matching/ancestor rows return —
  **and that the toggle's own request carried `q`** (§5a; falsified by reverting the toggle to
  `withOpen`-less parameter building, which is how the defect would actually reappear)
- **filter → clear restores the pre-filter expansion** (the stash), and **filter → mutate →
  clear** lands on the **collector fallback**. **The setup is load-bearing: collapse the
  destination chain BEFORE filtering**, so the pre-filter stash excludes it; then filter (which
  opens the chain), add there, and clear. Only then does a stale stash hide the created row and
  the assertion go red. Without the collapse the row is vacuous on every builder fixture — they
  are all small enough to land fully expanded under precedence step 4, so the destination is
  already open in the stash and the created row is present either way, which is exactly the
  vacuity this row's "assert on the created row, not on non-emptiness" wording was meant to
  avoid.
- **a superseded clear does not consume the stash** (§5d) — issue two clears in flight, drop
  the first by the generation counter, and assert the surviving one still restores the
  pre-filter expansion rather than falling back to the collector's filtered chains
- **collapse everything, filter, clear** — the tree comes back **empty**, not filled with the
  filter's chains (the `stash === null` rule; falsified by changing it to `if (!stash)`)
- **a below-floor query takes the clear path** — type `tryg`, then delete down to `t`, and
  assert the unfiltered tree is back rather than stale filtered markup
- **the Clear control appears after typing a query into an UNFILTERED page** (§4) — the
  server never rendered it, so only the JS visibility rule can produce it; and it disappears
  again when the box is emptied. This is the row that catches a server-only `{% if q %}`, which
  leaves the Firefox author the control exists for with no one-click clear at all.
- **clicking the Clear LINK with JS on does not navigate** (§4) — asserted with the
  no-navigation guard, and the pre-filter expansion is restored. Falsified by removing the
  interception: the page still ends up unfiltered, so only the navigation guard and the
  surviving expansions can tell the two apart.
- **a `?q=<match>` page load, then clear** — returns the unfiltered tree. Falsified by
  initialising the applied-`q` tracker to `""` instead of the server-rendered active `q`, which
  makes the clear a no-op and leaves filtered markup over an empty input (§5c).
- **a single astral character issues no filter fetch** — type `\u{1D400}` into the box and
  assert no `manage_tree` request and untouched expansions. This is the one row that can go red
  against a `.length` client measure (§5c), which is worth ~1M characters of tree-collapsing
  exposure; every other floor row uses BMP input, where the two spellings agree.
- **the client reads `data-q-min` rather than hardcoding it** — monkeypatch `MIN_QUERY` to 3
  and assert a 2-character query issues **no** filter fetch. The view-level row asserts the
  attribute; only this one can go red against a by-value `2` in `builder.js`.
- **typing below the floor into an UNFILTERED tree issues no request at all** (§5c) — expand
  several scopes, type `t`, and assert no `manage_tree` request was made and the expansions are
  untouched. Falsified by keying the guard off the input's contents instead of the applied `q`.
- **pressing Enter in the filter field applies the filter without navigating** (§5b) —
  asserted with the no-navigation guard slice 1 already uses, since a full-page load would also
  *look* filtered while silently discarding the stash
- **a clear is not overwritten by an in-flight FILTER response** — hold a filter response with
  `page.route` until a subsequent clear has landed, then release it, and assert the tree is
  unfiltered, the `filter` entry is gone and the URL has no `q`. This is the row that requires
  **one** generation counter across all `data-tree-url` requests (§5b); with a counter per path
  the released filter response repaints filtered markup over an empty input.
- **an out-of-order filter response is discarded** (the last-wins id). **The row must force
  the reversal** — hold the first `manage_tree` response with `page.route` until the second has
  landed, then release it — and assert the pane shows the *later* query's rows. "Two rapid
  queries" cannot go red: below 300 ms the debounce coalesces them into one fetch, and above it
  a local server answers FIFO, so the test passes with no last-wins id at all. §5b's own
  argument is that debounce is not last-wins; the test has to reproduce the case the argument
  names.
- **a toggle fired inside the debounce window carries the APPLIED `q`, not the typed one**
  (§5a) — apply `tryg`, type `trygo`, toggle before the debounce fires, and **assert on the
  toggle's outgoing request URL** (`q=tryg`, not `q=trygo`) via a request listener. **Not on the
  rendered children**: at t≈300 ms the `trygo` filter fetch lands and `applyFragment` replaces
  the whole top scope, taking the inserted children with it — so a DOM assertion has a window of
  300 ms minus the toggle round trip and goes red against a *correct* implementation whenever
  the toggle is slow. That is this repo's recorded "assert on requests, not on a sampled race
  window" trap. A rendered-children check may follow as a secondary, timing-tolerant assertion.
- **expand-all then collapse-all** returns to the top rows, and the address bar holds `open=`
- **the address bar after APPLYING a filter** — type `tryg` into an unfiltered builder and
  assert the URL holds `?q=tryg`. Nothing else covers this: every other address-bar row asserts
  a *clear* outcome, and the `?q=<match>` rows start from a server-rendered URL. Falsified by
  moving §5b's tracker write after `syncUrl`, which is the natural order to write it in.
- **the address bar after a clear** — clearing an applied `tryg` leaves no `q`; clearing it
  down to a below-floor `t` leaves `?q=t`, not `?q=tryg`; and a collapse-all under an active
  filter leaves `q` untouched. All three go red if the tracker is written after `syncUrl`
  instead of before it (§5d), and the third also catches `syncUrl` reading "what this request
  sent" on a path that sends nothing (§5a).
- **a toggle on a below-floor `?q=a` page leaves `q=a` in the address bar** (§5a's `syncUrl`
  rule) — falsified by gating `syncUrl` on `q_active` instead of on blankness, which strips the
  author's half-typed text on the JS path only
- collapse-all sets `aria-expanded="false"` and removes `aria-controls` on every toggle
- **the empty info slot is not rendered** — `document.querySelector(".builder__info").matches(":empty")`
  is true and its computed `display` is `none`, **both on an unfiltered untruncated page at
  load AND after a filter → clear cycle** (§3i). The second is the half that catches the JS
  leaving a whitespace text node behind, which makes the sunken bar permanent; every
  server-side `:empty` row is taken before the JS has written anything.
- **a fragment-borne notice lands on a page that had none** — load an unfiltered, untruncated
  builder, type a query, and assert a `[data-info-key="filter"]` entry appears. Without §3i's
  always-present slot the JS has nowhere to insert, and the resulting throw is swallowed by the
  `.catch` and mislabelled "Network error" (M15) while the tree still updates, so no other row
  notices.
- **the info slot replaces by key**: from a `?q=<match>` **page load**, two successive filter
  fetches leave `document.querySelectorAll('[data-info-key="filter"]').length === 1`. Falsified
  by skipping §3i's "read the server-rendered entries on init" step, which makes the second
  entry an append — the test must go RED there or it is guarding nothing.
- **clearing the filter removes the `filter` entry** — filter until it is on screen, clear,
  assert `[data-info-key="filter"]` is gone. This is the only path on which `none` does any
  work (§5d); falsified by making the JS ignore the `none` header, which leaves a stale
  "Filtered: 100 / 940" over an unfiltered tree while every server-side row still passes.
- **an absent `X-Builder-Info` does NOT clear the slot** — filter until the `filter` entry is
  on screen, rename a visible row (whose 200 is `_rename_result.html` and carries no header),
  and assert the entry is still there. §8's server-side row proves only that the header is
  absent; this is the half that proves the client *ignores* an absent header rather than
  clearing on it — the defect Delta 2 exists to prevent, and one that a "no header → clear"
  implementation passes every other test with.
- **the Move-picker fetch sends exactly ONE `q` parameter** — open the picker under an active
  filter and assert the outgoing request URL has a single `q`. An append implementation yields
  `?node=5&q=X&q=X`, which `QueryDict.get` resolves correctly, so every server-side and no-JS
  assertion stays green while Delta 11 is violated.
- **expand-all DOES fire a request under the ceiling, and does NOT over it** — both directions.
  The under-ceiling half is the one that catches a `data-expand-all-disabled` emitted by value
  (§3k), where the bail fires on every course and the control is silently dead everywhere.
- **collapse-all does not navigate** (§6b's `preventDefault`) — asserted with the
  no-navigation guard, since after a navigation the server renders the same collapsed toggles
  and the same `open=` in the address bar, so every other collapse-all row stays green
- **collapse-all over a dirty rename posts nothing** (§6b) — driven with a **real mouse click**,
  not keyboard activation, because focus moves at mousedown and the keyboard path is the one
  that was already correct. Falsified by removing the `pointerdown` arming.

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

This slice adds **eight new msgids** — the `filter` notice text, "Clear", "Expand all",
"Collapse all", the over-ceiling tooltip, "No matching titles.", the filter input's accessible
name "Filter by title" (§4), and the reorder refusal's *"Clear the filter to reorder."* (§3m) —
and gives **two existing msgids a further reference**.
So the catalog work is a task, not an afterthought.

**Each notice text is ONE msgid used twice.** The same literal appears in `_info_entries`'s
`_(…)` and in the `data-msg-<key>` attribute, deliberately (§3i), so `makemessages` collapses
them into a single entry. Two entries for one notice is the defect, not the baseline — it lets
the page and the fragment route disagree in translation.

**Two of the strings are NOT new, and the count is a review signal — if the diff shows a new
entry for either, the literals have drifted apart.**

`msgid "Filter"` already ships with five references (`locale/pl/LC_MESSAGES/django.po:3509`),
one of them in `templates/courses/manage/media/manager.html:36` — the very file §4 models its
markup on. The submit button reuses it; only the field's accessible name is new.

**The `truncation` text is NOT new either.** `_("Only the first %(limit)s scopes were opened.")` shipped
in slice 1 (`views_manage.py:369-370`) and is already in both catalogs
(`locale/pl/LC_MESSAGES/django.po:2237`). Adding `data-msg-truncation` gives it a second
reference, not a second entry — and if the diff shows a new entry for it, the literals have
drifted apart.

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

- **Re-enabling drag and the up/down arrows under an active filter** (§3m). Deferred
  deliberately, and recorded here as future work rather than a closed question: the decision to
  suppress them is the cheap correct answer, not the only one. Making them work means giving
  the ordering path a filter-independent way to express a position — carry the neighbouring
  sibling's **pk** instead of a visible-list ordinal, and have `ordering.place_node` and
  `builder.reorder_node` resolve it against the real sibling list. That is a change to two
  shipped service functions plus the drag payload and the reorder form, so it belongs in its
  own PR with its own tests, not bolted onto a filter slice. Until then the Move picker is the
  documented route for moving things while filtered.
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
