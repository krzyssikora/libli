# Pinned TOC toggle for the student unit tree

## Purpose

On desktop a student reading a unit sees the course tree in a 14rem rail on the left. Collapsing that
rail today does not remove it: `html.unit-tree-collapsed .unit-tree { flex-basis: 2.4rem }`
(`courses/static/courses/css/courses.css:868`) shrinks it to a **sliver** that keeps its sunken
background, its right border, its sticky bar and a flipped `‹` toggle. The student trades a useful
rail for a useless vertical stripe: ~38px of width reclaimed, and a bordered bar still dividing the
page.

Replace that sliver with a **pinned table-of-contents icon**. When the tree is collapsed the rail
leaves the layout entirely, a small icon button stays pinned in the left margin as the only way back,
and the unit body expands into the reclaimed space.

The goal is *reclaiming the rail*, not merely styling it away — so the width the unit gains is part
of the deliverable, and so is keeping prose readable while it gains it.

### Scope

In scope: the student unit page (lesson and quiz), desktop only (>640px).

Out of scope, deliberately:

- **The mobile drawer (≤640px).** `.unit-foot__contents` already opens a bottom-sheet drawer there
  and the inline rail is already `display: none`. Untouched.
- **The teacher quiz-review rail** (`.review-roster` on
  `templates/courses/manage/review_submission.html`, URL
  `/manage/courses/<slug>/review/<submission_pk>/`). It shares the `.unit-shell` wrapper but uses its
  own `review-roster*` classes, its own `libli_review_roster_collapsed` key and its own pre-paint
  block — a documented, deliberate separation (`review_submission.html:26-30`). It keeps the sliver
  pattern. After this ships the two pages will differ; that is an accepted, stated cost, and porting
  the treatment later is a mechanical rename against the `review-roster*` names.

## Architecture / components

### Existing pieces this builds on

| Piece | Location | Role |
|---|---|---|
| `.unit-shell` | `courses.css:535` | `display: flex; align-items: flex-start` row wrapping the rail + main column |
| `.unit-tree` | `courses.css:540` | the 14rem rail; sticky, own scrollbar |
| `.unit-tree__toggle` | `_unit_tree.html:5-8` | the in-rail `‹` collapse control |
| `unit_nav.js` | `courses/static/courses/js/unit_nav.js:48-67` | binds `[data-unit-tree-toggle]`, writes `localStorage`, calls `centerActive()` |
| pre-paint restore | `templates/base.html:34-41` | reads `libli_unit_tree_collapsed`, sets `html.unit-tree-collapsed` before paint |
| collapsed rules | `courses.css:866-873` | the sliver being replaced |

The state hook (`html.unit-tree-collapsed`), the storage key, and the pre-paint script are **reused
unchanged**. This is a presentation + one-new-control change, not a state-model change. No Python, no
models, no migrations, no new views.

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

Notes on this markup:

- **Server-rendered, not JS-created.** The pre-paint script has already set
  `html.unit-tree-collapsed` before first paint, so a CSS-only reveal is flash-free. A JS-created
  button would pop in after hydration.
- **Its own attribute, `data-unit-tree-pin`** — deliberately *not* a second `[data-unit-tree-toggle]`.
  Two elements sharing that attribute would break `document.querySelector` in `unit_nav.js:49` (it
  would silently bind only the first) and would make every existing Playwright
  `page.locator("[data-unit-tree-toggle]")` a strict-mode violation.
- **`aria-controls="unit-tree"`** requires adding `id="unit-tree"` to the `<nav class="unit-tree">`.
- **Icon**: an inline `currentColor` line SVG carrying the shared `.icon` class, per the repo's
  icon convention (monochrome SVG, never emoji, never a sprite `<use>`). The mark is a
  table-of-contents glyph — three horizontal rules, each led by a dot — **not** `☰`. `☰` already
  means "primary menu" in the app header (`base.html:76`) and "open the mobile contents drawer" in
  the unit footer (`_unit_footer.html:32`); a third meaning on the same page would muddy both.

### Geometry

**Collapsed** (`html.unit-tree-collapsed`, ≥641px):

- `.unit-tree { display: none }` — the rail leaves the flow completely, replacing the
  `flex-basis: 2.4rem` sliver and the four rules that dress it.
