# Mobile editor scroll anchor after element ops

Date: 2026-10-17 · Status: owner-approved ("yes start the scroll fix", 2026-10-17)

## Purpose

On a phone (the mobile PWA) the unit editor loses the author's place after almost
every element operation. The owner's report: add a callout at the end, move it up
to a position, then move other elements into the callout. After nearly every
move, the editor ends up showing something unrelated, and the author cannot tell
whether the changed elements are above or below. The owner saw it in the
**editor-only** view mode. Desktop has no such problem.

Measured with a read-only Playwright reproduction (390×844 against 1280×800,
editor-only mode, text-only fixture):

| Step | 390×844 (stacked) | 1280×800 (two-pane) |
|---|---|---|
| ↑ past a callout holding 8 children | row top 422 → **−730** (off-screen above); `scrollY` unchanged 1332 → 1332 | row pinned to pane top (557 → 364) |
| ↑ ×6 on a callout (rows ~86 px) | row top 517 → 277 → 191 → 105 → 19 → −67; window never moves | row stays at 364 every press |
| Select (⊹, clipboard) | rows below shift +73 px (banner); document grows 1875 → 2421 | pane absorbs it |
| Move here into callout | `scrollY` **clamped** 1229 → 1003 as document shrinks 2421 → 1847 | row pinned |

### Root cause

- `courses/static/courses/css/editor.css` (the `@media (min-width: 70rem)` block)
  makes `.editor-pane .pane-body` / `.preview-pane .pane-body` the scroll
  containers (`overflow-y: auto`) **only at ≥70rem**. Below that width the panes
  are `overflow: visible`, the layout stacks, and the **window** scrolls. That
  covers every phone in both orientations, and also any 901–1119 px window.
- `courses/static/courses/js/editor.js`:
  - `captureScroll` / `restoreScroll` save and restore only `.pane-body.scrollTop`.
    That is always 0 on the stacked layout, so they do nothing.
  - `alignTopInPane(el)` calls `body.scrollTo(...)` on the element's `.pane-body`.
    A non-scrolling box ignores it, so it silently does nothing.
  - The delegated `submit` handler for `form[data-op]` calls
    `alignTopInPane(focusRow)` after `applyFragments`. That is what keeps the row
    in place on desktop. On the stacked layout it has no effect, so the window
    keeps its exact `scrollY`. The row then drifts by the height of whatever it
    moved past, and an editor-only document that shrinks additionally clamps
    `scrollY`.

## Architecture / components

A change confined to **`courses/static/courses/js/editor.js`**, inside the
`form[data-op]` submit handler. That handler covers move ↑/↓, clipboard select and
cancel, paste "Move here" / "Move before", save (create and update), delete and
duplicate. No CSS, template, view or server change.

### Scroller detection (the gate)

Add a small helper, `paneScrolls(el)`. It returns true when `el`'s closest
`.pane-body` is a scroll container, i.e. its computed `overflow-y` is `auto`,
`scroll` or `overlay`. It returns false when there is no `.pane-body`, or when
`overflow-y` is anything else (`visible`, `clip`, `hidden`).

The gate is the **computed style of the actual scroller**, never a viewport-width
check. This tracks the CSS breakpoint automatically if it ever changes.

### Behaviour by layout

- **Pane scroller (desktop, ≥70rem): unchanged.**
  - The handler calls `alignTopInPane(focusRow)` and `scrollPreviewTo(focusId)`
    exactly as today, in the same order, with the same arguments.
  - The new code may *measure* before the POST (one `getBoundingClientRect`
    read), but it must not scroll anything on this path.
- **Window scroller (stacked, <70rem): new anchoring.**
  - **Before `post()`:** if the op has an `opRow` (the existing `keepId` logic:
    `form.closest(".el-row[data-element]")`), record `anchorId = keepId` and
    `anchorTop = opRow.getBoundingClientRect().top`.
  - **After `applyFragments`:** resolve `focusId` as today (`data-saved-element`
    wins, else `keepId`), then look up `focusRow`.
  - **Keep in place.** If `focusRow` exists, `focusId === anchorId`, and the
    recorded `anchorTop` was on-screen (`0 <= anchorTop < window.innerHeight`),
    then call `window.scrollBy(0, focusRow.getBoundingClientRect().top - anchorTop)`.
    The row returns to the screen position it had when the author tapped, so the
    ↑/↓ button stays under the thumb for repeated presses. This also cancels the
    clipboard banner shift and the editor-only `scrollY` clamp.
  - **Fallback: align near the viewport top.** If `focusRow` exists but there is
    no comparable anchor, scroll the window so the row's top lands at a small top
    margin. That covers two cases: a create, where `focusId` comes from
    `data-saved-element` and differs from `keepId`; and an op whose anchor was
    off-screen.
    - Target: `window.scrollBy(0, focusRow.getBoundingClientRect().top - margin)`.
    - Margin: the editor pane body's computed `padding-top`, mirroring
      `alignTopInPane`'s "inside the padding" alignment. Fall back to 0 when it
      can't be read.
  - **No-op cases.** If there is no `focusRow` (e.g. delete removed the row, or a
    top-level op has no element), do nothing. That matches today's desktop no-op.
  - **No sub-pixel fight.** Skip any scroll whose |delta| < 1 px, as
    `alignTopInPane` does.
  - **Preview stays put.** `scrollPreviewTo(focusId)` is still called on the
    stacked layout, but it must stay a no-op there. It routes through
    `alignTopInPane` on the preview's non-scrolling `.pane-body`, which does
    nothing. Never redirect it to the window: in stacked split mode that would
    drag the page down to the preview after every op.

### What does NOT change

