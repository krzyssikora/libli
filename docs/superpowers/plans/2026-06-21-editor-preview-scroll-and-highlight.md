# Unit Editor: Independent Preview Scroll, Scroll-to-on-Select, Contrast-Safe Highlight — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the unit editor and its live preview visually connected on long units, by giving the preview its own scroll, scrolling it to the element you select, and making the hover highlight read clearly on any background.

**Architecture:** Three small, independent front-end changes. (1) CSS turns the sticky preview pane into a viewport-capped, internally-scrolling flex column. (2) JS hangs a deferred `scrollIntoView` off the existing `.el-select` (select/edit) click so the preview scrolls to the chosen element after the fragment swap rebuilds it. (3) CSS replaces the single highlight ring with a two-layer contrast halo. No templates, views, models, or migrations change; the existing `data-element` / `data-element-id` matching and the `applyFragments` swap flow are reused unchanged.

**Tech Stack:** Server-rendered Django; token-driven hand-written CSS (`courses/static/courses/css/editor.css`); vanilla ES5 IIFE JS (`courses/static/courses/js/editor.js`); WhiteNoise static serving; Playwright e2e via pytest.

## Global Constraints

- **No automated test is added for these visual/behavioural changes.** The spec decided this explicitly; the gate is the **existing editor e2e flow staying green** plus a **manual verification protocol**. Do not write new unit tests for CSS ring colours or scroll geometry.
- **Token-driven CSS only.** Use existing CSS custom properties (`var(--…)`); no hardcoded colours, sizes, or hex values. New colours must reuse existing tokens (`--primary`, `--surface-raised`, `--radius-sm`, `--space-4`).
- **Match the existing JS style in `editor.js`:** ES5 — `var` (no `let`/`const`), `function () {}` expressions (no arrow functions), 2-space indentation inside the IIFE. Reference browser globals with the `window.` prefix where the file already does (e.g. `window.libli*`); use `window.matchMedia`.
- **No new dependencies, no build step.** WhiteNoise serves the edited files directly under `runserver` with `DEBUG=True`; no bundler/eslint. (`collectstatic` is only for production.)
- **Commit messages** follow the repo's conventional-commit style (`feat(editor): …` / `fix(editor): …`) and must end with the repo's two trailer lines (`Co-Authored-By: Claude …` and `Claude-Session: …`) per repo policy.
- **Spec of record:** `docs/superpowers/specs/2026-06-21-editor-preview-scroll-and-highlight-design.md`.

## File Structure

| File | Responsibility | Tasks |
|------|----------------|-------|
| `courses/static/courses/css/editor.css` | Preview scroll container + responsive reset (`:199`, `:208`); contrast halo (`:284`) | Task 1, Task 2 |
| `courses/static/courses/js/editor.js` | `scrollPreviewTo` helper + scroll hook on the `.el-select` branch | Task 3 |

No files are created. No templates, views, models, or migrations are touched.

## Manual Verification Setup (used by Tasks 1–3 and 4)

You need a course unit whose preview is **taller than the viewport** and contains **both light- and dark-backgrounded elements** (e.g. a heading/text element and a media/callout element).

1. Start the dev server: `python manage.py runserver`
2. Log in as a user who can manage a course, and open a unit editor:
   `/manage/courses/<course-slug>/build/unit/<unit-pk>/edit/` (Django URL name `courses:manage_editor`).
3. If no unit is long enough, use the editor's **Add** button to add elements until the live preview clearly exceeds the viewport height. (Add is only for lengthening the unit — it is the unchanged `data-add-type` flow and is expected NOT to scroll-to-select, so don't read scroll motion on Add as a Task 3 result.)
4. **Hard-refresh (Ctrl+F5)** after each CSS/JS edit to bypass the browser cache.

---

### Task 1: Contrast-safe highlight (two-layer halo)

Smallest, fully isolated change — no dependency on the other two. Start here.

**Files:**
- Modify: `courses/static/courses/css/editor.css:284`

**Interfaces:**
- Consumes: existing tokens `--primary`, `--surface-raised`; existing `.prev-el { … transition: box-shadow .1s ease; }` at `editor.css:283` (kept, gives the fade).
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Replace the single-ring highlight with a two-layer halo**

In `courses/static/courses/css/editor.css`, find (line 284):

```css
.prev-el--hl { box-shadow: 0 0 0 2px var(--primary); }
```

