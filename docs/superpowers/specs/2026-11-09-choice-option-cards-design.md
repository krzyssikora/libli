# Choice questions as outlined option cards

## 1. Purpose

Student-facing choice questions show native radio buttons and checkboxes. The owner finds
the look of the original LAL course better: no visible controls, thin rounded outlines on
every option, and a clear picked state. This restyles single/multiple choice questions and
both grid question types to that look, in libli's own (admin-definable) brand colours, across
every state they render in.

This is a presentation change. Nothing about marking, stored answers, submitted field names,
what is revealed to a student and when, or the question-type editors changes.

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
`choice-after-check.html` (variant Y). Their numbers are restated in §3 so the build does not
depend on those files.

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

Colour and thickness are separate: the result colour comes from a verdict class, the
thickness and tint-as-picked from `:has(input:checked)`. In a lesson or an unlocked quiz the
inputs stay live after Check, so a student can move their pick away from a red card; that
card stays red with its ✗ (exactly as the ✗ stays today) but drops to the thin outline, and the
new pick reads as picked.

All colours are existing tokens, so the admin brand colour, dark mode and automatic theme need
no per-theme rules. The old `[data-theme="dark"] … td:has(input:checked)` overrides are removed.

### 3.2 Hiding the inputs

Inputs are hidden with the clip pattern (`position: absolute; width: 1px; height: 1px;
margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0`), as
`.settings-wrap .vh` does, with `position: relative` on the card so focus cannot scroll the
page to a stray location. They keep their `name`, `value`, `checked`, `disabled` and
`aria-invalid` attributes.

The picked state depends on `:has()`. The hiding rule therefore lives inside
`@supports selector(:has(input:checked))`: a browser without `:has()` keeps visible native
inputs inside the outlined cards rather than losing the selection indicator.

### 3.3 Choice question

`templates/courses/elements/_choicequestion_options.html`:

- `<li class="question__choice">` is the card and gains `question__choice--correct`,
  `--wrong` or `--missed` from `mk.kind` when a mark exists. `choice_marks` remains the only
  source of which options carry a mark; the template just paints it.
- The label fills the card's first row, so the whole row is the tap target, with the padding
  on the label. The marker sits at the row's right edge (D8). `.question__choice-feedback`
  spans the full width beneath, inside the card, without its old left indent.
- `.question__choices--marked`, `marked_layout`, `question__choice--picked`, `show_picks` and
  the `.question__choice input:disabled` drawing block are removed (D9), with their context
  keys and comments in `ChoiceQuestionElement.render`.

Locked options get `cursor: default` and no hover, keyed on `input:disabled`.

### 3.4 Grids

`render_choice_grid` and `render_multigrid` (`courses/templatetags/courses_extras.py`):

- `<thead>` is dropped (D12). The `<table class="choicegrid|multigrid">`, `<tbody>`, row
  `is-correct`/`is-incorrect` classes, statement cell, `sr_verdict` text and input attributes
  all stay, so `courses/keycopy.py` and the row-painting code need no change.
- Each answer cell becomes `<td><label><input …><span class="gridbtn">{column label}</span></label></td>`,
  using `format_html` escaping. The radio now has an accessible name of its own.
- A painted row's statement gains a visible `aria-hidden` ✓ or ✗ after its text (D8), next to
  the existing `sr_verdict` text. No glyph on an unpainted row.

CSS (shared rule set for `.choicegrid` and `.multigrid`):

- `tbody tr` is `display: flex; flex-wrap: wrap`, the statement cell is
  `flex: 1 1 min(100%, 16rem)` with a 1px `--border-strong` bottom rule, and answer cells are
  `flex: 0 0 auto`. This needs no breakpoint: when a statement and its buttons do not fit on
  one line, the buttons drop below the statement and wrap as needed (D12). Every row has the
  same flex basis and the same button widths, so all rows make the same decision.
- `min-width: max-content`, the zebra stripes, the row rule, and the print-only
  `min-width: 0` rule are removed. The `.scroll-x` and `-scroll` wrappers stay as a safety net
  for a pathologically wide column label such as a long formula; ordinary grids never overflow.
