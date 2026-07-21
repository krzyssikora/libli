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

Three parts, shipped as **one PR with ordered commits** — not three PRs. They are small, they
share a review context ("long courses"), and 2A/2B share a stylesheet; splitting them would cost
three review cycles for one coherent change.

The commit order is **Part 1 → Part 2A → Part 2B**. Part 1 goes first because it is genuinely
independent (it touches only `builder.css` and `builder.js`) and therefore never conflicts with
what follows. Parts 2A and 2B are **coupled**: they share
`courses/static/courses/css/courses.css`, and 2B's centring has to account for a group 2A lets
the user fold. 2B's folded-group guard ships with **2B**, not 2A — between those two commits,
folding the active unit's own group is possible but the rail is simply never re-centred, which is
today's behaviour and therefore no regression at any point in the sequence.

### Part 1 — Builder: sticky detail panel

Files: `courses/static/courses/css/builder.css` and `courses/static/courses/js/builder.js`. The JS
change is confined to consolidating the nine panel-content assignments behind one `setPanel()`
helper (below); no template change.

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

- `align-self: start` is **belt-and-braces, not the load-bearing declaration.** The intuitive
  story ("a stretched item has no free space to travel in, so sticky does nothing") is
  contradicted by the very precedent quoted above: `.unit-tree` sets `align-self: stretch`
  **explicitly** (`courses.css:505`) and sticks fine in production, because `max-height` clamps
  the stretch and *that* is what creates the free space. Since Part 1 also specifies
  `max-height`, sticky would very likely work without `align-self: start`; it is specified
  anyway for the short-panel case where the cap never binds. The consequence is for testing:
  the builder e2e must be demonstrated RED by removing the **whole new declaration block**, not
  by removing `align-self` alone — which would probably still pass and produce a falsely
  reassuring red-green cycle (see Testing).
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
  stack vertically, and the mobile override must reverse **`position`, `max-height`, and
  `overflow`** — `top` and `align-self` need no reset, being inert once `position: static` and
  single-column stacking apply:

  ```css
  @media (max-width: 720px) { .builder__panel { position: static; max-height: none; overflow: visible; } }
  ```

  Dropping only `position: static` would leave the stacked panel a nested ~100vh scroll
  container sitting under the tree — a touch scroll-trap and a clipped panel on the narrowest
  viewport, strictly worse than today. No new breakpoint is introduced.
- **`100vh` is safe here** precisely because sticky only applies above 720px — the mobile
  visual-viewport discrepancy never comes into play. `top: var(--space-4)` needs no
  header-height offset because `.app-header` is `position: relative`, not sticky.
- **Panel scroll reset — via one helper, not by hand.** Once the panel is a scroll container,
  `builder.js` replacing its `innerHTML` on node select leaves any non-zero `scrollTop` in
  place, so the next unit's panel would appear scrolled part-way down. There are **nine**
  `panel.innerHTML = …` assignments in `builder.js` — lines **119, 122, 123, 164, 189, 190, 200,
  203, 296**. The easiest to miss is `refreshPanel`'s early return at 119
  (`if (!url) { panel.innerHTML = ""; return; }`), which sits *before* the fetch. A
  requirement phrased as "every place" would miss an async branch and reintroduce the bug with
  no test to catch it. Instead: a single `setPanel(html)` helper that assigns and then sets
  `scrollTop = 0`, with **every** site routed through it. The invariant is **exactly one
  `panel.innerHTML =` assignment site, inside `setPanel`** — stated that way rather than "none
  remain", which `setPanel`'s own body would violate. The existing *read* at `builder.js:10`
  (`var neutralPanel = panel.innerHTML;`) is a permitted non-assignment occurrence.
- **`.panel__seam` must stick to the bottom of the panel, or Part 1 misses its own goal.** In
  `templates/courses/manage/_unit_panel.html` the seam holding *+ Add element* and
  *Open editor →* sits **after** the element list (line 21, list at line 11). Cap the panel at
  ~100vh, scroll it internally, and reset `scrollTop = 0` on every swap, and an element-heavy
  unit shows the panel's *top* — with the two buttons the Purpose section names again below the
  fold. That is the author's original complaint relocated from the page into the panel, and
  "the last control is reachable" would be satisfied while the actual goal is not. The seam is
  therefore pinned to the bottom of the panel's scroll container —
  `position: sticky; bottom: 0` with an opaque background — mirroring `.unit-foot`'s existing
  pattern (`courses.css:558`), and it is **tested**: on a unit with enough elements to overflow
  the panel, both buttons are within the viewport immediately after selecting that unit, with no
  scrolling of any kind.
