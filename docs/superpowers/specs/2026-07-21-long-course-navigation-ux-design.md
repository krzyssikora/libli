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
   renders every unit of the course, fully expanded, with no per-group folding. The current
   unit carries `.is-active` (`--primary-subtle` background, `--primary` text), which reads
   well in a 12-row list and disappears in a 300-row one. `unit_nav.js` does centre the
   active unit in the rail — but only on page load, and only when the rail is not collapsed
   (`courses/static/courses/js/unit_nav.js:35-46`). A student who collapses the rail and
   later expands it lands at scroll-top with the active unit an arbitrary distance away, with
   no automatic recovery. That is a latent bug, not just a styling weakness.

The goal is that an author never scrolls to reach the panel, and a student always opens a
course tree with the current unit visible and unmistakable — without introducing persisted
tree state, which would create its own "where was I?" problem.

## Architecture / components

Three independent parts. They touch disjoint files apart from `courses.css`, and each is
independently shippable and testable.

### Part 1 — Builder: sticky detail panel (CSS only)

`courses/static/courses/css/builder.css` only. No template or JS change.

The student rail already solves this exact problem and has been in production since the
lesson-shell work (`courses/static/courses/css/courses.css:505-507`):

```css
.unit-tree { position: sticky; top: 0; max-height: 100vh; overflow-y: auto; }
```

Part 1 applies the same pattern to the builder's panel column:

```css
.builder__panel { position: sticky; top: var(--space-4); align-self: start;
                  max-height: calc(100vh - var(--space-8)); overflow-y: auto; }
```

- `align-self: start` is **required**, not decorative. Grid items default to
  `align-self: stretch`; a stretched item fills its row and therefore has no free space to
  travel within, so `position: sticky` silently does nothing. This is the single most likely
  way the part fails.
- `max-height` + `overflow-y: auto` cover the panel that is itself taller than the viewport
  (a unit with many elements). Without them, a tall panel's own buttons are pushed below the
  fold and the fix does not fix anything. `max-height` is a **ceiling**, not a fixed height —
  a short panel stays its natural height and produces no scroll container, so the page keeps
  scrolling normally when the pointer is over it.
- Below the builder's existing stacking breakpoint the two columns stack vertically. Sticky is
  dropped there (`position: static`) so the panel cannot hover over the tree it is stacked
  above. The breakpoint value is whatever `builder.css` already uses; this spec does not
  introduce a new one.

### Part 2A — Student tree: collapsible groups, current chain auto-open

Files: `courses/rollups.py`, `templates/courses/_unit_tree_node.html`,
`courses/static/courses/css/courses.css`.

**Markup.** `_unit_tree_node.html` currently renders a non-unit node as a
`<div class="unit-tree__head">` followed by `<ul class="unit-tree__children">`. It becomes a
native disclosure:

```
<li class="unit-tree__node unit-tree__node--{{ item.node.kind }}">
  <details class="unit-tree__group" {% if item.contains_current %}open{% endif %}>
    <summary class="unit-tree__head">title … progress</summary>
    <ul class="unit-tree__children">…</ul>
  </details>
</li>
```

Native `<details>`/`<summary>` is chosen over a JS disclosure because it works with JS off,
brings keyboard operation and correct screen-reader semantics for free, and needs no state
machine, no ARIA wiring, and no new JS file. A group with no children renders as it does
today (no `<details>` wrapper) — an empty disclosure would be a dead control.

**Open state.** `contains_current` is computed **server-side** so the correct groups are open
in the first painted frame; a JS pass would flash the fully-folded tree first.
`courses/rollups.py` already has the needed recursion inside `_top_level_part` — a local
`contains(d)` that tests `d["node"].pk == current_pk` or any child. That recursion is
generalised into a small pass over the `build_outline` tree that stamps `contains_current`
on every group dict whose subtree holds `current_pk`, and `_top_level_part` is expressed in
terms of the generalised helper rather than keeping a second copy of the same walk. The pass
is pure dict mutation over an already-materialised tree: **no additional queries**.

