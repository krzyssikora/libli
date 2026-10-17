# Mobile editor scroll anchor after element ops

Date: 2026-10-17 · Status: owner-approved ("yes start the scroll fix", 2026-10-17)

## Purpose

On a phone (the mobile PWA), the unit editor loses the author's place after
almost every element operation. The owner's report: add a callout at the end,
move it up to a position, then move other elements into the callout. After
nearly every move the editor ends up somewhere that doesn't show the changed
elements, and the author can't tell whether they are above or below. The owner
saw this in the **editor-only** view mode. Desktop has no such problem.

The owner approved the approach: keep the author's place on screen across the
op ("the row keeps its screen position"), and fall back to bringing the
affected row near the top when that isn't possible.

The problem was measured with a read-only Playwright reproduction (390×844
against 1280×800, editor-only mode, text-only fixture):

| Step | 390×844 (stacked) | 1280×800 (two-pane) |
|---|---|---|
| ↑ past a callout holding 8 children | row top 422 → **−730** (off-screen above); `scrollY` stays at 1332 | row pinned to the pane top (557 → 364) |
| ↑ ×6 on a callout (rows ~86 px) | row top 517 → 277 → 191 → 105 → 19 → −67; the window never moves | row stays at 364 after every press |
| Select (⊹, clipboard) | rows below shift +73 px (banner); document grows 1875 → 2421 | the pane absorbs it |
| Move here into callout | `scrollY` **clamped** 1229 → 1003 as the document shrinks 2421 → 1847 | row pinned |

### Root cause

- **CSS:** `courses/static/courses/css/editor.css` (the `@media (min-width: 70rem)`
  block) makes `.editor-pane .pane-body` and `.preview-pane .pane-body` the
  scroll containers (`overflow-y: auto`) **only at ≥70rem**. Below that the panes
  are `overflow: visible`, the layout stacks, and the **window** scrolls. That
  covers every phone in both orientations, and any 901–1119 px window.
- **JS:** `courses/static/courses/js/editor.js` only ever scrolls the panes:
  - `captureScroll` / `restoreScroll` save and restore only `.pane-body.scrollTop`.
    That is always 0 on the stacked layout, so they do nothing.
  - `alignTopInPane(el)` calls `body.scrollTo(...)` on the element's `.pane-body`.
    A non-scrolling box ignores the call, so it silently does nothing.
  - The delegated `submit` handler for `form[data-op]` calls
    `alignTopInPane(focusRow)` after `applyFragments`. That keeps the row in
    place on desktop. On the stacked layout the window keeps its exact `scrollY`,
    so the row drifts by the height of whatever it moved past. In editor-only
    mode a document that shrinks also clamps `scrollY`.

## Architecture / components

The change is confined to **`courses/static/courses/js/editor.js`**, inside the
`form[data-op]` submit handler and a few small helpers next to it. No CSS,
template, view or server change.

The handler covers these ops:
- move ↑/↓ (`data-op="element-move"`, `name="direction"` buttons in
  `_element_row_controls.html`);
- clipboard select ⊹ (`element-clip`, in the row controls);
- clipboard cancel ✕ (`element-clip`, in `#clip-banner`);
- "Move here" / "Copy here" (`element-paste`, rendered at the bottom of every
  container slot and once at top level, `_editor_scope.html`);
- "Move/Copy before this element" (`element-paste-before`, in the row controls);
- save (create and update, `element-save`);
- delete;
- duplicate.

### Helpers

- `paneScrolls()` returns true when the **editor pane's** body
  (`[data-scope="editor"] .pane-body`) is a scroll container, i.e. its computed
  `overflow-y` is `auto`, `scroll` or `overlay`. It returns false when there is
  no such element or `overflow-y` is anything else (`visible`, `clip`,
  `hidden`).
  - The gate is the **computed style of the actual scroller**, never a
    viewport-width check, so it follows the CSS breakpoint automatically.
  - It is evaluated **after** the swap. If the layout flipped while the request
    was in flight (e.g. a tablet rotating across 70rem), a recorded anchor is
    simply ignored on the pane path.
- `viewportH()` returns `(window.visualViewport && visualViewport.height) ||
  window.innerHeight`. With the soft keyboard open (e.g. Save from an edit form),
  this is the visible area, so a row hidden behind the keyboard does not count
  as on-screen.
