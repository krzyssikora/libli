# Pinned TOC toggle for the student unit tree

## Purpose

On desktop a student reading a unit sees the course tree in a 14rem rail on the left. Collapsing that
rail today does not remove it: `html.unit-tree-collapsed .unit-tree { flex-basis: 2.4rem }`
(`courses/static/courses/css/courses.css:868`) shrinks it to a **sliver** that keeps its sunken
background, its right border, its sticky bar and a flipped `‹` toggle.

**This is not primarily a width problem, and the spec should not pretend otherwise.** The rail is
`flex: 0 0 14rem` (224px) collapsing to 38.4px, so today's collapse *already* reclaims ~186px. Only
the last ~38px remains on the table. What the student is actually left with is a bordered vertical
stripe dividing the page for no purpose — the "waste of space" complaint is about the divider, not
about pixels.

So the deliverable is three things, in order of how much they matter:

1. **Remove the stripe.** The rail leaves the layout entirely; a small pinned icon in the left margin
   becomes the only (and sufficient) way back.
2. **Keep prose readable in the reclaimed space.** Today's collapsed state renders body text at
   ~834px — roughly 125 characters per line, well past the comfortable 60–80ch range. Capping prose
   is a readability *fix* that this change delivers, not a tax it pays.
3. **Reclaim the last ~38px** for tables, images and other wide content.

### Scope

In scope: the student unit page (lesson and quiz), desktop only (>640px).

Out of scope, deliberately:

- **The mobile drawer (≤640px).** `.unit-foot__contents` already opens a bottom-sheet drawer there
  and the inline rail is already `display: none`. Untouched.
- **The teacher quiz-review rail** (`.review-roster` on
  `templates/courses/manage/review_submission.html`, URL
  `/manage/courses/<slug>/review/<submission_pk>/`). It keeps the sliver pattern. After this ships
  the two pages will differ; that is an accepted, stated cost, and porting the treatment later is a
  mechanical rename against the `review-roster*` names.

  **This out-of-scope promise is load-bearing and must be enforced by selector scoping — see
  "Scoping" below.** The review page shares the `.unit-shell` wrapper *and* the global
  `html.unit-tree-collapsed` class, so a naively-scoped rule would silently deform it.

## Architecture / components

### Existing pieces this builds on

| Piece | Location | Role |
|---|---|---|
| `.unit-shell` | `courses.css:535` | `display: flex; align-items: flex-start; max-width: 72rem; margin: 0 auto` |
| `.unit-tree` | `courses.css:540` | the 14rem rail; sticky, own scrollbar |
| `.unit-tree__toggle` | `_unit_tree.html:5-8` | the in-rail `‹` collapse control |
| `unit_nav.js` | `courses/static/courses/js/unit_nav.js:48-67` | binds `[data-unit-tree-toggle]`, writes `localStorage`, calls `centerActive()` |
| pre-paint restore | `templates/base.html:34-41` | reads `libli_unit_tree_collapsed`, sets `html.unit-tree-collapsed` before paint |
| collapsed rules | `courses.css:868-872` | the sliver being replaced: the `flex-basis` rule at `:868` plus **three rules across four selectors** at `:869-872` (heading + list share one rule; toggle; bar) |
| `data-unit-shell` | `_unit_shell.html:2` | existing attribute, present **only** on the student shell — the scoping hook |

The state hook (`html.unit-tree-collapsed`), the storage key, and the pre-paint script are **reused
unchanged**. This is a presentation + one-new-control change: no Python, no models, no migrations, no
new views.

### Scoping — the constraint every new rule obeys

`html.unit-tree-collapsed` is **global, not page-scoped**. `templates/base.html:34-41` sets it from a
single global `libli_unit_tree_collapsed` key on *every* page extending `base.html`. And
`review_submission.html:24` renders `<div class="unit-shell review-shell">` — the same wrapper class.

Therefore a rule like `html.unit-tree-collapsed .unit-shell { margin-left: -2.4rem }` would shift the
teacher review page 38.4px left, with no pin filling the lane, for any teacher who had ever collapsed
the tree on a student page. The same hazard applies to the prose cap on every page rendering
`.el--text` or `.callout` (the builder preview, quiz review).

**Every new rule in this change is scoped `html.unit-tree-collapsed [data-unit-shell] …`.**
`_unit_shell.html:2` carries `data-unit-shell`; `review_submission.html:24` does not. The hook already
exists and is additive — nothing needs renaming.

