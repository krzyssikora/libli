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
- A student who solved a table before the author ticked the checkbox **is never permanently locked
  out** of the revealed content. (Not the same as "never sees a stale view" — one chained case needs
  a reload to resolve; see the Error handling table.)
- A gated table still prints.
- No database migration, and no `FORMAT_VERSION` bump.

### Non-goals

- **No new element type.** This is a flag on the existing one, not a `FillTableGateElement`.
- **No multi-table gate group.** "These three tables jointly unlock X" is not expressible; chaining
  gates is the supported composition.
- **No LAL-loader change.** The importer will not auto-detect a `div.success` and set `gate`.
  Authors tick the box. (A later slice could revisit this once the flag exists.)
- **No change to marking or the gradebook.** A fill-table records no marks, gated or not.
- **No new cascade scope.** `scopeOf` recognises five scopes and a two-column column is not among
  them; this design does not add one (see the Error handling table).
- **No change to `cascadeFrom`'s stop condition.** The chained pre-tick case below is left as a
  documented, reload-healed limitation rather than fixed here — the fix would change shared cascade
  semantics for all four families across all five scopes, which is out of proportion to this slice.
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
from courses.filltable import answer_cells, is_blank_answer   # local, mirroring canonical_cells

# A gate that can never be SATISFIED strands every following sibling behind an
# unsatisfiable check, with no author-visible symptom. TWO grid shapes do that,
# and FillTableElementForm.clean_data rejects BOTH:
#   (a) no answer cell at all -- filltable_check returns cells: [] / all_correct:
#       false unconditionally;
#   (b) an answer cell whose accepted-answer string is blank -- marking.blank_matches
#       loops over an EMPTY accepted list and returns False for every input.
# The form is only one write path: the importer (_build_fill_table -> normalize_data,
# model-level only, and _val_fill_table never inspects answers) and programmatic
# construction both bypass it. So mirror both of the form's rules here.
answers = [ans for _r, _c, ans in answer_cells(cells)]
gate = (
    bool(data.get("gate"))
    and bool(answers)
    and not any(is_blank_answer(a) for a in answers)
)

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

**`gate` is the first `data` key whose normalized value depends on OTHER fields' validity.** That is
what makes §9's editor re-render a real problem rather than a formality — see there.

**Normalizer-routing invariant.** `save()` calls only `_sanitized_data`, which passes unknown
top-level keys through untouched — so nothing at the model layer coerces `data["gate"]` on its own.
What guarantees the stored value is a real JSON boolean is that **every** write path routes through
`normalize_data` first: `FillTableElementForm.clean_data` returns it, `_build_fill_table` constructs
with it, and the LAL builder feeds it. A row hand-written into the database (or by a future path that
skips the normalizer) is out of contract; §7 depends on this invariant and test 10 pins it.

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
**forever** for a student who has already solved the table. Test 4 below pins the co-location
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
extracts the print block with a `@media print\s*\{(.*?)\n\}` regex and asserts the five *scope*
selectors are present in it — a different rule, and the regex still captures the narrowed one.

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
- **The `hasAttribute` guard is load-bearing, not defensive noise.** Without it an *ungated*
  fill-table also calls `cascadeFrom`, which adds `.reveal-shown` to its following siblings and —
  since `focus` defaults to true — moves focus and scrolls the page on every correct answer. The
  blast radius is bounded by the *other* guard in the same condition: `reveal.js` loads only under
  `{% if has_reveal_gate %}`, so `window.libliRevealCascade` is `undefined` on a unit with no gate at
  all and the call short-circuits regardless. The damage is therefore "every ungated fill-table on a
  unit that also contains some gate" — narrower than the whole product, but exactly the "byte for
  byte" goal being broken. Test 27 pins it, and for the same reason its fixture must contain a second,
  gating element or the mutant cannot be observed.
- `hideWrapper: false` matches `fillgate.js` — the solved table stays on screen with its green cells
  rather than being consumed, which is right for a gate whose content *is* the student's work.
- The `window.libliRevealCascade` guard is a **defensive load-order guard**, mirroring `fillgate.js`
  and `switchgate.js`, which write the same check. It is *not* required by the editor preview:
  `editor.html` loads `reveal.js` unconditionally (line 229) before `filltable.js` (line 279), so the
  function is always defined there. Keep it anyway — the cost is nothing and it fails safe if the
  conditional loading in `lesson_unit.html` ever drifts.

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

