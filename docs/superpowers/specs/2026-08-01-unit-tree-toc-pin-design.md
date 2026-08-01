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
   ~834px, a markedly longer measure than this repo's own established one. Capping prose back to
   `.lesson`'s standalone `max-width: 46rem` (`courses.css:181`) is a readability *fix* this change
   delivers, not a tax it pays.

   The justification is deliberately "return to the repo's existing measure", **not** "reach the
   classic 60–80ch range": 46rem is still ~110ch at this font size, so a ch-based rationale would
   argue for a much tighter cap than 46rem and would not survive contact with the constant actually
   chosen. Do not tighten the cap on ch grounds.
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
| `.unit-tree` | `courses.css:540` | the 14rem rail; sticky at `top: 0`, `overflow-y: auto` |
| `.unit-tree__toggle` | `_unit_tree.html:5-8` | the in-rail `‹` collapse control |
| `unit_nav.js` | `courses/static/courses/js/unit_nav.js:48-67` | binds `[data-unit-tree-toggle]`, writes `localStorage`, calls `centerActive()` |
| pre-paint restore | `templates/base.html:34-41` | reads `libli_unit_tree_collapsed`, sets `html.unit-tree-collapsed` before paint |
| collapsed rules | `courses.css:868-872` | the sliver: **four rules across five selectors** — `flex-basis` at `:868`, then heading + list (one rule, two selectors), toggle, bar |
| `data-unit-shell` | `_unit_shell.html:2` | existing attribute, present **only** on the student shell — the scoping hook |
| `.unit-strip` | `courses.css:1659`, rendered by `lesson_unit.html:53` / `quiz_unit.html:10` | full-width sibling **above** the shell (tags disclosure + staff Edit link) |

The state hook (`html.unit-tree-collapsed`), the storage key, and the pre-paint script are **reused
unchanged**. This is a presentation + one-new-control change: no Python, no models, no migrations, no
new views.

**`courses.css:866-873` is deleted in full — the comment at `:866`, the `@media (min-width: 641px)`
wrapper opened at `:867`, the rules at `:868-872`, and the closing brace at `:873`.** Deleting only
`:868-872` would leave an empty media block plus a comment describing rules that no longer exist —
and that stale comment text would then collide with test 11's source guard. Either delete the whole
block or replace it in place with the new collapsed rules.

This is normative, not descriptive. Those five selectors are unscoped (`html.unit-tree-collapsed .unit-tree`, `…__heading`, `…__list`, `…__toggle`, `…__bar`) —
exactly the pattern the Scoping section forbids — and leaving them would be **behaviourally
invisible**: `display: none` removes the rail's box entirely, so `flex-basis`, `transform` and the bar
padding all become inert regardless of specificity. (They do not lose a cascade contest; `display` and
`flex-basis` are different properties and never compete. The conclusion is the same, but the mechanism
matters — a reader who believes this is a specificity race might conclude a lower-specificity new rule
would fail to hide the rail.) Because nothing behavioural can detect the leftovers, **test 11 is a
source-level guard** — see Testing.

The deletion **includes `:871`'s `transform: scaleX(-1)`**: the `‹` is now only ever rendered in the
expanded state, so the flip has nothing left to indicate. That is orthogonal to the decision below to
leave the JS `data-label-*` swap alone.

### Scoping — the constraint every new rule obeys

`html.unit-tree-collapsed` is **global, not page-scoped**. `templates/base.html:34-41` sets it from a
single global `libli_unit_tree_collapsed` key on *every* page extending `base.html`. And
`review_submission.html:24` renders `<div class="unit-shell review-shell">` — the same wrapper class.

There are **two distinct hazards with two different victim pages**, and conflating them produces
tests that cannot fail:

- **The `margin-inline-start` hazard → the review page.** A rule like
  `html.unit-tree-collapsed .unit-shell { margin-inline-start: -2.4rem }` would shift
  `review_submission.html` 38.4px left, with no pin filling the lane, for any teacher who had ever
  collapsed the tree on a student page.
- **The prose-cap hazard → *not* the review page.** Verified: `review_submission.html` never calls
  `render_element`. It renders `<article class="card review">` with `.question__stem` and
  `.review__answer` (`:83-95`; the `<div data-question>` wrapper at `:87`, the stem at `:88`, the
  answer branches at `:91-93`) — **no `.el--text`, no `.el--question`, no `.callout`, no
  `.unit-crumbs`, none of the eight capped selectors**. Widening every prose-cap selector to
  `.unit-shell` would change that page by exactly zero pixels.

  The confirmed page that renders the full element surface outside `[data-unit-shell]` is
  `templates/courses/manage/editor/_preview.html:16` (`{% render_element el %}` in the builder's live
  preview). `courses.css:179`'s own comment also flags `quiz_results.html` as rendering
  `.el--question`, though that page's markup shows no `el--` class directly — confirm at
  implementation rather than trusting either the comment or this sentence.

Because the prose-cap family has no cheap behavioural victim, **its guard is a source assertion, not
a browser test** (test 11). That is deliberate: a behavioural test on the builder preview would cost a
staff login and a whole new fixture to assert something a two-line regex proves deterministically.

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
  `_unit_tree.html` is included exactly once per page (the mobile drawer inlines its own `<ul>` rather
  than re-including the partial), so the id is unique. **`aria-controls="unit-tree"` is also added to
  the existing `.unit-tree__toggle`**, which has `aria-expanded` but no `aria-controls` today: two
  controls that must agree on `aria-expanded` should not describe different disclosure relationships.
  This is the one deliberate exception to the otherwise zero-churn treatment of the expanded state —
  it is a single additive attribute with no behavioural effect.

  **Whenever the pin is visible, its `aria-controls` target is `display: none`** and therefore absent
  from the accessibility tree. This is intended and correct for a disclosure pattern — it is exactly
  what `aria-expanded="false"` announces — but it is a *new* condition, since today's sliver kept the
  rail in the tree. Stated here so an auditor does not "fix" it by switching to `hidden`/`inert` or by
  dropping the attribute.
