# Click-to-enlarge images

## Purpose

A student reading a lesson has no way to see a content image any larger than the text column allows.
Images authored at 1400px wide render downscaled to whatever the article column gives them, and fine
detail — a labelled diagram, a scanned worked example, a graph with axis numbers — becomes unreadable.

This adds a full-screen view: click or tap any content image to show it alone on an opaque backdrop,
scaled to fit the viewport but never enlarged past its own natural size; click, tap, or press Escape
to return. Nothing but the image is visible while it is open.

### Scope

Armed (all non-interactive content images):

| Surface | Template | Current markup |
|---|---|---|
| Standalone image element | `templates/courses/elements/imageelement.html` | `<img src="{{ el.media.file.url }}" alt="{{ el.alt }}">` inside `<figure class="el el--image">` |
| Gallery / carousel figure | `templates/courses/elements/galleryelement.html` | `<img src="{{ f.url }}" alt="{{ f.alt }}">` inside `<div class="gallery__frame">` |
| Fill-in-table image cell | `templates/courses/elements/_filltable_cell.html` | `<img class="filltable__img" …>` in the `cell.kind == "image"` branch |

**Container elements inherit arming transitively.** Tabs, Two-column and Spoiler render their nested
children through the very same element templates, so an image element inside a tab panel, a column, or
a `<details>` body is armed automatically. That is desirable and needs no extra work, but it puts
armed images inside **five** different hiding mechanisms, which differ in whether they remove the tab
stop. This table is meant to be exhaustive — a mechanism missing from it is a potential leaked tab stop:

| Hiding mechanism | Removes the tab stop? |
|---|---|
| Tabs — inactive panel carries the `hidden` attribute | Yes (`display:none` subtree is not focusable) |
| Spoiler — closed `<details>` | Yes (content is not rendered) |
| Reveal cascade — the `{% if has_reveal_gate %}` inline `<style>` in `lesson_unit.html:38-44` hides post-gate siblings via `…:not(.reveal-shown) { display: none }`, for all three gate families | Yes. **The highest-stakes row**: these hide *answers*, so a leaked tab stop would let a keyboard user open a gated answer image before passing the gate. Safe because the selectors are author-origin `display:none` at high specificity — unlike `[hidden]`, they cannot be defeated by an element wrapper's own `display` rule |
| Stepper — the `{% if has_stepper %}` inline `<style>` hides `[data-stepper-step]:not(.stepper-shown):not(:first-child)` the same way | Yes, same mechanism and same reasoning |
| Slideshow — a paginating unit's non-current `.slide` carries the `hidden` attribute (`slideshow.js` hides all at rest; `courses.css:238` → `display:none`) | Yes. One wrinkle: during the 320ms cross-fade the outgoing slide is `opacity:0` but not yet `hidden`, so its images are briefly focusable — the same window the gallery has permanently, and too short to reach by Tab |
| Gallery — inactive figure is `opacity:0; pointer-events:none` + `aria-hidden="true"`, deliberately still laid out (`courses.css:1233-1234`) so `gallery.js` can measure its height | **No** — see "Gallery figures need `inert`" below |

Not armed, deliberately:

- **Drag-to-image question stages** (`.dragimage__img`) — click and drag *is* the graded interaction
  there; a zoom overlay on top of it would break a marked question.
- **`HtmlElement` images** — they live inside a `sandbox="allow-scripts"` iframe (`htmlelement.html`),
  a separate document our page script cannot reach. Out of scope, not a gap to close later.
- **Editor-side thumbnails** — `.filltable-editor__img` (`_edit_filltable.html`) and
  `.gallery-editor__thumb` (`_edit_gallery.html`). These are authoring controls, not content.
- **Media picker grid / asset cells / branding logos** — teacher tooling and chrome.
- **Sanitized rich text and table cells** — `img` is not in `courses/sanitize.py`'s `ALLOWED_TAGS`, so
  a `<img>` cannot survive into a text element or a table cell's html. Nothing to arm.

Verified during exploration: `_filltable_cell.html` is included **only** by
`templates/courses/elements/filltableelement.html` (the student-facing table), never by the fill-table
editor, which emits its own `.filltable-editor__img` markup. Adding the hook there therefore cannot
leak into the editor.

### Non-goals

- No pinch-zoom, pan, or scroll beyond fit-to-viewport. "Fits the screen, at most natural size" is the
  whole sizing contract.
- No next/previous stepping between gallery figures from inside the overlay. Opening a gallery figure
  shows that figure; closing returns to the carousel.
- No caption, `figcaption`, gallery description, or close button in the overlay. Nothing but the image.
- **No open/close animation.** The overlay appears and disappears instantly. Animating a top-layer
  `<dialog>` is not a one-liner — the entry needs `@starting-style` and the exit needs
  `transition-behavior: allow-discrete` on `display`/`overlay`, or a naive `transition: opacity`
  silently never runs on close — and an instant swap is the right behaviour for a viewer anyway. No
  `prefers-reduced-motion` block is therefore needed; there is no motion to reduce.
- **Full-bleed is deliberate.** The image touches the viewport edges when it is capped by one axis; no
  gutter, no frame, no shadow — "nothing but the image." If the visual review later wants breathing
  room it must come as `max-height: calc(100% - 2 * gutter)` on the image (or a padded inner box), never
  as `padding` on the dialog, which the image's `max-height: 100%` would simply overflow.
- No real Fullscreen API. An in-page overlay was chosen over it (see Decisions).
- No "arm only when the image would grow" measurement. Every content image is always clickable
  (see Decisions).
- No thumbnail/derivative generation. The overlay shows the same file the page already loaded.

## Architecture

Two new artifacts and five touched files. No models, no migrations, no views, no forms, no new
template-context flags.

### New: `courses/static/courses/js/imagezoom.js`