- `onScreen(top)` is `0 <= top && top < viewportH()`. A panned visual viewport
  (`visualViewport.offsetTop > 0`, e.g. iOS with the keyboard open) is **accepted
  as best effort and untested**: the band is not shifted by `offsetTop`.
- `rendered(el)` is `el.isConnected && el.getClientRects().length > 0 &&
  el.getBoundingClientRect().height > 0`. Tabs and columns slots are `<details>`
  elements (`SLOT_DETAILS` in editor.js); callout, spoiler and before/after slots
  are always-open divs. `applyStoredSlots` re-applies the author's collapse
  state after every swap, but these slots are force-opened (`data-force-open`)
  while a clip is active, so the case cannot arise during a paste op. A row
  inside a closed `<details>` (or any `display:none` subtree) has an
  all-zero rect, which would otherwise pass `onScreen(0)` and read as "entirely
  off-screen" at the same time. **Every anchor candidate and the safety net
  require `rendered(row)`.** An unrendered row is never an anchor, and the safety
  net never acts on it.

### Anchor selection (measured just before the swap)

The anchor is measured **inside the `.then`, immediately before
`applyFragments(res.text)`**, not before `post()`. If the author scrolls while
the request is in flight, the position used is the one they ended on, not the
one at tap time. The old DOM is still intact at that point. Every node is
checked with `isConnected` before measuring.

The measurement runs whenever the response status is 200, 409 or 422. It is
cheap: a handful of `getBoundingClientRect` reads, and it never scrolls.

The result is an **ordered list of candidates**, each a pair `{id, top}`: `id` is
a `data-element` value to look up after the swap, and `top` is the screen
position to restore it to. Every applicable candidate below is recorded, in
this order. After the swap, the **first candidate whose row still exists and is
`rendered`** wins. That ordering is what handles ops that remove or relocate
rows (delete, paste-move): their own rows simply don't resolve, and resolution
moves on to the next candidate.

1. **Paste-move (primary).** The op is `element-paste` or
   `element-paste-before` and the mode is `move`.
   - For `element-paste`, the mode comes from the same submitter `post()`
     received (`e.submitter`, the `name="mode"` buttons). A null submitter means
     "not move": this candidate is skipped.
   - For `element-paste-before`, the mode comes from the hidden `mode` input.
   - `id` = the clip pk, `form.elements.element.value`.
   - `top` = the **form's** own `getBoundingClientRect().top`, i.e. where the
     author's finger was.
   - After the move, the moved element sits where that control was (end of the
     slot, or just before the target row). Restoring it to `top` keeps "the thing
     I just moved" under the thumb. This handles a callout that keeps growing,
     where the container's own top is far above the viewport.
   - `_move_into` (`courses/builder.py`) re-saves the same join row, so the
     moved element keeps its pk and this candidate normally resolves. If it ever
     doesn't, the next candidates take over.
2. **The op's own row.** The form has an `opRow`
   (`form.closest(".el-row[data-element]")`, the existing `keepId` logic) that
   is `rendered`, with `onScreen(opRow top)` → `id = keepId`, `top` = that row's
   top.
   - Covers move ↑/↓, select, update-save, duplicate and paste-before-copy whose
     row is visible.
   - For delete, this candidate is recorded too, but its row is gone after the
     swap, so it never resolves.
3. **Visible rows (catch-all).** Record up to **5** `.el-row[data-element]` inside
   `[data-scope="editor"]`, in document order, each `rendered` and with
   `onScreen(top)`.
   - Nested rows count. For a paste-move, rows inside the clip row's own subtree
     (the clip row included) are **excluded**: they relocate with the move, so
     holding one would track the moved block rather than the page.
   - For `element-delete`, `opRow` and its descendants are **excluded** too, the
     same way. Otherwise a deleted container with 5 or more visible children
     would use up the cap on rows that cannot resolve, leaving no surviving row
     to anchor.
   - Covers:
     - ops with no `opRow`: clipboard cancel, and top-level paste-**copy** (a
       top-level paste-move uses candidate 1);
     - ops whose `opRow` top is off-screen (a create or 422 inside a tall
       container; an update of a long row with the author at its Save button);
     - delete, including a delete of a tall container whose visible children
       vanish with it.

If no candidate resolves (no rendered rows on screen at all, or all of them
removed), there is no anchor.

### Resolution after the swap

