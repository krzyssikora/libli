# Choice questions as outlined option cards

## 1. Purpose

Student-facing choice questions show native radio buttons and checkboxes. The owner finds
the look of the original LAL course better: no visible controls, thin rounded outlines on
every option, and a clear picked state. This restyles single/multiple choice questions and
both grid question types to that look, in libli's own (admin-definable) brand colours, across
every state they render in.

This is a presentation change. Scoring, stored answers, submitted field names and the
question-type editors do not change. The one change to what a student sees per option is the
lesson mark rule in §3.7, which adds marks only where the verdict panel already gives the same
result.

## 2. Owner decisions (PROTECTED)

A review catch that would change any row below is NOT applied. It goes to the owner,
restating the visible consequence (what the student or author would see differently).

| # | Decision | Source (verbatim) |
|---|---|---|
| D1 | Remove the visible radio and checkbox circles; every option gets very thin rounded borders. | "remove these inputs and add very thin borders to all choices" |
| D2 | Picked option: thicker outline plus a light tint (mockup style C). | "C looks best to me" |
| D3 | Colours come from the admin-defined brand colour. | "it uses the libli colours that platform admin can define" |
| D4 | After Check, the card takes the result colour: green (correct pick), red (wrong pick), dashed amber outline with amber tint (correct answer not picked) (mockup variant Y). | "Y" |
| D5 | Normal choice questions and both grid types get this look. | Chose from mockups showing both; "yes" to the table |
| D6 | The real inputs stay in the page, visually hidden; keyboard use, screen readers and submitted answers do not change. | "the list looks right" |
| D7 | One-line hint on multi-answer questions and multi-answer grids; none on single-answer ones. Polish text: "Zaznacz wszystkie poprawne odpowiedzi." | "the list looks right" |
| D8 | ✓ / ✗ / ＋ at the card's right edge and author feedback inside the card; marks always stay, so colour is never the only signal. | "the list looks right" |
| D9 | Locked and results views use the same cards, not clickable; the old grey circles and the "picked row" highlight go. | "the list looks right" |
| D10 | Printing keeps the outlines, so a blank worksheet has boxes to mark. | "the list looks right" |
| D11 | Editor forms, settings, analytics controls and other radio/checkbox controls stay as they are. | "the list looks right" |
| D12 | Grids: the column name moves into each button as in LAL, and the header row goes away. On narrow screens each statement sits above its row of buttons, and buttons wrap if needed, rather than sideways scrolling. | "yes, start /pipeline" in reply to the table including D12 |

Approved mockups (git-ignored, local only, in the main checkout):
`.superpowers/brainstorm/411-1794186300/content/choice-selected-style.html` (style C) and
`choice-after-check.html` (variant Y). Their colours and sizes are restated in §3 so the build
does not depend on those files.

## 3. Architecture and components

### 3.1 Visual vocabulary (shared by all three types)

| State | Outline | Fill | Text |
|---|---|---|---|
| Unpicked | 1px solid `--border-strong`, radius `--radius-sm` | none | `--text-primary` (choice); `--text-secondary` (grid button) |
| Hover (live inputs only) | 1px `--primary` | none | unchanged |
| Keyboard focus | 2px `--primary` outline, 2px offset, from `:has(input:focus-visible)` | unchanged | unchanged |
| Picked | 1px `--primary` plus 1px inset `box-shadow` in `--primary` | `--primary-subtle` | `--text-primary` |
| Correct pick | as Picked, in `--success` | `--success-subtle` | `--text-primary` |
| Wrong pick | as Picked, in `--danger` | `--danger-subtle` | `--text-primary` |
| Missed (correct, not picked) | 1px dashed `--warning` | `--warning-subtle` | `--text-primary` |

The thicker outline is the inset shadow, never a wider `border`, so selecting never shifts
layout. Font weight does not change on selection, because a heavier label is wider and would
misalign grid buttons between rows.

Sizes from the mockups: option card padding `9px 14px`; gap between option cards `6px`; grid
button padding `5px 10px` at `14px` type; gap between grid buttons `6px 8px`; grid statement at
`15px`; hint at `14px`. Option text, grid buttons and statements are weight 400, overriding
`app.css`'s `label { font-weight: 500 }` and the old statement weight.

