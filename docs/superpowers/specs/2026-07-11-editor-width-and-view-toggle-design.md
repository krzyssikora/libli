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
| `--preview-w` | `48.5rem` | student content 46rem + pane padding 2×1rem (`--space-4`) + 0.5rem reserved scrollbar gutter → a true 46rem content region even when the pane scrolls |
| `--editor-min` | `17rem` | editor never narrower than this (2-row element tiles still fit) |
| `--editor-split-max` | `48rem` | editor's cap in split = same as preview ("if the screen allows") |
| `--editor-solo-max` | `54rem` | editor's cap on its own — a bit wider than its split width |
| `--editor-wide` | `70rem` (1120px) | the **single** editor-grid breakpoint: at/above it split is two-column and the panes viewport-lock; below it everything stacks/flows |
| page max | `102rem` | editor-page `.app-main` cap (≈1632px): comfortably fits two student-width columns + gap + padding, then centers |

**Arithmetic (why these values).** `.app-main` horizontal padding is `--space-5`
(1.25rem) each side — from `.app-main { … padding: var(--space-8) var(--space-5) }`
(app.css:34) — so inner width = outer − 2.5rem; the grid gap is also `--space-5` =
1.25rem. (The proof tolerates a padding-token delta up to the ~2rem slack below.)

- *Two full columns fit at the page max:* editor 48rem + preview 48.5rem + one
  1.25rem gap = 97.75rem; inner width at the 102rem cap = 102 − 2.5 = 99.5rem ≥
  97.75rem, ~1.75rem slack. (At the old 100rem the slack was ~0 — too tight to
  honestly call "two equal columns," which is why the cap is 102rem.)
- *`--editor-wide` = 70rem is the smallest width at which split does not overflow:*
  a fixed 48.5rem preview + 1.25rem gap + `--editor-min` 17rem = 66.75rem inner
  needs 66.75 + 2.5 padding = 69.25rem outer; 70rem gives headroom. Below 70rem a
  fixed preview + a usable editor cannot coexist, so split stacks there instead of
  overflowing.
- *Preview reserves its scrollbar:* the preview `.pane-body` has `overflow-y: auto`
  with an ~8px (0.5rem) custom scrollbar (editor.css:268) and, at wide widths, the
  viewport-lock makes only the pane bodies scroll — the normal authoring case. So
  the preview `.pane-body` sets `scrollbar-gutter: stable` and `--preview-w` bakes
  in that 0.5rem, keeping the content region a true 46rem whether or not the pane
  is currently overflowing (no reflow when the scrollbar appears/disappears).

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
- **`templates/courses/manage/editor/_preview.html`** — wrap the preview content
  (the title + `prev-el` sections) in a **new inner wrapper** `<div class="prev-inner">`,
  a *child* of `.pane-body.prev`, and cap **that wrapper** at `max-width: 46rem`
  **with `margin-inline: auto`** (centered). The cap must live on this inner child,
  **not** on `.pane-body` itself: `.pane-body` already carries `padding: var(--space-4)`
  (1rem/side, editor.css:242), so a 46rem cap on the pane-body would *include* that
  padding and yield only ~44rem of content — 2rem under student width. On the inner
  child the 46rem applies to content *inside* the pane padding, giving a true 46rem.
  This cap's role differs by width and is **load-bearing below `--editor-wide`**:
  at/above 70rem the preview is a fixed `--preview-w` column and the 46rem cap is
  redundant belt-and-suspenders; but **below 70rem the preview stacks to the base
  `1fr` full-width column**, so the 46rem cap is the *sole* constraint keeping the
  preview at student width there (without it the preview would render at ~65rem on a
  ~68rem viewport). It must not be dropped. Also set `scrollbar-gutter: stable` on
  the preview `.pane-body` (see the scrollbar arithmetic above).
