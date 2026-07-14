# Step-by-step inline reveal stepper element

## Purpose

Authors teaching worked procedures — especially algebra — want to reveal a short
chain of transformations **one at a time on a single line**, e.g.
`2^4·2^6=` → `2^{4+6}=` → `2^{10}`. Today libli has no element that does this:

- The **"Show more" reveal-gate** (PR #99) reveals *following sibling BLOCK
  elements* stacked vertically within a unit/tab scope. It cannot lay distinct
  fragments out inline on one line — each revealed sibling is its own block.
- **Spoiler / Callout** show or frame a single block; they have no stepping.

This element — display label **"Step-by-step"** — is the missing inline case: a
self-contained content element holding an ordered list of short inline fragments
(text + inline/display math). The first fragment is visible; a single walking
**"Show next"** button reveals the remaining fragments one at a time, flowing
left-to-right (wrapping as needed), then disappears. It is ungraded, stores no
per-student state, and makes no server round-trip. It ports the legacy
`.steps`/`.show_next`/`.show_step` widget
(`teaching/LAL/html/150_f_wykladnicza/010_test.html`), reinterpreted as an inline
self-contained element.

This is a lesson-only presentational element in the existing **Interactive**
add-menu group, alongside "Show more" and "Spoiler". It is the 27th entry in
`ELEMENT_MODELS`.

## Non-goals (YAGNI)

- **No rich text / nested block elements per step.** A step is a single-line
  fragment. Block content per step would force the steps to stack vertically —
  which is exactly what the reveal-gate already does — so it would collapse this
  element back into an existing one. Authors who need block-level progressive
  reveal use the reveal-gate.
- **No grading, no marks, no persistence, no server endpoint.** Progressive
  reveal is a pure client-side affordance; there is nothing to submit or store.
- **No reset / replay control.** Matches the legacy widget: the button walks to
  the end and is gone. Reloading the page resets it (fresh render).
- **No `FORMAT_VERSION` bump.** This is an additive element type; bumping would
  make every existing importer reject prior exports. (Mirrors the Matrix,
  Callout, and Spoiler decisions.)

## Architecture / components

The element follows the established GFK-join + concrete-model pattern
(`Element` join-row → `content_object`). Two new models:

- **`StepperElement(ElementBase)`** — the parent content element. Fields:
  - `prompt` (`CharField`, `blank=True`, `max_length` ~500): an optional lead-in
    line (text + inline math) rendered above the steps, e.g. "Follow the steps".
    Blank by default; when blank, no prompt node is rendered.
  - `elements = GenericRelation(Element)` — the standard cascade hook so deleting
    the concrete model removes its join-row (as every element has).
  - Steps are **not** stored here; they are child rows (below).
- **`StepperStep(models.Model)`** — one ordered step:
  - `stepper = ForeignKey(StepperElement, on_delete=CASCADE, related_name="steps")`
  - `order = OrderField(for_fields=["stepper"], blank=True)` — per-parent ordering
    space (the educa/OrderField pattern used by `ContentNode`, MatchPair, Matrix).
  - `content = CharField(max_length=500)` — the fragment's raw source (text with
    `\( \)` / `$$` math). Stored **raw** (not HTML) and escaped at render; math is
    typeset client-side by the existing KaTeX path. No nh3 sanitisation is needed
    because the value is never rendered as HTML — it is emitted inside a text node
    (autoescaped) and only KaTeX interprets the math delimiters. (Contrast Spoiler
    /Callout, which store sanitised HTML `body` fields.)

**Why a child model, not a JSON list.** Both patterns exist in the codebase
(Gallery uses a JSON `data` field; Matrix/Switch-grid/Match-pairs use child models
+ formsets). Steps are plain strings with **no** cross-references or linkage, so a
child model is trivial (`order` + `content`, no temp-id column mapping like Matrix)
and gives the editor a standard Django `inlineformset_factory` with free
add/remove/reorder — no bespoke JSON-serialising editor JS. The child model is the
lower-complexity choice here.

