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

### The real content width — derive it from the shell, not from `.lesson`

Every measurement below depends on the width of the box an image actually renders into, and the
obvious answer is wrong. `courses.css:181` says `.lesson { max-width: 46rem }` (736px), but
`lesson_unit.html:55` routes **every** unit through `_unit_shell.html`, and `courses.css:545-546`
then overrides it: `.unit-shell__main > .lesson, .unit-shell__main > .quiz { max-width: none;
margin-inline: 0; padding: 1.25rem 1.5rem; }`. The 46rem cap is reintroduced only under
`html.unit-tree-collapsed [data-unit-shell]` for a selector allow-list (`courses.css:960-973`) that
does **not** include `.el--image` — so an image is never prose-capped, in either TOC state.

There is one more wrapper outside the shell, and it binds before `.unit-shell` does. `base.html:147`
puts `{% block content %}` inside `<main class="app-main">`, and `app.css:34` caps that at
`max-width: 960px` with `padding: var(--space-8) var(--space-5)` (20px inline, dropping to
`var(--space-4)` = 16px at ≤640px, `app.css:246`). `lesson_unit.html` never overrides
`{% block main_class %}`, and the only `.app-main` widening anywhere is
`body.editor-page .app-main { max-width: 102rem }` (`editor.css:36`) — the **editor**, not the lesson
page. So `.unit-shell`'s 72rem cap **never binds** on a lesson.

The real content box, at the pinned 1280px desktop viewport with the TOC shown:

```
.app-main     max-width 960px      =  960px   (app.css:34)
.app-main     padding 20px x 2     = - 40px   (app.css:34)
                                     -------
                                       920px   (so .unit-shell's 72rem = 1152px never binds)
.unit-tree    flex 0 0 14rem       = -224px   (courses.css:548)
.lesson       padding 1.5rem x 2   = - 48px   (courses.css:546)
                                     -------
content box                           648px
```

On a phone (≤640px) `.unit-shell` becomes `display: block`, `.unit-tree` is hidden, `.app-main`
padding drops to 16px and `.lesson` padding to `1rem`, giving `360 − 32 − 32 =` **296px** at a 360px
viewport.

**Use 648px / 296px.** This spec has been wrong twice about this number. The first draft measured
against `.lesson`'s nominal 736px; a later one corrected to 880px by deriving from `.unit-shell` —
but still omitted `.app-main`, which caps the page outside the shell. **648px is the derivation with
every wrapper accounted for**, confirmed during plan-review of this slice and pinned at runtime by the
e2e tests (which read the column from `fig.parentElement` rather than hardcoding any of these).

### Measured evidence (1067 images with a readable file, local `libli` DB, 2026-08-04)

> **⚠ These counts were measured against the superseded 880px column and are an UPPER BOUND.**
> They have **not** been re-measured at the correct 648px. Do not quote them as current figures —
> see "Direction of the error" below, which is derivable from this section's own data.

Measured at the (superseded) **880px** content box:

| fact | count at 880px |
|---|---|
| wide or square | 1042 |
| tall (h/w > 1.5) | 25 |
| render taller than a 900px desktop window | 54 |
| overflow a 640px phone viewport | 10 |

Rendered-height percentiles at the 880px column: p50 550px, p75 690px, p90 835px, p95 903px,
p99 1306px, max 1546px. The worst source images are `494x1492` (h/w 3.0).

**Direction of the error.** The same query against 736px reported **30** over-tall images and
p50 466 / p95 804 / max 1492. So widening the assumed column 736 → 880 *raised* the count 30 → 54: a
wider column scales a too-wide image to a **greater** rendered height. The true column is **648px** —
narrower than both — so at the real width the over-tall count is **lower than 54, and lower than 30**.
The counts above overstate the defect; they do not understate it.

This does **not** weaken the design, for two reasons that do not depend on the count:

1. **The tall images that motivate the feature are unaffected by column width.** A tall image narrower
   than the column (the originating case is `297x719`, and the worst is `494x1492`) is never scaled by
   `max-width: 100%` at 648px, 736px or 880px — it renders at its intrinsic height in all three. The
   `max-height: 100dvh` floor is what bounds it, and that is viewport-relative, not column-relative.
