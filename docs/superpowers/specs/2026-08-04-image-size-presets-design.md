# Image size presets

## Purpose

An author has no way to size an image. `ImageElement` stores `media`, `alt` and `figcaption` and
nothing else (`courses/models.py:649-655`); the rendered `<figure>` carries no size hook
(`templates/courses/elements/imageelement.html:1-4`); and the only constraint anywhere is
`.el--image img { max-width: 100%; height: auto; }` (`courses/static/courses/css/courses.css:46`).
Two consequences:

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

Nested inside the existing model, alongside the current fields:

```python
class ImageElement(ElementBase):
    class Size(models.TextChoices):
        SMALL = "small", _("Small")
        MEDIUM = "medium", _("Medium")
        LARGE = "large", _("Large")
        FULL = "full", _("Full")

    media = models.ForeignKey(...)      # unchanged
    alt = models.CharField(...)         # unchanged
    figcaption = models.CharField(...)  # unchanged
    size = models.CharField(max_length=8, choices=Size.choices, default=Size.FULL)
```

`Size` is **nested** (referenced elsewhere as `ImageElement.Size.values`), matching
`CalloutElement.Kind`. Labels use `gettext_lazy` (module-level translatable strings must, per house
rule). A schema migration adds the column with `default="full"`.

**There is no data migration.** Because `full` carries a `max-height: 100dvh` (see §3), the 30
over-tall images are corrected by the CSS rule itself, and the other 1037 render byte-identically.
This is a deliberate reversal of an earlier draft that proposed defaulting to a capped preset: a
70vh default would have visibly changed **207 images (19%)** — 23 imperceptibly (<5%), 103 mildly
(5-20%), 70 noticeably (20-50%), and 11 by more than half (23+103+70+11 = 207) — to fix 10 mobile
cases. Capping only at the viewport changes exactly the images that are already broken.

### 2. Rendering — a class, not an inline style

```html
<figure class="el el--image el--image--{{ el.size }}" data-size-el="{{ el.pk }}">
  <img src="…" alt="…" data-zoomable>
```

A class, because the values are `%` of the column plus `dvh` of the viewport — not expressible as a
per-element inline style — and because it keeps all four boxes in one place.

