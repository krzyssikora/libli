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
With JavaScript disabled the whole unit — including every following sibling — is already
server-rendered and visible (fail-open), and the cycler degrades to an inert placeholder token (see
"No-JS fallback" under Data flow), matching the reveal-gate family invariant that content is never
permanently trapped behind dead JS.

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
  widget rather than an `<input>`. **Render safety:** stem is escaped/marked-safe on render
  **identically to `FillGateElement.stem`** (same helper, same treatment) — the non-token text
  segments get the same handling fillgate applies, so inline stem math renders and no new XSS surface
  is introduced beyond what fillgate already carries.
- `options` — `JSONField(default=list)`, a `list[str]` of option HTML fragments. Sanitized with the
  same allowlist used for table cell HTML, so inline math (`\(+\)`) and basic markup survive while
  scripts do not. **Sanitization ordering (see I5 resolution under Error handling):** each option is
  sanitized inside `SwitchGateForm.clean` *before* the count/empty checks run, and again
  idempotently in `save()`; an option that sanitizes to empty is a validation error, never silently
  dropped (dropping would shift the `answer` index).
- `answer` — `IntegerField(default=0)`, the index into `options` of the correct option. Invariant:
  `0 <= answer < len(options)`. Enforced by both the form (authoring) and the transfer `VALIDATORS`
  (import) — see C2 resolution.
- `elements = GenericRelation(Element)` — cascade delete of the join row, as every element model has.
- `render()` — mirrors `FillGateElement.render()`: looks up the join pk (`eid`) and renders
  `courses/elements/switchgateelement.html` with `{el, eid}`.

The stored `options`/`answer` shape keeps the correct index in a scalar field the server reads and
the student template never emits, which is what makes the server-side check meaningful.

### Server check endpoint (`switchgate_check`, in the same view module as `fillgate_check` + `courses/urls.py`)

A JSON POST endpoint mirroring `fillgate_check`:

- Accepts the chosen option index (form field `choice`, an integer string) plus the element pk (from
  the URL, as fillgate does).
- **Posted values:** the client posts `choice = -1` for the placeholder/unchosen state, else the
  0-based option index. The endpoint returns `{"correct": true}` **only** when the parsed integer
  equals the element's stored `answer`. Since `answer` is always in `range(len(options))`, `-1` can
  never be correct — so confirming on the placeholder always yields `{"correct": false}`.
- **Malformed input never 500s:** an out-of-range index, `-1`/placeholder, or a missing/non-integer
  `choice` all return `200 {"correct": false}`.
- **pk resolution — deliberate deviation from fillgate:** `fillgate_check` resolves its pk with
  `get_object_or_404` (so a missing or wrong-type pk **404s**, and its test asserts 404). Switchgate
  intentionally does **not** mirror that: it uses a **soft lookup**
  (`Element.objects.filter(pk=…).first()`, wrong content-type treated as a miss) and returns
  `200 {"correct": false}` on a miss — consistent with "malformed-but-authorized input yields
  `200 {correct:false}`," and avoiding a 404/existence-leak boundary. The endpoint test matrix asserts
  `200 {"correct": false}` for an unsaved/unresolved/wrong-type pk. (This is the one place switchgate
  departs from fillgate's guard flow, and it is called out precisely because fillgate resolves the pk
  *before* its access check.)
- **Access control:** for a **resolved** element, enforce the same access check `fillgate_check`
  applies (the requesting user must be able to reach the lesson). An **authorized-but-denied user gets
  a non-200 response** (a `403`/redirect, as fillgate responds for that case); the client treats any
  non-OK response as "leave the gate closed." This is a distinct boundary from malformed-but-authorized
  input (`200 {"correct": false}`); both appear in the endpoint test matrix.
- **Decorators mirror `fillgate_check`** — CSRF-protected via Django's standard machinery plus
  `@require_POST` / `@login_required` (whatever `fillgate_check` actually carries). It does **not** add
  an `X-Requested-With` gate, because `fillgate_check` has none. The only intentional divergence is the
  soft pk lookup above; the decorator stack and access check otherwise match.

### Client enhancer (`courses/static/courses/js/switchgate.js`)

IIFE mirroring `fillgate.js`:

- Sets `window.__switchGateBooted = true` at parse time — the `lesson_unit.html` prepaint watchdog
  fails the gate **open** (disarms the pre-hide) if this flag is still falsy at `DOMContentLoaded`,
  so a booted `reveal.js` plus a dead `switchgate.js` can never trap content hidden.
