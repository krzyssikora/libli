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

2. **The thumbnail crops.** `.asset-thumb` (`editor.css:360-365`) uses
   `object-fit: cover` at `aspect-ratio: 4 / 3`. When the only difference
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

Signature: `middle_truncate(value, budget=32)` → `str`.

Algorithm, in order:

- Coerce `budget = int(budget)`, then clamp `budget = max(budget, 0)`. The
  coercion is not decorative: Django hands filter arguments through as parsed,
  so `{{ name|middle_truncate:"20" }}` delivers the string `"20"` and
  `max("20", 0)` raises `TypeError`. A negative budget is a caller error;
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

**Budget derivation.** `.asset-dname` is a **single flex item** on flex line 1
of `.asset-names`, sharing that line with the ✎ button; `.asset-fname` has
`flex-basis: 100%` (`editor.css:721`) and so occupies flex line 2 on its own,
which the name never reaches. The consequence that governs this derivation: the
span's used width is `contentBox − button − gap` **for its entire height**. The
three lines the budget counts are soft-wrapped lines *inside* that one item, so
all three are equally narrow — lines 2 and 3 do **not** reclaim the button's
width.

At the grid's *theoretical* column minimum of 128 px
(`repeat(auto-fill, minmax(8rem, 1fr))`, `editor.css:350`) the cell's content
box is ~110 px after `var(--space-2)` padding and the 1 px border; the ✎ button
and its 4 px gap take ~34 px, leaving the span ~76 px, or ~11 characters per
line at `.9rem`/600. Capacity across three lines is therefore **~33
characters**, and the budget of 32 sits just inside it. A 14-character tail
covers a numeric suffix plus a four-character extension with room to spare. The
reported case (`przykladowa_parabola_0_2.png`, 28 characters) is under budget
and renders untouched.

The budget is deliberately derived at the theoretical *floor*, not at the width
the tests measure, so criterion (a) holds at every column width. `minmax(8rem,
1fr)` makes 128 px a floor, not the rendered width: at a 360 px viewport
`auto-fill` fits two columns and `1fr` distributes the remainder, so cards are
substantially wider and the same 32 characters occupy fewer lines. (The
docstring at `tests/test_e2e_media_manager.py:594-596` claims 360 px "pins
columns at the 128px minimum"; that claim is wrong and is inherited here, not
invented.) Implementation must still **measure** the rendered card width at
360 px, because the clamp's testability depends on it — see below.

The cost of deriving at the floor is over-truncation on wide cards, where more
would fit. The `title` attribute and the preview caption both carry the full
name, so nothing is unrecoverable.

Truncation slices by **code point**, not grapheme cluster. A name whose elision
boundary falls inside a combining sequence or an emoji ZWJ cluster may render a
broken glyph; grapheme-aware slicing is out of scope.

**Accepted limitations.** Two, both falling back on criterion (b):

- Two over-budget names differing only *inside* the elided middle truncate to
  identical strings. Criterion (a) is conditional on the difference lying
  outside the elision — which holds for the reported numeric-suffix case, since
  the tail is preserved.
- **If the 3-line clamp engages, the tail is lost.** `-webkit-line-clamp`
  truncates at the end of the third line and appends its own ellipsis, removing
  exactly the suffix `middle_truncate` reserved 14 characters to protect. With
  the budget at the floor capacity this requires glyphs wider than the `.9rem`
  average, so it is rare rather than impossible.

**The clamp may not survive measurement.** The clamp can only engage on a name
that is *within* budget (≤ 32 characters — anything longer is shortened by the
filter first) yet still overflows three lines at the rendered card width, which
is wider than the derivation floor. Implementation must determine whether such a
name exists at the measured width:

- If it does, the clamp stays and its test row uses that name.
- If it does not, the clamp is **unreachable in production as well as in test**.
  Delete **all four** declarations — `display: -webkit-box`,
  `-webkit-box-orient: vertical`, `-webkit-line-clamp: 3` **and
  `overflow: hidden`** — leaving `overflow-wrap: anywhere` as the sole
  containment rule. Not merely the last of the clamp triplet:
  `display: -webkit-box` swaps the span to legacy box layout and changes how the
  text node is boxed, which is exactly what the `getClientRects()` probe reads.
  And `overflow: hidden` goes with them because §3 gives it exactly one job
  beyond containment — letting the clamp clip — so once the clamp is gone it is
  a second, individually unfalsifiable mechanism for a guarantee
  `overflow-wrap: anywhere` already provides, which is the trap this spec
  rejects for `min-width: 0` and for the image `max-height`. The containment
  mutant then collapses to dropping that single remaining rule. Re-run the
  containment rows after the deletion, since the layout the probe measures has
  changed. The second accepted limitation above drops with it.

### 2. Card markup — `_asset_cell.html`

- `:1` becomes `{% load i18n courses_manage_extras %}`. Without it the template
  raises `TemplateSyntaxError: Invalid filter` on every manager render and every
  replace / rename / upload fragment — `courses_manage_extras` is not a
  configured template builtin, and every consumer of it (ten templates,
  `_link_picker_node.html` and `_element_row.html` among them) carries its own
  explicit load — none relies on it being a builtin. `{% load %}`
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

The seed reads the untruncated name from the cell root — the existing
`pen.closest(".asset-cell")` the handler already computes (`media_picker.js:334`)
— via `cell.getAttribute("data-name")`, **keeping** the `.trim()` the old seed
applied so a stored name with stray whitespace still seeds cleanly.

Two details that a literal reading gets wrong. `getAttribute` returns `null`,
not `""`, when the attribute is absent, so `.trim()` on it throws a `TypeError`
that kills the click handler and leaves no input at all — the read must be
null-checked. And on a null the handler **returns early**; it does **not** fall
back to `dname.textContent`. That is not squeamishness about dead code: the
fallback is the bug. `data-name` is unconditional in `_asset_cell.html`, and the
✎ control exists only in cells rendered by that template (`_picker_grid.html`
renders its own cells and has no rename affordance), so a null is a broken
invariant that should fail loudly rather than silently seed a truncated name
into the database.

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

**Module state.** Four pieces, kept distinct because conflating them is a live
bug source:

