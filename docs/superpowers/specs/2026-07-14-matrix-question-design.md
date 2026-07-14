# Matrix question — design

**Status:** approved design, pre-plan
**Date:** 2026-07-14
**Type:** new content element — the 10th `QuestionElement` subclass

## Purpose

A **Matrix question** presents N statements, each answered by choosing one of a
**shared set of columns**. It is a graded question type (partial credit per row)
that works both formatively in lessons and scored in quizzes, like every other
question type. True/false is a two-column preset, not a separate type.

It ports the legacy Demo-Course widgets **true/false** (`.truth`/`.false`/
`.confirmTF`) and **one choice in line** (`.one_choice`/`.confirm_choice`) into a
single native element. The multi-select-per-row variant (`.multi_many_ans`) and
per-option feedback (`.mult_feedback_incorrect`) remain separate future slices.

## Decisions (locked in brainstorming, 2026-07-14)

1. **Family:** graded `QuestionElement` subclass — NOT an Interactive-group
   self-check. Integrates with `MarkResult`, quiz scoring/results, and the
   `[A]`/`[N]`/`[R]` marking modes. Effective marking mode is `[A]` (auto).
2. **Grid shape:** shared columns (a classic matrix). Columns are defined once;
   each row is a statement whose answer is exactly one column. Per-row-varying
   option sets are dropped (YAGNI).
3. **Selection:** single-select per row (radio). Multi-select-per-row is a
   separate future slice.
4. **Scoring:** partial credit. `fraction = correct_rows / total_rows`;
   `correct` is true only when every row is right and there is ≥1 row.
5. **Name:** palette/label **"Matrix question"**, in the Questions group.
6. **Nestable:** NO. Top-level only, consistent with all 9 existing question
   types (none are in `NESTABLE_TYPE_KEYS` today). Matrix stays out of it.

## Architecture / components

### Prior art it mirrors

`MatchPairQuestionElement` (`courses/models.py`) is the structural template: a
`QuestionElement` subclass with relational sub-rows (`MatchPair`, FK + `order`
`OrderField`), `build_answer`/`mark` computing per-row correctness into a
`fraction` + a `reveal` tuple, and a `REVEAL_TEMPLATE`. The matrix differs only
in having two relational children (columns and rows) instead of one.

`ChoiceQuestionElement` is the reference for choice validation:
`build_answer` coerces/validates submitted ids against the question's own rows,
silently dropping foreign/forged ids (never error-leaking).

### Data model

Three models, mirroring the MatchPairs relational shape:

- **`ChoiceGridQuestionElement(QuestionElement)`** — inherits `stem`,
  `explanation`, and the marking-mode/max-marks/attempts fields. Adds
  `elements = GenericRelation(Element)` and
  `REVEAL_TEMPLATE = "courses/elements/_reveal_choicegrid.html"`.
  (Class name keeps the internal "choicegrid" identity; the human label is
  "Matrix question".)
- **`GridColumn`** — `question` FK (`related_name="columns"`),
  `label` `CharField(max_length=500)` (plain text + KaTeX delimiters, never
  sanitised — like `Choice.text`), `order` `OrderField(for_fields=["question"])`.
- **`GridRow`** — `question` FK (`related_name="rows"`),
  `statement` `CharField(max_length=500)` (plain text + KaTeX),
  `correct_column` FK → `GridColumn` (`on_delete=CASCADE`), `order` `OrderField`.

Ordering `["order", "pk"]` on both children (stable render/reveal order, as with
MatchPairs). A migration adds all three tables plus the `ELEMENT_MODELS`
validation-only `AlterField` on `Element` (as every prior question type did).

**Authoring invariants** (enforced in the form/formset `clean`):
- ≥1 column and ≥1 row.
- Column labels within a question are non-blank; blank rows/columns pruned.
- Each row's `correct_column` must reference a column belonging to the same
  question (formset cross-validation; a forged/foreign column id is a validation
  error, not a silent save).

## Data flow

### Marking

Answer payload is **id-based, per row** (robust to reorder — id-keyed, not
positional): each row's radio group is `name="row_<rowpk>"`, `value="<colpk>"`.

`build_answer(post)` returns a dict `{row_pk: col_pk}` built only from the
question's own rows/columns (submitted ids validated against
`self.rows`/`self.columns`; unknown/forged ids dropped — mirrors
`ChoiceQuestionElement.build_answer`).

