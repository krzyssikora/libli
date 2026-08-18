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

Settled during brainstorming (D1–D7). Do not re-litigate.

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
  this a no-JS student clicking a filter chip sees an outline of nothing. It also removes
  a fold-then-unfold flash on the JS path.

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
<details class="outline-node__group"
         data-node="{{ item.node.pk }}"
         data-depth="{{ item.depth }}"
         {% if item.depth == 0 or active_tag_ids and not item.tag_hidden %}open{% endif %}>
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
- **`data-depth` is required**, not decorative: §4.1 and §5 both need to recompute the D1
  default for a container the stored partition has never seen, and this attribute is the
  only carrier of that information on the client.
- **The `open` condition has two arms.** `item.depth == 0` is D1. The second arm is D8:
  when `active_tag_ids` is non-empty, `outline_with_tags` has already set `tag_hidden`
  False on exactly those containers that still hold a visible unit, so opening them is a
  direct read of an existing computed value — no new traversal. `active_tag_ids` is
  already in the outline view's context and `{% include %}` (used without `only`) passes
  the full context down, so no new include argument is needed. **Verify that**: if the
  include is ever changed to `only`, this silently renders every group closed under a
  filter, which is exactly the C7 regression this arm exists to prevent.
- The chevron is the rail's, reused verbatim (`_unit_tree_node.html`), rotated by CSS on
  `[open]`.
- **The childless-container branch keeps today's plain `<div class="outline-node__head">`.**
  An empty disclosure is a dead control. This mirrors the rail's own childless branch and
  its reasoning; like the rail's, it is unreachable on this path because `build_outline`
  prunes zero-child containers under both `hide` and `keep`. It is kept as a correct
  fallback, not as a live shape, and no test should assert it is reachable.
- *Start fresh* stays inside the `<summary>` (it must remain visible when the group is
  folded, and only the summary is). §4.6 covers the click interaction and §7 records the
  accessibility cost this incurs.

## 3. Header control — `templates/courses/outline.html`

Two changes in this file, plus the script tags §4.5 requires.

**(a) The nav gains the storage key's source.** `outline.html:14` becomes:

```
<nav class="outline-tree" data-course-slug="{{ course.slug }}" aria-label="…">
```

This attribute has an owner precisely because it is easy to drop: without it §4.1's key
degrades to `libli_outline_open:undefined`, i.e. one fold state shared across every
course, which no test would notice unless one asserts the attribute. §10 test 4 does.

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
  which computes and writes the correct label at that moment. There is deliberately **no
  server-rendered label**: with JS off the button would be a dead control (the same
  reasoning that reveals the drawer FAB in `unit_nav.js`), and the template cannot
  evaluate "is at least one group closed" anyway — `depth` alone does not say whether a
  container has a container child.
- **Zero-groups courses:** if the tree contains no `<details>` at all (a course whose
  units all sit at depth 0 — `demo-course` proves such shapes exist), `outline_tree.js`
  leaves the button `hidden`. "Every group is open" is vacuously true there, so an
  un-hidden button would read *Collapse all* and do nothing.
- Both labels are `{% trans %}`-wrapped and must land in `locale/` (`makemessages`
  regenerates; see the fuzzy-prefill hazard in §9).

## 4. Client — new `courses/static/courses/js/outline_tree.js`

An IIFE in the house style (`"use strict"`, no framework, null-guarded), loaded only by
`outline.html`. It no-ops if `.outline-tree` is absent.

### 4.1 Storage

Key `libli_outline_open:<slug>`, with `<slug>` read from the nav's `data-course-slug`
(§3a) — never parsed out of the URL. All reads and writes are wrapped in `try/catch`,
matching `unit_nav.js :: store` (a Safari private-mode `setItem` throws).

**The value is a partition, not an open-list:**

```json
{"v": 1, "open": [12, 47], "closed": [88, 91]}
```

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

Other load-time rules:

- **Key absent** → do nothing at all. The server's D1/D8 render stands. This is what makes
  a first visit correct without JS having to reproduce the default.
- **Key present but unparseable, or `v` unrecognised** → treat as absent (leave the
  server render) and overwrite on the next write. Never throw.
