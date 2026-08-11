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

- An author can tick one checkbox on a fill-table so that solving it reveals the following siblings
  **within its scope**.
- Two gating tables in sequence chain correctly: the first reveals the second, the second reveals
  what follows it.
- A student who solved a table *before* the author ticked the checkbox is not locked out of the
  revealed content.
- A gated table still prints.
- No database migration, and no `FORMAT_VERSION` bump.

### Non-goals

- **No new element type.** This is a flag on the existing one, not a `FillTableGateElement`.
- **No multi-table gate group.** "These three tables jointly unlock X" is not expressible; chaining
  gates is the supported composition.
- **No LAL-loader change.** The importer will not auto-detect a `div.success` and set `gate`.
  Authors tick the box. (A later slice could revisit this once the flag exists.)
- **No change to marking or the gradebook.** A fill-table records no marks, gated or not.
- **No change to how `.fillgate` prints.** The print rule addressed in §3 currently also swallows a
  fill-gate's answered Q&A. That is pre-existing, arguably wrong, and deliberately left alone — this
  change narrows the rule by exactly one new attribute and regresses nothing. Worth its own issue.

## Architecture / components

Eleven touch points. Each is small; the design's weight is in the restore seam (§4), the print
carve-out (§3), and the page-level query shape (§7), not in volume of code.

`courses/state.py` is deliberately **not** among them — see §4 for why.

### 1. The flag lives in `data`, not in a new column

`gate` becomes a key in the `data` JSONField, alongside the settings already there — `header_row`,
`header_col`, `case_sensitive`, `border`, `prompt`:

```python
# FillTableElement.normalize_data, after `cells` is built
from courses.filltable import answer_cells   # local import, mirroring canonical_cells

# A gate with no answer cell can NEVER open, so it would strand every following
# sibling behind an unsatisfiable check, with no author-visible symptom.
# FillTableElementForm.clean_data already rejects that shape, but the importer
# (_build_fill_table -> normalize_data, model-level only) and programmatic
# construction do not, so force it off here rather than trusting one write path.
gate = bool(data.get("gate")) and any(True for _ in answer_cells(cells))

return {
    "header_row": bool(data.get("header_row")),
    "header_col": bool(data.get("header_col")),
    "case_sensitive": bool(data.get("case_sensitive")),
    "gate": gate,          # new
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
  `False`. Ungated, as it should be.

`_sanitized_data` (called from `save()`) needs no change — it walks cells and `prompt` only, and
passes unknown top-level keys through untouched.

**Also update the class docstring**, which the Purpose section above quotes as motivation and which
this change falsifies. `courses/models.py:1271` currently ends "Checked server-side per cell; records
no marks, reveals nothing." Replace the tail with something like: "records no marks; when
`data['gate']` is set, a fully-correct check reveals the following siblings in scope (see
`reveal.js`)."

### 2. Template — the gate marker

`templates/courses/elements/filltableelement.html`. The real root div is:

```html
<div class="filltable" data-filltable
     data-element-pk="{{ eid }}"
     data-check-url="{% url 'courses:filltable_check' eid %}"
     data-success-msg="{% trans 'Great!' %}"
     data-retry-msg="{% trans 'Try again' %}"
     data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