An IIFE in the house style of `gallery.js` / `stepper.js` (`"use strict"`, ES5-level syntax, no build
step, no dependencies), ending in a parse-time `armAll(document)` exactly as `gallery.js` ends in
`initGallery(document)` — the script is `defer`red, so the DOM is complete when it runs. Three
responsibilities:

1. **Arm** — `armAll(root)` walks `[data-zoomable]` within `root` and, for each not already armed:
   - sets `role="button"` and `tabindex="0"`;
   - adds class `imgzoom-trigger` (the cursor affordance and focus-ring hook);
   - leaves a non-empty `alt` to serve as the accessible name; when `alt` is empty, sets
     `aria-label = IMAGEZOOM_I18N.enlarge` so the control is never nameless. **"Empty" means absent or
     empty after trimming** — all three templates always render the attribute, and `alt` is free author
     text, so a whitespace-only value would otherwise slip through as "non-empty" and produce an
     effectively nameless control. The trimmed test is what the accessible-name e2e relies on;
   - marks it armed via `dataset.imgzoomReady = "1"` — idempotent, exactly as `stepper.js`'s `initOne`
     guards on `dataset.stepperReady`.

   `armAll(root)` arms **descendants of `root` only**, and `root` itself if it matches — the
   `scope.matches(...)` branch `gallery.js`'s `initGallery` already carries, for parity, since this is a
   public hook (`window.libliInitImageZoom`) that a caller may reasonably point straight at an image.

   **Script order matters and is fixed:** `imagezoom.js` is included *after* `gallery.js` in all three
   page templates, so galleries are already upgraded (`gallery--js`, `is-active`, `inert`) before any
   image is armed. Arming reads no layout and no visibility state, so the order is not
   *correctness*-critical today; it is pinned so that any future state-dependent arming inherits a
   defined ordering rather than discovering one.

2. **Open / close** — one lazily-created `<dialog class="imgzoom">` appended to `document.body`,
   holding a single `<img class="imgzoom__img">`, reused for every open.
   - Open: guard `if (dialog.open) return` (calling `showModal()` on an open dialog throws
     `InvalidStateError`), remember the trigger, set the dialog image's `src` from the trigger's
     `currentSrc || src` and its `alt` from the trigger's `alt`, then `dialog.showModal()`.
   - Close: `dialog.close()` on any click inside the dialog (the image included). Escape closing is the
     `<dialog>` element's own behaviour — but the dialog *does* carry a `keydown` listener that calls
     `e.stopPropagation()` for Escape (never `preventDefault()`, which would stop the close). Without
     it one Escape press would also reach the document-level Escape handlers that every armed page
     registers — `unit_nav.js:95` (mobile unit drawer), `core/static/core/js/ui.js:76,116` (nav menus),
     and on the editor page `math_input.js` / `media_picker.js` / `catalog_modal.js` — closing the
     overlay *and* a second unrelated thing. Two lines beats reasoning about six handlers.
   - On the dialog's `close` event: **`img.removeAttribute("src")`** — never `img.src = ""`, which
     resolves against the document URL and makes the browser fetch the current HTML page as an image
     on every close (a real request plus a decode error). Then `if (trigger) trigger.focus()` — guarded,
     since a stray programmatic `close()` with no prior open would otherwise dereference null.

   **A double-click opens then closes, and that is the accepted behaviour.** The first click opens the
   overlay, which then sits under the cursor, so the second click's target is the dialog and the
   close-on-click rule fires: the overlay flashes. This is not a bug to suppress with a timing window —
   it is exactly the "second click returns to the standard view" contract, applied twice. An e2e pins
   the outcome so it stays deliberate.

   **Dialog accessible name.** The dialog always takes `aria-label = IMAGEZOOM_I18N.dialog`
   ("Enlarged image"); the description lives on the contained image's `alt` and only there. Naming the
   dialog with the same `alt` string would make a screen reader read the description twice on entry —
   the accessible-name duplication this repo already shipped once in `_unit_crumbs.html` and does not
   want a second instance of. Consequence for a decorative figure, stated deliberately: an empty `alt`
   is the author declaring the image decorative, so the overlay is description-free — the `aria-label`
   names the *control*, never the image, and there is nothing else for a screen reader to read.

   **Focus restoration is explicit, not inherited.** `<dialog>` restores focus to whatever was focused
   before `showModal()`, which is the trigger only if the browser focuses an
   `<img role="button" tabindex="0">` on click. Chromium does; WebKit historically does not focus
   non-form elements on click, so on iPad Safari the pre-open focus is `<body>` and closing would drop
   focus to the top of the document. The `close` handler therefore calls `trigger.focus()` itself and
   treats the platform's restore as a backstop.

3. **Delegate** — one `click` and one `keydown` listener on `document`:
   - `click`: `e.target.closest("[data-zoomable]")` → `preventDefault()` → open.
   - `keydown`: `e.key === "Enter" || e.key === " "` on a `[data-zoomable]` → `preventDefault()`
     (Space would scroll the page) → open. Key auto-repeat from a held key is harmless: the second
     and later events hit the `dialog.open` guard and return.

   Two listeners on `document` rather than N per image, which keeps arming a pure attribute pass and
   makes the click path independent of it: an image that is in the DOM but not yet armed still zooms.
   (No known code path produces that state — see "Dynamic content" in Data flow — so this is
   robustness, not a supported mode.)

   `preventDefault()` on click is defence in depth, not a fix for a known nesting: none of the three
   armed templates puts its image inside a `<summary>`, `<label>` or `<a>` today, and sanitisation
   prevents authored HTML from doing so. It costs nothing and pre-empts a future container that does
   nest one. It does **not** suppress native image dragging or text selection — those start from
   `mousedown`/`dragstart`, long before `click` — and no suppression of them is wanted here.

   Public re-arm hook: `window.libliInitImageZoom = armAll`, called by `editor.js` over a freshly
   swapped preview pane.