### New component: `.unit-toc-pin`

A `<button>` rendered in `templates/courses/_unit_shell.html` as the **first child of `.unit-shell`**,
before `.unit-tree`, so it leads the tab order when visible.

```html
<button type="button" class="unit-toc-pin" data-unit-tree-pin
        aria-controls="unit-tree" aria-expanded="false"
        aria-label="{% trans 'Show course contents' %}"
        title="{% trans 'Show course contents' %}">
  <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">…</svg>
</button>
```

- **Server-rendered, not JS-created.** The pre-paint script has already set
  `html.unit-tree-collapsed` before first paint, so a CSS-only reveal is flash-free.
- **Its own attribute, `data-unit-tree-pin`** — deliberately *not* a second `[data-unit-tree-toggle]`.
  Two elements sharing that attribute would break `document.querySelector` in `unit_nav.js:49` (it
  would silently bind only the first) and make every existing Playwright
  `page.locator("[data-unit-tree-toggle]")` a strict-mode violation.
- **`aria-controls="unit-tree"`** requires adding `id="unit-tree"` to `<nav class="unit-tree">`.
  `_unit_tree.html` is included exactly once per page, so the id is unique.
- **The label is static**, and carries **no** `data-label-expand` / `data-label-collapse` pair. Under
  this design each control is visible in exactly one state — the pin only while collapsed, the `‹`
  only while expanded — so neither ever needs to swap its label. `unit_nav.js` still syncs
  `aria-expanded` on both (see Behaviour); only the label swap is unnecessary.

  `.unit-tree__toggle` **keeps** its existing `data-label-*` attributes and swap logic untouched.
  That swap is now only ever observed in its expanded form, so it is technically dead — leaving it is
  a deliberate zero-churn choice for a state this change does not otherwise touch, not an oversight.
- **Icon**: an inline `currentColor` line SVG carrying the shared `.icon` class, per the repo's icon
  convention (monochrome SVG, never emoji, never a sprite `<use>`). The mark is a table-of-contents
  glyph — three horizontal rules, each led by a dot — **not** `☰`. `☰` already means "primary menu"
  in the app header (`base.html:76`) and "open the mobile contents drawer" in the unit footer
  (`_unit_footer.html:32`); a third meaning on the same page would muddy both.

### Geometry

**The lane is 2.4rem (38.4px) — exactly the width of the sliver it replaces.** That equality is
deliberate: it makes the narrow-desktop branch (below) width-neutral against today rather than 3.2px
worse. 2.4rem is a **fixed geometric constant**: the `-2.4rem` overhang, the 1040px breakpoint
derivation and the 920px content figure all depend on it. It is not a visual-taste parameter (see
"Visual verification").

**Collapsed** (`html.unit-tree-collapsed [data-unit-shell]`, ≥641px):

- `.unit-tree { display: none }` — the rail leaves the flow completely.
- `.unit-toc-pin` becomes visible: `flex: 0 0 2.4rem; position: sticky; top: .6rem; z-index: 21`. It
  starts where the rail's header bar used to be and rides up as the student scrolls, bounded by
  `.unit-shell`.
  - `align-self` is **not** declared — `.unit-shell` is already `align-items: flex-start`
    (`courses.css:535`), so it would be a no-op that reads as though it were doing work.
  - `z-index: 21` is one above `.unit-foot`'s 20 (`courses.css:670`). The two cannot overlap today
    for a structural reason — the foot lives inside `.unit-shell__main`, the pin in its own sibling
    flex column, so they are horizontally disjoint — but `.unit-shell__main` sets no `z-index` and
    so creates no stacking context, meaning the foot competes in the root context. The explicit
    `z-index` makes the guarantee survive any future full-bleed or negative-margin content.

| Viewport | Rule | Main column | vs today's collapsed |
|---|---|---|---|
| ≥1040px | `[data-unit-shell] { margin-left: -2.4rem }` | 920px | +38.4px |
| 641–1039px | no negative margin | container − 2.4rem | **exactly equal** |

At 900px, for example: `.app-main` is 900 − 40 = 860px of content box, the lane takes 38.4px, the
main column gets 821.6px — bit-identical to today's sliver layout. The narrow branch gains no width;
it gains the removal of the stripe and the prose cap.