**`data-size-el`, and deliberately NOT `data-element-id`.** The editor keys on `data-element-id`
(`_preview.html`'s `.prev-el`, `_element_row.html`, `editor.js` `:149`/`:189`/`:382`), so reusing it
here looks like the consistent choice. It is not, because that attribute has a **second consumer on
student pages**:

- `progress.js:52` runs `document.querySelectorAll("[data-element-id]")` — **unscoped by class,
  across the whole document** — and observes each match to build the "seen" set POSTed to `/seen/`.
- `slideshow.js:119-120` does the same per slide.
- `views.py:709-713` states the invariant outright: *"the frontend only reports
  `.lesson-block[data-element-id]` ids, which `_lesson_article.html` emits for top-level elements
  only. A nested pk here could never be satisfied, so the unit would never complete."*

**No element template emits `data-element-id` today** — verified by grep across
`templates/courses/elements/*.html`. `imageelement.html` renders on student lesson and quiz pages
via the same `render_element` tag as the preview pane, so putting `data-element-id` on the figure
would make this the first element to break that invariant: every image would be observed by
`progress.js`, top-level images would be reported twice, and a *nested* image's pk would enter the
`/seen/` payload where `_seen_current_ids` (`parent__isnull=True`) silently discards it. Harmless
today only by server-side filtering, not by design — and a latent trap if that filter ever changes.

A distinct name avoids all of it: the purposes genuinely differ (element identity for progress
tracking vs. a preview-target hook), and `data-size-el` is invisible to every existing consumer.
**Do not "unify" these two attributes later** — that is the bug, not the cleanup.

### 3. CSS — four bounding boxes

The prose column is `46rem` (`courses.css:181`, `.lesson { max-width: 46rem }`), i.e. 736px at a
16px root.

**The base rule is folded into the presets, not left to compete with them.** The existing
`.el--image img { max-width: 100%; height: auto; }` (`courses.css:46`) has *identical* specificity to
a new `.el--image--small img` rule (one class + a descendant type selector), so which one won would
be decided purely by source order — and a future reorganisation of the stylesheet could silently
revert small/medium/large to unbounded width. The implementation therefore replaces the base rule
with one rule-set in which each preset carries its own complete box, and `height: auto` is stated
once for `.el--image img`.

| class | max-width | max-height | tall image (297x719) renders as* |
|---|---|---|---|
| `.el--image--small` | 25% | 30dvh | 112 x 270 |
| `.el--image--medium` | 50% | 45dvh | 167 x 405 |
| `.el--image--large` | 75% | 60dvh | 223 x 540 |
| `.el--image--full` *(default)* | 100% | **100dvh** | 297 x 719 (unchanged) |

\* computed at a **900px-tall desktop viewport**, the same window height used in the measurements above.

`full`'s `100dvh` encodes one rule: **an image is never taller than the screen it is displayed on.**

**`dvh`, not `vh` — this codebase has already settled this question.** The imagezoom overlay uses
`height: 100dvh` with the comment *"vertical from 100dvh, which tracks a mobile collapsing toolbar"*
(`courses.css:1724-1727`). Plain `vh` resolves against the *toolbar-collapsed* viewport, so on a
phone with the address bar showing, a `100vh`-capped image can still fall below the fold — exactly
the 10-case defect this feature exists to fix. Using `vh` here would reintroduce the bug the overlay
already avoids two rules away in the same file.

This does **not** contradict the slide stage's rejection of viewport units (`courses.css:259-262`).
That case rejected `calc(100dvh - chrome)` because the *chrome offset* is not a constant (measured
325-546px across title length and window width). A bare `max-height: Ndvh` subtracts nothing and has
no such problem.

**Print.** `dvh` is meaningless on paper, so an `@media print` block substitutes physical heights.
There is no existing print-sizing precedent in this repo to inherit (no `@media print` rule fixes an
image height today), so the values are stated here rather than left to the implementer:

| class | print max-height |
|---|---|
| `.el--image--small` | 45mm |
| `.el--image--medium` | 75mm |
| `.el--image--large` | 110mm |
| `.el--image--full` | 170mm |

Derivation: A4 is 297mm tall; with this project's page margins roughly 250mm is printable. `full` at
170mm leaves ~80mm for surrounding text so an image never monopolises a page. The three smaller
presets step down from it in the same *order and rough spacing* as on screen — deliberately not an
exact ratio transfer (as fractions of `full` they are 26%/44%/65% against the screen's 30%/45%/60%),
because these are round millimetre values chosen to be sensible on paper rather than derived
arithmetically from the screen boxes. Max-widths stay percentages, which behave correctly in print. This is called out explicitly because this project shipped a print defect
of exactly this shape — `.spoiler__children` was missing from the `@media print` revert from #212
until #214 fixed it — where a screen rule had no print counterpart and content was lost in PDF.

**Widths are percentages of the containing block**, so an image nested in a spoiler, tabs,
two-column or callout scales relative to that container rather than the page. That is the desired
behaviour and must be asserted, not assumed (see testing row 12).

### 4. Editor control

**4a. The form must accept the field, or nothing else in this section matters.**
`ImageElementForm.Meta.fields` is a hardcoded literal `["media", "alt", "figcaption"]`
(`courses/element_forms.py:118-120`), consumed via `FORM_FOR_TYPE["image"]` on both the render path
(`views_manage.py:1446`, `:1728`) and the save path (`builder.py:959`). A Django `ModelForm`
binds, validates and persists **only** the fields named there; POST data for any other name is
silently discarded. So the list must become:

```python
fields = ["media", "alt", "figcaption", "size"]
```

mirroring `CalloutElementForm.Meta.fields = ["kind", "heading", "body"]` (`element_forms.py:228`),
the directly analogous choice field. Without this edit the radios render, the author picks one,
the save succeeds — and `size` is silently dropped. The feature would no-op with no error anywhere,
and the Error-handling row "a bad value submitted through the form → rejected by model `choices`
validation" could never fire, because the form would never look at `size` at all.

**4b. The control.** `templates/courses/manage/editor/_edit_image.html` gains a radio group beside
the existing alt and caption fields. Radios, not a `<select>`, and they work with JS disabled —
matching the pattern that file already documents for its media control ("works no-JS, and
`media_picker.js` sets/extends it with JS").

The group **must reflect the stored value as `checked`**, looping over the field's own choices so
the four presets are never duplicated between Python and template:

```html
{% for value, label in form.fields.size.choices %}
  <label><input type="radio" name="size" value="{{ value }}"
    {% if form.size.value|stringformat:"s" == value|stringformat:"s" %} checked{% endif %}
    data-size-preset data-for-element="{{ form.instance.pk }}"> {{ label }}</label>
{% endfor %}
```

The `stringformat:"s"` comparison mirrors `_edit_callout.html:6`, which reflects the stored
`CalloutElement.kind` the same way.

**`checked` is not cosmetic — omitting it breaks every image save.** `size` derives from a
non-`blank` `CharField`, so its form field is `required=True`. A radio group with nothing checked
submits **no** `size` key, so the form fails validation on *any* save of an image element — even an
alt-text-only edit — once 4a is applied. Two independent reasons this must be specified: an author
must see the element's current preset, and a freshly-opened element must render with the model
default `full` already checked via `form.instance.size`.

**4c. The two live-preview attributes**, carried by every radio above:

- `data-size-preset` — the hook the delegated listener matches on (a marker attribute, no value).
- `data-for-element` — the element pk, so the listener can find the matching rendered `<figure>`
  by its `data-size-el` (see §2 for why that is not `data-element-id`).

Without both attributes the enhancement in §5 silently does nothing, so they are part of this
section's contract, not an implementation detail.

### 5. Live preview (progressive enhancement)

The preview pane wraps each **top-level** element as
`<section class="prev-el" data-element-id="{{ el.pk }}">` (`_preview.html`), but a **nested** image —
inside a spoiler, tabs, two-column or callout — has no such wrapper. Nesting is the common case here
(the originating image is inside a spoiler), which is why §2 puts `data-size-el` on the figure
itself, where it is present at every nesting depth.

**On the create flow the live preview is inertly a no-op.** `views_manage.py:1437-1446` builds the
create form as `FORM_FOR_TYPE[type_key](initial=…)` with **no `instance`**, so `form.instance.pk` is
`None` and the radios render `data-for-element=""`. There is also no `<figure>` in the preview pane
yet, because the element does not exist in the DB. The `if (fig)` guard makes this a silent no-op,
which is the correct behaviour — the author sees the chosen size on first save. Testing rows 9 and
10 therefore exercise the **edit-an-existing-element** flow; a test written against the create flow
expecting a visible size change would be asserting a bug.

**The size branch extends the existing delegated handler**, rather than adding a second listener.
`editor.js` already establishes `var root = document.querySelector(".editor")` (`:3`) and already
runs a delegated `root.addEventListener("change", …)` (`:462`) which survives `applyFragments`' pane
swaps. `.editor` (`editor.html:11`) wraps both `[data-scope]` panes, so a radio inside the editor
pane is within its subtree. Reusing it keeps one change-handler in the file:

```js
var preset = e.target.closest("[data-size-preset]");
if (preset) {
  var fig = document.querySelector(
    '.el--image[data-size-el="' + preset.dataset.forElement + '"]'
  );
  if (fig) {
    fig.classList.remove(
      "el--image--small", "el--image--medium", "el--image--large", "el--image--full"
    );
    fig.classList.add("el--image--" + preset.value);
  }
}
```

`classList.remove/add` on just the `el--image--*` token, **not** `fig.className = …`, so the swap
cannot clobber any other class the figure carries now or later.

Delegation is load-bearing: `applyFragments` replaces the two `[data-scope]` panes wholesale, so
anything bound to nodes *inside* a pane dies on the next swap. A listener attached to a pane would
work until the first save and then silently stop — a defect no server-render test can see.

### 6. Click-to-enlarge

`data-zoomable` and `imagezoom.js` already provide a full-size overlay. Capping the inline size makes
that overlay the way to read a detailed diagram, so the overlay must show the image **unaffected by
the preset**. The preset classes apply only to the figure's own `<img>`, never to the overlay's.

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
an unrecognised value coerced to `"full"` (see Error handling for why this differs from `kind`).

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
| archive carries an unrecognised value (hand-edited, or a future fifth preset) | coerced to `"full"`; **must not raise** |
| a bad value submitted through the form | rejected by model `choices` validation |
| existing rows at migration time | column default `"full"`; no data migration, no back-fill |
| JS disabled or the enhancement fails | radios still submit; save-then-see still works |
| `@media print` | physical heights substituted for `dvh` |

**Why `size` coerces where `kind` raises.** `_val_callout` rejects an unknown `CalloutElement.Kind`
outright (`payloads.py:201-202`). The divergence is deliberate: a callout's `kind` selects a distinct
visual treatment (colour, icon, semantics) with **no safe fallback** — silently importing an
"important" callout as a "note" would misrepresent the author's meaning. `size` has a safe fallback
by construction: `full` *is* the pre-feature rendering, so coercing loses nothing an older install
would have shown anyway. The governing principle: **a cosmetic field with a lossless default must
never fail an import; a field whose default changes meaning must.**

## Testing

Per-test falsification is required throughout — disable the code a test guards, confirm RED, restore,
and name the mutant. A passing test proves nothing on its own.

| # | what | how |
|---|---|---|
| 1 | default is `full`; `choices` rejects junk | model test |
| 2 | each of the four presets renders its class | render test, one per preset |
| 3 | `data-size-el` is present and correct on the figure, including on a **nested** image | render test through a spoiler/callout |
| 3b | **the figure does NOT carry `data-element-id`** on a student page | render test — guards the `progress.js` invariant against a future "unify the attributes" cleanup |
| 3c | a nested image's pk is absent from `_seen_current_ids` | pins the `parent__isnull=True` filter that makes 3b's invariant safe |
| 4 | export writes `size` | transfer unit test |
| 5 | round-trip preserves all four presets | export → import, assert each |
| 6 | **an archive with no `size` key imports as `full`** | the back-compat pin; build the payload without the key |
| 7 | an archive with a junk `size` imports as `full` and does not raise | error-path pin |
| 8 | **each of the four presets' computed box is correct, at two viewport sizes** | **e2e**, `getBoundingClientRect()` per preset at a desktop and a phone viewport |
| 9 | **the live preview changes size with no save** | **e2e**, real gesture on the radio |
| 10 | the preview enhancement still works **after a fragment swap** | **e2e**: save once, then change the preset again |
| 11 | the zoom overlay shows the image unaffected by the preset | e2e |
| 12 | a nested image scales to its container in **all four** containers — spoiler, tabs, two-column, callout | render or e2e, one case each |
| 13 | print CSS defines all four presets | source-scan, block-extracted |
| 14 | the radios carry `data-size-preset` and `data-for-element` | render test — the §4/§5 contract |
| 15 | the stored preset renders as the `checked` radio; a fresh element shows `full` checked | render test — the §4b contract |
| 16 | an alt-text-only save of an image element still succeeds | regression pin for §4b's required-field trap |

Rows 8-10 are load-bearing and cannot be replaced by source scans.

- **Row 8's two viewports are pinned**, so its expected values are computable and reviewable rather
  than left to the implementer: **desktop 1280x900** (the 900px height the §3 table is footnoted
  against) and **phone 360x640**. At the phone viewport the `dvh` caps resolve to
  small 192px / medium 288px / large 384px / full 640px. The width caps resolve against the
  *containing block*, not the viewport, so the test asserts **whichever constraint binds** for the
  fixture image rather than a fixed width number.
- **Row 8** must run at **two** viewports. A single-viewport test passes even if the cap were
  silently authored as a fixed `px`, which is that row's specific target.
- **Row 8 must exercise all four presets, not one representative.** Row 2 only asserts that the
  right *class* is applied; it cannot see a wrong *value* in the CSS. Row 8 is the only row that
  measures computed pixels, so if it exercised only `full` (the preset tied to the original bug), a
  transposed number in `small`, `medium` or `large` — `45dvh` where `60dvh` was meant, or `50%` for
  `75%` — would ship with no coverage anywhere in the suite.
- **Row 8's known limit:** Playwright's phone viewport is a fixed pixel size and does **not** emulate
  a collapsing mobile address bar, so this row **cannot** distinguish `dvh` from `vh`. That choice is
  argued from the `courses.css:1724-1727` precedent, not pinned by a test. Accepted gap; verify once
  by hand on a real mobile browser with the address bar visible.
- **Row 10** is the fragment-swap seam — the difference between extending `editor.js`'s `root`
  handler and binding to a pane. Invisible to any server-render test.
- **Row 12** enumerates all four containers deliberately. This project's recorded lesson is that
  newly-legal combinations must be enumerated, not sampled.
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
