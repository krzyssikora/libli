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
| `--preview-w` | `48rem` | student content width (46rem) + preview pane padding — the real student experience |
| `--editor-min` | `17rem` | editor never narrower than this (2-row element tiles still fit) |
| `--editor-split-max` | `48rem` | editor's cap in split = same as preview ("if the screen allows") |
| `--editor-solo-max` | `54rem` | editor's cap on its own — a bit wider than its split width |
| page max | `100rem` | editor-page `.app-main` cap (≈1620px): fits two student-width columns, then centers |

Components touched:

- **`courses/static/courses/css/editor.css`** — new tokens; rework `.editor-grid`
  and the `.preview-pane` / `.editor-pane` rules to the width model; add the three
  `is-mode-*` modifier rules; add the editor-page `.app-main` max-width override.
  The existing `@media (min-width: 901px)` viewport-lock + per-pane internal
  scrolling is retained and continues to work in all three modes (a single visible
  pane fills the locked height).
- **`templates/courses/manage/editor/_editor_scope.html`** (and/or `editor.html`) —
  render the segmented toggle above `.editor-grid`; add the pre-paint inline
  script that stamps the stored mode class before first paint.
- **`templates/courses/manage/editor/_preview.html`** — constrain the preview
  content region to `46rem` so it mirrors the student width inside the fixed
  preview column.
- **A small JS enhancer** — wire the toggle buttons to the mode class +
  `localStorage`. May live in `courses/static/courses/js/editor.js` or a small
  dedicated file, following existing editor JS conventions.

### Width model (derived behaviour)

- **Preview** is a **fixed** column of `--preview-w` in both split and solo modes,
  and its rendered content is constrained to `46rem` so it matches the student
  view exactly (desktop student layout; see Non-goals for mobile).
- **Editor in split** is `minmax(--editor-min, --editor-split-max)`. On a wide
  screen it reaches preview width (two equal columns); on a medium screen it takes
  whatever remains beside the fixed preview; below the stacking breakpoint it
  stacks. This is "same as preview if the screen allows, otherwise the rest of the
  width."
- **Editor solo** is a single centered column capped at `--editor-solo-max`.
- **The page**: only `body.editor-page` overrides the global 960px cap, up to
  `100rem`, then `margin: 0 auto` centers it. On narrower windows it is naturally
  100% wide. Not full-window on large monitors.

### The 3-way toggle

A segmented control labelled **Editor · Split · Preview** sits above the grid,
reusing the existing `.type-toggle` segmented-control look already on the page.
Selecting a mode sets a modifier class on `.editor-grid`
(`is-mode-editor` / `is-mode-split` / `is-mode-preview`) that swaps the grid
template and hides the inactive pane via CSS. The default class corresponds to
**Split** — byte-for-byte the current experience for anyone who never touches the
toggle.

Modes:

- **Split** (default) — both panes, widths per the model above.
- **Editor** — only the editor pane, single centered column at `--editor-solo-max`.
- **Preview** — only the preview pane, single centered column at `--preview-w`
  (full student width).

The toggle applies at all widths. Below the stacking breakpoint it is still
useful: preview-only or editor-only avoids the long stacked scroll.

## Data flow

The view mode is a single small piece of client-side UI state; there is no
server round-trip.

1. **Load.** A pre-paint inline `<script>` in the editor template reads the stored
   mode from `localStorage` (key e.g. `libli-editor-view`), validates it against
   the three known modes (anything else → `split`), and stamps the corresponding
   `is-mode-*` class on `.editor-grid` before first paint — so there is no flash of
   the wrong layout.
2. **Toggle.** The JS enhancer (wired on `DOMContentLoaded`) attaches click
   handlers to the three segment buttons. Clicking a segment swaps the
   `is-mode-*` class on `.editor-grid`, updates the pressed/active state on the
   buttons, and writes the new mode to `localStorage`.
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
  mode class server-side, so the editor degrades to today's exact behaviour (both
  panes, no toggle interactivity). No functional regression.

## Testing

- **CSS/layout** verified visually with Playwright screenshots (light + dark),
  per the project's "verify UI with screenshots" practice, at representative
  widths: a wide screen (~100rem+, two equal columns), a medium screen (editor
  narrower than preview), and below the stacking breakpoint. Capture each of the
  three modes.
- **JS enhancer** covered by a focused test: toggling updates the grid mode class
  and writes the expected `localStorage` value; an invalid/missing stored value
  falls back to Split; the pre-paint script applies the stored mode on load.
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