Colour and thickness are separate. In a lesson or an unlocked quiz the inputs stay live after
Check, so a card can hold a verdict and then be picked or unpicked before the next Check. The
full matrix for an option card (v = `--success` for correct, `--danger` for wrong):

| Verdict class | Checked | Outline | Fill |
|---|---|---|---|
| none | no | 1px solid `--border-strong` | none |
| none | yes | 1px solid `--primary` + 1px inset `--primary` | `--primary-subtle` |
| correct or wrong | yes | 1px solid v + 1px inset v | v-subtle |
| correct or wrong | no (student moved away) | 1px solid v, no inset | v-subtle |
| missed | no | 1px dashed `--warning`, no inset | `--warning-subtle` |
| missed | yes (live lesson input) | 1px solid `--warning` + 1px inset `--warning` | `--warning-subtle` |

So a card the student moves away from stays red with its ✗ (as the ✗ stays today) but drops to
the thin outline, and the new pick reads as Picked. Hover changes the outline only on a card
with no verdict class and a live input; a verdict card keeps its colours. The same holds for a
grid button painted with its row's verdict (§3.4). Hover rules are inside `@media (hover: hover)`,
so a tap on a phone cannot leave a sticky teal outline on an unpicked card.

Ink on the fills: marks use `--success` and `--danger`, but the ＋ uses `--tc-orange`, because
`--warning` on `--warning-subtle` is below 3:1 and the mark is what D8 relies on. Author feedback
uses `--text-secondary` (the current `--text-tertiary` fails on the tints).

All colours are existing tokens, so the admin brand colour, dark mode and automatic theme need
no per-theme rules. The old `[data-theme="dark"] … td:has(input:checked)` overrides are removed.

Windows high-contrast mode drops `box-shadow` and repaints borders and fills, which would make
a Picked card look unpicked now that the native control is hidden. Under
`@media (forced-colors: active)`, picked option cards and picked `.gridbtn` use
`forced-color-adjust: none; background: Highlight; color: HighlightText; border-color: Highlight`.
"Picked" here includes checked cards with a verdict class and grid buttons painted with their
row's verdict, and the forced-colors selectors must out-rank the
`tr.is-* input[checked]:checked + .gridbtn` rule. Because `forced-color-adjust`
inherits and these elements carry their own colours, the label, `.question__choice-text`, marker
and feedback inside such a card also get `color: HighlightText`. This
applies only in that mode, so D1 and D2 are unaffected.

### 3.2 Hiding the inputs

Inputs are hidden with the clip pattern (`position: absolute; width: 1px; height: 1px;
margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0`), as
`.settings-wrap .vh` does, with `position: relative` on the input's host (the option card; the
grid `label`) so focus cannot scroll the page to a stray location. They keep their `name`, `value`, `checked`, `disabled` and
`aria-invalid` attributes.

The option card's picked state depends on `:has()`, so its hiding rule lives inside
`@supports selector(:has(input:checked))`: a browser without `:has()` keeps visible native
inputs inside the outlined cards rather than losing the selection indicator. Grid buttons use
the sibling selector and need no `:has()` for their picked state, so grid inputs are hidden
unconditionally.

### 3.3 Choice question

`templates/courses/elements/_choicequestion_options.html`:

- `<li class="question__choice">` is the card and gains `question__choice--correct`,
  `--wrong` or `--missed` from `mk.kind` when a mark exists. `choice_marks` remains the only
  source of which options carry a mark; the template just paints it.
- `.question__choice` is `margin: 0` and the list is `display: grid; gap: 6px;
  grid-template-columns: minmax(0, 1fr)`, giving the mockup's gap. The zero track minimum stops a
  wide formula from growing the card past the page, which would leave the scroller below unused.
- The label fills the card's first row and is `display: flex; gap: var(--space-2)` with
  `margin: 0; color: var(--text-primary)`, with `cursor: pointer` while its input is live (overriding `app.css`'s `label` margin, which the
  removed `--marked` rule used to reset, and its `--text-secondary` colour). With the input hidden it is out of flow and the text is the only flex item; in the
  §3.2 fallback the visible native input sits beside the text.
