# Long-course navigation UX

## Purpose

Two navigation failures appear only once a course grows long. Neither is visible on the
small demo courses the UI was built against.

1. **Builder — the detail panel scrolls away.** `.builder` is a two-column CSS grid
   (`grid-template-columns: 2fr 1fr`, `courses/static/courses/css/builder.css:1`). The right
   column (`.builder__panel`) is an ordinary in-flow grid item, so its content sits near the
   top of the document. On a course whose tree is several viewport-heights tall, an author
   who scrolls down and clicks a unit near the end gets the panel swapped in — off-screen
   above them. They must scroll back to the top to reach *Add element* / *Open editor*, then
   scroll back down to pick the next unit. The cost is paid on every single unit edit.

2. **Student tree — the current unit is hard to find.** `templates/courses/_unit_tree.html`
   renders every unit of the course, fully expanded, with no per-group folding. A 300-row
   list is hard to scan no matter how the current row is styled. `unit_nav.js` does centre the
   active unit in the rail — but only on page load, and only when the rail is not collapsed
   (`courses/static/courses/js/unit_nav.js:35-46`). A student who collapses the rail and
   later expands it lands at scroll-top with the active unit an arbitrary distance away, with
   no automatic recovery. That is a latent bug, not just a styling weakness.

The goal is that an author never scrolls to reach the panel, and a student always opens a
course tree with the current unit visible and unmistakable — without introducing persisted
tree state, which would create its own "where was I?" problem.

## Architecture / components

Three parts. Part 1 is genuinely independent (it touches only `builder.css`). Parts 2A and 2B
are **coupled**: they share `courses/static/courses/css/courses.css`, and 2B's centring has to
account for a group 2A lets the user fold. **Implementation and merge order is 2A before 2B**,
and 2B's folded-group guard (see C4 below) ships with 2B, not 2A — until 2B lands, folding the
active unit's own group is possible but the rail is never re-centred, which is today's
behaviour and therefore no regression.

### Part 1 — Builder: sticky detail panel (CSS only)

`courses/static/courses/css/builder.css` only. No template or JS change.

The student rail already solves this exact problem and has been in production since the
lesson-shell work (`courses/static/courses/css/courses.css:505-507`):

```css
.unit-tree { position: sticky; top: 0; max-height: 100vh; overflow-y: auto; }
```

Part 1 applies the same pattern to the builder's panel column. The existing rule is
`.builder__panel { min-width: 0; }` (`builder.css:10`), preceded by a comment explaining that
**both** grid items need `min-width: 0` or the 1fr track balloons past its share and collapses
the 2:1 ratio — the bug fixed in `96c0905` / `2a85e2a`. The new declarations are **merged into
that existing rule**; `min-width: 0` and its comment must not be dropped:

```css
/* (existing comment about min-width:0 on both tracks stays put) */
.builder__panel { min-width: 0;
                  position: sticky; top: var(--space-4); align-self: start;
                  max-height: calc(100vh - var(--space-8)); overflow: hidden auto; }
```

- `align-self: start` is **required**, not decorative. Grid items default to
  `align-self: stretch`; a stretched item fills its row and therefore has no free space to
  travel within, so `position: sticky` silently does nothing. This is the single most likely
  way the part fails, which is why the e2e for it must be shown failing first (see Testing).
- `max-height` + vertical overflow cover the panel that is itself taller than the viewport
  (a unit with many elements). Without them, a tall panel's own buttons are pushed below the
  fold and the fix does not fix anything. `max-height` is a **ceiling**, not a fixed height —
  a short panel stays its natural height and produces no scroll container, so the page keeps
  scrolling normally when the pointer is over it.
- **Overflow is written as the two-value `overflow: hidden auto`, not `overflow-y: auto`.**
  Per CSS, a non-`visible` `overflow-y` forces `overflow-x` to compute to `auto`, so
  `overflow-y: auto` alone would silently make the panel a horizontal scroll container too
  and invite a stray horizontal scrollbar in the narrow 1fr track. `hidden auto` pins the
  intent: no horizontal scrolling. This is safe because every wide panel child already wraps
  or truncates within `min-width: 0` (`.panel__seam` wraps, `.element-list__summary`
  ellipsises) — but it does mean panel content must continue to wrap or truncate rather than
  overflow, and the content-heavy-panel screenshot check exists to catch a regression there.
