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

**That comment is incomplete and must not be treated as the change set.** Six
further sites are model- or type-dispatched rather than registry-driven — plus the
author documentation — and each needs its own edit; they are enumerated in "Change
set" below.

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

### Callout nesting depth today

Recursive walk of `courses_element.parent_id`:

| DB | depth 1 | depth 2 | depth >= 3 |
|---|---|---|---|
| `libli` | 71 | 12 | **0** |
| `libli_mat` | no callouts at all | — | — |

This measures the blast radius of D3a below: today `callout` is not in
`CONTAINER_TRANSFER_KEYS`, so clause 4 never fires for it and a callout is legally
authorable at depth 4 — and `_add_menu.html:38` actively offers the unguarded Callout
card at depth 3. **Zero such rows exist**, with two levels of headroom.

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

### D3a — Arming clause 4 is a breaking change for archives; accepted on measurement

Adding `"callout"` to `CONTAINER_TRANSFER_KEYS` makes
`payloads.validate_nesting`'s clause 4 (`payloads.py:810-814`) **reject** a callout at
depth 4 — a shape that is legal today. So the change is **not** purely additive:

- an existing archive containing a depth-4 callout becomes unimportable;
- `builder.duplicate_unit` round-trips through `build_export` -> `materialize_duplicate`
  -> `_run_import`, so duplicating any unit containing one would 422.

Editing and viewing are unaffected — `save_element` never re-runs `resolve_scope` on
the update path, and export itself does not validate. Only import and duplicate break.

**Accepted**, because the measurement above shows zero affected rows in either
database and two levels of headroom. Pin the behaviour with a test asserting the
import 422 for a hand-crafted depth-4-callout archive, so it is a decided outcome
rather than an accident. Do **not** claim "old archives import unchanged".

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

Registry membership alone does **not** make a callout a working container. **This
table is the single index of the change set** — every file this slice touches appears
here, pointing at the section that specifies it. Items 3–8 are the ones a registry-only
reading would miss, and 5–7 are JS/CSS-seam changes: exactly the class of defect PR #209
shipped, because its diff contained no JS/CSS files and so they fell outside every
review surface by construction.

| # | Site | Why it is in the change set | Specified in |
|---|---|---|---|
| 1 | `courses/builder.py` — `_CONTAINER_REGISTRY`, `CONTAINER_TRANSFER_KEYS` | the registries themselves | §1 |
| 2 | `courses/transfer/payloads.py` — `_CONTAINER_SLOT_KEY` + `SINGLE_SLOT_ID` | registry, plus a hard-coded `SpoilerElement.SLOT_ID` | §2 |
| 3 | `courses/transfer/export.py` — `walk_unit_joins`'s inner `emit()` | explicit `isinstance` ladder; docstring says **"NOT registry-driven"**. Also fixes `duplicate_unit` | §3 |
| 4 | `templates/courses/manage/editor/_add_menu.html` | the Callout card is unguarded; clause 4 now applies to it | §4 |
| 5 | `courses/static/courses/js/reveal.js` + `templates/courses/lesson_unit.html` + `core/static/core/css/app.css` | `scopeOf`, the pre-hide CSS and the `@media print` revert are **three** literal scope lists | §5 |
| 6 | `courses/static/courses/js/math.js` | `renderInlineText` enumerates selectors literally | §6 |
| 7 | `courses/static/courses/css/editor.css` | per-container editor-row rules are enumerated literally | §7 |
| 8 | `docs/help/course-admin/content-editors{,.pl}.md` + `interactive-elements{,.pl}.md` | both state "the three container types"; the quiz add-menu paragraph and the Spoiler section are also falsified | Author documentation |
| 9 | `courses/models.py` — `CalloutElement` | `SLOT_ID`, `join_row()`, `resolved_children()`, a new `render()` | Model |
| 10 | `templates/courses/elements/calloutelement.html` | body block + `.callout__children` wrapper | Render templates |
| 11 | `templates/courses/elements/spoilerelement.html` | body block **moved above** children | Render templates |
| 12 | `courses/element_forms.py` | delete the `fields.pop("body")` guard | Forms |
| 13 | `courses/views.py` | `_callout_has_math` + the `_spoiler_has_math` body OR | Error handling |
| 14 | `templates/courses/manage/editor/_element_row.html` | the `calloutelement` branch + reworded empty-states | Editor |
| 15 | `courses/static/courses/css/courses.css` | `.callout__children`/`__child`, the prose-cap narrowing, the `.katex` heading reset | CSS |
| 16 | migration `courses/migrations/00XX_*.py` | the `RunPython` body cleanup | Cleanup migration |

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
`CalloutElement.SLOT_ID`, the import path against `SpoilerElement.SLOT_ID`. **Chosen
design:** a single shared `SINGLE_SLOT_ID` constant that both models reference — one
design, not "either a constant or a mapping", so the pinned test below is unambiguous.

