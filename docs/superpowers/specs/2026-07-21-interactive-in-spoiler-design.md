# Interactive elements as spoiler children

## Purpose

The nestable-spoiler feature made `SpoilerElement` a single-slot container of
**static leaf** children only (`SPOILER_CHILD_TYPES = {text, math, image, video,
iframe, table, gallery, callout}`). Interactive/stateful types were deliberately
excluded — the loader, `resolve_scope`, and transfer all REJECT-LOUDLY a
`reveal_gate`/`switch_gate`/`fill_gate`/`fillblank`/`switch_grid` nested in a
spoiler ("non-leaf child … spoilers hold only static content"), a decision taken
because the render/JS/practice-state cost was unquantified and prevalence unknown.

Prevalence is now measured: in the matematyka LAL corpus, **123 files across 10
parts** have an interactive element nested inside a spoiler — overwhelmingly
`switch_gate` (106) with `reveal_gate` (21), `fillblank` (4), `fill_gate` (3).
These come from LAL `<details>` "rozwiązanie"/"zobacz" (solution/see) collapses
wrapping a progressive step-through: **~250 of 268** such spoilers are labelled
"rozwiązanie"/"zobacz"/"rozwiąż zadanie" (solution reveals). The interactive
step-through is a teacher-authored scaffold (the student reconstructs the solution
by choosing each step) — pedagogically distinct from a static solution dump. The
current guard blocks loading all 123 files, gating both the batch import of parts
002–150 and live-rendering the recovered content.

This feature makes `SpoilerElement` accept those 5 interactive types as children,
**preserving the step-through interactivity**, and enables authoring them in the
editor. It is a general libli capability (spoilers can hold interactive content),
not import-specific.

## Scope

- **In scope:** allow `reveal_gate`, `switch_gate`, `fill_gate`, `switch_grid`,
  `fill_blank` (`FillBlankQuestionElement`) as depth-1 leaf children of a
  `SpoilerElement`, across: model/loader/editor allowlist, the JS-wiring flag for
  nested questions, the reveal-cascade client scoping (so a gate reveals content
  *within* its spoiler), transfer round-trip, and editor add-menu authoring.
- **Out of scope:** other nestable containers (Tabs/TwoColumn) already handle these
  types; no change there. No new element type, no migration (all changes are
  allowlists + JS/CSS + one query). Degrade-to-static (the rejected alternative) is
  not built. The parser is UNCHANGED — it already emits these as spoiler children;
  they were only being rejected downstream.
- **Invariant preserved:** all 5 types are **leaves** (non-containers). A gate
  reveals following *sibling* leaf children within the spoiler. Depth stays 1; the
  guards still reject containers (tabs/two_column) and spoiler-in-spoiler.

## Background: what already works (verified by investigation)

- **RENDER (no change):** `SpoilerElement.render()` (`courses/models.py:432`) →
  `resolved_children()` (`models.py:419`) → `spoilerelement.html:8-9` dispatches
  every child through the generic `{% render_element child %}`
  (`courses/templatetags/courses_extras.py:25`), which handles all types (incl.
  server-side `fillblank` restore at `courses_extras.py:55-85`). A nested gate
  renders its normal template unchanged.
- **PRACTICE-STATE (no change):** persist (`views.py:725` `element_state_save`,
  `views.py:783` `check_answer`) and the restore map (`views.py:386-393`) key by
  element **pk + unit**, not top-level scope, so nested elements persist/restore.
  `fillblank` restore is server-side per-pk (works nested); `switch_grid` restore
  is client-side per-widget global query (works nested).
- **TRANSFER SERIALIZERS (no change):** `_val_reveal_gate`/`_val_fill_gate`/
  `_val_switch_gate`/`_val_switch_grid`/`_val_fill_blank` exist and are registered
  in `VALIDATORS` (`payloads.py:759-791`); all 5 round-trip as top-level today
  through the same parent/join substrate spoilers already use for static leaves.