**Chosen `content` cap and step count.** `content` is `max_length=500` (a single
inline fragment, generous for math source). A stepper requires **at least 1 step**
to be meaningful and is capped at a sane maximum (`MAX_STEPS = 20`, mirroring
Gallery's ceiling) to bound the editor formset and render. `MIN_STEPS = 1`.

### Rendering (student view)

`StepperElement.render()` uses the base convention → `courses/elements/stepperelement.html`.
The template emits:

```
<div class="stepper" data-stepper>
  {% if el.prompt %}<p class="stepper__prompt">{{ el.prompt }}</p>{% endif %}
  <div class="stepper__line">
    {% for step in el.steps.all %}
      <span class="stepper__step"
            {% if not forloop.first %}hidden data-stepper-step{% endif %}>{{ step.content }}</span>
    {% endfor %}
    <button type="button" class="stepper__next ks-button" hidden data-stepper-next>{% trans "Show next" %}</button>
  </div>
</div>
```

- **Step 1 is always visible** (no `hidden`); steps 2..N carry `hidden` +
  `data-stepper-step` so the enhancer can reveal them in order.
- `{{ step.content }}` / `{{ el.prompt }}` are **autoescaped** (text nodes); KaTeX
  later scans the `.stepper` subtree and typesets the math delimiters. This is the
  same escape-then-typeset boundary the other math-bearing elements use.
- The **button is `hidden` by default and un-hidden by JS** (`data-stepper-next`).
  This is the no-JS fallback: with JS off the button never appears and every step
  span is shown (see below), so the full worked chain is readable.

**No-JS fallback.** The enhancer, on boot, (a) un-hides the button and (b) leaves
steps 2..N hidden until clicked. With **no JS**, the button stays `hidden` and the
`hidden` step spans stay hidden — which would hide steps 2..N with no way to reveal
them. To keep the no-JS view complete, the pre-hide is applied **by the enhancer**,
not by the server: the server renders steps 2..N *without* `hidden`, and the
enhancer adds `hidden` to them on boot (then reveals on click). This mirrors the
reveal-gate's watchdog approach (server renders visible; JS hides) so that no-JS
users see the entire chain. **This is the load-bearing accessibility invariant**:
*the server never hard-hides a step; only JS does.*

Concretely the template renders every step span visible and tagged
`data-stepper-step` (index ≥ 1), and the button `hidden`; `stepper.js` on boot
hides steps 2..N and un-hides the button.

### Reveal behavior (JS — `courses/static/courses/js/stepper.js`)

A **new, small, standalone enhancer** — it does **not** reuse
`window.libliRevealCascade`. The cascade walks *scope-level following siblings*
(`[data-tab-panel], .slide`) and is purpose-built for the sibling-block gate; the
stepper's reveal is entirely **intra-element** (reveal the element's own next step
span). It does, however, follow reveal.js's conventions: an idempotent
`data-*Ready` guard, a `window.libliInitStepper(root)` entry point re-runnable over
the editor preview pane, and eager `window.__stepperBooted = true` at parse time.

Per `[data-stepper]` element, on init (idempotent):

1. Mark ready (`dataset.stepperReady`); return early if already ready.
2. Collect the ordered step spans (`[data-stepper-step]`) and the button
   (`[data-stepper-next]`).
3. Hide steps at index ≥ 1 (`hidden = true`); un-hide the button
   (`button.hidden = false`). If there are 0 hidden steps (single-step stepper),
   keep the button hidden — nothing to reveal.
