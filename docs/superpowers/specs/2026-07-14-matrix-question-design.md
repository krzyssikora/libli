# Matrix question — design

**Status:** approved design, pre-plan
**Date:** 2026-07-14
**Type:** new content element — the 9th concrete `QuestionElement` subclass
(after Choice, ShortText, ShortNumeric, FillBlank, DragFillBlank, MatchPair,
DragToImage, ExtendedResponse). Note the palette shows more *cards* than
subclasses (Choice contributes two: single + multiple).

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
   `[A]`/`[N]`/`[R]` marking modes. It exposes the standard author-selectable
   `marking_mode` (via `_MarkingFieldsMixin`, like every graded type) and simply
   **defaults to `AUTO`** — it does NOT hard-pin `[A]`; there is no "effective
   marking mode" special-casing to implement.
2. **Grid shape:** shared columns (a classic matrix). Columns are defined once;
   each row is a statement whose answer is exactly one column. Per-row-varying
   option sets are dropped (YAGNI).
3. **Selection:** single-select per row (radio). Multi-select-per-row is a
   separate future slice.
4. **Scoring:** partial credit. `fraction = correct_rows / total_rows`;
   `correct` is true only when every row is right and there is ≥1 row.
5. **Name:** palette/label **"Matrix question"**, in the Questions group.
6. **Nestable:** NO. Top-level only, consistent with every existing question
   type (none are in `NESTABLE_TYPE_KEYS` today). Matrix stays out of it.

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
  `correct_column` FK → `GridColumn` with **`on_delete=models.PROTECT`** (NOT
  `CASCADE` — see column-deletion semantics below), `order` `OrderField`.

Ordering `["order", "pk"]` on both children (stable render/reveal order, as with
MatchPairs). A migration adds all three tables plus the `ELEMENT_MODELS`
validation-only `AlterField` on `Element` (as every prior question type did).

**Authoring invariants** (enforced in the form/formset `clean`):
- ≥1 column and ≥1 row.
- Column labels within a question are non-blank; blank rows/columns pruned.
- Each row's `correct_column` must reference a column belonging to the same
  question (formset cross-validation; a forged/foreign temp-id is a validation
  error, not a silent save).
- **Column deletion is guarded:** deleting a column still referenced by a row's
  `correct_column` is a validation error — the author must re-point or remove those
  rows first. This never silently drops statements. `on_delete=PROTECT` is the
  DB-level backstop for that rule (a bypass raises, never silent data loss). The
  atomic save orders row re-points/removals before column deletion so a legitimate
  same-submission "delete a column and re-point its rows" rebuild does not trip
  PROTECT.

## Data flow

### Marking

The answer payload is a **JSON-safe positional list aligned to rows**, mirroring
`MatchPairQuestionElement`'s `getlist("slot")` — NOT an id-keyed dict. This is
load-bearing: the quiz path persists the answer through a `JSONField`
(`answer_to_json`) and re-marks it on the results page by calling
`question.mark(answer_from_json(...))` (`courses/views.py::_stored_result`); a
dict `{row_pk: col_pk}` would rehydrate with **string** keys (`{"5": 3}`) so
`answer.get(int_pk)` would miss every key and mark every row wrong. A positional
list of ints round-trips through JSON unchanged, exactly as MatchPairs relies on.

- **HTML:** each row's radio group is `name="row_<rowpk>"`, `value="<colpk>"`
  (id-based names keep the markup robust and unambiguous).
- **`build_answer(post)`** iterates `self.rows.all()` in stable order and, for
  each row, reads `post.get("row_<rowpk>")`, int-coercing and validating it
  against this question's own column pks (`self.columns`). A **valid answered row
  stores the column pk as an int**; an unknown/forged/blank value stores the
  **empty-string sentinel `""`** (that row unanswered). Returns an **ordered list**
  aligned positionally to rows, e.g. `[colpk_int_or_"", ...]`. The `""` sentinel
  (NOT `None`) is deliberate and load-bearing — see the persistence note below.
  Foreign/forged ids are dropped, never error-leaking (mirrors
  `ChoiceQuestionElement.build_answer`).

`mark(answer)` first **normalises the incoming list to exactly `len(rows)`** by
padding/truncating with the `""` sentinel — `answer = (answer + [""] * n)[:n]` —
BEFORE any per-row comparison, mirroring `FillBlankQuestionElement.mark`'s
`vals = (vals + [""] * n)[:n]` guard. This is load-bearing: the results page
re-marks a **stored** `latest_answer` (`views.py::_stored_result` via
`answer_from_json`), and if rows were added after the answer was stored a raw
`answer[i]` would raise `IndexError` (a 500 on the results page). After
normalising, it iterates rows in order:
- a row is correct when `answer[i] == rows[i].correct_column_id`;
- `n_correct = #correct rows`, `n = #rows`;
- `MarkResult(correct=(n_correct == n and n > 0), fraction=(n_correct/n if n else 0.0), reveal=<per-row tuple>)`.