Replace it with:

```css
.prev-el--hl {
  box-shadow:
    0 0 0 3px var(--primary),
    0 0 0 5px var(--surface-raised);
}
```

Leave the `.prev-el { border-radius: var(--radius-sm); transition: box-shadow .1s ease; }` rule on the line above (283) unchanged — it still supplies the fade and the corner radius the halo inherits.

- [ ] **Step 2: Confirm the existing editor e2e flow still passes**

Run (the `-k editor` filter selects both editor e2e modules — `tests/test_e2e_editor.py` and
`tests/test_e2e_editor_ws3.py` — which is intended):

```bash
uv run python -m pytest -m e2e -k editor
```

Expected: PASS (no assertions touch `box-shadow`; this confirms the change didn't break the page). If Playwright browsers are not installed yet, first run `uv run playwright install --with-deps chromium`. If `-k editor` matches nothing, run the full e2e set: `uv run python -m pytest -m e2e`.

- [ ] **Step 3: Manual visual check**

With the dev server running (see Manual Verification Setup), hover an editor row whose preview element has a **light** background, then one with a **dark** background. Confirm the ring is **clearly visible on both** — the `--primary` ring separated from the content by the outer `--surface-raised` halo. Eyeball that the halo's rounded corners (inherited from `.prev-el`'s `--radius-sm`) read cleanly against adjacent elements.

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/css/editor.css
# Commit message must end with the repo's two trailer lines (Co-Authored-By / Claude-Session) — see Global Constraints; the one-liner below is only the subject.
git commit -m "feat(editor): contrast-safe two-layer highlight ring on preview hover"
```

---

### Task 2: Independent preview scroll container + responsive reset

Gives the preview its own viewport-capped scroll. Must land **before** Task 3, because Task 3's `scrollIntoView({block:"nearest"})` relies on `.pane-body` being the scroll container so the page itself does not scroll.

**Files:**
- Modify: `courses/static/courses/css/editor.css:199` (the `.preview-pane` rule)
- Modify: `courses/static/courses/css/editor.css:208` (the `@media (max-width: 900px)` block)

**Interfaces:**
- Consumes: existing tokens `--space-4`; existing `.pane-body { padding: var(--space-4); }` (`:198`) and `.editor-grid { align-items: start }` (`:16`).
- Produces: `.preview-pane .pane-body` becomes the scroll container that Task 3's `scrollIntoView` resolves against.

- [ ] **Step 1: Replace the `.preview-pane` rule with the scrolling flex column**

In `courses/static/courses/css/editor.css`, find (line 199):

```css
.preview-pane { position: sticky; top: var(--space-4); align-self: start; }
```

Replace it with:

```css
.preview-pane {
  position: sticky;
  top: var(--space-4);
  align-self: start;
  display: flex;
  flex-direction: column;
  /* Cap to the viewport so the preview can never run far past the editor.
     Accurate once the pane is stuck at top:var(--space-4); above that scroll
     position the pane sits below the page header (.editor-crumb / .editor-head /
     .unit-settings render above .editor-grid), so the cap overestimates the
     available height and the pane bottom may overhang until sticky engages. */
  max-height: calc(100vh - var(--space-4) * 2);
}
.preview-pane .pane-body {
  overflow-y: auto;
  min-height: 0; /* allow the flex child to shrink so overflow engages */
}
```

`align-self: start` is kept verbatim (belt-and-suspenders vs the grid's `align-items: start`). The new rules are scoped under `.preview-pane`, so the editor pane's own `.pane-body` (same class, different ancestor) is untouched.

- [ ] **Step 2: Extend the responsive block so the pane un-sticks when the panes stack**

In `courses/static/courses/css/editor.css`, find (line 208):

```css
@media (max-width: 900px) { .editor-grid { grid-template-columns: 1fr; } }
```

Replace it with:

```css
@media (max-width: 900px) {
  .editor-grid { grid-template-columns: 1fr; }
  .preview-pane { position: static; max-height: none; display: block; }
  .preview-pane .pane-body { overflow-y: visible; }
}
```

This is the correct breakpoint: `max-width: 900px` already covers every width ≤ 720px, so the panes stack at 900px and this is where the viewport-cap/sticky must be undone. (Leave the redundant `@media (max-width: 720px)` rule at `:19-21` as-is — do not move the reset there.) The desktop `min-height: 0` is intentionally left on `.pane-body`; on a `display: block` stacked pane it is inert.

- [ ] **Step 3: Confirm the existing editor e2e flow still passes**

```bash
uv run python -m pytest -m e2e -k editor
```

Expected: PASS. (Fallback: `uv run python -m pytest -m e2e`.)

- [ ] **Step 4: Manual layout check**

With a long unit (see Manual Verification Setup), confirm:
- The preview **scrolls internally** (its own scrollbar) and no longer runs far past the editor list.
- Scrolling the **page** still moves through the **editor rows** while the preview stays pinned (the editor column must NOT gain its own height cap).
- The **editor pane's own `.pane-body` has no scrollbar** (the override is scoped under `.preview-pane`).
- The preview's **rounded bottom corners** are not visibly clipped by the scrollbar gutter. (If they overrun, the spec's fallback is to add `border-bottom-left-radius`/`border-bottom-right-radius` to `.pane-body`, or move overflow to an inner wrapper with `overflow: hidden` on the pane — apply only if needed.)
- **Resize the window below 900px**: the preview stacks below the editor and scrolls with the page (no clipped or stuck pane).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/css/editor.css
# Commit message must end with the repo's two trailer lines (Co-Authored-By / Claude-Session) — see Global Constraints; the one-liner below is only the subject.
git commit -m "feat(editor): give the live preview its own viewport-capped scroll"
```