- The applied state is never a union with the server default; §10 test 12 pins that with a
  closed depth-0 root, which is the only case that discriminates the two implementations.

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
  summary contains an `<svg>` chevron, the title `<span>`, the rollup `<span>`s and the
  *Start fresh* `<a>`, so `e.target` is almost never the summary itself; a `matches()`
  implementation fires only on the bare gaps between children and looks like it works.
  `closest()` also resolves correctly from inside the SVG.
- If the click originated inside an `<a>` (`e.target.closest("a")`), return early —
  see §4.6.
- Otherwise schedule `setTimeout(…, 0)`, and inside it snapshot the whole tree into the
  §4.1 partition and write it. The timeout is required, not decoration: `<summary>`'s
  activation behaviour runs *after* click dispatch, so reading `open` inside the click
  handler reads the pre-click state. Keyboard activation (Enter/Space on a focused
  `summary`) dispatches a real `click`, so this path covers the keyboard too, with no
  extra `keydown` handling.
- The *Expand all / Collapse all* button writes directly after mutating (it is a user
  gesture and mutates synchronously, so it needs no timeout).

**Exceptions to "these two are the only writers", stated in full:**

1. The deep-link path (§4.4) writes.
2. **While `filterActive` is true (§5), *nothing* writes — not the summary gesture, not
   the toggle-all button, not the deep-link path.** This suppression overrides both
   writers above; §5 is normative and this bullet exists so that implementing §4.2 in
   isolation cannot ship the D5 bug.

### 4.3 Header-label sync — on `toggle`, capture phase

A `toggle` listener re-computes **which action the button offers** (per §3's rule, which
is normative — the label is not a description of current state, or it would read
*Collapse all* whenever anything was collapsed). It fires for user *and* programmatic
changes, which is exactly right for a button whose offer must always be current.

`toggle` **does not bubble**, so a normal delegated listener silently never fires — a
failure that looks like "the label just does not update". Register it in the **capture**
phase on the `.outline-tree` nav (`addEventListener("toggle", fn, true)`), which does
observe non-bubbling events on descendants.

The label must be driven from this listener, not recomputed inline inside the toggle-all
handler; §10 test 11 exists because an inline-only implementation passes the toggle-all
test with no `toggle` listener at all.

### 4.4 Deep links (`#node-N`)

`courses/views.py:841` redirects a container permalink to `outline#node-<pk>`, and
`app.css` carries a `:target` highlight for it. Inside a folded group both are useless.

On load, and on `hashchange`: if `location.hash` matches `^#node-\d+$`, find that `<li>`,
open **every ancestor `<details>`**, then `scrollIntoView({block: "center"})` it. Per D6
this **does** write storage (arriving by permalink is a deliberate navigation), except
under the §4.2 exception 2 suppression.

Two ordering hazards:

- **The `count === 0` event must not undo this.** `tags.js :: setupFilter` ends with an
  unconditional `applyFilter(active)`, so on *every* outline load that renders a filter
  bar, a `libli:tagfilter` event with `count: 0` arrives right after this ancestor-opening
  has run. §5's `count === 0` branch is therefore a **no-op unless `filterActive` was
  already true**. Without that guard the handler re-applies stored state (or the D1
  default when the key is absent, or when the §4.1 write silently failed in Safari private
  mode) and slams the just-opened ancestors shut.
- **KaTeX resizes rows after the scroll.** `outline.html` loads KaTeX when `has_math`, and
  titles above the target are typeset after this runs, changing their heights. The row can
  therefore drift off-centre. This is accepted rather than sequenced (waiting on KaTeX
  would couple this file to `math.js`'s lifecycle); §10 test 9 asserts *within the
  viewport*, not centred, for exactly this reason.

If the hash names a node that is not in the DOM (a draft the student cannot see, a
deleted node), do nothing — no throw, no write.

### 4.5 Load order

`outline_tree.js` is included in `outline.html` **immediately before** `tags.js`, both
`defer`. `defer` guarantees execution in document order, so `outline_tree.js` has
registered its `libli:tagfilter` listener before `tags.js` runs its initial
`applyFilter()`. Getting this backwards means the initial filter event is missed
entirely — including the `count: 0` one that §4.4 depends on being observable.

### 4.6 *Start fresh* inside the summary

The per-container *Start fresh* link now lives inside a `<summary>`. Two separate
questions, and only one of them has a portable answer:

- **Must not persist a phantom toggle.** Guaranteed by §4.2's `e.target.closest("a")`
  early return. This is the part that matters, and it does not depend on browser
  behaviour.
- **Whether the group also toggles** on the way out is left to the browser. Suppressing a
  default action portably needs `preventDefault()`, which would also cancel the link's
  navigation; `stopPropagation()` reaching the summary's activation behaviour is
  engine-internal and must not be asserted as a mechanism. It does not matter in practice:
  the link navigates away to the reset-confirm page, so any toggle is not observable, and
  on return the state comes from §4.1 storage — which the early return kept clean.

§10 test 13 pins the part that matters: click *Start fresh*, land on the confirm page, go
back, and the stored partition is unchanged.

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
    hazard). On a real filtered→unfiltered transition: clear the flag and re-apply the
    §4.1 partition, falling back to `data-depth` for groups in neither array.
