# Switch grid element (`SwitchGridElement`)

A self-contained lesson **self-check widget** in the **Interactive** palette group: multiple
lines of static math interleaved with clickable "cyclers", checked as a whole grid by one
confirm button. Ported from the legacy Demo Course `.switch_options` widget. It reuses the
cycler substrate of the existing `SwitchGateElement` (Choose & confirm) but is a distinct
element — it grades in place and reveals nothing (it is **not** a reveal gate).

## Purpose

Give authors a lightweight, ungraded self-check where a student clicks tokens to cycle through
candidate values (e.g. an operator `+ / − / · / :`) across several lines, then confirms the
whole grid at once. On confirm the widget marks each individual cycler correct/incorrect and
shows an overall success message only when every cycler is right. **No marks are recorded** —
this is a lesson self-check, like the reveal gates and the Spoiler element, not a quiz question.

### Relationship to `SwitchGateElement` (kept separate)

`SwitchGateElement` ("Choose & confirm", PR #106) is a **reveal gate**: a single inline cycler
whose correct choice reveals the following sibling elements via the shared `libliRevealCascade`
engine. It is one leg of the reveal-gate trilogy (show-more → fill&confirm → choose&confirm).

`SwitchGridElement` shares only the **cycler mechanic** (click-to-cycle a token, server-checked
by index). It differs in role: **many** cyclers across **multiple** lines, graded in place with
per-cycler feedback, revealing nothing. The two are distinct authoring tools and both are kept.
No `reveal-on-success` behavior is added to the grid — that would conflate the two clean patterns
and is explicitly out of scope.

## Architecture / components

### Data model — `SwitchGridElement(ElementBase)` (`courses/models.py`)

```python
class SwitchGridElement(ElementBase):
    prompt = models.TextField(blank=True)   # optional instruction line above the grid
    lines  = models.JSONField(default=list)
    elements = GenericRelation(Element)      # GFK join parity with other elements
```

`lines` is a list of **line objects**, each a token stem plus its ordered cyclers:

```json
[
  {"stem": "3 ￿0￿ 3 = 9", "cyclers": [{"options": ["+", "−", "·"], "answer": 2}]},
  {"stem": "3 ￿0￿ 3 = 0", "cyclers": [{"options": [":", "−"],      "answer": 0}]}
]
```

- `stem` — author HTML/math with each cycler position marked by a sentinel token
  `￿{i}￿` (reusing `courses.fillblank.SENTINEL`). The author types `{{choice}}`; the
  form converts the *i*-th occurrence to the `￿{i}￿` token, indexed exactly like
  fillblank's multi-blank scheme.
- `cyclers` — ordered list, one entry per sentinel in the stem; `cyclers[i]` binds to token
  `￿{i}￿`. Each is `{options: list[str], answer: int}` where `answer` is the 0-based
  index of the correct option. **`answer` is never shipped to the browser.**
- `save()` sanitizes every option HTML fragment via `sanitize_cell` (parity with
  `SwitchGateElement.save`). Stem segments are sanitized at form `clean()` time.

### Stem parser — generalize `courses/switchgate.py` to N tokens

`switchgate.py` currently enforces **exactly one** `{{choice}}` marker (`parse_stem`,
`to_author_stem`, `render_stem`). The grid needs **N** markers per line. Rather than fork the
logic, add multi-token helpers (either extend `switchgate.py` or a small sibling module,
whichever keeps single-token callers untouched):

- `parse_stem_multi(clean) -> (token_stem, count)` — replace the *i*-th `{{choice}}` with
  `￿{i}￿`; return the token stem and the marker count so the form can validate it
  against the number of authored cyclers.
- `to_author_stem_multi(token_stem) -> str` — inverse, for populating the edit form.
- `render_stem_multi(token_stem, widget_html_by_index) -> SafeString` — split on each sentinel
  and splice in the corresponding cycler widget HTML.

The existing single-token `SwitchGateElement` code path is left unchanged.

### Form — `SwitchGridForm` (`courses/element_forms.py`), key `switchgrid`

Fields: an optional `prompt`, plus a dynamically-sized **lines** structure. Each line carries a
stem input and, per `{{choice}}` marker, an options list with a "correct" index picker. Modeled
on the existing dynamic-row authoring patterns (`ChoiceQuestionForm` option rows + the
`SwitchGateForm` stem handling). `clean()`:

1. For each line, parse the stem via `parse_stem_multi`; the marker count **must equal** that
   line's authored cycler count, else a validation error naming the line.
2. Each cycler must have ≥ 2 options and a valid `answer` index within range.
3. Sanitize stem segments; store the normalized `lines` JSON on the instance.

Registered in `FORM_FOR_TYPE`; saved through `save_element` (`courses/builder.py`).

### Student render — `switchgridelement.html` + `{% render_switch_grid %}` tag

`templates/courses/elements/switchgridelement.html` delegates to a `render_switch_grid` template
tag (parallel to `render_switch_gate`). For each line the tag splits the stem on its sentinels
and splices in a **cycler widget** per token. Each cycler renders as a clickable element
initially showing `options[0]`. Below the lines: one **confirm** button plus a hidden success /
"try again" summary. Math is typeset by the existing MathLive/KaTeX pipeline.

**No-JS fallback:** each cycler renders `options[0]` as static text; the grid is visible but
inert (confirm does nothing). Acceptable for a no-marks self-check — parity with the gates'
"content visible without JS" fallback.

### Client enhancer — `courses/static/courses/js/switchgrid.js`

`window.libliInitSwitchGrid(root)` (idempotent boot guard, e.g. `__switchGridBooted` +
`switchgrid-armed` prepaint watchdog, following `switchgate.js`):

- Cycler click → advance that cycler's current index (modulo option count), re-render its option
  HTML, re-typeset math.
- Confirm click → collect every cycler's current index as a list-of-lists (`[line][cycler]`),
  POST to `switchgrid_check`, then apply per-cycler `correct`/`incorrect` classes from the
  returned `cells` map and reveal the whole-grid success summary only when `correct` is true
  (else show "try again").

Wired into **both** `editor.js` (`window.libliInitSwitchGrid(preview)` re-run after each editor
fragment swap, next to the gallery/tabs/switchgate re-inits) **and** `editor.html` (a
`<script src=".../switchgrid.js" defer>` tag) — the step historically missed for gallery and
reveal-gate. A test asserts the `editor.html` script tag is present.

### Server endpoint — `switchgrid_check` (`courses/views.py`, URL in `courses/urls.py`)

`POST /…/switchgrid/<element_pk>/check`. **Soft pk lookup** (switchgate parity): a missing or
wrong-type pk returns `200 {"correct": false, "cells": []}`, not 404. Access gated by
`can_access_course` (raise `PermissionDenied` otherwise). Reads the submitted indices, compares
each to the stored `answer`, and returns:

```json
{"correct": true, "cells": [[true], [true]]}
```

`correct` is the AND over all cyclers; `cells[line][cycler]` is per-cycler correctness. **Nothing
is persisted; no answer values are returned** (only booleans).

### Transfer (export / import)

Transfer key `switch_grid` (snake_case, differs from form key `switchgrid`). Add the trio:
`SERIALIZERS` (`courses/transfer/export.py`), `VALIDATORS` (`courses/transfer/payloads.py`),
`BUILDERS` (`courses/transfer/importer.py`) — serialize `prompt` + `lines` (stems with sentinels
+ cyclers). **No `FORMAT_VERSION` bump**: this is a new element type, not a shape change to an
existing one (per the choose-and-confirm learning).

### Scope decisions (v1)

- **Not nestable** inside tabs: `NESTABLE_TYPE_KEYS` is left untouched; the non-nestable card
  uses the `{% if not nested %}` guard (Spoiler parity). Nesting can be added later.
- **`has_math` gating**: stems and options carry math, so the element must be included in the
  `has_math` touch-point that triggers MathLive/KaTeX loading (the Spoiler learning).

## Data flow

1. **Author** opens the palette → "Switch grid" card → `manage_element_add` renders
   `_edit_switchgrid.html` via `_host_form.html`. They set a prompt and add lines; per line they
   type a stem with `{{choice}}` markers and fill each cycler's options + correct index.
2. **Save** → `SwitchGridForm.clean()` validates marker/cycler counts and option/answer ranges,
   converts `{{choice}}` → `￿{i}￿`, sanitizes; `save_element` persists the model;
   `save()` sanitizes option HTML.
3. **Student view** → `render_switch_grid` renders lines with cyclers at `options[0]` + confirm
   button; `switchgrid.js` enhances. Student cycles tokens, clicks confirm.
4. **Check** → JS POSTs `[line][cycler]` indices to `switchgrid_check`; server compares to stored
   `answer`s, returns `{correct, cells}`; JS paints per-cycler feedback + overall summary. No
   persistence.
5. **Transfer** → export serializes `prompt` + `lines`; import validates and rebuilds.

## Error handling

- **Form validation:** stem marker count ≠ cycler count → field error naming the offending line;
  a cycler with < 2 options or an out-of-range `answer` → field error. No silent truncation.
- **Endpoint:** missing/wrong-type pk → `200 {"correct": false, "cells": []}` (soft lookup);
  no course access → `PermissionDenied`; malformed/short index payload → treat missing entries as
  incorrect (never 500); indices out of range → that cycler is incorrect.
- **No-JS:** grid renders statically at `options[0]`, confirm inert — degraded but not broken.
- **Missing `_edit_switchgrid.html`** would 500 the palette card with `TemplateDoesNotExist`; an
  authoring test GET/POSTs `manage_element_add` for the type and asserts 200 to guard this.
- **Sanitization:** all option and stem-segment HTML sanitized (`sanitize_cell`) before storage
  and never re-marked unsafe at render beyond the vetted stem/widget splice.

## Testing

TDD across, roughly one test module per concern (mirroring the switchgate suite layout):

- **Stem parser** — `parse_stem_multi` / `to_author_stem_multi` / `render_stem_multi`: N-token
  round-trip, 0 markers, multiple markers per line, and marker/cycler count mismatch signalling.
- **Model** — `save()` sanitizes option HTML; `lines` JSON persists round-trip; `render()`
  resolves its GFK join.
- **Form** — valid multi-line/multi-cycler submission; marker≠cycler mismatch rejected;
  < 2 options rejected; out-of-range `answer` rejected; `{{choice}}` → sentinel conversion.
- **Context / render tag** — `render_switch_grid` splices cyclers at the right positions, emits
  `options[0]` initially, includes the confirm button + hidden summary, and never emits `answer`.
- **Endpoint `switchgrid_check`** — all-correct → `{correct: true, cells: all true}`; one wrong
  → `correct: false` with the right `cells`; bad/missing pk → soft `200 correct:false`; no access
  → `PermissionDenied`; short/malformed payload → no 500.
- **Transfer** — `switch_grid` export→import round-trip preserves `prompt` + `lines`; `ELEMENT_MODELS`
  count assertion in `tests/test_transfer_schema.py` bumped.
- **Authoring** — `manage_element_add` GET and POST for `switchgrid` both return 200
  (guards the `_edit_switchgrid.html` render path).
- **Editor wiring** — GET `manage_editor` asserts the `switchgrid.js` `<script>` tag is present.
- **i18n** — EN/PL strings added; message catalogs stay consistent (no obsolete `#~` entries).
- **e2e (focused, foreground)** — author a grid, cycle tokens, confirm; assert per-cycler
  feedback and the whole-grid success message; assert no marks recorded.