**Breakpoint derivation.** `.app-main` is `max-width: 960px` with `padding-inline: var(--space-5)` =
20px (`app.css:34`, `tokens.css:76`), so the shell's left edge sits at `(W − 960)/2 + 20`, where `W`
is the **layout viewport width** — the same quantity `@media (min-width: …)` tests, which excludes a
classic scrollbar. Overhanging 2.4rem leftward requires `(W − 960)/2 + 20 ≥ 38.4`, i.e. `W ≥ 997px`.
The breakpoint is set at **1040px**; the ~43px of slack is what absorbs scrollbar-width variation and
sub-pixel rounding, so the derivation never sits on its own boundary.

**Interaction with `.unit-shell`'s existing box.** `courses.css:535` sets `margin: 0 auto` and
`max-width: 72rem`. The new rule overrides only the `margin-left` longhand; `margin-right: auto` is
intentionally left alone, since the box already fills `.app-main`'s content width and the auto margin
has nothing to distribute. `max-width: 72rem` (1152px) is never binding — `.app-main`'s 920px content
box is always the smaller constraint. Specificity: `html.unit-tree-collapsed [data-unit-shell]` is
(0,3,1) against `.unit-shell`'s (0,1,0), so it wins regardless of source order.

**Verified precondition for the overhang**: no ancestor of `.unit-shell` sets `overflow: hidden`.
`reset.css`'s only such rule is on `.sr-only`; `.app-main` (`app.css:34`) sets none. A test pins this,
because a future `overflow` rule would silently amputate the only control that restores the tree.

**Expanded**: unchanged from today. `.unit-toc-pin` stays at its base `display: none` — `display`, not
`visibility`/`opacity`, so it leaves the tab order. The rail keeps its `‹`. `centerActive()`, the
sticky tree bar, the rail scrollbar styling and the active-row marker are untouched.

**Mobile (≤640px)**: the pin's base `display: none` already covers it, since the reveal lives inside
`@media (min-width: 641px)`. The footer drawer keeps that job.

**No transition.** `display: none` cannot be animated, and faking the slide is not worth the
complexity for a control used a handful of times per session.

### CSS shape

Representative, not exhaustive — but the selector *shape* below is normative:

```css
/* Base: inert until the collapsed state reveals it. The single positive override
   is the reveal inside the ≥641px query; there is no other rule that shows it. */
.unit-toc-pin { display: none; }

@media (min-width: 641px) {
  html.unit-tree-collapsed [data-unit-shell] > .unit-tree { display: none; }
  html.unit-tree-collapsed [data-unit-shell] > .unit-toc-pin {
    display: flex; align-items: center; justify-content: center;
    flex: 0 0 2.4rem;
    position: sticky; top: .6rem; z-index: 21;
  }
}

@media (min-width: 1040px) {
  html.unit-tree-collapsed [data-unit-shell] { margin-left: -2.4rem; }
}
```

### Content width

At 1440px:

| | Prose | Tables / media |
|---|---|---|
| Expanded (today, and unchanged by this change) | 648px | 648px |
| Collapsed (today, sliver) | 834px | 834px |
| **Collapsed (this change)** | **736px** | **872px** |

**The honest reading of that table**: collapsed prose becomes 98px *narrower* than it is today
(834 → 736). That is deliberate, and it is point 2 of the Purpose — 834px is ~125ch, which is the
readability problem being fixed, not a benefit being surrendered. An implementer who measures the
narrowing must not treat it as a bug.

The invariant that *does* hold: **nothing becomes narrower than the expanded state (648px)**, which is
what a student sees by default and what the vast majority see always. That is the constraint that
fixes the cap value from below; readability fixes it from above.

**The cap is 46rem** = 736px — `.lesson`'s own standalone `max-width` (`courses.css:181`), the measure
this repo already treats as correct for a lesson article. `.lesson` inside the shell overrides it to
`max-width: none` (`courses.css:537-538`); this reintroduces the same constant at element level, in
the collapsed state only.

**Mechanism — a prose allow-list, not cap-by-default.** Cap-by-default with a wide-element opt-out was
considered and rejected on inspection of the markup:

1. **The element root classes are heterogeneous.** `class="el el--*"` covers only text, math, image,
   video, iframe, table, filltable, gallery, tabs, twocolumn and questions. Callout renders
   `.callout`, spoiler `.spoiler`, stepper `.stepper`, mark-done `.markdone`, HTML `.html-el`,
   reveal-gate `.reveal-gate`, fill-gate `.fillgate`; switch-gate/switch-grid/guess-number come from
   `courses_extras.py` templatetags with their own names. An opt-out list against that surface is
   long and easy to miss an entry in.
