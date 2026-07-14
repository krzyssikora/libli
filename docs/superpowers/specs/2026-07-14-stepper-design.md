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
  - `prompt` (`CharField`, `blank=True`, `max_length=500`): an optional lead-in
    line (text + inline math) rendered above the steps, e.g. "Follow the steps".
    Blank by default. `StepperElement.save()` **strips** `prompt`
    (`self.prompt = self.prompt.strip()`) so a whitespace-only value normalizes to
    `""`; the template's `{% if el.prompt %}` then renders no empty prompt node.
    The value `500` is a single source of truth reused by the model, the import
    validator, and any length assertion.
  - `elements = GenericRelation(Element)` — the standard cascade hook so deleting
    the concrete model removes its join-row (as every element has).
  - Steps are **not** stored here; they are child rows (below).
- **`StepperStep(models.Model)`** — one ordered step:
  - `stepper = ForeignKey(StepperElement, on_delete=CASCADE, related_name="steps")`
  - `order = OrderField(for_fields=["stepper"], blank=True)` — per-parent ordering
    space (the educa/OrderField pattern used by `ContentNode`, MatchPair, Matrix).
    `save_element` sets `order` **explicitly** to the 0-based position of each row
    in the submitted formset (see Editor / Data flow) rather than relying on
    `OrderField`'s blank auto-increment, so ordering is deterministic and gap-free
    after row deletions.
  - `class Meta: ordering = ["order"]` — **required**. `OrderField` only supplies the
    field; without `Meta.ordering`, `el.steps.all` returns DB-default order, which is
    not guaranteed to match `order` (the template `{% for step in el.steps.all %}`
    and the "ordered by order" test both depend on this).
  - `content = CharField(max_length=500)` — the fragment's raw source (text with
    inline `\(...\)` / `\[...\]` math — the delimiters `math.js`'s `INLINE_DELIMS`
    supports; **`$$` is not supported** by the shared inline path and must not be
    advertised to authors). Stored **raw** (not HTML) and escaped at render; math is
    typeset client-side by the existing KaTeX path (see the `math.js` touch-point in
    Rendering). No nh3 sanitisation is needed
    because the value is never rendered as HTML — it is emitted inside a text node
    (autoescaped) and only KaTeX interprets the math delimiters. (Contrast Spoiler
    /Callout, which store sanitised HTML `body` fields.)

**Why a child model, not a JSON list.** Both patterns exist in the codebase
(Gallery uses a JSON `data` field; Matrix/Switch-grid/Match-pairs use child models
+ formsets). Steps are plain strings with **no** cross-references or linkage, so a
child model is trivial (`order` + `content`, no temp-id column mapping like Matrix)
and gives the editor a standard Django `inlineformset_factory` with add/remove — no
bespoke JSON-serialising editor JS. The child model is the lower-complexity choice
here. (Step **order is the formset row order**; there is no drag-to-reorder in v1 —
YAGNI. Authors reorder by editing row contents; an author-facing reorder control can
be a later refinement.)