**Reachability.** `cascadeFrom` calls `focusTargetIn` only when `lastRevealed === firstNew`, i.e.
when the next gate wrapper is the *immediately following* sibling with nothing between the two gates.
Unit 322 does **not** have that shape — a "Druga funkcja: …" text element sits between its two tables
— so this branch does not fire there, and the motivating unit is not what exercises it. It fires
whenever an author places two gating tables back to back, which is a legal and likely arrangement.
The e2e fixture for test 23 must therefore be built adjacent (see that item), and test 20 covers the
branch unconditionally as a source assertion.

This is the **only** `reveal.js` change. `scopeOf`, `isGateWrapper` and `cascadeFrom` all key on
`[data-reveal-gate]` generically and are left alone — including `cascadeFrom`'s `break` at an
already-open downstream gate, whose consequence is documented in the Error handling table.
`restoreGates` already computes `hideWrapper` as `gate.matches(RESTORABLE)`, and `RESTORABLE` is
`button.reveal-gate[data-reveal-gate]` — a fill-table is not a button, so it correctly restores with
`hideWrapper: false`.

### 7. `views.py` — page-level detection, without a ContentType SELECT

`has_reveal_gate` currently keys on *model name*, which cannot express a per-instance flag. It needs a
second term — but **not** the obvious reverse-`GenericRelation` form. `FillTableElement.objects
.filter(elements__unit=node, ...)` makes `GenericRelation.get_extra_restriction` call
`ContentType.objects.get_for_model`, which on a cold process cache is a DB SELECT. `views.py` rejects
that pattern explicitly in two existing comments — "app_label-pinned … to avoid cold-cache ContentType
SELECTs", and "get_for_model ct-ids were rejected because cold-cache CT SELECTs break
`tests/test_html_element.py`'s query-count assertion". That test compares two successive renders and
hand-warms only `MathElement` and `HtmlElement`, so a first-request-only CT SELECT turns it red.

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

**Three concrete edit sites in `build_lesson_context`:**

1. **Ordering.** `has_reveal_gate` is assigned at `views.py:424` and `has_fill_table` at `views.py:438`.
   Pasted in place the snippet raises `NameError`, so either hoist `has_fill_table` above
   `has_reveal_gate` or append the `or has_filltable_gate` term after both are bound.
2. **Import.** `FillTableElement` is **already imported** at `views.py:52` — do not add a second
   import; `ruff` would flag it.
3. **Context dict.** Add `"has_filltable_gate": has_filltable_gate` to the `return {...}` literal at
   `views.py:502-529`, next to `has_reveal_gate` (`:511`) and `has_fill_table` (`:515`). Omitting it
   makes `{% if has_filltable_gate %}` silently falsy, which drops §8's watchdog term with **no test
   failure** unless test 13's A/B is written as specified.

`data__gate=True` matches the JSON literal `true` only. That is exact rather than fragile *because* of
§1's normalizer-routing invariant: every write path stores a real boolean, so the view predicate and
the template's `{% if data.gate %}` (driven by `normalize_data`'s `bool(...)`) always agree. If they
ever diverge the failure is silent in both directions — a truthy-but-not-`true` value renders the
marker while `reveal.js` is never loaded, and a `true` value on an unsatisfiable grid arms the prepaint
while the marker is suppressed. Test 10 pins the invariant.

This is not cosmetic. `reveal.js` itself is loaded only under `{% if has_reveal_gate %}`
(`lesson_unit.html:89`), so on a unit whose only gate is a fill-table, **omitting this term means the
cascade engine never loads at all** and the gate silently does nothing.

The inner query is deliberately *not* scoped to `parent__isnull=True`, matching the existing comment
on `has_reveal_gate`: a gate nested inside a tab or callout keeps its own `unit` FK and must still be
found. Unit 322's tables are callout children, so this is exercised immediately.

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

The script-loading block needs no change: `filltable.js` already loads under `has_fill_table`, and
`reveal.js` now loads because `has_reveal_gate` includes gating tables. Load order is already correct
— `reveal.js` at line 89, `filltable.js` at line 93, both `defer`, so `libliRevealCascade` is defined
before any check can resolve.