- **While `filterActive` is true, no write to `localStorage` ever happens** — this is
  §4.2's exception 2, restated here because this is the normative site. The filtered view
  is transient by definition, and a student who folds something while filtering has not
  expressed a durable preference. This is D5, and it is the one rule that must survive
  review.
- **The toggle-all button while filtered:** *Collapse all* would hide every match and
  reproduce the exact failure this section exists to prevent. So while `filterActive` is
  true the button is **disabled** (`disabled` attribute, so it is also removed from the
  tab order and announced as unavailable) and re-enabled when the filter clears. Chosen
  over "re-run the force-open after collapsing", which would make the button visibly do
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
| `.outline-node > ul` | the hairline guide rule stops matching | re-point to `.outline-node__group > ul` |

**The three type-scale rules are the highest-risk item in this table.** They are what
§Purpose promises to keep ("part/chapter/section type scale"), and losing them produces a
visually flat but structurally correct tree — no error, no failing test, just a worse
page. §10 test 14 pins them.

On `.outline-node > ul`: it is re-pointed, not doubled. Neither surviving branch renders a
`<ul>` — the childless-container branch is childless by definition and the unit branch's
`<li>` has no nested list — so keeping the old form would create exactly the kind of dead
outline rule this spec elsewhere insists on naming.

### 6.2 New rules

- `summary.outline-node__head { cursor: pointer; list-style: none; }` plus
  `summary.outline-node__head::-webkit-details-marker { display: none; }`, mirroring
  `courses.css:716-717`. **Note for test authors:** `.outline-node__head` already carries
  `display: flex`, which removes the `display: list-item` box the marker depends on, so
  neither declaration is independently falsifiable. Do not write a test against them; they
  are defence against a future `display` change, exactly as in the rail.
- Chevron sizing and rotation, mirroring `courses.css:746-752`:
  `.outline-node__head > .outline-node__chevron { flex: none; align-self: center; transition: transform 120ms ease; }`
  and `.outline-node__group[open] > .outline-node__head > .outline-node__chevron { transform: rotate(90deg); }`
  — the **full direct-child chain**, as the rail's comment at `courses.css:749-751`
  requires: with a descendant combinator, a closed section inside an open chapter is
  painted open.
  `@media (prefers-reduced-motion: reduce) { .outline-node__chevron { transition: none; } }`.
- **`align-self: center` on the chevron is not cosmetic.** `.outline-node__head` is
  `align-items: baseline` (the rail's head is `flex-start`, so the chevron cannot simply
  be reused unaltered). A replaced element's baseline is its bottom margin edge, so a
  baseline-aligned chevron sits with its bottom on the text baseline — visibly high, and
  worst at part scale where `.icon`'s `1em` makes it largest.
- Hover and focus affordances, **with the specificity race pinned** the way
  `courses.css:719-723` documents it: `summary.outline-node__head:hover` is (0,2,1) and
  loses to the `:target` chain (0,3,0) and to the type-scale twins. So the hover rule
  changes **`background` only** (a property the higher-specificity rules do not set), never
  `color`. `summary.outline-node__head:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }`
  — `outline` is likewise unset by every competing rule. A `<summary>` is natively
  focusable; today's `.outline-node__head` `<div>` never was, so this focus style is new
  behaviour, not a port.

## 7. No-JS and accessibility

