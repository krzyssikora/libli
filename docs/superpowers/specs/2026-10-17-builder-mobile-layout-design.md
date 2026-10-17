# Course builder on a phone — design

Date: 2026-10-17 · Status: approved by the owner 2026-10-17 ("lgtm")
Mockup (approved by the owner 2026-10-17, "mockups look great!"):
`docs/mockups/builder-mobile-layout.html` (an HTML fragment; wireframe only)

## Intent and why

The course builder (`templates/courses/manage/builder.html`, `builder.css`,
`builder.js`) cannot be used from the mobile PWA:

- **Portrait (~390 CSS px):** every row has ~11 fixed-width items (toggle,
  kind badge, publish flag, obligatory flag, grip, ↑, ↓, move…, export,
  duplicate, delete). The title `<input>` is the only shrinkable item and
  gets 0–2 characters ("G…"). Each nesting level adds ~50 px of indent.
  Below 720 px the detail panel (`.builder__panel`) is stacked UNDER the
  whole tree, so tapping a row loads a panel the author cannot see.
- **Landscape (~890 CSS px):** the 2fr/1fr grid gives the panel a third of
  the width; titles show ~10 characters.

The real task that failed (owner, 2026-10-17): **split a unit in two** —
find the unit, duplicate it, rename the copy, then open each in the unit
editor and delete elements. The builder half of that (find → duplicate →
rename → open editor) must work comfortably on a phone. The unit editor
itself was fine on the phone (its separate scroll-jump bug is a different
piece of work, not in this design).

## Goals

1. Titles readable on a phone in both orientations: wrap to at most two
   lines, no single-line ellipsis. A title longer than two lines is
   clamped with an ellipsis at the end of line 2 (`line-clamp: 2`); the
   full title is always visible unclamped in the ⋯ menu header and in the
   sheet's panel heading.
2. Every action available today on a row stays available on a phone.
3. Tapping a row shows its detail panel **on screen**, without losing the
   author's place in the tree.
4. Course-level actions (metadata, media library, quiz review, analytics)
   reachable without scrolling past the tree.

## Non-goals

- No change to desktop behaviour or look above the breakpoint.
- No change to the unit editor (`editor.html`).
- No new actions, no server/view changes beyond what the layout strictly
  needs (none expected: every action already exists as a form/link).
- No drag-and-drop on touch.

## Anti-goals (would count as failure even if it "works")

- A tap meant to *look at* a unit pops up the on-screen keyboard.
- The panel appears somewhere the author must scroll to find.
- Closing the panel loses the tree's scroll position or expanded state.
- Desktop regresses in any way (rename-in-place, drag, keyboard Tab
  traversal with the 150 ms debounced panel load, focus-driven panel).

## Decided with the owner (verbatim intent)

