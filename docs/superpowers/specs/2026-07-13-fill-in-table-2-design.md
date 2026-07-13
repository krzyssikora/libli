# Fill-in table element — design

**Date:** 2026-07-13
**Type:** New unit content element ("Interactive" palette group)

## Purpose

Give authors a **table whose cells can be fillable inputs**, checked as an
**ungraded self-check**. The author marks some cells as *answer cells*; students
type into them, press one **Check** button, and get per-cell ✓/✗ feedback plus a
success / "try again" summary. It records **no marks**, reveals no answers, is
never a quiz question / graded item, and never appears in the teacher analytics
matrix. (It may still be *placed* as content on a quiz page — see "has_math /
script gating" — but it is not itself a graded quiz question.) This is the
"Fillable table" item from the interactive-elements roadmap.

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
- **Palette card** in `_add_menu.html`, placed in the **non-nestable
  `{% if not nested %}` section** (Interactive group) — because the element is not
  in `NESTABLE_TYPE_KEYS`, the card must not be offered inside a Tabs (nested)
  editing context. Plus all the label/summary touch-points (see checklist).

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
- **`prompt`** is a **plain-text** instruction line (no HTML, no math). It is
  stored as-is (trimmed), rendered **escaped** (Django autoescape — never `|safe`),
  and does **not** participate in the `has_math` gate. Empty string ⇒ omitted from
  the render.
- A `normalize_data` staticmethod (mirroring `TableElement.normalize_data`)
  rectangularises ragged rows, coerces bad cells, defaults missing keys, and gives
  every cell a valid `kind` (unknown → `"static"`), reusing the same `MAX_ROWS`/
  `MAX_COLS`/degenerate-collapse guards; a degenerate 0×N (or N×0) grid collapses to
  the **default 2×2 grid** (identical to `TableElement.normalize_data`). It also
  **coerces the scalar fields** so `save()` can never fault on a tampered import:
  a non-string `prompt` → `""` (else trimmed); a non-bool `case_sensitive` /
  `header_row` / `header_col` → `bool(...)`; a `border` outside the enum → the
  default `"grid"`; a non-string answer-cell `answer` → `""`.

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
   cell"** toggle converts the **active cell** between *static* (contenteditable rich
   cell) and *answer* (shaded plain-text `<input>` pre-filled with the accepted
   string; placeholder documents the `|` separator). The editor tracks the **active
   cell** as the last grid cell to receive focus / caret / input selection; the
   toggle is **disabled (no-op) when no cell is active**, so there is always a single
   unambiguous target for the stash-and-restore.
   **Conversion never silently loses content.** On static→answer, the cell's prior
   rich `html` is **stashed** in the editor's client state and the answer input seeds
   **empty**; on answer→static, the cell restores its stashed `html` (or empty if
   none) and the answer string is stashed likewise — so an accidental toggle is fully
   reversible within the editing session. The stash is keyed to the **live cell DOM
   node** (a per-node token, not an `r/c` position), and **all stashes are discarded
   on any structural grid edit** (row/column insert, delete, or reorder) so a stash
   can never restore into the wrong cell after the grid shape changes. Only the
   cell's *current* mode is serialised into `data` (static ⇒ `html`, answer ⇒
   `answer`); the stash is editor-only and not persisted.