```

Add `{% if data.gate %}data-reveal-gate data-filltablegate{% endif %}` to **that** div, immediately
after `data-filltable`. `data-reveal-gate` is the family barrier `reveal.js` scans for;
`data-filltablegate` is the family discriminator, mirroring `data-fillgate` / `data-switchgate`.

**Invariant — the gate marker and `data-state` must be the same node.** `reveal.js::storedOpen(btn)`
reads `btn.dataset.state` directly off the node it found via `[data-reveal-gate]`. The template has
a second plausible host, the inner `.el.el--filltable` div; putting the marker there would make
`storedOpen` read `undefined` → `false` → prefix-closure `break` → the revealed content is hidden
**forever** for a student who has already solved the table. Test 3 below pins the co-location
specifically, because a test that merely asserts "the attributes appear in the rendered output"
stays green under exactly that mutation.

The root `.filltable` div is already the outermost node the element renders, so it also lands as a
direct child of the container's child-wrapper (`.callout__child`, `.tabs__child`, `.spoiler__child`,
`.ba__child`, or a slide's `.lesson-block__body`) — which is what the pre-hide CSS's
`:has(> [data-reveal-gate])` requires. The pre-hide rules themselves need no change; they match on
the attribute generically across all five scopes. The **print** rules do — see §3.

### 3. Print — carve the new family out of the gate-hiding rule

`core/static/core/css/app.css` holds a third copy of the scope selectors (this is what
`courses/tests/test_reveal_scope_agreement.py` exists to enforce: five scopes, three files). Inside
`@media print` it first *reverts* the pre-hide, so a printout shows gated content, and then hides the
gate controls themselves, which are meaningless on paper:

```css
@media print {
  .reveal-armed .slide > .lesson-block:has(...) ~ .lesson-block,
  ... /* five scopes */ {
    display: revert !important;
  }
  [data-reveal-gate] { display: none !important; }   /* app.css:1022 */
}
```

For the three existing families the hidden node is a control — a button, a blanks form, a cycler. For
a fill-table the node carrying `[data-reveal-gate]` **is the student's work**. Left alone, ticking
the checkbox silently deletes the whole table from every printout and PDF — both tables, in unit 322
— which flatly contradicts the "gating is purely additive" framing. Narrow the rule:

```css
[data-reveal-gate]:not([data-filltablegate]) { display: none !important; }
```

The `:not()` is the minimal correct form: every existing family's print behaviour stays byte-identical
and only the new family is carved out. It does not disturb `test_reveal_scope_agreement.py`, which
extracts the print block and asserts the five *scope* selectors are present in it — a different rule.

### 4. Render — the `done` → `open` seam (the sole restore path)

This is the one genuinely subtle part, and its mechanism is not what it first looks like.

`reveal.js` decides whether a stored gate is already open with a strict shape test:

```js
return !!(blob && blob.open === true);   // storedOpen()
```

A fill-table's stored blob has no `open` key, and **cannot acquire one**. `courses/state.py` maps
`"filltableelement"` to `_val_done`, which returns `{"done": True} if payload.get("done") else EMPTY`
— every other key is discarded server-side on every write. So there is no "legacy blob vs new blob"
distinction to bridge: *every* fill-table blob is `{done: true}`, now and after this change.

Two consequences, both load-bearing:

- **`courses/state.py` needs no change**, and deliberately so. `_val_done`'s monotone one-value shape
  is correct for a fill-table (the student's answers are re-rendered server-side from the element's
  own answers, gated on the flag); widening it to carry `open` would add a second source of truth for
  the same fact.
- **The render-time derivation below is the only mechanism by which a gated fill-table ever
  restores.** It is not a legacy-compatibility shim. Removing it does not degrade an edge case — it
  breaks restore for every gated table, leaving the student looking at a solved, locked table with
  the revealed content gone and no way to get it back.

Derive `open` at render time. The existing `render` body already opens with the `_state_context` call
and already branches on `done`, so this is a modification of that body, not an insertion before it:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        nd = self.normalize_data(self.data)          # hoisted: both branches used it
        if ctx["mine"].get("done"):
            # Shallow-copied dict, NEVER `self.data["cells"] = ...` -- mutating
            # self.data in place would silently overwrite the student's stored
            # pipe-delimited alternatives in-memory for the rest of the request.
            ctx["data"] = {**nd, "cells": self.canonical_cells}
            if nd["gate"]:
                # reveal.js::storedOpen tests `blob.open === true`, but state.py's
                # _val_done stores only {"done": True} -- nothing ever writes `open`.
                # Deriving it here is the ONLY thing that restores the cascade.
                # COPY, never in-place: _state_context's `mine` is a reference into
                # the caller's state blob, and mutating it would leak `open` into
                # every other reader of that blob for the rest of the request.
                ctx["mine"] = {**ctx["mine"], "open": True}
                ctx["mine_json"] = json.dumps(ctx["mine"])
        else:
            ctx["data"] = {**nd, "cells": self.resolved_cells}
        return render_to_string("courses/elements/filltableelement.html", ctx)
```