- `hoveredAnchor` — pointer bookkeeping only. Set on `mouseover`, cleared on
  `mouseout`. Drives the dwell and the already-pending / already-open no-ops.
- `openAnchor` — **the anchor the overlay is currently rendering.** Set by both
  the dwell path and the `focusin` path; cleared on close. Every teardown check
  and every placement measurement keys on *this*, never on `hoveredAnchor` —
  with the pointer resting on thumb A while the user Tabs into cell B, the
  overlay shows B and only `openAnchor` says so.
- `openedBy` — `"pointer"` or `"focus"`, scoping the `focusout` close (see Error
  handling). It is **derived from the state that currently justifies the
  overlay, not from whichever event fired last**: it is `"pointer"` whenever
  `hoveredAnchor === openAnchor` **or a hide timer is pending for
  `openAnchor`**, and `"focus"` otherwise. That second clause is not decoration:
  `mouseout` clears `hoveredAnchor`, so without it a pointer-opened overlay
  would be relabelled `"focus"` for the whole 300 ms grace, and a `focusout`
  landing in that window would close it early. Re-evaluated on every
  event that touches either variable — including a same-anchor `mouseover` and
  an in-place swap. Tying it to the last event instead would leave the commonest
  mixed case wrong: Tab to ✎ on cell A, then move the pointer onto that same
  cell's thumb, and a later Tab elsewhere would `focusout`-kill an overlay the
  pointer is actively hovering.
- An **open-generation token**, incremented on every open — including an
  in-place swap, which is an open in every respect but the `hidden` toggle. The
  `load` / `error` handlers, the hide timer and the deferred scroll binding all
  check it, so work scheduled by one open can never act on a later one.

**The overlay element.** One singleton, created on first use, appended to
`document.body` and kept there for the page's lifetime. Structure:
`div.asset-preview[aria-hidden="true"]` containing
`img[data-asset-preview-img]` and `div.asset-preview__caption`. **Closed state
is the `hidden` attribute** on the root, so tests can wait on an exact
`state="hidden"` / `state="visible"` transition and read the image through
`[data-asset-preview-img]`.

> `.asset-preview[hidden] { display: none; }` is **required**. `[hidden] {
> display: none }` comes from the UA stylesheet and any author `display` beats
> it, so without this rule the overlay is permanently visible from creation. The
> same file already ships `.math-modal[hidden] { display: none; }`
> (`editor.css:806`) and a `.picker__panel[hidden]` twin for exactly this reason
> — it is not redundant. Writing it *before* the `display: flex` declaration is
> a house convention matching `.math-modal`, not a cascade requirement:
> `.asset-preview[hidden]` is (0,2,0) against `.asset-preview`'s (0,1,0) and
> wins on specificity at any source position.

**Because the element is a singleton, every open must fully reset it.** The
broken-image path hides the `<img>`; without a reset, one broken thumbnail would
leave every subsequent preview on that page caption-only, still carrying the
previous asset's `src`. The open sequence therefore begins by restoring the
`<img>` to its default state, and only then applies the guards below. This reset
is unconditional and idempotent.

The image is hidden and revealed with the **`hidden` attribute**, matching the
overlay root's convention, so a test can wait on an exact state rather than
guess. Its companion rule is written `[data-asset-preview-img][hidden] {
display: none; }` — keyed on the same data attribute the structure and the
sizing rules use, not on a class the element does not carry. Unlike the root,
the image has no competing author `display`, so this rule is defensive rather
than strictly required; it is kept so the hide contract rests on a declaration
rather than on the UA stylesheet remaining unopposed. The
choice is load-bearing twice over: `display: none` keeps the image out of layout,
which is why the first placement measurement legitimately sees a caption-only
box and is re-run on `load`; and `opacity: 0` would leave Playwright reporting
the image *visible*, defeating the "before the image is visible" assertion
outright.

**The caption is written with `textContent`, never `innerHTML`.** This is a
security requirement, not a style preference, and it is the JS half of the
escaping argument §1 makes for `middle_truncate`. `data-name` holds
`display_name`, which falls back to `original_filename` — an uploaded file's
name, attacker-controllable — and `getAttribute` hands it back **fully
decoded**, so the server-side escaping that protects the card's markup gives the
overlay no protection at all. `innerHTML` here would be a live DOM XSS on
exactly the input the spec identifies as hostile. The image's `alt` is assigned
the same way (property assignment, never markup).

**The reset does not clear `src` at all.** It restores the `hidden` attribute on
the image, and that is all; the new source is then assigned directly over the
old one. It does not touch `alt`: the overlay image is decorative relative to
its own caption and carries `alt=""` set once at creation, so there is nothing
per-asset to restore. Neither `img.src = ""` nor
`img.removeAttribute("src")` may be used, and the reason is worth stating
because the second one looks safe and is not. Per HTML's "update the image data"
algorithm both produce a null selected source and **queue an `error` task** —
`src = ""` additionally resolves against the document URL and fetches the
manager page — and that task is dispatched asynchronously, after the open
sequence has already assigned the new source. No stale-event guard can catch it
either: within one synchronous task the order is clear → increment → assign, so
by dispatch time the generation is current *and* the image has a `src`, and both
guards pass. The `error` then flips a perfectly good, just-opened overlay to
caption-only, on every card of an A→B sweep.

Assigning the new `src` over the old one queues no such event, so the hazard
simply does not arise. A source that genuinely fails still fires its own honest
`error`, which is what the caption-only path is for.

**But reveal must not depend on `load` firing.** Re-opening the *same* anchor —
hover A, leave, hover A again, the commonest repeat in a scanning sweep —
assigns an `src` identical to the one the image already holds, and whether that
re-queues a `load` task on an already-complete image is engine behaviour this
spec will not bet on. If it does not, the reset's `hidden` is never lifted and a
perfectly good image renders caption-only forever. The open sequence therefore
checks, immediately after assigning:
`img.getAttribute("src") === expectedSrc && img.complete && img.naturalWidth > 0`
→ reveal **synchronously**; otherwise leave it hidden and wait for `load`. That
is correct whichever way the engine behaves, so it needs no spike.

The `load` and `error` handlers are bound **once at creation**, not per open, and
read the current anchor from module state. Per-open `addEventListener` without
removal would accumulate one handler per hover for the page's lifetime, each
re-running placement against a possibly stale anchor on every later load.

