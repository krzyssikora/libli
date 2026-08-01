# Display-math authoring: multi-line `\[…\]`, and `<` inside math

## Purpose

Authoring a display-math block in libli fails in two independent, silent ways. Both were reproduced
against this repo's vendored KaTeX 0.16.11 and this repo's own sanitiser before this spec was
written; every claim below is a measurement, not a recollection.

The reported symptom — a paste like

```latex
\begin{align*}
a^n\cdot a^k&=a^{n+k}\\
a^n: a^k&=a^{n-k}\\
\left(a^n\right)^k&=a^{nk}
\end{align*}
```

"is not accepted within `\(\)` or `\[\]`, i.e. it does not render".

### What is actually wrong

**Problem 1 — the RTE splits the span, and auto-render only matches inside a single text node.**

`renderMathInElement` scans **text nodes**. It never joins text across element boundaries. A
contenteditable turns each ENTER into a `<div>` (Chrome/Safari) or a `<br>` (Firefox) — see the
comment already in `courses/sanitize.py` on why `div` is in `ALLOWED_TAGS`. So the opening `\[` and
the closing `\]` land in different text nodes and the whole span is skipped, with no error and no
visible trace.

Measured in real Chromium against the vendored `katex.min.js` + `contrib/auto-render.min.js`:

| Input | `.katex` nodes |
|---|---|
| `\[\begin{align*}…\end{align*}\]` in **one** text node | **1** — renders correctly |
| the same span split across `<div>` lines | **0** — silently nothing |
| the same span split by `<br>` | **0** — silently nothing |
| the same span **rejoined into one text node**, newline at each boundary, prose before and after | **1**, three aligned rows, prose intact |

So `\[…\]` already supports `align*`. The delimiters are fine; the DOM shape is not.

**Problem 2 — `\(…\)` cannot host an alignment environment.** Measured against `katex.renderToString`
for 23 environments, exactly ten are display-only and raise
`{…} can be used only in display mode` when `displayMode: false`:

```
align  align*  alignat  alignat*  gather  gather*  equation  equation*  CD  split
```

Everything else (`aligned`, `alignedat`, `gathered`, `cases`, `matrix`, `pmatrix`, `bmatrix`,
`array`, `smallmatrix`, `darray`, `dcases`, `rcases`) works in both modes. So an author who reaches
for `\(` with an alignment environment gets a red KaTeX error, correctly but unhelpfully.

**Problem 3 — the Math element rejects the delimiters.** `mathelement.html` is
`<div class="el el--math" data-katex>{{ el.latex }}</div>` and `math.js` `renderOne` passes
`el.textContent` straight to `katex.render(…, {displayMode: true})`. `\[` and `\]` are auto-render
*delimiters*, not KaTeX control sequences, so `\[\begin{align*}…\end{align*}\]` in a Math element
fails with `Undefined control sequence: \[` — while the identical text **without** the wrapper
renders today. The author cannot tell which surface wants delimiters and which forbids them.

**Problem 4 — `<` inside math is destroyed at save, in text/callout/spoiler bodies.** `sanitize_cell`
protects balanced LaTeX spans from the HTML tokenizer before running nh3; `sanitize_html` does not.
Measured on this worktree:

```python
sanitize_html(r'\[a<b\]')                       # -> '\[a'                 tail destroyed
sanitize_cell(r'\[a<b\]')                       # -> '\[a&lt;b\]'          correct
sanitize_html(r'\[\begin{align*} a&=b\\ c<d \end{align*}\]')
                                                # -> '\[\begin{align*} a&amp;=b\ c'
```

nh3 reads `<b\]` as a `<b>` tag with garbage attributes, drops it, and takes everything after it. In
a maths course (`x<5`, `a<b`, `\left<`) this is on the main path. It is **destructive at save time**:
the tail is gone from the database, and no render-time fix can bring it back. This is the gap
recorded as a deferred follow-up when the table element shipped.

Note that Problems 1–3 are `<`-free — Problem 4 is a separate defect that this spec closes in the
same slice because it belongs to the same authoring story.

### Deliverables

Two independently-valuable parts, one PR, separable commits.

- **A1 — render-time reflow (non-destructive, retroactive).** A new client module rejoins split math
  spans and normalises delimiters before KaTeX runs. It changes no stored data, so roughly 20,000
  already-imported *matematyka* elements start rendering correctly on deploy with no migration.
- **A2 — save-time math protection (forward-only).** `sanitize_html` gains the math-span protection
  `sanitize_cell` already has, so `<` inside math stops being destroyed.

### Non-goals

