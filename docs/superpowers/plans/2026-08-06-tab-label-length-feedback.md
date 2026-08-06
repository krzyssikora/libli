# Tab label length feedback + tab strip width cap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell a content author when a tab label is approaching and has hit the 80-character limit, and stop one long label from monopolising the student tab strip — without ever hiding label text from any reader.

**Architecture:** Two independent changes sharing no source file. **Change 1** adds a client-side character counter to each row of the tabs editor (a per-row digits span plus one per-editor `aria-live` region), driven by a single `refreshCount()` rebuild function hung off the existing delegated `input` listener. **Change 2** is CSS-only: cap `.tabs__tab` width and let the label wrap instead of clipping.

**Tech Stack:** Django templates, vanilla ES5 JavaScript (no build step, no framework), hand-written CSS with design tokens, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-08-06-tab-label-length-feedback-design.md` — read it before starting. It went through 10 review rounds; its assertion forms are load-bearing and several were rewritten specifically because earlier versions could not go RED.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Worktree.** All work happens in `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/tab-label-length-feedback` on branch `pipeline/tab-label-length-feedback`. Use `git -C "<worktree>"`. The Bash tool's working directory resets to the **main repo** between calls — never edit or commit there.
- **`uv run` is mandatory.** `ruff`, `pytest` and `python` are NOT on PATH. Every command is `uv run <tool>`.
- **e2e needs `-m e2e`.** Without it the selection silently empties and pytest exits 5 (which is *not* a pass).
- **One pytest at a time.** Never run two pytest invocations concurrently across worktrees — they collide on the test database. If a run is backgrounded, wait for it.
- **`TabsElement.LABEL_MAX` stays at 80.** Do not modify it, `sanitize_label`, `tabs_bounds`, or `check_str`. No model, migration, transfer or `FORMAT_VERSION` change.
- **Do not touch** `courses/static/courses/js/tabs.js`, `templates/courses/elements/tabselement.html`, or any carousel CSS rule.
- **Falsify every test.** For each new test, apply its named mutant, confirm RED, revert, confirm GREEN. **A named mutant that cannot go RED is a defect in the test, not a step to skip** — fix the assertion, do not edit working code to make it fail.
- **Scope test runs with `-k`.** Whole-suite sweeps belong to Task 9 only.
- **Per-task lint:** `uv run ruff check <files>` **and** `uv run ruff format --check <files>` on the Python files you touched. Both. PR #219 passed the first and failed CI on the second.
- **Nothing flagged is left unfixed.** If your task report would mention a lint nit, a stale comment, or an unrelated failure, fix it or state it in a way Task 9 can act on. #219's CI failure escaped exactly by being mentioned and scrolled past.
- **Copy strings byte-for-byte.** The at-cap msgid is `Tab {n} label limit reached — {max} characters` — em dash (`—`, U+2014), both `{n}` and `{max}` braces literal. The JS fallback literal must match it exactly.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `courses/static/courses/css/courses.css` | Change 2: the two `.tabs__tab` rules | 1 |
| `tests/test_tabs_css.py` | Change 2 static assertions | 1 |
| `courses/static/courses/css/editor.css` | Change 1: counter + status + label floor rules | 2 |
| `templates/courses/manage/editor/_edit_tabs.html` | Change 1: `data-msg-cap`, digits span, live region | 3 |
| `courses/static/courses/js/tabs_editor.js` | Change 1: `refreshCount`, `clearCapRegion`, wiring | 4 |
| `tests/test_tabs_editor_partial.py` | Change 1 markup, CSS and static-source assertions | 2, 3, 4, 5 |
| `locale/{en,pl}/LC_MESSAGES/django.{po,mo}` | The one new user-facing string | 5 |
| `tests/test_e2e_tabs.py` | Behavioural coverage for both changes | 6, 7 |

**Sequencing constraint (do not reorder Tasks 2 and 3).** `test_editor_css_styles_every_tabs_editor_class` (`tests/test_tabs_editor_partial.py:153`) scans `_edit_tabs.html` for every `tabs-editor__*` class and asserts `editor.css` styles each one. The assertion is one-directional — extra CSS rules with no markup are fine, markup with no CSS is not. **CSS (Task 2) must land before the markup (Task 3)** or that existing test goes red at the task boundary.

---

## Task 1: Change 2 — cap the tab width and wrap the label

Fully independent of Tasks 2-6. Touches only `courses.css` and `tests/test_tabs_css.py`.

**Files:**
- Modify: `courses/static/courses/css/courses.css:1505-1510`
- Test: `tests/test_tabs_css.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `.el--tabs .tabs__tab` declaring `max-width`, `overflow-wrap`, `text-align` and **not** `white-space: nowrap`; plus a new `.el--tabs .tabs__tab .katex` rule. Task 7's e2e depends on the 288px cap.

- [ ] **Step 1: Read the current rule**

Run: `git -C "<worktree>" show HEAD:courses/static/courses/css/courses.css | sed -n '1500,1515p'`

You should see the block below. Note it spans six lines — this is why the test slices a *declaration block*, not a line:

```css
.el--tabs .tabs__tab {
  flex: 0 0 auto; padding: var(--space-3) var(--space-4);
  border: 0; border-bottom: 2px solid transparent; background: none;
  color: var(--text-secondary); font: inherit; font-weight: 600; cursor: pointer;
  white-space: nowrap;
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_tabs_css.py`. The module already defines `CSS = ROOT / "courses/static/courses/css/courses.css"` at `:10` and imports `re` — use `CSS`, do not add a second path constant and do not re-import.

Lines are pre-wrapped to ruff-format's output shape: `pyproject.toml` selects `E` with no `line-length` override, so E501 fires at 88 and Step 7 lints these exact lines.

```python
def _rule_block(css, selector):
    """Slice the declaration block whose selector is EXACTLY `selector`.

    Line matching does not work here: `.el--tabs .tabs__tab` spans six physical
    lines, so a line-based parser finds no declarations on the selector's line. A
    substring match is worse -- it also hits `.tabs__tab:hover`,
    `.tabs__tab[aria-selected="true"]` and `.tabs__tab:focus-visible`, which follow
    immediately. Anchoring on a leading newline plus a trailing " {" pins the exact
    selector.
    """
    i = css.index("\n" + selector + " {")
    open_brace = css.index("{", i)
    return css[open_brace + 1 : css.index("}", open_brace)]


def test_a_long_tab_label_wraps_and_is_never_clipped():
    """The cap constrains WIDTH only. Clipping was rejected outright: a clipped
    label is unreadable on touch, where title tooltips do not exist."""
    css = CSS.read_text(encoding="utf-8")
    block = _rule_block(css, ".el--tabs .tabs__tab")

    assert "max-width" in block, "the tab has no width cap"
    assert "overflow-wrap" in block, (
        "an 80-char label with no spaces would overflow the cap, not wrap"
    )
    assert "text-align" in block, (
        "wrapped-label alignment must be declared, not inherited"
    )
    assert "white-space: nowrap" not in block, (
        "nowrap defeats wrapping -- the label would run past the cap on one line"
    )


def test_katex_stays_atomic_inside_a_tab():
    """KaTeX emits MULTIPLE `.katex .base` spans per formula and can line-break
    between them; each base is nowrap internally but nothing holds the bases
    together. `white-space: nowrap` on .tabs__tab was suppressing that, so removing
    it newly permits \\(a + b = c\\) to wrap mid-formula in a tab handle."""
    css = CSS.read_text(encoding="utf-8")
    block = _rule_block(css, ".el--tabs .tabs__tab .katex")
    assert "white-space: nowrap" in block


def test_the_width_cap_did_not_leak_onto_a_carousel_selector():
    """Carousel rules position and hide things; a max-width there would be a
    different bug. No carousel rule declares max-width today.

    This scan is LINE-based, which is sound only because every carousel rule in
    courses.css is currently written selector-and-body on one line. If a carousel
    rule is ever reformatted across lines this test goes blind to it -- prefer
    _rule_block per carousel selector if that happens.
    """
    css = CSS.read_text(encoding="utf-8")
    for line in css.splitlines():
        if '[data-display="carousel"]' in line or ".tabs--carousel" in line:
            assert "max-width" not in line, f"carousel selector gained a cap: {line}"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_css.py -k "wraps_and_is_never_clipped or katex_stays_atomic" -v`
