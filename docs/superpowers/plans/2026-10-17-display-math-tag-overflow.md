# Numbered display maths tag overflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Equation numbers of an overflowing numbered KaTeX display sit after the widest line, with a 1em gap, and scroll into view with it. A fitting display keeps vendor geometry.

**Architecture:** A CSS-only flex layout on `.katex-html` scoped to tagged displays: an equal-weight `::before` spacer, an in-flow `.tag` spacer with its number flush right, and a 1em margin on the tag's first child. Table widgets opt out. The tests are Playwright e2e A/B tests against the same page with the new rules deleted through CSSOM.

**Tech Stack:** CSS (`courses/static/courses/css/courses.css`), pytest + pytest-playwright e2e, vendored KaTeX.

**Spec:** `docs/superpowers/specs/2026-10-17-display-math-tag-overflow-design.md`. Read it fully before starting. Its CSS block, opt-out section, ink definition, fixtures, assertions 1–7 and falsification table are normative.

## Global Constraints

- CSS only. No JS, template or KaTeX change.
- The new block goes directly after the #292 prose scroller opt-out in courses.css (`.el--math .katex-display, .el--table .katex-display, .el--filltable .katex-display { overflow: visible; padding-block: 0; }`, ~line 1874–1879).
- Main selector chain, verbatim: `.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline))`. Opt-outs are the same chain prefixed with `.el--table ` / `.el--filltable `.
- Gap = `margin-inline-start: 1em` on `… > .tag > :first-child`.
- Main rules carry no shrink guards (`flex: none`, `min-width: max-content`). Opt-outs set nothing on `::before` or on the tag's `flex`.
- Tag "ink" = the union of rects of the tag's leaf descendant elements with width > 0, excluding `.strut`, `.pstrut` and `.vlist-s`. Never use `.tag`'s own box.
- Tolerance: 0.5px. 1em = the computed font-size of the tag's first child.
- Every pytest command from the worktree is prefixed with `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_tagovf`. Start the test DB container first: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. Never pass `-q`. e2e needs `-m e2e`. Run long commands in the FOREGROUND with a timeout. Do not background pytest.
- Never revert a mutant with `git checkout`. Edit it back by hand and check `git diff`.
- Comments follow courses.css house style: what the rule does, the mechanism, what was measured. Django templates are not touched.

## Review Focus

1. **A tagged display inside a callout / tabs / question stem** (`.callout__child .katex-display`). The selector is surface-agnostic, so this should work, and wide prose is the same path. Covered by the prose fixtures. Reviewer: check that no callout rule re-absolutises `.tag`. The grep is in Task 2, Step 6.
2. **Dark theme.** Pure layout, so no colour is involved, but the screenshots in Task 3 are taken in both themes.
3. **An auto-numbered `align` after other numbered displays on the same page.** The CSS counter yields (10), (11), and so on, so the ink is wider than a fresh (1). The ink union handles this. fit-mixed pins it with 11 rows.
4. **The editor live preview (`.math-live`)** renders the same KaTeX outside `.el--math`. The rule applies there too, unscroll-ed, which is accepted: it has no scroller, so an overflow just extends as before. No test.
5. **Quiz slides.** Same KaTeX path, so the prose / `.el--math` fixtures cover it.

---

### Task 1: Failing e2e A/B tests

**Files:**
- Create: `tests/test_e2e_display_math_tag_overflow.py`

