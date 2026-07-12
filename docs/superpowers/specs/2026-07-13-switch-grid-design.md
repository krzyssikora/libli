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
    prompt = models.TextField(blank=True)   # optional PLAIN-TEXT instruction line
    lines  = models.JSONField(default=list)
    elements = GenericRelation(Element)      # GFK join parity with other elements

    def save(self, *args, **kwargs): ...     # sanitizes every option HTML, mirrors SwitchGateElement.save
    def render(self): ...                     # renders switchgridelement.html with the GFK join pk, mirrors SwitchGateElement.render
```

**`prompt` is plain text, not author HTML/math.** It renders auto-escaped (Django default),
carries no math, and is therefore **not** sanitized as HTML and **not** included in the `has_math`
scan. (Deliberately narrower than the legacy `question_text`, to avoid an unsanitized injection
point and to keep math confined to stems/options.)

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

> **Sentinel handling (M2):** the `￿{i}￿` tokens shown in JSON examples in this spec are
> illustrative only. In code and tests the sentinel character must always be built from
> `courses.fillblank.SENTINEL` (`SENTINEL + str(i) + SENTINEL`), never copy-pasted from this
> document — the U+FFFF sentinel corrupts to U+FFFC through some file tools (the choose-and-confirm
> learning).

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
`SwitchGateForm` stem handling).

**POST field-naming convention (I2)** — the submission is parsed independently of the JS UI from
indexed field names (the marker↔cycler positional binding is established by the numeric indices in
the names, not by DOM order):

- `line-{i}-stem` — the stem text for line *i* (author types `{{choice}}` markers).
- `line-{i}-cycler-{j}-option-{k}` — option *k* of cycler *j* on line *i*.
- `line-{i}-cycler-{j}-answer` — the 0-based correct index for cycler *j* on line *i*.

`clean()` reconstructs `lines` by iterating *i*, then *j*, then *k* over the present indices; the
*j*-th cycler binds to the *j*-th `{{choice}}` marker in `line-{i}-stem`.

`clean()` validation:

1. **At least one line, and at least one cycler total across the grid (I5).** A grid with no lines,
   or whose every line is all-static (zero `{{choice}}` markers, zero cyclers), is rejected — this
   forecloses the vacuous "AND over zero cyclers == true" success. (A line with 0 cyclers is
   permitted *only* if some other line has ≥ 1; a grid needs ≥ 1 cycler overall.)
2. For each line, parse the stem via `parse_stem_multi`; the marker count **must equal** that
   line's authored cycler count, else a validation error naming the line.
3. **Blank options (I2):** dynamic-row UIs submit empty option inputs. `clean()` **drops blank
   option values first**, then applies the "≥ 2 options" count to the surviving non-blank options.
   The `answer` picker is submitted as a stable reference to a specific option row; after dropping
   blanks, `clean()` re-resolves `answer` to the 0-based index of the chosen option **within the
   compacted non-blank list**, and rejects the cycler if the chosen option was itself blank/dropped
   or the resolved index is out of range. (Equivalently: options are compacted to contiguous
   non-blank entries and `answer` is remapped onto that compacted list — never left pointing at a
   dropped slot.)
4. Each surviving cycler must have ≥ 2 non-blank options and a valid resolved `answer` index.
5. Sanitize stem segments; store the normalized `lines` JSON on the instance.

Registered in `FORM_FOR_TYPE`; saved through `save_element` (`courses/builder.py`).

### Student render — `switchgridelement.html` + `{% render_switch_grid %}` tag

`templates/courses/elements/switchgridelement.html` delegates to a `render_switch_grid` template
tag (parallel to `render_switch_gate`). Layout, top to bottom: the optional `prompt` (rendered
**above the lines**, only when non-blank), then one **`data-line`-tagged container per line**, then
one **confirm** button plus a hidden success / "try again" summary. For each line the tag splits
the stem on its sentinels and splices in a **cycler widget** per token; a static line renders its
stem with no cyclers (but still gets its `data-line` container — see I3/C1).

**Cycler option-set embedding (I1):** each cycler element must expose its **full ordered
option-HTML list** in the DOM so `switchgrid.js` can cycle and re-typeset — mirroring exactly how
`switchgate.js` embeds its options (whichever it uses: hidden option child nodes or a JSON
`data-options` attribute; follow switchgate's carrier for consistency). Only the display shows
`options[0]` initially; the remaining options ship in that carrier. **`answer` is never emitted**
(the correct index stays server-side).

**Summary strings (M3):** the success and "try again" messages are **fixed EN/PL i18n strings**,
not author-configurable. Math is typeset by the existing MathLive/KaTeX pipeline.

**No-JS fallback:** each cycler renders `options[0]` as static text; the grid is visible but
inert (confirm does nothing). Acceptable for a no-marks self-check — parity with the gates'
"content visible without JS" fallback.

### Client enhancer — `courses/static/courses/js/switchgrid.js`

`window.libliInitSwitchGrid(root)` (idempotent boot guard, e.g. `__switchGridBooted` +
`switchgrid-armed` prepaint watchdog, following `switchgate.js`):

- **Options-only cycler ring (M4 — deliberate deviation from `switchgate.js`):** each cycler
  cycles over indices `0..n-1` with **no** placeholder. It starts displaying `options[0]`
  (`currentIndex = 0`); there is no `-1` "Choose ▾" placeholder state that switchgate.js uses.
  An implementer must not copy switchgate.js's placeholder ring verbatim.
- **Per-line container + per-cycler DOM addressing (I3, C1):** the render tag emits **one
  container per line carrying `data-line="{i}"` for EVERY line — including all-static lines with
  zero cyclers** — and, inside it, each cycler element carries `data-cycler="{j}"` in stem-marker
  order. The alignment invariant, which must survive a leading/interleaved static line:
  - JS builds `indices` with **exactly one sub-list per line, in line order**, iterating the
    `data-line` containers (not by grouping loose cyclers); a static line contributes `[]`.
  - The server reads `indices[i]` **positionally** against stored `lines[i]`, and returns
    `cells` the same shape — one sub-list per line, `[]` for a static line.
  - `cells[i][j]` / `indices[i][j]` therefore index cyclers by stem-marker position within line
    `i`; the AND-fold for `correct` ignores empty (static) lines. JS locates cycler `[i][j]` for
    feedback via `data-line`/`data-cycler` (no positional DOM-walk guessing).
- Cycler click → advance that cycler's `currentIndex` modulo option count, re-render its option
  HTML, re-typeset math, and **clear any stale `correct`/`incorrect` class on that cycler**
  (parity with switchgate's `advance()`).
- Confirm click → collect indices as a list-of-lists ordered `[line][cycler]` and POST them to
  `switchgrid_check` **JSON-encoded in a single form field**: `indices=<json>` where `<json>` is
  `JSON.stringify(indicesListOfLists)` (chosen over a raw JSON body so the CSRF-token form field
  rides along unchanged, matching the app's fetch convention). Server parses with `json.loads`.
- On response: apply per-cycler `correct`/`incorrect` classes from `cells`, then —
  **re-attempt / lock behavior (I4):**
  - `correct == true` → reveal the whole-grid success summary, **lock all cyclers** (no further
    cycling) and remove/hide the confirm button (switchgate parity on success).
  - `correct == false` → show the "try again" summary; cyclers stay **interactive** — the student
    may re-cycle any token (which clears that cycler's stale class per the click rule) and press
    confirm again. No lock on failure.

Wired into **both** `editor.js` (`window.libliInitSwitchGrid(preview)` re-run after each editor
fragment swap, next to the gallery/tabs/switchgate re-inits) **and** `editor.html` (a
`<script src=".../switchgrid.js" defer>` tag) — the step historically missed for gallery and
reveal-gate. A test asserts the `editor.html` script tag is present.

### Server endpoint — `switchgrid_check` (`courses/views.py`, URL in `courses/urls.py`)

`POST /…/switchgrid/<element_pk>/check`. **Soft pk lookup** (switchgate parity): a missing or
wrong-type pk returns `200 {"correct": false, "cells": []}`, not 404. Access gated by
`can_access_course` (raise `PermissionDenied` otherwise).

**Request parse (C5):** reads the `indices` form field and `json.loads` it into a list-of-lists
`[line][cycler]` of ints. A missing/non-JSON/ill-shaped `indices` (not a list-of-lists of ints) →
`200 {"correct": false, "cells": []}` (never 500). Then, comparing against the stored `lines`
in stem-marker order: a submitted index that is missing (short payload) or out of range for its
cycler counts as **incorrect** for that cycler rather than erroring. Returns:

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

**Sanitization on import (M1):** the import path bypasses `SwitchGridForm.clean()`, so
`VALIDATORS`/`BUILDERS` must **sanitize stem segments** (split on sentinels, `sanitize_cell` each
segment) in addition to options — otherwise a hand-crafted import file's stem HTML would be stored
unsanitized and later spliced as `SafeString` by `render_stem_multi`. This upholds the "all
option and stem-segment HTML sanitized before storage" invariant on **both** the form and import
paths (match whatever `SwitchGateElement`'s importer does for its stem).

### Registration touch-points (lockstep — all required for the element to work)

A new `ElementBase` subclass is unreachable unless every registration site is updated together.
The full set, each an explicit implementation step:

1. **`ELEMENT_MODELS`** (`courses/models.py` ~line 259) — append `"switchgridelement"`. This list is
   the source of truth that feeds `Element.content_type`'s `limit_choices_to` (~line 313); the
   count assertion in `tests/test_transfer_schema.py` is a *consequence* of this edit, not the
   requirement.
2. **Migration** — generate `courses/migrations/0040_switchgridelement.py` (next free number) that
   `CreateModel`s `SwitchGridElement` **and** `AlterField`s `element.content_type.limit_choices_to`
   to include the new type (exactly the shape of `0038_switchgateelement.py` +
   `0039_*_alter_element_content_type.py`). DoD includes `makemigrations --check` (no missing
   migration) and applying migrations.
3. **`FORM_FOR_TYPE`** (`courses/element_forms.py`) — map form key `switchgrid` → `SwitchGridForm`.
4. **`element_add` and `element_save` type allow-tuples** (`courses/views_manage.py` ~875 / ~932) —
   insert `"switchgrid"` into **both**, or the palette card 400s ("bad type") on click/save even
   with the form registered.
5. **`_EDITOR_TYPE_LABELS`** (`courses/views_manage.py` ~738) — add a `"switchgrid"` label (the
   editor heading).
6. **Palette card** — add the "Switch grid" card to the **Interactive** group in the add-menu
   palette template (`templates/courses/manage/_add_menu.html`) with a monochrome `currentColor`
   SVG icon.
7. **Edit-form partial** — `templates/courses/manage/editor/_edit_switchgrid.html`, dynamically
   `{% include %}`d by `_host_form.html`; a missing partial 500s `TemplateDoesNotExist` the instant
   the card is clicked. Field names must match `SwitchGridForm`'s fields.
8. **`_ELEMENT_LABELS` + `element_summary`** (`courses/templatetags/courses_manage_extras.py`
   ~26 / ~72) — add a human label and a one-line summary for the builder row.
9. **`save_element`** (`courses/builder.py`) — handle persisting the `switchgrid` form.
10. **URL** — add the `switchgrid_check` route to `courses/urls.py`.
11. **i18n** — EN + PL strings for all new user-facing text; catalogs stay consistent (no obsolete
    `#~` entries).