**Chosen `content` cap and step count.** `content` is `max_length=500` (a single
inline fragment, generous for math source). A stepper requires **at least 1 step**
to be meaningful and is capped at a sane maximum (`MAX_STEPS = 20`, mirroring
Gallery's ceiling) to bound the editor formset and render. `MIN_STEPS = 1`.
`MIN_STEPS`/`MAX_STEPS` are **module-level constants** (like the `500` cap) imported
by both the formset `clean()` and `VALIDATORS['stepper']`, so the two paths cannot
drift to divergent literals.

**Whitespace normalization.** Surviving step `content` is **stripped** (parallel to
`prompt`) so the editor and import paths behave identically — either in
`StepperStep.save()` or when `save_element`/the builder writes rows. A step of
`"  x  "` is stored as `"x"`; the blank/normalize test covers both the drop-blank
and the strip behavior.

**Migration.** The two new models require a new `courses` migration (create
`StepperElement` + `StepperStep`); `ELEMENT_MODELS` also gains `"stepperelement"`.
CI's `makemigrations --check` must pass (no un-generated migration) — this is a
required touch-point like the templates and JS wiring.

### Rendering (student view)

`StepperElement.render()` uses the base convention → `courses/elements/stepperelement.html`.
The template emits (illustrative — exact class names/markers may follow reveal-gate
conventions in implementation):

```
<div class="stepper" data-stepper>
  {% if el.prompt %}<p class="stepper__prompt">{{ el.prompt }}</p>{% endif %}
  <div class="stepper__line">
    {% for step in el.steps.all %}
      <span class="stepper__step" data-stepper-step>{{ step.content }}</span>
    {% endfor %}
    <button type="button" class="stepper__next btn btn--small" hidden data-stepper-next>{% trans "Show next" %}</button>
  </div>
</div>
```

The load-bearing invariants of this markup:

- **The server NEVER renders a step span with a `hidden` attribute.** Every step
  span is rendered visible and tagged `data-stepper-step`. This is the single
  authoritative rule; all step visibility after the first is controlled by JS +
  the arm-CSS described below, never by a server-set `hidden`. (Only the *button*
  is server-`hidden`, because a button is useless without JS — see below.)
- `{{ step.content }}` / `{{ el.prompt }}` are **autoescaped** (text nodes); KaTeX
  later scans the `.stepper` subtree and typesets the math delimiters. **This does
  NOT work for free:** `math.js`'s `renderInlineText()` scans a *hardcoded* class
  allowlist (`.el--text, .el--table, .el--gallery, .el--tabs, .fillgate`) — `.stepper`
  is not in it, so without a change step math renders as raw LaTeX. **Required
  touch-point:** add `.stepper` to the `renderInlineText()` selector in `math.js`
  (the explicit, low-coupling fix — preferred over borrowing the `el--text` class,
  which would also drag text-element styling onto the inline spans). A test asserts a
  step's inline math is typeset on the lesson page.
- The **button is rendered `hidden` and un-hidden by JS** (`data-stepper-next`). A
  button that reveals steps does nothing with JS off, so with no JS it correctly
  stays hidden (no dead control) while every step remains visible.
- Button class is **`btn btn--small`** (the established element-button convention;
  `ks-button` does not exist in this codebase), plus `stepper__next`.

**Visibility is a two-layer mechanism.** There are two distinct concerns —
*post-boot stepping* (what makes it step, everywhere) and *pre-boot anti-flash* (a
lesson-only polish). Both layers key on the same `:not(.stepper-shown)` selector, so
they never disagree about which steps are visible.

- **Layer B — post-boot stepping state (everywhere, incl. the editor preview).**
  `courses.css` carries the authoritative hide rule keyed on a container class the
  JS adds: `.stepper.is-stepping [data-stepper-step]:not(.stepper-shown){display:none !important}`.
  `stepper.js`, on init, adds `is-stepping` to the `.stepper` container **and**
  `stepper-shown` to step 0 in the same synchronous tick (so step 0 is never hidden,
  no `:first-child` guard needed here), then reveals further steps by adding
  `stepper-shown`. Because this rule lives in `courses.css` (loaded on both the
  lesson page and the editor), **the editor preview genuinely steps** — this is what
  resolves the "preview can't demonstrate reveal" gap. With JS off/broken,
  `is-stepping` is never added, so every step stays visible (fail-open by
  construction — no watchdog needed for this layer).

- **Layer A — pre-boot anti-flash (lesson page only).** Without this, a worked
  solution would *flash all steps (including the answer) then collapse to step 1*
  before `defer`red JS boots — pedagogically bad (it spoils the answer). So
  `lesson_unit.html` (under `{% if has_stepper %}`) adds a render-blocking
  `stepper-armed` class to `<html>` via an **inline script**, plus an inline CSS rule
  `.stepper-armed .stepper [data-stepper-step]:not(.stepper-shown):not(:first-child){display:none}`
  (the `:first-child` guard keeps step 1 visible before JS marks it shown). A
  **DOMContentLoaded watchdog** removes `stepper-armed` when `window.__stepperBooted`
  is falsy (script blocked/broken) so a broken-JS client falls open to all-visible —
  this is `__stepperBooted`'s consumer. Because the arm class is added *by an inline
  script*, a fully-JS-off client never arms at all. Once JS boots, Layer B's
  `is-stepping` becomes the operative rule and Layer A staying armed is harmless
  (both hide the exact same `:not(.stepper-shown)` set).

- **The server-render invariant** underpins both layers: every step is rendered
  visible, so with JS fully disabled the entire worked chain is readable — the no-JS
  goal. Only the two CSS layers above ever hide a step, and both are gated on a
  client-side class that a no-JS client never receives.

### Reveal behavior (JS — `courses/static/courses/js/stepper.js`)

A **new, small, standalone enhancer** — it does **not** reuse
`window.libliRevealCascade`. The cascade walks *scope-level following siblings*
(`[data-tab-panel], .slide`) and is purpose-built for the sibling-block gate; the
stepper's reveal is entirely **intra-element** (reveal the element's own next step
span). It does, however, follow reveal.js's conventions: eager
`window.__stepperBooted = true` at parse time (read by the watchdog above), an
idempotent `data-stepperReady` guard, and a `window.libliInitStepper(root)` entry
point re-runnable over the editor preview pane.