- **The label is static**, and carries **no** `data-label-expand` / `data-label-collapse` pair. Under
  this design each control is visible in exactly one state — the pin only while collapsed, the `‹`
  only while expanded — so neither ever needs to swap its label. `unit_nav.js` still syncs
  `aria-expanded` on both (see Behaviour); only the label swap is unnecessary.

  `.unit-tree__toggle` **keeps** its existing `data-label-*` attributes and swap logic untouched.
  That swap is now only ever observed in its expanded form, so it is technically dead — leaving it is
  a deliberate zero-churn choice, not an oversight.
- **Icon**: an inline `currentColor` line SVG carrying the shared `.icon` class, per the repo's icon
  convention (monochrome SVG, never emoji, never a sprite `<use>`). The mark is a table-of-contents
  glyph — three horizontal rules, each led by a dot — **not** `☰`. `☰` already means "primary menu"
  in the app header (`base.html:76`) and "open the mobile contents drawer" in the unit footer
  (`_unit_footer.html:32`); a third meaning on the same page would muddy both.

### Geometry

**The lane is 2.4rem (38.4px) — exactly the width of the sliver it replaces.** That equality is
deliberate: it makes the narrow-desktop branch (below) width-neutral against today rather than 3.2px
worse. 2.4rem is a **fixed geometric constant**: the `-2.4rem` overhang, the 1040px breakpoint
derivation, the 920px content figure and tests 4, 5 and 10 all depend on it. It is not a visual-taste
parameter (see "Visual verification").

**Collapsed** (`html.unit-tree-collapsed [data-unit-shell]`, ≥641px):

- `.unit-tree { display: none }` — the rail leaves the flow completely.
- `.unit-toc-pin` becomes visible: `flex: 0 0 2.4rem; min-height: 2.4rem; position: sticky;
  top: .6rem; z-index: 21`.
  - **`min-height: 2.4rem` is required, not decorative.** `flex: 0 0 2.4rem` fixes only the *main*
    size (width). The cross size would otherwise fall out of the content — `.icon` is `1em × 1em`
    (`app.css:108-113`) on the inherited 16px body font, plus UA button padding — giving a ~38×20px
    control, under the 24×24 minimum target size. `min-height` makes the button square in its lane
    and gives block-size an owner.
  - **`.unit-shell`'s `align-items: flex-start` (`courses.css:535`) is a load-bearing precondition,
    not merely a reason to omit `align-self`.** Under the flex default (`stretch`) the pin would be
    stretched to the shell's full height, leaving `position: sticky` no room to move and silently
    killing the entire treatment. `align-self` is not declared *because* the container already
    supplies `flex-start`; if that ever changes, the pin needs `align-self: flex-start` explicitly.
  - **Sticky offsets.** As a flex item under `align-items: flex-start`, the pin's *static* position is
    the top of `.unit-shell` — exactly where the rail's top edge is, so at scroll 0 the pin and the
    rail start at the same y. `top: .6rem` is the **stuck** offset only, and is deliberately not the
    rail's `top: 0` (`courses.css:541`): the rail is a full-height panel that reads correctly flush to
    the viewport edge, whereas a small free-floating button flush to that edge reads as clipped. The
    two controls are never co-visible, so the 9.6px difference is unobservable.
  - `z-index: 21` is one above `.unit-foot`'s 20 (`courses.css:670`). The two cannot overlap today
    for a structural reason — the foot lives inside `.unit-shell__main`, the pin in its own sibling
    flex column, so they are horizontally disjoint — but `.unit-shell__main` sets no `z-index` and
    so creates no stacking context, meaning the foot competes in the root context. The explicit
    `z-index` makes the guarantee survive any future full-bleed or negative-margin content.

| Viewport | Rule | Main column | vs today's collapsed |
|---|---|---|---|
| ≥1040px | `[data-unit-shell] { margin-inline-start: -2.4rem }` | 920px | +38.4px |
| 641–1039px | no negative margin | container − 2.4rem | **exactly equal** |

The narrow branch gains no width; it gains the removal of the stripe and the prose cap.

**Breakpoint derivation.** `.app-main` is `max-width: 960px` with `padding-inline: var(--space-5)` =
20px (`app.css:34`, `tokens.css:76`). Those constants apply here only because `base.html:147` is
`<main class="{% block main_class %}app-main{% endblock %}">` and **neither `lesson_unit.html` nor
`quiz_unit.html` overrides `main_class`** — the derivation is page-specific, not structural. Given
that, the shell's left edge sits at `(W − 960)/2 + 20`, where `W`
is the **layout viewport width** — the same quantity `@media (min-width: …)` tests, which excludes a
classic scrollbar. Overhanging 2.4rem leftward requires `(W − 960)/2 + 20 ≥ 38.4`, i.e. `W ≥ 997px`.
The breakpoint is set at **1040px**; the ~43px of slack is what absorbs scrollbar-width variation and
sub-pixel rounding, so the derivation never sits on its own boundary.

Every worked figure below is quoted in **layout-viewport** terms. A Playwright viewport of 900px
yields roughly an 885px layout viewport once Chromium's classic scrollbar is subtracted, so tests
derive container widths by measuring at runtime rather than hard-coding them.

**Interaction with `.unit-strip`** (the full-width sibling rendered directly above the shell). This
is worth stating because the negative margin makes it look like a misalignment hazard, and it is not:

- **≥1040px collapsed** — the shell's box starts 38.4px left of the strip, but `.unit-shell` paints
  nothing (no background, no border, `courses.css:535`), and the pin exactly fills that overhang. So
  `.unit-shell__main` begins at the strip's left edge: the content column and the strip align
  **perfectly**, which is better than today.
- **641–1039px collapsed** — the main column is indented 38.4px relative to the strip. That is
  **exactly today's behaviour** (the sliver occupies the same 38.4px), so it is not a regression; and
  the expanded state indents it 224px, so an indented main column is this page's normal look.

