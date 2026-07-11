# Editor width & 3-way view toggle

## Purpose

The course editor page is capped by the app-wide `.app-main { max-width: 960px }`
(`core/static/core/css/app.css:34`). Inside that cap the editor grid splits the
space into a narrow editor column (`minmax(17rem, 22rem)`) and a `1fr` preview
column, so the live preview renders at roughly 560px — far narrower than a real
student screen. Authoring a course this way is cramped: both the editor form and
the preview fight over half the width they should have.

The goal is to give the preview real student width and the editor more comfortable
room, and let the author focus on either pane. Specifically:

- **Preview** always renders at the **real student width**, whether shown in split
  or on its own.
- **Editor** is a bit wider than today (some element forms carry lots of detail),
  but with a firm maximum.
- The page may grow **wider than the rest of the app**, but not full-window on a
  large monitor — it has a maximum and then centers.
- The author can switch between **Editor only / Split / Preview only**, and that
  choice persists across reloads.

This is a purely presentational change: template + CSS + a small JS enhancer. No
model, view, URL, or backend changes.

## Architecture / components

All widths are driven off a small set of CSS custom properties scoped to the
editor page. The grounding fact is the student content width:
`.lesson { max-width: 46rem }` (`courses/static/courses/css/courses.css:118`).

| Token | Value | Meaning |
|---|---|---|
| `--preview-w` | `48rem` | student content width (46rem) + preview pane padding (`--space-4` = 1rem each side) — the real student experience |
| `--editor-min` | `17rem` | editor never narrower than this (2-row element tiles still fit) |
| `--editor-split-max` | `48rem` | editor's cap in split = same as preview ("if the screen allows") |
| `--editor-solo-max` | `54rem` | editor's cap on its own — a bit wider than its split width |
| `--editor-wide` | `70rem` (1120px) | the **single** editor-grid breakpoint: at/above it split is two-column and the panes viewport-lock; below it everything stacks/flows |
| page max | `102rem` | editor-page `.app-main` cap (≈1632px): comfortably fits two student-width columns + gap + padding, then centers |

**Arithmetic (why these values).** `.app-main` inner width = outer − 2×`--space-5`
(1.25rem) padding; the grid gap is `--space-5` = 1.25rem.

- *Two full columns fit at the page max:* two 48rem columns + one 1.25rem gap =
  97.25rem; inner width at the 102rem cap = 102 − 2.5 = 99.5rem ≥ 97.25rem, with
  comfortable slack. (At the old 100rem the slack was only 0.25rem — too tight to
  honestly call "two equal columns," which is why the cap is 102rem.)
- *`--editor-wide` = 70rem is the smallest width at which split does not overflow:*
  a fixed 48rem preview + 1.25rem gap + `--editor-min` 17rem = 66.25rem inner needs
  66.25 + 2.5 padding = 68.75rem outer; 70rem gives headroom. Below 70rem a fixed
  preview + a usable editor cannot coexist, so split stacks there instead of
  overflowing.

Components touched:

- **`courses/static/courses/css/editor.css`** — new tokens; rework `.editor-grid`
  and the `.preview-pane` / `.editor-pane` rules to the width model; add the three
  `is-mode-*` modifier rules per the specificity structure below; add the
  editor-page `.app-main` max-width override; **consolidate** the three existing
  breakpoint rules (`@media (max-width: 720px)` at editor.css:19, `@media
  (max-width: 900px)` at editor.css:285, and `@media (min-width: 901px)` at
  editor.css:251) onto the single `--editor-wide` (70rem) breakpoint. The
  viewport-lock + per-pane internal scrolling moves from `min-width: 901px` to
  `min-width: 70rem` and continues to work in all three modes (a single visible
  pane fills the locked height).
- **`templates/courses/manage/editor/editor.html`** — render the segmented toggle
  here (in `editor.html`, **not** `_editor_scope.html`), placed above the
  `_editor_scope` include so it sits **outside** the two `[data-scope]` panes that
  `editor.js` swaps on fragment updates (`existing.replaceWith(incoming)` keyed on
  `[data-scope]`, editor.js:64–68). Add the pre-paint inline `<script>` immediately
  **after** the `_editor_scope` include, so at parse time `.editor-grid` already
  exists in source order and the mode class is stamped before first paint. (A
  head-level script cannot reach `.editor-grid`; a script inside a swapped pane
  would be re-run on every fragment swap — both are why placement is pinned here.)
