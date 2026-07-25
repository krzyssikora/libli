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
- No real Fullscreen API. An in-page overlay was chosen over it (see Decisions).
- No "arm only when the image would actually grow" measurement. Every content image is always
  clickable (see Decisions).
- No thumbnail/derivative generation. The overlay shows the same file the page already loaded.

## Architecture

Two new artifacts and four touched files. No models, no migrations, no views, no forms, no new
template-context flags.

### New: `courses/static/courses/js/imagezoom.js`

An IIFE in the house style of `gallery.js` / `stepper.js` (`"use strict"`, ES5-level syntax, no build
step, no dependencies). Three responsibilities:

1. **Arm** — `armAll(root)` walks `[data-zoomable]` within `root` and, for each not already armed:
   - sets `role="button"` and `tabindex="0"`;
   - adds class `imgzoom-trigger` (the cursor affordance and focus-ring hook);
   - gives it an accessible name: the image's own non-empty `alt` is left to serve as the name;
     when `alt` is empty (a decorative gallery figure), sets
     `aria-label = IMAGEZOOM_I18N.enlarge` so the control is never nameless;
   - marks it armed via `dataset.imgzoomReady = "1"` — idempotent, exactly as
     `stepper.js`'s `initOne` guards on `dataset.stepperReady`.

2. **Open / close** — one lazily-created `<dialog class="imgzoom">` appended to `document.body`,
   holding a single `<img class="imgzoom__img">`, reused for every open.
   - Open: set the dialog image's `src` from the trigger's `currentSrc || src` and its `alt` from the
     trigger's `alt`, set the dialog's `aria-label` (the trigger's `alt`, else
     `IMAGEZOOM_I18N.dialog`), then `dialog.showModal()`.
   - Close: `dialog.close()` on any click inside the dialog (the image included).
   - Escape is handled by `<dialog>` itself; no key handler for it.
   - `dialog.addEventListener("close", …)` clears the image `src` so a stale frame is never shown at
     the start of the next open.

