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
`NESTABLE_TYPE_KEYS` (`courses/builder.py`) — so "several tables, one visible at a time"
already works today; only the *navigation idiom* is missing. This spec adds a **display
mode** to the tabs element: the same data, the same children, the same editor, rendered
either as today's tab strip or as a gallery-style carousel with prev/next arrows and dots.

### Why not extend the gallery

`GalleryElement` stores `data = {desc_pos, images: [{media: int, desc: str}]}`.
`resolved_images()` does an `in_bulk` over `MediaAsset` and `render()` returns `""` when
nothing resolves; the per-slide `desc` is rich text but passes through `sanitize_cell`,
which does not keep table markup. There is no seam where a child element could enter.
Turning it into a real container would require a data migration converting every stored
`images` list into child `Element` rows on every deployed database, entries in all three
container registries, unwinding the per-type media-list export pass built for it, and a full
editor rewrite — to arrive where tabs already stands. **The gallery is out of scope and must
not be modified by this work.** It is referenced throughout as a *read-only pattern source*:
`gallery.js` and the `.el--gallery` CSS block already solve every hard problem this feature
has, and the carousel should port their solutions rather than reinvent them.

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

`data` gains two scalar keys beside the existing `tabs` list. Each enum is declared **once**,
as an ordered tuple of `(value, lazy_label)` pairs, with the validation set derived from it —
a bare `set` of members plus a separate label mapping would be two declarations of one enum
that can silently disagree (a member with no label renders a blank `<option>`; a label with
no member coerces to the default on save):

```python
DISPLAY_CHOICES = (("tabs", _("Tabs")), ("carousel", _("Carousel")))
DISPLAYS = frozenset(v for v, _l in DISPLAY_CHOICES)
DEFAULT_DISPLAY = "tabs"

LABEL_POS_CHOICES = (("above", _("Above")), ("below", _("Below")), ("hidden", _("Hidden")))
LABEL_POSITIONS = frozenset(v for v, _l in LABEL_POS_CHOICES)
DEFAULT_LABEL_POS = "above"
```

The labels are module/class-level and evaluated at import time, so they **must** use
`gettext_lazy` — plain `gettext` there freezes the first request's locale for the whole
process lifetime.

This is a **conscious departure** from the gallery's naming (`CAPTION_POSITIONS` /
`DEFAULT_POS`, a bare set with no labels): the gallery's positions never needed ordered,
translated option text. The `*_CHOICES` / derived-set shape is what makes the
single-source-of-truth requirement above enforceable.

Both keys are coerced enum-or-default the way `GalleryElement.normalize_data` coerces
`desc_pos` against `CAPTION_POSITIONS` / `DEFAULT_POS`: an unrecognised value normalises to
the default and **never raises**. Neither key is nullable and neither is ever absent after
normalisation.

**No migration.** `data` is a `JSONField`; the normalizers supply the defaults on read, so
every stored tabs element keeps rendering exactly as it does today with no database change
and no backfill. This is the same "new optional key, defaulted on read" shape the gallery's
`desc_pos` and the image element's `size` already use.

`default_data()` gains both keys explicitly, so a freshly added element is self-describing
rather than relying on a later normalisation pass to fill it in.

#### ⚠️ The key-drop trap — the single highest-risk point of this change

**There are THREE sites that rebuild `data` from a fresh dict literal, and all three must
thread the new keys.** Any key absent from one of those literals is silently discarded — no
exception, no log, no failing request:

1. **`TabsElement.normalize_labels_and_ids`** ends with `return {"tabs": tabs}`, and `save()`
   does `self.data = self.normalize_labels_and_ids(self.data)`. Miss this one and the
   setting survives the POST, renders correctly on the response, and vanishes the moment the
   row is written.
2. **`TabsElement.normalize_data`** also ends with `return {"tabs": tabs}` — it calls
   `normalize_labels_and_ids` for its input but then builds its own literal from
   `norm["tabs"]` alone. It inherits **nothing** for free. Since `render()` reads
   `display`/`label_pos` from `normalize_data(self.data)`, missing this one means the render
   context never sees them and every element renders as `tabs` forever.
3. **`TabsElementForm.clean_data`** returns
   `TabsElement.normalize_labels_and_ids({"tabs": tabs})` — a fresh dict that drops whatever
   the author submitted unless the two keys are passed into it.