- **No `$$…$$` support** and **no bare `\begin{align*}` without delimiters.** Both were measured to
  work (a `\begin{…}`/`\end{…}` delimiter pair *is* re-included in the source auto-render hands to
  KaTeX), and both were declined: the accepted prose syntaxes remain exactly `\(…\)` and `\[…\]`.
- **No repair of already-damaged content.** A body truncated by Problem 4 stays truncated. No
  management command, no scan, no backfill.
- **No data migration and no re-save of any element.** A1 is render-only by construction.
- **No change to which elements may nest in which** — that is slice B.
- **No new authoring UI.** No RTE "insert display math" button, no MathLive changes.
- **No server-side math rendering.** KaTeX stays client-side; without JS there is no math today and
  there is none after this.

## Architecture

### A1 — `courses/static/courses/js/math_reflow.js`

One new module installing two **pre-hooks** on the two globals every math path already funnels
through. This is the established technique in this repo, not an invention: `text_colour.js:537-565`
already wraps the identical pair as *post*-hooks and documents why the hook works
("math.js resolves that global at CALL time"). Ours run before the original, theirs after, so the two
compose in either installation order.

Why hooks rather than editing call sites: `renderMathInElement` is called from **10 modules** —
`math.js`, `question.js`, `quiz.js`, `filltable.js`, `switchgate.js`, `switchgrid.js`,
`choicegrid.js`, `dnd.js`, `editor.js`, `math_input.js` — several of which pass no delimiters at all.
One hook covers every one of them, plus any added later, plus JS-injected content (quiz feedback,
fill-table, switch-grid) that no server-side filter can ever see.

**Hook A — `window.renderMathInElement(root, options)`**: reflow `root`'s DOM, then call through.

**Hook B — `window.katex.render(expr, element, options)`**: strip one balanced surrounding `\[…\]` or
`\(…\)` from `expr`; if the stripped wrapper was `\[…\]`, force `displayMode: true`. Then call
through. This is Problem 3, and it also covers the Math editor's `[data-math-live]` preview.

Both wrappers are idempotent, guarded by their own marker property (`__libliReflowWrapped`), distinct
from `text_colour.js`'s `__libliColourWrapped`.

#### Load order

`math_reflow.js` is added to the **five** templates that load `contrib/auto-render.min.js`:

| template | loads `math.js` |
|---|---|
| `templates/courses/lesson_unit.html` | yes |
| `templates/courses/quiz_unit.html` | yes |
| `templates/courses/manage/editor/editor.html` | yes |
| `templates/courses/quiz_results.html` | no |
| `templates/courses/manage/review_submission.html` | no |

Placed **immediately after `auto-render.min.js` and before `text_colour.js`**, `defer` like its
neighbours. Deferred scripts execute in document order, so `window.katex` and
`window.renderMathInElement` both exist when the module runs.

#### The reflow rule

Deliberately narrow. The governing invariant is:

> **A math span that already lies entirely inside a single text node is never touched.**

That is precisely the set of spans that render correctly today, so existing content cannot regress —
the code path is not merely equivalent, it is not entered.

**Ignored subtrees.** The walk skips the same tags auto-render skips by default:
`script, noscript, style, textarea, pre, code, option`. `pre` and `code` are in `ALLOWED_TAGS`, so
this is reachable, and mutating a subtree that will never be typeset anyway is pure risk.

**Mergeable vs barrier.** Within one element's child list, a child node is *mergeable* if it is

- a text node, or
- a `<br>`, or
- a `<div>` or `<p>` whose descendants are exclusively text nodes and `<br>` elements.

Every other node is a **barrier**: `<td>`, `<th>`, `<li>`, `<h2>`, `<h3>`, `<h4>`, `<a>`, `<strong>`,
`<em>`, `<u>`, `<blockquote>`, a `tc-*` colour `<span>`, and any `<div>`/`<p>` with element content
beyond `<br>`. The mergeable set is exactly what a contenteditable emits for a line break in this
codebase and nothing else.

**Algorithm**, for each element in the walk, over its own child list:

1. Partition the children into maximal **runs** of consecutive mergeable nodes. Barriers terminate a
   run and are never crossed. Each run is processed independently.
2. Build the run's linear text: a text node contributes its data; a `<br>` contributes `"\n"`; a
   mergeable `<div>`/`<p>` contributes `"\n"` + its text (its own `<br>`s becoming `"\n"`) + `"\n"`.
