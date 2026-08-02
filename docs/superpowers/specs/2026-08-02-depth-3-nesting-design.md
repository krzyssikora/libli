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
- The LAL loader's child-type gate widens by seven types — see the LAL loader section,
  which is a behavioural change and not merely a compile fix.

### Depth is computed, not stored

`depth(join)` walks the `parent_id` chain. No new column, **no migration**.

**The walk must be a hop-counting loop that reads `MAX_NEST_DEPTH`, not a hard-coded
two-hop conjunction.** A hard-coded `join.parent_id is not None and
join.parent.parent_id is not None` produces the right answer today but makes
`MAX_NEST_DEPTH` decorative: mutating the constant would change nothing, and the headline
falsification mutant in the coverage table would be vacuous.

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

Use `select_related("parent")` where the parent join is fetched so the common path costs
no extra round trip.

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

### Components touched

- `courses/builder.py` — `MAX_NEST_DEPTH`, `element_depth`, the canonical registry,
  `resolve_scope`, the recursive subtree delete, the tab-removal cleanup.
- `courses/transfer/export.py` — recursive `walk_unit_joins`.
- `courses/transfer/payloads.py` — hop-bounded `validate_nesting`; delete
  `_CONTAINER_SLOT_KEY`; three message changes (see Error handling).
- `courses/views.py` — `has_html` in both context builders; remove the now-unused
  `html_ct_id`.
- `templates/courses/manage/editor/_element_row.html` — depth threading, spoiler branch.
- `templates/courses/manage/editor/_editor_scope.html` — **seeds `depth`**; see below.
- `templates/courses/manage/editor/_add_menu.html` — drop `in_spoiler`, add depth rules.
- `courses/lal_loader/builders.py` — allowlist decision (see LAL loader section).

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

**Clause 3 is unreachable-by-construction on the import path, and that is deliberate.** A
depth-4 element requires a container at depth 3, which clause 4 rejects first (`_err`
raises on the first violation); and a leaf can never be a parent, because a non-container
parent is already rejected. So clause 3 is defence-in-depth here, exactly as the depth-3
add-menu guard is on the editor side. The consequence for testing is that a depth-4 archive
must be asserted against the **clause-4 message**, not a generic `pytest.raises`, or the
test cannot distinguish the two clauses and its mutant is vacuous.

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
- `courses/views.py:1198` — the quiz context's own copy

So an HTML element authored inside a tab today never loads `html_element.js`
(`lesson_unit.html:67`, `quiz_unit.html:23`) unless an unrelated top-level HTML element
happens to exist. This is a **pre-existing** defect, not one this slice creates. It is fixed
here because the single allowlist newly admits `html` into spoilers, and because every
sibling flag (`has_questions`, `has_reveal_gate`, `has_switch_grid`, `has_stepper`,
`has_markdone`, `has_guess_number`, `has_stateful_elements`) is already a flat unit-wide
query for exactly this reason.

**Fix:** both sites become flat `node.elements.filter(...)` queries. `courses/views.py:328`
computes `html_ct_id` whose **only** consumer is line 346, so it must be **removed** in the
same change — an assigned-but-unused local trips ruff F841 against the "ruff clean" DoD
gate. Check whether the `HtmlElement` import becomes unused at either site and remove it
too. Note that CT-id lookups were deliberately preferred here once before, to avoid
cold-cache ContentType SELECTs breaking a query-count assertion; the replacement filter
should therefore use `content_type__model="htmlelement"` pinned by
`content_type__app_label="courses"`, the same shape `has_stateful_elements` already uses.

**Correction to an earlier draft of this spec, recorded so it is not re-introduced:** it is
NOT true that `tests/test_html_element.py` carries an expected query *number* that needs
bumping. `test_lesson_html_render_query_count_invariant` asserts a **relative** invariant
(`len(q3) == len(q1)`, a 1-element page against a 3-element page); one additional constant
query lands in both captures and the assertion is unaffected. What does need attention is
that test's ContentType warm-up comment, which references `get_for_model(HtmlElement)` on a
code path this fix may remove.

### `_add_menu.html` loses `in_spoiler` entirely

The flag exists only to express the narrower spoiler allowlist. With one allowlist it
disappears. Each guard needs its replacement stated, because two of them are inclusion
guards and deleting them outright is wrong:

- HTML (line 20), Spoiler (35), Step-by-step (36), Checklist (37), Guess-the-number (38):
  `{% if not in_spoiler %}` is **deleted** — except Spoiler, which becomes a container card
  governed by the depth predicate.
- Fill-in-the-blanks (line 39): `{% if in_spoiler %}` becomes `{% if nested %}`. Deleting
  it outright would render the card at top level, where line 49 already emits an identical
  `data-add-type="fillblankquestion"` card — two duplicates in the top-level menu.
- Tabs / Columns (lines 24-25): `{% if not nested %}` becomes the depth predicate.

Card visibility becomes a function of `nested` and `depth` only.

### LAL loader — a real widening, not a compile fix