| # | Decision |
|---|---|
| D1 | Row actions ↑, ↓, Move…, Export, Duplicate, Delete collapse into **one ⋯ button per row** that opens a small menu. |
| D2 | The drag handle is **hidden** on the phone layout (↑/↓ and Move… cover reordering). |
| D3 | Container badges (`CZĘŚĆ`, `ROZDZIAŁ`, and any other container kind) become **one-letter circles** like the existing `L`/`Q` unit badges. |
| D4 | **Smaller indent** per nesting level. |
| D5 | Titles **wrap to two lines** instead of an ellipsis. |
| D6 | The detail panel becomes a **bottom sheet that slides up over the tree** when a row is tapped, with a close (✕) control; the tree stays where it was underneath. **Both orientations.** (Owner chose this over "panel below the tree".) |
| D7 | The course panel opens the same way, from a small **"Kurs" button at the top** of the tree. |
| D8 | On the phone, the title is **plain text**; tapping it opens the sheet; **renaming moves into the ⋯ menu** ("Zmień nazwę"). Desktop keeps the editable title. (Shown in the approved mockup's notes.) |
| D9 | Landscape uses the **same** layout as portrait. |
| D10 | The phone layout applies when **touch is the primary input AND the screen is narrower than 960 px**. Large tablets and touch-screen laptops keep the desktop layout. |
| D11 | On the phone, the **filter box stays visible**; Import, Export, Expand all, Collapse all, the legends and the help line move into the **"Kurs" sheet**. Desktop unchanged. |

## Shape of the solution (from the approved mockup)

**Row (phone):** toggle · one-letter badge · title (≤2 lines, takes all
free width) · publish ○ · obligatory ★ · ⋯. Publish/obligatory stay on the
row because they are glanceable status (my call — the mockup shows them
there and the owner approved it). Draft units keep their strike-through. On the phone layout `.builder`'s
two-column grid (and the 720 px stacking) gives way to a full-width
`.builder__tree`; the sheet wrapper is taken out of flow (fixed), so the
tree uses the whole viewport width in both orientations.
On desktop `builder.css:194-198` puts the flags LEFT of the title
(`.tree__flag` order 3, title order 4); the phone layout overrides flex
`order` so they sit after the title. DOM order is NOT changed (the hidden
Rename button must stay ahead of every other submit button so Enter
renames — `_tree_node.html` comment).

Plain unit flag buttons are one-tap toggles. Container flags, and a
published quiz with submissions, are `data-flag-confirm` anchors that open a
confirm strip under the row (`insertStripAfterRowhead`); on the phone that
strip must fit 390 px and its ✕/Escape must keep working alongside the
menu and sheet. Under an active filter, inert container flags explain
themselves only via `title` (no tooltip on touch) — accepted as-is for
flags; not a regression.

**⋯ menu:** header = the row's title; items in this order: Rename, Move
up, Move down, Move…, Duplicate (units only, as today), Export, Delete
(danger colour, last). Disabled states mirror today's (first/last row,
active filter); when Move up/down are disabled because a filter is active,
the menu shows the reason as visible text ("Clear the filter to reorder.",
the existing string) because `title` tooltips never appear on touch.
Closes on outside tap, Escape, or choosing an item. Choosing an item
dispatches activation on the row's REAL control (`control.click()` on the
element re-found by `data-node`), so the event bubbles through `root` and
builder.js's delegated handlers run unchanged: Move…'s fetch, Delete's
stamping of the live `open` set (builder.js:1091-1097), the op submit
interception, tokens and error paths. The menu never copies hrefs or
formactions onto its own elements and never submits forms itself.
**Focus after an item:** before the menu hides, focus moves to the row's
⋯; after the op's `applyFragment`, focus goes to the ⋯ re-found by
`data-node` (the same node for Move up/down, the original row for
Duplicate), so a keyboard or switch user keeps their place. Items that
open the sheet (Move…) follow the sheet's focus rules instead.
**Rename is the one exception:** it clicks no row control (and must never
`click()` the visually hidden submit button, which would submit the
unchanged title); it opens the editable field for that row (see the
title section below) and the commit goes through `commitRename`. The menu is
ONE shared element, populated from the tapped row; when an item is chosen
it re-finds the row by `data-node` (the row may have been replaced by an
`applyFragment` while the menu was open) and acts on the CURRENT row's
control; if the row is gone, the menu closes and does nothing. The ⋯
button is `type="button"` (it lives inside the rename form; a submit-type
button would submit a rename or hijack implicit submission) and is not
rendered visible without JS (`.js` gate) — the no-JS path keeps today's
visible cluster.