4. On button click: reveal the next still-hidden step (`hidden = false`), dispatch
   a bubbling `libli:reveal` on it (so a gallery/tabs enhancer in an ancestor can
   re-measure, consistent with the cascade's contract), move focus to the newly
   revealed span (`tabindex=-1`), and if no hidden steps remain, hide the button
   (`button.hidden = true`).

`window.libliInitStepper(root)` enhances every `[data-stepper]` under `root`
(default `document`), idempotently. Wired into:

- **`editor.js`** — re-run `window.libliInitStepper(preview)` after each fragment
  swap, next to the existing `libliInitGallery`/`libliInitTabs`/`libliInitRevealGates`
  re-inits, so the live preview reflects the enhanced behavior.
- **`editor.html`** — add `<script src="{% static 'courses/js/stepper.js' %}" defer></script>`.
  **This is the step historically missed twice (gallery, reveal-gate shipped with a
  dead preview because editor.html never loaded the enhancer).** A test GETs the
  editor page and asserts the `stepper.js` script tag is present.
- The lesson consumption page already loads element enhancers the same way the
  other Interactive elements are loaded (via the `has_<type>` context flags — see
  Data flow).

### Editor (authoring)

`_edit_stepper.html` is the edit-form partial `_host_form.html` includes for the
`stepper` type (**required — a missing partial 500s `TemplateDoesNotExist` the
instant the palette card is clicked**). It renders:

- the `prompt` field (a single text input, math-authoring-capable like other
  text+math fields), and
- an **inline formset** of steps (`StepperStepForm`, one `content` text input per
  row) with add/remove controls, using the standard formset management-form +
  clone-`__prefix__` JS pattern already used by the child-model editors.

Field names in the partial must match the form's field names. The formset uses
`extra` sized so a fresh add starts with one blank step row; server-side the
formset validation enforces `MIN_STEPS`/`MAX_STEPS` and drops all-blank rows.

## Data flow

**Authoring (create/edit):**

1. Author clicks the **Step-by-step** card in the Interactive group of
   `_add_menu.html` (lesson units only — the whole Interactive group is hidden when
   `unit_is_quiz`).
2. `element_add` (`stepper` in its allow-tuple) renders `_host_form.html` →
   `_edit_stepper.html` with an empty `StepperElement` form + step formset.
3. `element_save` / `builder.save_element` (`stepper` in its type dispatch) binds
   the `StepperElement` form and the step formset, validates, and on success saves
   the parent then the child steps (formset `save`), assigning `order` per row.
4. Editor preview re-renders the saved element; `editor.js` re-runs
   `libliInitStepper(preview)` so the preview shows the stepping behavior.

**Consumption (lesson):**

1. `build_lesson_context` scans the unit's elements; a `stepper` present sets a
   `has_stepper` flag (the established `has_<type>` pattern) so the lesson template
   loads `stepper.js`. Because steps carry math, the has-math scan must also
   include stepper content so KaTeX loads and typesets it — wired via the existing
   `_element_has_math` helper (the stepper branch returns True when any step
   `content` or the `prompt` contains a math delimiter). (Stepper is **not** a
   question, so the question-side `_question_has_math`/`question.js` path is not
   involved.)
2. The unit renders each element via `Element.render()` → `stepperelement.html`.
3. `stepper.js` boots, hides steps 2..N, un-hides the button, and drives the walk.

**Nesting in tabs.** The stepper is nestable inside a Tabs element. Its transfer
key `stepper` is added to `NESTABLE_TYPE_KEYS`, and the form key `stepper` is
aliased at `resolve_scope` via `_NESTABLE_FORM_KEY_ALIASES` if the form key and
transfer key differ (here they are the same string `stepper`, so the alias is a
no-op but is asserted by the nestable-consistency test). Rendered inside a tab
panel, the enhancer still works: its reveal is intra-element and independent of the
tab scope.

## Transfer (export / import)

The stepper joins the transfer trio with snake_case transfer key `stepper`
(distinct from, but here equal to, the form key):

- **`SERIALIZERS['stepper']`** — emits `{"prompt": <str>, "steps": [<str>, ...]}`
  (ordered step contents).
- **`VALIDATORS['stepper']`** — validates shape: `prompt` a string; `steps` a list
  of strings within `MIN_STEPS`..`MAX_STEPS`, each within `content` max length.
  Bounds-checks so a corrupt archive raises a clean validation error, never a 500.
- **`BUILDERS['stepper']`** — constructs the `StepperElement` + its `StepperStep`
  children from the payload (saving children with sequential `order`).

No `FORMAT_VERSION` bump (additive type).

## Error handling

- **Empty / all-blank steps:** the editor formset rejects a stepper with zero
  non-blank steps (`MIN_STEPS = 1`); all-blank extra rows are dropped before the
  count check.
- **Over-cap steps:** the formset rejects more than `MAX_STEPS` steps.
- **Corrupt import payload:** `VALIDATORS['stepper']` bounds-checks types and
  counts; a malformed archive yields a validation error, not a server error.
- **Single-step stepper:** valid; renders one visible span and no button (nothing
  to reveal). The enhancer keeps the button hidden.
- **Unresolved/parent delete:** `on_delete=CASCADE` on `StepperStep.stepper` and
  the `GenericRelation` on `StepperElement` mean deleting the element or its unit
  cleans up steps and the join-row with no dangling rows.
- **XSS:** `content`/`prompt` are emitted in autoescaped text nodes and never as
  HTML, so no sanitisation gap; KaTeX only interprets math delimiters.

## Testing

- **Model:** `StepperElement` + `StepperStep` create/order; `steps.all()` ordered
  by `order`; cascade delete removes steps and join-row.
- **Render (student):** step 1 has no `hidden`; steps 2..N rendered `data-stepper-step`;
  button rendered `hidden`; prompt shown only when non-blank; content autoescaped;
  a `<script>`-y step is escaped (negative XSS assert).
- **No-JS completeness:** with the server render (no JS), every step span is
  present and visible (server does not hard-hide steps) — the full chain is
  readable.
- **has_stepper / has_math:** a stepper-bearing unit sets `has_stepper` and, when a
  step/prompt has math, triggers the math typesetter load (via `_element_has_math`).
- **Editor authoring path:** GET **and** POST `manage_element_add` for `stepper`
  returns 200 (covers `element_add` → `_host_form` → `_edit_stepper` render — the
  path historically left untested). Editing an existing stepper re-seeds the step
  formset. Formset enforces MIN/MAX and drops blank rows.
- **editor.html script tag:** GET `manage_editor` asserts the `stepper.js` `<script>`
  tag is present (guards the twice-missed wiring).
- **Nestable:** `stepper` in `NESTABLE_TYPE_KEYS`; the nestable-consistency
  invariant (`NESTABLE ⊆ SERIALIZERS`) holds; a stepper can be added inside a tab.
- **Transfer round-trip:** export → import of a stepper preserves prompt + ordered
  steps; a corrupt payload is rejected by the validator (no 500). `ELEMENT_MODELS`
  count assertion updated to 27.
- **e2e:** on a lesson page, clicking "Show next" reveals steps one at a time and
  the button disappears after the last step (drive the real click, not
  `page.evaluate`).
- **i18n:** "Show next" and the label "Step-by-step" have real Polish translations;
  PO catalog stays clean (no fuzzy/obsolete entries).
