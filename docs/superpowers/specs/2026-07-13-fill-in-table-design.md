# Fill-in table element — design

**Date:** 2026-07-13
**Status:** Approved (brainstorming)
**Type:** New unit content element ("Interactive" palette group)

## Summary

A new **`FillTableElement`** — a table where the author marks some cells as
**answer cells**. Students type into those cells, press a single **Check**
button, and receive per-cell ✓/✗ feedback plus a success / "try again"
summary. It is an **ungraded self-check**: it records no marks, reveals no
answers, and never appears in quizzes or the teacher analytics matrix. This is
the "Fillable table" item from the interactive-elements roadmap.

It reuses two existing substrates:

- **Structure & authoring** — the existing display `TableElement` editor (WYSIWYG
  grid, header row/column toggles, border presets, per-cell alignment, inline
  math, cell-HTML sanitisation at `save()`).
- **Self-check server flow** — the `SwitchGridElement` pattern (a soft-pk check
  endpoint returning per-cell correctness + a success/retry summary, never
  persisting anything, recording no marks, lock-on-success on the client).

## Non-goals (YAGNI)

- **No marks / no grading.** It is not a `QuestionElement`; it does not appear in
  quizzes, the results page, or the analytics matrix.
- **No per-cell case-sensitivity or per-cell accepted-answer lists beyond a simple
  alternatives separator.** Matching is deliberately lightweight (see below).
- **No answer reveal.** Incorrect cells show ✗; the correct value is not shown.
- **Not nestable inside Tabs** for the first version (not added to
  `NESTABLE_TYPE_KEYS`). Can be added later if demand appears.

## Data model

New concrete model `FillTableElement(ElementBase)` with a single `data`
`JSONField` (mirrors `TableElement`), plus `elements = GenericRelation(Element)`.
Migration adds the model. No `FORMAT_VERSION` bump is required unless the
transfer shape of *existing* elements changes (it does not — this is a new type).

`data` extends the table shape with a per-cell **kind**:

```jsonc
{
  "header_row": bool,
  "header_col": bool,
  "border": "grid" | "rows" | "header" | "none",
  "case_sensitive": bool,          // table-wide, default false
  "prompt": "…optional instruction line…",   // "" to omit
  "cells": [
    [
      { "kind": "static", "html": "…sanitised…", "halign": "left", "valign": "top" },
      { "kind": "answer", "answer": "0,5 | 0.5", "halign": "left", "valign": "top" }
    ]
  ]
}
```

- **Static cells** keep full WYSIWYG content (`<strong>/<b>/<em>/<i>/<u>/<br>` +
  inline `\(…\)` / `\[…\]` math), sanitised at `save()` via the existing
  `sanitize_cell` with math-protection — identical to `TableElement`.
- **Answer cells** store an accepted-answer string; `html` is not used for them.
- A `normalize_data` staticmethod (mirroring `TableElement.normalize_data`)
  rectangularises ragged rows, coerces bad cells, defaults missing keys, and
  guarantees each cell has a valid `kind`. Unknown `kind` → `"static"`.

`save()` sanitises static-cell HTML and strips/normalises answer strings; it does
**not** sanitise answer text as HTML (answers are compared as plain text).

## Answer matching

Reuse `fillblank.blank_matches` (whitespace-normalised text comparison).

- Each answer cell's stored string is split on `|` into **alternatives**; the
  student's input matches if it matches **any** alternative (e.g. `0,5 | 0.5`).
- A single table-wide **`case_sensitive`** toggle (default off) is threaded into
  `blank_matches(case_sensitive=…)` for every cell.
- Empty student input for an answer cell → incorrect.
- Alternatives and the surrounding whitespace are trimmed; empty alternatives are
  dropped. An answer cell whose stored string is entirely blank is treated as
  accepting only empty input (author error surfaced in the editor, see below).

## Student render & check flow

Template `templates/courses/elements/filltableelement.html`:

- Renders like the display table (`.el--filltable`, border/header classes, per-cell
  `ta-*`/`va-*`). Static cells emit sanitised HTML (`|safe`); answer cells emit
  `<input type="text" data-r="{r}" data-c="{c}">`.
- Optional `prompt` renders above the table when non-empty.
- One **Check** button below the table.
- Client JS (`filltable.js`): on Check, POST the answer-cell values (keyed
  `r{row}c{col}`) to `filltable_check`; paint each answer cell with a
  correct/incorrect class from the response; show a mutually-exclusive
  success / try-again summary (`data-success-msg` / `data-retry-msg`).
  **Lock-on-success** (disable inputs + hide Check) mirroring Switch grid;
  guard the Check button with `.filltable__confirm[hidden]{display:none!important}`
  (the recurring `.btn[hidden]` gotcha).
- Math in static cells typesets client-side (add `.el--filltable` to math.js
  `renderInlineText`). Answer-cell inputs are plain text (no math typesetting).
- **No-JS fallback:** inputs render and are usable, Check is inert — consistent
  with the other server-checked self-checks.

