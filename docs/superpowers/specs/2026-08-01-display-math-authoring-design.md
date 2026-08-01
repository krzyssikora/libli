# Display-math authoring: making multi-line `\[…\]` render

## Purpose

Pasting a multi-line display-math block into libli silently renders nothing. Everything below was
reproduced against this repo's vendored KaTeX 0.16.11 and measured on this worktree; the corpus
numbers come from a read-only scan of the live local `libli` database.

The reported symptom — a paste like

```latex
\begin{align*}
a^n\cdot a^k&=a^{n+k}\\
a^n: a^k&=a^{n-k}\\
\left(a^n\right)^k&=a^{nk}
\end{align*}
```

"is not accepted within `\(\)` or `\[\]`, i.e. it does not render".

> **Scope note.** An earlier draft of this spec also carried a fix for `<` inside math being
> destroyed by `sanitize_html` at save time. Review established that it is a security-sensitive
> change to the repo's primary sanitiser (it reintroduces a quote-injection XSS if ported naively)
> with **zero** measured benefit on the current corpus. It has been split into its own spec,
> `2026-08-01-sanitize-math-protection-design.md`, sequenced after the mat-pp links PROD cutover.
> **This spec changes no save path and no stored data whatsoever.**

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

### What the existing corpus actually looks like

A read-only scan of every `sanitize_html`-shaped rich-text field in the live local `libli` database
(the `courses/richtext.py` registry — 16 models / 27 fields), classifying each opening delimiter by
where its partner sits.

Counted in **values**:

| | |
|---|---|
| rich-text values scanned | 17,594 |
| values containing any LaTeX | 7,693 |

Counted in **spans**:

| | |
|---|---|
| intact (no tag between the delimiters — renders today) | **17,821** |
| mergeable (partner past a `<div>`/`<p>`/`<br>` boundary — this spec fixes these) | **6** |
| past a non-structural barrier (left alone) | **0** |
| unclosed | 1 |

**This measurement corrects the obvious assumption, and it changes how the work is justified.** The
imported *matematyka* content is essentially all intact: the LAL importer wrote math into single text
nodes, so the split-span defect is an **authoring-time** defect, not an import-time one. This spec
repairs six spans retroactively. Its real value is that multi-line display math becomes *authorable
at all* — the user's current blocker — not that it rescues a broken corpus.

### Non-goals

- **No new delimiters are registered.** The module reflows whatever delimiter set the calling code
  already registered — see "Delimiter set" for the one consequence of that, which is that `$$` and
  `\begin{align}` *already* work on three surfaces today and will therefore also reflow there. That
  is not new support; nothing this spec adds makes `$$` work anywhere it does not already.
- **No bare `\begin{align*}` support on the seven explicit-delimiter surfaces.** It was measured to
  render when the environment is explicitly registered as a delimiter pair, and was declined.
- **No save-path change and no stored-data change of any kind.** See the scope note above.
- **No repair of already-damaged content**, no migration, no management command.
- **No change to which elements may nest in which** — that is a separate slice.
- **No new authoring UI.** No RTE "insert display math" button, no MathLive changes.
- **No server-side math rendering.** KaTeX stays client-side.
- **No interaction with the pending mat-pp links PROD cutover.** Because nothing here runs at save,
  the two are independent and may land in either order.

## Architecture

### `courses/static/courses/js/math_reflow.js`

One new module installing two **pre-hooks** on the two globals every math path already funnels
through. This is the established technique in this repo, not an invention: `text_colour.js:553-579`
already wraps the identical pair as *post*-hooks and documents why the hook works
("math.js resolves that global at CALL time"). Ours run before the original, theirs after.

Why hooks rather than editing call sites: `renderMathInElement` is called from **10 modules** —
`math.js`, `question.js`, `quiz.js`, `filltable.js`, `switchgate.js`, `switchgrid.js`,
`choicegrid.js`, `dnd.js`, `editor.js`, `math_input.js`. One hook covers every one of them, plus any
added later, plus JS-injected content (quiz feedback, fill-table, switch-grid) that no server-side
filter could ever see.

