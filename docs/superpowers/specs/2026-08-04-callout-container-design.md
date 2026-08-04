# Callout container

## Purpose

Make `CalloutElement` a container so a table (or an image, or math laid out as a
table) can be nested inside a callout, and fix the reachability defect in
`SpoilerElement`'s dual-shape render — in one branch, so both elements end up
behaving identically for a content author.

This is slice B2 of the 2026-08-01 nesting request. Slice B1 (depth-3 nesting)
shipped as PR #209.

### Problem 1 — a callout cannot hold anything

`CalloutElement` is a leaf: `kind`, `heading`, `body`, and no child slot. Confirmed:

- `courses/builder.py:89` — `_CONTAINER_REGISTRY` holds only `TabsElement`,
  `TwoColumnElement`, `SpoilerElement`.
- `courses/builder.py:31` — `CONTAINER_TRANSFER_KEYS = {"tabs", "two_column", "spoiler"}`.
- `resolve_scope` rejects a callout parent at `courses/builder.py:147` with
  `"parent is not a container"`.

`"callout"` *is* already in `NESTABLE_TYPE_KEYS`, but that is the other direction: a
callout may be a **child** of a container; nothing may be its child.

There is no workaround through the rich-text editor — `ALLOWED_TAGS` in
`courses/sanitize.py:14` has no `table`/`tr`/`td`, so a pasted table is stripped from
the body on save.

The code anticipated this work by name at `courses/builder.py:28`:

> `PR2 (Callout as a container) must add its key to THIS set, to _CONTAINER_REGISTRY`
> `and to payloads._CONTAINER_SLOT_KEY -- all three.`

**That comment is incomplete and must not be treated as the change set.** Three
further sites are model- or type-dispatched rather than registry-driven and each
needs its own edit; they are enumerated in "Change set" below.

### Problem 2 — a spoiler's body becomes unreachable once it has children

`SpoilerElement` carries both a legacy rich-text `body` and children. Two independent
mechanisms strand the body:

- `templates/courses/elements/spoilerelement.html:7` —
  `{% if children %} … {% elif el.body %}` — the body is **not rendered** when
  children exist.
- `courses/element_forms.py:224-230` — `SpoilerElementForm.__init__` pops `body` from
  the form when `instance.resolved_children()` is non-empty, so the body is **not
  editable** either. The template still references `{{ form.body.value }}`, which
  resolves silently to empty on a form lacking the field, so the RTE renders blank
  with no error.

Text entered *before* a child is added therefore becomes invisible on the page,
invisible in the editor, and impossible to edit or delete through any UI. The only
hint is the editor empty-state at
`templates/courses/manage/editor/_element_row.html:189`, which fires only when there
are **no** children — never in the broken state.

The `fields.pop` was protective in intent ("so a save can never blank it"), but it
protects data nobody can reach.

## Measured evidence

Read-only queries against local `libli` (the dev DB the checkout points at) and
`libli_mat` (the mat-pp snapshot), plus a headless-Chromium render of live `mat-pp`
content. Recorded so implementation need not re-derive them.

### Spoilers in the body+children state

| DB | spoilers | with body | with children | body **and** children |
|---|---|---|---|---|
| `libli` | 1359 | 14 | 1292 | **2** |
| `libli_mat` | 1348 | 0 | 1347 | **0** |

Both affected rows are in course `mat-pp`, unit node 1094:

- `SpoilerElement` pk **1395** — body `<br>` (4 bytes), 2 children.
- `SpoilerElement` pk **1396** — body 544 bytes of real content, 1 child.

**pk 1396's child `TextElement` pk 13818 is a byte-identical copy of the stranded
body.** No content is currently missing from the rendered page; the body is dead
residue behind an identical child. The author hit the defect and worked around it by
re-creating the text as a child.

This is the sharp constraint on the fix: rendering the body above children **without
a cleanup migration would make spoiler 1396 display the same explanation twice**.

Classification under the rule the migration will use:

```
1395 -> A: EMPTY-ISH (safe to clear)
1396 -> B: EXACT DUPLICATE of a child (safe to clear)
```