`mark(answer)` iterates rows in order:
- a row is correct when `answer.get(row.pk) == row.correct_column_id`;
- `n_correct = #correct rows`, `n = #rows`;
- `MarkResult(correct=(n_correct == n and n > 0), fraction=(n_correct/n if n else 0.0), reveal=<per-row tuple>)`.

`reveal` is a tuple of per-row dicts carrying enough for the results page to show
the correct column (e.g. `{"statement", "correct_label", "chosen_label"|None, "is_correct"}`),
built in stable row order (mirrors the MatchPairs reveal-tuple construction).

Earned marks flow through the existing scoring path unchanged
(`earned_marks = fraction × max_marks`).

### Student render & no-JS baseline

`ChoiceGridQuestionElement.render(...)` mirrors the other question `render`
overrides (same kwargs: `element`, `feedback_for_pk`, `mode`, `action_url`,
`locked`, `attempts_left`, feedback plumbing). It renders
`courses/elements/choicegrid.html`:

- a table (or CSS grid) with a header row of column labels and one body row per
  statement;
- each body row is one native radio group: `name="row_<rowpk>"` with a radio per
  column `value="<colpk>"`.

**The native radios are the source of truth.** No-JS posts the full form to the
existing `check_answer` (lesson) / quiz-answer endpoints and marks correctly.
Any JS is decoration only (e.g. inline-KaTeX pass over statements/labels, same as
`question.js` does for choice questions; button-styled labels are optional
polish). This follows the DnD "select-is-source-of-truth, JS decorates" rule.

Previously-selected columns repopulate from the submitted/persisted answer on
re-render (checked state per row), matching how choices repopulate from
`selected_ids`.

### Reveal / feedback

One `_reveal_choicegrid.html`, following the fill-blank/DnD results convention:
- a **correct** row shows ✓ only (no answer echoed);
- a **wrong or unanswered** row reveals its correct column;
- the global `explanation` renders as it does for all question types.

Lesson (formative) shows feedback immediately; quiz withholds until locked — both
handled by the existing `quiz_feedback_context`/reveal-gating plumbing threaded
through `mode`/`locked`, no new logic.

### Authoring editor

`_edit_choicegrid.html` partial (dynamically included by `_host_form.html`), plus
a Questions-group add-menu card.

- **Columns section:** add / remove / reorder column labels (inline formset,
  clone-row pattern used by choice/match editors). Column text uses the shared
  RTE/∑ math-input contract (`[data-math-field]`/`[data-math-trigger]`).
- **Rows section:** each row = a statement field + a "correct column" selector
  whose options are the current columns. Statement uses the RTE/∑ contract.
- **True/False preset:** a one-click button that seeds two columns
  ("True"/"False", localised) into the empty columns formset — pure client-side
  convenience over the same underlying model (no special-casing server-side).
- On edit, the correct-column selector is repopulated from the saved columns;
  renaming/reordering columns keeps row→column links intact (id-based FK).

`ChoiceGridQuestionElementForm` + two inline formsets (columns, rows) with the
cross-validation above. Formset is built in BOTH `_render_open_form` (display)
and `builder.save_element` (save), as with every prior formset-bearing type.
`element_add` seeds an empty grid; `save_element` persists atomically
(`@transaction.atomic`, 409-before-422), as choice/match do.

### JS enhancer

`choicegrid.js` (or fold into the existing question enhancer) providing: inline
KaTeX over statements/labels; the True/False preset button; add/remove/reorder
column & row formset rows; correct-column `<select>` option sync when columns
change. Wired into **both** `editor.js` (re-run after fragment swap, next to the
other question/gallery re-inits) **and** `editor.html` (`<script defer>` tag) —
the double-wire that has been missed twice before. A test GETs `manage_editor`
and asserts the script tag is present.

### Transfer (export/import)

New entries in the transfer trio (`SERIALIZERS`/`VALIDATORS`/`BUILDERS`), transfer
key `choice_grid` (snake_case; may differ from the form key `choicegrid`).
Serialise `stem`/`explanation`/marking fields + the ordered columns (label) +
ordered rows (statement + correct-column reference by export-local index/id).
Because sub-tables change the on-disk shape, **bump `FORMAT_VERSION`**. The
importer rebuilds columns first, then rows resolving each `correct_column`
against the freshly-created columns (two-pass, as tabs/match importers do).

