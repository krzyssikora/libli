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
T7 pins this shape.

These are raw counts including drafts; the student view passes `drafts="hide"`, so a
student sees fewer. The ratio is what matters, and it does not depend on the filtering.

## Decisions

D1–D7 were settled during brainstorming; D8–D9 were added during spec review, with
their reasons recorded. Do not re-litigate.

- **D1 — first view: depth-0 containers `open`, every deeper container folded.**
  Rejected: fold-everything (on a 3-root course the page looks empty), and
  auto-open-the-branch-you-are-working-on (needs a "next unit" computation the outline
  does not have, and is less predictable).
- **D2 — fold state persists per course in `localStorage`**, key
  `libli_outline_open:<course.slug>`. The value is a **partition**, not a single list —
  see §4.1, which explains why an open-only list cannot distinguish "the student closed
  this" from "this container did not exist last visit". Rejected: no persistence (a
  student re-opens their chapter on every return trip) and a server-side preference (a
  model, a migration and a write endpoint for a cosmetic preference).
- **D3 — native `<details>`/`<summary>`**, mirroring the rail. Rejected: a
  button + `hidden` toggle (builder style — needs JS to fold at all, and hand-rolls the
  `aria-expanded` semantics `<details>` gives free), and reusing the rail component
  wholesale (the outline row carries five affordances the rail deliberately lacks).
- **D4 — one *Expand all / Collapse all* toggle** in the outline header, its label naming
  the action it offers. *Collapse all* folds depth 0 too.
- **D5 — a tag filter force-opens groups; that forced state is never persisted.**
  See §5 — this is the single most damaging thing the feature could get wrong.
- **D6 — a `#node-N` deep link opens its ancestors, and that *does* persist.**
- **D7 — the rail, the builder tree and the teacher per-student tree are untouched.**
- **D8 — the *server* opens the ancestors of every filter match** when `?tags=…` is in
  the URL (§2, §5). Added during spec review: the tag filter is not JS-only, so without
  this a no-JS student clicking a filter chip sees an outline of nothing.
- **D9 — *Start fresh* renders as a sibling of the `<details>`, not inside the
  `<summary>`.** Added during spec review, superseding the brainstormed placement. A
  `<summary>` is one button-role control whose accessible name is the concatenation of
  everything inside it, so an inner *Start fresh* both corrupts that name and becomes a
  focusable control nested inside a focusable control — exposed inconsistently by screen
  readers. §2 places it by grid so it still sits on the head row and stays visible when
  the group is folded.

## 1. Server — `depth` on the outline dicts

`courses/rollups.py :: build_outline` gains exactly one **additive** key per node dict:

```
"depth": 0 for a root, parent's depth + 1 otherwise
```

