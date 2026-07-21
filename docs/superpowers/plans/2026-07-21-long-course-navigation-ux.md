# Long-course navigation UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make long courses navigable — the builder's detail panel stays on screen while the tree scrolls, and a student's course tree folds to the current unit's chapter with an unmistakable "you are here" marker.

**Architecture:** Three parts in one PR, committed in order. Part 1 is CSS on `.builder__panel` plus a `setPanel()` chokepoint in `builder.js`. Part 2A converts group nodes in `_unit_tree_node.html` to native `<details>`, opened server-side by a new `contains_current` flag stamped in `courses/rollups.py`. Part 2B extracts `centerActive()` in `unit_nav.js` so the rail re-centres on expand, and strengthens `.is-active`.

**Tech Stack:** Django 5.2 templates, vanilla ES5-style JS (no build step), token-driven CSS (`core/static/core/css/tokens.css`), pytest + pytest-django, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-07-21-long-course-navigation-ux-design.md` — read it before starting. It records *why* each decision was made and lists premises that were falsified during review; do not re-derive them.

## Global Constraints

- **Tooling:** `ruff`/`pytest`/`python` are NOT on PATH. Always `uv run ruff …`, `uv run pytest …`. `ruff format --check` too.
- **Test DB:** this worktree needs its own `DATABASE_URL` — concurrent worktrees collide on Postgres `test_libli`.
- **e2e:** run foreground only, never backgrounded (background `-m e2e` spawns runaway browsers). Drive the real UI with real clicks; `page.evaluate` may READ state but must never SUBSTITUTE for a user gesture.
- **RED first:** every new test must be observed failing before its implementation lands. A passing test proves nothing until you've seen it fail.
- **i18n:** new user-visible strings go in both `locale/en/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.po`. Never leave `#~` obsolete entries.
- **CSS:** token-driven, no hardcoded colours. Monochrome `currentColor` line SVGs for icons.
- **Commits:** one per task, scoped to that task's files. Verify `git branch --show-current` is `pipeline/long-course-navigation-ux` before every commit — parallel sessions share this repo directory.
- **Branch/worktree:** all work happens in `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/long-course-navigation-ux`.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `courses/static/courses/css/builder.css` | sticky panel, mobile override, sticky seam, panel-scoped `.op-error` | 1 |
| `courses/static/courses/js/builder.js` | `setPanel()` chokepoint for all 9 panel writes | 2 |
| `tests/test_builder_js_invariants.py` (new) | source-scan: exactly one `panel.innerHTML =` assignment | 2 |
| `tests/test_e2e_builder_tree_layout.py` | builder e2e: deep unit, tall panel, stacked, scroll reset, notice | 1, 2 |
| `courses/rollups.py` | `_stamp_current_chain()`, `_top_level_part()` refactor | 3 |
| `templates/courses/_unit_tree_node.html` | `<details>` group shape, counter, a11y sentence | 4 |
| `locale/{en,pl}/LC_MESSAGES/django.po` | the counter's msgid | 4 |
| `tests/test_unit_nav_render.py` | stamping + render assertions | 3, 4 |
| `courses/static/courses/css/courses.css` | summary layout, child-combinator fix, chevron, active marker | 5, 6 |
| `courses/static/courses/js/unit_nav.js` | `focusable()` widening (5), `centerActive()` (6) | 5, 6 |
| `tests/test_e2e_unit_nav.py` | grouped seed, folding, focus trap, re-centre, marker | 5, 6 |

---

### Task 1: Builder — sticky panel, sticky seam, panel-scoped error bar (CSS)

**Files:**
- Modify: `courses/static/courses/css/builder.css` (rule at `:10`, media block at `:2`, seam rule at `:88`)
- Test: `tests/test_e2e_builder_tree_layout.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `.builder__panel` is a sticky, internally-scrolling grid item above 720px; `.builder__panel .panel__seam` is sticky-bottom; `.builder__panel > .op-error` is sticky-top and opaque. Task 2 relies on the panel being a scroll container.

**Context you need:** `builder.css:1` is `.builder { display: grid; grid-template-columns: 2fr 1fr; … }`. Line 2 is the file's ONLY media query. Line 10 is `.builder__panel { min-width: 0; }` — that declaration is load-bearing (it stops the 1fr track ballooning; bug fixed in `96c0905`/`2a85e2a`) and **must survive**. `.op-error` is styled only in `editor.css:5`, which the builder page does not load.

- [ ] **Step 1: Write the failing e2e**

Append to `tests/test_e2e_builder_tree_layout.py`:

```python
LONG_BODY = "<p>" + ("Filler paragraph to make this element list tall. " * 8) + "</p>"


def _seed_tall_course(slug):
    """A course whose tree overflows the viewport and whose first unit has enough
    elements that its panel overflows too."""
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    course = Course.objects.create(slug=slug, title="Tall Demo")
    first = None
    for i in range(40):
        unit = ContentNode.objects.create(
            course=course, kind="unit", unit_type="lesson", title=f"Unit {i + 1}"
        )
        if first is None:
            first = unit
    for _ in range(25):
        Element.objects.create(
            unit=first,
            content_object=TextElement.objects.create(body=LONG_BODY),
        )
    return course, first


@pytest.mark.django_db(transaction=True)
def test_panel_stays_reachable_on_a_long_tree(page, live_server):
    """Clicking a unit at the bottom of a long tree leaves both panel actions on screen."""
    _make_pa_user("pa_sticky")
    course, _first = _seed_tall_course("sticky-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_sticky")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")

    # Scroll to the very bottom of the page, then click the LAST unit in the tree.
    page.mouse.wheel(0, 20000)
    page.locator(".tree__title", has_text="Unit 40").first.click()
    page.locator(".panel__seam").wait_for(state="visible")

    vh = page.evaluate("() => window.innerHeight")
    for label in ("+ Add element", "Open editor"):
        box = page.locator(".builder__panel").get_by_text(label).first.bounding_box()
        assert box is not None, f"{label!r} has no box"
        assert 0 <= box["y"] and box["y"] + box["height"] <= vh, (
            f"{label!r} is outside the viewport (y={box['y']}, h={box['height']}, vh={vh})"
        )


@pytest.mark.django_db(transaction=True)
def test_tall_panel_keeps_actions_on_screen(page, live_server):
    """An element-heavy unit's panel scrolls internally; the seam stays pinned."""
    _make_pa_user("pa_tall")
    course, first = _seed_tall_course("tall-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_tall")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.locator(".tree__title", has_text="Unit 1").first.click()
    page.locator(".panel__seam").wait_for(state="visible")

    # The panel really is overflowing (otherwise this test proves nothing).
    overflow = page.locator(".builder__panel").evaluate(
        "el => el.scrollHeight - el.clientHeight"
    )
    assert overflow > 0, "panel is not overflowing; seed more elements"

    vh = page.evaluate("() => window.innerHeight")
    box = page.locator(".builder__panel").get_by_text("Open editor").first.bounding_box()
    assert box["y"] + box["height"] <= vh, "seam is below the fold on a tall panel"