Expected: **FAIL** — `white-space: nowrap` is still present, `max-width` absent, and `_rule_block` raises `ValueError` for the `.katex` selector that does not exist yet.

- [ ] **Step 4: Apply the CSS change**

Replace the block at `courses.css:1505-1510` with:

```css
.el--tabs .tabs__tab {
  flex: 0 0 auto; padding: var(--space-3) var(--space-4);
  border: 0; border-bottom: 2px solid transparent; background: none;
  color: var(--text-secondary); font: inherit; font-weight: 600; cursor: pointer;
  /* Width cap + wrap, NOT clip. A clipped label is unreadable on touch (no title
     tooltips), and today a phone reader can swipe the strip to read it all.
     18rem = 288px; box-sizing:border-box and 16px padding each side leave 256px of
     text, ~34 chars per line, so an 80-char label wraps to about three lines.
     55vw is VIEWPORT-relative: it keeps a second tab and the edge fade visible on a
     ~360px phone, but in a narrow CONTAINER on a wide viewport the 18rem arm wins and
     the strip's existing scroller/fade/chevrons take over. text-align is declared so
     the centring reads as a decision, not an accident. */
  max-width: min(18rem, 55vw); overflow-wrap: break-word; text-align: center;
}
/* Keep a formula atomic. KaTeX splits a formula into several `.base` spans at
   top-level operators and relations; each is nowrap internally but they can break
   between. The tab's own nowrap was holding them together, so removing it above
   would let \(a + b = c\) wrap mid-expression. Cost: a formula wider than the cap
   overflows it -- accepted, because the alternative is clipping or mangling. */
.el--tabs .tabs__tab .katex { white-space: nowrap; }
```

`.tabs__strip` has no `align-items` (`courses.css:1503`) so it defaults to `stretch`: once one tab wraps, every tab in that strip becomes equally tall and the 2px active underline stays on one baseline. That is intended — do not "fix" it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_css.py -v`
Expected: **PASS** (all, including the pre-existing tests in this module).

- [ ] **Step 6: Falsify each test**

Apply each mutant, confirm the named test goes RED, then revert:

| Mutant | Must turn RED |
|---|---|
| Re-add `white-space: nowrap;` to the `.tabs__tab` block | `test_a_long_tab_label_wraps_and_is_never_clipped` |
| Delete `max-width: min(18rem, 55vw);` | `test_a_long_tab_label_wraps_and_is_never_clipped` |
| Delete `overflow-wrap: break-word;` | `test_a_long_tab_label_wraps_and_is_never_clipped` |
| Delete the `.el--tabs .tabs__tab .katex` rule | `test_katex_stays_atomic_inside_a_tab` |
| Move `max-width` onto `.el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage` | `test_the_width_cap_did_not_leak_onto_a_carousel_selector` |

- [ ] **Step 7: Lint and commit**

```bash
cd "<worktree>"
uv run ruff check tests/test_tabs_css.py
uv run ruff format --check tests/test_tabs_css.py
git add courses/static/courses/css/courses.css tests/test_tabs_css.py
git commit -m "feat(tabs): cap tab width and wrap long labels instead of clipping"
```

---

## Task 2: Change 1 — editor.css rules

**Must land before Task 3** (see the sequencing constraint above).

**Files:**
- Modify: `courses/static/courses/css/editor.css` — insert after the `.tabs-editor__label:focus` rule (~`:958-960`), before `.tabs-editor__ctl` (~`:961`); and modify `.tabs-editor__label` (~`:952-957`)
- Test: `tests/test_tabs_editor_partial.py`

**Interfaces:**
- Consumes: nothing.
- Produces: CSS rules for `.tabs-editor__count` (+ `[hidden]`, `.is-near`, `.is-at-cap`) and `.tabs-editor__status`. Task 3's markup relies on these existing; Task 4's JS toggles `is-near`/`is-at-cap`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tabs_editor_partial.py`. The module already defines an `EDITOR_CSS` path constant (used by `test_editor_css_styles_every_tabs_editor_class` at `:153`) — reuse it.

```python
def test_the_counter_is_removed_from_layout_when_hidden():
    """`.tabs-editor__row` is `display: flex; gap: var(--space-2)`, so a third flex
    item contributes a SECOND gap even while empty -- every row would permanently
    lose that much input width, for every author, below the threshold, and with JS
    disabled. The base rule declares `display: inline-flex`, which beats the UA
    `[hidden] { display: none }` regardless of specificity, so the paired rule is
    load-bearing rather than belt-and-braces."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert ".el-editor--tabs .tabs-editor__count[hidden]" in css
    block = _decl_block(css, ".el-editor--tabs .tabs-editor__count[hidden]")
    assert "display: none" in block


def test_the_counter_states_are_styled_and_at_cap_is_not_colour_alone():
    """A colour-only at-cap state is invisible to a colour-blind author. --danger is
    the token (a hard stop, not a caution); --text-tertiary is banned because it
    fails AA at body size."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    base = _decl_block(css, ".el-editor--tabs .tabs-editor__count")
    near = _decl_block(css, ".el-editor--tabs .tabs-editor__count.is-near")
    at_cap = _decl_block(css, ".el-editor--tabs .tabs-editor__count.is-at-cap")

    # The token caution is recorded AT BODY SIZE, so the size must be pinned or the
    # contrast claim is being judged against a different WCAG threshold.
    assert "font-size" in base, "counter size must be declared, not inherited"
    assert near.strip(), ".is-near carries no declarations"
    assert "--danger" in at_cap
    assert "font-weight" in at_cap, "at-cap must carry a non-colour signal too"
    assert "--text-tertiary" not in at_cap


def test_the_live_region_is_clip_based_never_display_none():
    """The region must stay in the a11y and text trees so aria-live announces it and
    Playwright can read it. display:none would make it a silently dead channel."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    block = _decl_block(css, ".el-editor--tabs .tabs-editor__status")
    assert "position: absolute" in block
    assert "clip:" in block
    assert "display: none" not in block


def test_the_label_input_has_a_non_zero_width_floor():
    """Adding a fourth fixed row item plus a second gap shrinks the label input at
    exactly the moment the author is typing a long label.

    Extract the VALUE and compare it. A plain `"min-width" in block` check stays
    green against the mutant, because `min-width: 0` is also a min-width declaration
    -- and so does the obvious-looking negative lookahead
    `re.search(r"min-width:\\s*(?!0\\b)", block)`: `\\s*` backtracks to zero
    characters, the lookahead is then evaluated at the SPACE rather than at the `0`,
    and it trivially succeeds. That form matches "min-width: 0;" and is completely
    inert. Verified by running it.
    """
    css = EDITOR_CSS.read_text(encoding="utf-8")
    block = _decl_block(css, ".el-editor--tabs .tabs-editor__label")
    m = re.search(r"min-width:\s*([^;}]+)", block)
    assert m, "label input declares no min-width at all"
    assert m.group(1).strip() not in ("0", "0px"), (
        "label input has no non-zero min-width floor"
    )
```

Add this helper next to them (the module already imports `re`; confirm before adding a duplicate import):

```python
def _decl_block(css, selector):
    """Slice the declaration block for an exact selector (see tests/test_tabs_css.py
    for why line matching is not sufficient)."""
    i = css.index("\n" + selector + " {")
    open_brace = css.index("{", i)
    return css[open_brace + 1 : css.index("}", open_brace)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -k "counter_is_removed or counter_states or live_region_is_clip or label_input_has_a_non_zero" -v`
Expected: **FAIL** — `_decl_block` raises `ValueError` (no such selectors yet) and the label floor is still `min-width: 0`.

- [ ] **Step 3: Add the CSS**

Insert after the `.el-editor--tabs .tabs-editor__label:focus` rule:

```css
/* Character counter. `display: inline-flex` here is what makes the paired [hidden]
   rule load-bearing: an author `display` beats the UA [hidden]{display:none}, and
   without the pair an empty span would still contribute a flex gap to every row.
   min-width is 5ch -- `ch` so the floor scales with font size; 5 is sized for the
   current TWO-DIGIT cap ("80/80") and would need revisiting if LABEL_MAX gained a
   digit. It does not track the digit count. */
.el-editor--tabs .tabs-editor__count {
  display: inline-flex; align-items: center; flex: 0 0 auto;
  min-width: 5ch; font-size: .82rem;
  font-variant-numeric: tabular-nums; color: var(--text-secondary);
}
.el-editor--tabs .tabs-editor__count[hidden] { display: none; }
.el-editor--tabs .tabs-editor__count.is-near { font-weight: 600; }
.el-editor--tabs .tabs-editor__count.is-at-cap { color: var(--danger); font-weight: 700; }
/* Locally-owned clip rule, mirroring .el--gallery .gallery__status and
   .el--tabs .tabs__status. Deliberately NOT the global .sr-only: that class has zero
   users repo-wide and no test pins it, so it is a plausible cleanup casualty -- and
   its loss would leave either a stray visible phrase in every tabs editor or a
   silently dead announcement channel. Must stay clip-based, never display:none. */
.el-editor--tabs .tabs-editor__status {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
```

