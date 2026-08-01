# Pinned TOC Toggle for the Student Unit Tree — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the collapsed course-tree's 2.4rem sliver with a pinned TOC icon that removes the rail entirely, and let the unit reclaim the freed width while prose stays capped at the repo's existing 46rem measure.

**Architecture:** Presentation-only. The existing state hook (`html.unit-tree-collapsed`), its `localStorage` key and its pre-paint script in `base.html` are reused unchanged. One new server-rendered `<button>` joins `.unit-shell`; four CSS blocks replace one; `unit_nav.js` grows from binding one control to iterating two. No Python, no models, no migrations, no views.

**Tech Stack:** Django templates, hand-written CSS (`courses.css`), vanilla JS IIFE (`unit_nav.js`), pytest + Playwright, Django i18n (`pl`/`en`).

**Spec:** `docs/superpowers/specs/2026-08-01-unit-tree-toc-pin-design.md` — read it before starting. It carries the derivations behind every constant below; this plan carries the constants.

## Global Constraints

- **Every new CSS rule lands in `courses/static/courses/css/courses.css`.** Not `app.css`. Task 2's source guard reads `courses.css` only; a rule elsewhere is unguarded and silent.
- **Every new selector containing `html.unit-tree-collapsed` must also contain `[data-unit-shell]`.** Unscoped, it leaks onto every page extending `base.html`, including the teacher review page.
- **The lane is exactly `2.4rem` (38.4px).** The `-2.4rem` overhang, the 1040px breakpoint, the 920px column figure and Tasks 4/5's assertions all depend on it. Do not change it.
- **The prose cap is exactly `46rem`** — the value in the shared `.quiz, .lesson { max-width: 46rem; margin-inline: auto; }` rule at `courses.css:180-181`. There is no lone `.lesson { … }` rule to look for.
- **The breakpoints are `641px` and `1040px`**, written exactly.
- Tools are not on PATH: prefix every command with `uv run`.
- e2e tests are excluded by default (`pyproject.toml:49` sets `addopts = "-q -m 'not e2e'"`). Running them **requires `-m e2e`** or they silently deselect and exit 5.
- Never hardcode a test password; import `TEST_PASSWORD` from `tests.factories`.
- Prose in comments and docstrings is scanned by source-level tests. Keep `courses.css` comments free of literal selector text that a guard might match.

---

### Task 1: Markup — the pin button, the `id`, and both `aria-controls`