@pytest.mark.django_db(transaction=True)
def test_panel_not_sticky_when_stacked(page, live_server):
    """At <=720px the columns stack: no sticky, and no nested scroll container."""
    _make_pa_user("pa_stack")
    course, _first = _seed_tall_course("stack-demo")

    page.set_viewport_size({"width": 600, "height": 800})
    _login(page, live_server, "pa_stack")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")

    style = page.locator(".builder__panel").evaluate(
        "el => { const s = getComputedStyle(el);"
        " return {pos: s.position, mh: s.maxHeight, ov: s.overflowY}; }"
    )
    assert style["pos"] == "static", f"expected static when stacked, got {style['pos']}"
    assert style["mh"] == "none", f"max-height must be reset when stacked, got {style['mh']}"
    assert style["ov"] == "visible", f"overflow must be reset when stacked, got {style['ov']}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```
uv run pytest tests/test_e2e_builder_tree_layout.py -m e2e -k "sticky or tall_panel or stacked" -v
```

Expected: all three FAIL. `test_panel_stays_reachable_on_a_long_tree` and `test_tall_panel_keeps_actions_on_screen` fail on the viewport assertion (the buttons are above/below the fold); `test_panel_not_sticky_when_stacked` fails on `max-height` (currently `none` — it passes today, so **confirm it goes red after Step 3 is written wrong**; see Step 5).

- [ ] **Step 3: Apply the CSS**

In `courses/static/courses/css/builder.css`, extend the existing rule at line 10 (keep `min-width: 0` and the comment above it):

```css
.builder__panel { min-width: 0;
  /* Sticky so the detail panel stays on screen while a long tree scrolls. Mirrors
     .unit-tree (courses.css:505). max-height is what un-stretches the grid item and
     creates the travel room; align-self:start is belt-and-braces for short panels.
     Two-value overflow: a non-visible overflow-y would force overflow-x to auto. */
  position: sticky; top: var(--space-4); align-self: start;
  max-height: calc(100vh - var(--space-8)); overflow: hidden auto; }

/* Stacked layout: reverse ALL of position/max-height/overflow, or the panel becomes a
   nested ~100vh scroll trap under the tree. MUST come after the rule above — media
   queries add no specificity, so an override placed in the line-2 block would lose. */
@media (max-width: 720px) {
  .builder__panel { position: static; max-height: none; overflow: visible; }
}
```

Extend the existing seam rule at line 88 (the seam holds *+ Add element* / *Open editor →* and sits AFTER the element list in `_unit_panel.html`, so without this a tall panel hides both):

```css
.builder__panel .panel__seam { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-5);
  /* Pinned to the bottom of the panel's scroll range. Containing block is the injected
     .panel wrapper, which spans the full panel content. Mirrors .unit-foot (courses.css:558). */
  position: sticky; bottom: 0; z-index: 1;
  background: var(--surface-default); padding-block: var(--space-2); }
```

Add the panel-scoped error bar (`.op-error` has no styling on this page — `editor.css` is not loaded here):

```css
/* Scoped to the panel: the page-level flash (builder.html:6) sits outside .builder and
   must NOT become sticky. The two network-error divs builder.js writes as panel content
   ARE direct children and are intentionally covered. */
.builder__panel > .op-error {
  position: sticky; top: 0; z-index: 2;
  padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3);
  background: var(--danger-subtle); border: 1px solid var(--danger);
  border-radius: var(--radius-sm); color: var(--text-primary); }
```

- [ ] **Step 4: Run the tests to verify they pass**

```
uv run pytest tests/test_e2e_builder_tree_layout.py -m e2e -v
```

Expected: PASS, including the pre-existing `test_builder_tree_layout` (it guards the 2:1 ratio and `min-width: 0` you just edited around).

- [ ] **Step 5: Prove the stacked test can fail**

Temporarily delete `max-height: none;` from the media block, re-run `-k stacked`, confirm FAIL, then restore it. A test that was green before your change proves nothing until you've seen it red.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check tests/test_e2e_builder_tree_layout.py
uv run ruff format --check tests/test_e2e_builder_tree_layout.py
git branch --show-current   # must be pipeline/long-course-navigation-ux
git add courses/static/courses/css/builder.css tests/test_e2e_builder_tree_layout.py
git commit -m "feat(builder): sticky detail panel + sticky seam so a long tree never hides the actions"
```

---

### Task 2: Builder — `setPanel()` chokepoint

**Files:**
- Modify: `courses/static/courses/js/builder.js` (lines 119, 122, 123, 164, 189, 190, 200, 203, 296)
- Create: `tests/test_builder_js_invariants.py`
- Test: `tests/test_e2e_builder_tree_layout.py`

**Interfaces:**
- Consumes: Task 1's scrolling panel.
- Produces: `setPanel(html)` — the single writer of panel content; resets `scrollTop` to 0 after every write.

**Context you need:** there are exactly nine `panel.innerHTML =` **assignments**, plus one **read** at line 10 (`var neutralPanel = panel.innerHTML;`) which stays. The easiest assignment to miss is `refreshPanel`'s early return at 119, before the fetch.

- [ ] **Step 1: Write the failing source-scan test**

Create `tests/test_builder_js_invariants.py`:

```python
"""Source-level invariants for builder.js.

The detail panel is a scroll container (builder.css). Every content swap must reset
scrollTop, or the next unit's panel opens scrolled part-way down. Rather than trust
nine call sites to each remember, all writes funnel through setPanel() — and this test
is what actually enforces that, since a grep in a spec is not run by CI.
"""

import re
from pathlib import Path

BUILDER_JS = (
    Path(__file__).resolve().parent.parent
    / "courses" / "static" / "courses" / "js" / "builder.js"
)

# `panel.innerHTML` followed by `=` but not `==`/`===`. The line-10 read
# (`var neutralPanel = panel.innerHTML;`) has no following `=`, so it is excluded
# naturally rather than special-cased.
ASSIGNMENT = re.compile(r"panel\.innerHTML\s*=(?!=)")


def test_exactly_one_panel_innerhtml_assignment():
    source = BUILDER_JS.read_text(encoding="utf-8")
    hits = ASSIGNMENT.findall(source)
    assert len(hits) == 1, (
        f"expected exactly 1 panel.innerHTML assignment (inside setPanel), found "
        f"{len(hits)}. Route every panel write through setPanel() so scrollTop resets."
    )


def test_setpanel_resets_scrolltop():
    source = BUILDER_JS.read_text(encoding="utf-8")
    assert "function setPanel(" in source, "setPanel() helper is missing"
    body = source.split("function setPanel(", 1)[1].split("\n  }", 1)[0]
    assert "scrollTop = 0" in body, "setPanel() must reset panel.scrollTop to 0"
```

- [ ] **Step 2: Run it to verify it fails**

```
uv run pytest tests/test_builder_js_invariants.py -v
```