Zero rows are category C (genuinely stranded, non-duplicate content). Because
production has not yet taken the mat-pp cutover, the shapes *not* observed locally
are the ones the predicate must still handle — see "Cleanup migration".

### Math already renders in callouts and table cells

Rendered with a real session against `libli`. `.katex-error` counts DOM nodes
irrespective of visibility, so a collapsed `<details>` cannot hide a failure from it.

| Unit | Content under test | `.katex` | `.katex-error` |
|---|---|---|---|
| 171 | `CalloutElement` 86 — `\begin{align*}` split across `<p>` by the RTE | 2 | 0 |
| 198 | `CalloutElement` 113 — unsplit `\[ \begin{align*}` | 7 | 0 |
| 200 | `CalloutElement` 115 | 12 | 0 |
| 917 | `TableElement` 275/276 — `\begin{` inside cells | 190 (12 within one `<table>`) | 0 |

Callout 86 is verbatim the `a^n\cdot a^k` example from the original request and it
typesets correctly. **The math half of the original request is already closed** by PR
#206/#208; this slice adds no math-*rendering* work. It must, however, keep KaTeX
*armed* for the new nesting shapes — see "Error handling".

Note *why* a callout body typesets today: `.callout__body` carries the class
`el el--text callout__body`, and `.el--text` is in `math.js`'s `renderInlineText`
selector list. `.callout__heading` is not, and is outside that div — which is what
makes C4 below load-bearing.

## Decisions

### D1 — Body renders above children; both stay editable

For **both** `SpoilerElement` and `CalloutElement`: when `body` is non-empty it
renders first, then children below. `body` is always present in the edit form.

Governing principle: content a CA enters must remain reachable. Preserving the
current either/or would have propagated the defect into the new element.

Rejected — *children only, body auto-converted to a leading Text child*: a cleaner
single mental model, but it concentrates cost in the riskiest place (a content data
migration plus importer back-compat for `body` in every previously exported archive)
and turns a one-line spoiler into a two-step add. Still available later.

Accepted cost: `body` is a privileged first block that cannot be reordered or deleted
like a child, and prose *after* a nested table still requires a Text child — so there
are two ways to write prose in one box.

### D2 — Callout is a single-slot container, mirroring Spoiler

Not a new mechanism. `SpoilerElement` is already a single-slot container
(`SLOT_ID = "only"`); that substrate is reused verbatim.

### D3 — A callout consumes a nesting level

A callout counts as a container everywhere the depth rules apply. Under
`MAX_NEST_DEPTH = 4`, `spoiler > tabs > callout > table` is legal;
`spoiler > tabs > spoiler > callout` is not.

Rejected — *exempting callouts from the depth count*: needs a genuinely new rule in
`resolve_scope` **and** its transfer twin in `payloads.py`, which is precisely the
pair where a divergence stays invisible until an import.

### D4 — Callout-in-callout is allowed

Falls out of the existing allowlist at no code cost and keeps every container
uniform. Blocking it would need a per-type exclusion no other container has,
duplicated across the write and import paths. It also *forces* the same-type nesting
fixture PR #209 identified as the gap a fixture monoculture hides.

### D5 — One branch

No live content loss exists, so there is no urgency argument for splitting. Shipping
together guarantees the two elements land with identical semantics rather than
diverging for a release.

## Change set

Registry membership alone does **not** make a callout a working container. Four
dispatch sites are hard-coded by model or type and each needs its own edit. Three of
the four are JS/CSS-seam changes — exactly the class of defect PR #209 shipped
because the diff contained no JS/CSS files.

