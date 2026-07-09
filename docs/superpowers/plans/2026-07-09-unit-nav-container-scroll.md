# Unit-nav container-scoped auto-scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `unit_nav.js`'s load-time active-item auto-scroll scroll the `[data-unit-tree]` rail container directly instead of via `scrollIntoView`, so the window/article never jumps on load; then remove the now-unneeded slideshow test warm-up.

**Architecture:** One JS block in `unit_nav.js` is rewritten to compute a rail-scroll target from live rects and call `tree.scrollTo(...)`. A new e2e test guards that the window doesn't move; the slideshow bar-position test drops its warm-up.

**Tech Stack:** Vanilla ES5-style JS (matching `unit_nav.js`), Playwright e2e (`pytest -m e2e`).

## Global Constraints

- **ES5 style** in `unit_nav.js`: `var`, function expressions — no arrow functions / `const` / `let`.
- **Never window-scroll:** if `[data-unit-tree]` is absent, no-op — never fall back to the window-scrolling `scrollIntoView`.
- **Preserve behavior:** same guard as today (scroll only when the rail + an active item exist AND the tree is not collapsed); preserve smooth vs reduced-motion (`behavior: reduce ? "auto" : "smooth"`).
- **Centering is offsetParent-independent** (rect-delta, not `offsetTop`) and border-robust (subtract `tree.clientTop`).
- **Run e2e with:** `uv run pytest tests/test_e2e_unit_nav.py tests/test_e2e_slideshow.py -m e2e -v` (both files are marked `e2e`, excluded from the default run; `-m e2e` includes them). Python tooling is only on PATH via `uv run`.

---

### Task 1: Container-scoped rail auto-scroll + window-no-jump test

Rewrite the desktop auto-scroll block in `unit_nav.js` to scroll the rail container directly, and add an e2e test proving the window doesn't move on load.

**Files:**
- Modify: `courses/static/courses/js/unit_nav.js` (the desktop auto-scroll block, currently lines ~29-42)
- Test: `tests/test_e2e_unit_nav.py` (new `test_active_unit_scroll_does_not_move_window`)

**Interfaces:**
- Consumes: existing `isCollapsed()` helper in `unit_nav.js`; existing `_seed_nav_course`, `_make_student`, `_login` in `tests/test_e2e_unit_nav.py`.
- Produces: no new JS exports (IIFE). The rail scroll targets `[data-unit-tree]`; the active item is resolved via `tree.querySelector(".unit-tree__unit.is-active")`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_e2e_unit_nav.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_active_unit_scroll_does_not_move_window(browser, live_server):
    """Load-time rail auto-scroll must NOT scroll the window/article.

    The active (last) unit has a tall article so the page overflows the viewport
    (window.scrollY CAN change); with the pre-fix `scrollIntoView` the queued
    window scroll pushed scrollY non-zero, with the container-scoped fix it stays 0.
    """
    from courses.models import TextElement
    from tests.factories import add_element

    _make_student("e2e_nav_nojump")
    course, units = _seed_nav_course("e2e_nav_nojump", "e2e-nav-nojump", num_units=35)
    last_unit = units[-1]
    tall = "".join(f"<p>Para {i}</p>" for i in range(200))
    add_element(last_unit, TextElement.objects.create(body=tall))

    # reduced-motion → instant scroll (rail AND, pre-fix, the window scroll) settles
    # synchronously, so the poll-then-read below is deterministic.
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_nav_nojump")
    unit_url = f"{live_server.url}/courses/{course.slug}/u/{last_unit.pk}/"
    page.goto(unit_url)

    # Precondition: the page really overflows, so the guard below can't go vacuous.
    assert page.evaluate(
        "() => document.documentElement.scrollHeight > window.innerHeight"
    ), "seed did not overflow the viewport; window-no-jump guard would be vacuous"

    # Wait until the rail has scrolled the active (last) item down.
    tree = page.locator("[data-unit-tree]")
    page.wait_for_function("el => el.scrollTop > 0", arg=tree.element_handle())

    assert page.evaluate("() => window.scrollY") == 0, (
        "load-time auto-scroll moved the window/article"
    )
    ctx.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_unit_nav.py::test_active_unit_scroll_does_not_move_window -m e2e -v`
Expected: FAIL — the current `active.scrollIntoView({block:"center"})` nudges the window, so `window.scrollY` is non-zero.

- [ ] **Step 3: Rewrite the auto-scroll block in `unit_nav.js`**

Find this block (currently lines ~29-42):

```javascript
  // Auto-scroll the active unit into view — only when expanded (labels visible),
  // after the pre-paint collapse restore has already run on <html>.
  var active = document.querySelector(".unit-tree__unit.is-active");
  if (active && !isCollapsed()) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    active.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }
  // NOTE: spec §3.3 mandates scrollIntoView({block:"center"}). It walks every scrollable
  // ancestor, so in principle it could also nudge the window (jumping the article), not
  // just the sticky tree rail. If the Task-7 screenshot/e2e pass reveals a page jump,
  // switch to scrolling the container directly:
  //   var tree = document.querySelector("[data-unit-tree]");
  //   if (tree && active) tree.scrollTop = active.offsetTop - tree.clientHeight / 2;
  // (the sticky/overflow-y:auto tree is the intended scroll target).