No rule is therefore needed on `.unit-strip`. Test 10 pins the ≥1040px alignment so a future change
to either box cannot silently break it.

**Interaction with `.unit-shell`'s existing box.** `courses.css:535` sets `margin: 0 auto` and
`max-width: 72rem`. The new rule overrides only the inline-start margin; the inline-end `auto` is
intentionally left alone, since the box already fills `.app-main`'s content width and the auto margin
has nothing to distribute. `max-width: 72rem` (1152px) is never binding — `.app-main`'s 920px content
box is always the smaller constraint. Specificity: `html.unit-tree-collapsed [data-unit-shell]` is
(0,3,1) against `.unit-shell`'s (0,1,0), so it wins regardless of source order.

**The property is `margin-inline-start`, not `margin-left`.** This codebase is consistently logical —
`margin-inline: auto` (`courses.css:180-181`), `margin-inline: 0` (`:538`), `padding-inline`
(`app.css:34`), `margin-block` on `.unit-strip` — and a lone physical longhand would be a silent
inconsistency. Logical and physical longhands cascade together and are resolved at computed-value
time, so the higher-specificity rule wins over `margin: 0 auto` either way; the choice is idiom, not
mechanism. The app ships `pl` and `en`, both LTR, so the two are equivalent today.

**Verified precondition for the overhang**: no ancestor of `.unit-shell` sets `overflow: hidden`.
`reset.css`'s only such rule is on `.sr-only`; `.app-main` (`app.css:34`) sets none. A test pins this,
because a future `overflow` rule would silently amputate the only control that restores the tree.

**Expanded**: visually and structurally as today — the rail keeps its `‹`, the sticky tree bar, the
scrollbar styling and the active-row marker. **One behaviour does change, and it is accepted rather
than unnoticed:**

> **The rail's scroll position no longer survives a collapse → expand round trip.** `.unit-tree` is
> `overflow-y: auto` (`courses.css:540-542`). Today's sliver keeps the box alive at
> `flex-basis: 2.4rem`, so `scrollTop` persists; `display: none` destroys the scroll box, and on
> re-display `scrollTop` is 0.
>
> `centerActive()` masks this in the ordinary case — it runs on expand and scrolls the active unit to
> centre, overriding whatever `scrollTop` was anyway. It does **not** mask it on its bail path, when
> the active row is not visible because the student folded the group containing it
> (`unit_nav.js:38`; the case `test_centering_is_skipped_when_the_active_group_is_folded` exercises).
> In exactly that path the rail lands at scroll-top where today it would have held position.
>
> **Decision: accept, do not add `scrollTop` save/restore.** The affected path requires the student to
> have manually folded the group holding their current unit *and* then collapsed and re-expanded the
> rail; group folding does not persist across loads (it is re-derived from `contains_current` each
> render), so the window is narrow and self-inflicted. Restoring a saved offset would also fight
> `centerActive()` on every other path. This paragraph exists so the reset is a recorded consequence,
> not a bug report waiting to happen.

**Mobile (≤640px)**: the pin's base `display: none` already covers it, since the reveal lives inside
`@media (min-width: 641px)`. The footer drawer keeps that job.

**No transition.** `display: none` cannot be animated, and faking the slide is not worth the
complexity for a control used a handful of times per session.

### CSS shape

The selector *shape* below is normative; the visual declarations are not exhaustive.

```css
/* Base: inert until the collapsed state reveals it. The single positive override
   is the reveal inside the ≥641px query; there is no other rule that shows it. */
.unit-toc-pin { display: none; }

@media (min-width: 641px) {
  html.unit-tree-collapsed [data-unit-shell] > .unit-tree { display: none; }
  html.unit-tree-collapsed [data-unit-shell] > .unit-toc-pin {
    display: flex; align-items: center; justify-content: center;
    flex: 0 0 2.4rem; min-height: 2.4rem;
    position: sticky; top: .6rem; z-index: 21;
  }
}

@media (min-width: 1040px) {
  html.unit-tree-collapsed [data-unit-shell] { margin-inline-start: -2.4rem; }
}
```

**Every selector above contains `[data-unit-shell]`. Test 11 asserts that mechanically** — it is the
only guard the prose-cap family has (see Scoping).

### Content width

**The three rows have two different domains — do not read the table as one.** Rows 1 and 2 hold at any
layout viewport ≥1000px, where `.app-main`'s 960px cap binds. Row 3 additionally needs the negative
margin, which only applies at **≥1040px**:

| | Prose | Tables / media | Domain |
|---|---|---|---|
| Expanded (today, and unchanged by this change) | 648px | 648px | ≥1000px |
| Collapsed (today, sliver) | 834px | 834px | ≥1000px |
| **Collapsed (this change)** | **736px** | **872px** | **≥1040px** |

In the **1000–1039px sub-band** the cap binds but there is no overhang, so the main column is 881.6px:
prose 736px, tables/media **833.6px** — not 872px. That band is width-neutral against today's sliver
(833.6px both ways), exactly as the geometry table states for 641–1039px.

All figures below are the **border box**. `box-sizing: border-box` is global (`reset.css:2`), and
`.quiz .el--question` / `.lesson .el--question` carry `padding: var(--space-5)` (20px) plus a 1px
border (`courses.css:184-191`), so a capped question card holds **694px of text** where a capped
`.el--text` holds 736px. Border boxes align; text right-edges do not. The visual sweep therefore
judges two prose measures, not one.

**The honest reading of that table**: collapsed prose becomes 98px *narrower* than it is today
(834 → 736). That is deliberate, and it is point 2 of the Purpose — 834px is ~125ch, which is the
readability problem being fixed, not a benefit being surrendered. An implementer who measures the
narrowing must not treat it as a bug.

The invariant that *does* hold: **at any viewport, the collapsed measure is never smaller than the
expanded measure at that same viewport** (648px expanded vs ≥736px collapsed above 1000px). It is
stated per-viewport rather than as a universal 648px floor, because below ~1000px the expanded measure
is smaller. That constraint fixes the cap from below; readability fixes it from above.