Expected: FAIL — `expected exactly 1 panel.innerHTML assignment …, found 9`.

- [ ] **Step 3: Add the helper and route every site through it**

In `courses/static/courses/js/builder.js`, immediately after the `neutralPanel` line (line 10), add:

```js
  // Single writer for panel content. The panel is a scroll container (builder.css), so
  // every swap must reset scrollTop or the next node's panel opens mid-way down. Nine
  // call sites funnel through here; tests/test_builder_js_invariants.py enforces it.
  function setPanel(html) {
    panel.innerHTML = html;
    panel.scrollTop = 0;
  }
```

Then replace each assignment with a `setPanel(...)` call:

| Line | Before | After |
|---|---|---|
| 119 | `if (!url) { panel.innerHTML = ""; return; }` | `if (!url) { setPanel(""); return; }` |
| 122 | `.then(function (html) { panel.innerHTML = html; })` | `.then(function (html) { setPanel(html); })` |
| 123 | `.catch(function () { panel.innerHTML = ""; });` | `.catch(function () { setPanel(""); });` |
| 164 | `panel.innerHTML = neutralPanel;` | `setPanel(neutralPanel);` |
| 189 | `.then(function (html) { panel.innerHTML = html; })` | `.then(function (html) { setPanel(html); })` |
| 190 | `.catch(function () { panel.innerHTML = '<div class="op-error" role="alert">Network error — please reload.</div>'; });` | `.catch(function () { setPanel('<div class="op-error" role="alert">Network error — please reload.</div>'); });` |
| 200 | `panel.innerHTML = html;` | `setPanel(html);` |
| 203 | `.catch(function () { panel.innerHTML = '<div class="op-error" role="alert">Network error — please reload.</div>'; });` | `.catch(function () { setPanel('<div class="op-error" role="alert">Network error — please reload.</div>'); });` |
| 296 | `if (panel.querySelector("form[data-op]")) panel.innerHTML = "";` | `if (panel.querySelector("form[data-op]")) setPanel("");` |

Leave line 10's `var neutralPanel = panel.innerHTML;` untouched — it is a read.

- [ ] **Step 4: Run the source-scan test to verify it passes**

```
uv run pytest tests/test_builder_js_invariants.py -v
```

Expected: PASS (2 passed).

- [ ] **Step 5: Write the failing behavioural e2e**

Append to `tests/test_e2e_builder_tree_layout.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_panel_scroll_resets_between_units(page, live_server):
    """Selecting another unit opens its panel at the top, not mid-scroll."""
    _make_pa_user("pa_reset")
    course, _first = _seed_tall_course("reset-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_reset")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")

    # Open the element-heavy unit and scroll its panel down (real wheel over the panel).
    page.locator(".tree__title", has_text="Unit 1").first.click()
    page.locator(".panel__seam").wait_for(state="visible")
    panel = page.locator(".builder__panel")
    panel.hover()
    page.mouse.wheel(0, 2000)
    assert panel.evaluate("el => el.scrollTop") > 0, "panel did not scroll; seed more elements"

    # Select a different unit through the real tree control.
    page.locator(".tree__title", has_text="Unit 2").first.click()
    page.wait_for_function(
        "() => document.querySelector('.builder__panel').textContent.includes('Unit 2')"
    )
    assert panel.evaluate("el => el.scrollTop") == 0, (
        "new panel opened mid-scroll — every swap must go through setPanel()"
    )


@pytest.mark.django_db(transaction=True)
def test_notice_bar_is_visible_and_opaque_while_panel_scrolled(page, live_server):
    """A network notice raised while the panel is scrolled down stays on screen and legible.

    Trigger: abort the panel form's POST. NOT the 409 path — that also calls
    refreshPanel(), which now routes through setPanel() and resets scroll, replacing the
    innerHTML the bar was prepended into.
    """
    _make_pa_user("pa_notice")
    course, _first = _seed_tall_course("notice-demo")

    page.set_viewport_size({"width": 1280, "height": 700})
    _login(page, live_server, "pa_notice")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.locator(".tree__title", has_text="Unit 1").first.click()
    page.locator(".panel__seam").wait_for(state="visible")

    panel = page.locator(".builder__panel")
    panel.hover()
    page.mouse.wheel(0, 2000)

    page.route("**/manage/courses/**", lambda route: route.abort()
               if route.request.method == "POST" else route.continue_())
    panel.locator("form[data-op] button[type='submit']").first.click()

    bar = page.locator(".builder__panel > .op-error")
    bar.wait_for(state="visible")
    box = bar.bounding_box()
    vh = page.evaluate("() => window.innerHeight")
    assert 0 <= box["y"] <= vh, "notice bar is off screen while the panel is scrolled"
    bg = bar.evaluate("el => getComputedStyle(el).backgroundColor")
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"notice bar has no painted background ({bg}) — content will scroll under its text"
    )
```

- [ ] **Step 6: Run them, then the whole builder e2e file**

```
uv run pytest tests/test_e2e_builder_tree_layout.py -m e2e -v
```

