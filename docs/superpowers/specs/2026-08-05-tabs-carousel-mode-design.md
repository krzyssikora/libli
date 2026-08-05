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
has, and the carousel should port their solutions rather than reinvent them — **except where
this spec says otherwise**, because a gallery slide is always a `<figure><img>` while a
carousel slide is arbitrary content, and several of the gallery's shortcuts do not survive
that generalisation.

### What the student sees

| | `display: tabs` (today, default) | `display: carousel` (new) |
|---|---|---|
| Navigation | `role=tablist` strip of labelled buttons | ‹ › arrows + one dot per slide |
| Access | Random — click any label | Arrows step sequentially and clamp at both ends (no wrap); a dot jumps directly |
| Label | *Is* the button | A caption above/below the slide, or hidden |
| Width | The strip must fit the 648px content column | Fixed-size nav bar regardless of slide count |

### Author-facing copy

- The tabs editor gains a **Display** select: EN "Tabs" / "Carousel", PL "Zakładki" /
  "Karuzela".
- And a **Label position** select, meaningful only in carousel mode: EN "Above" / "Below" /
  "Hidden", PL "Nad" / "Pod" / "Ukryta".
- The palette card stays **Tabs** — this is a setting on the existing element, not a new
  one. Discoverability was weighed against a separate picker entry and deliberately traded
  away for the smaller change. To offset it, `element_summary` gains the mode (below), so
  the builder tree distinguishes the two without opening the editor.

## Architecture / components

### Data model — `courses/models.py`, `TabsElement`

`data` gains two scalar keys beside the existing `tabs` list. Each enum is declared **once**,
as an ordered tuple of `(value, lazy_label)` pairs, with the validation collection derived
from it — a bare set of members plus a separate label mapping would be two declarations of
one enum that can silently disagree (a member with no label renders a blank `<option>`; a
label with no member coerces to the default on save).

The constants are **class attributes on `TabsElement`**, beside `MIN_TABS` / `MAX_TABS` /
`LABEL_MAX`, matching how this model already publishes its bounds. All three consumers
(`element_forms.TabsElementForm`, `courses_manage_extras.tabs_bounds`,
`transfer.payloads._val_tabs`) reference them as `TabsElement.<NAME>`:

```python
DISPLAY_CHOICES = (
    ("tabs", pgettext_lazy("tabs display", "Tabs")),
    ("carousel", pgettext_lazy("tabs display", "Carousel")),
)
DISPLAYS = tuple(v for v, _l in DISPLAY_CHOICES)
DEFAULT_DISPLAY = "tabs"

LABEL_POS_CHOICES = (
    ("above", pgettext_lazy("tabs label position", "Above")),
    ("below", pgettext_lazy("tabs label position", "Below")),
    ("hidden", pgettext_lazy("tabs label position", "Hidden")),
)
LABEL_POSITIONS = tuple(v for v, _l in LABEL_POS_CHOICES)
DEFAULT_LABEL_POS = "above"
```

⚠️ **The derived collections are `tuple`, deliberately not `frozenset`.** `[] in
frozenset(...)` raises `TypeError: unhashable type` — so with a set, a `data` blob of
`{"display": []}` makes the "total, never raises" normalizer raise, and `_val_tabs` 500s on
a hostile archive in the one module whose entire job is untrusted input. `in` against a
tuple uses `==` and never hashes. This is exactly why the precedent this spec follows,
`_val_image`, is safe: `ImageElement.Size.values` is a **list**. Belt and braces: every
membership test is additionally guarded by `isinstance(value, str)`.

The labels are evaluated at import time and **must** be lazy — plain `gettext` there freezes
the first request's locale for the whole process lifetime. Use **`pgettext_lazy` with a
context** (`"tabs display"`, `"tabs label position"`) rather than bare `gettext_lazy`: all
five are one-word adjectives whose Polish forms are gendered ("Ukryta" agrees with
*etykieta*) and would be wrong the moment the same msgid is reused for a masculine noun
elsewhere. `courses/models.py` already carries this exact precedent and its reasoning for
`pgettext_lazy("image size", "Full")`.

This is a **conscious departure** from the gallery's naming (`CAPTION_POSITIONS` /
`DEFAULT_POS`, a bare set with no labels): the gallery's positions never needed ordered,
translated option text. The `*_CHOICES` / derived-collection shape is what makes the
single-source-of-truth requirement enforceable.

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
   `display`/`label_pos` from the normalized blob, missing this one means the render context
   never sees them and every element renders as `tabs` forever.
3. **`TabsElementForm.clean_data`** returns
   `TabsElement.normalize_labels_and_ids({"tabs": tabs})` — a fresh dict that drops whatever
   the author submitted unless the two keys are passed into it.

The existing normalizer split stands unchanged and is load-bearing: `save()` must **never**
call `normalize_data`, because persisting its padding/truncation would permanently orphan a
tab's children.

**`render()` must NOT reach for the destructive normalizer to get the enums.** It already
passes `self.resolved_tabs()`, and `resolved_tabs()` opens with
`self.normalize_data(self.data)["tabs"]` — so an added `self.normalized_data` read would be a
**second** `normalize_data` call in one response, re-running id minting and padding on a
damaged blob and producing two different tab lists (the hazard `builder.py` warns about for
random ids). It is also unsatisfiable as a shortcut: the template iterates `(tab, children)`
pairs, which the normalized dict does not contain.

Add a small dedicated accessor instead — `display_settings()` — that coerces **only** the two
enums from `self.data`, with no tab-list work at all, and is called once by `render()`. It
touches nothing `resolved_tabs()` touches, so the two cannot disagree and no normalisation
runs twice. A test should assert `render()` triggers exactly one `normalize_data` call.

⚠️ **The coercion itself lives in ONE place.** `normalize_labels_and_ids`,
`display_settings()`, and the `editor_display` / `editor_label_pos` accessors all need the
same `isinstance` + tuple-membership + default logic, and three hand-copied versions are the
identical two-declarations-can-disagree failure this spec rejects for the enum members
themselves — a drift here surfaces as "the builder tree says carousel but the page renders
tabs". Write one private `_coerce_enum(value, allowed, default)` staticmethod and call it
from all of them, and test that `display_settings()` and `normalize_labels_and_ids()` agree
across the whole hostile-value matrix (`None`, `42`, `"CAROUSEL"`, `[]`, `{}`).

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

Two `<select>` controls are added above the label rows, each **wrapped in a visible
`<label>`** carrying the "Display" / "Label position" copy — `<label>Display <select …>…`,
which is precisely the shape `_edit_gallery.html` uses for its own position select. Wrapping,
not `for="…"`: a `for=` reference needs stable collision-free ids in a partial that is
injected by fragment swap, and the wrapping form needs none. A visible label (rather than the
`aria-label` the sibling label-inputs carry) is what makes a new setting discoverable in a
form whose other controls are self-evident.