- **The `notice()` bar must stay visible.** `builder.js`'s `notice(text)` builds an `.op-error`
  bar and calls `panel.prepend(bar)`, auto-removing it after 6s. Today the panel is short and
  top-anchored, so the bar is always seen. Once the panel scrolls internally, a notice
  prepended while the author is scrolled part-way down renders *above* the visible band and
  vanishes unseen — and these are precisely the conflict / illegal-move / network messages
  (`data-msg-conflict`, `data-msg-illegal`, `data-msg-network`) whose entire purpose is to be
  noticed. The bar is therefore pinned inside the scroll container, with a **scoped** selector —
  not a bare `.op-error` rule:

  ```css
  .builder__panel > .op-error { position: sticky; top: 0; z-index: 1; /* + opaque background */ }
  ```

  What the scoping excludes is the **page-level flash** at `builder.html:6`, which sits outside
  `.builder` entirely, and `_op_error.html`'s renders elsewhere in the app — a bare `.op-error`
  rule would make those sticky too. It does **not** exclude the two network-error strings
  `builder.js` writes as `panel.innerHTML` (`builder.js:190`, `:203`): those are
  `<div class="op-error">` written as the panel's direct child, so `.builder__panel > .op-error`
  matches them exactly as a bare rule would. That is intentional — they are error messages in a
  scrolling panel and should be pinned and backed like any other — but it is a decision, not an
  accident, and no test should assert that panel-content op-errors are non-sticky.

  **The bar also needs an opaque background of its own here.** `.op-error` is styled only in
  `courses/static/courses/css/editor.css:5` (whose comment even says "shared with builder; styled
  here"), and `builder.html`'s `extra_css` loads **only** `builder.css` — so on the builder page
  the bar today has no background, border, or padding. Sticking an unbacked bar at `top: 0` would
  let panel content scroll *under* its text, leaving the message less readable than before. The
  new rule in `builder.css` must therefore also give it `--danger-subtle` + border + padding
  mirroring `editor.css`. This is a degradation Part 1 must not introduce, and it is listed under
  Error handling for that reason.

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
      <svg class="icon unit-tree__chevron" aria-hidden="true" viewBox="0 0 24 24"><path d="…"/></svg>
      <span class="unit-tree__grouptitle" lang="{{ course.language }}">{{ item.node.title }}</span>
      {% if item.required_total %}
        <span class="unit-tree__count" aria-hidden="true">{{ item.required_done }}/{{ item.required_total }}</span>
        {% if item.required_done == item.required_total %}
          <span class="unit-tree__groupcheck badge badge--done" aria-hidden="true">✓</span>
        {% endif %}
        <span class="visually-hidden">{% blocktrans with done=item.required_done total=item.required_total %}{{ done }} of {{ total }} required units completed{% endblocktrans %}</span>
      {% endif %}
    </summary>
    <ul class="unit-tree__children">…</ul>
  </details>
</li>
```

**Child order is fixed** as chevron / title / counter / ✓ — the ✓ is *additive* at `n/n`, it does
not replace the counter, so a completed group reads `12/12 ✓`.

`lang="{{ course.language }}"` moves onto the **title span**, not the whole summary: the title
is author content, the counter is UI chrome in the interface language, and the current markup
would otherwise mislabel the counter's language.

Native `<details>`/`<summary>` is chosen over a JS disclosure because it works with JS off,
brings keyboard operation and correct screen-reader semantics for free, and needs no state
machine, no ARIA wiring, and no new JS file. The one keyboard trade-off: every `<summary>` is
natively focusable, so tabbing through the rail now stops once per group in addition to the unit
links. On the long courses this targets that is a net *reduction* in tab stops — folding removes
far more unit links from the tab order than the summaries add — so no `tabindex` intervention is
warranted.

**A group with no children renders as it does
today** (a plain `<div class="unit-tree__head">`, no `<details>` wrapper) — an empty disclosure
would be a dead control. Both shapes therefore exist in the DOM and both must be styled.

**The childless head reserves chevron-width space.** The `<details>` shape has a leading chevron
inside its flex row and the plain-div shape does not, so without compensation their titles start
at different left edges within the same list — reading as accidental misalignment in the very
column this feature exists to make scannable. The childless head therefore gets an
`aria-hidden` spacer (or equivalent padding) of the chevron's width, and a childless group is
included in the required rail screenshots so the result is actually reviewed.

**Open state.** `contains_current` is computed **server-side** so the correct groups are open
in the first painted frame; a JS pass would flash the fully-folded tree first.

**The stamping contract is explicit:** a single pass over the `build_outline` tree sets
`contains_current` on **every** node dict — group *and* unit — initialising it to `False` and
setting it to `True` for the current unit's dict (`pk == current_pk`) and every ancestor of it.
The key is therefore always present, never merely absent-when-false, so a test can assert
`is False` on non-ancestor groups without a `KeyError` and the template's
`{% if item.contains_current %}` has one unambiguous meaning.

`courses/rollups.py` already has this recursion inside `_top_level_part` — a local `contains(d)`
that tests `d["node"].pk == current_pk` or any child. That recursion is generalised into a
**named, module-level helper in `courses/rollups.py`**:

```python
def _stamp_current_chain(tree, current_pk) -> None:
    """Set contains_current on every dict: True for current_pk and its ancestors, else False.

    Mutates in place. _top_level_part requires an already-stamped tree.
    """
```

`build_unit_nav` calls it immediately **before** `_top_level_part`, and
**`_top_level_part` is re-expressed in terms of the stamped flag** rather than keeping a second
copy of the walk. Its post-refactor signature drops the now-redundant `current_pk` parameter —
`_top_level_part(tree)` — and it reads `d["contains_current"]` **directly, not via `.get()`**: on
an unstamped tree that raises `KeyError` loudly rather than silently returning `None` and blanking
`part_progress`. Its docstring states the stamped-tree precondition. It is private with exactly
one call site, so the signature change is contained.

Because the pass stamps unit dicts too, this preserves the existing contract that
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

**Find-in-page is the third accepted cost, and the least obvious one.** Ctrl+F is today the
cheapest way to locate a unit in a 300-row tree, and content inside a closed `<details>` is not
matched by find-in-page in most browsers (Chrome's auto-expanding search only reaches content
marked `hidden="until-found"`). Folding therefore removes the one scanning mechanism that
already scaled. This is accepted rather than compensated: `hidden="until-found"` was considered
and rejected because it means hiding the children with an attribute *instead of* relying on
`<details>`' own open state, which reintroduces the state machine and the JS-off breakage that
choosing native `<details>` exists to avoid, in exchange for a Chromium-only benefit. An
"expand all" control is likewise **out of scope** — the current chain being open on every load
is the intended answer to "where am I", and browsing a fully-expanded tree is what the course
outline page is for. If find-in-page loss proves painful in practice, revisit with a real search
box rather than an expand-all toggle.

**Folded row content.** A `<summary>` shows the group title plus its required-work progress as
`done/total`, read from `required_done` / `required_total`, which `build_outline` already places
on every group dict (`build_unit_nav` consumes exactly these fields today for `part_progress`
and `course_progress`). A group at `n/n` additionally gets a ✓ badge, so "finished" reads
identically at unit and group level **for groups that contain required work**. It cannot for the
rest: unit rows take their ✓ from `item.completed`, groups from
`required_done == required_total`, and quizzes have `required_total == 0` (`rollups.py:61`) — so
an all-quiz chapter shows every child ✓'d and stays bare itself. That is intentional: a group
with no required work has no completion to report.

**The group ✓ needs its own class**, `.unit-tree__groupcheck`, not the unit row's
`.unit-tree__check`. That class exists specifically to cancel `.badge--done`'s
`margin-left: auto` because in a *unit* row the ✓ is a **leading** icon (see the comment at
`courses.css:544-546`). In the summary the ✓ is a **trailing** chip, so reusing the class would
apply a reset written for the opposite case. `.unit-tree__groupcheck` composes with
`badge badge--done` for colour but keeps the trailing behaviour.

The counter is **suppressed entirely** — no counter, no ✓ — when `required_total == 0`: there is
no required work to count, so neither `0/0` nor a bare suffix is rendered.

There is **no anonymous-viewer case to handle.** `build_unit_nav` has three call sites
(`courses/views.py:422` inside `full_lesson_render_context`, `:1115`, `:1144`), reached from the
`lesson_unit` GET, the `check_answer` and notes no-JS re-renders, `quiz_unit`, and
`_quiz_render_feedback`'s no-JS re-render — i.e. every render path routed through
`full_lesson_render_context` / `_quiz_render_feedback`, **all** login-gated (`lesson_unit` at
`views.py:561` and `quiz_unit` at `:1100` are `@login_required` and additionally gate on
`can_access_course`). There is no anonymous render path and no preview-viewer role, so a
`user.is_authenticated` branch would be dead code and a test for it could not be driven through
the client at all (an anonymous GET redirects to `/accounts/login/`).

Those no-JS re-render paths add a **fourth accepted cost**: a student browsing without JS resets
their folds on every *answer submission*, not only on navigation.

**Summary row layout.** `.unit-tree__head` is a plain block today, and the rail is
`flex: 0 0 14rem` — adding a chevron and a counter to that row without pinning the layout would
wrap long chapter titles or push the counter out of view. The summary is a **flex row**:
chevron (`flex: none`) / title (`flex: 1; min-width: 0` with `overflow: hidden;
text-overflow: ellipsis`, mirroring `.unit-tree__label`) / counter (`flex: none`) / ✓
(`flex: none`).

**Title legibility, not just overflow.** Pinning the flex layout stops the row breaking, but it
does not guarantee the group titles this feature exists to make scannable stay readable. 14rem
is 224px; `.unit-tree__list` takes `.35rem` side padding, `.unit-tree__head` another `.35rem`
margin, and `.unit-tree__children` adds `.55rem` per nesting level — so a depth-3 section with a
chevron and a `12/12 ✓` chip has roughly 100–120px left for a `.64rem` uppercase title, i.e. a
few words before the ellipsis. Two requirements follow:

- The group title **may wrap to two lines** (unlike unit rows, which stay single-line): a
  chapter title is a landmark, and truncating it to "Introduction to…" defeats the point. Beyond
  two lines it ellipsises.
- The **worst case must be verified in the required screenshots**, pinned synthetically so it is
  repeatable: a depth-3 section, a 60-character title, and a `12/12 ✓` chip. If that case is
  still unreadable, widening the rail beyond 14rem is the fallback — an explicit decision to
  make at screenshot review, not silently.

**Accessible naming.** A bare `3/7` announces as "three slash seven" with no context. Exactly one
technique is used, not a choice of two: the visible ratio and the ✓ are both
`aria-hidden="true"`, and a sibling `<span class="visually-hidden">` (the class already ships at
`core/static/core/css/app.css:1167`) carries the translated sentence.

**Two forms, do not conflate them.** The `{% blocktrans %}` **body** is written with template
tokens — `{{ done }} of {{ total }} required units completed` — while the **msgid** that
`makemessages` extracts and that lands in the `.po` files is
`"%(done)s of %(total)s required units completed"`. Writing the `%(done)s` form *inside* the
template body is a hard failure, not a style slip: `blocktrans` collects an empty `vars` list,
`result % data` raises `KeyError`, and `BlockTranslateNode` re-raises it as `TemplateSyntaxError`
("unable to format string returned by gettext") — 500ing every lesson and quiz page that has a
counted group.

**Phrasing is count-neutral, deliberately.** The sentence is
`{{ done }} of {{ total }} required units completed` **without** a `{% plural %}` branch, which
would otherwise be wrong for Polish: PL has three plural forms, so a count-bearing noun would be
ungrammatical at 1, 2, and 5. Adding `{% plural %}` later would also turn the msgid into a
msgid/msgid_plural pair and invalidate the exact msgid pinned above. If the PL translation reads
awkwardly, the fix is a count-neutral rephrasing in **both** catalogs, never a plural branch on
one of them.

The msgid is added to both the `en` and `pl` catalogs. It lives only in a template, so
`gettext_lazy` does not arise. `aria-label` on the counter span is
**rejected**, not offered as an alternative: a bare `<span>` maps to role `generic`, on which
ARIA prohibits naming, so most screen readers ignore it. Marking the visible text
`aria-hidden` is what prevents the row announcing "three slash seven, three of seven required
units completed". The decorative chevron is `aria-hidden="true"`. `<details>`/`<summary>` supply
the expanded/collapsed state natively; no `aria-expanded` is added by hand.

**Both surfaces from one change — but they are not identical.** `_unit_tree_node.html` is
included by both `_unit_tree.html` (desktop rail) and `_unit_shell.html`'s mobile drawer, so
both gain folding from this single edit. The drawer nonetheless has its own container
(`.unit-drawer__panel`, `max-height: 80vh; overflow-y: auto`), its own list padding
(`.unit-drawer__list`), and its **own centring path**: `openDrawer()` calls
`act.scrollIntoView({block: "center"})`, which `centerActive()` does **not** replace.

That asymmetry is deliberate and stays: the drawer is a fixed-position modal whose panel is the
only scrollable thing on screen, so `scrollIntoView`'s ancestor-walking — the reason the rail
avoids it — is harmless there. The folded-active case is also benign in the drawer:
`scrollIntoView` on a `display: none` element is a no-op, leaving the panel at its natural top,
rather than the rail's negative-target-clamped jump. The drawer therefore needs no `offsetParent`
guard.

**The drawer's focus trap does need widening, and this is the one drawer change that is not
optional.** `unit_nav.js`'s `focusable()` selects
`a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])`. A `<summary>` is natively
tabbable but matches **none** of those, so after 2A it sits in the browser's tab order while
being absent from the trap's `items` list. `onKeydown` calls `preventDefault()` only when
`activeElement` is `items[0]` or `items[last]`, so focus resting on a summary Tabs natively —
and when a folded group's summary is the last tabbable thing in the panel (a shut chapter at the
end of the tree, the normal case once folding exists) **Tab escapes the drawer entirely**.
`focusable()`'s selector therefore gains `summary`. The existing
`test_mobile_drawer_focus_trap` re-implements the same selector in its own assertion, so it
would keep passing while the trap leaked — that in-test list must be updated to match, and an
e2e added that Tabs from a folded trailing `<summary>` and asserts focus is still inside
`[data-unit-drawer]`. Because the two surfaces diverge, the drawer gets its **own** e2e coverage rather than
inheriting the rail's (see Testing).

**Fold state is per-surface, and that is accepted.** The partial is included twice per page, so
every group exists as two independent `<details>` elements: folding a chapter in the rail leaves
the drawer's copy open, and vice versa. No JS syncs them. Both copies are server-seeded
identically on every load, so the divergence can only last until the next navigation, and the two
surfaces are never visible at the same time (the rail is `display: none` below 640px, the drawer
above it).

**Flat courses.** A course on the Flat depth preset has no group nodes at all, so its tree
renders byte-identically to today. Part 2B is what helps those courses.

**CSS — the child-combinator break is the real hazard.** The element change from `div` to
`summary` is minor; the added **nesting level** is not. Today
`.unit-tree__node--section > .unit-tree__head` and `.unit-tree__node--chapter > .unit-tree__head`
(`courses.css:540-542`) match a *direct child* of the `<li>`. With `<details class="unit-tree__group">`
interposed, both selectors stop matching and chapters/sections silently lose their uppercase
micro-type — destroying the exact scanability this feature exists to improve.

The fix is the **explicit `.unit-tree__group > .unit-tree__head` variant paired with the existing
direct-child selector**, i.e. each rule lists both shapes:

```css
.unit-tree__node--chapter > .unit-tree__head,                     /* childless group  */
.unit-tree__node--chapter > .unit-tree__group > .unit-tree__head  /* <details> group  */
```

**Simply dropping the `>` is rejected.** `.unit-tree__node--chapter .unit-tree__head` is a
descendant selector that would also match a *section*'s head nested inside a chapter — harmless
only because the chapter and section rules happen to carry identical declarations today, and it
would silently remove the ability to ever differentiate them (and match any future head added
deeper). Both shapes really do exist: a childless group keeps `.unit-tree__head` as a direct
child of the `<li>`. `.unit-tree__head`'s margins likewise have to survive the move. Because this
is the highest-risk part of 2A, it gets an explicit computed-style assertion in Testing rather
than relying on a screenshot glance.

The remaining `<summary>` declarations are pinned rather than left to interpretation:
`display: flex` (which also removes the default `list-item` box), `list-style: none`,
`::-webkit-details-marker { display: none }` for older WebKit, and `cursor: pointer` — the row
is now interactive. It also gets a `:focus-visible` treatment consistent with the rest of the
rail, and a hover treatment matching `.unit-tree__unit:hover`.

**The chevron follows the repo's icon convention:** a monochrome `currentColor` line SVG with the
shared `.icon` class (`fill: none; stroke: currentColor`, `app.css:108`), **not** a text glyph —
the `‹` on `.unit-tree__toggle` predates that convention and is not a precedent to copy.

It is an **inline `<svg>` with its own `<path>`, not a `<use>` reference.** The repo's only
sprite, `templates/courses/manage/_icon_sprite.html`, contains no chevron symbol (its ids are
`bi-*` and `el-*`) and is included by exactly three templates — `manage/builder.html`,
`manage/editor/editor.html`, `help/doc.html` — never by `base.html`, `_unit_tree.html`, or
`_unit_shell.html`. A `<use href="#icon-chevron-…">` on a lesson page would therefore resolve to
nothing and render an empty box. Inline SVG is also what non-manage pages already do (see the
notification bell at `templates/base.html:120`), and it avoids both adding a symbol and newly
including the whole manage sprite on every student page.

**The rotation selector must be a direct-child chain**, not a descendant selector:

```css
.unit-tree__group[open] > .unit-tree__head > .unit-tree__chevron { transform: rotate(90deg); }
```

The tree is recursive, so a **closed** section's `<details>` sits inside its **open** chapter's
`<details>`. A loose `details[open] .unit-tree__chevron` would match the closed section's chevron
too and paint every nested closed group in the open orientation — the same descendant-selector
hazard this spec devotes a section to for `.unit-tree__head`, and it must not be reintroduced
here. A computed-style assertion covers it (see Testing). The rotation carries a short
transition, suppressed under `prefers-reduced-motion: reduce`.

**Values for the new classes** (`.unit-tree__chevron`, `.unit-tree__count`,
`.unit-tree__groupcheck`) — size, colour token, gap, and the two-line title treatment — are
settled by the `frontend-design` skill under the constraints stated above, the same deferral
Part 2B(2) makes. The constraints are binding; the numbers are not pre-committed here.

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

**Folding a group *above* the active unit shifts the rail, and that is accepted.** Toggling a
group higher up changes the rail's content height, so rows below it — possibly including the one
the student is reading — move under the cursor. This is native `<details>` behaviour inside a
scroll container (scroll anchoring is not reliably applied there across engines), it is the
direct and legible consequence of a click the student just made, and every alternative (forcing
`overflow-anchor`, or compensating `scrollTop` by the measured height delta) adds JS to the
zero-JS half of the feature to smooth over an interaction the student initiated. No
compensation is specified.

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
  slightly thicker sibling. **The widening must be width-neutral.** `.unit-tree__unit` is a flex
  row with `border-left: 1px` and `margin-left: .35rem`, and `.is-active` overrides only the
  border colour/width — so 1px → 4px adds 3px to the active row's border box, jogging its text
  right relative to every neighbour and making the row wider than its siblings in an already
  tight 14rem rail. Either compensate with reduced `padding-left` on `.is-active`, or replace
  the border with an inset `box-shadow` / `::before` bar so no layout box changes at all
  (preferred). The active row's left text edge must align with inactive siblings — assert this,
  don't eyeball it.
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

counter shown only when required_total > 0   (both views are @login_required,
so there is no anonymous branch)

browser
  └─ unit_nav.js
       ├─ on load                → centerActive()
       └─ on toggle → expanding  → centerActive()          ← the fix
            centerActive(): re-queries rail + .is-active, returns early if
            collapsed, missing, or offsetParent === null (folded group)
```

