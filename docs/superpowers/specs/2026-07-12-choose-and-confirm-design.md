# Choose & confirm gate (`SwitchGateElement`)

Slice 3 (final) of the reveal-gate family of interactive content elements, ported from the legacy
Flask/JS "Demo Course" `switch_steps` widget. Follows slice 1 (**Show more** reveal gate, PR #99)
and slice 2 (**Fill in & confirm** / `FillGateElement`, PR #104), and reuses their substrate: the
shared client-side reveal cascade engine and the server-checked gate pattern.

## Purpose

Give teachers an inline **"Choose ▾"** widget embedded in lesson text. The student cycles a token
through a small set of author-defined options (text or inline math), then presses **Confirm**:

- **Correct choice** → the following sibling elements within the current scope (unit body, or a tab
  panel) are revealed, cascading to the next gate — identical reveal behavior to slices 1 & 2.
- **Incorrect choice** → an inline **"Try again"** message appears; the widget stays editable so the
  student can cycle to another option and retry.

The widget is a **lesson reveal, not a quiz**: it records no marks and stores no per-student state.
The correctness check runs **server-side** so the correct option index never ships to the client.
With JavaScript disabled everything is already server-rendered and visible (fail-open), matching the
reveal-gate family invariant that content is never permanently trapped behind dead JS.

This completes the reveal-gate trilogy. The multi-line grid grading variant of the legacy widget
(`switch_options` graded together) is explicitly **out of scope** — it remains its own future
element on the interactive-elements roadmap.

## Architecture / components

A new element type wired into every lockstep touch-point the codebase requires for a content
element. Naming follows the family convention (three distinct key spaces, as documented for
reveal-gate/fillgate):

- **type key** `switchgateelement` (in `ELEMENT_MODELS`, `models.py`)
- **form key** `switchgate` (in `FORM_FOR_TYPE`, `element_forms.py`)
- **transfer key** `switch_gate` (snake_case, in the transfer `SERIALIZERS`/`VALIDATORS`/`BUILDERS`)

### Data model (`SwitchGateElement(ElementBase)`, `courses/models.py`)

- `stem` — `TextField`, holds the surrounding lesson text with **exactly one** `�0�`
  placeholder sentinel marking where the cycler renders inline. Mirrors `FillGateElement.stem`; the
  render splits on the sentinel exactly as fillgate does, but the token expands into the cycler
  widget rather than an `<input>`.
- `options` — `JSONField(default=list)`, a `list[str]` of option HTML fragments. Sanitized on
  `save()` with the same allowlist used for table cell HTML, so inline math (`\(+\)`) and basic
  markup survive while scripts do not.
- `answer` — `IntegerField(default=0)`, the index into `options` of the correct option.
- `elements = GenericRelation(Element)` — cascade delete of the join row, as every element model has.
- `render()` — mirrors `FillGateElement.render()`: looks up the join pk (`eid`) and renders
  `courses/elements/switchgateelement.html` with `{el, eid}`.

The stored `options`/`answer` shape keeps the correct index in a scalar field the server reads and
the student template never emits, which is what makes the server-side check meaningful.

### Server check endpoint (`switchgate_check`, `courses/views_take.py` + `courses/urls.py`)

A JSON POST endpoint mirroring `fillgate_check`:

- Accepts the chosen option index (form field `choice`) plus the element pk (from the URL, as
  fillgate does).
- Returns `{"correct": bool}` — `true` only when the posted index equals the element's stored
  `answer`. An out-of-range index, the placeholder sentinel value, a missing/non-integer `choice`,
  or a pk that does not resolve all return `{"correct": false}` (never a 500).
- CSRF-protected and gated on `X-Requested-With` like the other AJAX endpoints; enforces the same
  access checks fillgate's endpoint uses (student can reach the lesson).

### Client enhancer (`courses/static/courses/js/switchgate.js`)

IIFE mirroring `fillgate.js`:

- Sets `window.__switchGateBooted = true` at parse time — the `lesson_unit.html` prepaint watchdog
  fails the gate **open** (disarms the pre-hide) if this flag is still falsy at `DOMContentLoaded`,
  so a booted `reveal.js` plus a dead `switchgate.js` can never trap content hidden.
- **Cycle:** clicking the cycler token advances a current-index cursor through the rendered options;
  the first shown state is the placeholder ("Choose ▾", cursor at a sentinel "unchosen" value), then
  each click steps to option 0, 1, … and wraps. Options are all present in the DOM (the student can
  read them by cycling anyway); only the correct *index* is withheld, server-side.
- **Confirm:** posts the current index to `data-check-url` with CSRF; on `{correct:true}` it locks
  the widget (removes the Confirm button, marks the container `--done`) and calls
  `window.libliRevealCascade(container, {hideWrapper:false})`; on `{correct:false}` it shows the
  inline "Try again" message and leaves the widget editable. An unsaved preview (pk `0` / missing
  url) is a no-op. A network/parse error leaves the gate closed and the widget editable (fail-safe).
- Exports idempotent `window.libliInitSwitchGates(root)` (re-runnable over a subtree).

### Rendering & wiring

- **Student template** `templates/courses/elements/switchgateelement.html`: renders `stem` with the
  sentinel replaced by the cycler markup (placeholder token + all option spans + Confirm button),
  wrapped in a `[data-switchgate]` container carrying `data-element-pk` and `data-check-url`. Confirm
  starts `hidden` and is armed by JS (so no-JS users see a plain, already-revealed page). Reuses
  fillgate's student styling idiom.
- **Editor partial** `templates/courses/manage/editor/_edit_switchgate.html`: a stem textarea + an
  "insert choice" button that drops the sentinel token, plus a repeatable **options list** where each
  row is a math-capable input with a radio marking the correct one. Field names match
  `SwitchGateForm`. (A missing `_edit_<form_key>.html` 500s `TemplateDoesNotExist` the instant the
  palette card is clicked — this partial is mandatory.)
- **Enhancer wiring (both files):** `editor.js` re-runs `window.libliInitSwitchGates(preview)` after
  each fragment swap (next to the gallery/tabs/fillgate re-inits); `editor.html` adds
  `<script src="…/switchgate.js" defer>` (the step historically missed for gallery and reveal-gate,
  which shipped with a blank preview pane — guarded here by a test).
- **Palette:** an "Interactive" group card in `_add_menu.html`, beside the other gates.
- **Transfer:** `SERIALIZERS` (`export.py`), `VALIDATORS` (`payloads.py`), `BUILDERS`
  (`importer.py`) under transfer key `switch_gate`; **bump `FORMAT_VERSION`** (`transfer/schema.py`)
  since the on-disk element shape gains a type. Add `switchgateelement` to `NESTABLE_TYPE_KEYS`
  (`builder.py`) — it must be addable inside tabs like the other gates — with the form-key alias
  registered at `resolve_scope` (transfer key ≠ form key).
- **Other lockstep touch-points:** `save_element` (`builder.py`); `element_add`/`element_save`
  tuples and `_EDITOR_TYPE_LABELS` (`views_manage.py`); `_ELEMENT_LABELS` + `element_summary`
  (`courses_manage_extras.py`); EN/PL i18n for every new translatable string; a migration for the
  new model.

## Data flow

**Authoring:** teacher adds the element from the Interactive palette group → `element_add` renders
`_host_form.html` → `_edit_switchgate.html` → teacher writes stem, inserts the choice token, adds
options and marks one correct → `element_save` → `SwitchGateForm.clean` validates (exactly one token
in stem, ≥2 options, exactly one correct, `answer` in range) → `save_element` persists;
`options` HTML is sanitized in `save()`.

**Taking (JS on):** lesson page server-renders the stem with the cycler and all options, following
siblings pre-hidden by `reveal.js`'s prepaint arm → `switchgate.js` boots, arms Confirm →
student cycles + confirms → POST `switchgate_check` → `{correct}` → correct: lock +
`libliRevealCascade` reveals next siblings and chains to the next gate; incorrect: inline "Try
again", retry allowed.

**Taking (JS off):** watchdog disarms the pre-hide (either because `reveal.js` never armed or because
`__switchGateBooted` is falsy) → the whole unit, including all following siblings, is visible; the
cycler/Confirm are inert but harmless.

**Transfer:** export writes `{type: "switch_gate", stem, options, answer}`; import validates the
shape and rebuilds the model; `FORMAT_VERSION` bump lets older importers reject the new shape cleanly.

## Error handling

- **Server:** every malformed input to `switchgate_check` (bad/missing/out-of-range index,
  placeholder value, unresolved pk) returns `{"correct": false}`, never a 500. Access control matches
  fillgate's endpoint.
- **Form validation:** `SwitchGateForm.clean` rejects a stem without exactly one sentinel token,
  fewer than 2 options, zero or multiple "correct" selections, or an `answer` out of range, with
  field-level errors.
- **Client fail-open:** the `__switchGateBooted` flag + `lesson_unit.html` prepaint watchdog
  guarantee content is never left permanently hidden if `switchgate.js` fails to boot. A fetch/JSON
  error during Confirm leaves the gate closed and the widget editable — no content is lost, the
  student simply cannot advance via the gate until JS/network recovers (and with the page fully
  server-rendered, a reload falls back to the visible state).
- **Unsaved preview:** in the builder preview the element pk is `0`; Confirm is a no-op (no endpoint
  call), so the editor never errors on an unsaved element.
- **Sanitization:** option HTML is sanitized on `save()`; unsafe markup cannot reach the student
  template.

## Testing

TDD per task. The suite must cover:

- **Model/form:** `save()` sanitizes option HTML; `SwitchGateForm.clean` validation matrix (token
  count, option count, exactly-one-correct, answer range).
- **Server endpoint:** `switchgate_check` returns `correct:true` only for the exact stored index;
  `false` for wrong/out-of-range/placeholder/missing; unsaved/unresolved pk safe; access control.
- **Authoring render path:** GET **and** POST `manage_element_add` for `switchgate` return 200 — this
  exercises `element_add → _host_form → _edit_switchgate` end-to-end, the path that shipped broken for
  reveal-gate (missing `_edit_` partial, fixed in PR #100) precisely because row/palette tests didn't
  cover it.
- **Editor script wiring:** GET `manage_editor` asserts the `switchgate.js` `<script>` is present in
  `editor.html` (the twice-missed step).
- **Transfer:** round-trip export → import preserves `stem`/`options`/`answer`; `FORMAT_VERSION`
  bump reflected; nestable inside tabs.
- **e2e behavior matrix** (real UI, real gesture — no `page.evaluate` shortcut): cycle options →
  Confirm wrong → "Try again" + still editable → cycle to correct → Confirm → following siblings
  reveal → chain to the next gate. Include a no-JS/fail-open assertion that content is visible.

**DoD:** full test suite green; `ruff check` **and** `ruff format --check`; i18n catalog tests if any
translatable strings are removed (none expected — this only adds strings).