### Touched: `courses/static/courses/js/gallery.js` — gallery figures need `inert`

Inactive carousel figures stay laid out on purpose (`position:absolute; opacity:0;
pointer-events:none`, plus `aria-hidden="true"`) so `gallery.js` can measure their natural height.
`pointer-events:none` already makes them unclickable, but nothing removes them from the **tab order** —
so arming every `.gallery__frame img` would give a 6-figure gallery 6 zoom tab stops, 5 of them
landing on an invisible image (the focus ring painted at `opacity:0`) inside an `aria-hidden` subtree:
the classic `aria-hidden-focus` violation.

Fix at the source: wherever `gallery.js` sets or removes `aria-hidden` on a `.gallery__item`, it also
sets or removes the **`inert`** attribute — four sites, each already paired with an `aria-hidden` write:
rest-init over all items (`gallery.js:41`), `settleHidden` (`:97`), the incoming item's clear (`:119`),
and the outgoing item during the fade (`:125`). `inert` makes the whole subtree non-focusable and
hidden from assistive tech in one attribute, changes no layout (so `measure()` is unaffected), and is
supported across current Chromium/WebKit/Firefox. Keeping `aria-hidden` alongside it is deliberate
belt-and-braces.

**Inerting an item that holds focus must rescue that focus first.** This is a real regression the change
would otherwise introduce, and it only exists because this feature makes something inside a figure
focusable for the first time. Inerting an element blurs any `document.activeElement` inside it to
`<body>`; `gallery.js`'s arrow-key handler is bound to `container` and bails on
`if (!container.contains(t)) return;` (`:143`). So: focus a zoom trigger → ArrowRight → the outgoing
item is inerted → focus drops to `<body>` → the next ArrowRight is ignored and the focus ring has
silently vanished. Keyboard carousel navigation would die after exactly one step.

**The rescue belongs to exactly one of the four sites: `show()`, immediately before the `:125` write.**
Only there are both the outgoing and incoming items in scope. The other three sites need no rescue and
must not attempt one:

- **rest-init (`:41`)** runs before `idx` is set and before the nav bar exists (`:78`), so it has no
  target to move focus to — and nothing inside a figure is focused yet, since the page has just loaded.
- **`settleHidden` (`:97`)** receives only the item, knows nothing of `pending.inn`, and runs from the
  fade timer or `finalizePending()` — 320ms *after* `show()` already inerted that same item at `:125`.
  Its write is a re-assert on an already-inert item.

Requirement at that one site: if the outgoing item contains `document.activeElement`, clear the
incoming item's `inert` **first** (focus cannot land inside an inert subtree), then move focus to the
incoming item's `[data-zoomable]`; if the incoming figure has no trigger, fall back to **the first
*enabled* control in the bar**, and if none is enabled, to the container itself given a `tabindex="-1"`.
The "enabled" qualifier is load-bearing: `gallery.js` sets `next.disabled` at the last slide and
`prev.disabled` at the first (`:115-118`), and `focus()` on a disabled button is a no-op that drops
focus to `<body>` — reintroducing the exact bug the rescue exists to prevent, at both boundary slides.
Those flags are updated at `:115-118`, before the inerting at `:125`, so the check reads the
post-update state. Focus already sitting on a nav button or a dot is outside the items and needs no
rescue. An e2e presses ArrowRight twice from a focused gallery image and asserts the carousel advanced
twice.

This also closes a latent pre-existing hole: gallery descriptions are sanitised HTML that permits
`<a href>`, so links inside inactive figures were already focusable inside an `aria-hidden` subtree.

### New: CSS block in `courses/static/courses/css/courses.css`

Appended as its own commented section, following the file's existing per-element organisation.

```css
.imgzoom-trigger { cursor: zoom-in; }
.imgzoom-trigger:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* Every box declaration is scoped to [open]: an unscoped author-origin `display`
   would beat the UA's `dialog:not([open]) { display: none }` and leave the dialog
   permanently covering the page. Same trap as `[hidden]` vs `display:grid` at
   courses.css:352. The rule below makes that explicit and guards a future edit
   that forgets the scoping — at (0,2,1) it also OUTRANKS an unscoped
   `.imgzoom { display: grid }` (0,1,0), which is why it, not the UA rule, is what
   governs the closed state, and why the e2e falsification for case 1 must delete
   BOTH this guard and the [open] scoping to go red. */
dialog.imgzoom:not([open]) { display: none; }

.imgzoom[open] {
  /* one viewport metric per axis, deliberately: horizontal from the initial
     containing block (top/left/right), which EXCLUDES a classic scrollbar;
     vertical from 100dvh, which tracks a mobile collapsing toolbar. Mixing
     `inset: 0` with an explicit height would over-constrain the vertical axis
     (`bottom` silently dropped) and mix two metrics on one axis. */
  position: fixed; top: 0; left: 0; right: 0; height: 100dvh;
  /* the UA gives dialog `max-width/max-height: calc(100% - 6px - 2em)` and
     `width/height: fit-content`; all four must be overridden */
  max-width: none; max-height: none;
  margin: 0; padding: 0; border: 0; overflow: hidden;
  background: var(--scrim-solid);
  display: grid; place-items: center;
  cursor: zoom-out;
}
.imgzoom::backdrop { background: var(--scrim-solid); }
/* 100% of the dialog's content box — which IS the fitted viewport, per above.
   Full-bleed by design; see Non-goals before adding a gutter. */
.imgzoom__img { max-width: 100%; max-height: 100%; width: auto; height: auto; display: block; }
```

**No `100vw` anywhere.** A modal `<dialog>` blocks document scrolling but does not remove the
document's scrollbar, and `100vw` includes that scrollbar's width — so a `100vw` box on a (always
scrollable) lesson page overflows the visible area by ~15px and centres the image off-centre.
`left: 0; right: 0` and `max-width: 100%` resolve against the initial containing block, which *excludes*
a classic scrollbar. `100dvh` rather than `100vh` for the vertical size so a mobile browser's collapsing
toolbar cannot clip the image. `overflow: hidden` is the belt to that braces.