2. **The primary justification is authorial control, not the defect count** (see §Purpose): today an
   author has no way to size an image at all and must guess dimensions before seeing the result.

**Re-measuring is a known outstanding item**, deliberately not done here to keep this a documentation
correction. Anyone quoting a count must re-run the corpus query at 648px first.

The originating report was unit 1095 ("Pierwiastek - wyłączanie i włączanie"), whose first spoiler
holds `czynnik_przed_pierwiastek_1.png` at **297x719** (h/w 2.42, element pk 1082) — fine on desktop,
taller than the viewport on a phone. Its sibling `czynnik_przed_pierwiastek_2.png` at 948x719 is
already fine on mobile, because it is wide enough for `max-width` to shrink it. That contrast is the
whole problem in one spoiler: **width-only constraints do not bound a tall image.**

### Why presets are bounding boxes, not widths

A width-only preset does not produce comparable visual sizes across aspect ratios. At "medium = 50%
of the 648px column" (324px):

| aspect | renders as | verdict |
|---|---|---|
| 1:3 tall | 324 x 972 | dominates the page — taller than any laptop screen |
| 2:1 wide | 324 x 162 | fine |

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
        # pgettext, NOT a bare _(): the msgid "Full" is already taken by the
        # structure-preset label at courses/forms.py:166, whose Polish is the
        # feminine "Pełna". Django keys the catalog by msgid alone, so a bare
        # _("Full") here ships one of the two ungrammatical. The context forks it.
        FULL = "full", pgettext_lazy("image size", "Full")

    media = models.ForeignKey(...)      # unchanged
    alt = models.CharField(...)         # unchanged
    figcaption = models.CharField(...)  # unchanged
    size = models.CharField(max_length=8, choices=Size.choices, default=Size.FULL)
```

`Size` is **nested** (referenced elsewhere as `ImageElement.Size.values`), matching
`CalloutElement.Kind`. Labels use `gettext_lazy` (module-level translatable strings must, per house
rule). A schema migration adds the column with `default="full"`.

**There is no data migration.** Because `full` carries a `max-height: 100dvh` (see §3), every
over-tall image is corrected by the CSS rule itself, and the rest render byte-identically. (The
54/1013 split quoted in earlier drafts came from the superseded 880px measurement — see the warning
in §Purpose. The *mechanism* is independent of the count.)
This is a deliberate reversal of an earlier draft that proposed defaulting to a capped preset: at the
then-assumed 880px column a 70vh default would have visibly changed **370 images (35%)** — 43 imperceptibly
(<5%), 156 mildly (5-20%), 159 noticeably (20-50%), and 12 by more than half (43+156+159+12 = 370) —
to fix 10 mobile cases. Capping only at the viewport changes exactly the images that are already
broken. (Re-measuring at the correct column made this argument *stronger*: against the wrong 736px
figure the same comparison read 207 images / 19%.)

### 2. Rendering — a class, not an inline style

```html
<figure class="el el--image el--image--{{ el.size }}" data-preview-el="{{ el.pk }}">
  <img src="…" alt="…" data-zoomable>