---

### Task 3: Scroll the preview to the selected element

Adds the `scrollPreviewTo` helper inside the editor IIFE and calls it after the `.el-select` fragment swap. Depends on Task 2 (the scroll container) for the "only the preview scrolls" behaviour.

**Files:**
- Modify: `courses/static/courses/js/editor.js` — insert helper after `bindHover` (after line 60); modify the `.el-select` branch (lines 149-153).

**Interfaces:**
- Consumes: IIFE-scoped `root` (`document.querySelector(".editor")`, `editor.js:3`); existing `applyFragments(html)` (`editor.js:28-45`); the `.el-select` button's `data-element-id` (`_element_row.html:11,33`); the preview section `.prev-el[data-element-id]` (`_preview.html:15`); `window.matchMedia`, `requestAnimationFrame`.
- Produces: `function scrollPreviewTo(id)` — no return value; a no-op when `id` is falsy or no matching `.prev-el` exists.

- [ ] **Step 1: Add the `scrollPreviewTo` helper inside the IIFE**

In `courses/static/courses/js/editor.js`, find the end of `bindHover` and the start of `post` (lines 58-62):

```js
      row.addEventListener("mouseenter", function () { setHighlight(id, true); });
      row.addEventListener("mouseleave", function () { setHighlight(id, false); });
    });
  }

  function post(form, submitter) {
```

Replace that span with (inserts the helper between `bindHover` and `post`):

```js
      row.addEventListener("mouseenter", function () { setHighlight(id, true); });
      row.addEventListener("mouseleave", function () { setHighlight(id, false); });
    });
  }

  // Scroll the preview to a just-selected element after the fragment swap rebuilt it.
  // Deferred one frame: applyFragments runs KaTeX / inline-math / DnD enhancement
  // synchronously, but scrollIntoView must read geometry AFTER the browser's layout
  // flush, or a re-rendered element that grew above the target throws the landing off.
  // querySelector returns null when the id is absent (failed/empty swap, or a deleted
  // element) and the guard makes it a no-op, so this can never throw.
  function scrollPreviewTo(id) {
    if (!id) return;
    var el = root.querySelector('.prev-el[data-element-id="' + id + '"]');
    if (!el) return;
    var smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(function () {
      el.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
    });
  }

  function post(form, submitter) {
```

- [ ] **Step 2: Call `scrollPreviewTo` from the `.el-select` branch**

In the same file, find the `.el-select` branch (lines 149-153):

```js
    var sel = e.target.closest(".el-select");
    if (sel) {
      fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); }).then(applyFragments);
    }
```

Replace it with:

```js
    var sel = e.target.closest(".el-select");
    if (sel) {
      var selId = sel.getAttribute("data-element-id");
      fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { applyFragments(html); scrollPreviewTo(selId); });
    }
```