Part 1 introduces no data flow: it is a stylesheet change to an existing grid item, plus routing
every panel swap through a new `setPanel()` helper that resets `scrollTop`.

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
- **`required_total == 0`.** No counter is rendered; no ratio is computed, so there is no
  divide-by-zero path.
- **Builder error notices.** Making the panel a scroll container would otherwise hide
  `notice()`'s prepended `.op-error` bar from a scrolled-down author — the one degradation Part 1
  could introduce, closed by the sticky-bar requirement in Part 1.
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
- The counter renders the **actual numerals** from the group's rollup fields (assert `3/7`, not
  merely that `.unit-tree__count` exists — a template scoping slip renders a bare `/` silently),
  is `aria-hidden`, and is accompanied by the `.visually-hidden` translated sentence.
- A group with `required_total == 0` renders no counter and no ✓.
- A group at `n/n` renders the ✓ **in addition to** the counter, using `.unit-tree__groupcheck`
  (not `.unit-tree__check`).
- A group with **no children** renders no `<details>` and keeps the plain `.unit-tree__head`.
- A Flat-preset course renders no `<details>` at all.
- `build_unit_nav` issues no more queries than before. The baseline must be **captured on
  `master` and quoted in the test's docstring**, then asserted with `assertNumQueries` — measuring
  post-change and hard-coding the result would make the assertion incapable of detecting the
  regression it exists to catch.