Both handlers act only when `img.getAttribute("src")` still equals the source
recorded in module state at assignment time. That is the discriminator — not a
generation stamp on the element, which cannot work here: a stamp is overwritten
by the latest assignment while the queued event carries no snapshot of the
generation in force when it was queued, so it always compares equal at dispatch.
Since the reset no longer clears `src` (above), the only events either handler
can see belong to a real source, and the expected-`src` comparison is enough to
drop one belonging to a source the module has already moved on from. That is the
live reason the guard exists: an in-place swap reassigns `src` while the
previous source's `load` or `error` may still be queued, and a handler that
acted on it would apply A's outcome to B's overlay.

**Trigger, and how it survives DOM churn.** `mouseenter` / `mouseleave` do
**not** bubble, so they cannot be delegated — and the manager replaces cells and
grids constantly (`insertCell` after upload, `cell.replaceWith(fresh)` after
rename and replace, `oldGrid.replaceWith(newGrid)` on every debounced filter).
Per-node listeners bound at load would therefore go silently dead on every
swapped-in cell. The module instead delegates the bubbling **`mouseover` /
`mouseout`** pair on the `.media-manager` root, resolving the anchor with
`e.target.closest("[data-asset-preview]")`. No arming pass and no per-cell
listener exists, so a cell inserted at any later moment works identically to one
rendered at load.

Opening waits out a dwell of **exactly 250 ms**. Anchoring to the thumbnail
rather than the whole cell keeps the image preview and the name's native `title`
tooltip on disjoint hover targets, so the two never stack.

**Anchor-to-anchor movement swaps in place, with no second dwell** — and making
that reachable requires a close *grace*, not an immediate hide. Moving from
thumb A to thumb B updates the source, the caption and the placement without
closing: the dwell guards against opening unintentionally, and re-paying it per
card would cost 250 ms each and defeat the "compare six cards in one pointer
sweep" rationale this whole design rests on.

The trap is that the thumbs are not adjacent. Between them lies cell A's
`var(--space-2)` padding and 1 px border, `.asset-grid`'s `gap: var(--space-3)`,
then B's border and padding — roughly 34 px of **non-anchor** space. A
physically moving pointer therefore always fires `mouseout` with `relatedTarget`
pointing at the cell or the grid, so an immediate hide would close the overlay
and force B to re-pay the full dwell. The in-place swap would then be reachable
only by a *teleporting* pointer — which is precisely what `page.hover(A)` then
`page.hover(B)` produces, so the e2e rows would certify a behaviour real users
never get.

Therefore: leaving an anchor starts a **hide timer** rather than hiding
outright. Entering *any* anchor within that window cancels the timer — another
anchor swaps in place, the **same** anchor simply resumes, which matters because
the pointer routinely drifts into the cell's own padding and back. A `mouseover`
resolving to the currently-open anchor is explicitly **not** a no-op: it cancels
the pending hide and re-evaluates `openedBy`. Without that, a 34 px drift and
return would leave the timer running, close the overlay under a pointer now
resting on the thumb, and — per the Escape reasoning above — leave nothing able
to reopen it. The timer expiring closes the overlay. A pending *open* dwell is
still cancelled immediately on leaving.

**The grace is 300 ms**, derived rather than guessed: the gap is ~34 px, and the
interaction this design exists for is a *deliberate* comparison sweep, not a
flick. 300 ms sets the floor at ~115 px/s, below any plausible intentional
traversal; at the 100 ms a first draft used, the floor is ~340 px/s and a slow
sweep silently re-pays the full 250 ms dwell — degrading to exactly the
behaviour the grace was introduced to fix.

Both A→B rows must drive `page.mouse.move()` through the inter-cell gap in a
stated number of small steps, never `hover(A)` → `hover(B)`, so they exercise
the path a real pointer takes. They must also assert on a **recorded transition
list** (see Testing) rather than on wall-clock proximity, so a slow harness
under parallel load cannot turn them red on a correct build.

**Timer hygiene.** Two rules, and the arming rule matters as much as the
cancelling one.

*Arming:* a `mouseout` arms the hide timer **only when the departed anchor is
`openAnchor`**; otherwise it merely clears `hoveredAnchor`. Without that scope,
the A-hovered/B-open configuration tears itself down: pointer resting on thumb
A, user Tabs into cell B (focus-open, timer cancelled), pointer then drifts off
A — that `mouseout` arms a fresh timer, the overlay is still open under the same
token 300 ms later so the bail below does not fire, and a mouse twitch on an
unrelated card kills a keyboard user's overlay. Every other teardown path is
already keyed on `openAnchor`; this one must be too.

*Cancelling:* the timer is cancelled on every close **and** on every open,
pointer or focus, and its callback bails unless the overlay is still open under
the same open-generation token — the same treatment the rAF-deferred scroll
binding gets, for the same reason. Otherwise a timer armed on A survives a Tab
that opens B and closes it 300 ms later; and in the mirror case a stale timer's
close disconnects the observer that a fresh open has just connected, reopening
the teardown hole this section spends two paragraphs closing.

The `e.relatedTarget`-contained-by-anchor check is **defensive, not currently
reachable**: the anchor is a replaced `<img>` with no descendants, so
`mouseover` / `mouseout` fire exactly once per entry and exit. It is kept
against a future non-replaced anchor. This is a deliberate exception to §4's
rejection of unreachable code, which is rejected there because the dead branch
would reintroduce a data-corruption bug; this one is inert. The
already-pending-dwell no-op is likewise unreachable today. The
already-*open* same-anchor case is **not** in that category — the hide grace
below makes it both reachable and load-bearing.

