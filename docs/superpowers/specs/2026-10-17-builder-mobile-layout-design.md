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
   lines, no single-line ellipsis.
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
there and the owner approved it). Draft units keep their strike-through.
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
Closes on outside tap, Escape, or choosing an item. Each item activates
the row's existing control (same `formaction`/`href`/`data-op`), so
builder.js's op handling, tokens and error paths are reused. The menu is
ONE shared element, populated from the tapped row; when an item is chosen
it re-finds the row by `data-node` (the row may have been replaced by an
`applyFragment` while the menu was open) and acts on the CURRENT row's
control; if the row is gone, the menu closes and does nothing. The ⋯
button is `type="button"` (it lives inside the rename form; a submit-type
button would submit a rename or hijack implicit submission) and is not
rendered visible without JS (`.js` gate) — the no-JS path keeps today's
visible cluster.

**Title element and Rename on phone (D8):** the phone title is a separate
non-input element in the row, with its OWN class (not `.tree__title`, so
none of builder.js's `.tree__title` focusin/keydown/focusout/input
handlers or the desktop debounce run on it). It is rendered server-side
next to the existing `input.tree__title`; the phone CSS hides the input
and shows the text, desktop the reverse. It must always show the input's
committed value: `applyRename` and `revert` (builder.js:280-320, 686-689)
must update it too, so after ⋯ → Rename → commit the row shows the new
title. Choosing Rename makes the title editable and commits through the
existing rename path (`form.tree__rowhead`, `commitRename`, concurrency
token); how the editable field is presented (inline in the row, or in a
small dialog) is left to the builder, subject to the anti-goals. **On the
phone layout, focusing the rename input never opens the sheet** — the
`focusin` panel load is desktop-only.

**What opens the sheet (phone layout):** the sheet opens on an explicit
tap only, never on focus:
1. a tap on a row's phone title element → load that node's panel;
2. Move… (from ⋯) → the picker loads into the panel and the sheet opens on
   it (the picker lives in the panel, so a closed sheet would make Move…
   do nothing);
3. the Kurs button → course panel (see below).
Panel-load failures ("Network error — please reload.") show inside the
open sheet. When builder.js restores `neutralPanel` after a picker
submit or `dismissPicker`, **the sheet closes** (the author returns to the
tree, where the move is visible). Every other `setPanel` call site keeps
its current behaviour and does not open the sheet.

**Sheet loading state:** when a row tap opens the sheet, the sheet opens
immediately showing a loading placeholder (never the previously shown
panel), and the requested node's panel replaces it when it arrives
(last-request-wins, as today). This prevents "Open editor →" on the wrong
unit — the split-a-unit task produces two rows with near-identical titles
("X" and "X (kopia)").

**Bottom sheet:** a sheet container (new markup, phone layout only)
that WRAPS the existing `.builder__panel` / `[data-panel]` element (course
panel, node panel, unit panel, move picker — panel content and `setPanel`
unchanged), anchored to the bottom, with its own scroll, a grab bar and
✕. On desktop the wrapper is layout-neutral and the panel renders exactly
as today. Height: about 2/3 of the
dynamic viewport height (`dvh`) in portrait, and near-full height in
landscape (a 410 px-tall landscape screen leaves too little at 2/3). The
tree behind is dimmed and inert (no taps, no focus); the page does not
scroll behind it. **Closing:** ✕, a tap on the dimmed area, Escape, and
**swipe down on the grab bar/sheet header** (promised in the approved
mockup — required, not optional). Device Back closing it is a nice-to-have.
The tree's scroll position (`scrollY`) and open/closed scopes are
identical before opening and after closing.

**Notices on the phone:** `notice()` (op errors, 409 conflicts, network
errors) prepends into the panel, which is usually closed on a phone.
On the phone layout notices must be visible without opening anything —
e.g. a fixed toast/bar over the tree — with the same 6 s lifetime and text.

**Escape and focus layering:** one Escape closes only the TOPMOST layer, in
this order: rename field (reverts, as today) → ⋯ menu → confirm strip →
move picker (dismissing the picker restores the course panel and closes
the sheet, per the rule above, in that one keypress) → sheet. Focus
returns to the opener: the row's ⋯ for menu actions and Move…, the row's
phone title for a row tap, the Kurs button for the course sheet. If that
row no longer exists (replaced or removed by `applyFragment`), focus goes
to the same row's replacement found by `data-node`, else to the Kurs
button. `dismissPicker`'s focus target (`a[data-move]`) is hidden on the
phone; on the phone layout it uses the ⋯ of that row instead.