**e2e (Playwright)** — must drive the real UI with real clicks; `page.evaluate` shortcuts are
forbidden by the repo's standing e2e rule, since they would let a broken control ship green.
Per the repo's "falsify tests, don't run them" rule, **each e2e below must be demonstrated RED**
before its implementation lands. For the builder cases, RED is demonstrated by removing the
**whole new `.builder__panel` declaration block** — not `align-self: start` alone, which
`max-height` would likely mask (see Part 1).

Seeding: `tests/test_e2e_unit_nav.py`'s `_seed_nav_course(..., num_units=35)` creates **one
`part` node** containing all the units — it does not create *chapter or section* nodes, and it is
not flat. Two consequences:

- The helper is extended (or a sibling helper added) taking `num_chapters` × `units_per_chapter`
  — enough total units to exceed the rail's viewport — with the current unit placed in the
  **middle** chapter so both "an earlier sibling is shut" and "a later sibling is shut" are
  observable.
- **Every existing test in that file is affected and is part of the must-pass set.** Because the
  helper already seeds a `part`, `test_desktop_tree_collapse_persists`,
  `test_active_unit_scrolled_into_view`, `test_active_unit_scroll_does_not_move_window` and both
  drawer tests will, after 2A, render their units inside a `<details>` with a new `<summary>` row
  and a `0/35` counter in the rail. Their scroll arithmetic and locators now see that extra row;
  any breakage is a real signal, not a fixture to paper over.

