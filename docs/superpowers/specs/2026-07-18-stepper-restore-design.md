# Step-by-step stepper restore

Bring the **Step-by-step** stepper element onto the per-student practice-state
substrate so a returning student sees the stepper at the same reveal depth they
walked it to, surviving a page reload. This is the last **ungraded** interactive
element still missing restore; the graded self-checks shipped in PR #150, the
reveal/fill/switch gates in PR #140/#147.

## Purpose

The stepper (`StepperElement`) is a lesson-only progressive-reveal widget: an
ordered list of short inline fragments on one line, with step 0 visible and a
walking "Show next" button that reveals the rest one at a time, then disappears.
Today it persists nothing — a reload snaps it back to "only step 0 shown," so any
walking the student did is lost. The broader practice-state initiative
(`[[student-practice-state-status]]`) exists precisely because ephemerality
destroys student work; the stepper is the final ungraded element to fold in.

**Success criterion:** a student who has clicked "Show next" N−1 times (revealing
N steps) returns after a reload to find the first N steps already shown and the
button in the correct state (hidden iff all steps are shown), driven by their own
persisted state and nothing else.

**Non-goals:**

- Anything graded (already shipped in PR #150).
- Slice 3 (lesson-mode question answers) — a separate mechanism, its own spec.
- Any change to the shared `state.js` / `window.libliState` helper.
- Reveal-gate-style cross-sibling cascade. The stepper reveals only its **own**
  `[data-stepper-step]` children inside `.stepper`; there is no cross-scope
  leakage and none of the reveal gate's per-scope prefix-closure applies.

## Architecture / components

Four small, well-bounded changes. The merged substrate (PR #140/#150) already
does the heavy lifting: `StepperElement` uses the default `ElementBase.render`,
so its template context already carries `eid`, `mine`, `mine_json`, `slug`,
`node_pk` (`courses/models.py` `_state_context`) — the stepper template simply
does not consume them yet.

### 1. Validator — `courses/state.py`

A new `_val_stepper(element, obj, payload)` registered under the content-type key
`"stepperelement"` (the `ELEMENT_MODELS` namespace — **not** the form key
`stepper`, not the transfer key; the three-namespace trap). The blob shape is a
**count**, `{"shown": N}`, where N is the number of steps revealed (a fresh
stepper is N=1: step 0 is always visible). It is the first non-flag (count-valued)
blob in the registry; the existing `_val_open_gate` / `_val_markdone` are
flag/list shaped.

```python
def _val_stepper(element, obj, payload):
    if not isinstance(payload, dict):
        return REJECT
    n = _int_or_none(payload.get("shown"))
    if n is None:
        return REJECT                       # malformed -> preserve prior good state
    n = min(n, obj.steps.count())           # author trimmed steps -> clamp, self-heal
    return {"shown": n} if n >= 2 else EMPTY  # N<2 == only step 0 == nothing to restore
```

Semantics, consistent with the existing validators' REJECT/EMPTY contract:

- Non-dict payload → `REJECT` (leave any stored key untouched).
- `shown` absent or non-integer → `REJECT` (malformed; never silently wipe prior
  good state).
- `shown` clamped to `[−∞, obj.steps.count()]`, then: clamped value `≥ 2` →
  store `{"shown": n}`; clamped value `< 2` → `EMPTY` (drop the key — only step 0
  would show, which is the default render, so there is nothing to restore).

The clamp is what makes restore **self-heal** when an author later edits the
stepper: reducing the step count clamps a too-large stored N down to the new
total (all steps shown, button hidden); adding steps leaves the student mid-walk
with the button available to continue.

The blob is **monotone forward** — the button only ever walks open — so the save
path is fire-and-forget with no adopt/revert and no server-echo handling, exactly
like the gates.

### 2. Template — `templates/courses/elements/stepperelement.html`

Emit the three practice-state attributes on the existing `.stepper` wrapper (the
element that already carries `data-stepper`), using the same
`{% url ... as save_url %}` pattern the reveal gate uses. No structural change; the
context variables are already present.

```django
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<div class="stepper" data-stepper
     data-element-pk="{{ eid }}" data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
```

`data-element-pk` is the established attribute name (the join-row pk `eid`), **not**
`data-element-id` (which is progress.js's seen-tracker). `data-state` is
`mine_json` — pre-serialized JSON from Python (no `|safe`, no JSON template
filter). In the authoring editor preview the context lacks `slug`/`node_pk`, so
`save_url` resolves to `""` — the inertness lever (see Error handling).

### 3. Client — `courses/static/courses/js/stepper.js`

`initOne(root)` reads the persisted count and reveals that many steps at boot
instead of only step 0; the "Show next" click handler saves the new count via the
merged shared helper. Restore is **read-only** — booting never POSTs.

- **Read (restore):** parse `root.dataset.state` (tiny inline `JSON.parse` in a
  `try`), read `.shown`, clamp to `[1, steps.length]`. The shared reader
  `window.libliState.storedFlag(el, key)` is hardcoded to `blob[key] === true`
  (built for the `{open:true}`/`{done:true}` flags) and cannot read a count, so
  the stepper reads its own count inline. `state.js` is **not** modified.
- **Reveal:** add `stepper-shown` to the first `shown` steps (was: step 0 only);
  add `is-stepping` to the wrapper as today; `btn.hidden = shown >= steps.length`.
- **Save:** in the existing click handler, after revealing the next step, compute
  the new shown-count and call
  `window.libliState.saveFlag(root, { shown: newCount })`. `saveFlag` is generic
  (its `stateObj` is arbitrary), POSTs `{element: eid, state: {shown: N}}` to
  `root.dataset.stateUrl`, is fire-and-forget with `keepalive`, and no-ops when
  the URL or pk is empty. No duplication of csrf/fetch is introduced.

The idempotency guard (`root.dataset.stepperReady`), the button-walk loop, the
`tabindex`/`focus` handling, and the `steps.length < 2` early-out are preserved.

### 4. Registry wiring

Add `"stepperelement": _val_stepper` to `VALIDATORS` in `courses/state.py`. No
route, view, or model migration change — `element_state_save` and
`UnitProgress.element_state` already store an opaque per-element blob keyed by the
join-row pk.

## Data flow

**Save (student walks the stepper):**

1. Student clicks "Show next"; `stepper.js` reveals the next step and computes the
   new shown-count K.
2. `window.libliState.saveFlag(root, {shown: K})` POSTs
   `{element: eid, state: {shown: K}}` to `element_state_save`.
3. The view calls `validate_state(element, obj, {shown: K})` →
   `_val_stepper` clamps and returns `{shown: K}` (or EMPTY/REJECT).
4. `{shown: K}` is stored in `UnitProgress.element_state[eid]`. Fire-and-forget;
   the echo is ignored.

**Restore (student reloads):**

1. Lesson view seeds `element_state` (str-keyed) into the render context;
   `_state_context` computes `mine = {shown: K}` for this element and
   `mine_json = "{\"shown\": K}"`.
2. The template renders `data-state="{"shown": K}"` on `.stepper`. Steps are
   server-rendered as plain text (no `stepper-shown`, no `hidden` attr — the
   no-JS invariant is preserved).
3. `stepper.js initOne` parses `data-state`, clamps K to `[1, steps.length]`,
   reveals the first K steps, sets `is-stepping`, and hides the button iff
   `K >= steps.length`.

**Math:** the step fragments are server-rendered text already typeset in place at
page boot — `.stepper` is in `math.js`'s inline-render allowlist, and KaTeX
typesets each `\(...\)`/`\[...\]` fragment whether the step is CSS-hidden or shown.
Restore only toggles the `stepper-shown` class; it never creates nodes, so no
re-typeset is needed (unlike switchgate, whose math is JS-built).

**Reset ("Start fresh"):** already handled generically by slice 1 —
`progress_reset` wipes `element_state` at any outline level, dropping the
stepper's blob with everything else. No new work.

## Error handling

- **REJECT vs EMPTY** (the substrate's data-loss guard): a malformed payload
  (non-dict, or non-integer `shown`) returns `REJECT` and leaves the stored blob
  untouched — a garbage POST never wipes a student's good state. A well-formed
  "nothing to restore" (clamped N < 2) returns `EMPTY` and drops the key. These
  are deliberately distinct sentinels.
- **Author edits after the fact:** the `min(n, obj.steps.count())` clamp
  self-heals a stored N that now exceeds the step count; the student simply sees
  all steps and no button. A stored N below the new count leaves the button
  present to continue.
- **Read-side fail-open:** `_state_context` already coerces a non-dict `mine` to
  `{}` (renders fresh, never 500). `stepper.js` wraps the `JSON.parse` in a
  `try` and defaults `shown = 1` on any parse failure, so a corrupt `data-state`
  degrades to the default render, never a JS throw that traps the widget.
- **Editor-preview inertness:** the preview passes real join rows but no
  `slug`/`node_pk`, so `save_url` is `""`; `saveFlag` no-ops on an empty URL, and
  a preview "Show next" click POSTs nothing. `editor.html` must load `state.js`
  (it already does — PR #150 added it after the shared-global extraction broke the
  editor preview) so `window.libliState` exists when `stepper.js` runs there.
- **JS off / blocked:** unchanged from today — the lesson-only render-blocking
  `stepper-armed` style plus the `__stepperBooted` DOMContentLoaded watchdog fail
  open (all steps show) if `stepper.js` never boots. Restore adds no new hard-hide
  path; the server still never renders a step with a `hidden` attribute.
- **No new user-facing strings:** the validator returns sentinels/dicts and adds
  no `gettext` messages, so the project-wide PO-catalog fuzzy gotcha does not
  apply to this slice.

## Testing

Falsifiability is the governing doctrine (`[[falsify-tests-not-run-them]]`): every
guard test must be shown to go RED when its guard is removed, not merely pass.

- **Validator units** (`courses/state.py`): non-dict → `REJECT`; non-integer
  `shown` → `REJECT`; `shown` clamped to `obj.steps.count()` (a stored value
  above the count stores the count, not the input — falsify by deleting the clamp
  and watching the `N > total` case go red); clamped `< 2` → `EMPTY`; happy path
  → `{"shown": n}`.
- **Render** through the **lesson view** (str-keyed `UnitProgress` seed — never
  bare `obj.render()` with an int key; the int/str-key seam has bitten prior
  slices): assert `.stepper` emits `data-element-pk`, `data-state-url`, and a
  `data-state` carrying the stored `{"shown": N}`.
- **e2e** (`-m e2e`, real browser, real click path per `[[e2e-must-drive-real-ui]]`
  — never `page.evaluate`): walk two "Show next" clicks, reload, assert the first
  three steps are visible and the button state is correct. Falsify by confirming
  that without the restore code the reload shows only step 0.
- **Editor-preview inertness e2e:** a preview "Show next" click sends no request
  (`save_url` is `""`); assert no POST and no page error (the shared-global
  regression class from PR #150).
- **DoD:** run the non-e2e suite with `-n auto` (the serial suite exceeds a
  subagent's stream watchdog); the targeted e2e file foreground with explicit
  `-m e2e` (never a background/whole-suite `-m e2e` run → runaway browsers);
  `ruff check`, `ruff format --check`, `manage.py makemigrations --check`,
  `manage.py check`, and the PO-catalog fuzzy-free check all clean.