Then change `.el-editor--tabs .tabs-editor__label`'s `min-width: 0` to:

```css
  flex: 1 1 auto; min-width: min(8rem, 100%);
```

Add this comment above that rule — the honest account matters, because the obvious reading of `min()` here is wrong:

```css
/* min(8rem, 100%) does NOT prevent the row overflowing: a percentage min-width
   resolves against the flex container's FULL inline size, not the space left after
   the badge, counter and buttons, so it stays 128px for every row wider than 128px --
   the whole at-risk band. Nor does it reduce grid inflation; raising this floor can
   only INCREASE .tabs-editor__rows' min-content contribution. All it buys over a bare
   8rem is less of that increase. The real gate is the screenshot check in the plan's
   Task 8. */
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -v`
Expected: **PASS** (all, including `test_editor_css_styles_every_tabs_editor_class`, which is still satisfied — extra CSS with no markup is fine).

- [ ] **Step 5: Falsify each test**

| Mutant | Must turn RED |
|---|---|
| Delete `.tabs-editor__count[hidden] { display: none; }` | `test_the_counter_is_removed_from_layout_when_hidden` |
| Reduce `.is-at-cap` to `color: var(--danger);` only | `test_the_counter_states_are_styled_and_at_cap_is_not_colour_alone` |
| Replace the `.tabs-editor__status` body with `display: none;` | `test_the_live_region_is_clip_based_never_display_none` |
| Revert the label to `min-width: 0` | `test_the_label_input_has_a_non_zero_width_floor` |

The last one is the important falsification: confirm it goes RED, proving the negative lookahead works where a plain substring check would not.

- [ ] **Step 6: Lint and commit**

```bash
cd "<worktree>"
uv run ruff check tests/test_tabs_editor_partial.py
uv run ruff format --check tests/test_tabs_editor_partial.py
git add courses/static/courses/css/editor.css tests/test_tabs_editor_partial.py
git commit -m "feat(tabs): style the editor label counter and its live region"
```

---

## Task 3: Change 1 — editor markup

**Depends on Task 2** (the class-scan test requires the CSS to exist first).

**Files:**
- Modify: `templates/courses/manage/editor/_edit_tabs.html` — root div (`:15-18`), the row's label input (`:51-53`), after `</ol>` (`:61`)
- Test: `tests/test_tabs_editor_partial.py`

**Interfaces:**
- Consumes: `.tabs-editor__count` / `.tabs-editor__status` rules from Task 2.
- Produces: `data-msg-cap` on `[data-tabs-editor]`; `[data-tab-num]` span per row; one `[data-tab-cap]` region per editor. Task 4's JS queries all three; Task 5's i18n test asserts on `data-msg-cap`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tabs_editor_partial.py`:

```python
def test_the_cap_message_rides_on_a_data_msg_attribute():
    """JS-built strings cannot call {% trans %}; tabs_editor.js reads them via
    label(root, key, fallback) off the [data-tabs-editor] root. Without the attribute
    the helper silently returns its English fallback forever."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert "data-msg-cap=" in html
    assert "{n}" in html and "{max}" in html


def test_each_row_carries_a_hidden_aria_hidden_counter():
    """Rendered empty and hidden: a server-rendered value is wrong the instant the
    author types, and `hidden` keeps the no-JS editor unchanged in layout too.
    aria-hidden because a bare "64/80" with no label is noise -- the live region is
    the announcement channel and it says what it means."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert html.count("data-tab-num") == 2
    assert html.count('class="tabs-editor__count"') == 2
    # Pin the WHOLE tag, in a fixed attribute order. Counting `hidden` or
    # `aria-hidden="true"` separately is not enough: `hidden` is the load-bearing
    # attribute (the no-JS layout and the "no permanent 0/80" argument both rest on
    # it) and a count of stray attributes elsewhere in the partial would mask its
    # removal. Keep Step 4's markup in exactly this order.
    span = '<span class="tabs-editor__count" data-tab-num aria-hidden="true" hidden>'
    assert html.count(span) == 2
    # The existing count assertion must not move.
    assert html.count("data-tab-row") == 2

    # POSITION, not just presence. The tag check above fixes the span's attributes and
    # their order but says nothing about where it sits: moving it after
    # .tabs-editor__ctl leaves every assertion above green, and the spec requires it
    # BETWEEN the input and the controls.
    first_row = html[: html.index("data-tab-row", html.index("data-tab-row") + 1)]
    assert (
        first_row.index("data-tab-label-input")
        < first_row.index("tabs-editor__count")
        < first_row.index("tabs-editor__ctl")
    )


