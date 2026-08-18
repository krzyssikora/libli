# Collapsible Course Outline

## Purpose

When a student opens a course they land on `courses:course_outline`
(`templates/courses/outline.html`), which renders the **entire** course as one flat
nested `<ul>`. Every part, chapter, section and unit in the course is in the DOM and
visible at once. On a real course that is unusable as a starting point: the student
must scroll past a thousand rows to find where they are.

One page over, the same tree is already collapsible. The unit rail
(`templates/courses/_unit_tree_node.html`) wraps each container in a native
`<details>`, server-opens the chain holding the current unit, and shows a
`done/total` counter on the summary. This spec brings that affordance to the outline
page, keeping the outline's own richer row (tag chips, edit-tags link, notes badge,
per-container *Start fresh*, part/chapter/section type scale).

### Measured starting state (local dev DB, 2026-08-18)

Raw `ContentNode` counts per course, by depth (depth 0 = root):

| Course | nodes | units | roots | max depth |
| --- | --- | --- | --- | --- |
| `mat-pp` | 1006 | 860 | 21 | 3 |
| `demo-course` | 48 | 32 | 5 | 2 |

`mat-pp` by depth: depth 0 — 21 containers, 0 units; depth 1 — 112 containers, 0 units;
depth 2 — 13 containers, 788 units; depth 3 — 0 containers, 72 units.

`demo-course` by depth: depth 0 — 3 containers, **2 units**; depth 1 — 13 containers,
**3 units**; depth 2 — 0 containers, 27 units.

Two of those numbers drive the design.

**`mat-pp` renders 1006 rows today.** Under the chosen default (D1: depth-0 containers
open, everything below folded) the first paint is 21 root rows + their 112 children =
**133 rows**, a 7.6x reduction. `demo-course` goes from 48 to 21.

**Units and containers coexist at the same depth.** `demo-course` has 2 units at depth 0
and 3 units at depth 1. "Top level open" therefore cannot mean "show only containers" —
a depth-0 unit is an ordinary row that is always visible, and only *containers* fold.

These are raw counts including drafts; the student view passes `drafts="hide"`, so a
student sees fewer. The ratio is what matters, and it does not depend on the filtering.

## Decisions

Settled during brainstorming. Do not re-litigate.

- **D1 — first view: depth-0 containers `open`, every deeper container folded.**
  Rejected: fold-everything (on a 3-root course the page looks empty), and
  auto-open-the-branch-you-are-working-on (needs a "next unit" computation the outline
  does not have, and is less predictable).
- **D2 — fold state persists per course in `localStorage`**, key
  `libli_outline_open:<course.slug>`, value a JSON array of open container node pks.
  Rejected: no persistence (a student re-opens their chapter on every return trip) and
  a server-side preference (a model, a migration and a write endpoint for a cosmetic
  preference).
- **D3 — native `<details>`/`<summary>`**, mirroring the rail. Rejected: a
  button + `hidden` toggle (builder style — needs JS to fold at all, and hand-rolls the
  `aria-expanded` semantics `<details>` gives free), and reusing the rail component
  wholesale (the outline row carries five affordances the rail deliberately lacks).
- **D4 — one *Expand all / Collapse all* toggle** in the outline header, its label
  reflecting current state. *Collapse all* folds depth 0 too.
- **D5 — a tag filter force-opens groups; that forced state is never persisted.**
  See §5 — this is the single most damaging thing the feature could get wrong.
- **D6 — a `#node-N` deep link opens its ancestors, and that *does* persist.**
- **D7 — the rail, the builder tree and the teacher per-student tree are untouched.**

## 1. Server — `depth` on the outline dicts

`courses/rollups.py :: build_outline` gains exactly one **additive** key per node dict:

```
"depth": 0 for a root, parent's depth + 1 otherwise
```

