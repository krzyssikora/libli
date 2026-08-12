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
`media_picker.js`, and a new preview module. `.asset-cell`, `.asset-thumb` and
`.asset-name` are shared with the picker; of these only `.asset-thumb` is
touched, and only by adding a data attribute hook, so the picker's rendering is
unchanged. Out of scope: thumbnail generation, the picker grid
(`_picker_grid.html`), and the `cursor: pointer` on a non-clickable manager
cell.

## Architecture / components

Five components, each independently testable.

### 1. `middle_truncate` template filter

New filter in `courses/templatetags/courses_manage_extras.py` (the existing home
for manage-side filters — `register = template.Library()` at `:26`).

Signature: `middle_truncate(value, budget=38)` → `str`.

Algorithm, in order:

- Clamp `budget = max(budget, 0)` at entry. A negative budget is a caller error;
  clamping keeps the length invariant below total rather than letting
  `value[:budget]` return `len(value) + budget` characters.
- If `len(value) <= budget`, return `value` unchanged.
- Let `tail = 14` and `head = budget - 1 - tail` (the `1` is the ellipsis).
- If `head >= 1` (i.e. `budget >= 16`), return
  `value[:head] + "…" + value[-tail:]`.
- Otherwise (`budget <= 15`, so a middle truncation cannot preserve both ends)
  fall back to plain end-truncation: return `value[: budget - 1] + "…"` when
  `budget >= 2`, and `value[:budget]` when `budget < 2`.

**Invariant:** for any `budget >= 0`, the return value is never longer than
`budget`.

**Budget derivation.** At the grid's 128 px column minimum
(`repeat(auto-fill, minmax(8rem, 1fr))`, `editor.css:350`) the cell's content
box is ~110 px after `var(--space-2)` padding and the 1 px border. With
`.asset-dname` set to `flex: 1 1 0` (§3) the ✎ button shares only the **first**
flex line, costing it ~30 px including the 4 px gap: line 1 holds ~11 characters
at `.9rem`/600, lines 2 and 3 hold ~15 each. Capacity across three lines is
therefore ~41 characters *for typical filename glyphs*, and the budget of 38
sits inside that with margin. A 14-character tail covers a numeric suffix plus a
four-character extension with room to spare. The reported case
(`przykladowa_parabola_0_2.png`, 28 characters) is under budget and renders
untouched.

That capacity figure is glyph-width-dependent, which is exactly why the 3-line
clamp (§3) is retained: a 38-character name of unusually wide glyphs *can*
exceed three lines, and the clamp is what bounds the card's height then. See the
clamp row in Testing for the fixture that reaches it.

Truncation slices by **code point**, not grapheme cluster. A name whose elision
boundary falls inside a combining sequence or an emoji ZWJ cluster may render a
broken glyph; grapheme-aware slicing is out of scope, and the `title` attribute
and the preview caption both carry the intact name.

**Accepted limitation.** Two over-budget names differing only *inside* the
elided middle truncate to identical strings. Success criterion (a) is therefore
conditional on the difference lying outside the elision — which holds for the
reported numeric-suffix case, since the tail is preserved — and criterion (b)
covers the rest.

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
  (`editor.css:721`, `white-space: nowrap`) at ~110 px, and for a renamed asset
  it is the only place the real file identity appears — without the `title` the
  exact filename would be unobtainable anywhere in the UI.
- `:7` (`.asset-thumb`, the `<img>` branch only) gains `data-asset-preview` as
  the preview module's hook. The `<span class="asset-thumb asset-thumb--video">`
  branch at `:9` does not.

Any commentary added to this template must be a single-line `{# … #}` that
Django strips — see the constraint under Testing.

### 3. Card CSS — `editor.css`

`.asset-dname` gains three things, and it matters which does what:

- `display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3;
  overflow: hidden` — **this is what stops the spill.** `overflow: hidden` makes
  the span a scroll container, and per CSS Flexbox §4.5 a scroll container's
  automatic minimum size is **zero** rather than content-based. That is what
  lets the flex item shrink inside the card and end the paint-over. The
  `-webkit-line-clamp: 3` half bounds the card's height when a name's glyphs are
  wider than the budget derivation assumes.
- `overflow-wrap: anywhere` — **this is what keeps the text legible.** With the
  box now clipping, a filename with no soft-wrap opportunity would render as a
  single line cut off after ~11 characters, losing the tail that
  `middle_truncate` exists to preserve. `anywhere` introduces break
  opportunities so the string wraps across all three lines. (It is also counted
  in min-content sizing, unlike `word-break: break-word` — but that property of
  it is redundant here, since `overflow: hidden` has already collapsed the
  minimum.)