The existing normalizer split stands unchanged and is load-bearing: `save()` must **never**
call `normalize_data`, because persisting its padding/truncation would permanently orphan a
tab's children.

### Form — `courses/element_forms.py`, `TabsElementForm`

- `clean_data` reads `raw.get("display")` and `raw.get("label_pos")` from the submitted JSON
  and passes both into the normalizer call, so the normalizer remains the one place the enum
  coercion lives.
- **The `tabs is None` early-return branch must thread them too.** That branch returns
  `TabsElement.default_data()` on the documented "add + save with no edit" path and on any
  path where `tabs_editor.js` did not serialise a tab list; as written it would drop a
  submitted `display` with no error — the same silent-drop class as the trap above. It must
  apply the two submitted values (normalised) on top of the defaults, and a form test must
  pin it.
- **An unrecognised value is coerced to the default, not rejected.** These values originate
  in a `<select>`; a value outside the enum means a hand-tampered payload, and matching the
  gallery's total-normalisation behaviour keeps the write path incapable of 500ing. The
  slide-count bounds keep raising `ValidationError` as they do today — that check is about
  *which tabs exist* and is not comparable.
- Two new `cached_property` accessors, `editor_display` and `editor_label_pos`, mirror
  `editor_rows`' existing bound/unbound source selection (`self._raw_data_json()` when
  bound, `self.instance.data` otherwise), so an invalid re-render preserves the author's
  selection instead of snapping back to the default.

### Editor — `_edit_tabs.html`, `tabs_editor.js`, `editor.css`

Two `<select>` controls are added above the label rows. **Neither carries a `name`
attribute**: the partial's documented contract is that the hidden `name="data"` field is the
*sole authoritative input*, and `tabs_editor.js` mirrors every control into it. They are
addressed by `data-tab-display` and `data-tab-label-pos`, matching the existing
`data-tab-row` / `data-tab-label-input` convention.

**The editor and student attribute prefixes deliberately differ** (`data-tab-label-pos` in
the editor, `data-label-pos` on the student root). `tests/test_tabs_partial.py` asserts
`html.count("data-tab-label") == 2` against the **student** markup; naming the student
attribute `data-tab-label-pos` would push that count to 3 and fail with a confusing message.
Harmonising the two prefixes is therefore forbidden, and the reason must be stated in the
template comment so a later tidy-up does not "fix" it. (`tests/test_tabs_editor_partial.py`
counts `data-tab-row == 2`, which neither new editor attribute contains.)

`tabs_editor.js` changes in two places: its serializer emits `display` and `label_pos`
alongside `tabs`, and a `change` listener on either select re-serialises. It also toggles a
`hidden` attribute on the label-position row whenever `display !== "carousel"`, since the
setting has no effect in tabs mode.

The option values and their translated labels come from the model's `*_CHOICES` tuples via
the existing `tabs_bounds` template tag, extended to expose them, so the template never
hardcodes an enum member or a label.

**`editor.css` must be edited in the same task.**
`tests/test_tabs_editor_partial.py::test_editor_css_styles_every_tabs_editor_class` scans
`_edit_tabs.html` for every `tabs-editor__*` class and asserts each appears in `editor.css`;
any styled wrapper for the new rows fails the suite until it is styled — and an unstyled
select row is a visible regression regardless.

### Student template — `templates/courses/elements/tabselement.html`

The root element gains `data-display="{{ display }}"` and `data-label-pos="{{ label_pos }}"`;
`TabsElement.render` adds both to its context, read from `normalize_data(self.data)` (the
same normalized blob `resolved_tabs()` already reads).

**The server-rendered markup is otherwise unchanged in both modes and remains the no-JS and
print fallback** — every section emitted, each panel under its `h3` label, all visible. That
is already the right behaviour for a carousel: without JS a reader sees every slide stacked
and labelled, and that is also exactly what should print. The enhancer may still build DOM
(it already inserts a tab bar today); "unchanged" constrains the *server template*, not the
JS.

### `courses/static/courses/js/tabs.js` — the carousel branch

The carousel lives **inside `tabs.js`, not a new file.** `tabs.js` already exposes idempotent
`window.libliInitTabs(root)` and `editor.js` already re-runs it over the live-preview pane
after every fragment swap — so folding in means the editor preview needs **no new wiring**.
A separate file would need a new `window.libliInit*` export registered in `editor.js` *and*
script tags in three templates; the gallery shipped a visible bug at exactly that seam,
rendering its no-JS stacked fallback in a pane labelled "as students see it" because
`editor.html` never loaded `gallery.js`.