All of this runs synchronously in the same `.then`, right after
`applyFragments`. The corrected position is therefore in place before the next
paint, and before any test predicate can see the new pane.

- **Pane scroller (`paneScrolls()` true; desktop ≥70rem): unchanged.**
  - The existing code runs exactly as today, in the same order, with the same
    arguments: `focusId` resolution, `alignTopInPane(focusRow)`,
    `scrollPreviewTo(focusId)`.
  - The recorded anchors are ignored, and nothing calls `window.scrollBy` or
    `window.scrollTo`.
- **Window scroller (`paneScrolls()` false; stacked <70rem): new.**
  0. The existing `flash()` call for a 409 stays where it is today: right after
     `applyFragments`, **before** keep-in-place. The measurement after the swap
     therefore already includes the bar, and the bar's insertion is compensated.
  1. **Keep in place.** Walk the candidate list in order and take the first
     whose row exists after the swap and is `rendered`. Let
     `dy = newRow.getBoundingClientRect().top - anchor.top`. If `|dy| >= 1`,
     call `window.scrollBy(0, dy)`.
     - The browser clamps this to the document's scroll range. When the
       document shrank below the anchor and the exact position is
       unreachable, the clamp is accepted as best effort. Step 2 below still
       guarantees the focus row isn't lost.
  2. **Focus visibility safety net.** **Skipped entirely when candidate 1
     (paste-move) resolved in step 1.** The moved element is then already where
     the author's finger was. Otherwise, for a paste-before move of a tall
     element, the target row T could land entirely below the viewport and the
     net would drag S up off-screen. Otherwise, resolve `focusId` exactly as
     today (`data-saved-element` wins, else `keepId`) and look up `focusRow`.
     - Only `element_save` sets `data-saved-element`
       (`views_manage.py`, `saved_element=join.pk`). For paste ops, `focusId` is
       therefore the container row ("Move here" in a slot), the target row
       (paste-before), or null (top-level paste), never the moved element.
       Bringing a moved element back on screen relies on candidate 1 plus the
       clamp alone.
     - If `focusRow` exists, is `rendered`, and is **entirely** off-screen
       (`bottom <= 0 || top >= viewportH()`), scroll so its top lands at the
       margin: `window.scrollBy(0, focusRow.getBoundingClientRect().top - margin)`,
       skipped when |delta| < 1.
     - `margin` is the editor pane body's computed `padding-top` (the same
       "inside the padding" alignment `alignTopInPane` uses), or 0 if it can't be
       read.
     - This is the "fall back to aligning near the viewport top" case. It covers a
       create whose new row was pushed out of view, an op with no anchor at all,
       and a focus row the clamp in step 1 could not bring back.
     - A **partially** visible focus row is left alone. For example, after a 422
       the author stays at the error form they were looking at, even if the row's
       top is above the viewport.
  3. `scrollPreviewTo(focusId)` is still called when `focusId` is set. On this
     layout it routes through `alignTopInPane` on the preview's non-scrolling
     `.pane-body`, so it **must stay a no-op**. Never redirect it to the window:
     in stacked split mode the preview renders below the editor, and the page
     would be dragged down to it after every op.

### What does NOT change

- **`alignTopInPane` is untouched.** It is shared with `scrollPreviewTo`, the
  add-menu reveal, the new-row alignment after "add element", the `.el-select`
  edit-open path, and `window.libliAlignTopInPane` (used by
  `filltable_editor.js` and `switchgrid_editor.js`). Teaching it a window
  fallback would make the preview path drag the page in split mode.
- **`captureScroll` / `restoreScroll`** stay as they are.
- **No `scrollIntoView`** anywhere (guarded by
  `tests/test_editor_js_scroll_invariants.py`).
  - `window.scrollBy` is not covered by that guard, and it is the intended
    primitive here.
  - On the stacked layout the author can scroll the page viewport normally,
    because the `body.editor-page { overflow: hidden }` lock exists only at
    ≥70rem.
- **Scrolling is instant** (`scrollBy(0, dy)`, `behavior: auto`). There is no
  root `scroll-behavior: smooth`, so this is a one-frame correction, matching
  desktop's `alignTopInPane` default.

### Out of scope (noted, not fixed here)

