# Locating nested elements in the unit editor's live preview

## Purpose

In the unit editor, clicking an element row scrolls the live preview to that element and
outlines it; hovering a row outlines it without scrolling. Today **this works for top-level
elements only.** Click a row for an element nested inside a tabs element, a two-column layout,
a spoiler, a callout or a before/after, and nothing happens at all — no scroll, no outline.

The reported symptom, in the author's words: *"if we have tabs with lots of content, we cannot
find out where the tab child is in the preview."*

This design makes the click → preview sync work for elements at **every** nesting depth, and —
because three of the five containers keep some of their children out of sight — makes the
preview **reveal** the container state needed to actually show the target.

### Root cause (verified, not inferred)

`templates/courses/manage/editor/_preview.html:28` is the only site that emits the
`data-element-id` preview marker:

```html
{% for el in preview_elements %}
  <section class="prev-el" data-element-id="{{ el.pk }}">{% render_element el ... %}</section>
{% endfor %}
```

`preview_elements` holds the unit's **top-level** join rows only. The filter that makes it
top-level lives once, in **`_editor_rows`** (`courses/views_manage.py`, `unit.elements.filter(
parent__isnull=True)`) — cite the function by name, not the line, which has rotted before; the
two context-key assignments that pass it to the template (`views_manage.py:1854` and `:1920`)
are only consumers.

Nested children are rendered *inside* `{% render_element %}`, by each container's own student
template, which wraps each child in a plain `<div class="<container>__child">` carrying **no
`data-element-id`**.

Both JS entry points look up that one marker:

- `courses/static/courses/js/editor.js:197` — `setHighlight(id, on)`, the hover outline
- `courses/static/courses/js/editor.js:237` — `scrollPreviewTo(id)`, the click scroll

```js
var sel = '.prev-el[data-element-id="' + id + '"]';
if (!root.querySelector(sel)) return;   // nested child -> always misses -> silent no-op
```

So this is **not** a broken lookup or a race. Nested elements are simply never labelled in the
preview DOM, and `scrollPreviewTo`'s explicit "absent -> no-op" early return swallows the miss.

#### Prior art: `data-preview-el` is a different marker, deliberately

`templates/courses/elements/imageelement.html:1` emits `data-preview-el="{{ el.pk }}"` on every
image at every nesting depth, **ungated**, and `editor.js:576` consumes it for the image-size
live preview. It exists precisely *because* `data-element-id` had to stay top-level-only.

It is not the seam for this work, for three reasons, and the plan must not conflate them:

- it carries the **content-object pk**, not the join-row pk (pinned by
  `courses/tests/test_image_size_render.py:88,98`) — a different identity namespace from the one
  the editor rows and `scrollPreviewTo` use;
- it is ungated, so it cannot carry an editor-only marker;
- it is image-only.

The two markers must remain distinguishable by name and by selector; nothing in this design
reads or writes `data-preview-el`.

### Reproduction (already run against master)

A unit holding a top-level text element, a tabs element with one child, and a spoiler with one
child; the editor page rendered and the preview pane sliced out of the response:

| element | `data-element-id` present in preview |
|---|---|
| top-level text | yes |
| tabs container | yes |
| child inside a tab | **no** |
| spoiler container | yes |
| child inside a spoiler | **no** |

The `__child` wrapper divs *are* present in that same preview HTML — they simply carry no
identity. That is the whole bug.

### Out of scope

- **Reveal gates** (`RevealGateElement`) as a general concern — see Error handling for the one
  interaction that does touch this design, and the explicit decision taken there.
- **No change to the student-page render.** Every marker added here is gated so student HTML
  stays byte-identical.

## Architecture / components

Two parts. Part 1 is the root-cause fix and is server-side only. Part 2 is what makes the
author's actual tabs scenario visible, and is client-side only.

### Part 1 — mark nested children in the preview

The five container templates **already** wrap each child in a per-child `<div>`, at every
nesting depth:

| Template | Line | Wrapper |
|---|---|---|
| `templates/courses/elements/tabselement.html` | 41 | `<div class="tabs__child">` |
| `templates/courses/elements/twocolumnelement.html` | 14 | `<div class="twocolumn__child">` |
| `templates/courses/elements/spoilerelement.html` | 48 | `<div class="spoiler__child">` |
| `templates/courses/elements/calloutelement.html` | 24 | `<div class="callout__child">` |
| `templates/courses/elements/beforeafterelement.html` | 28 | `<div class="ba__child">` |

The marker goes on **those existing divs**.

#### The exact emitted shape (pinned)

"Byte-identical student HTML" is a hard requirement, and whitespace is part of it, so the form
is specified rather than left to the implementer. Use exactly this shape, adapted per class
name:

```html
<div class="tabs__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>
```

Two inline `{% if %}`s, both on one line, the class-gate **inside** the quoted attribute value
and the attribute-gate contributing its own leading space. `beforeafterelement.html:28` is a
single-line `{% for %}` loop; a block-form `{% if %}` there would introduce newlines into
student output. The byte-identity claim is verified by **diffing a student render before and
after**, not by eye.

#### Why this seam

1. **No new DOM node.** Existing CSS reaches *through* and *across* these wrappers —
   `.callout__children > .callout__child:first-child > :first-child`
   (`courses/static/courses/css/courses.css:1987`, plus `:1988`, `:1989`),
   `.el--tabs .tabs__child + .tabs__child` (`:1775`), and
   `.el--twocolumn > .twocolumn__column > .twocolumn__child + .twocolumn__child` (`:1911`).
   An inserted wrapper would break every one of them. Adding attributes to the existing div
   breaks none.

2. **`.prev-el` is layout-neutral, and that is load-bearing.**
   `courses/static/courses/css/editor.css:826` declares only `border-radius` and a `box-shadow`
   transition; `.prev-el--hl` (`:827`) adds only a `box-shadow`. Neither declares `display`.
   That matters because the `[hidden]` guard is
   **`core/static/core/css/app.css:1179`** — `.lesson-block[hidden], .tabs__child[hidden],
   .ba__child[hidden] { display: none !important; }` — which lists **three** selectors and does
   **not** include `.callout__child` or `.spoiler__child`; those rely on the UA `[hidden]` rule,
   which only works while they carry no author `display`. Verify against
   **`app.css:1179` itself**, not the `courses.css:1982-1985` comment, which is stale (it names
   only two of the three selectors).

3. **Reusing the `prev-el` class means part 1 needs zero JS and zero CSS change.** The existing
   `.prev-el[data-element-id="<id>"]` selector starts matching nested elements at every depth
   automatically, for both the hover and the click path.

#### Why the `editor_preview` gate is sufficient — and what it protects

Three consumers query `[data-element-id]` **unscoped** and would misbehave if nested elements
carried it on a student page:

- `courses/static/courses/js/progress.js:52` — `document.querySelectorAll("[data-element-id]")`,
  observing every match;
- `courses/static/courses/js/slideshow.js:119` — maps a slide's matches to ints;
- `notes/static/notes/js/notes.js:427` — anchors on `.lesson-block[data-element-id]`.

