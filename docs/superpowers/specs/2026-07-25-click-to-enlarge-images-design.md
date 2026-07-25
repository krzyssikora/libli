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
armed images inside three different hiding mechanisms, which differ in whether they remove the tab stop:

| Hiding mechanism | Removes the tab stop? |
|---|---|
| Tabs — inactive panel carries the `hidden` attribute | Yes (`display:none` subtree is not focusable) |
| Spoiler — closed `<details>` | Yes (content is not rendered) |
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
   - leaves a non-empty `alt` to serve as the accessible name; when `alt` is empty (a decorative
     gallery figure), sets `aria-label = IMAGEZOOM_I18N.enlarge` so the control is never nameless;
   - marks it armed via `dataset.imgzoomReady = "1"` — idempotent, exactly as `stepper.js`'s `initOne`
     guards on `dataset.stepperReady`.

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
   - Close: `dialog.close()` on any click inside the dialog (the image included). Escape is handled by
     `<dialog>` itself; no key handler for it.
   - On the dialog's `close` event: **`img.removeAttribute("src")`** — never `img.src = ""`, which
     resolves against the document URL and makes the browser fetch the current HTML page as an image
     on every close (a real request plus a decode error). Then call `trigger.focus()` explicitly
     (see below).

   **Dialog accessible name.** The dialog always takes `aria-label = IMAGEZOOM_I18N.dialog`
   ("Enlarged image"); the description lives on the contained image's `alt` and only there. Naming the
   dialog with the same `alt` string would make a screen reader read the description twice on entry —
   the accessible-name duplication this repo already shipped once in `_unit_crumbs.html` and does not
   want a second instance of.

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
   prevents authored HTML from doing so. It costs nothing, suppresses the browser's native
   image-drag/selection artefact on the trigger, and pre-empts a future container that does nest one.

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
sets or removes the **`inert`** attribute — at rest-init (all items), in `settleHidden`/the outgoing
item of `show()`, and cleared on the incoming item. `inert` makes the whole subtree non-focusable and
hidden from assistive tech in one attribute, changes no layout (so `measure()` is unaffected), and is
supported across current Chromium/WebKit/Firefox. Keeping `aria-hidden` alongside it is deliberate
belt-and-braces.

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
   courses.css:352. The :not([open]) rule below makes that explicit and guards a
   future edit that forgets the scoping. */
dialog.imgzoom:not([open]) { display: none; }