- **Other `alignTopInPane` callers.** `.el-select` (opening an element's edit
  form), the new-row alignment after "add element", and the add-menu reveal call
  `alignTopInPane` outside the `form[data-op]` handler. They are no-ops on the
  stacked layout too, but the owner didn't report them; left for a follow-up.
- **409 flash bar.** On a 409, `flash()` prepends an in-flow `.op-error` bar and
  removes it 6 s later. On the stacked layout the anchored rows shift by the
  bar's height at that moment. The position is restored right after the swap,
  not kept across the later bar removal. This is accepted.
- **Late layout shifts.** Content whose height changes after the synchronous
  correction is not re-corrected. Examples: images in a re-rendered edit form,
  web fonts. Whatever the browser's native scroll anchoring (`overflow-anchor`)
  does there is untested. This is accepted: add **no** rAF or timeout
  re-corrections.
- **Drag-and-drop** (`editor_dnd.js`) is a desktop gesture.
- **The builder's mobile layout** is a separate design.

## Data flow

1. The author taps an op button. The handler resolves `opRow` / `keepId` as
   today and calls `post()`. Nothing is measured yet.
2. The response arrives with status 200, 409 or 422. Before `applyFragments`,
   record the ordered candidate list:
   1. the paste-move candidate (paste-move ops only);
   2. the op's own row, if it is rendered and on-screen;
   3. up to 5 rendered, on-screen rows (minus the clip subtree on a paste-move, and minus the deleted subtree on a
      delete).
3. `applyFragments(res.text)` replaces both panes. The `restoreScroll` inside it
   is a no-op on the stacked layout.
4. If `paneScrolls()` is true, run today's code unchanged
   (`alignTopInPane(focusRow)`, `scrollPreviewTo(focusId)`).
5. If `paneScrolls()` is false:
   1. keep in place (first candidate that resolves);
   2. apply the focus-visibility safety net;
   3. call `scrollPreviewTo(focusId)`, which is a no-op on this layout.

## Error handling

- **Status gating.** Only 200, 409 and 422 responses reach this code, as today.
  - **409 (conflict reload) and 422 (validation re-render)** get the same
    anchoring as 200.
  - **422 on a create.** The response has no `data-saved-element`, so `focusId`
    falls back to `keepId` (the container row, or null). Keep-in-place holds the
    first visible row, which is usually inside the error form's surroundings.
    The safety net only acts if the focus row is entirely off-screen. One rule,
    no special case.
- **Missing pieces.** A missing `.pane-body`, an anchor row that's gone after
  the swap, or a missing `focusRow` → that step is skipped. The code never
  throws: every `getComputedStyle` / `visualViewport` read is null-guarded, and
  every measured node is checked with `isConnected`.
- **Network failure.** The fetch rejects, the handler's `.then` never runs, and
  nothing scrolls. Unchanged.

## Testing

All new e2e tests live in **`tests/test_e2e_editor_mobile_scroll_anchor.py`**
(`pytestmark = pytest.mark.e2e`) and drive the real UI with button clicks.

### Scaffolding

- **Helpers.** Reuse `_make_pa_user`, `_login`, `_seed_course_and_unit` and
  `_editor_url` from `tests/test_e2e_editor.py`. Also add the session-scoped
  autouse `DJANGO_ALLOW_ASYNC_UNSAFE` fixture that file uses.
- **Seeding.** Seed top-level elements with `tests.factories.add_element(unit,
  TextElement.objects.create(...))` and `add_element(unit,
  CalloutElement.objects.create(kind="note", heading=...))`. Seed container
  children with `Element.objects.create(unit=unit, content_object=...,
  parent=<callout join>, tab_id=SINGLE_SLOT_ID)` (`SINGLE_SLOT_ID` from
  `courses.models`).
  - Every seed is built so the asserted positions are **reachable by
    construction**: neither end-of-document clamp may interfere. Each test's
    docstring says so.
    - **Trailing:** at least ~1.5 viewports of text rows below the rows under
      test (except (e), which pins its own layout).
    - **Leading:** enough rows above that, after the op, the row under test's
      document top is at least its recorded screen top + 100 px, so the
      required `scrollY` is never below 0.
    - Each test asserts its starting `scrollY` before the click: large enough
      to absorb any upward correction, and small enough that the bottom clamp
      cannot bite.
- **View mode.** Enter editor-only mode by clicking the real view toggle,
  `[data-view="editor"]`, after load.