`initOne` reads `container.getAttribute("data-display")` after its existing
`dataset.tabsReady` guard and the `ownSections` lookup, then branches. Shared by both modes,
unchanged:

- The **idempotence guard** — the preview pane re-runs the enhancer over the whole pane on
  every swap; re-entering would append a second nav bar.
- The **nested-instance scoping** (`ownSections` / `ownPart`). Since the depth-3 lift a tabs
  element may legally contain another tabs element, so a descendant-wide lookup from the
  outer container would swallow the inner instance's sections. A carousel may likewise
  contain a tabs element, or a tabs element a carousel; the carousel branch uses the same
  helpers and must never use a bare `querySelectorAll`.
- The `eid` DOM-id namespacing — two carousels on one page must not collide.
- The `.tabs--js` class is added in **both** modes, so the existing `:not(.tabs--js)` spacing
  rule stays correct. Every mode-specific CSS rule is scoped by `[data-display]` instead.

#### The slide mechanism — ported from the gallery, NOT the `hidden` attribute

**The slide unit is the whole `.tabs__section`** (its `h3` caption *and* its panel), so a
caption is shown and hidden with the slide it titles. Hiding only the panel would leave all
2–10 captions stacked above one visible slide.

Inactive slides must stay **laid out**, exactly as `gallery.js` keeps its figures laid out:

- The carousel branch creates a **`.tabs__stage`** (`position: relative`), inserts it before
  the first section, and re-parents every `.tabs__section` into it — the same move
  `gallery.js` makes with `.gallery__stage`. This is the element that receives the measured
  `min-height`; applying it to `.el--tabs` itself would be self-referential and would include
  the nav bar.
- Sections are `position: absolute; top: 0; left: 0; width: 100%; opacity: 0;
  pointer-events: none` with an `opacity` transition, and the active one carries `.is-active`
  (`opacity: 1; pointer-events: auto`) — mirroring `.gallery__item` / `.gallery__item.is-active`.
- At rest every section also gets `aria-hidden="true"` **and `inert`**; the active one has
  both cleared. `inert` is not decoration: without it, focusable content inside an invisible
  slide — a fill-in table's inputs, a link, an armed image-zoom trigger — stays in the tab
  order. `aria-hidden` alone does not remove it.

**The `hidden` attribute must not be used for carousel slides.** It computes to
`display: none`, which would make `offsetHeight` zero for every inactive slide, collapse the
height reservation to the current slide's height (defeating the entire section below), and
make the cross-fade impossible since a `display: none` element cannot transition or overlap
its successor.

#### Carousel-specific behaviour

