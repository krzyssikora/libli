# "Fill in & confirm" element — design

**Date:** 2026-07-12
**Feature:** Slice 2 of the reveal-gate family (see `docs/superpowers/specs/2026-07-11-reveal-gate-show-more-design.md` for slice 1)
**Status:** Approved, ready for implementation planning

## Purpose

A new **Interactive** content element: a reveal gate whose trigger is a fill-in-the-blank
instead of a plain "Show more" button. The author writes a short stem containing one or more
`{{answer}}` blanks. The student types answers and clicks **Confirm**; when *all* blanks are
correct the inputs lock and restyle as "answered", the Confirm button is removed, and the
existing reveal cascade reveals the following sibling elements within scope. A wrong answer
shows a gentle "Not quite — try again" message, keeps the inputs editable, allows unlimited
retries, and reveals nothing. The element records **no marks/analytics** — it is a
progressive-reveal lesson aid, not an assessed question. It is **nestable inside a Tabs
element** exactly like the plain gate, and is **fail-open** when JavaScript is unavailable.

This is the second member of the reveal-gate family. Slice 1 ("Show more") built the
scope-aware reveal cascade engine (`reveal.js`); this slice reuses that engine and the
fill-blank grading primitives, adding a graded trigger on top.

### Confirmed decisions

- **Grading:** server-side, reusing `courses.marking.blank_matches` (the numeric- and
  whitespace-aware matcher fill-blank already uses) as the single source of truth. Answers
  are never embedded in page source, and there is no duplicated matching logic in JS.
- **On correct:** the input(s) lock, restyle to read as answered/correct (visually distinct
  from surrounding text), the **Confirm button is removed**, then the cascade reveals the
  following siblings. The prompt/stem stays visible so the student can re-read the Q&A.
- **On incorrect:** show "Not quite — try again", keep inputs editable, unlimited retries,
  and mark each wrong blank (per-blank highlighting **ships in this slice**, not optional);
  nothing is revealed until all blanks are correct.
- **Blanks:** one or more per element — the author reuses fill-blank's `{{answer}}` /
  `{{a|b}}` stem authoring verbatim; all blanks must match to pass.
- **Scope:** nestable inside Tabs (cascade scoped to `.slide` / `[data-tab-panel]`), records
  no marks. Consistent with the plain gate.
- **No-JS:** fail-open (everything visible), identical to slice 1.

### Naming

| Namespace        | Value                       |
|------------------|-----------------------------|
| `model_name`     | `fillgateelement`           |
| Concrete model   | `FillGateElement`           |
| Form / editor key| `fillgate`                  |
| Transfer key     | `fill_gate`                 |
| Palette label EN | "Fill in & confirm"         |
| Palette label PL | "Uzupełnij i potwierdź"     |

Three key namespaces mirror the reveal-gate precedent (model_name / form key / transfer key
diverge). The form key `fillgate` is aliased to the transfer key `fill_gate` at exactly one
place (`_NESTABLE_FORM_KEY_ALIASES`), matching how `revealgate` → `reveal_gate` is handled.

## Architecture / components

### Data model & authoring

- New concrete model `FillGateElement(ElementBase)` with two data fields plus the standard
  generic-relation accessor:
  - `stem` — `TextField`, the token-stem in `￿n￿` sentinel form (as produced by
    `fillblank.parse`).
  - `answers` — `JSONField(default=list)`, `list[list[str]]`: the accepted alternatives per
    blank, in order (e.g. `[["colour", "color"], ["2"]]`). `default=list` gives a fresh/unsaved
    instance a sane empty value (not null/`dict`).
  - `elements = GenericRelation(Element)` — **required**, matching `TextElement` / `TabsElement`.
    The `render()` override reads `self.elements`, and this reverse accessor is also what
    cascades the GFK join-row delete when the concrete is deleted (without it, `render()` raises
    `AttributeError` and deleting the concrete orphans its join row).
- Storing accepted answers as a JSON field (rather than mirroring fill-blank's related
  `Blank` rows) keeps the element **self-contained**: fill-blank's `Blank` model is welded to
  the quiz `FillBlankQuestionElement` (FK `related_name="blanks"`), and this element records
  no marks, so a plain JSON field is the simpler, well-bounded choice — one model, one
  migration, no join rows.