There is already a standing invariant test for this:
`courses/tests/test_image_size_render.py:41-49` ("[data-element-id] is queried unscoped on
student pages and must stay top-level-only").

The design is safe because **none of those three scripts is loaded by
`templates/courses/manage/editor/editor.html`**, and the gate keeps them off the student page
entirely. The plan must **confirm** that non-loading as part of proving the gate sufficient,
rather than taking this paragraph's word for it.

#### Why `editor_preview` is available inside a container's children

The flag already propagates; this design adds no plumbing for it. The chain, which the plan must
**confirm rather than assume**:

- `courses/templatetags/courses_extras.py:160-176` — `render_element` builds a `page` dict and
  passes it **only** for `CONTAINER_MODELS`; `editor_preview` is one of its seven keys.
- `courses/models.py:471, 576, 679, 1936, 2060` — all five container `render()` methods spread
  `**(page or {})` into the child template context, `page` first so the container's own keys win.
- `courses/templatetags/courses_extras.py:74-75` — on the recursive child render,
  `render_element` re-reads `editor_preview` from context when not passed explicitly. The
  `is None` default (not `False`) is load-bearing and is commented as such at that site.

This is the same mechanism that already gets a **nested question's** "Try it" URL right, as
`_preview.html:15-26` documents at length. It therefore reaches arbitrary depth, not just
depth 2.

`child` in those five templates is the **`Element` join row**, so `child.pk` is the same
identity the editor rows carry as `data-element="{{ el.pk }}"` in `_element_row.html`, and the
same identity `setHighlight`/`scrollPreviewTo` are called with. The plan must confirm this too.

### Part 2 — reveal hidden ancestors before scrolling

Part 1 alone marks a child in an inactive tab, but the author still sees nothing. **The two tabs
display modes conceal their children by completely different means, and the difference decides
both the implementation and what a test may assert:**

| Ancestor | How it conceals a child | Consequence for the target's rect |
|---|---|---|
| Tabs, **strip** mode | inactive panel gets the `hidden` attribute (`display:none` via `app.css:1179` / UA) | **zero rect** — `alignTopInPane` measures nothing |
| Tabs, **carousel** mode | `courses.css:1788-1789`: every `.tabs__section` is `position:absolute; top:0; left:0; width:100%; opacity:0; pointer-events:none`, `.is-active` restores `opacity:1`; JS adds `inert` + `aria-hidden` | **rect is intact and already correct** — only `opacity` hides it |
| Spoiler | `<details>` closed | zero rect |
| Before/after | `.ba__panel[hidden]` | zero rect |

The carousel row has a sharp consequence the tests must respect: a target inside an inactive
slide **already has a correct rect**, so `alignTopInPane` scrolls to the right place with no
walk at all, and **Playwright treats `opacity: 0` as visible**. Any carousel assertion keyed on
visibility or geometry therefore passes on a build with no carousel reveal whatsoever. See
Testing.

#### The reveal steps

| Ancestor | Reveal |
|---|---|
| Spoiler | `details.open = true` |
| Tabs, strip mode | from `closest("[data-tab-panel]")` read its `id`, then click `[aria-controls="<id>"]` |
| Tabs, carousel mode | index of `closest(".tabs__section")` among its own container's sections, then click the matching own `.tabs__dot` |
| Before/after | if `closest(".ba__panel")` has the `hidden` attribute, click the container's own toggle |

#### Mode selection is by `data-display`, never by `[data-tab-panel]`

`tabselement.html` emits `data-tab-panel` in **both** display modes; only the strip branch ever
builds `[aria-controls]` buttons (`tabs.js:83` returns **early** into `initCarousel` when
`data-display === "carousel"`). An implementation that keys the strip branch on "the target has
a `[data-tab-panel]` ancestor" will match a carousel target, find no button, hit the
"missing control → skip" rule below, and **silently never reach the carousel branch** — while
looking like correct defensive code.

So: select the branch by reading the **owning container's `data-display`**, with an exact
`"carousel"` match, mirroring `tabs.js:83` (whose comment records that `null`, `""`, a stale
fragment, and any future third mode all fall through to the strip). `[data-tab-panel]` may be
used only to locate the panel *within* the already-chosen strip branch.

#### Direction, ordering, and termination

The walk collects the chain of hiding ancestors on the way **up**, then reveals **outermost
first**. The order is load-bearing, not cosmetic: `select(n)` calls `scrollIntoStrip(tabs[i])`,
which reads `tab.offsetLeft`, `tab.offsetWidth`, `scroller.scrollLeft` and
`scroller.clientWidth` — all zero while an outer ancestor is still `display:none`, leaving an
inner tab strip permanently mis-scrolled. The carousel's `measure()` reads geometry the same way.

The climb is **bounded at `[data-scope="preview"]`** (falling back to `.pane-body`). Without a
stop node it would continue into the editor pane. If that ancestor is absent, return quietly.

#### Drive the real control, and reimplement the ownership predicate

`tabs.js`'s `select(n)` / `show(n)` are closure-local; the file's only export is
`window.libliInitTabs`, and `ownSections()` / `ownPart()` (`tabs.js:44-62`) are **not
exported**. `editor.js` therefore implements its **own** `closest("[data-tabs]") === container`
predicate — the plan should not budget a refactor of `tabs.js`'s exports.

**Every container the walk drives needs that predicate, not just tabs.** A tabs element may
legally contain another tabs element (the depth-3 lift; `tabs.js:33-43` documents the failure at
length: an unscoped lookup from the outer container grabs the *inner* instance's controls, and
activating one hides the outer panel that contains it — the element goes blank). A before/after
may likewise contain another; `beforeafter.js:13-31` already implements `ownPanels()` /
`ownToggle()` with `closest("[data-beforeafter]") === container` for exactly this reason, and is
the shape to mirror.

**Where own-scoping is actually observable** (this decides a mutant, see Testing): strip-mode
panel ids are namespaced by the join-row pk — `tabselement.html` emits
`id="tabs-{{ eid }}-{{ tab.id }}-panel"` and `tabs.js:141` re-stamps the same value — so
`[aria-controls="tabs-<eid>-<tid>-panel"]` is **globally unique** and removing own-scoping from
the strip lookup changes nothing. Own-scoping is observable only in the **carousel** branch,
whose `.tabs__dot`s are index-keyed with no id at all; and DOM order makes it concrete, since
the outer instance's `nav` is appended after `.tabs__stage`, so an unscoped `.tabs__dot` query
returns the **inner** carousel's dots first.

#### Persistence is tabs-only

Clicking the real control earns persistence **for tabs**: `select()` stamps `data-tabs-active`
on the container (`tabs.js:167`), and `editor.js:79-96`'s `captureActiveTabs` /
`restoreActiveTabs` carry it across fragment swaps — keyed on `[data-tabs][data-tabs-eid]`.

That carry is **tabs-only**. A spoiler opened by the walk re-closes on the next save, and a
flipped before/after toggle resets to the Before panel — throwing the author back out of the
position this feature just found for them. **Decision: accepted as a follow-up, not handled
here.** The plan must not silently extend the capture/restore mechanism to cover them; if that
is wanted it is a separate change.

#### What settles late (and why no new timer is needed)

The carousel's 320 ms fade is pure `opacity` on absolutely-positioned slides that all sit at the
stage's top, so **it never moves the target** — there is nothing for a re-align to catch, and
"confirm the 500 ms re-align covers the 320 ms fade" would be a confident confirmation of a
non-issue.

What actually settles late is **`stage.style.minHeight`**, written by `measure()` behind a
`ResizeObserver` + `requestAnimationFrame` (`tabs.js`'s `scheduleMeasure`), which reflows
everything *below* the carousel. `scrollPreviewTo` already re-aligns on a
`requestAnimationFrame`, on every `img`/`iframe` load, and once more at 500 ms
(`editor.js:249`). The plan must confirm that existing 500 ms re-align survives **a stage
`min-height` change landing one or more frames after the click** — that is the risk, not the
fade.

The walk should also confirm `alignTopInPane`'s `el.closest(".pane-body")` (`editor.js:215`)
still resolves for a deeply nested target — it should, since `.pane-body` is a preview-pane
ancestor of everything in the preview, but it is one line to check and a silent `return` if
wrong.

## Data flow

**Server render (part 1).** Editor view → `_preview.html` loops top-level `preview_elements`,
wrapping each in `.prev-el[data-element-id]` and calling
`render_element(..., editor_preview=True)` → `render_element` puts `editor_preview` into the
`page` dict for containers → the container's `render()` spreads `page` into its child template
context → the container template emits
`<div class="<c>__child prev-el" data-element-id="<child.pk>">` and calls
`{% render_element child %}` → that call re-reads `editor_preview` from context, so the
recursion carries the flag down arbitrarily far.

On the **student** page `editor_preview` is falsy, every `{% if editor_preview %}` is skipped,
and the emitted HTML is byte-identical to today's.

**Client (part 2).** Author clicks an editor row → `scrollPreviewTo(id)` → the selector now
matches a nested child → the walk collects hiding ancestors up to `[data-scope="preview"]` and
reveals them outermost-first → `alignTopInPane` scrolls only `.pane-body` → the existing
re-aligns settle the position as async content and the stage re-measure land.

**Hover is deliberately not part of part 2.** `setHighlight` needs no change — the same selector
now matches, so it *does* apply `prev-el--hl` to nested elements. But hover **does not reveal**:
in strip mode the inactive panel is `display:none`, so the outline is drawn on a node with no
box and the author still sees nothing; in a carousel it is drawn at `opacity: 0`. This is the
accepted behaviour — the hover outline is observable only when the ancestor already shows the
child. The **server render test**, not an e2e, is what covers the hover path.

## Error handling

- **Target absent** (deleted element, failed swap): `scrollPreviewTo`'s existing early return
  stands. The walk runs **after** that guard, never before, so it is never handed `null`.
- **No hiding ancestor**: the walk is a no-op. A child in a callout or a two-column is visible in
  the preview's initial state, so part 1 alone suffices there.
- **Missing control**: if a tab button, dot, or before/after toggle cannot be found, skip that
  ancestor and continue up rather than throw — a throw would abort the whole click handler and
  lose the scroll part 1 already earned. (Note this rule is *also* the trap described under
  "Mode selection" — it must never be what a carousel target silently falls into.)
- **Already-revealed ancestor**: clicking the already-active tab is harmless — `select()` returns
  early on `i === active` (`tabs.js:163`). The before/after step **must** check for the `hidden`
  attribute before clicking, or it would toggle a visible panel *away*.
- **No-JS / failed enhancement**: `tabs.js` has a `bail()` path that strips enhancement on a
  throw; `beforeafter.js`'s `killOne` (`:34-40`) is the per-instance analogue — it removes
  `hidden` from both panels and adds `.ba--dead`. In both degraded states the content is already
  visible, the walk finds no control, and skipping is correct.

### The one reveal-gate interaction

The general reveal-gate concern is out of scope, but one case touches these exact divs and must
be stated correctly rather than hand-waved:

- The preview's **initial** state has every gated sibling **visible**. The pre-hide CSS is
  `.reveal-armed`-gated and lives only in `lesson_unit.html:40-44`, which the editor does not
  render — so the preview does *not* start with gated siblings hidden.
- The one case that does bite: when an author **clicks a gate in the preview**, `reveal.js`
  consumes it with `gateWrap.classList.remove("reveal-shown"); gateWrap.hidden = true;`
  (`reveal.js:155-161`), and `ownWrapper` (`:61-65`) resolves `gateWrap` to the direct child of
  the scope — i.e. exactly the `.tabs__child` / `.spoiler__child` / `.callout__child` /
  `.ba__child` div this design labels. Clicking that gate element's editor row then measures a
  zero node.

**Decision: out of scope.** That wrapper is the **target's own** wrapper, not an ancestor, so the
walk as specified can never see it; handling it would be a different mechanism (un-hiding the
target itself), and it only arises after the author has interactively consumed a gate inside the
preview. The plan must not silently extend the walk to cover it.

## Testing

This repo requires **falsification**, not merely green runs: each test is justified by the mutant
it kills.

### Server-side render tests

1. Nested children carry `data-element-id` in the **editor preview** at depth 2 **and** depth 3,
   across **all five** containers.
2. Nested children carry **no** `data-element-id` on the **student** page — this is what proves
   the `editor_preview` gate, and the only assertion that can catch the gate being dropped.
3. The student render is **byte-identical** before and after (diff-based, per Part 1).

**Scoping is mandatory and load-bearing.** The editor pane *also* uses `data-element-id` — on the
`el-act-edit` buttons in `_element_row.html` — so a bare substring assertion against the whole
page passes vacuously on a broken build. Every assertion must be scoped to the preview pane
(slice from `data-scope="preview"`), exactly the "a card above a list shadows its assertions"
trap this codebase has hit before.

### e2e

All e2e cases drive real UI. The click target must be **named**, because the two click paths
behave differently (see the `prev-el--hl` note below).

1. **Strip tabs** — seed a child into a **non-first** tab; click its editor row; assert the
   preview switched tabs and the child is genuinely visible (non-zero box).
2. **Carousel tabs** — seed a child into a non-first slide of a `display: "carousel"` tabs
   element; click its editor row; assert the reveal via a **discriminating signal**.
3. **Spoiler** — child inside a closed `<details>`; assert it opens.
4. **Before/after** — child in the After panel; assert the toggle flipped.
5. **Stacked ancestors** — a child in an inactive tab of a tabs element that itself sits inside a
   closed spoiler (or an inactive tab of an outer tabs element): assert **both** are revealed,
   and that the inner control's post-reveal state is sane — specifically that the inner tab strip
   is not left scrolled to a wrong offset, which is the failure outermost-first ordering prevents.

#### Two assertion traps that make a test vacuous

- **Never key the carousel assertion on visibility or geometry.** Inactive slides have intact
  rects and `opacity: 0`, which Playwright calls visible — so "in view" / `bounding_box()` passes
  with no carousel reveal at all. Key on `.tabs__section.is-active`, the absence of
  `inert` / `aria-hidden`, or `data-tabs-active`.
- **"The tab changed" needs a named observable, read at the right moment.** The durable signal is
  `data-tabs-active` on `[data-tabs][data-tabs-eid]` (scope by `data-tabs-eid` to the right
  instance); the strip-only signal is `aria-selected` on `.tabs__tab`. Capture the "before" value
  **before the click** — `applyFragments`' `captureActiveTabs`/`restoreActiveTabs`
  (`editor.js:79-96`) re-stamp the pre-click tab onto the rebuilt preview, so it cannot be
  inferred from the post-swap DOM.

#### `prev-el--hl` is not a click-path assertion

Do **not** assert `prev-el--hl` after a click. That class is toggled only by `setHighlight`,
bound to `mouseenter`/`mouseleave` on `.el-row[data-element]` (`editor.js:196-207`). On the
`.el-select` path (`editor.js:444-455`) `applyFragments` replaces **both** panes before
`scrollPreviewTo(selId)` runs — destroying the highlighted node — and `bindHover` re-binds to
fresh rows that receive no new `mouseenter` without pointer movement, so the class is absent. On
the other path (a click on the row body, `editor.js:460-464`) there is no swap and a prior
hover's class survives. The e2e asserts **reveal + position only**; making the outline follow a
click would be a **new requirement** on `scrollPreviewTo` and is not part of this design.

### Named mutants that must go RED

| # | Mutant | Test that must fail |
|---|---|---|
| a | Drop the marker from **one** container template | render test (hence: assert all five, not a sample) |
| b1 | Drop the **strip** reveal step | e2e 1 |
| b2 | Drop the **carousel** branch entirely (strip-mode-only implementation) | e2e 2 |
| b3 | Drop the spoiler `details.open = true` step | e2e 3 |
| b4 | Drop the before/after toggle step | e2e 4 |
| c | Drop the `{% if editor_preview %}` gate | student-page test |
| d | Un-scope the tabs control lookup | a nested **carousel** test |
| e | Reveal innermost-first instead of outermost-first | e2e 5 (inner strip left mis-scrolled) |

Two of these need their rationale recorded, or the plan will substitute a cheaper fixture that
cannot kill them:

- **(d) must be pinned to a nested _carousel_** — carousel-in-carousel, or a carousel containing
  the target. A nested **strip** fixture stays green on the mutated build, because strip panel
  ids are globally unique (see "Where own-scoping is actually observable"), so the unscoped
  lookup finds the same button. Own-scoping is unobservable in strip mode.
- **(b2) exists because mutant (b) as a single row was all-or-nothing.** A strip-only
  implementation kills no all-or-nothing mutant and ships green — the exact silent failure this
  design identified in prose. Splitting (b) per branch is what makes each of the four reveal
  steps individually tested.