Expected: PASS. If `test_panel_scroll_resets_between_units` passes before Step 3, your seed is not overflowing — increase the element count until it fails first.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check tests/
uv run ruff format --check tests/
git branch --show-current
git add courses/static/courses/js/builder.js tests/test_builder_js_invariants.py tests/test_e2e_builder_tree_layout.py
git commit -m "fix(builder): funnel every panel swap through setPanel() so the scroll position resets"
```

---

### Task 3: `_stamp_current_chain()` + `_top_level_part()` refactor

**Files:**
- Modify: `courses/rollups.py` (`_top_level_part` at `:682`, `build_unit_nav` at `:696`)
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: `build_outline(course, user)`'s tree of dicts (`node`, `children`, `is_unit`, `required_total`, `required_done`, `completed`).
- Produces:
  - `_stamp_current_chain(tree, current_pk) -> None` — sets `contains_current` on **every** dict: `True` for `current_pk` and its ancestors, `False` everywhere else. Mutates in place.
  - `_top_level_part(tree)` — new signature, no `current_pk`; returns the first root dict whose `contains_current` is `True`, else `None`. **Requires a stamped tree.**
  - Every dict in `build_unit_nav`'s returned `tree` carries `contains_current`. Task 4's template reads it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_unit_nav_render.py` (match the file's existing fixture/import idioms):

```python
@pytest.mark.django_db
def test_stamp_current_chain_marks_only_the_ancestor_chain():
    """contains_current is True on the current unit and its ancestors, False elsewhere.

    The key is always PRESENT (initialised False), never merely absent — so the
    template's {% if %} has one meaning and this test can assert `is False`.
    """
    from courses.rollups import _stamp_current_chain

    student = make_student()
    course = CourseFactory(owner=student)
    part_a = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    chap_a = ContentNodeFactory(course=course, kind="chapter", parent=part_a, unit_type=None)
    target = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a
    )
    sibling_chap = ContentNodeFactory(
        course=course, kind="chapter", parent=part_a, unit_type=None
    )
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=sibling_chap)
    part_b = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part_b)

    tree = build_outline(course, student)
    _stamp_current_chain(tree, target.pk)

    flags = {}

    def collect(items):
        for d in items:
            flags[d["node"].pk] = d["contains_current"]
            collect(d["children"])

    collect(tree)

    assert flags[target.pk] is True, "the current unit itself must be stamped"
    assert flags[chap_a.pk] is True, "the parent chapter must be stamped"
    assert flags[part_a.pk] is True, "the grandparent part must be stamped"
    assert flags[sibling_chap.pk] is False, "a sibling group must NOT be stamped"
    assert flags[part_b.pk] is False, "an unrelated branch must NOT be stamped"
    assert all(pk in flags for pk in (target.pk, chap_a.pk, part_a.pk)), "key must be present"


@pytest.mark.django_db
def test_top_level_part_still_returns_a_root_unit():
    """A depth-1 unit's root IS itself — build_unit_nav reads top["is_unit"] to
    suppress the part chip. The stamping pass must therefore stamp unit dicts too."""
    from courses.rollups import _stamp_current_chain
    from courses.rollups import _top_level_part

    student = make_student()
    course = CourseFactory(owner=student)
    root_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None
    )

    tree = build_outline(course, student)
    _stamp_current_chain(tree, root_unit.pk)
    top = _top_level_part(tree)

    assert top is not None
    assert top["node"].pk == root_unit.pk
    assert top["is_unit"] is True


@pytest.mark.django_db
def test_build_unit_nav_stamps_the_tree_it_returns():
    student = make_student()
    course = CourseFactory(owner=student)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part)

    nav = build_unit_nav(course, student, unit)

    assert nav["tree"][0]["contains_current"] is True
    assert nav["tree"][0]["children"][0]["contains_current"] is True
```

Note: reuse whatever student/course factory helpers `tests/test_unit_nav_render.py` already defines rather than inventing `make_student` if a different name is in use.

- [ ] **Step 2: Run to verify they fail**

```
uv run pytest tests/test_unit_nav_render.py -k "stamp or top_level_part" -v
```

Expected: FAIL with `ImportError: cannot import name '_stamp_current_chain'`.

- [ ] **Step 3: Implement**

In `courses/rollups.py`, replace `_top_level_part` (currently at `:682`) with:

```python
def _stamp_current_chain(tree, current_pk):
    """Set contains_current on EVERY dict in a build_outline tree.

    True for the node whose pk is current_pk and for every ancestor of it; False
    everywhere else. The key is always present so callers (and the template's
    {% if item.contains_current %}) never have to distinguish absent from False.

    Pure dict mutation over an already-materialised tree — no queries. Units are
    stamped too, which is what lets _top_level_part still return a root that IS the
    current unit (the depth-1 part-chip case).
    """

    def walk(d):
        hit = d["node"].pk == current_pk
        for child in d["children"]:
            if walk(child):
                hit = True
        d["contains_current"] = hit
        return hit

    for root in tree:
        walk(root)


def _top_level_part(tree):
    """The root dict whose subtree contains the current node, or None.

    REQUIRES a tree already stamped by _stamp_current_chain. If current_pk is itself a
    root, returns that root dict (its is_unit tells the caller it is a depth-1 unit with
    no enclosing part). Reads the flag directly, not via .get(), so an unstamped tree
    raises KeyError loudly instead of silently blanking part_progress.
    """
    for root in tree:
        if root["contains_current"]:
            return root
    return None
```

In `build_unit_nav`, insert the stamping call before the `_top_level_part` call and update the call site:

```python
    part_progress = None
    _stamp_current_chain(tree, current_node.pk)
    top = _top_level_part(tree)
```

- [ ] **Step 4: Run the new tests, then the whole file**

```
uv run pytest tests/test_unit_nav_render.py -v
```

Expected: PASS, including the pre-existing `test_unit_shell_part_chip_hidden_for_root_unit`.

- [ ] **Step 5: Pin the query baseline**

Capture the current count on master, then add the ratchet. Run on a clean checkout of `origin/master` (or reason from `build_outline`'s docstring: two queries, plus the view's own):

```
uv run pytest tests/test_unit_nav_render.py -k queries -v
```

Add to `tests/test_unit_nav_render.py`:

```python
@pytest.mark.django_db
def test_build_unit_nav_adds_no_queries(django_assert_num_queries):
    """Baseline measured on origin/master before this change: N queries.

    The stamping pass is pure dict mutation, so this number must not move. Measuring
    post-change and hard-coding the result would make this assertion incapable of
    detecting the regression it exists to catch.
    """
    student = make_student()
    course = CourseFactory(owner=student)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=part)

    with django_assert_num_queries(2):   # <- replace 2 with the measured master baseline
        build_unit_nav(course, student, unit)
```

Replace `2` with the number you actually measured, and replace `N` in the docstring to match. If the measured number differs, the baseline wins — do not adjust the code to fit a guess.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check courses/rollups.py tests/test_unit_nav_render.py
uv run ruff format --check courses/rollups.py tests/test_unit_nav_render.py
git branch --show-current
git add courses/rollups.py tests/test_unit_nav_render.py
git commit -m "feat(rollups): stamp contains_current on the current unit's ancestor chain"
```

---

### Task 4: `<details>` group markup, counter, and i18n

**Files:**
- Modify: `templates/courses/_unit_tree_node.html`
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: `item.contains_current`, `item.required_done`, `item.required_total` from Task 3.
- Produces: group nodes render as `<details class="unit-tree__group">` with `<summary class="unit-tree__head">`; new classes `.unit-tree__chevron`, `.unit-tree__grouptitle`, `.unit-tree__count`, `.unit-tree__groupcheck` for Task 5 to style.

**Context you need:** the partial is included by BOTH `_unit_tree.html` (rail) and `_unit_shell.html` (drawer), and recursively by itself. Only `item`, `course`, `current_pk` are in scope — `{{ done }}`/`{{ total }}` are NOT. A group with no children keeps today's plain-div shape.

- [ ] **Step 1: Write the failing render tests**

Append to `tests/test_unit_nav_render.py`:

```python
@pytest.mark.django_db
def test_group_renders_as_details_open_only_on_the_current_chain(client):
    student = make_student()
    course = CourseFactory(owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    chap_a = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None,
                                title="Current Chapter")
    target = ContentNodeFactory(course=course, kind="unit", unit_type="lesson",
                                parent=chap_a, title="Target Unit")
    chap_b = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None,
                                title="Other Chapter")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap_b)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{target.pk}/").content.decode()

    import re
    groups = re.findall(r'<details class="unit-tree__group"([^>]*)>', html)
    # Rail + drawer render the tree twice, so each chapter appears twice.
    assert sum("open" in g for g in groups) == 2, "only the current chapter should be open"
    assert sum("open" not in g for g in groups) == 2, "the other chapter should be shut"