- **`templates/courses/manage/editor/_preview.html`** — constrain the preview
  content region to `46rem` so it mirrors the student width inside the fixed
  preview column. This is **belt-and-suspenders**: a 48rem column already yields a
  46rem inner box given the 1rem pane padding, so the `max-width: 46rem` only bites
  if that padding ever changes. Not load-bearing, but cheap insurance.
- **A small JS enhancer** — reveal and wire the toggle buttons (mode class +
  `localStorage`). May live in `courses/static/courses/js/editor.js` or a small
  dedicated file, following existing editor JS conventions.

### Width model (derived behaviour)

- **Preview** is a **fixed** column of `--preview-w` in both split and solo modes
  (at/above `--editor-wide`), and its rendered content is constrained to `46rem` so
  it matches the student view exactly (desktop student layout; see Non-goals for
  mobile).
- **Editor in split** is `minmax(--editor-min, --editor-split-max)` — i.e. its
  effective width is `min(48rem, remaining space beside the fixed preview)`. At/above
  the page comfortable width it reaches the full 48rem (columns approach equal); on
  a medium-wide screen it takes whatever remains beside the fixed preview; below
  `--editor-wide` (70rem) split stacks (see "Breakpoints & CSS structure"). This is
  "same as preview if the screen allows, otherwise the rest of the width."
- **Editor solo** is a single centered column capped at `--editor-solo-max`.
- **The page**: only `body.editor-page` overrides the global 960px cap, up to
  `102rem`, then `margin: 0 auto` centers it. On narrower windows it is naturally
  100% wide. Not full-window on large monitors.

### Breakpoints & CSS structure (single breakpoint, specificity-safe)

The current `editor.css` has three overlapping breakpoint rules (720px and 900px
both stack the grid; 901px viewport-locks it). This design **consolidates them to
one** value, `--editor-wide` = 70rem (1120px), and structures the mode rules so a
class selector never fights the stacking media query:

- **Base rule (all widths):** `.editor-grid { grid-template-columns: 1fr; }` — a
  single column. This is the stacked/narrow layout and the safe default.
  (All CSS token references below are illustrative shorthand; in the actual rules
  every `--token` must be wrapped in `var(--token)` — a bare `--editor-min` in a
  value is an invalid, no-op declaration.)

- **Solo hide-rules + centering (all widths):** hiding the inactive pane in
  editor-only / preview-only mode is width-independent, so
  `.editor-grid.is-mode-editor .preview-pane { display: none }` and
  `.editor-grid.is-mode-preview .editor-pane { display: none }` apply at every
  width. The **visible** solo pane is capped and centered by giving *that pane* a
  `max-width` + `margin-inline: auto` (not a grid-track trick), with a **different
  cap per mode**: editor-solo → `var(--editor-solo-max)` (54rem), preview-solo →
  `var(--preview-w)` (48rem). The cap is scoped to the solo mode selectors so it
  never bleeds into split (where the pane widths come from the grid tracks).
  Vertically this composes with the wide-width viewport-lock: the lock stretches
  the pane to the locked height (`align-items: stretch`) while `margin-inline: auto`
  handles only horizontal centering — the two axes don't conflict.
- **Split two-column template (only inside `@media (min-width: 70rem)`):**
  `.editor-grid.is-mode-split { grid-template-columns: minmax(var(--editor-min),
  var(--editor-split-max)) var(--preview-w); justify-content: center; }` lives
  **inside** the wide media query. `justify-content: center` balances the leftover
  when both tracks reach their 48rem cap near the page max (between ~99.75rem outer,
  where the editor hits 48rem, and the 102rem cap there is ~2.25rem of slack) so
  the two equal columns sit centered rather than trailing left. Because the
  two-column template is never emitted below 70rem, the class rule cannot
  out-specify the narrow single-column base — there is no competing declaration at
  narrow widths to lose to. This is the fix for the specificity trap (a
  `.editor-grid.is-mode-split` selector at (0,2,0) would otherwise beat an
  unqualified `@media(max-width…) .editor-grid` at (0,1,0), since media queries add
  no specificity).
