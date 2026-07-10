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
substrate and one crisply-stated invariant, so that the ~10 existing places that walk a unit's
element list each get classified exactly once rather than drifting.

### Scope (v1)

**Allowed inside a tab:** text, math, image, video, iframe, html, table, gallery.

**Blocked in v1:** all question elements, slide break, tabs-inside-tabs.

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
    # data = {"tabs": [{"id": "t7f3a1", "label": "Definition"},
    #                  {"id": "t2b9c4", "label": "Example"}]}
```

- Labels are **plain text**, not rich text and not math: tags are stripped at `save()` and the label
  is truncated to ~80 characters.
- Each tab carries a **stable short id**, never an index. Reordering or deleting a tab must not
  silently reassign another tab's children — the classic index-shift bug. Ids are generated
  server-side, unique within the element.
- `normalize_data()` never raises, matching the `TableElement` / `GalleryElement` precedent: a
  malformed blob degrades to a sane default rather than 500-ing a lesson page.
- `render()` resolves each tab to its ordered child elements and renders
  `courses/elements/tabselement.html`.

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

A single new migration adds the two fields.

### The invariant

This is the heart of the design, and the thing that keeps the change from leaking:

> **Walkers that RENDER exclude children (`parent__isnull=True`). Walkers that COLLECT include
> them.**

Every existing walker is classified exactly once:

| Walker | Class | Change |
|---|---|---|
| `views.py` lesson element list (~196) | RENDER | add `parent__isnull=True` |
| `views.py` quiz element list (~509) | RENDER | add filter |
| `views_manage.py` editor rows (~158, ~547, ~651) | RENDER | add filter |
| `ordering.py` siblings (~47) | RENDER | scope to `(unit, parent, tab_id)` |
| `quiz.py` (~104) | RENDER | add filter (defensive — questions cannot nest in v1) |
| `review.py` (~107, ~171) | RENDER | add filter (defensive) |
| `views_review.py` (~68) | RENDER | add filter (defensive) |
| `rollups.py` (~159, ~195) | RENDER | add filter (defensive) |
| `models._delete_element_content_objects` | COLLECT | **already correct** (filters `unit__course`) |
| `has_math` computation (lesson + quiz) | COLLECT | **must recurse** |
| `courses/transfer/export.py` (~302) | COLLECT | must recurse **and** nest |
| `notes/services.py` (~37) | COLLECT | unchanged — a note may attach to a nested element |

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

### Server-side validation

Nesting is enforced on the server, not merely in the UI. On `element_add` / `element_save` /
`element_move`, when a `parent` is supplied:

1. the parent is a `TabsElement`,
2. the parent is in the same unit and the same course as the request,
3. the supplied `tab` id exists in the parent's `data["tabs"]`,
4. the child's type key is in the allowed set (not a question, slide break, or tabs).

Any violation returns `400`. This extends the two existing allow-tuples in `views_manage.py` rather
than introducing a parallel concept.

### Editor — inline nested list

`_element_row.html` gains a `tabselement` branch. The row renders a tab strip, then an indented
`<ol class="element-list element-list--nested">` of child rows — a **recursive include of the same
partial** — then a nested `_add_menu.html` carrying `data-parent="{{ el.pk }}"` and
`data-tab="{{ tab.id }}"`.

Because a child row is the same partial, clicking ✎ on a nested element expands the same inline
`.el-edit-slot` host form it would at top level. There is no navigation, no new page, and no new
editing concept — the existing row / edit-slot / add-menu machinery is simply scoped to a parent.

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
still contributes its media to the archive's media list. Import builds parents first, then resolves
child references. A v2 archive has no `parent` key, so the shim is a `setdefault` — the same shape as
the existing v1→v2 iframe-dimension shim.

## Error handling

- `normalize_data()` never raises. A malformed `data` blob — missing `tabs`, non-list, tabs without
  ids, duplicate ids, more than `MAX_TABS` — degrades to a valid structure rather than 500-ing.
- `resolved_tabs()` tolerates a child whose `tab_id` matches no tab in `data` (possible only via a
  direct DB edit or a partially-applied import): such orphans are skipped, never rendered, never
  raised on.
- Form validation enforces `MIN_TABS ≤ n ≤ MAX_TABS` and non-empty labels (a blank label falls back
  to `Tab N`).
- Nesting violations return `400` from the element views, per "Server-side validation" above.
- Deleting a tabs element or a single tab never leaves orphaned concrete rows.
- Import rejects `version > FORMAT_VERSION`; a `parent` reference to an unknown `e#`, or a `tab` id
  absent from the referenced parent, is a validation error rather than a partial import.

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
