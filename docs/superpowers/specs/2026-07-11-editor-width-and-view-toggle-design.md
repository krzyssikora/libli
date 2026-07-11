# Editor width & 3-way view toggle

## Problem

The course editor page is capped by the app-wide `.app-main { max-width: 960px }`
(`core/static/core/css/app.css:34`). Inside that cap the editor grid splits the
space into a narrow editor column (`minmax(17rem, 22rem)`) and a `1fr` preview
column, so the live preview renders at roughly 560px — far narrower than a real
student screen. Authoring a course this way is cramped: both the editor form and
the preview fight over half the width they should have.

## Goal

Give the preview real student width and the editor more comfortable room, and let
the author focus on either pane. Specifically:

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

## Width model

All widths are driven off a small set of tokens scoped to the editor page. The
grounding fact is the student content width: `.lesson { max-width: 46rem }`
(`courses/static/courses/css/courses.css:118`).

| Token | Value | Meaning |
|---|---|---|
| `--preview-w` | `48rem` | student content width (46rem) + preview pane padding — the real student experience |
| `--editor-min` | `17rem` | editor never narrower than this (2-row element tiles still fit) |
| `--editor-split-max` | `48rem` | editor's cap in split = same as preview ("if the screen allows") |
| `--editor-solo-max` | `54rem` | editor's cap on its own — a bit wider than its split width |
| page max | `100rem` | editor-page `.app-main` cap (≈1620px): fits two student-width columns, then centers |

Derived behaviour:

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

## The 3-way toggle

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

## Persistence

The chosen mode is a workflow preference (not per-unit content), so it persists
**globally** in `localStorage` under a single key (e.g. `libli-editor-view`),
consistent with the recent "persist tab open-state across refresh" work.

To avoid a flash of the wrong layout on reload, a tiny **pre-paint inline script**
in the editor template reads the stored mode and stamps the mode class on the grid
(or a parent) before first paint. The JS enhancer then wires the toggle buttons:
clicking a segment updates the class and writes `localStorage`. Values are
validated against the three known modes; anything else falls back to Split.

## Components

- **`editor.css`** — new tokens; rework `.editor-grid` and the `.preview-pane` /
  `.editor-pane` rules to the width model; add the three `is-mode-*` rules; add
  the editor-page `.app-main` max-width override. The existing
  `@media (min-width: 901px)` viewport-lock + per-pane internal scrolling is
  retained and continues to work in all three modes (a single visible pane fills
  the locked height).
- **`_editor_scope.html`** (or `editor.html`) — render the segmented toggle above
  `.editor-grid`; add the pre-paint inline script.
- **`_preview.html`** — constrain the preview content region to `46rem` so it
  mirrors the student width inside the fixed preview column.
- **A small JS enhancer** — wire the toggle to the mode class + `localStorage`.
  Can live in `editor.js` or a small dedicated file, following existing editor JS
  conventions.

## Testing

- **CSS/layout** verified visually with Playwright screenshots (light + dark),
  per the project's "verify UI with screenshots" practice, at representative
  widths: a wide screen (~100rem+, two equal columns), a medium screen (editor
  narrower than preview), and below the stacking breakpoint. Capture each of the
  three modes.
- **JS enhancer** covered by a focused test: toggling updates the grid mode class
  and writes the expected `localStorage` value; an invalid/missing stored value
  falls back to Split; the pre-paint script applies the stored mode on load.
- Full existing editor test suite stays green (no backend surface changed).

## Non-goals

- No responsive/mobile emulation inside the preview — the preview reproduces the
  **desktop** student width (46rem). Matching the phone student layout at a
  narrow breakpoint is out of scope.
- No per-unit or per-user server-side persistence — `localStorage` only.
- No changes to what the preview renders or how elements are tried; only its
  width changes.
- No changes to any page other than the editor.