3. Find spans with `/\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g` over that text.
4. A span **wholly inside one text-node segment** is skipped (the invariant above).
5. Any other span is rewritten. Let *covered* be the contiguous child nodes from the one holding the
   span's first character through the one holding its last. Those nodes — and only those; earlier and
   later siblings in the run are untouched — are replaced by up to three text nodes: the covered text
   preceding the span, the span itself, and the covered text following it, omitting empties.
   The span's own text carries real `\n` at each former boundary, which LaTeX ignores and which the
   `\\` row separators inside `align*` do not depend on.
6. Matches are processed left to right, re-deriving the run's segments after each rewrite. Runs are
   small; simplicity beats a single-pass rebuild here.
7. **Then** delimiter promotion: for every text node, a `\(…\)` span whose content matches
   `/^\s*\\begin\{(align|alignat|gather|equation|CD|split)\*?\}/` has its delimiters rewritten to
   `\[…\]`. Those are exactly the ten measured display-only environments.

Losing the `<div>` wrapper for prose adjacent to the span is intended and was verified visually: KaTeX
renders display math as a block, so lead-in and trailing prose each keep their own line anyway.

**Idempotence.** After one pass every rewritten span lives in a single text node, so a second pass
takes rule 4 and changes nothing. This matters because `renderMathInElement` is called repeatedly on
the same DOM (quiz feedback swaps, tab reveals, `libli:reveal` re-measures).

**Bounded failure.** An unclosed `\[`, or a span whose `\]` sits beyond a barrier, matches nothing and
is left exactly as-is. The module never throws into a caller: the whole reflow is wrapped so a
failure degrades to today's behaviour rather than blocking typesetting.

#### Hook B, precisely

Strip a wrapper only when it is unambiguously the outermost pair — that is, when the inner content
contains none of `\[`, `\]`, `\(`, `\)`. So `\[a\] + \[b\]` is left alone rather than mangled into
`a\] + \[b`.

```
/^\s*\\\[([\s\S]*)\\\]\s*$/   -> strip, force displayMode: true
/^\s*\\\(([\s\S]*)\\\)\s*$/   -> strip, leave displayMode as the caller passed it
```

### A2 — math protection in `sanitize_html`

`sanitize_cell` protects math by stashing each balanced `\(…\)` / `\[…\]` behind an alphanumeric
nonce placeholder, running nh3, then restoring each span through `_canon_math` (unescape once, escape
once — so the editor path, where `<` already arrives as `&lt;`, and the import path, where it arrives
literal, converge on one single-escaped value that is inert to the parser but decodes correctly for
KaTeX).

**A naive port of that code to `sanitize_html` is wrong, and this is the crux of A2.** `_MATH_SPAN` is
`\\\(.*?\\\)|\\\[.*?\\\]` with `DOTALL`. A cell never contains block tags (`CELL_TAGS` has no `div`),
but a *text body routinely does* — and it is exactly the split-span case from Problem 1. Measured:

```python
sanitize_cell(r'<div>\[\begin{align*}</div><div>a&=b\\</div><div>\end{align*}\]</div>')
# -> '\[\begin{align*}&lt;/div&gt;&lt;div&gt;a&amp;=b\&lt;/div&gt;&lt;div&gt;\end{align*}\]'
```

The intervening tags were swallowed **into** the math and escaped to literal text. Applied to text
bodies that would destroy the block structure the reflow depends on, and corrupt the LaTeX.

**Required behaviour.** The protection must be tag-aware: a math span may contain the recognised
structural tags `<br>`, `<br/>`, `<div>`, `</div>`, `<p>`, `</p>`, which stay tags; every other `<`
and `>` inside the span is literal math and must be escaped. Concretely, the span is protected in
**segments split at those recognised tags** — each non-tag run is stashed and restored through
`_canon_math`, and the tags are left in the stream for nh3 to see.

**Signature.** `sanitize_html(value, *, allowed_classes=None, protect_math=True)`.

**The `protect_math=False` escape hatch is load-bearing, not decoration.** `courses/recolour/replay.py:41`
builds `_legacy_html = partial(sanitize_html, allowed_classes=LEGACY_ALLOWED_CLASSES)` in order to
replay the sanitiser *as it behaved at import time* and reconstruct the lookup keys the loader
actually stored. That backfill has already been applied byte-exactly to the local mat-pp database and
the PROD cutover is still pending. Adding math protection changes `sanitize_html`'s output for every
math-bearing value, which would silently move those keys. `replay.py`'s legacy partials — and only
they — must pin `protect_math=False`, exactly as they already pin `allowed_classes`.