- The label's padding is `5px 2.25rem 5px 14px` in logical properties and the `<li>` has none, so
  the label fills the card. The `2.25rem` is reserved on every card, marked or not, so text does
  not reflow on Check. The marker is positioned over that padding at the row's right edge (D8),
  aligned with the first line of the option text (`top: 9px; inset-inline-end: 14px` from the
  card, not centred, so feedback below cannot move it), with `pointer-events: none`, so the whole
  row stays the tap target. These replace the marker's old `display` and `margin` rules.
- `.question__choice-feedback` spans the full width beneath, inside the card, without its old
  left indent, with `padding: 4px 14px 9px`. It has `overflow-wrap: anywhere` and the same maths scroller
  rules as the option text below, since feedback can hold KaTeX.
- `.question__choice-text` is `display: block; flex: 1; min-width: 0; overflow-wrap: anywhere`.
  An inline formula can still break between its top-level terms; only an unbreakable run needs
  to scroll. Such wide maths, inline or display, scrolls inside this
  element with `overflow-x: auto; overflow-y: hidden; padding-block: 4px`. Those three travel
  together, as the repo's existing maths scrollers record, because `overflow-x` alone makes
  `overflow-y` compute to `auto` and KaTeX overhang then produces a vertical scrollbar. The
  label's vertical padding is `5px`, so the total stays the mockup's `9px`. The marker sits
  outside the scroller, so it stays visible in the card.
- `.question__choices--marked`, `marked_layout`, `question__choice--picked`, `show_picks` and
  the `.question__choice input:disabled` drawing block are removed (D9), with their context
  keys and comments in `ChoiceQuestionElement.render` and the header comment of
  `_choicequestion_options.html`, which describes the `--marked` layout.

Locked options get `cursor: default` and no hover, keyed on `input:disabled`.

### 3.4 Grids

`render_choice_grid` and `render_multigrid` (`courses/templatetags/courses_extras.py`):

- `<thead>` is dropped (D12). The `<table class="choicegrid|multigrid">`, `<tbody>`, row
  `is-correct`/`is-incorrect` classes, statement cell, `sr_verdict` text and input attributes
  all stay, so `courses/keycopy.py` and the row-painting code need no change.
- Each row has two cells: the statement, with `id="choicegrid-stmt-{row.pk}"` or
  `id="multigrid-stmt-{row.pk}"` (the two row models have independent pk sequences, so the id
  is namespaced per type), and one answers cell,
  `<td class="grid-answers-cell"><div class="grid-answers" role="group" aria-labelledby="{that id}">…</div></td>`,
  whose `<div>` holds one
  `<label><input …><span class="gridbtn">{column label}</span></label>` per column, using
  `format_html` escaping. The group role is on the inner `<div>` because a `<td>` may not take
  it. The cell is a single flex item, so the buttons move as a block (D12).
- Each input now has an accessible name of its own (the column label) and each group is named
  by its statement. The id is on the cell, so on a painted row the group name also includes the
  `sr_verdict` word, as intended. That replaces the context the header row gave (D6). `keycopy.py` already
  suffixes ids and `aria-labelledby` inside the copy.
- A painted row's statement gains a visible `<span class="grid-verdict" aria-hidden="true">` ✓ or
  ✗ after its text (D8), next to the existing `sr_verdict` text, outside the statement's scroller
  (below) so it cannot scroll out of view. No glyph on an unpainted row.

CSS (shared rule set for `.choicegrid` and `.multigrid`):

- The table is `table-layout: fixed`. Under auto layout, a wide formula in a statement widens the
  whole table (measured in Chromium and Firefox), so the statement never scrolls and the buttons
  leave the phone screen.
- `tbody tr` is `display: flex; flex-wrap: wrap`, the statement cell is
  `flex: 1 1 min(100%, 16rem); min-width: 0` with a 1px `--border-strong` bottom rule, and
  `.grid-answers-cell` is `flex: 0 1 auto; max-width: 100%`. Inside it `.grid-answers` is
  `display: flex; flex-wrap: wrap; padding: 3px 4px`. Rows have no padding of their own, so the
  distance between buttons in adjacent rows is 3 + 3 = the mockup's `6px`. The focus ring reaches
  4px out, so the two scroll wrappers get `padding-block: 1px` to keep the first and last rows'
  rings unclipped. This needs no breakpoint and also works in a narrow container: when a
  statement and all its buttons do not fit on one line, the whole button block drops below the
  statement, and the buttons wrap inside it if the block is still too wide (D12). Every row has
  the same flex basis, `min-width` and button widths, so all rows make the same decision. Where
  they do fit, as with very short labels, they share the line.