## Visual design (frontend-design pass — required)

Both new surfaces get a dedicated **frontend-design** pass (per the user's
explicit instruction), consistent with the token-driven bespoke CSS system
(no Bootstrap/React), light + dark, verified by screenshots:

1. **Student render** — the matrix table: a clean header row of column labels and
   statement rows with radio cells. Must read as a coherent quiz question in the
   warm-teal identity, align columns cleanly, be legible with KaTeX in
   statements/labels, be usable on narrow/mobile widths (horizontal scroll or a
   stacked fallback rather than overflow), and style selected/correct/incorrect
   cell states within the existing feedback vocabulary. True/false (2-column) and
   wider (3–4 column) grids should both look intentional.
2. **Authoring editor** (`_edit_choicegrid.html`) — the columns section, the rows
   section with per-row correct-column selector, and the True/False preset button,
   styled to match the existing choice/match editors' vocabulary (clone-row
   controls, RTE/∑ affordances) rather than raw form defaults.

The frontend-design work is a distinct plan task (or tasks) after the functional
render/editor exist, and its output is screenshot-verified in both themes before
the branch is considered done.

## Error handling

- **Forged / foreign ids:** `build_answer` validates every submitted row/column
  id against the question's own children and drops unknown ids — a forged column
  id simply counts that row wrong, never errors or leaks.
- **Authoring validation:** formset `clean` rejects a row whose `correct_column`
  is not one of this question's columns, an empty grid (0 rows or 0 columns), and
  blank labels; invalid saves persist nothing (`@transaction.atomic`), returning a
  422 that re-renders the bound form; a stale unit token returns 409 before 422.
- **No correctness leak:** the correct column is serialised only on the
  answered/locked reveal path (`feedback_for_pk` gate + quiz withhold-until-locked);
  the initial GET and any non-answered element render carry no reveal data.
- **Empty answer:** a submission with no radios selected marks every row wrong
  (`fraction == 0.0`), never raising.

## Touchpoints (new-element-type checklist)

Per the canonical checklist: `ELEMENT_MODELS` + concrete models + migration;
`FORM_FOR_TYPE`; `save_element` branch; `_add_menu.html` card (Questions group);
`element_add`/`element_save` allow-tuples; `_EDITOR_TYPE_LABELS`;
`_ELEMENT_LABELS` + `element_summary`; student `choicegrid.html`; edit-form
`_edit_choicegrid.html`; reveal `_reveal_choicegrid.html`; transfer trio + bump
`FORMAT_VERSION`; i18n EN/PL; JS enhancer wired into `editor.js` AND `editor.html`
(+ script-presence test); a `manage_element_add` GET/POST-200 authoring test for
the new type. NOT added to `NESTABLE_TYPE_KEYS` (top-level only).

## Out of scope (YAGNI / future slices)

- Multi-select-per-row grid (`.multi_many_ans`).
- Per-option / per-row feedback messages (`.mult_feedback_incorrect`).
- Per-row-varying column sets.
- Nesting inside Tabs.

## Testing

- Model marking: all-correct → `fraction==1.0, correct==True`; partial →
  correct fraction, `correct==False`; empty answer → 0.0; forged/foreign col/row
  ids dropped (no error, counted wrong).
- `build_answer` id-validation against own rows/columns.
- No-leak: correct column never serialised except on the answered/locked reveal
  path; initial GET clean; quiz withhold-until-locked honoured.
- Reveal: correct row shows ✓ only; wrong/unanswered reveals correct column.
- Authoring: `manage_element_add` GET+POST 200; column/row formset
  cross-validation (row→foreign-column rejected); True/False preset seeds two
  columns; edit repopulates correct-column selectors.
- Transfer round-trip: export → import rebuilds columns then rows with links
  intact; `FORMAT_VERSION` bumped; schema test count updated.
- `editor.html` loads `choicegrid.js`.
- Playwright e2e: answer a grid in a lesson (immediate feedback) and in a quiz
  (withheld → locked → results reveal), driving the real radio clicks.
- Frontend-design: screenshot both surfaces (student render + editor) in light
  and dark; a CSS-presence/render guard for the matrix table classes.