**Neither select carries a `name` attribute**: the partial's documented contract is that the
hidden `name="data"` field is the *sole authoritative input*, and `tabs_editor.js` mirrors
every control into it. They are addressed by `data-tab-display` and `data-tab-label-pos`,
matching the existing `data-tab-row` / `data-tab-label-input` convention.

**The editor and student attribute prefixes deliberately differ** (`data-tab-label-pos` in
the editor, `data-label-pos` on the student root). `tests/test_tabs_partial.py` asserts
`html.count("data-tab-label") == 2` against the **student** markup; naming the student
attribute `data-tab-label-pos` would push that count to 3 and fail with a confusing message.
Harmonising the two prefixes is therefore forbidden, and the reason must be stated in the
template comment so a later tidy-up does not "fix" it. (`tests/test_tabs_editor_partial.py`
counts `data-tab-row == 2`, which neither new editor attribute contains.)

**Round-tripping a saved carousel is a required behaviour, not an implementation detail.**
`tabs_editor.js` serialises on init only when `hidden.value === ""` — which is exactly the
unbound *edit* path — and its `serialize()` currently emits `{tabs: tabs}` alone. So:

- the template renders `selected` on the stored option, from `form.editor_display` /
  `form.editor_label_pos`;
- `serialize()` reads the two **select elements' live values** (never a JS-side constant or
  a captured initial value) and emits all three keys;
- a `change` listener on either select re-serialises;
- it also toggles a `hidden` attribute on the label-position row whenever
  `display !== "carousel"`, since the setting has no effect in tabs mode.

  **The initial state is SERVER-rendered, and the JS call is the idempotent re-assertion.**
  `_edit_tabs.html` emits the label-position row with `hidden` when
  `form.editor_display != "carousel"`; `wire()` then calls the same toggle once at the end of
  init to cover the bound/JS-mutated case. Both halves are required and neither is redundant:
  a JS-only toggle means the server markup never carries `hidden`, so the partial-level test
  asserted below has nothing to assert and the row visibly flashes until `wire()` runs; a
  server-only render means the row never updates when the author changes Display. A test
  asserts the served tabs-mode form renders the row `hidden`.

Without the first two, opening a saved carousel and pressing Save without touching anything
silently reverts it to tabs — the same class of bug the `editor_rows` / `data-tab-id`
machinery exists to prevent for labels.

⚠️ **A Django form test cannot catch this one.** The defect lives in
`tabs_editor.js::serialize()`; a form test builds the POST body by hand and therefore always
includes `display`, so it passes green on a build where a real browser drops the key — the
same server-green/browser-broken shape as the `form.action` shadowing bug already recorded
for this element family. The no-op re-save must be guarded **at a layer that can see it**: an
e2e step that opens a saved carousel in the real editor, saves without touching a control,
and asserts the stored `display` is still `carousel` — plus, cheaply, a source assertion that
`serialize()` reads both select elements. The form-level test stays, but it is not the
guard.

The option values and their translated labels come from `TabsElement.DISPLAY_CHOICES` /
`LABEL_POS_CHOICES` via the existing `tabs_bounds` template tag, extended to expose them, so
the template never hardcodes an enum member or a label.

**`editor.css` must be edited in the same task**, and the hidden row needs an explicit rule:

- `tests/test_tabs_editor_partial.py::test_editor_css_styles_every_tabs_editor_class` scans
  `_edit_tabs.html` for every `tabs-editor__*` class and asserts each appears in
  `editor.css`; any styled wrapper for the new rows fails the suite until it is styled — and
  an unstyled select row is a visible regression regardless.
- ⚠️ A label+select row will naturally be `display: flex`, **which beats the UA
  `[hidden] { display: none }` rule regardless of specificity**, so the row would stay
  visible in tabs mode. Pair every layout rule with an explicit
  `.tabs-editor__<row>[hidden] { display: none; }`, exactly as `editor.css` already does for
  `.view-toggle[hidden]` — where the comment records this as a bug that shipped once before.

### Student template — `templates/courses/elements/tabselement.html`

The root element gains `data-display="{{ display }}"` and `data-label-pos="{{ label_pos }}"`.
`TabsElement.render` gets both from **`display_settings()`** — never from `normalized_data`,
for the reason given under the key-drop trap — and gets the `(tab, children)` pairs from
`resolved_tabs()` as it does today. Those are the only two reads.

**The sections are wrapped in a server-rendered `<div class="tabs__stage">`, in BOTH modes.**
This is a change to the shared markup, applied identically to tabs and carousel, so the
"byte-identical between modes apart from the two attributes" invariant still holds. It is
deliberate and it replaces the obvious alternative of having the JS create the stage and
re-parent the sections into it:

- **Moving a DOM node reloads any `<iframe>` inside it.** A gallery slide is always
  `<figure><img>`, but a carousel slide may hold a video or GeoGebra embed
  (`NESTABLE_TYPE_KEYS` makes this reachable), and the editor preview re-enhances from
  scratch after every fragment swap — so an author editing such a unit would pay a full
  embed reload on **every save, add, reorder or "try it" swap**. (`applyFragments` runs only
  from POST responses; there is no keystroke-driven swap. Frequent enough to decide this,
  not continuous.)
- A server-rendered wrapper is inert without JS (an unstyled `div`), keeps the no-JS and
  print fallback exactly as readable, gives the print rules a real element to target, and
  makes the enhancer simpler.

Existing selectors survive the wrapper: `.el--tabs .tabs__section` and friends are descendant
selectors, the `:not(.tabs--js) .tabs__section + .tabs__section` adjacency still holds inside
the wrapper, `ownSections()` is descendant-wide, and the tab bar is still inserted as the
container's first child.

Everything else about the markup is unchanged in both modes — every section emitted, each
panel under its `h3` label, all visible — and that remains the no-JS and print fallback.

**The template's header comment must be rewritten, not just extended.** It currently asserts
that "tabs.js upgrades it in place to a role=tablist and hides the inactive panels with the
`hidden` ATTRIBUTE" — false for half this element's configurations after this change, and
exactly the comment a future implementer would trust when deciding whether `hidden` is safe
to reuse. It must describe both branches and record why `.tabs__stage` is server-rendered
even in tabs mode (the iframe-reparent reason), alongside the `data-tab-label-pos` /
`data-label-pos` prefix note.

### `courses/static/courses/js/tabs.js` — the carousel branch

The carousel lives **inside `tabs.js`, not a new file.** `tabs.js` already exposes idempotent
`window.libliInitTabs(root)` and `editor.js` already re-runs it over the live-preview pane
after every fragment swap — so folding in means the editor preview needs **no new wiring**.
A separate file would need a new `window.libliInit*` export registered in `editor.js` *and*
script tags in three templates; the gallery shipped a visible bug at exactly that seam,
rendering its no-JS stacked fallback in a pane labelled "as students see it" because
`editor.html` never loaded `gallery.js`.

`initOne` reads `container.getAttribute("data-display")` after its existing
`dataset.tabsReady` guard and the `ownSections` lookup, then branches. **The carousel branch
is taken only on an exact `"carousel"` match**; every other value — `null`, `""`, a stale
cached fragment, a hand-written template, a future third mode — falls through to today's tab
strip. There is no undefined third path. Shared by both modes, unchanged:

- The **idempotence guard** — the preview pane re-runs the enhancer over the whole pane on
  every swap; re-entering would append a second nav bar.
- The **nested-instance scoping** (`ownSections` / `ownPart`). Since the depth-3 lift a tabs
  element may legally contain another tabs element, so a descendant-wide lookup from the
  outer container would swallow the inner instance's sections. A carousel may likewise
  contain a tabs element, or a tabs element a carousel; the carousel branch uses the same
  helpers and must never use a bare `querySelectorAll`.
- The `eid` DOM-id namespacing — two carousels on one page must not collide.
- The `.tabs--js` class is added in **both** modes.

#### The slide mechanism — ported from the gallery, NOT the `hidden` attribute

**The slide unit is the whole `.tabs__section`** (its `h3` caption *and* its panel), so a
caption is shown and hidden with the slide it titles. Hiding only the panel would leave all
2–10 captions stacked above one visible slide.

Inactive slides must stay **laid out**, exactly as `gallery.js` keeps its figures laid out:

- `.tabs__stage` (server-rendered, see above) is `position: relative` once enhanced and is
  the element that receives the measured `min-height`. Applying it to `.el--tabs` itself
  would be self-referential and would include the nav bar.
- Sections are `position: absolute; top: 0; left: 0; width: 100%; opacity: 0;
  pointer-events: none` with an `opacity` transition, and the active one carries `.is-active`
  (`opacity: 1; pointer-events: auto`) — mirroring `.gallery__item` /
  `.gallery__item.is-active`.
- At rest every section also gets `aria-hidden="true"` **and `inert`**; the active one has
  both cleared. `inert` is not decoration: without it, focusable content inside an invisible
  slide — a fill-in table's inputs, a link, an armed image-zoom trigger — stays in the tab
  order. `aria-hidden` alone does not remove it.

**The `hidden` attribute must not be used for carousel slides.** It computes to
`display: none`, which would make `offsetHeight` zero for every inactive slide, collapse the
height reservation to the current slide's height (defeating the entire section below), and
make the cross-fade impossible since a `display: none` element cannot transition or overlap
its successor.

⚠️ **Every carousel rule that hides, positions, reorders or clips MUST use an explicit child
chain, never a descendant selector.** The server markup guarantees
`.el--tabs > .tabs__stage > .tabs__section > .tabs__panel-label`, so write:

```
.el--tabs.tabs--js[data-display="carousel"] > .tabs__stage { … }
.el--tabs.tabs--js[data-display="carousel"] > .tabs__stage > .tabs__section { … }
.el--tabs.tabs--js[data-display="carousel"][data-label-pos="hidden"] > .tabs__stage > .tabs__section > .tabs__panel-label { … }
```

`tabs` is in `NESTABLE_TYPE_KEYS` and a carousel may contain a tabs element — a shape this
repo already exercises in `tests/test_e2e_depth3.py`. A **descendant** selector would match
the *inner* element's `.tabs__section` nodes, absolutely-position them at `opacity: 0`, and
render the inner element **completely blank**: the inner instance is in tabs mode, so it
hides panels with the `hidden` attribute and never adds `.is-active` to a section, meaning
nothing ever restores opacity. The `below` flex rule would likewise reorder an inner
element's captions and the `hidden` clip rule would hide an inner carousel's. This is the
exact hazard `ownSections`/`ownPart` solve in the JS, reintroduced through CSS — and the
note that "existing selectors survive the wrapper because they are descendant selectors"
applies to the *pre-existing* rules, not to the new ones. **The print resets need the same
child chain.** A nested tabs element and a nested carousel inside a carousel slide must both
be render-tested and e2e-tested as visible and operable.

⚠️ **The gate class is `.tabs--carousel`, added as the LAST step of a successful carousel
init — not `.tabs--js`.** In the real `tabs.js`, `classList.add("tabs--js")` runs immediately
after the `ownSections` length check, i.e. **before** the branch point. So gating on
`.tabs--js` would mean that any throw or early bail inside the carousel branch leaves every
section absolutely positioned at `opacity: 0` with nothing ever adding `.is-active` — the
element renders **completely blank**, not as the stacked fallback. That is not hypothetical:
this spec's own i18n section describes a template missing a carousel key yielding `undefined`
and throwing on `.replace`. `.tabs--js` protects the *no-JS* case only; it cannot protect the
*JS-errored* case, because by then it is already applied.

So: `initOne` keeps adding `.tabs--js` where it does today, and the carousel branch adds
`.tabs--carousel` only after `show(0)` has completed successfully. Every carousel screen rule
keys on `.tabs--carousel` (plus `[data-display="carousel"]` for clarity), and the print resets
use the same gate so the `!important` argument below still holds. A half-initialised carousel
then falls back to stacked-and-labelled, which is exactly what the Error-handling section
promises — and it can now honestly promise it.

⚠️ **Every carousel screen rule is also gated on that class AND `[data-display="carousel"]`**,
mirroring `.el--gallery.gallery--js .gallery__item`. `data-display` is emitted by the
*server*, so it is present with JS disabled — a rule keyed on the attribute alone would
absolutely-position every section with no enhanced stage to contain them, collapsing all
slides onto one another at `opacity: 0` and rendering the element blank. `data-display`
distinguishes the two *enhanced* modes; it does not replace the JS gate.

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
  just activated becomes disabled, focus moves to the opposite arrow. Two things this
  requires: the "was this arrow focused" test is captured **before** the `disabled`
  assignment (afterwards the information is gone), and the transfer applies **only when
  focus was on the nav bar** — i.e. exactly when `rescueFocus` returns early. That makes the
  two focus mechanisms mutually exclusive by construction; without the restriction both fire
  on one activation and the reader sees a visible focus jump.

- **`show()` order of operations is normative, not incidental.** `rescueFocus` is a no-op in
  any other sequence, so the steps are:

  1. clear `inert` and `aria-hidden` on the **incoming** section;
  2. call `rescueFocus(outgoing, incoming)`;
  3. set `inert` and `aria-hidden` on the **outgoing** section;
  4. start the fade / settle timer.

  The guard is `if (!out.contains(document.activeElement)) return;`, so inerting the outgoing
  section first (the natural reading of "at rest every section is inert") pushes focus to
  `<body>` before the rescue runs, the guard returns early, and keyboard navigation dies
  after exactly one step **with the rescue code present and correct**. Focusing into the
  incoming section before its `inert` is cleared is likewise a silent no-op. Because the
  broken build survives one keypress, the e2e must press ArrowRight **twice**.