**Interfaces:**
- Produces, module-level, used by Tasks 2 and 3:
  - `_open(page, live_server, username, slug, element) -> None`. Seeds a course and unit with `_make_pa_user`/`_login`/`_seed_course_and_unit` from `tests.test_e2e_editor` and `add_element` from `tests.factories`. `element` is a saved model instance. Navigates to `courses:lesson_unit` and waits for `.katex-html > .tag`, or `.katex-html > .base` for the untagged case. Then waits on `document.fonts.ready` and asserts `document.fonts.check("1em KaTeX_Main")`.
  - `_measure(page, surface) -> dict`. `surface` is `"prose"` (display `.el--text .katex-display`, scroller = that display) or `"math"` (display `.el--math .katex-display`, scroller = `.el--math`). Returns `{bases: [rect], base_union: rect, ink: rect, leaves: [rect], html: rect, scroller: rect, em: float, scroll_max: float}`. `scroller` is the CLIENT rect (`left + clientLeft`, width `clientWidth`, same for top/height), not the border box, with rects as `{left, right, top, bottom}` in viewport px. `leaves` are the ink leaves in document order.
  - `_scroll_to_end(page, surface) -> None`. Sets the scroller's `scrollLeft` to `scrollWidth`.
  - `_strip_new_rules(page) -> int`. Walks `document.styleSheets` (try/catch per sheet), recursing into grouping rules. Calls `deleteRule` on every rule whose `selectorText` contains `:has(> .tag)`, iterating indices backwards, and returns the count.
  - `_vendor_leg(page, surface) -> None`. Calls `_strip_new_rules`, asserts the count `== 13`, asserts the `.tag` computes `position: absolute`, and asserts `.tag > :first-child` computes `margin-inline-start: 0px`.
  - LaTeX constants: `WIDE`, `FIT_MIXED`, `MULTI_BASE`, `NEAR_FIT_PROSE`, `NEAR_FIT_MATH`.

- [ ] **Step 1: Write the fixtures and helpers.** Build every LaTeX string with raw strings. Starting candidates follow; tune them in Step 3.
  - `WIDE`: the owner's case. `\begin{align}|P(A)P(B)| &= \sqrt{((2-y_A)-(2-y_B))^2+((x_A+1)-(x_B+1))^2}\\ &= \sqrt{(-y_A+y_B)^2+(x_A-x_B)^2}\\ &= |AB|\end{align}`
  - `FIT_MIXED`: `r"egin{align}" + r"\ ".join(r"a_{%d}&=b" % i for i in range(1, 12)) + r"\end{align}"`. It must be inside an `align`, or no tag is emitted.
  - `MULTI_BASE`: `x = \frac{a}{b} + y \tag{3}`
  - `NEAR_FIT_*`: `\hspace{Npx} x = y + z \tag{1.2.3}`, with N tuned per surface.

  Prose bodies are `<p>\[…\]</p>` in a `TextElement`. Math is `MathElement(latex=…)` with no delimiters.

- [ ] **Step 2: Write the tests,** one per spec assertion, parametrised over `surface in ("prose", "math")` where the spec says so. Viewport is `page.set_viewport_size({"width": 390, "height": 900})` unless 1280 is named. Order per spec: new-build measurements at every width first, then `_vendor_leg`, then vendor measurements, resizing for each.
  - `test_tag_clears_formula_at_scroll_start[surface, fixture∈{wide, near}]` (assertion 1): `ink.left >= base_union.right + em - 0.5`. Also run the same check on the vendor leg and assert it is **False**, which proves the fixture reproduces the defect.
  - `test_tag_reachable_and_clear_at_scroll_end[surface]` (assertion 2, wide): after `_scroll_to_end`, the ink lies inside the `scroller` client rect ±0.5 and `ink.left >= base_union.right + em - 0.5`. Assert the same check is False on the vendor leg. Call `_scroll_to_end` again AFTER `_vendor_leg`, because stripping changes `scrollWidth`.
  - `test_fitting_display_matches_vendor[surface, fixture∈{fit_mixed, multi_base}]` (assertion 3): width is NOT a parameter. In one page, measure 390, then resize and measure 1280, then `_vendor_leg`, then measure 1280, then resize and measure 390. Every base rect, the ink rect and every leaf rect equal vendor within 0.5 at each width.
  - `test_numbers_level_with_rows[surface, fixture∈{fit_mixed, multi_base, wide, near}]` (assertion 4): `ink.top - html.top` and `ink.bottom - html.bottom` equal vendor within 0.5.
  - `test_near_fit_does_not_overflow[surface]` (assertion 5): scroller `scrollWidth <= clientWidth + 1`. New build only, no `_vendor_leg`.
  - `test_table_widgets_keep_vendor_tag[widget∈{table, filltable}]` (assertion 6): a `TableElement` (`{"cells": [[{"html": r"\[" + FIT_MIXED + r"\]", "halign": "left"}]]}`), or a `FillTableElement` with a `"kind": "static"` cell of the same content. Expect `.katex-html` display `block`, tag position `absolute`, tag `textAlign` == its parent's, the first child's `marginInlineStart == "0px"`, and the first child's `textAlign` == `.katex-html`'s.
  - `test_untagged_display_untouched`: an `align*` prose display whose `.katex-html` computes `display: block`.
  - `test_page_does_not_widen[surface]` (assertion 7, wide): `documentElement.scrollWidth == clientWidth`. New build only, no `_vendor_leg`.

