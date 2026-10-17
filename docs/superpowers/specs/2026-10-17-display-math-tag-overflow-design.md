# Numbered display maths: equation numbers must not cover a scrolled formula

## Purpose

An author writes a numbered environment (`align`, `equation`, `gather`, or any
display with `\tag{…}`). On a phone the formula is wider than the column. Since
PR #292, prose display maths scrolls sideways inside its own `.katex-display`
box, and a math element scrolls inside `.el--math`.

The equation numbers are laid out against the column width, not the formula's
width. At `scrollLeft = 0` they sit at the column's right edge, on top of the
formula's middle. When the reader scrolls to reveal the formula's tail, the
numbers scroll away to the left with everything else. Their position was fixed
by the column, so they cover the middle of the formula, never its end. Nowhere
in the scroll range is a number clear of the ink. The owner's screenshot (a
10-line `align` at 390px) shows numbers (3)–(9) printed on top of the square
roots, so the steps cannot be read.

Goal: when a numbered display overflows, its numbers sit after the widest line,
so the end of the scroll range shows them clear of the ink. They must never
overlap ink. When the display fits with room for the numbers, the layout must
stay as it is today: a centred formula with numbers flush at the right edge.
No help-page note is needed, so authors keep using `align`.

Out of scope: the editor/builder mobile layout (a separate design), `leqno`/
`fleqn` (the app never sets either option, per a grep of `courses/`), and the
two table widgets (opted out below). Print: the rule applies unchanged. A print
column is wider than a phone, so the only possible effect there is the
near-fit shift described below, which is the intended behaviour. No print
assertion is added.

## Root cause (verified against the vendored stylesheet)

`courses/static/courses/vendor/katex/katex.min.css`:

```
.katex-display>.katex>.katex-html{display:block;position:relative}
.katex-display>.katex>.katex-html>.tag{position:absolute;right:0}
.katex .vlist>span{display:block;height:0;position:relative}
.katex .vlist>span>span{display:inline-block}
```

`.katex-html` is a block, so its width is the column width, whatever the
formula's width. The `.base` runs are `nowrap` inline-blocks (nowrap is
inherited from `.katex-display>.katex`) that overflow it. `.tag` is absolutely
positioned at `right: 0` of `.katex-html`, which is the column's right edge in
content coordinates. `.katex-html` is inside the scroller, so the tag scrolls
with the content. But its position is fixed by the column width, not the
formula's width. It occupies no in-flow space, so nothing reserves room for it,
and it overlays whatever ink sits at that x.

The DOM KaTeX emits, verified by rendering with the vendored `katex.min.js`:

| source | `.katex-html` children |
|---|---|
| `\begin{align} a&=b\\ c&=d \end{align}` | `base`, `tag` |
| `\begin{equation} a=b \end{equation}` | `base`, `tag` |
| `x=1+y \tag{3}` | `base`, `base`, `base`, `tag` |
| `a=b \newline c \tag{2}` | `base`, `base`, `newline`, `base`, `tag` |
| `a \\ b \tag{1}` (top-level `\\`) | `base`, `newline`, `base`, `tag` |
| `\begin{align*} … \end{align*}` | `base` (no tag) |

So a tagged display has one or more `.base` runs followed by exactly one `.tag`
as the last child. In an `align`, the single `.tag` holds a vlist with one row
per equation. Each row is a block span holding an inline-block number, so rows
of different widths, such as (9) above (10), are aligned against each other by
the inherited `text-align`, which is `center` from `.katex-display>.katex`.

## Architecture

One CSS rule block in `courses/static/courses/css/courses.css`, placed directly
after the #292 prose-scroller block (`.katex-display { overflow-x: auto; … }` and
its opt-out). No JS and no template change.

The approved direction was to "let `.katex-html` size to its content and reserve
inline-end space for the tag". It is realised with flex layout instead of a
fixed `padding-inline-end`. A padding reserve cannot be sized to the tag:
`(1)`, `(10)`, `(2.14)` and `\tag{*}` all differ in width, and a reserve
large enough for the widest would shift every fitting formula off centre. An
**in-flow** tag reserves exactly its own width, automatically.

```css
/* (0,5,0) */
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) {
  display: flex;
  align-items: baseline;
}
/* (0,5,1) */
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline))::before {
  content: "";
  flex: 1 1 0;            /* left spacer */
}
/* (0,6,0) */
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) > .tag {
  position: static;       /* in flow: it now reserves its own width */
  flex: 1 1 0;            /* right spacer, the twin of ::before */
  text-align: right;      /* the number block flush right inside its share */
}
/* (0,6,0) -- `*` adds nothing */
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) > .tag > * {
  text-align: center;     /* restore the vendor's inherited alignment BETWEEN rows */
}
/* (0,7,0) -- `:first-child` is a pseudo-class and counts as a class */
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) > .tag > :first-child {
  margin-inline-start: 1em; /* minimum gap between formula and number */
}
```