Whether the page behind can still be scrolled is a **platform claim to test, not to trust**: a modal
`<dialog>` is specified to block document scrolling, but this repo has been burned by a confident, false
platform-behaviour claim before. An e2e dispatches a real wheel gesture over the open overlay and asserts
`window.scrollY` is unchanged. If that fails on any target engine, the fallback is an explicit lock — a
class on `<html>` setting `overflow: hidden`, removed on `close` — rather than a silent regression.

`:focus-visible` uses the `outline: 2px solid var(--primary); outline-offset: 2px` pair that
`.reveal-gate`, `.spoiler__toggle`, `.fillgate__confirm` and `.switchgate__cycler` already use.

**The scrim is a new token, `--scrim-solid`, with a concrete value.** `--surface-overlay` cannot be
reused: it is translucent (`rgba(30,28,24,0.45)` light / `rgba(0,0,0,0.55)` dark), through which the
page stays legible, contradicting "nothing but the image." Define `--scrim-solid: rgba(12,11,10,0.97)`
**once, in `tokens.css`'s `:root` block only, and deliberately not in the dark-theme block** — that
absence is the mechanism by which it is identical in both themes, and it carries a comment saying so,
because every neighbouring surface token *is* defined twice. Image viewers are conventionally dark in
both themes. The design pass (see Testing → visual review) may retune the value; it may not change the
mechanism — and precisely because every neighbour is defined twice, the next routine edit to
`tokens.css` is the one that would silently break this, so a **source-level test** guards the invariant
rather than a one-off review (see Testing).

Note also that the UA gives `dialog { background-color: Canvas }` — fully **opaque**, and light in the
light theme. A missing author `background` therefore does not fail loudly as a see-through overlay; it
fails as an opaque white panel. That is why the occlusion test asserts the resolved *colour* and not
merely the alpha channel.

Styling both the dialog box and `::backdrop` is intentional: the box's own background is what
guarantees opacity, and the matching `::backdrop` covers anything outside the box.

### Touched: three page templates

`imagezoom.js` plus an `IMAGEZOOM_I18N` blob are added **unconditionally**, and **after `gallery.js`**,
to:

- `templates/courses/lesson_unit.html`
- `templates/courses/quiz_unit.html`
- `templates/courses/manage/editor/editor.html` (the live-preview pane renders the student templates)

exactly as `gallery.js` and `tabs.js` are wired in all three today, with the same
`<script>window.X_I18N = {…}</script>` + `<script … defer>` shape as `GALLERY_I18N`
(`lesson_unit.html:73-74`). Two strings: `enlarge` ("Enlarge image") and `dialog` ("Enlarged image").

Unconditional rather than gated on a new `has_image` context flag: the script is a few hundred bytes,
its arming pass is a single no-op `querySelectorAll` when nothing is zoomable, and a flag would have to
be threaded through **both** `build_lesson_context` and `build_quiz_context` in `courses/views.py`
(plus kept in sync forever) to save that. `gallery.js`/`tabs.js` set the precedent.

### Touched: three element templates + `editor.js`

- `data-zoomable` added to the `<img>` in `imageelement.html`, `galleryelement.html`, and the `image`
  branch of `_filltable_cell.html`.
- One line in `courses/static/courses/js/editor.js`, beside the existing `libliInitGallery` call
  (~line 97): `if (preview && window.libliInitImageZoom) window.libliInitImageZoom(preview);`

An explicit `data-zoomable` attribute, not a CSS-selector list inside the JS: the selector approach
("`.el--image img, .gallery__frame img, .filltable__img`") would silently arm or miss images whenever
that markup is restyled, and cannot distinguish `.filltable__img` from `.filltable-editor__img` at a
glance. The attribute is the contract, greppable from both sides.

### Sizing — why no measurement is needed

