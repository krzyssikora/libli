# Mobile Editor Scroll Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the stacked (<70rem) unit editor, keep the author's place on screen across every `form[data-op]` op, so moved/edited rows no longer drift off-screen on phones.

**Architecture:** All production code lives in `courses/static/courses/js/editor.js`. It adds a few helpers plus two new steps in the existing `form[data-op]` submit handler:
- just before `applyFragments`, record an ordered list of anchor candidates;
- after the swap, if the editor pane is not a scroll container, resolve the first candidate that still exists and `window.scrollBy` it back to its old screen position, then apply a focus-row safety net.

The desktop pane path is byte-for-byte unchanged.

**Tech Stack:** Vanilla ES5-style JS (IIFE, `var`, no build step), Django templates, pytest + pytest-playwright e2e (sync API).

**Spec:** `docs/superpowers/specs/2026-10-17-mobile-editor-scroll-anchor-design.md`. Read it; this plan argues from it, and the spec's section names are cited below.

## Global Constraints

- Only `courses/static/courses/js/editor.js` changes in production. No CSS, template, view or server change.
- Never call `scrollIntoView` (guarded by `tests/test_editor_js_scroll_invariants.py`). The window primitive is `window.scrollBy(0, dy)`, instant (no `behavior: "smooth"`).
- `alignTopInPane` itself is not edited. `captureScroll`/`restoreScroll` are not edited.
- The gate is the computed `overflow-y` of `[data-scope="editor"] .pane-body` (`auto|scroll|overlay` ⇒ pane path). Never use a viewport-width check.
- The pane path (`paneScrolls()` true) runs today's code exactly: `alignTopInPane(focusRow)` then `scrollPreviewTo(focusId)`, inside `if (focusId)`. It never calls `window.scrollBy`/`window.scrollTo`.
- No rAF / `setTimeout` re-corrections. Everything runs synchronously in the handler's `.then`.
- Candidate cap = **5** catch-all rows. Tolerance in tests = **±2 px**. Sub-pixel skip = `|dy| < 1`.
- Tests run with `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_scrollfix`; another worktree uses `/libli_buildermobile`. Start the container first: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`.
- Never pass `-q` to pytest (addopts has it). Always pass `-m e2e` for e2e files. Grep the summary line; don't trust the exit code.
- **Scratchpad (literal path, no shell variables — every Bash call is a fresh shell):** `C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/83592fd0-f524-4a85-a21b-2c06f2fd95f9/scratchpad`. All backups and evidence files go there by this absolute path.
- Every new code comment for an untested path says so: the `rendered()` check, candidate 4, the 409/422 sharing of candidates 2–3, duplicate/update-save.

## Review Focus

Spec-implied conditions with no dedicated test, most likely to bite first. Each is pinned in the task that owns it.
1. **A 422 on update-save of a long row while the author is at Save.** Expect no jump; the error form stays where it was. Pinned: a code comment in Task 1 plus the shared path. Owner-accepted gap (spec "Admitted gap: 409/422").
2. **Cancel while looking at a twocolumn/tabs child** (its slot re-collapses). Expect the ancestor container row to hold. Candidate 4; admitted gap, with a code comment in Task 2.
3. **Repeated ↑ with fractional row heights.** Expect no cumulative drift. Pinned by test (b), which compares each press with its own pre-press top (Task 1).
4. **Desktop ops after this change.** Expect zero window-scroll calls and the same pane alignment. Pinned by (f)+(g) in Task 1, and by the existing suites in Task 3.
5. **Split mode on a phone (the default view).** Expect the preview timers not to drag the page. Pinned by (k) in Task 1.

---

## File Structure

- Modify `courses/static/courses/js/editor.js`:
  - helpers next to `alignTopInPane` (~line 229);
  - the submit handler (~lines 494–521).
- Create `tests/test_e2e_editor_mobile_scroll_anchor.py`: every new e2e case, plus local helpers (`_seed_texts`, `_seed_callout`, `_arm_swap`, `_wait_swap`, `_row_top`, `_first_visible_row_id`, `_scroll_window_to_row`).

---

### Task 1: Core window-path anchoring (candidates 2 + 3, safety net, gate)

**Files:**
- Modify: `courses/static/courses/js/editor.js` (helpers after `alignTopInPane`, ~229–246; submit handler ~494–521)
- Test: `tests/test_e2e_editor_mobile_scroll_anchor.py` (create)

**Interfaces:**
- Produces, inside the editor.js IIFE (not exported):
  - `paneScrolls() -> boolean`
  - `viewportH() -> number`
  - `onScreen(top: number) -> boolean`
  - `rendered(el: Element|null) -> boolean`
  - `editorRow(id: string) -> Element|null` (`root.querySelector('[data-scope="editor"] .el-row[data-element="' + id + '"]')`)
  - `recordAnchors(form: HTMLFormElement, submitter: Element|null, status: number, opRow: Element|null) -> Array<{id: string, top: number, primary: boolean}>`
  - `keepInPlace(anchors) -> boolean` (true iff the resolved anchor had `primary: true`)
  - `revealFocusRow(row: Element|null) -> void`
- Test helpers produced (module-level in the test file):
  - `_seed_texts(unit, n, prefix) -> list[Element]`
  - `_seed_callout(unit, children: int, parent=None) -> (Element, list[Element])`: a callout (top-level, or nested under `parent`) with `children` short text children.
  - `_arm_swap(page)`, `_wait_swap(page)`
  - `_row_top(page, eid) -> float`
  - `_first_visible_row_id(page) -> str`
  - `_scroll_window_to_row(page, eid, y_in_viewport)`
  - `_row_control(page, eid, selector) -> Locator`, scoped to `[data-scope="editor"] .el-row[data-element="<eid>"] > .el-row__head` before `selector`. A container's `<li>` also holds its children's controls, so an unscoped locator trips strict mode. Use it for **every** op click (↑, ⊹, delete, paste-before).
  - `_assert_unclamped(page, max_up, max_down)` asserts `scrollY >= max_up + 100` and `scrollHeight - innerHeight - scrollY >= max_down + 100`.

- [ ] **Step 1: Write the test module and the failing phone/desktop tests**

  Header: `pytestmark = pytest.mark.e2e`; the session-scoped autouse `DJANGO_ALLOW_ASYNC_UNSAFE` fixture (copy from `tests/test_e2e_editor.py:20-23`). Import `_make_pa_user`, `_login`, `_seed_course_and_unit`, `_editor_url` from `tests.test_e2e_editor`.

  **Helpers:**
  - **Seeding.**
    - Top-level text: `tests.factories.add_element(unit, TextElement.objects.create(body=...))`.
    - Callout: `add_element(unit, CalloutElement.objects.create(kind="note", heading="Box"))`.
    - Container children: `Element.objects.create(unit=unit, content_object=..., parent=<callout join>, tab_id=SINGLE_SLOT_ID)`. `SINGLE_SLOT_ID` comes from `courses.models`; `Element.order` is an `OrderField(for_fields=["unit"])`, so it is assigned automatically.
  - **Tall rows.** A TextElement editor row is a **one-line label** (`body_excerpt`, `.el-row__label { white-space: nowrap }`), so extra paragraphs never make it taller. A tall row = **a callout with N short children**; its height grows with N. Callouts are nestable (`NESTABLE_TYPE_KEYS`, `MAX_NEST_DEPTH = 4`). Each test that needs a tall row asserts its measured height before relying on it.
  - **Swap sync.** `_arm_swap` / `_wait_swap` use exactly the JS strings in spec §Testing → "Swap synchronisation", including the two-rAF `page.evaluate` Promise.
  - **`_first_visible_row_id`** returns the id of the first `[data-scope="editor"] .el-row[data-element]` in document order where `checkVisibility()` is true, height > 0, and `0 <= top < (visualViewport.height || innerHeight)`.
  - **Page setup.** Every test: `page.set_viewport_size(...)`, `goto`, `wait_for_selector('[data-scope="editor"]')`, then click `[data-view="editor"]` (or `split` for (k)).
  - **Pre-click guards.** Before each click, assert that the target button's rect lies inside `[0, innerHeight)`. Call `_assert_unclamped(page, max_up, max_down)` with the test's expected correction magnitude:
    - (a)/(b2)/(k): `max_up` ≈ the 8-child callout's height;
    - (b): one row height;
    - (c): S-callout's height;
    - (h)/(h2): S-callout's height;
    - (i): the deleted callout's height (`max_down`);
    - (l)/(d): 150;
    - (j): 0.

    (e) has its own guards.
  - **Every click** (including the preliminary ⊹ select in (c), (d), (h), (h2), (j) and (l)) is wrapped `_arm_swap(page)` → click → `_wait_swap(page)`.

  **Tests (390×844 unless noted):**

  ```python
  def test_phone_up_past_tall_container_keeps_row(page, live_server):  # (a)
      # seed: 10 texts, callout(8 children), TARGET, 1.5 viewports of trailing texts
      # TARGET at mid-viewport; t0=_row_top; click TARGET ↑ (button[name=direction][value=up])
      assert abs(_row_top(page, target) - t0) <= 2

  def test_phone_up_with_row_top_just_above_viewport(page, live_server):  # (b2)
      # as (a) but scroll so TARGET top ≈ -5 and its ↑ is on-screen (assert both)
      assert abs(_row_top(page, target) - t0) <= 2

  def test_phone_repeated_up_keeps_row(page, live_server):  # (b)
      # seed: 10 leading texts, the moving row M, 1.5 viewports trailing; M starts mid-viewport.
      # 4 presses, each past a plain text row; before each: ↑ on-screen check + _assert_unclamped;
      # per press: t=_row_top; click; then
      assert abs(_row_top(page, eid) - t) <= 2   # vs the top just before THAT press

  def test_phone_select_keeps_tapped_row(page, live_server):  # (l)
      # seed: texts, callout(2), P, trailing; first visible row is the callout or a
      # child of it, P is mid-viewport and is NOT the first visible row (assert all)
      # click P's ⊹ (button[aria-label="Select"])
      assert abs(_row_top(page, p) - t0) <= 2

  def test_phone_cancel_keeps_first_visible_row(page, live_server):  # (d)
      # seed: 4 short texts (select #1), 1.5 viewports trailing; scrollY >= 150 with ✕
      # on-screen (assert both); R=_first_visible_row_id; click #clip-banner ✕
      assert abs(_row_top(page, r) - t0) <= 2

  def test_phone_delete_tall_container_keeps_trailing_row(page, live_server):  # (i)
      # seed: texts, callout(>=7 short children), trailing; callout top above viewport,
      # >=5 children on-screen, >=1 trailing row on-screen (assert); D=first trailing
      # on-screen row; click the callout's own delete (form[data-op=element-delete])
      assert abs(_row_top(page, d) - t0) <= 2

  def test_phone_nested_create_lands_at_pane_top(page, live_server):  # (e)
      # seed: callout(2), trailing >= form height + 1 viewport; open the callout's nested
      # add menu: callout_row.locator("[data-add-menu].addwrap--nested [data-add-toggle]").click(),
      # then "[data-add-type='text']"; wait for "[data-edit-slot] form[data-op='element-save']".
      # Grow the form via the RTE surface (.rte-surface, contenteditable): click it, then
      # page.keyboard.type(<40 words>) + page.keyboard.press("Enter") per paragraph, looping
      # until form height >= 2*innerHeight (keyboard input fires the input event that syncs
      # [data-rte-source]; see test_e2e_editor.py::test_add_text_element). Scroll so Save is within
      # ~60px of the viewport bottom; assert form top <= -innerHeight, no row top on-screen,
      # scrollHeight - (scrollY+innerHeight) >= formHeight + 100; click Save =
      # callout_row.locator("[data-edit-slot] form[data-op='element-save'] button[type=submit]").first
      # (the pending create row has no data-element, so not _row_control), wrapped in swap sync
      new = page.evaluate("document.querySelector('[data-scope=\"editor\"]').getAttribute('data-saved-element')")
      pad = page.evaluate("parseFloat(getComputedStyle(document.querySelector('[data-scope=\"editor\"] .pane-body')).paddingTop)")
      assert abs(_row_top(page, new) - pad) <= 2

  def test_phone_split_mode_keeps_row_after_preview_timers(page, live_server):  # (k)
      # (a) after clicking [data-view="split"]
      assert abs(_row_top(page, target) - t0) <= 2
      page.evaluate("() => new Promise(r => setTimeout(r, 700))")  # after the 500 ms timer
      assert abs(_row_top(page, target) - t0) <= 2

  def test_desktop_up_aligns_to_pane_top_without_window_scroll(page, live_server):  # (f)+(g)
      # 1280x800, seed as (a); start via the pane's scrollTop (TARGET mid-pane), THEN install
      # spies: window.__ws=0; wrap window.scrollBy/scrollTo to increment; click ↑
      off = page.evaluate("""(id) => { const r=document.querySelector('[data-scope="editor"] .el-row[data-element="'+id+'"]').getBoundingClientRect();
        const b=document.querySelector('[data-scope="editor"] .pane-body'); return r.top-b.getBoundingClientRect().top-parseFloat(getComputedStyle(b).paddingTop); }""", target)
      assert abs(off) <= 2
      assert page.evaluate("window.__ws") == 0
  ```

- [ ] **Step 2: Run them against unmodified editor.js; they must fail**

  Run: `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_scrollfix uv run pytest tests/test_e2e_editor_mobile_scroll_anchor.py -m e2e -p no:xdist`

  Expected: (a), (b2), (b), (l), (d), (i), (e) and (k) FAIL on their position assertions; (f)+(g) PASS. If a phone test passes on master, its seed is not discriminating; fix the seed, not the assertion. Save the output to the scratchpad as `red_task1.txt` for the PR.

- [ ] **Step 3: Add the helpers in editor.js, directly after `window.libliAlignTopInPane = alignTopInPane;`**

  Semantics (verbatim from spec §Helpers):
  - `paneScrolls()`: `/^(auto|scroll|overlay)$/` on the editor `.pane-body`'s computed `overflowY`; false when the element is missing.
  - `viewportH()`: `(window.visualViewport && visualViewport.height) || window.innerHeight`.
  - `onScreen(top)`: `0 <= top && top < viewportH()`.
  - `rendered(el)`: `!!el && el.isConnected && (el.checkVisibility ? el.checkVisibility() : (!el.closest("details:not([open])") && el.getClientRects().length > 0)) && el.getBoundingClientRect().height > 0`. Its comment says it is defence-in-depth with no test (spec "Admitted gap: rendered()").

- [ ] **Step 4: Implement `recordAnchors(form, submitter, status, opRow)`, candidates 2 + 3 only in this task**

  - **Op name.** `op = form.getAttribute("data-op")`.
  - **Candidate 2.**
    - `HEAD_OPS = ["element-move", "element-clip", "element-duplicate"]`. Add `"element-paste-before"` when `form.elements.mode && form.elements.mode.value === "copy"` (always via `form.elements`, never `form.mode`; see the shadowing note in `post()`). Task 2 handles the move case.
    - `OTHER_OPS = ["element-save", "element-delete"]`. An op in neither set records nothing.
    - Record `{id: opRow's data-element, top: opRow top, primary: false}` when `rendered(opRow)` and either:
      - a head op with `onScreen(form.getBoundingClientRect().top)`; or
      - an other op with `onScreen(opRow top)`.
  - **Candidate 3.**
    - Walk `[data-scope="editor"] .el-row[data-element]` in document order.
    - Skip rows that are not `rendered`.
    - **Stop** at the first rendered row whose top is `>= viewportH()`.
    - Collect up to 5 with `onScreen(top)`.
    - For `element-delete`, skip `opRow` and rows inside it (`opRow.contains(row)`).
  - **Result.** Return the array in candidate order. Never scroll here.

- [ ] **Step 5: Implement `keepInPlace(anchors)` and `revealFocusRow(row)`**

  - `keepInPlace`:
    - Iterate in order. Take the first anchor whose `editorRow(id)` is `rendered`.
    - `dy = row.getBoundingClientRect().top - anchor.top`; if `Math.abs(dy) >= 1`, call `window.scrollBy(0, dy)`.
    - Return `anchor.primary`; return false if nothing resolved.
  - `revealFocusRow`:
    - If `rendered(row)` and (`bottom <= 0 || top >= viewportH()`), scroll by `top - margin`, skipped when `|delta| < 1`.
    - `margin` = `parseFloat(getComputedStyle(editor .pane-body).paddingTop) || 0`.

- [ ] **Step 6: Wire it into the submit handler**

  - Before `post(...)`: `var submitter = e.submitter || null;` Pass it to `post` in place of `e.submitter`, with the same value.
  - Inside the existing `if (res.status === 200 || res.status === 409 || res.status === 422)` block, **before** `applyFragments(res.text)`:
    `var anchors = recordAnchors(form, submitter, res.status, opRow);`
  - Keep `applyFragments` and the `flash` line as they are.
  - Keep the `pane` / `focusId` lines as they are. Then:

  ```js
  if (paneScrolls()) {
    if (focusId) {               // today's code, unchanged
      alignTopInPane(root.querySelector('.el-row[data-element="' + focusId + '"]'));
      scrollPreviewTo(focusId);
    }
  } else {
    var primaryHeld = keepInPlace(anchors);
    if (!primaryHeld && focusId) revealFocusRow(editorRow(focusId));
    if (focusId) scrollPreviewTo(focusId);   // no-op on this layout; never redirect it
  }
  ```

  - Add a comment beside this block noting:
    - 200/409/422 share candidates 2–3 untested (spec admitted gap);
    - duplicate/update-save have no dedicated test.

- [ ] **Step 7: Run the new file; all must pass**

  Same command as Step 2. Expected: every test in Step 1 PASSES.

  Then run every non-e2e test that reads editor.js. List them with `grep -l "editor.js" tests/test_*.py | grep -v test_e2e_`; this includes `tests/test_editor_js_scroll_invariants.py` and `tests/test_editor_js_form_action.py`. Run them with `uv run pytest <those paths>`. Expected: all pass.
  - `test_editor_js_form_action.py` fails on ANY `.action` in editor.js code, so no new code may spell `.action`.
  - The new code never needs the clip action, because cancel has no `opRow`.

- [ ] **Step 8: Commit**

  ```bash
  git add courses/static/courses/js/editor.js tests/test_e2e_editor_mobile_scroll_anchor.py
  git commit -m "fix(editor): keep the op row in place on the stacked (phone) editor"
  ```

---

### Task 2: Paste-move primary anchor (candidate 1), clip-subtree exclusion, container fallbacks (candidate 4)

**Files:**
- Modify: `courses/static/courses/js/editor.js` (`recordAnchors` only)
- Test: `tests/test_e2e_editor_mobile_scroll_anchor.py`

**Interfaces:**
- Consumes: `recordAnchors`, `keepInPlace`, `rendered`, `onScreen`, `viewportH`, `editorRow`, and the Task 1 test helpers.
- Produces: no new names. Candidate objects with `primary: true` come only from candidate 1.

- [ ] **Step 1: Write the failing paste tests**

  ```python
  def test_phone_move_here_lands_at_tapped_spot(page, live_server):  # (c)
      # seed: texts, S = callout(5 children) (assert S row height >= 200), destination callout D
      # with ~8 text children whose LAST child is a nested callout(8 children) (assert its height >
      # innerHeight/2), trailing. Discrimination: under mutant 1 S lands at f0 + formH - S.height.
      # select S; scroll so the callout's form[data-op=element-paste] button[value=move] is
      # mid-viewport, the callout row top < 0, and no child row top is on-screen (assert all)
      # f0 = paste form top; click Move here
      assert abs(_row_top(page, s) - f0) <= 2
      assert 0 <= _row_top(page, s) < page.evaluate("innerHeight")   # S on-screen

  def test_phone_move_before_lands_at_tapped_spot(page, live_server):  # (h)
      # seed: texts, S = callout(5 children), 3 texts, T, trailing; select S; scroll so T is the
      # FIRST rendered on-screen row (rows above it off-screen) and its paste-before button is
      # on-screen (assert both). That way mutant 6 (no candidate 1, no candidate 2) holds T,
      # putting S at T.top - S.height, far from f0.
      # f0 = T's form[data-op=element-paste-before] top; click it
      assert abs(_row_top(page, s) - f0) <= 2

  def test_phone_move_before_tall_element_skips_safety_net(page, live_server):  # (h2)
      # as (h) with S = callout(~15 children); assert S height > innerHeight - f0, so T lands
      # entirely below the viewport
      assert abs(_row_top(page, s) - f0) <= 2

  def test_phone_refused_move_does_not_jump(page, live_server):  # (j)
      # seed: texts, S, 6 texts, callout(2), trailing; select S; Move-here button mid-viewport,
      # S above the viewport; R=_first_visible_row_id; set the paste form's
      # input[name=unit_token] to "2000-01-01T00:00:00+00:00" via evaluate; click Move here (409)
      assert abs(_row_top(page, r) - t0) <= 2
      assert page.evaluate("(id)=>document.querySelector('[data-scope=\"editor\"] .el-row[data-element=\"'+id+'\"]').getBoundingClientRect().bottom", s) <= 0
  ```

- [ ] **Step 2: Run; (c), (h) and (h2) must fail**

  Run: `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_scrollfix uv run pytest tests/test_e2e_editor_mobile_scroll_anchor.py -m e2e -p no:xdist -k "move_here or move_before or refused"`

  Expected: (c), (h) and (h2) FAIL; (j) may pass. Save the output as `red_task2.txt`.

- [ ] **Step 3: Extend `recordAnchors`**

  - **Paste-move detection.**
    - `isPasteMove = (op === "element-paste" && submitter && submitter.name === "mode" && submitter.value === "move") || (op === "element-paste-before" && form.elements.mode && form.elements.mode.value === "move")`.
    - Read the mode through `form.elements`, never `form.action`/`form.mode` shortcuts (see the shadowing note in `post()`).
  - **Candidate 1, first in the list.** When `isPasteMove && status === 200`, record `{id: form.elements.element.value, top: form.getBoundingClientRect().top, primary: true}`.
  - **Candidate 2.**
    - `element-paste` never records candidate 2.
    - `element-paste-before` records it only when its mode is `copy`.
  - **Candidate 3: clip-subtree exclusion.**
    - When `isPasteMove` (any status), find `clipRow = editorRow(form.elements.element.value)`.
    - Skip `clipRow` and any row it `contains`. A missing `clipRow` means no exclusion.
  - **Candidate 4, after the catch-all rows.**
    - For each recorded catch-all row with `row.closest(SLOT_DETAILS)`, walk up its ancestor `.el-row[data-element]` rows, innermost first. Record each with its current top, even if off-screen.
    - Skip ids already recorded, and apply both exclusions.
    - Comment: "no test seeds a re-collapsing tabs/columns slot (spec admitted gap)".

- [ ] **Step 4: Run the whole new file; all must pass**

  Command as in Task 1 Step 2, without `-k`. Expected: all 13 PASS. Then re-run Task 1 Step 7's grep-derived non-e2e editor.js tests (the `.action` ban included). Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add courses/static/courses/js/editor.js tests/test_e2e_editor_mobile_scroll_anchor.py
  git commit -m "fix(editor): moved element lands where it was tapped on the stacked editor"
  ```

---

### Task 3: Falsification record and regression sweep

**Files:**
- No planned changes. Commit only seed fixes or formatting found here. The evidence goes to `<scratchpad>/falsification.md` and into the PR body.

**Interfaces:**
- Consumes: the finished `editor.js` (Task 2 commit) and the 13 tests.

- [ ] **Step 1: RED on master**

  1. Back up the fixed file: `cp courses/static/courses/js/editor.js "C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/83592fd0-f524-4a85-a21b-2c06f2fd95f9/scratchpad/editor.fixed.js"`.
  2. Install the base version. Run `git merge-base HEAD origin/master` first (one call), then `git show <that sha>:courses/static/courses/js/editor.js > courses/static/courses/js/editor.js`.
  3. Run the new file with Task 1 Step 2's command.
  4. Expected RED: (a), (b), (b2), (c), (d), (e), (h), (h2), (i), (k), (l). (j) and (f)+(g) may pass. Record (g)'s spy count as the **zero baseline**.
  5. Restore: `cp "C:/Users/krzys/AppData/Local/Temp/claude/C--Users-krzys-Documents-Python-own-libli/83592fd0-f524-4a85-a21b-2c06f2fd95f9/scratchpad/editor.fixed.js" courses/static/courses/js/editor.js`, then `git diff --quiet courses/static/courses/js/editor.js`. It must be clean.

  Never use `git checkout` to revert (memory: it has destroyed work three times).

- [ ] **Step 2: Mutants, one at a time**

  Apply each mutant by hand with Edit, read the `git diff`, run only the named test, record RED, then restore with the `cp` + `git diff --quiet` check.

  | # | Mutant (edit in `recordAnchors` / handler) | Must go RED |
  |---|---|---|
  | 1 | delete candidate 1's push | (c) |
  | 2 | delete the candidate-3 loop | (d) |
  | 3 | delete the `revealFocusRow(...)` call | (e) |
  | 4 | move the `recordAnchors` call to after `applyFragments` | (a) |
  | 5 | replace `paneScrolls()` with `false` | (g), with a non-zero spy count recorded |
  | 6 | read paste-before mode from `submitter.value` | (h) |
  | 7 | call `revealFocusRow` even when `primaryHeld` | (h2) |
  | 8 | drop the delete-subtree exclusion | (i) |
  | 9 | drop `&& status === 200` from candidate 1 | (j) |
  | 10 | in the window branch, follow `scrollPreviewTo(focusId)` with a `setTimeout(..., 500)` that does `window.scrollBy(0, <.prev-el[data-element-id=focusId]>.getBoundingClientRect().top)` (the preview redirected to the window) | (k) |
  | 11 | gate head ops on `onScreen(opRow top)` instead of the form's top | (b2) |
  | 12 | remove `"element-clip"` from `HEAD_OPS` (it then falls into neither set) | (l) |

  If a mutant stays GREEN, the test is not discriminating: fix the test's seed (spec §Testing), re-run its RED/GREEN, and commit the test change as `test(editor): ...`.

  Also record the discrimination:
  - (c), under mutant 1: S's top differs from `f0` by more than 50 px.
  - (h), under mutant 6: S's top differs from `f0` by more than 10 px.

- [ ] **Step 3: Regression sweep (branch gate)**

  Run in 3 chunks, foreground, each with a Bash timeout of 600000 and `-p no:xdist`. Prefix every command with
  `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_scrollfix uv run pytest -m e2e -p no:xdist`.
  - **Chunk 1:**
    - `tests/test_e2e_editor_scroll_containment.py`
    - `tests/test_e2e_editor_preview_state_regression.py`
    - `tests/test_e2e_preview_nested_locate.py`
    - `tests/test_e2e_editor.py`
    - `tests/test_e2e_editor_view_toggle.py`
    - `tests/test_e2e_editor_row_layout.py`
    - `tests/test_e2e_editor_container_state.py`
    - `tests/test_e2e_editor_force_open.py`
    - `tests/test_e2e_editor_saved_element_in_view.py`
    - `tests/test_e2e_editor_unit_token.py`
  - **Chunk 2:**
    - `tests/test_e2e_clipboard.py`
    - `tests/test_e2e_paste_before.py`
    - `tests/test_e2e_cross_unit_copy.py`
  - **Chunk 3:**
    - `tests/test_e2e_tabs.py`
    - `tests/test_e2e_twocolumn.py`
    - `tests/test_e2e_depth3.py`
  - **Unit files**, in their own command without `-m e2e`: the Task 1 Step 7 grep list, e.g. `uv run pytest tests/test_editor_js_scroll_invariants.py tests/test_editor_js_form_action.py ...`.

  The files, for reference:
  - Unit test: `tests/test_editor_js_scroll_invariants.py`.
  - e2e (with `-m e2e`, and the `TEST_DATABASE_URL` above):
    - `test_e2e_editor_scroll_containment.py`
    - `test_e2e_editor_preview_state_regression.py`
    - `test_e2e_preview_nested_locate.py`
    - `test_e2e_editor.py`
    - `test_e2e_clipboard.py`
    - `test_e2e_paste_before.py`
    - `test_e2e_cross_unit_copy.py`
    - `test_e2e_editor_view_toggle.py`
    - `test_e2e_editor_row_layout.py`
    - `test_e2e_editor_container_state.py`
    - `test_e2e_editor_force_open.py`
    - `test_e2e_editor_saved_element_in_view.py`
    - `test_e2e_editor_unit_token.py`
    - `test_e2e_tabs.py`
    - `test_e2e_twocolumn.py`
    - `test_e2e_depth3.py`

  Expected: all pass. For any failure, re-run that test alone. If it fails on master too (use the same `cp` swap), it is pre-existing; record it and do not fix it here.

- [ ] **Step 4: Lint/format gates**

  Run `uv run ruff check --no-cache tests/test_e2e_editor_mobile_scroll_anchor.py` and `uv run ruff format --check tests/test_e2e_editor_mobile_scroll_anchor.py`. Expected: both clean (run `ruff format` and commit if needed).