Per `[data-stepper]` element, on init (idempotent):

1. Mark ready (`dataset.stepperReady`); return early if already ready.
2. Collect the ordered step spans (`[data-stepper-step]`) in document order and
   the button (`[data-stepper-next]`).
3. In the same synchronous tick, add `stepper-shown` to step index 0 (the first)
   **and** `is-stepping` to the `.stepper` container (Layer B) — so the CSS hides
   indices ≥ 1 (which lack `stepper-shown`) while step 0 is never hidden. Un-hide the
   button (`button.hidden = false`) **only if** there is at least one not-yet-shown
   step; a single-step stepper keeps the button hidden (nothing to reveal) and does
   not add `is-stepping` (or adds it harmlessly — with one step there is nothing to
   hide).
4. On button click: reveal the next not-yet-shown step (add `stepper-shown`), move
   focus to it (`tabindex=-1`), and when the last step is revealed, hide the button
   again (`button.hidden = true`). No `libli:reveal` dispatch — steps hold only
   inline text/math, never a gallery/tabs that would need a re-measure signal
   (unlike the sibling cascade, whose revealed blocks can contain such enhancers).

Note the post-boot visibility mechanism is the single `stepper-shown` class (mirroring
reveal-gate's `reveal-shown`), gated by the `is-stepping` container class — NOT a
`hidden`-attribute toggle on steps — so there is exactly one rule governing which
steps show, and it never conflicts with the server render.

**Lesson-page boot (load-bearing).** `stepper.js` **self-invokes
`window.libliInitStepper(document)` on boot** (at parse-end, like `reveal.js`'s
trailing `initRevealGates(document)`) — this is the trigger that adds `is-stepping` +
`stepper-shown` on the actual lesson page. Without it, the arm CSS would hide steps
≥1 with nothing ever revealing them and `__stepperBooted` still true (watchdog would
NOT fail open) — a permanently truncated chain, strictly worse than JS-off. A test
asserts a stepper-bearing lesson page, after boot, shows step 0 + the button.

`window.libliInitStepper(root)` enhances every `[data-stepper]` under `root`
(default `document`), idempotently. Wired into:

- **`editor.js`** — re-run `window.libliInitStepper(preview)` after each fragment
  swap, next to the existing `libliInitGallery`/`libliInitTabs`/`libliInitRevealGates`
  re-inits. Because Layer B's `is-stepping` rule is in `courses.css` (loaded in the
  editor), the preview genuinely steps — clicking "Show next" reveals the next step.
- **`editor.html`** — add `<script src="{% static 'courses/js/stepper.js' %}" defer></script>`.
  **This is the step historically missed twice (gallery, reveal-gate shipped with a
  dead preview because editor.html never loaded the enhancer).** A test GETs the
  editor page and asserts the `stepper.js` script tag is present.