- Below the existing `@media (max-width: 720px)` breakpoint (`builder.css:2`) the two columns
  stack vertically. Sticky is dropped there (`position: static`) so the panel cannot hover
  over the tree it is stacked above. No new breakpoint is introduced.
- **`100vh` is safe here** precisely because sticky only applies above 720px — the mobile
  visual-viewport discrepancy never comes into play. `top: var(--space-4)` needs no
  header-height offset because `.app-header` is `position: relative`, not sticky.
- **Panel scroll reset.** Once the panel is a scroll container, `builder.js` replacing its
  `innerHTML` on node select leaves any non-zero `scrollTop` in place, so the next unit's
  panel would appear scrolled part-way down. Every place `builder.js` swaps panel content must
  set `panel.scrollTop = 0` after the swap.

### Part 2A — Student tree: collapsible groups, current chain auto-open

Files: `courses/rollups.py`, `templates/courses/_unit_tree_node.html`,
`courses/static/courses/css/courses.css`.

**Markup.** `_unit_tree_node.html` currently renders a non-unit node as a
`<div class="unit-tree__head" lang="{{ course.language }}">` followed by
`<ul class="unit-tree__children">`. It becomes a native disclosure:

```
<li class="unit-tree__node unit-tree__node--{{ item.node.kind }}">
  <details class="unit-tree__group" {% if item.contains_current %}open{% endif %}>
    <summary class="unit-tree__head">
      <span class="unit-tree__chevron" aria-hidden="true">…</span>
      <span class="unit-tree__grouptitle" lang="{{ course.language }}">{{ item.node.title }}</span>
      <span class="unit-tree__count">…</span>   {# only when a counter applies #}
    </summary>
    <ul class="unit-tree__children">…</ul>
  </details>
</li>
```

`lang="{{ course.language }}"` moves onto the **title span**, not the whole summary: the title
is author content, the counter is UI chrome in the interface language, and the current markup
would otherwise mislabel the counter's language.

Native `<details>`/`<summary>` is chosen over a JS disclosure because it works with JS off,
brings keyboard operation and correct screen-reader semantics for free, and needs no state
machine, no ARIA wiring, and no new JS file. **A group with no children renders as it does
today** (a plain `<div class="unit-tree__head">`, no `<details>` wrapper) — an empty disclosure
would be a dead control. Both shapes therefore exist in the DOM and both must be styled.

**Open state.** `contains_current` is computed **server-side** so the correct groups are open
in the first painted frame; a JS pass would flash the fully-folded tree first.

**The stamping contract is explicit:** a single pass over the `build_outline` tree sets
`contains_current` on **every** node dict — group *and* unit — initialising it to `False` and
setting it to `True` for the current unit's dict (`pk == current_pk`) and every ancestor of it.
The key is therefore always present, never merely absent-when-false, so a test can assert
`is False` on non-ancestor groups without a `KeyError` and the template's
`{% if item.contains_current %}` has one unambiguous meaning.

`courses/rollups.py` already has this recursion inside `_top_level_part` — a local `contains(d)`
that tests `d["node"].pk == current_pk` or any child. That recursion is generalised into the
stamping pass, and **`_top_level_part` is re-expressed in terms of the stamped flag** rather
than keeping a second copy of the walk: it returns the first root dict whose `contains_current`
is `True`. Because the pass stamps unit dicts too, this preserves the existing contract that
`_top_level_part` can return a root that **is itself the current unit** — `build_unit_nav`
reads `top["is_unit"]` to suppress the part chip for a depth-1 unit, and
`tests/test_unit_nav_render.py::test_unit_shell_part_chip_hidden_for_root_unit` guards exactly
that. A regression test for the depth-1-unit case is required (see Testing).

The pass is pure dict mutation over an already-materialised tree: **no additional queries**.

**No persistence, and no size threshold.** Fold state is not stored — every page load resets to
"the current unit's chain is open, everything else is shut." This is a deliberate product
decision: persisted fold state would let a student navigate to a unit whose chapter they had
previously folded shut, arriving at a tree that hides where they are, which in turn would
require a "jump to current" affordance to repair. Resetting per load makes that affordance
unnecessary. **The rule is unconditional — there is no "open everything for short courses"
threshold.** A short course does lose some at-a-glance context, but a size-dependent rule would
make the tree behave differently on two courses for no reason the student can see, and any
threshold would be arbitrary; one click reopens a group. The accepted costs, stated plainly:
short courses fold too, and a student who opens three chapters to browse loses those opens on
the next navigation.