@pytest.mark.django_db
def test_group_counter_renders_actual_numerals(client):
    """Assert the numerals, not just the class — a scoping slip renders a bare '/'."""
    student = make_student()
    course = CourseFactory(owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    chap = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None)
    units = [
        ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap)
        for _ in range(3)
    ]
    UnitProgress.objects.create(student=student, unit=units[0], completed=True)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{units[0].pk}/").content.decode()

    assert "1/3" in html, "counter must render real numerals from the rollup fields"
    assert "of 3 required units completed" in html, "a11y sentence missing"
    assert 'class="unit-tree__count" aria-hidden="true"' in html, (
        "visible ratio must be aria-hidden so it is not double-announced"
    )


@pytest.mark.django_db
def test_all_quiz_group_renders_no_counter_and_no_check(client):
    """required_total == 0 -> no counter, no tick (quizzes carry no required work)."""
    student = make_student()
    course = CourseFactory(owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    chap = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=chap)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{quiz.pk}/").content.decode()

    assert "unit-tree__count" not in html
    assert "unit-tree__groupcheck" not in html


@pytest.mark.django_db
def test_completed_group_renders_the_group_check(client):
    student = make_student()
    course = CourseFactory(owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    chap = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap)
    UnitProgress.objects.create(student=student, unit=unit, completed=True)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    import re
    summaries = re.findall(r"<summary.*?</summary>", html, re.S)
    assert summaries, "expected a group summary"
    assert any("unit-tree__groupcheck" in s for s in summaries), (
        "an n/n group gets its own trailing check class"
    )
    assert not any("unit-tree__check" in s for s in summaries), (
        "the group check must NOT reuse .unit-tree__check — that class resets "
        ".badge--done's margin-left:auto for a LEADING icon (courses.css:550-552); "
        "in the summary the check trails"
    )


@pytest.mark.django_db
def test_flat_course_renders_no_details(client):
    student = make_student()
    course = CourseFactory(owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    assert "unit-tree__group" not in html, "a flat course has no groups to fold"


@pytest.mark.django_db
def test_childless_group_keeps_the_plain_head_shape(client):
    """An empty disclosure would be a dead control, so childless groups don't get one."""
    student = make_student()
    course = CourseFactory(owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None,
                       title="Empty Chapter")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None)

    client.force_login(student)
    html = client.get(f"/courses/{course.slug}/u/{unit.pk}/").content.decode()

    assert '<div class="unit-tree__head"' in html, "childless group keeps the plain div"