### Scope decisions (v1)

- **Not nestable** inside tabs: `NESTABLE_TYPE_KEYS` is left untouched; the non-nestable card
  uses the `{% if not nested %}` guard (Spoiler parity). Nesting can be added later.
- **`has_math` gating (I6)**: the new `_element_has_math` branch (`courses/views.py`) must walk
  **every `lines[].stem`** and **every `lines[].cyclers[].options`** entry — a shallow stems-only
  check would silently fail to load KaTeX for math that lives only in an option. `prompt` is plain
  text (see Data model) and is **not** scanned.

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
  < 2 options rejected; out-of-range `answer` rejected; `{{choice}}` → sentinel conversion;
  **empty grid / all-static grid (zero cyclers) rejected (I5)**; field-naming reconstruction of
  `lines` from indexed POST keys (I2); **blank option inputs dropped then `answer` remapped onto
  the compacted list (I2)** — trailing-blank option and an `answer` pointing at a dropped/blank
  slot both handled (rejected or remapped, never left dangling).
- **Context / render tag** — `render_switch_grid` splices cyclers at the right positions, emits
  `options[0]` as the visible value while **embedding the full option set** in the cycler carrier
  (I1), emits a `data-line` container for **every** line including all-static ones (C1), renders
  `prompt` above the lines when non-blank, includes the confirm button + hidden summary, and
  **never emits `answer`**.