`reveal` is a tuple of per-row dicts carrying enough for the results page to show
the correct column (e.g. `{"statement", "correct_label", "chosen_label"|None, "is_correct"}`),
built in stable row order and indexed positionally (mirrors the MatchPairs
reveal-tuple construction). **Both labels resolve through a single
`{col.pk: col.label}` map** built once from the question's current columns — NOT
via `row.correct_column.label`. This is load-bearing for the prefetch: prefetching
the reverse `columns` relation does NOT populate the forward
`GridRow.correct_column` cache, so `row.correct_column.label` would fire one query
per row inside `build_quiz_context`'s `_stored_result` loop — the exact N+1 the
prefetch exists to prevent. So `correct_label = label_map[row.correct_column_id]`
and `chosen_label = label_map.get(chosen_pk)`. `chosen_label` **falls back to
`None`** when the stored chosen pk is absent from the map — a student may have
selected a column later deleted (PROTECT only guards a column that is some row's
`correct_column`, not one merely selected), so the lookup must not assume it
resolves. (`correct_label` always resolves, since PROTECT keeps every referenced
correct column alive.)

**Persistence-helper confirmation** (the `""`-sentinel makes the payload behave
exactly like MatchPairs' list, so the existing generic list branches are correct —
NOT merely "to be verified"): `answer_is_empty` is
`not any(str(v).strip() for v in answer)` (`courses/quiz.py`), so an all-`""` list
correctly reads as **empty** (`str("").strip()` is falsy) — whereas an all-`None`
list would NOT, because `str(None) == "None"` is truthy; this is precisely why the
sentinel is `""` and not `None`, and no `choice_grid` branch in `answer_is_empty` is
needed. `answer_to_json` serialises the list unchanged; `answer_from_json` returns
the list (int and `""` entries both survive JSON — no string-key problem);
`rehydrate` returns `set()` for the choice `selected_ids` slot and routes the list
to `latest_answer`/`submitted_values`. `mark` compares `answer[i]` (int or `""`)
against `rows[i].correct_column_id` (int), so `""` never matches → unanswered rows
count wrong.

Earned marks flow through the existing scoring path unchanged
(`earned_marks = fraction × max_marks`).

### Student render & no-JS baseline

`ChoiceGridQuestionElement` does **NOT** override `render` — it uses the base
`QuestionElement.render`, exactly as `MatchPairQuestionElement` does (verified: the
base render derives the template path from `self._meta.model_name` and already
passes `submitted_values`, `mark_result`, `reveal_template`, `mode`, `locked`,
`attempts_left`, and the feedback plumbing). No `render` override and no extra
render **context** are needed. The student template is named by the model:
`courses/elements/choicegridquestionelement.html`.

**No-JS grid markup is built by a Python simple tag, not in-template.** Django
templates cannot index a positional list by a loop variable, so the template
CANNOT itself "zip" `self.rows` against the `submitted_values` list to set each
row's checked radio. Every relational question type in this codebase renders its
no-JS widget through a `@register.simple_tag` that builds the HTML in Python
(`render_match_pairs` / `render_image_selects` / `render_dnd_selects` in
`courses_extras.py`). The matrix adds an analogous **`render_choice_grid`** tag
(+ its Python builder) that receives `el` and the positional `submitted_values`
list and emits the table (rows × columns), marking the selected radio per row.
The student template just invokes that tag. This is an explicit touchpoint.

The rendered table is:

- a table (or CSS grid) with a header row of column labels and one body row per
  statement;
- each body row is one native radio group: `name="row_<rowpk>"` with a radio per
  column `value="<colpk>"`.

**The native radios are the source of truth.** No-JS posts the full form to the
existing `check_answer` (lesson) / quiz-answer endpoints and marks correctly.
Any JS is decoration only (e.g. inline-KaTeX pass over statements/labels, same as
`question.js` does for choice questions; button-styled labels are optional
polish). This follows the DnD "select-is-source-of-truth, JS decorates" rule.

Previously-selected columns repopulate per-row from **`submitted_values`** (the
positional list), NOT from `selected_ids`. `selected_ids` is a flat pk `set` used
only by `ChoiceQuestionElement`; `check_answer` routes any non-set answer to
`submitted_values` and `rehydrate` returns `set()` for the choice slot, so the
matrix's list arrives via `submitted_values`/`latest_answer`. The
`render_choice_grid` tag consumes that list and sets each row's checked radio
(entries are ints or the `""` sentinel, per the Marking section).

