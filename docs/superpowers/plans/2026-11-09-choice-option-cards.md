# Choice option cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle student-facing choice questions and both grid question types as outlined option cards, with hidden native inputs and result colours after Check.

**Architecture:** Server-rendered markup changes in one options template and two grid template tags, plus one rule change in `ChoiceQuestionElement.choice_marks`. Everything visual is token-based CSS in `courses.css`. The real inputs stay in the page, clipped, so submission and keyboard behaviour do not change.

**Tech Stack:** Django templates and template tags, plain CSS with design tokens, pytest, Playwright (sync).

**Spec:** `docs/superpowers/specs/2026-11-09-choice-option-cards-design.md`. Read it with this plan: every CSS value below is cited by spec section, not repeated.

## Global Constraints

- Spec §2 (D1–D12) and §3.8 are protected owner decisions. Do not change them; if one seems wrong, stop and report it.
- Colours come only from existing tokens (`--primary`, `--primary-subtle`, `--border-strong`, `--success[-subtle]`, `--danger[-subtle]`, `--warning[-subtle]`, `--tc-orange`, `--text-primary`, `--text-secondary`). No per-theme rules, no literal colours.
- The picked thickness is an inset `box-shadow`, never a wider `border`. Font weight never changes on selection.
- `name`, `value`, `checked`, `disabled` and `aria-invalid` on inputs stay as they are. `courses/keycopy.py`, `build_answer`, `mark` and `part_verdicts` are not edited.
- Editor forms, settings, analytics controls, switch-grid and switch-gate controls are not touched (D11).
- Hint msgid is exactly `Tick every correct answer.` No `.po` or `.mo` change.
- Django comments: `{# #}` is single-line only. Use `{% comment %}` for anything longer.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_013qssAY2iGUB6uCLwaPVYHL`.
  Stage explicit paths only, never `git add -A`.

**Environment** (run everything from the worktree root):

- First time only: `cp ../../libli/.env .env` (git-ignored; the worktree has none).
- Before any test run: `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. Without it a run looks hung for about 4 minutes.
- Run these commands in the Bash tool, because PowerShell does not expand the `*css*` globs. Tools run through `uv run`. Browser tests need `-m e2e`. Never pass `-q` (it is already in `addopts`, and a second one hides the summary). Read the summary line; the exit code alone can mislead.
- A RED step counts only when the failure is an assertion failure, not a setup, import or ORM error. New e2e modules define the same session-scoped autouse `_allow_async_unsafe` fixture as `tests/test_e2e_quiz_choice_marking.py`, or ORM seeding raises `SynchronousOnlyOperation`.
- Only one test run at a time. Do not run the whole suite (it gets OOM-killed); run the files each task names.
- After any edit to a `.css` file, run every CSS source test:
  `uv run pytest tests/test_*css*.py courses/tests/test_*css*.py`.
- Revert a mutation by editing it back by hand, never with `git checkout`, which destroys uncommitted work. Read the `git diff` afterwards.

## Review Focus

Each line has its test in the named task.

1. A grid saved with no rows or no columns must render without an error and without a stray empty button group (Task 4).
2. A column label containing a formula: clicking directly on the formula must select that button (Task 5).
3. A grid inside a two-column container on a desktop screen must not overflow its column (Task 5).
4. After Check and a page reload, a lesson choice question must show the same picked and verdict card states (Task 3).
5. Ticking and then unticking a multi-answer card with the pointer moved away must return it to the Unpicked look (Task 3).

---

### Task 1: Lesson marks for answers that leak nothing

**Files:**
- Modify: `courses/models.py` (`ChoiceQuestionElement.choice_marks`, its docstring)
- Test: `tests/test_quiz_choice_inline_marking.py`

**Interfaces:**
- Produces: `choice_marks` in lesson mode also returns `{"kind": "correct"}` for every pick of a fully correct answer, and `{"kind": "wrong"}` for the pick of a wrong single-answer question.

- [ ] **Step 1: Write the failing tests**

Rewrite `test_lesson_correct_answer_does_not_gain_a_tick` as `test_lesson_correct_answer_gains_a_tick`, asserting `question__choice-marker--correct` is present on the real pick. Then add model-level tests:

```python
def _q(multiple, *rows):
    q = ChoiceQuestionElement.objects.create(stem="s", max_marks="1", multiple=multiple)
    return q, [q.choices.create(text=t, is_correct=c, feedback=f) for t, c, f in rows]

def _marks(q, picked):
    return q.choice_marks(list(q.choices.all()), set(picked), q.mark(set(picked)), "lesson", False)

@pytest.mark.django_db
def test_lesson_fully_correct_marks_every_pick():
    q, (a, b, c) = _q(True, ("a", True, ""), ("b", True, ""), ("c", False, ""))
    marks = _marks(q, [a.pk, b.pk])
    assert {k: v["kind"] for k, v in marks.items()} == {a.pk: "correct", b.pk: "correct"}

@pytest.mark.django_db
def test_lesson_wrong_single_answer_marks_the_pick():
    q, (a, b) = _q(False, ("a", True, ""), ("b", False, ""))
    assert _marks(q, [b.pk])[b.pk]["kind"] == "wrong"
    assert a.pk not in _marks(q, [b.pk])

@pytest.mark.django_db
def test_lesson_wrong_multi_answer_marks_only_annotated():
    q, (a, b, c) = _q(True, ("a", True, ""), ("b", False, "no"), ("c", True, ""))
    marks = _marks(q, [a.pk, b.pk])
    assert {k: v["kind"] for k, v in marks.items()} == {b.pk: "wrong"}
```

Also search `tests/` for other assertions that lesson marks are absent (`marker--correct`, `marker--wrong` near `lesson`) and rewrite those that contradict spec §3.7. Add a no-JS lesson re-render test beside the existing sibling test in `courses/tests/test_nested_question_nojs_feedback.py`: the checked question has a real pick (once correct, once wrong single-answer) and its sibling renders no `question__choice-marker`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_quiz_choice_inline_marking.py courses/tests/test_nested_question_nojs_feedback.py`
Expected: the new mark tests FAIL on missing marks. `test_lesson_wrong_multi_answer_marks_only_annotated` already passes; it guards against over-marking and is falsified in Step 5.

- [ ] **Step 3: Implement the two lesson cases**

After the existing `annotated` loop in the lesson branch: for each choice with `c.pk in selected`, set `"correct"` when `mark_result.correct`, otherwise `"wrong"` when `not self.multiple`. Rewrite the "LESSON — unchanged" docstring paragraph to state the rule in spec §3.7.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_quiz_choice_inline_marking.py tests/test_choice_inline_feedback.py courses/tests/test_question_lock_on_correct.py courses/tests/test_nested_question_nojs_feedback.py`
Expected: all pass.

- [ ] **Step 5: Mutate and commit**

Remove the `c.pk in selected` guard and confirm the sibling test goes RED; remove the `not self.multiple` condition and confirm the wrong multi-answer test goes RED. Restore each by hand. Commit `courses/models.py` and the test files with `feat(courses): mark safe lesson picks on choice questions`.

---

### Task 2: Option markup, verdict classes and hint

**Files:**
- Modify: `templates/courses/elements/_choicequestion_options.html`, `templates/courses/elements/choicequestion.html`, `courses/models.py` (`ChoiceQuestionElement.render`)
- Test: `tests/test_quiz_choice_inline_marking.py`, `tests/test_quiz_reveal_pr3_choice.py`, `tests/test_element_try.py`, `tests/test_choice_inline_feedback.py`

**Interfaces:**
- Produces: `li.question__choice` plus optional `question__choice--correct|--wrong|--missed`; `p.question__hint`. Tasks 3 and 5 style these.

- [ ] **Step 1: Update and add the render tests**

Replace assertions on `question__choice--picked` and `question__choices--marked` with what still proves the behaviour: the pick is rendered `checked` and carries its verdict class. For example `tests/test_quiz_reveal_pr3_choice.py:449` becomes `assert row.count(" checked") == 2`, its test is renamed `test_results_nr_choice_rows_keep_picks_without_verdicts`, and `PICKED` in `tests/test_quiz_choice_inline_marking.py` is replaced by per-kind class constants. Line 134's `assert PICKED not in html` becomes positive: the pick carries its verdict class and no `--missed` appears on any option. That module's docstring is rewritten, because "the pick is tinted" and "lesson mode is untouched" are no longer true. Add:

```python
assert "question__choice--picked" not in body
assert "question__choices--marked" not in body
assert 'class="question__choice question__choice--wrong"' in body   # wrong pick
assert 'class="question__choice question__choice--missed"' in body  # after the lock
assert body.count("question__hint") == 1   # multiple=True
assert "question__hint" not in single_answer_body
with translation.override("pl"):
    assert "Zaznacz wszystkie poprawne odpowiedzi." in render_multi_answer()
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_quiz_reveal_pr3_choice.py tests/test_quiz_choice_inline_marking.py tests/test_element_try.py`
Expected: FAIL on the new class and hint assertions.

- [ ] **Step 3: Change the templates and `render`**

In the options template, per spec §3.3: the `li` gets `{% if mk %} question__choice--{{ mk.kind }}{% endif %}`; drop the `--marked` class and the `show_picks` branch; rewrite the header comment and the "a lesson marks only…" comment. In `render`, delete the `show_picks` and `marked_layout` context keys, their variable and comments. Add the §3.5 hint directly after the stem in `choicequestion.html`, inside `{% if el.multiple %}`.

- [ ] **Step 4: Run the tests**

Run: the Step 2 command plus `tests/test_choice_inline_feedback.py`, `tests/test_quiz_results_choice_reveal.py`, `tests/test_questions_consumption.py`.
Expected: all pass.

- [ ] **Step 5: Commit**

Commit the templates, `courses/models.py` and the tests with `feat(courses): verdict classes and multi-answer hint on choice options`.

---

### Task 3: Option card CSS

**Files:**
- Modify: `courses/static/courses/css/courses.css` (Question element block, about lines 478–603; feedback rule; `@media print` block)
- Create: `tests/e2e_pick.py`, `tests/test_e2e_choice_cards.py`, `tests/test_choice_cards_css.py`
- Modify (repoint input driving): `tests/test_e2e_questions.py`, `tests/test_e2e_question_lock.py`, `tests/test_e2e_quiz_choice_marking.py`, `tests/test_e2e_choice_inline_feedback.py`, `tests/test_e2e_nested_question.py`, `tests/test_e2e_quiz_reveal_pr3.py`, and any choice-question caller in `tests/test_e2e_quiz_reveal_pr2.py`

**Interfaces:**
- Produces: `tests/e2e_pick.py::pick(input_locator) -> None`, which clicks the input's parent `label` (`input_locator.locator("xpath=..").click()`). It never uses `force=True`. Task 5 reuses it.

- [ ] **Step 1: Write the failing tests**

Create `tests/e2e_pick.py` as in Interfaces; the new e2e module and every repointed test import `pick` from it.

`tests/test_choice_cards_css.py` (source guards): the option-card hover selectors appear only inside `@media (hover: hover)`; the option-card hiding rule is inside `@supports selector(:has(input:checked))`; the Picked rule declares `box-shadow: inset` and no `border-width`; `.question__choice--picked` and `.question__choices--marked` no longer appear.

`tests/test_e2e_choice_cards.py`, with module-level `pytestmark = pytest.mark.e2e`. Quiz-mode tests seed like `tests/test_e2e_quiz_choice_marking.py` (or `tests/reveal_pr3_kit.py::choice`); lesson tests follow `_seed_inline_feedback_question` in `tests/test_e2e_choice_inline_feedback.py`, with parameters for single- or multi-answer and option count. `test_after_check_colours_quiz` needs a multi-answer quiz locked after one attempt; `test_after_check_colours_lesson` needs one fully correct and one single-answer lesson question; the matrix test needs a multi-answer lesson with author feedback on a distractor and on a correct option. Each name states its assertion, using `getComputedStyle` and real tokens resolved through a probe element so brand and theme are not hard-coded:

- `test_no_visible_input_and_thin_outline`: input box is 1×1 and clipped; card border `1px solid` in `--border-strong`.
- `test_click_selects_and_paints_picked`: `box-shadow` contains `inset`, background equals `--primary-subtle`; a single-answer question holds one pick.
- `test_untick_returns_to_unpicked_look` (Review Focus 5): multi-answer card ticked, unticked, mouse moved to `(0, 0)`; border colour equals resolved `--border-strong`, background is transparent and shadow is `none`, compared with tokens and not with an earlier measurement.
- `test_keyboard_changes_pick_and_shows_ring`: Tab reaches the group, ArrowDown moves the pick, outline is `2px` in `--primary`.
- `test_submitted_values_unchanged`: the Check request is multipart (`new FormData(form)`); parse its `name="choice"` parts and assert the set of pks equals the picks made.
- `test_after_check_colours_quiz`: correct, wrong and, once locked, missed cards match spec §3.1 and carry `✓ ✗ ＋`, the ＋ in resolved `--tc-orange`. A locked card ignores a click: `pick` and a plain label click time out on a disabled input, so this one assertion follows `tests/test_e2e_question_lock.py:112`, `.question__choice-text` `.click(force=True)`, then asserts the checked state is unchanged. The `force=True` ban covers only tests proving clickability.
- `test_after_check_colours_lesson`: correct answer green with ✓; wrong single-answer red with ✗.
- `test_matrix_pick_amber_and_unpick_red`: the two live-lesson matrix cells in spec §3.1.
- `test_lesson_verdict_survives_reload` (Review Focus 4): Check, reload; after the reload the pick's border and fill equal resolved `--success` and `--success-subtle` (a correct answer) and `box-shadow` contains `inset`, compared with tokens and not with the pre-reload state.
- `test_hover_leaves_verdict_and_locked_cards_unchanged`: `locator.hover()` on a verdict card and a locked card; the border colour does not change.
- `test_marker_sits_on_first_line_above_feedback`.
- `test_wide_maths_stays_in_card_at_360`: wide unbreakable inline formula (`{a+b+…}`) and display maths; content and marker inside the card; `documentElement.scrollWidth <= innerWidth`. A normal inline formula has `scrollHeight <= clientHeight` on `.question__choice-text`.
- `test_forced_colors_picked_differs`: `new_context(forced_colors="active")`; picked and unpicked differ; marker and `.question__choice-text` in a picked verdict card compute to the HighlightText value.
- `test_dark_and_custom_brand_resolve_from_tokens`: in dark theme the picked border equals resolved `--primary`; in light theme, with a custom brand set by writing the `primary` brand-colour row before the first page load (see `tests/test_institution.py`; the value is served through the cached `get_site_config()`, so clear that cache in the test), the picked card's border equals the literal custom colour.
- `test_print_keeps_outlines_and_tints`: `emulate_media(media="print")`; border and tint remain; a picked and a verdict card compute `webkitPrintColorAdjust === "exact"` (the tint assertion alone cannot fail, because emulation does not apply print economy); cards compute `breakInside === "avoid"`; option and feedback with a wide formula compute `overflow-x: visible`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_choice_cards_css.py` and `uv run pytest -m e2e tests/test_e2e_choice_cards.py`
Expected: FAIL, because the cards are not styled yet, except `test_submitted_values_unchanged`, which passes now as a preservation test. Prove it can fail by temporarily renaming the field in the template; restore by hand.

- [ ] **Step 3: Write the CSS**

Implement spec §3.1 (option-card rows and matrix, hover inside `@media (hover: hover)`, marker and feedback ink, forced colours), §3.2 (option part), §3.3 and §3.6 (option part), plus the hint style and margins of §3.5. Select with `.question__choices .question__choice…` so the rules also apply where a results fragment has no `.el--question` ancestor and out-rank `app.css`'s `label`. Keep the list reset at `courses.css:480` (`list-style: none; padding: 0; margin: 0 0 var(--space-3)`), or carry it into the new list rule. Delete only the `.el--question .question__choice` rules from line 481 onward, the disabled drawing block and the `--marked` rules. Do not touch the `prose-cap` sentinels.

- [ ] **Step 4: Repoint the existing tests**

In the Files list above, replace `.check()`, `.uncheck()` and `set_checked()` on `input[name='choice']` and equivalents with `pick(...)`. Update `test_solved_choice_marks_its_picks_in_dark_mode` in `tests/test_e2e_question_lock.py` (about line 167): the answer is fully correct, so after Task 1 the assertion moves from the clipped `input` to the `li`, which compares to resolved `--success` with an inset shadow, while a non-pick stays `--border-strong` with no shadow. Rename or re-comment the test, because brand fill no longer describes it. Delete `tests/test_e2e_quiz_choice_marking.py:139`, which can no longer fail, and assert the unlocked state some other way if that test needs it. `tests/test_e2e_start_fresh_activation.py` also calls `.check()`: confirm whether those are question inputs and repoint only if so. `tests/test_e2e_practice_state.py`, listed in spec §6, needs no repoint: its inputs are `.markdone` checkboxes.

- [ ] **Step 5: Run everything in scope**

Run: all CSS source tests, then `uv run pytest -m e2e` on `tests/test_e2e_choice_cards.py` and each file repointed in Step 4.
Expected: all pass. `tests/test_e2e_quiz_reveal_pr2.py` grid cases still drive visible inputs at this stage.

- [ ] **Step 6: Mutate and commit**

A/B: remove the Picked `box-shadow`, the `@supports` wrapper, the `minmax(0, 1fr)` track, the forced-colors label colour and `print-color-adjust`, one at a time; each must turn a named test RED. Restore by hand. Commit with `feat(courses): choice options as outlined cards`.

---

### Task 4: Grid markup

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (`render_choice_grid`, `render_multigrid`, `_grid_row_cells`, `_multigrid_row_cells`, a new helper), `templates/courses/elements/multigridquestionelement.html`
- Test: `tests/test_render_multigrid.py`, `tests/test_render_choicegrid.py`, `tests/test_choicegrid_styles.py`

**Interfaces:**
- Produces: row markup per spec §3.4: `td.choicegrid__stmt#choicegrid-stmt-<pk>|td.multigrid__stmt#multigrid-stmt-<pk>` > `span.grid-stmt-text`, then the `sr_verdict` text and optional `span.grid-verdict` outside the scroller, then `td.grid-answers-cell` > `div.grid-answers[role=group][aria-labelledby]` > `label` > `input` + `span.gridbtn`.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_header_and_label_in_every_button(): ...
    assert "<thead" not in html
    assert html.count('class="gridbtn">A &amp; B</span>') == 2   # two rows, label "A & B"