def test_exactly_one_live_region_renders_outside_the_row_list():
    """One per EDITOR, not per row. A per-row region hidden below the threshold is
    inserted into the a11y tree already containing its text, which assistive tech
    generally does not announce -- dropping the announcement on exactly the case that
    matters most (one input event jumping straight to the cap).

    The placement check slices the list forward. Do NOT use
    `html.index("data-tab-cap") > html.rindex("</ol>")`: in the SERVED render
    (_served_tabs_form) the open form is emitted as the last <li> inside
    _editor_scope.html's own top-level <ol class="element-list">, whose </ol> follows
    data-tab-cap -- so that form goes RED against a correct implementation.
    """
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert html.count("data-tab-cap") == 1
    assert 'aria-live="polite"' in html
    assert 'class="tabs-editor__status"' in html

    start = html.index("data-tab-list")
    assert "data-tab-cap" not in html[start : html.index("</ol>", start)], (
        "the live region must sit outside [data-tab-list], not inside a row"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -k "cap_message_rides or hidden_aria_hidden_counter or one_live_region" -v`
Expected: **FAIL** — none of the three markup pieces exists.

- [ ] **Step 3: Add `data-msg-cap` to the root div**

In `_edit_tabs.html`, extend the `[data-tabs-editor]` div's attribute list (currently `data-msg-remove` and `data-msg-confirm`):

```html
     data-msg-confirm="{% trans 'Deleting this tab also deletes everything inside it.' %}"
     data-msg-cap="{% trans 'Tab {n} label limit reached — {max} characters' %}">
```

Copy the msgid **exactly**: em dash `—` (U+2014), and `{n}` / `{max}` as literal braces. Task 4's JS fallback literal must match it byte-for-byte, or the degraded path renders a different string.

- [ ] **Step 4: Add the digits span to each row**

Immediately after the `<input ... data-tab-label-input ...>` element and before `<span class="tabs-editor__ctl">`:

```html
      <span class="tabs-editor__count" data-tab-num aria-hidden="true" hidden></span>
```

Attribute naming is constrained: `test_tabs_editor_partial.py:42` asserts `html.count("data-tab-row") == 2`. `data-tab-num` does not contain that substring. **Do not** rename it `data-tab-row-count`.

- [ ] **Step 5: Add the live region after the row list**

Immediately after the `</ol>` that closes `[data-tab-list]`, before the "Add tab" button:

```html
  {% comment %}One live region per EDITOR, not per row, and never hidden: a region
  revealed from display:none already containing its text is generally not announced,
  which would drop the announcement on a paste straight to the cap. It is clipped by
  .tabs-editor__status (position:absolute) so it costs no layout in the flex row.{% endcomment %}
  <span class="tabs-editor__status" data-tab-cap role="status" aria-live="polite"></span>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -v`
Expected: **PASS** — all, including `test_editor_css_styles_every_tabs_editor_class` (Task 2 supplied both rules) and the untouched `data-tab-row` count.

- [ ] **Step 7: Falsify each test**

| Mutant | Must turn RED |
|---|---|
| Drop `data-msg-cap` from the root div | `test_the_cap_message_rides_on_a_data_msg_attribute` |
| Drop `hidden` from the digits span | `test_each_row_carries_a_hidden_aria_hidden_counter` |
| Drop `aria-hidden="true"` from the digits span | `test_each_row_carries_a_hidden_aria_hidden_counter` |
| Rename the digits span `data-tab-row-count` | `test_each_row_carries_a_hidden_aria_hidden_counter` (via the `data-tab-row` count) |
| Move the digits span **after** `<span class="tabs-editor__ctl">` | `test_each_row_carries_a_hidden_aria_hidden_counter` (via the ordering assertion — every other assertion in it stays green) |
| Move the live region inside the `<li>` (before `</ol>`) | `test_exactly_one_live_region_renders_outside_the_row_list` |
| Drop `aria-live="polite"` | `test_exactly_one_live_region_renders_outside_the_row_list` |

The "move it inside" mutant is the one that matters — confirm the **slice** assertion is what fails, not the count, since the count alone cannot see placement.

- [ ] **Step 8: Lint and commit**

```bash
cd "<worktree>"
uv run ruff check tests/test_tabs_editor_partial.py
uv run ruff format --check tests/test_tabs_editor_partial.py
git add templates/courses/manage/editor/_edit_tabs.html tests/test_tabs_editor_partial.py
git commit -m "feat(tabs): add the label counter markup and its live region"
```

---

## Task 4: Change 1 — `refreshCount` and wiring

**Depends on Task 3.**

**Files:**
- Modify: `courses/static/courses/js/tabs_editor.js`
- Test: `tests/test_tabs_editor_partial.py`

**Interfaces:**
- Consumes: `[data-tab-num]`, `[data-tab-cap]`, `data-msg-cap` from Task 3; `.is-near` / `.is-at-cap` from Task 2.
- Produces: `refreshCount(li, announce)` and `clearCapRegion()`, both inside `wire()`. Task 6's e2e drives the resulting behaviour.

- [ ] **Step 1: Read the file end to end**

Run: `cd "<worktree>" && uv run python -c "print(open('courses/static/courses/js/tabs_editor.js', encoding='utf-8').read())"`

You need the exact current shape of `wire()`, its four handlers, and its tail. Do not work from memory.

- [ ] **Step 2: Write the failing static-source tests**

Append to `tests/test_tabs_editor_partial.py`. These pin two contracts no behavioural test can see.

```python
def _slice(js, start_anchor, end_anchor):
    """Slice between two anchors, asserting each occurs exactly once first.

    Anchor uniqueness is not pedantry. The wire() tail is
    `refreshControlState(); syncLabelPosRow(); if (hidden.value === "") serialize();`
    -- but `refreshControlState();` occurs 3x in this file and `syncLabelPosRow();`
    2x, and both appear BEFORE the add handler. Choosing either as the tail marker
    inverts the add slice into a ValueError or an empty string, on which a
    "last index" comparison passes vacuously. Only `if (hidden.value === "")` is
    unique.
    """
    assert js.count(start_anchor) == 1, f"anchor not unique: {start_anchor}"
    assert js.count(end_anchor) == 1, f"anchor not unique: {end_anchor}"
    return js[js.index(start_anchor) : js.index(end_anchor)]


def test_refresh_count_is_the_last_statement_at_every_call_site():
    """The counter is an affordance, never a dependency -- true only if a throw
    inside it cannot abort the authoritative work. In wire()'s tail this is sharpest:
    on the ADD path `hidden.value` starts "", so a throw above
    `if (hidden.value === "") serialize();` would submit an EMPTY data field.
    """
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    tail = 'if (hidden.value === "")'

    slices = {
        "input handler": _slice(
            js, 'rows.addEventListener("input"', 'rows.addEventListener("click"'
        ),
        "add handler": _slice(js, 'addBtn.addEventListener("click"', tail),
        "init": _slice(js, tail, "function initTabsEditor"),
    }
    for name, body in slices.items():
        assert "refreshCount(" in body, f"{name}: no refreshCount call"
        assert body.rindex("refreshCount(") > body.rindex("serialize("), (
            f"{name}: refreshCount must come after serialize()"
        )
        assert "function refreshCount(" not in body, (
            f"{name}: the declaration must sit outside this slice, or the ordering "
            "assertion is satisfied vacuously by the declaration itself"
        )


def test_the_cap_phrase_substitutes_every_placeholder_occurrence():
    """String.replace with a string pattern replaces only the FIRST occurrence, and a
    translation may legitimately repeat a token. This static check is the only thing
    enforcing it: both catalogs contain each token exactly once, so a .replace chain
    produces an identical string and no behavioural assertion can tell the
    difference. Note tabs.js:275-276 uses the rejected form -- do not copy it."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    assert '.replace("{n}"' not in js
    assert '.replace("{max}"' not in js
    assert '.split("{n}")' in js and '.split("{max}")' in js


def test_the_js_fallback_matches_the_trans_msgid_byte_for_byte():
    """These two literals are written by DIFFERENT tasks with no shared memory, and
    the spec calls their identity load-bearing: when data-msg-cap is missing, label()
    falls back to the JS literal, so a stray en dash or a dropped space would make
    the degraded path render a different string from the normal one. Nothing else
    connects them."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    partial = (ROOT / "templates/courses/manage/editor/_edit_tabs.html").read_text(
        encoding="utf-8"
    )

    msgid = re.search(r"data-msg-cap=\"\{% trans '([^']+)' %\}\"", partial)
    fallback = re.search(r'label\(editor, "cap", "([^"]+)"\)', js)
    assert msgid, "no data-msg-cap {% trans %} in the partial"
    assert fallback, 'no label(editor, "cap", ...) fallback in the JS'
    assert msgid.group(1) == fallback.group(1), (
        f"msgid {msgid.group(1)!r} != JS fallback {fallback.group(1)!r}"
    )


def test_the_reorder_branches_only_clear_the_region():
    """Reorder RENUMBERS rows, so a phrase naming "Tab 2" would describe a different
    tab -- and worse, the stale text would suppress the next announcement via the
    change-guard. But the rows themselves move intact, so no refreshCount is needed
    or permitted here (the ordering test exempts this handler)."""
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    # End anchor is addBtn.addEventListener("click" -- NOT "if (addBtn)", which
    # occurs TWICE (`if (addBtn) addBtn.disabled = ...` in refreshControlState, and
    # `if (addBtn) {` before the add handler). _slice's uniqueness assertion would
    # fail on it against a correct build.
    click = _slice(
        js, 'rows.addEventListener("click"', 'addBtn.addEventListener("click"'
    )
    # Slice the two branches SEPARATELY. Slicing `up` to the end of the click handler
    # would include the down branch, so deleting the clear from only the up branch
    # would leave the down branch's call inside the slice and the mutant could not
    # go RED.
    up = click[click.index("[data-tab-up]") : click.index("[data-tab-down]")]
    down = click[click.index("[data-tab-down]") :]
    for name, branch in (("up", up), ("down", down)):
        assert "insertBefore" in branch, f"{name}: no insertBefore"
        assert "clearCapRegion()" in branch, f"{name}: region not cleared"
        assert "refreshCount(" not in branch, f"{name}: must not call refreshCount"
```

Confirm `TABS_EDITOR_JS` is the module's existing path constant (`test_editor_css_styles_every_tabs_editor_class` uses it) before adding one.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -k "last_statement_at_every_call_site or substitutes_every_placeholder or js_fallback_matches_the_trans_msgid or reorder_branches_only_clear" -v`
Expected: **FAIL — all four.** Step 2 adds four tests; selecting only three would leave the cross-file msgid/fallback guard never observed RED, and that is the only thing tying two literals written by two memoryless tasks together. (`fallback` is `None` at this point because no `label(editor, "cap", …)` call exists yet.)

- [ ] **Step 4: Add `refreshCount` and `clearCapRegion`**

Insert **after** `function syncLabelPosRow()`'s closing brace and **before** the `if (displaySel) displaySel.addEventListener(...)` line. (`syncLabelPosRow` sits between `refreshControlState` and the first listener — the declaration goes after *both* functions, immediately before the first `addEventListener`.) This position is deliberate: it keeps the declaration outside all three slices above, and outside the `function serialize` → `function refreshControlState` range that `test_serialize_reads_both_select_elements` already slices.