- `.unit-toc-pin` becomes visible and occupies a **2.6rem lane**, as
  `position: sticky; top: .6rem; align-self: flex-start`. Sticky, not fixed: it starts exactly where
  the rail's header bar used to be, rides up as the student scrolls, and is bounded by `.unit-shell`,
  so it can never outlive the article nor collide with the sticky `.unit-foot`
  (`courses.css:670`, `z-index: 20`).
- Where the lane comes from depends on viewport width:

| Viewport | Rule | Text column |
|---|---|---|
| ≥1040px | `.unit-shell { margin-left: -2.6rem }` | lane carved from the empty left gutter; content gets the full 920px |
| 641–1039px | no negative margin | lane sits inside the shell; content gets 920px − 2.6rem |

The 1040px threshold is derived, not chosen by feel. `.app-main` is `max-width: 960px` with
`padding-inline: var(--space-5)` = 20px (`app.css:34`, `tokens.css:76`), so the shell's left edge sits
at `(100vw − 960)/2 + 20`. Overhanging 2.6rem (41.6px) leftward requires
`(100vw − 960)/2 + 20 ≥ 41.6`, i.e. `100vw ≥ 1003px`. 1040px leaves ~18px of slack.

**Verified precondition for the overhang**: no ancestor of `.unit-shell` sets `overflow: hidden`.
`reset.css` and `app.css` were checked — the only `overflow: hidden` in reset.css is on `.sr-only`,
and `.app-main` (`app.css:34`) sets none. So the overhanging pin will not be clipped. A test pins
this (see Testing), because a future `overflow` rule on `body`/`.app-main` would silently amputate
the control.

**Expanded**: unchanged from today. `.unit-toc-pin { display: none }` — `display`, not
`visibility`/`opacity`, so it leaves the tab order. The rail keeps its `‹`. `centerActive()`, the
sticky tree bar, the rail scrollbar styling and the active-row marker are all untouched.

**Mobile (≤640px)**: `.unit-toc-pin { display: none }` unconditionally; the footer drawer keeps that
job. `.unit-shell` is already `display: block` there.

**No transition.** `display: none` cannot be animated, and faking the slide is not worth the
complexity for a control used a handful of times per session.

### Content width

The unit gains width in the collapsed state; prose must not become unreadable while it does. At
1440px:

| | Prose | Tables / media |
|---|---|---|
| Expanded (today) | 648px | 648px |
| Collapsed (today, sliver) | 834px | 834px |
| **Collapsed (this change)** | **736px** | **872px** |

Nothing ever becomes narrower than it is today — that is a hard constraint, not an aspiration, and it
is what fixes the cap value.

**The cap is 46rem** = 736px. This is not an invented number: it is `.lesson`'s own standalone
`max-width` (`courses.css:181`), the measure this repo already treats as correct for a lesson article.
`.lesson` inside the shell overrides it to `max-width: none` (`courses.css:537-538`); this
reintroduces the same constant at element level in the collapsed state only.

**Mechanism — a prose allow-list, not cap-by-default.** Prose elements get
`max-width: 46rem` and stay **left-aligned** (so the left edge of the text never moves when toggling);
every other element type keeps the full column.

Cap-by-default with a wide-element opt-out was considered and rejected on inspection of the actual
markup. Two findings decided it:

1. **The element root classes are heterogeneous.** `class="el el--*"` covers only text, math, image,
   video, iframe, table, filltable, gallery, tabs, twocolumn and questions. Callout renders
   `.callout`, spoiler `.spoiler`, stepper `.stepper`, mark-done `.markdone`, HTML `.html-el`,
   reveal-gate `.reveal-gate`, fill-gate `.fillgate`, and switch-gate/switch-grid/guess-number come
   from `courses_extras.py` templatetags with their own class names. An opt-out list against that
   surface is long and easy to get wrong.
2. **Failure modes are asymmetric.** A missed opt-out *breaks* layout — a wide table squeezed into
   46rem. A missed allow-list entry only leaves prose wider than ideal. The gentler failure belongs
   on the more error-prone list.

