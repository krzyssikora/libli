# Image "Float right"

## Purpose

A lesson image always sits on its own line, centred (`.el--image--*` presets,
`courses.css` "Image size presets" block). A small illustration that belongs with a
paragraph cannot sit beside it, as it did in the LAL source. Reported case: unit 914
(mat-pp, "Reguła mnożenia 2"), Task 2 — the flag (`flaga3.png`, element 15752) was
`<div style="float: right"><img style="width: 200px">` beside two paragraphs in
`LAL/html/130_kombinatoryka/030_kombinatoryka.html`; in libli it renders Full, on its own row.

Workarounds rejected by the owner: a two-column element (columns are always equal width,
2-4 of them, and cannot be merged — the image column cannot be made narrow) and a table
(no merged-column width control).

**Goal:** an author ticks "Float right" on a Small or Medium image; the image sits at the
right of its column and the following text wraps beside it, on desktop and on a phone.

## Owner decisions (VERBATIM intent — do not reverse in review)

| # | Decision |
|---|----------|
| D1 | A per-image **"Float right"** checkbox, beside the size radios. |
| D2 | Offered for **Small and Medium only**. For Large/Full it is disabled, and a stored `true` is IGNORED at render. |
| D3 | **Wrap rule (a):** text and maths elements wrap beside the floated image; **headings and every non-text element start below it**. (Not "only the next element wraps": Task 2's text is TWO text elements, and the second must wrap too.) |
| D4 | Works at the **top level AND inside containers** (callout, tabs, two-column, spoiler, before/after). A floated image never escapes its container. |
| D5 | **Medium falls back** to today's centred, own-line layout when less than ~12rem (192px) would remain for text beside it. Measured against the box the image sits in, not the viewport. Small always floats. |
| D6 | The whole **top-level block** floats (`section.lesson-block`, carrying its notes handle), not just the `<figure>`. Floating the figure alone put the notes handle on top of the image (mockup round 1). |
| D7 | Below the 1200px notes rail, a text block's in-flow notes handle sits at the float's left edge, beside its paragraph. **Accepted as is** — any in-flow placement is beside the float, and clearing it would stop the following text wrapping. |
| D8 | At ≥1200px (notes rail), the floated block's handle must not stack on the handle of the paragraph beside it (mockup at 1300px: ~14px apart). Fix required. |
| D9 | Print keeps the float. |
| D10 | Off by default; every existing image renders exactly as today. No LAL-importer change; the owner ticks the box by hand. |

## Mockup evidence (2026-10-07)

A copy of the real unit 914 page with the real stylesheets plus three throwaway rules
(scratchpad only, nothing committed):

```css
.lesson-block:has(> .lesson-block__body > .el--image--float){float:right;width:25%;margin:0 0 var(--space-3) var(--space-4);}
.lesson-block > .lesson-block__body > .el--image--float{max-width:100%;margin:0 0 1rem;}
.lesson-block:not(:has(> .lesson-block__body > .el--text)),
.lesson-block:has(> .lesson-block__body > .el--text > :is(h2,h3,h4)){clear:right;}
```

- 367px phone: flag ~76px, text beside it ~30 characters per line, second paragraph full width
  under it, the spoiler below everything. Dark plate fine.
- 1300px (`notes-js`): flag ~160px beside the first paragraph; the two notes handles in the
  rail ~14px apart (D8).
- `margin-bottom: 1rem` on the figure is load-bearing: `.block-notes { margin-top: -1rem }`
  (`notes.css`) otherwise pulls the in-flow handle up onto the image.

The owner approved the look.

## Design

### Data

- `ImageElement.float_right = models.BooleanField(default=False)`; migration `0069`.
- An "effective float" is `float_right and size in {small, medium}`, exposed as a model property
  (e.g. `ImageElement.floats`) so the template and tests share one definition (D2).

### Editor

- `ImageElementForm.Meta.fields` gains `float_right`. `clean()` forces `float_right = False`
  when the size is Large or Full, so a disabled (therefore unsubmitted) checkbox and a
  hand-crafted POST agree.
- `_edit_image.html`: a checkbox after the size fieldset, label "Float right" (translated),
  carrying the same `data-for-element` contract as the size radios.
- `editor.js`: inside the EXISTING delegated `change` handler (one listener is pinned by
  `test_image_size_js.py`):
  - toggling the box toggles `el--image--float` on the preview figure;
  - choosing Large/Full unchecks and disables the box and removes the preview class; choosing
    Small/Medium re-enables it (unchecked — the author re-ticks it deliberately).

### Render

`imageelement.html` adds `el--image--float` to the figure when `el.floats`. No other markup
changes: the float container is chosen in CSS by `:has()` on the parent wrapper.

### CSS (courses.css, after the image preset block)

**The floated box** is the image's wrapper, chosen by `:has(> … > .el--image--float)`:

| Context | Floated box |
|---|---|
| Top level | `section.lesson-block` (via `> .lesson-block__body >`) |
| Builder preview | `section.prev-el` (the figure is its DIRECT child — no `__body` wrapper) |
| Callout / tabs / two-column / spoiler / before-after | `.callout__child` / `.tabs__child` / `.twocolumn__child` / `.spoiler__child` / `.ba__child` |

It gets `float: right`, a width equal to the preset (25% / 50% of the containing box —
the same percentages the presets use, so a floated image is no smaller than the unfloated
one), and an inline-start gap. The figure inside takes `max-width: 100%`, drops its
`margin-inline: auto`, and keeps a bottom margin (see mockup note).

**Clearing (D3).** A sibling wrapper clears (`clear: right`) unless its element is a text or
maths element without a heading. Wrapper-level selectors, same shape as the mockup:
`:not(:has(> … > :is(.el--text, .el--math)))` plus `:has(> … > .el--text > :is(h2, h3, h4))`.
A following floated image clears too (it is non-text), so two floats stack, never sit side by side.

**Containment (D4).** A container whose children include a floated image contains it with a
clearing `::after` (`content: ""; display: block; clear: both`) on the CONTAINER'S CHILD LIST
box — scoped by `:has(.el--image--float)` so no other container changes. NOT `display: flow-root`:
`app.css` (spoiler, around "deliberately not a flow-root") and `courses.css` (callout/tabs
child wrappers) rely on margins collapsing through these wrappers; flow-root would change the
spacing of every container. The plan must name the exact list box for each of the five
containers and prove containment per container in e2e.

At the top level, the floated block must not leak past the end of the lesson's content (unit
footer / navigation). `.slideshow-deck .slide` is already a BFC (absolute, `overflow-y: auto`);
the non-deck path needs the same clearing `::after` on the slide/lesson content box, scoped by
`:has()`.

