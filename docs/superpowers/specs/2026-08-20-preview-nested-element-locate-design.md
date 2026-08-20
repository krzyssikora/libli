# Locating nested elements in the unit editor's live preview

## Purpose

In the unit editor, clicking an element row scrolls the live preview to that element and
outlines it; hovering a row outlines it without scrolling. Today **this works for top-level
elements only.** Click a row for an element nested inside a tabs element, a two-column layout,
a spoiler, a callout or a before/after, and nothing happens at all — no scroll, no outline.

The reported symptom, in the author's words: *"if we have tabs with lots of content, we cannot
find out where the tab child is in the preview."*

This design makes the click/hover → preview sync work for elements at **every** nesting depth,
and — because three of the five containers keep some of their children hidden — makes the
preview **reveal** the container state needed to actually show the target.

### Root cause (verified, not inferred)

`templates/courses/manage/editor/_preview.html:28` is the **only** site in the codebase that
emits a preview marker:

```html
{% for el in preview_elements %}
  <section class="prev-el" data-element-id="{{ el.pk }}">{% render_element el ... %}</section>
{% endfor %}
```

`preview_elements` is the unit's **top-level** join rows only (`courses/views_manage.py:1854`
and `:1920`). Nested children are rendered *inside* `{% render_element %}`, by each container's
own student template, which wraps each child in a plain `<div class="<container>__child">`
carrying **no `data-element-id`**.

Both JS entry points look up that one marker:

- `courses/static/courses/js/editor.js:197` — `setHighlight(id, on)`, the hover outline
- `courses/static/courses/js/editor.js:237` — `scrollPreviewTo(id)`, the click scroll

```js
var sel = '.prev-el[data-element-id="' + id + '"]';
if (!root.querySelector(sel)) return;   // nested child -> always misses -> silent no-op
```

So this is **not** a broken lookup or a race. Nested elements are simply never labelled in the
preview DOM, and `scrollPreviewTo`'s explicit "absent -> no-op" early return swallows the miss.

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

- **Reveal gates** (`RevealGateElement`) can also hide preview content, but they hide
  *following siblings*, including top-level ones. That is a pre-existing, independent issue with
  a different shape; it is not part of this bug and must not be folded in.
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

The marker goes on **those existing divs** — add `data-element-id="{{ child.pk }}"` and the
`prev-el` class, both gated on `{% if editor_preview %}`.

Three properties make this the right seam:

1. **No new DOM node.** Existing CSS reaches *through* and *across* these wrappers —
   `.callout__children > .callout__child:first-child > :first-child`
   (`courses/static/courses/css/courses.css:1987`, plus `:1988`, `:1989`),
   `.el--tabs .tabs__child + .tabs__child` (`:1775`), and
   `.el--twocolumn > .twocolumn__column > .twocolumn__child + .twocolumn__child` (`:1911`).
   An inserted wrapper would break every one of them. Adding attributes to the existing div
   breaks none.

2. **`.prev-el` is layout-neutral.** `courses/static/courses/css/editor.css:826` declares only
   `border-radius` and a `box-shadow` transition; `.prev-el--hl` (`:827`) adds only a
   `box-shadow`. Critically, neither declares `display` — which matters because
   `courses.css:1982-1985` records that `.callout__child` must carry **no** `display`
   declaration, or `.callout__child[hidden]` has to join app.css's `[hidden]` guard for the
   reveal cascade's `gateWrap.hidden = true` to keep working. Adding `.prev-el` preserves that
   invariant. **The implementation must re-verify this holds rather than trusting this
   paragraph.**

3. **Reusing the `prev-el` class means part 1 needs zero JS and zero CSS change.** The existing
   `.prev-el[data-element-id="<id>"]` selector starts matching nested elements at every depth
   automatically, for both the hover and the click path.

#### Why `editor_preview` is available inside a container's children

The flag already propagates; this design does not add plumbing for it. The chain, which the
plan must **confirm rather than assume**:

- `courses/templatetags/courses_extras.py:160-176` — `render_element` builds a `page` dict and
  passes it **only** for `CONTAINER_MODELS`; `editor_preview` is one of its seven keys.
- `courses/models.py:471, 576, 679, 1936, 2060` — all five container `render()` methods spread
  `**(page or {})` into the child template context, `page` first so the container's own keys
  win.
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

Tabs render **all** panels into the DOM and hide the inactive ones; a collapsed spoiler
`<details>` and a before/after's off-side panel do the same. So part 1 alone marks a child in an
inactive tab, but `alignTopInPane` would then measure a hidden, zero-height node and the author
would see nothing — the reported complaint would remain.

One new function in `courses/static/courses/js/editor.js`, called from `scrollPreviewTo`
**before** the first align, walks up from the target and reveals each hiding ancestor:

| Ancestor | How it hides a child | Reveal |
|---|---|---|
| Spoiler | `<details>` closed | `details.open = true` |
| Tabs, **strip** mode | inactive panel gets the `hidden` attribute | from `closest("[data-tab-panel]")` read its `id`, then click `[aria-controls="<id>"]` |
| Tabs, **carousel** mode | rest slides get `inert` + `aria-hidden` | index of `closest(".tabs__section")` among its own container's sections, then click the matching own `.tabs__dot` |
| Before/after | `.ba__panel[hidden]` | click the container's toggle |

Four facts shape this:

- **Tabs has two display modes.** `courses/static/courses/js/tabs.js:83` returns **early** into
  `initCarousel` when `data-display === "carousel"`. The carousel branch builds no
  `aria-controls` tab buttons at all — its dots are **index-keyed** (`tabs.js:489-497`, one
  `.tabs__dot` per section, each closing over `show(k)`). A single strip-mode-only
  implementation silently does nothing for every carousel.