Hoisting `nd` also removes the third `normalize_data` call the naive form would introduce.

### 5. `filltable.js` — call the cascade

The all-correct branch currently locks and saves. It gains exactly one thing, the cascade call:

```js
if (data.all_correct === true && (data.cells || []).length > 0) {
  lock(root);
  if (root.hasAttribute("data-reveal-gate") && window.libliRevealCascade) {
    window.libliRevealCascade(root, { hideWrapper: false });
  }
  window.libliState.saveFlag(root, { done: true });   // UNCHANGED -- see §4
}
```

- The `saveFlag` line is **unchanged from today**. Writing `{done: true, open: true}` here would be
  dead code: `_val_done` strips `open` before it is stored (§4).
- `hideWrapper: false` matches `fillgate.js` — the solved table stays on screen with its green cells
  rather than being consumed, which is right for a gate whose content *is* the student's work.
- The `window.libliRevealCascade` guard covers the editor preview, where the pane may render a gating
  table without a live cascade.

`filltable.js` also gains a parse-time boot flag, mirroring `__fillGateBooted` / `__switchGateBooted`:

```js
window.__fillTableBooted = true;
```

`initOne`'s existing early return for a stored `done` flag needs no change: restore of the *cascade*
is `reveal.js`'s job (`restoreGates` runs independently off `data-state`), and restore of the
*table's own* locked appearance is already server-rendered.

### 6. `reveal.js` — focus target for a chained gate

`focusTargetIn()` resolves a focusable node inside a gate wrapper; a `<div>` is not focusable, so each
non-button family needs a branch. Add the fill-table's, alongside the existing two:

```js
if (gate.matches("[data-filltablegate]")) {
  return gate.querySelector(".filltable__input:not([disabled])");
}
```

The `:not([disabled])` is not decorative. `filltable.js::lock()` sets `inp.disabled = true` on the
live success path, and a disabled input cannot take focus — `focus()` would be a silent no-op that
drops focus to `<body>` instead of falling through to `cascadeFrom`'s existing
`target || makeFocusable(firstNew)` fallback. (The server-rendered restore path uses `readonly`,
which *is* focusable, so this only bites a table locked in the same session — invisibly.)

This branch only matters in the adjacent-gate case — one gating table immediately followed by another
— which is exactly unit 322's shape. Without it a keyboard user lands on a wrapper `<div>` instead of
the next table's first cell.

No other `reveal.js` change is required. `scopeOf`, `isGateWrapper` and `cascadeFrom` all key on
`[data-reveal-gate]` generically. `restoreGates` already computes `hideWrapper` as
`gate.matches(RESTORABLE)`, and `RESTORABLE` is `button.reveal-gate[data-reveal-gate]` — a fill-table
is not a button, so it correctly restores with `hideWrapper: false`.

### 7. `views.py` — page-level detection, without a ContentType SELECT

`has_reveal_gate` currently keys on *model name*, which cannot express a per-instance flag. It needs a
second term — but **not** the obvious reverse-`GenericRelation` form. `FillTableElement.objects
.filter(elements__unit=node, ...)` makes `GenericRelation.get_extra_restriction` call
`ContentType.objects.get_for_model`, which on a cold process cache is a DB SELECT. `views.py` rejects
that pattern explicitly in two existing comments — "app_label-pinned … to avoid cold-cache ContentType
SELECTs", and "get_for_model ct-ids were rejected because cold-cache CT SELECTs break
`tests/test_html_element.py`'s query-count assertion". That test asserts successive renders issue the
same number of queries and hand-warms only `MathElement` and `HtmlElement`, so a first-request-only CT
SELECT turns it red in an isolated run.

Use the CT-free shape instead, app_label-pinned like its neighbours:

```python
# CT-free by construction (see the has_html / has_stateful_elements comments): a
# reverse-GenericRelation filter would resolve FillTableElement's ContentType and
# emit a cold-cache CT SELECT, breaking test_html_element's query-count invariant.
# Short-circuited on has_fill_table so a unit with no fill-table costs zero queries.
has_filltable_gate = has_fill_table and FillTableElement.objects.filter(
    pk__in=node.elements.filter(
        content_type__app_label="courses", content_type__model="filltableelement"
    ).values_list("object_id", flat=True),
    data__gate=True,
).exists()

has_reveal_gate = (
    node.elements.filter(content_type__model__in=[...]).exists() or has_filltable_gate
)
```

`FillTableElement` must be imported in `views.py` if it is not already.

This is not cosmetic. `reveal.js` itself is loaded only under `{% if has_reveal_gate %}`
(`lesson_unit.html:89`), so on a unit whose only gate is a fill-table, **omitting this term means the
cascade engine never loads at all** and the gate silently does nothing.

The inner query is deliberately *not* scoped to `parent__isnull=True`, matching the existing comment
on `has_reveal_gate`: a gate nested inside a tab or callout keeps its own `unit` FK and must still be
found. Unit 322's tables are callout children, so this is exercised immediately.

`has_fill_table` (which loads `filltable.js`) is unchanged and already true whenever a gating table
exists.

### 8. `lesson_unit.html` — the prepaint watchdog

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

### 9. Editor — one checkbox

`case_sensitive` is the exact precedent: a `data`-borne boolean edited by a checkbox that
`filltable_editor.js` reads and folds into the serialized blob. Four touches, same shape:

| File | Site | Change |
|---|---|---|
| `templates/courses/manage/editor/_edit_filltable.html` | immediately after the `data-case-sensitive` label (line 38), inside `.table-editor__controls.filltable-editor__controls` | `<label><input type="checkbox" data-gate {% if d.gate %}checked{% endif %}> {% trans "…" %}</label>` |
| `courses/static/courses/js/filltable_editor.js` | the control-lookup block (~line 174) | `var gate = editor.querySelector("[data-gate]");` |
| `courses/static/courses/js/filltable_editor.js` | the `serialize` literal (~line 250) | `gate: !!(gate && gate.checked),` |
| `courses/static/courses/js/filltable_editor.js` | the listener block (~line 937) | `if (gate) gate.addEventListener("change", serialize);` |

`FillTableElementForm` needs **no change**: its only field is `data`, and `clean_data` returns
`normalize_data(...)`, which now carries `gate` through. `_grid_data` already carries it on both the
stored and bound-invalid re-render paths.

**Label wording.** The obvious phrasing — "Reveal what follows when all cells are correct" —
overpromises: `cascadeFrom` never leaves `scopeOf`'s scope, so a gated table inside a callout reveals
only later `.callout__child`s and nothing after the callout, and in a slideshow the scope is the
`.slide`. Since the motivating case is precisely a callout, name the boundary. Proposed English:
**"Reveal the rest of this section when all cells are correct"**.

**Twin-drift guard.** `tests/test_editor_twin_drift.py` classifies `serialize` as DIVERGENT with the
reason string "…its payload carries two extra document-level fields, case_sensitive and prompt"
(line 179). After this change there are three. The test stays green — the reason is prose — but the
guard's own documentation rots, and that file's docstring says the classification *is* the point.
Update the string to name `gate` as the third. No new `function` is introduced, so
`EXPECTED_COUNTS = {TABLE_JS: 30, FILL_JS: 36}` is untouched; confirm this rather than assume it.