```js
    // Character counter. Rebuilds the row's entire counter state from `n` on every
    // call -- a pure function of the current value, never an incremental mutation, so
    // the at-cap state cannot be stranded when the author deletes back below the cap.
    function refreshCount(li, announce) {
      if (!li) return;
      var input = li.querySelector("[data-tab-label-input]");
      var num = li.querySelector("[data-tab-num]");
      if (!input || !num) return;
      // The server already wrote maxlength="{{ tb.label_max }}"; reading it back means
      // no new data-* plumbing and no way to drift from LABEL_MAX. Absent -> -1.
      var max = input.maxLength;
      if (!max || max < 0) {
        num.hidden = true;
        num.textContent = "";
        num.classList.remove("is-near", "is-at-cap");
        return;
      }
      var n = input.value.length; // UTF-16 units, matching what maxlength counts
      // 80 * 0.8 is exactly 64.0 in IEEE-754, so ceil and floor are indistinguishable
      // at the current cap; ceil is chosen for a LABEL_MAX where it is fractional.
      var threshold = Math.ceil(max * 0.8);
      var atCap = n >= max; // >= not ==, so an over-length value degrades sanely
      num.hidden = n < threshold;
      num.textContent = n < threshold ? "" : n + "/" + max;
      num.classList.toggle("is-near", n >= threshold && !atCap);
      num.classList.toggle("is-at-cap", atCap);
      if (!announce) return;
      var region = editor.querySelector("[data-tab-cap]");
      if (!region) return;
      var msg = "";
      if (atCap) {
        // {n} is the row's 1-based position -- NOT decoration. A row-agnostic phrase
        // would be byte-identical between rows, so the change-guard below would
        // suppress the write when a SECOND row reaches the cap and nothing would be
        // announced. split/join, never .replace: that replaces one occurrence only.
        msg = label(editor, "cap", "Tab {n} label limit reached — {max} characters")
          .split("{n}")
          .join(rowEls().indexOf(li) + 1)
          .split("{max}")
          .join(max);
      }
      // Guarded on change: `input` keeps firing at the cap in some browsers, and
      // re-assigning the same string replaces the text node -- a mutation many screen
      // readers announce again. Do not write "" over an already-empty region either.
      if (region.textContent !== msg) region.textContent = msg;
    }

    function clearCapRegion() {
      var region = editor.querySelector("[data-tab-cap]");
      if (region && region.textContent !== "") region.textContent = "";
    }
```

- [ ] **Step 5: Wire the four call sites**

**(a)** Delegated `input` handler — `refreshCount` **after** `serialize()`. The handler has only `e.target` in scope; there is no `li`:

```js
    rows.addEventListener("input", function (e) {
      if (!e.target.closest("[data-tab-label-input]")) return;
      serialize();
      refreshCount(e.target.closest("[data-tab-row]"), true);
    });
```

**(b)** Remove branch — `clearCapRegion()` as its last statement, since the removed row may be the one that produced the phrase:

```js
        li.remove();
        refreshControlState();
        serialize();
        clearCapRegion();
        return;
```

**(c)** Both reorder branches — `clearCapRegion()` last, **no** `refreshCount`:

```js
      if (e.target.closest("[data-tab-up]")) {
        var prev = li.previousElementSibling;
        if (prev) rows.insertBefore(li, prev);
        serialize();
        clearCapRegion();
        return;
      }
      if (e.target.closest("[data-tab-down]")) {
        var next = li.nextElementSibling;
        if (next) rows.insertBefore(next, li);
        serialize();
        clearCapRegion();
        return;
      }
```

**(d)** Add handler — clear first, then `refreshCount` genuinely last. The clone copies the digits span **including its text, class and `hidden` state**, so cloning an at-cap row would otherwise show a stale `80/80` on a brand-new empty input:

```js
        rows.appendChild(li);
        if (input) input.focus();
        refreshControlState();
        serialize();
        clearCapRegion();
        refreshCount(li, false);
```

**(e)** `wire()` tail — the init loop as the **last** statement of the function, after the existing `if (hidden.value === "") serialize();`:

```js
    if (hidden.value === "") serialize();
    // Init: a saved label may already be at 80, and the digits must be right before
    // the author touches anything -- the one path a delegated input listener cannot
    // cover. announce=false: opening an editor is not an event to announce.
    rowEls().forEach(function (li) { refreshCount(li, false); });
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -v`
Expected: **PASS** — all, including `test_serialize_reads_both_select_elements`, which requires `function serialize` to still precede `function refreshControlState` in file order.

- [ ] **Step 7: Falsify each test**

| Mutant | Must turn RED |
|---|---|
| Move `refreshCount(...)` above `serialize()` in the `input` handler | `test_refresh_count_is_the_last_statement_at_every_call_site` |
| Move the init loop above `if (hidden.value === "")` | same test |
| Move the `function refreshCount` declaration inside the add handler | same test (via the `"function refreshCount(" not in body` assertion) |
| Swap `.split("{max}").join(max)` for `.replace("{max}", max)` | `test_the_cap_phrase_substitutes_every_placeholder_occurrence` |
| Change the em dash in the JS fallback literal to a hyphen | `test_the_js_fallback_matches_the_trans_msgid_byte_for_byte` |
| Delete `clearCapRegion()` from the **up** branch only | `test_the_reorder_branches_only_clear_the_region` |
| Delete `clearCapRegion()` from the **down** branch only | same test |
| Add `refreshCount(li, true)` to the up branch | same test |

Run the up-branch-only and down-branch-only mutants **separately** — that is what proves the two branches are sliced independently rather than as one range.

- [ ] **Step 8: Lint and commit**

```bash
cd "<worktree>"
uv run ruff check tests/test_tabs_editor_partial.py
uv run ruff format --check tests/test_tabs_editor_partial.py
git add courses/static/courses/js/tabs_editor.js tests/test_tabs_editor_partial.py
git commit -m "feat(tabs): drive the label counter and its at-cap announcement"
```

---

## Task 5: i18n — translate the at-cap phrase

**Depends on Task 3** (the `{% trans %}` string must exist for `makemessages` to find it).

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` and both compiled `.mo`
- Test: `tests/test_tabs_editor_partial.py`

**Interfaces:**
- Consumes: the `data-msg-cap` msgid from Task 3.
- Produces: a Polish msgstr for it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tabs_editor_partial.py`. Model it on `tests/test_tabs_partial.py:421` — but the string lives in `_edit_tabs.html`, so the test belongs in **this** module.

```python
def test_the_cap_phrase_resolves_to_polish():
    """A .po-only change ships English to Polish users with every test green. This is
    the assertion that catches it -- and catches a fuzzy pre-fill left in place."""
    from django.utils import translation

    with translation.override("pl"):
        html = _render_form(TabsElement(data=TabsElement.default_data()))

    start = html.index("data-msg-cap=")
    value = html[start : html.index(">", start)]
    assert "limit reached" not in value, "data-msg-cap is still English under pl"
    assert "{n}" in value and "{max}" in value, (
        "both placeholders must survive translation as literal tokens"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "<worktree>" && uv run pytest tests/test_tabs_editor_partial.py -k "resolves_to_polish" -v`
Expected: **FAIL** — untranslated, so the English msgid renders under `pl`.

- [ ] **Step 3: Extract messages**

```bash
cd "<worktree>"
uv run python manage.py makemessages -l pl -l en
git -C "<worktree>" diff --stat locale/
```

Both catalogs move. `en` is a source catalog with empty msgstrs — harmless, but commit it so the branch is consistent.

- [ ] **Step 4: Clear any fuzzy pre-fill, then translate**

Open `locale/pl/LC_MESSAGES/django.po` and find the new msgid. If `makemessages` guessed a translation from a similar msgid it will be marked fuzzy:

```
#, fuzzy
msgid "Tab {n} label limit reached — {max} characters"
msgstr "<some WRONG guess copied from another string>"
```

**Clearing it is TWO deletions** — remove the `#, fuzzy` marker **and** the wrong `msgstr` body. Deleting only the marker leaves the wrong translation live. Then translate:

```
msgid "Tab {n} label limit reached — {max} characters"
msgstr "Karta {n}: osiągnięto limit etykiety — {max} znaków"
```

`{n}` and `{max}` are **literal tokens**, not prose — they must appear verbatim in the msgstr or the runtime substitution leaves a hole.

- [ ] **Step 5: Compile and verify**

```bash
cd "<worktree>"
uv run python manage.py compilemessages
uv run pytest tests/test_tabs_editor_partial.py -k "resolves_to_polish" -v
```
Expected: **PASS**.