`SINGLE_SLOT_ID` lives at **module level in `courses/models.py`** — not in
`payloads.py`, which would make `courses/models.py` import from `courses.transfer`,
which imports `courses.models`: a circular import. `validate_nesting` picks it up
through the lazy in-function `from courses.models import …` it already uses at
`payloads.py:768`. It reads `SINGLE_SLOT_ID` **directly**, and both models set
`SLOT_ID = SINGLE_SLOT_ID`. Under this design drift is structurally impossible — there
is exactly one object — which is the point.

**Pinning this needs care, because two obvious tests are both vacuous:**

- `CalloutElement.SLOT_ID is SpoilerElement.SLOT_ID` — `"only"` is identifier-shaped,
  so CPython interns it at compile time and two classes that *independently* write
  `SLOT_ID = "only"` yield the **same object**; `is` returns `True` under exactly the
  divergence this item exists to prevent. Verified: `class A: SLOT_ID='only'` /
  `class B: SLOT_ID='only'` → `A.SLOT_ID is B.SLOT_ID` is `True`.
- Monkeypatching `CalloutElement.SLOT_ID` and asserting the import path rejects
  `tab="only"` — under *this* design `validate_nesting` never reads the model attribute,
  so the patch has no effect and the test would fail against a **correct**
  implementation.

**The pin that bites is source-level** (this repo already uses source-scanning tests):
assert that neither `SpoilerElement`'s nor `CalloutElement`'s class body contains a bare
`"only"` literal — i.e. both must reference `SINGLE_SLOT_ID`. Mutant: re-spell either as
`SLOT_ID = "only"` → RED.

Strip **both `#` comments and the class docstring** before scanning, or scan only
executable statement lines: `inspect.getsource()` includes the docstring, and
`SpoilerElement`'s already narrates its slot — a correct implementation whose docstring
happened to quote `"only"` would go falsely RED, the mirror image of the vacuity trap.
Correspondingly, do not rewrite those docstrings to quote the literal.

Update the now-false comment at `payloads.py:750-752`.

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

`builder.duplicate_unit` (`courses/builder.py:326-351`) reuses `build_export` +
`materialize_duplicate`, so the same missing arm **also silently drops callout children
from every unit duplication** — a far more common author gesture than export. Pin both:
the export → import round trip, and "duplicating a unit preserves a table nested in a
callout".

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
  (`courses/static/courses/js/reveal.js:51-52`). **It never returns `null`**:
  `templates/courses/_lesson_article.html:35-36` wraps every lesson's elements in
  `{% for slide in slides %}<div class="slide">` — slideshow or not (only
  `lesson--slideshow` and `data-slideshow` are conditional on `slides|length > 1`), and
  `closest()` matches regardless of `display`. So a gate inside a top-level callout
  resolves to `.slide` in **every** lesson.

  The actual pre-fix behaviour is worse than inaction: `ownWrapper` resolves to the
  enclosing `.lesson-block`, so `gateWrap.hidden = true` **hides the entire callout**,
  and because `isGateWrapper` under a `.slide` scope requires
  `:scope > .lesson-block__body > [data-reveal-gate]`, the cascade never finds a
  stopping point and marks **every following top-level `.lesson-block`**
  `.reveal-shown` — content leakage plus the callout disappearing.
- The pre-hide CSS at `templates/courses/lesson_unit.html:39-41` has exactly three
  selectors, none matching `.callout__child`, so gated content is **fully visible
  before the click** either way.

Add `.callout__children` to `scopeOf` and a fourth pre-hide selector. (Placement
within the selector list is cosmetic — `closest()` returns the nearest matching
ancestor regardless of the order selectors appear in; do not attach meaning to it.)

```css
.reveal-armed .callout__children > .callout__child:has(> [data-reveal-gate]) ~ .callout__child:not(.reveal-shown)
```

**And a third list: the print revert.** `core/static/core/css/app.css:1001-1005`
re-reveals gated content for printing, and enumerates only two scopes:

```css
@media print {
  .reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block,
  .reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child {
    display: revert !important;
  }
```

Adding a fourth pre-hide selector **without** a matching print revert makes every
post-gate sibling inside a callout `display:none` in print/PDF — permanent content loss
in that output mode. Note it is already missing `.spoiler__children`, so #212 shipped
this defect; fix both while here.

`isGateWrapper` (`reveal.js:72-78`) needs no new branch — like `.tabs__child` and
`.spoiler__child`, a `.callout__child` wraps its gate directly, so it takes the
existing `:scope > [data-reveal-gate]` form. Extend
the reveal-scope agreement check to cover all four scopes across all **three** files.

**This is a new test, not an extension.** `courses/tests/test_reveal_gate_render.py`
contains no cross-file check — its `test_lesson_prehide_css_covers_spoiler` (`:225`)
asserts a substring of the *rendered lesson HTML* and never reads `reveal.js` or
`app.css`; `test_reveal_refactor_static.py` reads `reveal.js` but only for
`cascadeFrom`/focus behaviour, and nothing reads the `@media print` block at all. Write
a source-agreement test that reads all three — `reveal.js`'s `scopeOf` selector list,
the `lesson_unit.html` pre-hide block, and `app.css`'s `@media print` revert — and
asserts they enumerate the same four scopes.

