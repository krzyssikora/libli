# Tabs content element

Slice 3 of 3 new course-content elements (table → gallery/carousel → **tabs**). Slice 1 shipped as
PR #87, slice 2 as PR #88.

## Purpose

Course authors need to present alternative or parallel views of the same idea in one place — a
definition alongside a worked example alongside a common-errors note — without forcing the student
to scroll past all of it. A tabbed container gives the author a compact way to group several
elements under labelled panels, and gives the student a way to read one at a time.

This is the codebase's **first true element nesting**. Every existing element is a leaf whose entire
content lives in its own fields or its `data` JSON blob. The slideshow only *appears* to nest: it is
a flat `SlideBreakElement` delimiter plus a `partition_into_slides()` function that chops the
ordered element list into runs. `TabsElement` introduces a real parent/child relationship on the
`Element` join row, and the design's central concern is doing that with the smallest possible
substrate and one crisply-stated classification, so that every existing place that walks a unit's
element list gets classified exactly once rather than drifting. The invariant table below is the
authoritative enumeration of those walkers.

### Scope (v1)

**Allowed inside a tab** — the `NESTABLE_TYPE_KEYS` allowlist: text, math, image, video, iframe,
html, table, gallery.

**Blocked in v1:** all question elements, slide break, tabs-inside-tabs.

The allowlist is **authoritative and positive**: any element type not named in `NESTABLE_TYPE_KEYS`
is non-nestable, including element types added in future slices, which must be added to the
allowlist explicitly before they can live inside a tab. The "blocked" list above is an illustrative
reading of the allowlist, never an independent denylist.

Blocking questions is the deliberate risk boundary: it keeps grading (`quiz.py`), the review queue
(`review.py`), analytics rollups (`rollups.py`) and submission handling (`views_review.py`) entirely
out of the blast radius, because a nested element can never be gradable. Questions inside tabs is a
follow-up slice.

**Also out of scope:** dragging an element across scopes (from top level into a tab, or between
tabs). Reorder stays within a single list; moving between tabs means delete and re-add.

## Architecture

### The `TabsElement` model

A normal leaf-shaped element that holds only the tab **labels** — never the children.

```python
class TabsElement(ElementBase):
    MIN_TABS = 2
    MAX_TABS = 10
    data = models.JSONField(default=dict)
    # data = {"tabs": [{"id": "t7f3a1c", "label": "Definition"},
    #                  {"id": "t2b9c4e", "label": "Example"}]}
```