- **LOADER BRANCHES (no change):** `build_element` already has branches for all 5
  (`builders.py:107 reveal_gate, 167 fill_gate, 179 fillblank, 223 switch_gate,
  237 switch_grid`), each calling `_attach` with the injected `parent=join,
  tab_id=SLOT_ID`. Only the allowlist check ahead of them (`builders.py:83`)
  rejects them today.
- **GATE JS FLAGS (no change):** `has_reveal_gate`/`has_fill_gate`/
  `has_switch_gate`/`has_switch_grid` (`views.py:344-357`) are **flat unit-wide**
  queries (`node.elements.filter(content_type__model=…)`), so a spoiler-nested gate
  already arms its JS bundle + the pre-hide `<style>` (`lesson_unit.html:5,37,77`).

## The type-key namespace problem (central design constraint)

`SPOILER_CHILD_TYPES` is consulted at three sites, each in a **different type-key
namespace**. For the existing static types all three coincide (`text`=`text`=`text`),
but the interactive types diverge:

| element | loader/parser key (`builders.py:83` `ctype`) | editor form key (`resolve_scope` `type_key`, `builder.py:118`) | transfer key (`payloads.py:731` `el["type"]`) |
|---|---|---|---|
| reveal gate | `reveal_gate` | `revealgate` | `reveal_gate` |
| fill gate | `fill_gate` | `fillgate` | `fill_gate` |
| switch gate | `switch_gate` | `switchgate` | `switch_gate` |
| switch grid | `switch_grid` | `switchgrid` | `switch_grid` |
| fill blank | `fillblank` | `fillblankquestion` | `fill_blank` |

The 4 gates: loader key == transfer key; only the form key differs (already handled
for tabs by `_NESTABLE_FORM_KEY_ALIASES`, `builder.py:65-73`). `fillblank` diverges
in **all three**.

**Design rule: `SPOILER_CHILD_TYPES` holds CANONICAL (transfer) keys, and each
non-canonical check site normalizes to canonical before checking** — mirroring how
the existing tabs path already normalizes form keys via `_NESTABLE_FORM_KEY_ALIASES`
before checking `NESTABLE_TYPE_KEYS` (`builder.py:133-134`). Canonical keys added:
`reveal_gate, fill_gate, switch_gate, switch_grid, fill_blank`.

## Design

### Layer 1 — Allowlist widening (model/loader/editor-scope/transfer)

1. **`SPOILER_CHILD_TYPES`** (`courses/builder.py:60`): add the 5 canonical keys
   `reveal_gate, fill_gate, switch_gate, switch_grid, fill_blank`. Update the
   comment (no longer "static content only").
2. **`NESTABLE_TYPE_KEYS`** (`courses/builder.py:34`): add `fill_blank` (the 4 gates
   are already present). This is required by the transfer general nestable check
   (`payloads.py:752`) and keeps the `NESTABLE_TYPE_KEYS <= set(SERIALIZERS)`
   invariant (`fill_blank` ∈ `SERIALIZERS`).
3. **`_NESTABLE_FORM_KEY_ALIASES`** (`courses/builder.py:65`): add
   `"fillblankquestion": "fill_blank"` so the editor form key normalizes to the
   canonical key (the 4 gate aliases already exist: `revealgate→reveal_gate`, etc.).
4. **`resolve_scope` spoiler branch** (`courses/builder.py:118`): change
   `if type_key not in SPOILER_CHILD_TYPES:` to normalize first —
   `child_key = _NESTABLE_FORM_KEY_ALIASES.get(type_key, type_key); if child_key
   not in SPOILER_CHILD_TYPES:`. For a static type (`text`) the alias is a no-op, so
   no regression; for a gate/fillblank form key it maps to canonical and passes.
5. **Loader spoiler-child check** (`courses/lal_loader/builders.py:83`): the parser
   `ctype` matches canonical for the 4 gates but not for `fillblank`. Normalize the
   one divergent key: introduce a module-level
   `_PARSER_TO_CANONICAL = {"fillblank": "fill_blank"}` and check
   `_PARSER_TO_CANONICAL.get(ctype, ctype) not in SPOILER_CHILD_TYPES`. (Symmetric
   with the form-key normalization; localizes the parser-namespace quirk at the
   parser↔model boundary where the loader already lives.)