Endpoint `filltable_check` (mirrors `switchgrid_check`):

- Soft pk lookup → **200 on miss** (not 404), `can_access_course` gate.
- Reads posted `r{i}c{j}` values, marks each answer cell via `blank_matches`,
  returns `{ cells: [{r,c,correct}], all_correct: bool }`.
- Never persists; records no marks.

`has_math` and the student `<script>` are gated by a `has_fill_table` flag set in
`build_lesson_context` (the top-level inline `has_math` OR-chain **and** the
`has_<type>` script gate in `lesson_unit.html` — both, per the switch-grid
lesson). A `has_fill_table` guard is also added at the quiz-unit site so the
widget's JS loads if a fill-table sits on a quiz page (even though it records no
marks).

## Authoring

Editor partial `templates/courses/manage/editor/_edit_filltable.html` +
`courses/static/courses/js/filltable_editor.js`, extending the table-editor
pattern:

- The controls strip gains the table-wide **case-sensitive** checkbox and an
  optional **prompt** text field, alongside the existing header/border controls.
- The toolbar gains an **"Answer cell"** toggle button. With a cell focused,
  clicking it converts the focused cell between:
  - **static** — a contenteditable rich cell (B/I/U/math, as today), and
  - **answer** — a shaded plain-text `<input>` pre-filled with the accepted-answer
    string (alternatives shown with the `|` separator; a placeholder documents it).
- The hidden `name="data"` field remains the sole authoritative input; the editor
  JS mirrors grid + controls state into it (same contract as `table_editor.js`).
- Grid + controls are server-rendered from normalised stored data so an existing
  fill-table shows its saved state (static vs answer cells preserved).
- **Validation surfaced in the editor** (capture-phase submit guard, mirroring the
  switch-grid editor): at least one answer cell must exist, and no answer cell may
  be entirely blank — a clear inline message, so the author cannot save a
  fill-table with nothing to check.
- JS-injected labels ride on `data-msg-*` / `data-*` attributes rendered via
  `{% trans %}` (makemessages does not scan `.js`).
- **Frontend-design pass** on both the editor interaction and the student render,
  light + dark, screenshot-verified (per the every-view-ships-styled rule; the
  switch-grid-editor lesson: run frontend-design on authoring UIs too).

## Transfer (export / import)

Transfer trio for key `fill_table`:

- **Serializer** (`export.py`) — emit `data` verbatim.
- **Validator** (`payloads.py`) — 3-arg `(data, elid, media_kinds)`, raising via
  `_err(_(…), el=elid)`; validate shape (border enum, cell kinds, rectangular
  cells, answer strings are strings); `return set()` (no media).
- **Builder** (`importer.py`) — construct the model and `save()` (which
  re-sanitises static cells), bypassing the form.

No new media kinds. No `FORMAT_VERSION` bump.

## Touch-points checklist (kept in lockstep)

Per the interactive-elements roadmap, adding a new element type touches:

- `ELEMENT_MODELS` + concrete model + migration
- `FORM_FOR_TYPE` (`element_forms.py`) + `FillTableElementForm`
- `save_element` (`builder.py`)
- `_add_menu.html` palette card (Interactive group)
- `element_add` / `element_save` tuples (`views_manage.py`)
- `_EDITOR_TYPE_LABELS` (`views_manage.py`)
- `_ELEMENT_LABELS` + `element_summary` (`courses_manage_extras.py`)
- `templates/courses/elements/filltableelement.html` (student render)
- `templates/courses/manage/editor/_edit_filltable.html` (edit-form partial —
  required, or the palette card 500s `TemplateDoesNotExist`)
- transfer trio `SERIALIZERS` / `VALIDATORS` / `BUILDERS`
- i18n EN/PL for all new strings
- JS enhancer wired into **both** `editor.js` (re-run `window.libliInitFillTable`
  after each fragment swap) **and** `editor.html` (add the
  `<script src=".../filltable.js" defer>` — the step missed twice before; guard
  with a test asserting the script tag is present)
- `build_lesson_context` `has_fill_table` flag (math OR-chain + `has_<type>`
  script gate) + quiz-unit guard
- a per-element authoring test that GET/POSTs `manage_element_add` for `filltable`
  and asserts 200 (covers the `element_add` → `_host_form` → `_edit_filltable`
  render path)

## Testing

- Unit: `normalize_data` (ragged/degenerate/unknown-kind), `save()` sanitisation,
  form parse (static/answer cell round-trip, `|` alternatives, empty-answer
  rejection, no-answer-cell rejection), `blank_matches` wiring incl.
  `case_sensitive`.
- View: `filltable_check` (all-correct, partial, soft-pk miss → 200, access gate),
  `manage_element_add` for `filltable` → 200, editor `<script>` present.
- Transfer: round-trip export → import; validator rejects malformed shapes;
  `ELEMENT_MODELS` count assertion updated.
- e2e (Chromium): author a fill-table, drive the real student gesture (type into
  cells, click Check), assert per-cell ✓/✗ and success lock — driving the actual
  click path, not `page.evaluate`.