The allow-list also composes correctly with nesting for free. Only `spoiler`, `tabs` and
`two_column` render nested child elements (verified: `spoilerelement.html:7-9` uses `render_element`;
`calloutelement.html` and `stepperelement.html` do not). A `.el--text` nested inside a two-column
column is already narrower than 46rem, so the cap is a harmless no-op there, at any depth — whereas
cap-by-default would have had to detect and exempt each container.

Initial allow-list:

- `.el--text` — rich text, the dominant prose element and the actual motivation for the cap
- `.callout` — prose in a box
- `.el--question`, excluding the grid/spatial variants that need the width:
  `:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill)`
- `.lesson-unit__head` — so the "Mark as done" pill stays beside the reading column instead of
  drifting ~200px right
- `.unit-crumbs`

Explicitly **not** capped, and why: `.el--math` (a wide display equation must be free to use the
column or scroll rather than be squeezed), all tables/grids/media, and all containers.

The list is a starting point, not a claim of completeness. The frontend-design pass (see below) walks
every element type in the collapsed state at 1440px and adds any that reads badly at full width;
that visual sweep, not this list, is the completeness mechanism.

**The cap is scoped to `html.unit-tree-collapsed`.** It would be a no-op if applied unconditionally
(the expanded column is 648px, under the cap), but scoping keeps the blast radius exactly the new
state and off every other page that renders elements — the builder preview, quiz review, exports.

### Behaviour

`unit_nav.js` currently binds one control (`unit_nav.js:49-67`). It grows to bind two, sharing one
toggle function:

1. Read the two labels from `data-label-expand` / `data-label-collapse` on each control.
2. On click: flip `html.classList.toggle("unit-tree-collapsed")`, write `localStorage`, sync
   `aria-expanded` + `aria-label` on **both** controls, call `centerActive()` when expanding.
3. **Move focus to the sibling control.** This is required, not polish: whichever control was clicked
   becomes `display: none` in the new state, so without an explicit move the browser drops focus to
   `<body>` and a keyboard user loses their place. Collapsing focuses `.unit-toc-pin`; expanding
   focuses `.unit-tree__toggle`.

`aria-expanded` on both controls describes the tree's state (`true` expanded, `false` collapsed) and
must agree between them at all times, including on first paint — the pin ships `aria-expanded="false"`
and `syncToggle()` corrects both on boot from the actual `<html>` class.

## Data flow

There is no server state and no request. The full cycle:

```
first paint    base.html pre-paint  ──reads──▶ localStorage["libli_unit_tree_collapsed"]
                       │
                       └──sets──▶ html.unit-tree-collapsed
                                        │
                                        ├──CSS──▶ .unit-tree      display:none
                                        ├──CSS──▶ .unit-toc-pin   visible, sticky, 2.6rem lane
                                        ├──CSS──▶ .unit-shell     margin-left:-2.6rem  (≥1040px)
                                        └──CSS──▶ prose allow-list  max-width:46rem

boot           unit_nav.js ──binds──▶ [data-unit-tree-toggle] + [data-unit-tree-pin]
                           ──syncs──▶ aria-expanded / aria-label on both

click          toggle() ──flips──▶ html.unit-tree-collapsed
                        ──writes──▶ localStorage
                        ──syncs───▶ aria on both controls
                        ──moves───▶ focus to the sibling control
                        ──calls───▶ centerActive()   (expand only)
```

Persistence is per-browser and cross-page: the key is global, not per-course, exactly as today.

## Error handling

The failure modes here are degradation modes, not exceptions:

- **JavaScript disabled or `unit_nav.js` fails to load.** The pre-paint script never runs, so
  `html.unit-tree-collapsed` is never set: the tree renders expanded and `.unit-toc-pin` stays
  `display: none`. No dead control is exposed — the same contract as `.unit-foot__contents`, which
  ships `hidden` and is revealed only once JS can act on it (`_unit_footer.html:29-33`,
  `unit_nav.js:80`). The in-rail `‹` remains inert without JS, exactly as it is today; this change
  neither fixes nor worsens that pre-existing state.
- **`localStorage` unavailable** (private mode, disabled storage). Both the pre-paint script
  (`base.html:36-40`) and `store()` (`unit_nav.js:6-8`) already wrap access in `try/catch`. The
  toggle still works for the session; the choice simply does not persist.
