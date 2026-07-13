# Fill-in table element — design

**Date:** 2026-07-13
**Type:** New unit content element ("Interactive" palette group)

## Purpose

Give authors a **table whose cells can be fillable inputs**, checked as an
**ungraded self-check**. The author marks some cells as *answer cells*; students
type into them, press one **Check** button, and get per-cell ✓/✗ feedback plus a
success / "try again" summary. It records **no marks**, reveals no answers, and
never appears in quizzes or the teacher analytics matrix. This is the "Fillable
table" item from the interactive-elements roadmap.

It reuses two existing substrates:

- **Structure & authoring** — the display `TableElement` editor (WYSIWYG grid,
  header row/column toggles, border presets, per-cell alignment, inline math,
  cell-HTML sanitisation at `save()`).
- **Self-check server flow** — the `SwitchGridElement` pattern: a soft-pk check
  endpoint returning per-cell correctness + a success/retry summary, persisting
  nothing, recording no marks, lock-on-success on the client.

### Non-goals (YAGNI)

- **No marks / no grading.** Not a `QuestionElement`; absent from quizzes, the
  results page, and the analytics matrix.
- **No per-cell case-sensitivity, no rich per-cell accepted-answer lists** beyond a
  simple `|` alternatives separator; matching is deliberately lightweight.
- **No answer reveal.** Incorrect cells show ✗; the correct value is not shown.
- **Not nestable inside Tabs** for v1 (not added to `NESTABLE_TYPE_KEYS`).

## Architecture / components

New concrete model `FillTableElement(ElementBase)` reusing the table substrate for
structure and the switch-grid substrate for the self-check. Components:

- **Model** `FillTableElement` — single `data` `JSONField` (mirrors `TableElement`)
  + `elements = GenericRelation(Element)`; `type_key`/form key `filltable`,
  transfer key `fill_table`, model name `filltableelement`, label **"Fill-in
  table"**. Added to `ELEMENT_MODELS`; new migration.
- **Form** `FillTableElementForm` (`element_forms.py`, wired into `FORM_FOR_TYPE`)
  — one hidden authoritative `data` field, mirrored from the editor JS (same
  contract as `TableElementForm`); validates that ≥1 answer cell exists and no
  answer cell is entirely blank.
- **Student template** `templates/courses/elements/filltableelement.html`.
- **Editor partial** `templates/courses/manage/editor/_edit_filltable.html`
  (required — a missing partial 500s `TemplateDoesNotExist` when the palette card
  is clicked).
- **Editor JS** `courses/static/courses/js/filltable_editor.js` (extends the
  table-editor pattern) and **student JS** `courses/static/courses/js/filltable.js`.
- **Check endpoint** `filltable_check` (mirrors `switchgrid_check`).
- **Transfer trio** for key `fill_table` (serializer / validator / builder).
- **Palette card** in `_add_menu.html` (Interactive group) + all the label/summary
  touch-points (see checklist).

### Data model

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
- **Answer cells** store an accepted-answer string; their `html` is unused.
- A `normalize_data` staticmethod (mirroring `TableElement.normalize_data`)
  rectangularises ragged rows, coerces bad cells, defaults missing keys, and gives
  every cell a valid `kind` (unknown → `"static"`), reusing the same `MAX_ROWS`/
  `MAX_COLS`/degenerate-collapse guards.

`save()` sanitises static-cell HTML and trims/normalises answer strings; answer
text is **not** HTML-sanitised (compared as plain text).

## Data flow

### Authoring (edit form)

1. `_edit_filltable.html` renders the controls strip (header/border toggles + a
   table-wide **case-sensitive** checkbox + an optional **prompt** field), a
   toolbar (B/I/U/math + an **"Answer cell"** toggle), and the grid, all
   server-rendered from `normalize_data(instance.data)` so an existing element
   shows its saved static/answer cells.
2. `filltable_editor.js` (document-level delegate, survives AJAX partial swaps)
   mirrors grid + controls into the hidden `name="data"` field. The **"Answer
   cell"** toggle converts the focused cell between *static* (contenteditable rich
   cell) and *answer* (shaded plain-text `<input>` pre-filled with the accepted
   string; placeholder documents the `|` separator).