- **`lesson_unit.html`** — the lesson page does **not** load enhancers
  automatically; each type has an explicit `{% if has_<type> %}` block (see the
  existing `has_reveal_gate` / `has_switch_gate` / `has_fill_table` blocks). Add,
  gated on `{% if has_stepper %}`: (a) the `<script src="{% static 'courses/js/stepper.js' %}" defer></script>`
  include alongside the other enhancer scripts, and (b) the inline `stepper-armed`
  arm script + the arm CSS rule + the `__stepperBooted` DOMContentLoaded watchdog
  described in the No-JS section (patterned on the existing `reveal-armed` block).
  A test asserts the `stepper.js` tag appears on a stepper-bearing lesson page
  (parallel to the editor.html test — this wiring is exactly the twice-missed kind).

### Editor (authoring)

The parent form is **`StepperElementForm(ModelForm)`** (fields: `prompt`), registered
as **`FORM_FOR_TYPE["stepper"]`** in `element_forms.py` — the dispatch `element_add`
and `save_element` both use. A registration test asserts
`FORM_FOR_TYPE["stepper"] is StepperElementForm` (as sibling specs do for `callout`
etc.).

The steps are a **`StepperStepForm`** (`content`) inline formset. **Critical
touch-point — the formset is not built automatically:** the shared host-form render
helper in `views_manage.py` (used by BOTH `element_add` and the edit render) builds
each child-model formset in an explicit **per-type branch** (see the existing
`matchpairquestion`/`choicegridquestion` branches); without a `stepper` branch the
`formset` context stays `None` and `_edit_stepper.html` renders **no step rows and no
management form** — a silently broken, non-authorable editor that a bare "returns
200" test would NOT catch. Add a `stepper` branch (a `build_stepper_formset` factory)
seeded from `form.instance if form.instance.pk else None`, mirroring the sibling
child-model blocks.

`_edit_stepper.html` is the edit-form partial `_host_form.html` includes for the
`stepper` type (**required — a missing partial 500s `TemplateDoesNotExist` the
instant the palette card is clicked**). It renders:

- the `prompt` field (a single text input, math-authoring-capable like other
  text+math fields), and
- the **inline formset** of steps (one `content` text input per row) with add/remove
  controls, using the standard formset management-form + clone-`__prefix__` JS
  pattern already used by the child-model editors. Field names in the partial must
  match the form/formset field names.

Field names in the partial must match the form's field names. The formset uses
`extra` sized so a fresh add starts with one blank step row. The `MIN_STEPS`/`MAX_STEPS`
count check runs in a **custom `BaseInlineFormSet.clean()`** over the **surviving
(non-blank, non-deleted)** rows — deliberately NOT via `inlineformset_factory`'s
`max_num`/`validate_max`, which count *raw submitted* forms (including blank extras)
and would disagree with the drop-blank rule at the boundary. Step **order is
determined by row position** in the submitted formset — no reorder widget in v1;
`save_element` assigns each surviving step's `order` to its 0-based position.

### Styling (`courses/static/courses/css/courses.css`)

The element ships styled (per the project's "every view ships styled" rule); the
persistent rules live in `courses.css` alongside the other element styles:

- **Inline flow + wrap:** `.stepper__line` is a flex row with `flex-wrap: wrap` and
  a small `gap`, so revealed fragments flow left-to-right and wrap on narrow
  viewports. The `gap` (M5) is the sole inter-fragment separation — the fragments do
  not butt together and the template does not rely on whitespace-between-tags.
- **Layer-B hide rule (in `courses.css`):**
  `.stepper.is-stepping [data-stepper-step]:not(.stepper-shown){display:none !important}`
  — the authoritative post-boot rule, loaded on both lesson and editor pages so the
  editor preview steps.
- **`[hidden]` override (load-bearing):** a codebase-confirmed pitfall is that any
  element given a non-default `display` overrides the UA `[hidden]{display:none}`
  rule (see `.filltable__confirm[hidden]{display:none !important}`,
  `.dnd__rows[hidden]`). The button is a `btn btn--small` (likely `inline-flex`), so
  an explicit **`.stepper__next[hidden]{display:none !important}`** rule is required
  or the button won't hide after the last step / in the no-JS view. (Steps use the
  `stepper-shown`/`is-stepping` classes, not `[hidden]`, so they need no such rule.)