**No persistence.** Fold state is not stored — every page load resets to "the current unit's
chain is open, everything else is shut." This is a deliberate product decision: persisted
fold state would let a student navigate to a unit whose chapter they had previously folded
shut, arriving at a tree that hides where they are, which in turn would require a
"jump to current" affordance to repair. Resetting per load makes that affordance unnecessary.
The cost is that a student who manually opens three chapters to browse loses those opens on
the next navigation; that is accepted.

**Folded row content.** A folded `<summary>` shows the group title plus its required-work
progress as `done/total`, read from `required_done` / `required_total`, which
`build_outline` already places on every group dict (`build_unit_nav` consumes exactly these
fields today for `part_progress` and `course_progress`). A group at `n/n` additionally gets
the ✓ badge that completed units already use (`.unit-tree__check.badge.badge--done`), so
"finished" reads identically at unit and group level. A group with `required_total == 0` has
no required work to count and shows **no counter at all** — neither `0/0` nor a bare title
suffix.

**Both surfaces from one change.** `_unit_tree_node.html` is included by both
`_unit_tree.html` (desktop rail) and `_unit_shell.html`'s mobile drawer, so the desktop rail
and the drawer both gain folding from this single edit.

**Flat courses.** A course on the Flat depth preset has no group nodes at all, so its tree
renders byte-identically to today. Part 2B is what helps those courses.