- [ ] **Step 5b: Run the whole-catalog health guards — the narrow `-k` above cannot see them**

```bash
cd "<worktree>"
uv run pytest tests/test_i18n_po_health.py -v
```

`tests/test_i18n_po_health.py` owns three guards over the **entire** catalog:
`test_no_fuzzy_entries` (`:158`), `test_no_obsolete_entries` (`:167`) and
`test_pl_has_no_untranslated_msgid` (`:176`). `makemessages` runs `msgmerge`, which
routinely marks the catalog **header** `#, fuzzy` and writes `#~` obsolete blocks for
any string that has drifted since the catalogs were last regenerated — neither of
which is your new string, and neither of which Step 5's `-k` can see.

Any of the three would leave the suite RED at this task's boundary. Both catalogs are clean today (verified: zero `#, fuzzy`, zero `#~`), so anything these guards report is drift `makemessages` surfaced. Before committing:

- delete any `#, fuzzy` on the **header** entry (the one with the empty msgid),
- delete any `#~`-prefixed obsolete blocks `makemessages` introduced,
- if `test_pl_has_no_untranslated_msgid` reports msgids **other than your new one**, those are pre-existing strings the regeneration exposed: translate them if they are obviously translatable, otherwise record each one explicitly in your task report for Task 9 to sweep. Do not leave the guard red and do not silently blank it.
- re-run `compilemessages` and this test file.

Expected: **PASS**. If a guard still fails on an entry unrelated to this change, say so
explicitly in your task report — Task 9 sweeps flagged-but-unfixed items, and this is
exactly the kind that gets scrolled past.

- [ ] **Step 6: Falsify**

| Mutant | Must turn RED |
|---|---|
| Restore `#, fuzzy` on the entry and recompile | `test_the_cap_phrase_resolves_to_polish` |
| Blank the `msgstr` and recompile | same test |

Recompile after reverting.

- [ ] **Step 7: Commit — including both binary `.mo` files**

```bash
cd "<worktree>"
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git add locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo
git add tests/test_tabs_editor_partial.py
git commit -m "i18n(tabs): translate the tab label cap announcement"
```

Confirm with `git -C "<worktree>" show --stat HEAD` that **both** `.mo` files are in the commit. A missing `.mo` ships English with every test green.

---

## Task 6: e2e — counter behaviour

**Depends on Tasks 2-5.**

**Files:**
- Test: `tests/test_e2e_tabs.py`

**Interfaces:**
- Consumes: the full Change 1 stack.
- Produces: nothing.

- [ ] **Step 1: Read the existing helpers**

Run: `cd "<worktree>" && sed -n '55,115p' tests/test_e2e_tabs.py`

You need `_make_pa_user` (~`:55`), `_login` (~`:69`), `_seed_unit` (~`:77`), `_editor_url` (~`:88`) and `_seed_tabs_element` (~`:101`). Use them; do not invent fixtures.

Also read one existing editor-driving case end to end — `tests/test_e2e_tabs.py:1634-1646` is a good one — so you copy the real open-the-form gesture rather than reconstructing it.

- [ ] **Step 2: Write the failing e2e cases**

Add to `tests/test_e2e_tabs.py`, following the module's existing marker/fixture style.

**Input-method rules, per the spec — these are not stylistic:**
- `fill()` sets the value and fires **one** `input` event; `press_sequentially()` fires one per character and costs real wall-clock.
- Every `fill()` string must be **exactly** the intended length — never longer. Whether `fill()` respects `maxlength` depends on the injection path.
- Use plain single-width characters, no leading/trailing/repeated whitespace, no `&` entities, so a value that round-trips the server survives `sanitize_label` unchanged.
- Assert `input.value.length` before asserting on the counter wherever length matters.

**Worked example — case 1 of the nine in the table below.** Write the remaining **eight** in this style, substituting the module's actual fixture names once you have read them in Step 1. Every one of them needs the same open-the-form and ready-flag gestures shown here, and every subsequent locator must be scoped with `[data-edit-slot]`.

**The editor URL alone does not render the tabs editor.** `[data-tab-row]` lives in `_edit_tabs.html`, which renders only when an element's edit form is *open*; `courses/views_manage.py:1510` defaults `open_form_pk=""`, so a plain GET shows the element list and no form. Every case must click the row's edit action first, exactly as the existing cases do — waiting on `[data-tab-row]` straight after `goto()` just times out.

Four more facts about this module you must not get wrong — all verified in the worktree:

- `_seed_unit(owner, slug)` returns **`(course, unit)`**, and `_editor_url(live_server, course, unit)` takes **three** arguments (`:78`, `:89`). Unpacking it as a single `unit` makes every downstream call fail.
- `_seed_tabs_element(...)` returns **`(obj, join)`**. You need `join.pk` to address the row's edit button.
- After the fragment swap, `wire()` sets `editor.dataset.tabsEditorReady = "1"` (`tabs_editor.js:19`) — which renders as the attribute **`data-tabs-editor-ready`**. `wait_for_selector` on the editor node alone resolves the moment it attaches, so a `fill()` can fire `input` *before* the delegated listener exists: the counter never updates and the case fails against a correct build (or an `is_hidden()` assertion passes vacuously). Wait on the ready attribute, not the node.
- The module sets `pytestmark = pytest.mark.e2e` at `:41`, so a per-test `@pytest.mark.e2e` is redundant. What each test **does** need is `@pytest.mark.django_db(transaction=True)` — every existing case has it, and without it rows written by the seed persist between cases, so the second case cloned from this example dies on a duplicate-username `IntegrityError`. **Give every case a distinct username and course slug.**
- The module does **not** import `expect` and has zero `expect(` call sites; existing cases use `wait_for_selector` plus plain `assert`. Follow that style rather than adding a new assertion vocabulary.

```python
@pytest.mark.django_db(transaction=True)
def test_the_counter_appears_only_at_the_threshold(live_server, page):
    """Below the threshold the counter is hidden entirely: a permanent 0/80 on up to
    MAX_TABS rows is noise that trains an author to stop reading it."""
    owner = _make_pa_user("counter_threshold_owner")
    course, unit = _seed_unit(owner, "counter-threshold")
    _obj, join = _seed_tabs_element(
        unit, [("t000001", "Tab 1"), ("t000002", "Tab 2")]
    )

    _login(page, live_server, "counter_threshold_owner")
    page.goto(_editor_url(live_server, course, unit))
    # Open the element's edit form -- the tabs editor does not exist until then.
    page.wait_for_selector('[data-scope="editor"] .el-row--tabs')
    page.locator(
        f'[data-scope="editor"] [data-element="{join.pk}"] .el-act-edit'
    ).first.click()
    # Wait for the READY flag, not just the node: wire() sets it after insertion, and
    # a fill() before that fires `input` with no delegated listener attached.
    page.wait_for_selector("[data-edit-slot] [data-tabs-editor][data-tabs-editor-ready]")

    row = page.locator("[data-edit-slot] [data-tab-row]").first
    label_input = row.locator("[data-tab-label-input]")
    digits = row.locator("[data-tab-num]")

    # 63 = threshold - 1. fill() is one input event and is cheap; the boundary is then
    # crossed by a single real keystroke so the per-keystroke path is exercised.
    label_input.fill("x" * 63)
    assert label_input.evaluate("el => el.value.length") == 63
    assert digits.is_hidden()

    label_input.press_sequentially("x")
    assert label_input.evaluate("el => el.value.length") == 64
    assert digits.is_visible()
    assert digits.text_content() == "64/80"
    cls = digits.get_attribute("class") or ""
    assert "is-near" in cls
    assert "is-at-cap" not in cls
```

**Test function names are mandated, not suggested.** Step 3's `-k` expression is derived from them, and a case named something else is silently deselected — which the plan elsewhere warns is not a pass. Use exactly these:

| # | Case | Test function name |
|---|---|---|
| 1 | threshold boundary | `test_the_counter_appears_only_at_the_threshold` |
| 2 | at cap | `test_the_counter_and_region_report_the_cap` |
| 3 | jump to cap | `test_a_single_event_jump_to_the_cap_still_announces` |
| 4 | second row to cap | `test_a_second_row_reaching_the_cap_announces_too` |
| 5 | descend | `test_descending_below_the_cap_clears_both_signals` |
| 6 | init | `test_a_stored_at_cap_label_shows_the_counter_at_first_paint` |
| 7 | add tab | `test_adding_a_tab_resets_the_cloned_counter` |
| 8 | remove | `test_removing_the_at_cap_row_clears_the_region` |
| 9 | reorder | `test_reordering_clears_the_region_so_the_next_cap_announces` |