6. **Transfer `validate_nesting`** (`courses/transfer/payloads.py:731`): `el["type"]`
   is already canonical → no code change; widening `SPOILER_CHILD_TYPES` (step 1) is
   sufficient. (The `NESTABLE_TYPE_KEYS` general check at `payloads.py:752` also runs
   and needs `fill_blank`, added in step 2.)

Result: the LAL loader, the editor save path, and transfer import all accept the 5
interactive types as spoiler children; containers and spoiler-in-spoiler stay
rejected (they are neither in `SPOILER_CHILD_TYPES` nor produced by the parser's
no-nest mode).

### Layer 2 — `has_questions` flat query (JS wiring for nested fillblank)

`has_questions` (`courses/views.py:340`) is the only element flag still computed
from the top-level `elements` list (`parent__isnull=True`), so a `fillblank` that
exists ONLY as a spoiler child would leave `has_questions` false → `question.js` +
`dnd.js` never load (`lesson_unit.html:65-66`), and the nested widget stays inert.
(`question.js` itself uses a global `document.querySelectorAll("[data-question]")`,
so it enhances the nested widget once loaded.)

Change `has_questions` to a flat unit-wide query, matching the gate flags:
`has_questions = node.elements.filter(content_type_id__in=question_ct_ids).exists()`
(`question_ct_ids` is already computed at `views.py:334`). This detects a question
anywhere in the unit. No other question type is nestable today, so this only newly
fires for a spoiler-nested `fillblank`; top-level behaviour is unchanged.

### Layer 3 — Reveal-cascade spoiler scope (the one real engineering item)

`reveal.js` bounds a gate's cascade to the nearest `[data-tab-panel]` or `.slide`
scope; a spoiler is neither, so a spoiler-nested `reveal_gate`/`switch_gate`/
`fill_gate` (the 3 that cascade — `switch_grid`/`fillblank` do not) resolves its
scope to the enclosing slide/tab-panel and reveals the siblings AFTER the whole
spoiler, and its gated content is never pre-hidden (leak) nor correctly revealed.

Teach the cascade that a spoiler body is a scope, mirroring the tab-panel case
(whose child wrapper directly contains the gate):

1. **`scopeOf`** (`reveal.js:44`): `return btn.closest("[data-tab-panel], .slide,
   .spoiler");`. `closest` returns the NEAREST match, so a gate inside a spoiler
   inside a tab correctly scopes to the spoiler (innermost). The spoiler `<details
   class="spoiler">` is the scope element; its direct children are the `<summary>`
   and the `.spoiler__child` wrappers (`spoilerelement.html:2-10`).
2. **`isGateWrapper`** (`reveal.js:60-66`): the wrapper→gate selector differs by
   scope. Today: tab-panel uses `:scope > [data-reveal-gate]`, slide uses
   `:scope > .lesson-block__body > [data-reveal-gate]`. A spoiler child wrapper
   (`.spoiler__child`) directly wraps `render_element child` (like `.tabs__child`),
   so it uses the direct-child selector. Refactor to:
   `var sel = scope.matches(".slide") ? ":scope > .lesson-block__body >
   [data-reveal-gate]" : ":scope > [data-reveal-gate]";` — the direct-child form now
   serves BOTH tab-panel and spoiler; only slide keeps the lesson-block form. (Same
   `wrapper.querySelector(sel)` call.)
3. **Pre-hide CSS** (`lesson_unit.html:39-40`): add a third selector mirroring the
   tab-panel rule for the spoiler wrapper:
   `.reveal-armed .spoiler > .spoiler__child:has(> [data-reveal-gate]) ~
   .spoiler__child:not(.reveal-shown) { display: none; }`. The `<summary>` is not a
   `.spoiler__child`, so the `~` sibling combinator never hides it, and the general
   sibling only hides `.spoiler__child`s AFTER a gate-bearing one.