.imgzoom[open] {
  position: fixed; inset: 0; width: auto; height: 100dvh;
  /* the UA gives dialog `max-width/max-height: calc(100% - 6px - 2em)` and
     `width/height: fit-content`; all four must be overridden */
  max-width: none; max-height: none;
  margin: 0; padding: 0; border: 0; overflow: hidden;
  background: var(--scrim-solid);
  display: grid; place-items: center;
  cursor: zoom-out;
}
.imgzoom::backdrop { background: var(--scrim-solid); }
.imgzoom__img { max-width: 100%; max-height: 100dvh; width: auto; height: auto; display: block; }
```

**No `100vw` anywhere.** A modal `<dialog>` blocks document scrolling but does not remove the
document's scrollbar, and `100vw` includes that scrollbar's width — so a `100vw` box on a (always
scrollable) lesson page overflows the visible area by ~15px and centres the image off-centre.
`inset: 0` and `max-width: 100%` resolve against the initial containing block, which *excludes* a
classic scrollbar. `100dvh` rather than `100vh` for the vertical cap so a mobile browser's collapsing
toolbar cannot clip the image. `overflow: hidden` is the belt to that braces.

`:focus-visible` uses the `outline: 2px solid var(--primary); outline-offset: 2px` pair that
`.reveal-gate`, `.spoiler__toggle`, `.fillgate__confirm` and `.switchgate__cycler` already use.

**The scrim is a new token, `--scrim-solid`, with a concrete value.** `--surface-overlay` cannot be
reused: it is translucent (`rgba(30,28,24,0.45)` light / `rgba(0,0,0,0.55)` dark), through which the
page stays legible, contradicting "nothing but the image." Define `--scrim-solid: rgba(12,11,10,0.97)`
**once, in `tokens.css`'s `:root` block only, and deliberately not in the dark-theme block** — that
absence is the mechanism by which it is identical in both themes, and it carries a comment saying so,
because every neighbouring surface token *is* defined twice. Image viewers are conventionally dark in
both themes. The design pass (see Testing → visual review) may retune the value; it may not change the
mechanism.

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
intrinsic size. So with `width: auto; height: auto; max-width: 100%; max-height: 100dvh`, the rendered
size is exactly `min(natural, viewport-fit)` — the "original size at most, fitted to the screen"
requirement, with no JS reading `naturalWidth` and no resize listener.

This is a **claim to verify by measurement**, not an assumption: the e2e tests assert the resulting
geometry (see Testing) rather than trusting the reasoning.

### Decisions and rejected alternatives

**Native `<dialog>` + `showModal()`, not a fixed-position div.** The codebase's existing overlays
(`.math-modal` in `editor.css`, `[data-catalog-modal]` in `catalog_modal.js`) are hand-rolled
`position: fixed` divs, each re-implementing a subset of what it needs. `showModal()` provides, as
platform behaviour: top-layer rendering that cannot lose a z-index fight with the nav dropdown
(`app.css:229`, `z-index: 50` — the highest stacking value on a lesson page) or the sticky builder
panel; Escape-to-close; a focus trap; and the rest of the document inert. Reimplementing those
correctly is more code and more failure modes than using them. The behaviours we rely on are asserted
in e2e rather than assumed — and focus *restoration*, the one platform affordance that is not
cross-browser reliable, is done explicitly instead (see above).

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
| `HTMLDialogElement`/`showModal` unavailable | Feature-detected at boot (`typeof d.showModal === "function"`); if absent the module returns before arming anything, so no image is made to look clickable when clicking cannot work. |
| Broken image URL (deleted media, placeholder) | The trigger still opens; the overlay shows the browser's broken-image state for the same `src` the page shows. No special handling — the page-level defect is already visible inline. |
| Already-open dialog re-opened (double-click, key auto-repeat) | `if (dialog.open) return` guard; `showModal()` on an open dialog would throw `InvalidStateError`. |
| Double arming (boot + editor re-init over the same node) | `data-imgzoom-ready` guard makes `armAll` idempotent. |
| Image inside a `<summary>` / `<label>` / link (not currently possible) | `preventDefault()` on the delegated click stops the host control from also activating. |
| Print | The dialog is closed during print and every box declaration is `[open]`-scoped, so the UA's `dialog:not([open]) { display: none }` applies and print output is unchanged. |
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
- `editor.js` contains the `libliInitImageZoom(preview)` re-init call, and `gallery.js` sets and clears
  `inert` — JS-source assertions in the style of `tests/test_builder_js_invariants.py`.

### e2e — `tests/test_e2e_imagezoom.py` (new, `pytestmark = pytest.mark.e2e`)

Real Playwright gestures only — never `page.evaluate` to simulate the interaction, per the project's
e2e rule. Run focused and in the foreground (a background `-m e2e` sweep spawns runaway browsers).

Fixture: a lesson unit with one `ImageElement` whose asset is **deliberately larger than the article
column** (1400×900), so "the overlay is bigger than the inline render" is measurable.
`tests/factories.make_image_asset` currently hardcodes a 1×1 PNG; it gains an explicit named
parameter `size=(1, 1)` **ahead of `**kw`** (never inside `kw`, which is splatted straight into
`MediaAsset.objects.create` and would raise on an unknown field), feeding `Image.new("RGB", size)` and
nothing else. Existing callers are unaffected.

**Viewport is set explicitly to 1280×800 for every geometry assertion** — never inherited. At that
size the 1400×900 asset is height-capped to ~1245px wide in the overlay against a ~700px article
column, a margin far outside measurement noise. The narrow-viewport case is exercised by the visual
review, not by the inequality assertions, because at 360px the inline and overlay widths converge to
within the column padding and the comparison becomes a coin flip.

1. **Closed dialog is not rendered.** Before any click, `.imgzoom` either does not exist or reports
   `checkVisibility()` false — the C1 guard. Falsify: move `display: grid` out of the `[open]` scope.
2. **Open + geometry.** Click the image →
   - the dialog is open;
   - the overlay image's rendered width is **greater** than the inline image's was;
   - and **≤ its `naturalWidth`** (never upscaled);
   - and its box fits inside the viewport in both axes (no overflow, no clipping) — this is what would
     catch a `100vw` regression.
3. **Nothing but the image is visible.** `checkVisibility()` cannot express this: a modal `<dialog>`
   makes the rest of the document *inert*, not unrendered, so the lesson article is still "visible" by
   that API. Assert occlusion two ways instead: (a) the computed `background-color` of `.imgzoom` has
   alpha ≥ 0.95; and (b) in a screenshot taken with the overlay open, sample a patch of pixels in a
   region that lesson text occupies when the overlay is closed, and require every sampled pixel to
   match the scrim colour within a small tolerance. Falsify: delete the `background` declaration from
   `.imgzoom[open]` — both halves must go RED.
4. **Close by second click**, and focus is on the trigger image afterwards.
5. **Close by Escape.**
6. **Keyboard open**: focus the image, press Enter → dialog open. Falsify: remove the `keydown`
   listener.
7. **Accessible name, both branches.** A non-empty-`alt` trigger is reachable as
   `get_by_role("button", name=<alt>)`; an empty-`alt` gallery figure is reachable as
   `get_by_role("button", name="Enlarge image")`. Falsify each by deleting its arm branch. Also assert
   the open dialog's own name is "Enlarged image", not the image's `alt` (the I9 no-duplication rule).
8. **Gallery: exactly one zoom tab stop.** In a 3-figure gallery, exactly one `[data-zoomable]` is
   focusable/queryable as a button — the `inert` guard. Then open it. Falsify: remove the `inert`
   handling from `gallery.js`.
9. **Fill-in-table image cell** opens the overlay — the third armed surface.
10. **Tiny image**: a 1×1 asset still opens (the always-clickable decision) and is not upscaled.

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

### Regression guard

The full non-e2e suite must pass. Two specific things to watch, both from the gallery change:
`gallery.js`'s carousel height measurement (armed images add attributes, no boxes — which is exactly
why the wrapping `<button>` was rejected; `inert` likewise changes no layout) and the existing gallery
e2e (`tests/test_e2e_gallery.py`), which drives the carousel that now toggles `inert`. `ruff check` and
`ruff format --check` clean via `uv run`.