- **DOM & cycle mechanism (the novel, non-inherited part):** the cycler renders inline as a **real
  `<button type="button" data-switchgate-cycler>`** (not a bare `<span>`/`<div>`), so it is natively
  keyboard-focusable and Enter/Space activate it exactly like a click — no manual `tabindex`/`role`
  wiring. Its **visible ring text is its accessible name** — there is **no
  competing `aria-label`** (an `aria-label` would override the text and make a screen reader announce
  the same static string on every cycle, defeating the point), so the reader announces the current
  ring entry as the cursor changes. Any static "Choose an option" instruction is attached separately
  as a description (a visually-hidden `aria-describedby` target, or `title`), never as the name. The button
  contains a placeholder token (`Choose ▾`) plus one `<span class="switchgate__option">` per option,
  **each option span carrying the HTML `hidden` attribute at render**. The placeholder is therefore
  the only visible ring entry on load. Activating the control (click or Enter/Space) advances a cursor
  through a ring of states — placeholder → option 0 → option 1 → … → option N−1 → **back to
  placeholder** → … (the placeholder **is** re-entered on wrap) — toggling the `hidden` attribute so
  exactly one ring entry shows at a time. The cursor maps to the value the Confirm step will post:
  `-1` at the placeholder, else the visible option's 0-based index. Rendering all option spans leaks
  nothing beyond what a student sees by cycling; only the correct *index* is withheld (server-side).