**`None` / short `submitted_values`.** On the initial lesson GET and the quiz
first attempt the tag receives `submitted_values=None` (not a list), and a stored
list can be shorter than the current row count. The tag must treat `None` and any
missing/short position as "nothing selected" (no row spuriously checked),
mirroring `render_match_pairs(el, submitted_values=None)`.

### Reveal / feedback

One `_reveal_choicegrid.html`, following the fill-blank/DnD results convention:
- a **correct** row shows ✓ only (no answer echoed);
- a **wrong or unanswered** row reveals its correct column;
- the global `explanation` renders as it does for all question types.

Lesson (formative) shows feedback immediately; quiz withholds until locked — both
handled by the existing `quiz_feedback_context`/reveal-gating plumbing threaded
through `mode`/`locked`, no new logic.

### Authoring editor

`_edit_choicegridquestion.html` partial (dynamically included by `_host_form.html`), plus
a Questions-group add-menu card.

- **Columns section:** add / remove / reorder column labels (inline formset,
  clone-row pattern used by choice/match editors). Column text uses the shared
  RTE/∑ math-input contract (`[data-math-field]`/`[data-math-trigger]`).
- **Rows section:** each row = a statement field + a "correct column" selector
  whose options are the current columns. Statement uses the RTE/∑ contract.
- **True/False preset:** a one-click button that seeds two columns
  ("True"/"False", localised) into the empty columns formset — pure client-side
  convenience over the same underlying model (no special-casing server-side).

**Correct-column linkage (load-bearing — one uniform mechanism for BOTH paths).**
The correct-column selector addresses columns by a **stable per-column client
temp-id**, NOT by pk and NOT by a raw positional ordinal. `save_element` builds a
`temp_id → saved-column` map **after** the columns formset is pruned and saved,
then resolves each row's `correct_column` against it (a column-then-row two-pass
rebuild). This single mechanism is required because all three cases break a
pk-based or ordinal-based approach:
- **Create** (incl. the True/False preset): columns are unsaved, no pk exists yet.
- **Edit adding a column in the same submission:** an author can add a new column
  and, in the same save, point a new row at it — that column has no pk at
  form-render time, so a pk-scoped `ModelChoiceField` cannot represent it.
- **Blank-pruning shifts raw ordinals:** because blank columns are pruned before
  save (see Authoring invariants), a raw positional index would resolve to the
  wrong or a nonexistent column; a stable temp-id survives pruning and reorder.

The temp-id is a client-generated identifier emitted on each column row and echoed
as the row's correct-column value; resolution happens after pruning so temp-ids
refer only to surviving columns of **this** question. A row whose temp-id resolves
to no surviving column is a **validation error** (the author must re-point or
remove it), never a silent save — scoping correctness to this question's columns
without relying on a cross-question `ModelChoiceField` queryset.

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
key `choice_grid` (snake_case; differs from the form/type key `choicegridquestion`).

**`_val_choice_grid` must bounds-check the ordinal up front** (the import loop
`_create_elements` wraps builders in `try/except ValidationError` only, so an
uncaught `IndexError` from `columns[ordinal]` on a corrupt/hand-edited archive
would be a 500, not a graceful `TransferError`). The validator enforces: ≥1 column,
≥1 row, every column label present, and every row's `correct_column` ordinal is an
int in `range(len(columns))` — mirroring how `_val_match_pair` rejects
empty/short payloads before the builder runs.
Serialise `stem`/`explanation`/marking fields + the ordered columns (label) +
ordered rows (statement + correct-column reference by **export-local ordinal
index** over the already-saved, already-pruned columns, not pk — at export time
columns are persisted and stable, so a plain ordinal is unambiguous here).

**Importer builder deviates from the flat-child-list contract (call it out
explicitly).** The generic import loop (`courses/transfer/importer.py`) calls
`BUILDERS[type](data, assets) -> (concrete, child_rows)` and then generically
`full_clean`+`save`s every item in the single flat `child_rows` list — it has no
FK-resolution step, and existing builders (`_build_match_pair` etc.) return
*unsaved* children for the loop to save. That contract cannot express the matrix's
required `GridRow.correct_column` (a PROTECT FK that must point to an
already-saved `GridColumn`). So `_build_choice_grid` **saves + `full_clean`s the
columns internally**, builds the `ordinal → saved-column-pk` map, constructs the
`GridRow`s with `correct_column` already resolved, and returns **`(question, rows)`**
so the generic loop saves only the rows. This is a deliberate, documented
deviation from the "builder returns unsaved children; loop saves them" pattern —
the plan must call it out so an implementer copying `_build_match_pair` doesn't
leave columns unsaved (rows would then fail `full_clean` on the unsaved FK). No
existing builder does intra-element child-to-child resolution; the closest analog
is the Tabs *element-level* ordinal/id resolution, applied here within one element.

