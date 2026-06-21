# Unit editor: independent preview scroll, scroll-to-on-select, contrast-safe highlight

**Date:** 2026-06-21
**Branch context:** unit editor live-preview UX (follows the narrower-editor / wider-preview change)

## Problem

Two follow-on issues remain after narrowing the editor column and widening the live preview:

1. **The hover highlight is not reliably visible.** Hovering an editor row draws a single-colour
   ring (`box-shadow: 0 0 0 2px var(--primary)`) on the matching preview element. Against an
   element whose background is close in tone to `--primary` — especially at a light/dark
   boundary — the ring blends in and the connection is lost. Thickness alone does not fix this;
   the cause is **contrast**, not size.

2. **The preview is much longer than the editor.** Editor and preview share the page's body
   scroll. A long unit makes the preview run far past the bottom of the editor list, so the row
   you are editing and its rendered output are rarely on screen together.

## Goals

- Keep editor and preview visually connected as the unit grows.
- Make the highlight read clearly on any element background.
- Do this with small, self-contained changes; no new dependencies; follow existing token-driven
  CSS and the existing `data-element` / `data-element-id` matching.

## Non-goals

- No hover-driven auto-scroll (rejected as jumpy during a brainstorm; casual mouse movement
  should not move the preview).
- No change to the matching mechanism, the fragment-swap flow, or the editor pane's own scroll
  (the editor list continues to flow with the page).
- No redesign of the highlight beyond contrast + a modest thickness bump.

## Existing mechanism (reference)

- **Match keys:** editor row `data-element="{{ el.pk }}"`
  (`templates/courses/manage/editor/_element_row.html:2-3`); preview section
  `data-element-id="{{ el.pk }}"` (`templates/courses/manage/editor/_preview.html:15`).
- **Hover highlight:** `editor.js` `setHighlight()` / `bindHover()` toggle `.prev-el--hl`
  on `mouseenter` / `mouseleave` (`courses/static/courses/js/editor.js:47-60`), re-bound after
  every fragment swap inside `applyFragments()` (`editor.js:44`).
- **Select / edit:** the ✎ icon and the row label are `.el-select` buttons carrying
  `data-element-id` and `data-form-url` (`_element_row.html:11-13,33-34`). A delegated click
  handler fetches the form and calls `applyFragments()`, which replaces **both** the editor and
  preview panes (`editor.js:149-153`, `28-45`).
- **Layout:** `.editor-grid` is a two-column grid; the preview is
  `.pane.preview-pane[data-scope="preview"]` containing `.pane-head` + `.pane-body.prev`
  (`_preview.html:2-4`). The preview pane is `position: sticky; top: var(--space-4)` with no
  independent overflow (`courses/static/courses/css/editor.css:199`); `.pane-body` has padding
  only (`editor.css:198`). Highlight CSS lives at `editor.css:282-284`.

## Design

Three independent changes.

### 1. Independent preview scroll container (CSS)

Turn the sticky preview pane into a flex column whose **body** scrolls internally, capped to the
viewport. The `.pane-head` ("Live preview") stays pinned; only the rendered elements scroll.

```css
.preview-pane {
  position: sticky;
  top: var(--space-4);
  align-self: start;
  display: flex;
  flex-direction: column;
  /* Cap to the viewport so the preview can never run far past the editor.
     Accurate once the pane is stuck at top:var(--space-4). Above that scroll
     position the pane sits below the page header (.editor-crumb / .editor-head /
     .unit-settings render above .editor-grid), so the cap overestimates the
     available height and the pane bottom may overhang the viewport until sticky
     engages — accepted; verify the offset feels right by eye (see Testing). */
  max-height: calc(100vh - var(--space-4) * 2);
}
.preview-pane .pane-body {
  overflow-y: auto;
  min-height: 0; /* allow the flex child to shrink so overflow engages */
}
```

The existing `.preview-pane { position: sticky; top: var(--space-4); align-self: start; }` rule
(`editor.css:199`) is replaced by the block above. The editor column is untouched and keeps
flowing with the page scroll, so scrolling the page still moves through the editor rows while the
preview stays pinned and self-contained.

**Rounded corners:** `.pane` has `border-radius: var(--radius-lg)` and a box-shadow
(`editor.css:188-189`); the now-scrolling `.pane-body` is its last child. The body's scrollbar
gutter sits inside its own `var(--space-4)` padding, so in the common case it stays clear of the
pane's rounded bottom corners. If the scrolling content visibly overruns the rounded corner, give
`.pane-body` matching `border-bottom-left-radius` / `border-bottom-right-radius`, or move the
overflow to an inner wrapper and keep `overflow: hidden` on the pane. Treat this as a visual to
confirm by eye (see Testing), not a blocker.

**Responsive note:** the grid collapses to a single column at `max-width: 900px` (`editor.css:208`).
Note there is also a redundant `@media (max-width: 720px)` rule setting the same
`grid-template-columns: 1fr` (`editor.css:19-21`); because `max-width: 900px` already subsumes every
width ≤ 720px, the **effective stacking breakpoint is 900px**, and the `:208` block is the correct,
sufficient place to scope the reset (do not move it to 720px — that would leave the panes stacked
but still sticky between 720–900px). A viewport-height sticky pane is wrong when stacked, so the
override is scoped to the two-column layout — inside the existing `@media (max-width: 900px)` block,
reset:

```css
@media (max-width: 900px) {
  .editor-grid { grid-template-columns: 1fr; }
  .preview-pane { position: static; max-height: none; display: block; }
  .preview-pane .pane-body { overflow-y: visible; }
}
```

### 2. Scroll preview to the selected element (JS)