```

- [ ] **Step 2: Run to verify they fail**

```
uv run pytest tests/test_unit_nav_render.py -k "group or details or counter or quiz or flat or childless" -v
```

Expected: FAIL — no `<details>` in the output.

- [ ] **Step 3: Rewrite the group branch of the template**

In `templates/courses/_unit_tree_node.html`, replace the `{% else %}` branch (currently lines 13-20) with:

```django
  {% else %}
    {% if item.children %}
      {# Native <details>: folding works with JS off, and keyboard + AT semantics come
         free. Server-set `open` on the current chain so the correct groups are open in
         the first painted frame (a JS pass would flash the folded tree). #}
      <details class="unit-tree__group"{% if item.contains_current %} open{% endif %}>
        <summary class="unit-tree__head">
          <svg class="icon unit-tree__chevron" aria-hidden="true" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>
          <span class="unit-tree__grouptitle" lang="{{ course.language }}">{{ item.node.title }}</span>
          {% if item.required_total %}
            <span class="unit-tree__count" aria-hidden="true">{{ item.required_done }}/{{ item.required_total }}</span>
            {% if item.required_done == item.required_total %}
              <span class="unit-tree__groupcheck badge badge--done" aria-hidden="true">✓</span>
            {% endif %}
            {# The visible ratio is aria-hidden; this sentence is what gets announced.
               Count-neutral on purpose — PL has three plural forms, so a count-bearing
               noun would need {% templatetag openblock %} plural {% templatetag closeblock %}, which would also change the msgid. #}
            <span class="visually-hidden">{% blocktrans with done=item.required_done total=item.required_total %}{{ done }} of {{ total }} required units completed{% endblocktrans %}</span>
          {% endif %}
        </summary>
        <ul class="unit-tree__children">
          {% for child in item.children %}{% include "courses/_unit_tree_node.html" with item=child course=course current_pk=current_pk %}{% endfor %}
        </ul>
      </details>
    {% else %}
      {# No children: an empty disclosure would be a dead control. The chevron-width
         spacer keeps this title's left edge aligned with the <details> shape's. #}
      <div class="unit-tree__head" lang="{{ course.language }}">
        <span class="unit-tree__chevron unit-tree__chevron--spacer" aria-hidden="true"></span>
        <span class="unit-tree__grouptitle">{{ item.node.title }}</span>
      </div>
    {% endif %}
  {% endif %}
```

The `{% templatetag %}` calls in that comment exist only so the comment can mention `{% plural %}` without Django parsing it — if you prefer, write the comment without naming the tag.

- [ ] **Step 4: Run the tests to verify they pass**

```
uv run pytest tests/test_unit_nav_render.py -v
```

Expected: PASS. If you get `TemplateSyntaxError: unable to format string returned by gettext`, your `blocktrans` **body** contains `%(done)s` — the body must use `{{ done }}`; `%(done)s` is only the extracted msgid form.

- [ ] **Step 5: Update both catalogs**

```
uv run python manage.py makemessages -l en -l pl
```

Confirm the new msgid appears as `"%(done)s of %(total)s required units completed"` in both `locale/en/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.po`. Fill in the Polish translation (count-neutral phrasing — do NOT add a plural branch). Remove any `#~` obsolete entries `makemessages` introduced, and clear stray `#, fuzzy` flags on entries you did not change.

```
uv run pytest tests/ -k i18n -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add templates/courses/_unit_tree_node.html locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po tests/test_unit_nav_render.py
git commit -m "feat(unit-tree): fold groups into <details>, current chain open, with progress counters"
```

---

### Task 5: Tree CSS + drawer focus trap

**Files:**
- Modify: `courses/static/courses/css/courses.css` (`:536-554`, especially `:540-542`)
- Modify: `courses/static/courses/js/unit_nav.js` (`focusable()` at `:59-63`)
- Test: `tests/test_e2e_unit_nav.py`

**Interfaces:**
- Consumes: Task 4's markup.
- Produces: styled summary rows; `focusable()` includes `summary`. Task 6 edits `centerActive()` in the same JS file.

**Context you need:** `.unit-tree__node--section > .unit-tree__head` and `--chapter > .unit-tree__head` (`courses.css:540-542`) are **direct-child** selectors. The interposed `<details>` breaks them and chapters silently lose their uppercase micro-type. `focusable()` already filters `el.offsetParent !== null`, so widening it with `summary` is sufficient — hidden links inside a folded group are excluded automatically.

- [ ] **Step 1: Write the failing e2e**

Add a grouped seed helper and tests to `tests/test_e2e_unit_nav.py`:

```python
def _seed_grouped_course(username, slug, num_chapters=6, units_per_chapter=8):
    """A course with several chapters, current unit in the MIDDLE chapter so both an
    earlier and a later sibling are observably shut."""
    from django.contrib.auth import get_user_model

    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    student = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)

    chapters, units = [], []
    for c in range(num_chapters):
        chapter = ContentNodeFactory(
            course=course, kind="chapter", parent=None, unit_type=None,
            title=f"Chapter {c + 1}",
        )
        chapters.append(chapter)
        for u in range(units_per_chapter):
            units.append(ContentNodeFactory(
                course=course, kind="unit", unit_type="lesson", parent=chapter,
                title=f"C{c + 1} Unit {u + 1}",
            ))
    middle = units[len(units) // 2]
    return course, chapters, units, middle


@pytest.mark.django_db(transaction=True)
def test_current_chapter_open_siblings_shut(browser, live_server):
    _make_student("e2e_fold")
    course, chapters, _units, middle = _seed_grouped_course("e2e_fold", "e2e-fold")

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_fold")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    open_titles = rail.locator("details[open] > summary .unit-tree__grouptitle").all_inner_texts()
    assert len(open_titles) == 1, f"exactly one chapter should be open, got {open_titles}"
    assert open_titles[0] == middle.parent.title

    shut = rail.locator("details:not([open])")
    assert shut.count() == len(chapters) - 1, "every other chapter should be shut"
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_clicking_a_folded_summary_reveals_its_units(browser, live_server):
    _make_student("e2e_reveal")
    course, chapters, _units, middle = _seed_grouped_course("e2e_reveal", "e2e-reveal")

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_reveal")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    first_unit_of_ch1 = rail.get_by_role("link", name="C1 Unit 1")
    assert not first_unit_of_ch1.is_visible(), "Chapter 1 should start folded"

    rail.locator("summary", has_text="Chapter 1").first.click()   # real click
    first_unit_of_ch1.wait_for(state="visible")
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_chapter_microtype_survives_the_details_nesting(browser, live_server):
    """The highest-risk change in 2A: the > child combinator stops matching once
    <details> is interposed, and chapters silently lose their uppercase micro-type.
    Baseline is the literal current value (courses.css:540-542), not 'same as today'."""
    _make_student("e2e_micro")
    course, _chapters, _units, middle = _seed_grouped_course("e2e_micro", "e2e-micro")
    from tests.factories import ContentNodeFactory
    ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None,
                       title="Empty Chapter")   # the childless shape

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_micro")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    for locator, shape in (
        (rail.locator("details > summary.unit-tree__head").first, "<details> shape"),
        (rail.locator("div.unit-tree__head").first, "childless shape"),
    ):
        style = locator.evaluate(
            "el => { const s = getComputedStyle(el);"
            " return {tt: s.textTransform, fs: s.fontSize}; }"
        )
        assert style["tt"] == "uppercase", f"{shape}: lost uppercase ({style['tt']})"
        # .64rem against the 16px root = 10.24px.
        assert abs(float(style["fs"].rstrip("px")) - 10.24) < 0.5, (
            f"{shape}: font-size drifted ({style['fs']})"
        )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_chevron_rotates_only_for_the_open_group(browser, live_server):
    """Both halves in one test so they cannot drift apart: a missing rule satisfies the
    negative assertion perfectly while shipping a chevron that never rotates."""
    _make_student("e2e_chev")
    course, _chapters, _units, middle = _seed_grouped_course("e2e_chev", "e2e-chev")

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_chev")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    open_t = rail.locator("details[open] > summary > .unit-tree__chevron").first.evaluate(
        "el => getComputedStyle(el).transform"
    )
    shut_t = rail.locator("details:not([open]) > summary > .unit-tree__chevron").first.evaluate(
        "el => getComputedStyle(el).transform"
    )
    assert open_t not in ("none", "matrix(1, 0, 0, 1, 0, 0)"), (
        f"open group's chevron does not rotate ({open_t})"
    )
    assert shut_t in ("none", "matrix(1, 0, 0, 1, 0, 0)"), (
        f"closed group's chevron is rotated ({shut_t}) — descendant selector leaked"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_drawer_focus_trap_holds_at_a_folded_summary(browser, live_server):
    """<summary> is natively tabbable but matches none of focusable()'s selectors, so
    without widening it, Tab from a trailing folded summary escapes the drawer."""
    _make_student("e2e_trap")
    course, _chapters, _units, middle = _seed_grouped_course("e2e_trap", "e2e-trap")

    ctx = browser.new_context(reduced_motion="reduce", viewport={"width": 480, "height": 800})
    page = ctx.new_page()
    _login(page, live_server, "e2e_trap")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    page.locator("[data-unit-drawer-open]").click()
    page.locator("[data-unit-drawer]").wait_for(state="visible")

    last_summary = page.locator("[data-unit-drawer] details:not([open]) > summary").last
    last_summary.focus()
    page.keyboard.press("Tab")

    inside = page.evaluate(
        "() => !!document.activeElement.closest('[data-unit-drawer]')"
    )
    assert inside, "Tab escaped the drawer from a folded summary — focusable() must include summary"
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_drawer_shows_the_current_chain_open(browser, live_server):
    """The drawer has its own container and centring path, so it gets its own coverage."""
    _make_student("e2e_drawer_fold")
    course, chapters, _units, middle = _seed_grouped_course("e2e_drawer_fold", "e2e-drawer-fold")

    ctx = browser.new_context(reduced_motion="reduce", viewport={"width": 480, "height": 800})
    page = ctx.new_page()
    _login(page, live_server, "e2e_drawer_fold")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    page.locator("[data-unit-drawer-open]").click()
    drawer = page.locator("[data-unit-drawer]")
    drawer.wait_for(state="visible")

    open_titles = drawer.locator("details[open] > summary .unit-tree__grouptitle").all_inner_texts()
    assert open_titles == [middle.parent.title]
    assert drawer.locator("details:not([open])").count() == len(chapters) - 1
    ctx.close()
```

- [ ] **Step 2: Run to verify they fail**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "fold or reveal or microtype or chevron or trap or drawer_shows" -v
```

Expected: the micro-type, chevron, and focus-trap tests FAIL (the folding ones may already pass from Task 4 — that is fine, they are regression cover).

- [ ] **Step 3: Fix the child-combinator break and style the summary**

In `courses/static/courses/css/courses.css`, replace the rule at `:540-542` so **both** DOM shapes match. Do NOT drop the `>` — a descendant selector would also match a section's head nested inside a chapter, permanently removing the ability to differentiate them:

The rule today (`courses.css:540-542`) is:

```css
.unit-tree__node--section > .unit-tree__head,
.unit-tree__node--chapter > .unit-tree__head { font-size: .64rem; font-weight: 700;
  letter-spacing: .05em; text-transform: uppercase; color: var(--text-tertiary); }
```

Replace it with — same declarations, four selectors:

```css
.unit-tree__node--section > .unit-tree__head,
.unit-tree__node--section > .unit-tree__group > .unit-tree__head,
.unit-tree__node--chapter > .unit-tree__head,
.unit-tree__node--chapter > .unit-tree__group > .unit-tree__head { font-size: .64rem; font-weight: 700;
  letter-spacing: .05em; text-transform: uppercase; color: var(--text-tertiary); }
```

Then add the new summary/group styling near the other `.unit-tree__*` rules:

```css
/* Group summary: flex row of chevron / title / counter / check. display:flex also drops
   the default list-item box; list-style + ::-webkit-details-marker kill the native
   triangle in favour of our own chevron. */
.unit-tree__head { display: flex; align-items: center; gap: .35rem; }
summary.unit-tree__head { cursor: pointer; list-style: none; }
summary.unit-tree__head::-webkit-details-marker { display: none; }
summary.unit-tree__head:hover { background: var(--surface-raised); color: var(--text-primary); }
summary.unit-tree__head:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }

/* Title may wrap to TWO lines (unlike unit rows): a chapter title is a landmark, and
   truncating it to "Introduction to…" in a 14rem rail defeats the purpose. */
.unit-tree__grouptitle { flex: 1; min-width: 0; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }

.unit-tree__chevron { flex: none; width: .75rem; height: .75rem;
  transition: transform 120ms ease; }
.unit-tree__chevron--spacer { visibility: hidden; }   /* keeps childless titles aligned */
/* Direct-child chain, NOT `details[open] .unit-tree__chevron`: the tree is recursive, so
   a CLOSED section sits inside an OPEN chapter and a descendant selector would paint it
   open too. */
.unit-tree__group[open] > .unit-tree__head > .unit-tree__chevron { transform: rotate(90deg); }
@media (prefers-reduced-motion: reduce) { .unit-tree__chevron { transition: none; } }

.unit-tree__count { flex: none; font-size: .64rem; color: var(--text-tertiary); }
/* Its OWN class, not .unit-tree__check: that one resets .badge--done's margin-left:auto
   because in a unit row the tick is a LEADING icon (courses.css:550-552). Here it trails. */
.unit-tree__groupcheck { flex: none; font-size: .72rem; }
```

- [ ] **Step 4: Widen the drawer's focus trap**

In `courses/static/courses/js/unit_nav.js`, change `focusable()`'s selector:

```js
    function focusable() {
      return Array.prototype.slice.call(
        // `summary` is natively tabbable but matches none of the other selectors, so
        // without it a trailing folded group's summary sits in the tab order yet outside
        // the trap's items list — and Tab escapes the drawer. The offsetParent filter
        // below already excludes links hidden inside a folded group.
        panel.querySelectorAll('a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')
      ).filter(function (el) { return el.offsetParent !== null; });
    }
```

Then update the in-test focusable list in `tests/test_e2e_unit_nav.py`'s `test_mobile_drawer_focus_trap` to match — it re-implements the same selector, so leaving it stale would let it pass while the trap leaks.

- [ ] **Step 5: Run the design pass and verify visually**

Invoke the `frontend-design` skill for the concrete values of `.unit-tree__chevron`, `.unit-tree__count`, and `.unit-tree__groupcheck` within the constraints above. Then capture Playwright screenshots in **light and dark**, for the **rail and the drawer**, including a pinned worst-case row (a depth-3 section, a 60-character title, and a `12/12 ✓` chip) and a childless group in the same shot. Confirm the worst-case title is still readable at 14rem; if it is not, widening the rail is the sanctioned fallback — make that call explicitly.

- [ ] **Step 6: Run the whole nav e2e file**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -v
```

Expected: PASS, including all five pre-existing tests (their scroll arithmetic and locators now see the extra summary row — any breakage there is a real signal, not a fixture to paper over).

- [ ] **Step 7: Commit**

```bash
uv run ruff check tests/test_e2e_unit_nav.py
uv run ruff format --check tests/test_e2e_unit_nav.py
git branch --show-current
git add courses/static/courses/css/courses.css courses/static/courses/js/unit_nav.js tests/test_e2e_unit_nav.py
git commit -m "feat(unit-tree): style folding groups; keep chapter micro-type; hold the drawer focus trap"
```

---

### Task 6: `centerActive()` + a louder active marker

**Files:**
- Modify: `courses/static/courses/js/unit_nav.js` (toggle handler `:21-25`, centring block `:35-46`)
- Modify: `courses/static/courses/css/courses.css` (`.unit-tree__unit.is-active` at `:548-549`)
- Test: `tests/test_e2e_unit_nav.py`

**Interfaces:**
- Consumes: Task 5's `focusable()` change in the same file — rebase cleanly, don't clobber it.
- Produces: `centerActive()` — no arguments, owns its own lookups and guards.

**Context you need:** `.is-active` ALREADY ships `font-weight: 600` and `border-left: 2px solid var(--primary)`. The remaining work is that this is too quiet *at scale* — every inactive row already carries `border-left: 1px solid var(--border-subtle)`, so the active row differs by one pixel of border and one weight step. Widening the border changes the row's box, so it must be made width-neutral.

- [ ] **Step 1: Write the failing e2e**

Append to `tests/test_e2e_unit_nav.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_expanding_the_rail_recentres_the_active_unit(browser, live_server):
    """The bug: centring ran only on load and only when not collapsed, so expanding a
    collapsed rail left the student at scroll-top with the active unit far away."""
    _make_student("e2e_recentre")
    course, _chapters, _units, middle = _seed_grouped_course("e2e_recentre", "e2e-recentre")

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_recentre")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    toggle = page.locator("[data-unit-tree-toggle]")
    toggle.click()                                   # collapse (real gesture)
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    toggle.click()                                   # expand
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('unit-tree-collapsed')"
    )

    # Poll: centerActive() may animate. Assert the active row sits inside the rail's
    # visible band, not merely that scrollTop moved.
    page.wait_for_function(
        """() => {
             const rail = document.querySelector('[data-unit-tree]');
             const act = rail && rail.querySelector('.unit-tree__unit.is-active');
             if (!act) return false;
             const r = act.getBoundingClientRect(), t = rail.getBoundingClientRect();
             return r.top >= t.top && r.bottom <= t.bottom;
           }""",
        timeout=5000,
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_active_marker_is_strong_and_width_neutral(browser, live_server):
    _make_student("e2e_marker")
    course, _chapters, _units, middle = _seed_grouped_course("e2e_marker", "e2e-marker")

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_marker")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    active = rail.locator(".unit-tree__unit.is-active").first
    inactive = rail.locator(".unit-tree__unit:not(.is-active)").first

    assert active.evaluate("el => getComputedStyle(el).fontWeight") == "700"

    # Width-neutral: the active row's text starts at the same x as its siblings'.
    ax = active.locator(".unit-tree__label").bounding_box()["x"]
    ix = inactive.locator(".unit-tree__label").bounding_box()["x"]
    assert abs(ax - ix) < 1.0, (
        f"active row's text jogged by {ax - ix:.1f}px — widen the bar without changing "
        f"the box (inset box-shadow or ::before), or compensate padding-left"
    )

    # Focus ring is present and distinct from the accent bar.
    active.focus()
    ring = active.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return {w: s.outlineWidth, c: s.outlineColor}; }"
    )
    assert ring["w"] not in ("0px", ""), "no focus-visible ring on the active row"
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_done_and_active_row_keeps_the_active_colour(browser, live_server):
    """A completed current unit must not render in .is-done's faint --text-tertiary —
    it is the one row the student most needs to find."""
    _make_student("e2e_doneactive")
    course, _chapters, _units, middle = _seed_grouped_course("e2e_doneactive", "e2e-doneactive")
    from courses.models import UnitProgress
    from django.contrib.auth import get_user_model
    student = get_user_model().objects.get(username="e2e_doneactive")
    UnitProgress.objects.create(student=student, unit=middle, completed=True)

    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    _login(page, live_server, "e2e_doneactive")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{middle.pk}/")

    rail = page.locator("[data-unit-tree]")
    active = rail.locator(".unit-tree__unit.is-active").first
    assert "is-done" in (active.get_attribute("class") or ""), "seed did not mark it done"

    active_colour = active.evaluate("el => getComputedStyle(el).color")
    done_only = rail.locator(".unit-tree__unit.is-done:not(.is-active)").first
    if done_only.count():
        assert active_colour != done_only.evaluate("el => getComputedStyle(el).color"), (
            "done+active resolves to the faint done colour — .is-active must win"
        )
    ctx.close()
```

- [ ] **Step 2: Run to verify they fail**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "recentre or marker or doneactive" -v
```

Expected: FAIL — `fontWeight` is `600`, and the re-centre poll times out.

- [ ] **Step 3: Extract `centerActive()`**

In `courses/static/courses/js/unit_nav.js`, replace the block at `:35-46` with a named function, and keep the arithmetic verbatim (`scrollIntoView` is deliberately avoided — it walks every scrollable ancestor and would nudge the window and the article):

```js
  // Centre the active unit within the rail. Self-contained: re-queries at CALL time
  // (never a stale module-eval reference) and owns its own guards, so both call sites
  // are unconditional one-liners.
  function centerActive() {
    var tree = document.querySelector("[data-unit-tree]");
    if (!tree || isCollapsed()) return;
    // Scope the lookup to the rail: the mobile drawer renders a SECOND .is-active node.
    var active = tree.querySelector(".unit-tree__unit.is-active");
    if (!active) return;
    // No layout box => the student folded the group holding it. Bail: the arithmetic
    // below would compute a large negative target and scrollTo would clamp it to 0,
    // silently yanking the rail to the top.
    if (active.offsetParent === null) return;

    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // getBoundingClientRect().top is the border-box outer edge; clientTop reconciles it
    // with scrollTop's padding-box origin. scrollTo clamps out-of-range targets.
    var delta = active.getBoundingClientRect().top - tree.getBoundingClientRect().top;
    var target = tree.scrollTop + delta - tree.clientTop - (tree.clientHeight - active.offsetHeight) / 2;
    tree.scrollTo({ top: target, behavior: reduce ? "auto" : "smooth" });
  }

  centerActive();   // on load
```

Place `centerActive()`'s definition ABOVE the toggle-handler block so the load-time call and the handler both see it.

**On the `offsetParent` guard's test:** the spec forbids the obvious e2e for it — "fold the active group, collapse → expand, assert `scrollTop` unchanged" is **vacuous**, because collapsing applies `html.unit-tree-collapsed .unit-tree__list { display: none }` (`courses.css:642`), which clamps `scrollTop` to 0 in *both* implementations. It can never go red. Ship the guard as documented defensive code (the comment above is that documentation) unless you can spy `tree.scrollTo` from a JS-level test; do not write a green-but-meaningless e2e for it. In the toggle's click handler (`:21-25`), add the expand-branch call:

```js
    toggle.addEventListener("click", function () {
      var collapsed = html.classList.toggle("unit-tree-collapsed");
      store(collapsed ? "1" : "0");
      syncToggle(collapsed);
      // Expanding restores the labels — re-centre, or the student lands at scroll-top
      // with the active unit an arbitrary distance away. Nothing to centre when collapsing.
      if (!collapsed) centerActive();
    });
```

- [ ] **Step 4: Strengthen the active marker**

In `courses/static/courses/css/courses.css`, replace `.unit-tree__unit.is-active` (`:548-549`). Use an inset `box-shadow` so **no layout box changes** — a 1px→4px border would jog the row's text right relative to every sibling:

```css
/* Placed AFTER .is-done so a completed current unit keeps the accent colour: it is the
   one row the student most needs to find, and .is-done's --text-tertiary would render
   it faintest of all. */
.unit-tree__unit.is-active { background: var(--primary-subtle); color: var(--primary);
  font-weight: 700;
  /* Inset shadow, not a wider border: width-neutral, so the text still aligns with the
     1px-bordered inactive rows. */
  border-left-color: transparent;
  box-shadow: inset 3px 0 0 0 var(--primary); }
.unit-tree__unit.is-active:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
```

Verify `.is-active` appears **after** `.is-done` in source order; if not, move it.

- [ ] **Step 5: Run the tests**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -v
```

Expected: PASS, all tests in the file.

- [ ] **Step 6: Design pass and screenshots**

Invoke the `frontend-design` skill for the final marker treatment within those constraints, then capture light + dark screenshots of the rail and the drawer. Judge "the focus ring does not double up into a muddy ring with the accent bar" here — that is a human call, deliberately not an assertion.

- [ ] **Step 7: Full suite and commit**

```bash
uv run pytest tests/ -m "not e2e" -q
uv run ruff check .
uv run ruff format --check .
git branch --show-current
git add courses/static/courses/js/unit_nav.js courses/static/courses/css/courses.css tests/test_e2e_unit_nav.py
git commit -m "fix(unit-tree): re-centre the active unit on expand; strengthen the active marker"
```

---

## Verification checklist (before opening the PR)

- [ ] `uv run pytest tests/ -m "not e2e" -q` — green
- [ ] `uv run pytest tests/test_e2e_unit_nav.py tests/test_e2e_builder_tree_layout.py -m e2e -v` — green, run **foreground**
- [ ] `uv run ruff check .` and `uv run ruff format --check .` — clean
- [ ] Every new test was observed RED before its implementation
- [ ] Screenshots reviewed: light + dark, rail + drawer, worst-case summary row, childless group, content-heavy builder panel
- [ ] Both `.po` catalogs updated, no `#~` obsolete entries, no stray fuzzy flags
- [ ] Any committed help screenshot under `core/static/core/img/help/` that depicts the unit tree has been regenerated
- [ ] Six commits, in order: builder CSS → setPanel → rollups → template+i18n → tree CSS+trap → centerActive+marker