| # | Site | Why registry membership is not enough |
|---|---|---|
| 1 | `courses/builder.py` — `_CONTAINER_REGISTRY`, `CONTAINER_TRANSFER_KEYS` | registry, see below |
| 2 | `courses/transfer/payloads.py` — `_CONTAINER_SLOT_KEY` + the single-slot constant | registry + a hard-coded `SpoilerElement.SLOT_ID` |
| 3 | `courses/transfer/export.py` — `walk_unit_joins`'s inner `emit()` | explicit `isinstance` ladder; docstring says **"NOT registry-driven"** |
| 4 | `templates/courses/manage/editor/_add_menu.html` | the Callout card is unguarded; clause 4 now applies to it |
| 5 | `courses/static/courses/js/reveal.js` + `templates/courses/lesson_unit.html` | `scopeOf` and the pre-hide CSS both enumerate scopes literally |
| 6 | `courses/static/courses/js/math.js` | `renderInlineText` enumerates selectors literally |
| 7 | `courses/static/courses/css/editor.css` | per-container editor-row rules are enumerated literally |

### 1 — builder registries

| Location | Change |
|---|---|
| `_CONTAINER_REGISTRY` | `CalloutElement: (lambda _data: {"slots": [{"id": CalloutElement.SLOT_ID}]}, "slots", "id")` |
| `CONTAINER_TRANSFER_KEYS` | add `"callout"` |

`courses/tests/test_nesting_rule.py:283-286` asserts the registries agree, which is
what stops the change landing in some but not all of them.
`NESTABLE_TYPE_KEYS` already contains `"callout"` — no change; children permitted
inside a callout are exactly the existing nestable set. `resolve_scope`'s
`getattr(parent_obj, "data", None)` at `courses/builder.py:161` already handles a
container with no `data` field — the shape Callout has.

### 2 — the single-slot constant must be shared, not coincidental

`_CONTAINER_SLOT_KEY` gains `"callout": None`. But when `slot_key is None`,
`validate_nesting` computes `valid_slot_ids = {SpoilerElement.SLOT_ID}` — a literal
reference to the **spoiler's** constant (`courses/transfer/payloads.py:788-792`,
imported at `:768`). A callout child would validate only because both classes
independently spell `"only"`.

That is a write/import divergence waiting to happen: the write path validates against
`CalloutElement.SLOT_ID`, the import path against `SpoilerElement.SLOT_ID`. Introduce
a single shared constant (e.g. `SINGLE_SLOT_ID` on a common home, with both models
referencing it) or a mapping from transfer key to the owning model's `SLOT_ID`, and
pin it with a test asserting the two are the *same* value by construction, not equal
by luck. Update the now-false comment at `payloads.py:750-752`.

### 3 — the export walk

`walk_unit_joins`'s inner `emit()` (`courses/transfer/export.py:507-523`) is an
explicit ladder over `TabsElement` / `TwoColumnElement` / `SpoilerElement`. Callout
children are excluded from the `parent__isnull=True` root query, so without a fourth
arm they are visited by nothing and **silently vanish from every export**:

```python
elif isinstance(obj, CalloutElement):
    for child in obj.resolved_children():
        yield from emit(child, join, CalloutElement.SLOT_ID)
```

The export → import round-trip test is what falsifies its absence.

### 4 — the palette card must be guarded

Adding `"callout"` to `CONTAINER_TRANSFER_KEYS` arms clause 4
(`courses/builder.py:168-171`), which rejects a callout child whenever
`parent_depth >= MAX_NEST_DEPTH - 1`. The Callout card at
`templates/courses/manage/editor/_add_menu.html:38` is rendered unguarded, while
Tabs (`:39`), Columns (`:40`) and Spoiler (`:50`) each carry
`{% if depth < max_nest_depth|add:-1 %}`.

