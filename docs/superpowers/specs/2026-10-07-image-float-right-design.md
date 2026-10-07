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

- `ImageElement.float_right = models.BooleanField(default=False)`; the next migration after
  master's graph head at PR time (`0069` today — re-check the head before the PR).
- An "effective float" is `float_right and size in {small, medium}`, exposed as a model property
  (e.g. `ImageElement.floats`) so the template and tests share one definition (D2).

### Editor

- `ImageElementForm.Meta.fields` gains `float_right`. `clean()` forces `float_right = False`
  when the size is Large or Full, so a disabled (therefore unsubmitted) checkbox and a
  hand-crafted POST agree.
- `_edit_image.html`: a checkbox after the size fieldset, label "Float right" (translated),
  carrying the same `data-for-element` contract as the size radios (used, as now, ONLY to find
  the preview figure). The size-radio handler finds ITS checkbox inside its own editor —
  `preset.closest(".el-editor--image").querySelector(…)` — never by `data-for-element`, which is
  `""` for every unsaved image on the create flow. **Server-rendered state**,
  from the FORM's current values (like the size radios, which render `form.size.value`):
  `checked` iff `form.float_right.value` is true AND `form.size.value` is Small/Medium;
  `disabled` iff `form.size.value` is Large/Full. For an unbound form these are the stored
  values, so a legacy/imported `true` on a Large image renders unchecked (the box shows what
  students see); for a bound form that failed validation (e.g. caption too long) the author's
  submitted size and tick survive the re-render; on the create flow the size defaults to Full,
  so the box starts disabled.
- `editor.js`: inside the EXISTING delegated `change` handler (one listener is pinned by
  `test_image_size_js.py`):
  - toggling the box toggles `el--image--float` on the preview figure;
  - choosing Large/Full unchecks and disables the box and removes the preview class;
  - leaving Large/Full for Small/Medium re-enables the box, unchecked (the author re-ticks it
    deliberately);
  - switching between Small and Medium leaves the box's checked state (and the preview class)
    untouched.
- i18n: a Polish catalog entry for the label (wording proposed in the PR for the owner to
  confirm), the `.mo` regenerated, and a check that the entry is not `#, fuzzy` (makemessages
  pre-fills a wrong fuzzy translation in this project).

### Render

`imageelement.html` adds `el--image--float` to the figure when `el.floats`. No other markup
changes: the float container is chosen in CSS by `:has()` on the parent wrapper.

### CSS (courses.css, after the image preset block)

**The floated box** is the image's wrapper, chosen by `:has(> … > .el--image--float)`:

| Context | Floated box |
|---|---|
| Lesson top level | `section.lesson-block` (via `> .lesson-block__body >`) |
| Quiz top level | the `section[data-element-id]` of `_quiz_article.html` (no `.lesson-block`, no `__body` — the figure is its direct child). ⚠ Lesson blocks AND preview blocks are ALSO `section[data-element-id]`; every quiz rule (float, sibling clear, …) MUST be scoped to the quiz article (e.g. `.quiz .slide > section[data-element-id]`, or `:not(.lesson-block):not(.prev-el)`). An unscoped `section[data-element-id]:not(:has(> :is(.el--text, .el--math)))` matches EVERY lesson text block (its text sits under `__body`, not directly under the section) and clears them all — D3 silently dead at the top level. |
| Builder preview | `section.prev-el` — the `section` qualifier is REQUIRED: in preview every container child is ALSO `.prev-el` (e.g. `.callout__child.prev-el`), and those are governed by the container rows below |
| Callout / tabs / two-column / spoiler / before-after | `.callout__child` / `.tabs__child` / `.twocolumn__child` / `.spoiler__child` / `.ba__child` |

