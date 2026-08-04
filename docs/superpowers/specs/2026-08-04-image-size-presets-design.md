# Image size presets

## Purpose

An author has no way to size an image. `ImageElement` stores `media`, `alt` and `figcaption` and
nothing else (`courses/models.py:649-655`); the rendered `<figure>` carries no size hook
(`templates/courses/elements/imageelement.html:1-4`); and the only constraint anywhere is the global
`max-width: 100%`. Two consequences:

1. **An author must guess dimensions before seeing the image in context.** The image is whatever size
   it was uploaded at.
2. **Nothing constrains image HEIGHT.** A tall, narrow image is never touched by `max-width` — it is
   already narrower than the column — so it renders at full natural height and overflows the screen.

### Measured evidence (1067 images with a readable file, local `libli` DB, 2026-08-04)

| fact | count |
|---|---|
| wide or square | 1042 |
| tall (h/w > 1.5) | 25 |
| naturally narrower than the 736px prose column | 162 |
| **render taller than a 900px desktop window** | **30** |
| **overflow a 640px phone viewport** | **10** |

Rendered-height percentiles at the 736px column: p50 466px, p75 591px, p90 736px, p95 804px,
p99 1306px, max 1492px. The worst are `494x1492` (h/w 3.0).

The originating report was unit 1095 ("Pierwiastek - wyłączanie i włączanie"), whose first spoiler
holds `czynnik_przed_pierwiastek_1.png` at **297x719** (h/w 2.42, element pk 1082) — fine on desktop,
taller than the viewport on a phone. Its sibling `czynnik_przed_pierwiastek_2.png` at 948x719 is
already fine on mobile, because it is wide enough for `max-width` to shrink it. That contrast is the
whole problem in one spoiler: **width-only constraints do not bound a tall image.**

### Why presets are bounding boxes, not widths

A width-only preset does not produce comparable visual sizes across aspect ratios. At "medium = 50%
of a 736px column" (368px):

| aspect | renders as | verdict |
|---|---|---|
| 1:3 tall | 368 x 1104 | dominates the page |
| 2:1 wide | 368 x 184 | fine |

So each preset is a **bounding box** — a max-width *and* a max-height — with the image scaled to fit
inside it, preserving aspect ratio. The browser does this natively with `max-width` + `max-height` +
`height: auto`; there is no server-side image processing anywhere in this design.

## Architecture / components

### 1. Model — `ImageElement.size`

```python
class Size(models.TextChoices):
    SMALL = "small", _("Small")
    MEDIUM = "medium", _("Medium")
    LARGE = "large", _("Large")
    FULL = "full", _("Full")

size = models.CharField(max_length=8, choices=Size.choices, default=Size.FULL)
```

Labels use `gettext_lazy` (module-level translatable strings must, per house rule). A schema
migration adds the column with `default="full"`.

**There is no data migration.** Because `full` carries a `max-height: 100vh` (see below), the 30
over-tall images are corrected by the CSS rule itself, and the other 1037 render byte-identically.
This is a deliberate reversal of an earlier draft that proposed defaulting to a capped preset: a
70vh default would have visibly shrunk **207 images (19%)** — 103 mildly, 70 noticeably, 11 by more
than half — to fix 10 mobile cases. Capping only at the viewport changes exactly the images that are
already broken.

### 2. Rendering — a class, not an inline style

```html
<figure class="el el--image el--image--{{ el.size }}" data-el-pk="{{ ... }}">
  <img src="…" alt="…" data-zoomable>
```

A class, because the values are `%` of the column plus `vh` of the viewport — not expressible as a
per-element inline style — and because it keeps all four boxes in one place.

`data-el-pk` exists solely so the editor's live preview can find this figure (see §5). It is inert on
student pages.

### 3. CSS — four bounding boxes

Applied to the `<img>` inside the figure, with `height: auto` so the browser preserves the ratio.
The prose column is `46rem` (`courses/static/courses/css/courses.css:181`, `.lesson { max-width:
46rem }`), i.e. 736px at a 16px root.