**Folded row content.** A `<summary>` shows the group title plus its required-work progress as
`done/total`, read from `required_done` / `required_total`, which `build_outline` already places
on every group dict (`build_unit_nav` consumes exactly these fields today for `part_progress`
and `course_progress`). A group at `n/n` additionally gets the ✓ badge that completed units
already use (`.unit-tree__check.badge.badge--done`), so "finished" reads identically at unit and
group level.

The counter is **suppressed entirely** — no counter, no ✓ — in either of these cases:

- `required_total == 0`: no required work to count. Neither `0/0` nor a bare suffix.
- `user.is_authenticated` is `False`: `build_outline` sets `completed = set()` for anonymous
  viewers, so every group would otherwise render a misleading `0/12` on a surface that shows no
  completion state today. Anonymous and preview viewers see titles only.

**Summary row layout.** `.unit-tree__head` is a plain block today, and the rail is
`flex: 0 0 14rem` — adding a chevron and a counter to that row without pinning the layout would
wrap long chapter titles or push the counter out of view. The summary is a **flex row**:
chevron (fixed, non-shrinking) / title (`flex: 1; min-width: 0` with `overflow: hidden;
text-overflow: ellipsis; white-space: nowrap`, mirroring `.unit-tree__label`) / counter
(non-shrinking trailing chip). 

**Accessible naming.** A bare `3/7` announces as "three slash seven" with no context. The
counter carries a translatable accessible label — a visually-hidden span or `aria-label` with
msgid `"%(done)s of %(total)s required units completed"` — added to **both** the `en` and `pl`
catalogs, using `gettext_lazy` if it is ever referenced at module level. The decorative chevron
is `aria-hidden="true"`. `<details>`/`<summary>` supply the expanded/collapsed state natively;
no `aria-expanded` is added by hand.

**Both surfaces from one change.** `_unit_tree_node.html` is included by both
`_unit_tree.html` (desktop rail) and `_unit_shell.html`'s mobile drawer, so the desktop rail
and the drawer both gain folding from this single edit.

**Flat courses.** A course on the Flat depth preset has no group nodes at all, so its tree
renders byte-identically to today. Part 2B is what helps those courses.

**CSS — the child-combinator break is the real hazard.** The element change from `div` to
`summary` is minor; the added **nesting level** is not. Today
`.unit-tree__node--section > .unit-tree__head` and `.unit-tree__node--chapter > .unit-tree__head`
(`courses.css:540-542`) match a *direct child* of the `<li>`. With `<details class="unit-tree__group">`
interposed, both selectors stop matching and chapters/sections silently lose their uppercase
micro-type — destroying the exact scanability this feature exists to improve. Those selectors
must be rewritten (drop the `>`, or add `.unit-tree__group > .unit-tree__head` variants) and
**must keep matching the childless-group shape**, which still has `.unit-tree__head` as a direct
child of the `<li>`. `.unit-tree__head`'s margins likewise have to survive the move.

The remaining `<summary>` declarations are pinned rather than left to interpretation:
`display: flex` (which also removes the default `list-item` box), `list-style: none`,
`::-webkit-details-marker { display: none }` for older WebKit, and `cursor: pointer` — the row
is now interactive. It also gets a `:focus-visible` treatment consistent with the rest of the
rail, and a hover treatment matching `.unit-tree__unit:hover`. The chevron rotates off
`details[open]`.

### Part 2B — Reliable "you are here"

Files: `courses/static/courses/js/unit_nav.js`, `courses/static/courses/css/courses.css`.

**(1) Re-centre on expand — bug fix.** The centring block at `unit_nav.js:35-46` runs once at
load and is guarded by `!isCollapsed()`. It is extracted into a named function `centerActive()`
with a **self-contained interface**, so both call sites are unconditional one-liners: the
function performs its own `document.querySelector("[data-unit-tree]")` and `.is-active` lookups
at call time (not module-evaluation time, so it never operates on a stale reference), and its own
`isCollapsed()` and null guards. It keeps the existing scroll-the-container arithmetic verbatim —
`scrollIntoView` is deliberately avoided because it walks every scrollable ancestor and can nudge
the window and the article, which is why the current code computes rail-relative coordinates by
hand — and keeps the existing `prefers-reduced-motion` branch.

Call sites:

- the existing load path, and
- the toggle's click handler. That handler has **no branch today** — it computes
  `var collapsed = html.classList.toggle("unit-tree-collapsed")` and calls `store` / `syncToggle`
  unconditionally. The change is to add `if (!collapsed) centerActive();` to it. Nothing is
  centred on the collapse direction (there is nothing to centre in a 2.4rem rail).

**Guard for a folded active unit.** Part 2A lets a student fold the very group containing the
active unit, and they can then collapse and expand the rail. A `display: none` element reports
`getBoundingClientRect().top === 0` and `offsetHeight === 0`, so the existing arithmetic computes
a large negative target and `scrollTo` clamps it to 0 — the rail silently jumps to the top. That
would be a **new bug shipped by the fix**, so `centerActive()` returns early when the active
element has no layout box (`active.offsetParent === null`), leaving `scrollTop` untouched.
`centerActive()` never opens groups; folding is the student's explicit choice and is respected.

**(2) Louder active marker.** The current treatment is **not** the bare subtle-primary the first
draft of this spec claimed. `courses.css:548-549` already ships:

```css
.unit-tree__unit.is-active { background: var(--primary-subtle); color: var(--primary);
  font-weight: 600; border-left: 2px solid var(--primary); }
```

So "add an accent bar and heavier weight" is already done and is not a requirement. What is
actually left is that this treatment is too quiet **at scale** — a 2px bar inset by
`margin-left: .35rem`, sitting in a column where every non-active row already carries
`border-left: 1px solid var(--border-subtle)`, differs from its neighbours by one pixel of border
and one weight step. The concrete requirements are:

- **Strengthen the bar** to 3–4px so it is not near-identical to every sibling row's 1px border,
  and make it read as a full-height marker against the row's rounded corners rather than a
  slightly thicker sibling.
- **Raise weight** from 600 to 700.
- **Survive `.is-done`.** A completed *and* current unit gets `.is-done`'s `--text-tertiary`
  applied alongside `.is-active`'s `--primary`; source order currently decides. The active
  treatment must win for a done+active row — otherwise the single row a student most needs to
  find is the one rendered faintest.
- **Compose with `:focus-visible`** without doubling up into a muddy ring.

The precise values within those constraints are settled by running the repo's `frontend-design`
skill, and verified with light **and** dark Playwright screenshots of both the rail and the
drawer before the work is considered done — the repo's standing rule for any styling change.

## Data flow

```
lesson_unit / quiz_unit view (courses/views.py)
  └─ build_unit_nav(course, user, current_node)          courses/rollups.py
       ├─ build_outline(course, user)   → tree of dicts, each with
       │      node, is_unit, children, required_done, required_total, completed
       ├─ NEW: stamping pass — contains_current = False on EVERY dict,
       │      then True on the current unit's dict and all its ancestors
       │                                              (pure, no queries)
       ├─ _top_level_part now reads the stamped flag (first root with
       │      contains_current True) — still returns a root that IS the
       │      current unit, so the depth-1 part-chip suppression holds
       └─ returns {tree, current_pk, prev, next, part_progress, course_progress}
             │
             ├─ templates/courses/_unit_tree.html        (desktop rail)
             └─ templates/courses/_unit_shell.html       (mobile drawer)
                    └─ both include _unit_tree_node.html (recursive)
                           ├─ unit          → <a class="unit-tree__unit … is-active">
                           ├─ group, kids   → <details {% if item.contains_current %}open{% endif %}>
                           │                    <summary> chevron + title + counter? </summary>
                           └─ group, no kids→ <div class="unit-tree__head"> (unchanged shape)

counter shown only when required_total > 0 AND user.is_authenticated

browser
  └─ unit_nav.js
       ├─ on load                → centerActive()
       └─ on toggle → expanding  → centerActive()          ← the fix
            centerActive(): re-queries rail + .is-active, returns early if
            collapsed, missing, or offsetParent === null (folded group)
```

Part 1 introduces no data flow: it is a stylesheet change to an existing grid item, plus a
`scrollTop = 0` reset at `builder.js`'s existing panel-swap sites.

## Error handling

The feature has no new failure modes of its own — no new requests, no new persisted state, no
new user input. What it has is a set of degradation paths that must each stay benign:

- **JS disabled.** `<details>` folding, including the server-set `open` on the current chain,
  works with no script at all. Only the centring and the mobile drawer need JS, exactly as
  today.
- **Missing / stale `contains_current`.** The stamping pass writes the key on every dict, so
  "missing" means the pass did not run at all; the tree then renders fully folded — degraded but
  not broken. The render tests assert both the `True` chain and `False` elsewhere, so this
  cannot ship silently.