- [ ] **Step 3: Size the fixtures on master.** Using a throwaway print (not committed), record per surface: column width, `C − F`, ink width n, and em. Use C = `html` width and F = `base_union` width. Record all fixtures at 390px, and the fit fixtures at 1280px too. Check against the spec's conditions:
  - wide: the ink starts off-screen on the new build. This is verified in Task 2; on master check only that it overflows.
  - fit-mixed and multi-base: `(C − F)/2 ≥ n + em + 20` at 390 and 1280.
  - near: `n + em + 4 ≤ C − F < 2n − 8`. Tune `\hspace` per surface.

  Put the measured numbers in the module docstring.

- [ ] **Step 4: Run on master and confirm the expected RED/GREEN split.**
  Run: `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_tagovf uv run pytest tests/test_e2e_display_math_tag_overflow.py -m e2e -p no:randomly`
  Expected:
  - Assertions 1 and 2 FAIL on the new-build measurement, since master has no rule.
  - `_vendor_leg`'s `count == 13` assertion FAILS in every A/B test, because there is nothing to strip.
  - The table, untagged, near-fit-overflow and page-width tests PASS.

  This is the RED state. Record it.

- [ ] **Step 5: Commit**
  ```bash
  git add tests/test_e2e_display_math_tag_overflow.py
  git commit -m "test(katex): failing A/B e2e for numbered display tag overflow"
  ```

### Task 2: The CSS rule