- **With JS off the page remains fully usable, including the tag filter** — but only
  because of D8/§2. Native `<details>` folds and unfolds on click and keyboard, the server
  renders the D1 default, and a `?tags=…` load opens the ancestors of every match. JS-only
  behaviours are: persistence, the expand-all button (which stays `hidden`), the
  client-side chip filter's force-open, and the deep-link force-open.
- `<summary>` supplies role, focusability and `aria-expanded` natively; no ARIA is
  hand-rolled for the disclosures. That is the main reason D3 chose `<details>`.
- **Accepted a11y cost: a focusable `<a>` (*Start fresh*) inside a `<summary>`.** A
  `<summary>` maps to a button-like role, and interactive content nested inside an
  interactive control is exposed inconsistently — some screen readers do not surface the
  inner link in browse mode. The rail's summary contains only non-interactive spans, so
  its "no ARIA needed" reassurance does not transfer unaltered. This is accepted rather
  than restructured because the alternative (rendering the link as a sibling of the
  `<summary>` and positioning it into the head row with CSS) trades a well-understood
  exposure for a fragile layout, and because per-container reset is not the only route to
  the same action: the course-level *Start fresh* in `.outline__head` and each unit's own
  reset remain reachable. §10 test 13 asserts the link is at least keyboard-reachable and
  activatable.
- The rollup counts on the head (`n/m required`) are what tells a student what is inside a
  folded group. **No change** to them: unlike the rail's bare `n/m` ratio, the outline's
  rollup already reads as text with a visible `{% trans "required" %}`, so there is
  nothing to hide from assistive tech and no second string to add. This keeps R5's new
  string count at exactly two and honours §11.
- Titles inside a folded `<details>` still carry `data-math-title` and are typeset by
  `math.js` exactly as the rail's folded titles already are. No new handling.

## 8. Existing tests that must change

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
  change) and §5 (`filterActive` suppresses all writes). Dedicated falsified e2e: test 8.
- **R2 — the async `toggle` trap.** Any implementation that suppresses persistence with a
  synchronous flag around a programmatic mutation is wrong and looks correct in casual
  testing. §4.2 exists solely to prevent it; test 6's mutant is the timing mutant.
- **R3 — the non-bubbling `toggle` trap.** A delegated `toggle` listener without
  `capture: true` never fires; the header label silently stops updating (§4.3). Test 11.
- **R4 — `querySelectorAll` sees straight through a closed `<details>`**, and elements
  inside one keep non-zero client rects. Any test asserting "folded" via `querySelector`,
  `getBoundingClientRect()` or `offsetParent` passes on a broken build. Use
  `checkVisibility()`; Playwright's `to_be_hidden()` uses computed visibility and is also
  acceptable.
- **R5 — i18n fuzzy pre-fill.** Exactly two new strings (*Expand all*, *Collapse all*) go
  through `makemessages`, which pre-fills a *wrong* translation marked fuzzy; clearing it
  is two deletions (the `#, fuzzy` line and the bogus `msgstr`). Both `.po` and the
  regenerated `.mo` must land in the branch.
- **R6 — the silent type-scale flattening (§6.1).** No error, no failing test by default,
  just a worse-looking page. Test 14.
- **R7 — `depth` shipped to consumers that ignore it.** Low: additive keys on a plain
  dict. Guarded by running the four consumers' tests (§1's table, test 2).

## 10. Testing

Every test below is **falsified against a targeted mutant before it counts**: introduce
the specific failure it is meant to catch, watch it go RED, then remove the mutant by hand
(never `git checkout`, which discards surrounding work). A test that cannot be shown RED
is not evidence.

**Django render tests** (`tests/test_outline_collapsible.py`, new):

1. A depth-0 container renders `<details … open>`; a depth-1 container renders `<details>`
   **without** `open`; both carry `data-node` and `data-depth`. Mutant: emit `open`
   unconditionally.
2. `build_outline` sets `depth` correctly on a 3-level tree, and all four §1 consumers
   still work (outline view, `build_unit_nav`, `build_student_breakdown`,
   `outline_with_tags`). Mutant: off-by-one (`parent_depth` instead of `+1`).
3. A container renders the chevron and keeps its rollup counts and *Start fresh* link
   **inside the `<summary>`**. Mutant: move *Start fresh* out of the summary — red, because
   outside the summary the link vanishes whenever the group is folded.
