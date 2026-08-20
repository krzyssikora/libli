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

**Citation policy for this spec.** Line numbers in this repo have rotted before. Where a symbol
name exists, the symbol is the anchor and any line number is a convenience only; the plan should
re-locate by symbol, not by line.

### Root cause (verified, not inferred)

`templates/courses/manage/editor/_preview.html:28` is the only site that emits the
`data-element-id` preview marker:

```html
{% for el in preview_elements %}
  <section class="prev-el" data-element-id="{{ el.pk }}">{% render_element el ... %}</section>
{% endfor %}
```

`preview_elements` holds the unit's **top-level** join rows only. The filter that makes it
top-level lives once, in **`_editor_rows`** (`courses/views_manage.py`,
`unit.elements.filter(parent__isnull=True)`); the two context-key assignments that pass it to the
template (`views_manage.py:1854`, `:1920`) are only consumers.

Nested children are rendered *inside* `{% render_element %}`, by each container's own student
template, which wraps each child in a plain `<div class="<container>__child">` carrying **no
`data-element-id`**.

Both JS entry points look up that one marker — `setHighlight(id, on)` (the hover outline) and
`scrollPreviewTo(id)` (the click scroll), both in `courses/static/courses/js/editor.js`:

```js
var sel = '.prev-el[data-element-id="' + id + '"]';
if (!root.querySelector(sel)) return;   // nested child -> always misses -> silent no-op
```

So this is **not** a broken lookup or a race. Nested elements are simply never labelled in the
preview DOM, and `scrollPreviewTo`'s explicit "absent -> no-op" early return swallows the miss.

#### Prior art: `data-preview-el` is a different marker, deliberately

`templates/courses/elements/imageelement.html:1` emits `data-preview-el="{{ el.pk }}"` on every
image at every nesting depth, **ungated**, and `editor.js` consumes it for the image-size live
preview. It exists precisely *because* `data-element-id` had to stay top-level-only.

It is not the seam for this work, and the plan must not conflate them:

- it carries the **content-object pk**, not the join-row pk (pinned by
  `courses/tests/test_image_size_render.py:88,98`) — a different identity namespace from the one
  the editor rows and `scrollPreviewTo` use;
- it is ungated, so it cannot carry an editor-only marker;
- it is image-only.

Nothing in this design reads or writes `data-preview-el`.

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
  interaction that touches this design, and the explicit decision taken there.
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

"Byte-identical student HTML" is a hard requirement and whitespace is part of it, so the form is
specified rather than left to the implementer. Use exactly this shape, adapted per class name:

```html
<div class="tabs__child{% if editor_preview %} prev-el{% endif %}"{% if editor_preview %} data-element-id="{{ child.pk }}"{% endif %}>
```

Two inline `{% if %}`s, both on one line, the class-gate **inside** the quoted attribute value
and the attribute-gate contributing its own leading space. `beforeafterelement.html:28` is a
single-line `{% for %}` loop; a block-form `{% if %}` there would introduce newlines into student
output.

**The shape is test-pinned, not stylistic.** `courses/tests/test_spoiler_render.py:33,36` assert
`html.count('class="spoiler__child"') == 3` on the student render. That literal survives only
because the gate sits *inside* the quotes and collapses to nothing when `editor_preview` is
falsy; a gate placed outside the attribute, or a second `class` attribute, breaks an existing
test rather than merely a whitespace diff.

**Both halves are load-bearing.** The consumer selector is
`.prev-el[data-element-id="<id>"]` — the class is as necessary as the attribute, and a build that
emits one without the other is broken. Tests must assert the **pair on the same node** (see
Testing, mutant (a2)).

#### Why this seam

1. **No new DOM node.** Existing CSS reaches *through* and *across* these wrappers —
   `.callout__children > .callout__child:first-child > :first-child`
   (`courses/static/courses/css/courses.css:1987`, plus `:1988`, `:1989`),
   `.el--tabs .tabs__child + .tabs__child` (`:1775`), and
   `.el--twocolumn > .twocolumn__column > .twocolumn__child + .twocolumn__child` (`:1911`).
   An inserted wrapper would break every one of them. Adding attributes to the existing div
   breaks none.

2. **`.prev-el` is layout-neutral, and that is load-bearing.** `courses/static/courses/css/editor.css`
   declares on `.prev-el` only `border-radius` and a `box-shadow` transition; `.prev-el--hl` adds
   only a `box-shadow`. Neither declares `display`. That matters because the `[hidden]` guard is
   **`core/static/core/css/app.css:1179`** — `.lesson-block[hidden], .tabs__child[hidden],
   .ba__child[hidden] { display: none !important; }` — which lists **three** selectors and does
   **not** include `.callout__child`, `.spoiler__child` **or** `.twocolumn__child`. Those three
   rely on the UA `[hidden]` rule, which works only while they carry no author `display`, so the
   constraint applies to each of them identically once they gain `prev-el`. Verify against
   **`app.css:1179` itself**, not the `courses.css:1982-1985` comment, which is stale (it names
   only two of the three guarded selectors).

3. **Reusing the `prev-el` class means part 1 needs zero JS and zero CSS change.** The existing
   selector starts matching nested elements at every depth automatically, for both the hover and
   the click path.

#### Why the `editor_preview` gate is sufficient — and what it protects

Three consumers query `[data-element-id]` **unscoped** and would misbehave if nested elements
carried it on a student page:

- `courses/static/courses/js/progress.js` — `document.querySelectorAll("[data-element-id]")`,
  observing every match;
- `courses/static/courses/js/slideshow.js` — maps a slide's matches to ints;
- `notes/static/notes/js/notes.js` — anchors on `.lesson-block[data-element-id]`.