Left unguarded, the editor offers Callout inside a depth-3 slot and every click
returns HTTP 400. Wrap the card in the same guard and update the partial's comment at
`:16-17`, which currently states the premise this slice invalidates ("Callout is a
plain LEAF in this slice and stays unguarded"). Pin a test that the Callout card is
absent from a depth-3 add-menu.

### 5 — the reveal cascade

`reveal_gate`, `fill_gate` and `switch_gate` are all in `NESTABLE_TYPE_KEYS`, so they
become legal callout children. Today:

- `scopeOf` is `btn.closest("[data-tab-panel], .slide, .spoiler__children, .spoiler")`
  (`courses/static/courses/js/reveal.js:51-52`). A gate inside a top-level callout
  resolves to `null` → `cascadeFrom` returns immediately → **dead button**. Inside a
  slideshow it resolves to `.slide` and cascades *out of* the callout across sibling
  lesson blocks.
- The pre-hide CSS at `templates/courses/lesson_unit.html:39-41` has exactly three
  selectors, none matching `.callout__child`, so gated content is **fully visible
  before the click** either way.

Add `.callout__children` to `scopeOf` (ahead of `.spoiler` for the same
nearest-match reason) and a fourth pre-hide selector:

```css
.reveal-armed .callout__children > .callout__child:has(> [data-reveal-gate]) ~ .callout__child:not(.reveal-shown)
```

`isGateWrapper` (`reveal.js:72-78`) needs no new branch — like `.tabs__child` and
`.spoiler__child`, a `.callout__child` wraps its gate directly, so it takes the
existing `:scope > [data-reveal-gate]` form. Extend
`courses/tests/test_reveal_gate_render.py`'s three-way agreement check to four.

### 6 — math.js must typeset the callout heading

PR #211's tab-label fix was two-sided: the label joined the has-math walk **and**
`.spoiler__toggle` joined `math.js`'s `renderInlineText` selector list
(`courses/static/courses/js/math.js:31`). `.callout__heading` is a `<span>` in
`.callout__header`, outside `.callout__body`, and matches nothing in that list.

Arming KaTeX off the heading without this leaves the heading showing raw `\(x^2\)` —
"the math renders" ≠ "the reader sees math". Add `.callout__heading` to the selector
list and pin it with an e2e assertion that a heading carrying `\(...\)` yields a
`.katex` node inside `.callout__heading`.

### 7 — editor.css

The editor branch below emits `el-row--callout` / `el-row__callout` markup.
`courses/static/courses/css/editor.css` has per-container rules only for the three
existing containers (`:821` tabs, `:827` `.el-row--spoiler .el-row__spoiler`, `:884`
two-column). Add the matching `.el-row--callout .el-row__callout` rule (mirroring the
spoiler's `margin-top: var(--space-3)`), and keep the class names in the template and
the CSS in agreement.

## Architecture / components

### Model — `CalloutElement`

Add, mirroring `SpoilerElement` (`courses/models.py:397-444`):

- `SLOT_ID` — the single implicit child slot, sourced from the shared single-slot
  constant of change-set item 2, not an independent literal.
- `join_row()` — this concrete's single `Element` join row.
- `resolved_children()` — ordered child join rows, `order_by("order", "pk")`, `[]`
  when the join row is transient.
- `render(*, element=None, state=None, slug=None, node_pk=None)`.

`render()` is genuinely new: `CalloutElement` has no `render()` today and reaches its
template through the generic path in `courses/templatetags/courses_extras.py`. It
already has `elements = GenericRelation(Element)`, which is what the join row needs.

**The context dict must be exactly these four keys plus `el`**, mirroring
`SpoilerElement.render` at `courses/models.py:432-444`:

```python
{"el": self, "children": self.resolved_children(),
 "element_state": state, "slug": slug, "node_pk": node_pk}
```

The rename `state` → **`element_state`** is load-bearing: the recursive
`{% render_element child %}` reads `context.get("element_state")`,
`context.get("slug")` and `context.get("node_pk")`
(`courses/templatetags/courses_extras.py:102-108`). Passing `state=state` to match the
kwarg name yields a callout whose nested stepper / mark-done / gate children render
with empty state and an empty save URL — a silent, 200-OK state loss. Pin it with a
test that a stateful child inside a callout receives its stored blob and a non-empty
state-save URL.

No new field, therefore **no schema migration** — only the data migration below.

### Render templates

`templates/courses/elements/calloutelement.html` — keep the header, then:

1. `{% if el.body %}` → the existing `.callout__body`.
2. `{% if children %}` → a single `.callout__children` wrapper holding one
   `.callout__child` per child.

`templates/courses/elements/spoilerelement.html` — change `{% elif el.body %}` to an
independent `{% if el.body %}` so both blocks can render; the existing
`.spoiler__children` wrapper is untouched (`scopeOf` and the pre-hide CSS both depend
on it).

The single wrapper is load-bearing, per PR #212: per-child borders cannot produce a
continuous left rule because child margins collapse through, leaving 16px holes.
`.spoiler__children` is also what the reveal cascade scopes to — `reveal.js`'s
`scopeOf`, the pre-hide CSS, and `courses/tests/test_reveal_gate_render.py` must
continue to agree (now four-way, per change-set item 5).

### Forms

`courses/element_forms.py:224-230` — delete the `fields.pop("body", None)` guard from
`SpoilerElementForm.__init__`. `CalloutElementForm` gains no equivalent guard.

### Editor

`templates/courses/manage/editor/_element_row.html` — a `calloutelement` branch
mirroring the `spoilerelement` branch at `:146-197`: the nested
`element-list--nested` `<ol>` recursing through `_element_row.html`, an empty-state,
and the add-menu include guarded by `{% if depth < max_nest_depth %}` with
`tab=obj.SLOT_ID`.

**Empty-state strings.** The spoiler branch has two, keyed on `obj.body`
(`:188-192`). Callout gets the same two-string shape. Exact English source strings, so
the translation round is a known quantity:

| Element | Condition | String |
|---|---|---|
| Spoiler | has body | `This spoiler shows its text above. Add an element below to nest more content.` |
| Spoiler | no body | `This spoiler is empty.` (unchanged) |
| Callout | has body | `This callout shows its text above. Add an element below to nest content inside it.` |
| Callout | no body | `This callout is empty.` |

The spoiler "has body" string is a **reword** — with the body now rendering, the old
"This spoiler shows saved text (edit it with the pencil)" described a hazard that no
longer exists. Three msgids change or appear, so the `.po` catalogs need regenerating
and a native Polish check (see `makemessages-fuzzy-prefills-wrong-translation` — the
fuzzy pre-fill trap fires reliably here).

The Callout palette card is guarded per change-set item 4.

### CSS

**Callout children.** `.callout` has `padding: var(--space-4)`
(`courses/static/courses/css/courses.css:1555-1563`), and **padding blocks margin
collapsing** — this is why `.callout__body > :first-child {margin-top:0}` and
`> :last-child {margin-bottom:0}` already exist at `:1589-1590`. The spoiler's
"margins collapse through, height unchanged" rationale does **not** transfer. So:

- `.callout__children > .callout__child:first-child > :first-child { margin-top: 0 }`
  and the `:last-child` mirror, matching the existing body pair.
- Separation when both render: `.callout__body + .callout__children { margin-top: var(--space-3) }`.
  Stated as a value, not as "unchanged height".

**Prose cap.** `.callout` is in the collapsed-TOC prose-cap allowlist at
`max-width: 46rem` (`courses/static/courses/css/courses.css:959-975`), whose own
comment names the hazard: *"a missed opt-out BREAKS layout (a squeezed table)"*. A
table is deliberately absent from that allowlist at top level, but a table nested in a
callout would inherit the cap and render narrower than the identical table outside
one — in the primary use case driving this slice. **Scope the cap to `.callout__body`
rather than `.callout`**, so prose stays capped and nested content does not. Pin with
a computed-width e2e assertion in the `unit-tree-collapsed` state.

**Spoiler combined shape.** `core/static/core/css/app.css:986-993` gives
`.spoiler__body` and `.spoiler > .spoiler__children` the same `padding-left` and 2px
left rule, but `.spoiler__body` additionally carries
`margin: var(--space-3) 0 var(--space-1) var(--space-3)`. The two shapes were mutually
exclusive until now, so nobody has seen them stacked: the both-present state D1
creates renders **two rules at different left offsets with a vertical gap** — breaking
the continuous-rule invariant PR #212 established. Required treatment:

```css
.spoiler__body:has(+ .spoiler__children) { margin-left: 0; margin-bottom: 0; }
.spoiler__body + .spoiler__children { margin-top: 0; }
```

so the two rules align and abut into one continuous line. The body-only shape keeps
its current indent. Pin with a computed-style e2e assertion that a body+children
spoiler shows a single continuous rule (equal `left` offsets, no vertical gap).

Per-kind accent handling is untouched. `editor.css` gains the row rule per change-set
item 7.

## Data flow

**Authoring.** The editor's add-menu POSTs `{type, unit, parent, tab}` to
`manage_element_add`. `resolve_scope(unit, parent_ref, tab, type_key)` loads the
parent join row (filtered by `unit`, which transitively enforces same-course), looks
the parent's model up in `_CONTAINER_REGISTRY`, translates the form key through
`_NESTABLE_FORM_KEY_ALIASES`, checks `NESTABLE_TYPE_KEYS`, validates the slot id
against the **non-destructive** normalizer's output, then applies the depth clauses.
For a callout the normalizer is the single-slot lambda and the only valid `tab` is
`"only"`. The new child is an `Element` row with `parent` = the callout's join row and
`tab_id = "only"`.

**Rendering.** `render_element` dispatches to `CalloutElement.render()`, which calls
`resolved_children()` and passes the four-key context above; the template recurses
through `render_element` per child, body first. `resolved_children()` costs
`join_row()` (one query) + the children query + one GFK prefetch query per distinct
content type — three or more, not one; do not write a query-count assertion against a
smaller number.

**Transfer.** Export descends the `resolved_*()` slot accessors via `walk_unit_joins`'s
`emit()` ladder (change-set item 3); delete descends `join.children`. That asymmetry
is deliberate and documented on both sides: `resolved_tabs()` runs the destructive
`normalize_data` and skips children whose `tab_id` matches no slot, so export omits
those on purpose while delete must not, or their concretes orphan. The existing
`_ser_callout` / `_val_callout` / `_build_callout` trio keeps `kind`/`heading`/`body`
unchanged, so old archives import unchanged and **no `FORMAT_VERSION` bump** is needed
(additive, exactly as the spoiler-nesting slice was).

**Import validation.** `payloads.py`'s `validate_nesting` is the transfer-side twin of
`resolve_scope`: it walks the parent chain, reads a container's slot list via
`_CONTAINER_SLOT_KEY` (membership tested *before* the lookup, since callout's value is
`None`), and applies the same depth clauses. Write/import clause parity is an exact
identity — import `depth == parent_depth + 1`, so `depth > 4 ⇔ parent_depth >= 4` and
`depth >= 4 ⇔ parent_depth >= 3`; only error *precedence* differs, never the outcome.
The single-slot id it validates against must come from the shared constant, not the
spoiler's (change-set item 2).

## Error handling

**Nesting violations.** `resolve_scope` raises `NestingError`, which the view turns
into HTTP 400. Unchanged for a callout parent: two un-numbered pre-checks (unknown
parent, parent-not-a-container) plus the four numbered clauses (disallowed child type,
unknown slot, too deep, container-too-deep). Adding `"callout"` to
`CONTAINER_TRANSFER_KEYS` is what arms clause 4 for it — and therefore what makes the
palette guard of change-set item 4 mandatory.

**`has_math` — two changes, both silent failures if missed.** A miss does not error;
KaTeX simply never loads and the math stays as raw source text. This is the
highest-risk item in the slice because its failure mode is invisible to any test that
only asserts a 200.

1. `courses/views.py:262-263` — `_spoiler_has_math` reads
   `if not children: return has_math_delimiters(el.body)`. Once the body always
   renders, a spoiler holding math **in its body and** children reports no math. The
   body must be OR'd in unconditionally.
2. `courses/views.py:202-203` — the existing `if isinstance(obj, CalloutElement)`
   branch **stays**, and its body becomes `return _callout_has_math(obj)`, mirroring
   how `_spoiler_has_math` is dispatched at `:200-201`. Do **not** also append callout
   to the trailing fallback chain at `:216-222` — that chain exists for the four types
   with no explicit branch, and adding a fifth entry would be permanently unreachable
   dead code.

`_callout_has_math` covers `heading`, `body`, and children, and self-guards with its
own `isinstance` check (returning `False` for a non-match) purely for symmetry with
its siblings — not because the fallback chain dispatches it. Including `heading`
is only correct together with change-set item 6; arming KaTeX for a heading that
`math.js` never visits produces raw LaTeX on screen.

**Malformed / tampered data.** `CalloutElement.save()` already coerces an unknown
`kind` to `example`. `resolved_children()` returns `[]` when the join row is
transient, so a mid-create callout renders its body and no child list rather than
raising.

### Cleanup migration

A `RunPython` data migration over `SpoilerElement` rows having both a non-empty `body`
and at least one child.

**Historical-model constraints.** `apps.get_model` returns models with fields but
**no custom methods** — `join_row()` and `resolved_children()` do not exist there, and
`Element` reaches its concrete only through a GFK. So the migration must:

- look up `ContentType` rows for `courses.spoilerelement` **and** `courses.textelement`
  itself;
- find each spoiler's join row via `Element.objects.filter(content_type=..., object_id=...)`
  and its children via `Element.objects.filter(parent=join, tab_id="only")` —
  with `"only"` **inlined as a literal**, never imported from the live model;
- write via `queryset.update(body="")`, **not** `.save()`, which would re-run
  `sanitize_html` over unrelated rows.

**Categories:**

- **A — empty-ish** → clear. Defined as an executable predicate, not prose:
  `strip_tags(body)` → `html.unescape(...)` → strip ASCII whitespace **and** U+00A0 →
  `== ""`. This must catch `<br>`, `<p><br></p>`, `<div>&nbsp;</div>` and a
  decoded-nbsp body; both `div` and `p` are in `ALLOWED_TAGS`, and the RTE's normal
  "empty" output is `<p><br></p>` or `<div><br></div>`, not a bare `<br>`. Only the
  bare-`<br>` shape was observed locally, so the predicate is doing real work on the
  unobserved prod shapes.
- **B — exact duplicate** → clear. `body` byte-identical to the `body` of one of its
  child `TextElement`s.
- **C — anything else** → **leave untouched**, so genuinely stranded content reappears
  above the children, which is the correct outcome.

Measured scope: `libli` 1×A + 1×B + 0×C; `libli_mat` 0. Reversible: the migration only
clears fields that were unreachable, and its reverse is a documented no-op.

`CalloutElement` needs no cleanup — it has no children today by construction.

## Testing

Beyond per-change unit tests, three things this slice must not repeat.

**The client-enhancer audit (the PR #209 lesson).** That slice shipped two defects —
`tabs.js` and `app.css` — that thirteen per-task reviews could not see, because the
implementation diff contained zero JS/CSS files, putting them outside every review
surface by construction. Both lived at the seam between "the server now permits X" and
"an untouched client enhancer assumes X is impossible."

Enumerate the newly-legal combinations in **both** directions and across **both**
kinds of child:

- *containers*: `callout` inside each of {`tabs`, `two_column`, `spoiler`, `callout`},
  and each of those inside `callout`;
- *leaves with client behaviour*: `reveal_gate`, `fill_gate`, `switch_gate`,
  `stepper`, `mark_done` inside a callout — these are the ones change-set item 5
  exists for, and restricting the audit to containers is what would miss them.

Then grep the client enhancers for unscoped `querySelectorAll` and descendant CSS
against each combination's own markup.

**A same-type fixture is mandatory.** PR #209's blindness root-caused to a fixture
monoculture: three tasks independently chose `tabs > spoiler > leaf`, so nothing in
the branch rendered a container inside a container of the same type. This slice must
include `callout > callout` and, for the fix, `spoiler > spoiler` where the outer has
a body.

**e2e, not render tests, for the cascade.** A Django render test is byte-identical
before and after a CSS-cascade defect and would be green under it. The nested callout
styling, the combined spoiler rule, and the reveal cascade need computed-style
assertions in a browser.

Cases to pin, each naming the mutant it kills (per `falsify-tests-not-run-them` — a
passing test that survives deleting the code it guards is vacuous):

| Case | Mutant it must turn RED |
|---|---|
| Spoiler with body **and** children renders both, in order | restore `{% elif el.body %}` |
| Spoiler edit form exposes `body` when children exist | restore `fields.pop("body", None)` |
| Spoiler with math in its **body** and a math-free child arms KaTeX | restore `if not children: return has_math_delimiters(el.body)` |
| Math in a table in a callout arms KaTeX | flatten `_callout_has_math` to `has_math_delimiters(obj.body)` |
| Callout heading with `\(...\)` yields `.katex` in `.callout__heading` | remove `.callout__heading` from `math.js` |
| Callout accepts a table child; `callout > callout` authorable | drop `CalloutElement` from `_CONTAINER_REGISTRY` |
| Table in a callout round-trips export → import | drop the `emit()` callout arm |
| Callout card absent from a depth-3 add-menu | drop the `{% if depth < max_nest_depth\|add:-1 %}` guard |
| Gate in a callout cascades and is pre-hidden | drop `.callout__children` from `scopeOf` / the 4th pre-hide selector |
| Stateful child in a callout gets its blob + save URL | pass `state=` instead of `element_state=` |
| Import validates callout slot via the shared constant | change one model's `SLOT_ID` and assert the other follows |
| `spoiler > tabs > callout > table` authorable; `spoiler > tabs > spoiler > callout` rejected | flip a depth clause comparison |
| Registry drift test passes with callout in all of them | add callout to two of the three |
| Migration: A, B and C rows — **C preserved** | broaden the predicate to clear C |
| Migration A predicate: `<p><br></p>`, `<div>&nbsp;</div>`, decoded-nbsp | narrow the predicate to a bare `<br>` |

Also extend `courses/tests/test_render_seam.py`'s `CONCRETES` list — described in-file
as "Every concrete `render()` the generic branch can reach" — with `CalloutElement`
**and** `SpoilerElement`, both currently absent, so the new override is covered by the
signature guard that exists for exactly this failure mode.

The cap-agreement trap from #209 applies here too — never monkeypatch a constant to
its real value; the test goes vacuous while still passing.

**Comment updates are part of the change set** (`comments-can-fail-tests`: at least
one test in this repo regexes raw source including comments). The change falsifies
`_add_menu.html:16-17` ("Callout is a plain LEAF in this slice and stays unguarded"),
`payloads.py:750-752` ("the only valid id is `SpoilerElement.SLOT_ID`"),
`builder.py:27-30` (the PR2 to-do, now done), and `_spoiler_has_math`'s docstring
("A nested spoiler has an empty body").

**Definition of done:** full non-e2e suite green serial, e2e green, `ruff` clean,
`makemigrations --check --dry-run` clean (the CI guard added in #204), `.po` catalogs
zero-fuzzy with the three changed/new msgids translated.

## Out of scope

- **Images in table cells** — the separate slice C, by widening the cell subset plus a
  media picker, not by making cells element slots.
- **Math rendering** — already works; measured above.
- **Elements nested inside a table cell** — dropped by agreement in the original
  decomposition.
- **The `sanitize_html` math-protection spec** — still deferred behind the mat-pp
  production cutover, unchanged by this slice.

## Risks

- **The duplicate-render hazard is the sharp edge.** Shipping D1 without the cleanup
  migration silently doubles content on any body+children row. The migration and the
  template change must land together.
- **Three of the seven change-set items are JS/CSS.** They are invisible to any test
  that asserts only server-rendered HTML, and they are the exact class PR #209 shipped
  broken. e2e coverage for them is mandatory, not preferred.
- **A `has_math` miss is silent.** No error, no bad status code — just unrendered math.
- A callout consuming a nesting level (D3) may surprise an author who thinks of it as
  a frame rather than a container. Accepted; the help documentation should say so.
- Three msgids change; the Polish fuzzy-prefill trap needs a native-speaker check.