- **Arm CSS location (Layer A):** the render-blocking
  `.stepper-armed .stepper [data-stepper-step]:not(.stepper-shown):not(:first-child){display:none}`
  rule lives **inline** in the `{% if has_stepper %}` block in `lesson_unit.html` (so
  it is render-blocking and scoped to pages that need it), mirroring the existing
  `reveal-armed` inline CSS — NOT in `courses.css`.
- **Prompt:** `.stepper__prompt` gets modest lead-in styling (muted, slightly
  smaller) consistent with other element intros.
- Verify appearance in **light and dark** themes (screenshot check), per the
  established styling DoD; run `frontend-design` if the default styling reads as
  templated.

## Data flow

**Authoring (create/edit):**

1. Author clicks the **Step-by-step** card in the Interactive group of
   `_add_menu.html` (lesson units only — the whole Interactive group is hidden when
   `unit_is_quiz`).
2. `element_add` (`stepper` in its allow-tuple) renders `_host_form.html` →
   `_edit_stepper.html` with an empty `StepperElement` form + step formset.
3. `save_element` (`stepper` in its type dispatch) binds the `StepperElement` form
   and the step formset, validates, and on success saves the parent then the child
   steps, assigning each surviving step's `order` to its 0-based row position.
   (`element_add`/`element_save` are the view functions; `manage_element_add` etc.
   are their URL names — see Testing.)
4. Editor preview re-renders the saved element; `editor.js` re-runs
   `libliInitStepper(preview)` so the preview shows the stepping behavior.

**Consumption (lesson):**