**Public entry point.** The reflow is exported as `window.libliMathReflow(root, options)` — not
merely an internal of the wrapper. This is a testability requirement, not a convenience: the
algorithm below is the most intricate part of the change and needs DOM-in/DOM-out coverage that
end-to-end scenarios cannot localise.

**Hook A — `window.renderMathInElement(root, options)`**: call `window.libliMathReflow(root, options)`,
then call through.

**Hook B — `window.katex.render(expr, element, options)`**: strip one balanced surrounding `\[…\]` or
`\(…\)` from `expr`, then call through. This is Problem 3, and it also covers the Math editor's
`[data-math-live]` preview.

**Installation is once, unconditional, with no retry.** `text_colour.js:587-595` re-runs its installs
on `DOMContentLoaded` when either global was missing. `math_reflow.js` must **not** copy that: marker
properties do not propagate through another module's wrapper, so a retry would wrap an
already-wrapped chain and reflow twice per call. A single install is safe because the module loads
after `katex.min.js` and `auto-render.min.js` in document order (below), so both globals exist. If
either global is absent the module installs nothing and every path keeps today's behaviour.

#### Load order

`math_reflow.js` is added to the **five** templates that load `contrib/auto-render.min.js`:

| template | what typesets there | loads `math.js` |
|---|---|---|
| `templates/courses/lesson_unit.html` | `math.js` + element modules | yes |
| `templates/courses/quiz_unit.html` | `math.js`, `quiz.js` | yes |
| `templates/courses/manage/editor/editor.html` | `math.js`, `editor.js` | yes |
| `templates/courses/quiz_results.html` | **`question.js`** (explicit `\(`/`\[`) | no |
| `templates/courses/manage/review_submission.html` | **`question.js`** (explicit `\(`/`\[`) | no |

The last two load no `math.js`; `question.js` is what typesets there, so the module is active — not
merely installed for uniformity.

Placed **immediately after `auto-render.min.js` and before `text_colour.js`**, `defer` like its
neighbours. Deferred scripts execute in document order. Because `text_colour.js` installs second, it
owns the outer function and its retry logic remains correct.

The required order is `katex.min.js` < `auto-render.min.js` < `math_reflow.js` < `text_colour.js`,
and additionally `math_reflow.js` < `math.js` wherever `math.js` is loaded — `math.js` runs
`renderMath(document)` and `renderInlineText(document)` at evaluation time, so if it ever preceded
the module the entire first paint would bypass both hooks with no error. All four relations are
asserted by the wiring test, not left to transitivity.

#### Delimiter set

The scan set is **derived from `options.delimiters`** when the caller supplied one, falling back to
auto-render's own defaults when it did not. Hardcoding `\(`/`\[` would silently skip the three
callers that pass no delimiters at all — `filltable.js:73,86`, `switchgate.js:93`,
`switchgrid.js:102,111` — a per-surface inconsistency invisible from any one page. The other seven
callers all pass exactly `\(`/`\[`.

Consequence, stated plainly rather than left as a surprise: on those three surfaces auto-render's
defaults are in force, which include `$$…$$`, `\begin{equation}`, `\begin{align}`, `\begin{alignat}`,
`\begin{gather}` and `\begin{CD}`. Split spans in those forms will therefore reflow there and not on
the other seven surfaces. This is pre-existing asymmetry in what those surfaces accept; the module
inherits it rather than creating it, and deliberately does not paper over it.

#### Backslash parity

A candidate delimiter only opens a span when the run of backslashes **immediately preceding its first
character** has even length. Without this, the row-spacing idiom inside the very construct this spec
exists to fix — `\[\begin{align*} a&=b \\[2ex] c&=d \end{align*}\]` — is misread: `\\[2ex]` contains
the two characters `\[`, so a naive scan opens a second span there.

Stated generally so it applies to every delimiter in the derived set, not only `\[`: for a delimiter
whose own first character is a backslash, that character is **not** counted as part of the preceding
run. For `$$`, which begins with no backslash, the rule reduces to "not preceded by an odd number of
backslashes". This rule governs both the reflow scan and Hook B's guard.

#### The walk, and what stops it

Two distinct concepts, and their interaction is the thing most likely to be got wrong:

- **Ignored subtrees stop the walk.** The walk does not descend into them at all.
- **Barriers do not stop the walk.** A barrier terminates the *run* it sits in — it is never merged
  across — but the walk still descends into it and processes its own child list. This is required:
  a `<td class="ta-center">` is a barrier for its parent `<tr>`'s run, yet a span split across two
  `<div>`s *inside* that cell must still merge. Reading "barrier" as "do not enter" would silently
  skip every table cell, list item and aligned block.

**Ignored subtrees** are anything matching:

- auto-render's own default ignore list — `script, noscript, style, textarea, pre, code, option`
  (`pre` and `code` are in `ALLOWED_TAGS`, so this is reachable);
- **`[contenteditable]`** — `text_toolbar.js:196-197` mounts a `contenteditable` `.rte-surface` in
  `editor.html`, and `sync()` writes that surface's `innerHTML` back into the POSTed textarea. A DOM
  mutation inside the RTE is therefore a **data** mutation, and would break the render-only
  guarantee. This exclusion is load-bearing, not hygiene. Its user-visible consequence is deliberate
  and must be documented for testers: **display math is not typeset live inside the editing surface**
  — the round trip is paste → save → view;
- **`.katex`, `math`, `annotation`** — after the first pass KaTeX's own output holds the original TeX
  in a MathML `<annotation encoding="application/x-tex">`. Re-entering it would let the promotion
  phase rewrite the string screen readers and copy-paste consumers receive, and it is wasted
  traversal over the largest subtrees on the page.

**Mergeable vs barrier.** Within one element's child list, a child node is *mergeable* if it is

- a text node, or
- a `<br>` **carrying no attributes**, or
- a `<div>` or `<p>` **carrying no attributes** whose descendants are exclusively text nodes and
  attribute-free `<br>` elements.

Every other node is a **barrier**. The attribute condition is load-bearing: `ALIGN_CLASS_TAGS` puts
`ta-left`/`ta-center`/`ta-right` on `div`, `p`, `h2`–`h4`, `blockquote`, `li`, and `text_toolbar.js`
emits them. Merging a `<div class="ta-center">` into a bare text node would silently discard the
author's centring.

#### Phase 1 — merge

For each element reached by the walk, over its own child list:

1. Partition the children into maximal **runs** of consecutive mergeable nodes. Barriers terminate a
   run. Each run is processed independently.
2. Build the run's linear text: a text node contributes its data; a `<br>` contributes `"\n"`; a
   mergeable `<div>`/`<p>` contributes `"\n"` + its text (its own `<br>`s becoming `"\n"`) + `"\n"`.
3. Find spans over that text using the derived delimiter set and the parity rule.
4. A span **wholly inside one text-node segment** is skipped.
5. Any other span is rewritten. Let *covered* be the contiguous child nodes from the one holding the
   span's first character through the one holding its last. Those nodes — and only those; earlier and
   later siblings in the run are untouched — are replaced by up to three text nodes: the covered text
   preceding the span, the span itself, and the covered text following it, omitting empties.
6. Matches are processed left to right, re-deriving the run's segments after each rewrite. Runs are
   small; simplicity beats a single-pass rebuild here.

> **Merge-phase invariant.** A math span that already lies entirely inside a single text node is
> never merged. That is exactly the 17,821 spans measured to render correctly today, so phase 1
> cannot regress them — the code path is not merely equivalent, it is not entered.

#### Phase 2 — delimiter promotion

**Phase 2 runs only after phase 1 has completed for the entire subtree.** The ordering is not
cosmetic: promote-then-merge would leave a `\(\begin{align*}…\end{align*}\)` that the RTE split
across `<div>`s unpromoted, because it is not yet inside any single text node — and that split case
is precisely the reported symptom. Merge first, then promote.

For every text node reached by the walk, a `\(…\)` span whose content begins with one of the ten
display-only environments has its delimiters rewritten to `\[…\]`. The environment set is enumerated
literally —

```
align  align*  alignat  alignat*  gather  gather*  equation  equation*  CD  split
```

— rather than expressed as `(align|alignat|gather|equation|CD|split)\*?`, which would also admit the
non-existent `CD*` and `split*`.

**The merge-phase invariant does not cover phase 2**: promotion by design rewrites spans that sit
inside a single text node. It therefore carries its own regression coverage, and the "cannot regress"
argument must not be extended to it.