**The dwell window is a teardown hole and must be guarded.** A filter, rename or
replace swap can land *between* `mouseover` and the timer firing, while the
`MutationObserver` below is not yet connected. `getBoundingClientRect()` on the
detached anchor then returns zeros, "fits on the right" trivially passes, and
the overlay is pinned to the top-left corner with no anchor left to fire a
`mouseout` — stranded until an unrelated scroll, resize or Escape.
The fix is one check, not two: **the timer callback tests `anchor.isConnected`
before opening and aborts if false.** Nothing more is needed, and it is worth
being explicit about why, because the obvious second measure — connecting the
`MutationObserver` at dwell start so it can witness a swap the open would
otherwise miss — is inert. Observer records are delivered at a microtask
checkpoint, so a swap landing during the dwell is delivered long before the
250 ms timer fires; at that moment `openAnchor` is still null and the callback,
which keys on `openAnchor` and never on `hoveredAnchor`, can take no action.
Connecting early would be a redundant second mechanism for a hazard the
`isConnected` check already closes — the same trap this spec rejects for
`min-width: 0` and for the image `max-height` — and it would drag in three
disconnect paths that otherwise need not exist.

**The observer therefore connects at open, on both paths, and only after every
gate has passed** — never before. That ordering is load-bearing:
`media_picker.js:339` focuses the rename input, which sits inside a previewable
cell and, being a text field, *always* matches `:focus-visible`, so a
connect-then-check order would arm an observer on every single ✎ click that the
standing gate then refuses to open, leaking one per click. It disconnects on
close. Since it is never connected without an open overlay, close is the only
terminal path it has.

The callback must also **no-op when `openAnchor` is null** rather than
dereferencing it.

**Pointer gate.** The `mouseover` / `mouseout` path is armed only when
`matchMedia("(hover: hover) and (pointer: fine)")` matches, evaluated **once at
load** (no `change` listener — a pointing device appearing mid-session is not
worth the complexity). On touch a tap synthesises hover events with no matching
leave, which would strand the overlay over the grid. The **focus path is armed
unconditionally** — a keyboard attached to a touch-first device is a real
configuration, and nothing about the touch failure mode applies to it.

**Keyboard, and why the focus path is gated on `:focus-visible`.** The manager
cell is a `div` and is not focusable, and giving each card a tab stop would add
a fourth to the three buttons it already holds. The overlay therefore opens on
`focusin` within a cell that contains a `[data-asset-preview]` — so tabbing to
✎ / ⇄ / 🗑 surfaces the preview at no extra cost — and the focus path opens
**immediately, with no dwell**, cancelling any pending pointer-dwell timer.

The `focusin` must additionally satisfy `e.target.matches(":focus-visible")`.
Without that gate the overlay opens on *programmatic* focus with no user intent,
and the manager does that routinely: `media_picker.js:550` calls
`focusTrigger(fresh)` after a successful replace, focusing the fresh cell's own
⇄ button (asserted at `tests/test_e2e_media_manager.py:139`), which sits inside
a previewable cell. Every replace commit would otherwise raise the overlay
unprompted, in five of the e2e tests this spec already repoints and in the
screenshot flow. `:focus-visible` is false for focus restored after a pointer
interaction and true for keyboard traversal, which is exactly the distinction
wanted.

Note what the gate does *not* suppress: a user who commits the replace with
Enter leaves the heuristic in keyboard mode, so `focusTrigger(fresh)` will match
`:focus-visible` and the preview *will* open. That is the correct outcome for a
keyboard user — the gate targets the pointer-driven commit specifically — and
the corresponding e2e row exercises only that pointer-driven path.

**Standing gate: never open over a live editing control.** While
`.media-manager` contains a `.asset-rename-input` or a `[data-replace-strip]`,
the module refuses to open — pointer path and focus path alike. This is a
*standing* condition re-evaluated at every open attempt, not a one-shot reaction
to the element's insertion: a one-shot close is defeated by simply moving the
pointer back onto that cell's thumb 250 ms later.

Closing an overlay that is *already* open when such a control appears is a
separate trigger, and it needs one: an open-time check by definition never runs
for an already-open overlay. The `MutationObserver` (Error handling) is
connected exactly then, so its callback carries it — it closes when a
`.asset-rename-input` or `[data-replace-strip]` appears anywhere under the root,
alongside its `openAnchor` detach check.