Set it in the existing pre-order fold loop, where the parent dict is guaranteed to
already exist (the loop's own invariant, documented in its docstring). No new query.

Additive is a hard constraint. The verified consumer list — every call site of
`build_outline` plus the one helper that mutates its dicts in place:

| Consumer | Site |
| --- | --- |
| the outline page | `courses/views.py:652` (`course_outline`) |
| the unit rail | `courses/rollups.py:996` (`build_unit_nav`, which stamps the current chain via `_stamp_current_chain` at `:915`) |
| the teacher per-student tree | `courses/rollups.py:535` (`build_student_breakdown`) |
| tag annotation | `tags/services.py:168` (`outline_with_tags`, which sets `tags` and `tag_hidden` on every dict in place) |

A new key is inert for the three that ignore it; renaming or reshaping anything existing
is out of scope. `outline_with_tags` is the consumer this feature actually interacts
with — its `tag_hidden` drives both §2's server-side filter-open and §5's client force-open.

Pruning happens *after* the fold (zero-child containers are dropped under both `hide`
and `keep`). Pruning removes nodes but never re-parents them, so a depth assigned
during the fold stays correct afterwards. No re-numbering pass is needed.

## 2. Markup — `templates/courses/_outline_node.html`

Only the **container-with-children** branch changes. Unit rows are untouched.

```
<li class="outline-node outline-node--{{kind}}" id="node-{{ item.node.pk }}" …>
  <details class="outline-node__group"
           data-node="{{ item.node.pk }}"
           data-depth="{{ item.depth }}"
           {% if item.depth == 0 or active_tag_ids and not item.tag_hidden %}open{% endif %}>
    <summary class="outline-node__head">
      <svg class="icon outline-node__chevron" aria-hidden="true" viewBox="0 0 24 24">
        <path d="M9 6l6 6-6 6"/></svg>
      <span class="outline-node__title" lang="…" data-math-title>{{ item.node.title }}</span>
      {rollup counts}  {additional-done pill}
    </summary>
    <ul>{children}</ul>
  </details>
  <a class="outline-node__reset" href="…">Start fresh</a>
</li>
```

- The `<li>` wrapper, its `outline-node--{{kind}}` modifier and the `hidden` attribute
  are unchanged. The `<details>` goes *inside* it. This keeps `id="node-N"` as the scroll
  target and keeps `tags.js`'s `li[data-unit]` / `li.outline-node` queries working
  untouched.
- **`data-depth` is required**, not decorative: §4.1 and §5 both need to recompute the D1
  default for a container the stored partition has never seen, and this attribute is the
  only carrier of that information on the client.
- **The `open` condition has two arms.** `item.depth == 0` is D1. The second arm is D8:
  when `active_tag_ids` is non-empty, `outline_with_tags` has already set `tag_hidden`
  False on exactly those containers that still hold a visible unit, so opening them is a
  direct read of an existing computed value — no new traversal. `active_tag_ids` is
  already in the outline view's context and both `{% include %}`s are written without
  `only`, so the full context passes down and no new include argument is needed.
  **Verify that**: if either include is ever changed to `only`, this silently renders
  every group closed under a filter — the C7 regression this arm exists to prevent.
- **D9: the *Start fresh* link is a sibling of the `<details>`, not a child of the
  `<summary>`.** It must still appear on the head row and remain visible when the group
  is folded, which §6.2 achieves with a two-column grid on the `<li>` — not absolute
  positioning, which would overlap a wrapped title.
- The chevron is the rail's, reused verbatim (`_unit_tree_node.html`), rotated by CSS on
  `[open]` and explicitly sized (§6.2).
- **The childless-container branch keeps today's plain `<div class="outline-node__head">`
  with the reset link inside it, unchanged.** An empty disclosure is a dead control. This
  mirrors the rail's own childless branch and its reasoning; like the rail's, it is
  unreachable on this path because `build_outline` prunes zero-child containers under
  both `hide` and `keep`. It is kept as a correct fallback, not as a live shape, and no
  test should assert it is reachable.

## 3. Header control — `templates/courses/outline.html`

Two changes in this file, plus the script tags §4.5 requires.

**(a) The nav gains the storage key's source.** `outline.html:14` becomes:

```
<nav class="outline-tree" data-course-slug="{{ course.slug }}" aria-label="…">
```

This attribute has an owner precisely because it is easy to drop: without it §4.1's key
degrades to `libli_outline_open:undefined`, i.e. one fold state shared across every
course, which no test would notice unless one asserts the attribute. T4 does.

**(b) One button in `.outline__head`, before the *My results* link:**

```
<button type="button" class="btn btn--ghost btn--small outline__toggle-all" hidden
        data-outline-toggle-all
        data-label-expand="{% trans 'Expand all' %}"
        data-label-collapse="{% trans 'Collapse all' %}"></button>
```

Rules:

- **The `data-label-*` attributes are a naming convention, not a shared mechanism.** In
  both existing consumers (`unit_nav.js :: syncToggle`, `builder.js:1137`) they drive
  `aria-label` while the visible text is a static glyph. Here they drive the button's
  **`textContent`**, because this button has no glyph and its visible text *is* the label.
  `outline_tree.js` sets `textContent` only; it does **not** set `aria-label` (which would
  duplicate the accessible name) and does **not** set `aria-expanded` (the button controls
  many disclosures, not one, so `aria-expanded` has no coherent referent — each
  `<summary>` carries its own).
- The label names the **action offered**: *Expand all* when at least one group is closed,
  *Collapse all* when every group is open. This is the single normative statement of the
  rule; §4.3 defers to it.
- *Collapse all* folds every group including depth 0.
- The button **ships `hidden` with empty content** and is un-hidden by `outline_tree.js`,
  which computes and writes the correct label at that moment via the shared `syncLabel()`
  of §4.3. There is deliberately **no server-rendered label**: with JS off the button
  would be a dead control (the same reasoning that reveals the drawer FAB in
  `unit_nav.js`), and the template cannot evaluate "is at least one group closed" anyway —
  `depth` alone does not say whether a container has a container child.
- **Zero-groups courses:** if the tree contains no `<details>` at all (a course whose
  units all sit at depth 0 — `demo-course` proves such shapes exist), `outline_tree.js`
  leaves the button `hidden`. "Every group is open" is vacuously true there, so an
  un-hidden button would read *Collapse all* and do nothing. T18.
- Both labels are `{% trans %}`-wrapped and must land in `locale/` (`makemessages`
  regenerates; see the fuzzy-prefill hazard in §9).

## 4. Client — new `courses/static/courses/js/outline_tree.js`

An IIFE in the house style (`"use strict"`, no framework, null-guarded), loaded only by
`outline.html`. It no-ops if `.outline-tree` is absent.

### 4.0 Initialisation order (normative)

The order below is load-bearing; two separate defects (C1, C2 in review round 2) came
from getting it wrong.

1. **Seed `filterActive` from the page, before anything else.** It is true iff the page
   loaded with a filter applied — detected as
   `!!document.querySelector("[data-tags-filter] a.tag-chip.is-active")`. It must **not**
   wait for the first `libli:tagfilter` event, because that event arrives after steps 2–4
   have already run and possibly written.
2. Un-hide the toggle-all button and `syncLabel()` (§3b, §4.3), unless there are zero
   groups.
3. **Apply stored state (§4.1) — but skip this entirely when `filterActive` is true.**
   Under a filter the server's D8 render is already correct, and re-applying the stored
   partition would fold matches shut only for §5 to force them open again a moment later.
4. Run the deep-link handler (§4.4).

### 4.1 Storage

Key `libli_outline_open:<slug>`, with `<slug>` read from the nav's `data-course-slug`
(§3a) — never parsed out of the URL. All reads and writes are wrapped in `try/catch`,
matching `unit_nav.js :: store` (a Safari private-mode `setItem` throws).

**The value is a partition, not an open-list:**

```json
{"v": 1, "open": ["12", "47"], "closed": ["88", "91"]}
```

**Ids are strings, normatively.** `details.dataset.node` yields a string, and
`[12, 47].includes("12")` is `false` — a writer that stores numbers and a reader that
compares against `dataset` produce a silent no-op that still passes any test seeding
storage in the writer's own representation. The client therefore normalises with
`String(...)` on **both** read and write, so a hand-seeded numeric array still applies.
T15 seeds numbers deliberately to prove the normalisation exists.

Every `<details>` present at write time appears in exactly one array. This shape is
load-bearing. With an open-only list, "not listed" is ambiguous between *the student
closed this* and *this container did not exist last visit*, and the two need opposite
treatments:

- a group in `open` → open it;
- a group in `closed` → close it, **even at depth 0** (a student who deliberately
  collapses a root must find it collapsed next visit);
- a group in **neither** → it is new since the last write; fall back to its own
  `data-depth` default (open iff depth 0). A newly authored top-level part therefore
  behaves like a first visit for that node instead of silently arriving folded.

**Two callers, two different rules for a missing key** — they are *not* one shared
routine, and conflating them was review round 2's C1:

| Caller | Key absent |
| --- | --- |
| **load-time apply** (§4.0 step 3) | do nothing at all; leave the server's D1/D8 render untouched |
| **filter-clear restore** (§5) | treat as an **empty partition** and drive every group from `data-depth`, so the force-opened tree returns to the D1 default |

If the restore path inherited "do nothing", a student on a first visit who filters and
then clears the filter would be left with a fully force-opened tree — the exact state D5
forbids. T11 pins it, and does so without writing storage first.

Other load-time rules:

- **Key present but unparseable, or `v` unrecognised** → treat as absent (leave the
  server render) and overwrite on the next write. Never throw.
- The applied state is never a union with the server default; T15 pins that with a closed
  depth-0 root, the only case that discriminates the two implementations.

### 4.2 Persisting — on user gesture, never on `toggle`

**This is a deliberate refinement of the brainstormed sketch, and the reason matters.**
The `toggle` event fires **asynchronously** (the browser queues a task), so the obvious
implementation — set a `programmatic = true` flag, mutate `open`, clear the flag — does
not work: the flag is cleared synchronously, long before the queued `toggle` events run,
so every programmatic open would still be persisted. That is precisely the failure D5
forbids, and it would be invisible until a student cleared a tag filter.

So persistence hangs off the **user gesture**, not off the state change:

- A delegated `click` listener on `.outline-tree` resolves the summary with
  **`e.target.closest("summary.outline-node__head")`** — not `e.target.matches(…)`. The
  summary contains an `<svg>` chevron, the title `<span>` and the rollup `<span>`s, so
  `e.target` is almost never the summary itself; a `matches()` implementation fires only
  on the bare gaps between children and looks like it works. `closest()` also resolves
  correctly from inside the SVG. A click on the *Start fresh* link (a sibling of the
  `<details>` under D9) yields `null` here and is ignored with no special-casing.
- On a match, schedule `setTimeout(…, 0)`, and inside it snapshot the whole tree into the
  §4.1 partition and write it. The timeout is required, not decoration: `<summary>`'s
  activation behaviour runs *after* click dispatch, so reading `open` inside the click
  handler reads the pre-click state. Keyboard activation (Enter/Space on a focused
  `summary`) dispatches a real `click`, so this path covers the keyboard too, with no
  extra `keydown` handling.
- The *Expand all / Collapse all* button writes directly after mutating (it is a user
  gesture and mutates synchronously, so it needs no timeout).

**Exceptions to "these two are the only writers", stated in full:**

1. The deep-link path (§4.4) writes.
2. **While `filterActive` is true, *nothing* writes** — not the summary gesture, not the
   toggle-all button, not the deep-link path. This suppression overrides both writers
   above; §5 is normative and this bullet exists so that implementing §4.2 in isolation
   cannot ship the D5 bug. Note that `filterActive` is seeded at init (§4.0 step 1), so it
   is already true for a page loaded with `?tags=…` — without that seeding, a
   `?tags=N#node-M` URL writes the server's force-opened tree straight into storage.

### 4.3 Header-label sync

One shared `syncLabel()` computes **which action the button offers** (per §3's rule, which
is normative — the label is not a description of current state, or it would read
*Collapse all* whenever anything was collapsed). It is called from exactly two places:

- once at init, when the button is un-hidden (§4.0 step 2) — there is no `toggle` event at
  load, so the initial label cannot come from the listener;
- from a `toggle` listener registered in the **capture** phase on the `.outline-tree` nav
  (`addEventListener("toggle", fn, true)`).

`toggle` **does not bubble**, so a normal delegated listener silently never fires — a
failure that looks like "the label just does not update". Capture-phase registration is
what observes non-bubbling events on descendants.

The prohibition is specific: the toggle-all **click handler must not set the label
itself**. If it does, T9 passes with no `toggle` listener at all and R3 goes uncovered —
which is why T14 exists.

### 4.4 Deep links (`#node-N`)

`courses/views.py:841` redirects a container permalink to `outline#node-<pk>`, and
`app.css` carries a `:target` highlight for it. Inside a folded group both are useless.

On load (§4.0 step 4), and on `hashchange`: if `location.hash` matches `^#node-\d+$`,
find that `<li>`, open **every ancestor `<details>`**, then
`scrollIntoView({block: "center"})` it. Per D6 this **does** write storage — except under
§4.2's exception 2, which covers the `?tags=…#node-…` case.

Two ordering hazards:

- **The `count === 0` event must not undo this.** `tags.js :: setupFilter` ends with an
  unconditional `applyFilter(active)`. On an **unfiltered** load that renders a filter
  bar, that dispatches `libli:tagfilter` with `count: 0` right after this
  ancestor-opening has run. (On a `?tags=N` load it dispatches `count: N > 0` instead,
  because `setupFilter` seeds `active` from the chips carrying `is-active` — that is the
  path that sets `filterActive` via the event, though §4.0 has already seeded it.) §5's
  `count === 0` branch is therefore a **no-op unless `filterActive` is currently true**.
  Without that guard the handler re-applies stored state — or the D1 default when the key
  is absent, or when the §4.1 write silently failed in Safari private mode — and slams the
  just-opened ancestors shut.
- **KaTeX resizes rows after the scroll.** `outline.html` loads KaTeX when `has_math`, and
  titles above the target are typeset after this runs, changing their heights. The row can
  therefore drift off-centre. This is accepted rather than sequenced (waiting on KaTeX
  would couple this file to `math.js`'s lifecycle); T13 asserts *within the viewport*, not
  centred, for exactly this reason.

If the hash names a node that is not in the DOM (a draft the student cannot see, a
deleted node), do nothing — no throw, no write.

### 4.5 Load order

`outline_tree.js` is included in `outline.html` **immediately before** `tags.js`, both
`defer`. `defer` guarantees execution in document order, so `outline_tree.js` has
registered its `libli:tagfilter` listener before `tags.js` runs its initial
`applyFilter()`. Getting this backwards means the initial filter event is missed
entirely — including the `count: 0` one that §4.4 depends on being observable.

## 5. Tag-filter interplay

The tag filter has **two** paths, and the spec must serve both.

**Server path (no JS, or a fresh load with `?tags=…`).** `_tags_filter_bar.html` renders
real `<a href="?tags=N">` chips; `courses/views.py :: course_outline` reads
`request.GET.getlist("tags")`; `tags/services.py :: outline_with_tags` sets `tag_hidden`,
which `_outline_node.html` renders as the `hidden` attribute. This works today with JS
off. D8 / §2's second `open` arm is what keeps it working: containers holding a visible
match render `open`. Without it, this change is a **regression on a currently-working
no-JS path**, not merely a missing enhancement.

**Client path (chip clicks after load).** `tags.js :: applyFilter` sets `hidden` on
non-matching `li[data-unit]` and bubbles visibility up, with no reload — so the server's
`open` render cannot help.

- `applyFilter()` gains one line at its end: dispatch
  `document.dispatchEvent(new CustomEvent("libli:tagfilter", {detail: {count: active.size}}))`.
  Nothing else in `tags.js` changes. The event is on `document` so the two files stay
  decoupled, and `tags.js` keeps working unchanged on pages with no outline.
- `outline_tree.js` listens:
  - **`count > 0`** → set `filterActive`, then force open every group that still contains
    a non-hidden unit (`li[data-unit]:not([hidden])`).
  - **`count === 0`** → **no-op unless `filterActive` is currently true** (see §4.4's first
    hazard). On a real filtered→unfiltered transition: clear the flag, re-enable the
    toggle-all button, and drive every group from the §4.1 partition — treating an absent
    key as an empty partition, so every group falls back to its `data-depth` default.
- **While `filterActive` is true, no write to `localStorage` ever happens** — this is
  §4.2's exception 2, restated here because this is the normative site. The filtered view
  is transient by definition, and a student who folds something while filtering has not
  expressed a durable preference. This is D5, and it is the one rule that must survive
  review.
- **The toggle-all button while filtered:** *Collapse all* would hide every match and
  reproduce the exact failure this section exists to prevent. So while `filterActive` is
  true the button is **disabled** (`disabled` attribute, so it also leaves the tab order
  and is announced as unavailable) and re-enabled when the filter clears. Chosen over
  "re-run the force-open after collapsing", which would make the button visibly do
  nothing — a worse affordance than a disabled one.

## 6. CSS — `core/static/core/css/app.css`

All outline styling lives in `app.css` (loaded globally by `base.html`). Note:
`courses/static/courses/css/courses.css:1` also carries `.outline-tree ul`, but
`outline.html` does **not** load `courses.css` and no other template uses
`.outline-tree` — that rule is **dead**, is not part of this change, and must not be
"fixed".

### 6.1 Selectors that break silently unless re-pointed

Named by selector, not line number, because line numbers rot. The rail hit every one of
these and fixed them by **doubling** the selector (plain-head branch + `> group >`
branch); `courses.css:707-710` is the precedent, with a comment explaining why dropping
to a descendant combinator instead would destroy the level distinction.

| Selector today | Consequence if left | Fix |
| --- | --- | --- |
| `.outline-node--part > .outline-node__head .outline-node__title` | part titles lose `font-size: 1.35rem` | add the `> .outline-node__group >` twin |
| `.outline-node--chapter > .outline-node__head .outline-node__title` | chapter titles lose `font-size: 1.1rem` | add the twin |
| `.outline-node--section > .outline-node__head .outline-node__title` | section micro-type (`.75rem`, 700, tracking, uppercase, `--text-tertiary`) is lost entirely | add the twin |
| `.outline-node:target > .outline-node__head` | the permalink highlight never lands on a real (nested) container | add `.outline-node:target > .outline-node__group > .outline-node__head` |
| `.outline-node > ul` | the nested-level hairline guide (`margin-top`, `padding-left`, `border-left`) stops matching | re-point to `.outline-node__group > ul` |

**The three type-scale rules and the guide rule are the highest-risk items in this
table.** Both produce a visually flat but structurally correct tree — no error, no failing
test by default, just a worse page. T17 pins both.

On `.outline-node > ul`: it is re-pointed, not doubled. Neither surviving branch renders a
`<ul>` — the childless-container branch is childless by definition and the unit branch's
`<li>` has no nested list — so keeping the old form would create exactly the kind of dead
outline rule this spec elsewhere insists on naming.

### 6.2 New rules

- **The `<li>` becomes a two-column grid** so D9's *Start fresh* sibling still sits on the
  head row: `.outline-node--part, .outline-node--chapter, .outline-node--section` (the
  container branches) get `display: grid; grid-template-columns: 1fr auto;` with the
  `<details>` in column 1 and `.outline-node__reset { grid-column: 2; grid-row: 1; align-self: start; }`.
  Grid, not `position: absolute` — an absolutely positioned link overlaps a title that
  wraps to two lines, and outline titles do wrap.
- `summary.outline-node__head { cursor: pointer; list-style: none; }` plus
  `summary.outline-node__head::-webkit-details-marker { display: none; }`, mirroring
  `courses.css:716-717`. **Note for test authors:** `.outline-node__head` already carries
  `display: flex`, which removes the `display: list-item` box the marker depends on, so
  neither declaration is independently falsifiable. Do not write a test against them; they
  are defence against a future `display` change, exactly as in the rail.
- Chevron, mirroring `courses.css:746-752`:
  `.outline-node__head > .outline-node__chevron { width: .8rem; height: .8rem; align-self: center; transition: transform 120ms ease; }`
  and `.outline-node__group[open] > .outline-node__head > .outline-node__chevron { transform: rotate(90deg); }`
  — the **full direct-child chain**, as the rail's comment at `courses.css:749-751`
  requires: with a descendant combinator, a closed section inside an open chapter is
  painted open.
  `@media (prefers-reduced-motion: reduce) { .outline-node__chevron { transition: none; } }`.
  Do **not** redeclare `flex: none` — `.icon` already sets it (`app.css:109`), so it is
  inert here and carries no possible mutant.
- **The explicit chevron size is required.** The type scale lives on
  `.outline-node__title`, not on `.outline-node__head`, so the head's font-size is `1rem`
  at every level and `.icon`'s `1em` would render an identical 16px chevron next to a
  `.75rem` uppercase section title — visibly oversized. A constant `.8rem` chevron across
  levels is deliberate (the disclosure is chrome, and the rail makes the same choice);
  per-level scaling was considered and rejected. Its optical fit is a named item in the
  screenshot gate.
- **`align-self: center`** because `.outline-node__head` is `align-items: baseline` (the
  rail's head is `flex-start`, so the chevron cannot simply be reused unaltered). A
  replaced element's baseline is its bottom margin edge, so a baseline-aligned chevron
  sits with its bottom on the text baseline — visibly high.
- Hover and focus: `summary.outline-node__head:hover { background: var(--surface-sunken); }`
  — the same token as `.outline-unit:hover`, so a group head and a unit row read
  identically on this page. **Accepted collision:** the `:target` rule sets
  `background: var(--surface-sunken)` at (0,3,0) and beats this (0,2,1) rule, so a
  permalink-targeted row keeps its target background instead of a hover change. Since both
  resolve to the same token the visible result is identical, so this is accepted rather
  than fought. (The rail's precedent comment at `courses.css:719-723` is about `color`, and
  the outline's type-scale rules target the *title span*, not the head, so neither competes
  here — do not carry that reasoning across.)
  `summary.outline-node__head:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }`
  — `outline` is unset by every competing rule. A `<summary>` is natively focusable;
  today's `.outline-node__head` `<div>` never was, so this focus style is new behaviour,
  not a port.

## 7. No-JS and accessibility

- **With JS off the page remains fully usable, including the tag filter** — but only
  because of D8/§2. Native `<details>` folds and unfolds on click and keyboard, the server
  renders the D1 default, and a `?tags=…` load opens the ancestors of every match. JS-only
  behaviours are: persistence, the expand-all button (which stays `hidden`), the
  client-side chip filter's force-open, and the deep-link force-open.
- `<summary>` supplies role, focusability and `aria-expanded` natively; no ARIA is
  hand-rolled for the disclosures. That is the main reason D3 chose `<details>`.
- **The summary's accessible name is deliberate.** A `<summary>` is one button-role control
  whose name is the concatenation of its contents, so under D9 it reads as *"Chapter 4 —
  Triangles, 3/5 required"* — the title plus its rollup, which is a good name for a
  disclosure. D9 exists because the pre-review markup also folded *Start fresh* into that
  name and nested a focusable link inside a focusable control. No `aria-hidden` on the
  rollup spans and no separate visually-hidden sentence: unlike the rail's bare `n/m`
  ratio, the outline's rollup already reads as text with a visible `{% trans "required" %}`.
  This keeps R5's new-string count at exactly two. T6 asserts the computed name.
- Titles inside a folded `<details>` still carry `data-math-title` and are typeset by
  `math.js` exactly as the rail's folded titles already are. No new handling.

## 8. Existing tests and citations that must change

- **`tests/test_e2e_link_dialog.py`** (the internal-content-link round trip) locates
  `#node-{chapter.pk} > .outline-node__head` and reads its `backgroundColor` to assert the
  `:target` highlight. That chapter has a child unit, so it becomes the `<details>` branch
  and the head is a **grandchild**: the locator resolves to nothing and the test errors.
  Re-point it to `#node-N > .outline-node__group > .outline-node__head`, preserving the
  direct-child scoping the test's own comment says is the point — do not loosen it to a
  descendant selector.
- **`tests/test_outline_anchors.py::test_target_highlight_is_scoped_to_the_row_not_the_li`**
  asserts the literal `.outline-node:target > .outline-node__head` in `app.css`. §6.1 keeps
  that selector *and* adds the `> .outline-node__group >` twin, so the existing assertion
  still holds — the test must **also** assert the twin, or the highlight can be lost on
  every real container with the test staying green. Record in the test why: after this
  change the *old* selector is inert cover for the unreachable childless branch, and the
  **new** twin is the live one, so the added assertion is the load-bearing half. The
  sibling assertion `"\n.outline-node:target {" not in css` is unaffected.
- **Line-number citations rot.** Inserting rules into `app.css`'s `.outline-*` block shifts
  every line below it, and `tests/test_outline_anchors.py` carries a comment citing
  "app.css:488" to explain a load-bearing anchoring trick. No per-task review sees a
  comment in an otherwise-untouched file. Re-check and update — or convert to
  selector-name citations — every `app.css:<n>` reference in `tests/` and in `app.css`'s
  own comments that the insertion displaces.
- **`tests/test_e2e_tags.py::test_tag_filter_untag_delete_via_ui`** builds units under a
  single depth-0 `part`, so they sit at depth 1 and stay visible under D1. It should pass
  unchanged — **verify, do not pre-emptively edit**. If it needs a change, that is a signal
  the default is wrong, not that the test is wrong.
- `tests/test_publish_outline.py`, `tests/test_tags_outline.py`,
  `tests/test_courses_rollups.py`, `tests/test_unit_nav_render.py` all touch
  `build_outline` or the outline HTML. `depth` is additive, so they should pass unchanged;
  run them as a regression gate.
- `tests/capture_title_math_screenshots.py` and `tests/capture_unit_marker_screenshots.py`
  screenshot `.outline-tree`. Their output legitimately changes shape (folded groups).
  They are capture scripts, not assertions — no edit needed, but expect different images.

## 9. Risks

- **R1 — forced-open leaking into storage.** The highest-impact failure: a student's fold
  state is silently destroyed by using the tag filter, and the damage only becomes visible
  after they clear it. Mitigated structurally by §4.2 (persist on gesture, not on state
  change), §4.0 step 1 (seed `filterActive` before any write) and §5. Falsified by T10 and
  T12.
- **R2 — the async `toggle` trap.** Any implementation that suppresses persistence with a
  synchronous flag around a programmatic mutation is wrong and looks correct in casual
  testing. §4.2 exists solely to prevent it; T8 carries the timing mutant.
- **R3 — the non-bubbling `toggle` trap.** A delegated `toggle` listener without
  `capture: true` never fires; the header label silently stops updating (§4.3). T14.
- **R4 — `querySelectorAll` sees straight through a closed `<details>`**, and elements
  inside one keep non-zero client rects. Any test asserting "folded" via `querySelector`,
  `getBoundingClientRect()` or `offsetParent` passes on a broken build. Use
  `checkVisibility()`; Playwright's `to_be_hidden()` uses computed visibility and is also
  acceptable.
- **R5 — i18n fuzzy pre-fill.** Exactly two new strings (*Expand all*, *Collapse all*) go
  through `makemessages`, which pre-fills a *wrong* translation marked fuzzy; clearing it
  is two deletions (the `#, fuzzy` line and the bogus `msgstr`). Both `.po` and the
  regenerated `.mo` must land in the branch.
- **R6 — silent CSS regressions (§6.1).** The type-scale flattening and the lost nested
  guide rule both leave a correct DOM and a worse page, with nothing red. T17.
- **R7 — `depth` shipped to consumers that ignore it.** Low: additive keys on a plain
  dict. Guarded by exercising all four consumers in T2.

## 10. Testing

Tests are labelled T1–T19 and referenced by label throughout this spec — deliberately, so
that inserting a test never silently re-points a cross-reference.

Every test is **falsified against a targeted mutant before it counts**: introduce the
specific failure it is meant to catch, watch it go RED, then remove the mutant by hand
(never `git checkout`, which discards surrounding work). A test that cannot be shown RED
is not evidence.

**Django render tests** (`tests/test_outline_collapsible.py`, new):

- **T1** — a depth-0 container renders `<details … open>`; a depth-1 container renders
  `<details>` **without** `open`; both carry `data-node` and `data-depth`. Mutant: emit
  `open` unconditionally.
- **T2** — `build_outline` sets `depth` correctly on a 3-level tree, and all four §1
  consumers still work (outline view, `build_unit_nav`, `build_student_breakdown`,
  `outline_with_tags`). Mutant: off-by-one (`parent_depth` instead of `+1`).
- **T3** — the `<summary>` contains the chevron, title and rollup counts, and the
  *Start fresh* link is a **sibling of the `<details>`**, not inside the summary (D9).
  Mutant: move the link back inside the summary. This is a *structural* assertion and
  reddens as one; the visibility and accessible-name consequences are the motivation for
  the rule, not the mechanism this tier observes.
- **T4** — the header button ships `hidden`, empty, with both `data-label-*` attributes;
  and the nav carries `data-course-slug="{{ course.slug }}"`. Mutant: drop the nav
  attribute.
- **T5** — D8. Fixture: two depth-0 roots, each with a depth-1 chapter, with the only
  tag match under one of them at depth 2. `GET ?tags=N` renders that match's ancestor
  chain `open`, and the **depth-1** chapter with no match does **not** render `open`. The
  negative assertion must target depth ≥ 1: depth-0 containers render `open`
  unconditionally under D1's arm, so a depth-0 negative would fail on a correct build.
  Mutant: drop the second `open` arm. This is the no-JS regression guard and must live at
  the render tier, not e2e.
- **T6** — the `<summary>`'s computed accessible name is the title plus its rollup text,
  and does **not** contain "Start fresh" (§7). Mutant: the T3 mutant.

**e2e** (`tests/test_e2e_outline_tree.py`, new; `-m e2e`):

- **T7** — first visit to a 3-level course: depth-1 container heads visible, depth-2 units
  not (`checkVisibility()` / `to_be_hidden()`, per R4), **and** the depth-1 `<details>` has
  no `open` attribute while the depth-0 one does. The attribute half is what actually pins
  D1; a visibility-only pair also passes under a stray `display: none`. Same test covers
  the mixed shape the Purpose section calls out: a course with a depth-0 **unit** beside a
  depth-0 container — the unit row is visible and has no disclosure, the container renders
  `<details open>`. Mutant: render every `<details>` open.
- **T8** — open a chapter by clicking the **title span** (not summary padding — that click
  target is what falsifies an `e.target.matches()` implementation), click into a unit, come
  back → the chapter is still open. Mutant: take the snapshot **synchronously inside the
  click handler** instead of inside `setTimeout(…, 0)`; it reads the pre-click state, so
  the newly-opened chapter is absent from the stored `open` array.
- **T9** — *Expand all* → every unit visible, label flips to *Collapse all*; reload → still
  expanded; *Collapse all* → depth-0 groups fold too.
- **T10** — R1. Fold chapter A, filter by a tag matching a unit inside a *different*,
  folded chapter B → that unit becomes visible, and the toggle-all button is `disabled`.
  Clear the filter → the tree returns to exactly the pre-filter fold state. **Mutant must
  be two-part**: persist inside a `toggle` handler *and* remove the `filterActive` write
  guard. Moving persistence onto `toggle` alone does **not** redden this test — the
  suppression still blocks writes during the filtered phase, and the post-clear
  programmatic toggles merely re-write the state just restored.
- **T11** — C1's case. Never write storage before filtering (no stored key at all), apply
  a filter, then clear it → the tree returns to the D1/D8 server default rather than
  staying force-opened. Mutant: make the filter-clear restore a no-op when the key is
  absent (i.e. share the load-path rule).
- **T12** — C2's case. Load `?tags=N#node-M` and assert `localStorage` is untouched.
  Mutant: seed `filterActive` only from the `libli:tagfilter` event instead of at init
  (§4.0 step 1) — the deep-link write then persists the server's force-opened tree.
- **T13** — `#node-N` deep link three levels down: the row is **within the viewport** (not
  "centred" — see §4.4's KaTeX hazard) and carries the `:target` highlight. Mutant: drop
  the ancestor-opening loop. Second case, same file: **the fixture must create a tag on a
  unit in the course** so `filter_chips` is non-empty and `_tags_filter_bar.html` actually
  renders — `tags.js` runs `setupFilter` only `if (bar)`, so without the bar no
  `libli:tagfilter` event fires and the case is vacuous. With the bar present, stub
  `localStorage.setItem` to throw and store no key: the deep-linked row must still be
  visible. Mutant: remove the `count === 0` no-op guard.
- **T14** — R3. With every group open (label *Collapse all*), click one summary closed and
  assert the label becomes *Expand all*. Mutant: register the `toggle` listener without
  `capture: true`. T9 alone cannot catch this — an implementation that updates the label
  inline in the button handler passes T9 with no listener at all.
- **T15** — §4.1's partition. (a) Collapse a depth-0 root, reload, assert it is still
  closed; mutant: union the stored set with the server default. (b) Seed a partition that
  omits a depth-0 group entirely (a container authored since the last visit), reload,
  assert it renders **open** per `data-depth`; seed the ids as **numbers**, not strings, so
  the case also falsifies a missing `String()` normalisation. (c) Seed `"not json"`,
  reload, assert the server default renders and nothing throws.
- **T16** — click a container's *Start fresh*, land on the reset-confirm page, navigate
  back, and assert the stored partition is byte-identical to before; and that the link is
  keyboard-reachable and activatable. Mutant: the T3 mutant (link inside the summary).
- **T17** — R6, both halves. A nested (depth-1) chapter's title computes `font-size: 1.1rem`
  and a nested section's computes `.75rem`/uppercase; **and** a nested `<ul>` computes a
  non-zero `border-left-width` with the expected `padding-left`. Mutants: omit the
  `> .outline-node__group >` type-scale twins; leave `.outline-node > ul` un-re-pointed.
  Both are pure-CSS regressions no HTML assertion can see.
- **T18** — zero-groups course (all units at depth 0): the toggle-all button stays
  `hidden`.
- **T19** — JS off: depth-0 groups open, deeper folded, clicking a summary still
  folds/unfolds, and a `?tags=N` load still shows its match (D3 + D8 together). The outline
  view is `@login_required`, so a bare `new_context(java_script_enabled=False)` lands on
  the login page and the assertions pass or fail for the wrong reason. Follow the existing
  precedent at `tests/test_e2e_before_after.py:874`: log in in a JS-enabled context,
  capture `storage_state`, then open the no-JS context with it.

**Gates before the PR:** `ruff check --no-cache` and `ruff format --check`, the affected
test set, then the outline/rollups/tags/unit-nav regression files named in §8. Start the
test-DB container before any pytest run. Light and dark screenshots of the outline page,
judged separately, and specifically checking the chevron's optical fit against both the
1.35rem part title and the .75rem section title (§6.2).

## 11. Out of scope

- No title search / filter box on the outline.
- No server-side or cross-device persistence.
- No change to the unit rail, the mobile drawer, the builder tree, or the teacher
  per-student tree.
- No change to `courses.css:1`'s dead `.outline-tree ul` rule.
- No change to what the rollup counts mean or how they are computed. (§7 does settle how
  they are *announced* — as part of the summary's accessible name — which is a consequence
  of D3, not a change to the rollup itself.)