**The cap is 46rem** = 736px — `.lesson`'s own standalone `max-width` (`courses.css:181`), the measure
this repo already treats as correct for a lesson article. `.lesson` inside the shell overrides it to
`max-width: none` (`courses.css:537-538`); this reintroduces the same constant at element level, in
the collapsed state only.

**Mechanism — a prose allow-list, not cap-by-default.** Cap-by-default with a wide-element opt-out was
considered and rejected on inspection of the markup:

1. **The element root classes are heterogeneous.** `class="el el--*"` covers text, math, image,
   video, iframe, table, filltable, gallery, tabs, twocolumn and questions (including the
   co-occurring variant classes `el--choicegrid`, `el--multigrid`, `el--dragimage`, `el--matchpair`,
   `el--dragfill` and `el--fillblank`). But callout's *root* is `.callout` (`calloutelement.html:2`),
   spoiler's is `.spoiler`, stepper's `.stepper`, mark-done's `.markdone`, HTML's `.html-el`,
   reveal-gate's `.reveal-gate`, fill-gate's `.fillgate`; switch-gate/switch-grid/guess-number come
   from `courses_extras.py` templatetags with their own names.

   Callout and spoiler *bodies* both carry `el el--text` (`calloutelement.html:7`,
   `spoilerelement.html:12`), but they land differently, because `.callout` is on the allow-list and
   `.spoiler` deliberately is not. The callout body is genuinely **double-capped and inert** — its
   container is already at 46rem, so the inner cap is unreachable. The spoiler body is capped
   **once, at 736px, inside an 872px `<details class="spoiler">`** — the same live behaviour described
   for spoiler children under "Nesting" below, not an inert no-op.

   An opt-out list against that root surface is long and easy to miss an entry in.
2. **Failure modes are asymmetric.** A missed opt-out *breaks* layout — a wide table squeezed into
   46rem. A missed allow-list entry only leaves prose wider than ideal. The gentler failure belongs
   on the more error-prone list.

```css
@media (min-width: 641px) {
  html.unit-tree-collapsed [data-unit-shell] .el--text,
  html.unit-tree-collapsed [data-unit-shell] .callout,
  html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill),
  html.unit-tree-collapsed [data-unit-shell] .lesson-unit__head,
  html.unit-tree-collapsed [data-unit-shell] .lesson-unit__title,
  html.unit-tree-collapsed [data-unit-shell] [data-quiz-preview-notice],
  html.unit-tree-collapsed [data-unit-shell] .quiz-finish,
  html.unit-tree-collapsed [data-unit-shell] .unit-crumbs {
    max-width: 46rem;
  }
}
```

Notes on that list:

- The `:not()` chain is required because the grid/spatial variants co-occur with `.el--question` on
  the same root (`class="el el--question el--choicegrid"`), so they cannot be excluded by omission.
- **`.el--fillblank` is deliberately absent from the `:not()` chain, i.e. deliberately capped.** It is
  prose with inline inputs, unlike the five grid/spatial variants that need the width.
- **Three entries exist for the quiz page.** The lesson wraps its `<h1>` in `.lesson-unit__head`
  (`_lesson_article.html:6`), but `_quiz_article.html:5` renders a bare
  `<h1 class="lesson-unit__title">` as a direct child of `.quiz`, `:20` renders the previewer banner,
  and `.quiz .quiz-finish` (`courses.css:211-215`) carries a **painted** `border-top`. Without these
  the quiz page's title, banner and finish divider would run 872px while every question above them
  stopped at 736px — a ragged edge, and in `.quiz-finish`'s case a literal rule drawn 136px wider
  than the content it separates. Capping the title is a harmless no-op on the lesson page, where it
  already sits inside the capped head.

**Nesting.** Containers that hold other elements are *not* capped, so they span 872px while the cap
still reaches their prose descendants through the descendant combinator. There are **four**, and the
fourth is easy to miss:

- **`two_column`** — the column is already narrower than 46rem, so the cap is a genuine no-op inside.
- **`spoiler`** and **`tabs`** — uncapped at 872px, so the cap *does* apply to nested prose, yielding
  736px text inside an 872px container. Intended, but a live behaviour rather than a no-op.
- **`.slideshow-deck`** — a **JS-constructed** container (`slideshow.js:40-46` builds it and moves the
  slides into it) with `border`, `border-radius`, `background` and `box-shadow`
  (`courses.css:249-256`), plus `padding: var(--space-6)` on its slides (`:263-271`). It behaves
  exactly like spoiler/tabs: 736px prose inside a visibly bordered card.

  **The enumeration of nesting containers was made from templates, so it structurally cannot find
  JS-constructed ones.** That is why this fourth entry was missed on the first two passes, and it is
  recorded here so a future reader does not trust a template grep to be complete.

The deck itself stays uncapped: it holds arbitrary slide content including tables, so capping it would
reintroduce the squeeze the allow-list exists to avoid. All four containers are on the visual sweep
list.

**Left alignment needs no declaration.** `reset.css`'s `* { margin: 0 }` means these elements have no
auto margins to centre them, so a `max-width` alone leaves them flush left and the text's left edge
never moves when toggling. This is worth stating because the codebase does centre by default
elsewhere — `.quiz, .lesson { margin-inline: auto }` at `courses.css:180-181` — so the absence of
`margin-inline: 0` here is a verified fact, not an omission.

**Block notes are an open visual question, deliberately deferred to the sweep.** `notes/_block_notes.html`
renders inside every `<section class="lesson-block">` (`_lesson_article.html:40`), which stays 872px.
`.block-notes__handle` is `margin-left: auto` (`notes/css/notes.css:51-58`) — tucked to the block's
right edge — so under a 736px-capped text element the handle floats ~136px right of the prose it
annotates. Two candidate resolutions: cap `.block-notes` too (aligns the handle with prose, but
misaligns it under a full-width table), or leave it anchored to the block (consistent with today, but
visually detached from capped prose). **The frontend-design sweep decides this with screenshots and
records the choice**; it is explicitly in that pass's remit.