- **`rescueFocus`, with an explicit and *validated* target chain.** Inerting a subtree blurs
  focus inside it to `<body>`, and the container-scoped keydown handler bails when focus is
  outside the container — so without the rescue, keyboard navigation dies. The gallery's
  target selection is image-specific (`.imgzoom-trigger`) and does **not** generalise: the
  headline use case, a slide holding one table, has no focusable node at all. Required
  chain, in order: **a focusable descendant of the incoming section that can actually take
  focus** → else the first enabled control in the nav bar → else the container itself, made
  focusable with `tabindex="-1"`.

  ⚠️ The first link needs a real definition, or it is worse than useless. A naive
  `section.querySelector("a[href],button,input,select,textarea,[tabindex]")` returns nodes
  that **cannot** receive focus: a nested carousel inside the incoming slide has its inactive
  `inert` sections first in DOM order (its nav bar is appended last), and a nested tabs
  element has `display:none` panels. `.focus()` on such a node silently does nothing, focus
  stays on `<body>`, and the keydown handler bails — the precise failure the chain exists to
  prevent, now reached *through* the fallback. So: exclude `[disabled]` and
  `[tabindex="-1"]`, reject any candidate with an `[inert]` ancestor, and require it to pass
  an `offsetParent` / opacity-aware visibility test before accepting it.

  ⚠️ **A fourth filter is mandatory: reject any candidate whose
  `closest("[data-tabs], [data-gallery]")` is not this container.** Otherwise the rescue and
  keyboard guard 3 fight each other, and the guard wins. Reachable path: slide 1 holds a
  link, slide 2 holds a nested tabs element. Focus the link → ArrowRight passes every guard →
  `rescueFocus` picks the incoming slide's first focusable, which may be the *nested*
  element's active panel (`tabIndex = 0`, visible, not `[inert]`, not `[tabindex="-1"]` — it
  passes every other filter listed). The next ArrowRight then resolves
  `closest("[data-tabs]")` to the inner container, so the outer carousel bails, and the inner
  element's own handler is bound to its strip rather than its panel — nothing happens at all.
  That is the "dies after exactly one step" failure, reached *through* the fallback that
  exists to prevent it.

  **The nav-bar fallback is the expected outcome for a plain table slide, not an edge case.**
  "Incoming slide holds a nested tabs element, ArrowRight twice" is an explicit e2e case,
  alongside a nested carousel.