- **Viewport-lock (only inside `@media (min-width: 70rem)`):** the page-height lock
  + per-pane internal scroll (moved here from `min-width: 901px`) applies to all
  three modes at wide widths; the single visible pane fills the locked height in
  solo modes.

Net effect: below 70rem the page flows naturally and split stacks (both panes,
one column); at/above 70rem split is two columns and the panes scroll internally.
The old 720px and 900px stacking rules are removed (folded into the base
single-column rule).

### The 3-way toggle

A segmented control of three `<button>`s labelled **Editor · Split · Preview**
sits above the grid, styled to match the existing segmented-control **look**.

**Distinct hook — do not reuse `.type-toggle`.** The editor page *already* has a
`.type-toggle` control: `editor.html:50` renders `<form class="type-toggle">` with
`.type-toggle__btn` (the Lesson/Quiz unit-type switch), sitting just above in
`.editor-head`. The new view toggle MUST therefore use its **own** classes
(`.view-toggle` / `.view-toggle__btn`) and its own wrapper hook
`<div class="view-toggle" role="group" aria-label="Editor view"
data-view-toggle>` — never the `.type-toggle*` selectors — so the enhancer,
pre-paint script, and e2e can bind/stamp strictly within `[data-view-toggle]` and
can never match the unit-type buttons. `.view-toggle` may share the `.type-toggle`
visual rules (e.g. a shared declaration or duplicated tokens), but its selectors
are distinct. Because the two identical-looking controls sit near each other and
do very different things, give the view toggle a short caption or label (e.g. a
small "View" prefix) so it is not mistaken for the unit-type switch.

Selecting a mode sets a modifier class on `.editor-grid`
(`is-mode-editor` / `is-mode-split` / `is-mode-preview`) that swaps the grid
template and hides the inactive pane via CSS (per "Breakpoints & CSS structure").
The default class is `is-mode-split`, which preserves the **same two-pane
arrangement** as today (see the accuracy note in Error handling — the split
*widths* deliberately change; only the two-pane arrangement is unchanged).

**Active-state semantics.** The three buttons form a single-select group. The
active button carries `aria-pressed="true"` (the other two `aria-pressed="false"`)
and the `.is-active` visual class; the `<div role="group" aria-label="Editor view"
data-view-toggle>` wraps them. The **pre-paint** inline script sets the initial
`is-mode-*` grid class **and** the initial pressed/`.is-active` button, so neither
the layout nor the active segment flashes to the default before the deferred
enhancer runs.

**Single mode class invariant.** Both the pre-paint script and the enhancer set
the mode by **clearing all three `is-mode-*` classes first, then adding exactly
one** — never a bare `classList.add`. The server renders `is-mode-split` as the
default; if the stored mode is non-default, the pre-paint script must *replace* it
(remove `is-mode-split`, add the stored one), so `.editor-grid` never carries two
mode classes at once (which would e.g. hide the editor pane via `is-mode-preview`
while `is-mode-split` still forced the two-column template — a broken grid).

Modes:

- **Split** (default) — both panes; two columns at/above `--editor-wide`, stacked
  below it.
- **Editor** — only the editor pane, single centered column at `--editor-solo-max`.
- **Preview** — only the preview pane, single centered column at `--preview-w`
  (full student width).

The toggle applies at all widths. Below `--editor-wide` it is still useful:
preview-only or editor-only avoids the long stacked scroll.

## Data flow

The view mode is a single small piece of client-side UI state; there is no
server round-trip.

The `localStorage` key is exactly **`libli-editor-view`** (normative, not an
example) and the three stored values are exactly **`editor`**, **`split`**,
**`preview`** — the pre-paint script and the enhancer MUST agree on these strings
verbatim.