- **Nav DOM** appended after the stage (the gallery's order: content, then controls), holding
  a prev button, a dot per slide, and a next button, inside a `<nav>` labelled with a
  **carousel-specific** string — reusing the existing `i18n.nav` would announce the landmark
  as "Tabs".
- **Arrows are real, focusable, labelled buttons.** This differs deliberately from the tabs
  chevrons, which are `aria-hidden` with `tabIndex = -1` *because* keyboard users navigate
  that mode via the tablist's arrow keys. Carousel mode has no tablist, so hiding its only
  controls from assistive technology would leave it unoperable.
- **Clamped, never wrapping**: at slide 1 the prev button is `disabled`, at slide N the next
  button is `disabled` — the gallery's boundary behaviour and its `:disabled` styling.
  **Because disabling the focused element blurs it to `<body>`**, when the button that was
  just activated becomes disabled, focus moves to the opposite arrow, so a keyboard user
  keeps their place at both boundaries.
- **`rescueFocus`, ported from `gallery.js`.** Inerting a subtree blurs focus inside it to
  `<body>`, and the arrow-key handler bails when focus is outside the container — so without
  the rescue, keyboard navigation dies after exactly one step. As in the gallery this is
  needed at exactly one site: when focus is inside the outgoing slide, move it into the
  incoming one.
- **Dots are unconditional.** `MAX_TABS` is 10, so the gallery's "more than `DOTS_MAX` dots →
  show a counter instead" branch is dead code here and is not ported.
- **No tab roles.** No `role=tablist`, `role=tab`, or `role=tabpanel` in carousel mode — it
  is not a tab set.
- **A `.tabs__status` region** (`role="status"`, `aria-live="polite"`) announces "Slide {n}
  of {total}" on each change, ported from `.gallery__status`. It **must** use the gallery's
  clip-based sr-only rule — `position:absolute; width:1px; height:1px; overflow:hidden;
  clip:…` — and never `display:none` or `visibility:hidden`, which would remove it from the
  accessibility tree (defeating the announcement) and from Playwright's text queries
  (defeating the e2e assertion).
- **Keyboard**: Left/Right step one slide, Home/End jump to the ends. Two guards, both
  required: ignore the keys when focus is inside an `input`, `select`, `textarea`, or a
  contenteditable (slides can contain form controls), **and assert node ownership** —
  `e.target.closest("[data-tabs]") === container`. Containment alone is not enough: a
  carousel may contain a tabs element or another carousel, and a keypress in the inner
  instance bubbles to an outer container that also `contains` it, advancing both on one
  press. The tabs strip handler calls `preventDefault` but not `stopPropagation`, so the
  outer handler still runs.
- **Cross-fade** of 320 ms, matching the gallery's `FADE_MS` and the CSS transition, and
  reduced to 0 when `prefers-reduced-motion` matches.
- **`libli:reveal`** is dispatched on the newly shown section, exactly as the tabs `select()`
  does. A gallery inside a hidden slide measures zero height and listens for this event to
  re-measure; a carousel that skipped it would show a collapsed letterbox to any reader who
  advanced to a slide containing a gallery.

#### Class naming — required for the style-drift guard to see it

`tests/test_tabs_css.py::test_every_tabs_class_the_js_emits_is_styled` finds classes with
`re.findall(r'className = "([\w-]*tabs__[\w-]+)"', js)`. So every new carousel class **must**
(a) use the `tabs__` prefix and (b) be assigned through a **literal** `className = "…"`
statement. A `carousel__*` name, or a class passed through a helper parameter the way
`chevron(cls, …)` passes its own, is invisible to the guard — vacuous coverage rather than a
failure. Building the carousel's buttons via a helper is fine provided the class is assigned
literally at the element. The concrete names: `tabs__stage`, `tabs__cbar`, `tabs__cprev`,
`tabs__cnext`, `tabs__dots`, `tabs__dot`, `tabs__status`. `tests/test_tabs_partial.py`
hardcodes a required-class list for the **server** markup; since the carousel adds no
server-rendered classes, that list is unchanged.

### Height reservation

Slides have no intrinsic aspect ratio, so without reservation every arrow click reflows the
page. Port the gallery's stable-frame reservation to `.tabs__stage`, simplified to a single
measured set (the sections) since there is no separate caption strip to equalise:

1. **Clear the reservation before measuring**, or the second pass reads the reserve back as
   the natural height and the frame can only ever grow.
2. Reserve `max(section.offsetHeight)` as `.tabs__stage`'s `min-height`. This depends on the
   absolute-positioning mechanism above: laid-out-but-transparent sections report their true
   height, `display:none` ones report zero.
3. Re-measure on `resize` and via a `ResizeObserver` on each section, **rAF-coalesced** — the
   measure mutates the very elements the observer watches, so an uncoalesced version
   re-enters and logs "ResizeObserver loop limit exceeded".
4. **Keep the detached-container guard**: a preview-pane swap detaches the container but
   leaves the `resize` listener and the observer bound. The guard disconnects both when
   `!container.isConnected`.
5. **Keep both `libli:reveal` listeners** — one on the container, one delegated on `document`
   filtered by `e.target.contains(container)` — so a carousel nested inside a collapsed tab,
   spoiler or callout measures correctly the moment its ancestor opens rather than reserving
   a zero-height frame.

KaTeX typesets after first paint and changes section heights; the `ResizeObserver` is what
catches that, which is why it is not optional.

### CSS — `courses/static/courses/css/courses.css`

New carousel styling (stage, sections, nav bar, arrows, dots, status) is additive and
token-driven, following the `.el--gallery` block, which already has directly reusable rules
for every one of those parts. The fade duration in CSS **must** equal the JS constant. Both
light and dark are in scope and are judged separately.

Four existing rules encode tabs-mode assumptions and must each be scoped or paired:

1. **`.el--tabs.tabs--js .tabs__panel-label` is visually hidden.** Correct for tabs, where
   the label became a strip button, but in carousel mode the label *is* the caption. Scope
   the existing rule to `[data-display="tabs"]`, and apply an equivalent **clip-based** rule
   in carousel mode only when `[data-label-pos="hidden"]`.
2. **The print rule keys on `[role="tabpanel"][hidden]`** (`display: block !important`).
   Carousel slides have no tab role and are hidden by absolute positioning + `opacity`, so
   as written the rule cannot match and *printing a carousel would silently lose every slide
   but the current one*. The print block must reset the carousel's mechanism instead — for
   `[data-display="carousel"]`, return `.tabs__stage` to `position: static` with no
   `min-height`, and every `.tabs__section` to `position: static; opacity: 1` — so all slides
   print in order.
3. **`.el--tabs .tabs__bar { display: none !important; }` in print** hides the tab strip.
   `.tabs__cbar` and `.tabs__status` must be added to that rule.
4. **`.el--tabs .tabs__panel { padding-top: var(--space-5) }`** exists to separate a panel
   from the strip above it. In carousel mode it leaves a stray gap above every slide (and
   feeds the height measurement). Scope it to `[data-display="tabs"]` and give carousel mode
   its own caption/panel spacing.

**`label_pos: "below"`** is a **CSS-only reorder**, since the `h3` always precedes the panel
in the DOM and the server markup may not change: in carousel mode `.tabs__section` becomes a
column flex container, and `[data-label-pos="below"]` gives `.tabs__panel-label` an `order`
that places it after the panel. Two consequences, both intended and both to be stated in the
CSS comment: the visual order diverges from the reading order (confined to a heading and the
content it titles, which is acceptable), and **print ignores it** — the print rules reset the
flex ordering, so a printed slide always shows its title above its content.

**`label_pos: "hidden"` is a screen-only setting.** The caption node is always emitted and is
hidden by the clip-based rule, never dropped, and the existing unscoped `!important` print
reset therefore still reveals it. So a printed carousel shows every slide's title even when
the author hid it on screen. That is the deliberate choice — a printed page has no
navigation, and untitled slabs of content would be unreadable — and it is why the render
test asserts the node is present in all three settings.

### i18n

`window.TABS_I18N` gains the carousel strings: the nav landmark label, previous/next slide,
the dot labels, and the `"Slide {n} of {total}"` status string, interpolated with `.replace`
the way the gallery does.

**Each new key needs a per-use-site default.** `tabs.js` opens with
`var i18n = window.TABS_I18N || { nav, prev, next }`, and the fallback object is used **only
when the global is entirely absent**. All three templates already define `TABS_I18N`, so a
template missing the *carousel* keys does not fall back to English — it yields `undefined`,
producing `aria-label="undefined"` and throwing on `.replace`. Read every new key as
`i18n.x || "…"` (or extend the defaults object and merge), never bare.

The `TABS_I18N` literal is duplicated in **three** templates — `lesson_unit.html`,
`quiz_unit.html`, and `manage/editor/editor.html`. A test must read all three and assert
each carries every new key; the repo already has the precedent in
`tests/test_tabs_css.py::test_every_surface_that_renders_the_student_template_loads_tabs_js`,
which loops the same three paths. Polish translations are added for every new string, and
the compiled `.mo` is regenerated before the PR.

### Transfer — `courses/transfer/`

- **`_ser_tabs` (`export.py`)** emits `display` and `label_pos` alongside `tabs`, read from
  the non-destructive normalizer it already calls (which now always supplies them).
- **`_val_tabs` (`payloads.py`)** uses `_exact_keys(data, ["tabs"], …)`, and `_exact_keys`
  both *requires* every listed key and *rejects* every unlisted one. So a pre-change archive
  would fail with "unknown key" the moment export starts emitting them, and a post-change
  archive would fail "missing the key" against the old list. Use the established
  **optional-key pattern**: `data.setdefault("display", "tabs")` and
  `data.setdefault("label_pos", "above")` *before* the `_exact_keys` call, then add both to
  the key list — mirroring the image element's `size` and the iframe's `width`/`height`.
- **An out-of-enum value is REPAIRED to the default, not rejected**, following `_val_image`,
  whose comment states the rule directly: "A cosmetic field with a lossless default must
  never fail an import: `full` IS the pre-feature rendering. (Contrast `_val_callout`, which
  rejects an unknown `kind` — a kind has no safe fallback.)" `display`/`label_pos` are
  exactly that shape — `tabs` **is** the pre-feature rendering — so they follow `size`, not
  `desc_pos` (which has been a required key since day one and has no pre-feature default) and
  not `callout.kind`.
- **`_build_tabs` (`importer.py`)** constructs `TabsElement(data={"tabs": data["tabs"]})`
  from an explicit literal and must pass both new keys through. `setdefault` mutated the
  validated dict in place, so they are guaranteed present by the time this runs.
- **`FORMAT_VERSION` 7 → 8 (`schema.py`).** The importer rejects any archive whose version
  exceeds its own, which is what stops an older libli choking on keys it has never heard of.
  Adding emitted keys without the bump would hand an old instance a same-version archive it
  cannot parse.

  **The bump has four pinned assertions in files this feature otherwise never touches**, and
  they must move in the same task or the branch gate fails long after the narrow per-task run
  passed: `tests/test_link_transfer.py::test_format_version_is_7`,
  `tests/test_tabs_transfer.py::test_format_version_is_7`,
  `tests/test_transfer_schema.py` (`assert FORMAT_VERSION == 7`), and
  `tests/test_transfer_export.py` (`assert manifest["format_version"] == 7`). The three
  `test_format_version_is_7` **function names** are renamed too, plus the stale `7` in a
  comment in `tests/test_table_transfer.py`.

  **Deploy-order note:** after merge, every archive this build exports is unimportable on any
  not-yet-upgraded instance. That is the normal cost of a format bump and is worth stating
  given the pending production cutover — upgrade before transferring.

### Explicitly untouched

`_CONTAINER_REGISTRY`, `CONTAINER_TRANSFER_KEYS`, `payloads._CONTAINER_SLOT_KEY`, the nesting
rules and `MAX_NEST_DEPTH` arithmetic, the element clipboard and paste path, `builder_filter`,
and `_ELEMENT_LABELS` / `element_summary`. `TabsElement` is already a registered container,
so children, depth limits, filtering, pasting and export/import routing all keep working with
no edits — that is the whole reason this change is small. `MIN_TABS = 2` / `MAX_TABS = 10`
are unchanged; the gallery's 2–20 is not adopted. `GalleryElement`, `gallery.js` and the
`.el--gallery` CSS are read-only references.

## Data flow

**Authoring.** The author picks Display and Label position → `tabs_editor.js` re-serialises
the whole editor into the hidden `name="data"` JSON → POST → `TabsElementForm.clean_data`
validates the slide count, threads all three keys into `normalize_labels_and_ids`, which
mints ids for new rows and coerces the two enums → `save()` runs the same normalizer again
(idempotent) and writes `data`.

**Rendering.** `TabsElement.render` → `normalize_data(self.data)` supplies `display` and
`label_pos` (padding/truncating only the tab list, read-side) → `resolved_tabs()` groups the
child `Element` rows by `tab_id` → the template emits every section with both data
attributes → `tabs.js` branches on `data-display`, builds the stage and nav, reserves the
stage height, and shows slide 1.

**Editor preview.** `editor.js applyFragments()` swaps the pane, then calls the existing
`window.libliInitTabs(preview)`, which re-enhances the carousel from scratch; the `tabsReady`
guard makes the re-run safe and the detached-container guard stops the outgoing instance's
observers.

**Transfer.** Export serialises `{tabs, display, label_pos}`; children are separate elements
carrying `parent` and `tab` refs, unchanged. Import defaults the two keys when absent,
repairs them when out of enum, and passes them into the constructed element.

## Error handling

- **Both normalizers are total** — an arbitrary or hostile `data` blob yields a well-formed
  dict, never an exception. A `display` of `null`, `42`, or `"CAROUSEL"` renders as `tabs`.
- **A damaged blob never orphans children.** The non-destructive/destructive split is
  preserved exactly; the new keys ride on both normalizers.
- **Zero resolvable slides** cannot happen — `normalize_data` pads to `MIN_TABS`.
- **No JS, JS error, or unsupported browser** → the stacked, labelled fallback, which is
  fully readable. `ResizeObserver` is feature-detected exactly as the gallery detects it; its
  absence costs re-measurement, not function. `inert` is likewise absent in older engines —
  its loss costs tab-order hygiene on invisible slides, not function, and it is not
  polyfilled.
- **Import never fails on these two keys** — absent → defaulted, out of enum → repaired.
  Malformed *tabs* keep failing exactly as today.
- **A carousel nested inside a collapsed container** reserves a zero-height stage until
  revealed; the `libli:reveal` listeners are what correct it, and their absence is a visible
  defect rather than a crash.

## Testing

Falsification is the standard: for each test, name the mutation it must catch, apply it, and
require RED. Run tests narrowly — `-k` the mutant's own tests; a whole-repo sweep is a
branch-level gate, not a per-task step. **The `FORMAT_VERSION` bump is the documented
exception**: its assertions live in three non-tabs files that a narrow run will not reach, so
that task runs the four transfer test files explicitly.

**Model / normalizer.** Defaults on an empty blob; each enum member round-trips; hostile
values (`None`, int, wrong-case string, a list) coerce to the default without raising;
`normalize_data` carries both keys through its padding and truncation paths; `DISPLAYS`
matches the keys of `DISPLAY_CHOICES` (and likewise for label positions), so the derived-set
invariant cannot silently rot. **The critical one: a `save()` round-trip asserting both keys
survive** — set `display="carousel"`, save, refetch, assert. Mutants, one per site: revert
`normalize_labels_and_ids` to `return {"tabs": tabs}` (the save round-trip must go RED);
revert `normalize_data` likewise (the render and padding tests must go RED). Neither mutant
may leave the whole file green.

**Form.** Both selects round-trip through `clean_data`; a submission with `display` but **no**
`tabs` keeps the display (the early-return branch); an out-of-enum submission coerces to the
default rather than raising; the slide-count `ValidationError`s still fire; `editor_display`
/ `editor_label_pos` reflect submitted data on a bound invalid re-render, not the instance.

**Render.** `data-display` and `data-label-pos` appear with the right values; the caption
node is present in all three `label_pos` settings (it is hidden by CSS, never omitted —
dropping it would strip the title from print); **the emitted markup is byte-identical between
the two modes apart from the two attributes**, which is what pins the no-JS/print fallback;
the existing `data-tab-panel`/`data-tab-label` counts still hold. Beware the known
bare-substring trap: an assertion for a short literal can be satisfied by the page `<head>` —
assert within the element's own markup.

**Templates / CSS invariants.** All three `TABS_I18N` templates carry every new key. The
existing class-drift guard covers each new `tabs__*` class (which requires the literal
`className = "…"` assignment above — a test that passes because the guard found *nothing* is
the failure mode to check for). `editor.css` styles every new `tabs-editor__*` class.

**Transfer.** Round-trip a carousel-mode element through export → validate → import and
compare; import an archive whose tabs payload **lacks** both keys and assert it succeeds with
the defaults; import an **out-of-enum** value and assert it is repaired to the default rather
than raising; assert `FORMAT_VERSION` is 8 and that a v9 archive is still refused.

**e2e — appended to the existing `tests/test_e2e_tabs.py`** (a new file would change what a
narrow `-k` run covers), run in the foreground. Build a unit with a carousel-mode tabs
element through the real UI — no fixtures shortcutting the editor — with **slides of
deliberately different natural heights** (e.g. a 3-row table and a 10-row table), because a
height assertion against similar slides passes trivially on a broken build. Then:

- click ›, assert slide 2's table is visible (`checkVisibility()`, not inferred from styles)
  and slide 1 is `aria-hidden`;
- assert `.tabs__stage`'s measured height is **unchanged** between slide 1 and slide 2 — the
  named node, not an ancestor that stretches to its content;
- assert prev is `disabled` on slide 1 and next on the last;
- assert `.tabs__status` reads "Slide 2 of N";
- assert an input inside an inactive slide is not reachable by tabbing (the `inert` guard).

Sync on conditions, never on sleeps. Screenshot **light and dark, judged separately** — a
dark screenshot is not verified by a light one passing.

**Manual/visual check.** Print preview of a unit containing a carousel: every slide must
appear, each under its label, in order, with the nav bar and status region absent. This is
the regression the print rules above exist to prevent and is not covered by any headless
assertion.