**Title element and Rename on phone (D8):** the phone title is a separate
`<button type="button">` holding the title text (focusable, Enter/Space
activate it; `type="button"` because it sits inside the rename form and
must never become a submitter), with its OWN class (not `.tree__title`, so
none of builder.js's `.tree__title` focusin/keydown/focusout/input
handlers or the desktop debounce run on it). It is rendered server-side
next to the existing `input.tree__title`; the phone CSS hides the input
and shows the text, desktop the reverse. It carries the draft
strike-through like the input, and its text is the row's accessible name
for opening the sheet. It must always show the input's
committed value: `applyRename` and `revert` (builder.js:280-320, 686-689)
must update it too, so after ⋯ → Rename → commit the row shows the new
title. Choosing Rename makes the title editable and commits through the
existing rename path (`form.tree__rowhead`, `commitRename`, concurrency
token); how the editable field is presented (inline in the row, or in a
small dialog) is left to the builder, subject to the anti-goals. **Exit
from the phone editing state:** Escape reverts (as today) and exits; a
successful commit exits after `applyRename`; a 409 (the row is re-rendered
by `applyFragment`) exits with the server's title; a 422 keeps the field
editing with the notice shown; blur/tap outside commits as on desktop,
then exits. On the Escape, Enter-commit and 409 exits, focus first moves
to the row's ⋯ (the Rename opener; re-found by `data-node` if the row was
replaced), and only then is the input hidden — focus never lands on a
hidden element, and hiding never triggers the focusout commit. On a
**blur exit** focus is left wherever the author put it (the filter,
another row's title…); the input, no longer focused, is simply hidden
when the commit settles, and focus is never pulled back to ⋯. **On the
phone layout, focusing the rename input never opens the sheet** — the
`focusin` panel load is desktop-only.

**What opens the sheet (phone layout):** the sheet opens on an explicit
tap only, never on focus:
1. a tap on a row's phone title element → load that node's panel;
2. Move… (from ⋯) → the sheet opens and the picker loads into the panel
   (the picker lives in the panel, so a closed sheet would make Move… do
   nothing);
3. the Kurs button → course panel (see below).
Panel-load failures ("Network error — please reload.") show inside the
open sheet. When builder.js restores `neutralPanel` after a picker
submit or `dismissPicker`, **the sheet closes** (the author returns to the
tree, where the move is visible). The close is attached to those two call
sites (`dismissPicker`, and the picker-submit `if (inPanel)
setPanel(neutralPanel)` at builder.js:464) — never detected inside
`setPanel` by comparing against `neutralPanel`, because Kurs makes the
same call to OPEN the sheet. Every other `setPanel` call site keeps
its current behaviour and does not open the sheet.

**Sheet loading state:** when a row tap or Move… opens the sheet, the
sheet opens immediately showing a loading placeholder (never the
previously shown panel) — written through `setPanel` with a stable marker
(`data-panel-loading`) that tests can assert on; the "Nine call sites"
comment above `setPanel` is updated to the new count — and the requested node's panel / the picker (or
its network error) replaces it when it arrives. **One last-request-wins
sequence covers every sheet-opening write:** a row tap, Move… and Kurs
each invalidate any pending node-panel load (bump `panelReq`, clear
`panelTimer`), and the Move… picker fetch is guarded by the same counter,
so a late response can never overwrite newer sheet content (and never
leaves `movingPk`/`.moving` set without a visible picker). **Every
close path also invalidates pending sheet loads** (bump `panelReq`, clear
`panelTimer`): a node-panel or picker response arriving after the sheet
closed is dropped, so `initPicker` never runs for a closed sheet. This
prevents "Open editor →" on the wrong unit — the split-a-unit task
produces two rows with near-identical titles ("X" and "X (kopia)").