- **Dots are unconditional, and they are activatable controls** — real `<button>`s with an
  `aria-label` and a `click → show(k)` handler, exactly as `gallery.js` builds them. So the
  *arrows* are the sequential, clamped affordance and the *dots* give direct access; a reader
  is never forced to walk. (`MAX_TABS` is 10, so the gallery's "more than `DOTS_MAX` dots →
  show a counter instead" branch is dead code here and is not ported.) On every position
  change the active dot gets **both** `.is-active` **and `aria-current="true"`**, cleared
  from all others — `gallery.js::updateIndicator` does both, and dropping the ARIA half
  leaves a screen-reader user with ten identically-announced buttons and no idea which slide
  they are on while the visual dot fills correctly; assert it in the e2e beside
  `.tabs__status`. Being real buttons is
  also what makes `rescueFocus`'s nav-bar fallback below viable, and what the i18n dot-label
  string is for.
- **No tab roles, and an explicit list of what the shared per-section loop does instead.**
  The tabs branch performs five mutations per section: eid-namespaced `panel.id`,
  `role="tabpanel"`, `aria-labelledby`, `panel.tabIndex = 0`, and cloning the label into a
  strip button. The carousel branch performs exactly **one**: `aria-labelledby`
  **on the section**, pointing at the `h3`'s server-rendered `tabs-{eid}-{tid}-label` id, so
  each slide is named to assistive technology even when `label_pos` is `hidden` (the
  clip-based rule keeps the heading in the accessibility tree). It needs **no id work at
  all** — the template already emits both `tabs-{eid}-{tid}-panel` and the `-label` id, and
  the tabs branch's `panel.id = panelId` merely re-assigns the identical string, so
  requiring it here would be asking for code that does nothing. It sets **no** `role`,
  **no** `tabIndex` on panels — a tab stop per panel would fight the `inert` tab-order
  assertion — and builds no strip button.
- **A `.tabs__status` region** (`role="status"`, `aria-live="polite"`) announces "Slide {n}
  of {total}" on each change, ported from `.gallery__status`. It **must** use the gallery's
  clip-based sr-only rule — `position:absolute; width:1px; height:1px; overflow:hidden;
  clip:…` — and never `display:none` or `visibility:hidden`, which would remove it from the
  accessibility tree (defeating the announcement) and from Playwright's text queries
  (defeating the e2e assertion). **It is appended inside the `<nav>`**, as `gallery.js` does
  — so the print rule hiding `.tabs__cbar` already hides it, and it sits inside the subtree
  `rescueFocus`'s nav-bar fallback scans (harmlessly: a `<span>` is not a button). The print
  rule still names both selectors defensively.
- **Keyboard**: Left/Right step one slide, Home/End jump to the ends. Three guards, all
  required, and **all four keys pass through all three** — Home/End inside a text input is
  ordinary caret movement and swallowing it on a slide holding a fill-in table would be a
  visible regression. `preventDefault` is called only after every guard has passed:
  1. Ignore the keys when focus is inside an `input`, `select`, `textarea`, or a
     contenteditable — slides can contain form controls.
  2. **Ignore them inside a box that is *actually* horizontally scrollable.** `.el--table__scroll`
     and `.el--filltable__scroll` are `overflow-x: auto`, Chrome makes such boxes keyboard
     focusable, and Left/Right there must scroll a wide table — the primary payload of this
     feature, so stealing its arrow keys would be self-inflicted. Tabs mode is unaffected
     today only because its handler is bound to the strip, not the container.

     ⚠️ **Pin the predicate as a measurement, not a class list.** Walk ancestors from
     `e.target` up to `container` and bail on the first element whose computed `overflow-x`
     is `auto`/`scroll` **and** whose `scrollWidth > clientWidth`. A class-only check
     (`closest(".el--table__scroll, .el--filltable__scroll")`) fires for any descendant of a
     table wrapper — including a focused link inside a table **narrow enough not to
     overflow**, where there is nothing to scroll and the arrow key would simply do nothing
     at all. Negative e2e case: a *narrow* table in a slide, focus inside it, ArrowRight must
     still advance.
  3. **Assert node ownership** — `e.target.closest("[data-tabs], [data-gallery]") ===
     container` — **and** bail when `e.defaultPrevented` is already true. Containment alone is
     not enough: a keypress in a nested instance bubbles to an outer container that also
     `contains` it, advancing both on one press, because neither the tabs strip handler nor
     `gallery.js` calls `stopPropagation` after `preventDefault`. **`[data-gallery]` is not
     optional**: a gallery is nestable inside a tab (`tests/test_tabs_transfer.py`'s nested
     fixture builds exactly that, and the add-menu test asserts `data-add-type="gallery"` is
     offered), and `gallery.js` binds its own ArrowLeft/ArrowRight handler on its container —
     so a `[data-tabs]`-only `closest()` walks straight past the gallery and one press
     advances the inner gallery *and* the outer carousel. The `defaultPrevented` check is the
     belt to that braces, and covers any future nested arrow-key consumer. A gallery inside a
     carousel slide must be an explicit test case.
- **Cross-fade** of 320 ms, matching the gallery's `FADE_MS` and the CSS transition, and
  reduced to 0 when `prefers-reduced-motion` matches — **in the JS *and* the CSS** (see the
  CSS list).
- **Overlapping fades need the gallery's `pending` / `finalizePending()` discipline,
  verbatim.** `gallery.js` keeps `pending = {out, inn, timer}` and finalises it at the top of
  every `show()`. Without that, a second activation 100 ms into a 320 ms fade leaves the
  first `setTimeout` alive; when it fires it runs `settleHidden(out)` and clears
  `inn.style.opacity` on slides that are no longer the ones transitioning — leaving a slide
  stuck at `opacity: 0` while carrying `.is-active`, or two slides visible at once. With ten
  dots and two arrows in a 648px column, fast successive activation is the normal
  interaction, not an edge case. e2e: click › twice inside the fade window and assert exactly
  one slide ends up `.is-active` and opaque.
- **`libli:reveal`** is dispatched on the newly shown section — as
  `new CustomEvent("libli:reveal", { bubbles: true })`, and **the `bubbles` flag is
  load-bearing, not boilerplate**. A nested gallery's own container listener cannot see an
  event dispatched on an ancestor section; only the `document`-delegated listener rescues it,
  and that requires the event to reach `document`. Same for a carousel nested in another
  carousel's slide. Falsification: drop `bubbles`, and the "nested gallery/carousel
  re-measures on reveal" assertion must go RED. Beyond that the dispatch stands on parity
  with the tabs `select()` and on any consumer that defers work while `inert` /
  `aria-hidden`.

  ⚠️ Do **not** justify this with "a gallery inside a hidden slide measures zero height" —
  under this spec's own slide mechanism that is false. Absolute + `opacity: 0` keeps inactive
  slides laid out (which is the whole argument against the `hidden` attribute), so a nested
  gallery measures its true height at init and the collapsed letterbox cannot occur. The
  requirement stands on parity; a falsification test written against the false rationale
  could not go RED even with the dispatch deleted.

#### Class naming — required for the style-drift guard to see it

`tests/test_tabs_css.py::test_every_tabs_class_the_js_emits_is_styled` finds classes with
`re.findall(r'className = "([\w-]*tabs__[\w-]+)"', js)`. So every new carousel class **must**:

- **(a)** use the `tabs__` prefix — a `carousel__*` name is invisible to the guard;
- **(b)** be assigned through a **literal** `className = "…"` statement — a class passed
  through a helper parameter, the way `chevron(cls, …)` passes its own, is invisible;
- **(c)** put exactly **one** class token in each such literal. A space is not in `[\w-]`, so
  `className = "tabs__cbtn tabs__cprev"` matches **nothing at all** — the natural
  base-plus-modifier shape silently disables the guard for both classes.

So: **one literal, one token, one element** — and **no shared base class at all**. Do not
reach for `el.className = "tabs__cprev"; el.classList.add("tabs__cbtn")` either: a class
added via `classList.add` is equally invisible to the regex, so the base class would ship
unstyled undetected. Give the two arrow buttons their shared look through a grouped selector
in CSS (`.tabs__cprev, .tabs__cnext { … }`), exactly as `.el--gallery` does for
`.gallery__prev, .gallery__next`.

All three failures are silent: `assert emitted` still passes because other single-token
classes keep the set non-empty. The six JS-built names, and no seventh: `tabs__cbar`,
`tabs__cprev`, `tabs__cnext`, `tabs__dots`, `tabs__dot`, `tabs__status`.

**`tabs__stage` is deliberately NOT in that list** — it is server-rendered (see the Student
template section), so it is never assigned in `tabs.js` and the JS-emitted guard can never
see it. Adding a dead `className` statement purely to satisfy the regex is forbidden; the
stage is covered by the partial render test plus the `courses.css` required-class list
instead.

`tests/test_tabs_partial.py::test_courses_css_defines_the_tabs_element` hardcodes a
required-class list checked against **`courses.css`** (not against markup). Adding the new
carousel classes to it is optional, since `test_tabs_css.py`'s drift guard already covers
them; `.tabs__stage` is now server-rendered and styled, so it may be added there for clarity.

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
   filtered by `e.target.contains(container)` — so a carousel revealed by a reveal-gate
   cascade, or sitting in an outer tab panel that has just been selected, measures correctly
   instead of keeping a zero-height stage. Those are the **only two dispatchers** in the
   codebase (`reveal.js` and `tabs.js::select()`); a spoiler is a native `<details>` that
   dispatches nothing and a callout is not collapsible at all, so for a carousel inside a
   spoiler the `ResizeObserver` is what rescues the measurement when the subtree stops being
   skipped.

KaTeX typesets after first paint and changes section heights; the `ResizeObserver` is what
catches that, which is why it is not optional.

### CSS — `courses/static/courses/css/courses.css`

New carousel styling is additive and token-driven, following the `.el--gallery` block, which
already has directly reusable rules for every part: stage, sections (absolute + opacity +
`.is-active`), nav bar, arrows with `:disabled`, dots with `.is-active`, and the clip-based
status region. **Plus the reduced-motion pair**: zeroing only the JS settle timer leaves the
CSS `transition: opacity 320ms` running, so a reduced-motion user still sees a fade under an
already-inert slide — `@media (prefers-reduced-motion: reduce) { … .tabs__section {
transition: none; } }`, as the gallery does. The fade duration in CSS **must** equal the JS
constant. Both light and dark are in scope and are judged separately.

Four existing rules encode tabs-mode assumptions and must each be scoped or paired:

1. **`.el--tabs.tabs--js .tabs__panel-label` is visually hidden.** Correct for tabs, where
   the label became a strip button, but in carousel mode the label *is* the caption. Scope
   the existing rule to tabs mode, and add an equivalent **clip-based** rule for carousel
   mode when `[data-label-pos="hidden"]`.

   ⚠️ **Both label rules need the child chain too — and that means the test helper must be
   updated, not worked around.** `tests/test_tabs_partial.py::_screen_label_rule()` finds the
   rule with `next(ln for ln in css.splitlines() if ".tabs--js .tabs__panel-label" in ln)` —
   a literal `class space class` substring that any child chain destroys. Leaving the tabs
   rule as a **descendant** selector to satisfy that matcher is not an option: `tabs` is
   nestable, so an outer tabs-mode element would match the `.tabs__panel-label` nodes of a
   **carousel nested inside one of its panels** and clip away every one of that carousel's
   captions. (This is the mirror image of the tabs-in-carousel hazard above, and it is the
   direction that is easy to miss.)

   So: give **both** label rules the explicit child chain, and widen `_screen_label_rule()`'s
   matcher to find the tabs-mode rule by a marker that survives it — e.g. the line containing
   both `[data-display="tabs"]` and `.tabs__panel-label`. Changing the helper is in scope for
   this task, exactly as widening `_print_block()`'s slice is. Once both rules are
   child-chained the carousel's hidden-label rule can no longer collide with the helper's
   matcher at all, so there is **no** "identical property set" requirement between them —
   the carousel caption rule declares only what a caption needs.

   ⚠️ **Both rules must also stay on ONE physical line, selector and declarations together.**
   The helper then does `line.split("{")[1].split("}")[0]` on whatever line it matched. The
   child-chained selector is much longer than today's, so the natural reflow onto two lines
   yields either an `IndexError` (the selector line has no `{`) or — far worse — an empty
   property set, which makes
   `test_print_label_reveal_resets_every_property_the_screen_rule_sets` pass **vacuously**
   while the print reset silently stops being checked at all.
2. **The print rule keys on `[role="tabpanel"][hidden]`** (`display: block !important`).
   Carousel slides have no tab role and are hidden by absolute positioning + `opacity`, so
   as written the rule cannot match and *printing a carousel would silently lose every slide
   but the current one*. The print block must reset the carousel's mechanism instead, for
   `[data-display="carousel"]`: `.tabs__stage` → `position: static` and `min-height: 0`;
   `.tabs__section` → `position: static; opacity: 1; display: block`, the last of which
   neutralises the `label_pos: "below"` flex `order` (see below) so a printed slide always
   shows its title above its content.

   ⚠️ **Every property in that reset needs `!important`, not just `display`.** Two separate
   reasons, either one fatal alone: (a) the screen rule is
   `.el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage > .tabs__section` at
   specificity 0-5-0, and any print selector that drops a component is lower — so
   `position: absolute; opacity: 0` would
   win *in print media* and every slide would stack at one origin, invisible; (b)
   `.tabs__stage`'s `min-height` is set **inline** by `measure()`
   (`stage.style.minHeight = …`), and no author rule of any specificity can override a style
   attribute without `!important`. The existing print block already records this rule in its
   own comment — both reveals need `!important` or the screen rules win.
3. **`.el--tabs .tabs__bar { display: none !important; }` in print** hides the tab strip.
   `.tabs__cbar` and `.tabs__status` must be added to that rule.
4. **`.el--tabs .tabs__panel { padding-top: var(--space-5) }`** exists to separate a panel
   from the strip above it. In carousel mode it leaves a stray gap above every slide (and
   feeds the height measurement). Scope it to tabs mode and give carousel mode its own
   caption/panel spacing — **and gate that replacement on `[data-display="carousel"]` alone,
   not on `.tabs--carousel`.** It only adds spacing, so it is safe unenhanced, and gating it
   on the JS class would leave the no-JS stacked fallback with every caption flush against
   its panel. (This is the one carousel rule exempt from the gate class, precisely because it
   neither hides nor positions anything — and being attribute-only it must still use the
   child chain, or it would re-space a nested element's panels.)

**The caption needs a typographic specification, not just spacing.** In tabs mode the
`h3.tabs__panel-label` is clipped the instant JS runs, so it has never been styled as visible
text; in carousel mode it becomes the slide caption on the default path and would otherwise
inherit the global `h3` rules, which are far too heavy sitting above a table. Specify it as a
caption: small (≈`.95rem`, the gallery's `.gallery__desc` size), `--text-secondary`, centred
over the slide — so the light and dark screenshots are judged against an intent rather than a
default.

⚠️ **The new print rules must be APPENDED after the existing ones, AND `_print_block()`'s
slice must be widened.** The helper returns only `chunk[:1200]` of the `@media print` chunk.
Measured against the current file the tabs print block occupies **769** of those characters,
leaving **431** — and the mandated additions cost roughly 311 of them (a child-chained
`.tabs__stage` reset ≈111, a `.tabs__section` reset ≈152, extending the bar-hide rule with
`.tabs__cbar` and `.tabs__status` ≈48). That leaves ~120 characters for comments in a
stylesheet where every other block carries a multi-line rationale — an unquantified "keep it
terse" guarding a hard cliff, and the new source-level print test uses the same helper, so an
overflow surfaces as "the reset is missing" rather than "the slice overflowed".

Both changes, then: append (so every currently-asserted line stays in range regardless), and
raise the slice. Raising it is safe — no earlier `@media print` chunk contains `.el--tabs`
even at a 3000-character window, so the helper still selects the same chunk.

**`label_pos: "below"`** is a **CSS-only reorder**, since the `h3` always precedes the panel
in the DOM and the server markup may not change: `.tabs__section` becomes a column flex
container and `.tabs__panel-label` gets an `order` that places it after the panel. The visual
order then diverges from the reading order — acceptable, being confined to a heading and the
content it titles — and print neutralises it via the `display: block !important` reset in
item 2 above.

⚠️ **The flex declaration is scoped to `[data-label-pos="below"]`, NOT to carousel mode
generally.** Only the reorder needs it, and applying it to every carousel would put the
default `above` path — the headline case — inside a flex container for no reason. This repo
already has the lesson that a flex ancestor's default `min-inline-size` can defeat a nested
`overflow-x: auto` box, and the primary payload of this feature is exactly such a box
(`.el--table__scroll`, `.el--filltable__scroll`). Keeping the default path on ordinary block
layout removes the risk from the common case; the `below` path must be **measured**, not
assumed: a wide table inside a `below` slide must still scroll horizontally rather than widen
the stage.

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

### Builder summary — `courses/templatetags/courses_manage_extras.py`

`element_summary` currently describes a tabs element by counting its tabs, so a carousel
would read as "3 tabs" in the element list and the builder tree with nothing to distinguish
it. Append the mode for carousel-mode elements. This is the one deliberate exception to the
"untouched" list below, and it is what keeps Display from being an entirely invisible
setting. New strings are translated; the existing `ngettext` count keeps its Polish plural
forms.

Note the dependency: `element_summary` reads the **non-destructive** normalizer, so this
affordance works only if `normalize_labels_and_ids` carries `display` — trap site 1 above.
Required tests: a carousel-mode element's summary names the mode; a tabs-mode element's
summary is **byte-identical to today's** (so the change cannot regress every existing
element's row); and the `ngettext` plural still resolves under the PL catalog.

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
  `desc_pos` (a required key since day one, with no pre-feature default) and not
  `callout.kind`. The membership test is `isinstance(v, str) and v in TabsElement.DISPLAYS`
  against a **tuple**, per the data-model note above.
- **`_build_tabs` (`importer.py`)** constructs `TabsElement(data={"tabs": data["tabs"]})`
  from an explicit literal and must pass both new keys through. `setdefault` mutated the
  validated dict in place, so they are guaranteed present by the time this runs.
- **`FORMAT_VERSION` 7 → 8 (`schema.py`).** The importer rejects any archive whose version
  exceeds its own, which is what stops an older libli choking on keys it has never heard of.
  Adding emitted keys without the bump would hand an old instance a same-version archive it
  cannot parse.

  **The bump has FIVE pinned assertions, spread across TWO test roots**, and they must move
  in the same task or the branch gate fails long after the narrow per-task run passed:

  | File | Note |
  |---|---|
  | `tests/test_link_transfer.py` | `test_format_version_is_7` — **rename** the function too |
  | `tests/test_tabs_transfer.py` | `test_format_version_is_7` — **rename** the function too |
  | `tests/test_transfer_schema.py` | assertion inside another test; no rename |
  | `tests/test_transfer_export.py` | `manifest["format_version"] == 7`; no rename |
  | `courses/tests/test_image_size_transfer.py` | ⚠️ **different test root**; `test_format_version_is_bumped` is version-agnostic in name, so no rename |

  The explicit test-file list this task runs must therefore span **both** `tests/` and
  `courses/tests/`. Also update the stale `7` in a comment in `tests/test_table_transfer.py`.

  **Deploy-order note:** after merge, every archive this build exports is unimportable on any
  not-yet-upgraded instance. That is the normal cost of a format bump and is worth stating
  given the pending production cutover — upgrade before transferring.

### Explicitly untouched

`_CONTAINER_REGISTRY`, `CONTAINER_TRANSFER_KEYS`, `payloads._CONTAINER_SLOT_KEY`, the nesting
rules and `MAX_NEST_DEPTH` arithmetic, the element clipboard and paste path, `builder_filter`,
and `_ELEMENT_LABELS`. `TabsElement` is already a registered container, so children, depth
limits, filtering, pasting and export/import routing all keep working with no edits — that is
the whole reason this change is small.

One documentation edit is still required inside an otherwise untouched file:
`_CONTAINER_REGISTRY`'s comment states "CONTRACT: each normalizer returns
`{slot_list_key: [{slot_id_key: <id>}, ...]}`". After this change
`normalize_labels_and_ids` returns three keys. No consumer breaks — `resolve_scope` and
`paste_allowed` index by `list_key` — but the comment becomes false at precisely the place a
future reader goes to learn the contract, so amend it to "at least `{slot_list_key: […]}`;
extra keys are permitted and ignored".

⚠️ **"Untouched" does not mean "independent" for duplicate and copy-paste.**
`builder.duplicate_element` → `_copy_below` → `build_element_export` + `graft_elements`, and
`paste_element`'s copy mode takes the same route — so duplicating or pasting a carousel is
governed **entirely** by `_ser_tabs` / `_val_tabs` / `_build_tabs`. Those files need no edits
*because this spec already changes all three*; if any one of them missed a key, duplicating a
carousel would silently yield a tabs element with a cheerful 200. A test must duplicate (or
copy-paste) a carousel-mode element and assert the copy's `display` is still `carousel` — do
not let the "untouched" framing argue that one away. `MIN_TABS = 2` / `MAX_TABS = 10` are unchanged; the
gallery's 2–20 is not adopted. `GalleryElement`, `gallery.js` and the `.el--gallery` CSS are
read-only references. (`element_summary` is the single deliberate exception, above.)

## Data flow

**Authoring.** The author picks Display and Label position → `tabs_editor.js` re-serialises
the whole editor into the hidden `name="data"` JSON, reading the selects' live values → POST
→ `TabsElementForm.clean_data` validates the slide count, threads all three keys into
`normalize_labels_and_ids`, which mints ids for new rows and coerces the two enums → `save()`
runs the same normalizer again (idempotent) and writes `data`.

**Rendering.** `TabsElement.render` → `resolved_tabs()` (which internally runs
`normalize_data` **once**) groups the child `Element` rows by `tab_id`, and
`display_settings()` supplies the two enums without touching the tab list → the template
emits the stage and every section, with both data attributes on the root → `tabs.js` branches
on `data-display`, builds the nav, reserves the stage height, and shows slide 1.

**Editor preview.** `editor.js applyFragments()` swaps the pane, then calls the existing
`window.libliInitTabs(preview)`, which re-enhances the carousel from scratch; the `tabsReady`
guard makes the re-run safe, the detached-container guard stops the outgoing instance's
observers, and because the stage is server-rendered no embed is re-parented or reloaded.

**Changing Display is reflected in the preview only after a save.** The `change` listener
re-serialises the hidden JSON and toggles the label-position row; it does not re-render the
pane. A live no-save preview switch is explicitly **out of scope** — worth stating because
the image-size slice set the opposite precedent in the same file, where `editor.js`'s
`[data-size-preset]` handler does a no-save class swap, so an implementer could reasonably
guess either way.

**Transfer.** Export serialises `{tabs, display, label_pos}`; children are separate elements
carrying `parent` and `tab` refs, unchanged. Import defaults the two keys when absent,
repairs them when out of enum, and passes them into the constructed element.

## Error handling

- **Both normalizers are total** — an arbitrary or hostile `data` blob yields a well-formed
  dict, never an exception. A `display` of `null`, `42`, `"CAROUSEL"`, `[]` or `{}` renders
  as `tabs`; the unhashable cases are why the membership collections are tuples with an
  `isinstance` guard rather than sets.
- **A damaged blob never orphans children.** The non-destructive/destructive split is
  preserved exactly; the new keys ride on both normalizers.
- **Zero resolvable slides** cannot happen — `normalize_data` pads to `MIN_TABS`.
- **No JS, JS error, or unsupported browser** → the stacked, labelled fallback, which is
  fully readable. This is why every carousel screen rule is gated on `.tabs--carousel`, which
  the branch adds only after `show(0)` succeeds: the server-emitted `data-display="carousel"`
  alone would blank the element with JS off, and `.tabs--js` alone would blank it whenever
  the branch **threw part-way** — that class is already applied before the branch is even
  reached. The late gate is what makes "JS error → stacked fallback" true rather than
  aspirational.
- **`ResizeObserver` absent** (feature-detected exactly as the gallery detects it): the stage
  is measured once at init and never re-measured, so a KaTeX typeset or font swap after first
  paint leaves the reservation short. The material case is a carousel inside a
  `<details>`-based spoiler, where nothing dispatches `libli:reveal` — there the stage stays
  at `min-height: 0` with absolutely-positioned slides overlapping the content below it,
  permanently. That is a real degradation on such engines, not merely "costs re-measurement".
- **`inert` absent** in older engines: its loss costs tab-order hygiene on invisible slides,
  not function, and it is not polyfilled.
- **Import never fails on these two keys** — absent → defaulted, out of enum → repaired.
  Malformed *tabs* keep failing exactly as today.
- **A carousel nested inside a collapsed container** reserves a zero-height stage until
  revealed; the `libli:reveal` listeners are what correct it, and their absence is a visible
  defect rather than a crash.

## Testing

Falsification is the standard: for each test, name the mutation it must catch, apply it, and
require RED. Run tests narrowly — `-k` the mutant's own tests; a whole-repo sweep is a
branch-level gate, not a per-task step. **The `FORMAT_VERSION` bump is the documented
exception**: its assertions live in four non-tabs files across two test roots that a narrow
run will not reach, so that task runs all five transfer test files explicitly.

**Model / normalizer.** Defaults on an empty blob; each enum member round-trips; hostile
values (`None`, int, wrong-case string, **a list**, **a dict**) coerce to the default without
raising — the last two are the falsification for the tuple-not-frozenset decision and go RED
against a `frozenset` implementation; `normalize_data` carries both keys through its padding
and truncation paths. Do **not** assert "`DISPLAYS` equals the values of `DISPLAY_CHOICES`":
it is derived from that tuple one line below, so no plausible mutation makes it fail — a test
with no mutant. The assertion with teeth lives at the template layer instead: every
`DISPLAY_CHOICES` label renders as non-empty `<option>` text in the served editor form, which
goes RED the moment someone reintroduces a hand-written label map. **The critical
one: a `save()` round-trip asserting both keys survive** — set `display="carousel"`, save,
refetch, assert. Mutants, one per site: revert `normalize_labels_and_ids` to
`return {"tabs": tabs}` (the save round-trip must go RED); revert `normalize_data` likewise
(the render and padding tests must go RED). Neither mutant may leave the whole file green.

**Form.** Both selects round-trip through `clean_data`; a submission with `display` but **no**
`tabs` keeps the display (the early-return branch); an out-of-enum submission coerces to the
default rather than raising; the slide-count `ValidationError`s still fire; `editor_display`
/ `editor_label_pos` reflect submitted data on a bound invalid re-render, not the instance;
**a saved carousel re-rendered in the editor and re-submitted unchanged is still a carousel**
(the no-op re-save round-trip).

**Render.** `data-display` and `data-label-pos` appear with the right values; the caption
node is present in all three `label_pos` settings (it is hidden by CSS, never omitted —
dropping it would strip the title from print); the `.tabs__stage` wrapper is present in both
modes; **the emitted markup is byte-identical between the two modes apart from the two
attributes**, which is what pins the no-JS/print fallback; the existing
`data-tab-panel`/`data-tab-label` counts still hold. Beware the known bare-substring trap: an
assertion for a short literal can be satisfied by the page `<head>` — assert within the
element's own markup.

**Templates / CSS invariants.** All three `TABS_I18N` templates carry every new key. The
existing class-drift guard covers each new `tabs__*` class — and because all three ways of
defeating that guard are silent, add an assertion that the extracted set actually *contains*
the new names, not merely that it is non-empty. `editor.css` styles every new
`tabs-editor__*` class **and** carries the paired `[hidden] { display: none }` rule. A
tabs-mode element renders the label-position row `hidden` from first paint. The two existing
print tests still pass (they are the regression detector for the appended-not-inserted
ordering, and for the single-physical-line constraint on the label rules).

**A source-level print test for the carousel reset — this is a guard, not a nicety.** The
spec identifies "printing a carousel silently loses every slide but the current one" as a
content-loss failure with no error, and a human running a print preview is not a defence
against a later tidy-up stripping an `!important`. Add to `tests/test_tabs_partial.py`: the
print block contains a `[data-display="carousel"]` reset covering `.tabs__stage`
(`position`, `min-height`) and `.tabs__section` (`position`, `opacity`, `display`), each rule
uses the child chain, and **every declaration in both rules carries `!important`**. The
manual print preview stays as a supplement.

**Nesting — all three directions.** A tabs element inside a carousel slide, a carousel inside
a carousel slide, **and a carousel inside a tabs panel** each render visible and operable.
The first two are the regression test for the child-combinator requirement (failure mode: a
completely blank inner element); the third is the regression test for the label rules
(failure mode: the inner carousel silently loses every caption to the outer element's sr-only
rule).

**Source references.** `tests/test_e2e_imagezoom.py` documents the tab-order contract with
three `tabs.js:<line>` citations (the strip-building loop, `panel.tabIndex = 0`, the roving
tabindex). Inserting the carousel branch shifts all three, so re-point them — preferably to
symbol names rather than line numbers — in the same task.

**Transfer, duplicate and paste.** Round-trip a carousel-mode element through export →
validate → import and compare; import an archive whose tabs payload **lacks** both keys and
assert it succeeds with the defaults; import an **out-of-enum** value and assert it is
repaired to the default rather than raising; import an **unhashable** value
(`{"display": []}`) and assert it is repaired rather than raising `TypeError`; assert
`FORMAT_VERSION` is 8 and that a v9 archive is still refused. **And duplicate (or
copy-paste) a carousel-mode element and assert the copy is still a carousel** — that path
runs through the same three transfer functions, so a missed key there degrades a duplicate
silently, with a 200.

**Builder summary.** A carousel-mode element's summary names the mode; a tabs-mode element's
summary is byte-identical to today's.

**e2e — appended to the existing `tests/test_e2e_tabs.py`** (a new file would change what a
narrow `-k` run covers), run in the foreground. Build a unit with a carousel-mode tabs
element through the real UI — no fixtures shortcutting the editor — with **slides of
deliberately different natural heights** (e.g. a 3-row table and a 10-row table), because a
height assertion against similar slides passes trivially on a broken build. Then:

- click ›, assert slide 2's table is visible and **assert the inactive slide is NOT visible**
  — the negative direction is the one that has teeth. ⚠️ `checkVisibility()` defaults
  `opacityProperty` and `visibilityProperty` to **false**, so it accounts only for
  `display:none` / `content-visibility` and returns `true` for *every* opacity-hidden slide;
  Playwright's `toBeVisible()` shares the blind spot. Use
  `checkVisibility({opacityProperty: true, visibilityProperty: true})` or assert computed
  `opacity` / the `.is-active` class directly. (The repo's standing "use `checkVisibility()`"
  guidance was written for `content-visibility` and does not transfer.)
- assert slide 1 is `aria-hidden` and `inert`, and that an input inside an inactive slide is
  not reachable by tabbing;
- **assert the reservation's value, not only its stability**: `.tabs__stage`'s height must be
  ≥ the tallest section's own measured height. Stability alone is vacuous — once sections are
  absolutely positioned the stage's height *is* `min-height` by construction, so a build that
  reserved only slide 1's height passes a stability check while the tall slide overflows the
  nav bar. Assert the nav bar's `y` is identical on both slides as a second angle.
- assert prev is `disabled` on slide 1 and next on the last;
- assert `.tabs__status` reads "Slide 2 of N";
- assert Left/Right inside a wide table's scroll box scrolls the table and does **not**
  advance the carousel;
- **assert a gallery nested in a carousel slide advances alone** — one ArrowRight with focus
  inside it must move the gallery by one and leave the carousel's slide index unchanged;
- **assert the no-op re-save**: reopen the saved carousel in the real editor, save without
  touching a control, reload, and assert it is still a carousel (the one layer that can see
  a `serialize()` that drops the key);
- with `label_pos: "below"`, assert a wide table inside a slide still scrolls horizontally
  rather than widening the stage — the flex-ancestor risk that scoping the flex rule to this
  path was meant to contain.

Sync on conditions, never on sleeps. Screenshot **light and dark, judged separately** — a
dark screenshot is not verified by a light one passing.

**Manual/visual check.** Print preview of a unit containing a carousel, including one with
`label_pos: "below"`: every slide must appear, in order, each with its title **above** its
content, with the nav bar and status region absent. This is the regression the print rules
exist to prevent and is not covered by any headless assertion.