Quiz units float exactly like lessons (D4's "top level" covers both), so the builder preview
matches what a student sees in either unit type.

The floated box gets `float: right`, `max-width: 25%` / `50%` (the preset's percentage of the
containing box) and NO fixed width — it shrink-wraps to the image like the unfloated
`fit-content` figure, so a narrow or height-capped image (`max-height: 30dvh/45dvh` on the img)
leaves no gap between itself and the wrapped text. Its margin is the approved mockup's
`0 0 var(--space-3) var(--space-4)`: the inline-start gap from the text, and the space above the
first full-width line under it. The figure inside takes `max-width: 100%`, drops its `margin-inline: auto`, and its block
margins are pinned to `0 0 1rem` as in the approved mockup (a float is a BFC root, so the
`.el { margin: 1rem 0 }` top margin would otherwise push the image ~1rem below the text's first
line; the bottom 1rem is the notes-handle clearance, see mockup note). The img's own
`margin-inline: auto` (the `.el--image--small img` group) becomes `margin-inline: auto 0`, so the
image hugs the float's RIGHT edge even when a figcaption longer than the image widens the float
(the figure is `fit-content`: it sizes to the wider of image and caption).

**Every float-specific declaration — on the wrapper, the figure, the img, and the D8
bottom-anchored notes handle — sits under the same condition as `float: right`.** A Medium image that falls back (D5) must render exactly like an
unflagged Medium (centred, ≤50%), not flush-left at full width.

**Clearing (D3).**
- A sibling wrapper clears (`clear: right`) unless its element is a text or maths element:
  `:not(:has(> … > :is(.el--text, .el--math)))`. A following floated image clears too (it is
  non-text), so two floats stack, never sit side by side.
- Headings clear THEMSELVES, wherever they sit inside a text element:
  `.el--text :is(<every heading tag>) { clear: right }` (descendant, so a heading inside an
  allowed `div`/`blockquote` counts). The heading list is the text sanitizer's allowed headings
  (`ALLOWED_TAGS` in `courses/sanitize.py`, h2–h4 today); the CSS source test derives the list
  from that set rather than pinning it. A text element that opens with a paragraph and has a
  heading further down wraps its paragraph and drops only from the heading on.
- Both clearing rules are deliberately UNSCOPED (no `.el--image--float` key): `clear` is a no-op
  when no float precedes, so they cannot change a page without a floated image. They are the two
  named exemptions of the D10 source test.

**Containment (D4).** A container whose children include a floated image contains it with a
clearing `::after` (`content: ""; display: block; clear: both`) on the CONTAINER'S CHILD LIST
box — scoped by `:has(.el--image--float)` so no other container changes. NOT `display: flow-root`:
`app.css` (spoiler, around "deliberately not a flow-root") and `courses.css` (callout/tabs
child wrappers) rely on margins collapsing through these wrappers; flow-root would change the
spacing of every container. The plan must:
- name the exact list box for each container, and grep each for an existing `::after` rule
  before adding one;
- give EVERY container's child list the `::after`, including two-column and carousel-mode tabs.
  On screen `.twocolumn__column` (a flex item) and the carousel `.tabs__section` (absolutely
  positioned) already contain floats, but print rewrites the carousel to `position: static
  !important` (courses.css print block), so only an explicit clear holds on paper (D9);
- prove containment per container in e2e.

At the top level, the floated block must not leak past the end of its slide. Every unit renders
one `div.slide` per slide (`_lesson_article.html`). EVERY `.slide:has(.el--image--float)` gets
the clearing `::after` — deck slides included: on screen a deck slide is already a BFC (absolute,
`overflow-y: auto`) and the `::after` is harmless, but print makes deck slides `position: static
!important; overflow: visible !important`, and outside the deck (single slide; multi-slide with
no JS, where slides stack) nothing else contains the float. Outside a slideshow `.slide` is
`display: contents` (courses.css slideshow block); its `::after` still generates and lands in
`article.lesson` after the slides' content, which is where the clear is needed. Quizzes render
the same `div.slide` per slide (`_quiz_article.html`), so the same `.slide` rule covers them —
there is no separate quiz list box.

**Medium fallback (D5).** Medium floats only when its containing box W leaves ≥ 12rem of text
beside it. Text width = 0.5W − space-4 (the float's inline-start margin sits outside its 50%),
so the threshold is W ≥ `2 × (12rem + space-4)` = `24rem + 32px` today (`--space-4: 16px`,
tokens.css). ⚠ A size-query condition cannot contain `var()` — `@container (min-width:
calc(24rem + var(--space-4) * 2))` is INVALID and is dropped silently ("Medium never floats").
The CSS therefore writes the LITERAL (`calc(24rem + 32px)` or `416px`); a source test derives the
expected literal from tokens.css's `--space-4` so the two cannot drift. The e2e computes the
threshold from the token at runtime. The mechanism must MEASURE THE
IMAGE'S CONTAINING BOX in every context (D5 verbatim) — a viewport media query is NOT
acceptable, whatever it passes. Within that, the mechanism is the plan's call, with these
constraints:
- The measuring box must exist in EVERY context a Medium image can float in: lesson top level,
  quiz top level (`article.quiz`, not `.lesson`), builder preview (`.prev-inner`, outside any
  article), and each of the five container child lists. `@container` with no ancestor query
  container evaluates FALSE — a missing container fails silently as "Medium never floats here".
  Note `.slide` is `display: contents` outside a slideshow and generates no box, so it cannot be
  the container there.
- In a JS slideshow deck the top-level block sits in `.slideshow-deck .slide` (created by
  slideshow.js; `padding: var(--space-6)` inside a bordered deck — ~50px narrower than the
  article). That slide must be the measuring box in decks (it is absolutely positioned with
  `inset: 0`, so its width is definite; audit it like the others), else every paginated lesson
  and quiz over-estimates the text width by ~50px — a quarter of the 12rem D5 protects.
- A size container query needs `container-type: inline-size` on an ancestor, which applies
  layout containment (a new BFC and a containing block for absolute/fixed descendants). Putting
  it on `.lesson` or on container wrappers can move notes pops, the image-zoom trigger, KaTeX
  scrollers — the plan must audit or choose a box where that is harmless, and an e2e must show
  the notes pop still opens beside its block. The audit must also cover inline-size
  containment's other two effects: the box's intrinsic inline size ignores its content (a
  content-sized box — fit-content, shrink-to-fit absolute, `flex-basis: auto`, inline-block —
  collapses), and its new BFC stops the margin collapsing that the container wrappers rely on
  ("deliberately not a flow-root"), so spacing would change in exactly the containers that hold
  a float.

**The floated block's own notes pop (below the rail).** Below 1200px, and at any width without
`notes-js`, `.block-notes__pop` is in flow inside `.lesson-block` — inside a float only ~80px wide
on a phone. While the floated block's panel is open the block UN-FLOATS
(`:has(.block-notes__panel[open])` → `float: none; max-width: none`, the image back to its
unfloated preset layout), so the pop gets the full column. The text reflows while notes are
open; accepted. **Scope:** only where the pop is in flow — `@media screen and (max-width:
1199.98px)`, OR `html:not(.notes-js)` at any screen width. NOT at ≥1200px with `notes-js` (the
pop is absolutely positioned in the rail; un-floating would reflow the paragraph, move the D8
handle and make notes.js's `pop.style.top = handle.offsetTop` jump) and NOT in print (D9).
Also accepted: when the page is rendered with panels open server-side (`notes_show`, or after
a no-JS composer error, `_block_notes.html` emits `<details open>`), a floated image that has
notes loads un-floated below the rail.

**Notes rail (D8).** Invariant: at `@media screen and (min-width: 1200px)` with `notes-js`, the
floated block's handle intersects NO other handle in the lane. Mechanism: anchor it to the
block's BOTTOM (`top: auto; bottom: 0` on the existing absolutely-positioned handle), level with
the bottom of the image, below the top-anchored handle of the paragraph beside it. Known limits,
accepted (author's call, not an owner decision): a floated image shorter than ~2 handle heights
(~60px), or a second wrapping paragraph whose top lands exactly at the image's bottom, can still
touch. e2e 7 asserts the invariant for the Task 2 shape (both paragraphs) and records the
short-image case as a measurement in its docstring, not an assertion. Also accepted: a
paragraph block beside the float spans the full column, so notes.js's hover highlight
(`.lesson-block.is-highlighted`) outlines the image area too and dims the floated block
(`.is-dimmed`); cosmetic, checked in the e2e 7 screenshots only.

**Print (D9).** No float override. The plan verifies the print mm caps (`@media print` image
block) still apply to a floated image and that the float survives in print emulation.
Exception: `notes.css`'s print block prints the in-flow pop of every block that has note cards;
inside a float that is ~45mm wide on A4 and makes the float tall. So in print a floated block
whose pop has printable notes UN-FLOATS — the print counterpart of the below-rail notes rule.
It uses the SAME CLASS LIST as the notes print rule (`.note-card`, `.note-composer--edit`,
`.note-composer--has-draft`, `.note-composer__error` today), but NOT its literal form: that rule
is `.block-notes__pop:not(:has(…))`, and keying a block on it would need `:has(… :has(…))` —
nested `:has()` is invalid, so the whole rule would be dropped silently (served but not parsed;
source greps stay green). Write it as descendant alternatives on the block:
`:has(.block-notes__pop .note-card, .block-notes__pop .note-composer--edit, …)`. A source test
asserts the class list equals notes.css's; the falsified print e2e proves the rule parses.

**Builder preview containment.** `_preview.html` renders `section.prev-el` straight into
`.prev-inner` — no `.slide`. `.prev-inner:has(.el--image--float)` gets the same clearing
`::after`, and a slide-break preview element after a float clears like any non-text element.

**Scoping (D10).** Every new rule except the two clearing rules (sibling clear, heading
self-clear — see Clearing) is keyed on
`.el--image--float` (directly or through `:has()`); in particular no `container-type`,
`::after` or float rule applies to a page with no floated image. A CSS source test asserts this
over the new block.

### Transfer

- `_ser_image` emits `"float_right"`; `_val_image` does `setdefault("float_right", False)`
  BEFORE `_exact_keys`, then COERCES a non-bool to `False`, like `size`'s coercion to `full` —
  `_val_image`'s own policy is that a cosmetic field with a lossless default must never fail an
  import (`courses/transfer/payloads.py`, the `size` comment). `_build_image` passes it.
- `FORMAT_VERSION` 16 → 17 in `courses/transfer/schema.py`; the "added in FORMAT_VERSION 17"
  note goes beside `_val_image`'s existing version comments in `payloads.py`. Bump EVERY test that pins 16 — derive
  the list by grep at plan time (`== 16`, `format_version`, `_16` in test names, across BOTH
  `tests/` and `courses/tests/`); do not trust a remembered count. ⚠ Two branches bumping the same constant merge silently — check master's
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
- editor template: checkbox state from the form's values — unbound: a stored `true` on Large →
  unchecked + disabled; create flow → disabled; an INVALID POST (Small + ticked + bad caption)
  re-renders Small checked, box checked and enabled;
- render: the class appears only when `floats`; at lesson top level, quiz top level, and nested
  in each container;
- transfer: round-trip, missing key → False, non-bool COERCED to False (import succeeds),
  version 17, duplicate keeps it;
- editor JS source: branch in the one delegated handler;
- CSS source: every new rule but the two clearing rules (sibling clear, heading self-clear) is
  keyed on `.el--image--float` (D10), and every quiz-context rule is scoped to the quiz article;
- i18n: the Polish entry exists and is not fuzzy.

e2e (Playwright), each FALSIFIED (rule removed → RED, from the failure mode):
1. Small at 367px and 1300px: the image's right edge equals the column's right edge; the
   following paragraph's first line starts left of the image and ends before it. Includes a
   SMALL-natural-width image (narrower than 25%): no gap between it and the text; and a
   narrow image with a figcaption longer than the image: the IMAGE's right edge still equals
   the column's right edge.
2. Two text elements after the image both wrap (D3) — Task 2's shape — in a LESSON (proves no
   quiz-context rule clears lesson text) and in a QUIZ. A maths element after the image sits
   beside it (its right edge left of the image's left edge) and the page does not scroll
   horizontally at 367px; a display formula narrower box scrolling inside its own scroller is
   accepted.
3. A heading element, a spoiler and a second image after the float each start below the image's
   bottom; a text element with a paragraph then an `<h3>` wraps the paragraph and drops the h3.
4. Medium at 367px: NOT floated, and its box equals an unflagged Medium's (centred, ≤50% of the
   column — not flush-left at full width); at 1300px floated; in a two-column column: the test
   MEASURES the column's content width and asserts floated iff it is ≥ the threshold (a 2-column
   column is ~314px with the tree pinned but ~426px collapsed, so a hard-coded "not floated" is
   wrong in one TOC state) — with a fixture that lands BELOW it (e.g. 3 columns) so the fallback
   branch is exercised, same equality as above. A multi-slide DECK case pairs a box above and
   below the threshold measured on the deck slide. The same float/fallback pair (a box above and below the
   threshold) in a QUIZ and in the BUILDER PREVIEW — proves the measuring container exists there.
5. Containment in each of the five containers (tabs in BOTH tab and carousel mode): the
   container's bottom ≥ the image's bottom when the text is shorter than the image; the next
   top-level block starts below both.
6. Top level, image as the last element: the unit footer starts below it; multi-slide unit with
   JS off: the next slide starts below it.
7. Notes rail at 1300px: the floated block's handle intersects neither paragraph handle of the
   Task 2 shape; each pop still opens; opening the floated block's pop leaves the block FLOATED
   (the un-float rule is below-rail only).
8. Notes pop below the rail at 367px: opening the floated block's notes un-floats it and the pop
   is as wide as the column.
9. Quiz unit: a top-level floated image floats, as in the builder preview.
10. Builder preview, on a SMALL image: ticking the box floats the preview without saving;
    choosing Large disables and unchecks the box and un-floats the preview; Small ↔ Medium keeps
    it ticked (assert the box and the `el--image--float` class, not geometry — Medium may
    legitimately fall back in the narrow pane); save round-trips. An image as the last preview
    element does not overflow `.prev-inner`; a slide-break after a float starts below it.
11. Dark theme: the image plate is intact on the floated image.
12. Print emulation: still floated, mm cap applied; a float at the end of a carousel-mode tab and
    at the end of a deck slide (multi-slide unit) stays contained — the next section/slide
    starts below it; a floated image WITH a note prints un-floated, its notes at column width.

Run every `tests/test_*css*.py` after the CSS edit (marker tests partition on text).