```

A class, because the values are `%` of the column plus `dvh` of the viewport — not expressible as a
per-element inline style — and because it keeps all four boxes in one place.

**`data-preview-el`, and deliberately NOT `data-element-id`.** The editor keys on `data-element-id`
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
tracking vs. a preview-target hook), and `data-preview-el` is invisible to every existing consumer.
**Do not "unify" these two attributes later** — that is the bug, not the cleanup.

### 3. CSS — four bounding boxes

Percentages resolve against the **containing block**, which for a top-level image is the `.lesson`
content box derived in §Purpose — **648px** at the pinned desktop viewport, not `.lesson`'s nominal
`46rem`. The percentages below are correct regardless (they are relative by construction); the
figure matters only for computing expected pixel values in tests, which is why row 8 measures the
container at runtime rather than hardcoding a width.

**The two axes live on different elements, which is what keeps them out of each other's way.**
`max-width` goes on the **figure** selector (`.el--image--small`, …) as a percentage of `.lesson`'s
definite content box; `max-height` goes on the **img** selector (`.el--image--small img`, …) in
`dvh`. The existing base rule `.el--image img { max-width: 100%; height: auto; }`
(`courses.css:46`) is **retained unchanged** and shared by all four presets.

That split also dissolves a specificity trap that an earlier draft of this spec had to work around:
`.el--image img` and `.el--image--small img` tie on specificity (one class + a descendant type
selector), so had per-preset `max-width` stayed on the `img`, which rule won would have been decided
purely by source order. With `max-width` on the figure there is no competing base rule on that
property at all, so nothing depends on ordering. (The `@media print` block is a separate matter and
*does* still depend on source order — see Print below.)

| class | max-width | max-height | tall image (297x719) renders as* |
|---|---|---|---|
| `.el--image--small` | 25% | 30dvh | 112 x 270 |
| `.el--image--medium` | 50% | 45dvh | 167 x 405 |
| `.el--image--large` | 75% | 60dvh | 223 x 540 |
| `.el--image--full` *(default)* | 100% | **100dvh** | 297 x 719 (unchanged) |

\* computed at a **900px-tall desktop viewport**, the same window height used in the measurements above.

`full`'s `100dvh` encodes one rule: **an image is never taller than the screen it is displayed on.**

#### The `<figure>` box must be constrained too, or a capped image sits in a full-width shell

Bounding only the `<img>` is not enough. `<figure>` is a block box, and **no rule in this stylesheet
sizes it** — the only two rules touching `.el--image` today are `.el { margin: 1rem 0 }`
(`courses.css:4`) and `.el--image img { max-width: 100%; height: auto }` (`:46`), and there is **no
`figcaption` rule anywhere**. So a `small` image would render at 25% width flush against the *left*
edge of a figure still spanning the full 648px, with a lake of white space to its right — and a
`<figcaption>`, an unconstrained sibling in that full-width figure, would wrap at 648px while sitting
under a 162px image. This project has already been bitten by the same shape: the imagezoom overlay's
comment at `courses.css:1729-1734` describes a dialog that "collapses to a fit-content box flush
LEFT."

The remedy, and one subtlety that dictates its shape:

```css
/* max-width lives on the FIGURE, not the img: a percentage on the img would resolve
   against a figure that is itself being sized to fit the img — circular. On the figure
   it resolves against .lesson's content box, which has a definite width. */
.el--image--small  { max-width: 25%; }
.el--image--medium { max-width: 50%; }
.el--image--large  { max-width: 75%; }
/* MUST be appended AFTER `.el { margin: 1rem 0 }` (courses.css:4): `.el` and
   `.el--image--small` are both single-class selectors on this same figure, so
   they tie on specificity and `margin-inline: auto` wins the horizontal margin
   only on source order — the same trap as the print block below. */
.el--image--small,
.el--image--medium,
.el--image--large  { width: fit-content; margin-inline: auto; }

/* Centre the image WITHIN the figure. Load-bearing whenever a figcaption is
   present: `fit-content` sizes the figure to the WIDER of {image, caption}
   max-content contributions, so a long caption widens the figure past the
   image and the image would otherwise sit flush left inside it. Scoped to the
   capped presets so `full` keeps today's flush-left geometry. */
.el--image--small  img,
.el--image--medium img,
.el--image--large  img { display: block; margin-inline: auto; }