- **A small JS enhancer** — reveal and wire the toggle buttons (mode class +
  `localStorage`). Preferably folded into `courses/static/courses/js/editor.js`
  (already registered in `editor.html`'s `extra_js`). If instead a **dedicated
  file** is used, it must be registered as a `<script … defer>` in the `extra_js`
  block (editor.html:68–108), following the existing editor JS conventions.

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
  single column. This is the stacked/narrow layout and the safe default. Only
  `grid-template-columns` changes from today's `minmax(17rem, 22rem) 1fr` to
  `1fr`; the rework must **preserve** the existing `gap: var(--space-5)` and
  `align-items: start` on `.editor-grid` (editor.css:12–17), which both stacked and
  split layouts still need — don't replace the rule wholesale and drop them.
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

**Behaviour-change note (901px → 1120px).** The viewport-lock / two-column
threshold deliberately rises from today's 901px to `--editor-wide` 1120px. So
viewports in the **901–1119px band** (e.g. common ~1024px laptops and
landscape tablets) that get a locked two-column split today will now **stack** in
split mode. This is an intended consequence of the fixed-student-width preview (a
768px preview + a usable editor genuinely needs ~1120px), and it is mitigated by
the always-available Editor-only / Preview-only solo modes, each of which uses the
full width in that band. Call this out for QA so the stacking there reads as
intended, not as a regression.

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

**Per-button mode hook (normative).** Each button declares its mode via
`data-view="editor|split|preview"` — reusing the three canonical values verbatim
(the same strings as the `localStorage` values). Both code paths resolve
value↔button strictly through this attribute — the pre-paint script maps the
stored value to the button with the matching `data-view` (to set `aria-pressed` /
`.is-active`), and the enhancer maps a clicked button's `data-view` to the mode
string (to set the class and persist). Neither path may key off button order,
index, or `textContent`, so the two separate paths cannot silently diverge — the
same reason the `localStorage` key/values are pinned.

**Single mode class invariant.** Both the pre-paint script and the enhancer set
the mode by **clearing all three `is-mode-*` classes first, then adding exactly
one** — never a bare `classList.add`. The server renders `is-mode-split` as the
default, hardcoded on `<div class="editor-grid …">` in `_editor_scope.html`
(line 2). Note that `_editor_scope.html` is also the fragment `editor.js` re-renders
on element add/save, but only the two `[data-scope]` panes are extracted from that
fragment — `.editor-grid` itself is never swapped, so a fragment update neither
resets nor re-applies the JS-set mode class (the class genuinely persists across
swaps; do not assume a swap re-applies `is-mode-split`). If the stored mode is
non-default, the pre-paint script must *replace* the default (remove
`is-mode-split`, add the stored one), so `.editor-grid` never carries two mode
classes at once (which would e.g. hide the editor pane via `is-mode-preview` while
`is-mode-split` still forced the two-column template — a broken grid).

Modes:

- **Split** (default) — both panes; two columns at/above `--editor-wide`, stacked
  below it.
- **Editor** — only the editor pane, single centered column at `--editor-solo-max`.
- **Preview** — only the preview pane, single centered column at `--preview-w`
  (full student width).

The toggle applies at all widths. Below `--editor-wide` it is still useful:
preview-only or editor-only avoids the long stacked scroll.

**i18n.** The project ships EN + PL and every user-facing template string goes
through `{% trans %}` (as sibling `_preview.html` already does). All new visible /
AT-visible strings — the three button labels (**Editor**, **Split**, **Preview**),
the group `aria-label` (**Editor view**), and the distinguishing caption — MUST be
wrapped in `{% trans %}`, and the PL `.po`/`.mo` catalog updated (translated, with
no fuzzy or obsolete entries) so the repo's i18n catalog tests stay green.

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
   `[data-view-toggle]`** (never `.type-toggle*`). On init the enhancer **trusts
   the DOM state the pre-paint script already established** — it does not re-read
   `localStorage` or re-assert the class on load (that would be redundant work the
   pre-paint script already did before paint). Clicking a segment swaps the
   `is-mode-*` class on `.editor-grid` (clear-all-then-add-one), updates
   `aria-pressed` + `.is-active` on the buttons, and writes the new value to
   `localStorage['libli-editor-view']`. **Validation** (the value↔three-known-modes
   check, fallback to `split`) lives in *both* code paths but on different phases:
   the pre-paint script validates the **read** at load; the enhancer validates only
   the **write/persist** path (it never persists a value outside the three).
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
  **Required `[hidden]` override:** because `.view-toggle` carries a flex display
  (it shares the `.type-toggle` `display: inline-flex` look), the UA
  `[hidden]{display:none}` rule is *overridden* by that author `display` and the
  control would NOT actually hide — the exact `[hidden]` gotcha this project has
  shipped before (`.btn[hidden]`, `.dnd__rows[hidden]`). editor.css MUST therefore
  include an explicit `.view-toggle[hidden] { display: none }` (equivalently
  `[data-view-toggle][hidden]`) rule; without it the no-dead-control guarantee and
  the pre-`DOMContentLoaded` no-flash both fail.

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
  and **narrow** (~64rem — below 70rem, split stacks). Capture each of the three modes.
- **JS behaviour** covered by **Playwright e2e** (the project has pytest +
  Playwright and no JS unit runner). Per the repo's "e2e must drive real UI" note,
  the test drives the **actual button clicks** and a **real page reload** — not a
  `page.evaluate` shortcut: (a) clicking Preview hides the editor pane and sets
  `localStorage['libli-editor-view'] == 'preview'`; (b) after a reload the grid's
  **end state** is Preview (assert `is-mode-preview` is present on load and the
  editor pane is hidden). Note this asserts the persisted end state, not the
  *absence of a flash* — Playwright cannot prove Split never momentarily rendered;
  the no-flash property is guaranteed structurally by the pre-paint script's inline
  placement (source order), not by a runtime check. (c) a corrupt/absent stored
  value loads as Split.
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