`max-width` / `max-height` only ever *shrink* a replaced element; neither can scale an image above its
intrinsic size. So with `width: auto; height: auto; max-width: 100%; max-height: 100%` — 100% of the
dialog's content box, which *is* the fitted viewport per the CSS comment above — the rendered size is
exactly `min(natural, viewport-fit)`: the "original size at most, fitted to the screen" requirement,
with no JS reading `naturalWidth` and no resize listener. (Stated as `100%`, not `100dvh`, to match the
declaration exactly; the two coincide today only because the dialog is exactly `100dvh` tall, and would
diverge the moment the Non-goals' gutter escape hatch were used.)

This is a **claim to verify by measurement**, not an assumption: the e2e tests assert the resulting
geometry (see Testing) rather than trusting the reasoning.

### Decisions and rejected alternatives

**Native `<dialog>` + `showModal()`, not a fixed-position div.** The codebase's existing overlays
(`.math-modal` in `editor.css`, `[data-catalog-modal]` in `catalog_modal.js`) are hand-rolled
`position: fixed` divs, each re-implementing a subset of what it needs. `showModal()` provides, as
platform behaviour: top-layer rendering that cannot lose a z-index fight with the nav dropdown
(`app.css:229`, `z-index: 50` — the highest stacking value on a lesson page) or, on the editor page
(also an armed surface), `.math-modal` at `z-index: 1000` (`editor.css:552`); Escape-to-close; a focus
trap; and the rest of the document inert. Reimplementing those
correctly is more code and more failure modes than using them.

Which of those are actually verified, stated honestly rather than as a blanket claim: Escape-to-close
and scroll-blocking get their own e2e cases, and the focus trap gets one (Tab twice, focus never leaves
the dialog — non-obvious here because the overlay contains no focusable element). Top-layer stacking and
document-inertness are taken on trust; nothing in the design degrades badly if an engine differs. Focus
*restoration*, the one affordance that is provably not cross-browser reliable, is not trusted at all —
it is done explicitly (see above).

**`role="button"` on the `<img>`, not a wrapping `<button>`.** A real button element is the
conventional choice, and the *behaviour* it provides is what we ship — Tab-reachable, Enter/Space
activated, named, focus-ringed. But wrapping would insert a new box inside `.gallery__frame`, whose
height `gallery.js` measures to reserve uniform carousel space, and inside `<td>`s in the fill-in
table; both are existing, load-bearing layouts. `role="button"` on the image is valid ARIA (an `img` is
not an interactive element, so the role override is permitted), yields the same interaction, and
changes no boxes. Accepted cost: assistive tech announces "button" rather than "image, button", with
the `alt` as the name.

**In-page overlay, not the Fullscreen API.** True fullscreen would also hide browser chrome, but it is
gesture-gated, absent for non-video elements on iPhone Safari, and its exit is driven by OS gestures
outside our control. The overlay behaves identically everywhere. (User decision.)

**Always clickable, not "only when the image would grow."** Arming conditionally would need live
re-measurement per image on resize, on reveal, and after lazy load — and an image inside a closed
`<details>`/inactive tab measures as zero, a trap this codebase has already been bitten by. Every
content image opens; even an already-natural-size image gains a distraction-free view. (User decision.)

**Extra tab stops accepted — for visible images.** A 20-image lesson gains 20 tab stops. That is the
honest consequence of making images interactive, and the alternative (focusable but skipped in tab
order) is a half-measure keyboard users would never discover. (User decision.) It does *not* extend to
images hidden by a container, which is why the gallery gets `inert`.

## Data flow

Nothing is persisted, requested, or submitted. There is no server round-trip and no state.

**Author → page.** Unchanged: an author picks a `MediaAsset`; the element templates render
`media.file.url` as they do today, now with a `data-zoomable` attribute.

**Page → armed.** `gallery.js` self-inits (carousels upgraded, inactive items `inert`), then
`imagezoom.js` self-inits: `armAll(document)` gives each `[data-zoomable]` its
`role`/`tabindex`/class/name and `data-imgzoom-ready="1"`.

**Interaction.** click or Enter/Space on a `[data-zoomable]` → delegated handler → `preventDefault()` →
dialog image `src` set from the trigger's `currentSrc` → `showModal()`. The `src` is the same URL the
page already fetched, so it is *expected* to be served from cache rather than refetched — expected,
not established: media is served by `core/media_serve.py` on the DEBUG route (prod has its own), whose
cache headers this spec has not audited. Nothing in the design depends on it; opening is instant either
way because the image is already decoded in the page.

**Close.** click inside the dialog, or Escape → `dialog.close()` → `close` handler removes the `src`
attribute and focuses the trigger.

**Dynamic content.** The editor's live-preview pane swaps fragments and re-arms explicitly via
`editor.js` → `libliInitImageZoom(preview)`. That is the **only** path that injects `[data-zoomable]`
markup after boot. Traced and confirmed: `check_answer`'s re-render is question-scoped
(`question.js` sets `form.innerHTML` / `slot.innerHTML`), and the only `<img>` any question element
emits is `.dragimage__img`, which is deliberately unarmed; `filltable.js` repaints cell classes and a
summary but never re-renders `_filltable_cell.html`. So no lesson-side re-arm hook is needed.

Should some future path inject an armed-eligible image without calling the hook, the delegated click
still opens it, but it would carry no `role`, no accessible name, no `cursor: zoom-in` (that lives on
the `imgzoom-trigger` class, added by arming) and no tab stop — a hidden click target. That is a
degraded state, not a supported one: the fix would be to call `libliInitImageZoom` on the new subtree.

**JS absent or broken.** No `data-zoomable` consumer runs, so images are exactly what they are today:
plain, non-interactive `<img>` elements with no misleading cursor and no dead controls. This matches
the progressive-enhancement contract documented in `galleryelement.html` ("No JS: figures show
stacked; gallery.js enhances into a carousel").

## Error handling

Every failure mode degrades to "the image behaves as it does today."

| Failure | Behaviour |
|---|---|
| `imagezoom.js` 404s or is blocked | Images render normally, unarmed, no cursor affordance, no dead click target. No page error. |
| `IMAGEZOOM_I18N` missing (a template that includes the script but not the blob) | Fallbacks used for both labels, read defensively (`(window.IMAGEZOOM_I18N \|\| {}).enlarge \|\| "Enlarge image"`), so the script never throws on a missing global. |
| `HTMLDialogElement`/`showModal` unavailable | Feature-detected at boot with a throwaway element — `typeof document.createElement("dialog").showModal === "function"` — since the real dialog is created lazily and does not exist yet at boot. If absent the module returns before arming anything (no image is made to look clickable when clicking cannot work) and `window.libliInitImageZoom` is **not exported**, which `editor.js`'s existing `window.libliInitImageZoom &&` guard already tolerates. |
| Broken image URL (deleted media, placeholder) | The trigger still opens; the overlay shows the browser's broken-image state for the same `src` the page shows. No special handling — the page-level defect is already visible inline. |
| Key auto-repeat from a held Enter/Space | `if (dialog.open) return` guard; `showModal()` on an open dialog would throw `InvalidStateError`. |
| Mouse double-click on a trigger | Opens, then closes — the second click lands on the now-covering dialog. Accepted and pinned by e2e; see "A double-click opens then closes" above. It never re-enters the open path, so the `dialog.open` guard is not what handles it. |
| Double arming (boot + editor re-init over the same node) | `data-imgzoom-ready` guard makes `armAll` idempotent. |
| Image inside a `<summary>` / `<label>` / link (not currently possible) | `preventDefault()` on the delegated click stops the host control from also activating. |
| Print with the overlay closed (the normal case) | The author guard `dialog.imgzoom:not([open]) { display: none }` governs (it outranks the UA's equivalent rule, which sits beneath it as a backstop), so print output is byte-identical to today's. |
| Print while the overlay is open | Out of scope. Chromium includes top-layer content in print output, so the printed page would be the enlarged image. Nothing makes the dialog close on `beforeprint`, and nothing should: a user who prints while looking at an enlarged image plausibly wants that image. |
| Trigger removed from the DOM while the overlay is open (preview swap) | `trigger.focus()` on a detached node is a no-op, not a throw; the overlay closes normally. |

## Testing

Per the project's testing lessons: every new test is **falsified before it is trusted** — break the
thing it guards (delete the attribute, the CSS rule, the handler) and require RED, then restore. A
passing test that was never seen to fail proves nothing. Each test below names what to break.

**Worktree note.** Two other pipeline worktrees exist on this machine; concurrent runs collide on the
Postgres test database. This branch's test runs use a worktree-unique `DATABASE_URL` (`libli_imgzoom`
→ `test_libli_imgzoom`), already configured in the worktree's gitignored `.env`.

### Unit / template tests — `tests/test_imagezoom_render.py` (new)

- `data-zoomable` present on the `<img>` rendered by `imageelement.html`, `galleryelement.html`, and
  the image branch of `_filltable_cell.html` (rendered assertions — all three render from plain
  context). Falsify: drop the attribute from one template.
- `data-zoomable` **absent** from `_edit_filltable.html`, `_edit_gallery.html` and
  `dragtoimagequestionelement.html` — the negative half of the scope decision, the half that would
  otherwise rot silently. **Source-level** assertions (read the template file, assert the token is not
  present), in the style of `tests/test_builder_js_invariants.py`: the two editor partials need a
  form/formset context to render, and the negative is about what the template *says*, not what one
  context renders. Falsify: add the attribute to one of them.
- `lesson_unit.html`, `quiz_unit.html` and `editor.html` each include `imagezoom.js` **and** the
  `IMAGEZOOM_I18N` blob (a script tag without its i18n blob is a live failure mode, so both are
  asserted together), with `imagezoom.js` appearing **after** `gallery.js` in each. Falsify: remove the
  blob from one page; swap the two script tags.
- `editor.js` contains the `libliInitImageZoom(preview)` re-init call and `imagezoom.js` exports the
  **same literal**, and `gallery.js` sets and clears `inert` — JS-source assertions in the style of
  `tests/test_builder_js_invariants.py`. Pinning both sides of the name is the point: a grep that only
  checks the call site cannot catch a typo'd export.
- `imagezoom.js`'s `close` handler contains the null-guarded `trigger.focus()` — a source assertion,
  because no Chromium e2e can falsify its removal (see e2e case 4).
- **`--scrim-solid` appears exactly once in `tokens.css`, and not inside the dark-theme block** — the
  invariant the whole light/dark scrim mechanism rests on, and the one a routine token edit would break
  silently since every neighbouring token is defined twice. Falsify: add a second definition in the dark
  block.

### e2e — `tests/test_e2e_imagezoom.py` (new, `pytestmark = pytest.mark.e2e`)

Real Playwright gestures only — never `page.evaluate` to simulate the interaction, per the project's
e2e rule. Run focused and in the foreground (a background `-m e2e` sweep spawns runaway browsers).

#### The media-serving problem — solve this first, or every geometry assertion is fiction

`config/settings/test.py` sets `DEBUG = False`, and `config/urls.py` routes `/media/` **only** inside
`if settings.DEBUG:`. So under `live_server` a fixture asset's `MEDIA_URL` 404s: the trigger renders as
a broken image with `naturalWidth === 0`, and every width/geometry/pixel assertion below would "pass"
while measuring nothing. No existing e2e contradicts this — `test_e2e_gallery.py` asserts carousel
structure only, never that an image loaded.

Note the asymmetry, so the scope of the fix is self-evident: pytest-django's `live_server` wraps the
handler in `StaticFilesHandler`, which serves `/static/` regardless of `DEBUG` — so the CSS and JS under
test *do* load. Only `/media/` is unserved, so only `/media/` needs intercepting.

Mechanism: **`page.route("**/media/**", …)` resolves each requested path to its file under `MEDIA_ROOT`
(which these tests point at `tmp_path`, so the real bytes are on disk) and fulfils with *those* bytes,
404-ing any path that does not map.** Per-request resolution, not one canned response: a single handler
that always returned the 1400×900 fixture's bytes would silently serve them for the 1×1 asset, the
portrait asset and the structured visual-review asset too — case 14 would measure `naturalWidth == 1400`
for a 1×1 image and the visual review would judge the wrong picture, both while appearing to pass. No app
config is touched, no URLConf is mutated, and the `<img>`, its `src`, and every gesture stay real — the
interception replaces only the unserved transport. This does not weaken the "e2e must drive real UI"
rule, which is about driving real gestures rather than stubbing them.

Guard against silent regress: **every case that measures geometry first asserts the natural size it
expects** — `naturalWidth == 1400` for the large fixture, `naturalWidth == 1` for the tiny one — so a
routing failure or a mis-mapped asset fails loudly instead of quietly measuring the wrong file.

#### Fixture

A lesson unit with one `ImageElement` whose asset is **deliberately larger than the article column**
(1400×900) and **not black**: `tests/factories.make_image_asset` builds its PNG with
`Image.new("RGB", (1, 1))`, whose default fill is `#000000` — indistinguishable from a near-black scrim,
which would let the occlusion test pass for the wrong reason and make the visual review a black
rectangle on a black field. The factory therefore gains **two explicit named parameters ahead of
`**kw`** — `size=(1, 1)` and `color="black"` (today's behaviour as the defaults) — feeding
`Image.new("RGB", size, color)` and nothing else; `kw` is splatted into `MediaAsset.objects.create`, so a
stray key there would raise on an unknown model field. This module's fixture passes
`size=(1400, 900), color="#FF00FF"`. Existing callers are unaffected.

`MEDIA_ROOT` is redirected to `tmp_path` for these tests. `config/settings/base.py:168` points it at
`BASE_DIR / "media"` and the test settings do not override it, so without this every run would drop a
1400×900 PNG into the developer's real media tree — and this repo has already lost real images to a
`MediaAsset` file-lifetime incident. Disk state under `media/` is confirmed unchanged after the run.

**Viewport is set explicitly to 1280×800 for every geometry assertion** — never inherited. At that size
the 1400×900 asset is height-capped in the overlay to 800px tall × ~1244px wide, against a ~700px
article column: a margin far outside measurement noise. The narrow-viewport case is exercised by the
visual review, not by the inequality assertions, because at 360px the inline and overlay widths converge
to within the column padding and the comparison becomes a coin flip.

#### Cases

Device scale factor is pinned to **1** in the browser context, so CSS-pixel box coordinates map 1:1 onto
screenshot pixels and no conversion arithmetic is needed anywhere below.

1. **A closed dialog is not rendered.** The dialog is created lazily, so asserting "absent or invisible"
   *before* the first open is vacuous — it passes even with `display: grid` unscoped, which is the very
   bug it exists to catch. Instead: open the overlay, close it, and **then** assert the now-existing
   `.imgzoom` reports `checkVisibility()` false, and that `bounding_box()` is `None` (the expected
   outcome for a `display:none` element — it does **not** return a zero-area box; a non-`None` box must
   have zero area). No "or does not exist" escape hatch. Falsify: the break is **two deletions** —
   unscope `display: grid` **and** delete the `dialog.imgzoom:not([open])` guard. Unscoping alone leaves
   the test GREEN, because the guard at (0,2,1) outranks `.imgzoom` at (0,1,0); the guard is what makes
   the scoping individually untestable, so the paired deletion is the only valid break.
2. **Open + geometry.** Click the image → assert `naturalWidth == 1400` first (see above), then:
   - the dialog is open;
   - the overlay image's rendered width is **greater** than the inline image's was;
   - and **≤ `naturalWidth`** (never upscaled);
   - and the box is inside the viewport with an explicit half-pixel tolerance —
     `x >= -0.5`, `y >= -0.5`, `x + width <= 1280.5`, `y + height <= 800.5`. The tolerance is not
     decoration: for this fixture the vertical axis sits **exactly at** the 800px cap and the 0.888…
     scale factor rounds at device-pixel resolution, so only the horizontal axis has real slack. This is
     the assertion that would catch a `100vw` regression (scrollbar overflow shows up as
     `x + width ≈ 1295`).
3. **Nothing but the image is visible.** `checkVisibility()` cannot express this — a modal `<dialog>`
   makes the rest of the document *inert*, not unrendered, so the lesson article still reports visible.
   Two independent assertions instead:
   - (a) the computed `background-color` of `.imgzoom` is the near-black scrim: **assert the resolved
     colour channels** (each within ±12 of `rgb(12,11,10)`) as well as alpha ≥ 0.95. Asserting alpha
     alone is not enough and its obvious falsification is impossible: the UA sets
     `dialog { background-color: Canvas }`, which is opaque, so deleting the author `background` leaves
     alpha at 1.0 and the overlay renders as an opaque **white** panel with the test still GREEN.
     Falsify instead by re-pointing the declaration at the translucent `var(--surface-overlay)`
     (alpha 0.45/0.55) — the real regression this guards — which must go RED.
   - (b) pixel sampling. Mechanism, stated because Playwright cannot read pixels: take an element
     screenshot of the dialog, decode it with **Pillow**, and sample a fixed set of points (the four
     corners and the midpoint of each usable band). With `device_scale_factor = 1` the box coordinates
     are the image coordinates. The sample rectangle is **computed from the measured image bounding box,
     not from where text used to be**: at 1280×800 the fitted image spans x≈18–1262 and the full height,
     so the article column is entirely *behind the image*, and sampling "where the text was" would
     sample image pixels. Sample inside the letterbox bands beside the measured box (x < box.x − 2).
     **First assert the band is usable** (`box.x >= 6`) and fail with a clear message otherwise: the
     band is only ~17.8 CSS px at this viewport and shrinks to ~10px once a classic scrollbar narrows
     the initial containing block, and if the fixture ever became width-capped instead the bands would
     move to the top/bottom and a left/right rectangle would silently sample nothing. The expected value
     is the **composited** colour, not the raw token — `rgba(12,11,10,0.97)` over the equally-tinted
     `::backdrop` resolves to ≈`rgb(12,11,10)` — with each channel required within ±12, which also
     comfortably excludes the fixture's `#FF00FF`. Falsify by deleting **both** scrim declarations, the
     box `background` *and* `.imgzoom::backdrop`: they paint the same colour, so removing one leaves the
     other painting it and this half would stay GREEN.
4. **Close by second click**, focus back on the trigger. Note honestly that plain Chromium cannot
   falsify the explicit `trigger.focus()`: Chromium focuses the trigger on click, so `<dialog>`'s native
   restore satisfies this assertion even with the line deleted. Two guards instead — the source-level
   assertion listed above, plus a variant here that **blurs the trigger before opening** (reproducing
   WebKit's pre-open focus of `<body>`) and still requires focus on the trigger after close. That
   variant *is* falsifiable in Chromium; the plain case is a smoke test, not a guard.
5. **Close by Escape.** Falsify: remove the dialog from the close path (or the Escape `keydown`
   wiring); note that Escape-closing is UA behaviour, so what is really pinned is that nothing in our
   code suppresses it.
6. **Double-click** a trigger → the overlay ends **closed** (open-then-close, the accepted behaviour).
   Falsify: add a timing window that swallows the second click; this must go RED, which is what keeps
   the behaviour a decision rather than an accident.
7. **Keyboard open**: focus the image, press Enter → dialog open. Falsify: remove the `keydown` listener.
8. **Accessible name, both branches.** A non-empty-`alt` trigger is reachable as
   `get_by_role("button", name=<alt>)`; an empty-`alt` gallery figure as
   `get_by_role("button", name="Enlarge image")`. Falsify each by deleting its arm branch. Also assert
   the open dialog's own name is "Enlarged image" and **not** the image's `alt` (the no-duplication rule).
9. **Gallery: only the active figure is a tab stop.** A `get_by_role("button")` **count is not a valid
   test here** — inactive figures already carry `aria-hidden="true"` today and Playwright's role engine
   excludes ARIA-hidden elements by default, so that assertion is already green with `inert` removed.
   Assert real tab traversal instead, with a **bounded loop and a positive control**: from a known
   anchor, press `Tab` a fixed N times (N covering the page's focusable set), recording
   `document.activeElement` at each step, then assert over the recorded list that (i) it **did** reach
   the *active* figure's trigger — without which the whole assertion could pass by never reaching the
   gallery at all, the same vacuity this case was written to replace — and (ii) it never landed inside a
   non-`is-active` `.gallery__item`. Falsify: remove the `inert` handling from `gallery.js`; must go RED.
10. **Gallery: arrow-key navigation survives the `inert` change.** Focus a gallery zoom trigger, press
    ArrowRight **twice**, assert the carousel advanced **twice** (and that focus is still inside the
    container, not on `<body>`). This is the C4 focus-rescue guard. Falsify: drop the focus rescue and
    keep the inerting; the second press must stop working.
11. **The page behind does not scroll.** Record `window.scrollY`, dispatch a real wheel gesture over the
    open overlay, assert `scrollY` unchanged — testing the platform claim rather than trusting it. Two
    things make this non-vacuous: the fixture page must **exceed the viewport height** (asserted as a
    precondition, `scrollHeight > innerHeight`), or `scrollY` is 0 before and after on any engine, lock
    or no lock; and the **positive control is the falsification** — the identical wheel gesture with the
    overlay *closed* must change `scrollY`. There is no line of our code to delete here, so that control
    is what stands in for a break.
12. **Focus trap.** With the overlay open, press Tab twice and assert `document.activeElement` never
    leaves the dialog. Non-obvious precisely because the overlay contains no focusable element.
13. **No `src` left behind on close.** After closing, the overlay `<img>` has **no `src` attribute** —
    the guard on the `removeAttribute("src")` decision, whose regression (`img.src = ""`) fires a request
    for the HTML page itself on every close. Falsify: replace the call with `img.src = ""`.
14. **Hidden containers keep their images out of the tab order.** Tab-traverse a lesson containing an
    image inside an inactive tab panel and inside a closed spoiler; focus must never enter either. The
    `hidden`/`display:none` rows of the hiding-mechanism table are currently safe *by inheritance* and
    have no other guard, while this repo has the documented `[hidden]` vs author-`display` trap
    (`courses.css:352`) and does put `display` on element wrappers (`.el--twocolumn { display: flex }`).
    Falsify: give the panel or the spoiler child an author `display: block`.
15. **Editor preview re-arm, through the real UI.** On the editor page, make an edit and save so the
    preview pane swaps, then click the preview's image with a real gesture and assert the overlay opens.
    A source grep proves the string `libliInitImageZoom` exists in `editor.js`; it cannot prove the name
    matches what `imagezoom.js` exports or that arming survives a real fragment swap. The source
    assertion must pin the **same literal** on both sides (export and call site). Falsify: remove the
    `editor.js` re-init line.
16. **Fill-in-table image cell** opens the overlay — the third armed surface. Falsify: drop
    `data-zoomable` from `_filltable_cell.html`.
17. **Tiny image**: a 1×1 asset still opens (the always-clickable decision) and is **not upscaled** —
    asserting `naturalWidth == 1` as its precondition (so a mis-mapped media route cannot hand it the
    1400px fixture) and then that the overlay image's rendered width is 1, not stretched to the viewport.
    Falsify: give `.imgzoom__img` a `width: 100%`, which upscales it; must go RED.

### i18n

Two new msgids collected into **both** `locale/en` and `locale/pl` `django.po` via
`uv run python manage.py makemessages -l pl -l en --no-obsolete`, with the Polish text filled in and
**fuzzy flags cleared properly** — deleting both the `#, fuzzy` line and the `#| msgid` line, since a
fuzzy entry can arrive pre-filled from an unrelated msgid. No obsolete `#~` entries may remain; the
existing `tests/test_i18n_po_health.py` guards the catalogs.

### Visual review

Light **and** dark theme Playwright screenshots of the overlay, self-critiqued before shipping, per the
project's UI rule — including the `--scrim-solid` value, the one judgement call this spec leaves to
that pass. Checked at 1280×800 and at 360px, and with a portrait (tall) image as well as a landscape
one, since the height-constrained case is what `max-height` governs.

The screenshots need the same `page.route` media fulfilment as the e2e cases, and an image with visible
internal structure — a couple of contrasting blocks, not a flat fill — because a flat rectangle on a
near-black field shows neither the fit nor the scrim boundary, which is precisely what is being judged.

### Regression guard

The full non-e2e suite must pass. Two specific things to watch, both from the gallery change:
`gallery.js`'s carousel height measurement (armed images add attributes, no boxes — which is exactly
why the wrapping `<button>` was rejected; `inert` likewise changes no layout) and the existing gallery
e2e (`tests/test_e2e_gallery.py`), which drives the carousel that now toggles `inert`. `ruff check` and
`ruff format --check` clean via `uv run`.