def test_inputs_unchanged(): ...
    assert f'name="row_{r1.pk}" value="{a.pk}" checked' in html

def test_group_named_by_statement(): ...
    assert f'id="multigrid-stmt-{r1.pk}"' in html
    assert f'role="group" aria-labelledby="multigrid-stmt-{r1.pk}"' in html

def test_grid_types_with_equal_row_pks_have_distinct_ids(): ...
    # GridRow and MultiGridRow created with the same explicit pk
    assert f'choicegrid-stmt-{pk}' in a and f'multigrid-stmt-{pk}' in b

def test_verdict_glyph_only_on_painted_rows(): ...
    assert html.count('class="grid-verdict"') == 1   # verdicts=[False, None]
    assert "✗" in html

def test_key_copy_suffixes_ids(): ...
    key = neutralise_key_copy(rendered_with_copy_key)   # courses.keycopy; copy="key" alone only paints
    assert f'id="multigrid-stmt-{r1.pk}-key"' in key
    assert f'aria-labelledby="multigrid-stmt-{r1.pk}-key"' in key
    assert 'name="row_' not in key

def test_multigrid_hint_once_with_key_copy(): ...
    assert body.count("question__hint") == 1

def test_empty_grid_renders(): ...   # Review Focus 1
    # no rows: <tbody></tbody>, no "gridbtn"
    # no columns: statement renders; "grid-answers" and 'role="group"' both absent