- **Current unit not in the tree** (e.g. a node the user cannot see): no dict is stamped `True`,
  nothing is force-opened, `_top_level_part` returns `None` (its existing contract, so
  `part_progress` stays `None`), and `centerActive()` finds no `.is-active` element and returns
  without touching scroll.
- **Active unit inside a user-folded group:** `centerActive()` returns early on
  `offsetParent === null` rather than clamping the rail to scroll-top.
- **`required_total == 0` / anonymous viewer.** No counter is rendered; no ratio is computed, so
  there is no divide-by-zero path.
- **Tall builder panel.** Handled structurally by `max-height` + overflow, not by an error path.
- **Sticky unsupported / stacked layout.** The panel falls back to its current in-flow
  behaviour — today's UX, not a broken one.

## Testing

**Django render tests** (`tests/test_unit_nav_render.py` is the existing home):

- `contains_current` is `True` for the current unit's dict and every ancestor, and **`False`**
  (present, not absent) for every other group — including a sibling group at the same depth and
  a deeper group in an unrelated branch.
- The rendered tree carries `open` on exactly those groups' `<details>`.
- **Depth-1 unit regression:** a course whose current unit is a root node still suppresses the
  part chip — `_top_level_part` returns that root unit dict after the refactor. (Extends the
  existing `test_unit_shell_part_chip_hidden_for_root_unit`.)
- The counter renders `done/total` from the group's rollup fields, with its accessible label.
- A group with `required_total == 0` renders no counter.
- An **anonymous** viewer sees no counter and no ✓ on any group.
- A group at `n/n` renders the done badge.
- A group with **no children** renders no `<details>` and keeps the plain `.unit-tree__head`.
- A Flat-preset course renders no `<details>` at all.
- `build_unit_nav` issues no more queries than before. The baseline must be **captured on
  `master` and quoted in the test's docstring**, then asserted with `assertNumQueries` — measuring
  post-change and hard-coding the result would make the assertion incapable of detecting the
  regression it exists to catch.

**e2e (Playwright)** — must drive the real UI with real clicks; `page.evaluate` shortcuts are
forbidden by the repo's standing e2e rule, since they would let a broken control ship green.
Per the repo's "falsify tests, don't run them" rule, **each e2e below must be demonstrated RED**
before its implementation lands — most importantly the builder one, whose whole subject is a
single easily-omitted `align-self: start`.

Seeding: `tests/test_e2e_unit_nav.py`'s `_seed_nav_course(..., num_units=35)` builds a **flat**
unit list; nothing in the file creates chapter/section nodes. It is extended (or a sibling helper
added) taking `num_chapters` × `units_per_chapter` — enough total units to exceed the rail's
viewport — with the current unit placed in the **middle** chapter so both "an earlier sibling is
shut" and "a later sibling is shut" are observable.

- On loading that middle-chapter unit, its chapter's `<details>` is open and the sibling
  chapters are shut.
- A real click on a folded `<summary>` reveals that chapter's units.
- Collapsing the rail with the real toggle and expanding it again leaves the active unit centred
  — assert the rail's scroll position places the active element within the rail's visible band,
  not merely that `scrollTop != 0`.
- **Folded-active guard:** fold the active unit's own group, then collapse → expand the rail, and
  assert the rail's `scrollTop` is unchanged (no jump to top).
- **Builder, deep unit:** with the tree scrolled to the bottom, click a deep unit and assert
  *Open editor* is inside the viewport.
- **Builder, tall panel:** on a unit whose panel exceeds the viewport, the panel's last control is
  reachable (the panel scrolls internally rather than clipping).
- **Builder, stacked:** at a ≤720px viewport the panel is **not** sticky.

**Screenshots.** Light and dark, desktop rail and mobile drawer, reviewed before shipping, plus
one content-heavy builder panel to confirm `overflow: hidden auto` clips nothing that matters.
Also check whether any committed help screenshot under `core/static/core/img/help/` depicts the
unit tree; if one does, regenerate it, since this change dates it.

**Conventions.** `uv run` for `pytest` / `ruff` (they are not on PATH). Any new user-visible
string is wrapped for i18n and added to both the `en` and `pl` catalogs; removed msgids are
deleted from both `.po` files rather than left as obsolete `#~` entries. This worktree needs
its own `DATABASE_URL` to avoid colliding with the other checkouts on the shared
`test_libli` database.