- **Confirm:** posts the current cursor value (`choice`) to `data-check-url` with CSRF; on
  `{correct:true}` it locks the widget (removes the Confirm button, **disables the cycler button**
  (`disabled`) so it can no longer be clicked, and marks the container `switchgate--done`) and calls
  `window.libliRevealCascade(container, {hideWrapper:false})` — mirroring how the sibling gates freeze
  their input on success; on `{correct:false}` it un-hides the inline **"Try again"** message and
  leaves the widget editable so the student can cycle and retry. **The "Try again" message re-hides
  the moment the student next cycles the control** (a fresh attempt starts clean); it otherwise
  persists until the next Confirm. The "Try again" text is a **hidden translatable element already in
  the template** (mirroring fillgate's `[data-fillgate-feedback]`/`[data-fillgate-message]` pattern),
  armed/shown by JS — not created in JS — so the EN/PL catalog owns the string and no-JS users never
  see a stray message. Confirm is always enabled, including at the placeholder (which resolves to a
  wrong answer). An **unsaved preview is a no-op**, detected canonically by `data-element-pk === "0"`
  (mirroring `fillgate.js`'s `!pk || pk === "0"` guard); the template reverses the check URL even in
  preview, so pk — not URL presence — is the preview signal. A network/parse error leaves the gate
  closed and the widget editable (fail-safe).
- **Math typesetting:** option spans may contain inline math and are `hidden` on load, so
  `switchgate.js` (and the editor-preview re-init) **typesets option + stem math at init regardless
  of visibility** — KaTeX/MathLive renders hidden nodes fine — rather than deferring to reveal time.
  This avoids the known "math in an initially-hidden span never typesets" footgun and keeps a
  freshly-cycled option correctly rendered. Covered by the render/e2e tests.
- Exports idempotent `window.libliInitSwitchGates(root)` (re-runnable over a subtree).

### Rendering & wiring

- **Student template** `templates/courses/elements/switchgateelement.html`: renders `stem` with the
  sentinel replaced by the cycler markup (placeholder token + all option spans, each `hidden`, +
  Confirm button + hidden "Try again" element), wrapped in a container that carries **both
  `data-reveal-gate` and `data-switchgate`** (mirroring fillgate's `<div class="fillgate"
  data-reveal-gate data-fillgate>` — the `data-reveal-gate` attribute is what the `lesson_unit.html`
  pre-hide CSS `:has(> .lesson-block__body > [data-reveal-gate])` and `reveal.js`'s `isGateWrapper`
  key off; without it the gate never pre-hides its following siblings and a preceding gate's cascade
  blows past it). The container also carries `data-element-pk` and `data-check-url`, and must be the
  **block-level direct child** of `.lesson-block__body` / `.tabs__child` (same structural position as
  fillgate) so the `:has(> … > [data-reveal-gate])` selector matches. Confirm starts `hidden` and is
  armed by JS. **No-JS
  result:** with JS off, the option spans stay `hidden` and Confirm stays `hidden`, so a student sees
  only the inert `Choose ▾` placeholder inline — a plain reading experience — while every following
  sibling is already visible (fail-open). Reuses fillgate's student styling idiom.
- **Editor partial** `templates/courses/manage/editor/_edit_switchgate.html`: a stem textarea + an
  "insert choice" button that drops the sentinel token, plus a repeatable **options list** where each
  row is a math-capable input with a radio marking the correct one. **Options-list POST contract**
  (novel — not inherited from fillgate's single-blank shape): every option row posts under the same
  repeated field name `option`, so the view collects them with `request.POST.getlist("option")` and
  the option count is that list's length (order = row order). The "correct" radios all share one field
  name `answer` whose posted value is the **0-based row index** of the chosen row; `SwitchGateForm`
  is a plain (non-`ModelForm`) form that builds `options` from the sanitized `getlist("option")` and
  stores the radio's integer as `answer`, then `clean` correlates `answer` against the post-sanitize
  options list (in range, exactly one selection) as specified under Error handling. Empty trailing
  rows are ignored before the count check. (A missing `_edit_<form_key>.html` 500s
  `TemplateDoesNotExist` the instant the palette card is clicked — this partial is mandatory.)
- **Enhancer wiring (both files):** `editor.js` re-runs `window.libliInitSwitchGates(preview)` after
  each fragment swap (next to the gallery/tabs/fillgate re-inits), which also re-typesets option math
  in the preview; `editor.html` adds `<script src="…/switchgate.js" defer>` (the step historically
  missed for gallery and reveal-gate, which shipped with a blank preview pane — guarded here by a
  test).
- **Palette:** an "Interactive" group card in `_add_menu.html`, beside the other gates.
- **Transfer:** `SERIALIZERS` (`export.py`), `VALIDATORS` (`payloads.py`), `BUILDERS`
  (`importer.py`) under transfer key `switch_gate`. **`VALIDATORS` must reject** a payload whose
  `options` has fewer than 2 entries, whose `answer` is not an integer in `range(len(options))`, or
  whose `stem` lacks exactly one sentinel — a logically-unopenable gate (valid JSON but unreachable
  `answer`) is a **data-integrity failure the fail-open watchdog does not cover** (with working JS the
  gate simply never opens), so it must be caught at import, not deferred. **Bump `FORMAT_VERSION`**
  (`transfer/schema.py`) by one — **from the current value 3 to 4** (the implementer confirms 3 is
  current before bumping). Back-compat expectation: the new (v4) importer still accepts older exports
  (they simply contain no `switch_gate` elements); older importers reject v4 files — that one-way
  rejection is the reason for the bump. Add the **transfer key** `switch_gate`
  (NOT the type key `switchgateelement`) to `NESTABLE_TYPE_KEYS` (`builder.py`) — its members are
  transfer keys (`reveal_gate`/`fill_gate`, …) and an invariant test asserts
  `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)` (which is keyed by transfer key), so the type key would
  both fail that test and never match at nesting time. Also add `{"switchgate": "switch_gate"}` (form
  key → transfer key) to the module-level `_NESTABLE_FORM_KEY_ALIASES` dict that `resolve_scope`
  consults, mirroring the existing `revealgate`/`fillgate` entries — this is what lets it be added
  inside tabs like the other gates.
- **Taking-view wiring (mandatory — the gate is a total no-op without every item here).** Verifying
  against the shipped fillgate wiring surfaced four taking-page edits that the model/form/transfer
  surface does not cover; each is required for the gate to function on the real lesson page:
  - **`has_reveal_gate` context query** (`courses/views.py`, or wherever the lesson context is built):
    the prepaint `<script>` and pre-hide `<style>` render only `{% if has_reveal_gate %}`, and that
    filter is `content_type__model__in=["revealgateelement","fillgateelement"]`. **Add
    `"switchgateelement"` to that list**, or a switchgate-only unit never pre-hides anything and the
    gate cannot gate — even with working JS.
  - **`has_switch_gate` flag + taking-view `<script>`** (mirroring `has_fill_gate`/`fillgate.js`):
    `fillgate.js` is loaded on the student page via a `{% if has_fill_gate %}<script src="fillgate.js"
    defer>` line in `lesson_unit.html`'s `extra_js`, backed by a `has_fill_gate` context flag. **Add
    an analogous `has_switch_gate` flag in the lesson-context builder and a
    `{% if has_switch_gate %}<script src="…/switchgate.js" defer>` line** — without it `switchgate.js`
    never boots on the lesson page (this is the taking-view analogue of the editor.html script line).
  - **`has_math` detection** (`courses/views.py`): KaTeX/`math.js` load only `{% if has_math %}`, and
    the `has_math` scan has no switchgate clause. **Add a `SwitchGateElement` clause that flags math when
    `has_math_delimiters(stem)` OR any `options` fragment carries delimiters** (math may live in the
    stem alone, an option alone, or both — so the operator is OR, not AND), or a switchgate carrying
    the only math on the page renders raw `\(+\)`.
  - **`reveal.js` `focusTargetIn` branch:** when a cascade reveals and stops at a *following* gate,
    `focusTargetIn` focuses that gate's operable control (fillgate's blank input, a plain gate's
    `<button>`); a switchgate would return the non-focusable `[data-reveal-gate]` container `<div>`,
    dropping keyboard focus on a gate→switchgate chain. **Add a switchgate arm that focuses the
    `[data-switchgate-cycler]` button.**
- **Prepaint watchdog (fail-open wiring — mandatory):** register `window.__switchGateBooted` with the
  `lesson_unit.html` prepaint watchdog **exactly as fillgate registered `__fillGateBooted`**. The
  implementer must confirm whether that watchdog reads a generic set of per-gate boot flags (in which
  case add `__switchGateBooted` to that set) or has a per-gate check (in which case add a sibling
  clause); either way the flag must actually be consulted, or fail-open silently breaks for a dead
  `switchgate.js`. This is a required edit, not an assumption.
- **Student CSS deliverable:** the novel classes `.switchgate__option`, the cycler button, and
  `.switchgate--done` have **no fillgate equivalent**, so "reuses fillgate's idiom" covers only the
  container/feedback styling — add the actual new `.switchgate*` rules to the same stylesheet
  fillgate's rules live in (locate fillgate's CSS and extend it), noting which parts reuse fillgate
  and which are new.
- **Other lockstep touch-points:** `save_element` (`builder.py`); `element_add`/`element_save`
  tuples and `_EDITOR_TYPE_LABELS` (`views_manage.py`); `_ELEMENT_LABELS` + `element_summary`
  (`courses_manage_extras.py`); EN/PL i18n for every new translatable string; a migration for the
  new model.

## Data flow

**Authoring:** teacher adds the element from the Interactive palette group → `element_add` renders
`_host_form.html` → `_edit_switchgate.html` → teacher writes stem, inserts the choice token, adds
options and marks one correct → `element_save` → `SwitchGateForm.clean` sanitizes each option, then
validates (exactly one token in stem, ≥2 non-empty-after-sanitize options, exactly one correct,
`answer` in `range(len(options))`) → `save_element` persists; `save()` re-sanitizes idempotently.

**Taking (JS on):** lesson page server-renders the stem with the cycler (placeholder visible, options
`hidden`), following siblings pre-hidden by `reveal.js`'s prepaint arm → `switchgate.js` boots,
typesets math, arms Confirm → student cycles + confirms → POST `switchgate_check` → `{correct}` →
correct: lock + `libliRevealCascade` reveals next siblings and chains to the next gate; incorrect:
un-hide inline "Try again", retry allowed.

**No-JS fallback:** the `reveal.js` prepaint watchdog disarms the pre-hide (either because `reveal.js`
never armed or because `__switchGateBooted` is falsy), so the whole unit including all following
siblings is visible; the cycler shows only its inert `Choose ▾` placeholder (options and Confirm stay
`hidden`) — inert but harmless, and no content is trapped.

**Transfer:** export writes `{type: "switch_gate", stem, options, answer}`; import validates the
shape (including the `answer`-in-range / ≥2-options / one-sentinel integrity checks above) and
rebuilds the model; the `FORMAT_VERSION` 3→4 bump lets older importers reject the new shape cleanly.

## Error handling

- **Server:** every malformed-but-authorized input to `switchgate_check` (bad/missing/out-of-range
  index, `-1`/placeholder value, unresolved pk) returns `200 {"correct": false}`, never a 500. An
  **access failure** (unenrolled/no-lesson-access user) returns a non-200 (`403`/redirect, matching
  fillgate's guard) — a distinct boundary, both in the test matrix.
- **Form validation:** `SwitchGateForm.clean` sanitizes each option first, then rejects a stem
  without exactly one sentinel token, fewer than 2 options (counting post-sanitize), any option that
  sanitizes to empty, zero or multiple "correct" selections, or an `answer` outside
  `range(len(options))`, with field-level errors. Sanitizing before counting closes the ordering hole
  where an all-script option would pass the count check and then vanish in `save()`.
- **Transfer integrity (C2):** the import `VALIDATORS` independently reject `answer` outside
  `range(len(options))`, fewer than 2 options, or a stem without exactly one sentinel. This is
  essential because the client fail-open watchdog only rescues *dead JS* — a booted `switchgate.js`
  facing an out-of-range `answer` would leave the gate armed and following siblings hidden **forever**
  (no student choice can ever match), so an unopenable gate must be rejected at the data layer, not
  left to the runtime.
- **Client fail-open:** the `__switchGateBooted` flag + `lesson_unit.html` prepaint watchdog
  guarantee content is never left permanently hidden if `switchgate.js` fails to boot. A fetch/JSON
  error during Confirm leaves the gate closed and the widget editable — no content is lost; with the
  page fully server-rendered, the watchdog has already made following content visible.
- **Unsaved preview:** in the builder preview `data-element-pk === "0"`; Confirm is a no-op (no
  endpoint call), so the editor never errors on an unsaved element.
- **Sanitization:** option HTML is sanitized in `clean()` and again in `save()`; unsafe markup cannot
  reach the student template. `stem` render safety is identical to `FillGateElement.stem`.

## Testing

TDD per task. The suite must cover:

- **Model/form:** `save()` sanitizes option HTML; `SwitchGateForm.clean` validation matrix — token
  count (0/1/2 sentinels), option count (post-sanitize <2 rejected), option-that-sanitizes-to-empty
  rejected, exactly-one-correct, `answer` in/out of range.
- **Server endpoint:** `switchgate_check` returns `correct:true` only for the exact stored index;
  `false` for wrong/out-of-range/`-1`-placeholder/missing/non-integer; unsaved/unresolved/**wrong-type**
  pk all `200 {correct:false}` (soft lookup — the deliberate deviation from fillgate's 404);
  **access-denied on a resolved element returns non-200** (distinct from malformed).
- **Transfer integrity:** import `VALIDATORS` reject `answer` out of range, `<2` options, and a stem
  without exactly one sentinel; round-trip export → import preserves `stem`/`options`/`answer`;
  `FORMAT_VERSION` is 4; nestable inside tabs.
- **Authoring render path:** GET **and** POST `manage_element_add` for `switchgate` return 200 — this
  exercises `element_add → _host_form → _edit_switchgate` end-to-end, the path that shipped broken for
  reveal-gate (missing `_edit_` partial, fixed in PR #100) precisely because row/palette tests didn't
  cover it.
- **Editor script wiring:** GET `manage_editor` asserts the `switchgate.js` `<script>` is present in
  `editor.html` (the twice-missed step).
- **Taking-view wiring:** for a unit whose **only** gate/math is a switchgate, GET the lesson page and
  assert (a) the prepaint `<script>`/pre-hide `<style>` render (i.e. `has_reveal_gate` picked up
  `switchgateelement`), (b) the `switchgate.js` `<script>` is present (`has_switch_gate`), and (c)
  KaTeX/`math.js` load when the switchgate stem or an option contains math (`has_math`). These guard
  the four taking-view edits that would otherwise make the gate a silent no-op.
- **e2e behavior matrix** (real UI, real gesture — no `page.evaluate` shortcut): cycle options
  (placeholder → options → wraps back to placeholder) → Confirm wrong → "Try again" + still editable
  → cycle to correct → Confirm → following siblings reveal → chain to the next gate. Assert option
  math is typeset (visible option renders KaTeX, not raw `\(+\)`). Include a no-JS/fail-open assertion
  that following content is visible and the cycler shows only the inert placeholder.

**DoD:** full test suite green; `ruff check` **and** `ruff format --check`; i18n catalog tests if any
translatable strings are removed (none expected — this only adds strings).
