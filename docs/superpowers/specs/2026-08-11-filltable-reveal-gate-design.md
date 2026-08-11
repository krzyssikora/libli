# Fill-in table as a reveal gate

## Purpose

A `FillTableElement` today is a dead end. It checks its cells server-side, paints them
correct/incorrect, locks itself on all-correct and persists `{done: true}` — and then nothing
happens. Its docstring says so outright: *"records no marks, reveals nothing."*

That leaves one authoring shape unbuildable: **fill in the table correctly, and only then see what
comes next.** It is the native shape of a large part of the imported LAL corpus, where a static page
would hide a `div.success` (usually holding GeoGebra applets) until a JS answer-check unhid it. The
motivating case is `mat-pp` unit 322 (`kwadratowa_010_parabola.html`): two tables of \(y\) values,
then two GeoGebra applets that appeared only once both tables were right. The tables ported over as
two `FillTableElement`s; the gating did not port at all, because the platform has no way to express
it.

The platform *does* already have the revealing half. `reveal.js` implements a general cascade —
reveal every following sibling within a scope, stop at the next gate, persist, restore on reload —
and three element types opt into it:

| Gate | Trigger | Marker attribute |
|---|---|---|
| `RevealGateElement` | a "Show more" button | `[data-reveal-gate]` |
| `FillGateElement` | fill-in blanks, server-checked | `[data-reveal-gate][data-fillgate]` |
| `SwitchGateElement` | a cycling "Choose ▾" widget | `[data-reveal-gate][data-switchgate]` |

This design makes `FillTableElement` an **optional** fourth member of that family, controlled by a
per-instance author checkbox. An ungated fill-table keeps its current behaviour byte for byte.

### Goals

- An author can tick one checkbox on a fill-table so that solving it reveals the following siblings.
- Two gating tables in sequence chain correctly: the first reveals the second, the second reveals
  what follows it.
- A student who solved a table *before* the author ticked the checkbox is not locked out of the
  revealed content.
- No database migration, and no `FORMAT_VERSION` bump.

### Non-goals

- **No new element type.** This is a flag on the existing one, not a `FillTableGateElement`.
- **No multi-table gate group.** "These three tables jointly unlock X" is not expressible; chaining
  gates is the supported composition.
- **No LAL-loader change.** The importer will not auto-detect a `div.success` and set `gate`.
  Authors tick the box. (A later slice could revisit this once the flag exists.)
- **No change to marking or the gradebook.** A fill-table records no marks, gated or not.

## Architecture / components

Nine touch points. Each is small; the design's weight is in getting the restore seam and the
page-level wiring right, not in volume of code.

### 1. The flag lives in `data`, not in a new column

`gate` becomes a key in the `data` JSONField, alongside the settings already there — `header_row`,
`header_col`, `case_sensitive`, `border`, `prompt`:

```python
# FillTableElement.normalize_data
return {
    "header_row": bool(data.get("header_row")),
    "header_col": bool(data.get("header_col")),
    "case_sensitive": bool(data.get("case_sensitive")),
    "gate": bool(data.get("gate")),          # new
    "border": ...,
    "prompt": ...,
    "cells": cells,
}
```

This is the decision the rest of the design hangs off, and it is worth stating why:

- **No migration.** No new column, so no `0059`, and nothing to backfill.
- **No `FORMAT_VERSION` bump.** `_ser_fill_table` opens with `normalize_data` and `_build_fill_table`
  closes with it, so import already carries any key the normalizer emits. Export needs exactly one
  added line. `FORMAT_VERSION` is at 11 on master; leaving it alone also sidesteps the standing
  hazard that two branches bumping to the same integer merge without a conflict.
- **Graceful cross-version behaviour.** `_val_fill_table` is deliberately lenient — no `_exact_keys`
  call — so an older libli importing a newer bundle sees an unknown `gate` key, ignores it, and its
  `normalize_data` drops it. The table imports as a plain ungated fill-table. Content, not crash.
- **Legacy rows read false.** A row stored before this change has no `gate` key; `bool(None)` is
  `False` and `data__gate=True` does not match it. Ungated, as it should be.

`_sanitized_data` (called from `save()`) needs no change — it walks cells and `prompt` only, and
passes unknown top-level keys through untouched.