**Unanchored notes are the same deferred question.** `_lesson_article.html:45` includes
`notes/_unanchored.html` as the last child of `<article class="lesson">` — outside every
`.lesson-block`, so it is a prose surface that runs the full 872px directly beneath 736px-capped
prose. It is deferred to the same sweep decision as `.block-notes`, and appears on the sweep's
coverage list.

Explicitly **not** capped, and why: `.el--math` (a wide display equation must be free to use the
column or scroll rather than be squeezed), all tables/grids/media, and all four containers.

The list is a starting point, not a claim of completeness. The visual sweep, not this list, is the
completeness mechanism.

### Behaviour

`unit_nav.js:48-67` currently closes `EXPAND`, `COLLAPSE` and `syncToggle` inside `if (toggle) { … }`.
That restructures as follows:

1. Look up `[data-unit-tree-toggle]` and `[data-unit-tree-pin]` **independently, each null-guarded**,
   and collect whichever exist. If the list is empty, **skip the toggle binding and fall through** —
   keep the guard local, exactly as today's `if (toggle) { … }` block does.

   **It must not `return`.** `unit_nav.js` is a single IIFE: `centerActive()` on load (`:69`) and the
   entire mobile-drawer wiring (`:71` onward) come *after* the toggle block, so an early `return`
   would silently unwire the mobile drawer — the precise hazard the file's own comment at `:11-15`
   already warns about for a different cause.

   (For the record, no current page needs that guard: `unit_nav.js` is loaded only by
   `lesson_unit.html:69` and `quiz_unit.html:25`, both of which render `_unit_shell.html`. The review
   page never loads it. The guard is for future consumers, not an existing one.)
2. `syncToggle(collapsed)` moves to module scope and **iterates the list**, setting `aria-expanded` on
   every control found. It applies the `data-label-*` swap only to controls that carry both
   attributes, so the pin's static label is left alone (this preserves today's
   `if (EXPAND && COLLAPSE)` guard at `unit_nav.js:51-56`, generalised per-control).

   The boot call (`unit_nav.js:66`, today `syncToggle(isCollapsed())` inside the guard) **moves out of
   the guard and runs unconditionally** — with an empty list it is a no-op, so the guard buys nothing
   and its absence removes one thing to reason about.
3. On click, in this exact order:
   a. flip `html.classList.toggle("unit-tree-collapsed")`;
   b. write `localStorage`;
   c. `syncToggle(collapsed)`;
   d. **move focus to the control that is now visible** — `[data-unit-tree-pin]` when collapsing,
      `[data-unit-tree-toggle]` when expanding — each null-guarded, and called as
      `el.focus({ preventScroll: true })`;
   e. `centerActive()` when expanding.

   **The target is named by attribute, not by the word "sibling".** Steps 1–2 deliberately generalise
   to a list of arbitrary length; "the sibling" would be undefined with one control present and
   ambiguous with more than two.

   **`preventScroll: true` is required, not defensive.** `HTMLElement.focus()` scrolls the element
   into view in every scrollable ancestor, including the window. On expand, focus lands on
   `.unit-tree__toggle` *inside* `.unit-tree` (`overflow-y: auto`) immediately before
   `centerActive()` issues its own smooth `tree.scrollTo(...)` — two scroll commands on one box, one
   of them a UA scroll. That UA scroll also does **not** pass through the `rail.scrollTo` monkeypatch
   that `test_centering_is_skipped_when_the_active_group_is_folded` counts, so without
   `preventScroll` the rail could move while the test still measures zero calls.

   **The class flip must precede the focus move.** The target is `display: none` until the class
   changes, and `.focus()` on a `display: none` element is a silent no-op that drops focus to
   `<body>` — precisely the failure the focus move exists to prevent.

The focus move is a requirement, not polish: whichever control was clicked becomes `display: none` in
the new state.

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
                                             ├──CSS──▶ [data-unit-shell]  margin-inline-start:-2.4rem (≥1040px)
                                             └──CSS──▶ prose allow-list   max-width:46rem

boot           unit_nav.js ──binds──▶ [data-unit-tree-toggle] + [data-unit-tree-pin] (each optional)
                           ──syncs──▶ aria-expanded on every control found (unconditional call)

click          toggle() ──flips──▶ html.unit-tree-collapsed
                        ──writes──▶ localStorage
                        ──syncs───▶ aria-expanded on both controls
                        ──moves───▶ focus to the now-visible control, preventScroll (after the flip)
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

| Test | `def` line | Collapse click | Expand click |
|---|---|---|---|
| `test_desktop_tree_collapse_persists` | `test_e2e_unit_nav.py:132` | `:147` | `:160` |
| `test_expanding_the_rail_recentres_the_active_unit` | `test_e2e_unit_nav.py:662` | `:710` | `:714` |
| `test_centering_is_skipped_when_the_active_group_is_folded` | `test_e2e_unit_nav.py:842` | `:878` | `:879` |

The last two share a shape: `:709` and `:877` assign a single `toggle` locator that is then used for
**both** clicks. In each, `toggle` stays bound to `[data-unit-tree-toggle]` for the collapse click and
a **separate** `[data-unit-tree-pin]` locator is introduced for the expand click. Do not repoint the
existing variable — that would send the collapse click at an element that is `display: none` while
expanded.

The remaining hit, `:772` in `test_active_marker_is_strong_and_width_neutral`, calls `.focus()` on the
toggle while **expanded** and needs no change.

`tests/test_unit_nav_render.py`, `tests/test_unit_tree_long_titles.py`, `tests/test_courses_views.py`
and `tests/test_consumption_css.py` were grepped for assumptions about the collapsed markup
(`unit-tree-collapsed`, `flex-basis`, the sliver rules) and hold none, so **no edits are expected in
them beyond the positive additions below**. In particular `test_consumption_css.py` — the existing
source guard over `courses.css`, and test 11's new home — anchors its regexes on `\.unit-strip\s*\{`
and `\.unit-strip\s+\.unit-tags\s*\{`, so neither the `:866-873` deletion nor the new blocks disturb
it. If implementation finds otherwise, that is a finding to report, not a silent fix.