- `.gridbtn` is `display: block; height: 100%; text-align: center` and its text wraps
  (`max-width: 100%`, `overflow-wrap: anywhere`), so a sentence-length column label wraps as one
  outlined button, and neighbouring outlines stay level; only unbreakable content can reach the
  scroll wrapper.
- `.grid-answers label` is `margin: 0; cursor: pointer`, with `cursor: default` when its input is
  disabled.
- The statement cell has `display: flex; gap: var(--space-2)` and no vertical padding, above its
  bottom rule, and keeps `color: var(--text-primary)`. Its text is wrapped in
  `<span class="grid-stmt-text">`, which is `flex: 0 1 auto; min-width: 0; overflow-wrap: anywhere;
  overflow-x: auto; overflow-y: hidden; padding-block: 4px` (the three travel together, §3.3, and
  the padding gives the mockup's 4px), so a wide unbreakable formula scrolls inside the statement and cannot paint over the buttons.
  The `.grid-verdict` glyph follows it directly. The `.choicegrid-scroll` and
  `.multigrid-scroll` wrappers get `overflow-y: hidden`, for the same KaTeX reason as §3.3.
- For both grid types these go: `min-width: max-content`, the zebra stripes, the row rule, the
  print-only `min-width: 0` rule, the `td:has(input:checked)` cell tint, the `td label` hover
  background, and the old `th`/`td` padding, centring, `td.*__stmt` `min-width: 10rem`, `td label`
  and `td input` sizing and `accent-color` rules, which the rules here replace, and the `thead th`
  blocks. Selectors are written so nothing left over outranks them. The section comments in
  `courses.css` and the `render_choice_grid` and `render_multigrid` docstrings that describe a
  header row, the statement tint and bar, or the zebra stripes are updated. The `.scroll-x` and `-scroll` wrappers stay as a safety net
  for a pathologically wide column label such as a long formula; ordinary grids never overflow.
- The picked state hangs off the input: `input:checked + .gridbtn`; focus, hover and locked
  likewise key on the sibling input.
- Row colour: a button takes its row's verdict colour only while it is the pick the server
  rendered, `input[checked]:checked + .gridbtn` inside `tr.is-correct` or `tr.is-incorrect`. Rows
  stay live after a wrong Check, and the row class persists until the next render, so any other
  live pick uses Picked: a corrected pick must not turn red or green before it is checked.
- The statement cell's existing tint and inset bar
  (`tr.is-correct td.*__stmt` and `tr.is-incorrect td.*__stmt`) are replaced by the glyph, per
  mockup Y.

### 3.5 Hint (D7)

`<p class="question__hint">{% trans "Tick every correct answer." %}</p>` directly after the
stem in `choicequestion.html` (when `el.multiple`) and always in
`multigridquestionelement.html`. This sits outside the controls include, so the correct-answer
copy does not repeat it. It renders in every mode, matching mockup Y. That msgid already exists
in the catalogue with exactly the D7 Polish text, so no `.po`/`.mo` change is needed.

Style: `--text-secondary`, `14px`, `margin-bottom: var(--space-2)`.

### 3.6 Print (D10)

Outlines print by default. Picked and verdict cards and buttons get
`print-color-adjust: exact` so their tints survive, and cards and grid rows
(`.choicegrid tbody tr`, `.multigrid tbody tr`) get `break-inside: avoid`.

Paper cannot scroll, so in print `.question__choice-text`, `.question__choice-feedback` and
`.grid-stmt-text` are `overflow: visible`, or the new `auto` scrollers could print a scrollbar. An over-wide inline formula runs past its card on paper,
as it already overruns its row today.

### 3.7 Lesson marks, and consequences of the existing rules

**The one logic change.** `choice_marks`' lesson branch gains two cases so D4 holds in lessons,
both only for `c.pk in selected` (a no-JS lesson re-render hands one page-level `mark_result` to
every question, so the pick condition keeps sibling questions unmarked):

- A fully correct answer marks every pick ✓ (green).
- A wrong answer on a single-answer question marks the pick ✗ (red).

The verdict panel already says both. The method's "LESSON — unchanged" docstring and the
`_choicequestion_options.html` comment ("a lesson marks only the author-annotated ones") are
updated to match.

The rest are consequences of leaving the other rules alone, stated so they are not read as bugs:

1. **Wrong multi-answer lesson answers.** These still mark only options the author wrote feedback
   for, because marking the others would show which picks were right. Those picks stay teal and
   the panel carries the result.
2. **Grid colour is per row.** Grid verdicts exist per row, and a per-button verdict would leak
   the key. In a wrong multi-grid row, all picked buttons are red, even one that was right.
3. **Grids have no amber.** They show correct answers through the existing Your answer /
   Correct answer switch.
4. **Same render, more places.** The editor's try-out and the teacher's view of a student's
   answers reuse these templates, so they get the cards too. Their surrounding controls do not
   change (D11).

### 3.8 To confirm with the owner before implementation

D4 has no lesson or grid exception and D5 applies "this look" to both grid types, but the rules
above narrow D4 and add one logic change that is not in the table. The owner is asked to confirm
these visible consequences, and the answer is recorded here. D1–D12 stay as they are.

- In a lesson, a fully correct answer turns green with ✓, and a wrong single-answer pick turns
  red with ✗. This is new behaviour, reversing the current lesson rule.
- In a lesson, a wrong multi-answer pick stays teal, and only options with author feedback change
  colour. A missed correct option goes amber only if the author wrote feedback for it.
- Grids never show amber, and in a wrong multi-answer grid row a correct pick shows red.
- A picked option's text is not heavier than an unpicked one, as it was in mockup C, because a
  heavier label would misalign grid buttons.

## 4. Data flow

Unchanged, apart from the lesson branch of `choice_marks` (§3.7). The same fields post,
`build_answer` and `mark` are untouched, and `part_verdicts` produces the same values. The server renders cards where it rendered rows,
including in the HTML fragments returned after Check. `quiz.js` and `editor.js` still disable
inputs on lock, and `:disabled` styling follows.

## 5. Error handling

There are no new failure paths. The two degraded cases are:

- A browser without `:has()` shows native inputs (§3.2).
- A very wide grid label scrolls inside the retained wrapper (§3.4).

Long option text wraps and wide maths scrolls inside the card without widening the page, by the
`.question__choice-text` rules in §3.3. A wide formula in author feedback or in a grid statement
scrolls inside that element (§3.3, §3.4).

## 6. Testing

Existing tests that pin the removed markup (`<thead>`, `question__choice--picked`, disabled
drawing, `--marked` layout, statement tints) are updated to the new behaviour, not deleted
wholesale. Each still has to assert something that fails on a broken build.

`tests/test_choicegrid_styles.py` pins the removed `td:has(input:checked)` selector and
`accent-color`, so it moves to the new rules.

Three groups of existing browser tests need more than a selector change:

- Tests that call `.check()` on these inputs will time out, because Playwright refuses clipped
  inputs. The plan derives the full list by searching `.check(` against these selectors; at least
  `test_e2e_questions.py`, `test_e2e_locked_controls_look.py`, `test_e2e_scroll_affordance.py`,
  `test_e2e_choicegrid.py`, `test_e2e_multigrid.py`, `test_e2e_nested_question.py`,
  `test_e2e_question_lock.py`, `test_e2e_practice_state.py`, `test_e2e_quiz_reveal_pr2.py`,
  `test_e2e_quiz_reveal_pr3.py`, `test_e2e_quiz_choice_marking.py` and
  `test_e2e_choice_inline_feedback.py` are affected. They click the visible card or `.gridbtn` instead, and
  `force=True` is not allowed in any test that proves clickability.
- `test_e2e_wide_content_scroll.py` and `test_e2e_scroll_affordance.py` use a four-column grid as
  their over-wide seed, and the first also reads `thead th`. Ordinary grids no longer overflow, so these are
  re-seeded with a long KaTeX formula as a column label, written as a single unbreakable box
  such as `{a+b+…}` (`overflow-wrap: anywhere` breaks plain text, and KaTeX can break between
  top-level terms), and wait for KaTeX before measuring, keeping the proof that the §5 fallback
  scroller and its edge shading still work, and repointed to a button.
- `test_e2e_print_layout.py::test_grid_question_fits_print_width` asserts the grid overflows on
  screen first, which is no longer true. It becomes: at print width every `.gridbtn` ends inside
  the scroll box and the statement wraps, with a precondition that fails if the flex or wrap rules
  are removed. Its print shade assertion is the only print guard of that rule, so it moves onto
  the re-seeded over-wide grid: wait for `.scroll-x.is-scroll-end`, emulate print, and assert
  `::after` is `display: none`.

New or updated coverage:

- **Render (no browser):** `<thead>` absent; each answer cell carries its escaped column label;
  input `name`, `value`, `checked` and `aria-invalid` unchanged; key copy still strips names and
  suffixes the statement id and `aria-labelledby`; verdict classes map one-to-one from mark kinds;
  statement glyph present only on painted rows; hint present exactly when multi-answer, and once
  only when a key copy exists; each new lesson mark case, including a wrong multi-answer lesson
  answer staying unmarked apart from author-annotated options, and a no-JS lesson re-render
  where the checked question has a real pick (correct, then wrong single-answer) and its sibling
  renders no marks; a choice grid and a multi-grid whose rows share a pk emit distinct statement
  ids.
- **CSS source:** the option-card input hiding is inside the `@supports` block and the grid input
  hiding is not; picked thickness is a
  `box-shadow`, not `border-width`; every `test_*css*.py` runs.
- **Browser (Playwright, `-m e2e`):**
  - Clicking a card selects it and changes its computed outline and background; a single-answer
    question has one pick at a time.
  - Keyboard: Tab reaches the group, arrows or Space change the pick, and the focus ring is visible.
  - Submitted values are unchanged end to end.
  - Accessibility tree: each unpainted grid row exposes a group named exactly by its statement,
    and a painted row's group name contains it, with inputs named by column.
  - Adjacent grid rows' buttons are `6px` apart.
  - After Check, in quiz mode and in lesson mode, correct, wrong and missed cards have the §3.1
    colours and marks; a locked card does not respond to clicks. The matrix cells for picking an
    amber card and unpicking a red card are asserted.
  - In a painted live grid, changing a pick gives the new button Picked colours, not danger.
  - A wide unbreakable formula in a grid statement at desktop width stays left of the first button.
    At 360px such a statement has wrapper `scrollWidth <= clientWidth`, `.grid-stmt-text`
    `scrollWidth > clientWidth`, every `.gridbtn` right edge inside the wrapper, and a painted row's
    `.grid-verdict` in view.
  - `.grid-answers` stays transparent with a pick. The marker sits above any feedback, in the
    option's first line.
  - With `forced_colors="active"`, picked and unpicked cards and buttons differ, and the marker
    and `.question__choice-text` in a picked verdict card compute to the HighlightText value. A
    verdict-painted `.gridbtn` computes to the Highlight background and HighlightText colour.
  - With fixture labels long enough not to fit beside a statement, at 360px and at a width where
    the statement plus one button fits but the statement plus all buttons does not, every button
    is below the statement, the page has no horizontal overflow, `.choicegrid-scroll` and
    `.multigrid-scroll` have `scrollWidth - clientWidth <= 0`, and every `.gridbtn` right edge is
    inside that box. A grid whose last-row statement holds a fraction has
    `scrollHeight <= clientHeight` on the wrapper and on `.grid-stmt-text`, the latter with an A/B
    against removing its padding. At desktop width statement and
    buttons share a line. A sentence-length column label at 360px wraps.
  - At 360px, an option holding a wide unbreakable inline formula and one holding display maths keep their
    content and marker inside the card, with no page overflow. An option holding a normal inline
    formula has `scrollHeight <= clientHeight` on its text element.
  - Dark theme and a custom brand colour resolve from tokens.
  - Print emulation keeps the outlines and picked tints, and an option, a feedback and a grid
    statement each holding a wide formula print no scrollbar.

CSS assertions need an A/B (the property differs with and without the rule). Mutation-check
the new guards.