3. **Delegate** — one `click` and one `keydown` listener on `document`, so images injected after boot
   (the editor's live-preview pane, a `check_answer` lesson re-render) work with no re-arming:
   - `click`: `e.target.closest("[data-zoomable]")` → `preventDefault()` then open. `preventDefault`
     matters because an image nested inside a `<summary>` or a `<label>` would otherwise also toggle
     that control.
   - `keydown`: Enter or Space on a `[data-zoomable]` → `preventDefault()` (Space would scroll) then
     open.

   Public re-arm hook: `window.libliInitImageZoom = armAll`, called on `DOMContentLoaded` over
   `document` and by `editor.js` over a freshly swapped preview pane.

The click/keydown delegation is what makes the feature work on dynamically injected content; the arming
pass only adds a11y attributes, so a not-yet-armed injected image still zooms by mouse and only lacks
keyboard access until the next `libliInitImageZoom` call.

### New: CSS block in `courses/static/courses/css/courses.css`

Appended as its own commented section, following the file's existing per-element organisation.

```css
.imgzoom-trigger { cursor: zoom-in; }
.imgzoom-trigger:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

.imgzoom {
  /* full-viewport, own opaque scrim: nothing of the page shows through */
  width: 100vw; max-width: 100vw; height: 100dvh; max-height: 100dvh;
  margin: 0; padding: 0; border: 0;
  background: <near-opaque dark scrim>;
  display: grid; place-items: center;
  cursor: zoom-out;
}
.imgzoom::backdrop { background: <same scrim>; }
.imgzoom__img { max-width: 100vw; max-height: 100dvh; width: auto; height: auto; display: block; }
```

`:focus-visible` uses the `outline: 2px solid var(--primary); outline-offset: 2px` pair that
`.reveal-gate`, `.spoiler__toggle`, `.fillgate__confirm` and `.switchgate__cycler` already use.

The **scrim is a new near-opaque dark value, not `--surface-overlay`** — that token is translucent
(`rgba(30,28,24,0.45)` light / `rgba(0,0,0,0.55)` dark), through which the page would remain legible,
contradicting "nothing but the image." It is dark in both themes, as image viewers conventionally are;
the exact value is a design-pass decision (see Testing → visual review), specified there as
"near-opaque, dark, identical in light and dark."

Styling both the dialog box and `::backdrop` is intentional belt-and-braces: the box's own background
is what guarantees opacity, and the matching `::backdrop` covers the inset region if a UA applies its
default dialog sizing before ours.

Any open/close transition is wrapped in `@media (prefers-reduced-motion: no-preference)`, matching the
existing usage at `core/static/core/css/app.css:464`.

### Touched: three page templates

`imagezoom.js` plus an `IMAGEZOOM_I18N` blob are added **unconditionally** to:

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
  (~line 97):
  `if (preview && window.libliInitImageZoom) window.libliInitImageZoom(preview);`

An explicit `data-zoomable` attribute, not a CSS-selector list inside the JS: the selector approach
("`.el--image img, .gallery__frame img, .filltable__img`") would silently arm or miss images whenever
that markup is restyled, and cannot distinguish `.filltable__img` from `.filltable-editor__img` at a
glance. The attribute is the contract, greppable from both sides.

### Sizing — why no measurement is needed

`max-width` / `max-height` only ever *shrink* a replaced element; neither can scale an image above its
intrinsic size. So with `width: auto; height: auto; max-width: 100vw; max-height: 100dvh`, the rendered
size is exactly `min(natural, viewport-fit)` — the "original size at most, fitted to the screen"
requirement, with no JS reading `naturalWidth` and no resize listener. `dvh` rather than `vh` so a
mobile browser's collapsing toolbar cannot clip the bottom of the image.

This is a **claim to verify by measurement**, not an assumption: the e2e tests assert the resulting
geometry (see Testing) rather than trusting the reasoning.

### Decisions and rejected alternatives

**Native `<dialog>` + `showModal()`, not a fixed-position div.** The codebase's existing overlays
(`.math-modal` in `editor.css`, `[data-catalog-modal]` in `catalog_modal.js`) are hand-rolled
`position: fixed` divs, and each re-implements a subset of what it needs. `showModal()` provides, as
platform behaviour: top-layer rendering that cannot lose a z-index fight with `.app-nav` (`z-index:50`)
or the sticky builder panel; Escape-to-close; a focus trap; focus restored to the previously focused
element on close; and the rest of the document inert. Reimplementing those correctly is more code and
more failure modes than using them. The behaviours we rely on are asserted in e2e rather than assumed.

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

**Extra tab stops accepted.** A 20-image lesson gains 20 tab stops. That is the honest consequence of
making images interactive, and the alternative (focusable but skipped in tab order) is a half-measure
keyboard users would never discover. (User decision.)

## Data flow

Nothing is persisted, requested, or submitted. There is no server round-trip and no state.

**Author → page.** Unchanged: an author picks a `MediaAsset`; the element templates render
`media.file.url` as they do today, now with a `data-zoomable` attribute.

**Page → armed.** `DOMContentLoaded` → `libliInitImageZoom(document)` → each `[data-zoomable]` gains
`role`/`tabindex`/class/name and `data-imgzoom-ready="1"`.

**Interaction.** click or Enter/Space on a `[data-zoomable]` → delegated handler → `preventDefault()` →
dialog image `src` set from the trigger's `currentSrc` → `showModal()`. The `src` is the same URL the
page already fetched, so the browser serves it from cache: no network request on open, which is what
keeps opening instantaneous.

**Close.** click inside the dialog, or Escape → `dialog.close()` → platform restores focus to the
trigger → `close` handler clears `src`.

**Dynamic content.** Editor preview fragment swap → `editor.js` → `libliInitImageZoom(preview)`.
Lesson `check_answer` re-render: no re-arm call, and none needed — the document-level delegation
already covers mouse and touch for any injected image; only keyboard arming waits for the next call.

**JS absent or broken.** No `data-zoomable` consumer runs, so images are exactly what they are today:
plain, non-interactive `<img>` elements with no misleading cursor and no dead controls. This matches
the progressive-enhancement contract documented in `galleryelement.html` ("No JS: figures show
stacked; gallery.js enhances into a carousel").

## Error handling

Every failure mode degrades to "the image behaves as it does today."

| Failure | Behaviour |
|---|---|
| `imagezoom.js` 404s or is blocked | Images render normally, unarmed, no cursor affordance, no dead click target. No page error. |
| `IMAGEZOOM_I18N` missing (a template that includes the script but not the blob) | Fallbacks used for the two labels, read defensively (`(window.IMAGEZOOM_I18N \|\| {}).enlarge \|\| "Enlarge image"`), so the script never throws on a missing global. |
| `HTMLDialogElement`/`showModal` unavailable | Feature-detected at boot (`typeof d.showModal === "function"`); if absent the module returns before arming anything, so no image is made to look clickable when clicking cannot work. |
| Broken image URL (deleted media, placeholder) | The trigger still opens; the overlay shows the browser's broken-image state for the same `src` the page shows. No special handling — the page-level defect is already visible inline. |
| Image inside `<summary>` / `<label>` / a link | `preventDefault()` on the delegated click stops the host control from also activating. |
| Already-open dialog re-opened | `showModal()` on an open dialog throws `InvalidStateError`; guarded by an `if (dialog.open) return` before opening. |
| Double arming (boot + editor re-init over the same node) | `data-imgzoom-ready` guard makes `armAll` idempotent. |
| A `[data-zoomable]` in a print view | The dialog is closed during print, and `<dialog>:not([open])` is `display:none`, so print output is unchanged. |

## Testing

Per the project's testing lessons: every new test is **falsified before it is trusted** — break the
thing it guards (delete the attribute, the CSS rule, the handler) and require RED, then restore. A
passing test that was never seen to fail proves nothing.

**Worktree note.** Two other pipeline worktrees exist on this machine; concurrent runs collide on the
Postgres test database. This branch's test runs must use a worktree-unique `DATABASE_URL` /
`test_libli` name.

### Unit / template tests — `tests/test_imagezoom_render.py` (new)

- `data-zoomable` present on the `<img>` rendered by `imageelement.html`, `galleryelement.html`, and
  the image branch of `_filltable_cell.html`.
- `data-zoomable` **absent** from `_edit_filltable.html`, `_edit_gallery.html`, and
  `dragtoimagequestionelement.html` — the negative half of the scope decision, which is the half that
  would otherwise rot silently.
- `lesson_unit.html`, `quiz_unit.html` and `editor.html` each include `imagezoom.js` **and** the
  `IMAGEZOOM_I18N` blob (a script tag without its i18n blob is a live failure mode, so both are
  asserted together).
- `editor.js` contains the `libliInitImageZoom(preview)` re-init call — a JS-source assertion in the
  style of the existing `tests/test_builder_js_invariants.py`.

### e2e — `tests/test_e2e_imagezoom.py` (new, `pytestmark = pytest.mark.e2e`)

Real Playwright gestures only — never `page.evaluate` to simulate the interaction, per the project's
e2e rule. Run focused and in the foreground.

Fixture: a lesson unit with one `ImageElement` whose asset is **deliberately larger than the article
column** (~1400×900), so "the overlay is bigger than the inline render" is actually measurable.
`tests/factories.make_image_asset` currently hardcodes a 1×1 PNG; it gains an optional
`size=(w, h)` kwarg defaulting to `(1, 1)`, so existing callers are unaffected.

1. **Open, geometry, isolation.** Click the image →
   - the dialog is open;
   - the overlay image's rendered width is **greater** than the inline image's was (it enlarged);
   - and **≤ its `naturalWidth`** (never upscaled);
   - and its box fits inside the viewport in both axes (never clipped or overflowing);
   - and the lesson content behind it is not visible (`checkVisibility()`-based, not `offsetParent` —
     the codebase has been burned by `offsetParent` staying truthy under `content-visibility`).
2. **Close by second click**, and focus is back on the trigger image.
3. **Close by Escape.**
4. **Keyboard open**: focus the image and press Enter → dialog open.
5. **Gallery figure** and **fill-in-table image cell** each open the overlay — one pass each, proving
   the two non-`ImageElement` surfaces are wired.
6. **Small image**: a 1×1/tiny asset still opens (the always-clickable decision) and is not upscaled.

### i18n

Two new msgids collected into **both** `locale/en` and `locale/pl` `django.po` via
`uv run python manage.py makemessages -l pl -l en --no-obsolete`, with the Polish text filled in and
**fuzzy flags cleared properly** — deleting both the `#, fuzzy` line and the `#| msgid` line, since a
fuzzy entry can arrive pre-filled from an unrelated msgid. No obsolete `#~` entries may remain; the
existing `tests/test_i18n_po_health.py` guards the catalogs.

### Visual review

Light **and** dark theme Playwright screenshots of the overlay, self-critiqued before shipping, per the
project's UI rule — including the scrim value, which is a judgement call this spec deliberately leaves
to that pass. Checked at a wide desktop viewport and at 360px, and with a portrait (tall) image as
well as a landscape one, since the height-constrained case is the one `max-height` governs.

### Regression guard

The full non-e2e suite must pass; `gallery.js`'s carousel height measurement is the specific thing to
watch, since `.gallery__frame` images are now armed (attributes only, no new boxes — which is exactly
why the wrapping `<button>` was rejected). `ruff check` and `ruff format --check` clean via `uv run`.