### 2. Template — the gate marker

`templates/courses/elements/filltableelement.html`, on the root `.filltable` div:

```html
<div class="filltable" data-filltable
     {% if data.gate %}data-reveal-gate data-filltablegate{% endif %}
     data-element-pk="{{ eid }}" ...>
```

`data-reveal-gate` is the family barrier `reveal.js` scans for; `data-filltablegate` is the
family discriminator, mirroring `data-fillgate` / `data-switchgate`.

The root `.filltable` div is already the outermost node the element renders, so it lands as a direct
child of the container's child-wrapper (`.callout__child`, `.tabs__child`, `.spoiler__child`,
`.ba__child`, or a slide's `.lesson-block__body`). That is what the pre-hide CSS's
`:has(> [data-reveal-gate])` requires. **No CSS change is needed** — the existing rules in
`lesson_unit.html` match on the attribute generically across all five scopes.

### 3. Render — the `done` → `open` seam

This is the one genuinely subtle part.

`reveal.js` decides whether a stored gate is already open with a strict shape test:

```js
return !!(blob && blob.open === true);   // storedOpen()
```

A fill-table stores `{done: true}`. Its restore path (`mine.done`) already swaps in
`canonical_cells` and renders every answer cell readonly with its canonical value.

Left alone, that mismatch produces a silent, permanent failure: a student who completed a table
*before* the author ticked the checkbox has `{done: true}` in state. Once the table renders
`data-reveal-gate`, `restoreGates` finds `open` missing, treats the gate as unanswered, and applies
prefix-closure — `break` — leaving the revealed content hidden **forever**, with the table itself
displayed as solved and locked. The student sees a finished task and no way forward.

Fixed at render time, so no data migration and no backfill are needed. In `FillTableElement.render`,
when the element is a gate and `mine.done` is set, derive `open`:

```python
ctx = self._state_context(element, state, slug, node_pk)
nd = self.normalize_data(self.data)
if nd["gate"] and ctx["mine"].get("done"):
    # Shallow COPY, never in-place: _state_context's `mine` is a reference into
    # the caller's state blob, and mutating it would leak `open` into every other
    # reader of that blob for the rest of the request.
    ctx["mine"] = {**ctx["mine"], "open": True}
    ctx["mine_json"] = json.dumps(ctx["mine"])
```

The copy is load-bearing, for the same reason the existing `render` already comments that it
shallow-copies rather than assigning into `self.data`.

After this, old blobs (`{done: true}`) and new ones (`{done: true, open: true}`) are indistinguishable
to `reveal.js`, and the two write paths converge.

### 4. `filltable.js` — call the cascade

The all-correct branch currently locks and saves. It gains the cascade call and a gate-aware state
shape:

```js
if (data.all_correct === true && (data.cells || []).length > 0) {
  lock(root);
  var gate = root.hasAttribute("data-reveal-gate");
  if (gate && window.libliRevealCascade) {
    window.libliRevealCascade(root, { hideWrapper: false });
  }
  window.libliState.saveFlag(root, gate ? { done: true, open: true } : { done: true });
}
```

- `hideWrapper: false` matches `fillgate.js` — the solved table stays on screen with its green cells
  rather than being consumed, which is right for a gate whose content *is* the student's work.
- The `window.libliRevealCascade` guard covers the editor preview, where the pane may render a gating
  table without a live cascade.
- An **ungated** table keeps writing exactly `{done: true}`, so no existing stored state changes shape.

`filltable.js` also gains a parse-time boot flag, mirroring `__fillGateBooted` / `__switchGateBooted`:

```js
window.__fillTableBooted = true;
```

`initOne`'s existing early return for a stored `done` flag needs no change: restore of the *cascade*
is `reveal.js`'s job (`restoreGates` runs independently off `data-state`), and restore of the
*table's own* locked appearance is already server-rendered.

### 5. `reveal.js` — focus target for a chained gate

`focusTargetIn()` resolves a focusable node inside a gate wrapper; a `<div>` is not focusable, so each
non-button family needs a branch. Add the fill-table's, alongside the existing two:

```js
if (gate.matches("[data-filltablegate]")) {
  return gate.querySelector(".filltable__input");
}
```