#### Newlines

The span's text carries a real `\n` at each former boundary. Two adjacent mergeable `<div>`s produce
a blank line, which in real LaTeX is a `\par` and an error inside `align*`; it is inert here only
because **KaTeX collapses** whitespace and has no paragraph handling. State it that way — an
implementer must not carry "LaTeX ignores it" anywhere else.

Losing the `<div>` wrapper for attribute-free prose adjacent to the span is intended and was verified
visually: KaTeX renders display math as a block, so lead-in and trailing prose each keep their own
line anyway.

#### Idempotence, failure, cost

**Idempotence.** After one pass every rewritten span lives in a single text node, so a second pass
takes rule 4 and changes nothing; phase 2 is idempotent because a promoted span no longer uses `\(`.
This matters because `renderMathInElement` is called repeatedly on the same DOM (quiz feedback swaps,
tab reveals, `libli:reveal` re-measures).

**Bounded failure.** An unclosed opening delimiter, or a span whose partner sits beyond a barrier,
matches nothing and is left exactly as-is. The whole reflow is wrapped so a failure degrades to
today's behaviour rather than blocking typesetting.

**Cost.** The walk is O(nodes under `root`). `math.js:31` calls `renderMathInElement` once per
matched element across nine selectors, and the roots are per-element, so the total added traversal is
bounded by one pass over the page's element subtrees — the same order as the work auto-render already
does. No budget beyond that is claimed, and none is needed; if a regression appears it will be on the
largest imported unit, which is where the e2e suite already runs.

#### Hook B, precisely

Two conditions, both required — the guard is part of the logic, not prose commentary alongside it:

1. the expression matches `/^\s*\\\[([\s\S]*)\\\]\s*$/` or `/^\s*\\\(([\s\S]*)\\\)\s*$/`; **and**
2. the captured group contains none of `\[`, `\]`, `\(`, `\)` **counted with the parity rule**, so a
   legitimate `\\[2ex]` inside the body does not veto stripping.

`[\s\S]*` is greedy, so condition 1 alone would match `\[a\] + \[b\]` with the group `a\] + \[b` and
strip exactly the case that must be left alone. Condition 2 is what prevents it.

On a match, strip the wrapper. **`displayMode` is left exactly as the caller passed it, for both
wrapper forms.** Both real callers reach `katex.render` through `math.js:6`, which hardcodes
`displayMode: true`, so a Math element containing `\(x\)` renders as display — which is correct, a
Math element is a display element by design, and its inline-looking wrapper is an author's habit, not
an instruction. The hook **constructs a shallow copy** of `options` (creating one when `options` is
`undefined`) and never mutates the caller's object; `text_colour.js` wraps the same function and
shares the argument list.

## Error handling

| Situation | Behaviour |
|---|---|
| Unclosed `\[` or `\(` in prose | No match; DOM untouched; renders as literal text, as today |
| Span crossing a barrier (`<td>`, `<li>`, `<strong>`, colour span, `<div class=…>`) | Not merged; unchanged |
| Span split across `<div>`s *inside* a barrier (`<td>`, `<li>`) | Merged — the walk descends into barriers |
| `\\[2ex]` row spacing inside a display block | Parity rule: not an opening delimiter; span reflows and Hook B still strips |
| `$$…$$` split span on fill-table / switch-gate / switch-grid | Reflowed, because the caller's own delimiter set registers it |
| `$$…$$` on the other seven surfaces | Not a delimiter there; untouched, as today |
| `renderMathInElement` or `katex` absent | Hooks never install; every path is today's behaviour |
| Reflow throws | Caught; the original `renderMathInElement` still runs on the untouched DOM |
| `\[a\] + \[b\]` reaching `katex.render` | Condition 2 fails; not stripped; today's behaviour |
| `\(x\)` in a Math element | Wrapper stripped; `displayMode` stays as the caller passed (`true`) |
| `options` undefined at Hook B | A fresh object is constructed; caller's argument never mutated |
| Display-only environment inside `\(…\)` | Promoted to `\[…\]`; renders as display |
| Non-display-only environment inside `\(…\)` (`cases`, `matrix`, …) | Untouched; already works inline |
| Math typed inside the RTE surface | Deliberately not typeset live; renders after save |