1. `build_lesson_context` sets a `has_stepper` flag so the lesson template loads
   `stepper.js` + the arm block. **Use the FLAT query form**
   `node.elements.filter(content_type__model="stepperelement").exists()` — NOT the
   `parent__isnull=True` top-level scan — mirroring `has_reveal_gate`/`has_switch_gate`
   (whose in-code comment is exactly "NOT scoped to `parent__isnull=True` so a gate
   nested inside a tab is still detected"). Since the stepper is nestable in tabs,
   the scoped form would silently fail to load `stepper.js` when the only stepper is
   inside a tab, so it would never step. A test asserts a stepper **nested in a tab**
   still sets `has_stepper`. Because steps carry math, the has-math scan must also
   include stepper content so KaTeX loads and typesets it — wired via the existing
   `_element_has_math` helper (the stepper branch returns True when any step
   `content` or the `prompt` contains a math delimiter; `_tabs_has_math` already
   recurses through `_element_has_math`, so a tab-nested stepper's math is covered).
   (Stepper is **not** a question, so the question-side
   `_question_has_math`/`question.js` path is not involved.)
2. The unit renders each element via `Element.render()` → `stepperelement.html`.
3. `stepper.js` self-boots (`libliInitStepper(document)`): it marks step 0
   `stepper-shown` and adds `is-stepping` (the CSS then keeps steps ≥1 hidden until
   revealed), un-hides the button, and drives the walk. JS only ever *adds* classes
   — it never sets `hidden`/`display` on a step span.

**Nesting in tabs.** The stepper is nestable inside a Tabs element. Its transfer
key `stepper` is added to `NESTABLE_TYPE_KEYS`. Because the form key and transfer
key are the **same** string (`stepper`), **no `_NESTABLE_FORM_KEY_ALIASES` entry is
added** — that alias map exists only for types whose form key differs from their
transfer key. The nestable-consistency test asserts the standing invariant
`NESTABLE_TYPE_KEYS ⊆ SERIALIZERS` (every nestable key has a serializer) and that a
stepper can be added inside a tab. Rendered inside a tab panel, the enhancer still
works: its reveal is intra-element and independent of the tab scope.

## Transfer (export / import)

The stepper joins the transfer trio with snake_case transfer key `stepper`
(distinct from, but here equal to, the form key):

- **`SERIALIZERS['stepper']`** — emits `{"prompt": <str>, "steps": [<str>, ...]}`
  (ordered step contents).
- **`VALIDATORS['stepper']`** — validates shape and bounds so a corrupt archive
  raises a clean validation error, never a 500 at model save or a `KeyError`:
  - **Missing keys:** an absent `prompt` key is valid and defaults to `""` (matches
    the model's `blank=True`); an absent or `None` `steps` key is a clean validation
    error (a stepper with no steps is invalid). The validator must not index either
    key without a presence check.
  - `prompt` (when present) is a string **and ≤ 500 chars** (bounds-checked — an
    over-long prompt must be rejected here, not left to fail at the Postgres
    `varchar(500)` DataError).
  - `steps` is a list of **non-blank** strings (blank/whitespace-only entries are
    rejected on import, matching the editor's drop-blank + `MIN_STEPS` rule — import
    must not create a state the editor forbids), with count in
    `MIN_STEPS`..`MAX_STEPS`, each ≤ 500 chars.
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
- **Render (student):** **no step span carries a server-side `hidden` attribute**
  (the load-bearing invariant) — every step is rendered visible and tagged
  `data-stepper-step`; the button is rendered `hidden` with `btn btn--small`; prompt
  shown only when non-blank; content autoescaped; a `<script>`-y step is escaped
  (negative XSS assert).
- **No-JS completeness:** with the server render (no JS), every step span is
  present and visible (server does not hard-hide steps) — the full chain is
  readable.
- **has_stepper / has_math:** a stepper-bearing unit sets `has_stepper` (flat query)
  and, when a step/prompt has math, triggers the math typesetter load (via
  `_element_has_math`). **A stepper nested inside a tab still sets `has_stepper`**
  (the flat-query regression guard) and its math is detected via `_tabs_has_math`.
- **Inline math typeset (math.js):** on a lesson page, a step containing `\(...\)`
  is typeset (not shown as raw LaTeX) — the guard for the `.stepper` selector
  addition to `renderInlineText()`.
- **Editor authoring path:** GET **and** POST `manage_element_add` for `stepper`
  returns 200 (covers `element_add` → `_host_form` → `_edit_stepper` render — the
  path historically left untested). The GET add-render asserts a **blank step row +
  the formset management form are present** (not merely HTTP 200 — a `formset=None`
  render would 200 with an empty, non-authorable editor). Editing an existing stepper
  re-seeds the step formset. Formset enforces MIN/MAX and drops blank rows.
- **Form registration:** `FORM_FOR_TYPE["stepper"] is StepperElementForm` (mirrors
  the sibling element registration tests).
- **editor.html script tag:** GET `manage_editor` asserts the `stepper.js` `<script>`
  tag is present (guards the twice-missed wiring).
- **lesson_unit.html script tag:** GET a stepper-bearing lesson page asserts the
  `stepper.js` `<script>` tag AND the `stepper-armed` inline arm block are present
  (guards the lesson-side twice-missed wiring — I4).
- **Nestable:** `stepper` in `NESTABLE_TYPE_KEYS`; the nestable-consistency
  invariant (`NESTABLE ⊆ SERIALIZERS`) holds; a stepper can be added inside a tab.
- **Transfer round-trip:** export → import of a stepper preserves prompt + ordered
  steps; a corrupt payload is rejected by the validator (no 500). Explicit cases:
  an over-long `prompt`, a blank/whitespace step, an over-`MAX_STEPS` list, a
  payload **omitting `prompt`** (valid → `""`), and a payload **omitting `steps`**
  (clean validation error, not `KeyError`). `ELEMENT_MODELS` count assertion updated
  to 27.
- **e2e:** on a lesson page, after JS boot only step 0 + the "Show next" button are
  visible (steps ≥1 hidden — confirms the self-boot + arm actually engaged, C1),
  then clicking "Show next" reveals steps one at a time and the button disappears
  after the last step (drive the real click, not `page.evaluate`). Also verify the
  **editor preview** steps (Layer B in `courses.css`).
- **i18n:** "Show next" and the label "Step-by-step" have real Polish translations;
  PO catalog stays clean (no fuzzy/obsolete entries).