**Files:**
- Modify: `templates/courses/_unit_shell.html:2-3`
- Modify: `templates/courses/_unit_tree.html:2`, `:5-8`
- Test: `tests/test_unit_nav_render.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `[data-unit-tree-pin]` (the pin button, bound by Task 3), `id="unit-tree"` on `<nav class="unit-tree">`, and the class name `.unit-toc-pin` (styled by Task 2).

- [ ] **Step 1: Write the failing render test**

Append to `tests/test_unit_nav_render.py`:

```python
@pytest.mark.django_db
def test_toc_pin_renders_on_lesson_and_quiz_with_a_unique_aria_controls_target(client):
    """The pin ships in the DOM server-rendered, not created by JS.

    base.html's pre-paint script sets html.unit-tree-collapsed BEFORE first
    paint, so a CSS-only reveal is flash-free; a JS-created button would pop in
    after hydration. Its aria-controls target must exist exactly once.
    """
    student = make_verified_user(
        username="pin_render", email="pin_render@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug="pin-render", owner=student)
    EnrollmentFactory(course=course, student=student)
    lesson = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    quiz = make_quiz_unit(course=course)
    client.force_login(student)

    for node in (lesson, quiz):
        url = reverse(
            "courses:lesson_unit" if node is lesson else "courses:quiz_unit",
            kwargs={"slug": course.slug, "node_pk": node.pk},
        )
        soup = BeautifulSoup(client.get(url, follow=True).content, "html.parser")

        pin = soup.select_one("[data-unit-tree-pin]")
        assert pin is not None, f"the TOC pin is missing from {url}"
        assert pin.get("aria-expanded") is not None, "the pin must ship aria-expanded"
        assert pin.get("aria-controls") == "unit-tree"

        targets = soup.select("#unit-tree")
        assert len(targets) == 1, (
            f"aria-controls must resolve to exactly one element, found {len(targets)}"
        )

        rail_toggle = soup.select_one("[data-unit-tree-toggle]")
        assert rail_toggle.get("aria-controls") == "unit-tree", (
            "both controls must describe the same disclosure relationship"
        )

        pins = soup.select("[data-unit-tree-pin]")
        assert len(pins) == 1, "the pin must not share a selector with the rail toggle"
```

- [ ] **Step 2: Run it to verify it fails**

```
uv run pytest tests/test_unit_nav_render.py::test_toc_pin_renders_on_lesson_and_quiz_with_a_unique_aria_controls_target -v --verbosity=0
```

Expected: FAIL — `AssertionError: the TOC pin is missing from /courses/pin-render/u/<pk>/`

- [ ] **Step 3: Add the pin to the shell**

In `templates/courses/_unit_shell.html`, replace lines 2-3:

```django
<div class="unit-shell" data-unit-shell>
  {% include "courses/_unit_tree.html" %}
```

with:

```django
<div class="unit-shell" data-unit-shell>
  {% comment %}FIRST child of the shell, before the tree, so it leads the tab order
     within the shell when visible. That ordering is a rationale, not a guarantee —
     no test exercises keyboard traversal into the shell, so a future reorder of
     these children would go green. Server-rendered rather than JS-created: base.html's pre-paint has
     already set html.unit-tree-collapsed, so the CSS-only reveal is flash-free.
     Its OWN attribute, never a second [data-unit-tree-toggle] — two elements sharing
     that attribute would break querySelector in unit_nav.js and make every existing
     Playwright locator a strict-mode violation.{% endcomment %}
  <button type="button" class="unit-toc-pin" data-unit-tree-pin
          aria-controls="unit-tree" aria-expanded="false"
          aria-label="{% trans 'Show course contents' %}"
          title="{% trans 'Show course contents' %}">
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="4" cy="6" r="1.6" fill="currentColor" stroke="none"/><path d="M9 6h11"/>
      <circle cx="4" cy="12" r="1.6" fill="currentColor" stroke="none"/><path d="M9 12h11"/>
      <circle cx="4" cy="18" r="1.6" fill="currentColor" stroke="none"/><path d="M9 18h11"/>
    </svg>
  </button>
  {% include "courses/_unit_tree.html" %}
```

A table-of-contents mark — three rules each led by a dot — deliberately **not** `☰`, which already means "primary menu" in the app header and "open the mobile drawer" in the unit footer.

- [ ] **Step 4: Add the id and aria-controls to the rail**

In `templates/courses/_unit_tree.html`, line 2, add `id="unit-tree"`:

```django
<nav class="unit-tree" id="unit-tree" aria-label="{% trans 'Course contents' %}" data-unit-tree>
```

Then on line 5, add `aria-controls="unit-tree"` to the existing toggle, leaving its `data-label-*` attributes untouched:

```django
    <button type="button" class="unit-tree__toggle" data-unit-tree-toggle
            aria-controls="unit-tree"
            aria-label="{% trans 'Collapse contents' %}" aria-expanded="true"
            data-label-collapse="{% trans 'Collapse contents' %}"
            data-label-expand="{% trans 'Expand contents' %}">‹</button>
```

- [ ] **Step 5: Run the test to verify it passes**

```
uv run pytest tests/test_unit_nav_render.py tests/test_tags_consumption.py tests/test_courses_views.py tests/test_review_roster.py --verbosity=0
```

Expected: all PASS. The extra three modules are not padding — `_unit_shell.html` is a shared partial,
and `tests/test_tags_consumption.py:142` indexes the literal `'<div class="unit-shell"'` and asserts
a strict ordering around it, while the other two assert on shell markup. Verifying only the render
module would let a structural break surface eight commits later.

- [ ] **Step 6: Falsify it**

Temporarily delete the `<button class="unit-toc-pin" …>` block from `_unit_shell.html`, re-run — it MUST fail. Restore it. A test that cannot be made to fail is not coverage.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/_unit_shell.html templates/courses/_unit_tree.html tests/test_unit_nav_render.py
git commit -m "feat(unit-nav): add the TOC pin button and its aria-controls target"
```

---

### Task 2: CSS — delete the sliver, add the four scoped blocks, guard both at source

**Files:**
- Modify: `courses/static/courses/css/courses.css:866-873` (delete and replace in place)
- Test: `tests/test_consumption_css.py`

**Interfaces:**
- Consumes: `.unit-toc-pin` and `[data-unit-shell]` from Task 1.
- Produces: the collapsed-state presentation. Task 3's focus moves depend on each control being `display: none` in exactly one state.

- [ ] **Step 1: Write the failing source guard**

Append to `tests/test_consumption_css.py`:

```python
def test_collapsed_rail_rules_are_deleted_and_every_new_rule_is_scoped():
    """Two source-level guards over COMMENT-STRIPPED courses.css.

    Stripping is mandatory, and the reason is braces, not prose: nine comments in
    this file carry a `{` or `}`, and the recipe below splits the whole file on
    `}`. Left unstripped, those braces desynchronise the chunking and can absorb
    a real prelude, silently dropping selectors from the coverage count.

    This test carries more weight than a typical source guard. It is the only
    guard that the prose-cap selectors are SCOPED to [data-unit-shell] (the
    teacher review page renders none of the thirteen capped selectors, so no
    behavioural test there can falsify a widened one), and the only guard for the
    deletion at all (display:none removes the rail's box, so leftover rules are
    behaviourally invisible).

    Note the narrower claim: Task 6 DOES give behavioural coverage that four of
    the thirteen entries cap at 46rem. Do not delete those assertions believing
    this test subsumes them, and do not weaken this test believing it carries
    more than scoping.
    """
    import re

    css = CSS.read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    # (a) The old sliver rules are gone. The pattern is deliberately LOOSE: four
    # of the five deleted selectors were .unit-tree__heading / __list / __toggle
    # / __bar, and they are caught only because `.unit-tree` is a prefix of each.
    # Anchoring on a following `,` or `{` would catch one and let four ship green.
    assert not re.search(r"html\.unit-tree-collapsed\s+\.unit-tree", stripped), (
        "the old unscoped sliver rules are still present; courses.css:866-873 must "
        "be deleted in full. The new form is "
        "`html.unit-tree-collapsed [data-unit-shell] > .unit-tree`, which does not "
        "match this pattern."
    )

    # (b) Every new collapsed rule is scoped, checked PER INDIVIDUAL SELECTOR.
    # rsplit is mandatory: every new rule lives inside an @media block, and the
    # first rule after `@media ... {` fuses with the at-rule prelude when the file
    # is split on `}`. A naive `split("{")[0]` yields "@media (min-width: 641px) ",
    # which contains no `html.unit-tree-collapsed`, so the check is skipped -- and
    # since the prose-cap rule is the only rule in its block, the entire
    # thirteen-selector list would go unexamined.
    examined = 0
    for chunk in stripped.split("}"):
        if "{" not in chunk:
            continue
        prelude = chunk.rsplit("{", 1)[0]
        for selector in prelude.split(","):
            if "html.unit-tree-collapsed" not in selector:
                continue
            examined += 1
            assert "[data-unit-shell]" in selector, (
                f"collapsed-state selector is not scoped to the student shell: "
                f"{selector.strip()!r}. html.unit-tree-collapsed is set by "
                f"base.html on EVERY page from one global localStorage key, and "
                f"review_submission.html reuses the .unit-shell class -- an "
                f"unscoped rule deforms the teacher review page."
            )

    # Coverage floor, so a tokenisation bug fails loudly instead of passing
    # vacuously. 4 structural (rail reveal, pin reveal, margin, print) + one per
    # allow-list entry (13) = 17. The operator is >=, so ADDING an allow-list
    # entry never reddens the suite; re-derive this number only on a removal.
    assert examined >= 17, (
        f"only {examined} collapsed-state selectors were examined, expected >= 17. "
        f"The tokenisation is broken -- a naive prelude split yields 1."
    )
```

- [ ] **Step 2: Run it to verify it fails**

```
uv run pytest tests/test_consumption_css.py::test_collapsed_rail_rules_are_deleted_and_every_new_rule_is_scoped -v --verbosity=0
```

Expected: FAIL on assertion (a) — the sliver rules are still present.

- [ ] **Step 3: Replace `courses.css:866-873` in place**

Delete these eight lines **in full** — the comment at `:866`, the `@media` wrapper at `:867`, the rules at `:868-872`, and the closing brace at `:873`:

```css
/* Collapsed desktop rail — state lives on <html> (pre-paint script), so scope from it. */
@media (min-width: 641px) {
  html.unit-tree-collapsed .unit-tree { flex-basis: 2.4rem; }
  html.unit-tree-collapsed .unit-tree__heading,
  html.unit-tree-collapsed .unit-tree__list { display: none; }
  html.unit-tree-collapsed .unit-tree__toggle { transform: scaleX(-1); }  /* ‹ → › */
  html.unit-tree-collapsed .unit-tree__bar { justify-content: center; padding: .55rem .35rem; }
}
```

Line `:871` carries a trailing `  /* ‹ → › */` — reproduced above so the block matches byte-for-byte
if used as an Edit anchor. If your editor normalises it, delete by line range `866-873` instead.

Replace with:

```css
/* Collapsed desktop rail. State lives on <html> (base.html pre-paint), which is
   GLOBAL to every page — so every rule below is additionally scoped to
   [data-unit-shell], present only on the student unit shell. */
.unit-toc-pin { display: none; }

@media (min-width: 641px) {
  html.unit-tree-collapsed [data-unit-shell] > .unit-tree { display: none; }
  /* min-height squares the button: flex-basis fixes only the MAIN size, and the
     icon is 1em on a 16px font, giving a ~38x20 control under the 24x24 minimum.
     The container's align-items: flex-start is load-bearing — under the flex
     default (stretch) the pin would fill the shell's height and sticky would have
     no room to move. gap: 0 on the shell is what makes the lane abut the column.
     z-index 21 is one above .unit-foot's 20 — the footer is inside
     .unit-shell__main, which sets no z-index and so creates no stacking context,
     leaving the footer competing in the ROOT context. The two are horizontally
     disjoint today, so this only matters if future full-bleed or negative-margin
     content appears in the column. Task 9 may not change it. */
  html.unit-tree-collapsed [data-unit-shell] > .unit-toc-pin {
    display: flex; align-items: center; justify-content: center;
    flex: 0 0 2.4rem; min-height: 2.4rem;
    position: sticky; top: .6rem; z-index: 21;
  }
}

/* `screen and` is required. Chromium evaluates print media queries against the
   page area, ~1046 CSS px for landscape A4 at default margins — above 1040.
   Unscoped, a landscape printout would apply the overhang while the print block
   below correctly hides the pin, indenting the article past an empty lane.
   Safe HERE because this block holds only the margin rule; it would NOT be safe
   on the 641px block, which also hides the rail and would print the full rail. */
@media screen and (min-width: 1040px) {
  html.unit-tree-collapsed [data-unit-shell] { margin-inline-start: -2.4rem; }
}

/* A navigation affordance is noise on paper. The selector MIRRORS the reveal and
   this block MUST stay after it: a bare `.unit-toc-pin { display: none }` here is
   (0,1,0) against the reveal's (0,3,1), and media queries add no specificity, so
   the reveal would win and the pin would print anyway. */
@media print {
  html.unit-tree-collapsed [data-unit-shell] > .unit-toc-pin { display: none; }
}
```

- [ ] **Step 4: Add the prose-cap block**

Immediately after the block above, add:

```css
/* Prose cap. 46rem is the value in the shared `.quiz, .lesson` rule near the top
   of this file, reintroduced at element level in the collapsed
   state only. An allow-list, NOT cap-by-default: element root classes are
   heterogeneous, and a missed opt-out BREAKS layout (a squeezed table) whereas a
   missed allow-list entry only leaves prose wide. Left alignment needs no
   declaration — the global `* { margin: 0 }` leaves no auto margins to centre.
   `screen and` because printed output must not depend on a per-browser collapse
   preference. */
@media screen and (min-width: 641px) {
  html.unit-tree-collapsed [data-unit-shell] .el--text,
  html.unit-tree-collapsed [data-unit-shell] .callout,
  html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill),
  html.unit-tree-collapsed [data-unit-shell] .lesson-unit__head,
  html.unit-tree-collapsed [data-unit-shell] .lesson-unit__title,
  html.unit-tree-collapsed [data-unit-shell] [data-quiz-preview-notice],
  html.unit-tree-collapsed [data-unit-shell] .quiz-finish,
  html.unit-tree-collapsed [data-unit-shell] .unit-crumbs,
  html.unit-tree-collapsed [data-unit-shell] .markdone,
  html.unit-tree-collapsed [data-unit-shell] .fillgate,
  html.unit-tree-collapsed [data-unit-shell] .stepper,
  html.unit-tree-collapsed [data-unit-shell] .switchgate,
  html.unit-tree-collapsed [data-unit-shell] .guessnumber {
    max-width: 46rem;
  }
}
```

The `:not()` chain is required because the grid/spatial variants co-occur with `.el--question` on the same root. `.el--fillblank` is deliberately absent from the chain — it is prose with inline inputs.

- [ ] **Step 5: Run the guard to verify it passes**

```
uv run pytest tests/test_consumption_css.py tests/test_courses_views.py tests/test_review_roster.py --verbosity=0
```

Expected: all PASS. `test_consumption_css.py` already owns `.unit-strip` regex guards over this same
file, and an in-place splice at `:866-873` sits close enough to them to be worth the wider net.

- [ ] **Step 6: Falsify both assertions**

1. Re-add `html.unit-tree-collapsed .unit-tree__bar { justify-content: center; }` anywhere → assertion (a) MUST fail. Remove it.
2. Change one prose-cap entry from `[data-unit-shell] .el--text` to `.unit-shell .el--text` → assertion (b) MUST fail. Restore it.
3. Change `chunk.rsplit("{", 1)[0]` to `chunk.split("{")[0]` in the test → the coverage assertion MUST fail reporting 1. Restore it.

All three must go red. If any stays green, the guard is not working.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_consumption_css.py
git commit -m "feat(unit-nav): remove the collapsed rail entirely and cap prose at 46rem"
```

---

### Task 3: JS — bind both controls, and repair the three e2e tests the CSS breaks

**Files:**
- Modify: `courses/static/courses/js/unit_nav.js:48-67`
- Modify: `tests/test_e2e_unit_nav.py:160`, `:709-714`, `:877-879`

**Interfaces:**
- Consumes: `[data-unit-tree-pin]` (Task 1), the collapsed CSS (Task 2).
- Produces: focus lands on the newly-visible control after each toggle; `aria-expanded` agrees across both controls at all times.

**Why the test repairs live in this task:** Task 2's commit already made `[data-unit-tree-toggle]` `display: none` while collapsed, so those three e2e tests are red **as of Task 2**, one commit before this one. They are repaired *here* rather than there because the pin only becomes clickable once this task's JS binds it — the repair is not possible earlier. The default suite excludes e2e (`addopts = "-q -m 'not e2e'"`), so the *non-e2e* suite stays green across both commits; the e2e suite is red for exactly one commit, deliberately.

- [ ] **Step 1: Confirm the three tests are red**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "collapse_persists or recentres or group_is_folded" -v --verbosity=0
```

Expected: 3 FAILED. Do NOT filter on bare `folded` — it also matches
`test_clicking_a_folded_summary_reveals_its_units` (`:496`) and
`test_drawer_focus_trap_holds_at_a_folded_summary` (`:593`), neither of which this change touches;
the run would report 5 selected / 3 failed and read as a partial break. — timeouts waiting for `[data-unit-tree-toggle]` to be actionable. `-m e2e` is mandatory; without it these silently deselect and pytest exits 5.

- [ ] **Step 2: Restructure `unit_nav.js`**

Replace lines 48-67 entirely:

```js
  // Desktop collapse toggle.
  var toggle = document.querySelector("[data-unit-tree-toggle]");
  if (toggle) {
    var EXPAND = toggle.getAttribute("data-label-expand");
    var COLLAPSE = toggle.getAttribute("data-label-collapse");
    function syncToggle(collapsed) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      // Announce the ACTION the button performs in its current state.
      if (EXPAND && COLLAPSE) toggle.setAttribute("aria-label", collapsed ? EXPAND : COLLAPSE);
    }
    toggle.addEventListener("click", function () {
      var collapsed = html.classList.toggle("unit-tree-collapsed");
      store(collapsed ? "1" : "0");
      syncToggle(collapsed);
      // Expanding restores the labels — re-centre, or the student lands at scroll-top
      // with the active unit an arbitrary distance away. Nothing to centre when collapsing.
      if (!collapsed) centerActive();
    });
    syncToggle(isCollapsed());
  }
```

with:

```js
  // TWO desktop collapse controls, each visible in exactly one state: the in-rail
  // `‹` while expanded, the gutter pin while collapsed. Looked up INDEPENDENTLY
  // and null-guarded. Note there is no `if (...) { ... }` wrapper and no early
  // return: centerActive() below and the whole mobile-drawer block after it must
  // run regardless, which an early return would silently kill (see the comment at
  // the top of this file for the same hazard from a different cause).
  var railToggle = document.querySelector("[data-unit-tree-toggle]");
  var pin = document.querySelector("[data-unit-tree-pin]");
  var controls = [railToggle, pin].filter(Boolean);

  // Module scope, and it ITERATES: both controls must report the same state. The
  // label swap applies only to controls carrying BOTH data-label-* attributes, so
  // the pin's static label is left alone — it is only ever visible collapsed, so
  // it has nothing to swap to.
  function syncToggle(collapsed) {
    controls.forEach(function (el) {
      el.setAttribute("aria-expanded", collapsed ? "false" : "true");
      var expand = el.getAttribute("data-label-expand");
      var collapse = el.getAttribute("data-label-collapse");
      if (expand && collapse) {
        el.setAttribute("aria-label", collapsed ? expand : collapse);
      }
    });
  }

  function onToggleClick() {
    // ORDER IS LOAD-BEARING. Flip first: the control we are about to focus is
    // display:none until the class changes, and .focus() on a display:none element
    // is a silent no-op that drops focus to <body> — exactly the failure the focus
    // move exists to prevent.
    var collapsed = html.classList.toggle("unit-tree-collapsed");
    store(collapsed ? "1" : "0");
    syncToggle(collapsed);
    // Whichever control was clicked is now display:none, so move focus to the one
    // that just became visible, or a keyboard user is stranded. preventScroll:
    // focus() otherwise scrolls .unit-tree (overflow-y:auto) into view right before
    // centerActive() issues its own scrollTo — and a UA scroll does NOT pass through
    // the rail.scrollTo monkeypatch that the folded-group test counts.
    var next = collapsed ? pin : railToggle;
    if (next) next.focus({ preventScroll: true });
    // Expanding restores the labels — re-centre, or the student lands at scroll-top
    // with the active unit an arbitrary distance away. Nothing to centre when collapsing.
    if (!collapsed) centerActive();
  }

  controls.forEach(function (el) {
    el.addEventListener("click", onToggleClick);
  });
  // Unconditional: with an empty list this is a no-op, so a guard would buy nothing.
  syncToggle(isCollapsed());
```

- [ ] **Step 3: Repair `test_desktop_tree_collapse_persists`**

At `tests/test_e2e_unit_nav.py:159-160` (the comment is `:159`, the click `:160`). Change:

```python
    # Toggle back → expanded; reload to confirm persistence.
    page.locator("[data-unit-tree-toggle]").click()
```

to:

```python
    # Toggle back → expanded. The rail toggle is display:none while collapsed, so
    # the pin is now the only way back — that IS the feature.
    page.locator("[data-unit-tree-pin]").click()
```

Leave the collapse click at `:147` on `[data-unit-tree-toggle]`.

- [ ] **Step 4: Repair `test_expanding_the_rail_recentres_the_active_unit`**

At `:709-714`, a single `toggle` locator serves both clicks. Change:

```python
    toggle = page.locator("[data-unit-tree-toggle]")
    toggle.click()  # collapse (real gesture)
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    toggle.click()  # expand
```

to:

```python
    toggle = page.locator("[data-unit-tree-toggle]")
    pin = page.locator("[data-unit-tree-pin]")
    toggle.click()  # collapse (real gesture)
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    pin.click()  # expand — the rail toggle is hidden in this state
```

Do **not** repoint the existing `toggle` variable: its collapse click must stay on the rail toggle, which is the control visible while expanded.

- [ ] **Step 5: Repair `test_centering_is_skipped_when_the_active_group_is_folded`**

At `:877-879`. Change:

```python
    toggle = page.locator("[data-unit-tree-toggle]")
    toggle.click()  # collapse (real gesture)
    toggle.click()  # expand   (real gesture) -> centerActive() runs
```

to:

```python
    toggle = page.locator("[data-unit-tree-toggle]")
    pin = page.locator("[data-unit-tree-pin]")
    toggle.click()  # collapse (real gesture)
    pin.click()     # expand   (real gesture) -> centerActive() runs
```

- [ ] **Step 6: Pin an explicit viewport on all three repaired tests**

Each of the three now depends on `[data-unit-tree-pin]` being *visible*, which holds only above
641px — the exact dependency precondition P1 (Task 5) exists to make explicit. All three currently
rely on Playwright's 1280px default, which P1 calls out as accidental. Add an explicit viewport to
each test's context, preserving any existing argument:

```python
# test_desktop_tree_collapse_persists (~:138)
ctx = browser.new_context(viewport={"width": 1440, "height": 900})

# test_expanding_the_rail_recentres_the_active_unit — KEEP reduced_motion
ctx = browser.new_context(
    reduced_motion="reduce", viewport={"width": 1440, "height": 900}
)

# test_centering_is_skipped_when_the_active_group_is_folded (:851)
ctx = browser.new_context(
    reduced_motion="reduce", viewport={"width": 1440, "height": 900}
)
```

**Edit by line number, not by string match.** `ctx = browser.new_context(reduced_motion="reduce")`
occurs **ten** times in this file (`:182, :236, :470, :502, :536, :567, :681, :741, :818, :851`), so a
string-targeted edit is either rejected as ambiguous or, with `replace_all`, silently rewrites nine
unrelated tests. The three targets are:

| Test | Line | Current |
|---|---|---|
| `test_desktop_tree_collapse_persists` | `:138` | `browser.new_context()` |
| `test_expanding_the_rail_recentres_the_active_unit` | `:681` | `browser.new_context(reduced_motion="reduce")` |
| `test_centering_is_skipped_when_the_active_group_is_folded` | `:851` | `browser.new_context(reduced_motion="reduce")` |

`reduced_motion="reduce"` is load-bearing where present — it stops `centerActive()`'s smooth scroll
racing the assertion — so preserve it on `:681` and `:851`.

- [ ] **Step 7: Run the three repaired tests**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "collapse_persists or recentres or group_is_folded" -v --verbosity=0
```

Expected: 3 PASSED.

- [ ] **Step 8: Run the whole nav e2e file for regressions**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e --verbosity=0
```

Expected: all PASSED.

- [ ] **Step 9: Commit**

```bash
git add courses/static/courses/js/unit_nav.js tests/test_e2e_unit_nav.py
git commit -m "feat(unit-nav): bind both collapse controls and move focus between them"
```

---

### Task 4: e2e — the rail is gone, state persists, focus moves, aria agrees

**Files:**
- Modify: `tests/test_e2e_unit_nav.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1-3. Uses the existing `_make_student`, `_login`, `_seed_nav_course` helpers already in this file.
- Produces: nothing later tasks depend on.

**Precondition P1 applies to all four tests here:** set the viewport explicitly. These assert the rail is hidden and the pin visible, which holds only above 641px — they depend on a breakpoint exactly as much as the measuring tests do, and would pass today only because Playwright's 1280px default happens to sit above it.

- [ ] **Step 1: Write the four behaviour tests**

These are **not** expected to fail on first run — Tasks 1-3 already landed the behaviour they
describe, so a red here means something is broken, not that TDD is working. **The RED evidence for
these tests comes from Step 3's falsification, not from a pre-implementation run.** Append to
`tests/test_e2e_unit_nav.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_collapsing_removes_the_rail_and_the_pin_is_the_way_back(browser, live_server):
    """The rail LEAVES the layout; the pin is the only route back.

    The leading assertion (pin hidden while expanded) is not padding: omitting the
    base `.unit-toc-pin { display: none }` rule, or writing the reveal unscoped,
    would render the pin permanently — beside an expanded rail, and on mobile beside
    the drawer trigger. Every other test in this set stays green through that, which
    is probably the single most likely CSS mistake in the change.
    """
    _make_student("e2e_pin_back")
    course, units = _seed_nav_course("e2e_pin_back", "e2e-pin-back")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_back")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")

    rail = page.locator("[data-unit-tree]")
    pin = page.locator("[data-unit-tree-pin]")
    toggle = page.locator("[data-unit-tree-toggle]")

    assert rail.is_visible(), "the rail should start expanded"
    assert not pin.is_visible(), (
        "the pin must be hidden while the tree is expanded — its base rule is "
        "display:none and only the collapsed reveal shows it"
    )
    assert toggle.get_attribute("aria-expanded") == "true"
    assert pin.get_attribute("aria-expanded") == "true", (
        "both controls must agree on aria-expanded, including the hidden one"
    )

    toggle.click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert not rail.is_visible(), (
        "the rail must be display:none when collapsed, not a 2.4rem sliver"
    )
    assert pin.is_visible(), "the pin must be the visible way back"
    assert toggle.get_attribute("aria-expanded") == "false"
    assert pin.get_attribute("aria-expanded") == "false"

    pin.click()
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert rail.is_visible(), "clicking the pin must restore the rail"
    assert not pin.is_visible(), "the pin must hide again once the rail is back"
    assert toggle.get_attribute("aria-expanded") == "true"
    assert pin.get_attribute("aria-expanded") == "true"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_collapsed_state_survives_reload_with_the_pin_visible(browser, live_server):
    """Pre-paint restore, plus the FIRST-PAINT half of the aria invariant.

    Only the .unit-tree__toggle assertion can detect a missing boot call: it is
    server-rendered aria-expanded="true", so on a collapsed reload the boot call is
    the only thing that corrects it to "false". The pin's assertion is a same-state
    consistency check — its server-rendered "false" already matches the collapsed
    state, so it stays green with the boot call deleted.
    """
    _make_student("e2e_pin_reload")
    course, units = _seed_nav_course("e2e_pin_reload", "e2e-pin-reload")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_reload")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")

    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    page.reload()

    assert "unit-tree-collapsed" in (page.locator("html").get_attribute("class") or "")
    assert not page.locator("[data-unit-tree]").is_visible()
    assert page.locator("[data-unit-tree-pin]").is_visible()
    # Before any click on the restored page.
    toggle = page.locator("[data-unit-tree-toggle]")
    assert toggle.get_attribute("aria-expanded") == "false"
    pin_el = page.locator("[data-unit-tree-pin]")
    assert pin_el.get_attribute("aria-expanded") == "false"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_focus_moves_to_the_control_that_becomes_visible(browser, live_server):
    """Whichever control was clicked becomes display:none, so focus must move or
    the browser drops it to <body> and a keyboard user loses their place."""
    _make_student("e2e_pin_focus")
    course, units = _seed_nav_course("e2e_pin_focus", "e2e-pin-focus")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_focus")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")

    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert page.evaluate(
        "() => document.activeElement.hasAttribute('data-unit-tree-pin')"
    ), "collapsing must focus the pin"

    page.locator("[data-unit-tree-pin]").click()
    page.wait_for_function(
        "() => !document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    assert page.evaluate(
        "() => document.activeElement.hasAttribute('data-unit-tree-toggle')"
    ), "expanding must focus the rail toggle"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_pin_is_hidden_at_mobile_width_in_both_states(browser, live_server):
    """At <=640px there is NO clickable control: courses.css hides .unit-tree (so
    the rail toggle is unclickable) and the pin's base rule hides it. So the
    expanded half is taken before any gesture, and the collapsed half is reached by
    collapsing at desktop width and resizing down — which exercises the resize path
    for free. Do not substitute a page.evaluate class flip.
    """
    _make_student("e2e_pin_mobile")
    course, units = _seed_nav_course("e2e_pin_mobile", "e2e-pin-mobile")
    url = f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/"

    ctx = browser.new_context(viewport={"width": 480, "height": 800})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_mobile")
    page.goto(url)
    assert not page.locator("[data-unit-tree-pin]").is_visible(), (
        "expanded at mobile width: the pin must be hidden"
    )

    page.set_viewport_size({"width": 1440, "height": 900})
    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )
    page.set_viewport_size({"width": 480, "height": 800})
    assert not page.locator("[data-unit-tree-pin]").is_visible(), (
        "collapsed at mobile width: the pin must still be hidden — the footer "
        "drawer owns contents navigation below 641px"
    )

    ctx.close()