4. The header button ships `hidden`, empty, with both `data-label-*` attributes; and the
   nav carries `data-course-slug="{{ course.slug }}"`. Mutant: drop the nav attribute.
5. **D8 / C7.** `GET ?tags=N` where the only match sits at depth 2: that unit's ancestor
   chain renders `open`, and a container with no match does not. Mutant: drop the second
   `open` arm — this is the no-JS regression test and must be a *render* test, not e2e.

**e2e** (`tests/test_e2e_outline_tree.py`, new; `-m e2e`):

6. First visit to a 3-level course: depth-1 container heads are visible, depth-2 units are
   not (`checkVisibility()` / `to_be_hidden()`, per R4), **and** the depth-1 `<details>`
   has no `open` attribute while the depth-0 one does. The attribute half is what actually
   pins D1; a visibility-only pair also passes under a stray `display:none`.
7. Open a chapter (clicking the **title span**, not summary padding — that click target is
   what falsifies an `e.target.matches()` implementation), click into a unit, come back →
   the chapter is still open. Mutant: take the snapshot **synchronously inside the click
   handler** instead of inside `setTimeout(…, 0)` — it reads the pre-click state, so the
   newly-opened chapter is absent from the stored `open` array.
8. *Expand all* → every unit visible, label flips to *Collapse all*; reload → still
   expanded; *Collapse all* → depth-0 groups fold too.
9. **R1's test.** Fold a chapter, filter by a tag matching a unit inside a *different*,
   folded chapter → that unit becomes visible. Clear the filter → the tree returns to
   exactly the pre-filter fold state. Mutant: persist on `toggle` instead of on gesture —
   the assertion after clearing must go red. Also assert the toggle-all button is
   `disabled` while filtered.
10. `#node-N` deep link three levels down: the row is **within the viewport** (not
    "centred" — see §4.4's KaTeX hazard) and carries the `:target` highlight. Mutant: drop
    the ancestor-opening loop. Second case, same test file: with `localStorage.setItem`
    stubbed to throw and no stored key, the deep-linked row is still visible — this is the
    C4 guard (the `count === 0` no-op) and it must go red if that guard is removed.
11. **R3's test.** With every group open (label *Collapse all*), click one summary closed
    and assert the label becomes *Expand all*. Mutant: register the `toggle` listener
    without `capture: true`. Test 8 alone cannot catch this — an implementation that
    updates the label inline in the button handler passes it with no listener at all.
12. **§4.1's partition.** (a) Collapse a depth-0 root, reload, assert it is still closed —
    mutant: union the stored set with the server default. (b) Seed a partition that omits a
    depth-0 group entirely (simulating a container authored since the last visit), reload,
    assert it renders **open** per `data-depth`. (c) Seed `"not json"`, reload, assert the
    server default renders and nothing throws.
13. Click a container's *Start fresh*, land on the reset-confirm page, navigate back, and
    assert the stored partition is byte-identical to before. Separately, assert the link is
    reachable by keyboard from the summary and activatable. Mutant: remove §4.2's
    `closest("a")` early return.
14. **R6.** On a rendered outline, a nested (depth-1) chapter's title computes
    `font-size: 1.1rem` and a nested section's computes `.75rem`/uppercase. Mutant: omit
    the `> .outline-node__group >` twins from §6.1 — a pure-CSS regression no HTML
    assertion can see.
15. Zero-groups course (all units at depth 0): the toggle-all button stays `hidden`.
16. JS off (or `outline_tree.js` blocked): depth-0 groups open, deeper folded, clicking a
    summary still folds/unfolds, and a `?tags=N` load still shows its match. Guards D3 and
    D8 together.

**Gates before the PR:** `ruff check --no-cache` and `ruff format --check`, the affected
test set, then the outline/rollups/tags/unit-nav regression files named in §8. Start the
test-DB container before any pytest run. Light and dark screenshots of the outline page,
judged separately, and specifically checking the chevron's optical alignment against the
part-scale title (§6.2's `align-self`).

## 11. Out of scope

- No title search / filter box on the outline.
- No server-side or cross-device persistence.
- No change to the unit rail, the mobile drawer, the builder tree, or the teacher
  per-student tree.
- No change to `courses.css:1`'s dead `.outline-tree ul` rule.
- No change to what the rollup counts mean, how they are computed, or how they are
  announced (§7).