`courses/lal_loader/builders.py:95-115` imports `SPOILER_CHILD_TYPES` as a **rejection
gate** (line 111) and interpolates `', '.join(sorted(SPOILER_CHILD_TYPES))` into its
`LoaderError` text (lines 113-115). Swapping in `NESTABLE_TYPE_KEYS` widens that gate by
seven types (`tabs`, `two_column`, `spoiler`, `html`, `stepper`, `mark_done`,
`guess_number`) and changes the error string.

`tests/lal_import/test_lesson.py:1483` depends on the current abort ("a depth-2 spoiler
dict … the loader guard would abort on"); after a naive swap it would no longer abort.

**Decision: the loader keeps its own narrower constant**, moved into the loader module and
named for what it is (the LAL corpus's permitted spoiler children). The loader is a
one-time import tool for a fixed corpus; widening its gate buys nothing and would silently
change what a re-run accepts. The named test above must keep passing unchanged; if the plan
finds it does not, that is a signal the constant was not actually preserved.

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

### Translatable strings that change (the `.po` gate depends on these)

Three message sites move, and the DoD's zero-fuzzy gate is a trap unless they are named:

| Site | Change |
|---|---|
| `payloads.py:784` `"Element '%(el)s' may not be nested inside a spoiler."` | **Deleted** with the spoiler branch. Removing a msgid leaves an obsolete entry — `makemessages` must run with `--no-obsolete`. |
| `payloads.py:797` `"Element '%(el)s' is nested more than one level deep."` | Factually wrong after this change; reword to name the actual cap, e.g. `"Element '%(el)s' is nested too deeply."` |
| `payloads.py:805` `"Element '%(el)s' may not be nested inside a tabs element."` | Now also reached for spoiler and two-column children; reword generically, e.g. `"Element '%(el)s' may not be nested."` |

A new clause-4 message is added for "a container may not be nested this deeply", and the
depth-4 test asserts against it (see Defect 3).

## Testing

### Falsification discipline (mandatory)

**Every test carries a named mutant** — a specific one-line edit to production code, at a
named file and line, that must be verified RED before the test counts as written. Not
"delete the feature and see"; not "same as above"; not a description of a behaviour to
break. A test whose named mutant does not go red is rewritten, not explained away. On an
earlier slice a falsification table was vacuous in six successive drafts before this rule
was applied.

One row below is deliberately exempt and says so.

### Coverage

| Area | Test | Named mutant |
|---|---|---|
| Depth rule | parametrized `resolve_scope`: (parent at depth 1/2/3) × (leaf, container). **The depth-3-parent parameters must be ORM-constructed** — clause 4 forbids a container at depth 3, so they are unreachable through `resolve_scope` itself; comment this in the test or it will be deleted as dead. | `builder.MAX_NEST_DEPTH 3 → 4` (valid only because `element_depth` reads the constant — see "Depth is computed, not stored") |
| Depth rule, clause 4 | a container child of a depth-2 parent is rejected; a leaf child of the same parent is accepted | delete the clause-4 branch in `resolve_scope` |
| Delete | delete a depth-3 subtree → zero orphan concretes at every level | `builder.py:411` → `_delete_element_content_objects(Element.objects.filter(parent=el))` (the pre-change one-level form) |
| Tab removal | remove a tab holding a container holding a leaf → no orphans | `builder.py:670` → `Element.objects.filter(parent=join, tab_id__in=removed)` without the subtree walk |
| **Duplicate unit** | duplicate a unit with leaf-in-spoiler-in-tab → the copy has the leaf | `export.py:walk_unit_joins` → drop the recursive descent, yield one level only |
| Export / import | full round trip at depth 3 | same edit as the row above, asserted on the archive payload rather than the duplicate |
| Import validator | depth-4 archive rejected, **asserting the clause-4 message specifically** | delete the clause-4 branch in `validate_nesting` |
| Import validator | container-at-depth-3 archive rejected | same branch deletion, asserted at depth 3 rather than 4 |
| Import validator | **parent-cycle archive terminates with a validation error** | raise the hop bound from `MAX_NEST_DEPTH` to a large finite number (e.g. 10_000) and assert the depth-4 chain is still caught. **Do NOT use `while parent is not None`** — that mutant hangs instead of failing, and `pytest-timeout` is not installed in this repo, so the run would wedge indefinitely rather than going RED. |
| Editor — nested spoiler | a spoiler nested in a tab renders its children and its add-menu | restore `and el.parent_id is None` on `_element_row.html:136` |
| Editor — top-level menu | the top-level add menu still offers Tabs and Columns (the `depth`-seeding regression) | delete `depth=1` / `depth=0` from `_editor_scope.html`, leaving `depth` unseeded |
| Editor — depth 2 | the add-menu inside a depth-1 container offers Tabs/Columns/Spoiler; the one inside a depth-2 container does not | delete the depth predicate on the Tabs card in `_add_menu.html` |
| Editor — depth 3 | no add-menu is emitted inside a depth-3 element (ORM-constructed fixture, see above) | delete the depth guard around the `_add_menu.html` include in `_element_row.html` |
| `has_html` | unit whose ONLY html element is inside a tab loads `html_element.js` | `views.py:346` → the pre-change `any(el.content_type_id == html_ct_id for el in elements)` |
| `has_math` | unit whose ONLY math sits at depth 3 | `views.py:201` `return _spoiler_has_math(obj)` → `return False` |
| Student render | a depth-3 leaf renders inside its nested container | **Exempt, deliberately.** The render path is unchanged by this slice (see Data flow), so this is a characterization test pinning existing behaviour at a new depth, not a test of new logic. |

### Vacuity traps

- The `has_html` and `has_math` tests MUST use an **isolated** unit whose only html/math
  lives at the nested depth under test. A unit that also has top-level math passes both
  before and after the fix.
- The editor-template tests must assert on rendered markup for a genuinely depth-3 fixture,
  not on a depth-2 fixture that happens to exercise the same branch.
- **Any test that renders `_element_row.html` or `_add_menu.html` directly must pass an
  explicit `depth`.** Django's `smartif` swallows comparison `TypeError`s, so a template
  test that omits `depth` evaluates every depth predicate to False and can keep passing
  vacuously while the real editor is broken. This applies to existing direct-render tests
  too: `courses/tests/test_reveal_gate_editor_row.py:46-50` and
  `tests/test_tabs_editor_partial.py:70-72` both call `render_to_string` with no `depth`
  and must be updated.

### Existing guardrail tests to INVERT (not delete)

These assert the old cap and are the tests most likely to be quietly removed. The list is
exhaustive as of master `901f6cf0`; the plan must re-verify it rather than trust it.

| Site | Action |
|---|---|
| `tests/test_twocolumn_registry.py:15` — `"two_column" not in NESTABLE_TYPE_KEYS` | Invert to `in`. |
| `tests/test_twocolumn_registry.py:16` — `"twocolumn" not in NESTABLE_TYPE_KEYS` | **Must survive unchanged.** `twocolumn` remains a form key only; this assertion pins the form-key/transfer-key split. Do not invert it along with line 15. |
| `tests/test_twocolumn_registry.py:48` — `test_resolve_scope_rejects_container_child_in_two_column` | The `"tabs"` case inverts to an accept (parent at depth 1); the `"choicequestion"` case stays a reject. Rename the test — its current name becomes false. |
| `courses/tests/test_spoiler_nesting.py:~149` — `for bad in ("tabs", "spoiler", "choicequestion")` against a top-level spoiler | `"tabs"` and `"spoiler"` become **legal** children — they are two of the three shapes in the Purpose section. The reject tuple reduces to `("choicequestion",)`; add a matching accept case for `tabs` and `spoiler`. |
| `courses/tests/test_spoiler_nesting.py:163-165` — the `SPOILER_CHILD_TYPES` membership table | The constant is deleted; the table becomes a `NESTABLE_TYPE_KEYS` table. |
| `courses/tests/test_spoiler_nesting.py:~190` — "a nested spoiler may not have children" | Inverts: a nested spoiler may now have children. |
| `tests/test_tabs_editor_partial.py:79-90` — `test_nested_add_menu_offers_only_nestable_types`, asserting `'data-add-type="tabs"' not in html` | Inverts: offering Tabs in a nested menu at depth 1 is the point of this slice. **Must pass an explicit `depth`** — without one the stale assertion keeps passing vacuously (see Vacuity traps). |
| `tests/test_tabs_transfer.py:135` — the `# depth > 1` reject case | Its middle element is a **text** element (`_child()` defaults to `type_="text"`), so after this change it is still rejected — by the "parent is not a container" rule, not by any depth rule. It silently stops testing depth and duplicates another row of the same table. Rebuild it with a container middle element so it still exercises the depth clause, or retire it in favour of the new depth-4 test. |
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
2026-08-02, and the round-1 spec review re-verified them by execution. One claim was found
false and is corrected in place (the `test_html_element.py` query-count claim). The plan
must still verify each load-bearing claim by execution before depending on it: a confident
false mechanism survived 26 review rounds on an earlier slice.

## Definition of done

Every gate below must be runnable exactly as written.

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
- `.po` catalogs zero-fuzzy, regenerated with `-l pl -l en --no-obsolete` (the three changed
  message sites above include one deletion, which leaves an obsolete entry otherwise).
- Every test in the coverage table has its named mutant recorded and verified RED, except
  the one row marked exempt.

## Out of scope

- **Callout as a container** — PR2 of this pair (tables in callouts, math in callouts). Its
  design decision is already taken: the callout's existing `body` renders FIRST and its
  children FOLLOW, so existing callouts are unaffected and nesting is purely additive. This
  deliberately differs from Spoiler, where children REPLACE the legacy body
  (`spoilerelement.html:7-13`; `SpoilerElementForm.__init__` drops the `body` field once
  children exist). **Spoiler's semantics are NOT changed here:** spoilers holding both a
  body and children exist in the wild and currently render children only; harmonising would
  newly reveal hidden text on live courses.
- Theme context for nested HTML elements (see Known limitation above).
- Images in table cells (slice C).
- The deferred `sanitize_html` math-protection spec — still blocked on the mat-pp PROD
  cutover.
- Elements inside table cells — dropped by agreement.