2. **Failure modes are asymmetric.** A missed opt-out *breaks* layout — a wide table squeezed into
   46rem. A missed allow-list entry only leaves prose wider than ideal. The gentler failure belongs
   on the more error-prone list.

The allow-list also handles nesting for free. Only `spoiler`, `tabs` and `two_column` render nested
child elements (verified: `spoilerelement.html:7-9` calls `render_element`; `calloutelement.html` and
`stepperelement.html` do not). A `.el--text` inside a two-column column is already narrower than
46rem, so the cap is a harmless no-op at any depth — whereas cap-by-default would have had to detect
and exempt each container.

```css
@media (min-width: 641px) {
  html.unit-tree-collapsed [data-unit-shell] .el--text,
  html.unit-tree-collapsed [data-unit-shell] .callout,
  html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill),
  html.unit-tree-collapsed [data-unit-shell] .lesson-unit__head,
  html.unit-tree-collapsed [data-unit-shell] .unit-crumbs {
    max-width: 46rem;
  }
}
```

The `:not()` chain is required because the grid/spatial question variants co-occur with `.el--question`
on the same root element (`class="el el--question el--choicegrid"`), so they cannot be excluded by
omission.

**Left alignment needs no declaration.** `reset.css`'s `* { margin: 0 }` means these elements have no
auto margins to centre them, so a `max-width` alone leaves them flush left and the text's left edge
never moves when toggling. This is worth stating because the codebase does centre by default
elsewhere — `.quiz, .lesson { margin-inline: auto }` at `courses.css:180-181` — so the absence of
`margin-inline: 0` here is a verified fact, not an omission.

Explicitly **not** capped, and why: `.el--math` (a wide display equation must be free to use the
column or scroll rather than be squeezed), all tables/grids/media, and all containers.

The list is a starting point, not a claim of completeness. The frontend-design pass walks every
element type in the collapsed state and adds any that reads badly at full width; that visual sweep,
not this list, is the completeness mechanism.

### Behaviour

`unit_nav.js:48-67` currently closes `EXPAND`, `COLLAPSE` and `syncToggle` inside `if (toggle) { … }`.
That restructures as follows:

1. Look up `[data-unit-tree-toggle]` and `[data-unit-tree-pin]` **independently, each null-guarded**.
   Collect whichever exist into a list. If the list is empty, bind nothing and return — the review
   page and any future consumer of `unit_nav.js` must not throw.
2. `syncToggle(collapsed)` moves to module scope and **iterates the list**, setting `aria-expanded` on
   every control found. It applies the `data-label-*` swap only to controls that carry both
   attributes, so the pin's static label is left alone (this preserves today's
   `if (EXPAND && COLLAPSE)` guard at `unit_nav.js:51-56`, generalised per-control).
3. On click, in this exact order:
   a. flip `html.classList.toggle("unit-tree-collapsed")`;
   b. write `localStorage`;
   c. `syncToggle(collapsed)`;
   d. **move focus to the sibling control**;
   e. `centerActive()` when expanding.

   **The class flip must precede the focus move.** The sibling is `display: none` until the class
   changes, and `.focus()` on a `display: none` element is a silent no-op that drops focus to
   `<body>` — precisely the failure the focus move exists to prevent. The focus call is also guarded
   on the sibling existing.

The focus move is a requirement, not polish: whichever control was clicked becomes `display: none` in
the new state. Collapsing focuses `.unit-toc-pin`; expanding focuses `.unit-tree__toggle`.

`aria-expanded` describes the tree's state (`true` expanded, `false` collapsed) and must agree between
the two controls at all times, including on first paint — the pin ships `aria-expanded="false"` and
`syncToggle()` corrects both on boot from the actual `<html>` class.

## Data flow

No server state, no request. The full cycle:

```
first paint    base.html pre-paint  ──reads──▶ localStorage["libli_unit_tree_collapsed"]
                       │
                       └──sets──▶ html.unit-tree-collapsed        (GLOBAL — every page)
                                        │
                                        └─ scoped by [data-unit-shell] to the student unit page:
                                             ├──CSS──▶ .unit-tree      display:none
                                             ├──CSS──▶ .unit-toc-pin   revealed, sticky, 2.4rem lane
                                             ├──CSS──▶ [data-unit-shell]  margin-left:-2.4rem (≥1040px)
                                             └──CSS──▶ prose allow-list   max-width:46rem

boot           unit_nav.js ──binds──▶ [data-unit-tree-toggle] + [data-unit-tree-pin] (each optional)
                           ──syncs──▶ aria-expanded on every control found

click          toggle() ──flips──▶ html.unit-tree-collapsed
                        ──writes──▶ localStorage
                        ──syncs───▶ aria-expanded on both controls
                        ──moves───▶ focus to the sibling control   (after the flip)
                        ──calls───▶ centerActive()                 (expand only)
```

Persistence is per-browser and cross-page: the key is global, not per-course, exactly as today.

## Error handling

These are degradation modes, not exceptions. The first two are **different branches with different
outcomes** and must not be collapsed into one claim:

- **JavaScript disabled.** The pre-paint script never runs, so `html.unit-tree-collapsed` is never
  set: the tree renders expanded and `.unit-toc-pin` stays at its base `display: none`. No dead
  control is exposed. The in-rail `‹` is inert, exactly as it is today; this change neither fixes nor
  worsens that pre-existing state.
- **JS enabled but `unit_nav.js` fails** (404, parse error, throw). The pre-paint script is an inline
  block in `base.html` and is **independent of `unit_nav.js`**, so it still runs. If the student had
  previously collapsed the tree: the rail is `display: none`, the pin *is* visible, and nothing binds
  it — a dead pin, with the desktop rail unreachable (the mobile drawer trigger is `display: none`
  above 640px).

  This is **no worse than today** — today's sliver leaves the `‹` equally unbound and the tree equally
  stuck — and the student is not stranded: the breadcrumb course link (`_unit_crumbs.html:20`) reaches
  the course outline, and the prev/next footer links still navigate. Accepted as-is; the alternative
  (revealing the pin from JS, like `.unit-foot__contents`) would trade a rare dead control for a
  guaranteed flash on every collapsed page load.
- **`localStorage` unavailable** (private mode, disabled storage). Both the pre-paint script
  (`base.html:36-40`) and `store()` (`unit_nav.js:6-8`) already wrap access in `try/catch`. The toggle
  works for the session; the choice does not persist.
- **A future `overflow: hidden` on `body` or `.app-main`** would clip the pin where it overhangs at
  ≥1040px. Covered by a test rather than a comment.
- **A pin click during `centerActive()`'s smooth scroll.** `centerActive()` re-queries at call time
  and early-returns when collapsed (`unit_nav.js:26-38`), so a rapid collapse during an expand
  animation cannot act on a stale node.

## Testing

Per this repo's standing rule, every test below is **falsified** before it counts: delete or revert
the thing it guards and confirm it goes red. A test that cannot be made to fail is not coverage.

### Existing tests this change breaks (must be updated)

Enumerated by grepping `[data-unit-tree-toggle]` across `tests/`, which returns exactly five hits.
Three of them click the toggle to **expand** as well as collapse, and that second click lands on a
`display: none` element under this design — Playwright's actionability wait times out:

| Test | File:line | Expand click |
|---|---|---|
| `test_desktop_tree_collapse_persists` | `test_e2e_unit_nav.py:132` | `:160` |
| the re-centre-on-expand test | `test_e2e_unit_nav.py` | `:709`/`:714` |
| `test_centering_is_skipped_when_the_active_group_is_folded` | `test_e2e_unit_nav.py:842` | `:878` |

All three must be updated to click `[data-unit-tree-pin]` for the expand step. This is required, not
optional — and it is itself a signal: if any of the three still passes unmodified, the rail was not
actually removed.

The remaining hit, `:772` in `test_active_marker_is_strong_and_width_neutral`, calls `.focus()` on the
toggle while **expanded** and needs no change.

`tests/test_unit_nav_render.py`, `tests/test_unit_tree_long_titles.py` and `tests/test_courses_views.py`
were grepped for assumptions about the collapsed markup (`unit-tree-collapsed`, `flex-basis`, the
sliver rules) and hold none, so **no edits are expected in them beyond the positive addition below**.
If implementation finds otherwise, that is a finding to report, not a silent fix.

### New coverage

Test 8 (render) lands in `tests/test_unit_nav_render.py`. Tests 1–7 land in `tests/test_e2e_unit_nav.py`.