**The gap.** Neither KaTeX tag path puts any space before the number. Without a
gap, in the near-fit and overflow cases the widest line would touch its number,
so `… = 2(3)` would read as multiplication. The gap is a margin on the tag's
**first child**, which is the vlist for an array environment and the full-height
`.strut` for `	ag{…}` (see the ink definition below). That margin raises the
tag's min-content width by 1em. It does not touch the flex base size the two
spacers share, so the fit case keeps exact centring, and the number stays flush
right inside its wider share. Padding on `.tag` was rejected: it adds to the
tag's outer size, so the formula would shift left by half the padding in every
fitting display. Mirroring it on `::before` would instead leave a 1em dead strip
at the formula's left edge when it overflows. Consequence for the fit
condition: "room for the number" now means free space / 2 ≥ number width + 1em.

The `.tag > *` rule exists because `text-align` inherits into the vlist rows.
Without it, a fitting `align` with (9) above (10) would switch its numbers from
centred against each other to right-aligned against each other, which is a
geometry change in a fitting display. `center` is the value the vendor tag
inherits on every surface this rule reaches, because tables are opted out
below.

**No shrink guards are needed, and none are declared.** The drafts had
`.base { flex: none }` and `.tag { min-width: max-content }`, and both are
redundant. Flex items with `overflow: visible` default to `min-width: auto`,
which is their min-content size. Every item here inherits `white-space: nowrap`
from `.katex-display>.katex`, so min-content equals max-content. Neither the
runs nor the number can shrink below their natural width. An unearned
declaration is worse than none (see the #292 comment on `position: relative`).

How it behaves, using the flex algorithm with equal-weight spacers either side
of the formula:

- **Fits, with room for the number** (free space / 2 ≥ number width). The free
  space splits equally between `::before` and `.tag`. The formula is exactly
  centred and the number sits flush right, which is today's vendor geometry.
- **Nearly fits** (formula + number ≤ column, but free space / 2 < number width,
  so the vendor version already overlaps). The tag's automatic minimum freezes
  it at the number's width, and the rest of the free space goes to `::before`.
  The formula moves left just far enough to clear the number. This is a strict
  improvement, and the only geometry change in a fitting display.
- **Overflows.** `::before` collapses to 0. The formula runs at full width and
  the tag follows it at its own width. The flex line overflows `.katex-html`,
  and the scroller (prose `.katex-display`, or the `.el--math` ancestor) takes
  the overflow into its scroll range. Scrolling to the end shows the numbers
  directly after the widest line, never on top of it.

`align-items: baseline` reproduces the vendor's inline baseline alignment
between the `.base` runs and the `.tag` vlist, so each number stays level with
its row. This is an A/B-pinned claim (see Testing).

### Prototype measurement (2026-10-17, Chromium via Playwright)

A standalone probe ran the vendored `katex.min.css`/`katex.min.js` plus the two
#292 scroller shapes: prose `.katex-display`, and an `.el--math` ancestor with
the inner display set to `overflow: visible`. It compared the vendor stylesheet
against the vendor stylesheet plus the draft rules. That draft had the two shrink
guards and lacked the `.tag > *` rule; the plan re-runs the measurement on the
final rules.

| width | fixture | vendor tag (L–R) vs base right | new tag ink vs base right | after scroll-to-end |
|---|---|---|---|---|
| 390 | wide align, prose | 348.6–374 over base ending 547.9 (**overlap**) | starts at 547.9 | vendor tag moved to 172.6–198 (still over ink). New ink right 372.3 ≤ scroller right 374 |
| 390 | wide align, `.el--math` | 346.1–374 over base ending 628 (**overlap**) | starts at 628 | vendor 90.1–118 (over ink). New 371.9 ≤ 374 |
| 390 / 1280 | fitting align, `\tag` with 3 bases | base rects identical | base rects identical, tag box flush right at 374 / 1264 (box, not ink -- the plan re-measures with the ink definition below) | n/a |

Vertical: `tag.top − katexHtml.top` and `tag.bottom − katexHtml.bottom` matched
vendor to within 0.02px in every case. `documentElement.scrollWidth` stayed
equal to `clientWidth` (390/390). The vendor tag moving by exactly the scroll
delta, 176px, confirms it scrolls with the content (see Root cause).

**Measurement consequence for the tests:** under the new rule, the `.tag` *box*
is a flex-grow spacer. It spans from the formula's right edge to the column
edge, with the number right-aligned inside it, and its height depends on flex
alignment. **Every tag measurement, horizontal and vertical, uses the tag's
ink, never `.tag`'s own box.** **Ink** = the union of the bounding rects of the
tag's *leaf* descendant elements (no element children) whose width is greater
than 0, excluding `.strut`, `.pstrut` and `.vlist-s`. Three facts make that
definition necessary rather than a simpler one:

- For `	ag{…}`, the tag's first child is a zero-width `.strut` whose height is
  the whole display's height plus depth. It is not the number (vendored
  `katex.min.js`: the tag is built through the unbreakable-base path and its
  `children[0]` gets the strut height).
