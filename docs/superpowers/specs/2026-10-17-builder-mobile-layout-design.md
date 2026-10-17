# Course builder on a phone — design

Date: 2026-10-17 · Status: draft for owner approval
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
row because they are glanceable status and one-tap toggles (my call — the
mockup shows them there and the owner approved it). Draft units keep their
strike-through.

**⋯ menu:** header = the row's title; items in this order: Rename, Move
up, Move down, Move…, Duplicate (units only, as today), Export, Delete
(danger colour, last). Disabled states mirror today's (first/last row,
active filter). Closes on outside tap, Escape, or choosing an item. Each
item triggers exactly the existing control (same `formaction`/`href`/
`data-op`), so builder.js's op handling, tokens and error paths are reused
unchanged.

**Rename on phone:** choosing Rename must let the author edit the title
and commit through the existing rename path (`form.tree__rowhead`,
`commitRename`, concurrency token). How the editable field is presented
(inline in the row, or in the sheet/a small dialog) is left to the builder,
subject to the anti-goals and D8.

**Bottom sheet:** the existing `.builder__panel` content (course panel,
node panel, unit panel — whatever builder.js loads today) shown in a
sheet anchored to the bottom, ~2/3 of the viewport height, its own
scroll, a grab bar and ✕. The tree behind is dimmed and inert; tap on the
dimmed area, ✕, Escape or the device Back gesture closes it (Back: see
"left to the builder"). The tree's scroll position and open/closed state
survive open/close. Content that today swaps in the panel after an op
(e.g. the op-error box `.builder__panel > .op-error`) must still be seen
by the author on a phone — the builder decides whether that opens the
sheet or shows inline.

**"Kurs" button:** in the builder's top area; opens the sheet with the
course panel (`_course_panel.html`).

**When the phone layout applies (D10):** `(pointer: coarse) and
(max-width: 959.98px)` — the PRIMARY pointer is touch AND the viewport is
narrower than 960 px. Use `pointer`, never `any-pointer`: a touch-screen
laptop's primary pointer is its trackpad/mouse, so it must keep the desktop
layout. Phones (both orientations, landscape up to ~932 px) and small
tablets in portrait get the phone layout; large tablets, touch laptops and
mouse-driven desktop windows of ANY width (incl. half-screen ~945 px) keep
the desktop layout. The same condition gates the CSS and the JS behaviour
(`matchMedia`, re-evaluated on change — e.g. rotation). Today's 720 px
stacking rule stays for non-touch narrow windows (unchanged behaviour).
Known limitation, accepted: on a large tablet (desktop layout), tapping a
title still brings up the keyboard, exactly as today.

**Toolbar above the tree on a phone (D11):** the filter box stays visible
(it is how the author finds a unit). Import content, Export, Expand all,
Collapse all, the structure legend, the flag legend and the slide-break
help line move into the "Kurs" sheet, **on the phone layout only** —
desktop's toolbar and `_course_panel.html` (which builder.js restores as
`neutralPanel` after ops) are unchanged; use a phone-only wrapper/section
rather than editing the shared course panel. The info slot
(`.builder__info`) must stay visible wherever its messages are seen today
or be surfaced equivalently.

## Constraints

- Bespoke token CSS, no frameworks (`ui-foundation-bespoke-from-bonnot`);
  icons are monochrome SVG via the existing sprite, never emoji.
- Light and dark themes both; verify with screenshots of both.
- Polish UI strings via the existing i18n catalog (`makemessages`, both
  `.po` and compiled `.mo`). New strings expected: "Course"/"Kurs",
  "More actions" (⋯ aria-label), "Close", "Rename" (may already exist).
- Accessibility: ⋯ is a real button with `aria-haspopup`/`aria-expanded`;
  sheet is a dialog with focus moved in and returned to the row on close.
  The project already uses `<dialog>` elsewhere — see the library gotchas
  index (dialog theme trap) before choosing it.
- Row DOM is large on big courses (mat-pp: ~2,900 rows when fully
  expanded; see the comment at the top of `_tree_node.html`). Do not
  duplicate per-row controls into a second per-row menu DOM; one shared
  menu populated from the tapped row is preferred.
- builder.js's focus-driven panel load (`focusin` on `.tree__title`,
  `builder.js:645-667`) and its pointer/keyboard debounce must keep working
  on desktop.
- The title is an `<input>` today and therefore cannot wrap; D5 + D8 imply
  a non-input title presentation on phones.
- e2e tests must drive the real UI at a phone viewport (390×844) and a
  landscape phone viewport (~890×410), and at desktop to prove no
  regression.

## Left to the builder

- Exact sheet mechanics (CSS transform vs `<dialog>`, swipe-to-close or not,
  animation; respect `prefers-reduced-motion`).
- How Rename's editable field is presented (subject to D8 + anti-goals).
- Whether Back closes the sheet (nice to have, not required).
- One-letter mapping for container kinds (e.g. C = Część, R = Rozdział,
  S = Sekcja) — derive from the existing kind display names; keep the full
  name as `title`/accessible name.
- Exact indent value, and the menu's position (anchored to ⋯ or a small
  bottom action sheet).
- Whether the "+ Sekcja / + Lekcja / + Quiz" add affordances need any
  phone tweak (they looked acceptable in the screenshots).
- Where op errors, 409 conflicts and network notices appear on the phone
  (today `notice()` prepends them into the panel, which is usually closed
  on a phone) — they must be seen without hunting.
- Whether the sheet closes after a Move-picker submit/cancel.
- Gating the phone CSS on JS being present (`.js`) so the no-JS path keeps
  visible controls.
- e2e device emulation: phone tests use `has_touch`/`is_mobile` so
  `pointer: coarse` matches; a desktop test at ~945 px width with a mouse
  proves D10's "no phone layout for a narrow desktop window".
