# Depth-3 nesting

One containment rule for every container: lift the nesting cap from 2 to 3 and replace
three bespoke container implementations with one registry-driven path.

**Date:** 2026-08-02
**Base:** master `901f6cf0`
**Slice:** B1 of 2. B2 (Callout as a fourth container) is a separate PR, OUT of scope here.

---

## Purpose

Authors cannot currently express three shapes the maths content needs:

- a spoiler inside a spoiler (a hint whose deeper hint is itself hidden);
- a tabs element inside a spoiler;
- a spoiler inside a tabs element **with children of its own** — today a spoiler nested in
  a tab is forced to be childless, so it degrades to a legacy body-only spoiler. This shape
  is directly guarded by an existing test
  (`courses/tests/test_spoiler_nesting.py:210-224`), which must invert.

All three are blocked by the same thing: a depth-2 cap that is not a stated rule but an
assumption baked into four independent places, plus a fourth container type
(`SpoilerElement`) that never joined the container registry and is instead special-cased
in five files on the runtime paths, plus the one-time LAL loader.

This slice states the rule once, enforces it in one place per surface, and fixes the four
code paths that silently assume one level of nesting.

The remaining two slice-B cases (tables in callouts, math in callouts) need Callout to
become a container and ship in the follow-up PR. The registry introduced here is the seam
that PR plugs into: **Callout must become one registry entry, not a sixth special case.**

## The containment rule

```
MAX_NEST_DEPTH = 3          # a top-level element has depth 1

a child of `parent_join` in slot `slot` is admissible iff
    1. type_key ∈ NESTABLE_TYPE_KEYS
    2. slot ∈ slots(parent_container)
    3. depth(parent_join) < MAX_NEST_DEPTH
    4. if depth(parent_join) == MAX_NEST_DEPTH - 1: type_key is NOT a container type
```

Clause 4 is the "depth 3 is leaves only" decision. A container placed at depth 3 could
never hold anything: it would render slots that cannot be filled and an add-menu that 400s
on every click. Containers therefore live at depth 1 or 2 only.

### One allowlist

`SPOILER_CHILD_TYPES` is **deleted**. Every container admits the same set.

`NESTABLE_TYPE_KEYS` gains `tabs` and `two_column`, going from 19 to 21 entries. Both are
already in `courses.transfer.export.SERIALIZERS`, so the standing invariant
`NESTABLE_TYPE_KEYS ⊆ set(SERIALIZERS)` continues to hold. Several existing tests assert
that invariant; it must not be weakened to accommodate this change.

`_NESTABLE_FORM_KEY_ALIASES` gains `"twocolumn": "two_column"` — the editor form key and
the transfer key diverge for that type, exactly as they do for `revealgate`. `tabs`
coincides in both namespaces and needs no alias.

**State plainly, because these are real widenings beyond containers:**

- Spoilers newly accept `html`, `stepper`, `mark_done` and `guess_number`, which
  `SPOILER_CHILD_TYPES` excluded. Its cost is the `has_html` fix below.
- Fill-in-the-blanks becomes offerable inside tabs and two-column containers, not just
  inside spoilers — see the `_add_menu.html` section, where its inclusion guard changes
  from `in_spoiler` to `nested`. `fill_blank` was already in `NESTABLE_TYPE_KEYS`, so this
  widens the **editor surface**, not the server rule.
- The LAL loader's child-type gate would widen by seven types if naively repointed; this
  spec keeps it narrow instead — see the LAL loader section.

### Depth is computed, not stored

`depth(join)` walks the `parent_id` chain. No new column, **no migration**.

**The walk must be a hop-counting loop that reads `MAX_NEST_DEPTH`, not a hard-coded
two-hop conjunction.** A hard-coded `join.parent_id is not None and
join.parent.parent_id is not None` produces the right answer today but hard-codes the cap
in a second place, so raising `MAX_NEST_DEPTH` later would silently not raise the cap.

```python
def element_depth(join):
    """1 for a top-level element. Bounded: never walks more than MAX_NEST_DEPTH hops,
    so a corrupt parent cycle returns a too-deep value instead of looping."""
    depth = 1
    parent = join.parent
    while parent is not None and depth <= MAX_NEST_DEPTH:
        depth += 1
        parent = parent.parent
    return depth
```

The loop bound exists **only** for cycle safety. It is not what makes `MAX_NEST_DEPTH`
load-bearing — clauses 3 and 4 comparing against the constant are. (Verified by tracing:
`element_depth` returns `[1,2,3,4,4]` for chains of depth 1–5 and `4` for both a 2-cycle
and a self-cycle.)

**Query cost.** `resolve_scope` currently fetches the parent join at `builder.py:122` with
`Element.objects.filter(pk=..., unit=unit).first()` and no `select_related` at all.
`select_related("parent")` would cover only one hop, leaving `parent.parent` as a fresh
query for exactly the depth-2 parents this slice newly enables. Use
`select_related("parent__parent")` — `MAX_NEST_DEPTH - 1` hops — so the walk adds no round
trips on the add path.

## Architecture / components

### The container registry and its key space

Three different key spaces exist today and the spec must say which is canonical, or
clause 4 cannot be implemented at all: `_CONTAINER_REGISTRY` (`courses/builder.py:99-102`)
is keyed by **model class**; `_CONTAINER_SLOT_KEY` (`courses/transfer/payloads.py:750`) is
keyed by **transfer type string**; the add-menu needs **form keys** (`tabs`, `twocolumn`,
`spoiler`).

**Decision: the transfer key is canonical.** One registry, keyed by transfer key, whose
entry carries everything the three call sites need:

| Entry field | Used by |
|---|---|
| transfer key (the dict key) | `validate_nesting`, clause 4 |
| model class | `resolve_scope`, `walk_unit_joins` (which hold a model instance) |
| form key | the add-menu's container-card predicate |
| slot ids for an instance | `resolve_scope` clause 2, `validate_nesting` clause 2 |
| ordered children in a slot | `walk_unit_joins`, the editor and student templates |