- **The controls must be own-scoped.** Since the depth-3 lift, a tabs element may legally
  contain **another** tabs element. `tabs.js:33-43` documents this at length and `tabs.js:44-62`
  implements `ownSections()` / `ownPart()` against it. A descendant-wide `querySelector` from
  an outer container grabs the *inner* instance's controls, and activating one of those hides
  the outer panel that contains it — the element goes blank. Every lookup in the walk must
  reject nodes owned by a nested instance the same way.
- **Drive the real control, not the internals.** `tabs.js`'s `select(n)` / `show(n)` are
  closure-local and not exported. Clicking the actual button is both the only available route
  and the more honest one — and it earns persistence for free: `select()` stamps
  `data-tabs-active` on the container (`tabs.js:167`), which `editor.js` already carries across
  fragment swaps. That attribute exists precisely because closure state cannot survive the
  preview being replaced wholesale after every save.
- **No new timing machinery.** The carousel fades over `FADE_MS = 320` (`tabs.js:17`) and then
  re-measures. `scrollPreviewTo` already re-aligns on a `requestAnimationFrame`, on every
  `img`/`iframe` load, and once more at 500 ms (`editor.js:249`). The plan must **confirm** the
  existing 500 ms re-align covers the 320 ms fade rather than adding a `setTimeout`.

The walk should also confirm that `alignTopInPane`'s `el.closest(".pane-body")`
(`editor.js:215`) still resolves for a deeply nested target — it should, since `.pane-body` is a
preview-pane ancestor of everything in the preview, but it is one line to check and a silent
`return` if wrong.

## Data flow

**Server render (part 1).** Editor view → `_preview.html` loops top-level `preview_elements`,
wrapping each in `.prev-el[data-element-id]` and calling `render_element(..., editor_preview=True)`
→ `render_element` puts `editor_preview` into the `page` dict for containers → the container's
`render()` spreads `page` into its child template context → the container template emits
`<div class="<c>__child prev-el" data-element-id="<child.pk>">` and calls `{% render_element child %}`
→ that call re-reads `editor_preview` from context, so the recursion carries the flag down
arbitrarily far.

On the **student** page `editor_preview` is falsy, so every `{% if editor_preview %}` is skipped
and the emitted HTML is byte-identical to today's.

**Client (parts 1 + 2).** Author clicks an editor row → the existing handler calls
`scrollPreviewTo(id)` → the selector now matches a nested child → the new walk reveals each
hiding ancestor from the target upward → `alignTopInPane` scrolls only `.pane-body` → the
existing re-aligns settle the position as async content and the carousel fade land.
`setHighlight` needs no change at all: the same selector now matches, so hover outlines nested
elements as a side effect of part 1.

## Error handling

- **Target absent** (deleted element, failed swap): `scrollPreviewTo`'s existing early return
  stands. The walk must run **after** that guard, never before, so it is never handed `null`.
- **No hiding ancestor**: the walk is a no-op. A child in a callout or a two-column is always
  visible; part 1 alone is sufficient there.
- **Missing control**: if a tab button, dot, or before/after toggle cannot be found, the walk
  must skip that ancestor and continue up rather than throw — a throw would abort the whole
  click handler and lose the scroll that part 1 already earned.
- **Already-revealed ancestor**: clicking the already-active tab is harmless — `select()` returns
  early on `i === active` (`tabs.js:163`). The before/after step must check for the `hidden`
  attribute before clicking, or it would toggle a visible panel *away*.
- **No-JS / failed enhancement**: `tabs.js` has a `bail()` path that strips enhancement on a
  throw. With no tab controls present, the walk finds none and skips — the panels are all
  visible in that state anyway.

## Testing

This repo requires **falsification**, not merely green runs: each test is justified by the
mutant it kills.

### Server-side render tests

1. Nested children carry `data-element-id` in the **editor preview** at depth 2 **and** depth 3,
   across **all five** containers.
2. Nested children carry **no** `data-element-id` on the **student** page — this is what proves
   the `editor_preview` gate, and it is the only assertion that can catch the gate being dropped.

**Scoping is mandatory and load-bearing.** The editor pane *also* uses `data-element-id` — on the
`el-act-edit` buttons in `_element_row.html` — so a bare substring assertion against the whole
page passes vacuously on a broken build. Every assertion must be scoped to the preview pane
(slice from `data-scope="preview"`), exactly the "a card above a list shadows its assertions"
trap this codebase has hit before.

### e2e

The author's real scenario, driving real UI: seed a child into a **non-first** tab, click that
child's editor row, and assert that the preview **switched tabs** and that the child ends up
outlined (`prev-el--hl`) and in view.

Seeding into a non-first tab is not incidental — a final-state-only assertion would pass on the
broken build whenever the target tab happened to already be active. The test must assert the tab
**changed**, not merely that it ends up correct.

### Named mutants that must go RED

| # | Mutant | Test that must fail |
|---|---|---|
| a | Drop the marker from **one** container template | the render test (hence: assert all five, not a sample) |
| b | Drop the reveal walk | the e2e — the child stays hidden |
| c | Drop the `{% if editor_preview %}` gate | the student-page test |
| d | Un-scope the tabs control lookup (remove own-scoping) | a **nested-tabs** test — a tabs element inside a tabs element |

Mutant (d) is the reason a nested-tabs case must exist in the suite at all: without it, the
own-scoping requirement is untested and a descendant-wide lookup ships green.