**Files:**
- Modify: `courses/static/courses/css/courses.css` (insert after the #292 opt-out rule, ~line 1879)

**Interfaces:**
- Consumes: Task 1's test file, unchanged except the docstring.

- [ ] **Step 1: Insert the block.** Five main rules, exactly as the spec's CSS block: container, `::before`, `> .tag`, `> .tag > *`, `> .tag > :first-child`. Then the opt-outs. For each of `.el--table` and `.el--filltable`:
  - container: `display: block`
  - tag: `position: absolute; text-align: inherit`
  - `tag > *`: `text-align: inherit`
  - `tag > :first-child`: `margin-inline-start: 0`

  That gives 5 + 4 + 4 = 13 rules containing `:has(> .tag)`. Precede the block with a comment in house style: the defect (column-positioned abs tag), the flex mechanism and its three bands, the gap, why there are no shrink guards, why titles are not opted out, and placeholders (`<GAP>`, `<END>`, `<VERT>`) for the measured numbers that Step 3 fills in.

- [ ] **Step 2: Run the new file.**
  Run: `TEST_DATABASE_URL=postgres://libli@127.0.0.1:55433/libli_tagovf uv run pytest tests/test_e2e_display_math_tag_overflow.py -m e2e -p no:randomly`
  Expected: all PASS.

- [ ] **Step 3: Record numbers, and check the wide-fixture condition.** Temporarily add `print(...)` of the `_measure` dicts in the wide and fit tests and run them with `-s`. Then:
  - Confirm, for both surfaces at scrollLeft 0, `ink.left > scroller.right`: the tag is off-screen, so reaching it needs the scroller. If not, lengthen `WIDE` and re-run Step 2.
  - Fill the placeholders: gap = `ink.left − base_union.right`, scroll-end `ink.right` vs `scroller.right`, and vertical offset deltas vs vendor.
  - Remove the prints, and confirm with `git diff tests/` that only intended changes remain.

- [ ] **Step 4: CSS-source and neighbour gates.**
  Run: `TEST_DATABASE_URL=… uv run pytest tests/test_container_label_math.py $(ls tests/test_*css*.py) -n 4`
  Then: `TEST_DATABASE_URL=… uv run pytest -m e2e tests/test_e2e_prose_display_math_overflow.py tests/test_e2e_math_element_overflow.py tests/test_e2e_table_display_math_align.py tests/test_e2e_math_reflow.py`
  Expected: all PASS. Grep the summary line; do not trust the exit code.

- [ ] **Step 5: Lint.** Run `uv run ruff check .` and `uv run ruff format --check .`. Both must be clean.

- [ ] **Step 6: Re-absolutising grep.** Run `grep -rn "\.tag" courses/static core/static --include=*.css | grep -v vendor`. Only the new block may touch `.katex-html > .tag`.

- [ ] **Step 7: Commit**
  ```bash
  git add courses/static/courses/css/courses.css tests/test_e2e_display_math_tag_overflow.py
  git commit -m "fix(katex): numbered display numbers follow an overflowing formula"
  ```

### Task 3: Falsification and visual A/B evidence

**Files:**
- No tracked files change unless a mutant exposes a decorative test. In that case, fix the test (`tests/test_e2e_display_math_tag_overflow.py`) or delete the unearned declaration from courses.css, per the spec.
- Scratch only: screenshots and a capture script in the session scratchpad, outside the repo.

- [ ] **Step 1: Run every mutant in the spec's falsification table.** Hand-edit courses.css, run the new test file, record pass/fail per test, and hand-revert. Run `git diff --stat` after each revert to confirm no diff. Required REDs:

  | mutant | must go RED |
  |---|---|
  | whole block | 1, 2 |
  | `align-items: baseline` | 3 (multi-base) and/or 4; unearned only if all green |
  | `.tag > *` rule | 3 (fit-mixed leaves) |
  | `.el--table` opt-out | 6 |
  | `.el--filltable` opt-out | 6 |
  | `.tag > *` reset in `.el--table` opt-out | 6 |
  | `:first-child` margin reset in `.el--table` opt-out | 6 |
  | gap rule | 1, 2 |
  | `text-align: right` on `.tag` | 3 |
  | #292 `.katex-display` overflow pair | 7[prose] (`[math]` stays green: `.el--math` keeps its own scroller) |

  Under the whole-block mutant, `_vendor_leg`'s count assertion also fails (count 0). That is expected. The REDs that matter are the new-build assertions 1 and 2.

- [ ] **Step 2: Fix and commit** anything a mutant exposed (`git commit -m "test(katex): …"`). Otherwise there is no commit.

- [ ] **Step 3: Screenshots.** Create an UNTRACKED file `tests/test_e2e_zz_tagovf_shots.py`, never committed and deleted after this step, so it gets the repo conftest and live_server. It imports `_open`, `_strip_new_rules`, `_scroll_to_end` and `WIDE` from the new module. For each surface and each theme:
  - Set the theme with `page.evaluate("document.documentElement.dataset.theme = 'dark'")` (or `'light'`). That is the attribute the app's toggle sets; see `tests/test_e2e_auth.py:69`.
  - Screenshot the scroller element at scroll 0 and at scroll end, call `_strip_new_rules`, and screenshot again. That gives 16 PNGs, written to the session scratchpad directory (absolute path).
  - Run with the usual `TEST_DATABASE_URL` prefix and `-m e2e`, then delete the file. `git status` must show it gone.
  - Look at every PNG. Judge dark separately.

- [ ] **Step 4: Record the evidence** (the falsification table with outcomes, screenshot paths, and measured numbers) in the session ledger for the PR body.
