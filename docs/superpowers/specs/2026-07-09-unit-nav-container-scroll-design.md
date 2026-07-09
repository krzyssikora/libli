# Unit-nav container-scoped auto-scroll

## Purpose

On a unit taking-page, `unit_nav.js` auto-scrolls the active item of the
course-contents rail into view on load (so a deep unit isn't off-screen in a long
tree). It does this with `active.scrollIntoView({ block: "center", behavior })`.
`scrollIntoView` walks **every** scrollable ancestor, so besides scrolling the
sticky rail it can also nudge the **window** — jumping the article down a few
hundred pixels on load. This was observed concretely during the slideshow-deck
work (PR #83): the jump forced a warm-up click + fixed `wait_for_timeout(300)` in
`test_bar_position_is_stable_across_slides` to drain the queued scroll before the
test could measure a stable bar position. The `unit_nav.js` code comment
(lines 36–42) already anticipates the fix.

This change makes the load-time auto-scroll **scroll the rail container directly**
(`[data-unit-tree]`) instead of delegating to `scrollIntoView`, so the window is
never touched. It then removes the now-unnecessary test warm-up. Behavior for the
user is unchanged except that the article no longer jumps on load.

### Out of scope

- **The mobile drawer scroll** (`unit_nav.js` line ~76,
  `act.scrollIntoView({ block: "center" })`): it scrolls within a
  `position:fixed` drawer panel, was not the source of the article jump, and is a
  different container/context. Left as-is.
- **The collapse toggle, drawer open/close, focus trap** — untouched.
- No change to markup, CSS, the rail's own sticky/overflow styling, or any server
  code.

## Architecture / components

One JS file changes plus one test-file cleanup and one test extension.

### 1. `unit_nav.js` — container-scoped desktop auto-scroll

Replace the desktop auto-scroll block (currently lines 31–35) and its trailing
"if the e2e reveals a page jump, switch to…" comment (lines 36–42). The current
code:

```js
var active = document.querySelector(".unit-tree__unit.is-active");
if (active && !isCollapsed()) {
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  active.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
}
```

becomes a scroll of the rail container itself. Requirements:

- Resolve the rail via `document.querySelector("[data-unit-tree]")`. Resolve the
  active item as today (`.unit-tree__unit.is-active`), but scoped **within the
  rail** so a second active node in the mobile drawer is never selected
  (`tree.querySelector(".unit-tree__unit.is-active")`).
- Guard exactly as today: only scroll when the rail **and** an active item exist
  **and** the tree is not collapsed (`!isCollapsed()`). If `[data-unit-tree]` is
  absent, **no-op** — never fall back to the window-scrolling `scrollIntoView`.
- **Centering must be offsetParent-independent.** Do not use `active.offsetTop`
  (it is relative to the nearest positioned ancestor, which may be an intermediate
  wrapper, not the rail). Compute the target from live rects:

  ```js
  var delta = active.getBoundingClientRect().top - tree.getBoundingClientRect().top;
  var target = tree.scrollTop + delta - (tree.clientHeight - active.offsetHeight) / 2;
  ```

  `delta` is the active item's current offset from the rail's top edge; adding it
  to the rail's current `scrollTop` yields the item's position in rail-scroll
  coordinates, and subtracting the half-gap centers it. `scrollTo` clamps a
  negative or over-max `target` to the valid range automatically, so no manual
  clamp is required.
- Preserve smooth / reduced-motion behavior via `scrollTo` (not an instant
  `scrollTop =` assignment, which would regress the smooth scroll the current code
  provides):

  ```js
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  tree.scrollTo({ top: target, behavior: reduce ? "auto" : "smooth" });
  ```
- Keep the existing placement (after the collapse-restore, before the mobile
  drawer block) and ES5 style (`var`, function expressions) to match the file.
- Replace the stale multi-line comment with a short one explaining that the rail
  is scrolled directly (not via `scrollIntoView`) so the window/article is never
  nudged.

### 2. `tests/test_e2e_slideshow.py` — remove the warm-up

`test_bar_position_is_stable_across_slides` added a `bar.click()` +
`page.wait_for_timeout(300)` warm-up (with an explanatory comment) solely to drain
this window-scroll before reading `y0`. With the rail no longer scrolling the
window, that warm-up is unnecessary: remove the warm-up lines and their comment,
and read `y0` directly after `page.goto` as the other tests do. The test's
invariant (bar `y` equal on slide 0 vs the tall later slide, within tolerance)
is unchanged.

### 3. `tests/test_e2e_unit_nav.py` — assert the window does not scroll

Extend `test_active_unit_scrolled_into_view` (or add a sibling test on the same
35-unit seed) to assert that on load the **window did not scroll** — the fix's
regression guard — while the rail still scrolls the active item into view.

## Data flow

Unchanged. The rail is server-rendered (`_unit_tree.html`, `<nav class="unit-tree"
data-unit-tree>`), sticky with `overflow-y:auto`. On load `unit_nav.js` reads the
active item and, when the tree is expanded, scrolls the rail so the item is
centered. The only change is the scroll *target*: the rail element itself rather
than whatever ancestor chain `scrollIntoView` chose.

## Error handling

- **No rail / no active item / collapsed tree:** no-op (same guard as today; the
  rail lookup simply returns null → skip).
- **Active item already fully visible:** the computed `target` may be at or near
  the current `scrollTop`; `scrollTo` is a cheap no-op-ish move. Fine.
- **`target` out of range** (active near the very top or bottom of the tree):
  `scrollTo` clamps to `[0, scrollHeight - clientHeight]`, so the active item
  lands as close to centered as the rail allows without over-scrolling.
- **Reduced motion:** `behavior: "auto"` → instant, matching the current code and
  keeping the existing e2e (which sets `reduced_motion="reduce"` for deterministic
  synchronous settling) valid.

## Testing

- **`test_active_unit_scrolled_into_view`** (existing, `reduced_motion="reduce"`,
  35-unit seed) must still pass: exactly one active node in `[data-unit-tree]`,
  the rail's `scrollTop > 0`, and the active item's box within the rail's box.
  This confirms the container-scoped scroll still centers the active item.
- **New window-no-jump assertion** on the same seed: after `page.goto` and after
  the rail has scrolled (`wait_for_function("el => el.scrollTop > 0")`), assert
  `page.evaluate("() => window.scrollY") == 0` (the article did not jump). This is
  the direct regression guard for the reported behavior. (If the page legitimately
  has no vertical overflow at the test viewport, `window.scrollY` is trivially 0;
  the meaningful part is that it stays 0 *despite* the rail scroll — the pre-fix
  `scrollIntoView` is what could push it non-zero.)
- **`test_bar_position_is_stable_across_slides`** (slideshow file) must still pass
  with the warm-up removed — proving the warm-up is no longer needed because the
  rail scroll no longer perturbs the window.
- Run: `uv run pytest tests/test_e2e_unit_nav.py tests/test_e2e_slideshow.py -m e2e -v`
  (both files are marked `e2e`, excluded from the default run; `-m e2e` includes
  them). Python tooling is only on PATH via `uv run`.