Two derived lookups are built from it at module level: **by model class** (for the call
sites holding a `content_object`) and **by form key**. `_CONTAINER_SLOT_KEY` in
`payloads.py` is **deleted** and its callers read the canonical registry.

Clause 4 asks "is this type key a container?" after normalizing the incoming form key
through `_NESTABLE_FORM_KEY_ALIASES`, then tests membership in the canonical registry.

A multi-slot container derives slot ids from its non-destructive normalizer, as today; a
single-slot container returns a constant `{SLOT_ID}`.

**The destructive/non-destructive distinction is load-bearing and must survive the
refactor.** `normalize_data` pads, truncates and mints fresh random ids on every call; a
write path that validated a slot against it could admit an ephemeral phantom id that never
matches at render time, silently orphaning the child. Slot validation on any write path
reads the **non-destructive** normalizer only. The comment recording this at
`builder.py:143-147` must not be lost.

### Fold Spoiler into the registry

`SpoilerElement` is special-cased in five runtime places today, plus the LAL loader:

| Site | File |
|---|---|
| write-path scope resolution | `courses/builder.py:128-142` |
| import validation | `courses/transfer/payloads.py:774-786` |
| export walk | `courses/transfer/export.py:498-500` |
| editor row template | `templates/courses/manage/editor/_element_row.html:136` |
| math detection | `courses/views.py:245-256` (`_spoiler_has_math`) |
| (one-time import tool) | `courses/lal_loader/builders.py:90-125` |

After the refactor, `resolve_scope` has no `isinstance(parent_obj, SpoilerElement)`
branch, and neither do `validate_nesting` nor `walk_unit_joins`.

**The other two sites keep their isinstance dispatch in this slice**, and saying so matters
because a coverage-table mutant targets one of them:

- `_element_row.html:136` keeps its `content_type.model == "spoilerelement"` branch; only
  the `and el.parent_id is None` clause is removed (see Defect 4).
- `_spoiler_has_math` (`views.py:245-256`) and its dispatch at `views.py:202` are left
  **as-is**. Folding math detection into the registry is a tempting but separate
  refactor; doing it here would delete the line a named mutant points at.

### Components touched

- `courses/builder.py` — `MAX_NEST_DEPTH`, `element_depth`, the canonical registry,
  `resolve_scope` (incl. `select_related("parent__parent")` at `:122`), the recursive
  subtree delete, the tab-removal cleanup.
- `courses/transfer/export.py` — recursive, cycle-safe `walk_unit_joins`.
- `courses/transfer/payloads.py` — hop-bounded `validate_nesting`; delete
  `_CONTAINER_SLOT_KEY`; three message changes plus one new message (see Error handling).
- `courses/views.py` — `has_html` in both context builders; remove the now-unused
  `html_ct_id`. `_spoiler_has_math` and its dispatch are deliberately NOT touched.
- **Stale comments and docstrings that become false**, all of which must be rewritten
  rather than left in place — this repo has a test that regexes raw source including
  comments, and an earlier slice already had to retarget stale comments as a follow-up:

  | Site | What becomes false |
  |---|---|
  | `payloads.py:754-757` (`validate_nesting` docstring) | "a parent chain deeper than one level -- that depth bound is what lets the editor's recursive row template terminate without a guard" |
  | `builder.py:404-407` (`delete_element` docstring) | "If it is a tabs element, its children's CONCRETE rows must go first" — now every container, at every level |
  | `builder.py:58-63` (the `SPOILER_CHILD_TYPES` header) | deleted with the constant; describes "the depth-1 leaf-only scope" |
  | `views_manage.py:1534-1539` | "'choicequestion' and 'tabs' are the cases here that actually reach resolve_scope and **prove nesting is blocked**" — `tabs` becomes an accept |
- `templates/courses/manage/editor/_element_row.html` — depth threading, spoiler branch,
  and **`:177` must drop `in_spoiler=True` and add `depth=depth`**; that line is the sole
  producer of the flag every consumer of which is being deleted, and leaving it behind
  would read as a live flag to the next maintainer.
- `templates/courses/manage/editor/_editor_scope.html` — **seeds `depth`**; see below.
- `templates/courses/manage/editor/_add_menu.html` — drop `in_spoiler`, add depth rules.
- `courses/lal_loader/builders.py` — allowlist decision (see LAL loader section).
- **Author-facing help docs, all four:** `docs/help/course-admin/content-editors.md:121-133`
  and its Polish twin `content-editors.pl.md:131-145` both state
  "Tabs and Columns are the two container types … A container cannot hold another
  container" / "Kontener nie może zawierać innego kontenera"; `interactive-elements.md:9`
  and `interactive-elements.pl.md:10` both say elements are "nestable inside Tabs and
  Columns". Every one of those sentences becomes false and these docs are served to
  authors. New wording must state: three container types (Tabs, Columns, Spoiler);
  containers admissible at depth 1–2; depth 3 is leaves only; fill-in-the-blanks now
  offered in any nested menu. Two further passages in `content-editors.md` also become
  false and must be rewritten: `:123-129` says the nested menu "offers only the **nine**
  non-container Content types" and enumerates them (Tabs and Columns join that group at
  depth 1), and `:131-133` says "inside a quiz a Tabs or Columns container's add-menu
  offers Content types only". Both have Polish twins.

### Seeding `depth` (the silent-failure trap)

`templates/courses/manage/editor/_editor_scope.html:11` is the **only** non-recursive
entry into `_element_row.html`, and `:15` includes `_add_menu.html` with no `with` clause.
If `depth` is left unseeded it resolves to the empty string, `{{ depth|add:1 }}` yields
`''` and never increments, and Django's `smartif` swallows the comparison `TypeError` so
`{% if depth < 2 %}` evaluates **False** — silently hiding the Tabs/Columns cards from the
**top-level** menu. This fails quietly, so the seed values are specified here rather than
left to the implementer:

- `_editor_scope.html:11` includes `_element_row.html` with `depth=1`.
- `_editor_scope.html:15` includes `_add_menu.html` with `depth=0` (the depth of the menu's
  *container*; its children land at depth 1).