### 9. Editor — one checkbox, and one form property

`case_sensitive` is the precedent for the checkbox itself: a `data`-borne boolean edited by a checkbox
that `filltable_editor.js` reads and folds into the serialized blob. Four touches, same shape:

| File | Site | Change |
|---|---|---|
| `templates/courses/manage/editor/_edit_filltable.html` | immediately after the `data-case-sensitive` label (line 38), inside `.table-editor__controls.filltable-editor__controls` | `<label><input type="checkbox" data-gate {% if d.gate %}checked{% endif %}> {% trans "…" %}</label>` |
| `courses/static/courses/js/filltable_editor.js` | the control-lookup block (~line 174) | `var gate = editor.querySelector("[data-gate]");` |
| `courses/static/courses/js/filltable_editor.js` | the `serialize` literal (~line 250) | `gate: !!(gate && gate.checked),` |
| `courses/static/courses/js/filltable_editor.js` | the listener block (~line 937) | `if (gate) gate.addEventListener("change", serialize);` |

**`FillTableElementForm.grid_data` DOES need an override — a rejected save would otherwise untick the
box.** This is where §1's "first field whose normalized value depends on other fields' validity" bites.
`_grid_data` (shared with `TableElementForm`) returns `model._sanitized_data(model.normalize_data(
parsed))` on the bound-invalid path, deliberately re-rendering the *submitted* grid so the author sees
their edit rather than the stored table. But §1's suppression forces `gate` to `False` on a **subset
of the conditions that make `clean_data` raise** — the no-answer-cell and blank-answer-cell rules are
both a rejection reason *and* a suppression trigger. So the author ticks the box, forgets one answer,
saves, gets "An answer cell is blank", and the checkbox comes back **unchecked** with no message about
it. Their next Save then posts `gate: false` from the DOM, silently discarding the intent.

The overlap is one-way, not an iff: `clean_data` has three further raising paths — an out-of-range
colspan/rowspan (`_scan_spans`, which runs *first*, before `normalize_data` can clamp it out of
sight), an over-cap grid (`_caps_ok`), and a course-scope image failure. For all three
`normalize_data` leaves `gate` at `True`, so the shared path would already re-render the box ticked.
The override below is written **unconditionally** rather than narrowed to the two triggering shapes,
which makes it a no-op on those other rejection paths and correct on all five.

Overlay the submitted value in `FillTableElementForm` (not in shared `_grid_data`, which
`TableElementForm` also uses and which has no `gate`):

```python
    @property
    def grid_data(self):
        d = _grid_data(self)
        # PRESERVE THE AUTHOR'S TICK across a rejected save. normalize_data (which
        # _grid_data runs) suppresses `gate` for exactly the two grids that make
        # clean_data raise, so the shared path would hand the template an unticked
        # box -- the author's intent, silently dropped, with the error message
        # pointing at the answer cell instead.
        if self.is_bound and not self.is_valid():
            raw = self.data.get("data")
            if isinstance(raw, str):
                try:
                    submitted = json.loads(raw)
                except ValueError:
                    submitted = None
                if isinstance(submitted, dict):
                    return {**d, "gate": bool(submitted.get("gate"))}
        return d
```

The template keeps reading `d.gate`, so no context plumbing changes. Test 18 pins it.

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
grid cannot satisfy it, per §1). `_val_fill_table` needs nothing: it checks only gross structural
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
it only if the grid can actually be satisfied) → saved. On a rejected save the tick survives the
re-render via §9's `grid_data` override.

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

**Chained tables (unit 322).** Table 1's cascade reveals the intervening "Druga funkcja" text and
table 2, then stops because table 2's wrapper is itself a gate wrapper. Because something sits between
the two gates, `cascadeFrom` focuses the first revealed block rather than calling `focusTargetIn`
(§6). Table 2's cascade then reveals the success text and both applet iframes, running to the end of
the callout's children.

## Error handling