**Do NOT bump `FORMAT_VERSION`.** A new element type is purely additive to the
archive: the element envelope (`{id, unit, title, type, data, parent, tab}`) and
every existing type's `data` shape are unchanged; only a new `type` string and its
self-contained `data` appear. The recent additive types (callout, switch-grid,
fill-in table, spoiler) were all added at the current version without a bump —
the documented convention ("don't bump FORMAT_VERSION for a new element type").
Bumping would make the importer's `version > FORMAT_VERSION` gate reject **every**
export from the new build (matrix-free courses included) on any instance still at
the old version — a gratuitous regression. Old importers already reject matrix
archives correctly via the `type not in VALIDATORS` check, independent of the
version number. (Reserve version bumps for changes to the shared envelope or an
existing type's shape, as tabs' nesting bump did.)

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
2. **Authoring editor** (`_edit_choicegridquestion.html`) — the columns section, the rows
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
- **Empty answer — path-dependent:** in the **lesson/immediate** (`check_answer`)
  path a submission with no radios selected reaches `mark`, which marks every row
  wrong (`fraction == 0.0`), never raising. In the **quiz** path the same all-blank
  submission (an all-`""` list) hits the shared `answer_is_empty` guard first, which
  reads it as empty (per the Marking persistence note — this is why the sentinel is
  `""`, not `None`), so `quiz_answer` records **no attempt** and re-renders a
  validation prompt — consistent with the other question types, not a 0.0 mark. No
  `choice_grid` branch is needed for this to hold.

## Touchpoints (new-element-type checklist)

**One form/type-key literal: `choicegridquestion`** (the `...question` suffix
every question type uses — `choicequestion`, `matchpairquestion`,
`dragtoimagequestion`). This single literal must be identical across
`FORM_FOR_TYPE`, the `save_element` branch, the `_add_menu.html` card, the
`element_add`/`element_save` allow-tuples, and the `_edit_choicegridquestion.html`
partial name (`_host_form.html` includes `_edit_<form_key>.html`). Distinct
namespaces: the model is `ChoiceGridQuestionElement`, the student template
`choicegridquestionelement.html` (model-name), the transfer key `choice_grid`
(snake_case), and the reveal include `_reveal_choicegrid.html` (short, per the
`_reveal_matchpair.html` convention).

Per the canonical checklist: `ELEMENT_MODELS` + concrete models + migration;
`FORM_FOR_TYPE`; `save_element` branch; `_add_menu.html` card (Questions group);
`element_add`/`element_save` allow-tuples; `_EDITOR_TYPE_LABELS`;
`_ELEMENT_LABELS` + `element_summary`; student
`choicegridquestionelement.html` (model-name path, base `render`); **`render_choice_grid`
simple tag + its Python builder in `courses_extras.py`** (builds the no-JS grid
markup — rows × columns × positional `submitted_values` — since a template cannot
index the list, mirroring `render_match_pairs`); edit-form
`_edit_choicegridquestion.html`; reveal `_reveal_choicegrid.html`; **`_question_has_math`
/ `_element_has_math` matrix branch** (returns true when any `columns.label` or
`rows.statement` carries KaTeX delimiters — else a math-in-statement/label matrix
renders raw `$...$` in the lesson and results paths, since KaTeX loads only when
`has_math` is set; quiz consumption masks this because `build_quiz_context` forces
`has_math`, but lesson/results do not); transfer trio (NO
`FORMAT_VERSION` bump — additive type); **render-context prefetch: register a
`choicegrid_qs` list and `prefetch_related_objects(choicegrid_qs, "columns",
"rows")` in both `build_quiz_context` and `build_lesson_context`** (matrix has two
child relations, so without this the grid render is N+1 per question, as MatchPairs
avoids via its `pairs` prefetch); i18n EN/PL; JS enhancer wired into `editor.js`
AND `editor.html` (+ script-presence test); a `manage_element_add` GET/POST-200
authoring test for the new type. NOT added to `NESTABLE_TYPE_KEYS` (top-level
only).

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
  intact; assert `FORMAT_VERSION` is **unchanged** (stays at its current value —
  NOT bumped); update the `ELEMENT_MODELS` count assertion in
  `tests/test_transfer_schema.py` from 25 to 26.
- `editor.html` loads `choicegrid.js`.
- Playwright e2e: answer a grid in a lesson (immediate feedback) and in a quiz
  (withheld → locked → results reveal), driving the real radio clicks.
- Frontend-design: screenshot both surfaces (student render + editor) in light
  and dark; a CSS-presence/render guard for the matrix table classes.