### New coverage

File assignment: test 8 in `tests/test_unit_nav_render.py`; **test 11 in
`tests/test_consumption_css.py`** — the repo's existing home for source-level guards over
`courses.css` (`test_unit_strip_rules_are_present_and_load_bearing` already regexes that file), which
makes it the natural neighbour rather than a render-test module; tests 1–7 and 10 in
`tests/test_e2e_unit_nav.py`; test 9 in a new `tests/test_e2e_review_shell_isolation.py`.

**The new e2e module needs the repo's e2e boilerplate, which `conftest.py` does not supply.** Mirror
`test_e2e_unit_nav.py:17-56`: `pytestmark = pytest.mark.e2e` (module level), its own session-scoped
`_allow_async_unsafe` fixture, the `_login` helper with `TEST_PASSWORD`, **and
`@pytest.mark.django_db(transaction=True)` on the test itself** (`test_e2e_unit_nav.py:131`), which
`live_server` requires — without it the test errors rather than failing informatively. Without the
module marker, `pyproject.toml:49`'s `addopts = "-q -m 'not e2e'"` silently deselects the whole file
and nobody notices.

**Preconditions shared by tests 1–7, 9 and 10** — that is, *every* test whose assertion depends on a
breakpoint, not only the measuring ones. **Test 9 is on this list for a non-obvious reason**: the only
rule it guards lives inside `@media (min-width: 1040px)`, so below that layout viewport its
falsification (widening the selector to `.unit-shell`) shifts nothing and the test stays green. It
must size its context above 1040px and assert the branch per precondition 3.

1. **Set the viewport explicitly.** This includes tests 1–3: they assert the rail is hidden and the
   pin visible, which is true only above 641px, so they depend on a breakpoint just as much as the
   measuring tests do. They would pass today only because Playwright's 1280px default happens to sit
   above it — the exact anti-pattern this rule exists to forbid.
2. **Collapse with a real `[data-unit-tree-toggle]` click**, then `wait_for_function` on
   `document.documentElement.classList.contains('unit-tree-collapsed')` before asserting. Without it
   every one of these measures the expanded layout and either fails or passes vacuously.
3. **Assert the branch before measuring it.** Any test targeting a specific side of the 1040px
   breakpoint must first assert
   `page.evaluate("() => matchMedia('(min-width: 1040px)').matches")` is the expected boolean.

   This is not belt-and-braces. Playwright's `viewport` sets the *window* size, and Chromium's
   classic scrollbar is subtracted from it to give the layout viewport that media queries test — so a
   `viewport={"width": 1040}` yields ~1025px of layout viewport and `(min-width: 1040px)` does **not**
   match. A test that "sets 1040px to check the overhang branch" would silently measure the
   *no*-overhang branch and pass.

   **Never write `breakpoint ± scrollbar`** — scrollbar width is platform- and channel-dependent, so
   that is not a number an implementer can commit. Choose window widths with **headroom on both
   sides** (see test 6's concrete values) and let the `matchMedia` assertion prove which branch was
   actually reached.

1. **e2e — the rail is gone, the pin is the way back, and the pin was hidden before.** At a desktop
   width, **first assert `[data-unit-tree-pin]` is NOT visible while expanded**; then collapse via
   `‹`; assert `.unit-tree` is not visible and the pin is; click the pin; assert the rail returns and
   the pin is hidden again. Falsified by reverting `.unit-tree { display: none }` to
   `flex-basis: 2.4rem`, and separately by deleting the base `.unit-toc-pin { display: none }` rule.

   **The leading assertion is not padding.** Omitting the base rule, or writing the reveal unscoped,
   would leave the pin rendered permanently — beside an expanded rail and, on mobile, beside the
   drawer trigger. Without this assertion every other test in the set stays green through what is the
   single most likely CSS mistake in the change; `test_active_marker_is_strong_and_width_neutral`
   would not catch it either, since the pin precedes the tree in DOM order and its forward-tab loop
   never reaches it.

   **Plus a mobile case**: at a ≤640px viewport, assert the pin is not visible in *either* state.
2. **e2e — persistence.** Collapsed state survives a reload via the pre-paint path, with the pin
   visible and the rail absent on the restored page.
3. **e2e — focus moves.** After collapsing, `document.activeElement` is the pin; after expanding, it
   is `.unit-tree__toggle`. Falsified by deleting the focus-move lines.
4. **e2e — width is actually reclaimed (≥1040px only).** At a 1440×900 viewport, measure `.lesson`'s
   border-box width expanded vs collapsed. **The expected delta is ~224px — the full 14rem rail — not
   262px.** The two 38.4px quantities cancel: the shell gains 38.4px by overhanging and immediately
   spends 38.4px on the pin's lane, so the column goes 696px → 920px. **Tolerance ±2px** — named, not
   left to the implementer, so it cannot be widened until a lane-width regression fits through it.
   This test must **not** run in the 641–1039px band, where the design is deliberately width-neutral
   and this assertion would correctly fail.
5. **e2e — the narrow band is width-neutral, not worse.** At a 900px-wide window, assert
   `.unit-shell__main`'s width equals `container − 38.4px` **within ±2px** (the same named tolerance
   as test 4 — not exact float equality, which across two measurement APIs at a fractional
   scrollbar-adjusted width is a flake, not a guard).

   **Name both measurement APIs**: `.unit-shell__main` via `getBoundingClientRect().width`, and
   `container` via `parseFloat(getComputedStyle(appMain).width)` — `.app-main`'s **content** width.
   `clientWidth` alone is 40px too wide (`app.css:34` sets 20px inline padding) and would fail against
   a correct implementation, which is the failure mode this test was rewritten to avoid.