- `alignTopInPane` itself is untouched. It is shared with `scrollPreviewTo`, the
  add-menu reveal, the new-row alignment after "add element", the `.el-select`
  edit-open path, and `window.libliAlignTopInPane` (used by
  `filltable_editor.js` / `switchgrid_editor.js`). Teaching it a window fallback
  would make the preview path drag the page in split mode.
- `captureScroll` / `restoreScroll` stay as they are.
- No `scrollIntoView` anywhere (guarded by
  `tests/test_editor_js_scroll_invariants.py`). `window.scrollBy` is not covered
  by that guard and is the intended primitive here. The page viewport is
  scrollable by the author on the stacked layout: the
  `body.editor-page { overflow: hidden }` lock exists only at ≥70rem.
- Scroll behaviour is instant (`scrollBy(0, dy)`, i.e. `behavior: auto`). There is
  no CSS `scroll-behavior: smooth` on the root, so this is a one-frame jump with
  no animation, matching desktop's `alignTopInPane` default.

### Out of scope (noted, not fixed here)

- `.el-select` (open an element's edit form), the post-"add element" new-row
  alignment, and the add-menu reveal call `alignTopInPane` outside the
  `form[data-op]` handler. They are no-ops on the stacked layout too, but the
  owner did not report them, so they are left for a follow-up.
- Drag-and-drop (`editor_dnd.js`) is a desktop gesture.
- The builder's mobile layout is a separate design.

## Data flow

1. Author taps an op button. The form is submitted, and the handler resolves
   `opRow` / `keepId` as today.
2. **New, stacked layout only:** measure `anchorTop` of `opRow` (if any).
3. `post()`. Then `applyFragments(res.text)` replaces both panes; the
   `restoreScroll` inside it is a no-op on the stacked layout.
4. Resolve `focusId` and `focusRow` (unchanged logic).
5. Branch on `paneScrolls(focusRow)`:
   - **true** → `alignTopInPane(focusRow)`; `scrollPreviewTo(focusId)`. This is
     today's code.
   - **false** → keep-in-place, or align near the top, via `window.scrollBy`;
     then `scrollPreviewTo(focusId)` (a no-op on this layout).

All of steps 4–5 run synchronously in the same `.then` callback as
`applyFragments`. The corrected scroll position is therefore in place before the
next frame paints, and before any test predicate can observe the new pane.

The pre-POST measurement is cheap: one layout read per op. It happens before the
network request, not in the swap path.

## Error handling

- **Status set.** The handler only acts on responses 200 / 409 / 422, as today.
  The 409 path (conflict reload) and the 422 path (validation re-render) get the
  same anchoring as 200: the author's row stays in place.
  - A 422 on a create has no `data-saved-element`. `focusId` falls back to
    `keepId`, which is the container row or null. If it is the same element as
    the anchor, it is kept in place; otherwise nothing scrolls.
- **Missing elements.** A missing `.pane-body`, `focusRow` or anchor means no
  scroll. The helper never throws. Any `getComputedStyle` read is null-guarded.
- **Network failure.** The fetch rejects, the handler's `.then` doesn't run, and
  nothing scrolls. That is unchanged.

## Testing

All e2e tests drive the real UI (button clicks), in editor-only mode, unless
stated.

1. **Regression e2e, phone 390×844, editor-only:**
   `tests/test_e2e_editor_mobile_scroll_anchor.py`, `pytest.mark.e2e`. Reuse the
   helpers in `tests/test_e2e_editor.py` (`_make_pa_user`, `_login`,
   `_seed_course_and_unit`, `_editor_url`).
   - **(a) ↑ past a tall container.**
     - Seed: 3 texts, then a callout with 8 children, then TARGET, then 3 texts.
     - Scroll TARGET's row to mid-viewport, record its top, click its ↑.
     - Assert: after the swap, TARGET's row top equals the recorded top within
       ±2 px, and the row is fully on-screen.
     - On master this goes to about −730.
   - **(b) Repeated ↑.**
     - Press ↑ on the same row 4 times.
     - Assert: the row top stays within ±2 px of its starting position after
       every press.
     - On master it drifts about one row height per press.
   - **(c) Move into callout, editor-only document shrink.**
     - Select an element with the clipboard ⊹, scroll the callout row to
       mid-viewport, then click "Move here" in the callout's paste form.
     - Assert: the callout's row (the op's anchor) stays within ±2 px of its
       pre-click top.
     - On master, `scrollY` clamps and the row jumps.
   - **Synchronisation.** Wait for the editor pane NODE to be replaced, using the
     `window.__oldPane` identity predicate. Then await a two-`requestAnimationFrame`
     promise via `page.evaluate`, which awaits Promises, unlike
     `wait_for_function`. Never use a fixed `wait_for_timeout` as the
     synchronisation.
2. **Desktop no-regression e2e, 1280×800, same file.** Scenario (a) at desktop.
   Assert the row lands at the pane-top alignment, exactly as master does today
   (row top − pane-body top − pane padding-top within ±2 px of 0). Also assert
   that `window.scrollY` is unchanged by the op. That proves the window path never
   fires when the pane scrolls.
3. **Falsification (required, recorded in the PR):**
   - Run (1) against the unmodified `editor.js`: it must go **RED**.
   - Re-apply the fix: it must go **GREEN**.
   - Mutant 1: change the gate to always pick the pane path. (1) must go red.
   - Mutant 2: force the window path on desktop. (2) must go red.
4. **Existing suites stay green:**
   - `tests/test_editor_js_scroll_invariants.py`;
   - every e2e test file whose name contains `editor` and `scroll` (e.g.
     `test_e2e_editor_scroll_containment.py`, and the preview-scroll tests);
   - `tests/test_e2e_editor.py`.
   Use an isolated test DB name
   (`TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_scrollfix`): another
   worktree may be running tests concurrently.
