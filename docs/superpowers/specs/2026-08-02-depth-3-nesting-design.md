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
  a tab is forced to be childless, so it degrades to a legacy body-only spoiler.

All three are blocked by the same thing: a depth-2 cap that is not a stated rule but an
assumption baked into four independent places, plus a fourth container type
(`SpoilerElement`) that never joined the container registry and is instead special-cased
in five files.

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

**State plainly, because it is a real widening beyond containers:** spoilers newly accept
`html`, `stepper`, `mark_done` and `guess_number`, which `SPOILER_CHILD_TYPES` excluded.
This is intended. Its cost is the `has_html` fix below.

### Depth is computed, not stored

`depth(join)` walks the `parent_id` chain, at most two hops given the cap. No new column,
**no migration**. The write-side check reduces to:

```python
# reject a child when its parent is already at depth 3
if join.parent_id is not None and join.parent.parent_id is not None:
    raise NestingError(...)
```

Use `select_related("parent")` where the parent join is fetched so the check costs no
extra round trip on the common path.

## Architecture / components

### Fold Spoiler into the container registry

`SpoilerElement` is special-cased in five places today:

| Site | File |
|---|---|
| write-path scope resolution | `courses/builder.py:128-142` |
| import validation | `courses/transfer/payloads.py:774-786` |
| export walk | `courses/transfer/export.py:498-500` |
| editor row template | `templates/courses/manage/editor/_element_row.html:136` |
| math detection | `courses/views.py:245-256` (`_spoiler_has_math`) |

`_CONTAINER_REGISTRY` (`courses/builder.py:99-102`) covers only `TabsElement` and
`TwoColumnElement`, and its contract assumes a slot list read out of `data`.

**Change:** widen the registry entry so a single-slot container can join it. An entry
supplies (a) the slot ids for an instance and (b) the ordered children in a slot. A
multi-slot container derives slot ids from its non-destructive normalizer, as today; a
single-slot container returns a constant `{SLOT_ID}`.

After the refactor, `resolve_scope` has no `isinstance(parent_obj, SpoilerElement)`
branch, and neither do `validate_nesting` nor `walk_unit_joins`.

**The destructive/non-destructive distinction is load-bearing and must survive the
refactor.** `normalize_data` pads, truncates and mints fresh random ids on every call; a
write path that validated a slot against it could admit an ephemeral phantom id that never
matches at render time, silently orphaning the child. Slot validation on any write path
reads the **non-destructive** normalizer only. The comment recording this at
`builder.py:143-147` must not be lost.

### Components touched

- `courses/builder.py` — `MAX_NEST_DEPTH`, the widened registry, `resolve_scope`, the
  recursive subtree delete, the tab-removal cleanup.
- `courses/transfer/export.py` — recursive `walk_unit_joins`.
- `courses/transfer/payloads.py` — hop-bounded `validate_nesting`.
- `courses/views.py` — `has_html` in both context builders.
- `templates/courses/manage/editor/_element_row.html` — depth threading, spoiler branch.
- `templates/courses/manage/editor/_add_menu.html` — drop `in_spoiler`, add depth rules.
- `courses/lal_loader/builders.py` — allowlist import.

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

`delete_element` and the tab-removal branch collect the element's whole subtree (bounded by
`MAX_NEST_DEPTH`) and delete concretes deepest-first, then let the join rows cascade.

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

**Fix:** a bounded subtree collection used by both sites, deleting concretes deepest-first.

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

The existing docstring rule stays true and must be preserved: children are reached ONLY
through the slot accessors, never `join.children.all()`. A child whose `tab_id` matches no
slot is deliberately omitted from the archive, because exporting it would produce a payload
the import validator rejects.

### 3. The import validator must walk — and must be hop-bounded

`validate_nesting` (`courses/transfer/payloads.py:753-807`) rejects nesting with
`if parent["parent"] is not None`. It becomes a chain walk enforcing clauses 3 and 4.