**Medium fallback (D5).** Medium floats only when its container leaves ≥ ~12rem beside a 50%
image, i.e. container ≥ ~25rem. The mechanism is the plan's call, with these constraints:
- A size container query needs `container-type: inline-size` on an ancestor, which applies
  layout containment (a new BFC and a containing block for absolute/fixed descendants). Putting
  it on `.lesson` or on container wrappers can move notes pops, the image-zoom trigger, KaTeX
  scrollers — the plan must audit or choose a box where that is harmless, and an e2e must show
  the notes pop still opens beside its block.
- A viewport media query is acceptable ONLY if the plan shows it handles a Medium image inside
  a two-column column at desktop width (a ~300px column must NOT float a Medium image).

**Notes rail (D8).** At `@media screen and (min-width: 1200px)` with `notes-js`, the handle of
a floated top-level block is anchored to the block's BOTTOM (`top: auto; bottom: 0` on the
existing absolutely-positioned handle), so it sits level with the bottom of the image, below the
neighbouring paragraph's top-anchored handle. e2e asserts the two handles' boxes do not
intersect.

**Print (D9).** No float override. The plan verifies the print mm caps (`@media print` image
block) still apply to a floated image and that the float survives in print emulation.

### Transfer

- `_ser_image` emits `"float_right"`; `_val_image` does `setdefault("float_right", False)`
  BEFORE `_exact_keys` (precedent: `_val_callout`'s `numbered`), then `check_bool`;
  `_build_image` passes it.
- `FORMAT_VERSION` 16 → 17, with the payloads comment. Nine tests pin 16 (list in the
  plan); bump each. ⚠ Two branches bumping the same constant merge silently — check master's
  value before the PR.
- Duplicate / copy-to-unit reuse the serializer and builder, so they carry the flag; a test
  proves it.

### Out of scope

Float left; Large/Full floats; float for gallery, video, table-cell images; inline images in
text (the Task 4 dice — the owner was advised to use the Unicode die faces ⚀–⚅); LAL importer.

## Testing

Unit (pytest):
- model default False; `floats` truth table over 4 sizes × 2 flag values;
- form saves the flag; Large/Full POST with the flag stores False; an edit without the key
  stores False;
- render: the class appears only when `floats`; nested in each container;
- transfer: round-trip, missing key → False, non-bool rejected, version 17, duplicate keeps it;
- editor JS source: branch in the one delegated handler.

e2e (Playwright), each FALSIFIED (rule removed → RED, from the failure mode):
1. Small at 367px and 1300px: image right-aligned in its column, the following paragraph's
   first line starts left of the image and ends before it.
2. Two text elements after the image both wrap (D3) — Task 2's shape.
3. A heading, a spoiler and a second image after the float each start below the image's bottom.
4. Medium at 367px: NOT floated (centred, own line); at 1300px floated; in a two-column column at
   desktop: not floated.
5. Containment in each of the five containers (tabs in BOTH tab and carousel mode): the container's bottom ≥ the image's bottom when
   the text is shorter than the image; the next top-level block starts below both.
6. Top level, image as the last element: the unit footer starts below it.
7. Notes rail at 1300px: the floated block's handle and the neighbour paragraph's handle do not
   intersect; the pop of each still opens.
8. Builder preview: ticking the box floats the preview without saving; choosing Large disables the
   box and un-floats the preview; save round-trips.
9. Dark theme: the image plate is intact on the floated image.
10. Print emulation: still floated, mm cap applied.

Run every `tests/test_*css*.py` after the CSS edit (marker tests partition on text).