- The picked state and row colour follow §3.1: within a painted row, picked buttons take the
  row's verdict colour. The statement cell's existing tint and inset bar
  (`tr.is-correct td.*__stmt` and `tr.is-incorrect td.*__stmt`) are replaced by the glyph, per
  mockup Y.

### 3.5 Hint (D7)

`<p class="question__hint">{% trans "Tick every correct answer." %}</p>` directly after the
stem in `choicequestion.html` (when `el.multiple`) and always in
`multigridquestionelement.html`. This sits outside the controls include, so the correct-answer
copy does not repeat it. It renders in every mode, matching mockup Y. That msgid already exists
in the catalogue with exactly the D7 Polish text, so no `.po`/`.mo` change is needed.

Style: `--text-secondary`, slightly smaller than body text.

### 3.6 Print (D10)

Outlines print by default. Picked and verdict cards and buttons get
`print-color-adjust: exact` so their tints survive, and cards get `break-inside: avoid`.

### 3.7 Consequences of the existing rules

These follow from leaving marking logic alone. They are stated here so they are not read as
bugs:

1. **Lessons colour only marked options.** In a lesson `choice_marks` marks only options the
   author wrote feedback for, so a wrong pick without author feedback stays teal and the verdict
   panel carries the result. Painting more would reveal the answer key in lessons.
2. **Grid colour is per row.** Grid verdicts exist per row, and a per-button verdict would leak
   the key. In a wrong multi-grid row, all picked buttons are red, even one that was right.
3. **Grids have no amber.** They show correct answers through the existing Your answer /
   Correct answer switch.
4. **Same render, more places.** The editor's try-out and the teacher's view of a student's
   answers reuse these templates, so they get the cards too. Their surrounding controls do not
   change (D11).

## 4. Data flow

Unchanged. The same fields post, `build_answer` and `mark` are untouched, and `part_verdicts`
and `choice_marks` produce the same values. The server renders cards where it rendered rows,
including in the HTML fragments returned after Check. `quiz.js` and `editor.js` still disable
inputs on lock, and `:disabled` styling follows.

## 5. Error handling

There are no new failure paths. The two degraded cases are:

- A browser without `:has()` shows native inputs (§3.2).
- A very wide grid label scrolls inside the retained wrapper (§3.4).

Long option text and display maths must wrap or scroll inside the card without widening the
page: the label is `min-width: 0` and text uses `overflow-wrap: anywhere` where it does not
disturb KaTeX.

## 6. Testing

Existing tests that pin the removed markup (`<thead>`, `question__choice--picked`, disabled
drawing, `--marked` layout, statement tints) are updated to the new behaviour, not deleted
wholesale. Each still has to assert something that fails on a broken build.

New or updated coverage:

- **Render (no browser):** `<thead>` absent; each answer cell carries its escaped column label;
  input `name`, `value`, `checked` and `aria-invalid` unchanged; key copy still strips names; verdict
  classes map one-to-one from mark kinds; statement glyph present only on painted rows; hint present
  exactly when multi-answer, and once only when a key copy exists.
- **CSS source:** the input hiding is inside the `@supports` block; picked thickness is a
  `box-shadow`, not `border-width`; every `test_*css*.py` runs.
- **Browser (Playwright, `-m e2e`):**
  - Clicking a card selects it and changes its computed outline and background; a single-answer
    question has one pick at a time.
  - Keyboard: Tab reaches the group, arrows or Space change the pick, and the focus ring is visible.
  - Submitted values are unchanged end to end.
  - After Check, correct, wrong and missed cards have the §3.1 colours and marks; a locked card
    does not respond to clicks.
  - At 360px width a grid has no horizontal page overflow, each statement is above its buttons,
    and at desktop width statement and buttons share a line.
  - Dark theme and a custom brand colour resolve from tokens.
  - Print emulation keeps the outlines and picked tints.

CSS assertions need an A/B (the property differs with and without the rule). Mutation-check
the new guards.