This only matters in the adjacent-gate case — when one gating table is immediately followed by
another — which is exactly unit 322's shape. Without it a keyboard user lands on a wrapper `<div>`
instead of the next table's first cell.

No other `reveal.js` change is required. `scopeOf`, `isGateWrapper` and `cascadeFrom` all key on
`[data-reveal-gate]` generically. `restoreGates` already computes `hideWrapper` as
`gate.matches(RESTORABLE)`, and `RESTORABLE` is `button.reveal-gate[data-reveal-gate]` — a fill-table
is not a button, so it correctly restores with `hideWrapper: false`.

### 6. `views.py` — page-level detection

`has_reveal_gate` currently keys on *model name*, which cannot express a per-instance flag. It needs a
second term:

```python
has_filltable_gate = FillTableElement.objects.filter(
    elements__unit=node, data__gate=True
).exists()
has_reveal_gate = (
    node.elements.filter(content_type__model__in=[...]).exists() or has_filltable_gate
)
```

This is not cosmetic. `reveal.js` itself is loaded only under `{% if has_reveal_gate %}`
(`lesson_unit.html:89`), so on a unit whose only gate is a fill-table, **omitting this term means the
cascade engine never loads at all** and the gate silently does nothing.

The query goes through the `elements` GenericRelation and is deliberately *not* scoped to
`parent__isnull=True`, matching the existing comment on `has_reveal_gate`: a gate nested inside a tab
or callout keeps its own `unit` FK and must still be found. Unit 322's tables are callout children,
so this is exercised immediately.

`has_fill_table` (which loads `filltable.js`) is unchanged and already true whenever a gating table
exists.

### 7. `lesson_unit.html` — the prepaint watchdog

The prepaint block arms `.reveal-armed` to hide gated content before first paint, and disarms it at
`DOMContentLoaded` if the engine did not boot — so a blocked or broken script fails *open* rather than
trapping content permanently invisible. A new gate family means a new boot flag to check:

```
if (!window.__revealBooted
    {% if has_fill_gate %} || !window.__fillGateBooted{% endif %}
    {% if has_switch_gate %} || !window.__switchGateBooted{% endif %}
    {% if has_filltable_gate %} || !window.__fillTableBooted{% endif %}) {
```

`has_filltable_gate` is added to the template context for this. The script-loading block needs no
change: `filltable.js` already loads under `has_fill_table`, and `reveal.js` now loads because
`has_reveal_gate` includes gating tables.

Load order is already correct — `reveal.js` at line 89, `filltable.js` at line 93, both `defer`, so
`libliRevealCascade` is defined before any check can resolve.

### 8. Editor — one checkbox

`case_sensitive` is the exact precedent: a `data`-borne boolean edited by a checkbox that
`filltable_editor.js` reads and folds into the serialized blob. Four touches, same shape:

| File | Site | Change |
|---|---|---|
| `_edit_filltable.html` | beside the Case-sensitive label | `<label><input type="checkbox" data-gate ...> {% trans "…" %}</label>`, checked from `d.gate` |
| `filltable_editor.js` | the control-lookup block | `var gate = editor.querySelector("[data-gate]");` |
| `filltable_editor.js` | the `serialize` literal | `gate: !!(gate && gate.checked),` |
| `filltable_editor.js` | the listener block | `if (gate) gate.addEventListener("change", serialize);` |

`FillTableElementForm` needs **no change**: its only field is `data`, and `clean_data` returns
`normalize_data(...)`, which now carries `gate` through.

The label needs an English source string and a Polish translation, which means `makemessages` plus a
`.mo` rebuild. Proposed English: *"Reveal what follows when all cells are correct"*.

### 9. Transfer — one line

`_ser_fill_table` returns an explicit key literal; add `gate`:

```python
return {
    "header_row": data["header_row"],
    "header_col": data["header_col"],
    "case_sensitive": data["case_sensitive"],
    "gate": data["gate"],          # new
    ...
}
```

The importer needs nothing — `_build_fill_table` ends with
`FillTableElement(data=FillTableElement.normalize_data(data))`, and the normalizer supplies `gate`
(defaulting to `False` for a legacy bundle that lacks the key). `_val_fill_table` needs nothing: it
checks only gross structural corruption and does no exact-keys check.