.el--image img { max-width: 100%; height: auto; }
.el--image--small  img { max-height: 30dvh; }
.el--image--medium img { max-height: 45dvh; }
.el--image--large  img { max-height: 60dvh; }
.el--image--full   img { max-height: 100dvh; }
```

**Why the image needs its own centring, measured.** `width: fit-content` resolves to the *maximum*
of the children's max-content contributions, clamped by the figure's `max-width`. A `<figcaption>`
has no width constraint of its own, so its contribution is its **unwrapped** text width. Measured
across the corpus: **104 of 1068 images (9.7%) carry a caption** — 1068 is every `ImageElement` row,
one more than the 1067 in the sizing table above, because that one's media file is unreadable and so
is excluded from pixel measurement but not from a caption count — median length **9 characters**
(~63px, narrower than any capped image, so the figure tracks the image) — but the tail is real, with
captions of **212, 200, 132, 123 and 122 characters**. At `small`, a 200-character caption's
max-content (~1400px) is clamped to the 220px preset cap, so the figure becomes 220px while a tall
image renders 112px — leaving the image flush left with a ~108px gap. `margin-inline: auto` on the
image removes that in every case, whichever child drives the width.

**`full` is deliberately excluded from the `fit-content` / `margin-inline` rule.** Today a 297px-wide
image sits flush left inside a full-width figure; giving `full` a shrink-wrapped, centred figure
would *move* it — silently re-laying-out images this spec promises render byte-identically, and
voiding the "no data migration" guarantee that rests on exactly that. `full` keeps today's geometry;
only the three capped presets, which are opt-in and new, get the shrink-wrapped centred figure.

This is **not** the deferred author-controlled alignment feature. It is what an image looks like the
moment any capped preset is applied, which is not optional.

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

**Placement is load-bearing: the `@media print` block MUST come after the preset rule-set.**
`@media print { .el--image--small img { max-height: 45mm } }` has *identical* specificity to the
screen rule `.el--image--small img { max-height: 30dvh }` — **a media query adds no specificity** —
so the winner is decided purely by source order. Put the print block first and every preset prints
at its `dvh` value, which on paper resolves against nothing useful.

This is not hypothetical: `courses.css:942-945` carries a comment about precisely this trap —
*"this block MUST stay after it: … media queries add no specificity, so the reveal would win and the
pin would print anyway."* And `@media print` blocks in this stylesheet are scattered (`:822`,
`:947`, `:1476`, `:1813`), so there is no ambient end-of-file convention to fall back on. The
implementation must place the block after the presets and carry a comment saying why, in the style
of `:942-945`.

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
the existing alt and caption fields.

**Radios rather than a `<select>`** because all four options stay visible at once and a single click
both selects and triggers the live preview — with a dropdown the author would open it, scrub through
options, and only see the result after committing. (This is *not* justified by the file's media
control: that is itself a `<select>` — `_edit_image.html:3` says so explicitly — and a `<select>`
works with JS disabled exactly as well as radios do. Both widgets are no-JS-safe; the reason to pick
radios here is the at-a-glance comparison, not progressive enhancement.)

The group is wrapped in a `<fieldset>` with a `<legend>`, so a screen-reader user hears the group's
name and not just four bare option labels, and it **must reflect the stored value as `checked`**,
looping over the field's own choices so the four presets are never duplicated between Python and
template:

```html
<fieldset class="size-presets">
  <legend>{% trans "Size" %}</legend>
  {% for value, label in form.fields.size.choices %}
    <label><input type="radio" name="size" value="{{ value }}"
      {% if form.size.value|stringformat:"s" == value|stringformat:"s" %} checked{% endif %}
      data-size-preset data-for-element="{{ form.instance.pk }}"> {{ label }}</label>
  {% endfor %}