**CSS.** `<summary>` needs its default disclosure marker suppressed
(`list-style: none` + `::-webkit-details-marker { display: none }`) and its `display` reset,
and the existing group styling (`courses.css:536-554`, notably
`.unit-tree__head`'s margins and the `--section`/`--chapter` size overrides) must survive the
element change from `div` to `summary`. A custom rotating chevron indicates open/closed
state, driven off `details[open]`.

### Part 2B — Reliable "you are here"

Files: `courses/static/courses/js/unit_nav.js`, `courses/static/courses/css/courses.css`.

**(1) Re-centre on expand — bug fix.** The centring block at `unit_nav.js:35-46` runs once at
load and is guarded by `!isCollapsed()`. It is extracted into a named function
(`centerActive()`) and called from two places: the existing load path, and the collapse
toggle's **expand** branch (`courses/static/courses/js/unit_nav.js:21-25`), where the rail's
labels have just become visible. It is *not* called on the collapse branch (nothing to
centre in a 2.4rem rail). The extracted function keeps the existing scroll-the-container
arithmetic verbatim — `scrollIntoView` is deliberately avoided because it walks every
scrollable ancestor and can nudge the window and the article, which is why the current code
computes rail-relative coordinates by hand. It also keeps the existing
`prefers-reduced-motion` branch.

One ordering consequence of Part 2A: a unit inside a folded group has no layout box, so
centring it would be meaningless. Because the current unit's chain is always open on load,
and folding is user-initiated after that, `centerActive()` retains its existing behaviour of
operating on whatever the active element's current geometry is; it does not attempt to open
groups.

**(2) Louder active marker.** `.unit-tree__unit.is-active` gains a solid left accent bar and
heavier text weight on top of its current subtle-primary treatment, so it is findable by
peripheral vision while scrolling rather than only on inspection. The precise treatment
(bar width, weight, and how it composes with `.is-done` and with the focus ring) is settled
by running the repo's `frontend-design` skill rather than being fixed numerically here, and
is verified with light **and** dark Playwright screenshots of both the rail and the drawer
before the work is considered done — the repo's standing rule for any styling change.

## Data flow

```
lesson_unit / quiz_unit view (courses/views.py)
  └─ build_unit_nav(course, user, current_node)          courses/rollups.py
       ├─ build_outline(course, user)   → tree of dicts, each with
       │      node, is_unit, children, required_done, required_total
       ├─ NEW: stamp contains_current on every group dict whose
       │      subtree contains current_node.pk        (pure, no queries)
       └─ returns {tree, current_pk, prev, next, part_progress, course_progress}
             │
             ├─ templates/courses/_unit_tree.html        (desktop rail)
             └─ templates/courses/_unit_shell.html       (mobile drawer)
                    └─ both include _unit_tree_node.html (recursive)
                           ├─ unit  → <a class="unit-tree__unit … is-active">
                           └─ group → <details {% if item.contains_current %}open{% endif %}>
                                        <summary>title + done/total (+ ✓ at n/n)</summary>

browser
  └─ unit_nav.js
       ├─ on load           → centerActive()   (when rail not collapsed)
       └─ on toggle→expand  → centerActive()   ← the fix
```

Part 1 introduces no data flow: it is a stylesheet change to an existing grid item.

## Error handling

The feature has no new failure modes of its own — no new requests, no new persisted state, no
new user input. What it has is a set of degradation paths that must each stay benign:

- **JS disabled.** `<details>` folding, including the server-set `open` on the current chain,
  works with no script at all. Only the centring and the mobile drawer need JS, exactly as
  today.
- **Missing / stale `contains_current`.** If the stamping pass somehow does not run, the
  template's `{% if item.contains_current %}` is falsey for every group and the tree renders
  fully folded — degraded but not broken, and caught by the render tests. Django templates
  swallow the missing-key case silently, which is why the tests assert the *presence* of
  `open` on the chain, not merely the absence elsewhere.
- **Current unit not in the tree** (e.g. a node the user cannot see): no group is stamped,
  nothing is force-opened, and `centerActive()` finds no `.is-active` element and returns
  without touching scroll — the existing null-guard already covers this.
- **`required_total == 0`.** No counter is rendered; no division or ratio is computed, so
  there is no divide-by-zero path.
- **Tall builder panel.** Handled structurally by `max-height` + `overflow-y`, not by an
  error path.
- **Sticky unsupported / stacked layout.** The panel falls back to its current in-flow
  behaviour — today's UX, not a broken one.

## Testing

**Django render tests** (`tests/test_unit_nav_render.py` is the existing home):

- `contains_current` is stamped on exactly the current unit's ancestor chain — assert it is
  true for every ancestor and false for every other group, including a sibling group at the
  same depth and a deeper group in an unrelated branch.
- The rendered tree carries `open` on exactly those groups' `<details>`.
- The folded-row counter renders `done/total` from the group's rollup fields.
- A group with `required_total == 0` renders no counter.
- A group at `n/n` renders the done badge.
- A Flat-preset course renders no `<details>` at all (no regression for the group-less case).
- `build_unit_nav` issues no more queries than before — assert with `assertNumQueries` against
  the pre-change count so "no extra queries" is enforced rather than asserted in prose.

**e2e (Playwright)** — must drive the real UI with real clicks; `page.evaluate` shortcuts are
forbidden by the repo's standing e2e rule, since they would let a broken control ship green:

- Seed a course long enough to exceed the rail's viewport, with several chapters. On loading a
  unit in the middle chapter, that chapter's `<details>` is open and the sibling chapters are
  shut.
- Clicking a folded `<summary>` reveals that chapter's units (real click on the summary).
- Collapsing the rail with the real toggle and then expanding it again leaves the active unit
  centred in the rail (assert the rail's scroll position places the active element within the
  rail's visible band, not merely that `scrollTop != 0`).
- Builder: with the tree scrolled to the bottom, click a deep unit and assert *Open editor* is
  inside the viewport.

**Screenshots.** Light and dark, desktop rail and mobile drawer, reviewed before shipping.

**Conventions.** `uv run` for `pytest` / `ruff` (they are not on PATH). Any new user-visible
string is wrapped for i18n and added to both the `en` and `pl` catalogs; removed msgids are
deleted from both `.po` files rather than left as obsolete `#~` entries. This worktree needs
its own `DATABASE_URL` to avoid colliding with the other checkouts on the shared
`test_libli` database.
