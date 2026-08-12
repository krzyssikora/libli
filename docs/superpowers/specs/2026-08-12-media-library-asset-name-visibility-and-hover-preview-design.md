# Media library: asset name visibility and hover preview

Date: 2026-08-12

## Purpose

In the course media manager grid, assets whose names differ only in a numeric
suffix (`przykladowa_parabola_0_1.png`, `przykladowa_parabola_0_2.png`) cannot
be told apart. Two independent causes, plus one irritant:

1. **The name spills out of the card.** `.asset-dname`
   (`courses/static/courses/css/editor.css:720`) carries no truncation rule at
   all — no `overflow`, no `text-overflow`, no `white-space`, and no
   `overflow-wrap`. It is a flex item inside `.asset-names`
   (`editor.css:719`, `flex-wrap: wrap`), and a flex item's automatic minimum
   size refuses to shrink below its content's min-content width. A filename with
   no soft-wrap opportunity has a min-content width equal to the entire string.
   The span therefore overflows its card and the neighbouring card's
   `--surface-raised` background paints over the overflow. The last card in a
   row shows its full name because nothing sits to its right — that asymmetry is
   the tell. The text is not being truncated; it is being covered.

2. **The thumbnail crops.** `.asset-thumb` uses `object-fit: cover` at
   `aspect-ratio: 4 / 3` (`editor.css:360-365`). When the only difference
   between two images lies outside that crop, the thumbnails are identical
   pixel-for-pixel and no name fix can help.

3. **The name is printed twice.** `_asset_cell.html:12` renders
   `asset.display_name` and `:15` renders `asset.original_filename`, but
   `display_name` is `self.name or self.original_filename`
   (`courses/models.py:754-756`). For any asset that was never renamed the card
   prints the same string on both lines.

**Success criteria.** A user scanning a row of similarly-named assets can (a)
read the *differing* region of each name inside the card without hovering, (b)
get the exact full name on hover, and (c) see a crop-free enlargement of any
image without leaving the grid.

**Scope.** The manager grid cell
(`templates/courses/manage/media/_asset_cell.html`), the manager-only CSS
classes `.asset-names` / `.asset-dname` / `.asset-fname`, one seed-value fix in
`media_picker.js`, and a new preview module. The manager template's
`<img class="asset-thumb">` gains a data attribute; `_picker_grid.html:6`
renders its own independent `<img class="asset-thumb">` and is untouched, so no
shared CSS class is modified and the picker's rendering is unchanged. Out of
scope: thumbnail generation, the picker grid, and the `cursor: pointer` on a
non-clickable manager cell.

## Architecture / components

Five components, each independently testable.

### 1. `middle_truncate` template filter

New filter in `courses/templatetags/courses_manage_extras.py` (the existing home
for manage-side filters — `register = template.Library()` at `:26`). Needs a new
import, `from django.template.defaultfilters import stringfilter`, and the
decorator order is load-bearing: `@register.filter` outermost, `@stringfilter`
innermost, so a lazy or non-string value is coerced before `len()` is taken. The
return value is **not** marked safe: the input is user-supplied and must stay
auto-escaped.

Signature: `middle_truncate(value, budget=38)` → `str`.

Algorithm, in order:

- Clamp `budget = max(budget, 0)` at entry. A negative budget is a caller error;
  clamping keeps the length invariant total rather than letting `value[:budget]`
  return `len(value) + budget` characters.
- If `len(value) <= budget`, return `value` unchanged.
- Let `tail = 14` and `head = budget - 1 - tail` (the `1` is the ellipsis).
- If `head >= 1` (i.e. `budget >= 16`), return
  `value[:head] + "…" + value[-tail:]`.
- Otherwise (`budget <= 15`, so a middle truncation cannot preserve both ends)
  fall back to plain end-truncation: return `value[: budget - 1] + "…"` when
  `budget >= 2`, and `value[:budget]` when `budget < 2`.

**Invariant:** for any `budget >= 0`, the return value is never longer than
`budget`.

**Budget derivation.** This derivation is against the grid's *theoretical*
column minimum of 128 px (`repeat(auto-fill, minmax(8rem, 1fr))`,
`editor.css:350`), where the cell's content box is ~110 px after
`var(--space-2)` padding and the 1 px border. With `.asset-dname` set to
`flex: 1 1 0` (§3) the ✎ button shares only the **first** flex line, costing it
~30 px including the 4 px gap: line 1 holds ~11 characters at `.9rem`/600, lines
2 and 3 hold ~15 each. Capacity across three lines is therefore ~41 characters
*for typical filename glyphs*, and the budget of 38 sits inside that with
margin. A 14-character tail covers a numeric suffix plus a four-character
extension with room to spare. The reported case
(`przykladowa_parabola_0_2.png`, 28 characters) is under budget and renders
untouched.