**Blast radius.** `sanitize_html` has these production callers, all of which gain the protection:
`models.py` TextElement / SpoilerElement / CalloutElement bodies (393, 412, 467), `success_message`
(779), question `stem` and `explanation` (1604-1605); `element_forms.py` fill-blank and gate stems
(257, 310, 411, 508, 814, 854) which compose as `sanitize_html -> strip_sentinel -> parse`;
`transfer/importer.py:768`; and the render-time `sanitize` filter at
`templatetags/courses_extras.py:117`. Widening is the point — math in a question stem has the same
defect — but the fill-blank composition means a test must pin that a sentinel token adjacent to a
math span still parses.

**Idempotence is mandatory**, because `sanitize_html` runs at save *and* again at render through the
filter. `_canon_math`'s unescape-once-escape-once is already idempotent; the segmenting must not
break that.

## Error handling

| Situation | Behaviour |
|---|---|
| Unclosed `\[` or `\(` in prose | No match; DOM untouched; renders as literal text, as today |
| Math span crossing a barrier (`<td>`, `<li>`, `<strong>`, colour span) | Not merged; unchanged |
| `renderMathInElement` absent (auto-render failed to load) | Hooks never install; every path is today's behaviour |
| Reflow throws | Caught; the original `renderMathInElement` still runs on the untouched DOM |
| `\[a\] + \[b\]` reaching `katex.render` | Not stripped (ambiguous); today's behaviour |
| Display-only environment inside `\(…\)` | Promoted to `\[…\]`; renders as display |
| A non-display-only environment inside `\(…\)` (`cases`, `matrix`, …) | Untouched; already works inline |
| `<` inside math, table cell | Already correct via `sanitize_cell`; unchanged |
| `<` inside math, text/callout/spoiler body | **Fixed by A2** going forward; already-truncated bodies stay truncated |
| Recolour backfill re-run | Unaffected — `replay.py` pins `protect_math=False` |

## Testing

Per this repo's convention, **falsification is the acceptance criterion**: each test must be shown to
go **red** when its guard is removed. A test that passes both with and against the change proves
nothing.

**e2e (`-m e2e`, real Chromium)** — the load-bearing proof, since the defect is a DOM-shape defect no
Python-level test can observe.

1. **Golden path through the real UI.** Paste the three-line `align*` block into the RTE of a text
   element, save, open the lesson, assert exactly one `.katex` node with three aligned rows and no
   `.katex-error`. This one must drive the real gesture rather than injecting HTML — the stored
   shape produced by a real multi-line paste is precisely the unknown under test.
2. Same block in a **callout body** and in a **table cell**, from fixtures.
3. A **Math element** whose `latex` carries the `\[…\]` wrapper renders instead of erroring.
4. `\(\begin{align*}…\end{align*}\)` renders as display rather than showing a red error.
5. **Regression**: a single-line `\(x^2\)` and a single-line `\[…\]` render byte-identically before
   and after.
6. **Idempotence**: a surface that re-renders (quiz feedback swap, or a tab reveal) still shows one
   `.katex` node, not a doubled or re-escaped one.

**Static wiring guards (pytest)** — `math_reflow.js` is referenced in all five templates, and in each
one it precedes `text_colour.js`; both wrapper marker properties coexist.

**A2 unit tests (pytest)** — a table of vectors through `sanitize_html`, each asserted **twice** to
pin idempotence: `\[a<b\]`; the `align*` block containing `c<d`; a split-across-`<div>`s span
(structural tags survive as tags, non-tag runs escaped); a span containing `<strong>` (escaped as
literal, not kept as markup); content with no math at all (byte-identical to today); and a
fill-blank stem with a sentinel token adjacent to a math span.

**A2 replay guard** — `_legacy_html` output is byte-identical to the pre-change `sanitize_html` for a
math-bearing value. This is the test that protects the pending mat-pp PROD cutover.

**Baseline** — the full non-e2e suite is green on this worktree at **4559 passed, 1 skipped** before
any change, so any later failure is unambiguous.

## Risks

| Risk | Mitigation |
|---|---|
| Reflow disturbs content that renders correctly today | Rule 4 makes those spans an unentered code path; pinned by regression test 5 |
| Wrapper composition with `text_colour.js` breaks colour mapping | Distinct marker properties; a test asserts both survive; hooks sit on opposite sides of `original` |
| A2 changes the recolour backfill's replay keys | `protect_math=False` pinned in `replay.py`; byte-identity test |
| A2's tag-aware segmenting is subtly wrong and corrupts bodies at save | Tested as a vector table with double application; the naive port is documented above as a known-wrong implementation so it cannot be reintroduced |
| Merging across a table cell or list item | `<td>`/`<th>`/`<li>` are barriers by construction; asserted directly |