| Situation | Behaviour |
|---|---|
| Student solved the table before the author ticked the box | Render derives `open` from `done`; cascade restores on the next load. No lockout. |
| **Chained gates, downstream one solved before the tick** | Two gated tables in one scope; the student had solved only table 2 while both were ungated. On load `restoreGates` `break`s at table 1 (prefix-closure) and never reaches table 2. The student then solves table 1; `cascadeFrom` reveals up to table 2's wrapper and `break`s at `isGateWrapper` **without consulting table 2's own stored state**. Table 2 is server-rendered `done`, so the template emits no Check button and `initOne` early-returns — nothing on the page can fire its cascade. **Everything after table 2 stays hidden until the student reloads**, at which point both gates restore and all content appears. Accepted, reload-healed, not permanent. Fixing it means teaching `cascadeFrom` to continue past a `storedOpen` downstream gate, which changes shared semantics for all four families across all five scopes — out of scope here; see Non-goals. Test 26 pins the documented behaviour, including that the reload heals it. |
| `reveal.js` blocked (extension, CSP, network) | `__revealBooted` falsy at `DOMContentLoaded` → watchdog disarms `.reveal-armed` → everything visible. Fail open. |
| `filltable.js` blocked | `__fillTableBooted` falsy → same disarm. Fail open. Content visible but ungated — the correct failure direction. |
| Check request fails | Existing `.catch` leaves the widget interactive; no cascade, no state write. |
| State POST fails | Fire-and-forget with `keepalive`; the DOM stays revealed for this session and the student re-earns it next load. Monotone, matching every other gate. |
| Drifted / unparseable `data-state` | `storedOpen`'s `try/catch` returns false → the gate stays live and re-answerable. |
| `gate: true` with **no answer cell** | `normalize_data` forces `gate` off (§1); marker never rendered, nothing stranded. Reachable only via import or programmatic construction. |
| `gate: true` with a **blank answer cell** | Same suppression, and for the same reason: `blank_matches` can never return true against an empty accepted list, so the gate would never open. |
| Rejected save on a gated table | §9's `grid_data` override re-renders the checkbox from the submitted payload, so the author's tick survives the validation error. |
| Gating table inside a **two-column column** | `fill_table` and `two_column` are both in `builder.NESTABLE_TYPE_KEYS`, but no two-column wrapper is a `scopeOf` scope. `scopeOf` resolves to the nearest *recognised* ancestor instead (`.slide` for a top-level two-column, `.callout__children` for one nested in a callout), and `isGateWrapper` is false at that level — so the pre-hide matches nothing and `restoreGates` skips the gate as mis-scoped. A live solve still runs `cascadeFrom`, adding `.reveal-shown` to siblings that were never hidden and moving focus, so the visible effect is a focus/scroll jump rather than a strict no-op. Fail-open; nothing is ever trapped. Accepted — the three existing families inherit the same limitation, and adding a sixth scope would change `test_reveal_scope_agreement.py`'s three-file contract. |
| Legacy bundle imported (no `gate` key) | `normalize_data` supplies `False`. Ungated. |
| Newer bundle imported by older libli | Unknown key ignored by the lenient validator, dropped by the old normalizer. Ungated, not an error. |
| Gating table with nothing after it in scope | `cascadeFrom` reveals nothing and falls back to focusing the scope. Harmless. |
| Editor preview | `data-state-url` is `""` so `saveFlag` no-ops. `reveal.js` loads unconditionally in the editor, so the cascade is live there. |

## Testing

Every test below must be **falsified before it is trusted** — introduce the named mutant, confirm
RED, then remove the mutant by editing it out (never by `git checkout`, which would discard the test
alongside it).

**Where things live.** `tests/` has an `__init__.py`; `courses/tests/` does not, so a helper cannot be
imported across the two roots — copy it. `tests/test_filltable_restore.py` already exists and is the
right home for every restore-shaped item (4, 6, 7, 8): it carries `_seed_filltable(unit, student,
cells, blob)`, a `_lesson_url` helper, a `data-state` regex assertion, and a module docstring
documenting the seam these tests will otherwise trip over — **`UnitProgress.element_state` is
str-keyed while `render()`'s `state` argument is int-keyed** (`views.py:485-494` does the conversion).
Seed through the lesson view with str keys; call `render()` directly only with int keys.

`_seed_filltable` needs a small extension first: it hardcodes `FillTableElement(data={"cells": cells})`
(line 38), so as written it cannot seed a gated element at all. Add a `gate=False` keyword folded into
the constructed `data` dict; the existing callers keep the default and are untouched.