- **A future `overflow: hidden` on `body` or `.app-main`** would clip the pin where it overhangs the
  gutter at ≥1040px, removing the only way back to the tree. Covered by a test rather than a comment.
- **A pin click while the tree is mid-`centerActive()` smooth scroll.** `centerActive()` re-queries at
  call time and early-returns when collapsed (`unit_nav.js:26-38`), so a rapid collapse during an
  expand animation cannot act on a stale node.

## Testing

Per this repo's standing rule, every test below is **falsified** before it counts: delete or revert
the thing it guards and confirm it goes red. A test that cannot be made to fail is not coverage.

### Existing tests this change breaks (must be updated)

Two e2e tests click `[data-unit-tree-toggle]` to **expand** as well as collapse:

- `tests/test_e2e_unit_nav.py:160` — `test_desktop_tree_collapse_persists`
- `tests/test_e2e_unit_nav.py:714` — the re-centre-on-expand test

Under this design that element is `display: none` once collapsed, so Playwright's actionability wait
would time out. Both must be updated to click `[data-unit-tree-pin]` for the expand step. This is a
required change, not optional — and it is itself a useful signal: if either still passes unmodified,
the rail was not actually removed.

`tests/test_unit_nav_render.py`, `tests/test_unit_tree_long_titles.py` and
`tests/test_courses_views.py` also reference the tree; each is checked for assumptions about the
collapsed markup and updated if it holds any.

### New coverage

1. **e2e — the rail is gone, the pin is the way back.** Collapse via `‹`; assert `.unit-tree` is not
   visible (`display: none`, not a 2.4rem sliver) and `[data-unit-tree-pin]` is; click the pin;
   assert the rail returns. Falsified by reverting `.unit-tree { display: none }` to
   `flex-basis: 2.4rem`.
2. **e2e — persistence.** Collapsed state survives a reload via the pre-paint path, with the pin
   visible and the rail absent on the restored page.
3. **e2e — focus moves.** After collapsing, `document.activeElement` is the pin; after expanding, it
   is `.unit-tree__toggle`. Falsified by deleting the focus-move lines.
4. **e2e — width is actually reclaimed.** At a ≥1040px viewport, measure the article's bounding width
   collapsed vs expanded and assert it grew. This is the test for the *purpose* of the feature, and
   the one that would catch "the rail is hidden but the column never widened."
5. **e2e — the pin is not clipped.** At ≥1040px, assert the pin's `getBoundingClientRect()` lies
   inside the viewport and is hit-testable at its centre point
   (`document.elementFromPoint` resolves to the button or a descendant). This is the guard against a
   future ancestor `overflow: hidden`, and against the overhang pushing the control off-screen at the
   breakpoint boundary.
6. **e2e — prose is capped, tables are not.** In the collapsed state, a text element's width is
   ≤46rem while a table element's exceeds it.
7. **e2e — `aria-expanded` agrees.** Both controls report the same state after each toggle.
8. **Render test** — the pin is present in the DOM on both the lesson page and the quiz page, and the
   `aria-controls` target `id="unit-tree"` exists.

Viewport note: tests 4–6 must set an explicit viewport ≥1040px. Playwright's default is 1280×720,
which is above the breakpoint, but relying on a default for a breakpoint-sensitive assertion is how a
test silently stops testing what it names.

### i18n

One new translatable string, `"Show course contents"`, used for both `aria-label` and `title`, plus
its `data-label-*` counterpart for the expanded direction. Both `pl` and `en` catalogs get entries and
the `.mo` files are regenerated. `makemessages` is run as `-l pl -l en --no-obsolete`; any `#, fuzzy`
marker it pre-fills must be cleared together with its `#| msgid` line, or a wrong translation ships
silently.

### Visual verification

The `frontend-design` skill runs once the mechanics pass, and is responsible for the pin's visual
treatment — size, weight, resting/hover/focus states, and how it reads against the article in both
themes. Screenshots in light **and** dark, judged separately, at ≥1040px and at ~900px (the
reserved-lane branch), in both collapsed and expanded states. Dark mode is judged on its own terms,
not assumed to follow from light.