**It must EXTRACT each block before scanning, or it is green under its own mutant.**
The scope tokens already occur elsewhere in the same files: `.spoiler__children` appears
2× in `app.css` (the shared rule at `:987`) and `.slide` 4×. A test that scans the
*file* for the four tokens therefore stays GREEN when a scope is missing from the
`@media print` revert — which is precisely the state `app.css:1001-1005` is in **today**.
Three of the four tokens would survive the mutant; only `.callout__children` would go
red, because the spec puts all other callout CSS in `courses.css`.

So: slice out the `@media print { … }` block from `app.css` and the
`{% if has_reveal_gate %}` `<style>` block from `lesson_unit.html` first — the same
split discipline `test_spoiler_css.py:34` already uses — then scan only those
substrings. **Falsification:** deleting the `.spoiler__children` line from the print
block *alone* must go RED.

This test is the slice's central defence against the "three literal scope lists" defect
class, so it must exist.

### 6 — math.js must typeset the callout heading

PR #211's tab-label fix was two-sided: the label joined the has-math walk **and**
`.spoiler__toggle` joined `math.js`'s `renderInlineText` selector list
(`courses/static/courses/js/math.js:31`). `.callout__heading` is a `<span>` in
`.callout__header`, outside `.callout__body`, and matches nothing in that list.

Arming KaTeX off the heading without this leaves the heading showing raw `\(x^2\)` —
"the math renders" ≠ "the reader sees math". Add `.callout__heading` to the selector
list.

**But the selector alone is not enough.** `.callout__heading` is the house *eyebrow*:
`font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase`
(`courses.css:1581-1588`). KaTeX emits glyphs as ordinary inherited-style spans, so
`text-transform` would uppercase every math letter (`\(x^2\)` → `X²`) and
`letter-spacing` would pull glyph and rule positioning apart, at 0.75rem.
`.spoiler__toggle` — the PR #211 precedent — carries none of those, so the precedent
does **not** transfer. A required companion rule neutralises the eyebrow treatment
inside typeset math:

```css
.callout__heading .katex { text-transform: none; letter-spacing: normal; font-size: 1rem; }
```

verified light+dark. **Decided values**, so the pin below is writable from the spec
rather than restating whatever the implementer happened to pick:

```css
.callout__heading .katex {
  text-transform: none;
  letter-spacing: normal;
  font-size: 1em;      /* match the eyebrow exactly; KaTeX's own sheet sets 1.21em */
  color: inherit;      /* carry --callout-accent */
  font-weight: inherit;/* carry the 700 eyebrow weight where KaTeX allows */
}
```

`font-size: 1em` is deliberate: KaTeX's stylesheet sets `.katex { font-size: 1.21em }`,
so un-reset heading math renders at 0.9075rem against a 0.75rem label — visibly larger
and liable to overflow the 1.1 line box. Assert the size **relatively** (equal to the computed size of `.callout__heading`
within 1px), so the test does not hard-code a literal — but **name the node precisely**:
the *first / outermost* `.mord` in `.callout__heading .katex-html`, or use a
superscript-free sample such as `\(a\cdot b\)`. KaTeX emits several `.mord` nodes for
`\(x^2\)`, and the superscript's is `.mord.mtight` inside `.sizing.reset-size6.size3`
at ~0.7em — a test written as "all `.mord`", or one that happens to select the tight
one, fails against a correct implementation.

And the e2e pin must assert something that actually **changes** under the defect.
`text-transform` is a paint-time transformation and never alters `textContent`, so a
"textContent is not uppercased" assertion is green with *and* without the reset —
the same vacuity as "a `.katex` node exists". Assert instead: computed
`text-transform` / `letter-spacing` / `font-size` on the outermost
`.callout__heading .katex-html .mord`,
plus a bounding-box or screenshot comparison of the same LaTeX rendered inside versus
outside the heading.

### 7 — editor.css

The editor branch below emits an `<li class="el-row el-row--callout" data-element="…">`
with an inner `.el-row__callout`. **The base `.el-row` class and `data-element` are
mandatory**, mirroring `_element_row.html:147`: `editor.js` selects rows via
`root.querySelectorAll(".el-row[data-element]")` (`:147`, and again at `:289`, `:296`,
`:361`, `:384`, `:391`) for selection, alignment and the edit-slot lifecycle. A branch
emitting only the modifier would silently drop the callout row out of every one of
those handlers, with no server-side test noticing.
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

`templates/courses/elements/spoilerelement.html` — **the body block must be MOVED
ABOVE the children block**, not merely converted from `elif` to `if`. The current
template is `{% if children %} … {% elif el.body %} … {% endif %}`
(`spoilerelement.html:7-30`) — children come **first**. Turning the `elif` into an
`if` in place yields DOM order children-then-body, which contradicts D1 *and* makes
both prescribed combined-shape selectors (`.spoiler__body:has(+ .spoiler__children)`
and `.spoiler__body + .spoiler__children > …`) match nothing, so the CSS fix would
silently do nothing. Final order must match the callout template: 1. body, 2. children.

Assert **source order** (offset of `spoiler__body` < offset of `spoiler__children`),
not merely that both substrings are present — a presence-only assertion is green under
the wrong order.