The only change is the final `.then` handler: the bare `applyFragments` reference becomes the inline `function (html) { applyFragments(html); scrollPreviewTo(selId); }`. The `.then(function (r) { return r.text(); })` text-extraction step is kept. `selId` is read from the button's `data-element-id` (NOT the row's `data-element` at `_element_row.html:2-3`, which only the hover path uses), inside the existing `if (sel)` guard where `sel` is non-null.

- [ ] **Step 3: Confirm the existing editor e2e flow still passes**

This task touches the select path, so the e2e gate matters most here:

```bash
uv run python -m pytest -m e2e -k editor
```

Expected: PASS — fragment swaps on select/edit still work. (Fallback: `uv run python -m pytest -m e2e`.)

- [ ] **Step 4: Manual behaviour check**

With a long unit (Manual Verification Setup), hard-refresh, then:
- Click the ✎ / label of rows **top to bottom**. Confirm the preview **scrolls each off-screen element into view** (smoothly) while already-visible ones **stay put**, and the **page itself does not jump**.
- Select an element, then **delete** it and select another — confirm no error in the console and no stray scroll (the missing-node guard).
- Enable **reduced motion** (OS setting, or Chrome DevTools → Rendering → "Emulate CSS prefers-reduced-motion: reduce"), select an off-screen row, and confirm the preview **jumps instantly** (no smooth animation).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/editor.js
# Commit message must end with the repo's two trailer lines (Co-Authored-By / Claude-Session) — see Global Constraints; the one-liner below is only the subject.
git commit -m "feat(editor): scroll the live preview to the element you select"
```

---

### Task 4: Full verification (DoD gate)

Run the project's full verification once all three changes are in, to confirm nothing regressed.

**Files:** none (verification only).

- [ ] **Step 1: Lint (Python) — confirms no accidental Python breakage**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: PASS. (Our changes are CSS/JS, which ruff does not lint; this just confirms the working tree is clean for CI.)

- [ ] **Step 2: Full unit/integration test suite**

```bash
uv run python -m pytest
```

Expected: PASS (suite is green; no new failures introduced).

- [ ] **Step 3: Full e2e suite**

```bash
uv run python -m pytest -m e2e
```

Expected: PASS. (Run `uv run playwright install --with-deps chromium` first if browsers aren't installed.)

- [ ] **Step 4: Final manual regression sweep**

In the editor (Manual Verification Setup), confirm the unchanged flows still work end-to-end: **save**, **move up/down**, **delete**, **add** an element, and a question's **"Try it"** preview form — each should swap fragments and re-render KaTeX/MathLive correctly, with the preview scroll and highlight behaving as in Tasks 1–3.

- [ ] **Step 5: (Optional) Confirm the spec's acceptance is met**

Re-read the spec's Testing section (`docs/superpowers/specs/2026-06-21-editor-preview-scroll-and-highlight-design.md`) and tick off each listed manual check. No code change expected here — this is the sign-off.

---

## Self-Review

**Spec coverage:**
- Design §1 (independent preview scroll container) → **Task 2** (Steps 1–2: `.preview-pane` flex/`max-height`, `.pane-body` overflow, responsive reset).
- Design §1 rounded-corners caveat → **Task 2 Step 4** manual check + stated fallback.
- Design §2 (scroll-to-on-select, rAF deferral, reduced-motion gate, attribute asymmetry, failure guard) → **Task 3** (Steps 1–2 helper + hook; Step 4 reduced-motion check).
- Design §3 (contrast-safe halo) → **Task 1**.
- Edge cases (already-visible/no-op, deleted/moved guard, render timing/rAF, reduced motion, short unit) → encoded in the Task 3 helper and its Step 4 checks.
- Testing (manual visual, reduced motion, regression, e2e stays green) → Tasks 1–4 verification steps.
- Non-goals (no hover auto-scroll, editor pane scroll untouched, matching/swap unchanged) → honoured; Task 2 Step 4 explicitly checks the editor pane keeps no scrollbar.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every code step shows the exact before/after. ✓

**Type/name consistency:** `scrollPreviewTo(id)` and `selId` are used identically in Task 3 Steps 1 and 2; selector `.prev-el[data-element-id]` matches the spec and `_preview.html:15`; `window.matchMedia` and `requestAnimationFrame` match the spec helper. ✓

**Ordering:** Task 2 (scroll container) precedes Task 3 (scroll-to) as required; Task 1 is independent and first because it's smallest. ✓