- `flex: 1 1 0` — **this is what keeps the ✎ button on the first line.** Flex
  line breaking happens before shrinking and uses each item's *hypothetical*
  main size; with the default `flex-basis: auto` that is the max-content width
  of the whole filename, which exceeds the ~110 px line on exactly the long
  names this feature targets, pushing the button onto flex line 2.
  `flex-basis: 0` makes the hypothetical size 0. `flex-grow: 1` is not optional
  alongside it — with basis 0 and no grow the span would be zero-width and the
  name invisible.

`min-width: 0` is deliberately **not** added: `overflow: hidden` already
collapses the automatic minimum, so it would change nothing observable and could
not be independently falsified.

`.asset-names` changes `align-items: center` → `align-items: start`, so the ✎
button aligns to the top of the first line rather than to the vertical middle of
a three-line name block.

**Visible consequence for every card, not just long-named ones.** `flex-grow: 1`
makes the name span absorb all free space on line 1, so the ✎ button moves from
sitting immediately after the name to the card's right edge — on short-named
assets too. This is intended and unavoidable given the basis-0 requirement
above, and the refreshed light/dark screenshots are expected to show it.

New `.asset-preview` overlay styles: see §5 for the sizing, placement and
stacking rules and the token list.

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

The seed changes to the untruncated name, read from the cell root's existing
`data-name` attribute (`_asset_cell.html:3`), with `dname.textContent.trim()`
retained only as a fallback if the attribute is absent.

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
Escape-capture arbitration — because a non-modal overlay needs none of it. What
it does carry over: reuse the already-fetched URL, and a deliberate `alt`.

The two can coexist later if click-to-enlarge is ever wanted here; nothing in
this design forecloses arming `[data-zoomable]` as well.

- **File and wiring.** `courses/static/courses/js/media_preview.js`, loaded from
  `manager.html`'s `{% block extra_js %}` (`:59`) alongside `media_picker.js`.
  It is a separate file rather than an addition to `media_picker.js` because it
  shares no state with the picker's upload / replace / rename / filter flows and
  `media_picker.js` is already the manager's largest script.
- **Pointer gate.** The whole module is inert unless
  `matchMedia("(hover: hover) and (pointer: fine)")` matches. On touch a tap
  synthesises `mouseenter` with no matching `mouseleave`, which would leave the
  overlay stuck over the grid.
- **Trigger, and how it survives DOM churn.** `mouseenter` / `mouseleave` do
  **not** bubble, so they cannot be delegated — and the manager replaces cells
  and grids constantly (`insertCell` after upload, `cell.replaceWith(fresh)`
  after rename and replace, `oldGrid.replaceWith(newGrid)` on every debounced
  filter). Per-node listeners bound at load would therefore go silently dead on
  every swapped-in cell. The module instead delegates the bubbling
  **`mouseover` / `mouseout`** pair on the `.media-manager` root, resolving the
  anchor with `e.target.closest("[data-asset-preview]")` and ignoring
  intra-anchor transitions by checking whether `e.relatedTarget` is contained by
  the same anchor. No arming pass and no per-cell listener exists, so a cell
  inserted at any later moment works identically to one rendered at load.
  Opening waits out a ~250 ms dwell so that sweeping a row does not strobe;
  leaving the anchor hides immediately and cancels a pending open.
  Anchoring to the thumbnail rather than the whole cell keeps the image preview
  and the name's native `title` tooltip on disjoint hover targets, so the two
  never stack.
- **Keyboard.** The manager cell is a `div` and is not focusable, and giving
  each card a tab stop would add a fourth to the three buttons it already holds.
  The overlay therefore opens on `focusin` within a cell that contains a
  `[data-asset-preview]` — so tabbing to ✎ / ⇄ / 🗑 surfaces the preview at no
  extra cost — and closes on `focusout` and on Escape. The focus path opens
  **immediately, with no dwell**, and cancels any pending pointer-dwell timer.
  `focusin` whose target is `.asset-rename-input` is **ignored**, and inserting
  that input closes any open overlay: the preview must not sit over the field
  the user is typing in.