`ownWrapper` (`reveal.js:50`), `cascadeFrom` (`reveal.js:99`), and `restoreGates`
(`reveal.js:181`) are scope-agnostic — they call `scopeOf`/`isGateWrapper` — so
fixing those two functions + the CSS fixes cascade AND restore for all 3 cascading
gates in one change. `switch_gate`/`fill_gate` reach the cascade via
`window.libliRevealCascade` (`switchgate.js:79`, `fillgate.js:72`), so they inherit
the fix; their own answer-check/lock already work nested.

**Must-verify before locking selectors (Task 0 of the plan):** confirm the rendered
DOM of a gate spoiler-child is a DIRECT child of `.spoiler__child`
(`.spoiler__child > [data-reveal-gate]`), matching the `:scope > [data-reveal-gate]`
selector and the pre-hide CSS. The tab-panel case proves `render_element` emits the
gate without a `.lesson-block__body` wrapper in a nested context, but verify via a
real render (the whole cascade/CSS correctness hinges on this one DOM fact). If a
wrapper intervenes, adjust both the `isGateWrapper` selector and the CSS to match.

### Layer 4 — Editor authoring (add-menu)

`_add_menu.html` currently hides interactive cards in a spoiler:

1. **Interactive group** (`_add_menu.html:27`): `{% if not unit_is_quiz and not
   in_spoiler %}` → `{% if not unit_is_quiz %}`. The 4 gate cards
   (revealgate/fillgate/switchgate/switchgrid) already render in a *tab* nested
   add-menu (they are not `nested`-gated), so dropping the `in_spoiler` clause makes
   them authorable in a spoiler too. `resolve_scope` (Layer 1.4) now accepts them.
2. **`fillblankquestion` card** (`_add_menu.html:41-48`): the question group is
   `{% if not nested %}`, so `fillblankquestion` is hidden in ANY nested context.
   Add a single `fillblankquestion` card shown when `in_spoiler` (it is the only
   nestable question). Keep the other question cards hidden (they are not nestable).
3. Editor rows + edit forms for nested interactive children already work via the
   generic `_element_row` (the nestable-spoiler editor branch renders children) and
   the now-permissive `resolve_scope`; no per-type editor change.

## Error handling

- **Loader/editor/transfer:** an unsupported child (a container, or a
  spoiler-in-spoiler) still hits the widened-but-still-bounded allowlist and raises
  the existing `LoaderError`/`NestingError`/transfer error — the REJECT-LOUDLY
  behaviour is preserved for genuinely unsupported nesting, only the 5 leaf
  interactive types are newly permitted.
- **Reveal JS:** `restoreGates` already `continue`s (skips) a gate whose
  `ownWrapper`/`isGateWrapper` is mis-scoped; after Layer 3 a spoiler-nested gate is
  correctly scoped, so it restores instead of being skipped. A gate with a drifted
  state blob still degrades to "stays live" (`storedOpen` returns false on parse
  error), unchanged.
- **has_questions:** the flat query is a strict superset detector; it can only add
  `question.js` loading, never remove it — no regression risk for existing units.

## Testing

TDD, falsifiable (RED first). Group by layer; use the existing test conventions
(`courses/tests/test_spoiler_nesting.py`, `test_*_transfer.py`,
`test_reveal_gate_*`, the LAL loader tests `tests/lal_import/…` /
`courses/tests/test_lal_loader_units.py`).

- **Loader accepts each interactive spoiler child (RED today):** a LAL JSON spoiler
  whose `elements` include a `switch_gate` / `reveal_gate` / `fill_gate` /
  `switch_grid` / `fillblank` loads without `LoaderError`, producing the child
  `Element` with `parent=<spoiler join>`, `tab_id=SLOT_ID`. Assert the `fillblank`
  case specifically (the `_PARSER_TO_CANONICAL` normalization) — RED without it.