- Each container branch in `_element_row.html` includes its child rows with
  `depth=depth|add:1` and its add-menu with `depth=depth`.

**The seeds must be unquoted numeric literals.** `{% include … with depth=1 %}` parses `1`
as an int; `depth="1"` binds a string, and while `{{ depth|add:1 }}` still yields `2`,
`{% if depth < 2 %}` evaluates **False** because smartif swallows the `str < int`
`TypeError` — reproducing the exact silent-hide failure with a seed apparently present.
Any test context must likewise pass `int`, not `str`.

A test must assert the **top-level** add menu still offers Tabs and Columns, or this
regression ships silently.

## Data flow

### Write path (authoring)

`manage_element_add` / `save_element` → `resolve_scope(unit, parent_ref, tab, type_key)`
→ (parent_join, slot_id) or `NestingError` → 400. `resolve_scope` is the single write-side
gate and enforces all four clauses of the rule.

### Render path (student)

Unchanged in shape. Every container's `render()` emits `{% render_element child %}` per
child, which dispatches recursively. Container walkers filter `parent__isnull=True` so
children render inside their container, not as top-level siblings. This already terminates
at any depth on acyclic data; depth 3 needs no change here.

### Transfer path

Export: `walk_unit_joins` yields `(join, parent_join, slot_id)`, parents before children,
each element exactly once — recursing through the registry's slot accessor.

Import: **needs no change, and this is pinned here so review does not invent work.**
`courses/transfer/importer.py` pass 1 creates every element join with `parent=None` in
payload order; pass 2 (`importer.py:903-909`) links `join.parent = joins[parent_ref]` from
a flat id map, saving only `["parent", "tab_id"]`, never `order`. A grandchild is linked by
the same mechanism as a child.

### Delete path

`delete_element` and the tab-removal branch collect the element's whole subtree and delete
concretes deepest-first, then let the join rows cascade.

**Termination is by a `seen` set of visited join pks, NOT by a depth bound.** A depth bound
would silently truncate on data deeper than the rule permits — and such data is reachable
in practice, since this spec's own depth-3 editor fixture is built by writing `Element`
rows directly through the ORM. Truncating is precisely the orphaned-concrete failure this
slice exists to fix, so the walk must collect everything and terminate on revisit instead.

## Defects that depth 3 creates

Four places hard-code "one level" as an assumption rather than a stated rule.

### 1. Deleting a container orphans grandchild concretes

`builder.delete_element` (`courses/builder.py:411`) deletes the concrete objects of
`Element.objects.filter(parent=el)` — exactly one level. Join rows cascade recursively
through the `parent` FK, but a concrete element row is reachable only through the `Element`
GFK, which DB cascade cannot traverse. At depth 3, deleting a top-level container leaves
every grandchild concrete orphaned in its table.

The same assumption sits in the tab-removal path, `builder.save_element`'s
`type_key == "tabs"` branch (`courses/builder.py:670`): removing a tab that held a container
that held a leaf orphans the leaf's concrete.

**Fix:** one cycle-safe subtree collection (see Delete path) used by both sites, deleting
concretes deepest-first.

**Not affected — do not "fix" these:** `Course.delete` (`models.py:166`) sweeps
`Element.objects.filter(unit__course=self)` and `ContentNode.delete` (`models.py:230`)
sweeps its whole node subtree. Both are already flat over every element regardless of depth.

### 2. Export drops depth-3 content, so Duplicate Unit silently loses it

`walk_unit_joins` (`courses/transfer/export.py:473-500`) expands exactly one level.

`builder.duplicate_unit` runs through `build_export`. So duplicating a unit that contains a
table inside a spoiler inside a tab produces a copy with the table **missing, with no error
surfaced to the author**. This is the highest-severity item in the slice.

**Fix:** recurse the walk through the registry's slot accessor, still yielding parents
before children — the import's payload-order pass depends on that ordering to reproduce
within-slot order without serializing `order`.

**Carry a `seen` set of visited join pks in the export walk too**, omitting an
already-visited join — matching the existing convention that a child whose `tab_id` matches
no slot is deliberately omitted rather than exported into an unimportable archive.

**But be honest about why: a cycle is NOT reachable here today.** `export.py:539` builds
`joins_by_unit` from `Element.objects.filter(unit_id__in=..., parent__isnull=True)`, and
the walk descends only through the slot accessors, which read `join.children`. Because
`Element.parent` is a single-valued FK, every node in a cycle has a non-null parent and is
therefore never a root, so the subgraph reachable from `parent__isnull=True` roots is
acyclic by construction. The `seen` set here is defence for a future non-root entry point,
not a live hang. **No test is expected to cover the export cycle branch** — the reachable
cycle is on the delete path (see Defect 1), which starts from an arbitrary request-supplied
`element_pk` and therefore *can* sit inside a cycle.

The existing docstring rule stays true and must be preserved: children are reached ONLY
through the slot accessors, never `join.children.all()`.

### 3. The import validator must walk — and must be hop-bounded

`validate_nesting` (`courses/transfer/payloads.py:753-807`) rejects nesting with
`if parent["parent"] is not None`. It becomes a chain walk enforcing clauses 3 and 4.

**The walk must count hops, not walk until `None`.** Today a parent cycle in a corrupt or
hostile archive (A → B → A) cannot loop, because only one level is ever inspected. A naive
`while parent is not None` walk would hang the import worker on such an archive. The walk
terminates after at most `MAX_NEST_DEPTH` hops and raises the ordinary validation error.

**Which clause fires is payload-order dependent, and both are reachable.** `validate_nesting`
builds `by_id` up front and then iterates `elements` in **payload order**, with `_err`
raising on the first violation (`payloads.py:31-32`); nothing requires parents to precede
children. So:

- A **parents-first** depth-4 archive trips **clause 4** first (the depth-3 container is
  examined before its child).
- A **child-before-parent** archive such as
  `[A(tabs, top), B(tabs, child of A), D(text, child of C), C(tabs, child of B)]` reaches
  `D` first, whose parent `C` is already at depth 3 — so **clause 3** fires and clause 4
  never runs.