```

- [ ] **Step 2: Run them**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "way_back or survives_reload or focus_moves or hidden_at_mobile" -v --verbosity=0
```

Expected: 4 PASSED (Tasks 1-3 already landed the behaviour).

Those substrings come from the **test names**, not the seeded usernames. `-k` matches node ids, so
filtering on `pin_back` / `pin_reload` / `pin_focus` / `pin_mobile` — which appear only inside the
function bodies as usernames — selects **zero** tests and pytest exits 5. Re-derive any `-k` you
change against `grep -n "^def test_" tests/test_e2e_unit_nav.py`.

- [ ] **Step 3: Falsify each**

1. Revert `> .unit-tree { display: none }` to `flex-basis: 2.4rem` → `test_collapsing_removes_the_rail…` MUST fail. Restore.
2. Delete the base `.unit-toc-pin { display: none }` rule → the same test's leading assertion AND `test_pin_is_hidden_at_mobile_width…` MUST fail. Restore.
3. Delete the `if (next) next.focus({ preventScroll: true });` line → `test_focus_moves…` MUST fail. Restore.
4. Delete the `syncToggle(collapsed);` call inside `onToggleClick` → the aria assertions in `test_collapsing_removes_the_rail…` MUST fail at the **collapse** step, not the expand step: the boot call has already set both controls to `"true"`, so the first click leaves them there while the test expects `"false"`. Restore.
5. Delete the trailing `syncToggle(isCollapsed());` boot call → `test_collapsed_state_survives_reload…` MUST fail, because `.unit-tree__toggle` keeps its server-rendered `aria-expanded="true"`. Restore.