```

The same set, except the hint test, applies to the choice grid in `tests/test_render_choicegrid.py` (radio inputs, `choicegrid-stmt-`), which also asserts `question__hint` is absent from a rendered choice grid question. Remove the `thead` guard from `tests/test_choicegrid_styles.py`; Task 5 retires its CSS guards.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_render_multigrid.py tests/test_render_choicegrid.py tests/test_choicegrid_styles.py`
Expected: FAIL on the new markup, except `test_inputs_unchanged`, `test_empty_grid_renders`, the choice-grid hint negative and the key-copy `name` assertion, which pass now and are falsified in Step 5.

- [ ] **Step 3: Implement the markup**

Add `_grid_row(row, cols, kind, verdict, cells_html)` or an equivalent so the statement and answers cell are built once for both types, with `kind` being `"choicegrid"` or `"multigrid"`. Keep the two `format_html` branches that make `checked` literal, and keep `{invalid}` last in the input tag. Show ✓ when the verdict is `True` and ✗ when `False`. When `cols` is empty, omit `td.grid-answers-cell` altogether. Rewrite both docstrings. Add the §3.5 hint after the stem in `multigridquestionelement.html`, unconditionally.

- [ ] **Step 4: Run the tests**

Run: the Step 2 command plus `tests/test_context_multigrid.py`, `tests/test_context_choicegrid.py`, `tests/test_quiz_reveal_pr2_grids.py`, `tests/test_quiz_reveal_pr2_paint.py`, `tests/test_grid_questions_nesting.py`, `tests/test_marking_choicegrid.py`.
Expected: all pass.

- [ ] **Step 5: Falsify the preservation tests and commit**

Temporarily drop `checked` from one `format_html` branch and confirm `test_inputs_unchanged` goes RED; remove the empty-`cols` branch and confirm `test_empty_grid_renders` goes RED; add the hint to `choicegridquestionelement.html` and confirm the negative goes RED. Restore each by hand. Commit `courses/templatetags/courses_extras.py`, the template and the tests with `feat(courses): grid rows carry their column labels in buttons`.

---

### Task 5: Grid CSS and the over-wide, print and dark tests

**Files:**
- Modify: `courses/static/courses/css/courses.css` (verdict rules about lines 1000–1014, `.choicegrid` and `.multigrid` blocks about lines 2375–2516, print rule about line 3615)
- Create: `tests/test_e2e_grid_cards.py`
- Modify: `tests/test_choicegrid_styles.py`, `tests/test_e2e_choicegrid.py`, `tests/test_e2e_multigrid.py`, `tests/test_e2e_locked_controls_look.py`, `tests/test_e2e_quiz_reveal_pr2.py`, `tests/test_e2e_scroll_affordance.py`, `tests/test_e2e_wide_content_scroll.py`, `tests/test_e2e_print_layout.py`, `tests/test_e2e_uniform_block_width.py`

**Interfaces:**
- Consumes: Task 3's `pick`, Task 4's markup.

- [ ] **Step 1: Write the failing tests**

`tests/test_choicegrid_styles.py`: replace the assertions on `accent-color: var(--primary)`, `.choicegrid tbody td:has(input:checked)` and `.choicegrid tbody tr.is-incorrect td.choicegrid__stmt` with source guards: grid inputs hidden outside `@supports`; `input[checked]:checked + .gridbtn` present inside `tr.is-correct` and `tr.is-incorrect` rules; `table-layout: fixed`; `.gridbtn` hover selectors only inside `@media (hover: hover)`; and `td:has(input:checked)` absent from the CSS.

`tests/test_e2e_grid_cards.py`, with module-level `pytestmark = pytest.mark.e2e`. Seeds: `_seed(..., max_attempts=2)` from `tests/test_e2e_quiz_reveal_pr2.py`, or a lesson, for live painted rows, and `max_attempts=1` for locked rows; direct `GridColumn` and `GridRow` creation as in `tests/test_e2e_choicegrid.py` for custom labels and formula or fraction statements; `TwoColumnElement.objects.create(data=TwoColumnElement.default_data())` plus a child `Element` with `parent` and the column's `tab_id`, as in `courses/tests/test_nested_question_nojs_feedback.py`, for the nested case. Names and assertions from spec §6:

- `test_hover_leaves_painted_button_unchanged`: `locator.hover()` on a verdict-painted `.gridbtn`; border colour unchanged.
- `test_gridbtn_picks_and_paints`, `test_keyboard_and_ring_on_gridbtn`, and `test_grid_answers_stays_transparent` (computed background transparent on both `.grid-answers-cell` and `.grid-answers` with a pick).
- `test_accessibility_tree`: `get_by_role("group", name=statement, exact=True)` on an unpainted row; `name` contains the statement on a painted row; inputs named by column.
- `test_live_painted_grid_new_pick_is_primary`: change a pick in an `is-incorrect` row; the new button has Picked colours and `--danger` appears nowhere on it.
- `test_desktop_rhythm`: adjacent rows' buttons exactly `6px` apart; statement rule within 4px of button bottom; statement and buttons on one line.
- `test_stacked_at_360_and_mid_width`: long labels, at 360px and at a width where the statement plus one button fits but not all; every button below the statement; no page overflow; wrapper `scrollWidth - clientWidth <= 0`; every `.gridbtn` right edge inside the wrapper.
- `test_stacked_rhythm_at_360`: next-statement gap exceeds own-buttons gap.
- `test_short_labels_stack_at_390`: P / F labels below the statement.
- `test_long_label_wraps_at_360`.
- `test_wide_statement_formula`: desktop, formula left of the first button; 360px, wrapper not scrolling, `.grid-stmt-text` scrolling, buttons inside, `.grid-verdict` in view.
- `test_fraction_statement_no_vertical_scroll`: wrapper and `.grid-stmt-text` `scrollHeight <= clientHeight`; A/B via an injected `padding-block: 0` that makes the text element fail.
- `test_click_on_formula_label_selects` (Review Focus 2): `page.mouse.click` at the centre of `.gridbtn .katex`, then assert the input `is_checked`.
- `test_grid_in_two_columns_does_not_overflow` (Review Focus 3): grid nested in a `twocolumn` element at 1280px, with labels whose single-line width exceeds the column (such as the five-label set in `tests/test_e2e_uniform_block_width.py`); `.grid-answers` right edge inside its column, the buttons occupy more than one distinct `top`, and each stays at single-line height.
- `test_forced_colors_painted_button`: a plain picked button differs from an unpicked one, and a verdict-painted button has Highlight background and HighlightText colour.
- `test_print_grid`: outlines and tints remain; a picked `.gridbtn` computes `webkitPrintColorAdjust === "exact"`; rows compute `breakInside === "avoid"`; `.grid-stmt-text` computes `overflow-x: visible`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_choicegrid_styles.py` and `uv run pytest -m e2e tests/test_e2e_grid_cards.py`
Expected: FAIL, except `test_click_on_formula_label_selects` and `test_accessibility_tree`, which depend only on Task 4's markup, pass now and are falsified in Step 6, and `test_fraction_statement_no_vertical_scroll`, which may pass now and is falsified by its own A/B.

- [ ] **Step 3: Write the CSS**

Implement spec §3.4 in one shared rule set for `.choicegrid` and `.multigrid`, the grid parts of §3.1, §3.2 and §3.6, and the §3.5 `.multigrid-scroll` margin. Delete everything §3.4 lists, including the statement tint rules about lines 1011–1014 and the print `min-width: 0` rule. Update the comments that describe a header row, the tint and bar, or the zebra stripes. `tests/test_css_citations_are_durable.py` checks line citations, so keep any new comment free of line numbers.

- [ ] **Step 4: Migrate the existing tests**

- Grid `.check()` and `.uncheck()` calls in the Files list: keep the existing input locators and wrap them in `pick(...)`.
- `test_e2e_wide_content_scroll.py` and `test_e2e_scroll_affordance.py`: re-seed per spec §6: in the shared `_seed_wide_unit`, the last `COLUMN_LABELS` entry becomes a KaTeX formula in a single `{…}` box, and tests wait for `.katex` before measuring. In `test_wide_grid_scrolls_to_reveal_its_last_column`, use the last `.gridbtn` through `.last` or `querySelectorAll` (`.gridbtn:last-child` matches every button), replace the label-text equality with a `.katex` count of 1 in that button, and add a precondition that its right edge is beyond the phone width before scrolling.
- `test_e2e_locked_controls_look.py::test_dark_locked_grid_pick_stands_out`: row 0 is answered correctly, so its locked pick has resolved `--success` border plus inset shadow, the unpicked button has `--border-strong` and no shadow, and the border-to-surface contrast is at least `3`. Delete `_CELL_CONTRAST` if nothing else uses it.
- `test_e2e_print_layout.py::test_grid_question_fits_print_width`: new assertions and the moved shade check per spec §6.
- `test_e2e_quiz_reveal_pr2.py`: the switch-position assertion keeps covering `multigrid` and must stay unchanged. In `test_grid_lock_keeps_the_students_pick_and_paints_rows` (about lines 306–307), replace the comparison of first-`td` backgrounds with each row's `.grid-verdict` glyph (✓ against ✗) and the differing computed border colour of the picked `.gridbtn`.
- `test_e2e_uniform_block_width.py`: update the empty-grid note and any selector that relied on `thead`.

- [ ] **Step 5: Run everything in scope**

Run: all CSS source tests and `uv run pytest tests/test_choicegrid_styles.py`, then `uv run pytest -m e2e` on `tests/test_e2e_grid_cards.py` and each `test_e2e_*` file in this task's Files list.
Expected: all pass.

- [ ] **Step 6: Mutate and commit**

A/B one at a time: remove `table-layout: fixed`; set `display: contents` on both `.grid-answers-cell` and `.grid-answers` (`test_stacked_at_360_and_mid_width` goes RED); drop `[checked]` from the verdict selector; delete the phone `flex-basis: 100%`; drop the forced-colors out-ranking; delete the `tr.is-correct … .gridbtn` rule (`test_dark_locked_grid_pick_stands_out`); remove `flex-wrap: wrap` from `.grid-answers`, and separately restore `min-width: max-content` on the table (each turns `test_grid_in_two_columns_does_not_overflow` RED); add `pointer-events: none` on `.grid-answers label` (`test_click_on_formula_label_selects`); remove `print-color-adjust` (`test_print_grid`); remove `aria-labelledby` from the markup (`test_accessibility_tree`). Each must turn a named test RED. Restore by hand. Commit with `feat(courses): grid questions as outlined button rows`.

---

### Task 6: Whole-branch verification

**Files:**
- Modify: only what these checks show is wrong.

- [ ] **Step 1: Find anything left behind**

Run a repository search over `courses/`, `templates/` and `tests/` (excluding `capture_*`) for `question__choice--picked`, `question__choices--marked`, `marked_layout`, `show_picks`, `choicegrid thead`, `multigrid thead`.
Expected: no matches, apart from negative assertions.

- [ ] **Step 2: Run the unit and CSS suites touching these elements**

Run: `uv run pytest tests/test_*css*.py courses/tests/test_*css*.py tests/test_choicegrid_styles.py tests/test_render_multigrid.py tests/test_render_choicegrid.py tests/test_quiz_choice_inline_marking.py tests/test_quiz_reveal_pr3_choice.py tests/test_quiz_reveal_pr2_grids.py tests/test_quiz_results_choice_reveal.py tests/test_element_try.py tests/test_analytics_student_quiz.py tests/test_answer_summary.py`
Expected: all pass.

- [ ] **Step 3: Run the browser suites touching these elements**

Run: `uv run pytest -m e2e` in chunks over every `tests/test_e2e_*.py` named in Tasks 3 and 5, plus `tests/test_e2e_slideshow.py` and `tests/test_e2e_print_wide_math.py`.
Expected: all pass. Re-run a failing file alone before believing the failure.

- [ ] **Step 4: Lint**

Run: `uv run ruff check --no-cache .` and `uv run ruff format --check .`
Expected: both clean.

- [ ] **Step 5: Commit any fixes**

Commit explicit paths with `test(courses): finish the choice card migration`, or skip if nothing changed.