Hang the scroll off the **existing select/edit click**, not hover. When `.el-select` is clicked
the element becomes the focus of work and `applyFragments()` rebuilds the preview; immediately
after that rebuild, scroll the new preview's matching section into view within the preview
container.

- In the `.el-select` click branch (`editor.js:149-153`), read the id from the clicked button's
  `data-element-id` and remember it across the fetch.
- After `applyFragments(html)` runs (the preview DOM now exists), look up
  `.prev-el[data-element-id="<id>"]` and call:

  ```js
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  ```

  `block: "nearest"` means no movement when the element is already visible — only off-screen
  selections scroll. When the preview overflows (long unit — the case this change targets), the
  nearest scrollable ancestor is the `.pane-body` container from change #1, so only the preview
  scrolls. When the unit is short enough that `.pane-body` does not overflow, it is not a scroll
  container; `block: "nearest"` then resolves against the page scroller and is a no-op if the
  selected element is already on screen, or otherwise nudges the page just enough to reveal it — a
  benign outcome, since the user just chose that element. The "only the preview scrolls" guarantee
  therefore holds specifically for the overflowing case that motivates this work.

Implementation shape (factor a small helper so the id flows cleanly through the existing promise
chain; exact wording left to the plan):

```js
function scrollPreviewTo(id) {
  if (!id) return;
  var el = root.querySelector('.prev-el[data-element-id="' + id + '"]');
  if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
// in the .el-select branch:
var selId = sel.getAttribute("data-element-id");
fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
  .then(function (r) { return r.text(); })
  .then(function (html) { applyFragments(html); scrollPreviewTo(selId); });
```

`scrollPreviewTo` is defined **inside the editor IIFE** (alongside `setHighlight` / `bindHover`)
so it closes over `root`; the snippet above relies on that scope.

**Failure handling:** the existing `.el-select` fetch has no `.catch` (`editor.js:151-152`). This
change deliberately keeps that behaviour rather than introducing an error path the rest of the
editor does not use. The added step is safe regardless: `scrollPreviewTo`'s `querySelector` returns
`null` when the id is absent — a failed/empty swap, or an element removed by the swap — and the
`if (el)` guard makes it a no-op, so it cannot throw even if `applyFragments` rendered nothing
useful.

Hover behaviour is unchanged: it still only toggles the highlight ring.

### 3. Contrast-safe highlight (CSS)

Replace the single ring with a two-layer `box-shadow`: the `--primary` ring plus a thin outer
halo in the pane surface colour, so the coloured ring is always separated from whatever is behind
the element. Bumped to 3px as requested.

```css
.prev-el--hl {
  box-shadow:
    0 0 0 3px var(--primary),
    0 0 0 5px var(--surface-raised);
}
```

(`editor.css:284`; the `.prev-el { ... transition: box-shadow .1s ease; }` rule at `editor.css:283`
is kept, so the two-layer ring fades in/out as before.) The outer ring is fixed to
`--surface-raised`, the preview pane's background, so it reads as a clean break on that surface. It
is a hardcoded token, not adaptive: if the preview surface ever changes, this halo colour must be
revisited.

## Components touched

| Change | File | Locus |
|--------|------|-------|
| Preview scroll container + responsive reset | `courses/static/courses/css/editor.css` | replace `:199`; extend `@media (max-width: 900px)` at `:208` |
| Contrast-safe highlight | `courses/static/courses/css/editor.css` | `:284` |
| Scroll-to-selected | `courses/static/courses/js/editor.js` | `.el-select` branch at `:149-153` (+ small helper) |

No template, view, model, or migration changes.

## Edge cases

- **Already-visible selection:** `block: "nearest"` is a no-op — no distracting motion.
- **Newly added element:** "Add" posts a different flow (`data-add-type`, `editor.js:125-135`) and
  does not carry a selected id; it is intentionally out of scope and keeps its current behaviour.
- **Deleted / moved element:** id may be gone after the swap; `scrollPreviewTo` guards on a missing
  node and silently does nothing.
- **`prefers-reduced-motion`:** gate the behaviour in JS — read
  `matchMedia("(prefers-reduced-motion: reduce)").matches` and pass `behavior: "auto"` when reduced
  motion is requested, `"smooth"` otherwise. Do **not** rely on the CSS `scroll-behavior` property
  here: an explicit `behavior` argument to `scrollIntoView` overrides CSS `scroll-behavior`, so a
  CSS-only media query would be silently ignored while the JS argument is present.
- **Short unit (preview shorter than viewport):** `max-height` is a cap, not a fixed height, so the
  pane shrinks to content and shows no scrollbar.

## Testing

- **Manual / visual (primary):** with a long unit, select rows top-to-bottom and confirm the
  preview scrolls each off-screen element into view while on-screen ones stay put; confirm the
  page itself does not jump. Confirm the editor column still flows with the page — scrolling the
  page moves through the editor rows while the preview stays pinned (the editor column must not gain
  its own height cap). Check the preview's rounded bottom corners are not visibly clipped by the
  scrollbar gutter. Hover a light element and a dark element and confirm the ring is clearly visible
  on both. Resize below 900px and confirm the preview stacks and scrolls with the page (no
  clipped/stuck pane).
- **Regression:** confirm fragment swaps (save/move/delete/add), the "Try it" preview forms, and
  KaTeX/MathLive re-render still work — i.e. the added `.then` does not disturb `applyFragments`.
- No new automated test is warranted for CSS ring colours / scroll behaviour; the existing editor
  e2e flow exercises the select path and must stay green.

## Risks

- Low. All three changes are additive and localised; the matching mechanism and swap flow are
  reused unchanged. The main thing to verify by eye is the `max-height` offset feeling right
  against the real header, and the halo colour reading well on the actual preview surfaces.