- Labels are **plain text**, not rich text and not math: tags are stripped and the label is truncated
  to **at most 80 characters**. Both steps live inside `normalize_labels_and_ids` (see "Error
  handling"), not in `save()` directly, so the read path applies them too — a label dirtied by a
  direct database edit is stripped before it reaches a template rather than relying solely on
  autoescaping. Both are non-destructive: they change a label's text, never which tabs exist.
- Each tab carries a **stable short id**, never an index. Reordering or deleting a tab must not
  silently reassign another tab's children — the classic index-shift bug.
- `normalize_data()` never raises, matching the `TableElement` / `GalleryElement` precedent: a
  malformed blob degrades to a sane default rather than 500-ing a lesson page.

**Tab-id format.** An id is the literal `"t"` followed by **6 lowercase hex characters** (e.g.
`t7f3a1c`) — 7 characters total, comfortably inside the `tab_id` field's `max_length=12`. Ids are
generated server-side. Uniqueness is required only **within one `TabsElement`**, so generation
regenerates on collision against the ids already present in that element's `data["tabs"]`. Ids are
never regenerated for an existing tab: not on rename, not on reorder, and not on import (see
"Transfer" below).

**Reaching the children from the concrete.** `Element.parent`'s `related_name="children"` lives on
the **join row**, not on the concrete `TabsElement`, and `ElementBase.render(self)` receives no join
row. `TabsElement` therefore reaches its own join row through the `elements` `GenericRelation` it
already inherits from `ElementBase` — `self.elements.order_by("pk").first()` — and from there
`.children`. This keeps `render()`'s existing zero-argument signature and requires no change to the
`render_element` template tag.

A concrete element has exactly one join row (the generic FK is effectively one-to-one; nothing in the
codebase creates a second), so `.first()` is unambiguous. The explicit `order_by("pk")` is defensive
determinism, not a real ambiguity. `join_row()` is a small helper on `TabsElement` wrapping this
lookup, so that **every** consumer that needs children uses one handle — `render()`, `resolved_tabs()`,
`has_math`, and the export walk alike. `has_math` in particular is the invariant table's
highest-risk line, and it reaches nested children through exactly this helper rather than
re-deriving the lookup.

`resolved_tabs()` encapsulates that lookup: it returns an ordered list of
`(tab_dict, [child_elements])` pairs, grouping `children` by `tab_id` and ordering each group by
`order`. `render()` calls it and renders `courses/elements/tabselement.html`. A `TabsElement` with no
join row (possible only transiently, mid-create) resolves to empty groups rather than raising.

### The nesting substrate

`Element` (the generic-FK join row) gains exactly two nullable fields. That is the whole substrate.

```python
parent  = models.ForeignKey("self", null=True, blank=True,
                            on_delete=models.CASCADE, related_name="children")
tab_id  = models.CharField(max_length=12, blank=True, default="")   # "" for top-level
```

Two decisions make this cheap:

**`unit` stays populated on nested children.** Children are not reparented out of the unit; they keep
their `unit` FK. This is what lets `Course.delete`, `ContentNode.delete` and the subtree-delete
helper keep working completely untouched, because they already filter by `unit__course` and
`unit_id__in=...` and will therefore sweep up nested children for free.

**`OrderField(for_fields=["unit"])` is not changed.** Sibling `order` values need not be contiguous
within a group; they only need to sort correctly among siblings. So the only change is that the code
computing "siblings" scopes itself to `(unit, parent, tab_id)` instead of `(unit)`. Touching
`OrderField` — whose `for_fields` behaviour with a nullable FK is unverified — is avoided entirely.

The insert and reorder paths coexist as follows, and cannot mis-sort:

- **Insert.** `OrderField` assigns the new row `max(order) + 1` computed **unit-wide**, ignoring
  group. That value is therefore greater than every existing `order` in the unit, and *a fortiori*
  greater than every `order` in the new row's own group — so the row lands last within its group,
  which is exactly append semantics. The unit-wide max is a harmless over-estimate, never a wrong
  sort.
- **Reorder.** The scoped sibling code renumbers only the members of one
  `(unit, parent, tab_id)` group, contiguously from 0. Because every query that consumes `order`
  filters to a single group first, `order` values are only ever compared *within* a group; two
  groups may freely reuse the same integers.

The one consequence to accept: after a group is renumbered, a subsequent insert anywhere in the unit
still draws from the unit-wide max, so `order` values grow monotonically and are not dense. Nothing
reads them as dense.

A single new migration adds the two fields.

### The invariant

This is the heart of the design, and the thing that keeps the change from leaking. It is **three**
classes, not two — an earlier framing as a RENDER/COLLECT binary was wrong, because `ordering.py`
belongs to neither:

> - **RENDER** walkers exclude children: add `parent__isnull=True`. They enumerate the blocks a
>   surface displays, and a nested child must never appear as a sibling of its own container.
> - **COLLECT** walkers include children. They gather everything a unit owns.
> - **SCOPE** walkers include children but *partition* them: they operate within one
>   `(unit, parent, tab_id)` group at a time. Filtering by `parent__isnull=True` would be actively
>   wrong here.

COLLECT further splits by **how** a walker reaches children, and the distinction decides whether it
needs code changes at all:

- **Reaches children for free**, because nested children retain their `unit` FK and the walker
  queries by `unit` / `unit__course`. No change needed.
- **Must recurse explicitly**, because the walker consumes a list that has *already* been
  RENDER-filtered upstream. `has_math` is exactly this case: it iterates the `elements` list built
  by the lesson/quiz view (`views.py:162-176`), which by then excludes children — so it must walk
  into `TabsElement.children` itself.

Every existing walker is classified exactly once:

| Walker | Class | Change |
|---|---|---|
| `views.py` lesson element list (~196) | RENDER | add `parent__isnull=True` |
| `views.py` quiz element list (~509) | RENDER | add filter |
| `views_manage.py` editor rows (~158, ~547, ~651) | RENDER | add filter |
| `quiz.py` (~104) | RENDER | add filter (defensive — questions cannot nest in v1) |
| `review.py` (~107, ~171) | RENDER | add filter (defensive) |
| `views_review.py` (~68) | RENDER | add filter (defensive) |
| `rollups.py` (~159, ~195) | RENDER | add filter (defensive) |
| `ordering.py` siblings (~47) | SCOPE | scope to `(unit, parent, tab_id)`; **never** `parent__isnull` |
| `models._delete_element_content_objects` | COLLECT (free) | **already correct** — filters `unit__course` |
| `notes/services.py` (~37) | COLLECT (free) | unchanged — see "Notes" below |
| `has_math` computation (lesson + quiz) | COLLECT (**must recurse**) | consumes the RENDER-filtered list |
| `courses/transfer/export.py` (~302) | COLLECT (**must recurse**) | recurse **and** nest the payload |

Two walkers are deliberately **exempt**, recorded here so that "every walker classified exactly once"
stays a true claim rather than an unchecked one:

- The quiz-**results** page renders only question rows, and a question can never be nested in v1, so
  no tabs element and no nested child can reach it. It needs neither a filter nor a recursion.
- `partition_into_slides()` is a **downstream consumer**, not a query: it receives the element list
  the lesson view already built, which by then carries the RENDER filter. It therefore needs no
  change — but the implementer must *verify* that it does not re-query the unit independently. If it
  ever did, nested children would leak in as phantom slide content.

The `has_math` row is the highest-risk line in this table. If it does not recurse, math authored
inside tab 2 never typesets — and it fails silently, because tab 1 typically has no math to reveal
the bug.

Its recursion must **dispatch each nested child through the same per-type math predicate the
top-level walk uses** (`_gallery_has_math`, `_table_has_math`, and so on) — not a generic scan for
`\(` / `\[` delimiters, and not an `isinstance(child, MathElement)` check. Math inside a nested
gallery's image description, or inside a nested table's cell, is found only by that type's own
predicate. A recursion that checks for a bare `MathElement` would pass a test written with a bare
`MathElement` and still leave the gallery and table cases silently broken — which is why test 2
below specifies the nested math as a **gallery description**, the case the naive implementation
misses.

The defensive filters on the four grading/review/analytics walkers cost nothing today (a nested
element can never be a question in v1) and mean the later questions-in-tabs slice starts from a
correct baseline rather than a latent bug.

A regression test pins the invariant directly: a nested child never surfaces as a top-level block on
the lesson page, the quiz page, or the editor element list.

### Notes

**A nested element cannot receive a personal note in v1**, and this falls out of the design rather
than needing enforcement. The notes UI binds its badge and anchor to `.lesson-block[data-element-id]`
sections, which `_lesson_article.html` emits only for **top-level** elements; a nested child is
rendered inside its panel and never becomes such a section. So no note can be created against one.

This matters because a note on a nested element would sit inside an inactive, `hidden` panel and hit
the same zero-height anchoring hazard the gallery does — the floating panel would position itself
against an invisible block. Rather than solve that, v1 simply cannot reach the state: scope is
immutable after creation (see "Server-side validation"), so an element that already carries a note
can never *become* nested either.

`notes/services.py` stays classified COLLECT purely because it queries by `unit` and would therefore
see children if any ever had notes; it needs no change. Notes on nested elements are a follow-up,
and they will need a `libli:reveal`-style solution.

### Deletion

Deleting a `TabsElement` cascades its child `Element` join-rows via the `parent` FK — but each
child's **concrete** object is reachable only through the generic FK, which the database cascade
cannot traverse, so the concretes would orphan. This is the same reason
`_delete_element_content_objects` exists at all.

`builder.delete_element` therefore collects the children first and routes them through that existing
helper before deleting the parent. Deleting a single **tab** (from the tabs edit form) does the same
for that tab's children. The test asserts zero orphaned concretes after both operations.

**The tabs form must round-trip every surviving tab's id.** `_edit_tabs.html` renders each existing
tab's id as a hidden field alongside its label input, so the id returns to the server on save. Only a
genuinely *new* tab row arrives without an id, and the server mints one for it. This is a hard
requirement of both mechanisms below: if the form submitted labels alone, the delete diff would see
every old id as removed and destroy every child, while `save()` would mint fresh ids for the
survivors and orphan the rest. Ids in, ids out.

**Deleting a tab is a list diff, not a delete endpoint.** `_edit_tabs.html` submits the *surviving*
tab list, so a removed tab is only visible to the server as an absence. The form's save path must
therefore compute it explicitly, before persisting the new list:

```
removed = {t["id"] for t in existing data["tabs"]} - {t["id"] for t in submitted tabs}
```

then collect `parent_join_row.children.filter(tab_id__in=removed)`, route their concretes through
`_delete_element_content_objects`, delete those join rows, and only then write the new
`data["tabs"]`. Skipping this step persists a valid-looking tabs element while silently orphaning
every concrete belonging to the removed tabs — the single most likely data-loss bug in this feature,
and the reason it is spelled out here rather than left to the implementer. It gets a dedicated test.

**Deleting a tab is refused below `MIN_TABS`.** The tabs edit form rejects a submission that would
leave fewer than `MIN_TABS = 2` tabs, surfacing a normal form validation error ("A tabs element must
keep at least 2 tabs"), and the editor disables the per-tab delete control at 2 tabs. Symmetrically,
it disables the add-tab control at `MAX_TABS = 10`, so neither bound is discovered only by hitting a
post-submit error. Both bounds remain enforced server-side regardless; the affordances are courtesy,
not the enforcement.

To remove the last two tabs the author deletes the whole tabs element. Deleting a tab is destructive
of that tab's children and the UI says so before it happens.

### Server-side validation

Nesting is enforced on the server, not merely in the UI.

The nested-child allowlist is a **new, narrower set** — `NESTABLE_TYPE_KEYS`, the 8 keys named under
"Scope (v1)". It is *not* the existing `element_add` / `element_save` allow-tuples, which admit every
question type and `slidebreak` and would therefore be wrong to reuse here. The two are independent
and both are needed:

- the existing allow-tuples are extended only to **add `"tabs"`** as a valid *top-level* type;
- `NESTABLE_TYPE_KEYS` separately gates what may be created *inside* a tab.

**Only the two creation views take `parent`/`tab` at all.** Scope is decided once, when an element is
created, and is immutable thereafter. This makes a cross-scope move impossible *by construction*
rather than by validation, and it is why the four views divide as follows:

| View | Takes `parent`/`tab`? | Scope behaviour |
|---|---|---|
| `element_add` | **yes** (from the nested add menu's `data-parent` / `data-tab`) | chooses the new element's scope |
| `element_save` | **yes, on create only** (`element_ref == "new"`) | on *update*, never reads or writes the join row's `parent` / `tab_id` — it edits the concrete's content only |
| `element_move` | **no** | reads the element's own `(unit, parent, tab_id)` and reorders **within** that group |
| `element_delete` | **no** | locates the row by pk |

Two consequences worth stating, because getting either wrong is a silent data bug:

- **`element_move` must not require the caller to resend scope.** An earlier framing had it validate
  that a requested `(parent, tab)` matched the element's current scope; but a reorder gesture sends
  no scope (top-level reorders never have), so "absent means top-level" would reject every
  *within-tab* reorder — the one nested move the design explicitly supports. Deriving the group from
  the element row instead is both simpler and correct.
- **`element_save` on update must never touch `parent` / `tab_id`.** The inline edit host form for a
  nested child does not resubmit its scope, so a save path that wrote "absent means top-level" would
  silently reparent the child out of its tab on every edit.

When `element_add`, or `element_save` with `element_ref == "new"`, supplies a `parent`:

1. `tab` is also supplied and non-empty — `parent` and `tab` come **together or not at all**, and one
   without the other is a `400`, checked explicitly rather than left to fall out of the lookup below;
2. the parent element exists and its concrete is a `TabsElement`;
3. the parent is in the same unit and the same course as the request;
4. the supplied `tab` id exists in the parent's `data["tabs"]`;
5. the child's type key is in `NESTABLE_TYPE_KEYS`.

Neither supplied means the new element is top-level. Any violation returns `400`.

### Editor — inline nested list

`_element_row.html` gains a `tabselement` branch. The row renders a tab strip, then an indented
`<ol class="element-list element-list--nested">` of child rows — a **recursive include of the same
partial** — then a nested `_add_menu.html` carrying `data-parent="{{ el.pk }}"` and
`data-tab="{{ tab.id }}"`.

Because a child row is the same partial, clicking ✎ on a nested element expands the same inline
`.el-edit-slot` host form it would at top level. There is no navigation, no new page, and no new
editing concept — the existing row / edit-slot / add-menu machinery is simply scoped to a parent.

The recursive include terminates **only** because tabs-inside-tabs is impossible: the template
itself carries no depth guard. That impossibility is upheld in two places — `NESTABLE_TYPE_KEYS`
excludes `tabs` on every write path, and import validation rejects a `parent` chain deeper than one
level — so the realized depth is always exactly 2. Should nested tabs ever be allowed, the template
needs an explicit depth bound before the model does.

`_edit_tabs.html` manages labels only: add, rename, reorder, delete a tab.

`element_add` accepts optional `parent` and `tab` parameters, and `element_save` accepts them only
when creating (`element_ref == "new"`). `element_move` and `element_delete` take neither — they
derive scope from the element row. See "Server-side validation" for why.

**Scope must survive the two-hop create.** Adding a nested element is two requests: the nested add
menu's `data-parent` / `data-tab` go to `element_add`, which only *renders* a blank host form; a
later `element_save` actually persists. So `element_add` must **embed `parent` and `tab` as hidden
fields in the host form it renders**, or they are lost between the hops and `element_save` — seeing
no scope — silently creates the child at top level. Same discipline as the tab ids in
`_edit_tabs.html`: whatever the server needs back, the form carries.

The editor branch of `_element_row.html` groups nested children with the **same `resolved_tabs()`
helper** the student template uses, rather than re-deriving the grouping. Single-sourcing it keeps
the two views from diverging — notably over read-side normalization, where an ad-hoc editor grouping
would miss `normalize_data`'s padding and truncation and show a different set of tabs than the
student sees.

### Student widget

`templates/courses/elements/tabselement.html` renders **every panel visible**, each preceded by its
label as a heading. That server output is simultaneously:

- the no-JS fallback (readable, nothing hidden), and
- what `@media print` shows.

**The template iterates every `resolved_tabs()` group, including empty ones**, emitting a label
heading and an empty panel per tab. A tabs element is *born* with two empty tabs, and a tab can be
emptied later, so skipping childless tabs would erase them from the strip the enhancer builds — the
author would create a tabs element and see no tabs at all. An empty panel renders as an empty panel.

`window.libliInitTabs(root)` then upgrades it in place to `role="tablist"` / `role="tab"` buttons
with `aria-selected` and `aria-controls`, `role="tabpanel"` panels, hides the inactive panels, and
wires ←/→/Home/End with **automatic activation** per the ARIA authoring practices.

**Panels are hidden with the `hidden` attribute, never an inline `display:none`.** Printing happens
*after* enhancement, so "print shows every panel" is only true if the hiding mechanism can be
overridden from a stylesheet — and an inline style cannot be. With the `hidden` attribute, a
`@media print` rule reveals all panels (and the tab strip's chevrons and fades are suppressed):

```css
@media print {
  .el--tabs [role="tabpanel"][hidden]  { display: block !important; }
  .el--tabs .tabs__strip               { display: none !important; }
  .el--tabs .tabs__panel-label         { display: block !important; }  /* no-JS headings return */
}
```

Every rule carries `!important`, including the label-reveal. The screen-hiding class the enhancer
applies to the labels may well match at equal specificity and later source order, in which case an
unweighted print rule silently loses and the labels vanish from print while the panel bodies remain.
The print test asserts the labels are **visible**, not merely present in the DOM.

**The enhancer must therefore preserve the per-panel `.tabs__panel-label` headings in the DOM.** It
builds the tab strip *from* those headings, and the tempting next step — detaching or reusing the
heading nodes — leaves the print rule with nothing to reveal, silently losing every panel title in
the printed output while the panel bodies still appear. The headings are instead **hidden on screen
via a class** after enhancement and revealed again by the rule above.

A test asserts both halves: that the print stylesheet reveals hidden panels, and that the labels
survive enhancement. This fails invisibly otherwise — nobody prints a lesson during development.

The initializer is multi-instance and idempotent — `querySelectorAll` with no module singletons, a
`dataset.tabsReady` guard, and a detached-container check. Both are lessons paid for by the gallery
slice, where a module singleton meant a lesson could hold only one carousel and a re-swap appended a
second nav bar.

**DOM ids must be document-unique, so the bare `tab_id` may never be used as one.** `aria-controls`
and `aria-labelledby` resolve against the whole document, but a tab id is only unique *within* one
`TabsElement` — two tabs elements on one lesson page can legitimately both contain `t7f3a1c`. Using
the raw id would produce duplicate DOM ids, invalid ARIA, and `getElementById` cross-talk in which
activating a tab in the second element reveals a panel in the first. The enhancer therefore
namespaces every generated DOM id with the element's own identity — the join-row pk, or a per-init
counter — e.g. `tabs-<element_pk>-<tab_id>-panel`. The multi-instance test puts two tabs elements on
one page, gives them a colliding tab id, and asserts that activating a tab in one leaves the other
untouched.

**Overflow.** The tab strip scrolls horizontally. It must always be visually obvious that more tabs
exist off-screen, so `.is-scroll-start` / `.is-scroll-end` are toggled on scroll and resize and drive
**both** an edge fade **and** a pair of chevron buttons. The chevrons are `aria-hidden` with
`tabindex="-1"`, because keyboard users already have arrow keys.

### Two known integration hazards

**A gallery inside a hidden tab panel measures zero height.** `gallery.js` reserves a stable
letterbox frame via a `ResizeObserver`; against a `display:none` panel it measures 0 and computes a
collapsed frame, which the student then sees the moment they reveal that tab. Fix: activating a tab
dispatches a `libli:reveal` event on the panel, and `gallery.js` listens and re-measures. (KaTeX, by
contrast, typesets hidden nodes happily, so math renders once at load for all panels.)

**Every surface that renders the student template must load `tabs.js`.** That is the lesson page,
the quiz page, **and** `editor.js`'s `applyFragments()` — which must call `libliInitTabs` *and*
re-run `libliInitGallery` for galleries nested inside panels. This is precisely the bug the gallery
slice shipped: the editor preview pane, labelled "as students see it", never loaded `gallery.js` and
so rendered the intentional no-JS stacked fallback, which read as a broken carousel (fixed in
PR #89). A progressively-enhanced element needs a third check beyond "does the fallback work" and
"does the enhancer work": *does every template that renders it load the enhancer.*

`.el--tabs` is added to `math.js`'s `renderInlineText` scope.

## Data flow

**Authoring.** Author picks Tabs from the add menu → `element_add` renders a blank `_edit_tabs.html`
host form → author names two tabs → `element_save` → `builder.save_element` takes the simple
single-form `else` branch and persists `TabsElement` + its `Element` join row. The editor fragment
swap re-renders the row, now showing a tab strip with two empty panels and a nested add menu.

Author picks Text from the *nested* add menu → the same `element_add`, now with `parent` and `tab`
read from the menu's data attributes → validation runs → the returned host form carries `parent` and
`tab` as hidden fields → `element_save` posts them back → the child `Element` row is created with
`unit` set, `parent` set to the tabs join row, and `tab_id` set to the chosen tab's id. Its `order`
is assigned among its `(unit, parent, tab_id)` siblings.

**Rendering.** The lesson view fetches top-level elements only (`parent__isnull=True`), so the tabs
element appears once and its children do not appear as sibling blocks. `TabsElement.render()`
resolves `data["tabs"]` against its `children`, grouped by `tab_id` and ordered by `order`, and
renders each child through the existing `render_element` tag. `has_math`, computed by a *collecting*
walk, recurses into children so KaTeX is loaded when only a nested element has math.

**Transfer.** `FORMAT_VERSION` goes 2 → 3. Each element payload gains optional `parent` (an internal
`e#` reference) and `tab` (the tab id). A v2 archive has no `parent` key, so the shim is a
`setdefault` — the same shape as the existing v1→v2 iframe-dimension shim.

Export has **two distinct walks**, and they must not be conflated or a nested gallery's media get
counted twice:

- the **payload walk** enumerates every element *including* children, emitting parents before
  children, so each gets its own `e#` entry;
- the **media walk** (`_element_mids`) iterates **top-level elements only** and recurses from a
  `TabsElement` into its children. Nested media are therefore collected exactly once, through the
  recursion, and never again by the outer iteration.

Import is **two-pass** for *reference resolution*. Pass 1 creates every element's concrete and join
row with `parent = None`; pass 2 resolves each `parent` `e#` reference and sets `parent` + `tab_id`.
This makes import robust to a hand-edited or re-serialized archive in which a child precedes its
parent, which a single-pass build would fail on.

Child **order within a tab** is preserved without serializing `order` explicitly, but only because
two things hold together, and both must be stated or an implementer may break one:

- export emits the elements of each `(parent, tab)` group in `order`, and
- pass 1 creates rows **in payload order**, so `OrderField`'s unit-wide `max(order) + 1`
  auto-assignment hands out strictly increasing values in that same sequence.

Pass 2 sets `parent`/`tab_id` but never touches `order`, and `order` is only ever compared within a
group, so the relative sequence assigned in pass 1 is exactly the archive's. The round-trip test
asserts this directly, with **two** children in tab 2 whose order must survive.

Both new payload keys get a v2 shim, not just `parent`: `setdefault("parent", None)` and
`setdefault("tab", "")`, so code that reads either key unconditionally cannot `KeyError` on a v2
archive.

Import **preserves tab ids verbatim** from the archive. The child payloads' `tab` values are
references into the parent's `data["tabs"]` ids, so regenerating those ids at import — which
`TabsElement.save()` would otherwise be free to do for a tab lacking one — would orphan every child.
`save()` therefore only ever *fills in* a missing id, and never rewrites an existing **unique** one,
on any code path.

The "unique" qualifier is load-bearing: `normalize_labels_and_ids` *does* rewrite the later of a
duplicate pair, so an archive carrying duplicate tab ids would survive validation, get its later
duplicate regenerated at `save()`, and orphan the child that referenced it. Import therefore rejects
duplicate tab ids outright (see "Error handling"), which is what makes duplicates unreachable on the
imported path and keeps this guarantee true.

## Error handling

- Normalization never raises. Every malformed `data` blob degrades to a valid structure rather than
  500-ing a lesson page. It is realized as **two distinct pure functions**, not one — each takes a
  blob and returns a blob, and neither writes to the database. The split is what keeps a save from
  destroying data, so it is a decomposition requirement, not a stylistic note:

  **`normalize_labels_and_ids(blob)` — non-destructive. Called by `save()`, and persisted.**

  | Input | Result |
  |---|---|
  | a tab is not a dict, or has no usable `label` | label falls back to `Tab N` (its 1-based position) |
  | a label containing markup | tags stripped |
  | a label longer than 80 characters | truncated to 80 |
  | a tab has no `id` | an id is generated (never overwriting a present one) |
  | duplicate ids | later duplicates are regenerated; the **first** occurrence keeps the id |

  It cannot change *which* tabs exist, so it cannot orphan a child by removing its tab. (One
  exception, noted for completeness: regenerating a duplicated id does change *that* tab's id, so a
  child pointing at the second occurrence is orphaned. Duplicate ids are unreachable on any authored
  or imported path — only a direct database edit produces them — so this is not a concern in
  practice, merely a limit on the guarantee.)

  **`normalize_data(blob)` — destructive. Called by `resolved_tabs()` at read time, and never
  persisted.** It applies `normalize_labels_and_ids` first, then:

  | Input | Result |
  |---|---|
  | missing `tabs` key, `data` not a dict, or `tabs` not a list | `MIN_TABS` generated tabs, labelled `Tab 1`, `Tab 2` |
  | fewer than `MIN_TABS` tabs | padded with generated tabs up to `MIN_TABS` |
  | more than `MAX_TABS` tabs | truncated to the first `MAX_TABS` |

  Padding and truncation change which tabs exist. Persisting them would permanently orphan children
  the first time an otherwise-valid element was re-saved — the failure this split exists to prevent.
  **`save()` must never call `normalize_data`.** Read-side application keeps the damage transient
  and recoverable: the stored `data` is untouched and the children still exist, so repairing the blob
  restores them.

  A blob can only *become* destructively-malformed via a direct database edit or an external
  mutation — the form enforces `MIN_TABS ≤ n ≤ MAX_TABS` on every authored write, and import rejects
  out-of-bounds tab counts outright (see below), so neither path can produce one.

- `resolved_tabs()` tolerates a child whose `tab_id` matches no tab in the normalized `data`
  (reachable via a direct DB edit, a read-side truncation, or a partially-applied import): such
  orphans are skipped, never rendered, never raised on. They remain in the database and are still
  swept by the delete helpers, so they can never leak as orphaned concretes.
- Form validation enforces `MIN_TABS ≤ n ≤ MAX_TABS` and non-empty labels (a blank label falls back
  to `Tab N`). Deleting a tab below `MIN_TABS` is refused, per "Deletion" above.
- Nesting violations return `400` from the element views, per "Server-side validation" above.
- Deleting a tabs element or a single tab never leaves orphaned concrete rows.
- Import rejects `version > FORMAT_VERSION`. Each of these is a validation error that aborts the
  import rather than producing a partial one: a `parent` reference to an unknown `e#`; a `tab` id
  absent from the referenced parent's `data["tabs"]`; a `parent` whose referent is not a
  `TabsElement`; a child whose type key is not in `NESTABLE_TYPE_KEYS`; a `parent` chain deeper than
  one level (which would otherwise defeat the template's implicit termination — see "Editor"); a tab
  id that does not match the `"t"` + 6-hex format, or would not fit `tab_id`'s `max_length=12`;
  **duplicate tab ids within one element's `data["tabs"]`**; and a `TabsElement` whose tab count
  falls outside `MIN_TABS … MAX_TABS`.

  The duplicate-id rejection is what makes `save()`'s "never rewrites an existing unique id"
  guarantee hold on the import path: without it, `normalize_labels_and_ids` would regenerate the
  later duplicate at save time and orphan the child referencing it.

  That last check is what keeps import validation and read-side normalization from racing. Because
  import **rejects** an out-of-bounds tab count rather than importing it, `normalize_data`'s
  destructive padding/truncation can never fire on imported data, and the question of whether a
  child's `tab` reference is checked before or after truncation never arises. Tab references are
  validated against the archive's own `data["tabs"]`, verbatim.

## Testing

TDD throughout. Beyond per-unit coverage of the model, form, views and transfer functions, these
tests carry the design's weight:

1. **The invariant.** A nested child never surfaces as a top-level block on the lesson page, the quiz
   page, or the editor element list.
2. **`has_math` recursion, on both sites, via a per-type predicate.** A **lesson** whose *only* math
   lives inside tab 2 still loads KaTeX — and, as a separate test, a **quiz** whose only math lives
   inside a nested element does too. The invariant table lists two independent `has_math` call sites,
   and tabs are a valid top-level element on the quiz element list, so covering only the lesson would
   leave the quiz path with the same silent-failure mode, unguarded.

   The nested math in both tests is a **gallery image description**, not a bare `MathElement`. A
   naive recursion that checks `isinstance(child, MathElement)` passes the bare-`MathElement` version
   of this test while leaving nested galleries and tables broken; using the gallery case forces the
   recursion through the real per-type predicates.
3. **Delete cascade.** Deleting a tabs element leaves zero orphaned concretes; deleting a single tab
   removes exactly that tab's children.
4. **Transfer round-trip.** Export then import a **gallery nested in tab 2** and assert the nesting,
   the media, **and the relative order of two children within that tab** all survive. A v2 archive
   still imports, with all elements top-level.
5. **Tab-id stability.** Reordering and deleting tabs never reassigns another tab's children.
6. **Nesting validation.** Adding a question, a slide break, or a tabs element inside a tab returns
   `400`; so does a `parent` in another course, and a `parent` without a `tab`.
7. **Scope immutability.** Reordering a nested child within its tab succeeds; editing and saving a
   nested child leaves its `parent` and `tab_id` unchanged; a freshly created tabs element renders
   both of its empty tabs. The first of these guards the reorder-rejection bug that an earlier
   scope-validation design would have introduced.
8. **Multi-instance isolation.** Two tabs elements on one page, sharing a colliding `tab_id`:
   activating a tab in one must leave the other untouched. Guards the namespaced-DOM-id requirement.
9. **Print fidelity.** After enhancement, the print stylesheet reveals every panel **and** every
   per-panel label — asserting visibility, not mere DOM presence.
10. **E2E, driving real gestures** (never a `page.evaluate` shortcut): create a tabs element, add a
    text element into tab 2, then on the student page click between tabs and arrow-key between tabs.
11. **Registry completeness.** The element summary renders "3 tabs" (via `ngettext`, with Polish's
    three plural forms), not a raw `TabsElement` class name — the exact regression the gallery slice
    shipped.

### Definition of done

- Full non-e2e suite green (~2240 tests), plus the full `-m e2e` suite re-run at the end, because
  `pytest` deselects e2e by default and a per-task e2e written early can silently go stale — this bit
  the table slice in CI.
- `ruff check` **and** `ruff format --check`.
- The i18n catalog tests, which fail on obsolete `#~` entries whenever a build removes translatable
  strings.
- EN + PL catalogs complete.
- Shipped **styled** — a frontend-design pass inside this slice, as the gallery slice did, not
  deferred as the table slice did. Light and dark verified with screenshots before the PR opens.

## Implementation notes

### The registry sites

A new element type must be added to each of these. `grep` for `gallery` to locate every one:

1. `courses/models.py` — `ELEMENT_MODELS` (~255)
2. `courses/element_forms.py` — `FORM_FOR_TYPE` (~714)
3. `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS` (~25) **and** an
   `element_summary` branch (~69)
4. `courses/views_manage.py` — `_EDITOR_TYPE_LABELS` (~723)
5. `courses/views_manage.py` — `element_add` allow-tuple (~846)
6. `courses/views_manage.py` — `element_save` allow-tuple (~878)
7. `courses/transfer/export.py` — `SERIALIZERS` + `_MODEL_TO_KEY` (~202)
8. `courses/transfer/payloads.py` — `VALIDATORS` (~404)
9. `courses/transfer/importer.py` — `BUILDERS` (~614)

Plus: `templates/courses/manage/editor/_edit_tabs.html`;
`templates/courses/elements/tabselement.html`; an `el-tabs` symbol in
`templates/courses/manage/_icon_sprite.html` at **16×16 fill**, matching its siblings (the table
slice wrongly used a 24×24 stroke icon and had to be corrected); `courses.css`; `tabs.js`; the
`editor.js` init hook.

Two key namespaces exist — the editor/UI key derives from the model name, while the transfer key is
hand-chosen snake_case. For this element both are `tabs`; keep them consistent.

`courses/builder.py` `save_element` (~206) has an `else` branch for simple single-form types; tabs
belongs there. The `("image", "video", "gallery")` course-kwarg tuples (`views_manage` ~762, ~949;
`builder` ~304) do **not** need tabs.

### Conventions

- Module-level translatable dicts must use `gettext_lazy`. Eager `gettext` once froze the editor's
  type labels to English.
- Django `{# #}` comments must be single-line; use `{% comment %}` for multi-line, or it renders as
  visible text.
- All icons are monochrome `currentColor` line SVGs via the shared `.icon` util — never emoji.
- JS-built controls cannot call `{% trans %}`. Labels ride on `data-msg-*` attributes and are read
  via a `label(root, key, fallback)` helper, following `table_editor.js`.
- No hardcoded test passwords — use `tests.factories.TEST_PASSWORD`; CI's secret scanner flags
  literals.
- `uv run` for `ruff` / `pytest` / `python`; they are not on the bash `PATH`.
