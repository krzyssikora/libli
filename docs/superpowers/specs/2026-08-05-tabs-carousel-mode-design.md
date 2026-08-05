# Tabs element — carousel display mode

## Purpose

Give authors a **gallery-style carousel whose slides hold arbitrary elements** — tables
above all, but equally text, math, images or a nested container. Today the only carousel in
libli is `GalleryElement`, and it is image-only by construction, so an author who wants to
step a reader through several tables has to screenshot them — which freezes the tables into
one colour mode and loses the theme tokens, selectable text, and print fidelity that real
table elements have.

The cheapest correct answer is **not** to generalise the gallery. `TabsElement` is already a
registered container whose slots hold real child `Element` rows, and `"table"` is already in
`NESTABLE_TYPE_KEYS` (`courses/builder.py:75`) — so "several tables, one visible at a time"
already works today; only the *navigation idiom* is missing. This spec adds a **display
mode** to the tabs element: the same data, the same children, the same editor, rendered
either as today's tab strip or as a gallery-style carousel with prev/next arrows and dots.

### Why not extend the gallery

`GalleryElement` (`courses/models.py:1275`) stores `data = {desc_pos, images: [{media: int,
desc: str}]}`. `resolved_images()` does an `in_bulk` over `MediaAsset` and `render()`
returns `""` when nothing resolves; the per-slide `desc` is rich text but passes through
`sanitize_cell`, which does not keep table markup. There is no seam where a child element
could enter. Turning it into a real container would require a data migration converting
every stored `images` list into child `Element` rows on every deployed database, entries in
all three container registries, unwinding the per-type media-list export pass built for it,
and a full editor rewrite — to arrive where tabs already stands. **The gallery is out of
scope and must not be modified by this work.**

### What the student sees

| | `display: tabs` (today, default) | `display: carousel` (new) |
|---|---|---|
| Navigation | `role=tablist` strip of labelled buttons | ‹ › arrows + one dot per slide |
| Access | Random — click any label | Sequential — clamped at both ends, no wrap |
| Label | *Is* the button | A caption above/below the slide, or hidden |
| Width | The strip must fit the 648px content column | Fixed-size nav bar regardless of slide count |

### Author-facing copy

- The tabs editor gains a **Display** select: EN "Tabs" / "Carousel", PL "Zakładki" /
  "Karuzela".
- And a **Label position** select, meaningful only in carousel mode: EN "Above" / "Below" /
  "Hidden", PL "Nad" / "Pod" / "Ukryta".
- The palette card stays **Tabs** — this is a setting on the existing element, not a new
  one. Discoverability was weighed against a separate picker entry and deliberately traded
  away for the smaller change.

## Architecture / components

### Data model — `courses/models.py`, `TabsElement`

`data` gains two scalar keys beside the existing `tabs` list:

```python
DISPLAYS = {"tabs", "carousel"}
DEFAULT_DISPLAY = "tabs"
LABEL_POSITIONS = {"above", "below", "hidden"}
DEFAULT_LABEL_POS = "above"
```

Both are coerced enum-or-default exactly as `GalleryElement.desc_pos` is
(`courses/models.py:1305`): an unrecognised value normalises to the default and **never
raises**. Neither key is nullable and neither is ever absent after normalisation.

**No migration.** `data` is a `JSONField`; both normalizers supply the defaults on read, so
every stored tabs element keeps rendering exactly as it does today with no database change
and no backfill. This is the same "new optional key, defaulted on read" shape the gallery's
`desc_pos` and the image element's `size` already use.

`default_data()` gains both keys explicitly, so a freshly added element is self-describing
rather than relying on a later normalisation pass to fill it in.

#### ⚠️ The `save()` key-drop trap — the single highest-risk point of this change

`normalize_labels_and_ids` currently ends with:

```python
return {"tabs": tabs}
```

and `save()` (`courses/models.py:1455`) does `self.data = self.normalize_labels_and_ids(self.data)`.
**Any key not present in that returned literal is silently discarded on every save.** If the
new keys are threaded through the form but not through this normalizer, the setting will
appear to work in the editor, survive the POST, and vanish the moment the row is written —
with no error anywhere.