Note for step 5: do **not** instead try moving the boot call inside a control guard. On these pages the control list is never empty, so that mutation is unobservable and the test would stay green. The empty-list path is a future-consumer safeguard with no coverage, deliberately.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_unit_nav.py
git commit -m "test(e2e): cover rail removal, persistence, focus movement and aria agreement"
```

---

### Task 5: e2e — the geometry actually delivers

**Files:**
- Modify: `tests/test_e2e_unit_nav.py` (append)

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: nothing.

**Preconditions for every test here:** set the viewport explicitly (P1); collapse with a real `[data-unit-tree-toggle]` click and `wait_for_function` on the class (P2); and where a specific side of the 1040px breakpoint matters, **assert `matchMedia` before measuring** (P3).

**On P3, measured rather than assumed:** this Chromium uses *overlay* scrollbars, so the layout viewport equals the Playwright viewport — probed on a genuinely scrolling document, `matchMedia('(min-width: 1040px)')` is `True` at a 1040px window and `False` at 1039px, with no subtraction. The spec's rationale for choosing 1060/1010 over 1040/1039 assumed a ~15px classic scrollbar and is therefore wrong on this platform; the *choice* still stands (extra headroom costs nothing and survives a future headed or classic-scrollbar run), and the `matchMedia` assertions remain as cheap insurance. What the assumption did corrupt are two derived figures — corrected in the falsifier list below.

- [ ] **Step 1: Write the four behaviour tests**

As in Task 4, these pass on first run — the behaviour landed in Tasks 1-3. Their RED evidence is
Step 3's falsification. Append to `tests/test_e2e_unit_nav.py`:

```python
def _collapse(page):
    """Collapse via the real gesture and wait for the state class."""
    page.locator("[data-unit-tree-toggle]").click()
    page.wait_for_function(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    )


