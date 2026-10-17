# Numbered display maths: equation numbers must not cover a scrolled formula

## Purpose

An author writes a numbered environment (`align`, `equation`, `gather`, or any
display with `\tag{…}`). On a phone the formula is wider than the column. Since
PR #292, prose display maths scrolls sideways inside its own `.katex-display`
box, and a math element scrolls inside `.el--math`. The equation numbers do not
scroll with it. They stay pinned to the right edge of the visible box, and the
formula slides underneath them. The owner's screenshot (a 10-line `align` at
390px) shows numbers (3)–(9) printed on top of the square roots, so the steps
cannot be read.

Goal: when a numbered display overflows, its numbers sit after the widest line
and scroll with the formula. They must never overlap ink. When the display
fits, the layout must stay as it is today: a centred formula with numbers at the
right edge. No help-page note is needed, so authors keep using `align`.

Out of scope: the editor/builder mobile layout (a separate design), `leqno`/
`fleqn` (the app never sets either option, per a grep of `courses/`), and the
two table widgets.

## Root cause (verified against the vendored stylesheet)

`courses/static/courses/vendor/katex/katex.min.css`:

```
.katex-display>.katex>.katex-html{display:block;position:relative}
.katex-display>.katex>.katex-html>.tag{position:absolute;right:0}
```

`.katex-html` is a block, so its width is the column width, whatever the
formula's width. The `.base` runs are `nowrap` inline-blocks that overflow
it. `.tag` is absolutely positioned against `.katex-html`'s right edge, which is
the right edge of the *visible* column. The scroller's scrollable overflow
contains the `.base` ink. The tag occupies no in-flow space, so nothing reserves
room for it, and it overlays whatever ink scrolls beneath it.

The DOM KaTeX emits, verified by rendering with the vendored `katex.min.js`:

| source | `.katex-html` children |
|---|---|
| `\begin{align} a&=b\\ c&=d \end{align}` | `base`, `tag` |
| `\begin{equation} a=b \end{equation}` | `base`, `tag` |
| `x=1+y \tag{3}` | `base`, `base`, `base`, `tag` |
| `a=b \newline c \tag{2}` | `base`, `base`, `newline`, `base`, `tag` |
| `\begin{align*} … \end{align*}` | `base` (no tag) |