1. **e2e — the rail is gone, the pin is the way back.** Collapse via `‹`; assert `.unit-tree` is not
   visible and `[data-unit-tree-pin]` is; click the pin; assert the rail returns. Falsified by
   reverting `.unit-tree { display: none }` to `flex-basis: 2.4rem`.
2. **e2e — persistence.** Collapsed state survives a reload via the pre-paint path, with the pin
   visible and the rail absent on the restored page.
3. **e2e — focus moves.** After collapsing, `document.activeElement` is the pin; after expanding, it
   is `.unit-tree__toggle`. Falsified by deleting the focus-move lines.
4. **e2e — width is actually reclaimed (≥1040px only).** Set a 1440×900 viewport; measure the
   article's bounding width collapsed vs expanded; assert it grew by ~38px + the removed rail. This
   is the test for the *purpose* of the feature. It must **not** run in the 641–1039px band, where
   the design is deliberately width-neutral and this assertion would correctly fail.
5. **e2e — the narrow band is width-neutral, not worse.** At a 900×900 viewport, assert the main
   column's collapsed width equals what today's sliver produces (container − 38.4px), so the
   3.2px-regression failure mode is pinned rather than merely reasoned about.
6. **e2e — the pin is not clipped.** At 1440px, assert the pin's `getBoundingClientRect()` lies inside
   the viewport and is hit-testable at its centre (`document.elementFromPoint` resolves to the button
   or a descendant). Guards against a future ancestor `overflow: hidden` and against the overhang
   pushing the control off-screen near the breakpoint.
7. **e2e — prose is capped, tables are not.** Requires a unit containing **both** a text element and
   a table element. No existing helper in `test_e2e_unit_nav.py` seeds content elements
   (`_seed_nav_course`, `_seed_traversal_course`, `_seed_grouped_course` build structure only), so a
   new seed helper is **part of the deliverable**, built on `add_element()` from `tests/factories.py`
   with `TextElement` + `TableElement` instances (see `tests/test_align_render.py` for the idiom).
   At a 1440px viewport, assert the text element's width is ≤736px (46rem) and the table element's
   is >736px.
8. **Render test** — the pin is present in the DOM on both the lesson page and the quiz page, carries
   `aria-expanded`, and its `aria-controls="unit-tree"` target exists exactly once.
9. **Non-regression — the review page is untouched.** Load
   `/manage/courses/<slug>/review/<submission_pk>/` (seed via `make_review_submission()` in
   `tests/factories.py`) with `localStorage["libli_unit_tree_collapsed"] = "1"` pre-set, and assert
   the review shell's bounding box is identical to the not-collapsed case. This is the guard for the
   Scope promise, and for the exact silent-leak failure that scoping on `[data-unit-shell]` prevents.
   Falsified by widening any new selector from `[data-unit-shell]` to `.unit-shell`.

Both `aria-expanded` values agreeing after each toggle is asserted inside tests 1 and 3 rather than as
a separate case.

**Viewport discipline.** Tests 4–7 and 9 set an explicit viewport. Playwright's 1280×720 default
happens to sit above the 1040px breakpoint, but relying on a default for a breakpoint-sensitive
assertion is how a test silently stops testing what it names.

### i18n

One new translatable string, `"Show course contents"`, used for both `aria-label` and `title`.

`_unit_tree.html:7` already ships `"Expand contents"` for the same conceptual action, so this is a
**recorded, deliberate duplication**: the pin appears outside the rail with no adjacent "Contents"
heading to give "Expand contents" its referent, so it needs the explicit noun. The two Polish
translations must be kept consistent in tone; a reviewer should treat divergence as a bug.

Both `pl` and `en` catalogs get entries and the `.mo` files are regenerated. `makemessages` is run as
`-l pl -l en --no-obsolete`; any `#, fuzzy` marker it pre-fills must be cleared together with its
`#| msgid` line, or a wrong translation ships silently.

### Visual verification

The `frontend-design` skill runs once the mechanics pass. Its remit is **colour, weight, iconography,
border/radius, and resting/hover/focus/active states, within the fixed 2.4rem lane**.

It may **not** change the lane width. 2.4rem is load-bearing for the `-2.4rem` overhang, the 1040px
breakpoint derivation, the 920px content figure and test 5's equality assertion; changing it without
re-deriving all four would silently invalidate them.

Screenshots in light **and** dark, judged separately, at 1440px and ~900px (the reserved-lane branch),
in both collapsed and expanded states.