### Unit / render

1. **Model / normalizer** — `normalize_data` emits `gate: False` by default and `True` when set on a
   satisfiable grid. *Mutant: drop the `gate` line.*
2. **Gate forced off — no answer cells** — a grid of only static cells plus `gate: true` normalizes to
   `gate: False`. *Mutant: drop the `bool(answers)` conjunct.*
3. **Gate forced off — blank answer cell** — a grid with one answer cell whose answer is `""` (or
   `"|"`) plus `gate: true` normalizes to `gate: False`. *Mutant: drop the `is_blank_answer` conjunct.*
   Separate from test 2 because the two conjuncts fail independently.
4. **Render, gated, co-located** — the node matching `[data-reveal-gate][data-filltablegate]` is the
   **same** node carrying a non-empty `data-state`. Go through the lesson view (per the note above) so
   `data-state-url` is real rather than the empty string a bare `el.render()` produces. *Mutant: move
   the attributes to the inner `.el--filltable` div* — a presence-only assertion stays green under it,
   and the consequence is a permanent lockout.
5. **Render, ungated** — neither attribute appears, and the rendered output is otherwise unchanged.
   *Mutant: emit the attributes unconditionally.*
6. **Restore derivation** — the highest-value test here. Element with `gate: true` and state
   `{"done": True}` renders `data-state` containing `"open": true`. *Mutant: remove the injection.*
   This is the sole restore path (§4); without this test its removal is invisible to the whole suite.
7. **No state leak** — `render` must not mutate the caller's state blob: pass an int-keyed state dict,
   render, assert the caller's dict still lacks `open`. *Mutant: assign into `ctx["mine"]` in place.*
8. **Ungated restore unchanged** — `gate: false` + `{"done": True}` renders `data-state` **without**
   `open`. *Mutant: derive `open` unconditionally.*
9. **Stored blob shape** — the *persisted* state after a gated success is exactly `{"done": True}`.
   Note that `filltable_check` writes **nothing** — it only returns `{"cells": …, "all_correct": …}`;
   persistence is a separate `saveFlag` POST. So the test must POST
   `{"element": <pk>, "state": {"done": true, "open": true}}` to `courses:element_state_save` and then
   read `UnitProgress.element_state`; driving `filltable_check` alone would find nothing stored.
   Sending `open` in the payload is the point — it is what exercises `_val_done`'s stripping. Pins
   §4's claim, and stops a later change from asserting against a persisted `open` that never exists.
   *Mutant: add `open` to `_val_done`'s return* — the test should go red, proving it reads storage.
10. **Normalizer-routing invariant** — saving through `FillTableElementForm` and importing through
    `_build_fill_table` both store a real JSON boolean at `data["gate"]`, so `data__gate=True` and the
    template's `{% if data.gate %}` agree. *Mutant: bypass `normalize_data` on one write path.*
11. **View flag** — a unit whose only gate is a gating fill-table gets `has_reveal_gate=True` and
    `has_filltable_gate=True`; a unit with only an ungated fill-table gets both false. Cover a table
    nested as a **callout child**, since that is the real shape and the flat (non-`parent__isnull`)
    query is what makes it work. *Mutant: drop the `or has_filltable_gate`.*
12. **Query shape pinned at the source** — a **source assertion**, not a query-count test. Assert
    `courses/views.py`'s fill-table gate term is built from `object_id` / `pk__in` and does **not**
    contain `elements__unit=`, in the style of `courses/tests/test_reveal_refactor_static.py`; use §7's
    rationale as the test's docstring. *Mutant: rewrite the query as
    `FillTableElement.objects.filter(elements__unit=node, …)`.*

    A runtime query-count test was considered and rejected as unfalsifiable, which is worth recording
    so nobody re-adds one: the mutant's extra `get_for_model(FillTableElement)` is gated on
    `has_fill_table`, not on `gate`, so an A/B between a gated and an ungated **fill-table** unit pays
    identical cost in both arms and the delta is 0 under every configuration. `clear_cache()` before
    the capture does not rescue it — `build_lesson_context`'s `prefetch_related("content_object")`
    (`views.py:348-351`) re-warms the cache in-request for top-level elements, and Django's
    `_add_to_cache` populates the `(app_label, model)` key alongside the id key. Nor does
    `tests/test_html_element.py` guard this: its fixtures contain only `HtmlElement`s, so
    `has_fill_table` is False and the new term short-circuits before the mutant is reached. That test
    must still stay green unmodified, but it is not the guard here.