## Data flow

**Authoring.** Author ticks the checkbox → `filltable_editor.js` serializes `gate: true` into the
posted `data` blob → `FillTableElementForm.clean_data` runs it through `normalize_data` → saved.

**Page load (unattempted).** `views.lesson_unit` computes `has_filltable_gate` → true, so
`has_reveal_gate` is true → prepaint arms `.reveal-armed`, hiding every `.callout__child` following
the one that `:has(> [data-reveal-gate])` → `reveal.js` and `filltable.js` both load → `restoreGates`
finds `data-state` without `open` and stops at this gate → content stays hidden. `filltable.js` arms
Check.

**Correct answer.** Student fills the cells, clicks Check → `filltable_check` returns
`all_correct: true` → `paint`, `summarize`, `lock` → `libliRevealCascade(root, {hideWrapper: false})`
reveals following siblings within the scope, stopping after the next gate wrapper, dispatching
`libli:reveal` on each so nested enhancers can re-measure → `saveFlag({done: true, open: true})`.

**Wrong answer.** Cells painted, retry message shown, no cascade, no state write. Unlimited retries.

**Reload after success.** `render` sees `mine.done` → swaps in `canonical_cells` (readonly, locked)
*and* injects `open: true` into `data-state` → `restoreGates` reads `open === true` → replays the
cascade with `focus: false` → content visible, no scroll jump.

**Chained tables (unit 322).** Table 1's cascade reveals the intervening text and table 2, then stops
because table 2's wrapper is itself a gate wrapper. Table 2's cascade reveals the success text and
both applet iframes, then runs to the end of the callout's children.

## Error handling

| Situation | Behaviour |
|---|---|
| Student solved the table before the author ticked the box | Render derives `open` from `done`; cascade restores. No lockout, no data migration. |
| `reveal.js` blocked (extension, CSP, network) | `__revealBooted` falsy at `DOMContentLoaded` → watchdog disarms `.reveal-armed` → everything visible. Fail open. |
| `filltable.js` blocked | `__fillTableBooted` falsy → same disarm. Fail open. Content visible but ungated — the correct failure direction. |
| Check request fails | Existing `.catch` leaves the widget interactive; no cascade, no state write. |
| State POST fails | Fire-and-forget with `keepalive`; the DOM stays revealed for this session and the student re-earns it next load. Monotone, matching every other gate. |
| Drifted / unparseable `data-state` | `storedOpen`'s `try/catch` returns false → the gate stays live and re-answerable. |
| Element with `gate: true` and **no** answer cells | Cannot be authored: `FillTableElementForm.clean_data` already rejects a table with no answer cells. `filltable.js` additionally requires `cells.length > 0` before treating a response as all-correct. |
| Legacy bundle imported (no `gate` key) | `normalize_data` supplies `False`. Ungated. |
| Newer bundle imported by older libli | Unknown key ignored by the lenient validator, dropped by the old normalizer. Ungated, not an error. |
| Gating table with nothing after it in scope | `cascadeFrom` reveals nothing and falls back to focusing the scope. Harmless. |
| Editor preview | `data-state-url` is `""` so `saveFlag` no-ops; `libliRevealCascade` is guarded and `reveal.js` loads unconditionally in the editor anyway. |

## Testing

Every test below must be **falsified before it is trusted** — introduce the named mutant, confirm
RED, then remove the mutant by editing it out (never by `git checkout`, which would discard the test
alongside it).

### Unit / render (`courses/tests/`, `tests/`)

Mirror the naming of the existing `test_filltable_*` and `test_fillgate_*` families.

1. **Model / normalizer** — `normalize_data` emits `gate: False` by default, `True` when set, and
   coerces a non-boolean. *Mutant: drop the `gate` line.*
2. **Render, gated** — `gate: true` emits both `data-reveal-gate` and `data-filltablegate`.
   *Mutant: drop the `{% if %}`.*
3. **Render, ungated** — neither attribute appears, and the rendered output is otherwise unchanged.
   *Mutant: emit the attributes unconditionally.*