The existing `.spoiler__children` wrapper is otherwise untouched (`scopeOf` and the
pre-hide CSS both depend on it).

`.callout__children` is load-bearing for **three reasons of its own** — note the PR
#212 "a per-child border cannot make a continuous rule" argument is about
`.spoiler__children`, which carries a 2px left rule; `.callout__children` carries no
rule at all, so do not transplant that rationale (or add a border the design never
asked for). The callout wrapper earns its place because it is (a) the node
`reveal.js`'s `scopeOf` must resolve to, (b) the anchor for
`.callout__body + .callout__children`, and (c) the subject of the
`:has(> .callout__children)` predicate the prose-cap fix keys on.

For the spoiler, the #212 rationale does apply verbatim: per-child borders cannot
produce a continuous left rule because child margins collapse through, leaving 16px
holes. `.spoiler__children` is also what the reveal cascade scopes to — `reveal.js`'s
`scopeOf`, the pre-hide CSS, and `courses/tests/test_reveal_gate_render.py` must
continue to agree (now four-way, per change-set item 5).

### Forms

`courses/element_forms.py:224-230` — delete the `fields.pop("body", None)` guard from
`SpoilerElementForm.__init__`. `CalloutElementForm` gains no equivalent guard.

### Author documentation

`docs/help/course-admin/content-editors.md` (and its `.pl` twin) ships author-facing
statements this slice makes false, so they are part of the change set, not a follow-up:

- `:123` — "Tabs, Columns, and Spoiler are the three container types." Now four.
- `:130-133` — the nested add-menu "offers the non-container … Callout — plus, where
  depth still allows it, the Tabs, Columns, and Spoiler container cards themselves."
  Callout moves from the non-container list into the depth-guarded list.
- `:95` — describes Callout purely as a leaf aside.
- `:140-142` — "inside a quiz, a nested add-menu offers the Content types plus — where
  depth allows — Tabs and Columns". Wrong once Callout is depth-guarded while sitting
  in the Content group.

And a second file, `docs/help/course-admin/interactive-elements.md` (plus its `.pl` twin):

- `:11-12` — "Spoiler is unusual among them, since it is also one of **the three
  container types** itself." Now four.
- `:74-85` — the Spoiler section describes only a rich-text body and never mentions
  children, so D1's body+children semantics are undocumented.

Neither file is matched by the three-container grep above, which is why they are named
explicitly.

