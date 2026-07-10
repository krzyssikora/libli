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

- Labels are **plain text**, not rich text and not math: tags are stripped at `save()` and the label
  is truncated to exactly **80 characters**.
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
already inherits from `ElementBase` — `self.elements.first()` — and from there `.children`. This
keeps `render()`'s existing zero-argument signature and requires no change to the `render_element`
template tag.

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
| `notes/services.py` (~37) | COLLECT (free) | unchanged — a note may attach to a nested element |
| `has_math` computation (lesson + quiz) | COLLECT (**must recurse**) | consumes the RENDER-filtered list |
| `courses/transfer/export.py` (~302) | COLLECT (**must recurse**) | recurse **and** nest the payload |

The `has_math` row is the highest-risk line in this table. If it does not recurse, math authored
inside tab 2 never typesets — and it fails silently, because tab 1 typically has no math to reveal
the bug. It gets its own test.

The defensive filters on the four grading/review/analytics walkers cost nothing today (a nested
element can never be a question in v1) and mean the later questions-in-tabs slice starts from a
correct baseline rather than a latent bug.

A regression test pins the invariant directly: a nested child never surfaces as a top-level block on
the lesson page, the quiz page, or the editor element list.

### Deletion

Deleting a `TabsElement` cascades its child `Element` join-rows via the `parent` FK — but each
child's **concrete** object is reachable only through the generic FK, which the database cascade
cannot traverse, so the concretes would orphan. This is the same reason
`_delete_element_content_objects` exists at all.

`builder.delete_element` therefore collects the children first and routes them through that existing
helper before deleting the parent. Deleting a single **tab** (from the tabs edit form) does the same
for that tab's children. The test asserts zero orphaned concretes after both operations.

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
keep at least 2 tabs"), and the editor hides or disables the per-tab delete control at 2 tabs. To
remove the last two tabs the author deletes the whole tabs element. Deleting a tab is destructive of
that tab's children and the UI says so before it happens.

### Server-side validation

Nesting is enforced on the server, not merely in the UI.

The nested-child allowlist is a **new, narrower set** — `NESTABLE_TYPE_KEYS`, the 8 keys named under
"Scope (v1)". It is *not* the existing `element_add` / `element_save` allow-tuples, which admit every
question type and `slidebreak` and would therefore be wrong to reuse here. The two are independent
and both are needed:

- the existing allow-tuples are extended only to **add `"tabs"`** as a valid *top-level* type;
- `NESTABLE_TYPE_KEYS` separately gates what may be created *inside* a tab.

`parent` and `tab` are supplied **together or not at all**: a request carrying one without the other
is a `400`, checked explicitly rather than left to fall out of the tab-lookup below. Neither supplied
means the element is top-level.

On `element_add` / `element_save` / `element_move` / `element_delete`, when a `parent` is supplied:

1. `tab` is also supplied and non-empty,
2. the parent element exists and its concrete is a `TabsElement`,
3. the parent is in the same unit and the same course as the request,
4. the supplied `tab` id exists in the parent's `data["tabs"]`,
5. the child's type key is in `NESTABLE_TYPE_KEYS`.

Additionally, because cross-scope moves are out of scope for v1, **`element_move` must not change an
element's scope**: it validates that the requested `(parent, tab)` is identical to the element's
current `(parent, tab_id)` — including the top-level case, where both must be null/empty. A move
that would relocate an element into, out of, or between tabs is rejected. Without this check the
`parent`/`tab` parameters that `element_move` accepts would be a back door around the stated scope
limit.

Any violation returns `400`.

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

`element_add`, `element_save`, `element_move` and `element_delete` accept optional `parent` and `tab`
parameters.

### Student widget

`templates/courses/elements/tabselement.html` renders **every panel visible**, each preceded by its
label as a heading. That server output is simultaneously:

- the no-JS fallback (readable, nothing hidden), and
- what `@media print` shows.

`window.libliInitTabs(root)` then upgrades it in place to `role="tablist"` / `role="tab"` buttons
with `aria-selected` and `aria-controls`, `role="tabpanel"` panels, hides the inactive panels, and
wires ←/→/Home/End with **automatic activation** per the ARIA authoring practices.