- Registered in `ELEMENT_MODELS` (`courses/models.py`).
- **Authoring reuses the fill-blank parser verbatim.** The edit-form partial
  `templates/courses/manage/editor/_edit_fillgate.html` presents one RTE `<textarea
  name="stem">` with the same hint ("Mark each blank with `{{answer}}`. Use `|` for
  alternatives, e.g. `{{colour|color}}`."). The form
  (`FillGateElementForm` in `courses/element_forms.py`, registered in `FORM_FOR_TYPE`):
  - `clean_stem`: `sanitize_html` (the same sanitizer `FillBlankQuestionElementForm.clean_stem`
    uses) → `fillblank.strip_sentinel` → `fillblank.parse()`; store the
    returned token-stem in `stem` and the parsed alternatives list on the instance for
    `answers`. Raise a friendly `ValidationError` on `FillBlankError` (empty/unterminated
    marker, no blanks).
  - `__init__` (edit path): rebuild the author's `{{answer}}` markup via
    `fillblank.to_author_stem(stem, answers)` so the teacher sees `{{answer}}`, not tokens.
- Persistence rides the **generic-else path** in `courses/builder.py:save_element` (like
  reveal-gate), with the form writing both `stem` and `answers`. Because `answers` is not a
  plain form field, the form must set it in `clean`/`save` from the parsed blanks (mirroring
  how `FillBlankQuestionElementForm.clean_stem` stashes `parsed_blanks`).
- **Render override (needed for the join-row pk).** The default `ElementBase.render()`
  (`courses/models.py`) renders with only `{"el": self}` — the concrete instance, no `Element`
  join row — so a generic-path element cannot see its join-row pk. But the fill-gate template
  needs that pk to build `data-check-url` / `data-element-pk` (see Confirm flow). Therefore
  **`FillGateElement` overrides `render()`** to look up its join row
  (`self.elements.order_by("pk").first()`) and pass its pk into the template context, mirroring
  `TabsElement.render()`'s `"eid": join.pk if join else 0`. Fill-gate does **not** use the
  default `ElementBase.render()`. The `else 0` fallback covers an unsaved preview element (no
  join row yet); the template renders `data-element-pk="0"` and `fillgate.js` **no-ops the
  submit when the pk is 0** (see Confirm flow / preview edge).

### Student render & no-JS fallback

- `templates/courses/elements/fillgateelement.html`: a container element carrying
  `data-reveal-gate` (so the shared cascade engine recognises it as a gate boundary — a
  *preceding* gate reveals up to and including it, then stops) **plus a distinguishing
  `data-fillgate` attribute** (see the "grading-bypass" note in Reveal-engine integration),
  wrapping:
  - a `<form>` whose body is rendered by the **existing `{% render_fill_blanks el %}`
    simple-tag** (`courses/templatetags/courses_extras.py`, which already delegates to
    `fillblank.render_inputs(el.stem)` for any `el` with a `.stem`) — do **not** write a bespoke
    render call. It emits `<input type="text" name="blank" class="question__blank-input">` fields
    interleaved with sanitized stem text. **Note:** `render_inputs` hard-codes the quiz-flavoured
    `question__blank-input` class; the fill-gate's own CSS (touch-point 16) must scope/override
    input styling under the `[data-fillgate]` container so the lesson-aid look does not inherit
    unintended quiz styling.
  - **The check URL is NOT the form's `action`.** To keep the form genuinely inert without JS
    (a `hidden` submit button does *not* stop an Enter-key implicit submit), the form's `action`
    is empty/inert; the check URL — built from the Element join-row pk — is stored in a
    `data-check-url` attribute (with the pk also exposed as `data-element-pk`) that **only
    `fillgate.js` reads**. `fillgate.js` reads `data-check-url`/`data-element-pk` (never regexes
    `form.action`) and treats an absent/`0` pk as a no-op (unsaved preview element). A no-JS user
    pressing Enter therefore performs no navigation to the JSON endpoint.
  - a **Confirm** button that ships **`hidden`** and is un-hidden/armed only when `fillgate.js`
    boots (mirroring the plain gate's `<button ... hidden>` pattern) — so a no-JS user never
    sees an actionable Confirm;
  - an empty feedback slot (`data-fillgate-feedback`) for the "try again" message.
- **Blank-to-index invariant:** the *i*-th `input[name="blank"]` in DOM order corresponds to
  `answers[i]` / `blanks[i]`. This holds because `render_inputs` emits the inputs in the
  stem's marker order and `fillblank.parse` produces `answers` in that same order. `fillgate.js`
  relies on this order to map the per-blank result array back onto the inputs.
- **No-JS fallback:** fail-open, identical to slice 1. The render-blocking pre-hide only
  arms `.reveal-armed` when JS boots (and disarms via the DOMContentLoaded watchdog if the
  engine never boots), so without JS everything below the gate is visible and the input group
  is inert/cosmetic. Because the form's `action` is empty/inert (the check URL lives only in
  `data-check-url`) and Confirm ships `hidden`, **neither a click nor an Enter-key press can
  navigate a no-JS user to the JSON endpoint**. No server-side form-POST fallback is needed.

### Confirm flow (server-side check)

- New JSON endpoint: `POST /courses/element/<element_pk>/fillgate-check/`, guarded by
  `require_POST` (a GET → 405). Behavior:
  - **`<element_pk>` is the `Element` join-row pk**, **not** the concrete `FillGateElement` pk.
    The template emits this join-row pk into the form's `data-check-url` / `data-element-pk`
    attributes (not `action` — see Student render) — see the render-override note (the generic
    render path does not expose the pk). This choice also makes the unit resolvable for a nested
    (tab-child) fill-gate, whose concrete model has no direct `unit` field. **Note on URL shape:** the student-side action siblings (`check_answer`, `seen`) are
    `courses/<slug>/u/<node_pk>/...`; `build/element/<pk>` is the *manage* side. This flat
    `courses/element/<pk>/` shape is a **new pattern** that deliberately drops slug/node_pk and
    instead derives the course from `element.unit.course` (below) — not a copy of either
    precedent.
  - Resolution: `element = get_object_or_404(Element, pk=element_pk)`; require
    `element.content_object` to be a `FillGateElement` (else 404); `answers =
    element.content_object.answers`.
  - **Access check:** the lesson consumption view (`lesson_unit`, `courses/views.py`) gates on
    the **course-level** predicate `can_access_course(request.user, node.course)` — there is no
    unit-scoped helper. Because the endpoint URL carries only `element_pk`, derive
    `course = element.unit.course` and call `can_access_course(request.user, course)`, raising
    `PermissionDenied` on failure (matching `lesson_unit` / `seen` / `check_answer`). Use this
    exact helper, **not** the manage/build-side permission. The access-denied test asserts
    against it.
  - Read `request.POST.getlist("blank")`; pad/truncate to `len(answers)`.
  - For each position `i`, `blank_matches(values[i], answers[i])` (from
    `courses.marking`, `case_sensitive=False`).
  - Return `{"correct": all(results), "blanks": results}` as JSON.
- No attempt/mark is recorded — this endpoint only reports correctness.
- New enhancer `courses/static/courses/js/fillgate.js` (`window.libliInitFillGates`,
  idempotent via a `dataset` ready-flag, mirroring `reveal.js`/`tabs.js`/`gallery.js`):
  - Intercepts the form submit (`preventDefault`), POSTs the FormData to the URL from
    `data-check-url` with `X-Requested-With` + `X-CSRFToken`. `fillgate.js` defines its **own
    local** `csrf()` copy following the same cookie-read pattern as `question.js` / `progress.js`
    (each of those defines its own IIFE-local `csrf()` — there is no shared global to reuse): a
    `document.cookie` match on `csrftoken`, which the lesson page already sets. **Not** a
    rendered `{% csrf_token %}` field.
  - If `data-element-pk` is `0` or absent (an unsaved preview element with no join row yet), the
    submit is a **no-op** — the check flow only functions for a saved element; the preview
    re-renders with a real pk after save.
  - **Every submit first resets prior attempt state:** clear all per-blank wrong-markers and
    empty the feedback slot before applying the new result. (With unlimited retries and no page
    reload, failing to reset would leave a stale "wrong" highlight on a blank the student has
    since corrected, or a lingering try-again message.)
  - **On `correct: true`** → (after the reset above) lock every input (readonly/disabled), add a
    "correct" style class, remove the Confirm button, then trigger the shared cascade. Any
    try-again message is already cleared by the reset.
  - **On `correct: false`** → (after the reset above) show the "Not quite — try again" message in
    the feedback slot, mark exactly the currently-wrong blanks (using the per-blank `blanks`
    array), keep inputs editable.
    - **i18n:** the message text must be **server-provided**, not a literal in `fillgate.js`
      — the project has no `JavaScriptCatalog`/`jsi18n` route, so a JS literal cannot be
      translated by the PO workflow (touch-point 17). Pre-render the translated string into the
      fill-gate template as a hidden node / `data-` attribute (e.g. `{% trans "Not quite — try
      again" %}` in a hidden element) that `fillgate.js` reveals, matching how existing
      enhancers surface server-rendered feedback text. PL users then get the PL string.
- Wired into **three** places — miss any one and the feature is dead somewhere:
  1. `editor.js` — re-run `window.libliInitFillGates(preview)` after each fragment swap, next
     to the reveal/gallery/tabs re-inits (authoring preview).
  2. `editor.html` — add `<script src=".../fillgate.js" defer>` (authoring preview), placed
     **after** `reveal.js` (and before `editor.js`): with `defer`, execution follows document
     order, and `fillgate.js` calls `window.libliRevealCascade` from `reveal.js`.
  3. **`lesson_unit.html` — add `<script src=".../fillgate.js" defer>` for the *student*
     consumption page**, gated by a `has_fill_gate` flag. `lesson_unit.html` loads its own
     enhancers (it conditionally loads `reveal.js` behind `has_reveal_gate`); without this the
     Confirm submit is never intercepted and the feature is dead for students. This is the
     "missed twice before" enhancer-wiring mistake — here for the consumption page, not just
     the editor.
- `fillgate.js` depends on `reveal.js` (it calls `window.libliRevealCascade`). Because
  `has_reveal_gate` is generalized to arm on *any* gate (see Pre-hide arming), `reveal.js`
  already loads whenever a fill-gate is present, so load order is satisfied as long as
  `fillgate.js`'s `<script>` follows `reveal.js`'s in `lesson_unit.html`.
- Regression tests: GET `manage_editor` asserts `editor.html` loads `fillgate.js`; GET a
  lesson containing a fill-gate asserts `lesson_unit.html` loads `fillgate.js`.

### Reveal-engine integration (shared cascade refactor)

- Refactor `courses/static/courses/js/reveal.js` to export a pure cascade function, e.g.
  `window.libliRevealCascade(triggerEl, { hideWrapper })`, that performs the sibling-reveal
  (`.reveal-shown` + bubbling `libli:reveal` dispatch), stops at the next gate wrapper, and
  runs focus management — everything the current `reveal()` does *except* the
  hide-the-clicked-wrapper step, which becomes conditional on `hideWrapper`.
  - The **plain "Show more" gate** calls it with `hideWrapper: true` — its current
    self-consume behavior, unchanged. Existing reveal-gate tests must still pass identically.
  - **fillgate.js** calls it with `hideWrapper: false` — the answered Q&A stays visible;
    fillgate.js has already locked the inputs and removed Confirm.
- `isGateWrapper` already keys off `[data-reveal-gate]`, which the fill-gate container
  carries, so "reveal up to and including the next gate, then stop" works uniformly across
  both gate types (a plain gate stops at a fill-gate and vice-versa).
- **Grading-bypass hazard (must fix):** `data-reveal-gate` currently plays *two* roles in
  `reveal.js` — a passive boundary marker (`isGateWrapper`, pre-hide CSS) **and** the selector
  that `initRevealGates`/`initOne` use to attach the plain click-to-reveal handler. If the
  fill-gate container carries `data-reveal-gate` unchanged, `initRevealGates(document)` would
  bind the self-consuming `hideWrapper:true` cascade to it, and a click anywhere inside the
  container (bubbling up from the inputs/Confirm) would reveal all following siblings **with no
  answer check**. Resolution: keep `data-reveal-gate` as the shared *boundary* marker, but
  **narrow the clickable-enhancement selector** in `initRevealGates`/`initOne` so it only
  matches the plain gate button — e.g. `button.reveal-gate[data-reveal-gate]` (the plain gate
  is a `<button>`; the fill-gate is a `<div>`), equivalently `[data-reveal-gate]:not([data-fillgate])`.
  A regression test must assert the fill-gate container receives no plain click handler.
- **Focus onto a fill-gate boundary (must fix):** `reveal()`'s focus step does
  `lastRevealed.querySelector("[data-reveal-gate]").focus()`. For a plain gate that node is a
  focusable `<button>`; for a fill-gate it is the non-focusable container `<div>`, so `.focus()`
  silently no-ops and focus falls through to `<body>`. The refactored cascade must resolve the
  focus target to a focusable node: for a plain gate, the button; for a fill-gate, its first
  `input[name="blank"]` (or give the container `tabindex="-1"` and focus that). Covered by the
  focus/e2e tests.
- One cascade engine, no duplication — consistent with the roadmap's treatment of the
  cascade as the family's shared, load-bearing asset.

### Pre-hide arming

- `has_reveal_gate` in `build_lesson_context` (`courses/views.py`) currently detects only
  `revealgateelement`. **Generalize it to also detect `fillgateelement`** (any gate type), so
  the render-blocking pre-hide arms `.reveal-armed` and `reveal.js` loads for a lesson that
  contains a fill-gate (fill-gate needs the cascade engine).
- Add a **separate `has_fill_gate` flag** (detects `fillgateelement` only) to
  `build_lesson_context`, used solely to gate the `fillgate.js` `<script>` in
  `lesson_unit.html` — so a plain-gate-only lesson does not load the unused enhancer.
- **Both** the generalized `has_reveal_gate` and the new `has_fill_gate` must use the **flat**
  `node.elements.filter(content_type__model=...)` query — **not** scoped to `parent__isnull=True`
  — exactly as the existing `has_reveal_gate` does (with its explanatory comment). Otherwise a
  fill-gate nested inside a Tabs element (which keeps its own `unit` FK but is not top-level)
  would be missed, and neither `reveal.js` nor `fillgate.js` would load for that lesson.

### Math detection (KaTeX loading)

- The fill-gate stem is the **first gate to carry authored rich content that can include math**
  (`fillblank.parse` masks/restores `\(...\)`, and `render_inputs` emits it literally into the
  page). `build_lesson_context`'s `has_math` chain (`courses/views.py`) and its
  `_element_has_math` / `_tabs_has_math` helpers currently have **no `fillgateelement` branch**,
  so a lesson whose only math lives in a fill-gate stem would not load KaTeX and would render
  raw `\(...\)`.
- **Add a fill-gate branch:** `has_math` (top-level chain) checks
  `has_math_delimiters(el.content_object.stem)` for a fill-gate, and `_element_has_math` returns
  the same for a `fillgateelement` so the tabs recursion (`_tabs_has_math`) also catches a
  nested fill-gate. Tests assert `has_math` is set for both a top-level and a nested-in-tab
  fill-gate whose stem contains math.
- The pre-hide CSS selectors in `lesson_unit.html` already target `[data-reveal-gate]`, which
  the fill-gate carries, so no CSS selector change is required for the hide-guard — only the
  Python detection flags need adding/broadening.

### Nesting

- Add `fill_gate` (transfer key) to `NESTABLE_TYPE_KEYS` (`courses/builder.py`) — preserving
  the invariant `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)`.
- Add `"fillgate": "fill_gate"` to `_NESTABLE_FORM_KEY_ALIASES` so the incoming form key is
  translated to the transfer key at the `resolve_scope()` membership check (both call sites
  pass the form key).

## Data flow

1. **Authoring.** Teacher opens the editor, adds a "Fill in & confirm" element from the
   Interactive palette group → `element_add` renders `_host_form` → `_edit_fillgate.html`
   (RTE textarea). On save, `FillGateElementForm.clean_stem` parses the `{{answer}}` markup
   into a token-stem + alternatives list; `save_element` (generic-else) persists `stem` and
   `answers`. Editing re-hydrates `{{answer}}` markup via `to_author_stem`.
2. **Lesson render.** `build_lesson_context` sets `has_reveal_gate` when the unit contains a
   reveal-gate *or* a fill-gate → `lesson_unit.html` arms the render-blocking pre-hide. The
   fill-gate template renders the stem inputs (`render_inputs`) + Confirm inside a
   `data-reveal-gate` container; the following siblings start hidden (pre-hide CSS).
3. **Confirm.** Student fills the input(s), clicks Confirm → `fillgate.js` POSTs the values to
   `/courses/element/<id>/fillgate-check/` → server runs `blank_matches` per blank → returns
   `{correct, blanks}`.
4. **On correct.** `fillgate.js` locks inputs, adds correct styling, removes Confirm, then
   calls `libliRevealCascade(container, { hideWrapper: false })` → following siblings gain
   `.reveal-shown` (cascade stops at the next gate), `libli:reveal` dispatched so nested
   galleries/tabs re-measure, focus moves to the next gate/revealed sibling.
5. **On incorrect.** `fillgate.js` shows "try again", marks wrong blanks, leaves inputs
   editable; nothing is revealed. Student retries.
6. **Transfer.** Export serializes `{stem, answers}` under key `fill_gate`; import rebuilds
   the `FillGateElement`. Nesting inside tabs travels via the existing nestable substrate.

## Error handling

- **Authoring validation:** `fillblank.parse` raises `FillBlankError` on an empty/unterminated
  `{{}}` marker or a stem with no blanks; `clean_stem` converts this to a friendly form
  `ValidationError` (same wording path as fill-blank).
- **Check endpoint:** rejects users without access to the element's unit (403/permission
  check reusing the lesson access path); a non-existent element id → 404. Missing/short
  `blank` list is padded so a truncated POST simply grades as incorrect rather than erroring.
  Empty input for a blank returns `False` from `blank_matches` (never a match).