Each clause therefore needs its own fixture with its own payload ordering, and each test
must assert the **specific message**, or the two clauses are indistinguishable and both
mutants are vacuous. An earlier draft of this spec claimed clause 3 was
unreachable-by-construction here; that was wrong, and the counterexample above is why.

### 4. The editor recursion needs a real depth guard

`templates/courses/manage/editor/_element_row.html` carries three comments asserting "the
realized depth is always exactly 2. There is no depth guard here." (lines 68-73, 114-119,
160-164). All three become false and must be rewritten, not merely left in place.

- The spoiler branch condition `el.content_type.model == "spoilerelement" and
  el.parent_id is None` (line 136) loses the `parent_id` clause. That clause is precisely
  why a nested spoiler currently falls through to the leaf `{% else %}` branch and renders
  with no children and no add-menu.
- A `depth` variable is threaded through the recursive `{% include %}` in all container
  branches, seeded as specified above.
- **Positive requirement, or this slice ships as a UI no-op:** `_add_menu.html:24-25`
  currently guards the Tabs and Columns cards with `{% if not nested %}`, and the Spoiler
  card with `{% if not in_spoiler %}`. Those guards must be **replaced** by a depth
  predicate so the three container cards ARE offered inside a depth-1 container. An
  implementer who only implements the "hide at depth 2" half satisfies every other sentence
  in this spec and ships a feature the server accepts but no author can reach.
- At depth 2, `_add_menu.html` hides the **three** container cards — Tabs, Columns,
  Spoiler. Callout is a plain leaf in this slice (`_add_menu.html:23` carries no guard and
  `callout ∈ NESTABLE_TYPE_KEYS`); hiding it at depth 2 would wrongly forbid a legal
  depth-3 leaf. Callout becomes the fourth container only in PR2.
- At depth 3, no add-menu is emitted at all. This is defence in depth rather than a
  reachable authoring state: clause 4 means no container can legitimately sit at depth 3,
  so the fixture for its test is built by creating `Element` rows directly through the ORM,
  bypassing `resolve_scope`. Say so in the test, or the next reader will delete it as dead.

## Consequences of the single allowlist

### `has_html` is already wrong, and this widens its exposure

`_add_menu.html:20` offers the HTML card whenever `not in_spoiler`, which includes
nested-in-tabs, and `html` is in `NESTABLE_TYPE_KEYS`. But `has_html` is computed over the
top-level list only:

- `courses/views.py:346` — `any(el.content_type_id == html_ct_id for el in elements)`,
  where `elements` is filtered `parent__isnull=True`
- `courses/views.py:1198` — the quiz context's equivalent, in a **different shape**:
  `any(isinstance(el.content_object, HtmlElement) for el in elements)`, an isinstance walk
  rather than a CT-id compare

So an HTML element authored inside a tab today never loads `html_element.js`
(`lesson_unit.html:67`, `quiz_unit.html:23`) unless an unrelated top-level HTML element
happens to exist. This is a **pre-existing** defect, not one this slice creates. It is fixed
here because the single allowlist newly admits `html` into spoilers, and because every
sibling flag (`has_questions`, `has_reveal_gate`, `has_switch_grid`, `has_stepper`,
`has_markdone`, `has_guess_number`, `has_stateful_elements`) is already a flat unit-wide
query for exactly this reason.

**Fix:** both sites become flat `node.elements.filter(...)` queries. The two removals are
separate, because the two sites are not the same shape:

- Lesson site: `courses/views.py:328` computes `html_ct_id` whose **only** consumer is line
  346, so it must be **removed** in the same change — an assigned-but-unused local trips
  ruff F841 against the "ruff clean" DoD gate.
- Quiz site: line 1198's isinstance walk may leave the `HtmlElement` import unused at that
  site; check and remove it.

The CT-id caveat applies to the lesson site only: CT-id lookups were deliberately preferred
there once before, to avoid cold-cache ContentType SELECTs breaking a query-count
assertion. The replacement filter should therefore use `content_type__model="htmlelement"`
pinned by `content_type__app_label="courses"`, the same shape `has_stateful_elements`
already uses.

**The quiz site is a real, reachable bug too, and needs its own test.** The HTML card
(`_add_menu.html:20`) sits in the Content group, **outside** the `{% if not unit_is_quiz %}`
at `:27`, so an HTML element nested in a tab inside a **quiz** unit is authorable today, and
`quiz_unit.html:23` gates `html_element.js` on `has_html`.

**Correction to an earlier draft of this spec, recorded so it is not re-introduced:** it is
NOT true that `tests/test_html_element.py` carries an expected query *number* that needs
bumping. `test_lesson_html_render_query_count_invariant` asserts a **relative** invariant
(`len(q3) == len(q1)`, a 1-element page against a 3-element page); one additional constant
query lands in both captures and the assertion is unaffected. What does need attention is
that test's ContentType warm-up comment, which references `get_for_model(HtmlElement)` on a
code path this fix may remove.

### `_add_menu.html` loses `in_spoiler` entirely

The flag exists only to express the narrower spoiler allowlist. With one allowlist it
disappears — both its consumers here and its sole producer at `_element_row.html:177`. Each
guard needs its replacement stated, because two of them are inclusion guards and deleting
them outright is wrong:

- HTML (line 20), Step-by-step (36), Checklist (37), Guess-the-number (38):
  `{% if not in_spoiler %}` is **deleted**.
- Spoiler (line 35): becomes a container card governed by the depth predicate.
- Fill-in-the-blanks (line 39): `{% if in_spoiler %}` becomes `{% if nested %}`. Deleting
  it outright would render the card at top level, where line 49 already emits an identical
  `data-add-type="fillblankquestion"` card — two duplicates in the top-level menu **of a
  lesson**. (Line 39 sits inside the `{% if not unit_is_quiz %}` group at line 27 while
  line 49 sits inside `{% if not nested %}` at line 42, so no duplicate arises in a quiz;
  the guard test for this must therefore use a **lesson** fixture or it passes vacuously.)