6. **e2e — the pin is not clipped, at 1440px *and* on both sides of the breakpoint.** Assert the
   pin's `getBoundingClientRect()` lies inside the viewport and is hit-testable at its centre
   (`document.elementFromPoint` resolves to the button or a descendant).

   Three cases, at **concrete window widths with headroom on both sides of the breakpoint**:

   | Case | Window width | `matchMedia('(min-width: 1040px)')` | Branch |
   |---|---|---|---|
   | wide | 1440 | `True` | overhang; pin sits well inside the gutter |
   | just above | **1060** | `True` | overhang; pin's left edge ~20–45px from the viewport edge |
   | just below | **1010** | `False` | reserved lane, no overhang |

   1060/1010 rather than 1040/1039: the latter pair puts *both* cases on the same side of the media
   query once the scrollbar is subtracted, making them byte-identical in behaviour while appearing to
   test both branches. Each case asserts its `matchMedia` value **before** measuring, so a
   platform with an unusually wide scrollbar fails loudly instead of silently testing the wrong
   branch.

   The "just above" case is where the clipping risk actually lives and is the reason this test exists;
   the wide case alone cannot reach it. Any pin-left-edge figures quoted in prose (~221px at 1440) are
   scrollbar-free approximations for sanity-checking only — never assert on them; the assertions are
   relational.
7. **e2e — prose is capped, tables are not; on both page types.** Requires a unit containing **both**
   a text element and a table element. No existing helper in `test_e2e_unit_nav.py` seeds content
   elements (`_seed_nav_course`, `_seed_traversal_course`, `_seed_grouped_course` build structure
   only), so a new seed helper is **part of the deliverable**, built on `add_element()` from
   `tests/factories.py` with `TextElement` + `TableElement` instances (see `tests/test_align_render.py`
   for the idiom). At 1440px collapsed, assert `.el--text` ≤736px and `.el--table` >736px. Measure
   those nodes specifically — **not** the enclosing `<section class="lesson-block">`, which is 872px
   either way and would make the assertion vacuous.

   **A quiz case is required, not optional** — `.lesson-unit__title`, `[data-quiz-preview-notice]`
   and `.quiz-finish` were added specifically for `_quiz_article.html`, and deleting all three would
   otherwise leave the suite green.

   **It takes two page loads, because the banner and the finish form are mutually exclusive.**
   `courses/views.py:1213-1214` sets `previewing = not enrolled` and
   `read_only = quiz_submitted or not enrolled`, and `_quiz_article.html:39` wraps the finish form in
   `{% if not read_only %}`. So `previewing` being true *guarantees* `.quiz-finish` is absent: a
   single load can never contain both, and a test asserting on both would fail (or, with a soft
   locator, pass vacuously) no matter how correct the CSS is.

   - **Load A — previewer**: `.lesson-unit__title`, `[data-quiz-preview-notice]` and `.el--question`
     each ≤736px. No `.quiz-finish` on the page.
   - **Load B — enrolled student, unsubmitted**: `.lesson-unit__title`, `.el--question` and
     `.quiz-finish` each ≤736px. No banner on the page.

   **Load A's actor must reach the page by ownership, not by "no relationship".**
   `quiz_unit` (`courses/views.py:1230`) raises `PermissionDenied` unless
   `can_access_course(user, course)`, which is "enrolled OR staff OR owner"
   (`courses/access.py:32-34`). A user with no enrolment *and* no other relationship gets a 403 and
   never renders the banner the load exists to measure. So Load A's actor is the course **owner** (or
   `is_staff`) and is **not** enrolled — that combination is exactly what makes
   `previewing = not enrolled` true while the page still loads. Load B's actor gets an
   `EnrollmentFactory` instead.

   **The quiz unit needs a question element attached.** `make_quiz_unit()` (`tests/factories.py:235`)
   returns a bare `ContentNodeFactory(kind="unit", unit_type="quiz")` with no elements, so
   `.el--question` would not render at all. Attach at least one via `add_element()` (e.g.
   `ShortTextQuestionElement`).
8. **Render test** — the pin is present in the DOM on both the lesson page and the quiz page, carries
   `aria-expanded`, and its `aria-controls="unit-tree"` target exists exactly once.
9. **Non-regression — the review page is untouched.** Load
   `/manage/courses/<slug>/review/<submission_pk>/` seeded via `make_review_submission()`
   (`tests/factories.py:271`) and assert the page renders identically with and without the collapsed
   state.

   **The actor must be built by the test, not taken from the fixture.** `make_review_submission`
   builds its `reviewer` with `UserFactory`, whose password is `"password123"` (`factories.py:64`) —
   not `TEST_PASSWORD` (`:54`) — and with no email verification, so it cannot log in through the
   allauth form the e2e `_login` helper drives. The returned `reviewer` is therefore **deliberately
   discarded**.

   **The gate is `reviewable_students`, not `can_review_course`.** `review_submission`
   (`views_review.py:126`) goes through `_resolve_for_review` (`:37`) → `_resolve_submission` (`:21`),
   which requires
   `scoping.reviewable_students(request.user, course).filter(pk=submission.student_id).exists()`.
   `can_review_course` gates only the *queue* view (`:111`). `_resolve_for_review` adds a second
   precondition — `submission.status` must be `SUBMITTED` — which the fixture already satisfies.

   **The owner path needs an `Enrollment` that the fixture does not create.**
   `reviewable_students` (`grouping/scoping.py:62-79`) resolves a platform admin or course owner to
   *enrolled* students only (`Enrollment.objects.filter(course=course)`), and
   `make_review_submission` gives its student a `GroupMembership`, never an `Enrollment`. So making
   the actor the course owner and stopping there **404s**. Recipe:

   ```python
   result = make_review_submission()
   submission = result["submission"]
   course = submission.unit.course              # the fixture does not return the course
   actor = make_verified_user(username=..., email=..., password=TEST_PASSWORD)
   course.owner = actor
   course.save(update_fields=["owner"])
   EnrollmentFactory(course=course, student=submission.student)   # required by the owner path
   ```

   The group-teacher path is the alternative (add `actor` to the fixture's group's `teachers`), but
   the fixture does not return that group either, so the owner + enrolment route is the one with a
   named handle for every object it touches.

   **The collapsed state must be installed before first paint.** `base.html:34-41` reads
   `localStorage` pre-paint, so a plain `page.evaluate(...)` after `page.goto` measures a page that
   already painted uncollapsed and the test passes for the wrong reason — vacuous exactly where it
   matters.

   **The two options are not interchangeable, because this test needs *both* states.**
   `add_init_script` is registered on the **BrowserContext** and cannot be removed, so a context
   carrying it can never produce the uncollapsed baseline. Either:

   - use **two `browser.new_context()` instances** — one plain for the baseline, one with the init
     script for the collapsed load; or
   - use **goto → `setItem` → reload** for the collapsed load and
     **goto → `removeItem` → reload** for the baseline, in a single context.

   Do not mix: an `add_init_script` context plus a `removeItem` reload still re-installs the key on
   every navigation.

   **This test guards exactly one rule family — the `margin-inline-start` one.** Assert the review
   shell's bounding box is unchanged; falsify by widening that selector to `.unit-shell`, which must
   turn it red.

   It deliberately does **not** attempt a second, inner-node assertion for the prose-cap family.
   `review_submission.html` renders none of the eight capped selectors (see Scoping — it never calls
   `render_element`), so widening every one of them changes that page by zero pixels: such an
   assertion could never go red and would be guaranteed-green boilerplate. **The prose-cap family is
   guarded by test 11 instead.**