4. **Restore derivation** — the highest-value test here. Element with `gate: true` and state
   `{"done": True}` renders `data-state` containing `"open": true`. *Mutant: remove the injection.*
   Without this test the permanent-lockout regression is invisible to the whole suite.
5. **No state leak** — `render` must not mutate the caller's state blob: pass a state dict, render,
   assert the caller's dict still lacks `open`. *Mutant: assign into `ctx["mine"]` in place.*
6. **Ungated restore unchanged** — `gate: false` + `{"done": True}` renders `data-state` **without**
   `open`. *Mutant: derive `open` unconditionally.*
7. **View flag** — a unit whose only gate is a gating fill-table gets `has_reveal_gate=True` and
   `has_filltable_gate=True`; a unit with only an ungated fill-table gets both false. Cover a table
   nested as a **callout child**, since that is the real shape and the flat (non-`parent__isnull`)
   query is what makes it work. *Mutant: drop the `or has_filltable_gate`.*
8. **Prepaint A/B** — render the unit page with and without a gating table and diff the prepaint
   block: the `__fillTableBooted` term and the `.reveal-armed` style block appear only in the gated
   render. This must be an A/B; asserting the rule is present in the gated render alone proves
   nothing about whether the flag drives it.
9. **Direct-child pin** — in rendered callout output, `.filltable[data-reveal-gate]` is a **direct**
   child of `.callout__child`. The pre-hide CSS is `:has(> [data-reveal-gate])`; one extra wrapper
   div disarms it silently. Check against `test_reveal_scope_agreement.py` first — if that file
   already asserts JS/CSS selector agreement per family, extend it rather than adding a parallel test.
10. **Transfer round-trip** — export → import preserves `gate: true`; a bundle whose fill-table data
    omits `gate` imports as `False`. *Mutant: drop the export line.*
11. **Editor partial** — the checkbox renders, and renders checked for a gated element. Extend
    `test_filltable_editor_partial.py`.

### Static / wiring

12. **Boot flag present** — `filltable.js` assigns `window.__fillTableBooted` at parse time (a source
    assertion, in the style of `test_reveal_refactor_static.py`). A boot flag that is never set makes
    the watchdog disarm on *every* load, quietly defeating the pre-hide.

### e2e (`tests/test_e2e_*.py`, `-m e2e`)

Extend `test_e2e_filltable.py` or add a sibling, following `test_e2e_reveal_gate.py` /
`test_e2e_fillgate.py`.

13. **Wrong answer keeps content hidden** — fill one cell wrong, Check, assert the following element
    is not visible via `checkVisibility()` (Playwright's own visibility notion reports a
    1×1-clipped node as visible, so it cannot be trusted here).
14. **Correct answer reveals** — fill all cells correctly, Check, assert the following element is
    visible and the table is locked.
15. **Chain of two gates** — table 1 correct reveals table 2 but *not* the trailing content; table 2
    correct reveals the trailing content. This is unit 322's exact shape and the only test that
    exercises `isGateWrapper`'s stop condition for this family.
16. **Reload restores** — after success, reload; revealed content is still visible and the table is
    still locked.
17. **Pre-tick lockout** — the regression test for §3, end to end: solve an *ungated* table, then set
    `gate: true` on it, reload, and assert the following content is visible. This is the only test
    that exercises the seam through a real stored blob rather than a synthetic one.

Run e2e narrowly (`-m e2e` is mandatory or the suite silently deselects), start the test-DB container
first, and do not background the run.

### Screenshots

Capture the gated-then-revealed states in **light and dark**, judging dark on its own terms rather
than assuming the light result carries over.

## Risks and accepted trade-offs

- **No `FORMAT_VERSION` bump.** A newer bundle imported by an older libli loses the gate silently
  rather than being rejected. Accepted: the degraded result is a working ungated table, the validator
  is lenient by design, and a version bump carries its own merge hazard.
- **Chained gates change the reading experience.** In unit 322 the second table is hidden until the
  first is solved, where the original page showed both at once. Accepted deliberately — it keeps the
  feature to one checkbox per table and avoids a multi-table gate group.
- **`data__gate=True` adds one query per lesson-unit render.** Consistent with the eight sibling
  `has_*` `.exists()` queries already in that view.