</fieldset>
```

The `stringformat:"s"` comparison mirrors `_edit_callout.html:6`, which reflects the stored
`CalloutElement.kind` the same way.

**`checked` is not cosmetic — omitting it breaks every image save.** `size` derives from a
non-`blank` `CharField`, so its form field is `required=True`. A radio group with nothing checked
submits **no** `size` key, so the form fails validation on *any* save of an image element — even an
alt-text-only edit — once 4a is applied. Two independent reasons this must be specified: an author
must see the element's current preset, and a freshly-opened element must render with the model
default `full` already checked — via **`form.size.value`**, the same path the snippet above compares
against. On an unbound `ModelForm` that resolves through a freshly-constructed `ImageElement()`
whose `size` already carries the field default, so no extra initial-value logic is needed. (Do not
reach for `form.instance.size` here; the template compares `form.size.value`, and mixing the two is
how the checked state and the submitted value drift apart.)

**4c. The two live-preview attributes**, carried by every radio above:

- `data-size-preset` — the hook the delegated listener matches on (a marker attribute, no value).
- `data-for-element` — the element pk, so the listener can find the matching rendered `<figure>`
  by its `data-preview-el` (see §2 for why that is not `data-element-id`).

Without both attributes the enhancement in §5 silently does nothing, so they are part of this
section's contract, not an implementation detail.

### 5. Live preview (progressive enhancement)

The preview pane wraps each **top-level** element as
`<section class="prev-el" data-element-id="{{ el.pk }}">` (`_preview.html`), but a **nested** image —
inside a spoiler, tabs, two-column or callout — has no such wrapper. Nesting is the common case here
(the originating image is inside a spoiler), which is why §2 puts `data-preview-el` on the figure
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
    '.el--image[data-preview-el="' + preset.dataset.forElement + '"]'
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
in FORMAT_VERSION 2 (`payloads.py:153-157` — the rationale comment at `:153`, the two `setdefault` calls at `:156-157`):

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

Three of the rows below degrade to `full` (today's rendering); the other three are **not** failures
and must not be conflated with them — a bad form value is *rejected*, not silently coerced, and the
JS-disabled and print rows are simply different valid rendering paths. The distinction matters: a
reader who took "everything degrades to `full`" literally might make the form coerce instead of
validate, which would let a typo in a POST silently resize an image.

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
| 3 | `data-preview-el` is present and correct on the figure, including on a **nested** image | render test through a spoiler/callout |
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
| 13b | **under print media the RESOLVED `max-height` is the mm value, not the `dvh` one** | **e2e**, `page.emulate_media(media="print")` then read the computed style per preset |
| 14 | the radios carry `data-size-preset` and `data-for-element` | render test — the §4/§5 contract |
| 15 | the stored preset renders as the `checked` radio; a fresh element shows `full` checked | render test — the §4b contract |
| 16 | an alt-text-only save of an image element still succeeds | regression pin for §4b's required-field trap |
| 17 | under a capped preset the image is **centred within its figure**, with a **long** caption present | **e2e** — must use a caption long enough to drive `fit-content` past the image (the corpus has 212/200/132-char captions); a short caption cannot exercise this |
| 18 | **`full` figure geometry is unchanged** — same box and offset as before the feature | **e2e**, the guard on the byte-identical promise for the 1013 untouched images |
| 19 | under a capped preset the **`<figure>` itself is centred in the column**, on a fixture with **no caption** | **e2e** — assert roughly equal left/right offset from the `.lesson` edges. This is the only row covering the round-7 fix; rows 8/17/18 all pass with the figure rule missing entirely |

Rows 8-10 are load-bearing and cannot be replaced by source scans.

- **Row 8's two viewports are pinned**, so its expected values are computable and reviewable rather
  than left to the implementer: **desktop 1280x900** (the 900px height the §3 table is footnoted
  against) and **phone 360x640**. At the phone viewport the `dvh` caps resolve to
  small 192px / medium 288px / large 384px / full 640px.
- **Row 8 needs TWO fixtures — one tall, one wide — or the width caps are never tested.** For the
  tall fixture (297x719) the height cap binds first at *every* preset, so `max-width` is dead weight
  in the measurement: shipping `small` as `35%` instead of `25%` would not move the rendered box by
  a pixel. Pair it with a wide fixture — **948x719**, the real sibling image from the same spoiler in
  unit 1095 — where the width cap binds instead. One tall + one wide per preset per viewport is what
  makes both numbers in each bounding box load-bearing.
- **Row 8 must read the container width at runtime**, not hardcode one.
  `.unit-shell__main > .lesson` overrides `.lesson`'s nominal `46rem` (§Purpose), so the content box
  is 648px on desktop and 296px on a phone (§Purpose) — and all of them depend on `.app-main`, the
  shell, the TOC state and the padding, every one of which can change. Assert the image against
  `container.getBoundingClientRect().width * <preset fraction>`, so the test keeps testing the
  preset rather than silently re-encoding today's layout. A hardcoded 736, 880 or 648 would make this
  row fail the next time the shell is touched, for a reason that has nothing to do with sizing.
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
- **Row 13 alone is not sufficient, which is why 13b exists.** A source-scan proves the print rule is
  *present*; it cannot prove the print rule *wins*. Since the print and screen declarations tie on
  specificity, a print block placed above the presets would leave row 13 green while every image
  printed at its `dvh` height. Only reading the resolved value under emulated print media catches it.

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