- Tabs / Columns (lines 24-25): `{% if not nested %}` becomes the depth predicate.

**Card visibility becomes a function of `nested`, `depth` and `unit_is_quiz`** — not of
`nested` and `depth` alone. `_add_menu.html:27` wraps the whole Interactive group in
`{% if not unit_is_quiz %}`, and **the Spoiler card (line 35) and the fill-blank card
(line 39) both live inside it**. So in a quiz unit only two of the three container cards
can ever appear at depth 1, and the newly-`{% if nested %}`-guarded fill-blank card is
still unreachable in nested quiz menus. Any test asserting "the depth-1 nested menu offers
Tabs/Columns/Spoiler" must use a **lesson** unit or it fails. Moving the Spoiler card out
of the quiz-gated group is **not** in scope for this slice.

### LAL loader — keep the gate narrow, and note it is untested

`courses/lal_loader/builders.py:95-115` imports `SPOILER_CHILD_TYPES` as a **rejection
gate** (line 111) and interpolates `', '.join(sorted(SPOILER_CHILD_TYPES))` into its
`LoaderError` text (lines 113-115). Repointing it at `NESTABLE_TYPE_KEYS` would widen that
gate by seven types (`tabs`, `two_column`, `spoiler`, `html`, `stepper`, `mark_done`,
`guess_number`) and change the error string.