**i18n.** One new msgid on a page that already contains close neighbours ("Case-sensitive", and the
three gate families' copy) is the classic `makemessages` fuzzy-prefill case: a wrong Polish string
lands pre-filled and marked fuzzy, and clearing it means removing **both** the `#, fuzzy` marker and
the bogus `msgstr`. Steps: run `makemessages`, inspect the new entry for a `#, fuzzy` marker, supply
the real Polish translation, rebuild the `.mo`. Do the `.mo` rebuild at the **end** of the branch —
it is a binary artifact and regenerating it early invites a merge conflict.

### 10. Transfer — one line

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
(defaulting to `False` for a legacy bundle that lacks the key, and forcing it off for a bundle whose
grid has no answer cells, per §1). `_val_fill_table` needs nothing: it checks only gross structural
corruption and does no exact-keys check.

### 11. Help documentation

`docs/help/course-admin/interactive-elements.md` ends its `{el:filltable}` section with "Records no
marks and reveals nothing." (line 77) — which this change falsifies. The page already frames the three
gate families in their own sections (`{el:revealgate}`, `{el:fillgate}`, `{el:switchgate}`), so the
fill-table's entry should describe the checkbox and, like those three, say that the reveal is confined
to the current section/container.

There is a maintained Polish twin, `docs/help/course-admin/interactive-elements.pl.md`. Update both.

## Data flow

**Authoring.** Author ticks the checkbox → `filltable_editor.js` serializes `gate: true` into the
posted `data` blob → `FillTableElementForm.clean_data` runs it through `normalize_data` (which keeps
it only if the grid has answer cells) → saved.

**Page load (unattempted).** `views.lesson_unit` computes `has_filltable_gate` → true, so
`has_reveal_gate` is true → prepaint arms `.reveal-armed`, hiding every `.callout__child` following
the one that `:has(> [data-reveal-gate])` → `reveal.js` and `filltable.js` both load → `restoreGates`
finds `data-state` without `open` and stops at this gate → content stays hidden. `filltable.js` arms
Check.

**Correct answer.** Student fills the cells, clicks Check → `filltable_check` returns
`all_correct: true` → `paint`, `summarize`, `lock` → `libliRevealCascade(root, {hideWrapper: false})`
reveals following siblings within the scope, stopping after the next gate wrapper, dispatching
`libli:reveal` on each so nested enhancers can re-measure → `saveFlag({done: true})` → `_val_done`
stores exactly `{"done": True}`.

**Wrong answer.** Cells painted, retry message shown, no cascade, no state write. Unlimited retries.

**Reload after success.** `render` sees `mine.done` → swaps in `canonical_cells` (readonly, locked)
*and* derives `open: true` into `data-state` → `restoreGates` reads `open === true` → replays the
cascade with `focus: false` → content visible, no scroll jump.

**Print.** The `@media print` revert un-hides gated content; the narrowed hide rule (§3) removes the
three control-shaped gate families but leaves the fill-table — table, answers and all — on the page.

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
| `gate: true` with **no** answer cells | `normalize_data` forces `gate` off (§1), so the marker is never rendered and nothing is stranded. Reachable only via import or programmatic construction; the editor form rejects it earlier. |
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
2. **Normalizer forces gate off with no answer cells** — a grid of only static cells plus
   `gate: true` normalizes to `gate: False`. *Mutant: drop the `answer_cells` conjunct.*
3. **Render, gated, co-located** — the node matching `[data-reveal-gate][data-filltablegate]` is the
   **same** node carrying a non-empty `data-state` and a `data-state-url`. Assert co-location, not
   mere presence. *Mutant: move the attributes to the inner `.el--filltable` div* — a
   presence-only assertion stays green under it, and the consequence is a permanent lockout.
4. **Render, ungated** — neither attribute appears, and the rendered output is otherwise unchanged.
   *Mutant: emit the attributes unconditionally.*
5. **Restore derivation** — the highest-value test here. Element with `gate: true` and state
   `{"done": True}` renders `data-state` containing `"open": true`. *Mutant: remove the injection.*
   This is the sole restore path (§4); without this test its removal is invisible to the whole suite.
6. **No state leak** — `render` must not mutate the caller's state blob: pass a state dict, render,
   assert the caller's dict still lacks `open`. *Mutant: assign into `ctx["mine"]` in place.*
7. **Ungated restore unchanged** — `gate: false` + `{"done": True}` renders `data-state` **without**
   `open`. *Mutant: derive `open` unconditionally.*
8. **Stored blob shape** — after a successful gated check, the *persisted* state is exactly
   `{"done": True}`. This pins §4's claim that `_val_done` strips everything else, and stops a later
   change from asserting against a persisted `open` that never exists.
9. **View flag** — a unit whose only gate is a gating fill-table gets `has_reveal_gate=True` and
   `has_filltable_gate=True`; a unit with only an ungated fill-table gets both false. Cover a table
   nested as a **callout child**, since that is the real shape and the flat (non-`parent__isnull`)
   query is what makes it work. *Mutant: drop the `or has_filltable_gate`.*
10. **No ContentType SELECT** — assert the gating-table detection does not add a `django_content_type`
    query, in the style of `tests/test_html_element.py`'s query-count invariant (which must stay green
    unmodified). *Mutant: rewrite the query as `FillTableElement.objects.filter(elements__unit=node,
    …)`.*
