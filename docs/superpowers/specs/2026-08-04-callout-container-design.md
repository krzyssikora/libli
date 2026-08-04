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

Zero rows are category C (genuinely stranded, non-duplicate content).

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

## Architecture / components

### Model — `CalloutElement`

Add, mirroring `SpoilerElement` (`courses/models.py:397-444`):

- `SLOT_ID = "only"` — the single implicit child slot; the child `Element.tab_id` value.
- `join_row()` — this concrete's single `Element` join row.
- `resolved_children()` — ordered child join rows, `order_by("order", "pk")`, `[]`
  when the join row is transient.
- `render(*, element=None, state=None, slug=None, node_pk=None)` passing
  `children=self.resolved_children()` into the template context.

`render()` is genuinely new: `CalloutElement` has no `render()` today and reaches its
template through the generic path in `courses/templatetags/courses_extras.py`. It
already has `elements = GenericRelation(Element)`, which is what the join row needs.

No new field, therefore **no schema migration** — only the data migration below.

### The three registries

`courses/tests/test_nesting_rule.py:283-286` asserts these agree, which is what stops
the change landing in two of three:

| Location | Change |
|---|---|
| `courses/builder.py` `_CONTAINER_REGISTRY` | `CalloutElement: (lambda _data: {"slots": [{"id": CalloutElement.SLOT_ID}]}, "slots", "id")` |
| `courses/builder.py` `CONTAINER_TRANSFER_KEYS` | add `"callout"` |
| `courses/transfer/payloads.py` `_CONTAINER_SLOT_KEY` | add `"callout": None` |

`NESTABLE_TYPE_KEYS` already contains `"callout"` — no change. Children permitted
inside a callout are therefore exactly the existing nestable set; no new allowlist,
no per-parent subset rule.

`resolve_scope`'s `getattr(parent_obj, "data", None)` at `courses/builder.py:161`
already handles a container with no `data` field — the shape Callout has.

### Render templates

`templates/courses/elements/calloutelement.html` — keep the header, then:

1. `{% if el.body %}` → the existing `.callout__body`.
2. `{% if children %}` → a single `.callout__children` wrapper holding one
   `.callout__child` per child.

`templates/courses/elements/spoilerelement.html` — change `{% elif el.body %}` to an
independent `{% if el.body %}` so both blocks can render; the existing
`.spoiler__children` wrapper is untouched.

The single wrapper is load-bearing, per PR #212: per-child borders cannot produce a
continuous left rule because child margins collapse through, leaving 16px holes.
`.spoiler__children` is also what the reveal cascade scopes to — `reveal.js`'s
`scopeOf`, the pre-hide CSS in `lesson_unit.html`, and
`courses/tests/test_reveal_gate_render.py` must continue to agree.

### Forms

`courses/element_forms.py:224-230` — delete the `fields.pop("body", None)` guard from
`SpoilerElementForm.__init__`. `CalloutElementForm` gains no equivalent guard.

### Editor

`templates/courses/manage/editor/_element_row.html` — a `calloutelement` branch
mirroring the `spoilerelement` branch at `:146-197`: the nested
`element-list--nested` `<ol>` recursing through `_element_row.html`, an empty-state,
and the add-menu include guarded by `{% if depth < max_nest_depth %}` with
`tab=obj.SLOT_ID`.

Reword the spoiler empty-state at `:189` — with the body now rendering, "This spoiler
shows saved text … Add an element below to start nesting content" no longer describes
a hazard.

The Callout palette card stays where it is (Content group, unwrapped); this slice
changes what a callout can *contain*, not where it can be added.

### CSS

`.callout__children` / `.callout__child` in `courses/static/courses/css/courses.css`,
alongside the existing `.callout` rules. The wrapper carries no vertical margin so
child margins keep collapsing through and the callout's height is unchanged. Per-kind
accent handling is untouched.

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
`resolved_children()` (one query, `select_related("content_type")` +
`prefetch_related("content_object")`) and passes them to the template, which recurses
through `render_element` per child. The body renders first when non-empty.

**Transfer.** Export descends the `resolved_*()` slot accessors; delete descends
`join.children`. That asymmetry is deliberate and documented on both sides (see
`depth-3-nesting-status`): `resolved_tabs()` runs the destructive `normalize_data`
and skips children whose `tab_id` matches no slot, so export omits those on purpose
while delete must not, or their concretes orphan. Callout follows the same convention
as Spoiler. The existing `_ser_callout` / `_val_callout` / `_build_callout` trio keeps
`kind`/`heading`/`body` unchanged, so old archives import unchanged and **no
`FORMAT_VERSION` bump** is needed (additive, exactly as the spoiler-nesting slice was).

**Import validation.** `payloads.py`'s `validate_nesting` is the transfer-side twin of
`resolve_scope`: it walks the parent chain, reads a container's slot list via
`_CONTAINER_SLOT_KEY` (membership tested *before* the lookup, since callout's value is
`None`), and applies the same depth clauses. Write/import clause parity is an exact
identity — import `depth == parent_depth + 1`, so `depth > 4 ⇔ parent_depth >= 4` and
`depth >= 4 ⇔ parent_depth >= 3`; only error *precedence* differs, never the outcome.

## Error handling