The same literal-rebuild appears a second time in `TabsElementForm.clean_data`
(`courses/element_forms.py:1694`), which returns
`TabsElement.normalize_labels_and_ids({"tabs": tabs})` — a fresh dict that drops whatever
the author submitted unless the two keys are passed into it.

Both sites must be fixed. `normalize_data` — the destructive read-side normalizer that pads
to `MIN_TABS` and truncates to `MAX_TABS` — builds on `normalize_labels_and_ids` and
therefore inherits both keys for free, provided it does not rebuild its own literal either.

The existing split stands unchanged and is load-bearing: `save()` must **never** call
`normalize_data`, because persisting its padding/truncation would permanently orphan a tab's
children.

### Form — `courses/element_forms.py`, `TabsElementForm`

- `clean_data` reads `raw.get("display")` and `raw.get("label_pos")` from the submitted JSON
  and passes both into the normalizer call, so the normalizer remains the one place the
  enum coercion lives.
- **An unrecognised value is coerced to the default, not rejected.** These values originate
  in a `<select>`; a value outside the enum means a hand-tampered payload, and matching
  `desc_pos`'s total-normalisation behaviour keeps the write path incapable of 500ing. The
  slide-count bounds keep raising `ValidationError` as they do today — that check is about
  *which tabs exist* and is not comparable.
- Two new `cached_property` accessors, `editor_display` and `editor_label_pos`, mirror
  `editor_rows`' existing bound/unbound source selection (`self._raw_data_json()` when
  bound, `self.instance.data` otherwise), so an invalid re-render preserves the author's
  selection instead of snapping back to the default.

### Editor — `templates/courses/manage/editor/_edit_tabs.html` + `tabs_editor.js`

Two `<select>` controls are added above the label rows. **Neither carries a `name`
attribute**: the partial's documented contract is that the hidden `name="data"` field is the
*sole authoritative input*, and `tabs_editor.js` mirrors every control into it. They are
addressed by `data-tab-display` and `data-tab-label-pos`, matching the existing
`data-tab-row` / `data-tab-label-input` convention.

`tabs_editor.js` changes in two places: its serializer emits `display` and `label_pos`
alongside `tabs`, and a `change` listener on either select re-serialises. It also toggles a
`hidden` attribute on the label-position row whenever `display !== "carousel"`, since the
setting has no effect in tabs mode.

The option *values* come from the model constants via the existing `tabs_bounds` template
tag (`courses/templatetags/courses_manage_extras.py:177`), extended to expose ordered
`(value, label)` pairs, so the template never hardcodes an enum member. The human-readable
option labels live in module-level mappings on the model and **must** use `gettext_lazy` —
a module-level dict evaluated at import time with plain `gettext` freezes the first
request's locale for the process lifetime.

### Student template — `templates/courses/elements/tabselement.html`

The root element gains `data-display="{{ display }}"` and `data-label-pos="{{ label_pos }}"`;
`TabsElement.render` adds both to its context, read from `normalize_data(self.data)` (the
same normalized blob `resolved_tabs()` already reads).

**The existing markup is unchanged in both modes and remains the no-JS and print fallback**
— every section emitted, each panel under its `h3` label, all visible. That is already the
right behaviour for a carousel: without JS a reader sees every slide stacked and labelled,
and that is also exactly what should print.

### CSS — `courses/static/courses/css/courses.css`

Three existing rules key on tabs-mode assumptions and break in carousel mode. Each must be
scoped or paired:

1. **`.el--tabs.tabs--js .tabs__panel-label` is visually hidden** (`:1496`) — correct for
   tabs, where the label became a strip button, but in carousel mode with `label_pos` of
   `above`/`below` the label *is* the caption and must be visible. Scope the sr-only rule to
   `[data-display="tabs"]`, and apply it in carousel mode only when
   `[data-label-pos="hidden"]`. The enhancer keeps adding `.tabs--js` in both modes so the
   other `.tabs--js` rules (e.g. the `:not(.tabs--js)` section spacing at `:1537`) stay
   correct.
2. **The print rule keys on `[role="tabpanel"][hidden]`** (`:1543`, `display: block
   !important`). Carousel panels are hidden by the same `hidden` attribute but carry **no
   `role=tabpanel`**, so as written the rule would not match and *printing a carousel would
   silently lose every slide but the current one* — the exact failure mode the comment at
   `:883` warns about for another element. The print block must also match the carousel's
   panels (e.g. via `[data-tab-panel][hidden]`, which covers both modes).