**The derivation width is not the width the tests measure.** `minmax(8rem, 1fr)`
makes 128 px a *floor*, not the rendered width: at a 360 px viewport `auto-fill`
fits two columns and `1fr` distributes the remainder, so each card is
substantially wider than 128 px. (The docstring at
`tests/test_e2e_media_manager.py:594-596` claims 360 px "pins columns at the
128px minimum"; that claim is wrong and is inherited here, not invented.)
Implementation must **measure** the rendered card width at 360 px. The
38-character budget is deliberately conservative and does not depend on that
measurement, but the clamp does — see "The clamp may not survive measurement"
below.

Truncation slices by **code point**, not grapheme cluster. A name whose elision
boundary falls inside a combining sequence or an emoji ZWJ cluster may render a
broken glyph; grapheme-aware slicing is out of scope, and the `title` attribute
and the preview caption both carry the intact name.

**Accepted limitations.** Two, both falling back on criterion (b):

- Two over-budget names differing only *inside* the elided middle truncate to
  identical strings. Criterion (a) is conditional on the difference lying
  outside the elision — which holds for the reported numeric-suffix case, since
  the tail is preserved.
- **If the 3-line clamp engages, the tail is lost.** `-webkit-line-clamp`
  truncates at the end of the third line and appends its own ellipsis, removing
  exactly the suffix `middle_truncate` reserved 14 characters to protect. For
  such a name criterion (a) fails and only the `title` and the preview caption
  recover it.

**The clamp may not survive measurement.** The clamp can only ever engage on a
name that is *within* budget (≤ 38 characters — anything longer is shortened by
the filter first) yet still overflows three lines at the rendered card width. At
the measured 360 px width that margin is thin. Implementation must determine
whether such a name exists:

- If it does, the clamp stays and its test row uses that name.
- If it does not, the clamp is **unreachable in production as well as in test**.
  Delete the `-webkit-line-clamp: 3` declaration and its test row rather than
  shipping an unfalsifiable rule — and keep `overflow: hidden`, which is doing
  separate work (§3). The second accepted limitation above then drops with it.

### 2. Card markup — `_asset_cell.html`

- `:1` becomes `{% load i18n courses_manage_extras %}`. Without it the template
  raises `TemplateSyntaxError: Invalid filter` on every manager render and every
  replace / rename / upload fragment — `courses_manage_extras` is not a
  configured template builtin, and the only other consumer
  (`_link_picker_node.html:1`) carries its own explicit load. `{% load %}`
  renders nothing, so it does not trip
  `test_no_template_comment_leaks_into_the_asset_cell`.
- `:12` gains `title="{{ asset.display_name }}"` and renders
  `{{ asset.display_name|middle_truncate }}`. The `title` carries the **full,
  untruncated** name, so the tooltip is always a superset of the visible text.
- `:15` (`.asset-fname`) renders only when
  `asset.original_filename != asset.display_name`, and gains
  `title="{{ asset.original_filename }}"`. That line is CSS-ellipsised
  (`editor.css:721`, `white-space: nowrap`), and for a renamed asset it is the
  only place the real file identity appears — without the `title` the exact
  filename would be unobtainable anywhere in the UI.
- `:7` (the `<img class="asset-thumb">` branch only) gains `data-asset-preview`
  as the preview module's hook. The
  `<span class="asset-thumb asset-thumb--video">` branch at `:9` does not.

Any commentary added to this template must be a single-line `{# … #}` that
Django strips — see the constraint under Testing.

### 3. Card CSS — `editor.css`

`.asset-dname` gains three things:

- `overflow-wrap: anywhere` and `overflow: hidden` — **either one alone
  collapses the flex automatic minimum size**, and the pair is retained because
  each also does separate work. `overflow: hidden` makes the span a scroll
  container, whose automatic minimum size is zero per CSS Flexbox §4.5.
  `overflow-wrap: anywhere` introduces soft-wrap opportunities that *are*
  counted in min-content intrinsic sizing (unlike `word-break: break-word`), so
  it collapses the minimum too. Beyond containment: `overflow: hidden` is
  required for `-webkit-line-clamp` to clip at all, and `overflow-wrap:
  anywhere` is what makes the string wrap across three lines instead of
  rendering as a single line cut off after ~11 characters, losing the tail that
  `middle_truncate` exists to preserve. **Because either alone suffices for
  containment, the containment test's mutant must drop both** (see Testing).
- `display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3` —
  bounds the card's height for a within-budget name whose glyphs are wider than
  the derivation assumes, subject to §1's "may not survive measurement".
- `flex: 1 1 0` — **this is what keeps the ✎ button on the first line.** Flex
  line breaking happens before shrinking and uses each item's *hypothetical*
  main size; with the default `flex-basis: auto` that is the max-content width
  of the whole filename, which exceeds the line on exactly the long names this
  feature targets, pushing the button onto flex line 2. `flex-basis: 0` makes
  the hypothetical size 0. `flex-grow: 1` is not optional alongside it — with
  basis 0 and no grow the span would be zero-width and the name invisible.

`min-width: 0` is deliberately **not** added: it would change nothing observable
alongside either rule above and could not be independently falsified.

`.asset-names` changes `align-items: center` → `align-items: start`, so the ✎
button aligns to the top of the first line rather than to the vertical middle of
a three-line name block.

**Visible consequence for every card, not just long-named ones.** `flex-grow: 1`
makes the name span absorb all free space on line 1, so the ✎ button moves from
sitting immediately after the name to the card's right edge — on short-named
assets too. This is intended and unavoidable given the basis-0 requirement
above. Note that the button is `opacity: 0` until its cell is hovered
(`editor.css:725-726`), so this repositioning is only *visible* on a hovered
cell — which constrains both the screenshot pass and the alignment test (see
Testing).

**Divergence from the picker, deliberately.** `.asset-name` (`editor.css:366`,
picker-only) uses `word-break: break-word` for the same class of problem. The
new rule set is not converged with it — the picker is out of scope and does not
clamp.

### 4. Rename seed fix — `media_picker.js`

**This is a correctness fix, not a nicety.** `media_picker.js:338` seeds the
rename input with `input.value = dname.textContent.trim()`, and `:375` commits
on `blur`. Once the span renders a middle-truncated string, clicking ✎ and then
clicking anywhere else writes `head…tail` into `MediaAsset.name` as a permanent
custom name, after which `display_name` returns the ellipsised string forever.

The seed becomes `cell.getAttribute("data-name").trim()` — reading the
untruncated name from the cell root (`_asset_cell.html:3`) and **keeping** the
`.trim()` the old seed applied, so a stored name with stray whitespace still
seeds cleanly. There is **no `textContent` fallback**: `data-name` is
unconditional in the template and every render path goes through it, so a
fallback would be unreachable dead code that — if it ever *were* reached —
would reintroduce precisely this bug.

No other change to the rename flow is needed: it reinserts the **same span
node** on cancel (`:344`), on a non-200 (`:351`), and on network failure
(`:367`), so the server-rendered `title` survives all three; the success path
replaces the whole cell with fresh server HTML (`:363`), which carries every
attribute natively.

### 5. Hover preview — new `media_preview.js`

**Why not `imagezoom.js`.** `courses/static/courses/js/imagezoom.js` already
implements a single reused overlay for enlarging an image: `[data-zoomable]`
arming, a modal `<dialog>` with `showModal()` feature detection, an
`IMAGEZOOM_I18N` blob with fallbacks, a `tabindex="-1"` focus holder,
capture-phase Escape arbitration against `unit_nav.js`, and an
`html.imgzoom-open` scroll lock. Arming `.asset-thumb` as `[data-zoomable]`
would deliver criterion (c) with no new overlay code.

It is not used here because the interaction is wrong for the task. The goal is
*scanning* a row of near-identical thumbnails; a modal costs a click to open,
Escape to dismiss, and a click to open the next, and it blocks the grid behind
it while open. A non-modal hover preview compares six cards in one pointer
sweep. Choosing non-modal also means the new module does **not** re-implement
imagezoom's modal machinery — no `showModal`, no scroll lock, no focus trap, no
Escape-capture arbitration. What it does carry over: reuse the already-fetched
URL, and a deliberate `alt`.

**File and wiring.** `courses/static/courses/js/media_preview.js`, loaded from
`manager.html`'s `{% block extra_js %}` (`:59`) alongside `media_picker.js` and
with the same `defer` attribute — without `defer` the delegated listeners would
bind before `.media-manager` exists and the module would be silently dead. The
module returns early when `.media-manager` is absent. It is a separate file
rather than an addition to `media_picker.js` because it shares no state with the
picker's upload / replace / rename / filter flows and `media_picker.js` is
already the manager's largest script.

**The overlay element.** One singleton, created on first use, appended to
`document.body` and kept there for the page's lifetime. Structure:
`div.asset-preview[aria-hidden="true"]` containing
`img[data-asset-preview-img]` and `div.asset-preview__caption`. **Closed state
is the `hidden` attribute** on the root, so tests can wait on an exact
`state="hidden"` / `state="visible"` transition and read the image through
`[data-asset-preview-img]`.

> `.asset-preview[hidden] { display: none; }` is **required** and must be stated
> before the `display: flex` declaration. `[hidden] { display: none }` comes
> from the UA stylesheet and any author `display` beats it, so without this rule
> the overlay is permanently visible from creation. The same file already ships
> `.math-modal[hidden] { display: none; }` (`editor.css:806`) and a
> `.picker__panel[hidden]` twin for exactly this reason — it is not redundant.

**Trigger, and how it survives DOM churn.** `mouseenter` / `mouseleave` do
**not** bubble, so they cannot be delegated — and the manager replaces cells and
grids constantly (`insertCell` after upload, `cell.replaceWith(fresh)` after
rename and replace, `oldGrid.replaceWith(newGrid)` on every debounced filter).
Per-node listeners bound at load would therefore go silently dead on every
swapped-in cell. The module instead delegates the bubbling **`mouseover` /
`mouseout`** pair on the `.media-manager` root, resolving the anchor with
`e.target.closest("[data-asset-preview]")` and ignoring intra-anchor transitions
by checking whether `e.relatedTarget` is contained by the same anchor. No arming
pass and no per-cell listener exists, so a cell inserted at any later moment
works identically to one rendered at load.

Opening waits out a dwell of **exactly 250 ms**, so that sweeping a row does not
strobe. A `mouseover` on an anchor whose timer is already pending is a no-op
(the timer is **not** restarted); a `mouseover` on the already-open anchor is
also a no-op. Leaving the anchor hides immediately and cancels a pending open.
Anchoring to the thumbnail rather than the whole cell keeps the image preview
and the name's native `title` tooltip on disjoint hover targets, so the two
never stack.

The module tracks the currently-hovered anchor in a module-level `hoveredAnchor`
variable, set on `mouseover` and cleared on `mouseout` **and** in the
`MutationObserver` teardown — not `anchor.matches(":hover")`, which is also true
for ancestors and can be stale immediately after a DOM swap.

**Pointer gate.** The `mouseover` / `mouseout` path is armed only when
`matchMedia("(hover: hover) and (pointer: fine)")` matches, evaluated **once at
load** (no `change` listener — a pointing device appearing mid-session is not
worth the complexity). On touch a tap synthesises hover events with no matching
leave, which would strand the overlay over the grid. The **focus path is armed
unconditionally** — a keyboard attached to a touch-first device is a real
configuration, and nothing about the touch failure mode applies to it.

**Keyboard.** The manager cell is a `div` and is not focusable, and giving each
card a tab stop would add a fourth to the three buttons it already holds. The
overlay therefore opens on `focusin` within a cell that contains a
`[data-asset-preview]` — so tabbing to ✎ / ⇄ / 🗑 surfaces the preview at no
extra cost — and closes on `focusout`. The focus path opens **immediately, with
no dwell**, and cancels any pending pointer-dwell timer. Two exclusions, both
"do not sit over the control the user is operating":

- `focusin` whose target is `.asset-rename-input` is ignored.
- `focusin` originating inside `[data-replace-strip]` is ignored. The replace
  flow focuses `[data-replace-commit]` the moment the strip appears
  (`media_picker.js:461`, asserted at `tests/test_e2e_media_manager.py:124`),
  and the strip renders inside the cell (`cell.appendChild(strip)`) — so without
  this every ⇄ click would raise the overlay over the confirm prompt.

Ignoring the `focusin` is not sufficient on its own, because the ✎ / ⇄ button
that *precedes* the insertion has already opened the overlay via its own
`focusin`. The `MutationObserver` below therefore also closes the overlay when a
`.asset-rename-input` or a `[data-replace-strip]` appears anywhere under
`.media-manager`.

**Escape.** Bound on `document` in the **bubble** phase, **only while the
overlay is open**, and it must not call `preventDefault()` or
`stopPropagation()`. `media_picker.js:371-373` already handles Escape on the
rename input to cancel; swallowing the key would be a latent regression. This is
deliberately not the capture-phase arbitration `imagezoom.js` needs, because a
non-modal overlay has no claim to exclusivity.

After an Escape the overlay stays closed until the pointer leaves the anchor and
returns — no suppression flag is needed, and none is kept. `mouseover` fires on
*entering* an element, so a stationary pointer inside the anchor generates no
further events and nothing can reopen the overlay on its own. A flag guarding
against that would be provably inert.

**Content and the actual un-crop mechanism.** The crop comes from
`.asset-thumb`'s own `aspect-ratio: 4 / 3` + `object-fit: cover`
(`editor.css:360-364`). The overlay's image is a *separate* element that simply
does not carry those declarations — **that**, not any property on the overlay
image, is what shows the full frame. `object-fit: contain` on the overlay image
is meaningful only in combination with the explicit box below (a replaced
element with both dimensions constrained); it is declared for that case and is
otherwise inert. A source smaller than the box **is** upscaled — the preview's
job is to un-crop, not to add detail. The caption is `display_name` (read from
the cell root's `data-name`) — for a renamed asset that is the custom name, not
the file's name; the card's own `.asset-fname` line, now carrying its own
`title`, is where the original filename is readable.

**Sizing.** Three rules, because a `max-height` on the container does not bound
its children — a portrait source at `width: 100%` of a 320 px box would
otherwise render thousands of pixels tall and overflow:

- `.asset-preview`: `position: fixed`, `z-index: 60`,
  `max-width: min(320px, calc(100vw - 16px))`,
  `max-height: calc(100vh - 16px)`, `overflow: hidden`, `display: flex` in
  column direction (after the `[hidden]` rule above).
- `[data-asset-preview-img]`: `max-width: 100%`, `min-height: 0`,
  `flex: 0 1 auto`, so the image yields to the caption and the padding and can
  never exceed the container's remaining height.
- `.asset-preview__caption`: `overflow-wrap: anywhere` and free to wrap to
  multiple lines within the container's height budget. A filename has no
  soft-wrap opportunities, so without this the caption renders one unbreakable
  line and `overflow: hidden` clips the very tail the caption exists to recover.

**Placement.** All measurement happens **after** the `hidden` attribute is
removed — a `display: none` element has no box and `getBoundingClientRect()`
returns zeros, which would make every "does it fit?" test compare against width
0 and always answer yes. The sequence is: populate → remove `hidden` with
`visibility: hidden` → measure → position → restore `visibility`. Placement is
then recomputed on the overlay image's `load` event, because assigning `src`
does not synchronously give a cached image its `naturalHeight`, so the first
measurement sees a caption-only box.

- Gap between the overlay and the card: **8 px**.
- "Fits on the right" means
  `viewportWidth - cardRect.right - 8 >= overlayWidth`; "fits on the left" is
  the mirror. Below/above use the same inequality on the vertical axis.
- Order: right, left, below, above, then centred in the viewport when none fit
  — the operative case at 360 px, where neither side has room.
- On the perpendicular axis the overlay is top-aligned with the card (for
  left/right) or left-aligned (for above/below), then **clamped** into the
  viewport with an 8 px margin, so a card near an edge cannot push the overlay
  off-screen.
- Centring is `left`/`top` computed from the measured box, not `margin: auto` —
  the element is `position: fixed` with no `inset`.

**Containing block.** Appended to `document.body`, not to `.media-manager`, so
that `position: fixed` resolves against the viewport. Any ancestor with
`transform`, `filter`, `backdrop-filter`, `will-change` or `contain` would
otherwise silently become the containing block.

**Surface.** Theme tokens, so light and dark both resolve without a second rule
set: `background: var(--surface-raised)`,
`border: 1px solid var(--border-default)`, `border-radius: var(--radius-md)`,
`box-shadow: var(--shadow-lg)`, padding `var(--space-2)`, caption at `.72rem` in
`var(--text-secondary)`. `z-index: 60` is defensive headroom above the
codebase's existing overlay tier (`.picker-overlay` at 50, `editor.css:378`) and
below the modal tier (`.math-modal` at 1000, `:807`); neither shares a page with
the manager, so this is a convention choice, not an ordering against a
coexisting surface.

**`pointer-events: none`** on the overlay. It necessarily covers the
neighbouring grid cell; without this, sweeping right would fire `mouseout` then
`mouseover` on the same anchor in a strobe loop, and the covered neighbour could
never be hovered.

**Accessibility.** `.asset-preview` carries `aria-hidden="true"`: it is a purely
visual redundancy of text already present in the cell, appended at the end of
`<body>`, and announcing it would give a screen-reader user an orphaned
duplicate of a name they have already heard.

**Accepted WCAG limitation.** SC 1.4.13 (Content on Hover or Focus) requires
author-built hover content to be dismissible, hoverable and persistent. This
overlay is dismissible (Escape) and persistent, but `pointer-events: none` makes
it **not hoverable** — the pointer can never move onto it. That is a deliberate
trade against the strobe loop above and the fact that the overlay's content is
inert (no links, no text worth selecting). Recorded here so it is a known,
reasoned gap rather than an oversight.

**Images only.** A video cell is a ▶ glyph (`_asset_cell.html:9`) and carries no
`[data-asset-preview]` hook.

**No new request.** The overlay reuses the thumbnail's own `currentSrc`, so the
browser serves it from cache.

**No translatable strings.** The overlay's image is decorative relative to its
own caption and uses `alt=""`; the caption is the asset name, which is data, not
UI copy. Nothing is added to the `data-msg-*` channel on `.media-manager`
(`manager.html:10-16`) and no catalog regeneration follows.

## Data flow

**Render.** `manage_media` view → `_asset_grid.html` → one `_asset_cell.html`
per asset. `asset.display_name` (model property, `courses/models.py:754`) flows
into three places: the `title` attribute (full), the visible span body (via
`middle_truncate`), and the pre-existing `data-name` attribute on the cell root
(`:3`, full). `asset.original_filename` flows into `.asset-fname` — both its
body and its `title` — only when it differs from `display_name`.

**Hover.** `mouseover` on `.media-manager` → `closest("[data-asset-preview]")`
→ `relatedTarget` containment check → set `hoveredAnchor` → 250 ms dwell → read
the thumbnail's `currentSrc` and the cell root's `data-name` → populate → remove
`hidden` (invisible) → measure → place → reveal → reposition on the image's
`load`. `mouseout` to outside the anchor / `focusout` / Escape / scroll / resize
/ anchor-detach / rename-input or replace-strip insertion → restore `hidden`.

**Rename.** ✎ swaps `[data-asset-dname]` for an input
(`media_picker.js:335-339`) seeded from `data-name` (§4), and reinserts the same
span node on cancel, on a non-200, and on network failure; the success path
re-renders the whole cell from the server.

## Error handling

- **Overlay outlives its anchor.** The overlay lives on `document.body`, so it
  survives the events that destroy the cell that opened it. The module observes
  these with a `MutationObserver` on the `.media-manager` root
  (`childList: true, subtree: true`), **connected only while the overlay is
  open** and disconnected on close. Its callback closes the overlay when either
  is true: the stored anchor node's `isConnected` is false (and then also clears
  `hoveredAnchor`), or a `.asset-rename-input` or `[data-replace-strip]` has
  appeared anywhere under the root. The detach check keys on the anchor
  **node**, never on a selector — a selector-keyed guard is a no-op when the
  event is a node replacement. This observer is for teardown only; arming needs
  none, because the trigger is delegated (§5). No change to `media_picker.js`
  is required for either.
- **Scroll and resize.** A `fixed`-positioned overlay anchored to a moving card
  detaches visually, and a resize also re-flows the auto-fill grid and moves
  every card. Both close the overlay. The scroll listener is
  `document.addEventListener("scroll", …, { capture: true, passive: true })` —
  `scroll` does not bubble from element scrollers to `window`, and capture is
  what catches an inner scroller such as an expanded `.asset-uses-list`. Both
  are bound only while the overlay is open.
- **Broken or missing image.** Two distinct cases, both ending in the same
  caption-only state with the `<img>` hidden and no empty box:
  - The overlay's own load fails → its `error` event.
  - The *thumbnail* already failed, so there is nothing to copy. Guard before
    assigning: if `currentSrc` (falling back to `getAttribute("src")`) is empty,
    or the anchor is `complete && naturalWidth === 0`, go straight to
    caption-only without touching `src`. Assigning `""` to `src` does not
    reliably fire `error` and can leave the previous image in place.
- **Degenerate truncation inputs.** `middle_truncate` handles a value shorter
  than the tail length, a value with no extension, a non-ASCII value, a `budget`
  at or below `tail + 1` (the end-truncation fallback in §1) and a negative
  `budget` (clamped at entry) without raising.
- **No JS.** With scripts disabled the wrapped name, the middle truncation and
  both `title` tooltips still work; only the preview is lost.

## Testing

**Unit — `middle_truncate`.** Value shorter than `budget` returned unchanged;
value at exactly `budget` returned unchanged; over-budget value keeps both the
extension and the tail; over-budget value's result length equals `budget`;
`budget = 16` (the first middle-truncating budget — expects a 1-character head,
the ellipsis, and a 14-character tail); `budget = 15` (the last fallback budget
— expects end-truncation); `budget = 1`; `budget = -5` (clamped, returns `""`);
a value with no extension; a non-ASCII value; and a value shorter than the tail
length **with an explicit small budget** (e.g. `budget=5, value="ab.png"`) so it
actually reaches the fallback branch — at the default budget that case exits at
the first guard and exercises nothing new.

**Django client — `_asset_cell.html`.** `title=` present on `.asset-dname` and
carrying the **full** name while the visible text is truncated (assert both, on
one over-budget asset); `.asset-fname` present with its own
`title="<original_filename>"` when `original_filename` differs from
`display_name`, and absent when they match; `data-asset-preview` present on an
image asset's thumb and absent on a video asset's.

### e2e — measured, not eyeballed

A CSS assertion made with the rule in place proves nothing, so each row below is
falsified against its mutant before it is believed.

**Probe rule.** `inner_text()` is **not** an acceptable probe for the geometry
rows: it reports the same string whether the text is painted inside the card or
clipped away, so an assertion built on it passes on a build where the text is
invisible. Those rows use `document.createRange()` over the `.asset-dname` text
node and `getClientRects()`. Note precisely what that buys: `getClientRects()`
reports **laid-out geometry and is equally unaffected by ancestor clipping** —
it is the right probe here because the failure modes change the rects'
*position* and their *count*, not because it measures clipping.

**Overlay assertions must be waits, never immediate reads.** The dwell is
250 ms, so a `page.evaluate` fired straight after `hover()` reads the closed
state. Use `expect(...).to_be_visible()` / `wait_for_selector(state=...)`.

**Fixture scoping is load-bearing.** If the clamp survives measurement (§1), its
fixture's text deliberately exceeds three lines, so its clamped-away runs lay
out below the card's clipped bottom edge. It must be seeded on its **own**
page/test, never alongside the containment fixtures — otherwise the containment
row goes red on a correct build. The containment rows use a name that is under
budget and wraps within three lines.

**Two constraints on the clamp fixture,** if it exists: long enough to exceed
three lines at the *measured* card width, and ≤ 38 characters so
`middle_truncate` leaves it intact — otherwise the filter shortens it first and
the rect count is decided by the budget on both builds. The test asserts the
rendered text length equals the source length, so a later budget change fails
loudly instead of silently defusing the row.

**Unverified premise, to settle before writing the clamp row.** Whether Blink
removes clamped lines from the layout tree (so `getClientRects()` returns 3) or
lays them out and merely clips the paint (so it returns 4+ on *both* builds, and
the row is unfalsifiable) is engine behaviour this spec asserts rather than
knows. Run a one-off spike against both builds first. If rects do not
discriminate, fall back to `scrollHeight > clientHeight` on the span.

| Test | Mutant that must turn it red |
| --- | --- |
| At 360 px, every text-run rect of `.asset-dname` lies inside its card's border box (under-budget fixture, own page) | drop **both** `overflow: hidden` and `overflow-wrap: anywhere` — either alone still contains the text |
| For two assets differing only in a numeric suffix, the rendered text of each contains its own suffix **and** the rect covering that suffix is inside the card's border box | drop `overflow-wrap: anywhere` (the string then renders as one clipped line and the suffix is unpainted) |
| The ✎ button's `bounding_box().y` equals the `.asset-dname` **element's** `bounding_box().y` within 1 px, on a 3-line name | drop `flex: 1 1 0`; and separately, revert `align-items` to `center` |
| (If the clamp survives §1's measurement) the clamp fixture produces exactly 3 text-run rects | drop `-webkit-line-clamp: 3` (it then produces 4 or more) |
| A name past the budget renders head + `…` + tail, not head alone | off-by-one in `middle_truncate` |
| Opening the rename input on an over-budget name pre-fills the **full** name | restore the `dname.textContent` seed |
| Hover opens the overlay (`[hidden]` removed) and `overlayImg.currentSrc === thumb.currentSrc`, with a box larger than the thumb | drop the `mouseover` binding |
| A source whose aspect ratio is not 4:3 shows its full extent in the overlay | give the overlay image `aspect-ratio: 4/3; object-fit: cover` |
| At 360 px both the overlay's box **and** its image's box are inside the viewport, for a tall portrait source, and the overlay lands centred rather than beside the card | drop the image's `max-width`/`min-height` rules; measure before removing `hidden` |
| An over-budget name is fully readable in the caption (wraps, not clipped) | drop the caption's `overflow-wrap: anywhere` |
| Hovering thumb A then the neighbour the overlay covers switches the overlay to B's source | drop `pointer-events: none` (Playwright then reports the overlay intercepting) |
| After the debounced filter swaps the grid, hovering a cell in the **new** grid still opens the overlay | bind `mouseenter` per node at load instead of delegating |
| `mouseout`, Escape, `focusout`, scroll and resize each close it | drop each handler in turn |
| Focusing a card button opens it; Tab to a second button in the same cell reopens it; clicking ✎ and clicking ⇄ each leave it closed | drop the `focusin` binding; drop the observer's rename-input / replace-strip close |
| Filter-swapping the grid while the overlay is open closes it | drop the `MutationObserver` teardown |
| An overlay whose image 404s, and one whose thumbnail never loaded, both show the caption and no image box | drop the `error` handler; drop the empty-`currentSrc` guard |
| In a context created with `has_touch=True`, tapping a thumb does **not** open the overlay | drop the `matchMedia` gate |

**Fixture requirement.** `make_image_asset` defaults to `size=(1, 1)`
(`tests/factories.py:150`), which would make "a box larger than the thumb"
unachievable or true for the wrong reason. Every overlay e2e asset must be
seeded with an explicit `size=` larger than the rendered thumb.

**The rename-seed test must cancel with Escape.** `media_picker.js:375` commits
on `blur` with `save = true`, so a test that opens the input, reads `value` and
then lets focus move fires a live rename POST — which on a broken build writes
the ellipsised string into `MediaAsset.name`, the exact corruption §4 exists to
prevent. Read `input.value`, press Escape, then finish.

**Playwright contexts.** The geometry and overlay tests need the pointer gate to
match, or they time out with no clue why; `set_viewport_size` alone does not
enable touch emulation, so the default context satisfies
`(hover: hover) and (pointer: fine)` and no `has_touch` flag may be introduced
for the 360 px case. The pointer-gate row above is the one deliberate exception
and creates its **own** context with `has_touch=True`.

**The ✎ button is `opacity: 0` until its cell is hovered**
(`editor.css:725-726`). The alignment row therefore probes `bounding_box()` on a
transparent element and must **not** assert visibility.

**Screenshots.** `test_screenshots_light_and_dark`
(`tests/test_e2e_media_manager.py:588`) takes *element* screenshots
(`unused_cell.screenshot(...)`), which clip to the element's own box — a
`body`-appended, `position: fixed` overlay placed outside the card can never
appear in one. The refresh therefore: keeps the four existing element shots
(card height changes there), and **adds** a viewport-level `page.screenshot(...)`
with the pointer held over a thumb for the duration of the capture, in both
themes, for the overlay. Dark mode is judged on its own rather than assumed to
follow from light. Note that shot 1 (the unused cell) shows no ✎ at all, so the
button's new right-edge position can only be evidenced on a shot whose cell is
hovered or clicked first.

**Existing tests to repoint.** Suppressing the duplicate `.asset-fname` breaks
assertions that key on it: in those fixtures the asset carries no custom `name`,
so after a replace `display_name` falls back to the new `original_filename`, the
two match, and the secondary line is not rendered. This list was derived by
grepping `.asset-fname` across `tests/test_e2e_media_manager.py` and is
exhaustive as of `bb80f2f2`; re-derive it the same way if the file has moved on.
Each moves to `.asset-dname`, which always renders:

- `test_replace_swaps_the_cell_and_the_rendered_image` — `:136`
- `test_two_consecutive_replaces_both_succeed` — `:250`, `:259`
- `test_a_filter_swap_mid_flight_still_updates_the_cell` — `:309`
- `test_a_grid_swap_while_the_file_chooser_is_open_still_lands` — `:401`
- `test_an_upload_after_filtering_lands_in_the_live_grid` — `:436`

The explanatory comments at `:130-134` and `:245-248` must be rewritten
alongside the selectors, and they record **two different things** that must stay
distinct. `:130-134` says a bare `.asset-cell:has-text("replacement.png")` would
be satisfied *the instant the strip appears* — because `:has-text` matches
descendants and `[data-replace-filename]` holds exactly that name — making the
wait a **no-op that races the round-trip**. `:245-248` records the *downstream*
consequence in the second test: that no-op wait runs the next click while
`replaceBusy` is still true, the handler returns early, no chooser is raised,
and the test times out **on a correct build**. The rewrite must restate that
`.asset-dname` preserves the property that made `.asset-fname` correct —
`[data-replace-filename]` is not a descendant of `.asset-dname` — so a later
reader does not "simplify" back to `.asset-cell`.

Note also that a repointed assertion must match against the **truncated**
rendered text when the fixture name is over budget; the fixture names in these
tests (`replacement.png`, `first.png`, `second.png`, `late.png`,
`after-swap.png`, `after-filter.png`) are all well under budget and render
whole.

`tests/test_media_manager.py` asserts on the response body rather than on a
selector, so it is unaffected — except that
`test_no_template_comment_leaks_into_the_asset_cell` (`:629`) rejects `{#`,
`#}`, `{%`, `%}` in the rendered body, which constrains any comment added to
`_asset_cell.html` to a single-line `{# … #}` that Django strips.

## Consequences

Cards in a row grow to the tallest card, as they already do. Two or three title
lines is the expected range. The ✎ button sits at the card's right edge on every
card, not only long-named ones — visible on hover, since it is transparent
otherwise.