Cases to write, each with its named mutant:

1. **threshold boundary** — as written above.
   *Mutants:* `n < threshold` → `n <= threshold`; the `0.8` fraction → `0.75`.
   **Not** `Math.ceil` → `Math.floor`: `80 * 0.8` is exactly `64.0`, so that mutation is a no-op at the current cap and can never go RED.
2. **at cap** — `fill()` to 79, then `press_sequentially("x")` → `.is-at-cap`, `[data-tab-cap]` holds the phrase with the row number and `80` interpolated, and contains no residual `{`.
   *Mutant:* delete the `.is-at-cap` branch.
3. **jump to cap** — a single `fill()` carrying the value from below `max - 1` straight to 80 → the region receives the phrase. No emptying step needed: a default row already holds `"Tab 1"` (5 chars). The discriminating property is one `input` event spanning the gap.
   *Mutant:* announce only when the previous length was exactly `max - 1`. Name it that precisely — the looser "conditional on previous state" invites `if (!wasAtCap && n >= max)`, which still announces here and cannot go RED.
4. **second row to cap** — fill **row 1** to 80 (region now holds row 1's phrase), then fill **row 2** straight to 80 → the region carries **row 2's** phrase (assert the row number in the text differs from row 1's).
   This is the only behavioural test of the interaction the spec devotes an entire section to ("Why the phrase names the row"). Without it the suppression hole ships untested: nothing else in this suite drives a *second distinct row* to the cap.
   *Mutant:* make the phrase row-agnostic (drop the `{n}` interpolation) and keep the plain `textContent` change-guard — the intended string is then byte-identical to what the region already holds, the guard suppresses the write, and nothing is announced.
5. **descend** — from 80, `press("Backspace")` once → digits `79/80`, `.is-near` present **and `.is-at-cap` absent**, phrase cleared; then `fill()` to 63 → digits `hidden`.
   The `.is-at-cap`-absent assertion is load-bearing: an add-only class implementation (`if (n >= max) cls.add("is-at-cap")`, no removal) passes every other assertion here while showing the author bold red `79/80`. The single `Backspace` matters — a `fill("")`-then-`fill()` sequence would not exercise the at-cap → is-near transition.
   *Mutants:* drop the `classList.toggle`'s removal / use add-only handling; make `refreshCount` append rather than rebuild.
6. **init** — open the editor on an element whose **stored** label is already 80 characters (seeded per the character rules above), assert `input.value.length == 80`, then assert the at-cap digits at first paint before any keystroke **and** that the region is empty.
   *Mutants:* delete the init loop; pass `announce = true` at init.
7. **add tab** — fill the **last** row (`[data-tab-row]:last-of-type`) to 80, then "Add tab" → the new row's digits are `hidden`, empty and carry no `.is-at-cap`; region empty.
   Filling the **last** row is mandatory: the add handler clones `existing[existing.length - 1]`, so filling row 1 of 2 would clone the untouched row 2 — already hidden and empty — and the first mutant would stay GREEN.
   *Mutants:* remove `refreshCount` from the add handler; remove `clearCapRegion()` from it.
8. **remove** — **two** preconditions, both required or the case goes RED against a correct build while its mutant is also RED, discriminating nothing:
   - Seed **three** tabs (`_seed_tabs_element`) or click "Add tab" first, and assert the Remove button is enabled. `MIN_TABS = 2` gates it twice — `disabled = n <= minTabs` (`tabs_editor.js:58`) and an early `return` (`:84`).
   - Register `page.once("dialog", lambda d: d.accept())` **before** clicking. `tabs_editor.js:85` is `window.confirm(...)`, and **Playwright auto-dismisses dialogs when no listener is attached** — a dismissed confirm returns `false`, so `li.remove()` never runs. This file has no dialog handling today; the trap is written out at `tests/test_e2e_spanning_merge.py:8-15`.

   Then fill a row to 80, remove it, **assert the `[data-tab-row]` count dropped 3 → 2**, and finally assert the region is empty.
   *Mutant:* delete `clearCapRegion()` from the remove branch.
9. **reorder** — fill row 2 to 80; click Move up; **assert `[data-tab-cap]` is empty at this point**; then fill the row now at position 2 to 80 → the region carries the phrase again.
   The mid-sequence assertion is the only discriminating one: at the **end** both builds read identically (correct = cleared then rewritten; mutant = never cleared, so the change-guard suppresses the rewrite and the same text remains).
   *Mutant:* delete `clearCapRegion()` from the reorder branches.

*Sync on conditions, never sleeps.* This element has a known init-time transition window — a bare `wait_for_selector` can resolve mid-transition, so negative visibility assertions need a settled condition.

- [ ] **Step 3: Run to verify they pass — then falsify in Step 4**

There is no RED→GREEN cycle available here: the implementation already landed in Tasks 2-5, so these cases are expected to pass on first run. Their falsification is Step 4, and that is what earns them.

Run, using the mandated names from the table above:

```bash
cd "<worktree>"
uv run pytest tests/test_e2e_tabs.py -m e2e -v -k "\
the_counter_appears_only_at_the_threshold or \
the_counter_and_region_report_the_cap or \
a_single_event_jump_to_the_cap_still_announces or \
a_second_row_reaching_the_cap_announces_too or \
descending_below_the_cap_clears_both_signals or \
a_stored_at_cap_label_shows_the_counter_at_first_paint or \
adding_a_tab_resets_the_cloned_counter or \
removing_the_at_cap_row_clears_the_region or \
reordering_clears_the_region_so_the_next_cap_announces"
```

Confirm the report says **9 passed**. Exit code 5 or a smaller count means cases were deselected by a name mismatch — that is not a pass.

- [ ] **Step 4: Falsify every case**

Apply each mutant from Step 2's list one at a time, confirm the named case goes RED, revert. If any mutant leaves the suite green, **fix the assertion** — do not skip it and do not change working code to make it fail.

- [ ] **Step 5: Lint and commit**

```bash
cd "<worktree>"
uv run ruff check tests/test_e2e_tabs.py
uv run ruff format --check tests/test_e2e_tabs.py
git add tests/test_e2e_tabs.py
git commit -m "test(tabs): e2e coverage for the label counter and its announcement"
```

---

## Task 7: e2e — strip wrapping

**Depends on Task 1.**

**Files:**
- Test: `tests/test_e2e_tabs.py`

- [ ] **Step 1: Read the existing helpers**

Run: `cd "<worktree>" && sed -n '55,115p' tests/test_e2e_tabs.py`

You need `_make_pa_user`, `_login`, `_seed_unit` and `_seed_tabs_element`, plus **`_lesson_url(live_server, unit)`** (`:92`) — this task drives the **student** page, not the editor, so it does not use `_editor_url` and needs none of Task 6's open-the-edit-form gesture.

Note the same three module facts Task 6 records: `_seed_unit` returns `(course, unit)`; the module already sets `pytestmark = pytest.mark.e2e` so each case needs `@pytest.mark.django_db(transaction=True)` and a **distinct username and course slug**; and the module uses `wait_for_selector` + plain `assert`, not `expect`.

- [ ] **Step 2: Write the case**

Name it **`test_a_long_tab_label_wraps_within_the_width_cap`** — Step 3's `-k` depends on it.

Sequence: seed a tabs element whose `display` stays **`"tabs"`** (the default — `.tabs__tab` exists only in the tabs branch of `tabs.js`; in carousel mode there is no strip and the case has nothing to assert on), with the **80-character label first** and a short label second. Log in, `page.goto(_lesson_url(live_server, unit))`, then `page.wait_for_selector(".tabs__tab")` so the enhancer has built the strip.

Address the long tab as `page.locator(".tabs__strip .tabs__tab").first` (seeding order fixes which that is). Getting this wrong is a confusing false RED: `.tabs__strip` stretches every tab to equal height, so the *height* assertion passes on either tab while the 288px *width* assertion fails on the short one.

Pin the viewport so the expected pixel value is computable:

```python
page.set_viewport_size({"width": 1280, "height": 900})
```

At 1280px, `min(18rem, 55vw)` = `min(288px, 704px)` = **288px**. Choosing the `18rem` arm also sidesteps Chromium measuring `vw` against the viewport *including* the classic scrollbar.

Assertions on a tab whose label is 80 characters:

- `clientWidth` is **288px within a small tolerance** — assert at/near that value, **not** merely `<= the cap`. On a wide viewport `<= 55vw` is vacuously true and would stay green against a deleted `max-width`. `clientWidth` equals the border-box width here only because `.tabs__tab` sets `border: 0` on the horizontal edges.
- To prove it **wrapped**, assert on content height: `clientHeight >= 2 * lineHeight + 24`.

  The arithmetic matters. `clientHeight` is the padding box; with `padding: 12px` top and bottom and an inherited `line-height` of 24px (1.5 × 16px, `font: inherit`), a **single-line** tab measures `24 + 24 = 48px` — *exactly* `2 × line-height`. So a naive "at least twice the line-height" check passes against an unwrapped tab. The `+ 24` makes the bar 72px: a single line fails at 48, a ~3-line 80-character label clears it at ~96.
- **Do not** compare against a short tab in the same strip. `.tabs__strip` stretches every tab to equal height, so those two numbers are equal by design and the test would fail against a *correct* implementation.

*Mutant:* delete the `max-width` declaration — confirm it goes RED on the **height** assertion specifically, not only on the width one.

- [ ] **Step 3: Run, falsify, commit**

```bash
cd "<worktree>"
uv run pytest tests/test_e2e_tabs.py -m e2e -k "a_long_tab_label_wraps_within_the_width_cap" -v
```

Confirm **1 passed** — exit code 5 or 0 selected means the name does not match.

Then apply the mutant (delete `max-width: min(18rem, 55vw);` from `courses.css`), confirm the **height** assertion goes RED specifically, and revert.

```bash
cd "<worktree>"
uv run ruff check tests/test_e2e_tabs.py
uv run ruff format --check tests/test_e2e_tabs.py
git add tests/test_e2e_tabs.py
git commit -m "test(tabs): e2e coverage for the wrapped tab width cap"
```

---

## Task 8: Screenshot verification

**Depends on Tasks 1-7.** Three fixtures, **light and dark judged separately** — dark is not a recolour of light. None of these is provable from the DOM, which is why this is a task and not an assertion.

**Files:** none committed except the report; capture screenshots to the scratchpad.

- [ ] **Step 0: Clone the existing harness — do not invent one**

Run: `cd "<worktree>" && sed -n '1785,1850p' tests/test_e2e_tabs.py`

`test_carousel_screenshots_light_and_dark` (`:1790`) is a working model for exactly this job and is the harness to copy: it seeds fixtures, drives both themes and writes to `tmp_path`.

The one thing that is easy to get wrong, and which that test's own docstring records: **for dark mode set `User.theme`, not the `libli_theme` cookie** — an authed user's theme wins outright in `_resolve_theme_pref`, so the cookie is ignored and you would silently capture two light screenshots and "verify" dark against them.

Judge the two themes **separately**. A dark screenshot is not verified by a light one passing.

- [ ] **Step 1: An 80-character label in a strip**

Confirm it wraps, every tab in the strip is equal height, and the active-tab underline sits on one baseline.

- [ ] **Step 2: A tab whose label carries a multi-base formula wider than the cap**

Use `\(a + b = c + d + e + f\)` — KaTeX splits this into several `.base` spans. A single-base fixture such as `\(\frac{a}{b}\)` is **structurally incapable** of showing the behaviour under test, because what is being checked is whether rule (b) holds the bases together.

Confirm it does not break mid-expression, that the line box contains its vertical extent without clipping, and **record how far it overflows the cap and how the overlap with the neighbouring tab looks** — this is the accepted edge, and the screenshot is the only thing that shows how bad it really is.

- [ ] **Step 3: A tabs editor at the deepest legal nesting level in the narrowest realistic editor pane, with a row at the cap**

Pin the numbers so the gate is reproducible rather than a judgement call:

- **Viewport:** `page.set_viewport_size({"width": 1280, "height": 900})`, the same width Task 7 uses.
- **View mode: `split`.** Viewport width alone does not determine the pane width — `editor.html:86-88` ships a three-way toggle (`data-view="editor" | "split" | "preview"`) and the pane follows it. `split` is the narrowest realistic case and is already `is-active` by default; assert that (`[data-view="split"].is-active`) or click it explicitly, and state in the report which mode the measurement was taken in. Without this, two agents get different numbers and both claim the gate passed.
- **Nesting depth: 3.** Use that number literally. `courses/builder.py:56` defines `MAX_NEST_DEPTH = 4` with the comment "a top-level element has depth 1", and `builder.py:300-308` caps a **container** at `MAX_NEST_DEPTH - 1` = 3. So 3 is the deepest a tabs element can legally sit; seeding it at 4 is rejected and this step becomes unbuildable. (Do not grep for lowercase `max_nest_depth` — that matches only the two context-dict lines in `views_manage.py` and never shows a value.)
- **Fixture source:** `tests/test_carousel_screenshots_light_and_dark` seeds a flat, top-level, *student-page* carousel and cannot produce a nested editor fixture. Take the nesting from `tests/test_e2e_depth3.py` (the parent + `tab_id` seeding pattern around `:306-380`) and the light/dark theme mechanics from the carousel screenshot test. This step is the combination of the two.
- **What to measure:** the row's `scrollWidth` vs `clientWidth`. Overflow means `scrollWidth > clientWidth` on `.tabs-editor__row`; report both numbers, not an impression.

**This is the real gate on the `min-width` floor** — the declaration alone does not guarantee it, and the Task 2 comment says so explicitly: `min(8rem, 100%)` resolves to 128px for every row wider than 128px, which is the whole at-risk band. If the row overflows, the remedy is to lower the floor or let the counter be the item that yields. Report it rather than accepting it.

- [ ] **Step 4: Report**

State plainly what each screenshot showed, in both themes. If any of the three is unsatisfactory, say so and stop — do not proceed to the branch gate with a known visual regression.

---

## Task 9: Branch gate

**Depends on all previous tasks.** This is the only place a whole-repo sweep belongs.

- [ ] **Step 1: Full test suite**

```bash
cd "<worktree>"
uv run pytest --verbosity=0
```

Then the e2e suite (separately, and never concurrently with the above):

```bash
uv run pytest -m e2e --verbosity=0
```

**Use `--verbosity=0`, not `-q`.** `pyproject.toml:49` already sets `addopts = "-q -m 'not e2e'"`, so adding `-q` yields `-qq`, which suppresses the short test summary — the branch gate's own output would then hide *which* tests failed.

- [ ] **Step 2: Both lint steps**

```bash
cd "<worktree>"
uv run ruff check .
uv run ruff format --check .
```

**Both.** PR #219 passed `check` and failed CI on `format --check`, because a "wrap to 88 columns" instruction makes implementers wrap defensively and `format --check` rejects unnecessary wrapping. If `format --check` reports files, run `uv run ruff format <files>` and commit the result.

- [ ] **Step 3: Sweep every flagged-but-unfixed item**

Re-read each task report from this plan. Any lint nit, stale comment, unrelated failure or "Task N may want to look at this" that was **mentioned but not fixed** gets fixed now or explicitly recorded as out of scope with a reason. This step exists because #219's CI failure was flagged by a subagent, read once, and scrolled past.

- [ ] **Step 4: Confirm the diff is what the spec describes**

```bash
cd "<worktree>"
git diff --stat origin/master...HEAD
```

Expect exactly: `courses.css`, `editor.css`, `_edit_tabs.html`, `tabs_editor.js`, `tests/test_tabs_css.py`, `tests/test_tabs_editor_partial.py`, `tests/test_e2e_tabs.py`, four `locale/` files, and the spec + plan documents. **Anything else is a mistake** — in particular `tabs.js`, `tabselement.html`, `models.py` and any migration must be untouched.

- [ ] **Step 5: Commit any gate fixes**

```bash
cd "<worktree>"
git status --porcelain
```

Inspect that output and stage **explicit paths only** — the files `ruff format` rewrote, nothing else:

```bash
git add <each reformatted file>
git commit -m "chore(tabs): branch gate fixes"
```

**Do not use `git add -A`.** It would stage any untracked byproduct sitting in the worktree — screenshots, crash dumps (the repo already carries a stray `bash.exe.stackdump`), scratch files — committing exactly what Step 4 just declared a mistake.

Skip if the gate was clean.