## Testing

Per this repo's convention, **falsification is the acceptance criterion**: each test must be shown to
go **red** when its guard is removed.

**Baseline** — the full non-e2e suite is green on this worktree at **4559 passed, 1 skipped**,
measured at branch point `0a9c2882` before any change.

### `tests/test_e2e_math_reflow.py` (e2e-marked, real Chromium)

1. **Golden path through the real UI.** Paste the three-line `align*` block into the RTE of a text
   element, **save**, open the lesson, assert exactly one `.katex` node with three aligned rows and
   no `.katex-error`. This one must drive the real gesture — the stored shape a real multi-line paste
   produces is precisely the unknown under test.
2. The same block in a **callout body** and in a **table cell**, from fixtures.
3. A **Math element** whose `latex` carries the `\[…\]` wrapper renders instead of erroring; and one
   carrying `\(x\)` renders as display.
4. `\(\begin{align*}…\end{align*}\)` renders as display — **phase 2's own regression coverage**,
   which the merge-phase invariant does not provide.
5. `\[a\] + \[b\]` in a Math element is left alone (Hook B condition 2).
6. A display block containing `\\[2ex]` reflows and strips correctly (parity rule).
7. **Regression**: single-line `\(x^2\)` and single-line `\[…\]` render identically before and after.
8. **Idempotence**: a re-rendering surface (quiz feedback swap or tab reveal) still shows one
   `.katex` node.

### `tests/test_math_reflow_unit.py` (e2e-marked; DOM table driven from a Playwright page)

Direct DOM-in/DOM-out cases against `window.libliMathReflow`, because the algorithm cannot be
localised through end-to-end scenarios:

- two spans in one run, and siblings outside the covered range left untouched (rule 5);
- a `<div>` with element content beyond `<br>` acts as a barrier;
- a `<div class="ta-center">` acts as a barrier and keeps its class;
- **a span split across two `<div>`s inside a `<td class="ta-center">` merges** — the barrier is
  descended into;
- a `\(…align*…\)` span split across two `<div>`s comes out **both merged and promoted** — pins the
  phase-1-before-phase-2 ordering;
- each ignored subtree: `pre`, `code`, `textarea`, `[contenteditable]`, `.katex`/`annotation`. The
  `[contenteditable]` case asserts the surface's `innerHTML` is **byte-identical** after the call;
- delimiter set derived from `options.delimiters`, including the no-delimiters caller shape, and a
  `$$` and a `\begin{align}` case under those defaults;
- idempotence: a second call is a no-op.

### `tests/test_math_reflow_wiring.py` (pytest, static)

`math_reflow.js` is referenced in all five templates, and in each the full ordering holds:
`katex.min.js` < `auto-render.min.js` < `math_reflow.js` < `text_colour.js`, plus
`math_reflow.js` < `math.js` in the three templates that load it.

It also asserts the module registers no `DOMContentLoaded` retry. **That assertion must strip
comments before matching**, because the Installation section requires the module to carry a comment
explaining why it does not copy `text_colour.js`'s retry — a raw-source regex would match the
explanation and fail. (This repo has already been bitten by exactly that: `test_element_state_write_routes.py`
regexes raw source including comments.) Assert on the call form `addEventListener("DOMContentLoaded"`
in comment-stripped source.

## Risks

| Risk | Mitigation |
|---|---|
| Phase 1 disturbs the 17,821 spans that render today | Rule 4 makes them an unentered path; pinned by e2e 7 |
| Phase 2 rewrites existing single-node content | Acknowledged as deliberate; own coverage at e2e 4 |
| Barrier read as "do not enter", skipping cells and list items | Stated explicitly; pinned by the `<td class="ta-center">` unit case |
| Phase ordering inverted, leaving split `\(align*\)` unpromoted | Pinned by the split-and-promoted unit case |
| Reflow mutates the RTE surface and is persisted | `[contenteditable]` ignored; byte-identity assertion |
| Double-wrapping with `text_colour.js` | Single unconditional install, no retry; wiring guard |
| Load order silently reordered, bypassing hooks on first paint | All four ordering relations asserted, not left to transitivity |