@pytest.mark.django_db(transaction=True)
def test_collapsing_reclaims_the_full_rail_width_above_the_breakpoint(
    browser, live_server
):
    """The test for the PURPOSE of the feature.

    Expected delta is ~224px — the full 14rem rail — NOT 262px. The two 38.4px
    quantities cancel: the shell gains 38.4px by overhanging and immediately spends
    38.4px on the pin's lane, so the article column goes 696 -> 920.
    """
    _make_student("e2e_pin_width")
    course, units = _seed_nav_course("e2e_pin_width", "e2e-pin-width")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_width")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is True

    before = page.evaluate(
        "() => document.querySelector('.lesson').getBoundingClientRect().width"
    )
    _collapse(page)
    after = page.evaluate(
        "() => document.querySelector('.lesson').getBoundingClientRect().width"
    )

    assert abs((after - before) - 224) <= 2, (
        f"expected the column to grow by the full 14rem rail (~224px), got "
        f"{after - before:.1f}px ({before:.1f} -> {after:.1f})"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_narrow_desktop_band_is_width_neutral(browser, live_server):
    """Below 1040px there is no overhang, so the lane sits inside the shell. The
    2.4rem lane exactly equals the sliver it replaces, so this band is neutral
    against today rather than worse.

    The container is derived at RUNTIME rather than hard-coded, so the assertion
    survives any future change to scrollbar behaviour or app-main's padding.

    Measure `.unit-shell` with getBoundingClientRect, NOT `.app-main` with
    getComputedStyle. The shell is the actual containing box of the two flex
    children, so `main == shell - lane` needs no padding arithmetic at all --
    and `box-sizing: border-box` is global here (reset.css:2), which makes
    `getComputedStyle(x).width` ambiguous between the border box and the content
    box. Sidestep the ambiguity rather than reason about it.
    """
    _make_student("e2e_pin_narrow")
    course, units = _seed_nav_course("e2e_pin_narrow", "e2e-pin-narrow")

    ctx = browser.new_context(viewport={"width": 900, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_narrow")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is False
    assert page.evaluate("() => matchMedia('(min-width: 641px)').matches") is True

    _collapse(page)
    shell = page.evaluate(
        "() => document.querySelector('.unit-shell').getBoundingClientRect().width"
    )
    main = page.evaluate(
        "() => document.querySelector('.unit-shell__main')"
        ".getBoundingClientRect().width"
    )
    assert abs(main - (shell - 38.4)) <= 2, (
        f"expected the main column to be shell-38.4px ({shell - 38.4:.1f}), "
        f"got {main:.1f} — below 1040px the lane sits INSIDE the shell, so the "
        f"column loses exactly one lane and nothing else"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "width,expect_overhang",
    [(1440, True), (1060, True), (1010, False)],
    ids=["wide", "just-above", "just-below"],
)
def test_pin_is_never_clipped_or_offscreen(
    browser, live_server, width, expect_overhang
):
    """1060/1010 rather than 1040/1039: the latter pair puts BOTH cases on the same
    side of the media query once the scrollbar is subtracted, making them identical
    in behaviour while appearing to test both branches. Each case asserts its
    matchMedia value before measuring, so an unusual scrollbar fails loudly.

    The containment assertion is EXACT (left >= 0) — the +/-2px used elsewhere would
    swallow the margins this test measures.
    """
    user = f"e2e_pin_clip_{width}"
    _make_student(user)
    course, units = _seed_nav_course(user, f"e2e-pin-clip-{width}")

    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, user)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert (
        page.evaluate("() => matchMedia('(min-width: 1040px)').matches")
        is expect_overhang
    ), f"window {width} landed on the wrong side of the 1040px breakpoint"

    _collapse(page)
    rect = page.evaluate(
        "() => { const r = document.querySelector('[data-unit-tree-pin]')"
        ".getBoundingClientRect();"
        " return {l: r.left, t: r.top, w: r.width, h: r.height}; }"
    )
    assert rect["l"] >= 0, f"the pin hangs off the left edge: left={rect['l']:.1f}"
    assert rect["t"] >= 0, f"the pin hangs off the top edge: top={rect['t']:.1f}"

    hit = page.evaluate(
        "() => { const b = document.querySelector('[data-unit-tree-pin]');"
        "const r = b.getBoundingClientRect();"
        "const el = document.elementFromPoint("
        "r.left + r.width / 2, r.top + r.height / 2);"
        "return !!el && b.contains(el); }"
    )
    assert hit, "the pin is not hit-testable at its centre"

    # The assertion that actually guards the no-overflow:hidden precondition.
    # A rect or centre hit-test CANNOT detect it: the pin overhangs 38.4px into
    # .app-main's 20px padding, so under overflow:hidden 20px stays inside the clip
    # and the centre lands ~0.8px on the visible side.
    # body and <html> are walked as a deliberate TRIPWIRE, not because they can clip
    # (body has no margin so its box spans the viewport; the root's overflow
    # propagates to the viewport). A red on those two means "re-check whether this
    # propagates to the viewport", NOT "the pin is clipped".
    clipping = page.evaluate(
        "() => { const out = [];"
        "for (let n = document.querySelector('.unit-shell').parentElement;"
        "     n; n = n.parentElement) {"
        "  const o = getComputedStyle(n).overflowX;"
        "  if (o !== 'visible') out.push(n.tagName + '.' + n.className + ':' + o);"
        "} return out; }"
    )
    assert clipping == [], (
        f"an ancestor of .unit-shell clips overflow-x, which would amputate the "
        f"overhanging pin: {clipping}"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_content_column_aligns_with_the_strip_above_it(browser, live_server):
    """At >=1040px the shell's box starts 38.4px left of the strip, but .unit-shell
    paints nothing and the pin exactly fills that overhang — so the content COLUMN
    lands on the strip's left edge. (The visible prose stays inset a further 24px by
    the article's own padding, unchanged from today; this asserts the column box,
    which is what the negative margin controls.)
    """
    _make_student("e2e_pin_align")
    course, units = _seed_nav_course("e2e_pin_align", "e2e-pin-align")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_align")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{units[0].pk}/")
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is True

    _collapse(page)
    edges = page.evaluate(
        "() => ({"
        " main: document.querySelector('.unit-shell__main')"
        ".getBoundingClientRect().left,"
        " strip: document.querySelector('.unit-strip').getBoundingClientRect().left,"
        " pin: document.querySelector('[data-unit-tree-pin]')"
        ".getBoundingClientRect().left"
        "})"
    )
    assert abs(edges["main"] - edges["strip"]) <= 1, (
        f"the content column must align with the strip above it: "
        f"main={edges['main']:.1f} strip={edges['strip']:.1f}"
    )
    assert abs((edges["strip"] - edges["pin"]) - 38.4) <= 1, (
        f"the pin must sit exactly one lane left of the strip: "
        f"gap={edges['strip'] - edges['pin']:.1f}, expected 38.4"
    )
    ctx.close()
```

- [ ] **Step 2: Run them**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "reclaims or narrow_desktop_band or clipped or aligns" -v --verbosity=0
```

Expected: 6 PASSED (the clip test is parametrized ×3). Do NOT filter on `width_neutral` — it also
matches the pre-existing `test_active_marker_is_strong_and_width_neutral` (`:735`).

- [ ] **Step 3: Falsify each**

1. Change the margin rule to `margin-inline-start: 0` → `test_collapsing_reclaims…` and `test_content_column_aligns…` MUST fail. Restore.
2. Change the lane to `flex: 0 0 4rem` → `test_narrow_desktop_band…` and `test_content_column_aligns…` MUST fail. Restore.
3. Change the overhang to `-6rem` → the **just-above** clip case MUST fail (pin left ≈ **−26.0px**, measured on this Chromium's overlay scrollbars). It will NOT fail at wide (**+164.0px**) or just-below (that block does not match there — the ancestor-walk falsifier is what reaches that case). Restore.
4. Add `overflow: hidden` to `.app-main` in `app.css` → the ancestor-walk assertion MUST fail in all three clip cases. Restore.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_unit_nav.py
git commit -m "test(e2e): pin the collapsed geometry across both breakpoint branches"
```

---

### Task 6: e2e — prose is capped, wide content is not, on both page types

**Files:**
- Modify: `tests/test_e2e_unit_nav.py` (append a seed helper and one test)

**Interfaces:**
- Consumes: Tasks 1-3, and `_collapse()` from Task 5.
- Produces: nothing.

- [ ] **Step 1: Write the seed helper and the behaviour tests**

As in Tasks 4 and 5, these pass on first run — Tasks 1-3 already landed the behaviour. Their RED
evidence is Step 3's falsification, not a pre-implementation run.

Append to `tests/test_e2e_unit_nav.py`:

```python
def _seed_text_and_table_unit(username, slug):
    """A lesson unit holding one text element and one table element.

    None of this file's existing seeds attach content elements — they build course
    structure only. Shape follows tests/test_e2e_wide_content_scroll.py.
    """
    from django.contrib.auth import get_user_model

    from courses.models import Enrollment
    from courses.models import TableElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    student = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")

    add_element(
        unit,
        TextElement.objects.create(
            body="<p>" + ("Lorem ipsum dolor sit amet. " * 40) + "</p>"
        ),
    )

    # The cell key is "html", NOT "text": TableElement._cell() reads
    # raw.get("html") (courses/models.py:885), so normalize_data would rewrite a
    # "text" key to {"html": ""} and every cell would render blank. The width
    # assertion would still pass — .el--table is a block box that fills the column
    # whatever the cells hold — so the seed's wrongness would be invisible to this
    # test and only surface as an empty table in Task 9's screenshot sweep.
    cells = [[{"html": f"r{r}c{c}"} for c in range(4)] for r in range(3)]
    add_element(
        unit, TableElement.objects.create(data={"cells": cells, "border": "grid"})
    )

    return course, unit


@pytest.mark.django_db(transaction=True)
def test_prose_is_capped_while_the_table_takes_the_full_column(browser, live_server):
    """46rem = 736px. Measure the ELEMENT roots, not the enclosing
    <section class="lesson-block"> — that stays 872px either way and would make the
    assertion vacuous.
    """
    _make_student("e2e_pin_cap")
    course, unit = _seed_text_and_table_unit("e2e_pin_cap", "e2e-pin-cap")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_cap")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    _collapse(page)

    text_w = page.evaluate(
        "() => document.querySelector('.el--text').getBoundingClientRect().width"
    )
    table_w = page.evaluate(
        "() => document.querySelector('.el--table').getBoundingClientRect().width"
    )
    assert text_w <= 736 + 2, f"prose must cap at 46rem (736px), got {text_w:.1f}"
    assert table_w > 736 + 2, (
        f"the table must take the full column, got {table_w:.1f} — if this equals "
        f"the prose width the cap has leaked onto wide content"
    )
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_quiz_chrome_is_capped_across_both_page_states(browser, live_server):
    """The quiz entries (.lesson-unit__title, [data-quiz-preview-notice],
    .quiz-finish) exist only for _quiz_article.html; without this the whole suite
    stays green if all three are deleted.

    TWO loads with ONE actor. previewing = not enrolled and read_only =
    quiz_submitted or not enrolled, and the finish form sits behind
    {% if not read_only %} — so the banner and the finish form can never coexist.
    The course OWNER satisfies can_access_course without being enrolled, which is
    exactly what makes previewing true while the page still loads; enrolling the
    same user via the ORM and reloading flips to the other state. Do not use two
    users: _login cannot switch identity, because allauth redirects an already
    authenticated visitor away from the login page.
    """
    from courses.models import Element
    from courses.models import ShortTextQuestionElement
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_quiz_unit

    actor = _make_student("e2e_pin_quiz")
    course = CourseFactory(slug="e2e-pin-quiz", owner=actor)
    unit = make_quiz_unit(course=course)
    q = ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7")
    Element.objects.create(unit=unit, content_object=q)

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    _login(page, live_server, "e2e_pin_quiz")
    # The quiz route is /courses/<slug>/u/<node_pk>/quiz/ -- NOT /q/<pk>/.
    url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"

    # Load A — owner, NOT enrolled: banner renders, no finish form.
    page.goto(url)
    _collapse(page)
    assert page.locator("[data-quiz-preview-notice]").count() == 1
    assert page.locator(".quiz-finish").count() == 0
    for sel in (".lesson-unit__title", "[data-quiz-preview-notice]", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert w <= 736 + 2, f"{sel} must cap at 736px, got {w:.1f}"

    # Load B — same session, now enrolled: finish form renders, no banner.
    EnrollmentFactory(course=course, student=actor)
    page.reload()
    assert page.locator("[data-quiz-preview-notice]").count() == 0
    assert page.locator(".quiz-finish").count() == 1
    for sel in (".lesson-unit__title", ".quiz-finish", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert w <= 736 + 2, f"{sel} must cap at 736px, got {w:.1f}"

    ctx.close()
```

The quiz route is `/courses/<slug>/u/<node_pk>/quiz/` (`courses/urls.py:70-73`), verified — not `/q/<pk>/`. `ShortTextQuestionElement`'s accepted-answers field is `accepted`, not `answer` (`courses/models.py:1815`).

- [ ] **Step 2: Run them**

```
uv run pytest tests/test_e2e_unit_nav.py -m e2e -k "prose_is_capped or quiz_chrome" -v --verbosity=0
```

Expected: 2 PASSED.

- [ ] **Step 3: Falsify**

1. Delete the `.el--text` entry from the prose-cap block → `test_prose_is_capped…` MUST fail. Restore.
2. Add `.el--table` to the prose-cap block → the same test's second assertion MUST fail. Restore.
3. Delete `.lesson-unit__title`, `[data-quiz-preview-notice]` and `.quiz-finish` → `test_quiz_chrome…` MUST fail. Restore.

- [ ] **Step 4: Refresh the module docstring**

`tests/test_e2e_unit_nav.py:1-19` opens with a docstring that enumerates the file's tests ("Tests:
1. … 2. … 3. …"). Tasks 4, 5 and 6 have appended ten tests and three helpers to it, so that
enumeration now indexes under a third of the file. Replace the numbered list with a one-line pointer
("see the test names below"), or extend it — either way it must stop being a stale index.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_unit_nav.py
git commit -m "test(e2e): prose caps at 46rem while wide content and quiz chrome hold"
```

---

### Task 7: e2e — the teacher review page is untouched

**Files:**
- Create: `tests/test_e2e_review_shell_isolation.py`

**Interfaces:**
- Consumes: Task 2's scoping.
- Produces: nothing.

**Why a new file:** this needs a staff-capable actor and a review fixture, neither of which `test_e2e_unit_nav.py` has. The module must carry the repo's e2e boilerplate itself — `conftest.py` supplies none of it.

- [ ] **Step 1: Write the behaviour test**

As in Tasks 4-6, this passes on first run — Task 2 already landed the scoping. Its RED evidence is
Step 3's falsification. Create `tests/test_e2e_review_shell_isolation.py`:

```python
"""The teacher quiz-review page must be unaffected by the student tree's collapse.

review_submission.html reuses the .unit-shell wrapper AND inherits
html.unit-tree-collapsed (base.html sets it on every page from one global key), so
an unscoped rule would deform it for any teacher who had ever collapsed the tree on
a student page.

This test guards exactly ONE rule family — the margin. It deliberately does not
attempt an inner-node assertion for the prose cap: this page renders none of the
thirteen capped selectors (it never calls render_element), so such an assertion
could never go red. That the prose-cap selectors are correctly SCOPED is guarded by
the source
assertion in tests/test_consumption_css.py instead; that four of them cap at the
right width is guarded behaviourally in test_e2e_unit_nav.py.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _shell_box(page, url):
    page.goto(url)
    assert page.evaluate("() => matchMedia('(min-width: 1040px)').matches") is True, (
        "the rule under test lives inside @media (min-width: 1040px); below it the "
        "falsification would shift nothing and this test would pass vacuously"
    )
    return page.evaluate(
        "() => { const r = document.querySelector('.unit-shell')"
        ".getBoundingClientRect();"
        "return {l: r.left, w: r.width}; }"
    )


@pytest.mark.django_db(transaction=True)
def test_review_shell_is_unmoved_by_the_student_tree_collapse(browser, live_server):
    from tests.factories import EnrollmentFactory
    from tests.factories import make_review_submission

    result = make_review_submission()
    submission = result["submission"]
    course = submission.unit.course

    # The fixture's own `reviewer` is built with UserFactory (password
    # "password123", no verified email), so it cannot log in through the allauth
    # form -- discard it. The gate is reviewable_students(), not can_review_course:
    # the submission page resolves through _resolve_submission. Its owner path
    # filters through Enrollment, which the fixture never creates, so making the
    # actor the owner WITHOUT the enrolment below 404s.
    actor = make_verified_user(
        username="e2e_review_iso",
        email="e2e_review_iso@t.example.com",
        password=TEST_PASSWORD,
    )
    course.owner = actor
    course.save(update_fields=["owner"])
    EnrollmentFactory(course=course, student=submission.student)

    url = f"{live_server.url}/manage/courses/{course.slug}/review/{submission.pk}/"

    # Baseline context: no collapse state at all.
    plain = browser.new_context(viewport={"width": 1440, "height": 900})
    page = plain.new_page()
    _login(page, live_server, "e2e_review_iso")
    baseline = _shell_box(page, url)
    plain.close()

    # Collapsed context. The class MUST be installed before first paint: base.html
    # reads localStorage pre-paint, so a page.evaluate after goto would measure a
    # page that already painted uncollapsed and pass for the wrong reason.
    # add_init_script is registered on the CONTEXT and cannot be removed, which is
    # why the baseline above needs its own context -- sized identically.
    collapsed_ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    collapsed_ctx.add_init_script(
        "localStorage.setItem('libli_unit_tree_collapsed','1')"
    )
    page = collapsed_ctx.new_page()
    _login(page, live_server, "e2e_review_iso")
    collapsed = _shell_box(page, url)
    assert page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "the pre-paint restore did not run; this test would be vacuous"
    collapsed_ctx.close()

    assert abs(collapsed["l"] - baseline["l"]) <= 1, (
        f"the review shell moved {collapsed['l'] - baseline['l']:.1f}px when the "
        f"student tree was collapsed — a new rule is scoped to .unit-shell instead "
        f"of [data-unit-shell]"
    )
    assert abs(collapsed["w"] - baseline["w"]) <= 1, (
        f"the review shell changed width by {collapsed['w'] - baseline['w']:.1f}px"
    )
```

- [ ] **Step 2: Run it**

```
uv run pytest tests/test_e2e_review_shell_isolation.py -m e2e -v --verbosity=0
```

Expected: PASS. If it errors rather than fails, check the `@pytest.mark.django_db(transaction=True)` decorator — `live_server` needs it.

- [ ] **Step 3: Falsify**

Change the margin rule's selector from `html.unit-tree-collapsed [data-unit-shell]` to `html.unit-tree-collapsed .unit-shell`, re-run — it MUST fail on the left-edge assertion. Restore. (Note this also reddens the Task 2 source guard, which is the intended belt-and-braces.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_review_shell_isolation.py
git commit -m "test(e2e): guard the teacher review page against collapsed-state leakage"
```

---

### Task 8: i18n — the new string in both catalogs

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`
- Modify: `locale/pl/LC_MESSAGES/django.mo`, `locale/en/LC_MESSAGES/django.mo`

**Interfaces:**
- Consumes: the `{% trans 'Show course contents' %}` calls added in Task 1.
- Produces: nothing.

- [ ] **Step 1: Extract**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Both language flags and `--no-obsolete` are required; a bare `makemessages` rewrites every catalog.

- [ ] **Step 2: Check for fuzzy pre-fills**

```bash
git diff locale/ | grep -n "fuzzy" || echo "no fuzzy markers"
```

`makemessages` pre-fills a near-match translation and marks it `#, fuzzy`. Clearing one means **two** deletions — the `#, fuzzy` line **and** the `#| msgid` line above it. Leaving either ships a wrong translation silently. The likely near-neighbours here are `"Expand contents"` and `"Open course contents"`.

- [ ] **Step 3: Translate**

In `locale/pl/LC_MESSAGES/django.po`, set the Polish string:

```po
msgid "Show course contents"
msgstr "Pokaż spis treści"
```

In `locale/en/LC_MESSAGES/django.po`:

```po
msgid "Show course contents"
msgstr "Show course contents"
```

Keep the tone consistent with the existing `"Expand contents"` / `"Open course contents"` entries — three strings now name the same concept, and divergent phrasing between them is a bug.

- [ ] **Step 4: Compile**

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 5: Verify the catalogs are healthy**

```
uv run pytest tests/test_i18n_po_health.py -v --verbosity=0
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale/
git commit -m "i18n: add the TOC pin's label to the pl and en catalogs"
```

**If the branch is rebased onto master before the PR, re-run `compilemessages` and re-commit the
`.mo` files rather than resolving by hand.** Tracked `.mo` files are binary and have no three-way
merge, so a branch that sits behind master through nine tasks hits an unmergeable conflict — a
recurring hazard in this repo.

---

### Task 9: Full suite, then the visual pass

**Files:**
- Modify: `courses/static/courses/css/courses.css` (visual declarations only)
- Modify: `tests/test_e2e_unit_nav.py` (Step 5 appends the focus-ring assertion)
- Modify: `docs/superpowers/plans/2026-08-01-unit-tree-toc-pin.md` (append the resolved deferred decisions)

- [ ] **Step 1: Lint**

```
uv run ruff check .
uv run ruff format --check .
```

Expected: both clean. `.github/workflows/ci.yml` runs exactly these, so a violation here becomes a
red PR after everything else has passed. `pyproject.toml:35-36` selects `["E", "F", "I", "UP", "B", "S"]`
at ruff's default 88-column limit, and **`E501` on a long string literal is not auto-fixable** —
`ruff format` cannot rewrap a string, so it must be split by hand. Note `force-single-line = true`
for isort: one import per line, no parenthesised groups.

- [ ] **Step 2: Run the non-e2e suite**

```
uv run pytest --verbosity=0
```

Expected: all PASS. This is where a stray comment tripping a source-level guard, or a broken template, surfaces.

- [ ] **Step 3: Run the e2e suite in foreground chunks**

```
uv run pytest tests/test_e2e_unit_nav.py tests/test_e2e_review_shell_isolation.py -m e2e --verbosity=0
```

Expected: all PASS. Then sweep the rest — **44 of the 78 e2e modules render `.unit-shell`**, so a
hand-picked subset would be arbitrary. Run the whole suite in foreground chunks, the convention this
repo already uses, with an explicit all-PASS expectation per chunk:

First record the baseline count, so "the sweep ran" has something to verify against:

```
uv run pytest tests/ -m e2e --co --verbosity=0
```

Note the collected count `N` from the summary line (**565** on this tree at time of writing). Do **not** pipe this through `tail`: `addopts`
already carries `-q`, and a second `-q` stacks to quiet-2 which prints no verdict at all, so the run
reads as a hang. `-x` is inert under `--co`.

Then sweep in chunks. **The e2e modules start with `a b c e f g h i l m n p q r s t u w` — there is no
`d`.** A non-matching glob is not expanded by bash or PowerShell, so pytest would receive the literal
path and abort the whole chunk with a usage error before running anything:

```
uv run pytest tests/test_e2e_a*.py tests/test_e2e_b*.py tests/test_e2e_c*.py -m e2e --verbosity=0
uv run pytest tests/test_e2e_e*.py tests/test_e2e_f*.py tests/test_e2e_g*.py -m e2e --verbosity=0
uv run pytest tests/test_e2e_h*.py tests/test_e2e_i*.py tests/test_e2e_l*.py tests/test_e2e_m*.py -m e2e --verbosity=0
uv run pytest tests/test_e2e_n*.py tests/test_e2e_p*.py tests/test_e2e_q*.py -m e2e --verbosity=0
uv run pytest tests/test_e2e_r*.py tests/test_e2e_s*.py -m e2e --verbosity=0
uv run pytest tests/test_e2e_t*.py tests/test_e2e_u*.py tests/test_e2e_w*.py -m e2e --verbosity=0
uv run pytest tests/test_link_apply.py tests/test_link_dialog_behaviour.py \n              tests/test_table_grid_algebra.py tests/test_tabs_editor_dnd.py -m e2e --verbosity=0
```

**That seventh chunk is not optional.** Four e2e modules do not follow the `test_e2e_*` naming
convention, so the six letter-globs collect only **464** of the 565 — a 101-test gap that CI's
`pytest -m e2e` *does* run, surfacing after the PR is open. `test_tabs_editor_dnd.py` is the easiest
to miss: it marks per-function with `@pytest.mark.e2e` rather than a module-level `pytestmark`, so it
hides from the obvious grep.

Expected: every chunk all-PASS, and the seven chunk counts summing to `N` (464 + 101 = 565). One invocation at a time —
never two pytest processes at once against the same database. If a chunk fails, A/B it against
`origin/master` before blaming this diff: this repo has a documented family of e2e flakes that fail
only under parallel load and pass in isolation.

- [ ] **Step 4: Land the minimum visual treatment**

Tasks 1-8 ship a bare `<button>` with a UA border and no colour, radius or hover. Add these as a
**second, separate** `.unit-toc-pin` rule immediately after the base one — **do not merge into or
replace the base rule**, which must keep `display: none` as its only declaration. Merging would ship
a permanently visible pin, the exact regression Task 4's leading assertion exists to catch.

```css
/* Visual treatment. Borrows .unit-tree__toggle's so the two read as one control
   that moved. No :focus-visible rule here — reset.css:24 already applies
   `outline: 2px solid var(--primary); outline-offset: 2px` to :focus-visible
   globally, so an element-specific copy would be a byte-for-byte duplicate. */
.unit-toc-pin {
  border: 1px solid var(--border-default);
  border-radius: .4rem;
  background: var(--surface-raised);
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 0;
}
.unit-toc-pin:hover {
  color: var(--text-secondary);
  border-color: var(--border-strong);
}
```

- [ ] **Step 5: Add the focus-ring assertion**

The ring comes free from `reset.css:24`, but nothing currently proves it reaches the pin — and Task
3's whole focus-move design is pointless if a keyboard user cannot see where focus landed. Extend
`test_focus_moves_to_the_control_that_becomes_visible` (Task 4), after the collapse assertion:

```python
    # Driven by a REAL Tab, mirroring the proven idiom at
    # tests/test_e2e_unit_nav.py:768-792. Chromium's :focus-visible heuristic does
    # not reliably arm on a programmatic .focus() with no prior keyboard input, so
    # blur first and tab in. Bounded, so a regression fails rather than hangs.
    page.evaluate("() => document.activeElement.blur()")
    for _ in range(200):
        page.keyboard.press("Tab")
        if page.evaluate(
            "() => !!document.activeElement"
            " && document.activeElement.hasAttribute('data-unit-tree-pin')"
        ):
            break
    else:
        raise AssertionError("never reached the pin by tabbing")

    ring = page.evaluate(
        "() => { const s = getComputedStyle("
        "document.querySelector('[data-unit-tree-pin]'));"
        " return {style: s.outlineStyle, offset: s.outlineOffset}; }"
    )
    assert ring["style"] != "none", (
        f"no focus-visible ring on the pin (outline-style={ring['style']!r})"
    )
    assert ring["offset"] not in ("0px", ""), (
        f"the focus ring has no offset ({ring['offset']}) — it merges into the "
        f"button border"
    )
```

**Assert on `outline-style`, never on `outline-width`.** Chromium reports a non-zero
`outlineWidth` even when `outlineStyle` is `none`, so a width-only assertion passes with no ring
rendered at all. And **never** pass `':focus-visible'` as `getComputedStyle`'s second argument — that
parameter takes a pseudo-*element*, and `:focus-visible` is a pseudo-*class*, so it returns an empty
string and the assertion fails unconditionally.

**Falsify by adding**, temporarily, `.unit-toc-pin:focus-visible { outline: none; }` — it MUST go red.
Do **not** try to falsify by deleting a `.unit-toc-pin:focus-visible` rule: there isn't one, and the
global `reset.css:24` ring would keep the assertion green.

- [ ] **Step 6: Invoke the frontend-design skill for the rest**

With the minimum landed, the skill's remit is **refinement**: colour, weight, iconography,
border/radius, and resting/hover/focus/active states, within the fixed 2.4rem lane. It may **not**
change the lane width, the `min-height`, or the `z-index` — all three are load-bearing for the
overhang, the breakpoint derivation and Task 5's assertions.

Two layout decisions are deliberately deferred to this pass. **Record both in this plan file**, under
a new "## Deferred decisions — resolved" heading appended at the end, with the choice and one line of
reasoning each. The plan file is self-contained and the record is verifiable in the diff; the PR body
is opened by the surrounding pipeline, not by any step here, so "record it in the PR" would name no
executable action.

1. **Whether `.block-notes` is capped.** Capping aligns the handle with prose but misaligns it under a full-width table **and detaches the note popover**: `.block-notes__pop` is absolutely positioned against `.lesson-block`, which stays 872px, so the handle would move ~136px away from the panel it opens. View this with a **note panel open at ≥1200px** — the only configuration where it is visible.
2. **Whether unanchored notes are capped** (`notes/_unanchored.html`, the last child of `.lesson`).

- [ ] **Step 7: Screenshot sweep**

This step feeds back into code — its output decides whether an element root joins the Task 2
allow-list — so it needs a concrete seed and a concrete capture path, not a coverage wish-list.

**Seed.** Extend `_seed_text_and_table_unit` (Task 6) into `_seed_sweep_unit` in a throwaway script,
attaching one of each element root named in the spec's per-root ruling table
(`docs/superpowers/specs/2026-08-01-unit-tree-toc-pin-design.md`, the table under "Per-root capping
ruling" — it adds `.el--math`, `.html-el`, `.reveal-gate`, the matrix/filltable roots and switch-grid
beyond the thirteen allow-list entries), plus one `.el--text` nested inside each of
`TwoColumnElement`, `SpoilerElement` and `TabsElement`, plus a slide-break pair so `slideshow.js`
builds a `.slideshow-deck` at runtime (a template grep cannot find that container — it does not exist
until JS runs). Follow `tests/factories.py::seed_slideshow_unit` for the slide-break idiom.

**`add_element()` cannot nest** — `tests/factories.py:170` is
`Element.objects.create(unit=unit, content_object=obj)` with no `parent` and no `tab_id`, so it only
makes top-level rows. Nesting needs the join row spelled out, with a **container-specific** slot id:

```python
container = add_element(unit, TabsElement.objects.create(...))
Element.objects.create(
    unit=unit, content_object=TextElement.objects.create(body="..."),
    parent=container, tab_id="t000001",
)
```

The slot id differs per container — `"t000001"` for tabs, `SpoilerElement.SLOT_ID` for spoiler,
per-column ids for two-column. Follow `tests/test_e2e_imagezoom.py:627-637` as the worked idiom; it
covers both the tabs and spoiler forms.

**Capture.** Mirror `tests/capture_help_screenshots.py`, which already establishes this repo's
pattern — `browser.new_context(viewport=…)` per shot. Loop the four axes:

```
viewport   ∈ {1440×900, 900×900}
state      ∈ {expanded, collapsed}   # collapsed via a real [data-unit-tree-toggle] click
theme      ∈ {light, dark}
page       ∈ {lesson unit, quiz unit}
```

**Dark mode is set on the user, not by a cookie** — `user.theme = "dark"; user.save()` before the
context opens. The cookie route does not survive a server-rendered page in this app, and a sweep that
silently captured light twice would be worse than no sweep.

Add the block-notes case separately: ≥1200px, JS on, a note panel **open** — the only configuration
in which the popover-detachment consequence is visible.

**Pass criterion, so the allow-list edit has a decidable trigger:** an element root fails if, in the
collapsed state, its text runs the full 872px directly beside a 736px-capped sibling — that is the
ragged right edge the quiz-chrome entries were added to prevent. Anything failing that joins the
allow-list; re-derive the Task 2 coverage floor **only if an entry is removed** (the assertion is
`>=`, so additions never redden it).

Judge light and dark separately — dark is not assumed to follow from light.

- [ ] **Step 8: Re-run lint and the suites after any change above**

```
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/test_consumption_css.py --verbosity=0
uv run pytest tests/test_e2e_unit_nav.py tests/test_e2e_review_shell_isolation.py -m e2e --verbosity=0
```

The review-isolation module is included because Step 7 is authorised to amend the allow-list — i.e.
to write new `html.unit-tree-collapsed [data-unit-shell] …` selectors *after* every other
verification has run. It is the behavioural half of the scoping guard.

Lint is re-run because Step 5 added Python, not only CSS — and E501 on the new assertion's string
literals is exactly the kind of thing Step 1's earlier pass cannot have caught.

- [ ] **Step 9: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_e2e_unit_nav.py \n        docs/superpowers/plans/2026-08-01-unit-tree-toc-pin.md
git commit -m "style(unit-nav): visual treatment for the TOC pin"
```

`tests/test_e2e_unit_nav.py` is in that list because Step 5 appends the focus-ring assertion to it.
Task 9 is the last task — anything left unstaged here never reaches the PR.

---

## Self-Review

**Spec coverage:** Scoping → Task 2. Geometry (lane, breakpoint, sticky, z-index, strip interaction) → Tasks 2, 5. Content width incl. all thirteen allow-list entries → Tasks 2, 6. The `courses.css:866-873` deletion → Task 2, guarded by its source test. Behaviour (null-guards, module-scope `syncToggle`, unconditional boot call, flip-before-focus, `preventScroll`) → Task 3, falsified in Task 4. Error handling — the JS-off and `unit_nav.js`-fails branches are accepted degradations with no test, by design; the `scrollTop` reset is accepted; the `overflow: hidden` precondition → Task 5's ancestor walk. All eleven spec tests map: 1→Task 4, 2→Task 4, 3→Task 4, 4→Task 5, 5→Task 5, 6→Task 5, 7→Task 6, 8→Task 1, 9→Task 7, 10→Task 5, 11→Task 2. i18n → Task 8. Visual verification → Task 9.

**Placeholder scan:** none — every code step carries complete code, every command its expected output.

**Type consistency:** `[data-unit-tree-pin]` and `.unit-toc-pin` are used identically in Tasks 1-7. `_collapse(page)` is defined once in Task 5 and reused in Task 6. `id="unit-tree"` matches `aria-controls` in Tasks 1 and 4. The coverage floor of 17 in Task 2 matches the thirteen allow-list entries plus four structural selectors written in the same task.