- For an array environment the first child is the `.vlist-t`, whose box
  overshoots the number by 2px: KaTeX's `vlist-t2` margin trick. A re-run of the
  probe measured that box's right edge at 376 against a 374 column edge, on both
  builds.
- Auto-numbers have **no text nodes**. `.eqn-num` gets its "(n)" from a CSS
  counter in `::before`. A text-node Range sees nothing, so a leaf-element union,
  where `.eqn-num` is the leaf, is the robust choice. (The counter runs across
  the whole page, which is why the owner's second display starts at (3).
  Unchanged by this work.)

### Scope and opt-outs

- `:has(> .tag)`: untagged displays (`align*`, `\[…\]`) are untouched.
- `:not(:has(> .newline))`: a top-level `\newline` or `\\` emits a block-level
  `.newline` child (verified for both, in the table above), and flex would put it
  on the same line. Such displays keep vendor layout. KaTeX itself warns that a
  line break does nothing in display mode.
- **Tables** (`.el--table`, `.el--filltable`): their display maths deliberately
  inherits cell alignment (`text-align: inherit`, courses.css ~line 1741). A
  centring spacer would override that, so they reset to vendor behaviour. Each
  opt-out is written as **the same selector chain with the surface class
  prefixed**: `.el--table .katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline))`
  and so on. Each opt-out then out-specifies its counterpart by exactly one
  class. The opt-outs are (0,6,0), (0,6,1), (0,7,0), (0,7,0) and (0,8,0); the main
  rules they beat are (0,5,0), (0,5,1), (0,6,0), (0,6,0) and (0,7,0), in the
  order container, `::before`, tag, `tag > *`, `tag > :first-child`. Declarations: `display: block` on `.katex-html`
  (`align-items` is inert on a block, so it needs no reset), `content: none` on
  `::before`, and `position: absolute; flex: initial; text-align: inherit` on
  the tag. `inherit` restores the vendor's inherited cell alignment, which
  `initial` would not. The vendor `right: 0` is never overridden, so it
  survives. The `.tag > *` rule gets `text-align: inherit` too, and the
  `.tag > :first-child` rule gets `margin-inline-start: 0`.
- **Titles** (`[data-math-title]`, app.css ~line 2399): no opt-out. There
  `.katex-display > .katex` is forced `inline-block`, so `.katex-html` is
  shrink-to-fit at the formula's width. On vendor, the abs-pos tag at `right: 0`
  of that width therefore overlaps the formula's end. Under the new rule the tag
  follows the formula. It is an improvement on a near-theoretical surface, and
  it is not asserted.

Browser support: `:has()` is already relied on in courses.css (the
`:has(> :is(.el--text, .el--math))` float-clearing rules, ~line 291). A UA without
it gets today's vendor layout, so it degrades to the current state, not worse.

## Data flow

None. The change is presentational only. The KaTeX DOM, the stored LaTeX,
`math.js`, auto-render and `math_reflow.js` are untouched. The rule applies
wherever the vendored KaTeX renders a tagged display outside the opt-outs:
lesson prose, callout bodies, question stems, `.el--math` elements, quiz slides
and the editor live preview.

## Error handling

Not applicable to runtime. Failure modes to guard against at build time:

- The selector stops matching (a KaTeX upgrade renames `.tag`/`.base`/`.katex-html`).
  Tests render real KaTeX, so this goes red, not silently inert.
- A future rule re-absolutises the tag. The overlap assertion goes red.
- CSS-source tests that partition courses.css by text markers can be hijacked by
  the new block. Run every `tests/test_*css*.py` (memory: css-edits-run-every-
  css-source-test).

## Testing

New e2e file `tests/test_e2e_display_math_tag_overflow.py` (Playwright, real
vendored KaTeX, live_server, same fixture idiom as
`tests/test_e2e_prose_display_math_overflow.py`).

**The A/B mechanism is prescribed.** The "vendor" leg runs in the same page with
the new rules removed through CSSOM. Walk `document.styleSheets` and
`deleteRule` every rule whose `selectorText` contains `:has(> .tag)`. That
removes the main rules and the table opt-outs together, so the result is exactly
the vendor cascade. A sanity check must follow, asserting that the fixture's
`.tag` now computes `position: absolute`. Without that check a silent no-op
(selector text serialised differently, or the sheet unreachable) would make
both legs identical. No hand-written override stylesheet is used, because it
would have to restore each property at the right specificity, and one missed
property makes a hybrid.