- **`resolve_scope` accepts each form key in a spoiler (RED today):** calling
  `resolve_scope(unit, <spoiler join pk>, SLOT_ID, "switchgate")` (and the other 4
  form keys, incl. `"fillblankquestion"`) returns `(join, SLOT_ID)` instead of
  raising `NestingError`. Assert a container form key (`"tabs"`) STILL raises
  (invariant intact).
- **`resolve_scope` still rejects a nested (depth-2) spoiler's children** — the
  `join.parent_id is not None` guard is untouched; add/keep a test.
- **Transfer round-trip (RED today):** export a unit with a spoiler containing a
  `switch_gate` child, re-import into a fresh course, assert the child survives with
  the right parent/slot and its data (options/answer). Include a `fill_blank` case
  (exercises the `NESTABLE_TYPE_KEYS` + `SPOILER_CHILD_TYPES` widening). Assert
  `validate_nesting` rejects a container-in-spoiler archive still.
- **`has_questions` flat (RED today):** a unit whose ONLY question is a `fillblank`
  nested in a spoiler → `build_lesson_context` returns `has_questions True` (so
  `question.js` loads). A unit with no questions anywhere → still False.
- **Reveal-cascade spoiler scope (Layer 3):** the hard part to test without a
  browser. (a) A render/template test asserting the pre-hide `<style>` includes the
  `.spoiler > .spoiler__child…` selector when `has_reveal_gate`. (b) A DOM-structure
  assertion (real render of a spoiler with a `reveal_gate` child + following
  sibling) that the gate is a direct child of `.spoiler__child` (locks the selector
  assumption). (c) A JS-level e2e (Playwright, following the existing reveal e2e
  pattern) — a `reveal_gate` inside an OPEN spoiler, on click, reveals the next
  `.spoiler__child` WITHIN the spoiler and does NOT reveal content after the spoiler;
  and on reload `restoreGates` re-reveals it. Run e2e foreground.
- **Editor add-menu (RED today):** the editor page for a top-level spoiler renders
  the 4 interactive cards + a `fillblankquestion` card in its in-spoiler add-menu;
  a POST authoring a `switchgate` into the spoiler (through `manage_element_save` →
  `resolve_scope`) succeeds (200) and creates the child. Assert the PR#126
  no-regression: the Tabs nested add-menu is unaffected.
- **Regression:** the existing `test_spoiler_nesting.py` guards (static-only
  rejection now widened — update the specific "rejects disallowed child type"
  test to assert a still-disallowed type like `tabs`, not a now-allowed gate) and
  all nestable-spoiler tests pass.
- **Live corpus (secondary):** reload part `100_geometria_2` /
  `104_geometria_3_czworokaty` into `libli_mat` — previously aborted with
  "non-leaf child (switch_gate) …"; now loads. Render a "rozwiązanie" unit and
  confirm the step-through works inside the reveal.

## Verification

- Reload the two previously-blocked parts (`100_geometria_2`,
  `104_geometria_3_czworokaty`) into `libli_mat` (`.env` DEBUG server) — they load
  without the interactive-in-spoiler `LoaderError`. Note the separate pre-existing
  missing-video block on part `050` (unrelated).
- Open a "rozwiązanie" solution-reveal unit (e.g. a 100/104 unit with a
  switch-in-details): the spoiler toggles, and inside it the switch/reveal
  step-through works — clicking a cycler + confirm reveals the next step WITHIN the
  spoiler, not content after it; reloading restores revealed steps.
- Author check: in the editor, add a "Choose & confirm" (switchgate) inside a
  top-level spoiler, save, confirm it renders and works in the lesson view.
- Hand the user the URLs.

## Out of scope / follow-up

- Degrade-to-static (rejected in favour of preserving interactivity).
- Authoring interactive children in a spoiler that is itself nested in a tab is
  bounded by the existing depth-1 rule (a nested spoiler takes no children); this
  feature does not change that.
- The broader batch load of parts 002–150 depends on this feature but is a separate
  effort (this unblocks it, does not perform it).