**Polish anchors, given separately because the inflection differs** and the prescribed
grep has holes exactly there: `content-editors.pl.md:133-134` ("trzy typy kontenerów")
and `:141-144` ("karty kontenerów: Zakładki, Kolumny i Rozwijaną treść" — the twin of
the English `:130-133`); `interactive-elements.pl.md:11-14` ("jednym z **trzech typów**
kontenerów", which `trzy typy kontener` does **not** match); plus
`content-editors.pl.md:103` (`{el:callout} **Ramka** — …`, the twin of English `:95`)
and `interactive-elements.pl.md:85` (`## {el:spoiler} Rozwijana treść`, the twin of
English `:74-85`).

**The discovery rule is pairing, not grepping.** Verified by running it: `rg -ni
"kontener" docs/help` hits `content-editors.pl.md` 14× and `interactive-elements.pl.md`
3×, but **neither of the last two anchors above contains the word "kontener" at all** —
the Ramka description and the Rozwijana treść heading would both be silently missed and
the English and Polish manuals would diverge. So: edit every English anchor, then edit
its `.pl` twin by pairing, and run the sweep only as a supplement to catch stragglers.

State explicitly that a callout consumes a nesting level (D3), since that is the
surprising part for an author who reads a callout as a frame. Check for a matching help
screenshot. "Help docs updated — **both files**, both languages" joins the Definition
of done.

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
- **Gap between adjacent children:**
  `.callout__children > .callout__child + .callout__child { margin-top: var(--space-5) }`,
  mirroring the tabs precedent at `courses.css:1471`
  (`.el--tabs .tabs__child + .tabs__child`). Without it two margin-less children — the
  primary use case, e.g. two tables, or a table then an image — abut with zero gap. The
  spoiler gets away with having no such rule only because its children's own margins
  collapse through; a padded callout gives no such guarantee.
- **`.callout__child` must carry no `display` declaration.** `app.css:997` reads
  `.lesson-block[hidden], .tabs__child[hidden] { display: none !important; }` — an
  explicit guard so an author-facing `display` cannot beat `[hidden]`, which is how the
  reveal cascade consumes a gate (`reveal.js:137` sets `gateWrap.hidden = true`).
  `.spoiler__child` is absent from that guard only because it declares no `display`.
  If a `display` (flex/grid — a tempting way to get the sibling gap above) is ever
  added, `.callout__child[hidden]` MUST join the `app.css:997` guard.

**Prose cap.** `.callout` is in the collapsed-TOC prose-cap allowlist at
`max-width: 46rem` (`courses/static/courses/css/courses.css:959-975`), whose own
comment names the hazard: *"a missed opt-out BREAKS layout (a squeezed table)"*. A
table is deliberately absent from that allowlist at top level, but a table nested in a
callout would inherit the cap and render narrower than the identical table outside
one — in the primary use case driving this slice.

Two facts make the naive fix wrong. (a) Adding a `.callout__body` selector is a
**no-op**: `.callout__body` already carries `el--text` (`calloutelement.html:7`) and
`html.unit-tree-collapsed [data-unit-shell] .el--text` is already in the allowlist at
`courses.css:961`. The only load-bearing edit is to the `.callout` entry. (b) Simply
**deleting** `.callout` would send the callout *frame* (border, tint, padding)
full-shell-width in the collapsed state for all 83 existing prose-only callouts — a
visible change to content that has nothing to do with nesting.

**Chosen:** narrow the existing entry to
`.callout:not(:has(> .callout__children))`, so a prose-only callout keeps today's cap
byte-for-byte and only a callout that actually holds children un-caps. Blast radius on
existing content is zero. Pin with a computed-width e2e assertion in the
`unit-tree-collapsed` state, covering both a prose-only and a table-bearing callout.

**The setup is what makes this pin non-vacuous.** The cap lives under
`@media screen and (min-width: 641px)` and is scoped
`html.unit-tree-collapsed [data-unit-shell] …`, and `unit-tree-collapsed` is applied to
`<html>` by the TOC-pin JS from `localStorage` — never by the server. A run that simply
loads the lesson measures the *uncapped* state in both arms, so "the table-bearing
callout is wider than 46rem" is green with and without the narrowing. Require the test
to: enter the collapsed state explicitly (seed `localStorage` or click the pin) and
assert `html.unit-tree-collapsed` is present; run at a viewport wide enough that the cap actually
**binds**; and include the **control** arm — the prose-only callout must measure exactly
46rem on the same page — so the setup is proven live before the negative assertion is
trusted.

**`≥ 641px` (the media-query floor) is not sufficient and would make the control arm
unsatisfiable.** 46rem is 736px, but the collapsed shell's content box is
`min(viewport, 72rem) − 2.4rem (the collapsed pin lane, `courses.css:926-928`) − 3rem
(`.lesson`'s `padding: 1.25rem 1.5rem`, `:546`)`. At a 641px viewport that is ≈555px, so
the prose-only control measures 555px rather than 736px **and** the negative arm fails
too — the cap never binds. The floor is ≈822px; **use 1280×900** for the test.

**Spoiler combined shape.** `core/static/core/css/app.css:986-993` gives
`.spoiler__body` and `.spoiler > .spoiler__children` the same `padding-left` and 2px
left rule, but `.spoiler__body` additionally carries
`margin: var(--space-3) 0 var(--space-1) var(--space-3)`. The two shapes were mutually
exclusive until now, so nobody has seen them stacked: the both-present state D1
creates renders **two rules at different left offsets with a vertical gap** — breaking
the continuous-rule invariant PR #212 established.

**The requirement is an outcome, driven by measurement, not a fixed rule set:** in the
body+children shape the two rules must share one `left` offset and show zero vertical
gap, so they read as a single continuous line; the body-only shape keeps its current
indent. Starting point:

```css
.spoiler__body:has(+ .spoiler__children) { margin-left: 0; margin-bottom: 0; }
.spoiler__body:has(+ .spoiler__children) > :last-child { margin-bottom: 0 }
.spoiler__body + .spoiler__children > .spoiler__child:first-child > :first-child { margin-top: 0 }
```

**The gap has two symmetric sources, so zeroing one side is not enough.**
`.spoiler__body` declares only `padding-left` and `border-left` — no bottom padding or
border — so its own last child's `margin-bottom` collapses *through* the body box and
survives `margin-bottom: 0` on `.spoiler__body` itself (collapsing takes the max of
parent and child). Hence the second rule above, the mirror of
`.callout__body > :last-child { margin-bottom: 0 }` which already exists at
`courses.css:1589` and which the spoiler has never had.

**Placement constraint (a real trap).** `courses/tests/test_spoiler_css.py:34` reads
the rule block as `css.split(".spoiler__children")[1].split("}")[0]` over the
concatenated, comment-stripped CSS, then asserts `border-left` and `padding-left` are
in it. That is a *first-occurrence* split — and `_all_css()` concatenates
`courses/static/courses/css/*.css` **first**, then `core/static/core/css/*.css`.

So the constraint is **cross-file and absolute**, not a within-`app.css` ordering nicety:
every new selector mentioning `.spoiler__children` must live in `app.css`, positioned
**below** the shared `.spoiler__body, .spoiler > .spoiler__children` block at `:986`, and
**none may appear in `courses.css` or `editor.css` at all** — any placement there sorts
ahead of `app.css` in the glob and makes the split read the new declarations, failing the
test for a reason unrelated to this change. That is a real temptation, since the new
callout rules do belong in `courses.css` and co-locating the spoiler ones beside them
would look tidy. Say so in a comment beside the new rules.

Note what does **not** work and why: `.spoiler > .spoiler__children` declares no margin
and `reset.css` zeroes margins, so a `margin-top: 0` on the wrapper itself is inert.
PR #212 deliberately made the wrapper *not* a flow-root so "the children's own margins
keep collapsing through it" (`app.css:981-985`) — which means the gap is opened by the
first child's own collapsed-through top margin, and only the deeper selector above
closes it. This is exactly the treatment the callout side already specifies; the
analogue was missing here.

Pin with a computed-style e2e assertion on the outcome (equal `left`, zero vertical
gap), not on the presence of particular declarations — **and the `<details>` must be
opened first.** A `.spoiler` is closed by default, so its contents are not rendered and
`getBoundingClientRect()` returns all-zeros for both `.spoiler__body` and
`.spoiler__children`: "equal `left`" (0 == 0) and "zero vertical gap" (0 − 0) both hold
**with and without** the fix, leaving the named mutant green. This is the same
closed-`<details>` trap already recorded in this repo.

Require the test to open the element (click the summary or set `open`), assert
visibility before measuring, and — so the author proves the setup is live — record what
the **broken** build produces: the two `left` values differ by `var(--space-3)` and the
vertical gap is non-zero.

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
unchanged, so no payload key changes and **no `FORMAT_VERSION` bump** is needed. This
is *not* the same as "old archives import unchanged" — see D3a for the depth-4 callout
break.

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

`_callout_has_math` covers the **stored `heading` field** (never `display_heading` —
the per-kind defaults are translated labels, so the property would pass a lazy
translation proxy into `has_math_delimiters` and check a string that can never carry
math), `body`, and children. **COLLECT + MUST
RECURSE**, mirroring `_tabs_has_math` verbatim: each child is dispatched through
`_element_has_math`, never through `has_math_delimiters` directly. That is the whole
risk — `callout > tabs > table` and `callout > callout > text` are newly legal, and a
non-recursive implementation that special-cases tables passes a depth-1 test while
silently missing math two containers deep.

**Order is load-bearing: heading → body → children walk**, with the
`join_row() is None` transient guard applying **only to the children walk**. Do *not*
copy `_twocolumn_has_math`'s top-of-function guard (`views.py:274-276`): a two-column
element has no text of its own, but a callout does, so an early `return False` would
make a transient callout carrying `\(x^2\)` in its heading or body report no math.
`_spoiler_has_math` deliberately has no such guard — it relies on `resolved_children()`
returning `[]` — and `test_spoiler_nesting.py`'s
`test_legacy_body_spoiler_math_still_detected` exercises exactly that join-row-less
shape and expects `True`.

**Chosen: keep the guard, on the children walk only** — not "either/or". The
alternative (omit it, relying on `resolved_children() == []`) leaves the mutant table
row "move the `join_row() is None` guard to the top" inapplicable, because there would
be no guard to move, and the invariant this paragraph calls load-bearing would have no
test that can go red.

It self-guards with its own `isinstance` check purely for symmetry — not because the
fallback chain dispatches it.

Including `heading` is only correct together with change-set item 6; arming KaTeX for a
heading that `math.js` never visits produces raw LaTeX on screen.

**Malformed / tampered data.** `CalloutElement.save()` already coerces an unknown
`kind` to `example`. `resolved_children()` returns `[]` when the join row is
transient, so a mid-create callout renders its body and no child list rather than
raising.

### Cleanup migration

A `RunPython` data migration over **every** `SpoilerElement` row with a non-empty
`body` — not only those that also have children.

Why the wider filter: of the 14 bodied spoilers in `libli`, only 2 have children, so
~12 carry a body and none. Those are harmless today, but the moment an author adds a
child to one, an empty-ish body (`<p><br></p>`, `<div>&nbsp;</div>`) starts rendering
as a blank paragraph above the children — the exact cosmetic defect category A exists
to prevent, arriving *after* the migration has already run. Category A is safe to clear
regardless of children, so restricting the filter buys nothing. Category B is evaluated
only where children exist (it is defined against them).

**Historical-model constraints.** `apps.get_model` returns models with fields but
**no custom methods** — `join_row()` and `resolved_children()` do not exist there, and
`Element` reaches its concrete only through a GFK. So the migration must:

- look up `ContentType` rows for `courses.spoilerelement` **and** `courses.textelement`
  itself;
- find each spoiler's join row via `Element.objects.filter(content_type=..., object_id=...)`
  **ordered `.order_by("pk").first()`**, mirroring `join_row()`;
- find its children via `Element.objects.filter(parent=join)` — **on `parent` alone, no
  `tab_id` filter**. This mirrors `resolved_children()` (`models.py:419-430`), whose
  docstring says "Grouped by `parent` alone — the single slot means tab_id is not needed
  to disambiguate". A narrower `tab_id="only"` filter would make the migration's notion
  of "children" differ from the renderer's: a child whose `tab_id` had drifted would
  still render (and so duplicate the body) while staying invisible to the category-B
  check, classifying the row as C and leaving the duplicate in place. Where the literal
  `"only"` *is* needed elsewhere, inline it — never import it from the live model;
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

**`CalloutElement` needs no cleanup — on measurement, not on principle.** "It has no
children today" is precisely the reasoning rejected above for spoilers, since this slice
is what enables children. The real justification is the count:

| DB | callouts | with body | **empty-ish body** |
|---|---|---|---|
| `libli` | 83 | 82 | **0** |
| `libli_mat` | 0 | 0 | 0 |

Zero callouts carry an empty-ish body, so there is nothing for a category-A pass to
clear and no blank-paragraph hazard when an author adds the first child. If that count
were non-zero the migration would have to cover `CalloutElement` too.

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
| Math **two containers deep** — `callout > tabs > table` — arms KaTeX | walk children with `has_math_delimiters` instead of `_element_has_math` |
| Callout heading with `\(...\)` yields `.katex` in `.callout__heading` | remove `.callout__heading` from `math.js` |
| Callout accepts a table child; `callout > callout` authorable | drop `CalloutElement` from `_CONTAINER_REGISTRY` |
| Table in a callout round-trips export → import | drop the `emit()` callout arm |
| Callout card absent from a depth-3 add-menu | drop the `{% if depth < max_nest_depth\|add:-1 %}` guard |
| Gate in a callout: the callout stays visible after the click, siblings unaffected, gated content hidden before it | drop `.callout__children` from `scopeOf` / the 4th pre-hide selector. **Do not** assert "the button did nothing" — that is green under the defect and RED under the fix |
| Stateful child in a callout gets its blob + save URL | pass `state=` instead of `element_state=` |
| Neither model re-spells the slot literal | source-scan (comments stripped) asserts no bare `"only"` in either class body; mutant: write `SLOT_ID = "only"` in one of them (strip `#` comments AND the class docstring before scanning, or a correct impl whose docstring quotes the literal goes falsely RED) |
| `spoiler > tabs > callout > table` authorable; `spoiler > tabs > spoiler > callout` rejected | flip a depth clause comparison |
| Registry drift test passes with callout in all of them | add callout to two of the three |
| Import of a hand-crafted depth-4-callout archive 422s (D3a, decided break) | drop `"callout"` from `CONTAINER_TRANSFER_KEYS` |
| Duplicating a unit preserves a table nested in a callout | drop the `emit()` callout arm |
| Gated content inside a callout is visible in print | omit `.callout__children` from the `@media print` revert |
| Gated content inside a **spoiler** is visible in print (the pre-existing #212 gap this slice also fixes) | omit `.spoiler__children` from the `@media print` revert — without this row the slice can ship the callout half and silently leave the spoiler half broken |
| Callout heading math is not uppercased or letter-spaced | drop the `.callout__heading .katex` reset |
| Migration: A, B and C rows — **C preserved** | broaden the predicate to clear C |
| Migration clears an empty-ish body on a **childless** spoiler | narrow the row filter to body+children |
| Spoiler body renders **before** children (source offset) | leave the body block below the children block |
| Transient callout (no join row) with body/heading math reports math | move the `join_row() is None` guard to the top of `_callout_has_math` |
| Migration A predicate: `<p><br></p>`, `<div>&nbsp;</div>`, decoded-nbsp | narrow the predicate to a bare `<br>` |

### Existing tests this slice must invert

D1 and the `fields.pop` deletion turn two currently-passing tests RED. They assert the
old behaviour deliberately, so they must be rewritten — not worked around. An
implementer hitting them without this list cannot tell whether the spec or the test is
wrong:

| Test | Current assertion | Replacement |
|---|---|---|
| `courses/tests/test_spoiler_nesting.py:63` `test_render_prefers_children_over_body` | `"LEGACY-BODY" not in html` | **both** `CHILD-BODY` and `LEGACY-BODY` present, body before children by source offset; rename (it no longer "prefers") |
| `courses/tests/test_spoiler_nesting.py:266` `test_spoiler_form_drops_body_when_instance_has_children` | `"body" not in form.fields` | `"body" in form.fields` with children present; rename |
| `tests/test_editor_depth.py:157` `test_depth_3_nested_menu_hides_containers_but_keeps_leaves` | `'data-add-type="callout"' in menu  # a legal depth-4 LEAF` | flips to `not in`; keep a genuine leaf (e.g. `text`) asserted present so the test still proves the menu rendered |
| `tests/test_editor_depth.py:82` `CONTAINER_CARDS = ("tabs", "twocolumn", "spoiler")` | drives five loops (`:103`, `:120`, `:139`, `:155`, `:299`) | must become four-membered with `"callout"` — otherwise the depth-3 negative assertion never covers the new card |

**The mutant for "Callout card absent from a depth-3 add-menu" is killed by the flipped
`:157` assertion plus the widened `CONTAINER_CARDS`, not by a new test.** Note this file
is `tests/test_editor_depth.py` (repo-root `tests/`), not `courses/tests/`.

Sweep `test_spoiler_render.py`, `test_spoiler_css.py` and `test_spoiler_context.py` in
the same pass for the same either/or assumption.

Also extend `courses/tests/test_render_seam.py`'s `CONCRETES` list — described in-file
as "Every concrete `render()` the generic branch can reach" — with `CalloutElement`
**and** `SpoilerElement`, both currently absent, so the new override is covered by the
signature guard that exists for exactly this failure mode.

**`CONCRETES` parametrizes two tests, not one**: `test_render_accepts_the_state_kwargs`
(`:39`) and `test_lesson_renders_200_with_each_concrete` (`:178`), the latter crossed
with `placement ∈ {top, tabs, twocolumn}` (`:180`). Add `"callout"` (and `"spoiler"`) to
that `placement` list — **but adding the ids alone is worse than useless.**
`test_lesson_renders_200_with_each_concrete` (`:180-208`) dispatches with
`if placement == "top": … elif placement == "tabs": … else:` — and that `else` is the
**two-column** branch. New ids with no new branch would silently construct a
`TwoColumnElement` parent and pass, doubling the test count while adding zero coverage,
in the very parametrize the spec leans on as the audit's backbone.

So the two new branches must be written explicitly: a `CalloutElement` parent plus
`Element.objects.create(unit=unit, content_object=obj, parent=parent, tab_id=CalloutElement.SLOT_ID)`,
and the same for `SpoilerElement`. **Falsification, for BOTH new ids** — guarding only one reproduces the very
fallthrough this paragraph exists to prevent: with the branches omitted, the `callout`
id must be distinguishable from `twocolumn` (assert the response contains
`callout__children`), and the `spoiler` id likewise (assert it contains
`spoiler__children`).

With the branches present, that parametrize renders every concrete inside a callout and
is the mechanical backbone of the client-enhancer audit above — the prose audit then
only has to cover what a 200-check cannot: computed style and cascade behaviour.

The cap-agreement trap from #209 applies here too — never monkeypatch a constant to
its real value; the test goes vacuous while still passing.

**Comment updates are part of the change set** (`comments-can-fail-tests`: at least
one test in this repo regexes raw source including comments). At minimum these twelve
sites become false:

| Site | False claim |
|---|---|
| `_add_menu.html:12-17` | ":12-13" — "The CONTAINER cards (**Tabs, Columns, Spoiler**) are guarded by …"; and ":16-17" — "Callout is a plain LEAF in this slice and stays unguarded". The prescribed `rg` misses `:12-13` (no "and" before Spoiler) |
| `payloads.py:750-752` | "the only valid id is `SpoilerElement.SLOT_ID`" |
| `payloads.py:779-781` | "spoiler is a single-slot container … its sole valid slot id is `SpoilerElement.SLOT_ID`" — a second, distinct claim |
| `builder.py:27-30` | the PR2 to-do — now done |
| `_spoiler_has_math` docstring | "A nested spoiler has an empty body" |
| `models.py:399-401` | `SpoilerElement` expands "**either** legacy rich-text `body` **OR** … child elements" — now both |
| `spoilerelement.html:8-24` | the block comment describing the two shapes as mutually exclusive |
| `app.css:978-985` | "Two shapes get the SAME treatment"; "total height is unchanged — measured 154px" |
| `export.py:560-562` | "tabs, two_column, spoiler" |
| `export.py:660-663` | "A parent is always a CONTAINER element (tabs, two_column, or spoiler)" |
| `reveal.js:41-50` | the `scopeOf` comment enumerating three scopes |
| `reveal.js:68-78` | `isGateWrapper`'s "**Three scopes exist**" — now four, with callout a third member of the direct-child family |
| `tests/test_editor_depth.py:161` | "`_element_row.html` includes `_add_menu.html` at **three** sites -- tabs, two-column and spoiler" — now four; the fixture-choice rationale needs a callout clause. Test docstrings are in scope for this sweep |

Not a closed list: grep for the three-container enumeration
(`rg -n "tabs.*two_column.*spoiler|Tabs, Columns,? and Spoiler"`), **and** a second
grep for the scope/count enumeration (`rg -ni "three scopes|three container types"`), plus the Polish stem sweep
`rg -ni "kontener" docs/help`, and update every hit.

**Definition of done:** full non-e2e suite green serial, e2e green, `ruff` clean,
`makemigrations --check --dry-run` clean (the CI guard added in #204), `.po` catalogs
zero-fuzzy with the three changed/new msgids translated — note the spoiler reword is a
**deletion plus an addition**: the old "This spoiler shows saved text (edit it with the
pencil). Add an element below to start nesting content." must be removed from both
`locale/en` and `locale/pl`, which `makemessages -l pl -l en --no-obsolete` handles and
a bare `makemessages` does not (it would leave an obsolete entry and fuzzy-prefill the
new one) — and
`docs/help/course-admin/content-editors{,.pl}.md` **and**
`docs/help/course-admin/interactive-elements{,.pl}.md` updated per "Author
documentation".

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
- **Items 5–7 are JS/CSS.** They are invisible to any test
  that asserts only server-rendered HTML, and they are the exact class PR #209 shipped
  broken. e2e coverage for them is mandatory, not preferred.
- **A `has_math` miss is silent.** No error, no bad status code — just unrendered math.
- A callout consuming a nesting level (D3) may surprise an author who thinks of it as
  a frame rather than a container. Accepted, and the help doc rewrite below is the
  mitigation — not an optional nicety.
- Three msgids change; the Polish fuzzy-prefill trap needs a native-speaker check.