Fixtures, each appearing in prose (TextElement `\[…\]`, auto-render) and as a
MathElement (`.el--math`):

- **wide**: a numbered `align` that overflows the 390px viewport's column by at
  least the tag's ink width plus 50px. That margin makes the vendor tag still
  overlap ink at max scroll (prototype: about 176px and 256px of overflow).
- **fit-mixed**: a fitting numbered `align` with at least ten rows, so (9) sits
  above (10) and the number widths differ. It must satisfy free space / 2 ≥ tag
  ink width + 1em + 20px at 390px and at 1280px.
- **multi-base**: `x = … \tag{3}`, fitting, which yields several `.base` runs.
- **near-fit**: a numbered display where, at 390px, formula + tag ink ≤ column −
  10px − 1em but free space / 2 < tag ink width + 1em − 10px. The vendor build overlaps
  here and the new one must not. The plan sizes it by measurement.

Assertions. "Overlap" means the tag ink's horizontal interval intersects the
union of the `.base` rects. Rects are compared with a 0.5px tolerance.

1. **No overlap at scroll 0 (wide, near-fit; 390px; prose and `.el--math`).**
   The tag ink's left ≥ the base union's right + 1em − 0.5px
   (1em = the display's computed font-size). RED on vendor.
2. **Numbers clear of ink at the end of the scroll range (wide; 390px).** After
   setting the scroller's `scrollLeft` to its maximum, the tag ink lies entirely
   inside the scroller's client rect, and its left ≥ the base union's right +
   1em − 0.5px. RED
   on vendor, where the tag has scrolled left onto the formula. A "moves by the
   scroll delta" check is deliberately absent: it holds on both builds.
3. **Fitting display unchanged (fit-mixed, multi-base; 390px and 1280px).**
   Every `.base` rect and the tag ink rect match the vendor leg. This is a
   regression guard, expected green on both builds by construction. Its job is to
   catch a geometry change, such as the I2 inheritance (see falsification).
4. **Numbers stay level with their rows (fit-mixed, multi-base).**
   `ink.top − katexHtml.top` and `ink.bottom − katexHtml.bottom` match the
   vendor leg. Also a regression guard.
5. **Near-fit has no overflow.** On near-fit at 390px, the scroller's
   `scrollWidth ≤ clientWidth + 1`, so the formula moved left rather than
   overflowing.
6. **Opt-outs and the untagged case (drift guards).** In `.el--table` and
   `.el--filltable` (tagged fixture), `.katex-html` computes `display: block`,
   the tag computes `position: absolute`, and the tag's `text-align` equals its
   parent's. In an untagged display, `.katex-html` computes `display: block`.
7. **Page does not widen (regression guard).** At 390px with wide,
   `documentElement.scrollWidth == clientWidth`. This is the #292 invariant,
   re-pinned for the new flex overflow.

**Falsification (required, recorded in the PR).** Each mutant is applied by hand
to courses.css, never with `git checkout`, and the file is re-run:

| mutant | must go RED |
|---|---|
| delete the whole new block (main rules and opt-outs) | 1, 2, 5 |
| delete only `align-items: baseline` | 4 (if it stays green, the declaration is unearned: remove it or fix the test) |
| delete only the `.tag > *` rule | 3 (fit-mixed) |
| delete only the `.el--table` opt-out | 6 |
| delete only the `.el--filltable` opt-out | 6 |
| delete only the `.tag > :first-child` gap rule | 1, 2 (the gap term) |
| delete only `text-align: right` on `.tag` | 3 (fit fixtures; in near-fit/overflow the share equals the number, so nothing moves) |
| delete the #292 `.katex-display` `overflow-x`/`overflow-y` pair | 7 |

Assertions 3, 4 and 7 are regression guards and are expected green when the
whole block is deleted. That is stated, not an anomaly.

**Visual A/B evidence:** before/after screenshots at 390px, light and dark, of
the wide `align` in prose and in `.el--math`. Capture them with a scratch script
outside the repo, never a `tests/capture_*` script, because those overwrite
tracked screenshots. Reference the images in the PR description.

**Gates:** `uv run ruff check .`, `uv run ruff format --check .`, every
`tests/test_*css*.py`, the new e2e file, and the neighbouring e2e files
(`test_e2e_prose_display_math_overflow.py`, `test_e2e_math_element_overflow.py`,
`test_e2e_table_display_math_align.py`, `test_e2e_math_reflow.py`). Every pytest
run from the worktree uses a private `TEST_DATABASE_URL`.