10. **e2e — the content column aligns with the strip above it (≥1040px).** At 1440px collapsed,
    assert `.unit-shell__main`'s left edge equals `.unit-strip`'s left edge (within 1px), and that
    the pin's left edge is ~38.4px left of both. Pins the negative-margin arithmetic against a future
    change to either box.
11. **Source guard — the sliver rules are gone, and every new rule is scoped.** Two assertions over
    comment-stripped `courses.css`. This carries more weight than a typical source test: it is the
    *only* guard for the prose-cap family (test 9 cannot falsify it) and the *only* guard for the
    deletion (nothing behavioural can detect the leftovers — see Architecture).

    (a) **No sliver leftovers.** `re.search(r"html\.unit-tree-collapsed\s+\.unit-tree", stripped)`
    must not match. The pattern is pinned deliberately: four of the five deleted selectors are
    `…__heading`, `…__list`, `…__toggle`, `…__bar`, and they are caught **only** because
    `.unit-tree` is a prefix of each. The natural stricter form — anchoring on a following `,`, `{`
    or whitespace — would catch `:868` alone and let the other four ship green, which is precisely
    what this test exists to prevent. The new form, `[data-unit-shell] > .unit-tree`, does not match
    this pattern, so it does not false-positive.

    (b) **Every new collapsed rule is scoped — checked per individual selector.** Every selector
    containing `html.unit-tree-collapsed` must also contain `[data-unit-shell]`.

    **The tokenisation is load-bearing and must be spelled out**, because the prose-cap rule is a
    *single* comma-separated list of eight selectors. A test that checks each rule's whole prelude as
    one string would see `[data-unit-shell]` in seven correct siblings and pass while one widened
    entry (`html.unit-tree-collapsed .unit-shell .el--text`) shipped green — destroying the only
    guard this family has. Recipe: strip comments → split the file on `}` → take each rule's prelude
    → split that on `,` → apply the implication to **each** resulting selector. Falsify by widening
    exactly one entry in the eight-selector list.

    **Strip comments before matching.** The existing idiom in this repo
    (`tests/test_element_state_write_routes.py`, which regexes raw source, and
    `tests/test_i18n_po_health.py`) is known to trip on prose: a raw-source regex matches text inside
    `/* … */` too, so a comment that merely *mentions* the old selector reddens the suite. Match
    comment-stripped CSS and say so in the docstring.

Both `aria-expanded` values agreeing after each toggle is asserted inside tests 1 and 3 rather than as
a separate case.

**Viewport discipline.** Every test whose assertion depends on a breakpoint — not merely every
*measuring* test — sets its viewport explicitly and, near 1040px, asserts the branch via `matchMedia`
first. See preconditions 1 and 3 above. Playwright's 1280×720 default happens to sit above both
breakpoints, which is exactly why relying on it is how a test silently stops testing what it names.

### i18n

One new translatable string, `"Show course contents"`, used for both `aria-label` and `title`.

`_unit_tree.html:8` already ships `"Expand contents"` for the same conceptual action, so this is a
**recorded, deliberate duplication**: the pin appears outside the rail with no adjacent "Contents"
heading to give "Expand contents" its referent, so it needs the explicit noun. The two Polish
translations must be kept consistent in tone; a reviewer should treat divergence as a bug.

Both `pl` and `en` catalogs get entries and the `.mo` files are regenerated. `makemessages` is run as
`-l pl -l en --no-obsolete`; any `#, fuzzy` marker it pre-fills must be cleared together with its
`#| msgid` line, or a wrong translation ships silently.

### Visual verification

The `frontend-design` skill runs once the mechanics pass. Its remit is **colour, weight, iconography,
border/radius, and resting/hover/focus/active states, within the fixed 2.4rem lane** — plus the two
open layout decisions the spec deliberately left to it: **whether `.block-notes` is capped** and
**whether unanchored notes are capped** (see "Block notes" and "Unanchored notes" above). Both
choices must be recorded in the PR, not made silently.

It may **not** change the lane width or the `min-height` that squares the button. 2.4rem is
load-bearing for the `-2.4rem` overhang, the 1040px breakpoint derivation, the 920px content figure,
and tests 4, 5, 6 and 10; changing it without re-deriving all of them would silently invalidate them.

The sweep covers every element type at top level, prose nested inside **all four** containers
(`two_column`, `spoiler`, `tabs`, `.slideshow-deck`), the quiz page's article chrome (title, previewer
banner, finish divider), the block-notes handle, and unanchored notes. Screenshots in light **and**
dark, judged
separately, at 1440px and ~900px (the reserved-lane branch), in both collapsed and expanded states.