13. **Prepaint A/B** — render the unit page with and without a gating table and diff the prepaint
    block: the `__fillTableBooted` term and the `.reveal-armed` style block appear only in the gated
    render. This must be an A/B; asserting the rule is present in the gated render alone proves
    nothing about whether the flag drives it. *Mutant: omit `has_filltable_gate` from the context
    dict* (§7 site 3) — the term vanishes and only this test notices.
14. **Print carve-out** — lives in `courses/tests/`, next to `test_reveal_scope_agreement.py`; copy
    that file's four-line `_print_block` helper rather than importing it. Assert the gate-hiding rule
    inside `@media print` excludes `[data-filltablegate]`. *Mutant: restore the bare
    `[data-reveal-gate]` selector.* `test_reveal_scope_agreement.py` must stay green unmodified.
15. **Direct-child pin** — in rendered callout output, `.filltable[data-reveal-gate]` is a **direct**
    child of `.callout__child`. The pre-hide CSS is `:has(> [data-reveal-gate])`; one extra wrapper
    div disarms it silently. Add to `tests/test_filltable_render.py`. *Mutant: wrap the root div.*
16. **Transfer round-trip** — export → import preserves `gate: true`; a bundle whose fill-table data
    omits `gate` imports as `False`. *Mutant: drop the export line.*
17. **Editor partial** — the checkbox renders, and renders checked for a gated element. Extend
    `tests/test_filltable_editor_partial.py`. *Mutant: drop the `{% if d.gate %}checked{% endif %}`.*
18. **Rejected save keeps the tick** — POST a gated table with one blank answer cell, assert the form
    is invalid **and** the re-rendered checkbox is still checked. *Mutant: delete §9's `grid_data`
    override* — without it the box comes back unchecked and the author's intent is silently lost.

### Static / wiring

19. **Boot flag present** — `filltable.js` assigns `window.__fillTableBooted` at parse time. A source
    assertion in the style of `courses/tests/test_reveal_refactor_static.py`; put it in that file or a
    `filltable`-named sibling in the same directory. *Mutant: delete the assignment.* A boot flag that
    is never set makes the watchdog disarm on *every* load, quietly defeating the pre-hide.
20. **Focus branch pinned** — extend `courses/tests/test_reveal_refactor_static.py`, whose
    `test_focus_targets_fill_gate_input` is the exact precedent, with the fill-table branch including
    the `:not([disabled])` qualifier. *Mutant: delete the `[data-filltablegate]` branch.* Test 23's
    `activeElement` assertion also covers this, but only on an adjacent-gate fixture; this static test
    covers it unconditionally.

### e2e (`tests/test_e2e_*.py`, `-m e2e`)

Extend `tests/test_e2e_filltable.py` or add a sibling, following `tests/test_e2e_reveal_gate.py` /
`tests/test_e2e_fillgate.py`. The whole block is falsified as a group by reverting §5's
`libliRevealCascade` call; per-item mutants are named where a sharper one exists.

21. **Wrong answer keeps content hidden** — fill one cell wrong, Check, assert the following element
    is not visible via `checkVisibility()` (Playwright's own visibility notion reports a
    1×1-clipped node as visible, so it cannot be trusted here). *Mutant: cascade unconditionally,
    ignoring `all_correct`.*
22. **Correct answer reveals** — fill all cells correctly, Check, assert the following element is
    visible and the table is locked. *Mutant: remove the `libliRevealCascade` call.*
23. **Chain of two gates, adjacent** — the fixture must place the two gating tables as **immediately
    adjacent** scope children, with nothing between them; this differs deliberately from unit 322,
    whose tables are separated by a text element (§6). Table 1 correct reveals table 2 but *not* the
    trailing content; table 2 correct reveals the trailing content. Additionally assert
    `document.activeElement` is table 2's first enabled `.filltable__input`, not its wrapper.
    *Mutant: delete `isGateWrapper`'s `break`* — the first table would reveal everything at once.