1. **Load.** A pre-paint inline `<script>` in the editor template reads
   `localStorage['libli-editor-view']`, validates it against the three values
   (anything missing/other → `split`), then — **guarding first that `.editor-grid`
   and the `[data-view-toggle]` group exist** (null-check; do nothing if a future
   variant omits them) — sets the mode by **clearing all three `is-mode-*` classes
   and adding exactly one** (never a bare add, per the single-mode-class
   invariant), and sets the initial pressed/`.is-active` button within
   `[data-view-toggle]`. All before first paint, so neither the layout nor the
   active segment flashes.
2. **Reveal + toggle.** The `[data-view-toggle]` group is rendered with the
   `hidden` attribute (see Error handling: no dead control for no-JS). The JS
   enhancer (wired on `DOMContentLoaded`) removes `hidden` and attaches click
   handlers to the three segment buttons **selected strictly within
   `[data-view-toggle]`** (never `.type-toggle*`). Clicking a segment swaps the
   `is-mode-*` class on `.editor-grid` (clear-all-then-add-one), updates
   `aria-pressed` + `.is-active` on the buttons, and writes the new value to
   `localStorage['libli-editor-view']`.
3. **CSS reacts.** Grid template columns and pane visibility are entirely
   CSS-driven off the `is-mode-*` class; no inline styles are set by JS.

State is global (a workflow preference), not per-unit, consistent with the recent
"persist tab open-state across refresh" work.

## Error handling

- **Missing / invalid stored mode** → fall back to `split` (the default). The
  validation lives in both the pre-paint script and the enhancer so a corrupt
  value can never leave the grid without a mode class.
- **`localStorage` unavailable / throws** (private-mode quirks, disabled storage)
  → both the read and the write are wrapped so a throw is swallowed; the editor
  falls back to the default `split` mode and simply does not persist. The toggle
  still works within the session.
- **JS disabled entirely** → the template's default markup renders the `split`
  mode class server-side, and the `[data-view-toggle]` group is rendered with the
  `hidden` attribute (only the enhancer removes it). So a no-JS user sees the
  **same two-pane arrangement** as today, and **no dead/inert control**. (The
  pre-paint script is inline, not deferred, so under normal JS it runs before
  paint; `hidden` matters only when JS is off entirely or fails to load.)

**Accuracy note — split is not pixel-identical to today.** The default `split`
mode preserves the two-pane *arrangement*, but its **widths deliberately change**
for everyone (including no-JS users): the page cap goes 960px → 102rem, the
preview becomes a fixed 48rem, and the editor column re-caps. "Same as today"
throughout this spec means the same mode/arrangement, not byte-for-byte output.
The Testing "full existing editor test suite stays green" claim is about
**backend/behavioural** tests (no view/URL/model change) and any layout assertions
that are not pixel-width-specific; a test that asserted the old exact split column
widths, if one exists, is expected to update to the new model.

## Testing

- **CSS/layout** verified visually with Playwright screenshots (light + dark),
  per the project's "verify UI with screenshots" practice, at three representative
  widths: **wide** (≥102rem — split shows two ~equal 48rem columns), **medium**
  (~80rem — split shows the editor narrower than the fixed preview, no overflow),
  and **narrow** (<70rem — split stacks). Capture each of the three modes.
- **JS behaviour** covered by **Playwright e2e** (the project has pytest +
  Playwright and no JS unit runner). Per the repo's "e2e must drive real UI" note,
  the test drives the **actual button clicks** and a **real page reload** — not a
  `page.evaluate` shortcut: (a) clicking Preview hides the editor pane and sets
  `localStorage['libli-editor-view'] == 'preview'`; (b) after a reload the grid
  loads in Preview with no flash of Split (assert the `is-mode-preview` class is
  present on load and the editor pane is hidden); (c) a corrupt/absent stored value
  loads as Split.
- **Regression:** the full existing editor test suite stays green (no backend
  surface changed).

## Non-goals

- No responsive/mobile emulation inside the preview — the preview reproduces the
  **desktop** student width (46rem). Matching the phone student layout at a
  narrow breakpoint is out of scope.
- No per-unit or per-user server-side persistence — `localStorage` only.
- No changes to what the preview renders or how elements are tried; only its
  width changes.
- No changes to any page other than the editor.