**"Kurs" button (D7):** in the builder's top bar; opens the sheet and
replaces whatever the panel holds with the course panel via
`setPanel(neutralPanel)` (no fetch).

**Toolbar above the tree on a phone (D11):** the filter box stays visible
(it is how the author finds a unit). Import content, Export, Expand all,
Collapse all, the structure legend, the flag legend and the slide-break
help line are shown in the Kurs sheet **on the phone layout only**.
Mechanism (decided here to keep builder.js's whole-root queries
`[data-expand-all]`/`[data-collapse-all]`/`rewriteBulkHrefs` single-target):
these controls are **not duplicated**. They stay in the tree header DOM,
and on the phone layout JS **moves** that header group into a phone-only
section that sits **outside** `[data-panel]` but inside the sheet
container (so node-panel loads and `neutralPanel` restores never destroy
it), and moves it back when the layout reverts to desktop. The Kurs sheet
therefore shows: that phone-only section + the course panel. The bulk
links' hrefs must remain correct after a filter change (they are the same
elements `rewriteBulkHrefs` already updates). Choosing Expand all or
Collapse all **closes the sheet** so the author sees the tree change and
the existing busy dimming; the `data-expand-all-disabled` /
`aria-disabled` state and its explanation ("This course is too large to
expand at once.") stay, and on the phone the explanation is visible text,
not only a tooltip. The info slot (`.builder__info`, `role="status"`)
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
phone rules must win over them (order/specificity) — the 720 px stacking
stays exactly as today for non-touch narrow windows. Known limitation,
accepted: on a large tablet (desktop layout), tapping a title still brings
up the keyboard, exactly as today.

**Layout flip while open:** when the media query changes (e.g. a small
tablet rotates across 960 px), JS closes the ⋯ menu and the sheet, removes
the tree's inert state and any scroll lock, returns the moved header group
to its desktop place, and leaves an in-progress rename intact (its typed
value is not lost or committed by the flip). Desktop then looks exactly as
it does on a fresh desktop load.

## Constraints

- Bespoke token CSS, no frameworks (`ui-foundation-bespoke-from-bonnot`);
  icons are monochrome SVG (masked `.icm` icons in the tree, never emoji).
- Light and dark themes both; verify with screenshots of both.
- Polish UI strings via the existing i18n catalog (`makemessages`, both
  `.po` and compiled `.mo`). New strings expected: "Course"/"Kurs",
  "More actions" (⋯ aria-label), "Close", "Rename", "Loading…" (reuse any
  that already exist).
- Accessibility: ⋯ is a real `type="button"` with `aria-haspopup` /
  `aria-expanded`; the sheet is a modal dialog (focus moved in on open,
  returned per the layering rules on close). The project already uses
  `<dialog>` elsewhere — see the library gotchas index (dialog theme trap)
  before choosing it.
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
   sheet, a move completes and the sheet closes.
5. The loading placeholder shows on open; the previously shown panel is
   never visible for the new row.
6. A 409 or network notice is visible with the sheet closed.
7. Container publish via the confirm strip at 390×844 (renders within the
   width, ✕ and Escape dismiss).
8. Kurs sheet: course panel + moved toolbar group; Expand all/Collapse all
   close the sheet and act; bulk hrefs correct after a filter change.
9. Layout flip across 960 px with the sheet open: sheet/menu closed, no
   inert/scroll lock left, header group back in place.
10. Desktop no-regression: a ~945 px mouse window keeps the desktop
    layout with rename-in-place, drag and the Tab debounce intact; the
    existing builder e2e suite stays green.

## Left to the builder

- Exact sheet mechanics (CSS transform vs `<dialog>`, animation; respect
  `prefers-reduced-motion`) — within the closing rules above.
- How Rename's editable field is presented (subject to D8 + anti-goals).
- One-letter mapping for container kinds (e.g. C = Część, R = Rozdział,
  S = Sekcja) — derive from the existing kind display names; keep the full
  name as `title`/accessible name.
- Exact indent value, and the menu's position (anchored to ⋯ or a small
  bottom action sheet).
- Whether the "+ Sekcja / + Lekcja / + Quiz" add affordances need any
  phone tweak (they looked acceptable in the screenshots).
- The notice presentation on the phone (toast/bar), within the rule above.