3. A **capture-phase submit guard** (before editor.js's bubble-phase save) flushes
   any debounced reconcile and blocks submit with a clear inline message if there
   is no answer cell or any answer cell is blank.
4. `save_element` (`builder.py`) + `FillTableElementForm.clean` parse `data`,
   normalise it, and persist via `save()`.

### Student render + check

1. `filltableelement.html` renders like the display table (`.el--filltable`,
   border/header classes, per-cell `ta-*`/`va-*`). Static cells emit sanitised
   HTML (`|safe`); answer cells emit an **empty** `<input type="text" data-r data-c>`
   — **the accepted answer string must never reach the client** (no `value=`, no
   `data-answer`, no `json_script`/inline-JSON dump of `data`): only static-cell
   `html` and cell geometry are serialised to the DOM, since checking is server-side
   only and any leaked answer would trivially defeat the self-check via View Source.
   Optional `prompt` renders (escaped) above; one **Check** button below. The whole
   widget is wrapped in a root element carrying `data-element-pk`, `data-check-url`
   (the reversed `filltable_check` URL, mirroring switchgrid's `data-check-url`), and
   the translated `data-success-msg` / `data-retry-msg` summary strings, so multiple
   fill-tables coexist on one page.
2. `filltable.js` operates **per element instance**: it scopes collection and
   painting to its own widget root (never global). On init it calls
   `window.renderMathInElement(root)` so static-cell math typesets (and re-typesets
   after editor AJAX fragment swaps where page-level auto-render won't fire). It
   **returns early (no-op) when the root's `data-element-pk` is falsy or `"0"`, or
   `data-check-url` is absent** — the unsaved editor-preview case (mirrors
   `switchgrid.js`'s `if (!pk || pk === "0" || !url) return;`). Otherwise, on Check
   it collects the root's answer-cell values (keyed `r{row}c{col}` *within that
   root*) and POSTs them to the root's `data-check-url` as **individual form fields
   named `r{row}c{col}`** — the pk travels in the **URL path**, not the body — with
   the `X-CSRFToken` header (from the `csrftoken` cookie) and `credentials:
   "same-origin"`, mirroring `switchgrid.js`. It paints each answer cell
   correct/incorrect from the response; shows the mutually-exclusive success /
   try-again summary from `data-success-msg` / `data-retry-msg`; and **locks on
   success** — but **only when the response reports at least one answer cell and
   `all_correct` is true** (never locks on an empty `cells` list). Lock = disable
   inputs + hide Check, guarded by
   `.filltable__confirm[hidden]{display:none!important}`.
3. `filltable_check(request, element_pk)` — pk is a **URL path kwarg**
   (`courses/element/<int:element_pk>/filltable-check/`, registered in
   `courses/urls.py`), exactly like `switchgrid_check`. It mirrors switchgrid's
   structure and gate order: **soft lookup first** — `.first()` on the pk; if it is
   `None` (no such element) or the concrete element is not a `FillTableElement`,
   **return the 200 empty-set body immediately** (never dereferencing a missing
   element); **only then**, on a found element, run
   `can_access_course(request.user, element.unit.course)`, raising `PermissionDenied`
   on a found-but-forbidden element. (This order matters: gating access before the
   existence check would dereference `None.unit.course` and 500 instead of returning
   the promised 200 — the exact ordering of `switchgrid_check`. "pk missing" here
   means "`.first()` → None", not an absent request field.) Each answer cell's value
   is read with `request.POST.get("r{r}c{c}", "")` (an absent field ⇒ empty input ⇒
   that cell incorrect, never a 500). It splits each stored answer string on `|`,
   trims, drops empty alternatives, and passes the resulting list to
   `courses.marking.blank_matches(got, accepted_lines, case_sensitive=…)` as
   `accepted_lines` (using the **same** split/trim/drop rule as the form's
   blank-answer validation, so authoring and checking agree). It returns a flat
   list:
   - **hit, all answer cells correct:** `{"cells": [{"r":R,"c":C,"correct":true}, …],
     "all_correct": true}`
   - **hit, partial:** same `cells` list with mixed `correct`; `"all_correct": false`
   - **soft-pk miss OR an element with zero answer cells:** `{"cells": [],
     "all_correct": false}` — `all_correct` is `false` for the empty set, never the
     vacuous `true`, so the client cannot false-lock.
   - **bad/missing POST value for a present answer cell:** treated as empty input →
     that cell is `correct: false` (never a 500).
   Never persists; records no marks.

### Answer matching

Reuse `courses.marking.blank_matches` (imported `from courses.marking import
blank_matches`, as `courses/views.py` and `courses/models.py` already do). Its
matching is **dual**: it matches on whitespace-normalised text **or** on numeric
value when both sides parse as numbers (so `3,14`, `3.14`, and `3.140` are all
equal, and a comma decimal separator matches a dot). This numeric branch is a
feature for a maths context, but authors must be aware of it — e.g. `3` will match
`3.0`, and a bare `0,5` already matches `0.5` without needing an explicit
alternative.

Each answer-cell string is split on `|` into **alternatives**; the student matches
if any alternative matches. A single table-wide **`case_sensitive`** flag threads
into `blank_matches(…, case_sensitive=…)`. Alternatives are trimmed and empty ones
dropped; empty student input → incorrect.

- **`|` is a hard separator with no escape** (accepted YAGNI limitation): an answer
  cannot itself contain a literal `|`. The `|`-split example
  `"0,5 | 0.5"` in the data model is illustrative only — because of the numeric
  branch a single `0,5` suffices; genuine use of alternatives is for distinct
  *textual* forms (e.g. `pi | π`).
- **"Blank" for validation** (see form validation) means **zero non-empty
  alternatives after trimming**, so a pipe-only answer like `"|"` or `"  |  "`
  (which can never match) is rejected exactly like an empty string.

### has_math / script gating

`build_lesson_context` drives math and script gating through **two distinct
mechanisms** (matching the real switch-grid/table shape — do not collapse them into
one bare flag):

- **Math OR-chain** — a **content-inspecting** helper `_fill_table_has_math(obj)`
  that looks for actual `\(…\)` / `\[…\]` delimiters in the static cells (fill-table
  static cells share `TableElement`'s cell shape/`html` key, so this can reuse
  `_table_has_math`). This is what folds into the inline `has_math` OR-chain, so
  KaTeX loads **only** for a fill-table that actually contains math — not for every
  fill-table.
- **`<script>` existence gate** — a separate existence flag
  `has_fill_table = node.elements.filter(...)` driving the `has_<type>` `<script>`
  gate in `lesson_unit.html` (a non-nestable element's JS is gated there, not via
  `_element_has_math`).

Because a fill-table may be placed as content on a quiz page, the **quiz-unit
builder** gets both mechanisms too: the content-inspecting math helper folded into
its math gate (so static-cell KaTeX typesets) **and** the existence flag driving its
`<script>` gate (so `filltable.js` loads). Adding only the script gate would load
the JS but leave math cells un-typeset on a quiz page.

### Transfer (export / import)

Transfer trio for key `fill_table`: serializer emits `data` verbatim; 3-arg
validator `(data, elid, media_kinds)` raises via `_err(_(…), el=elid)` and
`return set()` (no media); builder constructs the model and `save()`s
(re-sanitising static cells). No new media kinds, no `FORMAT_VERSION` bump.

**Validator vs. `normalize_data` — clear division of labour** (they are not in
tension):

- The **validator rejects only gross structural corruption** that indicates a
  malformed/hand-tampered payload: `data` not a dict; `cells` present but not a
  list; a row that is not a list; a cell that is not a dict. These are the shapes an
  honest export never produces. A **value-enum** field like `border` is deliberately
  **not** validator-rejected — a future version could add a border option, so an
  out-of-enum `border` is honest cross-version drift; it falls through to
  `normalize_data`'s default-coercion instead (aligning with `TableElement`'s
  transfer validator, which likewise does not hard-reject on `border`).
- **`normalize_data` (at build/`save()`) tolerantly repairs everything else** an
  honest export might carry across versions: ragged rows (padded), missing
  top-level keys (defaulted), unknown/missing per-cell `kind` (→ `static`), and
  out-of-range alignments.
- The validator **does not** enforce the form's authoring rules (≥1 answer cell,
  no all-blank answer cell) — those guard *authoring*, and the import path
  deliberately bypasses the form. A zero-answer imported table is therefore
  accepted and is harmless at runtime: the check endpoint returns
  `all_correct:false` for the empty set and the client never locks (see "Student
  render + check").

## Error handling

- **Malformed / ragged stored data** → `normalize_data` rectangularises rather than
  raising; degenerate 0×N collapses to the default grid; non-dict cells and unknown
  `kind` coerce to a safe static cell. The student render and check tolerate any
  normalised shape.
- **Form validation** — missing answer cells or an all-blank answer cell are
  rejected in the form (`clean`) *and* pre-empted by the editor's capture-phase
  submit guard, so the author sees a clear inline message, never a server 500.
- **Defensive parse in the endpoint** — `filltable_check` never 500s on bad/missing
  POST keys: absent values are treated as empty (incorrect); the soft lookup /
  wrong-type miss returns the 200 empty-set body **before** any access dereference
  (mirrors `switchgrid_check`, unlike fillgate's 404); a found-but-forbidden element
  raises `PermissionDenied` via `can_access_course`.
- **XSS** — static-cell HTML is sanitised at `save()` and on import with the
  existing math-protected `sanitize_cell`; answer text is compared as plain text and
  is emitted only as an input `value`/placeholder in the editor, escaped; the
  `prompt` is plain text emitted escaped (never `|safe`).
- **No-JS fallback** — inputs render and are usable; Check is inert (checking is
  server-side only) — consistent with the other self-checks.

## Testing

- **Unit** — `normalize_data` (ragged / degenerate / unknown-kind); `save()`
  sanitisation (static HTML sanitised, answer text + `prompt` left plain but
  trimmed); form parse round-trip (static/answer cells, `|` alternatives,
  empty-answer rejection, **pipe-only `"|"` answer rejection**, no-answer-cell
  rejection); `blank_matches` wiring incl. `case_sensitive` **and the numeric
  branch** (`0,5` matches `0.5`; `3` matches `3.0`).
- **View** — `filltable_check` (all-correct, partial, **zero-answer-cell element →
  `{"cells":[],"all_correct":false}`**, soft-pk miss → 200 with the empty-set body,
  access gate, missing POST keys → cell incorrect not 500); `manage_element_add` for
  `filltable` → 200 (covers the `element_add` → `_host_form` → `_edit_filltable`
  render path); a test asserting `editor.html` loads `filltable.js`; a test that the
  palette card is **absent from the nested (`nested=True`) add-menu**.
- **Transfer** — round-trip export → import; validator **rejects the enumerated
  malformed shapes** (non-dict `data`, non-list `cells`, non-list row, non-dict
  cell) and **accepts** a tolerable-but-imperfect export (ragged / unknown-kind /
  zero-answer / out-of-enum `border` → defaulted by `normalize_data`); update the
  `ELEMENT_MODELS` count assertion in the transfer-schema test.
- **Editor JS** — static↔answer toggle is reversible (stash restores prior `html`
  on toggle-back); the capture-phase submit guard blocks a no-answer-cell / blank
  save with an inline message.
- **e2e (Chromium)** — author a fill-table, then drive the **real student gesture**
  (type into cells, click Check), asserting per-cell ✓/✗ and the success lock —
  the actual click path, not `page.evaluate`.

## Touch-points checklist (kept in lockstep)

`ELEMENT_MODELS` + model + migration; `FORM_FOR_TYPE` + `FillTableElementForm`;
`save_element` (`builder.py`); `_add_menu.html` palette card (Interactive group,
inside the non-nestable `{% if not nested %}` section);
`element_add`/`element_save` tuples (`views_manage.py`); `_EDITOR_TYPE_LABELS`;
`_ELEMENT_LABELS` + `element_summary` (`courses_manage_extras.py`); student template
(emitting `data-element-pk` + `data-check-url` + translated `data-success-msg` /
`data-retry-msg` on the widget root, and **never** the answer string);
edit-form partial `_edit_filltable.html`; **`courses/urls.py` route for
`filltable_check` (`courses/element/<int:element_pk>/filltable-check/`,
`name="filltable_check"`)** + the `filltable_check` view; transfer trio
`SERIALIZERS`/`VALIDATORS`/`BUILDERS`; i18n EN/PL; JS enhancer wired into **both**
`editor.js` (re-run `window.libliInitFillTable` after each fragment swap) **and**
`editor.html` (add `<script src=".../filltable.js" defer>`, guarded by a test);
`build_lesson_context` — content-inspecting `_fill_table_has_math` in the math
OR-chain + separate `has_fill_table` existence flag for the `<script>` gate — plus
the same two on the quiz-unit builder; per-element `manage_element_add` 200
authoring test.