So a tagged display has one or more `.base` runs followed by exactly one `.tag`
as the last child. In an `align`, the single `.tag` holds a vlist with one number
per row, which baseline layout lines up against the rows.

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
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) {
  display: flex;
  align-items: baseline;
}
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline))::before {
  content: "";
  flex: 1 1 0;            /* left spacer */
}
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) > .base {
  flex: none;             /* runs keep their natural width, never shrink */
}
.katex-display > .katex > .katex-html:has(> .tag):not(:has(> .newline)) > .tag {
  position: static;       /* in flow: it now reserves its own width */
  flex: 1 1 0;            /* right spacer, the twin of ::before ... */
  min-width: max-content; /* ... that can never shrink below the number */
  text-align: right;      /* number flush right inside its share */
}
```

How it behaves, using the flex algorithm with equal-weight spacers either side
of the formula:

- **Fits, with room for the number.** The free space splits equally between
  `::before` and `.tag`. The formula is exactly centred and the number sits
  flush right, which is today's vendor geometry.
- **Nearly fits** (the vendor version would already overlap). The tag's
  `min-width: max-content` freezes it at the number's width, and the rest of the
  free space goes to `::before`. The formula moves left just far enough to clear
  the number. This is a strict improvement, and the only geometry change in a
  fitting display.
- **Overflows.** `::before` collapses to 0. The formula runs at full width and
  the tag follows it at its own width. The flex line overflows `.katex-html`,
  and the scroller (prose `.katex-display`, or the `.el--math` ancestor) takes
  the overflow into its scroll range. Scrolling to the end shows the numbers
  directly after the widest line, never on top of it.

`align-items: baseline` reproduces the vendor's inline baseline alignment
between the `.base` runs and the `.tag` vlist, so each number stays level with
its row. This is an A/B-pinned claim (see Testing). If measurement shows any
vertical drift, the plan must fix it before shipping, not explain it away.

### Prototype measurement (2026-10-17, Chromium via Playwright)

A standalone probe ran the vendored `katex.min.css`/`katex.min.js` plus the two
#292 scroller shapes: prose `.katex-display`, and an `.el--math` ancestor with
the inner display set to `overflow: visible`. It compared the vendor stylesheet
against the vendor stylesheet plus the four rules above:

| width | fixture | vendor tag (L–R) vs base right | new tag ink vs base right | after scroll-to-end (new) |
|---|---|---|---|---|
| 390 | wide align, prose | 348.6–374 over base ending 547.9 (**overlap**) | starts at 547.9 | ink right 372.3 ≤ scroller right 374 |
| 390 | wide align, `.el--math` | 346.1–374 over base ending 628 (**overlap**) | starts at 628 | ink right 371.9 ≤ 374 |
| 390 / 1280 | fitting align, `	ag` with 3 bases | base rects identical | base rects identical, ink flush right at 374 / 1264 | n/a |

Vertical: `tag.top − katexHtml.top` and `tag.bottom − katexHtml.bottom` matched
vendor to within 0.02px in every case. `documentElement.scrollWidth` stayed
equal to `clientWidth` (390/390).

**Measurement consequence for the tests:** under the new rule the `.tag` *box*
is a flex-grow spacer. It spans from the formula's right edge to the column
edge, and the number is right-aligned inside it. Every horizontal assertion must
therefore measure the tag's **ink**, the rect of its content (its first child
element, or a Range over its contents), never `.tag`'s own box. On the vendor
build the two coincide, so the A/B stays like-for-like.

### Scope and opt-outs

- `:has(> .tag)`: untagged displays (`align*`, `\[…\]`) are untouched.
- `:not(:has(> .newline))`: a top-level `\newline` emits a block-level
  `.newline` child, and flex would put it on the same line. Such displays keep
  vendor layout. KaTeX itself warns that `\newline` does nothing in display mode.
- **Tables** (`.el--table`, `.el--filltable`): their display maths deliberately
  inherits cell alignment (`text-align: inherit`, courses.css ~line 1741). A
  centring spacer would override that. Reset to vendor behaviour:
  `display: block` on `.katex-html`, `content: none` on `::before`, and
  `position: absolute; flex: initial; min-width: 0; text-align: initial` on the
  tag. Restate the vendor `right: 0` only if needed: it is not overridden, so it
  survives.
- **Titles** (`[data-math-title]`, app.css ~line 2399): display maths is forced
  inline there. A tagged title display gets the same reset. This is defensive:
  `.katex` is `inline-block` there, so the case is near-theoretical, but the
  reset keeps one behaviour per surface.

The opt-out selectors must out-specify the main rule: (0,5,0) for the
`:has()`/`:not(:has())` chain plus one class. The plan states the exact
specificities, in the style of the existing comments.

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
`tests/test_e2e_prose_display_math_overflow.py`). Every behavioural assertion is
an **A/B against the same element with the new rule neutralised** by an injected
override that restores vendor values. Measuring only the shipped state proves
nothing (memory: css-confirmation-needs-an-ab).

Fixtures: one wide `align` (several numbered rows, wide enough to overflow 390px
by a lot), one fitting `align`, one `\tag{…}` with several `.base` runs. Each
appears both in prose (TextElement `\[…\]`, auto-render) and as a MathElement
(`.el--math`).

Assertions:

1. **No overlap, overflowing (390px), prose and `.el--math`.** The tag's left
   edge is ≥ the right edge of the union of `.base` rects (−0.5px tolerance).
   On the neutralised build the tag overlaps the base union. That is the RED
   leg, and it proves the test measures the defect.
2. **The tag is reachable and scrolls with the formula.** After setting the
   scroller's `scrollLeft` to its max, the tag rect lies inside the scroller's
   client rect. The tag's x moves by the scroll delta. On the neutralised build
   it does not move, because the abs-pos tag is pinned to the visible edge.
3. **Fitting display unchanged (desktop 1280px, and a fitting formula at
   390px).** Every `.base` rect and the tag rect match the neutralised build
   within 0.5px.
4. **Numbers stay level with their rows.** `tag.top − katexHtml.top` and
   `tag.bottom − katexHtml.bottom` match the neutralised build within 0.5px, on
   the fitting fixture (where vendor geometry is the reference).
5. **Opt-outs and the untagged case.** In `.el--table`, `.el--filltable` and an
   untagged display, `.katex-html` computes `display: block` and the tag (where
   present) computes `position: absolute`. These are drift guards.
6. **Page does not widen.** At 390px, `documentElement.scrollWidth ==
   clientWidth` with the wide tagged fixture. This is the #292 invariant,
   re-pinned for the new flex overflow.

**Falsification (required, recorded in the PR):** delete the new rule block,
run the file, and confirm assertions 1, 2 and 6, or whichever legs claim to pin
the rule, go RED. Then restore it and confirm green. Delete only the
`align-items: baseline` line and confirm assertion 4 goes RED. If it stays
green, the declaration is unearned and must be removed or the test fixed. Do the
same for `min-width: max-content` against a near-fit fixture that exercises it.

**Visual A/B evidence:** before/after screenshots at 390px, light and dark, of
the wide `align` in prose and in `.el--math`. Capture them with a scratch script
outside the repo, never a `tests/capture_*` script, because those overwrite
tracked screenshots. Reference the images in the PR description.

**Gates:** `uv run ruff check .`, `uv run ruff format --check .`, every
`tests/test_*css*.py`, the new e2e file, and the neighbouring e2e files
(`test_e2e_prose_display_math_overflow.py`, `test_e2e_math_element_overflow.py`,
`test_e2e_table_display_math_align.py`, `test_e2e_math_reflow.py`). Every pytest
run from the worktree uses a private `TEST_DATABASE_URL`.