11. **Prepaint A/B** — render the unit page with and without a gating table and diff the prepaint
    block: the `__fillTableBooted` term and the `.reveal-armed` style block appear only in the gated
    render. This must be an A/B; asserting the rule is present in the gated render alone proves
    nothing about whether the flag drives it.
12. **Print carve-out** — extract the `@media print` block from `app.css` (reuse
    `test_reveal_scope_agreement.py`'s `_print_block` helper) and assert the gate-hiding rule excludes
    `[data-filltablegate]`. *Mutant: restore the bare `[data-reveal-gate]` selector.* Keep
    `test_reveal_scope_agreement.py` green unmodified — it is the reason this third file is in scope
    at all.
13. **Direct-child pin** — in rendered callout output, `.filltable[data-reveal-gate]` is a **direct**
    child of `.callout__child`. The pre-hide CSS is `:has(> [data-reveal-gate])`; one extra wrapper
    div disarms it silently. Add this to `tests/test_filltable_render.py`.
14. **Transfer round-trip** — export → import preserves `gate: true`; a bundle whose fill-table data
    omits `gate` imports as `False`. *Mutant: drop the export line.*
15. **Editor partial** — the checkbox renders, and renders checked for a gated element. Extend
    `tests/test_filltable_editor_partial.py`.

### Static / wiring

16. **Boot flag present** — `filltable.js` assigns `window.__fillTableBooted` at parse time (a source
    assertion, in the style of `tests/test_reveal_refactor_static.py`). A boot flag that is never set
    makes the watchdog disarm on *every* load, quietly defeating the pre-hide.
17. **Focus branch pinned** — extend `courses/tests/test_reveal_refactor_static.py`, whose
    `test_focus_targets_fill_gate_input` is the exact precedent, with the fill-table branch, including
    the `:not([disabled])` qualifier. *Mutant: delete the `[data-filltablegate]` branch* — note that
    e2e item 20 below passes with or without it, so this is the only coverage §6 gets.

### e2e (`tests/test_e2e_*.py`, `-m e2e`)

Extend `tests/test_e2e_filltable.py` or add a sibling, following `tests/test_e2e_reveal_gate.py` /
`tests/test_e2e_fillgate.py`.

18. **Wrong answer keeps content hidden** — fill one cell wrong, Check, assert the following element
    is not visible via `checkVisibility()` (Playwright's own visibility notion reports a
    1×1-clipped node as visible, so it cannot be trusted here).
19. **Correct answer reveals** — fill all cells correctly, Check, assert the following element is
    visible and the table is locked.
20. **Chain of two gates** — table 1 correct reveals table 2 but *not* the trailing content; table 2
    correct reveals the trailing content. This is unit 322's exact shape and the only test that
    exercises `isGateWrapper`'s stop condition for this family. Additionally assert
    `document.activeElement` is table 2's first enabled `.filltable__input`, not its wrapper — that
    assertion, and only that one, exercises §6's branch end-to-end.
21. **Reload restores** — after success, reload; revealed content is still visible and the table is
    still locked.
22. **Pre-tick lockout** — the regression test for §4, end to end: solve an *ungated* table, then set
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
- **One extra query per lesson-unit render, and only on units that already have a fill-table** (the
  `has_fill_table` short-circuit in §7). CT-free by construction, so it does not perturb the
  query-count invariant.
- **`.fillgate` still vanishes in print.** Pre-existing and untouched here; see Non-goals.