**The walk must count hops, not walk until `None`.** Today a parent cycle in a corrupt or
hostile archive (A → B → A) cannot loop, because only one level is ever inspected. A naive
`while parent is not None` walk would hang the import worker on such an archive. The walk
terminates after at most `MAX_NEST_DEPTH` hops and raises the ordinary validation error.

### 4. The editor recursion needs a real depth guard

`templates/courses/manage/editor/_element_row.html` carries three comments asserting "the
realized depth is always exactly 2. There is no depth guard here." (lines 68-73, 114-119,
160-164). All three become false and must be rewritten, not merely left in place.

- The spoiler branch condition `el.content_type.model == "spoilerelement" and
  el.parent_id is None` (line 136) loses the `parent_id` clause. That clause is precisely
  why a nested spoiler currently falls through to the leaf `{% else %}` branch and renders
  with no children and no add-menu.
- A `depth` variable is threaded through the recursive `{% include %}` in all container
  branches.
- At depth 2, `_add_menu.html` hides the four container cards (their children would be
  depth 3, which clause 4 forbids).
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
- `courses/views.py:1198` — the quiz context's own copy

So an HTML element authored inside a tab today never loads `html_element.js`
(`lesson_unit.html:67`, `quiz_unit.html:23`) unless an unrelated top-level HTML element
happens to exist. This is a **pre-existing** defect, not one this slice creates. It is fixed
here because the single allowlist newly admits `html` into spoilers, and because every
sibling flag (`has_questions`, `has_reveal_gate`, `has_switch_grid`, `has_stepper`,
`has_markdone`, `has_guess_number`, `has_stateful_elements`) is already a flat unit-wide
query for exactly this reason.

**Fix:** both sites become flat `node.elements.filter(...)` queries.

**Known cost:** this replaces a Python scan of an already-loaded list with a DB query,
adding one query per lesson render. `tests/test_html_element.py` carries a query-count
assertion that may need its expected number bumped. Check this in the plan rather than
discover it in CI.

### `_add_menu.html` loses `in_spoiler` entirely

The flag exists only to express the narrower spoiler allowlist. With one allowlist it
disappears, together with the `{% if not in_spoiler %}` guards on the HTML, Spoiler,
Step-by-step, Checklist and Guess-the-number cards (lines 20, 35-38) and the
`{% if in_spoiler %}` guard on the Fill-in-the-blanks card (line 39). Card visibility
becomes a function of `nested` and `depth` only.

### LAL loader

`courses/lal_loader/builders.py:95-115` imports `SPOILER_CHILD_TYPES` for its child-type
allowlist and its error message. It switches to the unified allowlist. This is a one-time
corpus import tool that only ever produces depth-2 content; no behavioural change is
intended beyond keeping it compiling against the surviving constant.

## Error handling

- **Write path:** every rule violation raises `NestingError`, which the view turns into a
  400. Distinct messages per clause so a failure is diagnosable: unknown parent, unknown
  slot, type not nestable, too deep, container not allowed at this depth.
- **Import path:** every rule violation raises the transfer validation error, rejecting the
  archive — never repairing it. This includes the hop-bounded cycle case, which must
  produce a validation error rather than a hang or a `RecursionError`.
- **Delete path:** the subtree walk is bounded; it never recurses on unbounded data.
- **Editor:** the add-menu never offers a card that `resolve_scope` would reject, so an
  author cannot reach a 400 through the normal UI.

## Testing

### Falsification discipline (mandatory)

**Every test carries a named mutant** — a specific one-line edit to production code that
must be verified RED before the test counts as written. Not "delete the feature and see"; a
named edit, recorded in the plan next to the test, e.g.
`mutant: builder.MAX_NEST_DEPTH 3 → 4` / `expect: test_depth_4_rejected FAILS`.

A test whose named mutant does not go red is rewritten, not explained away. On an earlier
slice a falsification table was vacuous in six successive drafts before this rule was
applied.

### Coverage