That branch is **not** redundant with `focusout`, despite both flows moving
focus off the ✎ / ⇄ button before the new element is focused
(`media_picker.js:339` and `:461-462`). The `focusout` close is scoped to
`openedBy === "focus"` (Error handling), so a *pointer*-opened overlay survives
it — and a pointer-opened overlay on cell A plus a keyboard-driven rename on
cell B would otherwise leave the overlay sitting over the control this gate
exists to protect.

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
(`editor.css:360-365`). The overlay's image is a *separate* element that simply
does not carry those declarations — **that**, not any property on the overlay
image, is what shows the full frame. The caption is `display_name` (read from
the cell root's `data-name`) — for a renamed asset that is the custom name, not
the file's name; the card's own `.asset-fname` line, now carrying its own
`title`, is where the original filename is readable.

**Sizing.** The overlay image is *enlarged to fill the box*, so a source smaller
than the thumb's rendered size still previews larger than the thumb — the
preview's job is to un-crop, not to add detail. That requires `width: 100%`, not
merely a `max-width` ceiling, which is why the height must be bounded
independently: a `max-height` on the container does **not** bound its children,
so a portrait source at `width: 100%` of a 320 px box would render thousands of
pixels tall and overflow.

- `.asset-preview`: `position: fixed`, `z-index: 60`,
  **`width: min(320px, calc(100vw - 16px))`** — a definite width, *not* a
  `max-width`. A fixed-positioned element with only a `max-width` is
  shrink-to-fit, and a percentage width on a flex item resolves against that
  same indefinite box, so `width: 100%` on the image would collapse back to the
  image's natural width: a 40 px source would render a 40 px overlay, with the
  box's size decided accidentally by the caption's max-content width. Plus
  `max-height: calc(100vh - 16px)`, `overflow: hidden`, `display: flex`,
  `flex-direction: column`.
- `[data-asset-preview-img]`: `width: 100%`, `height: auto`, `min-height: 0`,
  `flex: 0 1 auto`, `object-fit: contain`. **The height bound is the flex
  shrink, and only the flex shrink.** In a column container clamped by
  `max-height`, an item with `flex-shrink: 1` and `min-height: 0` is already
  shrunk to fit; adding a `max-height` on the image would be a second mechanism
  achieving the same thing, so neither could be independently falsified — the
  same trap the `.asset-dname` pair documents. `object-fit: contain` is what
  keeps the aspect ratio once that shrink has constrained both dimensions.
  No `align-items` is set on the container: `align-self: stretch` applies only
  when the item's cross size computes to `auto`, and this image has an explicit
  `width`, so `center` versus `stretch` would be inert here.
- `.asset-preview__caption`: `overflow-wrap: anywhere`, and free to wrap to
  multiple lines. A filename has no soft-wrap opportunities, so without this the
  caption renders one unbreakable line and `overflow: hidden` clips the very
  tail it exists to recover. No `flex` override is needed: the caption's
  automatic minimum size is its content height (Flexbox §4.5 — the same rule
  that makes `min-height: 0` load-bearing on the image), so it cannot shrink
  below its text even at the default `flex-shrink: 1`, and the image absorbs
  all shrinkage regardless. Declaring `flex: 0 0 auto` here would be a second
  mechanism for a guarantee the first already gives, with no mutant able to tell
  them apart.

**Image swap must not show the previous asset.** An `<img>` keeps painting its
old frame until the new source decodes, so sweeping A → B would briefly show A's
image under B's caption — for a grid whose assets are near-identical, a
wrong-image-with-right-caption frame is precisely the confusion this feature
exists to remove. The `<img>` is therefore blanked as part of the unconditional
reset above and revealed only on its `load` (or replaced by the caption-only
state on `error`).

**The open sequence, in order.** Reset the singleton (§5) → **increment the
open-generation token** → populate: assign `src`, record it in module state as
the expected source, **reveal the image synchronously if it is already complete**
(the `complete && naturalWidth > 0` check above), set the caption with
`textContent`, set `openAnchor` and `openedBy` → connect the `MutationObserver`
→ remove `hidden` with `visibility: hidden` → measure → position → restore
`visibility` → bind the deferred scroll listener.

The reveal's position inside `populate`, **ahead of `measure`**, is load-bearing
and not incidental: on the synchronous path there may be no `load` event at all,
so the measurement taken here is the only one that will ever happen and it must
already include the image.

**An in-place anchor-to-anchor swap runs this same sequence** — minus the
`hidden` toggle on the root and minus the dwell. It is not a special path with
its own rules: it re-runs the reset, increments the token, re-records the
expected source, and re-measures, so the `load`/`error` discrimination and the
timer bails behave identically to a cold open.

**Placement.** All measurement happens **after** the `hidden` attribute is
removed — a `display: none` element has no box and `getBoundingClientRect()`
returns zeros, which would make every "does it fit?" test compare against width
0 and always answer yes. Placement is recomputed on the image's `load`, because
for an image that is *not* already complete, assigning `src` does not
synchronously give it a `naturalHeight`, so the first measurement sees a
caption-only box. On the synchronous-reveal path the opposite holds: the image
is already laid out when `measure` runs, there may be no `load` at all, and that
first measurement is both the only one and already correct.

- **The reference box is the cell, not the thumb.** `[data-asset-preview]` sits
  on the `<img>`, which is inset from the cell by `var(--space-2)` padding and a
  1 px border and is materially shorter than it, so the two rects are not
  interchangeable. Every placement calculation — and the zero-rect hazard in the
  dwell-window paragraph above — uses `anchor.closest('.asset-cell')`'s rect.
- Gap between the overlay and that cell rect: **8 px**.
- "Fits on the right" means
  `viewportWidth - cellRect.right - 8 >= overlayWidth`; "fits on the left" is
  the mirror. Below/above use the same inequality on the vertical axis.
- Order: right, left, below, above, then centred in the viewport when none fit.
  Centring is genuinely a last resort, not "the 360 px branch": at 360×900 a
  normal 4:3 preview still fits *below* a card near the top, so it is only the
  tall-portrait case — where the overlay is nearly viewport-height and no axis
  has room — that reaches it.
- On the perpendicular axis the overlay is top-aligned with the card (for
  left/right) or left-aligned (for above/below), then **clamped** into the
  viewport with an 8 px margin, so a card near an edge cannot push the overlay
  off-screen.
- **The viewport basis is `document.documentElement.clientWidth` /
  `clientHeight`** — for the fit inequalities, for the clamp, and for the e2e
  assertions, which must use the same quantity. The three candidates disagree by
  the scrollbar width (~15 px in Playwright's Chromium, and the manager grid at
  360 px certainly has a scrollbar): CSS `100vw` and `window.innerWidth` include
  it, `clientWidth` does not, and only `clientWidth` describes the space a
  `position: fixed` box can actually occupy. Using `innerWidth` would let the
  clamp tuck the overlay's right edge under the scrollbar, and the "both boxes
  are inside the viewport" row would pass or fail purely on which quantity the
  assertion happened to pick. The `100vw` / `100vh` in the `width` and
  `max-height` declarations are the deliberate exceptions — both only ever
  *shrink* the box, so erring ~15 px small is harmless. Note the asymmetry:
  `100vh` is ≥ `clientHeight` whenever a horizontal scrollbar exists, so the
  height cap can nominally exceed the clamp's budget; the clamp is authoritative
  and simply wins.
- **Clamp precedence when the box exceeds an axis:** top and left win — a box
  taller than the axis is pinned to the top margin and overflows the bottom.
  This is a general-case rule and is **not** reachable in the tall-portrait test
  row: `max-height` bounds the border box (`reset.css` sets `box-sizing:
  border-box` globally), and at 360×900 with no horizontal scrollbar `100vh`
  equals `clientHeight`, so that row's box always fits vertically. Assert the
  whole box, both edges.
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
→ set `hoveredAnchor`, cancel any pending hide → then **three ways**:

- resolves to `openAnchor` → stop; the overlay is already correct (only
  `openedBy` is re-evaluated).
- a *different* anchor **while the overlay is open** → run the in-place swap
  immediately, **no dwell**. This branch is what makes the sweep cheap; folding
  it into the dwell branch would re-pay 250 ms per card and leave A's image
  under the pointer for a quarter second.
- a different anchor **while closed** → start the 250 ms dwell → timer fires →
  `anchor.isConnected` and standing-gate checks (the pointer gate having been
  evaluated once at load; `:focus-visible` belongs to the focus path and has no
  meaning here) → the open sequence of §5, then reveal the image and re-place on
  its `load`.

**Close.** `mouseout` to a non-anchor (or a null `relatedTarget`) → 300 ms hide
timer → expiry restores `hidden` and clears `openAnchor`. `focusout`
(focus-opened only), Escape, scroll, resize and an `openAnchor` detach each
close immediately. Every close cancels the hide timer, the pending dwell and the
deferred scroll rAF, and disconnects the observer.

**Rename.** ✎ swaps `[data-asset-dname]` for an input
(`media_picker.js:335-339`) seeded from `data-name` (§4), and reinserts the same
span node on cancel, on a non-200, and on network failure; the success path
re-renders the whole cell from the server.

## Error handling

- **Overlay outlives its anchor.** The overlay lives on `document.body`, so it
  survives the events that destroy the cell that opened it. The module observes
  these with a `MutationObserver` on the `.media-manager` root
  (`childList: true, subtree: true`). Its connect point and its
  gates-first ordering are specified in §5 and are not restated here — code them
  from that paragraph, not from this bullet. Its callback no-ops when
  `openAnchor` is null, and otherwise closes the overlay on either of two
  conditions: `openAnchor` (not `hoveredAnchor`) has `isConnected === false`,
  clearing both; or a `.asset-rename-input` /
  `[data-replace-strip]` has appeared under the root (§5's standing gate). The
  detach check keys on the anchor **node**, never on a selector — a
  selector-keyed guard is a no-op when the event is a node replacement. This
  observer is for teardown only; arming needs none, because the trigger is
  delegated (§5). No change to `media_picker.js` is required for either.
- **`focusout` closes only what focus opened.** An unscoped `focusout` would
  close a pointer-opened overlay whenever focus moved anywhere on the page — a
  Tab out of the filter search box would dismiss the preview the user is
  actively hovering, and with no suppression flag they would have to move the
  pointer off the thumb and back to recover it. The close is therefore gated on
  `openedBy === "focus"`.
- **Scroll and resize.** A `fixed`-positioned overlay anchored to a moving card
  detaches visually, and a resize also re-flows the auto-fill grid and moves
  every card. Both close the overlay, regardless of `openedBy`. The scroll
  listener is
  `document.addEventListener("scroll", …, { capture: true, passive: true })` —
  `scroll` does not bubble from element scrollers to `window`, so capture is the
  only way to see one. (No inner scroller exists on the manager page today;
  capture is for any future one, not for a specific current node.) Both are
  bound only while the overlay is open.
- **The scroll close must not eat its own opening.** Sequential focus navigation
  scrolls the newly focused element into view — `focus()` does that by default —
  and the resulting `scroll` event is dispatched at the next rendering
  opportunity, i.e. *after* the `focusin` handler has already bound this
  listener. On any grid taller than the viewport, Tabbing to a card button would
  therefore open the overlay and instantly close it, and the "Tabbing opens it"
  test row would be red-to-flaky depending on fixture count. The scroll listener
  is therefore bound inside a `requestAnimationFrame` after open, so the
  focus-induced scroll has already been dispatched by the time it exists.

  That deferral introduces its own hole and must be closed: if the overlay shuts
  inside that same frame — a fast `mouseout`, an observer-driven close, Escape —
  the close's `removeEventListener` runs *before* the rAF callback adds the
  listener, leaving a live scroll handler with no overlay open and nothing to
  remove it. The next focus-open then meets it, the focus-induced scroll fires,
  and the overlay closes instantly: the exact failure the rAF was added to
  prevent, now intermittent rather than deterministic, which is worse. Store the
  rAF handle and `cancelAnimationFrame` it on every close, **and** have the
  callback bail unless the overlay is still open under the same open-generation
  token.
- **Broken or missing image.** Two distinct cases, both ending in the same
  caption-only state with the `<img>` hidden and no empty box — and both
  undone by the unconditional reset at the next open (§5):
  - The overlay's own load fails → its `error` event.
  - The *thumbnail* already failed, so there is nothing to copy. Guard before
    assigning: if `currentSrc` (falling back to `getAttribute("src")`) is empty,
    or the anchor is `complete && naturalWidth === 0`, go straight to
    caption-only without touching `src`. Assigning `""` to `src` does not
    reliably fire `error` and can leave the previous image in place.
- **A null `relatedTarget`.** `mouseout` carries `relatedTarget === null`
  whenever the pointer leaves the document — out of the window, into browser
  chrome, into a devtools pane — which is routine while an overlay is open.
  Every branch that inspects it (`closest`, contained-by) would throw on null
  and strand the overlay on screen with no further event able to close it. Null
  is therefore treated as "not an anchor": it starts the hide timer of §5 like
  any other exit.
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
length **with an explicit small budget** (e.g. `budget=5, value="ab.png"`) so it
actually reaches the fallback branch — at the default budget that case exits at
the first guard and exercises nothing new; a string `budget` (`"20"`, exercising
the `int()` coercion); and an assertion that the return value is a plain `str`,
**not** a `SafeString` — run on an **over-budget** value, and again on a
`budget <= 15` value, so it inspects the *constructed* returns. Run on a short
value it would only re-prove that the input was a plain `str`, and a `mark_safe`
applied to the truncating branches — the likeliest form of the regression —
would sail straight through it.

That last one is not pedantry. `display_name` falls back to
`original_filename`, which comes from an uploaded file's name and is
attacker-controllable, so a later `mark_safe(...)` "fix" would be a stored XSS.
Every other unit case uses innocuous ASCII and would stay green through it.

**Django client — `_asset_cell.html`.** `title=` present on `.asset-dname` and
carrying the **full** name while the visible text is truncated (assert both, on
one over-budget asset); `.asset-fname` present with its own
`title="<original_filename>"` when `original_filename` differs from
`display_name`, and absent when they match; `data-asset-preview` present on an
image asset's thumb and absent on a video asset's; and an asset whose name
contains markup (`<img src=x onerror=1>.png`) renders **escaped** in both the
span body and the `title` attribute — the client-side half of the `mark_safe`
guard above.

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

**Positive overlay assertions must be waits, never immediate reads.** The dwell
is 250 ms, so a `page.evaluate` fired straight after `hover()` reads the closed
state. Use `expect(...).to_be_visible()` / `wait_for_selector(state=...)`.

**Negative overlay assertions must first outlive the dwell.** This is the
mirror trap and it is easy to get wrong: `expect(overlay).not_to_be_visible()`
succeeds *instantly*, including on a mutant build where the overlay would appear
250 ms later. Every "does not open" row must wait past the dwell (an explicit
>250 ms settle, or a `wait_for_selector(state="hidden")` whose timeout outlives
it) before asserting closed.

**Viewport per overlay row.** Placement branches on viewport width, so each
overlay row states its viewport. Default for the overlay group is 1280×900,
where the overlay lands 8 px to the right of the cell's border box. Exactly
**one** overlay row runs at 360 px — the tall-portrait row — and it reaches the
centred fallback because that fixture leaves no axis with room, not because the
viewport is narrow. (The other 360 px rows in the table are card-geometry rows
and have nothing to do with placement.) The `pointer-events` row must identify
the covered neighbour from the measured overlay box rather than assuming which
cell it lands on.

**Constraint on the containment fixtures.** Their names must contain **no
hyphen, space, or other soft-wrap opportunity** — underscores and digits only,
e.g. `przykladowa_parabola_0_2.png`. Both containment mutants depend on the
fixture's min-content width being the whole string (§1); a hyphenated name has
natural break opportunities, so it wraps and stays inside the card even with
both rules dropped, and the rows pass on a broken build. Note that five of the
six repointed fixtures already in the file *are* hyphenated (`after-swap.png`,
`after-filter.png`) — do not reuse them here.

**Fixture scoping is load-bearing.** If the clamp survives measurement (§1), its
fixture's text deliberately exceeds three lines, so its clamped-away runs lay
out below the card's clipped bottom edge. It must be seeded on its **own**
page/test, never alongside the containment fixtures — otherwise the containment
row goes red on a correct build. The containment rows use a name that is under
budget and wraps within three lines.

**Two constraints on the clamp fixture,** if it exists: long enough to exceed
three lines at the *measured* card width, and ≤ 32 characters so
`middle_truncate` leaves it intact — otherwise the filter shortens it first and
the rect count is decided by the budget on both builds. The test asserts the
rendered text length equals the source length, so a later budget change fails
loudly instead of silently defusing the row.

**Two unverified engine premises, to settle by spike before writing their
rows.** Neither is knowledge this spec has:

1. Whether Blink removes clamped lines from the layout tree (so
   `getClientRects()` returns 3) or lays them out and merely clips the paint (so
   it returns 4+ on *both* builds, making the row unfalsifiable). Fallback probe
   if rects do not discriminate: `scrollHeight > clientHeight` on the span.
2. Whether Playwright's `has_touch=True` actually flips
   `(hover: hover) and (pointer: fine)`. In Chromium those media features follow
   the device-emulation configuration, which Playwright derives from
   `is_mobile`, not from `has_touch` alone — if the query still matches, the
   pointer-gate row is red on a correct build. Prefer a full device descriptor
   (`**playwright.devices["Pixel 5"]`, which sets both), and note `is_mobile` is
   Chromium-only.
(A third premise — whether Chromium queues an `error` for a *removed* `src` —
was retired when the reset stopped clearing `src` at all. §5 records why.)

| Test | Viewport | Mutant that must turn it red |
| --- | --- | --- |
| Every text-run rect of `.asset-dname` lies inside its card's border box (under-budget fixture, own page) | 360 px | drop **both** `overflow: hidden` and `overflow-wrap: anywhere` — either alone still contains the text |
| For two assets differing only in a numeric suffix, the rendered text of each contains its own suffix **and** the rect covering that suffix is inside the card's border box | 360 px | drop `overflow-wrap: anywhere` (the string then renders as one clipped line and the suffix is unpainted) |
| The ✎ button's `bounding_box().y` equals the `.asset-dname` **element's** `bounding_box().y` within 1 px, on a name that wraps to **at least two** lines at the measured width (a 3-line name may not be constructible within the 32-character budget — same caveat §1 gives the clamp fixture; both mutants discriminate at two lines) | 360 px | drop `flex: 1 1 0`; and separately, revert `align-items` to `center` |
| (If the clamp survives §1) the clamp fixture produces exactly 3 text-run rects | 360 px | drop `-webkit-line-clamp: 3` (it then produces 4 or more) |
| A name past the budget renders head + `…` + tail, not head alone | 1280 px | off-by-one in `middle_truncate` |
| Opening the rename input on an over-budget name pre-fills the **full** name | 1280 px | restore the `dname.textContent` seed |
| Hover opens the overlay and `overlayImg.currentSrc === thumb.currentSrc`, with a box larger than the thumb | 1280 px | drop the `mouseover` binding |
| A source whose aspect ratio is not 4:3 shows its full extent, undistorted, in the overlay | 1280 px | give the overlay image `aspect-ratio: 4/3; object-fit: cover` |
| A source smaller than the rendered thumb still previews larger than the thumb — fixture must pair a **deliberately short name** (`s.png`) with a small explicit `size=` (40×30), and the assertion is on the **image's** width, not the overlay's. Otherwise the mutant's shrink-wrapped box is decided by the caption's max-content width (~160 px for a normal filename, already wider than a ~115 px thumb) and the row stays green | 1280 px | change `.asset-preview`'s definite `width` to `max-width` (the box then shrink-wraps and `width: 100%` collapses to the natural size) |
| Sweeping A → B with `page.mouse.move(..., steps=10)` **through the inter-cell gap** swaps in place — install an in-page `MutationObserver` on the overlay root's `hidden` attribute *before* the sweep and assert the recorded transition list contains no visible→hidden→visible cycle, and that B's source is showing. Correct build and mutant reach the same terminal state and differ only in a transient, so a post-hoc read certifies nothing and polling for it is the trap the next row documents | 1280 px | hide immediately on `mouseout` instead of starting the 300 ms grace timer |
| A pointer that drifts off a thumb into its own cell's padding and back within the grace leaves the overlay open | 1280 px | make a same-anchor `mouseover` a no-op instead of cancelling the pending hide |
| While B's image is held unresolved by a `page.route` delay, the caption already reads B **and** the overlay's `<img>` is still `[hidden]` — so A's frame is never painted under B's caption. Hold the window open with the route rather than polling for it; the natural window is a cached decode, far shorter than any poll interval | 1280 px | reveal the image immediately instead of on `load` |
| A broken-thumbnail asset previewed **before** a good one leaves the good one's image box intact | 1280 px | drop the unconditional reset at open |
| Both the overlay's box **and** its image's box are inside the viewport for a tall portrait source, and the overlay lands centred rather than beside the card | 360 px | drop the image's `min-height: 0` (it then refuses to shrink); measure before removing `hidden` |
| An over-budget name is fully readable in the caption — probe `scrollWidth <= clientWidth` on the caption, never `inner_text()`, which reports the full string whether painted or clipped | 1280 px | drop the caption's `overflow-wrap: anywhere` |
| The caption of an asset named `<img src=x onerror=1>.png` has that exact `textContent` and the overlay subtree contains no injected element | 1280 px | write the caption with `innerHTML` instead of `textContent` |
| Hovering A, leaving past the grace, then hovering A again shows the **image**, not a caption-only box, **and places the overlay against the image's height rather than a caption-only box** | 1280 px | reveal only on `load`, dropping the synchronous `complete && naturalWidth > 0` check; and separately, reveal after `measure` instead of before it |
| With the pointer parked on thumb A and a focus-opened overlay on cell B, moving the pointer off A leaves B's overlay open past 300 ms | 1280 px | arm the hide timer on every anchor exit instead of only when the departed anchor is `openAnchor` |
| Hovering thumb A then the neighbour the overlay covers switches the overlay to B's source | 1280 px | drop `pointer-events: none` (Playwright then reports the overlay intercepting) |
| After the debounced filter swaps the grid, hovering a cell in the **new** grid still opens the overlay | 1280 px | bind `mouseenter` per node at load instead of delegating |
| A grid swap landing **during** the dwell leaves no overlay open | 1280 px | drop the `isConnected` check in the timer |
| `mouseout`, Escape, scroll and resize each close it; `focusout` closes a focus-opened overlay but **not** a pointer-opened one | 1280 px | drop each handler in turn; drop the `openedBy` scoping |
| Tabbing to a card button opens it **and it stays open** — run against a grid taller than the viewport, so the focus-induced scroll actually fires; Tab to a second button in the same cell reopens it | 1280 px | drop the `focusin` binding; and separately, bind the scroll listener synchronously at open instead of inside `requestAnimationFrame` |
| Closing the overlay within the same frame as opening it, then Tabbing to a card button, still leaves it open. No ordinary action sequence produces a same-frame close (`focus()` then `press("Escape")` are separate frames and the row would pass on the mutant) — use a single `page.evaluate` that focuses a card button and then synchronously dispatches a bubbling `keydown{key:"Escape"}` on `document` before yielding | 1280 px | drop the `cancelAnimationFrame` on close (the orphaned scroll listener then kills the next focus-open) |
| A replace commit does **not** leave the overlay open (`focusTrigger` is programmatic) | 1280 px | drop the `:focus-visible` gate |
| With a rename input open, hovering that cell's thumb does not open the overlay; same with a replace strip open | 1280 px | make the rename/replace close one-shot instead of a standing gate |
| Filter-swapping the grid while the overlay is open closes it — run once for a pointer-opened overlay and once for a focus-opened one | 1280 px | drop the `MutationObserver` teardown; connect the observer only at dwell start (the focus-opened variant then stays open) |
| An overlay whose image 404s, and one whose thumbnail never loaded, both show the caption and no image box | 1280 px | drop the `error` handler; drop the empty-`currentSrc` guard |
| In a touch-emulating context, tapping a thumb does **not** open the overlay | device descriptor | drop the `matchMedia` gate |

**Fixture requirement.** `make_image_asset` defaults to `size=(1, 1)`
(`tests/factories.py:150`), which would make "a box larger than the thumb"
unachievable or true for the wrong reason. Every overlay e2e asset must be
seeded with an explicit `size=`.

**The rename-seed test must cancel with Escape.** `media_picker.js:375` commits
on `blur` with `save = true`, so a test that opens the input, reads `value` and
then lets focus move fires a live rename POST — which on a broken build writes
the ellipsised string into `MediaAsset.name`, the exact corruption §4 exists to
prevent. Read `input.value`, press Escape, then finish.

**Playwright contexts.** The geometry and overlay tests need the pointer gate to
match, or they time out with no clue why; `set_viewport_size` alone does not
enable touch emulation, so the default context satisfies
`(hover: hover) and (pointer: fine)` and no touch emulation may be introduced
for the 360 px rows. The pointer-gate row is the one deliberate exception and
creates its **own** context.

**The ✎ button is `opacity: 0` until its cell is hovered**
(`editor.css:725-726`). The alignment row therefore probes `bounding_box()` on a
transparent element and must **not** assert visibility.

**Screenshots.** `test_screenshots_light_and_dark`
(`tests/test_e2e_media_manager.py:588`) takes *element* screenshots
(`unused_cell.screenshot(...)`), which clip to the element's own box — a
`body`-appended, `position: fixed` overlay placed outside the card can never
appear in one. The refresh therefore keeps the four existing element shots (card
height changes there) and **adds** a viewport-level `page.screenshot(...)` with
the pointer held over a thumb for the duration of the capture, in both themes,
for the overlay. That test pins 360×900, but the overlay shot must be taken at
**1280×900** — the overlay group's default, and the branch a reviewer should be
judging. At 360 px a 320 px overlay nearly fills the viewport and lands via the
below/centred fallback, which is legitimate but unrepresentative. Re-set the
viewport for the overlay shots and restore 360 px for the four element shots,
which must stay where they are. Dark mode is judged on its own rather than assumed to follow
from light. Note that shot 1 (the unused cell) shows no ✎ at all, so the
button's new right-edge position can only be evidenced on a shot whose cell is
hovered or clicked first.

**Correct that test's docstring while editing it.** `:594-596` currently states
that a 360 px viewport "pins columns at the 128px minimum". It does not:
`auto-fill` fits two columns there and `1fr` widens both past the 8rem floor.
Leaving it would put a claim in the tree that directly contradicts the budget
derivation this spec rests on.

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
otherwise. Names are truncated more aggressively than a wide card strictly needs,
because the budget is derived at the narrowest column the grid can produce.