**Decision: the loader keeps its own narrower constant**, moved into the loader module and
named for what it is (the LAL corpus's permitted spoiler children). The loader is a
one-time import tool for a fixed corpus; widening its gate buys nothing and would silently
change what a re-run accepts.

**The gate is currently untested, so there is no existing signal that the constant was
preserved.** An earlier draft of this spec claimed `tests/lal_import/test_lesson.py:1483`
depended on the abort; it does not — that test calls `parse_lesson(...)` and asserts on
parsed dicts, never reaching `builders.py`, and the guard's message
`"not allowed inside a spoiler"` appears nowhere in the test suite. The plan must therefore
**add** a loader-level test that constructs a spoiler dict containing a now-widened child
type and asserts the gate fires, so the narrow constant has an actual guard.

**The child type must be one the loader can actually build, and the assertion must name the
message.** `build_element` has 21 `etype ==` branches and ends at `builders.py:391` with
`raise LoaderError(f"unknown element type {etype!r} …")`. So a type the loader does not know
— `stepper` is not among its branches — raises `LoaderError` from that fallthrough whether
or not the gate fired, and a test asserting only the exception class would pass under the
very mutant it exists to catch. Use `mark_done` (`builders.py:299`) or `guess_number`
(`:306`), which the loader can build, and assert the substring
`"not allowed inside a spoiler"`.

## Error handling

- **Write path:** every rule violation raises `NestingError`, which the view turns into a
  400. Distinct messages per clause so a failure is diagnosable: unknown parent, unknown
  slot, type not nestable, too deep, container not allowed at this depth.
- **Import path:** every rule violation raises the transfer validation error, rejecting the
  archive — never repairing it. This includes the hop-bounded cycle case, which must
  produce a validation error rather than a hang or a `RecursionError`.
- **Delete path:** the subtree walk terminates on a `seen` set; it never recurses on
  unbounded data and never truncates legal data.
- **Export path:** same `seen`-set termination; an already-visited join is omitted. Not
  reachable today (see Defect 2) — defence for a future non-root entry point.
- **Editor:** the add-menu never offers a card that `resolve_scope` would reject, so an
  author cannot reach a 400 through the normal UI.

### Translatable strings that change (the `.po` gate depends on these)

Three message sites move and one is added, and the DoD's zero-fuzzy gate is a trap unless
they are named:

| Site | Change |
|---|---|
| `payloads.py:784` `"Element '%(el)s' may not be nested inside a spoiler."` | **Deleted** with the spoiler branch. Removing a msgid leaves an obsolete entry — `makemessages` must run with `--no-obsolete`. |
| `payloads.py:797` `"Element '%(el)s' is nested more than one level deep."` | Factually wrong after this change; reword to name the actual cap, e.g. `"Element '%(el)s' is nested too deeply."` This is the **clause-3** message. |
| `payloads.py:805` `"Element '%(el)s' may not be nested inside a tabs element."` | Now also reached for spoiler and two-column children; reword generically, e.g. `"Element '%(el)s' may not be nested."` |
| *(new)* | A **clause-4** message, e.g. `"Element '%(el)s' is a container and may not be nested this deeply."` The depth-4 and depth-3-container tests assert against it. |

## Testing

### Falsification discipline (mandatory)

**Every test carries a named mutant** — a specific one-line edit to production code, at a
named file and line, that must be verified RED before the test counts as written. Not
"delete the feature and see"; not "same as above"; not a description of a behaviour to
break. A test whose named mutant does not go red is rewritten, not explained away. On an
earlier slice a falsification table was vacuous in six successive drafts before this rule
was applied — and in this spec's own review, four successive mutant proposals were found
vacuous before landing on the ones below.

**"Verified RED" means the NAMED test goes red — not merely that the suite does.** Several
mutants below also break pre-existing tests; that is fine and expected, but it proves
nothing about the new test. Verification is: apply the mutant, run *that test by node id*,
observe it fail, revert.

One row below is deliberately exempt and says so.

### Coverage

| Area | Test | Named mutant |
|---|---|---|
| Depth rule | parametrized `resolve_scope`: (parent at depth 1/2/3) × (leaf, container). **The depth-3-parent parameters must be ORM-constructed** — clause 4 forbids a container at depth 3, so they are unreachable through `resolve_scope` itself; comment this in the test or it will be deleted as dead. | `builder.MAX_NEST_DEPTH 3 → 4` — lethal because clauses 3 and 4 compare against the constant. (`element_depth`'s loop bound is independent and exists only for cycle safety; do not cite it as the reason.) |
| Depth rule, clause 4 | a container child of a depth-2 parent is rejected; a leaf child of the same parent is accepted | delete the clause-4 branch in `resolve_scope` |
| Delete | delete a depth-3 subtree → zero orphan concretes at every level | `builder.py:411` → `_delete_element_content_objects(Element.objects.filter(parent=el))` (the pre-change one-level form) |
| Tab removal | remove a tab holding a container holding a leaf → no orphans | `builder.py:670` → `Element.objects.filter(parent=join, tab_id__in=removed)` without the subtree walk |
| **Duplicate unit** | duplicate a unit with leaf-in-spoiler-in-tab → the copy has the leaf | `export.py:walk_unit_joins` → drop the recursive descent, yield one level only |
| Export / import | full round trip at depth 3 | `export.py:walk_unit_joins` → yield all top-level joins first and grandchildren afterwards, breaking parents-before-children. The import's payload-order pass depends on that ordering, so the round trip's within-slot order changes; the duplicate test would not catch this. |
| Delete, cycle | an ORM-constructed `A.parent=B, B.parent=A` pair passed to `delete_element` completes — no hang, no `RecursionError`. **This is the one genuinely reachable cycle**: `delete_element` starts from a request-supplied `element_pk` (`_locked_element`), so an element inside a corrupt cycle IS reachable, unlike the export walk (Defect 2). | remove the `seen` guard from the subtree collector |
| Import validator, clause 4 | depth-4 archive listed **parents-first**, asserting the clause-4 message | delete the clause-4 branch in `validate_nesting` |
| Import validator, clause 3 | depth-4 archive listed **child-before-parent** (see Defect 3 for the exact shape), asserting the clause-3 message | delete the clause-3 branch in `validate_nesting` |
| Import validator, cycle | **parent-cycle archive raises the validation error rather than hanging or `RecursionError`.** This test asserts the exception TYPE only, deliberately: a hop-bounded walk reports a cycle as a parent at depth > MAX, so it fires clause 3 and emits the identical "nested too deeply" message an ordinary depth-4 archive does. That collision is accepted rather than papered over with a distinct "cycle detected" message, because distinguishing them would require the very unbounded traversal this bound exists to avoid. Note the exemption here so it does not read as an oversight against Defect 3's "assert the specific message" rule. | replace the hop-bounded loop in `validate_nesting` with a recursive helper carrying no bound, so the cycle raises `RecursionError` and the test's `pytest.raises(TransferError)` fails. **`while parent is not None` remains forbidden as a mutant** — it hangs instead of failing, and `pytest-timeout` is not installed, so the run would wedge. Raising the bound to a large finite number is also forbidden: the walk still terminates and still raises, so that mutant is vacuous. |
| Editor — nested spoiler | a spoiler nested in a tab renders its children and its add-menu | restore `and el.parent_id is None` on `_element_row.html:136` |
| Editor — top-level menu | the top-level add menu still offers Tabs and Columns (the `depth`-seeding regression) | delete `depth=1` / `depth=0` from `_editor_scope.html`, leaving `depth` unseeded |
| Editor — depth 2 | in a **lesson** unit, the add-menu inside a depth-1 container offers Tabs/Columns/Spoiler; the one inside a depth-2 container does not | delete the depth predicate on the Tabs card in `_add_menu.html` |
| Editor — depth 3 | no add-menu is emitted inside a depth-3 element (ORM-constructed fixture, see above) | `_element_row.html` includes `_add_menu.html` at **three** sites — `:85` (tabs), `:131` (two-column), `:177` (spoiler) — which all carry the same guard. Name the container the fixture uses and delete the guard at that site only; deleting a different one leaves the test green. |
| Editor — no duplicate card | in a **lesson**, the top-level menu emits exactly one `fillblankquestion` card | `_add_menu.html:39` → delete the guard entirely instead of changing it to `{% if nested %}` |
| LAL loader gate | a spoiler dict containing `mark_done` (a type the loader CAN build, and one the naive widening would admit) fails with a `LoaderError` whose message contains `"not allowed inside a spoiler"` | repoint `builders.py:111` at `NESTABLE_TYPE_KEYS` (the naive widening this spec rejects). Asserting the message, not just the class, is what makes this lethal — an unknown type would raise `LoaderError` from the `builders.py:391` fallthrough regardless. |
| `has_html`, lesson | lesson unit whose ONLY html element is inside a tab loads `html_element.js` | `views.py:346` → `any(isinstance(el.content_object, HtmlElement) for el in elements)` — the top-level-only shape. Do **not** name "revert to the pre-change line": `html_ct_id` is deleted by the fix, so reverting line 346 alone raises `NameError` and every lesson render 500s, which is noise rather than signal. |
| `has_html`, quiz | **quiz** unit whose ONLY html element is inside a tab loads `html_element.js` | `views.py:1198` → the pre-change `any(isinstance(el.content_object, HtmlElement) for el in elements)` (self-contained; no deleted local involved) |
| `has_math` | unit whose ONLY math sits at depth 3, via the pinned chain **tabs → spoiler → math**, with no other math anywhere in the unit | `views.py:239-242` (`_tabs_has_math` body) → `return False`. Not `views.py:202`: that line is already killed by pre-existing top-level-spoiler tests, and a depth-3 chain such as tabs → two_column → math never reaches it at all, so it proves nothing about this fixture. |
| Student render | a depth-3 leaf renders inside its nested container | **Exempt, deliberately.** The render path is unchanged by this slice (see Data flow), so this is a characterization test pinning existing behaviour at a new depth, not a test of new logic. |

### Vacuity traps

- The `has_html` and `has_math` tests MUST use an **isolated** unit whose only html/math
  lives at the nested depth under test. A unit that also has top-level math passes both
  before and after the fix.
- The editor-template tests must assert on rendered markup for a genuinely depth-3 fixture,
  not on a depth-2 fixture that happens to exercise the same branch.
- Tests asserting container-card visibility must use a **lesson** unit — the Spoiler and
  fill-blank cards sit inside the `{% if not unit_is_quiz %}` group (see above).
- **Any test that renders `_element_row.html` or `_add_menu.html` directly must pass an
  explicit integer `depth`.** Django's `smartif` swallows comparison `TypeError`s, so a
  template test that omits `depth` (or passes a string) evaluates every depth predicate to
  False and can keep passing vacuously while the real editor is broken. Five existing
  direct-render sites must be updated:

  | Site | Note |
  |---|---|
  | `courses/tests/test_reveal_gate_editor_row.py:46-50` | renders `_element_row.html` with no `depth` |
  | `tests/test_tabs_editor_partial.py:70-72` | renders `_element_row.html` with no `depth` |
  | `tests/test_tabs_editor_partial.py:83-86` | renders `_add_menu.html` with `{"nested": True, …}` and no `depth` — this is the render behind the inverted assertion at `:79-90` |
  | `tests/test_gallery_manage.py:26` | renders `_add_menu.html` with **no context at all**; its cards are unguarded, so a seed is needed only to prevent future vacuity |
  | `tests/test_table_manage_plumbing.py:23` | same as above |

- **e2e locators must be scoped.** Several e2e tests click cards with an unscoped
  `page.locator("[data-add-type='…']")` — `tests/test_e2e_tabs.py:137`,
  `tests/test_e2e_twocolumn.py:148`, `tests/test_e2e_editor.py:82`,
  `tests/test_e2e_editor_ws3.py:68`. These pass today only because they run against an
  empty editor. Once nested menus emit the Tabs/Columns/Spoiler/fill-blank cards, any such
  click on a page that already contains a container matches more than one element and fails
  Playwright strict mode. Any locator for a newly-nested card must be scoped to its
  `[data-add-menu]` ancestor.

### Existing guardrail tests to INVERT (not delete)

These assert the old cap and are the tests most likely to be quietly removed. This list
grew from 3 sites to 9 in review round 1 and to 14 in round 2; **the plan must re-derive it
by search rather than trust it**, and treat any further site it finds as expected, not
anomalous.

| Site | Action |
|---|---|
| `tests/test_twocolumn_registry.py:15` — `"two_column" not in NESTABLE_TYPE_KEYS` | Invert to `in`. |
| `tests/test_twocolumn_registry.py:16` — `"twocolumn" not in NESTABLE_TYPE_KEYS` | **Must survive unchanged.** `twocolumn` remains a form key only; this assertion pins the form-key/transfer-key split. Do not invert it along with line 15. |
| `tests/test_twocolumn_registry.py:48` — `test_resolve_scope_rejects_container_child_in_two_column` | The `"tabs"` case inverts to an accept (parent at depth 1); the `"choicequestion"` case stays a reject. Rename the test — its current name becomes false. |
| `tests/test_tabs_form_views.py:119-131` — `test_non_nestable_child_type_raises`, driving `save_element(..., "tabs", ...)` with `# tabs-in-tabs` inside `pytest.raises(NestingError)` | Inverts to an accept: `resolve_scope` passes and `data=""` hits `clean_data`'s blank-payload MIN_TABS default, so the save succeeds. Rename the test. |
| `courses/tests/test_spoiler_nesting.py:~149` — `for bad in ("tabs", "spoiler", "choicequestion")` against a top-level spoiler | `"tabs"` and `"spoiler"` become **legal** children — two of the three shapes in Purpose. The reject tuple reduces to `("choicequestion",)`; add a matching accept case. |
| `courses/tests/test_spoiler_nesting.py:163-165` — the `SPOILER_CHILD_TYPES` membership table | The constant is deleted; the table becomes a `NESTABLE_TYPE_KEYS` table. |
| `courses/tests/test_spoiler_nesting.py:~190` — "a nested spoiler may not have children" | Inverts: a nested spoiler may now have children. |
| `courses/tests/test_spoiler_nesting.py:210-224` — `test_resolve_scope_refuses_children_for_nested_spoiler`, a spoiler nested in a **tab** | Inverts to an accept. **This is the direct assertion of Purpose bullet 3** — the slice's headline shape is guarded by this test. |
| `courses/tests/test_spoiler_nesting.py:306-313` — `test_spoiler_add_menu_hides_disallowed_cards`, banning `("html", "spoiler", "stepper", "markdone", "guessnumber")` | All five are now emitted; move them to the allowed list. The ten `banned_question` entries at `:315-327` stay banned (the Questions group remains `{% if not nested %}`). |
| `courses/tests/test_spoiler_nesting.py:346` — `present.isdisjoint({"spoiler", "stepper", "markdone", "guessnumber"})` | All four become present. Lines 348-350's question-card disjointness is unchanged. |
| `courses/tests/test_spoiler_nesting.py:394-399` — `test_tabs_add_menu_unaffected`, asserting `fillblankquestion` absent from the **tabs** nested menu | Inverts — the `{% if nested %}` change makes it present. Rename the test; "unaffected" becomes false. |
| `tests/test_tabs_editor_partial.py:79-90` — `test_nested_add_menu_offers_only_nestable_types`, asserting `'data-add-type="tabs"' not in html` | Inverts: offering Tabs in a nested menu at depth 1 is the point of this slice. **Must pass an explicit `depth`** — without one the stale assertion keeps passing vacuously. |
| `tests/test_tabs_transfer.py:135` — the `# depth > 1` reject case | Its middle element is a **text** element (`_child()` defaults to `type_="text"`), so after this change it is still rejected — by the "parent is not a container" rule, not by any depth rule. It silently stops testing depth. Rebuild it with a container middle element, or retire it in favour of the new clause-3/clause-4 tests. |
| `tests/test_tabs_transfer.py` — the `tabs`-in-`tabs` reject case | Becomes a **valid** document (parent at depth 1, container child at depth 2). Move it from the reject table into the accept test. |

### Surfaces deliberately left top-level-scoped

`courses/quiz.py:207` (`compute_scores`), `courses/rollups.py:194` and `:232`,
`courses/review.py:107` and `:173`, and `courses/views_review.py:68` all filter
`parent__isnull=True` and therefore skip nested questions. This is **by design and
unchanged by this slice**: the Interactive palette group is gated off in quiz units
(`_add_menu.html:27`), and the only nestable question type is `fill_blank`, so a graded
nested question is not reachable through the editor. Depth 3 does not change that
reachability. Stated here so the `has_html` fix does not read as an argument that every
top-level scan is a bug.

### Known limitation, out of scope

A nested `HtmlElement` renders without theme context. `render_element`
(`courses_extras.py:43-45`) reads `theme_pref`/`data_theme` from the outer template
context, but `SpoilerElement.render` / `TabsElement.render` / `TwoColumnElement.render`
(`models.py:430-441`, `:1446-1459`, `:1555-1562`) build a fresh context carrying only `el`,
`children`/`tabs`/`columns`, `element_state`, `slug`, `node_pk`. This is **pre-existing**
for tabs and is not introduced here, but admitting `html` into spoilers widens its
exposure. Explicitly out of scope for this slice; worth its own follow-up.

### Review instruction (carried over, non-negotiable)

Spec-review and plan-review agents are instructed to **EXTRACT AND RUN the embedded code**,
not read it. On the previous slice every defect worth finding came from execution —
including a rule that would have made the feature a silent no-op on real content while all
fixtures stayed green, and a definition-of-done gate that was unpassable as written. A DoD
gate that cannot be executed as written is itself a defect.

### Mechanism claims are claims, not facts

Every file:line and mechanism in this spec was read from the tree at master `901f6cf0` on
2026-08-02, and three spec-review rounds re-verified them by execution. **Six claims were
found false and are corrected in place** — note that three of them were introduced by an
*earlier round's own fix*, which is why the plan must re-verify rather than assume the
reviewed spec is settled:

| Claim | Verdict |
|---|---|
| `tests/test_html_element.py` carries an expected query number needing a bump | False — it is a relative invariant |
| Clause 3 is unreachable-by-construction on the import path | False — payload ordering reaches it |
| `tests/lal_import/test_lesson.py:1483` guards the loader gate | False — it never reaches the loader; nothing tests the gate |
| A corrupt parent cycle could hang the export walk / a request | False — the walk starts from `parent__isnull=True` roots, so its reachable subgraph is acyclic |
| `stepper` exercises the loader gate | False — the loader has no `stepper` branch, so it raises from the unknown-type fallthrough regardless |
| All DoD gates pass on the unmodified tree | False — two of them must fail beforehand |

The plan must still verify each load-bearing claim by execution before depending on it: a
confident false mechanism survived 26 review rounds on an earlier slice.

## Definition of done

Every gate below must be runnable exactly as written. They fall into two groups, and
conflating them produces a false "verified" claim — an earlier draft of this spec asserted
all of them passed on the unmodified tree, which was false for the last three, two of which
*must* fail beforehand.

**Group A — gates that pass on the unmodified tree** (each was executed against this
worktree during spec review and does pass today; a failure here is a regression this slice
introduced):

- **Full non-e2e suite green, run serially:** `uv run pytest --verbosity=0` (no `-n`; the
  Windows xdist DB-setup race produces spurious failures at ~98%). **Do not add a second
  `-q`** — `pyproject.toml:49` already sets `addopts = "-q -m 'not e2e'"`, and a doubled
  `-q` suppresses the summary entirely, leaving no "N passed" line and no verdict to check.
  Green means a terminal line of the form `N passed` (plus any skips) and exit status 0.
- **Full e2e suite green:** `uv run pytest -m e2e --verbosity=0`. A command-line `-m`
  overrides the `-m 'not e2e'` in `addopts`; without it every e2e test is silently
  deselected and pytest exits 5.
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- `uv run python manage.py makemigrations --check --dry-run` clean. Expected: **no new
  migration** — depth is computed, no model field changes. A migration appearing here means
  the design was not followed.

**Group B — gates that can only pass after the change** (two of these MUST fail on the
unmodified tree; if one passes before the work starts, the gate is inert and is itself a
defect):

- `.po` catalogs zero-fuzzy, regenerated with `-l pl -l en --no-obsolete` (the message
  table above includes one deletion, which leaves an obsolete entry otherwise).
- **No help doc asserts the old cap.** A line-oriented search of `docs/help/` for all six
  phrases below returns nothing. Each was verified to match on a **single line** of the
  unmodified tree — a phrase that spans a line wrap can never match and would make that
  part of the gate inert in both directions:

  | Phrase | Matches today at |
  |---|---|
  | `two container types` | `content-editors.md:123` |
  | `cannot hold another container` | `content-editors.md:128` |
  | `dwa typy kontenerów` | `content-editors.pl.md:133` |
  | `może zawierać innego kontenera` | `content-editors.pl.md:140` — note: NOT `nie może zawierać innego kontenera`, which spans the `:139`/`:140` wrap and matches nothing |
  | `nestable inside Tabs and Columns` | `interactive-elements.md:9` |
  | `wewnątrz Zakładek` | `interactive-elements.pl.md:10` |

  The last two exist because the four phrases from `content-editors` alone would let an
  implementer edit that file, pass the gate, and ship two stale `interactive-elements`
  files.

- Every test in the coverage table has its named mutant recorded and verified RED — meaning
  *that named test*, run by node id, fails under the mutant — except the one row marked
  exempt.

## Out of scope

- **Callout as a container** — PR2 of this pair (tables in callouts, math in callouts). Its
  design decision is already taken: the callout's existing `body` renders FIRST and its
  children FOLLOW, so existing callouts are unaffected and nesting is purely additive. This
  deliberately differs from Spoiler, where children REPLACE the legacy body
  (`spoilerelement.html:7-13`; `SpoilerElementForm.__init__` drops the `body` field once
  children exist). **Spoiler's semantics are NOT changed here:** spoilers holding both a
  body and children exist in the wild and currently render children only; harmonising would
  newly reveal hidden text on live courses.
- Moving the Spoiler card out of the quiz-gated Interactive group.
- Theme context for nested HTML elements (see Known limitation above).
- Images in table cells (slice C).
- The deferred `sanitize_html` math-protection spec — still blocked on the mat-pp PROD
  cutover.
- Elements inside table cells — dropped by agreement.