- **JS resilience:** `fillgate.js` is idempotent (re-init safe in the editor preview) and a
  fetch failure leaves the gate closed with the inputs editable (fail-safe: the student can
  retry; no content is wrongly revealed). With no JS at all, the gate is fail-open — the
  cascade never arms, so all content stays visible.
- **Partial-JS fail-CLOSED trap (must fix).** The pre-hide is armed by `reveal.js`
  (`has_reveal_gate`), but the Confirm button is un-hidden only by the *separate* `fillgate.js`.
  If `reveal.js` boots (arming the pre-hide) but `fillgate.js` fails to load/errors before
  arming, the following siblings stay hidden **and** Confirm stays hidden — a dead,
  unrecoverable gate that `reveal.js`'s own watchdog (which only fires when `reveal.js` never
  boots) does not cover. Resolution: `fillgate.js` sets its own parse-time boot flag
  `window.__fillGateBooted = true`, and the `lesson_unit.html` prepaint watchdog is extended so
  that **when `has_fill_gate` is true it also requires `__fillGateBooted`** before leaving the
  pre-hide armed — otherwise it disarms (fails the gate open), exactly mirroring the
  `__revealBooted` contract. Specify and test the reveal-up/fillgate-down case (content ends up
  visible, not trapped).
- **Cascade refactor safety:** the `reveal.js` change is behavior-preserving for the plain
  gate (`hideWrapper: true` reproduces the current self-consume); the existing reveal-gate
  test suite must pass unchanged, guarding against regression.