**Bottom sheet:** a sheet container (new markup, phone layout only)
that WRAPS the existing `.builder__panel` / `[data-panel]` element (course
panel, node panel, unit panel, move picker — panel content and `setPanel`
unchanged), anchored to the bottom, with a grab bar and ✕. On the
phone the **wrapper's body is the single scroll container** (it holds the
phone toolbar section and the panel); `[data-panel]` itself does not
scroll there. `setPanel` stays the single writer of panel content and, on
the phone layout, also resets the wrapper body's `scrollTop` to 0; every
sheet open resets it too, so a sheet never opens mid-way down. On desktop the wrapper is layout-neutral and the panel renders exactly
as today: outside the phone media query the wrapper is `display: contents`
(so `.builder__panel` stays the grid item with its sticky positioning,
`align-self`, max-height and the 720 px stacked override all unchanged),
and the grab bar, ✕, phone toolbar section, dim layer and toast
container are `display: none`. The dim layer is part of the sheet
wrapper (or its sibling), outside the inert container, so it receives the
close tap. The wrapper is **not** a `<dialog>` element (a closed
`<dialog>` is `display:none` and would hide the desktop panel, and
`showModal`'s native Escape/`cancel` would bypass the layering rules);
modal semantics come from `role="dialog"` + `aria-modal="true"` on the
wrapper, present on the phone layout **only while the sheet is open**.
A closed sheet on the phone layout is removed from the tab order and the
accessibility tree (`visibility: hidden` once the close transition ends,
plus `inert`), so Tab from the tree never reaches its controls. Height: about 2/3 of the
dynamic viewport height (`dvh`) in portrait, and near-full height in
landscape (a 410 px-tall landscape screen leaves too little at 2/3). While
the sheet is open, everything else in the builder — the tree, the filter
box, the Kurs button, the info slot — is dimmed and `inert` (no taps, no
focus); only the sheet, and the notice toast, stay live. Implementation
shape: the builder content other than the sheet wrapper sits in one
container that receives `inert` (the sheet cannot live inside an inert
ancestor). The page does not scroll behind it: the sheet's scroll body
has `overscroll-behavior: contain`, the page scroll is locked while the
sheet is open, and whatever lock technique is used restores the exact
`scrollY` on close. **Closing:** ✕, a tap on the dimmed area, Escape, and
**swipe down on the grab bar/sheet header** (promised in the approved
mockup — required, not optional). Device Back closing it is a nice-to-have.
The tree's scroll position (`scrollY`) and open/closed scopes are
identical before opening and after closing. **Closing while the move
picker is showing — by any path (✕, dimmed-area tap, swipe, Escape) — runs
the same cleanup as `dismissPicker`** (`clearMoving`, restore
`neutralPanel`), so no picker, `movingPk` or `.moving` highlight survives
a closed sheet. Swipe-down is implemented with **pointer events** (touch
pointers), and its e2e drives it with real touch input (CDP
`Input.dispatchTouchEvent` start → several moves → end), which the browser
turns into touch-type pointer events. The swipe area (grab bar + sheet
header) has `touch-action: none` so the browser does not claim the drag
for panning and fire `pointercancel`. It closes only past a minimum
downward travel (my call: 80 px or a quarter of the sheet height,
whichever is smaller); a shorter drag, or `pointercancel`, snaps the sheet
back. A tap (no travel) on the close button or the header is never a swipe.

**Notices on the phone:** `notice()` (op errors, 409 conflicts, network
errors) prepends into the panel, which is usually closed on a phone.
On the phone layout notices must be visible without opening anything —
e.g. a fixed toast/bar — with the same 6 s lifetime and text. When the
sheet is open, the toast sits ABOVE the sheet and its dim layer (e.g. a
422 from a picker submit is visible). The toast's container sits OUTSIDE
the inert container (a sibling of the sheet wrapper inside `.builder`),
is `position: fixed` (never an in-flow `.builder` grid item) and
`display: none` outside the phone layout, and carries `role="alert"` so
assistive tech announces it.

**Escape and focus layering:** one Escape closes only the TOPMOST layer.
There are two layers:
- **Tree layer** (active only while the sheet is closed): rename field
  or inline add-title input (`[data-add-title]`; Escape reverts/cancels,
  as today) → ⋯ menu → confirm strip. Opening the ⋯ menu closes any open
  add row.
- **Sheet layer** (while the sheet is open): move picker (dismissing the
  picker restores the course panel and closes the sheet, per the rule
  above, in that one keypress) → sheet.
While the sheet is open, ONE handler owns Escape: the sheet's handler
runs first (capture phase on `document`), performs the sheet-layer step,
and calls `preventDefault()`, so builder.js's existing document-level
picker Escape handler (builder.js:127-136) hits its `e.defaultPrevented`
early return and never double-dismisses. With the sheet closed the
existing handlers behave as today.
**Close ordering:** every close path — including the one inside
`dismissPicker` and the picker-submit success/409 branch that calls
`setPanel(neutralPanel)` — closes the sheet and removes `inert` and the
scroll lock **before** any focus-return call (`focus()` on an inert
element is silently ignored). The info slot's live-region update
(`applyInfo`) runs before the sheet closes in the picker-submit path, so
that one announcement may be lost while the slot is inert; accepted
limitation (my call) — the slot's text is visible once the sheet closes.
Opening the sheet closes the ⋯ menu and dismisses any open confirm strip
(via `dismissStrip`) first, so nothing from the tree layer lingers under
the sheet. Focus
returns to the opener: the row's ⋯ for menu actions and Move…, the row's
phone title for a row tap, the Kurs button for the course sheet. If that
row no longer exists (replaced or removed by `applyFragment`), focus goes
to the same row's replacement found by `data-node`, else to the Kurs
button. `dismissPicker`'s focus target (`a[data-move]`) is hidden on the
phone; on the phone layout it uses the ⋯ of that row instead, and its
`panel.focus()` fallback is replaced by the Kurs button — focus never
lands on a hidden element.

**"Kurs" button (D7):** rendered for every layout but hidden on desktop,
inside `header.manage__head` next to the never-moving items (the h1 and
the filter), never inside a moved group, so it never ends up in the sheet
it opens. On the phone layout the header row that remains (course title,
Kurs, filter) is `position: sticky` at the top of the viewport, so Kurs
and the filter are reachable from deep in a long tree (my call). Its
height is bounded: the h1 is clamped to one line with an ellipsis, and
Kurs + the filter form stay on one row, so the sticky header stays at
or below ~25% of the viewport height even in ~890×410 landscape. Kurs
opens the sheet and
replaces whatever the panel holds with the course panel via
`setPanel(neutralPanel)` (no fetch).

**Toolbar above the tree on a phone (D11):** the filter box stays visible
(it is how the author finds a unit). Import content, Export, Expand all,
Collapse all, the structure legend, the flag legend and the slide-break
help line are shown in the Kurs sheet **on the phone layout only**.
Mechanism (decided here to keep builder.js's whole-root queries
`[data-expand-all]`/`[data-collapse-all]`/`rewriteBulkHrefs` single-target):
these controls are **not duplicated**. Exactly these nodes move: Import
content, Export, Expand all, Collapse all (all four inside
`header.manage__head`, where the filter sits between Export and Expand
all), the structure legend, the flag legend and the slide-break help line
(siblings after the header). These stay put: the h1, the filter form, the
Kurs button, the info slot. To make the move exact, the template wraps
the movable items in new server-rendered containers that are
layout-neutral on desktop (`display: contents`, so the header's flex row
and today's look are unchanged): one around Import+Export, one around
Expand all+Collapse all, one around the two legends + help line. On the
phone layout JS moves those three containers, in order, into a
phone-only section that sits **outside** `[data-panel]` but inside the
sheet wrapper (so node-panel loads and `neutralPanel` restores never
destroy it); each container's original position is remembered with an
empty marker (a comment node or `<template>` placeholder left in its
place), and on phone -> desktop each container is put back immediately
before its marker, restoring the exact original order. The forward move
runs on first load when the phone layout already applies, and whenever
the layout flips desktop → phone. The Kurs sheet
therefore shows: that phone-only section + the course panel. The
phone-only section is visible **only** in a sheet opened by Kurs; a sheet
opened by a row tap or Move… hides it (a sheet-mode set by each opener,
under the same last-request-wins counter), so node panels and the picker
start at the top of the sheet. The bulk
links' hrefs must remain correct after a filter change (they are the same
elements `rewriteBulkHrefs` already updates). Choosing Expand all or
Collapse all **closes the sheet** so the author sees the tree change and
the existing busy dimming; the `data-expand-all-disabled` /
`aria-disabled` state and its explanation ("This course is too large to
expand at once.") stay, and on the phone the explanation is visible text,
not only a tooltip. Tapping the disabled Expand all does nothing and
leaves the sheet open, so the explanation stays readable. The info slot (`.builder__info`, `role="status"`)
stays visible above the tree on the phone.

**When the phone layout applies (D10):** `(pointer: coarse) and
(max-width: 959.98px)` — the PRIMARY pointer is touch AND the viewport is
narrower than 960 px. Use `pointer`, never `any-pointer`: a touch-screen
laptop's primary pointer is its trackpad/mouse, so it must keep the desktop
layout. Phones (both orientations, landscape up to ~932 px) and small
tablets in portrait get the phone layout; large tablets, touch laptops and
mouse-driven desktop windows of ANY width (incl. half-screen ~945 px) keep
the desktop layout. The same condition gates the CSS and the JS behaviour
(`matchMedia`, listening for changes — e.g. rotation). Today's width-only
720 px rules (`builder.css:2`, `:22-24`) also match a 390 px phone; the
phone rules must win over them (order/specificity), and must also reset
the BASE `.builder__panel` rule (`position: sticky`, `max-height`,
`overflow`, builder.css:10-17), which is in force in landscape (>720 px)
and would make the panel a second scroll container — the 720 px stacking
stays exactly as today for non-touch narrow windows. Known limitation,
accepted: on a large tablet (desktop layout), tapping a title still brings
up the keyboard, exactly as today.

**Layout flip while open:** when the media query changes desktop → phone
while a node panel or picker shows in the desktop panel, the panel keeps
its content and the sheet stays closed (the author can reopen it); a
showing picker is dismissed (`dismissPicker` cleanup). If a rename is in
progress (the title input focused or dirty), the flip neither commits nor
loses it: the row enters the phone Rename editing state with the typed
value preserved and focused (hiding a focused input would blur it and let
builder.js's focusout handler commit a half-typed title). When it changes
phone → desktop (e.g. a small tablet rotates across 960 px), JS closes the
⋯ menu and the sheet, removes the inert state and any scroll lock, returns
the moved containers to their desktop places, and leaves an in-progress
rename intact (its typed value is not lost or committed by the flip). The
panel is reset with the `dismissPicker` cleanup: a showing picker is
dismissed and the panel shows the course panel; a pending node-panel load
or loading placeholder is invalidated (bump `panelReq`) so the panel also
ends on the course panel. Desktop's chrome and layout then match a fresh
desktop load (and so does the panel content: the course panel).

## Constraints

- Bespoke token CSS, no frameworks (`ui-foundation-bespoke-from-bonnot`);
  icons are monochrome SVG (masked `.icm` icons in the tree, never emoji).
- Light and dark themes both; verify with screenshots of both.
- Polish UI strings via the existing i18n catalog (`makemessages`, both
  `.po` and compiled `.mo`). New strings expected: "Course"/"Kurs",
  "More actions" (⋯ aria-label), "Close", "Rename", "Loading…", "Details" (reuse any
  that already exist).
- Accessibility: ⋯ is a real `type="button"` with `aria-expanded` and
  `aria-controls` pointing at the shared menu — a plain **disclosure**,
  not an ARIA `role="menu"` (no `aria-haspopup="menu"`, no arrow-key
  model): on open, focus moves to the first enabled item, items are
  reached with Tab/Shift+Tab, Escape closes the menu and returns focus to
  ⋯. The sheet wrapper is a modal dialog via `role="dialog"` +
  `aria-modal="true"` + a fixed `aria-label` (new i18n string
  "Details"/"Szczegóły"; not `aria-labelledby`, whose target `setPanel`
  would replace) (phone only; NOT a `<dialog>`
  element, see Bottom sheet). On open, focus moves to a **stable target
  that `setPanel` never replaces** — the sheet's ✕ button — so it survives
  the placeholder being replaced by the panel or picker; focus is
  returned per the layering rules on close.
- Row DOM is large on big courses (mat-pp: ~2,900 rows when fully
  expanded; see the comment at the top of `_tree_node.html`). Do not
  duplicate per-row controls into a second per-row menu DOM; the one
  shared menu above is required. The extra per-row phone title element is
  the only per-row addition.
- builder.js's focus-driven panel load (`focusin` on `.tree__title`,
  `builder.js:645-667`) and its pointer/keyboard debounce keep working on
  desktop, unchanged.
- `setPanel` stays the single writer of panel content
  (`tests/test_builder_js_invariants.py` enforces it).

## Required tests (e2e drive the real UI)

Phone tests emulate touch (`has_touch`/`is_mobile`) so `pointer: coarse`
matches, at 390×844 portrait and ~890×410 landscape. At minimum:
1. **Split-a-unit flow on a phone:** filter → ⋯ Duplicate → ⋯ Rename the
   copy (the visible phone title changes) → tap the copy → the sheet shows
   the copy (not the original) → "Open editor →" opens the copy's editor.
2. Tapping a title focuses no text input (`document.activeElement` is not
   an input) and no keyboard-bearing element.
3. Open and close the sheet from a deep scroll position: `scrollY` and the
   set of open scopes are identical after closing; ✕, dimmed-area tap,
   Escape and swipe-down each close it.
4. Every ⋯ item works from the menu, including disabled first/last and
   filter states (with the visible reason); Move… opens the picker in the
   sheet, a move completes and the sheet closes. After ⋯ Move up,
   `document.activeElement` is that node's ⋯.
5. The loading placeholder shows on open; the previously shown panel is
   never visible for the new row; after the panel arrives
   `document.activeElement` is still inside the sheet wrapper. In
   landscape `[data-panel]` has no scroll overflow of its own. Scroll a
   Kurs sheet down, close it, tap a row: the new sheet starts at the top.
6. A 409 or network notice is visible with the sheet closed.
7. Container publish via the confirm strip at 390×844 (renders within the
   width, ✕ and Escape dismiss).
8. Kurs sheet: course panel + moved toolbar group; Expand all/Collapse all
   close the sheet and act; bulk hrefs correct after a filter change. A
   row-tap sheet and a Move… sheet do NOT show the toolbar section. A
   disabled Expand all leaves the sheet open with its explanation.
9. Layout flips (mechanism: a touch context — `has_touch`/`is_mobile`
   cannot change mid-context — and `set_viewport_size` across 960 px,
   e.g. 1000 → 900 → 1000, asserting the `matchMedia` result before
   acting): desktop → phone while typing a rename (no commit, typed
   value kept in the phone editing state); phone → desktop with the sheet open (sheet/menu closed,
   no inert/scroll lock left, header group back in place); desktop →
   phone with a node panel and with a picker showing (header group moved,
   sheet closed, picker dismissed, Kurs visible).
10. Race: hold a slow node-panel response, then tap Kurs (and separately
    ⋯ Move…); the late response must not overwrite the sheet. Hold the
    picker response, close the sheet, release it: no `.moving` row, and
    the next Kurs sheet shows no picker. With the sheet closed, Tab from
    the last tree row never reaches the panel or the toolbar section.
    ⋯ Rename, type, tap the filter: one POST, and focus stays in the
    filter after the response.
11. Keyboard: the phone title opens the sheet with Enter; focus returns
    to it on close. A title longer than two lines wraps to two lines with
    an ellipsis at the end of line 2 (no single-line ellipsis), and its
    full text is shown in the ⋯ menu header.
12. Modality: with the sheet open, a tap on a tree row, the filter or Kurs
    does nothing, Tab cannot reach any of them, and `scrollY` does not
    change on a real touch-drag scroll attempt (CDP touch events, not
    `window.scrollBy`). (Page chrome outside `.builder` — the site
    header/nav — is not made inert; accepted limitation, my call.)
13. A 422 from a picker submit shows a visible toast while the sheet is
    open (toast above the sheet and its dim layer).
14. Escape layering: with the ⋯ menu open over an open confirm strip, one
    Escape closes only the menu; with the picker showing in the sheet, one
    Escape dismisses the picker and closes the sheet.
15. Focus return: focus lands on the row's ⋯ after closing a Move… sheet,
    including when that row was replaced by `applyFragment` (found by
    `data-node`); on Kurs after closing the course sheet.
16. Fresh phone load: a page loaded at 390×844 already has the moved
    containers in the Kurs sheet section and the filter, h1 and Kurs in
    the sticky header row; in landscape (~890×410) a row's title box is
    wider than 60% of the viewport and the sticky header is at most ~25%
    of the viewport height (with a long course title).
17. ⋯ Rename then Escape: no POST is sent, the title is unchanged,
    `document.activeElement` is the row's ⋯. ⋯ Rename then Enter: one
    POST, the phone title shows the new value, focus on ⋯.
18. ⋯ Delete chosen from the menu carries the current `open` set in its
    href (proves activation goes through the real control).
19. Desktop no-regression: a ~945 px mouse window keeps the desktop
    layout with rename-in-place, drag and the Tab debounce intact; the
    desktop header looks and orders exactly as before; on a long tree the
    panel stays in the viewport after scrolling (sticky, its top near
    `--space-4`); no new grid row or gap appears; the existing builder
    e2e suite stays green.

## Left to the builder

- The sheet's animation technique (e.g. CSS transform/transition) and
  respecting `prefers-reduced-motion` — within the closing rules above
  (the wrapper is never a `<dialog>`).
- How Rename's editable field is presented (subject to D8 + anti-goals).
- One-letter mapping for container kinds (e.g. C = Część, R = Rozdział,
  S = Sekcja) — derive from the existing kind display names; keep the full
  name as `title`/accessible name.
- Exact indent value, and the menu's position (anchored to ⋯ or a small
  bottom action sheet).
- Whether the "+ Sekcja / + Lekcja / + Quiz" add affordances need any
  phone tweak (they looked acceptable in the screenshots).
- The notice presentation on the phone (toast/bar), within the rule above.
