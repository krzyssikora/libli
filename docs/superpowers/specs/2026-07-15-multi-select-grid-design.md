# Multi-select grid element

## Purpose

Add a new graded content element, **"Multi-select grid"**, that presents a table of
row-statements against a shared set of columns, where each row's answer is a **set** of
checked columns (checkboxes). It is the direct sibling of the already-shipped Matrix element
(`ChoiceGridQuestionElement`), which handles the *single*-choice-per-row case (radio buttons).
This ports the legacy Demo-course widgets `.multi_many_ans` / `.multi_ans` ("multiple possible
answers in multiple lines") from `_template.html`.

Like every `QuestionElement`, it works **formatively in lessons** (inline check + feedback,
no marks recorded against a grade) and **scored in quizzes** (partial credit contributes to
the quiz score). It is the next slice of the [[interactive-elements-roadmap]] choice-quiz
family. The complementary *per-option / per-line feedback* capability (`.mult_feedback_incorrect`)
is explicitly **out of scope** for this slice.

### Success criteria

- An author can add a "Multi-select grid" from the add-menu, define N columns and M rows, and
  mark, per row, a **set** of correct columns via checkboxes in the editor.
- A learner sees a checkbox grid; on submit the element marks **all-or-nothing per row**, with
  **grid-level partial credit** = (fully-correct rows / total rows), and reveals the correct
  column set per row.
- Works with JavaScript disabled (server renders a real `<form>` grid; check via POST).
- Round-trips through course export/import (transfer key `multi_grid`) without a `FORMAT_VERSION`
  bump.
- All existing tests continue to pass; the shared `answer_is_empty` change is covered by a
  regression test for the flat-list (Matrix / fill-blank) case.

## Architecture / components

### Data model (`courses/models.py`)

Three new models, mirroring the Matrix trio (`ChoiceGridQuestionElement` / `GridColumn` /
`GridRow`) with **one structural change**: a row owns a *set* of correct columns, not one.

- **`MultiGridQuestionElement(QuestionElement)`** — new concrete `QuestionElement` subclass.
  - `elements = GenericRelation(Element)`; `REVEAL_TEMPLATE = "courses/elements/_reveal_multigrid.html"`.
  - Overrides `build_answer(post)` and `mark(answer)` (detailed under **Data flow**). It does
    **not** override `feedback_context()` — the base `QuestionElement.feedback_context` (supplying
    `el` / `mark_result` / `reveal_template`) suffices, exactly as for Matrix.
  - Adding this concrete model makes **`ELEMENT_MODELS` count 28** and requires a new migration.
- **`MultiGridColumn`** — `question` FK (`CASCADE`, `related_name="columns"`), `label`
  `CharField(max_length=500)` (plain text + KaTeX, never sanitised), `order`
  `OrderField(for_fields=["question"])`. Identical to `GridColumn`.
- **`MultiGridRow`** — `question` FK (`CASCADE`, `related_name="rows"`), `statement`
  `CharField(max_length=500)`, `order` `OrderField(for_fields=["question"])`, **plus
  `correct_columns = ManyToManyField(MultiGridColumn, related_name="+")`** — the set of correct
  columns for that row.
  - **Why M2M, not a per-row FK (the Matrix divergence #1):** the answer is set-valued, so a row
    references 0..N columns. M2M is the idiomatic store. It also removes Matrix's `PROTECT` +
    "re-point rows before deleting columns" dance: deleting a column simply drops it from every
    row's M2M set (Django clears the through-rows automatically), which is the desired behaviour.

### Marking (all-or-nothing per row, averaged)

Per the approved design (mirrors `ChoiceGridQuestionElement.mark` generalised from a single
value to a set):

- For each row `i`: `is_correct_i = (checked_set_i == correct_set_i)`, where **both sides are
  compared as sets** — explicitly `set(answer[i]) == {c.pk for c in row.correct_columns.all()}`.
  This cast is load-bearing: `build_answer` yields a *sorted list* per row and the stored answer
  stays a list through the JSON round-trip, while `correct_columns` is a set; a naive `list == set`
  is always `False` and would silently mark every row wrong.
- Grid `fraction = (# rows where is_correct) / (# rows)`; `0.0` when there are no rows.
- Grid `correct = (all rows correct AND rows > 0)`.
- `reveal` carries, per row, the `statement`, the **correct column label set**, the **chosen
  column label set**, and `is_correct` — for the no-JS reveal partial and the quiz results view.

### Answer payload and the `answer_is_empty` fix (divergence #2)

- `build_answer(post)` returns a **positional list aligned to rows**; each entry is a **sorted
  list of chosen column pks** (validated against this question's own columns; foreign/forged ids
  dropped), or `[]` for an untouched row. This is JSON-safe and survives the
  `QuestionResponse.latest_answer` round-trip and quiz re-mark.
- **Problem:** the shared `courses/quiz.py::answer_is_empty` treats a list as empty via
  `not any(str(v).strip() for v in answer)`. For a list-of-lists like `[[], [], []]`, `str([])`
  is `"[]"` (truthy), so an untouched grid would be judged **non-empty** and wrongly record a
  0.0 attempt.
- **Fix:** extend `answer_is_empty` to treat nested lists/tuples as empty when they contain
  nothing markable (recurse/flatten), so `[[], [], []]` → empty while the existing flat-list
  behaviour is preserved (Matrix `["", 3]` stays non-empty; `["", ""]` stays empty). The recursion
  must be leaf-aware: keep the existing `str`-first guard (a string is tested via `.strip()`, never
  iterated into characters), descend **only** into `list`/`tuple`, and test any other scalar
  (notably the `int` pk leaves) via `str(v).strip()` — matching the current flat behaviour and
  avoiding a `TypeError` on int leaves. Guarded by a regression test covering both the flat and
  nested cases.
- `mark(answer)` **pads/truncates** the stored answer to `len(rows)` with the Matrix idiom
  (`(list(answer) + [[]] * n)[:n]`) so a stored answer whose length drifted from the current row
  count cannot `IndexError` a 500 on the results re-mark. The empty-row sentinel here is `[]`.

### Editor / authoring (`courses/element_forms.py`, `courses/builder.py`, templates)

Mirrors the Matrix **two-formset** plumbing (columns formset + rows formset), which already
threads `columns_formset` / `rows_formset` context and an `ElementFormInvalid.formset2`.

- Two `extra=0` formsets with `has_changed` overrides keyed on the visible field (`label` for
  columns, `statement` for rows) so a blank starter row/column added by JS does not defeat
  Django's all-blank-extra skip.
- **Each kept row requires at least one correct column.** `BaseMultiGridRowFormSet.clean`
  mirrors Matrix's "Each row needs a correct column" rule generalised to a set: a kept row whose
  `correct_temp_ids` resolves to an **empty** set is a validation error. A row where the intended
  answer is literally "check nothing" is therefore **not authorable** — an explicit product
  decision (keeps authoring and marking unambiguous). Consequently `mark`'s empty-`correct_set`
  branch is defensive only (it still returns a well-defined result for a corrupt/legacy row), not
  a reachable authoring state.
- **Row ↔ correct-column-set linkage via stable client temp-ids** (the exact mechanism Matrix
  uses, generalised to a set): each column row carries a client `temp_id`; each grid row binds a
  **non-model `correct_temp_ids` field** (comma-joined temp-ids of its checked columns).
  `save_element` (`courses/builder.py`) saves columns first, builds a `temp_id -> saved column`
  map, then sets each row's `correct_columns` M2M from its `correct_temp_ids`.
- **Partial temp-id resolution (the "column deleted in the same submission" case):** when
  resolving a row's `correct_temp_ids`, **silently drop** any temp-id with no surviving column and
  keep the rest. If, after dropping, a kept row has **zero** surviving correct columns, raise
  `ElementFormInvalid` — mirrors Matrix's `builder.py` hard-fail when a row's correct column didn't
  survive, and is consistent with the "≥1 correct column per row" rule above. So "delete a column
  and re-point its rows in one submission" works as long as each affected row keeps ≥1 correct
  column; deleting the *last* correct column of a row is a validation error, not silent data loss.
- **On edit**, seed each column form's `temp_id = str(col.pk)` and each row form's
  `correct_temp_ids` from the saved M2M (`",".join(str(pk) for pk in row.correct_columns...)`),
  so the client-only linkage reconstructs. (Matrix hit exactly this bug — edit dropped saved
  correct columns — and fixed it by seeding in `__init__`; we replicate the seeding.)
- The authoring grid uses **checkboxes** (multi-select) where Matrix uses radios.
- Editor JS enhancer (`multigrid_editor.js`, or an extension of the matrix editor JS) adds/removes
  columns and rows and keeps the checkbox grid in sync; it is wired into **both** `editor.js`
  (re-run after each preview fragment swap) **and** `editor.html` (`<script defer>` include) —
  the twice-missed step, guarded by a test asserting the script is present on `manage_editor`.

### Rendering (student + reveal templates)

- Base `render()` (inherited) → `courses/elements/multigridquestionelement.html`.
- The no-JS grid is built by a **`render_multigrid` simple tag** (`format_html` /
  `format_html_join`, no `mark_safe`/manual escape) because a Django template cannot index a
  positional list by loop variable (same constraint Matrix's `render_choice_grid` solved).
- **POST field-name convention (the contract between the render tag and `build_answer`):** each
  grid cell is a `<input type="checkbox" name="row_{row.pk}" value="{col.pk}">` (Matrix uses the
  same `row_{pk}` name for its single radio, so the checkbox multi-select is the natural
  generalisation). `build_answer` reads each row via **`post.getlist(f"row_{row.pk}")`** (not
  `.get`), int-coerces, and validates against the question's own column pks.
- Reveal partial `_reveal_multigrid.html` shows, per row, the correct column set and the chosen
  set; it does **not** render `el.explanation` (the containing feedback/results partials already
  do — double-render guard, per Matrix).

### Transfer (export / import / validate)

- Transfer **key `multi_grid`** (snake_case, ≠ form key `multigridquestion`).
- `SERIALIZERS` (export): emit `{"stem", "columns": [labels...], "rows": [{"statement",
  "correct": [column-ordinals...]}], ...}` — correct columns as **ordinals into the exported
  columns list** (pk-independent, matches Matrix). The per-row `correct` list is emitted
  **sorted** (`sorted(index[c.pk] for c in row.correct_columns.all())`) — M2M `.all()` has no
  guaranteed ordering, and sorting keeps export output deterministic and the round-trip test
  stable.
- `VALIDATORS` (`_val_multi_grid`): bounds-check every correct-column ordinal against the column
  count (raise a clean `TransferError`, never let a corrupt archive `IndexError` → 500).
- `BUILDERS` (`_build_multi_grid`): **the M2M forces a deeper deviation than Matrix's builder.**
  Matrix's `_build_choice_grid` returns *unsaved* `GridRow` objects carrying a settable-pre-save
  FK (`correct_column`), and the generic import loop in `_create_elements` `full_clean`s + `save`s
  them. An M2M (`correct_columns`) **cannot be assigned before the row has a pk**, and the generic
  loop has **no post-save per-type hook**. Therefore `_build_multi_grid` must itself save the
  columns, `full_clean`/`save` each row, then call `row.correct_columns.set(resolved_columns)`
  **internally**, and return **`(question, [])`** (an empty child list) so the generic loop does
  not try to re-`full_clean`/re-`save` already-saved rows. Returning `(question, rows)` with a
  pending M2M — the naive "exactly like Matrix" path — would **silently drop every imported row's
  correct-set** (the M2M is never populated). A one-line comment in the builder must call this out.
- **No `FORMAT_VERSION` bump** — additive element type; bumping would make old importers reject
  every new export.

### Lesson wiring / lockstep touch-points

All the standard "add a new element type" touch-points from [[interactive-elements-roadmap]] are
updated in lockstep:

`ELEMENT_MODELS` + concrete model + migration; `FORM_FOR_TYPE`; `save_element`; `_add_menu.html`
palette card; `element_add` / `element_save` allow-tuples; `_EDITOR_TYPE_LABELS`;
`_ELEMENT_LABELS` + `element_summary`; `templates/courses/elements/multigridquestionelement.html`
(student) + `templates/courses/manage/editor/_edit_multigridquestion.html` (edit-form partial —
a missing one 500s `TemplateDoesNotExist`); transfer `SERIALIZERS` / `VALIDATORS` / `BUILDERS`;
EN/PL i18n.

- **`question_models` in `build_lesson_context`** must include the new model so `has_questions`
  loads `question.js` (the only lesson-side typesetter of question subtrees + inline feedback) —
  a matrix-only lesson needed this; a multigrid-only lesson does too.
- **Per-type prefetch registration** (the lockstep site Matrix uses in **both**
  `build_lesson_context` and the quiz/results path in `views.py`): build a `multigrid_qs` list
  and `prefetch_related_objects(multigrid_qs, "columns", "rows", "rows__correct_columns")`. The
  `"rows__correct_columns"` leg is **required** — without it, marking/reveal over M rows fires an
  N+1 (one query per row's M2M) on the quiz re-mark. Mirror Matrix's existing
  `prefetch_related_objects(choicegrid_qs, "columns", "rows")` at each of the two sites.
- **`_question_has_math`** (not `_element_has_math`) gets a `MultiGridQuestionElement` branch so
  KaTeX in labels/statements typesets.
- **Top-level only** — like every question type, **not** added to `NESTABLE_TYPE_KEYS`.
- Form/type key literal `multigridquestion` (the `...question` convention) used consistently
  across `FORM_FOR_TYPE` / `save_element` / add-menu / allow-tuples / `_edit_multigridquestion.html`.

## Data flow

1. **Author** opens the editor, adds a Multi-select grid, defines columns + rows, checks the
   correct columns per row. On save, `save_element` persists columns, maps temp-ids → saved
   columns, saves rows, and sets each row's `correct_columns` M2M.
2. **Learner (lesson)** submits the inline grid form → `build_answer` builds the positional
   list-of-lists → `answer_is_empty` short-circuits an untouched grid → `mark` computes per-row
   all-or-nothing + grid fraction → feedback partial renders the reveal (correct/chosen sets).
3. **Learner (quiz)** submits → the answer is stored JSON (`answer_to_json` → list-of-lists is
   already JSON-safe) → on results re-mark, `rehydrate` + `mark` (with pad/truncate) recompute
   the fraction into the quiz score.
4. **Export** serialises to `multi_grid` with ordinal correct-sets; **import** validates ordinals
   and rebuilds columns/rows/M2M.

## Error handling

- **Untouched grid** → `answer_is_empty` true → no attempt recorded (the core reason for the
  shared-function fix).
- **Forged / foreign column ids** in POST → dropped in `build_answer` (validated against the
  question's own columns), never error-leaking.
- **Answer-length drift** (stored answer shorter/longer than current rows) → `mark` pads/truncates
  to `len(rows)`, no `IndexError`.
- **Column deleted in the same submission that references it** → the temp-id resolves to no
  surviving column and is dropped from the row's set; M2M through-rows are cleared automatically,
  no `PROTECT` violation (unlike Matrix's FK). If dropping leaves the row with **zero** correct
  columns, `save_element` raises `ElementFormInvalid` (the ≥1-correct-column rule), so the failure
  is a surfaced validation error, never silent data loss.
- **Corrupt import** (correct ordinal out of range) → `_val_multi_grid` raises `TransferError`,
  not a 500.
- **JS disabled** → server renders a real form grid; POST check works; editor edit partial present
  so the add path never 500s.

## Testing

- **Model / marking unit tests:** per-row all-or-nothing; grid fraction = fully-correct/total;
  `correct` only when all rows right and rows > 0; empty grid → `fraction 0.0`; pad/truncate on
  answer drift; `build_answer` drops forged ids and returns sorted pk lists.
- **`answer_is_empty` regression test:** `[[], [], []]` → empty; `[[3], []]` → non-empty; and the
  preserved flat cases (`["", ""]` → empty, `["", 3]` → non-empty).
- **Authoring path test:** GET **and** POST `manage_element_add` for `multigridquestion` returns
  200 (covers `element_add` → `_host_form` → `_edit_multigridquestion` — the render path Matrix
  left untested until PR #100 caught the missing partial). Save + reload round-trips the correct
  column set (guards the edit-seed-`correct_temp_ids` bug Matrix hit). A save where a kept row has
  no checked column is rejected (the ≥1-correct-column rule); a save that deletes a column
  re-points its rows and errors only when a row is left with zero correct columns.
- **Editor-JS-loaded test:** GET `manage_editor` asserts the enhancer `<script>` is present.
- **Transfer round-trip test:** export → import reproduces columns, rows, and per-row correct sets;
  a corrupt ordinal raises `TransferError`.
- **Lesson-render / has_questions test:** a lesson containing only a multigrid loads `question.js`
  and renders the grid + KaTeX (guards the `question_models` / `_question_has_math` wiring).
- **e2e (real browser):** author a small grid, take it as a learner, check a partially-correct
  answer scores per-row all-or-nothing and reveals the correct sets; KaTeX in a label typesets.
- **DoD:** full non-e2e suite green (run with `-n auto` to stay under the subagent watchdog),
  targeted multigrid e2e green, `ruff` / `ruff format --check` / `makemigrations --check` /
  `manage check` clean, PO catalogs fuzzy-free (strip `makemessages` fuzzy matches on the new
  msgids — the recurring stepper/matrix gotcha).

## Out of scope (YAGNI)

- Per-row / per-option feedback (`.multi_feedback_ans` / `.mult_feedback_incorrect`) — the
  deferred complementary capability; the reveal already shows correct answers.
- Within-row partial credit (overlap/cell-level) — the approved decision is all-or-nothing per row.
- Nesting inside tabs — no question type is nestable.
- `FORMAT_VERSION` bump — additive type only.