- **Content.** The image at `object-fit: contain` inside the overlay's box, plus
  a caption. `contain` is the substantive part: it undoes the 4:3 `cover` crop
  that can hide the differing region entirely. A source smaller than the box
  **is** upscaled — the preview's job is to un-crop, not to add detail, and a
  "preview" that renders smaller than the thumbnail it previews would be
  absurd. The caption is `display_name` (read from the cell root's `data-name`)
  — for a renamed asset that is the custom name, not the file's name; the card's
  own `.asset-fname` line, now carrying its own `title`, is where the original
  filename is readable.
- **Sizing and placement.** `max-width: min(320px, calc(100vw - 16px))` and
  `max-height: calc(100vh - 16px)`, so the overlay always fits the viewport on
  both axes. Placement is tried in order: right of the card, left of the card,
  below it, above it, and finally centred in the viewport when no side fits —
  which is the operative case at the 360 px viewport the screenshot test uses,
  where neither side has room.
- **Containing block.** Appended to `document.body`, not to `.media-manager`, so
  that `position: fixed` resolves against the viewport. Any ancestor with
  `transform`, `filter`, `backdrop-filter`, `will-change` or `contain` would
  otherwise silently become the containing block.
- **Stacking and surface.** `z-index: 60` — above `.picker-overlay`'s 50
  (`editor.css:378`) so no positioned page chrome can bury it, and below
  `.math-modal`'s 1000 (`:807`), which is a true modal and must always win. The
  overlay is built from theme tokens so light and dark both resolve without a
  second rule set: `background: var(--surface-raised)`,
  `border: 1px solid var(--border-default)`,
  `border-radius: var(--radius-md)`, `box-shadow: var(--shadow-lg)`, padding
  `var(--space-2)`, caption at `.72rem` in `var(--text-secondary)`.
- **`pointer-events: none`** on the overlay. It necessarily covers the
  neighbouring grid cell; without this, sweeping right would fire `mouseout`
  then `mouseover` on the same anchor in a strobe loop, and the covered
  neighbour could never be hovered.
- **Accessibility.** `.asset-preview` carries `aria-hidden="true"`. It is a
  purely visual redundancy of text already present in the cell, appended at the
  end of `<body>`; announcing it would give a screen-reader user an orphaned
  duplicate of a name they have already heard.
- **Images only.** A video cell is a ▶ glyph (`_asset_cell.html:9`) and carries
  no `[data-asset-preview]` hook.
- **No new request.** The overlay reuses the thumbnail's own `currentSrc`, so
  the browser serves it from cache.
- **No translatable strings.** The overlay's image is decorative relative to its
  own caption and uses `alt=""`; the caption is the asset name, which is data,
  not UI copy. Nothing is added to the `data-msg-*` channel on `.media-manager`
  (`manager.html:10-16`) and no catalog regeneration follows.

## Data flow

**Render.** `manage_media` view → `_asset_grid.html` → one `_asset_cell.html`
per asset. `asset.display_name` (model property, `courses/models.py:754`) flows
into three places: the `title` attribute (full), the visible span body (via
`middle_truncate`), and the pre-existing `data-name` attribute on the cell root
(`:3`, full). `asset.original_filename` flows into `.asset-fname` — both its
body and its `title` — only when it differs from `display_name`.

**Hover.** `mouseover` on `.media-manager` → `closest("[data-asset-preview]")`
→ `relatedTarget` containment check → dwell timer → read the thumbnail's
`currentSrc` and the cell root's `data-name` → populate, size, and place the
single body-level overlay → show. `mouseout` to outside the anchor / `focusout`
/ Escape / scroll / anchor-detach → hide.

**Rename.** ✎ swaps `[data-asset-dname]` for an input (`media_picker.js:335-339`)
seeded from `data-name` (§4), and reinserts the same span node on cancel, on a
non-200, and on network failure; the success path re-renders the whole cell from
the server.

## Error handling

- **Overlay outlives its anchor.** The overlay lives on `document.body`, so it
  survives the events that destroy the cell that opened it. The module observes
  these with a `MutationObserver` on the `.media-manager` root
  (`childList: true, subtree: true`), **connected only while the overlay is
  open** and disconnected on close. On each mutation, if the stored anchor node's
  `isConnected` is false, the overlay closes. The check keys on the anchor
  **node**, never on a selector — a selector-keyed guard is a no-op when the
  event is a node replacement. This observer is for teardown only; arming needs
  none, because the trigger is delegated (§5). No change to `media_picker.js`
  is required for either.
- **Re-arm after an explicit dismiss.** Escape, `focusout` and scroll can all
  leave the pointer still inside the anchor, where no new `mouseover` will fire
  until it leaves and returns. A dismissed anchor is therefore recorded in a
  suppression flag cleared on that anchor's `mouseout`. The flag gates the
  **pointer path only** — `focusin` always reopens — and is set only when the
  pointer is actually inside the anchor at dismiss time, so a keyboard user's
  Escape from across the page cannot strand a flag on an anchor whose `mouseout`
  will never fire.
- **Scroll.** A `fixed`-positioned overlay anchored to a moving card would
  detach visually, so scroll closes it. The listener is
  `document.addEventListener("scroll", …, { capture: true, passive: true })`,
  bound only while the overlay is open — `scroll` does not bubble from element
  scrollers to `window`, and capture is what catches an inner scroller such as
  an expanded `.asset-uses-list`.
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
a value with no extension; a non-ASCII value; a value shorter than the tail
length.

**Django client — `_asset_cell.html`.** `title=` present on `.asset-dname` and
carrying the **full** name while the visible text is truncated (assert both, on
one over-budget asset); `.asset-fname` present with its own
`title="<original_filename>"` when `original_filename` differs from
`display_name`, and absent when they match; `data-asset-preview` present on an
image asset's thumb and absent on a video asset's.

**e2e — measured, not eyeballed.** A CSS assertion made with the rule in place
proves nothing, so each row is falsified against its mutant before it is
believed.

**Probe rule, binding on the four geometry rows below.** `inner_text()` is
**not** an acceptable probe: it is unaffected by `overflow: hidden` clipping, so
an assertion built on it passes on a build where the text is invisible. Those
rows use `document.createRange()` over the `.asset-dname` text node and
`getClientRects()` — the rect count is the line-box count, `[0]` is the first
line's box, and the last rect's right and bottom edges are what must lie inside
the card's border box.

| Test | Mutant that must turn it red |
| --- | --- |
| At 360 px, every text-run rect of `.asset-dname` lies inside its card's border box | drop `overflow: hidden` |
| For two assets differing only in a numeric suffix, the rendered text of each contains its own suffix **and** the rect covering that suffix is inside the card's border box | drop `overflow-wrap: anywhere` (the string then renders as one clipped line and the suffix is unpainted) |
| The ✎ button's box top aligns with the first text-run rect's top on a 3-line name | drop `flex: 1 1 0`; and separately, revert `align-items` to `center` |
| A 38-character all-uppercase-`W` name at 360 px produces exactly 3 text-run rects | drop `-webkit-line-clamp: 3` (it then produces 4 or more) |
| A name past the budget renders head + `…` + tail, not head alone | off-by-one in `middle_truncate` |
| Opening the rename input on an over-budget name pre-fills the **full** name | restore the `dname.textContent` seed |
| Hover opens the overlay with the thumbnail's `src` and a box larger than the thumb | drop the `mouseover` binding |
| After the debounced filter swaps the grid, hovering a cell in the **new** grid still opens the overlay | bind `mouseenter` per node at load instead of delegating |
| `mouseout`, Escape, `focusout` and scroll each close it | drop each handler in turn |
| Focusing a card button opens it; Tab to a second button in the same cell reopens it; focusing the rename input does not | drop the `focusin` binding; make the suppression flag gate the focus path; drop the `.asset-rename-input` exclusion |
| Filter-swapping the grid while the overlay is open closes it | drop the `MutationObserver` teardown |
| An overlay whose image 404s, and one whose thumbnail never loaded, both show the caption and no image box | drop the `error` handler; drop the empty-`currentSrc` guard |

**Fixture requirement.** `make_image_asset` defaults to `size=(1, 1)`
(`tests/factories.py:150`), which would make "a box larger than the thumb"
unachievable or true for the wrong reason. Every overlay e2e asset must be
seeded with an explicit `size=` larger than the rendered thumb.

Overlay tests run at the default 1280×900 viewport except the placement case,
which runs at 360 px and asserts the overlay's box is inside the viewport on
both axes.

`test_screenshots_light_and_dark` (`tests/test_e2e_media_manager.py:588`) is
refreshed — card height changes and the ✎ button moves to the card's right edge
— and dark mode is judged on its own rather than assumed to follow from light.
The overlay is included in that pass, hovered open, in both themes.

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

Note that a repointed assertion must match against the **truncated** rendered
text when the fixture name is over budget; the fixture names in these tests
(`replacement.png`, `first.png`, `second.png`, `late.png`, `after-swap.png`,
`after-filter.png`) are all well under budget and render whole.

`tests/test_media_manager.py` asserts on the response body rather than on a
selector, so it is unaffected — except that
`test_no_template_comment_leaks_into_the_asset_cell` (`:629`) rejects `{#`,
`#}`, `{%`, `%}` in the rendered body, which constrains any comment added to
`_asset_cell.html` to a single-line `{# … #}` that Django strips.

## Consequences

Cards in a row grow to the tallest card, as they already do. Two or three title
lines is the expected range at the 128 px column minimum. The ✎ button sits at
the card's right edge on every card, not only long-named ones.