- **Scrolling to a start position.** Scroll the window (the stacked layout's
  scroller) with `page.evaluate("window.scrollTo(...)")`, so that the button
  about to be clicked is already on-screen. Record its row top only *after*
  confirming it is visible, so Playwright's own scroll-into-view on `click()`
  never moves the page.
  - Each test asserts, right before clicking, that the target button's rect is
    within the viewport.
- **Swap synchronisation (defined here; no existing helper).**
  - Before each click, run
    `page.evaluate("() => { window.__oldPane = document.querySelector('[data-scope=\"editor\"]'); }")`.
  - Then `page.wait_for_function("() => { const p = document.querySelector('[data-scope=\"editor\"]'); return p && p !== window.__oldPane; }")`.
  - Then await two animation frames:
    `page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")`.
    `page.evaluate` awaits Promises; `wait_for_function` does not.
  - Re-arm `__oldPane` before **every** click (including each of (b)'s presses).
  - Never use a fixed `wait_for_timeout` as the synchronisation.

### Phone cases (390×844, editor-only)

Tolerance is ±2 px throughout.

- **(a) ↑ past a tall container.**
  - Seed:
    - ~10 leading texts;
    - then a callout with 8 children;
    - then TARGET;
    - then trailing texts.
  - Put TARGET's row at mid-viewport, record its top, click its ↑.
  - Assert: TARGET's row top equals the recorded top.
  - On master it lands around −730.
- **(b) Repeated ↑.**
  - Press ↑ on the same row 4 times, each time past a plain text row.
  - Assert: the row top stays at its starting position after every press.
  - On master it drifts about one row height per press.
- **(c) Move here into a callout whose top is OFF-screen.**
  - Seed:
    - leading texts;
    - a **tall** selected text S (several paragraphs, rendered row height ≥ 200 px,
      i.e. much taller than the paste form);
    - a callout with ~10 children, the **last of them tall** (taller than half
      the viewport);
    - then trailing texts.
  - Select S with ⊹ (re-synchronise).
  - Scroll so that, at once:
    - the callout's "Move here" button is at mid-viewport;
    - the callout's own row top is above the viewport;
    - **no child row's top is on-screen**: the tall last child starts above the
      viewport.

    Assert all three. Record the paste form's top.
  - **Why the seed is shaped this way.** It makes the test discriminate the
    primary candidate from the catch-all. Without candidate 1, the catch-all
    would hold the first trailing row below the form. S would then land at
    `formTop + formH − S.height`, far above the asserted `formTop` because
    S.height ≫ formH. The falsification record shows that both numbers differ by
    more than 50 px.
  - Click "Move here".
  - Assert: S's row (same `data-element`) top equals the recorded form top, and
    S's row is on-screen.
  - On master the window is clamped or the row is off-screen.
- **(d) Clipboard cancel keeps the visible rows still.**
  - `#clip-banner` sits at the top of the editor pane and is not sticky, so ✕ is
    only reachable near the top of the page.
  - Seed a short unit head (page header + ~2 texts), so ✕ is visible while
    `scrollY` is still ≥ 150 px. That is enough to absorb the banner (~73 px)
    plus the paste-before buttons above R.
  - Select an element. Scroll to a pinned `scrollY` where ✕ is on-screen, and
    assert both conditions. Take R = **the first rendered
    `.el-row[data-element]` whose top is on-screen**, i.e. exactly the row the
    catch-all records first. Record its top.
  - Click the banner's cancel ✕.
  - Assert: R's top is unchanged. On master, the banner and every paste button
    disappearing shifts R.
- **(e) Create inside a container lands at the top (safety net), with no anchor.**
  - Seed: a callout with 2 children, followed by trailing texts amounting to
    **at least the edit form's height plus one viewport**. Saving collapses the
    tall form, so the document shrinks by roughly that much; without this the
    bottom clamp could leave the new row partly visible on a correct build.
  - Open the callout's nested "Add element" → a text type. Fill the body with
    enough lines that the edit form is taller than the viewport.
  - Scroll so the form's Save button is on-screen and **no**
    `.el-row[data-element]` top is on-screen (assert this). Then no candidate
    exists.
  - Before Save, also assert:
    `documentElement.scrollHeight − (scrollY + viewportH) ≥ formHeight + 100`.
  - Save. The collapsed new row lands where the form's top was, i.e. entirely
    above the viewport, unless the safety net acts.
  - Assert: the new row (`data-saved-element`) top equals the editor pane body's
    computed `padding-top`, within ±2 px.
- **(h) "Move before this element" (paste-before move).**
  - Seed: leading texts, a selected text S, ≥ 3 texts, a target text T, then
    trailing texts.
  - Select S. Scroll so T's row (and its paste-before button) is at
    mid-viewport, and record the paste-before form's top.
  - Click T's "Move before this element".
  - Assert: S's row top equals the recorded paste-before form top.
  - This guards the hidden-input mode read. The paste-before submit button has
    no `name`/`value`, so reading the mode from the submitter would skip
    candidate 1.
- **(h2) "Move before" a tall element: the safety net must not fire.**
  - Same as (h), but S is taller than `viewportH − formTop` (many paragraphs),
    so T lands entirely below the viewport after the move.
  - Assert: S's top still equals the recorded form top.
- **(i) Delete of a tall container.**
  - Seed: leading texts; a callout with ≥ 7 short children; trailing texts.
  - Scroll so the callout's own row top is above the viewport, ≥ 5 of its
    children are on-screen, and at least one trailing row is on-screen. Assert
    all three.
  - Pick D = the first trailing row on-screen, and record its top.
  - Delete the callout (accept the real `confirm` dialog via a
    `page.on("dialog")` handler, if the delete asks for one).
  - Assert: D's top is unchanged.

### Desktop no-regression (1280×800, editor-only)

- **(f)** Scenario (a) at desktop. Set the start position by setting
  `[data-scope="editor"] .pane-body`'s `scrollTop` (the page itself is locked),
  **before** installing (g)'s spies. Assert that the row lands at the pane-top
  alignment exactly as today: `row.top − paneBody.top − paneBody.paddingTop`
  within ±2 px of 0.
- **(g) Window path never runs on desktop.** Run this inside (f), on the same
  ↑ past the tall container (a large, known shift). Before the click, wrap
  `window.scrollBy` and `window.scrollTo` with counting spies via
  `page.evaluate`, then assert zero calls after the op.
  - The falsification record must show:
    - the **baseline**: zero calls on unmodified master for the same op, which
      proves nothing else on the page calls these;
    - a **non-zero** count under mutant 5.
  - `window.scrollY` is NOT a usable signal: the ≥70rem page is locked to the
    viewport and cannot scroll.

### Falsification (required; output recorded in the PR)

- Run (a)–(e), (h), (h2) and (i) against the unmodified `editor.js`: all must go
  **RED**.
  Re-apply the fix: all **GREEN**.
- Mutants, each chosen from a likely implementation mistake. Each must turn the
  named test red:
  1. **Candidate 1 deleted from the list** (resolution falls through to
     candidates 2 and 3, unchanged) → (c).
  2. **First-visible-row catch-all removed** → (d).
  3. **Safety net removed** → (e).
  4. **Anchor measured after `applyFragments`** instead of before → (a).
  5. **Gate forced to the window path on desktop** → (g).
  6. **Paste-before mode read from the submitter** instead of the hidden
     input → (h).
  7. **Safety net left active after candidate 1 resolves** → (h2).
  8. **Deleted-subtree exclusion removed from the catch-all** → (i).
- **Admitted gap: 409/422 anchoring.** Every test uses a 200 response. Gating on
  `status === 200` would stay green. The implementation shares one code path
  for 200/409/422 (no status branch inside the anchoring), and the code comment
  says so. No dedicated test is claimed.
- **Admitted gap: `rendered()`.** It is defence-in-depth with no independently
  observable effect in these tests. Two things make it unobservable here:
  - resolution re-checks `rendered` after the swap, and `applyStoredSlots` keeps
    collapsed slots collapsed, so a recorded zero-rect row is skipped anyway;
  - no deterministic seed makes the safety net meet an unrendered focus row.

  No mutant is claimed for it, and the code comment beside the check says so,
  per the "admit in a comment" rule.

### Existing suites that must stay green

- `tests/test_editor_js_scroll_invariants.py`
- `tests/test_e2e_editor_scroll_containment.py`
- `tests/test_e2e_editor_preview_state_regression.py`
- `tests/test_e2e_preview_nested_locate.py`
- `tests/test_e2e_editor.py`

Run them against an isolated test DB, because another worktree may be running
tests concurrently:
`TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_scrollfix`.