- On loading that middle-chapter unit, its chapter's `<details>` is open and the sibling
  chapters are shut.
- A real click on a folded `<summary>` reveals that chapter's units.
- Collapsing the rail with the real toggle and expanding it again leaves the active unit centred
  — assert the rail's scroll position places the active element within the rail's visible band,
  not merely that `scrollTop != 0`. This test **must** run in a
  `browser.new_context(reduced_motion="reduce")` context and **poll** via `wait_for_function`
  rather than reading the position once: `centerActive()` keeps the existing
  `behavior: reduce ? "auto" : "smooth"` branch, so a default context animates the scroll and a
  single immediate read is flaky. The file's existing `test_active_unit_scrolled_into_view`
  already does exactly this, for exactly this reason — match it.
- **Folded-active guard — NOT an e2e.** The obvious test ("fold the active group, collapse →
  expand, assert `scrollTop` unchanged") is **vacuous** and must not be written: collapsing
  applies `html.unit-tree-collapsed .unit-tree__list { display: none }` (`courses.css:642`),
  which shrinks the rail's content and makes the browser clamp `scrollTop` to 0. On expand the
  rail is at 0 in *both* implementations — the buggy one via `scrollTo`'s clamp of a negative
  target, the fixed one via the early return — so the assertion is 0 → 0 either way and can
  never be shown RED. Instead the guard is asserted at the **JS level**: spy the rail's
  `scrollTo` and assert `centerActive()` does not call it when the active element has
  `offsetParent === null`. If that spy is impractical in this harness, the guard is demoted to
  documented defensive code with an explicit note that it is not observable through the real UI —
  never papered over with a green-but-meaningless e2e.
- **Chapter micro-type survives the `<details>` nesting** — the highest-risk change in 2A, and
  invisible to every other assertion. Computed-style assertion that a chapter `<summary>`
  resolves **the literal current values** — `text-transform: uppercase` and the px equivalent of
  `font-size: .64rem` (`courses.css:540-542`) — in **both** shapes: the `<details>` group and the
  childless group. Asserting only that the two shapes agree *with each other* would pass with the
  new selector wrong in both, so the baseline is quoted, not inferred.
- **Chevron rotation, both halves in one test** so they cannot drift apart: the open chapter's
  own chevron resolves a **non-identity** `transform` (the 90° rotation matrix), **and** a closed
  section nested inside it resolves none. The negative half alone is satisfied perfectly by a
  typo'd or entirely missing rule, which would ship a chevron that never rotates — removing the
  only visual signal that a group is open.
- **Drawer focus trap:** Tab from a folded trailing `<summary>` in the open drawer and assert
  focus is still within `[data-unit-drawer]`.
- **Mobile drawer:** open the drawer at a mobile viewport and assert the current unit's chapter
  is open while a sibling chapter is shut — the drawer has its own container and centring path,
  so it does not inherit the rail's coverage.

Part 2B(2) is verified by **computed-style assertions**, not screenshot review — a cascade bug
here is exactly what an eyeball misses:

- The active row's left text edge equals an inactive sibling's (the width-neutrality requirement:
  "assert this, don't eyeball it").
- `font-weight` on the active row resolves to 700.
- A row carrying **both** `.is-done` and `.is-active` resolves `color` to the `--primary` value,
  not `--text-tertiary` — the source-order precedence requirement.
- Focus the active row with a real `Tab` and assert `outline-width` resolves non-zero and
  `outline-color` differs from the accent-bar colour. ("Does not double up into a muddy ring" is
  a judgement, not a computed value — it belongs on the screenshot-review checklist, and is
  listed there rather than faked as an assertion.)

Builder e2e — home file **`tests/test_e2e_builder_tree_layout.py`**, which already owns the
`.builder__panel` rule Part 1 edits (it guards the 2:1 ratio and `min-width: 0`). Its existing
assertions are part of the must-pass set, since a careless rewrite of that rule regresses them.
Seed: a course deep and large enough that the rendered tree exceeds the viewport at the test's
window size — reuse the file's existing builder-course fixture, extended with enough nodes to
scroll (the tree, not the panel, is what must overflow).

- **Builder, deep unit:** with the tree scrolled to the bottom, click a deep unit and assert
  *Open editor* is inside the viewport.
- **Builder, tall panel:** on a unit whose panel exceeds the viewport, both *+ Add element* and
  *Open editor →* are **within the viewport immediately after selecting that unit, with no
  scrolling** — the `.panel__seam` sticky-bottom requirement, and the assertion that actually
  encodes Part 1's goal (a mere "last control is reachable" check passes while the goal fails).
- **Builder, notice legibility:** a `notice()` bar raised while the panel is scrolled down is
  visible **and legible** — assert its painted background, not merely `is_visible()`, since an
  unbacked sticky bar lets content scroll under its text. **Name the trigger:** use a
  `page.route(...)`-aborted panel-form POST (or a drag producing a 422). The 409-conflict path is
  explicitly **not** the one under test — it also calls `refreshPanel`, which post-change routes
  through `setPanel`, resetting `scrollTop` and replacing the innerHTML the bar was prepended
  into, making the assertion vacuous.
- **Builder, panel scroll reset:** scroll a tall panel down, then click a *different* unit
  through the real tree control, and assert the new panel is at `scrollTop === 0`. Demonstrated
  RED against a `setPanel`-less implementation.
- **`setPanel` invariant, as a real test.** The e2e above drives only the `data-select` path
  (`builder.js:122`); a partial refactor that routes 122 through `setPanel` and leaves 119, 164,
  189/190, 200/203 and 296 raw passes it green — exactly the missed-async-branch failure the
  helper exists to prevent. So the invariant gets a **source-scan unit test**: read `builder.js`
  and assert exactly one `panel.innerHTML =` **assignment**, excluding the `builder.js:10` read.
  ("A grep is not run by CI" is not a reason to skip this — a test that greps is.)
- **Builder, stacked:** at a ≤720px viewport the panel is **not** sticky **and is not a scroll
  container** — assert computed `max-height: none` (or `scrollHeight <= clientHeight`), not
  merely that `position` is `static`, or the nested-scroll-trap regression ships green.

**Screenshots.** Light and dark, desktop rail and mobile drawer, reviewed before shipping, plus
one content-heavy builder panel to confirm `overflow: hidden auto` clips nothing that matters.
The rail shots must include a **pinned synthetic worst-case summary row** so the title-legibility
decision — including whether 14rem still suffices — is made against repeatable evidence rather
than "the longest title in some production course", which no seed can reproduce: a **depth-3
section, a 60-character title, and a `12/12 ✓` chip**. A **childless group** appears in the same
shot so the chevron-spacer alignment is reviewed alongside it.
Also check whether any committed help screenshot under `core/static/core/img/help/` depicts the
unit tree; if one does, regenerate it, since this change dates it.

**Conventions.** `uv run` for `pytest` / `ruff` (they are not on PATH). Any new user-visible
string is wrapped for i18n and added to both the `en` and `pl` catalogs; removed msgids are
deleted from both `.po` files rather than left as obsolete `#~` entries. This worktree needs
its own `DATABASE_URL` to avoid colliding with the other checkouts on the shared
`test_libli` database.