3. A **capture-phase submit guard** (before editor.js's bubble-phase save) flushes
   any debounced reconcile and blocks submit with a clear inline message if there
   is no answer cell or any answer cell is blank.
4. `save_element` (`builder.py`) + `FillTableElementForm.clean` parse `data`,
   normalise it, and persist via `save()`.

### Student render + check

1. `filltableelement.html` renders like the display table (`.el--filltable`,
   border/header classes, per-cell `ta-*`/`va-*`). Static cells emit sanitised
   HTML (`|safe`); answer cells emit `<input type="text" data-r data-c>`. Optional
   `prompt` renders above; one **Check** button below.
2. `filltable.js` collects answer-cell values (keyed `r{row}c{col}`) and POSTs to
   `filltable_check`; paints each answer cell correct/incorrect from the response;
   shows a mutually-exclusive success / try-again summary
   (`data-success-msg` / `data-retry-msg`); **locks on success** (disable inputs +
   hide Check, guarded by `.filltable__confirm[hidden]{display:none!important}`).
3. `filltable_check` does a soft pk lookup (**200 on miss**), gates on
   `can_access_course`, marks each answer cell via `fillblank.blank_matches`, and
   returns `{ cells: [{r,c,correct}], all_correct }`. Never persists; no marks.

### Answer matching

Reuse `fillblank.blank_matches` (whitespace-normalised text match). Each answer
cell string is split on `|` into **alternatives**; the student matches if any
alternative matches. A single table-wide **`case_sensitive`** flag threads into
`blank_matches(case_sensitive=…)`. Alternatives are trimmed, empties dropped;
empty student input → incorrect.

### has_math / script gating

`build_lesson_context` sets a `has_fill_table` flag driving **both** the top-level
inline `has_math` OR-chain **and** the `has_<type>` `<script>` gate in
`lesson_unit.html` (a non-nestable element's math + JS are gated there, not via
`_element_has_math`). A `has_fill_table` guard is also added at the quiz-unit site
so the widget's JS loads if a fill-table sits on a quiz page.

### Transfer (export / import)

Transfer trio for key `fill_table`: serializer emits `data` verbatim; 3-arg
validator `(data, elid, media_kinds)` raises via `_err(_(…), el=elid)` and
`return set()` (no media); builder constructs the model and `save()`s
(re-sanitising static cells). No new media kinds, no `FORMAT_VERSION` bump.

## Error handling

- **Malformed / ragged stored data** → `normalize_data` rectangularises rather than
  raising; degenerate 0×N collapses to the default grid; non-dict cells and unknown
  `kind` coerce to a safe static cell. The student render and check tolerate any
  normalised shape.
- **Form validation** — missing answer cells or an all-blank answer cell are
  rejected in the form (`clean`) *and* pre-empted by the editor's capture-phase
  submit guard, so the author sees a clear inline message, never a server 500.
- **Defensive parse in the endpoint** — `filltable_check` never 500s on bad/missing
  POST keys: absent values are treated as empty (incorrect), a soft pk miss returns
  200 (mirrors `switchgrid_check`, unlike fillgate's 404), and access is gated by
  `can_access_course`.
- **XSS** — static-cell HTML is sanitised at `save()` and on import with the
  existing math-protected `sanitize_cell`; answer text is compared as plain text and
  is emitted only as an input `value`/placeholder in the editor, escaped.
- **No-JS fallback** — inputs render and are usable; Check is inert (checking is
  server-side only) — consistent with the other self-checks.

## Testing

- **Unit** — `normalize_data` (ragged / degenerate / unknown-kind); `save()`
  sanitisation (static HTML sanitised, answer text left plain but trimmed); form
  parse round-trip (static/answer cells, `|` alternatives, empty-answer rejection,
  no-answer-cell rejection); `blank_matches` wiring incl. `case_sensitive`.
- **View** — `filltable_check` (all-correct, partial, soft-pk miss → 200, access
  gate, missing POST keys); `manage_element_add` for `filltable` → 200 (covers the
  `element_add` → `_host_form` → `_edit_filltable` render path); a test asserting
  `editor.html` loads `filltable.js`.
- **Transfer** — round-trip export → import; validator rejects malformed shapes;
  update the `ELEMENT_MODELS` count assertion in the transfer-schema test.
- **e2e (Chromium)** — author a fill-table, then drive the **real student gesture**
  (type into cells, click Check), asserting per-cell ✓/✗ and the success lock —
  the actual click path, not `page.evaluate`.

## Touch-points checklist (kept in lockstep)

`ELEMENT_MODELS` + model + migration; `FORM_FOR_TYPE` + `FillTableElementForm`;
`save_element` (`builder.py`); `_add_menu.html` palette card (Interactive group);
`element_add`/`element_save` tuples (`views_manage.py`); `_EDITOR_TYPE_LABELS`;
`_ELEMENT_LABELS` + `element_summary` (`courses_manage_extras.py`); student template;
edit-form partial `_edit_filltable.html`; transfer trio
`SERIALIZERS`/`VALIDATORS`/`BUILDERS`; i18n EN/PL; JS enhancer wired into **both**
`editor.js` (re-run `window.libliInitFillTable` after each fragment swap) **and**
`editor.html` (add `<script src=".../filltable.js" defer>`, guarded by a test);
`build_lesson_context` `has_fill_table` flag (math OR-chain + `has_<type>` script
gate) + quiz-unit guard; per-element `manage_element_add` 200 authoring test.