**Nesting violations.** `resolve_scope` raises `NestingError`, which the view turns
into HTTP 400. The four clauses apply to a callout parent unchanged: unknown parent,
parent-not-a-container, disallowed child type, unknown slot, too deep, and
container-too-deep. Adding `"callout"` to `CONTAINER_TRANSFER_KEYS` is what arms
clause 4 for it.

**`has_math` — two changes, both silent failures if missed.** A miss does not error;
KaTeX simply never loads and the math stays as raw source text on the page. This is
the highest-risk item in the slice because its failure mode is invisible to any test
that only asserts a 200.

1. `courses/views.py:262-263` — `_spoiler_has_math` reads
   `if not children: return has_math_delimiters(el.body)`. Once the body always
   renders, a spoiler holding math **in its body and** children would report no math.
   The body must be OR'd in unconditionally.
2. `courses/views.py:202-203` — the `CalloutElement` branch is
   `return has_math_delimiters(obj.body)`. It must become a recursive
   `_callout_has_math` covering `heading`, `body`, and children — otherwise math
   inside a table nested in a callout never arms KaTeX, which is the primary use case
   driving this slice.

`_callout_has_math` follows `_spoiler_has_math`'s COLLECT + MUST RECURSE shape and
self-guards with its own `isinstance` check, returning `False` for a non-match so the
trailing fallback chain in `_element_has_math` can dispatch it. `heading` is the
callout's analogue of the spoiler label — the one part of the element that is not a
child element, and the exact class of omission PR #211 fixed for tab labels.

**Malformed / tampered data.** `CalloutElement.save()` already coerces an unknown
`kind` to `example`. `resolved_children()` returns `[]` when the join row is
transient, so a mid-create callout renders its body and no child list rather than
raising.

**Cleanup migration.** A data migration over `SpoilerElement` rows having both a
non-empty `body` and at least one child:

- **A** — body empty once `<br>`, `&nbsp;` and whitespace are stripped → set `body = ""`.
- **B** — body byte-identical to the `body` of one of its child `TextElement`s → set
  `body = ""`.
- **C** — anything else → **leave untouched**, so genuinely stranded content reappears
  above the children, which is the correct outcome.

Measured scope: `libli` 1×A + 1×B + 0×C; `libli_mat` 0. Written defensively for
category C even though it was not observed, because production has not yet taken the
mat-pp cutover. Reversible: the migration only clears fields that were unreachable,
and its reverse is a documented no-op.

`CalloutElement` needs no cleanup — it has no children today by construction.

## Testing

Beyond per-change unit tests, three things this slice must not repeat.

**The client-enhancer audit (the PR #209 lesson).** That slice shipped two defects —
`tabs.js` and `app.css` — that thirteen per-task reviews could not see, because the
implementation diff contained zero JS/CSS files, putting them outside every review
surface by construction. Both lived at the seam between "the server now permits X" and
"an untouched client enhancer assumes X is impossible."

Enumerate the newly-legal combinations — `callout` inside each of
{`tabs`, `two_column`, `spoiler`, `callout`}, and each of those inside `callout` — then
grep the client enhancers for unscoped `querySelectorAll` and descendant CSS against
each combination's own markup. `.callout` has no JS of its own, but a *nested* tabs or
spoiler inside a callout exercises theirs.

**A same-type fixture is mandatory.** PR #209's blindness root-caused to a fixture
monoculture: three tasks independently chose `tabs > spoiler > leaf`, so nothing in
the branch rendered a container inside a container of the same type. This slice must
include `callout > callout` and, for the fix, `spoiler > spoiler` where the outer has
a body.

**e2e, not render tests, for the cascade.** A Django render test is byte-identical
before and after a CSS-cascade defect and would be green under it. The nested callout
styling and the reveal cascade need computed-style assertions in a browser.

Cases to pin:

- A spoiler with body **and** children renders both, in that order.
- The spoiler edit form exposes `body` when children exist (falsifies the
  `fields.pop` removal).
- A callout accepts a table child via `resolve_scope`; `callout > callout` is
  authorable.
- A table authored into a callout round-trips through export → import.
- Math inside a table inside a callout arms KaTeX — assert on the KaTeX asset being
  present in the context/response, not on `.katex` nodes, which a Django test cannot
  produce.
- Depth: `spoiler > tabs > callout > table` is authorable;
  `spoiler > tabs > spoiler > callout` is rejected.
- The three-registry drift test still passes with callout added to all three.
- Migration: an A row, a B row and a C row, asserting **C is preserved**.

Per `falsify-tests-not-run-them`, each test names the mutant it kills; a passing test
that survives deleting the code it guards is vacuous. The cap-agreement trap from
#209 applies here too — never monkeypatch a constant to its real value.

**Definition of done:** full non-e2e suite green serial, e2e green, `ruff` clean,
`makemigrations --check --dry-run` clean (the CI guard added in #204), `.po` catalogs
zero-fuzzy if any msgid changed.

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
- **A `has_math` miss is silent.** No error, no failing status code — just unrendered
  math. Tests must assert positively that KaTeX is armed for the nested shapes.
- A callout consuming a nesting level (D3) may surprise an author who thinks of it as
  a frame rather than a container. Accepted; the help documentation should say so.
- Polish strings for any new editor copy need a native-speaker check, as PR #209's did.