```

Replace it with:

```javascript
  // Auto-scroll the active unit into view — only when expanded (labels visible),
  // after the pre-paint collapse restore has already run on <html>. Scroll the rail
  // CONTAINER directly rather than active.scrollIntoView({block:"center"}): the
  // latter walks every scrollable ancestor and could also nudge the window/article
  // on load. Scope the active lookup to the rail so the mobile drawer's second
  // .is-active node is never selected.
  var tree = document.querySelector("[data-unit-tree]");
  var active = tree && tree.querySelector(".unit-tree__unit.is-active");
  if (tree && active && !isCollapsed()) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Center the active item within the rail, in the rail's scroll coordinates.
    // getBoundingClientRect().top is the border-box outer edge; clientTop (top
    // border, 0 today) reconciles it with scrollTop's padding-box origin so the
    // formula survives a future top-border. scrollTo clamps out-of-range targets.
    var delta = active.getBoundingClientRect().top - tree.getBoundingClientRect().top;
    var target = tree.scrollTop + delta - tree.clientTop - (tree.clientHeight - active.offsetHeight) / 2;
    tree.scrollTo({ top: target, behavior: reduce ? "auto" : "smooth" });
  }
```

- [ ] **Step 4: Run the new test + the existing centering test to verify green**

Run: `uv run pytest tests/test_e2e_unit_nav.py::test_active_unit_scroll_does_not_move_window tests/test_e2e_unit_nav.py::test_active_unit_scrolled_into_view -m e2e -v`
Expected: BOTH PASS — the new test confirms `window.scrollY == 0`; `test_active_unit_scrolled_into_view` confirms the rail still scrolls (`scrollTop > 0`) and centers the active item within the rail box (the container-scoped scroll preserves the centering behavior).

- [ ] **Step 5: Run the full unit-nav e2e file (no regressions)**

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e -v`
Expected: all pass (collapse persistence, centering, the new no-jump test, mobile drawer tests, traversal).

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/unit_nav.js tests/test_e2e_unit_nav.py
git commit -m "fix(unit-nav): scroll the rail container directly so load doesn't jump the window"
```

---

### Task 2: Drop the now-unneeded slideshow test warm-up

With the rail no longer scrolling the window, `test_bar_position_is_stable_across_slides` no longer needs its warm-up click + fixed wait.

**Files:**
- Modify: `tests/test_e2e_slideshow.py` (`test_bar_position_is_stable_across_slides`)

**Interfaces:**
- Consumes: the `unit_nav.js` fix from Task 1 (the reason the warm-up is safe to remove).

- [ ] **Step 1: Remove the warm-up block**

In `tests/test_e2e_slideshow.py`, in `test_bar_position_is_stable_across_slides`, delete the warm-up comment + `bar.click()` + `page.wait_for_timeout(300)` so `y0` is read directly after `page.goto`. Find:

```python
    page.goto(f"{live_server.url}{path}")
    bar = page.locator(".slideshow-bar")
    # Warm-up click: unrelated to the deck under test, this settles a pre-existing
    # queued animation (unit_nav.js centers the active sidebar entry with a
    # window-level `scrollIntoView({behavior:"smooth"})` on load) that Chromium
    # otherwise defers until the first trusted user gesture, which would otherwise
    # land on our first "Next" click and get misread as deck instability. Click a
    # non-interactive part of the bar so slide state (idx) is untouched.
    bar.click()
    page.wait_for_timeout(300)
    y0 = bar.bounding_box()["y"]
```

Replace with:

```python
    page.goto(f"{live_server.url}{path}")
    bar = page.locator(".slideshow-bar")
    y0 = bar.bounding_box()["y"]
```

- [ ] **Step 2: Run the test to verify it passes without the warm-up**

Run: `uv run pytest tests/test_e2e_slideshow.py::test_bar_position_is_stable_across_slides -m e2e -v`
Expected: PASS — the bar's viewport `y` is stable across slide 0 and the tall slide 2 without any warm-up, because the unit_nav rail scroll (Task 1) no longer perturbs the window. This is the cross-file regression guard: had the window-jump remained, reading `y0` immediately after load would race the deferred scroll and the assertion would fail.

- [ ] **Step 3: Run the full slideshow e2e file (no regressions)**

Run: `uv run pytest tests/test_e2e_slideshow.py -m e2e -v`
Expected: all 17 pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_slideshow.py
git commit -m "test(slideshow): drop bar-position warm-up now that unit_nav no longer window-scrolls"
```

---

## Notes for the executor

- Run only the two e2e files named per task; the controller runs any broader DoD.
- `add_element(unit, obj)` and `TextElement.objects.create(body=...)` follow the exact idiom already used by the tall seeds in `tests/test_e2e_slideshow.py` and `tests/factories.py`; import them locally inside the new test (the file's established pattern).
- Keep ES5 style in `unit_nav.js`.