| Area | Test | Named mutant |
|---|---|---|
| Depth rule | parametrized `resolve_scope`: (parent at depth 1/2/3) × (leaf, container) | `MAX_NEST_DEPTH → 4`; separately, delete clause 4 |
| Delete | delete a depth-3 subtree → zero orphan concretes at every level | revert to `filter(parent=el)` |
| Tab removal | remove a tab holding a container holding a leaf → no orphans | same |
| **Duplicate unit** | duplicate a unit with leaf-in-spoiler-in-tab → the copy has the leaf | revert `walk_unit_joins` to one level |
| Export / import | full round trip at depth 3 | same |
| Import validator | depth-4 archive rejected | drop the depth clause |
| Import validator | container-at-depth-3 archive rejected | drop clause 4 from the validator |
| Import validator | **parent-cycle archive terminates with a validation error** | replace the hop counter with `while parent is not None` |
| Editor | depth-3 row renders; no add-menu at depth 3; container cards hidden at depth 2 | restore `and el.parent_id is None` on the spoiler branch |
| Editor | a nested spoiler renders its children and its add-menu | same |
| `has_html` | unit whose ONLY html element is inside a tab loads `html_element.js` | revert to the `parent__isnull=True` scan |
| `has_math` | unit whose ONLY math sits at depth 3 | break `_element_has_math` recursion into containers |
| Student render | a depth-3 leaf renders inside its nested container | — |

### Vacuity traps

- The `has_html` and `has_math` tests MUST use an **isolated** unit whose only html/math
  lives at the nested depth under test. A unit that also has top-level math passes both
  before and after the fix.
- The editor-template tests must assert on rendered markup for a genuinely depth-3 fixture,
  not on a depth-2 fixture that happens to exercise the same branch.

### Existing guardrail tests to INVERT (not delete)

These assert the old cap and are the tests most likely to be quietly removed:

- `tests/test_twocolumn_registry.py:15-16` — `"two_column" not in NESTABLE_TYPE_KEYS`
- `courses/tests/test_spoiler_nesting.py:163-165` — the `SPOILER_CHILD_TYPES` membership
  table (the constant is being deleted; the table becomes a `NESTABLE_TYPE_KEYS` table)
- `courses/tests/test_spoiler_nesting.py:~190` — "a nested spoiler may not have children"

### Review instruction (carried over, non-negotiable)

Spec-review and plan-review agents are instructed to **EXTRACT AND RUN the embedded code**,
not read it. On the previous slice every defect worth finding came from execution —
including a rule that would have made the feature a silent no-op on real content while all
fixtures stayed green, and a definition-of-done gate that was unpassable as written. A DoD
gate that cannot be executed as written is itself a defect.

### Mechanism claims are claims, not facts

Every file:line and mechanism in this spec was read from the tree at master `901f6cf0` on
2026-08-02, but **reading is not running**. The plan must verify each load-bearing claim by
execution before depending on it. A confident false mechanism survived 26 review rounds on
an earlier slice.

## Definition of done

- Full non-e2e suite green, run **serially** (`uv run pytest -q`, no `-n`) — the Windows
  xdist DB-setup race produces spurious failures at ~98%.
- Full e2e suite green; `-m e2e` is mandatory or e2e is silently deselected (exit 5).
- `ruff` + format clean.
- `uv run python manage.py makemigrations --check --dry-run` clean. Expected: **no new
  migration** — depth is computed, no model field changes. A migration appearing here means
  the design was not followed.
- `.po` catalogs zero-fuzzy for any new or changed translatable string.
- Every test in the coverage table has its named mutant recorded and verified RED.

## Out of scope

- **Callout as a container** — PR2 of this pair (tables in callouts, math in callouts). Its
  design decision is already taken: the callout's existing `body` renders FIRST and its
  children FOLLOW, so existing callouts are unaffected and nesting is purely additive. This
  deliberately differs from Spoiler, where children REPLACE the legacy body
  (`spoilerelement.html:7-13`; `SpoilerElementForm.__init__` drops the `body` field once
  children exist). **Spoiler's semantics are NOT changed here:** spoilers holding both a
  body and children exist in the wild and currently render children only; harmonising would
  newly reveal hidden text on live courses.
- Images in table cells (slice C).
- The deferred `sanitize_html` math-protection spec — still blocked on the mat-pp PROD
  cutover.
- Elements inside table cells — dropped by agreement.