3. **`.el--tabs .tabs__bar { display: none !important; }` in print** (`:1547`) hides the tab
   strip. The carousel's nav bar needs the same treatment; if it uses a different class, add
   it to that rule.

New carousel styling — the nav bar, the arrow buttons, the dots, and the cross-fade — is
additive and token-driven, following the gallery's `.el--gallery` block. The fade duration
in CSS **must** equal the JS constant (see below). Both light and dark are in scope and are
judged separately.

### `courses/static/courses/js/tabs.js` — the carousel branch

The carousel lives **inside `tabs.js`, not a new file.** `tabs.js` already exposes idempotent
`window.libliInitTabs(root)` (`:201`) and `editor.js:105` already re-runs it over the
live-preview pane after every fragment swap — so folding in means the editor preview needs
**no new wiring**. A separate file would need a new `window.libliInit*` export registered in
`editor.js` *and* script tags in three templates; the gallery shipped a visible bug at
exactly that seam, rendering its no-JS stacked fallback in a pane labelled "as students see
it" because `editor.html` never loaded `gallery.js`.

`initOne` reads `container.getAttribute("data-display")` after its existing
`dataset.tabsReady` guard and the `ownSections` lookup, then branches. Shared by both modes,
unchanged:

- The **idempotence guard** (`:55`) — the preview pane re-runs the enhancer over the whole
  pane on every swap; re-entering would append a second nav bar.
- The **nested-instance scoping** (`ownSections` / `ownPart`, `:33-50`). Since the depth-3
  lift a tabs element may legally contain another tabs element, so a descendant-wide lookup
  from the outer container would swallow the inner instance's sections. A carousel may
  likewise contain a tabs element, or a tabs element a carousel; the carousel branch uses
  the same helpers and must never use a bare `querySelectorAll`.
- The `eid` DOM-id namespacing (`:65`) — two carousels on one page must not collide.

Carousel-specific behaviour:

- **Nav DOM** appended after the sections (the gallery's order: content, then nav), holding
  a prev button, a dot per slide, and a next button.
- **Arrows are real, focusable, labelled buttons.** This differs deliberately from the tabs
  chevrons, which are `aria-hidden` with `tabIndex = -1` (`:12-13`) *because* keyboard users
  navigate that mode via the tablist's arrow keys. Carousel mode has no tablist, so hiding
  its only controls from assistive technology would leave it unoperable.
- **Clamped, never wrapping**: at slide 1 the prev button is `disabled`, at slide N the next
  button is `disabled` — the gallery's boundary behaviour.
- **Dots are unconditional.** `MAX_TABS` is 10, so the gallery's "more than 12 dots → show a
  counter instead" branch is dead code here and is not ported.
- **No tab roles.** No `role=tablist`, `role=tab`, or `role=tabpanel` in carousel mode — it
  is not a tab set. Inactive panels get the `hidden` attribute (never an inline
  `display:none`, which the print rule could not override) plus `aria-hidden="true"`,
  matching the gallery.
- **A visually-hidden `aria-live="polite"` status region** announces "Slide *n* of *N*" on
  each change. The gallery has none; a carousel whose only cue is a dot's colour is opaque
  to a screen-reader user, and this is the cheap standard remedy.
- **Keyboard**: Left/Right step one slide, Home/End jump to the ends, following the
  gallery's guard that ignores the keys when focus is inside an `input`, `select`,
  `textarea`, or a contenteditable — slides can contain form controls.
- **Cross-fade** of 320 ms, matching the gallery's `FADE_MS` and the CSS transition, and
  reduced to 0 when `prefers-reduced-motion` matches.
- **`libli:reveal`** is dispatched on the newly shown panel, exactly as `select()` does at
  `tabs.js:148`. A gallery inside a hidden panel measures zero height and listens for this
  event to re-measure; a carousel that skipped it would show a collapsed letterbox to any
  reader who advanced to a slide containing a gallery.

### Height reservation

Slides have no intrinsic aspect ratio, so without reservation every arrow click reflows the
page. Port the gallery's stable-frame reservation (`gallery.js:179-227`) to the carousel's
stage, simplified to a single measured set (the panels) since there is no separate caption
strip to equalise:

1. **Clear the reservation before measuring**, or the second pass reads the reserve back as
   the natural height and the frame can only ever grow.
2. Reserve `max(panel.offsetHeight)` as the stage's `min-height`.
3. Re-measure on `resize` and via a `ResizeObserver` on each panel, **rAF-coalesced** — the
   measure mutates the very elements the observer watches, so an uncoalesced version
   re-enters and logs "ResizeObserver loop limit exceeded".
4. **Keep the detached-container guard**: a preview-pane swap detaches the container but
   leaves the `resize` listener and the observer bound. The guard disconnects both when
   `!container.isConnected`.
5. **Keep both `libli:reveal` listeners** — one on the container, one delegated on
   `document` filtered by `e.target.contains(container)` — so a carousel nested inside a
   collapsed tab, spoiler or callout measures correctly the moment its ancestor opens rather
   than reserving a zero-height frame.

KaTeX typesets after first paint and changes panel heights; the `ResizeObserver` is what
catches that, which is why it is not optional.

### i18n

`window.TABS_I18N` gains the carousel strings (previous slide, next slide, "Slide {n} of
{total}", and the dot labels). The literal is duplicated in **three** templates —
`lesson_unit.html:80`, `quiz_unit.html:33`, and `manage/editor/editor.html:168` — and all
three must be updated together, or the carousel silently falls back to the untranslated
defaults on whichever surface was missed. Polish translations are added for every new
string, and the compiled `.mo` is regenerated before the PR.

### Transfer — `courses/transfer/`

Three coordinated edits, plus a format bump:

- **`export.py:234` `_ser_tabs`** emits `display` and `label_pos` alongside `tabs`, read
  from the non-destructive normalizer it already calls (which now always supplies them).
- **`payloads.py:707` `_val_tabs`** uses `_exact_keys(data, ["tabs"], …)`, and
  `_exact_keys` (`schema.py:97`) both *requires* every listed key and *rejects* every
  unlisted one. So a pre-change archive would fail with "unknown key" the moment export
  starts emitting them, and a post-change archive would fail "missing the key" against the
  old list. Use the established **optional-key pattern**: `data.setdefault("display",
  "tabs")` and `data.setdefault("label_pos", "above")` *before* the `_exact_keys` call, then
  add both to the key list — mirroring the image element's `size` (`payloads.py:133`) and
  the iframe's `width`/`height` (`payloads.py:164`). When present, each value is validated
  against the model's constant and **rejected** if invalid, matching `_val_gallery`'s
  treatment of `desc_pos` (`payloads.py:568`); import validates strictly even though the
  form normalises leniently, because a rejected import is visible while a silently rewritten
  one is not.
- **`importer.py:783` `_build_tabs`** constructs `TabsElement(data={"tabs": data["tabs"]})`
  from an explicit literal and must pass both new keys through. `setdefault` mutated the
  validated dict in place, so they are guaranteed present by the time this runs.
- **`schema.py:14` `FORMAT_VERSION` 7 → 8.** The importer rejects any archive whose version
  exceeds its own (`importer.py:189`), which is what stops an older libli from choking on
  keys it has never heard of. Adding emitted keys without the bump would hand an old
  instance a same-version archive it cannot parse.

### Explicitly untouched

`_CONTAINER_REGISTRY`, `CONTAINER_TRANSFER_KEYS`, `payloads._CONTAINER_SLOT_KEY`, the
nesting rules and `MAX_NEST_DEPTH` arithmetic, the element clipboard and paste path,
`builder_filter`, and `_ELEMENT_LABELS` / `element_summary`. `TabsElement` is already a
registered container, so children, depth limits, filtering, pasting and export/import
routing all keep working with no edits — that is the whole reason this change is small.
`MIN_TABS = 2` / `MAX_TABS = 10` are unchanged; the gallery's 2–20 is not adopted.
`GalleryElement` and `gallery.js` are read-only references here.

## Data flow

**Authoring.** The author picks Display and Label position → `tabs_editor.js` re-serialises
the whole editor into the hidden `name="data"` JSON → POST → `TabsElementForm.clean_data`
validates the slide count, threads all three keys into `normalize_labels_and_ids`, which
mints ids for new rows and coerces the two enums → `save()` runs the same normalizer again
(idempotent) and writes `data`.

**Rendering.** `TabsElement.render` → `normalize_data(self.data)` supplies `display` and
`label_pos` (padding/truncating only the tab list, read-side) → `resolved_tabs()` groups the
child `Element` rows by `tab_id` → the template emits every section with both data
attributes → `tabs.js` branches on `data-display`, builds the strip or the carousel nav,
reserves the stage height, and shows slide 1.

**Editor preview.** `editor.js applyFragments()` swaps the pane, then calls the existing
`window.libliInitTabs(preview)`, which re-enhances the carousel from scratch; the
`tabsReady` guard makes the re-run safe and the detached-container guard stops the outgoing
instance's observers.

**Transfer.** Export serialises `{tabs, display, label_pos}`; children are separate elements
carrying `parent` and `tab` refs, unchanged. Import defaults the two keys when absent,
validates them when present, and passes them into the constructed element.

## Error handling

- **Both normalizers are total** — an arbitrary or hostile `data` blob yields a well-formed
  dict, never an exception. A `display` of `null`, `42`, or `"CAROUSEL"` renders as `tabs`.
- **A damaged blob never orphans children.** The non-destructive/destructive split is
  preserved exactly; the new keys ride on the non-destructive normalizer that `save()` uses.
- **Zero resolvable slides** cannot happen — `normalize_data` pads to `MIN_TABS`.
- **No JS, JS error, or unsupported browser** → the stacked, labelled fallback, which is
  fully readable. `ResizeObserver` is feature-detected exactly as the gallery detects it;
  its absence costs re-measurement, not function.
- **Import** rejects an out-of-enum `display`/`label_pos` with a localised message naming the
  element, consistent with the gallery's invalid-position error; it does not repair them.
- **A carousel nested inside a collapsed container** reserves a zero-height stage until
  revealed; the `libli:reveal` listeners are what correct it, and their absence is a visible
  defect rather than a crash.

## Testing

Falsification is the standard: for each test, name the mutation it must catch, apply it, and
require RED. Run tests narrowly — `-k` the mutant's own tests; a whole-repo sweep is a
branch-level gate, not a per-task step.

**Model / normalizer.** Defaults on an empty blob; each enum member round-trips; hostile
values (`None`, int, wrong-case string, a list) coerce to the default without raising;
`normalize_data` carries both keys through its padding and truncation paths. **The critical
one: a `save()` round-trip asserting both keys survive** — set `display="carousel"`, save,
refetch, assert. Mutant: revert `normalize_labels_and_ids` to `return {"tabs": tabs}`; that
test must fail and the others must not silently pass.

**Form.** Both selects round-trip through `clean_data`; an out-of-enum submission coerces to
the default rather than raising; the slide-count `ValidationError`s still fire; `editor_display`
/ `editor_label_pos` reflect submitted data on a bound invalid re-render, not the instance.

**Render.** `data-display` and `data-label-pos` appear with the right values; the label
heading is present in all three `label_pos` settings (the caption is placed and hidden by
CSS class, not by omitting the node — dropping it would strip the title from print);
**the emitted markup is byte-identical between the two modes apart from the two attributes**,
which is what pins the no-JS/print fallback. Beware the known bare-substring trap: an
assertion for a short literal can be satisfied by the page `<head>` — assert within the
element's own markup.

**Transfer.** Round-trip a carousel-mode element through export → validate → import and
compare; import an archive whose tabs payload **lacks** both keys and assert it succeeds with
the defaults; import an out-of-enum value and assert a clean rejection; assert
`FORMAT_VERSION` is 8 and that a v9 archive is still refused.

**e2e (one focused file, run in the foreground).** Build a unit with a carousel-mode tabs
element holding a real table per slide, through the real UI — no fixtures shortcutting the
editor. Click ›, assert slide 2's table is visible and slide 1 is `aria-hidden`; assert prev
is `disabled` on slide 1 and next on the last; assert the stage height does not change
between slides. Sync on conditions, never on sleeps, and use `checkVisibility()` rather than
inferring visibility from styles. Screenshot **light and dark, judged separately** — a dark
screenshot is not verified by a light one passing.

**Manual/visual check.** Print preview of a unit containing a carousel: every slide must
appear, each under its label, with the nav bar absent. This is the regression the two print
rules above exist to prevent and is not covered by any headless assertion.