24. **Reload restores** — after success, reload; revealed content is still visible and the table is
    still locked. *Mutant: remove §4's `open` derivation.*
25. **Pre-tick lockout, single gate** — solve an *ungated* table, then set `gate: true` on it, reload,
    and assert the following content is visible. What distinguishes this from test 24 is **ordering,
    not storage**: test 24 also writes and re-reads a real blob (its live success `saveFlag`s through
    `element_state_save` → `_val_done`). This is the only test where the blob is written while the
    table is still ungated, which is the actual pre-tick sequence authors will create. Keep both.
    *Mutant: same as 24 — it must fail here too, or the test is not reading storage.*
26. **Pre-tick, chained** — the documented limitation from the Error handling table. Seed table 2
    `{"done": true}` with table 1 unsolved, tick `gate` on both, load, solve table 1, and assert the
    trailing content is **still hidden**; then reload and assert it is visible. Written to pin the
    accepted behaviour, so it is also the test that goes red if someone later changes `cascadeFrom`'s
    stop condition — which is the point: that change should be deliberate.
27. **Ungated table does not cascade** — solve an *ungated* fill-table that has a following sibling in
    its scope, and assert no `.reveal-shown` class is added there. *Mutant: delete the
    `hasAttribute("data-reveal-gate")` guard in §5.*

    **Do not assert "`document.activeElement` is unchanged" — that is red on a correct build.**
    `lock()` sets `btn.hidden = true` on the Check button (the node a click just focused) and
    `inp.disabled = true` on every input (the node focused on the Enter path); hiding or disabling the
    focused element resets `activeElement` to `<body>`. So focus moves on *every* successful check,
    cascade or not, and `<body>` is the expected baseline. Assert the negative that actually
    distinguishes the mutant instead: `activeElement` is not the following sibling wrapper and is not
    inside it. `window.scrollY` unchanged is a good second assertion, since the cascade's `focus()`
    is what scrolls.
    **The fixture must also contain a second, gating element** — a `RevealGateElement`, or a gated
    fill-table in a different scope (another slide, another container) — so `has_reveal_gate` is true
    and `reveal.js` actually loads. Without one, `window.libliRevealCascade` is `undefined`, the
    mutated line short-circuits on the *other* half of the condition, and the test is green against
    its own mutant. Assert only on the ungated table's own scope, so the second element's gating does
    not confound it. This is the only test defending Goal 1's "byte for byte"; every other new test
    uses a gated fixture. It is filed here, not in the render block, because `.reveal-shown` and
    `activeElement` exist only at runtime.

Run e2e narrowly (`-m e2e` is mandatory or the suite silently deselects), start the test-DB container
first, and do not background the run.

**Deliberately not tested: the revealed iframe's box.** An earlier draft proposed asserting a revealed
GeoGebra iframe has a non-zero `bounding_box()`, on the theory that a `loading="lazy"` iframe revealed
out of `display: none` might come up collapsed (no enhancer listens for `libli:reveal` on iframes —
only `gallery.js` and `tabs.js` do). The CSS settles it: `.embed-frame` is
`width: 100%; aspect-ratio: 16 / 9` with the iframe absolutely filling it (`courses.css:113-114`), and
`iframeelement.html` puts the per-element ratio in an inline style on that wrapper. The height is
purely CSS-derived from container width and is non-zero the instant the node is not `display: none`,
loaded or not. Such an assertion would pass under the group mutant only because nothing was revealed
at all — i.e. it would duplicate test 22 while appearing to cover lazy-loading. Dropped rather than
shipped as a test that cannot go red for its stated reason.

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
- **The chained pre-tick case needs a reload.** Documented in Error handling, pinned by test 26, and
  explicitly out of scope to fix here.
- **The checkbox is offered in placements where it cannot work** (a two-column column). Fail-open and
  inherited from the existing families; see the Error handling table.
- **One extra query per lesson-unit render, and only on units that already have a fill-table** (the
  `has_fill_table` short-circuit in §7). CT-free by construction, so it does not perturb the
  query-count invariant.
- **`.fillgate` still vanishes in print.** Pre-existing and untouched here; see Non-goals.