| class | max-width | max-height | tall image (297x719) renders as, desktop |
|---|---|---|---|
| `.el--image--small` | 25% | 30vh | 112 x 270 |
| `.el--image--medium` | 50% | 45vh | 167 x 405 |
| `.el--image--large` | 75% | 60vh | 223 x 540 |
| `.el--image--full` *(default)* | 100% | **100vh** | 297 x 719 (unchanged) |

`full`'s `100vh` encodes one rule: **an image is never taller than the screen it is displayed on.**

**Print.** `vh` is meaningless on paper, so an `@media print` block substitutes fixed heights for all
four presets. This is called out explicitly because this project shipped a print defect of exactly
this shape — `.spoiler__children` was missing from the `@media print` revert from #212 until #214
fixed it — where a screen rule had no print counterpart and content was lost in PDF output.

**Widths are percentages of the containing block**, so an image nested in a two-column or a callout
scales relative to that container rather than the page. That is the desired behaviour and must be
asserted, not assumed.

### 4. Editor control

`templates/courses/manage/editor/_edit_image.html` gains a radio group beside the existing alt and
caption fields. Radios, not a `<select>`, and they work with JS disabled — matching the pattern that
file already documents for its media control ("works no-JS, and `media_picker.js` sets/extends it
with JS").

### 5. Live preview (progressive enhancement)

The preview pane wraps each top-level element as
`<section class="prev-el" data-element-id="{{ el.pk }}">` (`_preview.html`), but a **nested** image —
inside a spoiler, tabs, two-column or callout — has no such wrapper. Nesting is the common case here
(the originating image is inside a spoiler), so the lookup hangs off `data-el-pk` on the figure
itself, which is present at every nesting depth.

One **delegated** listener on `document` swaps the class:

```js
document.addEventListener("change", (e) => {
  const r = e.target.closest("[data-size-preset]");
  if (!r) return;
  const fig = document.querySelector(`.el--image[data-el-pk="${r.dataset.forElement}"]`);
  if (fig) fig.className = `el el--image el--image--${r.value}`;
});
```

Delegation on `document` is load-bearing: `editor.js`'s `applyFragments` replaces the two
`[data-scope]` panes wholesale, so anything bound to nodes *inside* a pane dies on the next swap.
Binding to `document` means there is nothing to re-attach. A listener attached to the pane would work
until the first save and then silently stop — a defect no server-render test can see.

### 6. Click-to-enlarge

`data-zoomable` and `imagezoom.js` already provide a full-size overlay. Capping the inline size makes
that overlay the way to read a detailed diagram, so the overlay must show the image **unaffected by
the preset**. The preset classes therefore apply only to the figure's own `<img>`, never to the
overlay's.

### 7. Transfer

Three call sites, all in the image trio:

- **Export** — `_ser_image` (`courses/transfer/export.py:82-83`) returns
  `{"media", "alt", "figcaption"}`; add `"size": el.size`.
- **Validate** — `_val_image` (`courses/transfer/payloads.py:131-136`) calls
  `_exact_keys(data, ["media", "alt", "figcaption"], …)`. **Exact**, not an allowlist: an archive
  carrying an unknown key is rejected, and an archive missing a listed key is rejected too. So
  `size` cannot simply be appended to that list — that would reject every archive exported before
  this feature.
- **Import** — `_build_image` (`courses/transfer/importer.py:491-495`).

The house pattern for exactly this already exists in the same file, for iframe `width`/`height` added
in FORMAT_VERSION 2 (`payloads.py:153-156`):

> `data.setdefault("width", None)` — *"so a legacy v1 archive (which has neither) gains them and
> passes the exact-keys check, and so downstream `_build_iframe` never KeyErrors."*

`_val_image` follows it verbatim: `data.setdefault("size", "full")` **before** `_exact_keys`, then
`size` joins the exact-keys list, then the value is validated against `ImageElement.Size.values` with
an unrecognised value coerced to `"full"` rather than raising.

**`FORMAT_VERSION` bumps 6 → 7** (`courses/transfer/schema.py:14`). Back-compat is handled by
`setdefault`, but *forward* compat is not: an older install importing a new archive would hit its own
`_exact_keys` with an unexpected `size` key and fail with a confusing message. The version bump makes
that a clean, intentional rejection. (Precedent: iframe width/height bumped to 2; the tabs element
bumped 2 → 3.)

## Data flow

**Authoring.** Author opens an image element → picks a preset radio → (JS) the matching figure in the
preview pane swaps its size class immediately, no save → author saves → the form's `size` is
validated against `choices` and stored → `applyFragments` replaces both panes with the server render,
which now carries the same class.

**Consumption.** `imageelement.html` renders `el--image--<size>` on the figure; the stylesheet bounds
the `<img>`; the browser scales to fit, preserving ratio. Clicking opens the full-size overlay.

**Export.** `_ser_image` writes `size` into the element payload; the value is a plain string, so no
media registration or id remapping is involved.

**Import.** `_val_image` `setdefault`s `size` to `"full"` for older archives, validates it, and
`_build_image` passes it to the constructor.

## Error handling

Every failure path degrades to `full`, i.e. today's rendering:

| condition | behaviour |
|---|---|
| archive predates the feature (no `size` key) | `setdefault` → `"full"`; passes exact-keys; imports identically to today |
| archive carries an unrecognised value (hand-edited, or a future fifth preset) | coerced to `"full"`; **must not raise** — an import must not fail on a cosmetic field |
| a bad value submitted through the form | rejected by model `choices` validation |
| existing rows at migration time | column default `"full"`; no data migration, no back-fill |
| JS disabled or the enhancement fails | radios still submit; save-then-see still works |
| `@media print` | fixed heights substituted for `vh` |

The governing principle: **a cosmetic sizing field must never be able to fail an import.** Media
resolution can fail an import because a missing asset is a real data loss; a bad size string is not.

## Testing

Per-test falsification is required throughout — disable the code a test guards, confirm RED, restore,
and name the mutant. A passing test proves nothing on its own.

| # | what | how |
|---|---|---|
| 1 | default is `full`; `choices` rejects junk | model test |
| 2 | each of the four presets renders its class | render test, one per preset |
| 3 | `data-el-pk` is present and correct, including on a **nested** image | render test through a spoiler/callout |
| 4 | export writes `size` | transfer unit test |
| 5 | round-trip preserves all four presets | export → import, assert each |
| 6 | **an archive with no `size` key imports as `full`** | the back-compat pin; build the payload without the key |
| 7 | an archive with a junk `size` imports as `full` and does not raise | error-path pin |
| 8 | **rendered height obeys the cap at two viewport sizes** | **e2e**, `getBoundingClientRect()` at a desktop and a phone viewport |
| 9 | **the live preview changes size with no save** | **e2e**, real gesture on the radio |
| 10 | the preview enhancement still works **after a fragment swap** | **e2e**: save once, then change the preset again |
| 11 | the zoom overlay shows the image unaffected by the preset | e2e |
| 12 | a nested image scales to its container, not the page | render or e2e |
| 13 | print CSS defines all four presets | source-scan, block-extracted |

Rows 8-10 are load-bearing and cannot be replaced by source scans.

- **Row 8** must run at **two** viewports. A single-viewport test passes even if `vh` were silently
  authored as a fixed `px`, which is the specific bug worth catching.
- **Row 10** is the fragment-swap seam. It is the difference between a listener bound to `document`
  and one bound to the pane, and it is invisible to any server-render test.
- **Row 13** must extract the `@media print` block before scanning it. A file-wide scan for
  `.el--image--small` passes while the print block is empty, because the selector also appears in the
  screen rules — the exact defect shape found in #214's reveal-scope agreement test.

## Out of scope

- **Image alignment** (left/right/centre) and **text wrap** — separate features; each multiplies the
  rendered states to test.
- **Gallery/carousel and video sizing** — those sit in their own containers, which already constrain
  their contents. The pattern established here can be extended to them later.
- **Per-image custom percentages** — presets first. Widening presets → free values later is a much
  easier migration than the reverse.
- **Images in table cells (slice C2)** — the next slice. It inherits these presets; a cell image needs
  a height bound even more than a lesson image does, because height is what wrecks a table row.
- **Responsive `srcset` / `loading="lazy"`** — no `<img>` in the repo has either today. Sizing does
  not depend on them, and adding them is an orthogonal performance change.
