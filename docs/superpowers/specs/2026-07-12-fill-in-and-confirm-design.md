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
  optionally highlight the wrong blank(s); nothing is revealed until all blanks are correct.
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

- New concrete model `FillGateElement(ElementBase)` with **two fields**:
  - `stem` — `TextField`, the token-stem in `￿n￿` sentinel form (as produced by
    `fillblank.parse`).
  - `answers` — `JSONField`, `list[list[str]]`: the accepted alternatives per blank, in
    order (e.g. `[["colour", "color"], ["2"]]`).
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
  - `clean_stem`: sanitize → `fillblank.strip_sentinel` → `fillblank.parse()`; store the
    returned token-stem in `stem` and the parsed alternatives list on the instance for
    `answers`. Raise a friendly `ValidationError` on `FillBlankError` (empty/unterminated
    marker, no blanks).
  - `__init__` (edit path): rebuild the author's `{{answer}}` markup via
    `fillblank.to_author_stem(stem, answers)` so the teacher sees `{{answer}}`, not tokens.
- Persistence rides the **generic-else path** in `courses/builder.py:save_element` (like
  reveal-gate), with the form writing both `stem` and `answers`. Because `answers` is not a
  plain form field, the form must set it in `clean`/`save` from the parsed blanks (mirroring
  how `FillBlankQuestionElementForm.clean_stem` stashes `parsed_blanks`).

### Student render & no-JS fallback

- `templates/courses/elements/fillgateelement.html`: a container element carrying
  `data-reveal-gate` (so the shared cascade engine recognises it as a gate boundary — a
  *preceding* gate reveals up to and including it, then stops), wrapping:
  - a `<form>` whose body is `fillblank.render_inputs(el.stem)` — the same server-built
    `<input type="text" name="blank">` fields interleaved with sanitized stem text that
    fill-blank emits;
  - a **Confirm** submit button;
  - an empty feedback slot (`data-fillgate-feedback`) for the "try again" message.
- **No-JS fallback:** fail-open, identical to slice 1. The render-blocking pre-hide only
  arms `.reveal-armed` when JS boots (and disarms via the DOMContentLoaded watchdog if the
  engine never boots), so without JS everything below the gate is visible and the input group
  is inert/cosmetic. No server-side form-POST fallback is needed.

### Confirm flow (server-side check)

- New JSON endpoint: `POST /courses/element/<id>/fillgate-check/`, permission-checked against
  the unit's access (reuse existing lesson/consumption access checks). Behavior:
  - Load the `FillGateElement` by id; verify the requesting user can access its unit.
  - Read `request.POST.getlist("blank")`; pad/truncate to `len(el.answers)`.
  - For each position `i`, `blank_matches(values[i], el.answers[i])` (from
    `courses.marking`, `case_sensitive=False`).
  - Return `{"correct": all(results), "blanks": results}` as JSON.
- No attempt/mark is recorded — this endpoint only reports correctness.
- New enhancer `courses/static/courses/js/fillgate.js` (`window.libliInitFillGates`,
  idempotent via a `dataset` ready-flag, mirroring `reveal.js`/`tabs.js`/`gallery.js`):
  - Intercepts the form submit (`preventDefault`), POSTs the FormData to the element's
    check URL with `X-Requested-With` + `X-CSRFToken`.
  - **On `correct: true`** → lock every input (readonly/disabled), add a "correct" style
    class, remove the Confirm button, then trigger the shared cascade.
  - **On `correct: false`** → render "Not quite — try again" in the feedback slot, mark the
    wrong blanks (using the per-blank `blanks` array), keep inputs editable.
- Wired into **both** `editor.js` (re-run `window.libliInitFillGates(preview)` after each
  fragment swap, next to the reveal/gallery/tabs re-inits) **and** `editor.html` (add
  `<script src=".../fillgate.js" defer>`). This is the step missed twice before (gallery,
  reveal-gate); a regression test asserts `editor.html` loads `fillgate.js`.

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
- One cascade engine, no duplication — consistent with the roadmap's treatment of the
  cascade as the family's shared, load-bearing asset.

### Pre-hide arming

- `has_reveal_gate` in `build_lesson_context` (`courses/views.py`) currently detects only
  `revealgateelement`. **Generalize it to also detect `fillgateelement`** (any gate type), so
  the render-blocking pre-hide arms `.reveal-armed` for a lesson that contains a fill-gate.
- The pre-hide CSS selectors in `lesson_unit.html` already target `[data-reveal-gate]`, which
  the fill-gate carries, so no CSS selector change is required for the hide-guard — only the
  Python detection flag needs to broaden.

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
- **Cascade refactor safety:** the `reveal.js` change is behavior-preserving for the plain
  gate (`hideWrapper: true` reproduces the current self-consume); the existing reveal-gate
  test suite must pass unchanged, guarding against regression.

## Testing

- **Grading endpoint:** correct answer → `{correct: true}`; wrong → `{correct: false}` with
  per-blank flags; multi-blank (some right, some wrong); numeric equivalence
  (`3,14` == `3.14` == `3.140`); whitespace/case normalization; access denied for a user
  without unit access; 404 for a bad id.
- **Authoring render path:** GET/POST `manage_element_add` for `fillgate` returns 200 (drives
  `element_add` → `_host_form` → `_edit_fillgate` — the path missed on slice 1's first cut).
  Round-trip an edit: save `{{answer}}` markup → reopen editor shows `{{answer}}` again.
- **Transfer round-trip:** export → import a fill-gate preserves `stem` + `answers`;
  nested-in-tab fill-gate survives export/import.
- **Pre-hide arming:** a lesson containing a fill-gate sets `has_reveal_gate` (arms
  `.reveal-armed`); a lesson with neither gate does not.
- **Editor loads enhancer:** GET `manage_editor` asserts `fillgate.js` is present.
- **Reveal-gate regression:** existing plain-gate cascade tests still pass after the
  `reveal.js` refactor.
- **e2e:** correct answer locks inputs + removes Confirm + reveals the next sibling; wrong
  answer keeps the gate closed and shows try-again; a fill-gate acts as a stop boundary for a
  preceding plain gate's cascade; nested-in-tab fill-gate cascades within its panel only.
- **No-JS:** with JS disabled, content below the gate is visible (fail-open).

## Full touch-point checklist (kept in lockstep)

1. `FillGateElement` model + `ELEMENT_MODELS` registration + migration (`courses/models.py`).
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
12. `has_reveal_gate` generalized to also detect `fillgateelement` (`courses/views.py`).
13. New check endpoint + URL (`POST /courses/element/<id>/fillgate-check/`).
14. `courses/static/courses/js/fillgate.js` + re-init in `editor.js` + `<script>` in
    `editor.html`.
15. `reveal.js` refactor to export `libliRevealCascade(triggerEl, { hideWrapper })`; plain
    gate switches to it with `hideWrapper: true`.
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