## Testing

- **Grading endpoint:** correct answer → `{correct: true}`; wrong → `{correct: false}` with
  per-blank flags; multi-blank (some right, some wrong); numeric equivalence
  (`3,14` == `3.14` == `3.140`); whitespace/case normalization; access denied
  (`can_access_course` false) for a user without course access; 404 for a bad id; **405 for a
  GET** (`require_POST`).
- **Math detection:** `has_math` is set for a lesson whose only math is in a fill-gate stem —
  both top-level and nested-in-tab (so KaTeX loads).
- **Partial-JS fail-open:** with `reveal.js` booted but `fillgate.js` absent/failed, the
  prepaint watchdog disarms the pre-hide and the following content ends up visible (not
  trapped).
- **Authoring render path:** GET/POST `manage_element_add` for `fillgate` returns 200 (drives
  `element_add` → `_host_form` → `_edit_fillgate` — the path missed on slice 1's first cut).
  Round-trip an edit: save `{{answer}}` markup → reopen editor shows `{{answer}}` again.
- **Transfer round-trip:** export → import a fill-gate preserves `stem` + `answers`;
  nested-in-tab fill-gate survives export/import.
- **Pre-hide arming:** a lesson containing a fill-gate sets `has_reveal_gate` (arms
  `.reveal-armed`); a lesson with neither gate does not.
- **Enhancer loaded on both pages:** GET `manage_editor` asserts `editor.html` loads
  `fillgate.js`; GET a lesson containing a fill-gate asserts `lesson_unit.html` loads
  `fillgate.js` (and does not for a lesson without one).
- **No grading bypass (C1):** the fill-gate container gets no plain click-to-reveal handler —
  clicking inside the container without a correct answer reveals nothing (e2e), and the
  narrowed `initRevealGates` selector does not match the fill-gate container (unit/JS test).
- **Cascade focus (I1):** when a preceding plain gate's cascade (or another fill-gate) stops
  at a fill-gate, focus lands on the fill-gate's first `input[name="blank"]`, not `<body>`.
- **Reveal-gate regression:** existing plain-gate cascade tests still pass after the
  `reveal.js` refactor.
- **e2e:** correct answer locks inputs + removes Confirm + reveals the next sibling; wrong
  answer keeps the gate closed and shows try-again with the wrong blank(s) marked; a fill-gate
  acts as a stop boundary for a preceding plain gate's cascade; nested-in-tab fill-gate
  cascades within its panel only.
- **Multi-attempt reset (I2):** on a second submit, per-blank markers reflect only the current
  attempt (a blank wrong on attempt 1 then corrected shows no stale "wrong"); a later
  `correct:true` clears the try-again message.
- **No-JS:** with JS disabled, content below the gate is visible (fail-open); and **pressing
  Enter in a blank does not navigate to the JSON endpoint** (the form has no live `action`).

## Full touch-point checklist (kept in lockstep)

1. `FillGateElement` model (+ `render()` override exposing the join-row pk) + `ELEMENT_MODELS`
   registration + migration (`courses/models.py`).
2. `FillGateElementForm` + `FORM_FOR_TYPE` entry `"fillgate"` (`courses/element_forms.py`).
3. `save_element` generic-else path writes `stem` + `answers` (`courses/builder.py`).
4. `NESTABLE_TYPE_KEYS` += `"fill_gate"` and `_NESTABLE_FORM_KEY_ALIASES` +=
   `{"fillgate": "fill_gate"}` (`courses/builder.py`).
5. Palette card `data-add-type="fillgate"` + `#el-fillgate` SVG symbol
   (`_add_menu.html` + the icon sprite).
6. `element_add` / `element_save` allow-tuples += `"fillgate"` (`courses/views_manage.py`).
7. `_EDITOR_TYPE_LABELS["fillgate"]` (`courses/views_manage.py`).
8. `_ELEMENT_LABELS["fillgateelement"]` + `element_summary` branch
   (`courses/templatetags/courses_manage_extras.py`).
9. Student template `templates/courses/elements/fillgateelement.html`.
10. Edit partial `templates/courses/manage/editor/_edit_fillgate.html`.
11. Transfer trio (`fill_gate`) in export / payloads / importer.
12. `has_reveal_gate` generalized to detect `fillgateelement` **and** a new `has_fill_gate`
    flag (fillgateelement only), both flat-query, in `build_lesson_context`
    (`courses/views.py`); **plus** a `fillgateelement` branch in the `has_math` chain and
    `_element_has_math` (so KaTeX loads for math in a fill-gate stem, top-level and nested).
13. New check endpoint + URL (`POST /courses/element/<element_pk>/fillgate-check/`, `<element_pk>`
    = `Element` join-row pk), reusing the lesson consumption view's student access predicate.
14. `courses/static/courses/js/fillgate.js` + re-init in `editor.js` + `<script>` in
    **both** `editor.html` **and** `lesson_unit.html` (student page, gated on `has_fill_gate`,
    ordered after `reveal.js`).
15. `reveal.js` refactor: export `libliRevealCascade(triggerEl, { hideWrapper })`; plain gate
    switches to it with `hideWrapper: true`; **narrow the click-enhancement selector** in
    `initRevealGates`/`initOne` to the plain gate button only (fill-gate container excluded);
    resolve cascade **focus** to a focusable node (fill-gate → first `input[name="blank"]`).
16. Student + editor CSS for the fill-gate (input group, Confirm button, correct/locked
    state, try-again message) — theme tokens, light + dark verified.
17. i18n EN/PL catalogs for all new strings.

No `FORMAT_VERSION` bump — this is an additive new element type (new transfer key), the
on-disk shape of existing types is unchanged. (Revisit only if plan-review finds a reason.)

## Out of scope

- Slice 3 "Choose & confirm" (dropdown-widget gate + retry UX) — separate later PR.
- The deferred inline reveal stepper.
- Any marks/analytics recording for this element.
- Per-blank "show answer / give up" escape hatch (user chose unlimited retries, no escape).