- **Endpoint `switchgrid_check`** — `indices` JSON round-trip; all-correct → `{correct: true,
  cells: all true}`; one wrong → `correct: false` with the right `cells`; bad/missing pk → soft
  `200 correct:false`; no access → `PermissionDenied`; missing/non-JSON/ill-shaped `indices` → no
  500 (soft `correct:false`); short payload and out-of-range index → that cycler counts incorrect,
  no 500; **leading all-static line (C1)** → a later cycler-bearing line still grades correctly
  (positional `indices[i]`↔`lines[i]` alignment, `[]` for the static line).
- **Transfer** — `switch_grid` export→import round-trip preserves `prompt` + `lines`; `ELEMENT_MODELS`
  count assertion in `tests/test_transfer_schema.py` bumped.
- **Authoring** — `manage_element_add` GET and POST for `switchgrid` both return 200
  (guards the `_edit_switchgrid.html` render path).
- **Editor wiring** — GET `manage_editor` asserts the `switchgrid.js` `<script>` tag is present.
- **i18n** — EN/PL strings added; message catalogs stay consistent (no obsolete `#~` entries).
- **e2e (focused, foreground)** — author a grid, cycle tokens, confirm; assert per-cycler
  feedback classes and the whole-grid success message; assert an incorrect confirm shows "try
  again" and leaves cyclers **interactive** (re-cycle clears the stale class), and a correct
  confirm **locks** cyclers + hides confirm (I4).
- **No-marks assertion (M3)** — concretely: after exercising `switchgrid_check`, assert that **no
  `Response`/attempt/mark row is created** for the unit/user (query the relevant results model and
  assert an empty count), i.e. the endpoint is read-only. Not a vacuous "no marks" phrase.