**Panels are hidden with the `hidden` attribute, never an inline `display:none`.** Printing happens
*after* enhancement, so "print shows every panel" is only true if the hiding mechanism can be
overridden from a stylesheet — and an inline style cannot be. With the `hidden` attribute, a
`@media print` rule reveals all panels (and the tab strip's chevrons and fades are suppressed):

```css
@media print {
  .el--tabs [role="tabpanel"][hidden] { display: block !important; }
  .el--tabs .tabs__strip { display: none; }
  .el--tabs .tabs__panel-label { display: block; }   /* the no-JS headings return */
}
```

A test asserts the print stylesheet reveals hidden panels, because this fails invisibly — nobody
prints a lesson during development.

The initializer is multi-instance and idempotent — `querySelectorAll` with no module singletons, a
`dataset.tabsReady` guard, and a detached-container check. Both are lessons paid for by the gallery
slice, where a module singleton meant a lesson could hold only one carousel and a re-swap appended a
second nav bar.

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

Author picks Text from the *nested* add menu → the same `element_add`, now with `parent` and `tab` →
validation runs → on save, the child `Element` row is created with `unit` set, `parent` set to the
tabs join row, and `tab_id` set to the chosen tab's id. Its `order` is assigned among its
`(unit, parent, tab_id)` siblings.

**Rendering.** The lesson view fetches top-level elements only (`parent__isnull=True`), so the tabs
element appears once and its children do not appear as sibling blocks. `TabsElement.render()`
resolves `data["tabs"]` against its `children`, grouped by `tab_id` and ordered by `order`, and
renders each child through the existing `render_element` tag. `has_math`, computed by a *collecting*
walk, recurses into children so KaTeX is loaded when only a nested element has math.

**Transfer.** `FORMAT_VERSION` goes 2 → 3. Each element payload gains optional `parent` (an internal
`e#` reference) and `tab` (the tab id). Export walks the unit's elements including children, emits
parents before children, and `_element_mids` recurses into children so a gallery nested in a tab
still contributes its media to the archive's media list. A v2 archive has no `parent` key, so the
shim is a `setdefault` — the same shape as the existing v1→v2 iframe-dimension shim.

Import is **two-pass**, and does not rely on the archive's element ordering. Pass 1 creates every
element's concrete and join row with `parent = None`; pass 2 resolves each `parent` `e#` reference
and sets `parent` + `tab_id`. This makes import robust to a hand-edited or re-serialized archive in
which a child precedes its parent, which a single-pass build would fail on.

Import **preserves tab ids verbatim** from the archive. The child payloads' `tab` values are
references into the parent's `data["tabs"]` ids, so regenerating those ids at import — which
`TabsElement.save()` would otherwise be free to do for a tab lacking one — would orphan every child.
`save()` therefore only ever *fills in* a missing id and never rewrites an existing one, on any code
path.

## Error handling

- `normalize_data()` never raises. Every malformed `data` blob degrades to a valid structure rather
  than 500-ing a lesson page. It is a **pure function**: it takes a blob and returns a normalized
  blob, and never writes to the database itself.

  Its degrade cases divide into two kinds, and the distinction is load-bearing:

  | Input | Result | Kind |
  |---|---|---|
  | a tab is not a dict, or has no usable `label` | label falls back to `Tab N` (its 1-based position) | non-destructive |
  | a tab has no `id` | an id is generated (never overwriting a present one) | non-destructive |
  | duplicate ids | later duplicates are regenerated; the **first** occurrence keeps the id | non-destructive |
  | missing `tabs` key, `data` not a dict, or `tabs` not a list | `MIN_TABS` generated tabs, labelled `Tab 1`, `Tab 2` | destructive |
  | fewer than `MIN_TABS` tabs | padded with generated tabs up to `MIN_TABS` | destructive |
  | more than `MAX_TABS` tabs | truncated to the first `MAX_TABS` | destructive |

  **Where each kind runs:**

  - **`save()` applies only the non-destructive cases** — label fallback, id fill-in, duplicate-id
    resolution — and persists the result. All three are idempotent and cannot change *which* tabs
    exist, so they can never orphan a child.
  - **The destructive cases are read-side only.** They are applied by `resolved_tabs()` when
    rendering a damaged blob, and are **never persisted**. Padding and truncation change which tabs
    exist, so persisting them would permanently orphan children the first time an otherwise-valid
    element was re-saved. Read-side application keeps the damage transient and recoverable: the
    underlying `data` is untouched, and the children still exist.

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
  id that does not match the `"t"` + 6-hex format, or would not fit `tab_id`'s `max_length=12`; and
  a `TabsElement` whose tab count falls outside `MIN_TABS … MAX_TABS`.

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
2. **`has_math` recursion.** A lesson whose *only* math lives inside tab 2 still loads KaTeX. (Guards
   the silent-failure case.)
3. **Delete cascade.** Deleting a tabs element leaves zero orphaned concretes; deleting a single tab
   removes exactly that tab's children.
4. **Transfer round-trip.** Export then import a **gallery nested in tab 2** and assert both the
   nesting and the media survive. A v2 archive still imports, with all elements top-level.
5. **Tab-id stability.** Reordering and deleting tabs never reassigns another tab's children.
6. **Nesting validation.** Adding a question, a slide break, or a tabs element inside a tab returns
   `400`; so does a `parent` in another course.
7. **E2E, driving real gestures** (never a `page.evaluate` shortcut): create a tabs element, add a
   text element into tab 2, then on the student page click between tabs and arrow-key between tabs.
8. **Registry completeness.** The element summary renders "3 tabs" (via `ngettext`, with Polish's
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