Set it in the existing pre-order fold loop, where the parent dict is guaranteed to
already exist (the loop's own invariant, documented in its docstring). No new query.

Additive is a hard constraint: `build_outline` has three consumers —
`courses/views.py :: course_outline`, the rail via `mark_contains_current`, and the
teacher per-student tree at `courses/rollups.py:528`. A new key is inert for the two
that ignore it; renaming or reshaping anything existing is out of scope.

Pruning happens *after* the fold (zero-child containers are dropped under both `hide`
and `keep`). Pruning removes nodes but never re-parents them, so a depth assigned
during the fold stays correct afterwards. No re-numbering pass is needed.

## 2. Markup — `templates/courses/_outline_node.html`

Only the **container-with-children** branch changes. Unit rows are untouched.

```
<details class="outline-node__group" data-node="{{ item.node.pk }}"
         {% if item.depth == 0 %}open{% endif %}>
  <summary class="outline-node__head">
    <svg class="icon outline-node__chevron" aria-hidden="true" viewBox="0 0 24 24">
      <path d="M9 6l6 6-6 6"/></svg>
    <span class="outline-node__title" lang="…" data-math-title>{{ item.node.title }}</span>
    {rollup counts}  {additional-done pill}  {Start fresh link}
  </summary>
  <ul>{children}</ul>
</details>
```

- The `<li class="outline-node" id="node-N">` wrapper, its `outline-node--{{kind}}`
  modifier and the `hidden` attribute all stay on the `<li>`, unchanged. The `<details>`
  goes *inside* it. This keeps `id="node-N"` as the scroll target and keeps
  `tags.js`'s `li[data-unit]` / `li.outline-node` queries working untouched.
- The chevron is the rail's, reused verbatim (`_unit_tree_node.html`), rotated by CSS on
  `[open]`.
- **The childless-container branch keeps today's plain `<div class="outline-node__head">`.**
  An empty disclosure is a dead control. This mirrors the rail's own childless branch and
  its reasoning; like the rail's, it is unreachable on this path because `build_outline`
  prunes zero-child containers under both `hide` and `keep`. It is kept as a correct
  fallback, not as a live shape, and no test should assert it is reachable.
- `data-node` on the `<details>` is what the client persists; it is deliberately on the
  `<details>` and not the `<li>`, so the client never has to walk between the two.
- *Start fresh* stays inside the `<summary>` (it must remain visible when the group is
  folded, and only the summary is). §4.6 stops its click from also toggling.

## 3. Header control — `templates/courses/outline.html`

One button in `.outline__head`, before the *My results* link:

```
<button type="button" class="btn btn--ghost btn--small outline__toggle-all"
        data-outline-toggle-all
        data-label-expand="{% trans 'Expand all' %}"
        data-label-collapse="{% trans 'Collapse all' %}">…</button>
```

Same `data-label-*` contract the rail's toggle uses, so the label swap is a shared
idiom rather than a new one. Rules:

- Label reads **Expand all** when at least one group is closed, **Collapse all** when
  every group is open. The server renders the initial label from the same rule (with the
  D1 default and at least one depth-1 container present, that is *Expand all*).
- *Collapse all* folds every group including depth 0.
- The button ships **without** a working no-JS behaviour: with JS off it would be a dead
  control, so it must be revealed by JS the way the drawer FAB is
  (`fab.hidden = false` in `unit_nav.js`). Ship it `hidden` in the template;
  `outline_tree.js` un-hides it.
- Both labels must be `{% trans %}`-wrapped and land in `locale/` (`makemessages`
  regenerates; see the fuzzy-prefill hazard in §9).

## 4. Client — new `courses/static/courses/js/outline_tree.js`

An IIFE in the house style (`"use strict"`, no framework, null-guarded), loaded only by
`outline.html`. It no-ops if `.outline-tree` is absent.

### 4.1 Storage

Key `libli_outline_open:<slug>`, read from a `data-course-slug` attribute on the
`.outline-tree` nav (added in §2/§3's template work) — never parsed out of the URL.
Value: JSON array of the `data-node` values of currently-open groups. All reads and
writes are wrapped in `try/catch`, matching `unit_nav.js :: store` (a Safari private-mode
`setItem` throws).

On load:

- **Key absent** → do nothing. The server's D1 default stands. This is what makes a
  first visit correct without JS having to reproduce the default.
- **Key present** → apply it *exactly*: open every group whose `data-node` is listed,
  close every group that is not. Not a union with the server default — otherwise a
  student who deliberately collapsed a root would find it re-opened on every visit.
- **Key present but unparseable** → treat as absent (leave the server default) and
  overwrite it on the next write. Never throw.

### 4.2 Persisting — on user gesture, never on `toggle`

**This is a deliberate refinement of the brainstormed sketch, and the reason matters.**
The `toggle` event fires **asynchronously** (the browser queues a task), so the obvious
implementation — set a `programmatic = true` flag, mutate `open`, clear the flag — does
not work: the flag is cleared synchronously, long before the queued `toggle` events run,
so every programmatic open would still be persisted. That is precisely the failure D5
forbids, and it would be invisible until a student cleared a tag filter.

So persistence hangs off the **user gesture**, not off the state change:

- A delegated `click` listener on `.outline-tree` that matches `summary.outline-node__head`
  schedules a `setTimeout(…, 0)` which snapshots the whole tree's open set and writes it.
  The timeout is required, not decoration: `<summary>`'s activation behaviour runs *after*
  click dispatch, so reading `open` inside the click handler reads the pre-click state.
  Keyboard activation (Enter/Space on a focused `summary`) dispatches a real `click`, so
  this path covers the keyboard too, with no extra `keydown` handling.
- The *Expand all / Collapse all* button writes directly after mutating (it is a user
  gesture and mutates synchronously, so it needs no timeout).
- Nothing else ever writes, with the single explicit exception of the deep-link path
  (§4.4).

### 4.3 Header-label sync — on `toggle`, capture phase

A `toggle` listener re-computes the header button's label. It fires for user *and*
programmatic changes, which is exactly right for a label that must always describe the
current state.

`toggle` **does not bubble**, so a normal delegated listener silently never fires — a
failure that looks like "the label just does not update". Register it in the **capture**
phase on the `.outline-tree` nav (`addEventListener("toggle", fn, true)`), which does
observe non-bubbling events on descendants.

### 4.4 Deep links (`#node-N`)

`courses/views.py:841` redirects a container permalink to `outline#node-<pk>`, and
`app.css` carries a `:target` highlight for it. Inside a folded group both are useless.

On load, and on `hashchange`: if `location.hash` matches `^#node-\d+$`, find that `<li>`,
open **every ancestor `<details>`**, then `scrollIntoView({block: "center"})` it. Per D6
this **does** write storage (arriving by permalink is a deliberate navigation), except
while a filter is active (§5), where nothing writes.

If the hash names a node that is not in the DOM (a draft the student cannot see, a
deleted node), do nothing — no throw, no write.

### 4.5 Load order

`outline_tree.js` is included in `outline.html` **immediately before** `tags.js`, both
`defer`. `defer` guarantees execution in document order, so `outline_tree.js` has
registered its `libli:tagfilter` listener before `tags.js` runs its initial
`applyFilter()`. Getting this backwards means a page loaded with `?tags=…` in the URL
misses the very first filter event and shows an empty-looking tree.

### 4.6 *Start fresh* inside the summary

The per-container *Start fresh* link now lives inside a `<summary>`, so activating it
would also toggle the group. Attach a `click` handler that calls `stopPropagation()`
(which prevents the summary's activation behaviour, and also keeps §4.2's delegated
listener from persisting a phantom toggle). Navigation still happens — the link's own
default action is untouched.

## 5. Tag-filter interplay — `tags/static/tags/js/tags.js`

Today `applyFilter()` sets `hidden` on non-matching `li[data-unit]` and bubbles
visibility up to containers. With folding, a *matching* unit inside a folded group is
still invisible, so filtering would appear to find nothing.

- `applyFilter()` gains one line at its end: dispatch
  `document.dispatchEvent(new CustomEvent("libli:tagfilter", {detail: {count: active.size}}))`.
  Nothing else in `tags.js` changes. The event is on `document` so the two files stay
  decoupled, and `tags.js` keeps working unchanged on pages with no outline.
- `outline_tree.js` listens:
  - **`count > 0`** → force open every group that still contains a non-hidden unit
    (`li[data-unit]:not([hidden])`), and set an internal `filterActive` flag.
  - **`count === 0`** → clear the flag and re-apply the stored set (or, if the key is
    absent, the D1 default — recomputed from `item.depth`, which the client reads back
    off a `data-depth` attribute rendered in §2, so this does not require a reload).
- **While `filterActive` is true, no write to `localStorage` ever happens** — not from a
  user gesture, not from the deep-link path. The filtered view is transient by
  definition, and a student who folds something while filtering has not expressed a
  durable preference. This is D5, and it is the one rule that must survive review.

## 6. CSS — `core/static/core/css/app.css`

All outline styling lives in `app.css` (loaded globally by `base.html`). Note:
`courses/static/courses/css/courses.css:1` also carries `.outline-tree ul`, but
`outline.html` does **not** load `courses.css` and no other template uses
`.outline-tree` — that rule is **dead**, is not part of this change, and must not be
"fixed".

New rules:

- `summary.outline-node__head { list-style: none; cursor: pointer; }` plus
  `.outline-node__head::-webkit-details-marker { display: none; }` — the UA triangle
  must go; the chevron replaces it.
- Chevron: shares the rail's shape and rotation
  (`.outline-node__group[open] > .outline-node__head .outline-node__chevron { transform: rotate(90deg); }`),
  with a `prefers-reduced-motion` guard on the transition, consistent with the rest of
  the codebase.
- A hover affordance on the summary, and a `:focus-visible` outline (a `<summary>` is
  natively focusable, and today's `.outline-node__head` `<div>` has no focus style
  because it was never focusable).

Existing rules that now reach *through* the `<details>` and break silently unless
re-pointed — named by selector, not by line number, because line numbers rot:

| Selector today | Problem | Fix |
| --- | --- | --- |
| `.outline-node > ul` | the `<ul>` is now a child of `<details>`, not of the `<li>` | add `.outline-node__group > ul` (keep both — the childless branch and the unit branch still use the old shape) |
| `.outline-node:target > .outline-node__head` | the head is now a grandchild | add `.outline-node:target > .outline-node__group > .outline-node__head` |
| `.outline-tree ul`, `.outline-tree > ul > .outline-node` | the first is a descendant combinator and still matches through `<details>`; the second only matches top-level `<li>`s, which are still direct children of `.outline-tree > ul` | no change; verify, do not edit |

The `:target` change has a **test consequence** — see §8.

## 7. No-JS and accessibility

- With JS off the page is fully usable: the server renders the D1 default and native
  `<details>` folds and unfolds on click and on keyboard. Only persistence, the
  expand-all button (which ships `hidden`), the filter force-open and the deep-link
  force-open are JS-only.
- `<summary>` supplies role, focusability and `aria-expanded` natively; no ARIA is
  hand-rolled. This is the main reason D3 chose `<details>`.
- The rollup counts already on the head (`n/m required`) are what tells a student what is
  inside a folded group. Match whatever the rail does for their announcement rather than
  inventing a second convention: the rail marks its visible ratio `aria-hidden` and puts
  a `blocktrans` sentence beside it.
- Titles inside a folded `<details>` still carry `data-math-title` and are typeset by
  `math.js` exactly as the rail's folded titles already are. No new handling.

## 8. Existing tests that must change

- **`tests/test_outline_anchors.py::test_target_highlight_is_scoped_to_the_row_not_the_li`**
  asserts the literal string `.outline-node:target > .outline-node__head` is present in
  `app.css`. §6 keeps that selector *and* adds the `> .outline-node__group >` variant, so
  the existing assertion still holds — but the test must **also** assert the new variant,
  or the highlight can be lost on every real (nested) container with the test staying
  green. Its sibling assertion `"\n.outline-node:target {" not in css` is unaffected.
- **`tests/test_e2e_tags.py::test_tag_filter_untag_delete_via_ui`** builds units under a
  single depth-0 `part`, so those units sit at depth 1 and stay visible under D1. It
  should pass unchanged — **verify, do not pre-emptively edit**. If it does need a
  change, that is a signal the default is wrong, not that the test is wrong.
- `tests/test_publish_outline.py`, `tests/test_tags_outline.py`,
  `tests/test_courses_rollups.py`, `tests/test_unit_nav_render.py` all touch
  `build_outline` or the outline HTML. `depth` is additive, so they should pass
  unchanged; run them as a regression gate.
- `tests/capture_title_math_screenshots.py` and
  `tests/capture_unit_marker_screenshots.py` screenshot `.outline-tree`. Their output
  will legitimately change shape (folded groups). They are capture scripts, not
  assertions — no edit needed, but expect different images.

## 9. Risks

- **R1 — forced-open leaking into storage.** The highest-impact failure: a student's fold
  state is silently destroyed by using the tag filter, and the damage only becomes
  visible after they clear it. Mitigated structurally by §4.2 (persist on gesture, not on
  state change) and §5 (`filterActive` suppresses all writes). Must have a dedicated
  falsified e2e test.
- **R2 — the async `toggle` trap.** Any implementation that tries to suppress
  persistence with a synchronous flag around a programmatic mutation is wrong and will
  look correct in casual testing. §4.2 exists solely to prevent it.
- **R3 — the non-bubbling `toggle` trap.** A delegated `toggle` listener without
  `capture: true` never fires; the header label silently stops updating (§4.3).
- **R4 — `querySelectorAll` sees straight through a closed `<details>`**, and elements
  inside one keep non-zero client rects. Any test asserting "folded" via
  `querySelector`, `getBoundingClientRect()` or `offsetParent` passes on a broken build.
  Use `checkVisibility()` (Playwright's `to_be_hidden()` uses computed visibility and is
  also acceptable) — see §10.
- **R5 — i18n fuzzy pre-fill.** Two new strings (*Expand all*, *Collapse all*) go through
  `makemessages`, which pre-fills a *wrong* translation marked fuzzy; clearing it is two
  deletions (the `#, fuzzy` line and the bogus `msgstr`). Both `.po` and the regenerated
  `.mo` must land in the branch.
- **R6 — `depth` shipped to consumers that ignore it.** Low: additive keys on a plain
  dict. Guarded by running the rollup and rail render tests.

## 10. Testing

Every test below is **falsified against a targeted mutant before it counts**: introduce
the specific failure it is meant to catch, watch it go RED, then remove the mutant by
hand (never `git checkout`, which discards surrounding work). A test that cannot be shown
RED is not evidence.

**Django render tests** (`tests/test_outline_collapsible.py`, new):

1. A depth-0 container renders `<details … open>`; a depth-1 container renders `<details>`
   without `open`. Mutant: make the template emit `open` unconditionally.
2. `build_outline` sets `depth` correctly on a 3-level tree, and the three existing
   consumers still work. Mutant: off-by-one (`parent_depth` instead of `+1`).
3. A container renders the chevron and keeps its rollup counts and *Start fresh* link
   **inside the `<summary>`**. Mutant: move *Start fresh* out of the summary — it must go
   red, because outside the summary the link vanishes whenever the group is folded.
4. The header button renders both `data-label-expand` and `data-label-collapse` and
   ships `hidden`.

**e2e** (`tests/test_e2e_outline_tree.py`, new; `-m e2e`):

5. First visit to a 3-level course: depth-1 container heads are visible, depth-2 units are
   **not** (`checkVisibility()` / `to_be_hidden()`, per R4). Mutant: render every
   `<details>` `open`.
6. Open a chapter, click into a unit, come back → the chapter is still open. Mutant: skip
   the `setTimeout` write in §4.2.
7. *Expand all* → every unit visible and the label flips to *Collapse all*; reload → still
   expanded. Then *Collapse all* → depth-0 groups fold too.
8. **R1's test.** Fold a chapter, filter by a tag matching a unit inside a *different*,
   folded chapter → that unit becomes visible. Clear the filter → the tree returns to
   exactly the pre-filter fold state. Mutant: persist on `toggle` instead of on gesture —
   the assertion after clearing must go red.
9. A `#node-N` deep link three levels down: the row is visible, scrolled into view, and
   carries the `:target` highlight. Mutant: drop the ancestor-opening loop.
10. JS off (or `outline_tree.js` blocked): depth-0 groups are open, deeper ones folded,
    and clicking a summary still folds/unfolds. Guards the D3 rationale.

**Gates before the PR:** `ruff check --no-cache` and `ruff format --check`, the affected
test set, then the outline/rollups/tags/unit-nav regression files named in §8. Start the
test-DB container before any pytest run. Light and dark screenshots of the outline page,
judged separately.

## 11. Out of scope

- No title search / filter box on the outline.
- No server-side or cross-device persistence.
- No change to the unit rail, the mobile drawer, the builder tree, or the teacher
  per-student tree.
- No change to `courses.css:1`'s dead `.outline-tree ul` rule.
- No change to what the rollup counts mean or how they are computed.