There is already a standing invariant test:
`courses/tests/test_image_size_render.py:41-49` ("[data-element-id] is queried unscoped on
student pages and must stay top-level-only").

The design is safe because **none of those three scripts is loaded by
`templates/courses/manage/editor/editor.html`**, and the gate keeps them off the student page
entirely. The plan must **confirm** that non-loading rather than taking this paragraph's word.

#### Why `editor_preview` is available inside a container's children

The flag already propagates; this design adds no plumbing. The chain, which the plan must
**confirm rather than assume**:

- `courses/templatetags/courses_extras.py:160-176` — `render_element` builds a `page` dict and
  passes it **only** for `CONTAINER_MODELS`; `editor_preview` is one of its seven keys.
- `courses/models.py:471, 576, 679, 1936, 2060` — all five container `render()` methods spread
  `**(page or {})` into the child template context, `page` first so the container's own keys win.
- `courses/templatetags/courses_extras.py:74-75` — on the recursive child render,
  `render_element` re-reads `editor_preview` from context when not passed explicitly. The
  `is None` default (not `False`) is load-bearing and is commented as such at that site.

This is the same mechanism that already gets a **nested question's** "Try it" URL right, as
`_preview.html:15-26` documents at length. It reaches arbitrary depth, not just depth 2.

`child` in those five templates is the **`Element` join row**, so `child.pk` is the same identity
the editor rows carry as `data-element="{{ el.pk }}"`, and the same identity
`setHighlight`/`scrollPreviewTo` are called with. The plan must confirm this too.

### Part 2 — reveal hidden ancestors before scrolling

Part 1 alone marks a child in an inactive tab, but the author still sees nothing. **The two tabs
display modes conceal their children by completely different means, and the difference decides
both the implementation and what a test may assert:**

| Ancestor | How it conceals a child | Consequence for the target's rect |
|---|---|---|
| Tabs, **strip** mode | `select()` sets the `hidden` attribute on the inactive `.tabs__panel` — hidden by the **UA `[hidden]` rule only**; `.tabs__panel` is deliberately absent from the `app.css:1179` guard list, which covers the reveal-cascade wrappers, not the panel | **zero rect** |
| Tabs, **carousel** mode | `.el--tabs.tabs--carousel[data-display="carousel"] > .tabs__stage > .tabs__section` is `position:absolute; top:0; left:0; width:100%; opacity:0; pointer-events:none`; `.is-active` restores `opacity:1`. JS also sets `inert` + `aria-hidden` | **rect intact and already correct** — only `opacity` hides it |
| Spoiler | `<details>` closed | zero rect |
| Before/after | `.ba__panel[hidden]` | zero rect |

Two consequences the tests must respect. First, a carousel target **already has a correct rect**,
so `alignTopInPane` scrolls to the right place with no walk at all, and **Playwright treats
`opacity: 0` as visible** — any carousel assertion keyed on visibility or geometry passes on a
build with no carousel reveal whatsoever. Second, the carousel row's selector is gated on
`.tabs--carousel`, which `initCarousel` adds **last**, only after a successful `show(0)`; it also
returns early (stripping `tabs--js`) when there are fewer than two sections, and `bail()` removes
the class on a throw. So a `data-display="carousel"` element is **not necessarily concealing
anything** — a bailed or single-slide carousel shows all sections statically and has no dots, and
correctly degrades to the "missing control → skip" rule below.

#### What counts as a hiding ancestor (the collection predicate)

The walk needs a membership rule, not just a per-type action. **"Hidden" is not decidable by the
`hidden` attribute alone** — a carousel conceals purely by class/opacity/`inert`, so an
implementer who generalises the before/after rule to "collect nodes carrying `[hidden]`" will
never collect a carousel ancestor, reproducing the exact silent-skip failure this design warns
about. Collect node-by-node, per type:

In every row `C` is the **controlling** node — the one whose control the walk will drive — never
an inner panel:

| Ancestor type (`C`) | Collected when |
|---|---|
| `<details>` (spoiler) | `details:not([open])` |
| `[data-tabs]` container | **unconditionally**, whenever an owned `.tabs__section` contains the target — rely on `select()`/`show()`'s own `i === active` early return rather than pre-checking |
| `[data-beforeafter]` container | its owned `.ba__panel` that contains the target carries the `hidden` attribute |

The before/after row names the **container**, not the panel, deliberately: a `.ba__panel` has no
"own toggle" of its own (the toggle is a sibling of `.ba__panels`, i.e. the panel's uncle), and
the ownership predicate `closest("[data-beforeafter]") === container` is meaningless when `C` is
itself a panel.

#### Per-ancestor node resolution — never `closest()` from the target

For a stacked chain (tabs-in-tabs, which e2e 5 and mutant (d) require),
`target.closest(".tabs__section")` returns the **innermost** section for *every* ancestor in the
chain. The outer container would then compute an index against a section it does not own
(`indexOf` → -1) and reveal the wrong slide, or nothing. The same defect applies to
`closest("[data-tab-panel]")`, `closest("details")` and `closest(".ba__panel")`.

**The rule is a filter over `C`'s own nodes, not a walk step.** For each collected ancestor `C`:

> `s` = the single node in `C`'s **owned** node list for which `s.contains(target)` —
> `ownSections(C)` for a tabs container, `ownPanels(C)` for a before/after.

**Timing note:** for tabs the collection is unconditional, so `s` can be resolved after
collection. For before/after the collection decision **is** this lookup (the predicate asks
whether the owned panel containing the target carries `hidden`), so `s` is resolved during
collection and carried forward — resolve it once, not twice.

It is emphatically **not** "the child of `C` the climb passed through": the real DOM is
`[data-tabs] > .tabs__stage > .tabs__section > .tabs__panel > .tabs__child` and
`[data-beforeafter] > .ba__panels > .ba__panel > .ba__child`, so that child is `.tabs__stage` /
`.ba__panels` — a wrapper that is neither a section nor a panel, has no `id`, and yields
`indexOf → -1`. Filter `C`'s owned list; never take the climb's direct child, and never
`closest()` from the target.

#### The reveal steps

Given a collected ancestor `C` and its resolved node `s`. **`s` is always the owned
`.tabs__section` (tabs) or `.ba__panel` (before/after)** — one definition, not two:

| Ancestor | Reveal |
|---|---|
| Spoiler | `C.open = true`, then dispatch a bubbling `libli:reveal` (see "What settles late") |
| Tabs, strip mode | derive the panel from `s` with an `ownPart(s, "[data-tab-panel]")`-shaped lookup (rejecting a nested instance's panel, mirroring `tabs.js`), read that panel's `id`, then click `[aria-controls="<id>"]` |
| Tabs, carousel mode | index of `s` among `ownSections(C)`, then click the dot at that index in `C`'s **own** dot list |
| Before/after | click `C`'s own toggle (`ownToggle(C)`) |

The strip branch needs that extra hop because `.tabs__section` carries **no `id`** in the
template — the `id` the `[aria-controls]` lookup needs is on the `.tabs__panel` inside it.

**"Click" means the element's own `.click()`** — a real DOM click, which dispatches the listener
**synchronously**, so each step completes before the next ancestor inward is measured. That
synchrony is what the ordering argument rests on; a queued/synthetic event would break it. The
`[aria-controls]` lookup may be **document-rooted**: those ids are namespaced by the join-row pk
and therefore globally unique (see "Where own-scoping is actually observable"). The dot lookup
may **not** be — it has no id and must use the ownership filter.

**A resolution that yields more than one node means the ownership filter was omitted.** The
filter is precisely what makes `s` unique: for a nested before/after, both the outer's panel and
the inner's panel satisfy `s.contains(target)`, and only `closest("[data-beforeafter]") === C`
disambiguates them. There is no first-match/last-match tie-break to fall back on — a multi-match
is a bug in the filter, not a case to resolve.

**Own-scoping observability, before/after edition** (the tabs analysis is above): **neither**
before/after lookup is observable, so neither gets a mutant. Un-scoping `ownToggle` is
unobservable because the container's own `.ba__toggle` precedes any nested one in document order,
so a descendant query returns it anyway. Un-scoping `ownPanels` is unobservable for the same
reason, and more strongly: any nested `.ba__panel` containing the target is necessarily a
*descendant* of one of `C`'s own panels, so in document order the **first** `.ba__panel` under `C`
satisfying `s.contains(target)` is provably `C`'s own. Keep the ownership filter anyway — it is
what makes the result unique by construction rather than by relying on document order — but do
not manufacture a test for it.

**The carousel step depends on an undocumented coupling:** `dots` is positionally 1:1 with
`ownSections(container)` (`initCarousel` builds it as `sections.map(...)`), and unlike the strip
branch there is no id to key on. Nothing in `tabs.js` names or pins that invariant, and a future
change that filtered or reordered dots would break the walk silently. Record the dependency, and
derive the dot list with the **same ownership filter** used for sections rather than a separate
query.

#### Mode selection is by `data-display`, never by `[data-tab-panel]`

`tabselement.html` emits `data-tab-panel` in **both** display modes; only the strip branch ever
builds `[aria-controls]` buttons (`tabs.js` returns **early** into `initCarousel` when
`data-display === "carousel"`). An implementation that keys the strip branch on "the target has a
`[data-tab-panel]` ancestor" will match a carousel target, find no button, hit the
"missing control → skip" rule, and **silently never reach the carousel branch** — while looking
like correct defensive code.

So: select the branch by reading the **owning container's `data-display`**, with an exact
`"carousel"` match, mirroring `tabs.js` (whose comment records that `null`, `""`, a stale
fragment, and any future third mode all fall through to the strip). `[data-tab-panel]` may be
used only to locate the panel *within* the already-chosen strip branch.

#### Direction, ordering, and termination

The walk collects the chain of hiding ancestors on the way **up**, then reveals **outermost
first**. The order is load-bearing, not cosmetic: `select(n)` calls `scrollIntoStrip(tabs[i])`,
which reads `tab.offsetLeft`, `tab.offsetWidth`, `scroller.scrollLeft` and
`scroller.clientWidth` — all zero while an outer ancestor is still `display:none`, leaving an
inner tab strip permanently mis-scrolled. The carousel's `measure()` reads geometry the same way.

The climb is **bounded at `[data-scope="preview"]`. If that ancestor is absent, do not walk at
all.** (No `.pane-body` fallback: any target in the preview is already inside the preview's own
`.pane-body`, so it could never rescue a missing `[data-scope="preview"]` in a way that differs
from it.) Without a stop node the climb would continue into the editor pane.

**The bound is defensive-only and currently unobservable**, so no mutant covers it and the plan
should not spend a task inventing a test that cannot go red: there is nothing collectible above
`[data-scope="preview"]` on today's editor page — `_unit_settings.html`'s `<details>` is a
**sibling** of the editor grid, not an ancestor of the preview, and no `[data-tabs]` sits above
the pane.

**The reveal cascade runs synchronously**, immediately after the absent-target early return and
**before** `scrollPreviewTo` schedules its existing `requestAnimationFrame`. This is pinned
because putting the reveal *inside* that rAF callback — a natural reading of "reveal, then
align" — measures the pre-reveal layout on the first pass and leaves the smooth scroll animating
toward a stale position, with only the 500 ms backstop correcting it. No re-query of the target
is needed after the cascade: none of the four reveal steps replaces nodes.

**This ordering is unobservable after settling, and gets the same treatment as the climb bound:
no mutant covers it.** Its own failure mode is "the settled position is reached late, via the
backstop" — and every position assertion in this spec polls past that backstop, so the final
state is identical either way. Falsifying it would require bracketing the transient (sampling the
delta on the frame after the click, under `prefers-reduced-motion: reduce`) rather than the
settled state. That is deliberately **not** prescribed: it is the flakiest possible assertion for
the smallest possible gain. The plan should not spend a task trying to make it go red.

#### Drive the real control, and reimplement the ownership predicate

`tabs.js`'s `select(n)` / `show(n)` are closure-local; the file's only export is
`window.libliInitTabs`, and `ownSections()` / `ownPart()` are **not exported**. `editor.js`
therefore implements its **own** `closest("[data-tabs]") === container` predicate — the plan
should not budget a refactor of `tabs.js`'s exports.

**Every container the walk drives needs that predicate, not just tabs.** A tabs element may
legally contain another (the depth-3 lift; `tabs.js`'s scoping comment documents the failure: an
unscoped lookup from the outer container grabs the *inner* instance's controls, and activating one
hides the outer panel that contains it — the element goes blank). A before/after may likewise
contain another; `beforeafter.js`'s `ownPanels()` / `ownToggle()` use
`closest("[data-beforeafter]") === container` for exactly this reason and are the shape to mirror.

**Where own-scoping is actually observable** (this decides a mutant): strip-mode panel ids are
namespaced by the join-row pk — `tabselement.html` emits `id="tabs-{{ eid }}-{{ tab.id }}-panel"`
and `initOne` re-stamps the same value onto `panel.id` — so `[aria-controls="tabs-<eid>-<tid>-panel"]`
is **globally unique** and removing own-scoping from the strip lookup changes nothing. Own-scoping
is observable only in the **carousel** branch, whose dots are index-keyed with no id at all; and
DOM order makes it concrete, since the outer instance's `nav` is appended after `.tabs__stage`, so
an unscoped `.tabs__dot` query returns the **inner** carousel's dots first.

#### Persistence is tabs-only

Clicking the real control earns persistence **for tabs**: `select()` stamps `data-tabs-active` on
the container, and `editor.js`'s `captureActiveTabs` / `restoreActiveTabs` carry it across
fragment swaps, keyed on `[data-tabs][data-tabs-eid]`.

That carry is **tabs-only**. A spoiler opened by the walk re-closes on the next save, and a
flipped before/after toggle resets to the Before panel — throwing the author back out of the
position this feature just found. **Decision: accepted as a follow-up, not handled here.** The
plan must not silently extend capture/restore to cover them.

#### All three `scrollPreviewTo` call sites inherit the walk

There are **three**, not two, and the walk lives inside `scrollPreviewTo`, so all three get it:

| Call site | Path | Fragment swap? |
|---|---|---|
| `editor.js:367` | after **any** `form[data-op]` submit — save, move, duplicate, delete, including the 409 and 422 branches | yes (`applyFragments` runs `restoreActiveTabs` first) |
| `editor.js:451` | the `.el-select` path (opens the edit form) | yes |
| `editor.js:463` | a click on the row body (no editor opened) | no |

**Decision: the reveal on the post-op path is intended.** After saving or moving a nested
element, revealing that element's own tab is the useful behaviour, and it is consistent with the
scroll that site already performs. Note the interaction: `restoreActiveTabs` re-stamps the
author's previous tab onto the rebuilt preview, and then the walk overrides it — so after an op
the visible tab is the **operated element's** tab, not the author's previous one. This is a
behaviour change on every element op and is deliberate.

#### What settles late (and why no new timer is needed)

The carousel's 320 ms fade is pure `opacity` on absolutely-positioned slides that all sit at the
stage's top, so **it never moves the target** — there is nothing for a re-align to catch.

What settles late is **`stage.style.minHeight`**, written by `measure()` behind a
`ResizeObserver` + `requestAnimationFrame` (`scheduleMeasure`), which reflows everything *below*
the carousel; a nested carousel can schedule its measure after the outer reveal.
`scrollPreviewTo` already re-aligns on a `requestAnimationFrame`, on every `img`/`iframe` load,
and once more at 500 ms.

**Acceptance criterion:** after settling, the target's top is within **4 px** of the pane's
content top (consistent with `alignTopInPane`'s own `< 1px` no-op threshold plus sub-pixel
layout).

**If the 500 ms backstop proves insufficient** for a nested carousel, the specified fallback is
an additional re-align bound to `libli:reveal` — not an arbitrarily longer timeout. But that
event has a gap the plan must close: `libli:reveal` is dispatched by `tabs.js` (`select`/`show`),
`beforeafter.js` and `reveal.js`, and **not by a `<details>`** — `tabs.js` says so at its own
`document.addEventListener("libli:reveal", …)` site ("A `<details>`-based spoiler dispatches
nothing — there the ResizeObserver is what rescues the measurement"). So for exactly the chain
this section worries about — a carousel whose `measure()` lands late because a **spoiler** above
it was opened — the fallback would have no event to bind to.

**Resolution: the walk dispatches the event itself.** The spoiler reveal step sets `C.open = true`
and then dispatches a bubbling `libli:reveal` from `C`. That closes the gap for the fallback and
independently gives a nested carousel's `scheduleMeasure` the signal it otherwise misses.

**This makes an in-tree comment false — amend it.** The comment above `tabs.js`'s
`container.addEventListener("libli:reveal", scheduleMeasure)` states that reveal-gates and outer
tab panels "are the only two dispatchers in the codebase" and that "a `<details>`-based spoiler
dispatches nothing". After this change `editor.js`'s walk is a third dispatcher and a spoiler
*does* dispatch, in the editor preview. The plan must update that comment (naming the walk,
editor-preview-only) and keep the edit **line-count neutral**, per this repo's citation-rot
convention. This spec already flags `courses.css:1982-1985` as a stale-comment trap; do not
create a second one.

The plan must record the measured outcome in the PR body either way.

The plan should also confirm `alignTopInPane`'s `el.closest(".pane-body")` still resolves for a
deeply nested target — it should, but it is one line to check and a silent `return` if wrong.

## Data flow

**Server render (part 1).** Editor view → `_preview.html` loops top-level `preview_elements`,
wrapping each in `.prev-el[data-element-id]` and calling
`render_element(..., editor_preview=True)` → `render_element` puts `editor_preview` into the
`page` dict for containers → the container's `render()` spreads `page` into its child template
context → the container template emits
`<div class="<c>__child prev-el" data-element-id="<child.pk>">` and calls
`{% render_element child %}` → that call re-reads `editor_preview` from context, so the recursion
carries the flag down arbitrarily far.

On the **student** page `editor_preview` is falsy, every `{% if editor_preview %}` is skipped, and
the emitted HTML is byte-identical to today's.

**Client (part 2).** Any of the three call sites above invokes `scrollPreviewTo(id)` → the
selector now matches a nested child → the walk collects hiding ancestors up to
`[data-scope="preview"]` and reveals them outermost-first → `alignTopInPane` scrolls only
`.pane-body` → the existing re-aligns settle the position as async content and the stage
re-measure land.

**Hover reveals nothing, by decision.** `setHighlight` needs no change — the same selector now
matches, so it *does* apply `prev-el--hl` to nested elements, which is the whole hover fix. But
hover does **not** trigger the walk: in strip mode the outline is then drawn on a `display:none`
node and in a carousel at `opacity: 0`, so it is observable only when the ancestor already shows
the child. That is accepted; the hover path is covered by a dedicated e2e over an
always-visible nested child (see Testing), because a server render test cannot prove
`setHighlight` reaches a nested node.

## Error handling

- **Target absent** (deleted element, failed swap): `scrollPreviewTo`'s existing early return
  stands. The walk runs **after** that guard, never before, so it is never handed `null`.
- **No hiding ancestor**: the walk is a no-op. A child in a callout or a two-column is visible in
  the preview's initial state, so part 1 alone suffices there.
- **Missing control**: if a tab button, dot, or before/after toggle cannot be found, skip that
  ancestor and continue with the next one **inward in the reveal order** — never throw, which
  would abort the whole click handler and lose the scroll part 1 already earned. (Collection runs
  outward and reveal runs inward; missing controls are discovered during the *reveal* phase, so
  "continue inward" is the direction that matters here.) This is the correct behaviour for a
  bailed carousel and a `killOne`'d before/after. It is *also* the trap described under "Mode
  selection" — it must never be what a healthy carousel target silently falls into.
- **Already-revealed ancestor**: clicking the already-active tab is harmless — `select()` returns
  early on `i === active`. The before/after step is gated by the collection predicate, so it
  never toggles a visible panel *away*.
- **No-JS / failed enhancement**: `tabs.js` has a `bail()` path that strips enhancement on a
  throw; `beforeafter.js`'s `killOne` is the per-instance analogue — it removes `hidden` from both
  panels and adds `.ba--dead`. In both degraded states the content is already visible, the walk
  finds no control, and skipping is correct.

### The one reveal-gate interaction

The general reveal-gate concern is out of scope, but one case touches these exact divs:

- The preview's **initial** state has every gated sibling **visible**. The pre-hide CSS is
  `.reveal-armed`-gated and lives only in `lesson_unit.html:40-44`, which the editor does not
  render — so the preview does *not* start with gated siblings hidden.
- The case that does bite: when an author **clicks a gate in the preview**, `reveal.js` consumes
  it with `gateWrap.classList.remove("reveal-shown"); gateWrap.hidden = true;`, and `ownWrapper`
  resolves `gateWrap` to the direct child of the scope — i.e. exactly the `.tabs__child` /
  `.spoiler__child` / `.callout__child` / `.ba__child` div this design labels. Clicking that gate
  element's editor row then measures a zero node.

**Decision: out of scope.** That wrapper is the **target's own** wrapper, not an ancestor, so the
walk as specified can never see it; handling it would be a different mechanism (un-hiding the
target itself), and it only arises after the author has interactively consumed a gate inside the
preview. The plan must not silently extend the walk to cover it.


## Testing

This repo requires **falsification**, not merely green runs: each test is justified by the mutant
it kills.

### Pre-work sweep

Before writing anything, grep the test suite for `prev-el` and for the five
`<container>__child` class literals, and record that each existing assertion still holds under
the pinned shape. Known consumers: `tests/test_manage_element_ops.py:320` (`b'class="prev-el"'`),
`tests/test_e2e_media_manager.py:195` (`.prev-el img`),
`courses/tests/test_spoiler_render.py:33,36` (the counted `class="spoiler__child"` literal), and
`courses/tests/test_nested_question_nojs_feedback.py` (slices on the child-class names). All
appear to survive, but the sweep is what proves it.

### Server-side render tests

1. Nested children carry **both halves of the marker on the same node** in the **editor
   preview** — assert a `.<container>__child.prev-el[data-element-id="<child.pk>"]` node exists.
   Asserting the attribute alone leaves a class-dropping mutant green, and for callout and
   two-column there is no e2e to catch it.

   **Coverage matrix:** all **five** containers at depth 2, plus **tabs-inside-a-spoiler** at
   depth 3 (the depth-3 case proves the recursion carries `editor_preview` across two
   `CONTAINER_MODELS` barriers; repeating it for all 25 nesting pairs proves nothing further).
   That pair is named rather than left to choice because the pairs differ in risk — a
   callout-in-callout is the mildest case — and because it mirrors the shape e2e 5 exercises.
   **Build fixtures with direct `Element(parent=…)` rows**, as
   `courses/tests/test_image_size_render.py` does — not through `builder.resolve_scope`, whose
   clause 3/4 depth rules would couple this test to the nesting policy it is not testing.
2. On the **student** page, nested children carry **neither** half: no `data-element-id` **and**
   no `prev-el` class on the child wrappers. Both halves are separately gated, so a build that
   drops only the class-gate leaks `prev-el` into every student page while an attribute-only
   assertion stays green — and the one-off byte diff below, by definition, never runs again.

**Scoping is mandatory and load-bearing — but the two tests scope differently.**

*Render test 1 (editor page).* The editor pane *also* uses `data-element-id` — on the
`el-act-edit` buttons in `_element_row.html` — so a bare substring assertion against the whole
page passes vacuously on a broken build, exactly the "a card above a list shadows its assertions"
trap this codebase has hit before. Parse the document **once** and root the selector at
`[data-scope="preview"]` (e.g. `[data-scope="preview"] .tabs__child.prev-el[...]`), rather than
slicing the response body — a string slice followed by a select on the fragment re-parses partial
HTML.

*Render test 2 (student page).* **Do not apply that rule here.** A student lesson page has **no**
`[data-scope="preview"]` node — it exists only in the editor's `_preview.html` — so a selector
rooted there matches zero nodes and "neither half is present" is trivially true, leaving mutants
(c1) and (c2) both alive. Instead select the five `.<container>__child` wrappers on the student
page, **assert that selection is non-empty first** (otherwise the test is vacuous for the same
reason), then assert neither marker half appears on them.

### Byte-identity: a pre-merge verification step, not a test

This is **not** an automated test — a suite running on the post-change tree has no "before"
render to diff against, and left in the test list it would be quietly downgraded to render test 2
(which does not cover whitespace at all).

It is a **one-off pre-merge verification**: render a student lesson page containing all five
container types on `origin/master` and on the branch, and diff the two outputs byte-for-byte.

**The diff must be normalized first, or it can never come out clean.** `templates/base.html:62`
and `:139` each emit `{% csrf_token %}`, and `_lesson_article.html:26` emits a third — and Django
re-masks the CSRF token with a fresh random salt on **every** render, so two renders of an
identical template always differ. Procedure:

1. Normalize: replace every `name="csrfmiddlewaretoken" value="…"` with a constant, plus anything
   else the control diff turns up.
2. **Run a control diff of master against master first** and require it to come out **empty**.
   This is what proves the normalization sufficient; without it a clean branch diff means nothing
   and a dirty one is uninterpretable.
3. Only then diff master against the branch.

The result must be recorded in the PR body. No golden fixture is committed.

### CSS guard test

`.prev-el` must **never** declare `display`. Once the child wrappers carry it, an author `display`
on `.prev-el` would stop `.callout__child` / `.spoiler__child` / `.twocolumn__child` honouring the
UA `[hidden]` rule (they are absent from the `app.css:1179` guard), which in turn breaks
`reveal.js`'s `gateWrap.hidden = true` in the editor preview.

Reading it once is not enough for a cross-file invariant. Leave a standing tripwire, modelled
directly on the repo's existing analogue,
`courses/tests/test_beforeafter_css.py::test_panel_and_child_declare_no_display` (which carries
its own first-match-regex warning worth reusing). Mutant: add `display: block` to `.prev-el` → RED.

### e2e

All e2e cases drive real UI.

**Mandatory precondition — nested editor rows start collapsed.** `_element_row.html:82` wraps each
tab's child rows in `<details class="tabs-rows">` that is `open` only when the slot is in
`open_slots`, or `clip_active`, or **`forloop.first`** — so a child in a **non-first** tab starts
collapsed. `_element_row.html:141` (`<details class="columns-rows">`) has **no** `forloop.first`
clause, so *both* two-column slots start collapsed. In a fresh Playwright context nothing is
restored, so "click its editor row" would hang on a not-visible locator. Every tabs and
two-column case must first open the owning `<details>` (or seed `open_slots`). Spoiler, callout
and before/after rows are always-open divs and need no such step.

**Settling.** "After settling" is not an observable, and a fixed sleep is forbidden by this
codebase's e2e conventions. Every position assertion must either poll the computed delta
(`expect.poll`-shaped) with a timeout comfortably past the 500 ms backstop, **or** run in a
fixture with `prefers-reduced-motion: reduce` so the first align is instantaneous. State which
one each test uses; do not mix silently.

**Which click path — name it per case.** The row's visible label is itself a
`<button class="el-select el-row__label">` (`_element_row.html:62/114/173/225/278/329`), and the
row-body handler explicitly excludes `button, a, input, …`. So a default centre-of-box
`row.click()` lands on **either** path depending on layout, and the two differ materially: the
`.el-select` path (`editor.js:451`) destroys and rebuilds the preview, re-runs `libliInitTabs`,
and re-stamps `data-tabs-active` via `restoreActiveTabs` before the walk runs; the row-body path
(`editor.js:463`) does none of that. Every case must state which path it drives and target it
explicitly — `.el-row__label` for the `.el-select` path, a named non-button region for the
row-body path — and **at least one reveal case must run on each path**.

**Position-observability constraints (referenced by cases 6 and 8).** For a scroll assertion to
discriminate at all, the fixture must place the target **well below the pane fold** (several
viewport heights of preceding content) *and* carry enough content after it that `.pane-body` can
actually scroll it to the top; the case must assert pre-click that `y` is far from the content
top. Without the first, both builds read "already at the top"; without the second, the target can
never reach the top even on a correct build and the case goes falsely red.

**"The pane's content top"** means `.pane-body`'s rect top **plus its computed `padding-top`** —
`alignTopInPane`'s own arithmetic. Taking the bare bounding-box top instead is off by the pane's
padding, which can exceed the 4 px tolerance and turn a correct build red.

1. **Strip tabs** — child in a **non-first** tab; open the owning `<details>`; click the row;
   assert the preview switched tabs and the child is genuinely visible (non-zero box).
2. **Carousel tabs** — child in a non-first slide of a `display: "carousel"` tabs element; assert
   the reveal via a discriminating signal (below).
3. **Spoiler** — child inside a closed `<details>`; assert it opens.
4. **Before/after** — child in the After panel; assert the toggle flipped.
5. **Stacked ancestors** — kills mutants (e) and (f) together, which constrains the fixture
   tightly (see the mutant rationales): **two nested strip-mode tabs elements**; the **inner tabs
   element must itself sit in a non-first tab of the outer**; the target in a **late, non-first**
   tab of the **inner** one; and the inner tab strip **overflowing**. Assert both ancestors are
   revealed and `scrollLeft > 0` on the inner strip, preceded by a pre-flight assertion that the
   strip really overflows.

   **Scope the scroller selector to the inner instance** —
   `[data-tabs][data-tabs-eid="<inner pk>"] > .tabs__bar .tabs__scroller`. `scroller` is
   closure-local in `tabs.js`, so the test must query `.tabs__scroller`; and `initOne` does
   `container.insertBefore(bar, container.firstChild)`, so the **outer** instance's scroller comes
   **first** in DOM order and an unscoped `.first` reads the outer strip, whose `scrollLeft` is 0
   on both builds. Note this is the **reverse** of the dot ordering documented above (the
   carousel's `nav` is *appended* after `.tabs__stage`, so unscoped dots return the *inner*
   instance first) — reasoning by analogy from one to the other gets it backwards.
6. **Position** — the headline user value: the target's `bounding_box().y` is within **4 px** of
   the preview pane's content top (as defined above). Must satisfy the position-observability
   constraints above, or mutant (g) survives.
7. **Hover** — over an **always-visible** nested child (callout or two-column, which need no
   reveal): hover the nested editor row and assert `prev-el--hl` lands on the nested preview node.
8. **Degraded ancestor** — a **bailed** carousel nested inside a **closed spoiler**. Assert the
   spoiler still opens and the scroll still happens, i.e. the walk skipped the control-less
   carousel rather than throwing.

   **The scroll assertion is the discriminator, not the spoiler-open one.** Reveal runs
   outermost-first and the spoiler is the outer ancestor, so on the throwing (mutant i) build the
   spoiler has **already opened** before the inner carousel throws — that half passes on the
   broken build. So this case must satisfy the **position-observability constraints** above
   exactly as case 6 does; on a small fixture it reads "already at the top" on both builds and
   (i) survives.
   **Building the bail.** Both obvious mechanisms are dead ends and must not be substituted:
   `killOne` does `removeAttribute("hidden")` on **every** owned panel, so afterwards no
   `.ba__panel` carries `hidden`, the collection predicate never fires, and the walk never reaches
   the missing-control branch; and a single-slide carousel is **unreachable from data**
   (`TabsElement.MIN_TABS == 2`, `TabsElementForm.clean_data` rejects fewer, and `normalize_data`
   pads to 2 on the read side). Force the bail with a bad `window.TABS_I18N` key — the same
   injection `tabs.js`'s own error-bail e2e uses. The outer ancestor must be a **spoiler, not
   tabs**, because that injection is global and would bail an outer tabs instance too.
9. **Nested carousel** — the fixture for mutant (d), which no other case can kill: an **outer
   carousel** with the target in a **non-first slide**, containing an **inner carousel** in that
   slide with at least as many slides as the outer's target index (so a wrong-instance click
   lands somewhere rather than no-oping). Assert the **outer** container's `data-tabs-active`
   (scoped by its own `data-tabs-eid`) equals **the `data-tab-id` of the target section's own
   `[data-tab-panel]`** — that is what `show()` stamps (`ids[idx]`), a model-level tab id, not the
   `tabs-<eid>-<tid>-panel` DOM id used by the strip lookup. On the un-scoped build the
   `.tabs__dot` query returns the **inner** nav's dots first — the outer's `nav` is appended after
   `.tabs__stage` — so the outer never advances.
10. **Post-op reveal** (the `editor.js:367` path) — with the author looking at a *different* tab,
    save a nested element that lives in a non-first tab; assert the post-op `data-tabs-active` is
    the **operated element's** tab, not the author's previous one. This **pins the deliberate
    behaviour change** — the most user-visible side effect in the design — but note it is *not*
    what kills mutant (k); see below.
11. **Post-op reveal through a non-persistent ancestor** — the fixture for mutant (k): same
    `editor.js:367` path, but the nested element sits inside a **closed spoiler** (or a
    before/after flipped to After). Assert the ancestor is revealed **after** the op.

    A tabs ancestor cannot kill (k), because the tabs-persistence machinery launders the
    mutation: on the mutated build the walk runs against the *old* preview and `select()` stamps
    the target's tab there, and `applyFragments` **opens** with `captureActiveTabs()` — reading
    that just-mutated old pane — so `restoreActiveTabs` puts the target's tab on the rebuilt
    preview and `initOne` opens it. `data-tabs-active` and `aria-selected` end up byte-identical
    on both builds. A spoiler has no such carry (persistence is tabs-only, by decision), so a
    reveal performed on the pre-swap DOM is simply discarded and the mutant goes red.

#### Assertion traps that make a test vacuous

- **Never key the carousel assertion on visibility or geometry.** Inactive slides have intact
  rects and `opacity: 0`, which Playwright calls visible.
- **Assert the carousel positively, on the target only.** `show()` adds `is-active` to the
  incoming slide synchronously and sets `inert`/`aria-hidden` on the outgoing slide
  synchronously, but calls `settleHidden(out)` — which removes the outgoing `is-active` — only
  after `FADE_MS` (320 ms). So "exactly one `.is-active`" or "the previous slide lost
  `is-active`" is **flaky for 320 ms**. Assert instead that the **target's own** `.tabs__section`
  gains `is-active` and loses `inert`/`aria-hidden`, or read `data-tabs-active` on the owning
  `[data-tabs-eid]`. Any assertion about the outgoing slide's class during the fade is forbidden.
- **"The tab changed" needs a named observable, read at the right moment.** The durable signal is
  `data-tabs-active` on `[data-tabs][data-tabs-eid]` (scoped by `data-tabs-eid` to the right
  instance); the strip-only signal is `aria-selected` on `.tabs__tab`. Capture the "before" value
  **before the click** — `captureActiveTabs`/`restoreActiveTabs` re-stamp the pre-click tab onto
  the rebuilt preview, so it cannot be inferred from the post-swap DOM.

#### `prev-el--hl` is not a click-path assertion

Do **not** assert `prev-el--hl` after a click. That class is toggled only by `setHighlight`, bound
to `mouseenter`/`mouseleave` on `.el-row[data-element]`. On the `.el-select` path
(`editor.js:451`) `applyFragments` replaces **both** panes before `scrollPreviewTo` runs —
destroying the highlighted node — and `bindHover` re-binds to fresh rows that receive no new
`mouseenter` without pointer movement, so the class is absent. On the row-body path
(`editor.js:463`) there is no swap and a prior hover's class survives. Click cases assert reveal
+ position only; the hover class is asserted only by e2e 7, on the hover path.

### Named mutants that must go RED

| # | Mutant | Test that must fail |
|---|---|---|
| a1 | Drop the marker from **one** container template | render test 1 (hence: assert all five, not a sample) |
| a2 | Emit `data-element-id` but **not** the `prev-el` class | render test 1 (hence: assert the pair on one node) |
| b1 | Drop the **strip** reveal step | e2e 1 |
| b2 | Drop the **carousel** branch entirely (strip-mode-only implementation) | e2e 2 |
| b3 | Drop the spoiler `open = true` step | e2e 3 |
| b4 | Drop the before/after toggle step | e2e 4 |
| c1 | Drop the `{% if editor_preview %}` gate | render test 2 |
| c2 | Gate the **attribute** but not the **class** | render test 2 (hence: assert both halves absent) |
| d | Un-scope the tabs (dot) control lookup | e2e 9 |
| e | Reveal innermost-first instead of outermost-first | e2e 5 |
| f | Resolve each ancestor's node with `closest()` from the target | e2e 5 |
| g | Skip the scroll (reveal only) | e2e 6 |
| h | Scope `setHighlight` to top-level (`.prev-inner > .prev-el`) | e2e 7 |
| i | Throw instead of skip on a missing control | e2e 8 (the **scroll** assertion) |
| k | Run the walk **before** `applyFragments` on the post-op path | e2e **11** (the spoiler case — **not** e2e 10) |
| l | Add `display: block` to `.prev-el` | the CSS guard test |

Four requirements are deliberately **left uncovered** because they are unobservable, and are
labelled as such where they are stated, so no task is spent trying to falsify them:

- the `[data-scope="preview"]` **climb bound** — nothing collectible sits above it on today's page;
- the **synchronous-cascade ordering** — identical settled state, only the transient differs;
- un-scoping **`ownToggle`** — the container's own toggle wins any descendant query;
- un-scoping **`ownPanels`** — document order provably returns `C`'s own panel first (see
  "Own-scoping observability, before/after edition"). An earlier draft carried a mutant (j) and a
  nested-before/after e2e for this; both were **removed** once the document-order argument showed
  the mutant could not go red. Do not reinstate them.

Four of these need their rationale recorded, or the plan will substitute a cheaper fixture that
cannot kill them:

- **(d) must be pinned to a nested _carousel_.** A nested **strip** fixture stays green on the
  mutated build, because strip panel ids are globally unique (see "Where own-scoping is actually
  observable"), so the unscoped lookup finds the same button. Own-scoping is unobservable in
  strip mode.
- **(e) needs an overflowing inner strip _and_ a strip-mode outer.** The only geometry `select()`
  writes is `scroller.scrollLeft`, via `scrollIntoStrip`. On the broken (innermost-first) build
  every term is 0 and `scrollLeft` stays 0 — but on the **correct** build `scrollLeft` also stays
  0 unless the strip actually overflows *and* the target tab lies outside the visible range, so a
  default two-or-three-short-label fixture reads 0 on both builds. The target must also sit in a
  late, non-first tab, since `select()` early-returns on `i === active`. **The outer ancestor must
  be strip mode**: (e) depends on the outer *zeroing* the inner strip's geometry, which
  `display:none` does and a **carousel outer does not** — its inactive slides keep intact rects
  (absolutely positioned, `opacity: 0`), so `offsetLeft`/`clientWidth` are non-zero even on the
  broken build and (e) survives.
- **(f) needs two tabs ancestors, not a spoiler + tabs.** With one tabs ancestor,
  `target.closest(".tabs__section")` returns precisely the correct section and the mutant
  survives. This is why e2e 5's fixture is two nested strip-mode tabs elements rather than the
  simpler spoiler-outside variant — that fixture kills (e) but not (f).
- **(e) and (f) both additionally need the inner tabs element to sit in a _non-first_ tab of the
  outer.** `initOne` opens on tab 0, so if the inner element lives in the outer's first tab the
  outer conceals nothing: the inner strip is already visible and measurable, `scrollIntoStrip`
  sets `scrollLeft > 0` even on the innermost-first build, and "both ancestors revealed" passes
  trivially — (e) survives. The same fixture also lets (f) survive, because resolving the outer's
  node with `closest()` clicks the inner button while the outer is already on the correct tab, so
  the end states are indistinguishable. Pinning only the *target's* index within the inner element
  is not enough.
- **(b) was split into b1–b4** because a single all-or-nothing row let a strip-only implementation
  ship green — the exact silent failure this design identified in prose. One mutant per reveal
  step is what makes each individually tested.

### Visual verification

`.prev-el--hl` is an outset double ring (`0 0 0 3px` + `0 0 0 5px`, `editor.css:827-831`) that has
only ever been drawn on top-level `<section class="prev-el">` nodes owning the full prose column.
It will now be drawn on tightly-packed `.tabs__child` / `.twocolumn__child` / `.callout__child`
boxes, where an outset ring can collide with a neighbour or its container's edge.

Per this repo's standing convention for anything that renders: take **light and dark**
screenshots of a hovered nested child in at least a **two-column** and a **callout**, judge the
dark one on its own terms rather than assuming it follows the light one, and record the result in
the PR body.
